"""Frozen configuration contract for Phase 4 baselines."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class BaselineConfig:
    """Reviewed Phase 4 baseline parameters."""

    schema_version: str
    baseline_version: str
    random_seed: int
    batch_size: int
    binary_threshold: float


def load_baseline_config(path: Path) -> BaselineConfig:
    """Load the baseline contract and reject unreviewed algorithm changes."""

    raw: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("baseline config must contain a JSON object")
    mapping: dict[str, Any] = raw
    expected = {
        "binary_dummy_strategy": "training_prior",
        "attack_family_strategy": "training_prior",
        "headline_split": "validation",
        "final_test_policy": "sealed_not_evaluated",
    }
    for key, value in expected.items():
        if mapping.get(key) != value:
            raise ValueError(f"baseline config {key} must be {value!r}")
    logistic = mapping.get("binary_logistic")
    expected_logistic = {
        "estimator": "SGDClassifier",
        "loss": "log_loss",
        "penalty": "l2",
        "alpha": 0.0001,
        "learning_rate": "optimal",
        "average": True,
        "shuffle": False,
        "class_weighting": "balanced_from_training_support",
        "epochs": 1,
    }
    if logistic != expected_logistic:
        raise ValueError("baseline config binary_logistic parameters have drifted")
    seed = mapping.get("random_seed")
    batch_size = mapping.get("batch_size")
    threshold = mapping.get("binary_threshold")
    if not isinstance(seed, int) or seed < 0:
        raise ValueError("baseline random_seed must be a non-negative integer")
    if not isinstance(batch_size, int) or batch_size < 1:
        raise ValueError("baseline batch_size must be positive")
    if not isinstance(threshold, (int, float)) or not 0.0 < float(threshold) < 1.0:
        raise ValueError("baseline binary_threshold must be between zero and one")
    return BaselineConfig(
        schema_version=_string(mapping, "schema_version"),
        baseline_version=_string(mapping, "baseline_version"),
        random_seed=seed,
        batch_size=batch_size,
        binary_threshold=float(threshold),
    )


def _string(mapping: dict[str, Any], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"baseline config field {key!r} must be a non-empty string")
    return value
