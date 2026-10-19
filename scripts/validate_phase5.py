#!/usr/bin/env python3
"""Validate committed Phase 5 selection and artifact contracts."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_FILES = (
    "configs/model-selection-v1.json",
    "docs/ml/model-selection-v1.md",
    "docs/model-card.md",
    "ml/src/ids_ml/modeling/artifact.py",
    "ml/src/ids_ml/modeling/config.py",
    "ml/src/ids_ml/modeling/data.py",
    "ml/src/ids_ml/modeling/models.py",
    "ml/src/ids_ml/modeling/pipeline.py",
    "ml/src/ids_ml/modeling/port_variant.py",
    "ml/tests/test_modeling.py",
)


def _json(relative: str) -> dict[str, Any]:
    raw: object = json.loads((ROOT / relative).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{relative} must contain a JSON object")
    return raw


def _validate_config(errors: list[str]) -> None:
    config = _json("configs/model-selection-v1.json")
    if config.get("random_seed") != 42:
        errors.append("model selection random_seed must remain 42")
    if config.get("validation_folds") != 3:
        errors.append("model selection must keep three group-aware validation folds")
    if config.get("calibration_method") != "binary_platt_family_temperature":
        errors.append("model selection calibration method changed unexpectedly")
    if config.get("selection_frozen") is not True:
        errors.append("Phase 5 selection must be frozen before finalization")
    expected = {
        "feature_variant": "without_destination_port",
        "binary_candidate": "rf-binary-compact",
        "family_candidate": "rf-family-deep",
    }
    if config.get("frozen_selection") != expected:
        errors.append(f"frozen selection must remain {expected}")
    threshold = config.get("threshold_search")
    if not isinstance(threshold, dict) or threshold.get("maximum_false_positive_rate") != 0.03:
        errors.append("threshold search must retain the 0.03 false-positive-rate ceiling")


def _validate_feature_boundary(errors: list[str]) -> None:
    contract = _json("contracts/features-v1.json")
    features = contract.get("required_features")
    if not isinstance(features, list) or "destination_port" in features:
        errors.append("the frozen production schema must exclude destination_port")
        return
    if len(features) != 63:
        errors.append("the frozen production schema must retain 63 features")


def _validate_final_guard(errors: list[str]) -> None:
    source = (ROOT / "ml/src/ids_ml/modeling/pipeline.py").read_text(encoding="utf-8")
    freeze_guard = "if finalize and not config.selection_frozen:"
    final_open = 'selected_processed / "final_test.csv.gz"'
    if freeze_guard not in source or final_open not in source:
        errors.append("modeling pipeline is missing the selection-freeze final-test guard")
    elif source.index(freeze_guard) > source.index(final_open):
        errors.append("final-test materialization occurs before the selection-freeze guard")
    for value in (
        '"final_test_used_for_selection": False',
        '"status": "evaluated_once_after_selection_freeze"',
        '"final_test_reopened_for_predictions": False',
    ):
        if value not in source:
            errors.append(f"modeling pipeline is missing final-test evidence: {value}")


def _validate_docs(errors: list[str]) -> None:
    guide = (ROOT / "docs/ml/model-selection-v1.md").read_text(encoding="utf-8")
    card = (ROOT / "docs/model-card.md").read_text(encoding="utf-8")
    for value in (
        "validation_tuning",
        "validation_calibration",
        "validation_selection_holdout",
        "destination_port",
        "make gate-5",
        "manifest.json",
    ):
        if value not in guide:
            errors.append(f"model-selection guide is missing reviewed detail: {value}")
    for value in (
        "ids-rf-v1.0.0",
        "0.015",
        "0.009507",
        "0.998202",
        "INFILTRATION",
        "RARE_OTHER",
    ):
        if value not in card:
            errors.append(f"model card is missing selection evidence: {value}")


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
        f"missing required Phase 5 file: {path}"
        for path in REQUIRED_FILES
        if not (ROOT / path).is_file()
    ]
    if not errors:
        _validate_config(errors)
        _validate_feature_boundary(errors)
        _validate_final_guard(errors)
        _validate_docs(errors)
        _validate_artifact_boundary(errors)
    if errors:
        print("Phase 5 validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Phase 5 repository validation passed: selection frozen, final-test guard enforced.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
