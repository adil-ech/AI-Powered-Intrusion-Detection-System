#!/usr/bin/env python3
"""Validate committed Phase 8 full-stack integration contracts."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = "frontend/public/samples/ids-demo-mixed.csv"
REQUIRED_FILES = (
    "docs/frontend/phase-08-integration.md",
    "frontend/.env.example",
    "frontend/e2e/live-workflow.spec.ts",
    "frontend/playwright.config.ts",
    "frontend/src/api/client.test.ts",
    "frontend/src/api/client.ts",
    "reports/checkpoints/phase-08/integration-review.md",
    SAMPLE,
    "scripts/e2e.sh",
)


def _json(relative: str) -> dict[str, Any]:
    raw: object = json.loads((ROOT / relative).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{relative} must contain a JSON object")
    return raw


def _contains(relative: str, values: tuple[str, ...], errors: list[str]) -> None:
    source = (ROOT / relative).read_text(encoding="utf-8")
    for value in values:
        if value not in source:
            errors.append(f"{relative} is missing required Phase 8 text: {value}")


def _validate_production_transport(errors: list[str]) -> None:
    app_source = (ROOT / "frontend/src/App.tsx").read_text(encoding="utf-8")
    forbidden = ("fixtures/api-v1", "getFixture(", "scenario=")
    for value in forbidden:
        if value in app_source:
            errors.append(f"frontend/src/App.tsx still contains fixture transport: {value}")

    _contains(
        "frontend/src/api/client.ts",
        (
            '"/ready"',
            '"/api/v1/model"',
            '"/api/v1/input-template"',
            '"/api/v1/predictions/file"',
            "REQUEST_TIMEOUT_MS",
            "UPLOAD_TIMEOUT_MS",
            "AbortSignal",
            "VITE_API_BASE_URL",
        ),
        errors,
    )


def _validate_sample(errors: list[str]) -> None:
    contract = _json("contracts/features-v1.json")
    features = contract.get("required_features")
    if not isinstance(features, list) or not all(isinstance(item, str) for item in features):
        errors.append("contracts/features-v1.json has no valid required_features list")
        return

    with (ROOT / SAMPLE).open(encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        rows = list(reader)
    if not rows:
        errors.append(f"{SAMPLE} is empty")
        return
    if rows[0] != ["row_id", *features]:
        errors.append(f"{SAMPLE} does not exactly match features-v1 order")
    if len(rows) != 7:
        errors.append(f"{SAMPLE} must contain exactly six data rows")
    expected_ids = [f"demo-{index:02d}" for index in range(1, 7)]
    if [row[0] for row in rows[1:] if row] != expected_ids:
        errors.append(f"{SAMPLE} must use only the six documented demo row IDs")


def _validate_e2e(errors: list[str]) -> None:
    _contains(
        "frontend/e2e/live-workflow.spec.ts",
        (
            "Model ready:",
            "Download model template",
            "Rows received",
            "Suspicious",
            "Verdict",
            "Details",
            "Export view",
            "MISSING_REQUIRED_COLUMNS",
            "FILE_TOO_LARGE",
            'compose("stop", "api")',
            'compose("start", "api")',
            "applicationErrors",
        ),
        errors,
    )
    _contains(
        "scripts/e2e.sh",
        ("down --remove-orphans", "up --build --detach --wait", "trap cleanup EXIT"),
        errors,
    )
    _contains(
        "frontend/nginx.conf",
        ("client_max_body_size 11m", "proxy_connect_timeout 3s"),
        errors,
    )


def _validate_frontend_config(errors: list[str]) -> None:
    package = _json("frontend/package.json")
    scripts = package.get("scripts", {})
    if not isinstance(scripts, dict) or "e2e" not in scripts:
        errors.append("frontend package is missing the e2e script")
    dependencies = package.get("devDependencies", {})
    if not isinstance(dependencies, dict) or "@playwright/test" not in dependencies:
        errors.append("frontend package is missing @playwright/test")


def main() -> int:
    errors = [
        f"missing required Phase 8 file: {path}"
        for path in REQUIRED_FILES
        if not (ROOT / path).is_file()
    ]
    if not errors:
        _validate_production_transport(errors)
        _validate_sample(errors)
        _validate_e2e(errors)
        _validate_frontend_config(errors)
        _contains(
            "Makefile",
            ("test-e2e:", "gate-8:", "scripts/validate_phase8.py"),
            errors,
        )

    if errors:
        print("Phase 8 validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(
        "Phase 8 repository validation passed: live transport, safe sample, "
        "browser journey, and recovery contracts enforced."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
