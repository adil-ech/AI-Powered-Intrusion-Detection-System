#!/usr/bin/env python3
"""Validate committed Phase 4 baseline and evaluation contracts."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_FILES = (
    "configs/baselines-v1.json",
    "docs/ml/baselines-v1.md",
    "ml/src/ids_ml/evaluation/config.py",
    "ml/src/ids_ml/evaluation/data.py",
    "ml/src/ids_ml/evaluation/metrics.py",
    "ml/src/ids_ml/evaluation/models.py",
    "ml/src/ids_ml/evaluation/report.py",
    "ml/tests/test_evaluation.py",
)


def _load_json(relative: str) -> dict[str, Any]:
    raw: object = json.loads((ROOT / relative).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{relative} must contain a JSON object")
    return raw


def _validate_config(errors: list[str]) -> None:
    config = _load_json("configs/baselines-v1.json")
    expected = {
        "random_seed": 42,
        "batch_size": 8192,
        "binary_threshold": 0.5,
        "headline_split": "validation",
        "final_test_policy": "sealed_not_evaluated",
    }
    for key, value in expected.items():
        if config.get(key) != value:
            errors.append(f"baseline config {key} must remain {value!r}")
    logistic = config.get("binary_logistic")
    if not isinstance(logistic, dict) or logistic.get("loss") != "log_loss":
        errors.append("binary logistic baseline must use logistic loss")
    elif logistic.get("class_weighting") != "balanced_from_training_support":
        errors.append("binary logistic baseline must record training-only class weighting")


def _validate_dependencies(errors: list[str]) -> None:
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    for dependency in ("joblib>=", "numpy>=", "scikit-learn>="):
        if dependency not in project:
            errors.append(f"pyproject is missing direct runtime dependency: {dependency}")


def _validate_final_test_boundary(errors: list[str]) -> None:
    report_source = (ROOT / "ml/src/ids_ml/evaluation/report.py").read_text(encoding="utf-8")
    required = (
        '"status": "sealed_not_evaluated"',
        '"final_test_opened_for_predictions": False',
        '"final_test_used_for_selection": False',
    )
    for value in required:
        if value not in report_source:
            errors.append(f"baseline report source is missing final-test guard: {value}")


def _validate_docs(errors: list[str]) -> None:
    text = (ROOT / "docs/ml/baselines-v1.md").read_text(encoding="utf-8")
    required = (
        "make gate-4",
        "SGDClassifier",
        "validation",
        "SEALED",
        "false-positive rate",
        "class support",
    )
    for value in required:
        if value not in text:
            errors.append(f"baseline guide is missing reviewed detail: {value}")


def _validate_artifact_boundary(errors: list[str]) -> None:
    result = subprocess.run(
        ["git", "ls-files", "--", "models"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    tracked = [line for line in result.stdout.splitlines() if line]
    if tracked != ["models/README.md"]:
        errors.append(f"generated model tracking boundary violated: {tracked}")


def main() -> int:
    errors = [
        f"missing required Phase 4 file: {path}"
        for path in REQUIRED_FILES
        if not (ROOT / path).is_file()
    ]
    if not errors:
        _validate_config(errors)
        _validate_dependencies(errors)
        _validate_final_test_boundary(errors)
        _validate_docs(errors)
        _validate_artifact_boundary(errors)
    if errors:
        print("Phase 4 validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Phase 4 repository validation passed: validation-only baselines, final test sealed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
