"""Phase 9 hostile-input, privacy, and resource-boundary tests."""

from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import random
import subprocess
import sys
import tempfile
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import UploadFile
from starlette.types import Message, Receive, Scope, Send

from backend.app.config import Settings
from backend.app.errors import APIError
from backend.app.inference import InferenceService
from backend.app.main import RequestGuardMiddleware, create_app
from backend.tests.test_api import ARTIFACT, ORIGINS, ROOT, _test_service


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "artifact_dir": ARTIFACT,
        "cors_origins": ORIGINS,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


@pytest.fixture
def client() -> Iterator[TestClient]:
    application = create_app(_settings(), service_factory=lambda _path: _test_service())
    with TestClient(application, raise_server_exceptions=False) as test_client:
        yield test_client


def _template(client: TestClient) -> tuple[list[str], list[str]]:
    rows = list(csv.reader(io.StringIO(client.get("/api/v1/input-template").text)))
    return rows[0], rows[1]


def _csv_bytes(rows: list[list[str]]) -> bytes:
    stream = io.StringIO(newline="")
    csv.writer(stream, lineterminator="\n").writerows(rows)
    return stream.getvalue().encode("utf-8")


def _upload(
    client: TestClient,
    payload: bytes,
    *,
    filename: str = "flows.csv",
    media_type: str = "text/csv",
) -> Any:
    return client.post(
        "/api/v1/predictions/file",
        files={"file": (filename, payload, media_type)},
    )


def test_random_malformed_csv_never_crashes_or_echoes_content(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="ids_api.access")
    generator = random.Random(920_260)
    marker = "private-fuzz-marker-920260"

    for _ in range(64):
        size = generator.randint(0, 2_048)
        payload = marker.encode() + generator.randbytes(size)
        response = _upload(client, payload)
        assert response.status_code in {400, 413, 415, 422}
        assert response.status_code < 500
        assert marker not in response.text

    logs = "\n".join(record.getMessage() for record in caplog.records)
    assert marker not in logs
    assert "private-fuzz" not in logs


@pytest.mark.parametrize(
    "hostile_value",
    [
        "nan",
        "inf",
        "-inf",
        "1e999999",
        '=WEBSERVICE("https://invalid.example")',
        "+cmd|' /C calc'!A0",
        "@SUM(1+1)",
        "not-a-number-private-token",
    ],
)
def test_hostile_numeric_values_are_rejected_without_reflection(
    client: TestClient, hostile_value: str
) -> None:
    header, values = _template(client)
    row = ["hostile-row", *values[1:]]
    row[1] = hostile_value
    response = _upload(client, _csv_bytes([header, row]))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "NO_VALID_ROWS"
    assert hostile_value not in response.text


def test_path_filenames_and_model_or_archive_uploads_are_rejected(
    client: TestClient, tmp_path: Path
) -> None:
    header, values = _template(client)
    path_target = tmp_path / "escaped.csv"
    traversal = _upload(
        client,
        _csv_bytes([header, values]),
        filename=str(path_target),
    )
    model = _upload(client, b"not-a-model", filename="pipeline.joblib")
    archive_stream = io.BytesIO()
    with zipfile.ZipFile(archive_stream, "w") as archive:
        archive.writestr("flows.csv", "row_id,flow_duration\nprivate,1\n")
    archive = _upload(
        client,
        archive_stream.getvalue(),
        filename="flows.zip",
        media_type="application/zip",
    )

    assert traversal.status_code == 400
    assert traversal.json()["error"]["code"] == "INVALID_FILENAME"
    assert model.status_code == 415
    assert model.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"
    assert archive.status_code == 415
    assert archive.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"
    assert not path_target.exists()


def test_spooled_upload_is_closed_and_leaves_no_temporary_file(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    closed: list[str | None] = []
    original_close = UploadFile.close

    async def tracked_close(upload: UploadFile) -> None:
        closed.append(upload.filename)
        await original_close(upload)

    monkeypatch.setattr(UploadFile, "close", tracked_close)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    response = _upload(client, b"private-invalid-body," * 100_000)

    assert response.status_code in {400, 413, 422}
    assert closed and set(closed) == {"flows.csv"}
    assert list(tmp_path.iterdir()) == []


def test_processing_deadline_returns_a_stable_timeout(client: TestClient) -> None:
    header, values = _template(client)
    service = _test_service()
    with pytest.raises(APIError) as captured:
        service.validate_csv(
            _csv_bytes([header, values]),
            max_rows=10,
            max_columns=120,
            deadline=-1.0,
        )

    assert captured.value.status_code == 504
    assert captured.value.code == "PROCESSING_TIMEOUT"


def test_streamed_request_limit_applies_without_content_length() -> None:
    settings = _settings(max_upload_bytes=8)

    async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
        while True:
            message = await receive()
            if message["type"] == "http.request" and not message.get("more_body", False):
                break
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware = RequestGuardMiddleware(downstream, settings=settings)
    messages = iter(
        [
            {"type": "http.request", "body": b"a" * 200_000, "more_body": True},
            {"type": "http.request", "body": b"b" * 100_000, "more_body": False},
        ]
    )
    sent: list[Message] = []

    async def receive() -> Message:
        return next(messages)

    async def send(message: Message) -> None:
        sent.append(message)

    scope: Scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/v1/predictions",
        "raw_path": b"/api/v1/predictions",
        "query_string": b"",
        "root_path": "",
        "headers": [(b"content-type", b"application/json")],
        "client": ("127.0.0.1", 1234),
        "server": ("test", 80),
        "state": {},
    }
    asyncio.run(middleware(scope, receive, send))

    start = next(message for message in sent if message["type"] == "http.response.start")
    body = b"".join(
        message.get("body", b"") for message in sent if message["type"] == "http.response.body"
    )
    assert start["status"] == 413
    assert json.loads(body)["error"]["code"] == "FILE_TOO_LARGE"


