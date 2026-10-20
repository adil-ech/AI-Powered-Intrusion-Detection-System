#!/usr/bin/env python3
"""Validate committed Phase 7 fixture-frontend contracts."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_FILES = (
    "docs/frontend/phase-07-art-direction.md",
    "frontend/src/accessibility.test.tsx",
    "frontend/src/components/ResultsDashboard.tsx",
    "frontend/src/components/UploadExperience.tsx",
    "frontend/src/fixtures/api-v1.test.ts",
    "frontend/src/fixtures/api-v1.ts",
    "frontend/src/lib/analytics.ts",
    "frontend/src/lib/csv.test.ts",
    "frontend/src/lib/csv.ts",
    "frontend/src/types/api.ts",
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
            errors.append(f"{relative} is missing required Phase 7 text: {value}")


def _validate_template_contract(errors: list[str]) -> None:
    contract = _json("contracts/features-v1.json")
    expected = contract.get("required_features")
    if not isinstance(expected, list) or not all(isinstance(item, str) for item in expected):
        errors.append("contracts/features-v1.json has no valid required_features list")
        return

    source = (ROOT / "frontend/src/lib/csv.ts").read_text(encoding="utf-8")
    match = re.search(
        r"export const REQUIRED_FEATURES = \[(.*?)\] as const;",
        source,
        flags=re.DOTALL,
    )
    if match is None:
        errors.append("frontend CSV template does not expose REQUIRED_FEATURES")
        return
    actual = re.findall(r'"([a-z0-9_]+)"', match.group(1))
    if actual != expected:
        errors.append("frontend CSV template does not exactly match features-v1 order")


def _validate_frontend_config(errors: list[str]) -> None:
    package = _json("frontend/package.json")
    scripts = package.get("scripts", {})
    for command in ("build", "format:check", "lint", "test", "typecheck"):
        if command not in scripts:
            errors.append(f"frontend package is missing the {command!r} script")

    dev_dependencies = package.get("devDependencies", {})
    for dependency in ("@testing-library/user-event", "axe-core"):
        if dependency not in dev_dependencies:
            errors.append(f"frontend package is missing {dependency}")


def main() -> int:
    errors = [
        f"missing required Phase 7 file: {path}"
        for path in REQUIRED_FILES
        if not (ROOT / path).is_file()
    ]
    if not errors:
        _validate_template_contract(errors)
        _validate_frontend_config(errors)
        _contains(
            "frontend/src/fixtures/api-v1.ts",
            (
                "normal:",
                "mixed:",
                "edge:",
                "empty:",
                "invalid:",
                "failure:",
                "ids-rf-v1.0.0",
                "features-v1",
            ),
            errors,
        )
        _contains(
            "frontend/src/styles.css",
            (
                "prefers-reduced-motion: reduce",
                "@media (max-width: 760px)",
                "@media (max-width: 640px)",
                ":focus-visible",
            ),
            errors,
        )
        _contains(
            "frontend/src/lib/csv.ts",
            (
                "neutralizeSpreadsheetFormula",
                "feature_schema_version",
                "analysis_status",
            ),
            errors,
        )
        _contains(
            "docs/frontend/phase-07-art-direction.md",
            (
                "The product performs",
                "216573512",
                "versioned local responses",
            ),
            errors,
        )

    if errors:
        print("Phase 7 validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(
        "Phase 7 repository validation passed: fixture states, schema, export, "
        "and visual contracts enforced."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
