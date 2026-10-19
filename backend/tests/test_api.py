"""Phase 6 API contract, validation, and real-artifact integration tests."""

from __future__ import annotations

import csv
import io
import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ids_ml.modeling.artifact import InferenceBundle

from backend.app.config import Settings
from backend.app.inference import InferenceService
from backend.app.main import create_app

ROOT = Path(__file__).resolve().parents[2]
ARTIFACT = ROOT / "models/ids-rf-v1"
CONTRACTS = ROOT / "contracts/api-v1"
ORIGINS = ("http://localhost:5173", "http://localhost:8080")


class _BinaryModel:
    def predict_proba(self, features: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
        malicious = np.where(features[:, 0] > 0.0, 0.95, 0.01)
        return np.column_stack((1.0 - malicious, malicious))


class _FamilyModel:
    classes_ = np.arange(7)

    def predict_proba(self, features: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
        probabilities = np.full((features.shape[0], 7), 0.1 / 6.0)
        probabilities[:, 0] = 0.9
        return probabilities


def _test_service() -> InferenceService:
    contract = json.loads((ROOT / "contracts/features-v1.json").read_text())
    features = tuple(str(value) for value in contract["required_features"])
    attack_labels = (
        "DOS_DDOS",
        "PORT_SCAN",
        "BRUTE_FORCE",
        "WEB_ATTACK",
        "BOTNET",
        "INFILTRATION",
        "RARE_OTHER",
    )
    bundle = InferenceBundle(
        artifact_schema_version="1.0.0",
        model_version="ids-rf-v1.0.0",
        feature_schema_version="features-v1",
        feature_schema_hash=str(contract["feature_schema_sha256"]),
        required_features=features,
        imputation_values=(0.0,) * len(features),
        attack_labels=attack_labels,
        malicious_threshold=0.015,
        low_confidence_threshold=0.65,
        high_risk_threshold=0.85,
        binary_model=_BinaryModel(),
        attack_family_model=_FamilyModel(),
    )
    metadata = {
        "model_name": "cicids2017-two-stage-random-forest",
        "model_version": bundle.model_version,
        "artifact_schema_version": bundle.artifact_schema_version,
        "training_dataset": "CIC-IDS2017",
        "feature_schema_version": bundle.feature_schema_version,
        "feature_schema_hash": bundle.feature_schema_hash,
        "required_features": list(features),
        "attack_categories": ["BENIGN", *attack_labels],
        "thresholds": {
            "malicious": bundle.malicious_threshold,
            "low_confidence": bundle.low_confidence_threshold,
            "high_risk": bundle.high_risk_threshold,
        },
        "created_at": "2026-10-19T00:00:00Z",
    }
    return InferenceService(bundle, metadata)


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "artifact_dir": ARTIFACT,
        "cors_origins": ORIGINS,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    application = create_app(_settings(), service_factory=lambda _path: _test_service())
    with TestClient(application, raise_server_exceptions=False) as test_client:
        yield test_client
    assert application.state.model_service is None


@pytest.fixture(scope="module")
def real_client() -> Iterator[TestClient]:
    if not (ARTIFACT / "manifest.json").is_file():
        pytest.skip("the ignored Phase 5 artifact is not available in this checkout")
    application = create_app(_settings())
    with TestClient(application, raise_server_exceptions=False) as test_client:
        yield test_client
    assert application.state.model_service is None


def _template_rows(client: TestClient) -> tuple[list[str], list[str]]:
    response = client.get("/api/v1/input-template")
    assert response.status_code == 200
    rows = list(csv.reader(io.StringIO(response.text)))
    assert len(rows) == 2
    return rows[0], rows[1]


def _template_features(client: TestClient) -> dict[str, float]:
    header, values = _template_rows(client)
    return {name: float(value) for name, value in zip(header[1:], values[1:], strict=True)}


def _csv_bytes(rows: list[list[str]]) -> bytes:
    stream = io.StringIO(newline="")
    csv.writer(stream, lineterminator="\n").writerows(rows)
    return stream.getvalue().encode("utf-8")


def _upload(client: TestClient, payload: bytes, media_type: str = "text/csv") -> Any:
    return client.post(
        "/api/v1/predictions/file",
        files={"file": ("flows.csv", payload, media_type)},
    )


def _error_code(response: Any) -> str:
    payload = response.json()
    assert set(payload) == {"error"}
    error = payload["error"]
    assert set(error) == {"code", "message", "details", "request_id"}
    assert error["request_id"] == response.headers["x-request-id"]
    assert "traceback" not in response.text.casefold()
    return str(error["code"])


def test_liveness_readiness_metadata_and_template(client: TestClient) -> None:
    health = client.get("/health")
    ready = client.get("/ready")
    model = client.get("/api/v1/model")
    template = client.get("/api/v1/input-template")

    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert ready.status_code == 200
    assert ready.json() == {"status": "ready", "model_version": "ids-rf-v1.0.0"}
    assert model.status_code == 200
    assert model.json()["artifact_status"] == "READY"
    assert len(model.json()["required_features"]) == 63
    assert model.json()["thresholds"] == {
        "malicious": 0.015,
        "low_confidence": 0.65,
        "high_risk": 0.85,
    }
    assert template.status_code == 200
    assert template.headers["content-type"].startswith("text/csv")
    assert template.headers["x-model-version"] == "ids-rf-v1.0.0"
    assert len(_template_rows(client)[0]) == 64


def test_json_and_csv_have_equivalent_real_artifact_predictions(
    real_client: TestClient,
) -> None:
    header, values = _template_rows(real_client)
    features = _template_features(real_client)
    json_response = real_client.post(
        "/api/v1/predictions",
        json={"records": [{"row_id": "same-row", "features": features}]},
    )
    csv_response = _upload(real_client, _csv_bytes([header, ["same-row", *values[1:]]]))

    assert json_response.status_code == csv_response.status_code == 200
    json_body = json_response.json()
    csv_body = csv_response.json()
    assert json_body["request_id"] == json_response.headers["x-request-id"]
    assert csv_body["request_id"] == csv_response.headers["x-request-id"]
    assert json_body["predictions"] == csv_body["predictions"]
    assert json_body["summary"] == csv_body["summary"]
    assert json_body["model"] == csv_body["model"]


def test_response_shapes_match_the_committed_contract_examples(client: TestClient) -> None:
    expected_model = json.loads((CONTRACTS / "model-response.example.json").read_text())
    expected_prediction = json.loads((CONTRACTS / "prediction-response.example.json").read_text())
    model = client.get("/api/v1/model").json()
    prediction = client.post(
        "/api/v1/predictions",
        json={"records": [{"features": _template_features(client)}]},
    ).json()

    assert set(model) == set(expected_model)
    assert set(model["thresholds"]) == set(expected_model["thresholds"])
    assert set(prediction) == set(expected_prediction)
    assert set(prediction["model"]) == set(expected_prediction["model"])
    assert set(prediction["summary"]) == set(expected_prediction["summary"])
    assert set(prediction["predictions"][0]) == set(expected_prediction["predictions"][0])


def test_openapi_uses_the_loaded_schema_and_real_example(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    assert set(schema["paths"]) >= {
        "/health",
        "/ready",
        "/api/v1/model",
        "/api/v1/input-template",
        "/api/v1/predictions",
        "/api/v1/predictions/file",
    }
    example = schema["paths"]["/api/v1/predictions"]["post"]["requestBody"]["content"][
        "application/json"
    ]["example"]
    assert len(example["records"][0]["features"]) == 63
    assert (
        schema["paths"]["/api/v1/model"]["get"]["responses"]["200"]["content"]["application/json"][
            "example"
        ]["model_version"]
        == "ids-rf-v1.0.0"
    )


@pytest.mark.parametrize(
    ("payload", "media_type", "status_code", "code"),
    [
        (b"", "text/csv", 400, "EMPTY_INPUT"),
        (b"not a csv", "text/plain", 415, "UNSUPPORTED_MEDIA_TYPE"),
        (b"\xff\xfe\x00", "text/csv", 415, "UNSUPPORTED_ENCODING"),
    ],
)
def test_file_level_rejections_are_stable(
    client: TestClient,
    payload: bytes,
    media_type: str,
    status_code: int,
    code: str,
) -> None:
    response = _upload(client, payload, media_type)
    assert response.status_code == status_code
    assert _error_code(response) == code


def test_malformed_multipart_uses_the_safe_error_envelope(client: TestClient) -> None:
    response = client.post(
        "/api/v1/predictions/file",
        content=b"not-a-valid-multipart-body",
        headers={"Content-Type": "multipart/form-data; boundary=missing-boundary"},
    )
    assert response.status_code == 400
    assert _error_code(response) == "INVALID_REQUEST"


def test_csv_rejects_duplicate_missing_and_excess_headers(client: TestClient) -> None:
    header, values = _template_rows(client)
    duplicate = _upload(client, _csv_bytes([[*header, header[1]], [*values, values[1]]]))
    missing = _upload(client, _csv_bytes([header[:-1], values[:-1]]))
    excessive_header = [f"column-{index}" for index in range(121)]
    excessive = _upload(client, _csv_bytes([excessive_header, ["0"] * 121]))

    assert duplicate.status_code == 400
    assert _error_code(duplicate) == "DUPLICATE_COLUMNS"
    assert missing.status_code == 422
    assert _error_code(missing) == "MISSING_REQUIRED_COLUMNS"
    assert excessive.status_code == 413
    assert _error_code(excessive) == "TOO_MANY_COLUMNS"


def test_csv_reports_bad_rows_and_ignores_extra_columns(client: TestClient) -> None:
    header, values = _template_rows(client)
    valid = ["valid", *values[1:], "kept private"]
    invalid_text = ["bad-text", *values[1:], "kept private"]
    invalid_text[2] = "private-invalid-token"
    invalid_infinity = ["bad-inf", *values[1:], "kept private"]
    invalid_infinity[3] = "inf"
    response = _upload(
        client,
        _csv_bytes([[*header, "analyst_note"], valid, invalid_text, invalid_infinity]),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "PARTIAL_SUCCESS"
    assert body["summary"]["total_rows"] == 3
    assert body["summary"]["valid_rows"] == 1
    assert body["summary"]["invalid_rows"] == 2
    assert [error["row_id"] for error in body["row_errors"]] == ["bad-text", "bad-inf"]
    assert all(error["code"] == "INVALID_FEATURE_VALUE" for error in body["row_errors"])
    assert body["warnings"] == ["Ignored extra columns: analyst_note."]
    assert "private-invalid-token" not in response.text
    assert "kept private" not in response.text


def test_json_validation_is_strict_but_allows_partial_success(client: TestClient) -> None:
    valid = _template_features(client)
    invalid = dict(valid)
    invalid["flow_duration"] = True
    missing = dict(valid)
    del missing["flow_duration"]
    response = client.post(
        "/api/v1/predictions",
        json={
            "records": [
                {"row_id": "valid", "features": valid},
                {"row_id": "invalid", "features": invalid},
                {"row_id": "missing", "features": missing},
            ]
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "PARTIAL_SUCCESS"
    assert body["summary"]["total_rows"] == 3
    assert body["summary"]["valid_rows"] == 1
    assert body["summary"]["invalid_rows"] == 2
    assert [error["code"] for error in body["row_errors"]] == [
        "INVALID_FEATURE_VALUE",
        "MISSING_REQUIRED_COLUMNS",
    ]


def test_empty_all_invalid_and_duplicate_id_json_fail_safely(client: TestClient) -> None:
    features = _template_features(client)
    invalid: dict[str, object] = dict(features)
    invalid["flow_duration"] = "secret-invalid-value"
    empty = client.post("/api/v1/predictions", json={"records": []})
    unusable = client.post("/api/v1/predictions", json={"records": [{"features": invalid}]})
    duplicate = client.post(
        "/api/v1/predictions",
        json={
            "records": [
                {"row_id": "duplicate", "features": features},
                {"row_id": "duplicate", "features": features},
            ]
        },
    )

    assert empty.status_code == 400
    assert _error_code(empty) == "EMPTY_INPUT"
    assert unusable.status_code == 422
    assert _error_code(unusable) == "NO_VALID_ROWS"
    assert "secret-invalid-value" not in unusable.text
    assert duplicate.status_code == 422
    assert _error_code(duplicate) == "DUPLICATE_ROW_ID"


def test_configured_row_and_byte_limits_are_enforced(client: TestClient) -> None:
    header, values = _template_rows(client)
    csv_app = create_app(
        _settings(csv_max_rows=2, max_upload_bytes=128),
        service_factory=lambda _path: _test_service(),
    )
    with TestClient(csv_app, raise_server_exceptions=False) as limited:
        too_many = _upload(
            limited,
            _csv_bytes([header, values, ["row-2", *values[1:]], ["row-3", *values[1:]]]),
        )
        too_large = _upload(limited, b"x" * 129)
    json_app = create_app(_settings(json_max_rows=2), service_factory=lambda _path: _test_service())
    with TestClient(json_app, raise_server_exceptions=False) as limited:
        features = _template_features(client)
        too_many_json = limited.post(
            "/api/v1/predictions",
            json={"records": [{"features": features}] * 3},
        )

    assert too_many.status_code == 413
    assert _error_code(too_many) == "FILE_TOO_LARGE"
    assert too_large.status_code == 413
    assert _error_code(too_large) == "FILE_TOO_LARGE"
    assert too_many_json.status_code == 413
    assert _error_code(too_many_json) == "TOO_MANY_ROWS"


def test_csv_row_limit_is_distinct_from_file_limit(client: TestClient) -> None:
    header, values = _template_rows(client)
    application = create_app(
        _settings(csv_max_rows=2), service_factory=lambda _path: _test_service()
    )
    with TestClient(application, raise_server_exceptions=False) as limited:
        response = _upload(
            limited,
            _csv_bytes([header, values, ["row-2", *values[1:]], ["row-3", *values[1:]]]),
        )
    assert response.status_code == 413
    assert _error_code(response) == "TOO_MANY_ROWS"


def test_unavailable_model_preserves_liveness_and_blocks_inference(tmp_path: Path) -> None:
    application = create_app(_settings(artifact_dir=tmp_path / "missing"))
    with TestClient(application, raise_server_exceptions=False) as unavailable:
        health = unavailable.get("/health")
        ready = unavailable.get("/ready")
        model = unavailable.get("/api/v1/model")
        prediction = unavailable.post("/api/v1/predictions", json={"records": []})

    assert health.status_code == 200
    assert ready.status_code == 503
    assert ready.json() == {"status": "not_ready", "reason": "model_not_loaded"}
    assert model.status_code == 503
    assert _error_code(model) == "MODEL_UNAVAILABLE"
    assert prediction.status_code == 503
    assert _error_code(prediction) == "MODEL_UNAVAILABLE"


def test_inference_failure_returns_no_traceback(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("private-internal-detail")

    service = cast(FastAPI, client.app).state.model_service
    monkeypatch.setattr(service.bundle, "predict_probabilities", fail)
    response = client.post(
        "/api/v1/predictions",
        json={"records": [{"features": _template_features(client)}]},
    )
    assert response.status_code == 500
    assert _error_code(response) == "INFERENCE_FAILED"
    assert "private-internal-detail" not in response.text


def test_access_logs_are_structured_and_do_not_contain_rows(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="ids_api.access")
    marker = "private-row-marker-7391"
    response = client.post(
        "/api/v1/predictions",
        json={
            "records": [
                {
                    "row_id": marker,
                    "features": _template_features(client),
                }
            ]
        },
    )
    assert response.status_code == 200
    messages = [record.getMessage() for record in caplog.records if record.name == "ids_api.access"]
    event = json.loads(messages[-1])
    assert event["event"] == "request_complete"
    assert event["request_id"] == response.headers["x-request-id"]
    assert marker not in "\n".join(messages)
    assert "flow_duration" not in "\n".join(messages)


def test_cors_uses_the_configured_allowlist(client: TestClient) -> None:
    allowed = client.options(
        "/api/v1/model",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    denied = client.options(
        "/api/v1/model",
        headers={
            "Origin": "https://attacker.invalid",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert denied.status_code == 400
    assert "access-control-allow-origin" not in denied.headers
