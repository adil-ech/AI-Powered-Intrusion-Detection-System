#!/usr/bin/env python3
"""Validate committed Phase 10 performance and reproducibility contracts."""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_FILES = (
    "backend/tests/test_phase10.py",
    "docs/deployment-performance.md",
    "frontend/public/fonts/OFL.txt",
    "frontend/public/fonts/jost-latin.woff2",
    "scripts/benchmark_phase10.py",
    "scripts/verify_clean_checkout.py",
)
EXPECTED_FONT_SHA256 = "235d8f8964bfdf105fc0c3e4c77b5e70f31bee1dad611d59318b5f2a5cb64d90"


def _contains(relative: str, values: tuple[str, ...], errors: list[str]) -> None:
    source = (ROOT / relative).read_text(encoding="utf-8")
    for value in values:
        if value not in source:
            errors.append(f"{relative} is missing required Phase 10 text: {value}")


def _validate_dockerfiles(errors: list[str]) -> None:
    for relative in ("backend/Dockerfile", "frontend/Dockerfile"):
        source = (ROOT / relative).read_text(encoding="utf-8")
        bases = re.findall(r"^FROM\s+(\S+)", source, flags=re.MULTILINE)
        if not bases or any("@sha256:" not in base for base in bases):
            errors.append(f"{relative} must pin every base image by digest")
    _contains(
        "backend/Dockerfile",
        (
            " AS build",
            " AS runtime",
            "/app/.venv ./.venv",
            "USER app",
        ),
        errors,
    )
    _contains(
        "frontend/Dockerfile",
        (" AS build", " AS runtime", "npm ci", "USER 101:101"),
        errors,
    )


def _validate_tracked_boundaries(errors: list[str]) -> None:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    tracked = [Path(value.decode()) for value in result.stdout.split(b"\0") if value]
    forbidden = [
        str(path)
        for path in tracked
        if (
            (path.parts[:2] == ("data", "raw") and path.name != "README.md")
            or (path.parts[:1] == ("models",) and path.name != "README.md")
            or path.parts[:2] == ("reports", "generated")
            or (path.name.startswith(".env") and path.name != ".env.example")
        )
    ]
    if forbidden:
        errors.append("generated/private files are tracked: " + ", ".join(forbidden))


def main() -> int:
    errors = [
        f"missing required Phase 10 file: {relative}"
        for relative in REQUIRED_FILES
        if not (ROOT / relative).is_file()
    ]
    if not errors:
        _validate_dockerfiles(errors)
        _validate_tracked_boundaries(errors)
        _contains(
            "docker-compose.yml",
            (
                "IDS_MODEL_HOST_DIR",
                "API_MEMORY_LIMIT",
                "FRONTEND_MEMORY_LIMIT",
                "pids_limit:",
                "healthcheck:",
            ),
            errors,
        )
        _contains(
            ".env.example",
            (
                "IDS_MODEL_HOST_DIR=",
                "API_CPU_LIMIT=",
                "API_MEMORY_LIMIT=",
                "FRONTEND_CPU_LIMIT=",
                "FRONTEND_MEMORY_LIMIT=",
            ),
            errors,
        )
        _contains(
            "scripts/benchmark_phase10.py",
            (
                '"--repetitions", type=int, default=5',
                '"--max-rows", type=int, default=10_000',
                '"max_batch_p95_seconds": 10.0',
                "isolated_request_ids",
                "api_peak_memory_bytes",
            ),
            errors,
        )
        _contains(
            "scripts/verify_clean_checkout.py",
            (
                '"git", "status", "--porcelain=v1"',
                '"git", "archive"',
                '"build", "--no-cache", "--pull"',
                '".env.example"',
            ),
            errors,
        )
        _contains(
            "Makefile",
            ("performance:", "gate-10:", "scripts/validate_phase10.py"),
            errors,
        )
        _contains(
            "frontend/src/styles.css",
            ('url("/fonts/jost-latin.woff2")',),
            errors,
        )
        external_font_markers = ("fonts.googleapis.com", "fonts.gstatic.com")
        for relative in ("frontend/index.html", "frontend/nginx.conf"):
            source = (ROOT / relative).read_text(encoding="utf-8")
            if any(marker in source for marker in external_font_markers):
                errors.append(f"{relative} still depends on an external font host")
        font_hash = hashlib.sha256(
            (ROOT / "frontend/public/fonts/jost-latin.woff2").read_bytes()
        ).hexdigest()
        if font_hash != EXPECTED_FONT_SHA256:
            errors.append("self-hosted Jost asset does not match its reviewed SHA-256")

    if errors:
        print("Phase 10 validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(
        "Phase 10 repository validation passed: digests, offline assets, resource limits, "
        "clean-checkout build, and benchmark contracts enforced."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
