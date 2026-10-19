"""Random Forest tuning, calibration, thresholding, and feature-variant selection."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression

from ids_ml.evaluation.metrics import evaluate_binary, evaluate_multiclass
from ids_ml.modeling.config import (
    ForestCandidate,
    ModelSelectionConfig,
    VariantPolicy,
)


def _logit(probability: NDArray[np.float64]) -> NDArray[np.float64]:
    clipped = np.clip(probability, 1e-8, 1.0 - 1e-8)
    return np.log(clipped / (1.0 - clipped))


@dataclass
class BinaryPlattCalibrator:
    """Sigmoid calibration over a frozen forest's positive-class score."""

    base_model: RandomForestClassifier
    calibrator: LogisticRegression
    classes_: NDArray[np.int64]

    def predict_proba(self, features: NDArray[np.float32]) -> NDArray[np.float64]:
        raw = np.asarray(self.base_model.predict_proba(features)[:, 1], dtype=np.float64)
        return np.asarray(self.calibrator.predict_proba(_logit(raw).reshape(-1, 1)))


@dataclass
class MulticlassTemperatureCalibrator:
    """One-temperature probability calibration that retains absent contract columns."""

    base_model: RandomForestClassifier
    temperature: float
    classes_: NDArray[np.int64]

    def predict_proba(self, features: NDArray[np.float32]) -> NDArray[np.float64]:
        raw = np.asarray(self.base_model.predict_proba(features), dtype=np.float64)
        logits = np.log(np.clip(raw, 1e-12, 1.0)) / self.temperature
        logits -= np.max(logits, axis=1, keepdims=True)
        exponentiated = np.exp(logits)
        return exponentiated / np.sum(exponentiated, axis=1, keepdims=True)


def build_forest(candidate: ForestCandidate, *, random_seed: int) -> RandomForestClassifier:
    """Build a deterministic, class-weighted production candidate."""

    return RandomForestClassifier(
        n_estimators=candidate.n_estimators,
        max_depth=candidate.max_depth,
        min_samples_leaf=candidate.min_samples_leaf,
        max_features=candidate.max_features,
        max_samples=candidate.max_samples,
        class_weight="balanced_subsample",
        n_jobs=-1,
        random_state=random_seed,
    )


def _family_probabilities(
    model: Any,
    features: NDArray[np.float32],
    label_count: int,
) -> NDArray[np.float64]:
    raw = np.asarray(model.predict_proba(features), dtype=np.float64)
    classes = np.asarray(model.classes_, dtype=np.int64)
    result = np.zeros((features.shape[0], label_count), dtype=np.float64)
    result[:, classes] = raw
    return result


def _family_targets(
    binary_targets: NDArray[np.uint8], category_ids: NDArray[np.int8]
) -> NDArray[np.int64]:
    malicious = binary_targets == 1
    targets = np.asarray(category_ids[malicious], dtype=np.int64) - 1
    if np.any(targets < 0):
        raise ValueError("malicious rows must map to an attack-family category")
    return targets


def tune_binary_forest(
    train_features: NDArray[np.float32],
    train_targets: NDArray[np.uint8],
    tuning_features: NDArray[np.float32],
    tuning_targets: NDArray[np.uint8],
    candidates: tuple[ForestCandidate, ...],
    *,
    random_seed: int,
) -> tuple[RandomForestClassifier, ForestCandidate, list[dict[str, Any]]]:
    """Select a binary forest using ranking metrics on the tuning fold only."""

    fitted: list[tuple[tuple[float, float, float], RandomForestClassifier, ForestCandidate]] = []
    reports: list[dict[str, Any]] = []
    for candidate in candidates:
        model = build_forest(candidate, random_seed=random_seed)
        started = time.perf_counter()
        model.fit(train_features, train_targets)
        training_seconds = time.perf_counter() - started
        probabilities = np.asarray(model.predict_proba(tuning_features)[:, 1], dtype=np.float64)
        metrics = evaluate_binary(
            np.asarray(tuning_targets, dtype=np.int64),
            probabilities,
            threshold=0.5,
            split="validation_tuning",
            model=candidate.candidate_id,
        )
        reports.append(
            {
                "candidate": asdict(candidate),
                "training_seconds": training_seconds,
                "metrics": metrics,
            }
        )
        fitted.append(
            (
                (float(metrics["pr_auc"]), float(metrics["f1"]), float(metrics["recall"])),
                model,
                candidate,
            )
        )
    _, model, candidate = max(fitted, key=lambda item: (item[0], item[2].candidate_id))
    return model, candidate, reports


