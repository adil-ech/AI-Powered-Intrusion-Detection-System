#!/usr/bin/env python3
"""Validate committed Phase 9 security, privacy, and resilience contracts."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_FILES = (
    ".gitleaks.toml",
    "backend/tests/test_security.py",
    "configs/security-exceptions.json",
    "docs/security-privacy.md",
    "reports/checkpoints/phase-09/security-report.md",
    "scripts/security.sh",
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
            errors.append(f"{relative} is missing required Phase 9 text: {value}")


def _validate_ignored_environment(errors: list[str]) -> None:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    tracked = [Path(item.decode()) for item in result.stdout.split(b"\0") if item]
    unexpected = [
        str(path)
        for path in tracked
        if path.name.startswith(".env") and path.name != ".env.example"
    ]
    if unexpected:
        errors.append("non-example environment files are tracked: " + ", ".join(unexpected))

    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    if ".env" not in ignore or ".env.*" not in ignore or "!.env.example" not in ignore:
        errors.append(".gitignore does not preserve the environment-file deny-by-default policy")


def _validate_locks(errors: list[str]) -> None:
    lock = (ROOT / "uv.lock").read_text(encoding="utf-8")
    if not lock.startswith("version = 1"):
        errors.append("uv.lock is not a recognized exact dependency lock")
    package_lock = _json("frontend/package-lock.json")
    if package_lock.get("lockfileVersion") != 3:
        errors.append("frontend/package-lock.json must use lockfileVersion 3")


def main() -> int:
    errors = [
        f"missing required Phase 9 file: {path}"
        for path in REQUIRED_FILES
        if not (ROOT / path).is_file()
    ]
    if not errors:
        _validate_ignored_environment(errors)
        _validate_locks(errors)
        _contains(
            "backend/app/main.py",
            (
                "RequestGuardMiddleware",
                "PROCESSING_TIMEOUT",
                "await file.close()",
                "INVALID_FILENAME",
                "debug=False",
                "X-Content-Type-Options",
            ),
            errors,
        )
        _contains(
            "backend/app/config.py",
            (
                'origin == "*"',
                "IDS_MAX_UPLOAD_BYTES",
                "IDS_PROCESSING_TIMEOUT_SECONDS",
            ),
            errors,
        )
        _contains(
            "frontend/src/lib/csv.ts",
            ("neutralizeSpreadsheetFormula", r"/^[=+\-@\t\r]/"),
            errors,
        )
        _contains(
            "docker-compose.yml",
            ("read_only: true", "no-new-privileges:true", "cap_drop:", "tmpfs:"),
            errors,
        )
        _contains(
            "backend/Dockerfile",
            ("USER app", "--no-cache", "COPY backend/app ./backend/app"),
            errors,
        )
        _contains("frontend/Dockerfile", ("USER 101:101",), errors)
        _contains(
            "scripts/security.sh",
            (
                "gitleaks:v8.30.1",
                "trivy:0.76.0",
                "--severity HIGH,CRITICAL",
                "check_vulnerability_report.py",
                "--network none",
                "--read-only",
            ),
            errors,
        )
        _contains(
            "Makefile",
            ("security:", "test-security:", "gate-9:", "scripts/validate_phase9.py"),
            errors,
        )

    if errors:
        print("Phase 9 validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(
        "Phase 9 repository validation passed: hostile-input, privacy, secret, "
        "dependency, image, and runtime contracts enforced."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
