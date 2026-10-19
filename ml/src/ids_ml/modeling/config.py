"""Validated configuration for Phase 5 model selection."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal


@dataclass(frozen=True)
class ForestCandidate:
    """One bounded Random Forest candidate."""

    candidate_id: str
    n_estimators: int
    max_depth: int
    min_samples_leaf: int
    max_features: str
    max_samples: float


@dataclass(frozen=True)
class ThresholdSearch:
    minimum: float
    maximum: float
    step: float
    maximum_false_positive_rate: float


@dataclass(frozen=True)
class AcceptanceTargets:
    minimum_binary_recall: float
    maximum_binary_false_positive_rate: float
    minimum_family_macro_f1: float


@dataclass(frozen=True)
class VariantPolicy:
    minimum_family_macro_f1_gain: float
    maximum_binary_f1_regression: float
    maximum_per_class_recall_regression: float


@dataclass(frozen=True)
class FrozenSelection:
    feature_variant: Literal["without_destination_port", "with_destination_port"]
    binary_candidate: str
    family_candidate: str


@dataclass(frozen=True)
class ModelSelectionConfig:
    schema_version: str
    model_version: str
    random_seed: int
    batch_size: int
    validation_folds: int
    calibration_method: str
    binary_candidates: tuple[ForestCandidate, ...]
    family_candidates: tuple[ForestCandidate, ...]
    threshold_search: ThresholdSearch
    acceptance: AcceptanceTargets
    variant_policy: VariantPolicy
    low_confidence_threshold: float
    high_risk_threshold: float
    selection_frozen: bool
    frozen_selection: FrozenSelection | None


def _mapping(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    return value


def _probability(mapping: dict[str, Any], field: str) -> float:
    value = mapping.get(field)
    if not isinstance(value, (int, float)) or not 0.0 <= float(value) <= 1.0:
        raise ValueError(f"{field} must be between zero and one")
    return float(value)


def _candidate(value: object) -> ForestCandidate:
    mapping = _mapping(value, "forest candidate")
    identifier = mapping.get("id")
    max_features = mapping.get("max_features")
    integers = ("n_estimators", "max_depth", "min_samples_leaf")
    if not isinstance(identifier, str) or not identifier:
        raise ValueError("forest candidate id must be a non-empty string")
    if max_features != "sqrt":
        raise ValueError("Phase 5 forest candidates must use max_features='sqrt'")
    if not all(isinstance(mapping.get(field), int) and mapping[field] > 0 for field in integers):
        raise ValueError("forest size and depth fields must be positive integers")
    max_samples = mapping.get("max_samples")
    if not isinstance(max_samples, (int, float)) or not 0.0 < float(max_samples) <= 1.0:
        raise ValueError("forest max_samples must be in (0, 1]")
    return ForestCandidate(
        candidate_id=identifier,
        n_estimators=int(mapping["n_estimators"]),
        max_depth=int(mapping["max_depth"]),
        min_samples_leaf=int(mapping["min_samples_leaf"]),
        max_features=max_features,
        max_samples=float(max_samples),
    )


def _candidate_list(value: object, field: str) -> tuple[ForestCandidate, ...]:
    if not isinstance(value, list) or len(value) < 2:
        raise ValueError(f"{field} must contain at least two candidates")
    candidates = tuple(_candidate(item) for item in value)
    identifiers = [item.candidate_id for item in candidates]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError(f"{field} candidate ids must be unique")
    return candidates


def load_model_selection_config(path: Path) -> ModelSelectionConfig:
    """Load the committed selection policy and reject ambiguous settings."""

    raw: object = json.loads(path.read_text(encoding="utf-8"))
    mapping = _mapping(raw, "model selection config")
    threshold = _mapping(mapping.get("threshold_search"), "threshold_search")
    acceptance = _mapping(mapping.get("acceptance"), "acceptance")
    variant = _mapping(mapping.get("feature_variant_policy"), "feature_variant_policy")
    confidence = _mapping(mapping.get("confidence_thresholds"), "confidence_thresholds")
    if threshold.get("objective") != "maximize_recall_then_f1":
        raise ValueError("unsupported threshold objective")
    if mapping.get("calibration_method") != "binary_platt_family_temperature":
        raise ValueError("Phase 5 calibration_method must be binary_platt_family_temperature")
    seed = mapping.get("random_seed")
    batch_size = mapping.get("batch_size")
    validation_folds = mapping.get("validation_folds")
    if not isinstance(seed, int) or seed < 0:
        raise ValueError("random_seed must be a non-negative integer")
    if not isinstance(batch_size, int) or batch_size < 1:
        raise ValueError("batch_size must be positive")
    if validation_folds != 3:
        raise ValueError("Phase 5 requires three group-aware validation folds")
    minimum = _probability(threshold, "minimum")
    maximum = _probability(threshold, "maximum")
    step = _probability(threshold, "step")
    if not 0.0 < minimum < maximum < 1.0 or step <= 0.0:
        raise ValueError("threshold search bounds are invalid")
    if variant.get("default") != "without_destination_port":
        raise ValueError("default feature variant must exclude destination_port")
    if variant.get("candidate") != "with_destination_port":
        raise ValueError("candidate feature variant must add destination_port")
    selection_frozen = mapping.get("selection_frozen")
    if not isinstance(selection_frozen, bool):
        raise ValueError("selection_frozen must be boolean")
    frozen_raw = mapping.get("frozen_selection")
    frozen: FrozenSelection | None = None
    if selection_frozen:
        frozen_mapping = _mapping(frozen_raw, "frozen_selection")
        feature_variant = frozen_mapping.get("feature_variant")
        if feature_variant not in {"without_destination_port", "with_destination_port"}:
            raise ValueError("frozen feature variant is invalid")
        binary_candidate = frozen_mapping.get("binary_candidate")
        family_candidate = frozen_mapping.get("family_candidate")
        if not isinstance(binary_candidate, str) or not isinstance(family_candidate, str):
            raise ValueError("frozen candidate ids must be strings")
        frozen = FrozenSelection(feature_variant, binary_candidate, family_candidate)
    elif frozen_raw is not None:
        raise ValueError("frozen_selection must be null until selection is frozen")
    binary_candidates = _candidate_list(mapping.get("binary_candidates"), "binary_candidates")
    family_candidates = _candidate_list(mapping.get("family_candidates"), "family_candidates")
    if frozen is not None:
        if frozen.binary_candidate not in {item.candidate_id for item in binary_candidates}:
            raise ValueError("frozen binary candidate is not configured")
        if frozen.family_candidate not in {item.candidate_id for item in family_candidates}:
            raise ValueError("frozen family candidate is not configured")
    schema_version = mapping.get("schema_version")
    model_version = mapping.get("model_version")
    if not isinstance(schema_version, str) or not isinstance(model_version, str):
        raise ValueError("schema_version and model_version must be strings")
    return ModelSelectionConfig(
        schema_version=schema_version,
        model_version=model_version,
        random_seed=seed,
        batch_size=batch_size,
        validation_folds=validation_folds,
        calibration_method="binary_platt_family_temperature",
        binary_candidates=binary_candidates,
        family_candidates=family_candidates,
        threshold_search=ThresholdSearch(
            minimum=minimum,
            maximum=maximum,
            step=step,
            maximum_false_positive_rate=_probability(threshold, "maximum_false_positive_rate"),
        ),
        acceptance=AcceptanceTargets(
            minimum_binary_recall=_probability(acceptance, "minimum_binary_recall"),
            maximum_binary_false_positive_rate=_probability(
                acceptance, "maximum_binary_false_positive_rate"
            ),
            minimum_family_macro_f1=_probability(acceptance, "minimum_family_macro_f1"),
        ),
        variant_policy=VariantPolicy(
            minimum_family_macro_f1_gain=_probability(variant, "minimum_family_macro_f1_gain"),
            maximum_binary_f1_regression=_probability(variant, "maximum_binary_f1_regression"),
            maximum_per_class_recall_regression=_probability(
                variant, "maximum_per_class_recall_regression"
            ),
        ),
        low_confidence_threshold=_probability(confidence, "low_confidence"),
        high_risk_threshold=_probability(confidence, "high_risk"),
        selection_frozen=selection_frozen,
        frozen_selection=frozen,
    )