def tune_family_forest(
    train_features: NDArray[np.float32],
    train_binary: NDArray[np.uint8],
    train_categories: NDArray[np.int8],
    tuning_features: NDArray[np.float32],
    tuning_binary: NDArray[np.uint8],
    tuning_categories: NDArray[np.int8],
    candidates: tuple[ForestCandidate, ...],
    attack_labels: list[str],
    *,
    random_seed: int,
) -> tuple[RandomForestClassifier, ForestCandidate, list[dict[str, Any]]]:
    """Select an attack-family forest on malicious tuning rows only."""

    train_malicious = train_binary == 1
    tuning_malicious = tuning_binary == 1
    train_targets = _family_targets(train_binary, train_categories)
    tuning_targets = _family_targets(tuning_binary, tuning_categories)
    target_names = np.asarray(attack_labels, dtype=np.str_)[tuning_targets]
    fitted: list[tuple[tuple[float, float], RandomForestClassifier, ForestCandidate]] = []
    reports: list[dict[str, Any]] = []
    for candidate in candidates:
        model = build_forest(candidate, random_seed=random_seed)
        started = time.perf_counter()
        model.fit(train_features[train_malicious], train_targets)
        training_seconds = time.perf_counter() - started
        probabilities = _family_probabilities(
            model, tuning_features[tuning_malicious], len(attack_labels)
        )
        metrics = evaluate_multiclass(
            target_names,
            probabilities,
            labels=attack_labels,
            split="validation_tuning_malicious_rows",
            model=candidate.candidate_id,
        )
        reports.append(
            {
                "candidate": asdict(candidate),
                "training_seconds": training_seconds,
                "metrics": metrics,
            }
        )
        fitted.append(
            (
                (float(metrics["macro_f1"]), float(metrics["weighted_f1"])),
                model,
                candidate,
            )
        )
    _, model, candidate = max(fitted, key=lambda item: (item[0], item[2].candidate_id))
    return model, candidate, reports


def calibrate_binary(
    model: RandomForestClassifier,
    features: NDArray[np.float32],
    targets: NDArray[np.uint8],
) -> BinaryPlattCalibrator:
    raw = np.asarray(model.predict_proba(features)[:, 1], dtype=np.float64)
    calibrator = LogisticRegression(
        C=1_000_000.0,
        solver="lbfgs",
        max_iter=1000,
        random_state=0,
    )
    calibrator.fit(_logit(raw).reshape(-1, 1), targets)
    return BinaryPlattCalibrator(
        base_model=model,
        calibrator=calibrator,
        classes_=np.asarray([0, 1], dtype=np.int64),
    )


def calibrate_family(
    model: RandomForestClassifier,
    features: NDArray[np.float32],
    binary_targets: NDArray[np.uint8],
    category_ids: NDArray[np.int8],
) -> MulticlassTemperatureCalibrator:
    malicious = binary_targets == 1
    targets = _family_targets(binary_targets, category_ids)
    raw = np.asarray(model.predict_proba(features[malicious]), dtype=np.float64)
    if raw.shape[1] != model.classes_.size:
        raise ValueError("family forest probability columns do not match its classes")
    temperatures = np.linspace(0.25, 4.0, 301, dtype=np.float64)
    losses: list[float] = []
    clipped = np.clip(raw, 1e-12, 1.0)
    for temperature in temperatures:
        logits = np.log(clipped) / temperature
        logits -= np.max(logits, axis=1, keepdims=True)
        probability = np.exp(logits)
        probability /= np.sum(probability, axis=1, keepdims=True)
        losses.append(
            float(
                -np.mean(np.log(np.clip(probability[np.arange(targets.size), targets], 1e-15, 1.0)))
            )
        )
    best = int(np.argmin(np.asarray(losses)))
    return MulticlassTemperatureCalibrator(
        base_model=model,
        temperature=float(temperatures[best]),
        classes_=np.asarray(model.classes_, dtype=np.int64),
    )


