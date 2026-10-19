#!/usr/bin/env python3
"""Validate committed Phase 6 API and deployment contracts."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_FILES = (
    "backend/app/config.py",
    "backend/app/errors.py",
    "backend/app/inference.py",
    "backend/app/main.py",
    "backend/app/schemas.py",
    "backend/tests/test_api.py",
    "docs/api-contract.md",
    "docs/api-inference-v1.md",
)
ROUTES = (
    '"/health"',
    '"/ready"',
    '"/api/v1/model"',
    '"/api/v1/input-template"',
    '"/api/v1/predictions"',
    '"/api/v1/predictions/file"',
)
ERROR_CODES = (
    "EMPTY_INPUT",
    "INVALID_CSV",
    "DUPLICATE_COLUMNS",
    "MISSING_REQUIRED_COLUMNS",
    "TOO_MANY_COLUMNS",
    "TOO_MANY_ROWS",
    "FILE_TOO_LARGE",
    "UNSUPPORTED_MEDIA_TYPE",
    "UNSUPPORTED_ENCODING",
    "INVALID_FEATURE_VALUE",
    "NO_VALID_ROWS",
    "MODEL_UNAVAILABLE",
    "INFERENCE_FAILED",
    "INVALID_REQUEST",
    "DUPLICATE_ROW_ID",
)


def _contains(relative: str, values: tuple[str, ...], errors: list[str]) -> None:
    source = (ROOT / relative).read_text(encoding="utf-8")
    for value in values:
        if value not in source:
            errors.append(f"{relative} is missing required Phase 6 contract text: {value}")


def _validate_artifact_boundary(errors: list[str]) -> None:
    result = subprocess.run(
        ["git", "check-ignore", "models/ids-rf-v1/pipeline.joblib"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        errors.append("the generated production artifact is not ignored by Git")


def main() -> int:
    errors = [
        f"missing required Phase 6 file: {path}"
        for path in REQUIRED_FILES
        if not (ROOT / path).is_file()
    ]
    if not errors:
        _contains("backend/app/main.py", ROUTES, errors)
        _contains("docs/api-contract.md", ERROR_CODES, errors)
        _contains(
            "backend/app/inference.py",
            (
                "load_artifact",
                "math.isfinite",
                "MISSING_REQUIRED_COLUMNS",
                "INVALID_FEATURE_VALUE",
                "PARTIAL_SUCCESS",
            ),
            errors,
        )
        _contains(
            "docker-compose.yml",
            ("/ready", ":/app/models/ids-rf-v1:ro", "IDS_CORS_ORIGINS"),
            errors,
        )
        _contains(
            "scripts/smoke.sh",
            ("/api/v1/input-template", "/api/v1/predictions/file", "valid_rows"),
            errors,
        )
        _validate_artifact_boundary(errors)
    if errors:
        print("Phase 6 validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Phase 6 repository validation passed: API contract and artifact boundary enforced.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
