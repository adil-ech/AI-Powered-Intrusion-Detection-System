"""Stable, explicit metric calculations shared by every model."""

from __future__ import annotations

from typing import Any

import numpy as np
from numpy.typing import NDArray
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    log_loss,
    precision_recall_fscore_support,
    precision_score,
    recall_score,
    roc_auc_score,
)


def _safe_ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _validate_probabilities(probabilities: NDArray[np.float64]) -> None:
    if probabilities.ndim != 1:
        raise ValueError("binary probabilities must be one-dimensional")
    if not np.all(np.isfinite(probabilities)):
        raise ValueError("probabilities must be finite")
    if np.any((probabilities < 0.0) | (probabilities > 1.0)):
        raise ValueError("probabilities must be between zero and one")


def reliability_bins(
    outcomes: NDArray[np.float64],
    probabilities: NDArray[np.float64],
    *,
    bin_count: int = 10,
) -> list[dict[str, float | int | None]]:
    """Return fixed confidence buckets, including explicit empty bins."""

    if bin_count < 1:
        raise ValueError("bin_count must be positive")
    if outcomes.shape != probabilities.shape:
        raise ValueError("outcomes and probabilities must have equal shape")
    _validate_probabilities(probabilities)
    indexes = np.minimum((probabilities * bin_count).astype(np.int64), bin_count - 1)
    result: list[dict[str, float | int | None]] = []
    for index in range(bin_count):
        mask = indexes == index
        count = int(np.count_nonzero(mask))
        result.append(
            {
                "lower": index / bin_count,
                "upper": (index + 1) / bin_count,
                "count": count,
                "mean_probability": float(np.mean(probabilities[mask])) if count else None,
                "observed_frequency": float(np.mean(outcomes[mask])) if count else None,
            }
        )
    return result


def evaluate_binary(
    targets: NDArray[np.int64],
    probabilities: NDArray[np.float64],
    *,
    threshold: float,
    split: str,
    model: str,
) -> dict[str, Any]:
    """Evaluate malicious-class behavior without hiding absent denominators."""

    if targets.ndim != 1 or targets.shape != probabilities.shape:
        raise ValueError("binary targets and probabilities must be aligned vectors")
    if not 0.0 < threshold < 1.0:
        raise ValueError("threshold must be strictly between zero and one")
    if np.any((targets != 0) & (targets != 1)):
        raise ValueError("binary targets must contain only zero and one")
    _validate_probabilities(probabilities)
    predictions = (probabilities >= threshold).astype(np.int64)
    matrix = confusion_matrix(targets, predictions, labels=[0, 1])
    true_negative, false_positive, false_negative, true_positive = (
        int(value) for value in matrix.ravel()
    )
    benign_support = true_negative + false_positive
    malicious_support = true_positive + false_negative
    has_both_classes = benign_support > 0 and malicious_support > 0
    clipped = np.clip(probabilities, 1e-15, 1 - 1e-15)
    return {
        "model": model,
        "split": split,
        "threshold": threshold,
        "support": {
            "total": int(targets.size),
            "benign": benign_support,
            "malicious": malicious_support,
        },
        "precision": float(precision_score(targets, predictions, zero_division=0)),
        "recall": float(recall_score(targets, predictions, zero_division=0)),
        "f1": float(f1_score(targets, predictions, zero_division=0)),
        "accuracy_secondary": float(accuracy_score(targets, predictions)),
        "pr_auc": (
            float(average_precision_score(targets, probabilities)) if has_both_classes else None
        ),
        "roc_auc": float(roc_auc_score(targets, probabilities)) if has_both_classes else None,
        "false_positive_rate": _safe_ratio(false_positive, benign_support),
        "false_negative_rate": _safe_ratio(false_negative, malicious_support),
        "confusion_matrix": {
            "labels": [0, 1],
            "values": matrix.astype(int).tolist(),
            "true_negative": true_negative,
            "false_positive": false_positive,
            "false_negative": false_negative,
            "true_positive": true_positive,
        },
        "calibration": {
            "brier_score": float(brier_score_loss(targets, probabilities)),
            "log_loss": float(log_loss(targets, clipped, labels=[0, 1])),
            "reliability_bins": reliability_bins(targets.astype(np.float64), probabilities),
        },
    }


def evaluate_multiclass(
    targets: NDArray[np.str_],
    probabilities: NDArray[np.float64],
    *,
    labels: list[str],
    split: str,
    model: str,
) -> dict[str, Any]:
    """Evaluate attack families with stable label order and absent-class reporting."""

    if targets.ndim != 1 or probabilities.ndim != 2:
        raise ValueError("multiclass targets and probabilities have invalid dimensions")
    if probabilities.shape != (targets.size, len(labels)):
        raise ValueError("multiclass probability columns must match the label order")
    if not np.all(np.isfinite(probabilities)):
        raise ValueError("multiclass probabilities must be finite")
    if np.any(probabilities < 0.0) or not np.allclose(
        np.sum(probabilities, axis=1), 1.0, atol=1e-10
    ):
        raise ValueError("multiclass probabilities must be normalized")
    unknown = sorted(set(targets.tolist()) - set(labels))
    if unknown:
        raise ValueError(f"targets contain unknown attack categories: {unknown}")
    label_array = np.asarray(labels, dtype=np.str_)
    predictions = label_array[np.argmax(probabilities, axis=1)]
    precision, recall, f1, support = precision_recall_fscore_support(
        targets,
        predictions,
        labels=labels,
        zero_division=0,
    )
    observed_labels = [label for label, count in zip(labels, support, strict=True) if count]
    matrix = confusion_matrix(targets, predictions, labels=labels)
    one_hot = np.zeros_like(probabilities)
    label_indexes = {label: index for index, label in enumerate(labels)}
    target_indexes = np.asarray([label_indexes[str(target)] for target in targets], dtype=np.int64)
    one_hot[np.arange(targets.size), target_indexes] = 1.0
    confidence = np.max(probabilities, axis=1)
    correct = (predictions == targets).astype(np.float64)
    clipped = np.clip(probabilities, 1e-15, 1.0)
    return {
        "model": model,
        "split": split,
        "label_order": labels,
        "support": {label: int(value) for label, value in zip(labels, support, strict=True)},
        "macro_f1": float(
            f1_score(
                targets,
                predictions,
                labels=observed_labels,
                average="macro",
                zero_division=0,
            )
        ),
        "macro_f1_all_contract_classes": float(
            f1_score(
                targets,
                predictions,
                labels=labels,
                average="macro",
                zero_division=0,
            )
        ),
        "weighted_f1": float(
            f1_score(
                targets,
                predictions,
                labels=labels,
                average="weighted",
                zero_division=0,
            )
        ),
        "accuracy_secondary": float(accuracy_score(targets, predictions)),
        "per_class": {
            label: {
                "precision": float(precision[index]),
                "recall": float(recall[index]),
                "f1": float(f1[index]),
                "support": int(support[index]),
            }
            for index, label in enumerate(labels)
        },
        "confusion_matrix": {
            "labels": labels,
            "values": matrix.astype(int).tolist(),
        },
        "calibration": {
            "log_loss": float(-np.mean(np.log(clipped[np.arange(targets.size), target_indexes]))),
            "multiclass_brier_score": float(
                np.mean(np.sum((probabilities - one_hot) ** 2, axis=1))
            ),
            "confidence_reliability_bins": reliability_bins(correct, confidence),
        },
    }
