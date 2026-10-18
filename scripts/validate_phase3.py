#!/usr/bin/env python3
"""Validate committed Phase 3 preprocessing contracts without the raw dataset."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_FILES = (
    "configs/preprocessing-v1.json",
    "contracts/features-v1.json",
    "docs/data/preprocessing-v1.md",
    "ml/src/ids_ml/data/labels.py",
    "ml/src/ids_ml/data/preprocess.py",
    "ml/tests/test_preprocessing.py",
)
DIRECT_OR_LEAKAGE_FEATURES = {
    "label",
    "flow_id",
    "source_ip",
    "destination_ip",
    "timestamp",
    "source_port",
    "destination_port",
}


def _load_json(relative: str) -> dict[str, Any]:
    raw: object = json.loads((ROOT / relative).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{relative} must contain a JSON object")
    return raw


def _schema_hash(version: object, features: object) -> str:
    payload = {
        "feature_schema_version": version,
        "features": features,
    }
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def _validate_config(errors: list[str]) -> None:
    config = _load_json("configs/preprocessing-v1.json")
    ratios = config.get("split_basis_points")
    if not isinstance(ratios, dict) or set(ratios) != {
        "train",
        "validation",
        "final_test",
    }:
        errors.append("preprocessing config must define train, validation, and final_test")
    elif sum(value for value in ratios.values() if isinstance(value, int)) != 10_000:
        errors.append("preprocessing split basis points must total 10000")
    if config.get("group_size_rows") != 4096:
        errors.append("features-v1 must retain the reviewed 4096-row group size")
    if config.get("imputation_strategy") != "training_mean":
        errors.append("features-v1 must use the reviewed training_mean imputer")
    excluded = config.get("excluded_features")
    if not isinstance(excluded, dict) or not DIRECT_OR_LEAKAGE_FEATURES.issubset(excluded):
        errors.append("preprocessing config must exclude target, identifiers, and both ports")


def _validate_feature_contract(errors: list[str]) -> None:
    contract = _load_json("contracts/features-v1.json")
    required = contract.get("required_features")
    features = contract.get("features")
    if (
        not isinstance(required, list)
        or not required
        or not all(isinstance(item, str) for item in required)
    ):
        errors.append("feature contract must contain an ordered required_features list")
        return
    if len(required) != len(set(required)):
        errors.append("feature contract required_features must be unique")
    if len(required) != 63:
        errors.append(f"features-v1 must contain the reviewed 63 features, found {len(required)}")
    leakage = DIRECT_OR_LEAKAGE_FEATURES.intersection(required)
    if leakage:
        errors.append(f"feature contract contains excluded fields: {sorted(leakage)}")
    if not isinstance(features, list) or [item.get("name") for item in features] != required:
        errors.append("feature metadata order must exactly match required_features")
        return
    if any(
        item.get("dtype") != "float64" or item.get("missing_value_policy") != "training_mean"
        for item in features
    ):
        errors.append("every features-v1 entry must be float64 with training_mean imputation")
    expected_hash = _schema_hash(contract.get("feature_schema_version"), features)
    if contract.get("feature_schema_sha256") != expected_hash:
        errors.append("feature_schema_sha256 does not match the ordered feature metadata")
    transform = contract.get("transform")
    if not isinstance(transform, dict) or transform.get("fit_split") != "train":
        errors.append("feature transform must declare train as its only fit split")


def _validate_docs(errors: list[str]) -> None:
    text = (ROOT / "docs/data/preprocessing-v1.md").read_text(encoding="utf-8")
    required = (
        "make gate-3",
        "4096",
        "final-test",
        "RARE_OTHER",
        "destination_port",
        "35471c9144bcfe174a4d20e4122d3a673267cb5a7594b1283ae47224aa926152",
    )
    for value in required:
        if value not in text:
            errors.append(f"preprocessing guide is missing reviewed detail: {value}")


def main() -> int:
    errors = [
        f"missing required Phase 3 file: {path}"
        for path in REQUIRED_FILES
        if not (ROOT / path).is_file()
    ]
    if not errors:
        _validate_config(errors)
        _validate_feature_contract(errors)
        _validate_docs(errors)
    if errors:
        print("Phase 3 validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Phase 3 repository validation passed: 63 ordered features and train-only transforms.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
