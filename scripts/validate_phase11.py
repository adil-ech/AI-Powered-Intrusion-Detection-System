#!/usr/bin/env python3
"""Validate the Phase 11 documentation and release-candidate contracts."""

from __future__ import annotations

import csv
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_FILES = (
    "CHANGELOG.md",
    "THIRD_PARTY_NOTICES.md",
    "docs/architecture.md",
    "docs/demo-script.md",
    "docs/release-checklist.md",
    "reports/checkpoints/phase-08/browser/live-results-desktop.png",
    "reports/checkpoints/phase-08/browser/live-results-mobile.png",
    "reports/checkpoints/phase-08/browser/live-results-tablet.png",
    "frontend/public/samples/ids-demo-mixed.csv",
    "scripts/verify_release.py",
)
README_HEADINGS = (
    "## Architecture",
    "## Quick start with Docker",
    "## API examples",
    "## Measured model and runtime behavior",
    "## Supported environment and browsers",
    "## Troubleshooting",
    "## License and notices",
)


def _require_text(relative: str, required: tuple[str, ...], errors: list[str]) -> None:
    source = (ROOT / relative).read_text(encoding="utf-8")
    for value in required:
        if value not in source:
            errors.append(f"{relative} is missing required release text: {value}")


def _validate_prior_checkpoints(errors: list[str]) -> None:
    for phase in range(11):
        relative = f"reports/checkpoints/phase-{phase:02d}/summary.md"
        path = ROOT / relative
        if not path.is_file():
            errors.append(f"missing earlier checkpoint: {relative}")
            continue
        source = path.read_text(encoding="utf-8")
        if "Status: PASS" not in source and "**Status:** PASS" not in source:
            errors.append(f"earlier checkpoint is not PASS: {relative}")


def _validate_safe_sample(errors: list[str]) -> None:
    contract: object = json.loads((ROOT / "contracts/features-v1.json").read_text())
    if not isinstance(contract, dict) or not isinstance(contract.get("features"), list):
        errors.append("feature contract is malformed")
        return
    features = [item.get("name") for item in contract["features"] if isinstance(item, dict)]
    sample_path = ROOT / "frontend/public/samples/ids-demo-mixed.csv"
    with sample_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        headers = reader.fieldnames
    expected_headers = ["row_id", *features]
    if headers != expected_headers:
        errors.append("safe demo sample does not exactly match the ordered feature contract")
    if [row.get("row_id") for row in rows] != [f"demo-{index:02d}" for index in range(1, 7)]:
        errors.append("safe demo sample must contain the six reviewed demo row IDs")
    prohibited = {
        "label",
        "source_ip",
        "destination_ip",
        "source_port",
        "destination_port",
        "timestamp",
    }
    if headers is not None and prohibited.intersection(headers):
        errors.append("safe demo sample contains a label or network identifier column")
    for row in rows:
        for feature in features:
            value = row.get(str(feature), "")
            try:
                finite = math.isfinite(float(value))
            except ValueError:
                finite = False
            if not finite:
                errors.append(f"safe demo sample has a non-finite value in {feature}")
                return


def main() -> int:
    errors = [
        f"missing required Phase 11 file: {relative}"
        for relative in REQUIRED_FILES
        if not (ROOT / relative).is_file()
    ]
    if not errors:
        _validate_prior_checkpoints(errors)
        _validate_safe_sample(errors)
        _require_text("README.md", README_HEADINGS, errors)
        _require_text(
            "README.md",
            (
                "reports/checkpoints/phase-08/browser/live-results-desktop.png",
                "make release-check",
                "ids-rf-v1.0.0",
                "not a packet sniffer",
            ),
            errors,
        )
        _require_text(
            "docs/model-card.md",
            ("## Dataset citation", "## Release use and review", "0.918035", "0.375000"),
            errors,
        )
        _require_text(
            "docs/architecture.md",
            (
                "```mermaid",
                "Trusted read-only artifact",
                "Neither service writes upload rows",
                "live-results-mobile.png",
                "recovered-results-desktop.png",
            ),
            errors,
        )
        _require_text(
            "docs/demo-script.md",
            ("demo-03", "91.35%", "ids-rf-v1.0.0", "docker compose down"),
            errors,
        )
        _require_text(
            "THIRD_PARTY_NOTICES.md",
            ("Jost", "SIL Open Font License", "CIC-IDS2017", "React"),
            errors,
        )
        _require_text(
            "CHANGELOG.md",
            ("## [0.1.0] - 2026-10-21", "### Known limitations"),
            errors,
        )
        _require_text(
            "Makefile",
            ("release-check:", "gate-11:", "scripts/validate_phase11.py"),
            errors,
        )
        for relative in REQUIRED_FILES:
            path = ROOT / relative
            if path.suffix.lower() in {".png", ".jpg"} and path.stat().st_size < 10_000:
                errors.append(f"approved screenshot is unexpectedly small: {relative}")

    if errors:
        print("Phase 11 validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(
        "Phase 11 repository validation passed: release docs, prior checkpoints, "
        "safe demo, screenshots, notices, and release commands are complete."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