def test_untrusted_artifact_directory_fails_before_deserialization(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact"
    artifact.mkdir()
    (artifact / "manifest.json").write_text(
        json.dumps(
            {
                "artifact_schema_version": "1.0.0",
                "model_version": "attacker-controlled",
                "files": {"payload.joblib": {"sha256": "0" * 64, "bytes": 1}},
            }
        ),
        encoding="utf-8",
    )
    (artifact / "payload.joblib").write_bytes(b"!")

    with pytest.raises(ValueError, match="exact required files"):
        InferenceService.load(artifact)


@pytest.mark.parametrize(
    "value",
    ["*", "file:///tmp", "https://example.com/path", "https://user@example.com"],
)
def test_cors_environment_rejects_non_origins(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("IDS_CORS_ORIGINS", value)
    with pytest.raises(ValueError, match="IDS_CORS_ORIGINS"):
        Settings.from_env()


def test_security_headers_and_server_generated_request_ids(client: TestClient) -> None:
    supplied = "attacker-selected-request-id"
    response = client.get("/health", headers={"X-Request-ID": supplied})

    assert response.status_code == 200
    assert response.headers["x-request-id"].startswith("req_")
    assert response.headers["x-request-id"] != supplied
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cache-control"] == "no-store"


def _run_vulnerability_policy(
    tmp_path: Path,
    finding: dict[str, str],
    exception: dict[str, object] | None,
) -> subprocess.CompletedProcess[str]:
    report = tmp_path / "report.json"
    policy = tmp_path / "exceptions.json"
    report.write_text(
        json.dumps({"Results": [{"Vulnerabilities": [finding]}]}),
        encoding="utf-8",
    )
    policy.write_text(
        json.dumps(
            {
                "schema_version": "security-exceptions-v1",
                "exceptions": [] if exception is None else [exception],
            }
        ),
        encoding="utf-8",
    )
    return subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/check_vulnerability_report.py"),
            "--report",
            str(report),
            "--exceptions",
            str(policy),
            "--image",
            "api",
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def test_unfixed_high_requires_a_complete_current_exception(tmp_path: Path) -> None:
    finding = {
        "VulnerabilityID": "CVE-2099-0001",
        "PkgName": "demo-package",
        "Severity": "HIGH",
        "FixedVersion": "",
    }
    exception: dict[str, object] = {
        "id": "CVE-2099-0001",
        "images": ["api"],
        "owner": "test owner",
        "expires_on": "2099-12-31",
        "rationale": "No fixed package exists in this test case.",
        "compensating_controls": "The vulnerable path is not invoked.",
    }

    result = _run_vulnerability_policy(tmp_path, finding, exception)

    assert result.returncode == 0
    assert "1 explicit unfixed advisory exceptions" in result.stdout


@pytest.mark.parametrize(
    ("severity", "fixed_version", "expires_on", "expected"),
    [
        ("CRITICAL", "", "2099-12-31", "critical findings cannot pass"),
        ("HIGH", "2.0", "2099-12-31", "fixed version 2.0 is available"),
        ("HIGH", "", "2020-01-01", "exception expired"),
    ],
)
def test_vulnerability_policy_rejects_unsafe_exceptions(
    tmp_path: Path,
    severity: str,
    fixed_version: str,
    expires_on: str,
    expected: str,
) -> None:
    finding = {
        "VulnerabilityID": "CVE-2099-0002",
        "PkgName": "demo-package",
        "Severity": severity,
        "FixedVersion": fixed_version,
    }
    exception: dict[str, object] = {
        "id": "CVE-2099-0002",
        "images": ["api"],
        "owner": "test owner",
        "expires_on": expires_on,
        "rationale": "Test-only exception.",
        "compensating_controls": "Test-only control.",
    }

    result = _run_vulnerability_policy(tmp_path, finding, exception)

    assert result.returncode == 1
    assert expected in result.stdout


def test_vulnerability_policy_rejects_an_unknown_high_finding(tmp_path: Path) -> None:
    result = _run_vulnerability_policy(
        tmp_path,
        {
            "VulnerabilityID": "CVE-2099-0003",
            "PkgName": "demo-package",
            "Severity": "HIGH",
            "FixedVersion": "",
        },
        None,
    )

    assert result.returncode == 1
    assert "no exception" in result.stdout
