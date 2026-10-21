#!/usr/bin/env python3
"""Benchmark the production Compose stack and enforce Phase 10 budgets."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import platform
import re
import statistics
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, cast

MIB = 1024 * 1024
EXPECTED_ARTIFACT_FILES = {
    "pipeline.joblib",
    "metadata.json",
    "feature-schema.json",
    "label-taxonomy.json",
    "metrics.json",
}
BUDGETS: dict[str, float | int] = {
    "startup_seconds": 30.0,
    "restart_seconds": 30.0,
    "single_row_p95_seconds": 2.0,
    "max_batch_p95_seconds": 10.0,
    "api_peak_memory_bytes": 512 * MIB,
    "frontend_asset_bytes": 1 * MIB,
    "max_batch_response_bytes": 16 * MIB,
    "api_image_bytes": 600 * MIB,
    "frontend_image_bytes": 100 * MIB,
}


class AssetParser(HTMLParser):
    """Collect the local stylesheets and scripts needed for the first page."""

    def __init__(self) -> None:
        super().__init__()
        self.paths: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "script" and values.get("src"):
            self.paths.add(str(values["src"]))
        if tag == "link" and values.get("rel") == "stylesheet" and values.get("href"):
            self.paths.add(str(values["href"]))


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--build-seconds", type=float, default=0.0)
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--max-rows", type=int, default=10_000)
    parser.add_argument("--concurrency", type=int, default=4)
    return parser.parse_args()


def _run(
    command: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )


def _compose(
    project_root: Path,
    environment: dict[str, str],
    *arguments: str,
) -> subprocess.CompletedProcess[str]:
    return _run(
        [
            "docker",
            "compose",
            "--project-directory",
            str(project_root),
            "--env-file",
            str(project_root / ".env.example"),
            *arguments,
        ],
        cwd=project_root,
        environment=environment,
    )


def _request(url: str, *, body: bytes | None = None, content_type: str | None = None) -> bytes:
    headers = {"Accept": "application/json"}
    if content_type is not None:
        headers["Content-Type"] = content_type
    request = urllib.request.Request(
        url, data=body, headers=headers, method="POST" if body else "GET"
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        return cast(bytes, response.read())


def _multipart(payload: bytes) -> tuple[bytes, str]:
    boundary = "ids-phase10-benchmark"
    prefix = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="benchmark.csv"\r\n'
        "Content-Type: text/csv\r\n\r\n"
    ).encode()
    body = prefix + payload + f"\r\n--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


def _post_csv(base_url: str, payload: bytes) -> tuple[dict[str, Any], int, float]:
    body, content_type = _multipart(payload)
    started = time.perf_counter()
    raw = _request(
        f"{base_url}/api/v1/predictions/file",
        body=body,
        content_type=content_type,
    )
    duration = time.perf_counter() - started
    parsed: object = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("prediction response must be a JSON object")
    return parsed, len(raw), duration


def _csv_payload(template: bytes, rows: int, *, prefix: str) -> tuple[bytes, list[str]]:
    parsed = list(csv.reader(io.StringIO(template.decode("utf-8"))))
    if len(parsed) != 2 or len(parsed[0]) != len(parsed[1]):
        raise ValueError("input template must contain one header and one sample row")
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(parsed[0])
    compact_values = [format(float(value), ".10g") for value in parsed[1][1:]]
    identifiers: list[str] = []
    for index in range(rows):
        identifier = f"{prefix}-{index:05d}"
        identifiers.append(identifier)
        writer.writerow([identifier, *compact_values])
    return output.getvalue().encode("utf-8"), identifiers


def _validate_prediction(response: dict[str, Any], expected_ids: list[str]) -> str:
    summary = response.get("summary")
    predictions = response.get("predictions")
    request_id = response.get("request_id")
    if not isinstance(summary, dict) or summary.get("valid_rows") != len(expected_ids):
        raise ValueError("prediction summary does not match the submitted rows")
    if not isinstance(predictions, list):
        raise ValueError("prediction response is missing predictions")
    actual_ids = [item.get("row_id") for item in predictions if isinstance(item, dict)]
    if actual_ids != expected_ids:
        raise ValueError("prediction row order or identity was contaminated")
    if not isinstance(request_id, str) or not request_id.startswith("req_"):
        raise ValueError("prediction response has an invalid request ID")
    return request_id


def _summary(samples: list[float]) -> dict[str, Any]:
    ordered = sorted(samples)
    rank = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return {
        "samples_seconds": [round(value, 6) for value in samples],
        "median_seconds": round(statistics.median(samples), 6),
        "p95_seconds": round(ordered[rank], 6),
    }


def _size_bytes(value: str) -> int:
    match = re.fullmatch(r"\s*([0-9.]+)\s*([KMGT]?i?B)\s*", value)
    if match is None:
        raise ValueError(f"unsupported Docker size: {value}")
    amount = float(match.group(1))
    factors = {
        "B": 1,
        "KB": 1000,
        "MB": 1000**2,
        "GB": 1000**3,
        "TB": 1000**4,
        "KiB": 1024,
        "MiB": 1024**2,
        "GiB": 1024**3,
        "TiB": 1024**4,
    }
    return round(amount * factors[match.group(2)])


def _container_id(project_root: Path, environment: dict[str, str], service: str) -> str:
    identifier = _compose(project_root, environment, "ps", "--quiet", service).stdout.strip()
    if not identifier:
        raise RuntimeError(f"Compose did not return a container for {service}")
    return identifier


def _container_memory(identifier: str, *, cwd: Path, environment: dict[str, str]) -> int:
    output = _run(
        ["docker", "stats", "--no-stream", "--format", "{{json .}}", identifier],
        cwd=cwd,
        environment=environment,
    ).stdout.strip()
    stats: object = json.loads(output)
    if not isinstance(stats, dict) or not isinstance(stats.get("MemUsage"), str):
        raise ValueError("Docker stats did not return memory usage")
    used, _separator, _limit = stats["MemUsage"].partition("/")
    return _size_bytes(used)


def _container_limits(identifier: str, *, cwd: Path, environment: dict[str, str]) -> dict[str, int]:
    output = _run(
        ["docker", "inspect", "--format", "{{json .HostConfig}}", identifier],
        cwd=cwd,
        environment=environment,
    ).stdout
    config: object = json.loads(output)
    if not isinstance(config, dict):
        raise ValueError("Docker inspect did not return host configuration")
    return {
        "memory_bytes": int(config.get("Memory", 0)),
        "nano_cpus": int(config.get("NanoCpus", 0)),
        "pids_limit": int(config.get("PidsLimit", 0)),
    }


def _image_metadata(cwd: Path, environment: dict[str, str]) -> dict[str, dict[str, Any]]:
    output = _run(
        ["docker", "image", "inspect", "ids-demo-api:local", "ids-demo-frontend:local"],
        cwd=cwd,
        environment=environment,
    ).stdout
    raw: object = json.loads(output)
    if not isinstance(raw, list) or len(raw) != 2:
        raise ValueError("Docker image inspection did not return both application images")
    result: dict[str, dict[str, Any]] = {}
    for name, item in zip(("api", "frontend"), raw, strict=True):
        if not isinstance(item, dict):
            raise ValueError("Docker image inspection returned an invalid entry")
        result[name] = {
            "id": item.get("Id"),
            "size_bytes": int(item.get("Size", 0)),
            "configured_user": (item.get("Config") or {}).get("User"),
        }
    return result


def _artifact_metadata(model_dir: Path) -> dict[str, Any]:
    manifest_path = model_dir / "manifest.json"
    raw: object = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("files"), dict):
        raise ValueError("model manifest is malformed")
    files = raw["files"]
    if set(files) != EXPECTED_ARTIFACT_FILES:
        raise ValueError("model manifest does not list the exact artifact files")
    for name in EXPECTED_ARTIFACT_FILES:
        item = files[name]
        path = model_dir / name
        if not isinstance(item, dict) or not path.is_file():
            raise ValueError(f"model artifact entry is invalid: {name}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if item.get("sha256") != digest or item.get("bytes") != path.stat().st_size:
            raise ValueError(f"model artifact integrity check failed: {name}")
    return {
        "model_version": raw.get("model_version"),
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "total_bytes": sum((model_dir / name).stat().st_size for name in files),
        "files": files,
    }


def _frontend_assets(base_url: str) -> dict[str, Any]:
    html = _request(f"{base_url}/")
    parser = AssetParser()
    parser.feed(html.decode("utf-8"))
    assets: dict[str, int] = {"/": len(html)}
    css_bodies: list[str] = []
    for path in sorted(parser.paths):
        body = _request(urllib.parse.urljoin(base_url, path))
        assets[path] = len(body)
        if path.endswith(".css"):
            css_bodies.append(body.decode("utf-8"))
    for css in css_bodies:
        for path in re.findall(r"url\([\"']?([^\"')]+)", css):
            if path.startswith("data:"):
                continue
            absolute_path = urllib.parse.urlparse(urllib.parse.urljoin(base_url, path)).path
            if absolute_path not in assets:
                assets[absolute_path] = len(_request(urllib.parse.urljoin(base_url, path)))
    runtime_text = html.decode("utf-8") + "\n".join(css_bodies)
    if re.search(r"https?://", runtime_text):
        raise ValueError("frontend entry assets contain an external runtime URL")
    return {"files": assets, "total_bytes": sum(assets.values())}


def _markdown(report: dict[str, Any]) -> str:
    measurements = report["measurements"]
    images = report["images"]
    memory = report["memory"]
    lines = [
        "# Phase 10 generated performance report",
        "",
        f"- Status: **{report['status']}**",
        f"- Generated: `{report['generated_at']}`",
        f"- Clean build: `{measurements['clean_build_seconds']:.3f}s`",
        f"- Startup: `{measurements['startup_seconds']:.3f}s`",
        f"- Restart: `{measurements['restart_seconds']:.3f}s`",
        "",
        "| Measurement | Median | p95 |",
        "|---|---:|---:|",
        (
            "| One-row inference | "
            f"{measurements['single_row']['median_seconds']:.3f}s | "
            f"{measurements['single_row']['p95_seconds']:.3f}s |"
        ),
        (
            "| 10,000-row inference | "
            f"{measurements['max_batch']['median_seconds']:.3f}s | "
            f"{measurements['max_batch']['p95_seconds']:.3f}s |"
        ),
        "",
        f"- API peak memory: `{memory['api_peak_bytes'] / MIB:.2f} MiB`.",
        f"- Frontend peak memory: `{memory['frontend_peak_bytes'] / MIB:.2f} MiB`.",
        f"- API image: `{images['api']['size_bytes'] / MIB:.2f} MiB`.",
        f"- Frontend image: `{images['frontend']['size_bytes'] / MIB:.2f} MiB`.",
        (
            "- First-page assets, including the local font: "
            f"`{report['frontend_assets']['total_bytes'] / 1024:.2f} KiB`."
        ),
        (f"- Maximum-batch response: `{measurements['max_batch_response_bytes'] / MIB:.2f} MiB`."),
        (
            f"- Concurrency: `{report['concurrency']['requests']}` requests at "
            f"`{report['concurrency']['workers']}` workers; row/request isolation passed."
        ),
        "",
    ]
    if report["violations"]:
        lines.extend(["## Violations", ""])
        lines.extend(f"- {item}" for item in report["violations"])
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    arguments = _arguments()
    project_root = arguments.project_root.resolve()
    model_dir = arguments.model_dir.resolve()
    output = arguments.output.resolve()
    if arguments.repetitions != 5:
        raise ValueError("Phase 10 requires exactly five benchmark repetitions")
    if arguments.max_rows != 10_000:
        raise ValueError("Phase 10 requires the supported 10,000-row maximum batch")

    environment = os.environ.copy()
    environment["IDS_MODEL_HOST_DIR"] = str(model_dir)
    environment.setdefault("COMPOSE_PROJECT_NAME", "ids_phase10")
    api_url = f"http://127.0.0.1:{environment.get('API_PORT', '8000')}"
    frontend_url = f"http://127.0.0.1:{environment.get('FRONTEND_PORT', '8080')}"
    api_peak = 0
    frontend_peak = 0
    stop_sampling = threading.Event()
    sampling_errors: list[str] = []
    api_id = ""
    frontend_id = ""

    def sample_memory() -> None:
        nonlocal api_peak, frontend_peak
        while not stop_sampling.is_set():
            try:
                api_peak = max(
                    api_peak,
                    _container_memory(api_id, cwd=project_root, environment=environment),
                )
                frontend_peak = max(
                    frontend_peak,
                    _container_memory(frontend_id, cwd=project_root, environment=environment),
                )
            except (ValueError, subprocess.CalledProcessError) as error:
                sampling_errors.append(str(error))
                return
            stop_sampling.wait(0.25)

    _compose(project_root, environment, "down", "--remove-orphans")
    try:
        started = time.perf_counter()
        _compose(
            project_root,
            environment,
            "up",
            "--detach",
            "--no-build",
            "--wait",
            "--wait-timeout",
            "45",
        )
        startup_seconds = time.perf_counter() - started
        api_id = _container_id(project_root, environment, "api")
        frontend_id = _container_id(project_root, environment, "frontend")
        sampler = threading.Thread(target=sample_memory, daemon=True)
        sampler.start()

        ready: object = json.loads(_request(f"{api_url}/ready"))
        if ready != {"status": "ready", "model_version": "ids-rf-v1.0.0"}:
            raise ValueError(f"unexpected readiness response: {ready}")
        template = _request(f"{api_url}/api/v1/input-template")
        single_payload, single_ids = _csv_payload(template, 1, prefix="single")
        max_payload, max_ids = _csv_payload(template, arguments.max_rows, prefix="maximum")
        warmup, _size, _duration = _post_csv(api_url, single_payload)
        _validate_prediction(warmup, single_ids)

        single_samples: list[float] = []
        single_response_bytes = 0
        for _index in range(arguments.repetitions):
            response, response_bytes, duration = _post_csv(api_url, single_payload)
            _validate_prediction(response, single_ids)
            single_samples.append(duration)
            single_response_bytes = max(single_response_bytes, response_bytes)

        max_samples: list[float] = []
        max_response_bytes = 0
        for _index in range(arguments.repetitions):
            response, response_bytes, duration = _post_csv(api_url, max_payload)
            _validate_prediction(response, max_ids)
            max_samples.append(duration)
            max_response_bytes = max(max_response_bytes, response_bytes)

        def concurrent_request(index: int) -> tuple[str, str]:
            payload, expected = _csv_payload(template, 1, prefix=f"concurrent-{index}")
            response, _response_bytes, _duration = _post_csv(api_url, payload)
            return expected[0], _validate_prediction(response, expected)

        concurrent_count = arguments.concurrency * 2
        with ThreadPoolExecutor(max_workers=arguments.concurrency) as executor:
            concurrent_results = list(executor.map(concurrent_request, range(concurrent_count)))
        if len({row_id for row_id, _request_id in concurrent_results}) != concurrent_count:
            raise ValueError("concurrent response rows were not isolated")
        if len({_request_id for _row_id, _request_id in concurrent_results}) != concurrent_count:
            raise ValueError("concurrent request IDs were not isolated")

        frontend_assets = _frontend_assets(frontend_url)
        limits = {
            "api": _container_limits(api_id, cwd=project_root, environment=environment),
            "frontend": _container_limits(frontend_id, cwd=project_root, environment=environment),
        }
        images = _image_metadata(project_root, environment)
        artifact = _artifact_metadata(model_dir)

        stop_sampling.set()
        sampler.join(timeout=10)
        if sampler.is_alive() or sampling_errors:
            raise RuntimeError("memory sampling failed: " + "; ".join(sampling_errors))

        _compose(project_root, environment, "down", "--remove-orphans")
        restarted = time.perf_counter()
        _compose(
            project_root,
            environment,
            "up",
            "--detach",
            "--no-build",
            "--wait",
            "--wait-timeout",
            "45",
        )
        restart_seconds = time.perf_counter() - restarted
        restart_prediction, _restart_bytes, _restart_duration = _post_csv(api_url, single_payload)
        _validate_prediction(restart_prediction, single_ids)
        _request(f"{frontend_url}/")

        single_summary = _summary(single_samples)
        max_summary = _summary(max_samples)
        violations: list[str] = []
        checks = {
            "startup_seconds": startup_seconds,
            "restart_seconds": restart_seconds,
            "single_row_p95_seconds": single_summary["p95_seconds"],
            "max_batch_p95_seconds": max_summary["p95_seconds"],
            "api_peak_memory_bytes": api_peak,
            "frontend_asset_bytes": frontend_assets["total_bytes"],
            "max_batch_response_bytes": max_response_bytes,
            "api_image_bytes": images["api"]["size_bytes"],
            "frontend_image_bytes": images["frontend"]["size_bytes"],
        }
        for name, value in checks.items():
            if value > BUDGETS[name]:
                violations.append(f"{name}={value} exceeds budget {BUDGETS[name]}")
        for service, service_limits in limits.items():
            if any(service_limits[key] <= 0 for key in ("memory_bytes", "nano_cpus", "pids_limit")):
                violations.append(f"{service} is missing a memory, CPU, or PID limit")
        if api_peak >= limits["api"]["memory_bytes"]:
            violations.append("API measured memory reached or exceeded its container limit")

        docker_version = _run(
            ["docker", "version", "--format", "{{.Client.Version}}/{{.Server.Version}}"],
            cwd=project_root,
            environment=environment,
        ).stdout.strip()
        report: dict[str, Any] = {
            "schema_version": "phase10-performance-v1",
            "status": "PASS" if not violations else "FAIL",
            "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "environment": {
                "platform": platform.platform(),
                "machine": platform.machine(),
                "python": platform.python_version(),
                "docker_client_server": docker_version,
            },
            "budgets": BUDGETS,
            "measurements": {
                "clean_build_seconds": round(arguments.build_seconds, 6),
                "startup_seconds": round(startup_seconds, 6),
                "restart_seconds": round(restart_seconds, 6),
                "single_row": single_summary,
                "max_batch": max_summary,
                "single_response_bytes": single_response_bytes,
                "max_batch_request_bytes": len(max_payload),
                "max_batch_response_bytes": max_response_bytes,
            },
            "memory": {
                "api_peak_bytes": api_peak,
                "frontend_peak_bytes": frontend_peak,
                "container_limits": limits,
            },
            "images": images,
            "frontend_assets": frontend_assets,
            "concurrency": {
                "workers": arguments.concurrency,
                "requests": concurrent_count,
                "isolated_row_ids": True,
                "isolated_request_ids": True,
            },
            "artifact": artifact,
            "violations": violations,
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        output.with_suffix(".md").write_text(_markdown(report), encoding="utf-8")
        print(_markdown(report))
        return 0 if not violations else 1
    finally:
        stop_sampling.set()
        _compose(project_root, environment, "down", "--remove-orphans")


if __name__ == "__main__":
    raise SystemExit(main())