def select_binary_threshold(
    targets: NDArray[np.uint8],
    probabilities: NDArray[np.float64],
    config: ModelSelectionConfig,
    *,
    split: str,
    model: str,
) -> tuple[float, dict[str, Any]]:
    """Maximize recall under the frozen false-positive constraint."""

    search = config.threshold_search
    thresholds = np.arange(
        search.minimum,
        search.maximum + search.step / 2.0,
        search.step,
        dtype=np.float64,
    )
    candidates: list[dict[str, Any]] = []
    integer_targets = np.asarray(targets, dtype=np.int64)
    for threshold in thresholds:
        metrics = evaluate_binary(
            integer_targets,
            probabilities,
            threshold=float(round(float(threshold), 6)),
            split=split,
            model=model,
        )
        false_positive_rate = metrics["false_positive_rate"]
        if (
            false_positive_rate is not None
            and float(false_positive_rate) <= search.maximum_false_positive_rate
        ):
            candidates.append(metrics)
    if not candidates:
        raise ValueError("no threshold satisfies the false-positive-rate constraint")
    selected = max(
        candidates,
        key=lambda item: (
            float(item["recall"]),
            float(item["f1"]),
            float(item["precision"]),
            float(item["threshold"]),
        ),
    )
    return float(selected["threshold"]), selected


def evaluate_selected_models(
    binary_model: Any,
    family_model: Any,
    features: NDArray[np.float32],
    binary_targets: NDArray[np.uint8],
    category_ids: NDArray[np.int8],
    attack_labels: list[str],
    *,
    threshold: float,
    split: str,
    variant: str,
) -> dict[str, Any]:
    binary_probabilities = np.asarray(binary_model.predict_proba(features)[:, 1], dtype=np.float64)
    malicious = binary_targets == 1
    family_probabilities = _family_probabilities(
        family_model, features[malicious], len(attack_labels)
    )
    family_targets = np.asarray(attack_labels, dtype=np.str_)[
        _family_targets(binary_targets, category_ids)
    ]
    return {
        "feature_variant": variant,
        "binary": evaluate_binary(
            np.asarray(binary_targets, dtype=np.int64),
            binary_probabilities,
            threshold=threshold,
            split=split,
            model=f"random_forest_binary:{variant}",
        ),
        "attack_family": evaluate_multiclass(
            family_targets,
            family_probabilities,
            labels=attack_labels,
            split=f"{split}_malicious_rows",
            model=f"random_forest_attack_family:{variant}",
        ),
    }


def choose_feature_variant(
    without_port: dict[str, Any],
    with_port: dict[str, Any],
    policy: VariantPolicy,
) -> tuple[str, dict[str, Any]]:
    """Apply the preregistered conservative destination-port policy."""

    base_binary = without_port["binary"]
    port_binary = with_port["binary"]
    base_family = without_port["attack_family"]
    port_family = with_port["attack_family"]
    family_gain = float(port_family["macro_f1"]) - float(base_family["macro_f1"])
    binary_regression = float(base_binary["f1"]) - float(port_binary["f1"])
    observed_labels = [
        label for label, support in base_family["support"].items() if int(support) > 0
    ]
    recall_regressions = {
        label: float(base_family["per_class"][label]["recall"])
        - float(port_family["per_class"][label]["recall"])
        for label in observed_labels
    }
    maximum_recall_regression = max(recall_regressions.values(), default=0.0)
    port_qualifies = (
        family_gain >= policy.minimum_family_macro_f1_gain
        and binary_regression <= policy.maximum_binary_f1_regression
        and maximum_recall_regression <= policy.maximum_per_class_recall_regression
    )
    selected = "with_destination_port" if port_qualifies else "without_destination_port"
    return selected, {
        "selected": selected,
        "port_qualifies": port_qualifies,
        "family_macro_f1_gain": family_gain,
        "binary_f1_regression": binary_regression,
        "per_class_recall_regression": recall_regressions,
        "maximum_per_class_recall_regression": maximum_recall_regression,
        "policy": asdict(policy),
        "reason": (
            "destination_port met every preregistered improvement and regression bound"
            if port_qualifies
            else "destination_port did not justify its CIC lab-layout leakage risk"
        ),
    }
