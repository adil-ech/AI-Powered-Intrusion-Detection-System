"""Reproducible streaming baselines for binary and attack-family targets."""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray
from sklearn.linear_model import SGDClassifier
from sklearn.preprocessing import StandardScaler

from ids_ml.evaluation.data import iter_processed_batches


@dataclass(frozen=True)
class PriorBinaryModel:
    """A deterministic class-prior binary dummy baseline."""

    malicious_probability: float

    def predict_proba(self, features: NDArray[np.float64]) -> NDArray[np.float64]:
        positive = np.full(features.shape[0], self.malicious_probability, dtype=np.float64)
        return np.column_stack((1.0 - positive, positive))


@dataclass(frozen=True)
class PriorFamilyModel:
    """A deterministic class-prior attack-family baseline."""

    labels: tuple[str, ...]
    probabilities: tuple[float, ...]

    def predict_proba(self, features: NDArray[np.float64]) -> NDArray[np.float64]:
        row = np.asarray(self.probabilities, dtype=np.float64)
        return np.repeat(row[np.newaxis, :], features.shape[0], axis=0)


@dataclass
class LogisticBaselineModel:
    """Standardized logistic-loss SGD model suitable for large frozen splits."""

    scaler: StandardScaler
    classifier: SGDClassifier

    def predict_proba(self, features: NDArray[np.float64]) -> NDArray[np.float64]:
        transformed = self.scaler.transform(features)
        return np.asarray(self.classifier.predict_proba(transformed), dtype=np.float64)


@dataclass
class BaselineBundle:
    """Serialized Phase 4 baseline artifact."""

    schema_version: str
    random_seed: int
    required_features: tuple[str, ...]
    attack_labels: tuple[str, ...]
    binary_dummy: PriorBinaryModel
    binary_logistic: LogisticBaselineModel
    attack_family_prior: PriorFamilyModel


def fit_baselines(
    train_path: Path,
    required_features: list[str],
    attack_labels: list[str],
    *,
    random_seed: int,
    batch_size: int,
) -> tuple[BaselineBundle, dict[str, Any]]:
    """Fit all Phase 4 baselines without loading the full split into memory."""

    scaler = StandardScaler()
    binary_counts: Counter[int] = Counter()
    family_counts: Counter[str] = Counter()
    scan_started = time.perf_counter()
    for batch in iter_processed_batches(train_path, required_features, batch_size=batch_size):
        scaler.partial_fit(batch.features)
        binary_counts.update(int(value) for value in batch.binary_targets)
        family_counts.update(
            str(category)
            for category, target in zip(batch.categories, batch.binary_targets, strict=True)
            if target == 1
        )
    scan_seconds = time.perf_counter() - scan_started
    if set(binary_counts) != {0, 1}:
        raise ValueError("binary training split must contain benign and malicious rows")
    unknown_families = sorted(set(family_counts) - set(attack_labels))
    if unknown_families:
        raise ValueError(f"training split contains unknown attack families: {unknown_families}")
    total_rows = sum(binary_counts.values())
    malicious_rows = binary_counts[1]
    dummy = PriorBinaryModel(malicious_probability=malicious_rows / total_rows)
    family_total = sum(family_counts.values())
    family_probabilities = tuple(family_counts[label] / family_total for label in attack_labels)
    family_prior = PriorFamilyModel(labels=tuple(attack_labels), probabilities=family_probabilities)

    classifier = SGDClassifier(
        loss="log_loss",
        penalty="l2",
        alpha=0.0001,
        learning_rate="optimal",
        average=True,
        fit_intercept=True,
        shuffle=False,
        random_state=random_seed,
        max_iter=1,
        tol=None,
    )
    class_weights = {label: total_rows / (2.0 * binary_counts[label]) for label in (0, 1)}
    update_started = time.perf_counter()
    first_batch = True
    for batch in iter_processed_batches(train_path, required_features, batch_size=batch_size):
        transformed = scaler.transform(batch.features)
        weights = np.asarray(
            [class_weights[int(target)] for target in batch.binary_targets],
            dtype=np.float64,
        )
        if first_batch:
            classifier.partial_fit(
                transformed,
                batch.binary_targets,
                classes=np.asarray([0, 1], dtype=np.int64),
                sample_weight=weights,
            )
            first_batch = False
        else:
            classifier.partial_fit(transformed, batch.binary_targets, sample_weight=weights)
    update_seconds = time.perf_counter() - update_started
    bundle = BaselineBundle(
        schema_version="1.0.0",
        random_seed=random_seed,
        required_features=tuple(required_features),
        attack_labels=tuple(attack_labels),
        binary_dummy=dummy,
        binary_logistic=LogisticBaselineModel(
            scaler=scaler,
            classifier=classifier,
        ),
        attack_family_prior=family_prior,
    )
    details: dict[str, Any] = {
        "train_rows": total_rows,
        "binary_support": {
            "benign": binary_counts[0],
            "malicious": binary_counts[1],
        },
        "attack_family_support": {label: family_counts[label] for label in attack_labels},
        "class_weights": {str(label): weight for label, weight in class_weights.items()},
        "training_seconds": {
            "shared_scaler_and_prior_scan": scan_seconds,
            "binary_dummy": scan_seconds,
            "binary_logistic": scan_seconds + update_seconds,
            "attack_family_prior": scan_seconds,
            "logistic_update_only": update_seconds,
        },
    }
    return bundle, details
