"""Bounded-memory readers for frozen Phase 3 processed splits."""

from __future__ import annotations

import csv
import gzip
import json
import math
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True)
class EvaluationBatch:
    """One ordered feature batch with both product targets."""

    features: NDArray[np.float64]
    categories: NDArray[np.str_]
    binary_targets: NDArray[np.int64]


def load_required_features(path: Path) -> tuple[list[str], str]:
    """Load ordered features and the frozen schema hash."""

    raw: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("feature contract must contain a JSON object")
    mapping: dict[str, Any] = raw
    required = mapping.get("required_features")
    schema_hash = mapping.get("feature_schema_sha256")
    if (
        not isinstance(required, list)
        or not required
        or not all(isinstance(item, str) for item in required)
    ):
        raise ValueError("feature contract must define ordered required_features")
    if not isinstance(schema_hash, str) or len(schema_hash) != 64:
        raise ValueError("feature contract must define feature_schema_sha256")
    return [str(item) for item in required], schema_hash


def iter_processed_batches(
    path: Path,
    required_features: list[str],
    *,
    batch_size: int,
) -> Iterator[EvaluationBatch]:
    """Yield finite, schema-checked NumPy batches from a compressed split."""

    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    expected_header = [*required_features, "category", "is_malicious"]
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader, None)
        if header != expected_header:
            raise ValueError(f"processed split header does not match the feature contract: {path}")
        feature_rows: list[list[float]] = []
        categories: list[str] = []
        binary_targets: list[int] = []
        for row_number, row in enumerate(reader, start=2):
            if len(row) != len(expected_header):
                raise ValueError(f"processed row width mismatch at {path.name}:{row_number}")
            try:
                values = [float(value) for value in row[: len(required_features)]]
            except ValueError as error:
                raise ValueError(
                    f"invalid processed feature at {path.name}:{row_number}"
                ) from error
            if not all(math.isfinite(value) for value in values):
                raise ValueError(f"non-finite processed feature at {path.name}:{row_number}")
            try:
                binary_target = int(row[-1])
            except ValueError as error:
                raise ValueError(f"invalid binary target at {path.name}:{row_number}") from error
            if binary_target not in {0, 1}:
                raise ValueError(f"binary target must be 0 or 1 at {path.name}:{row_number}")
            feature_rows.append(values)
            categories.append(row[-2])
            binary_targets.append(binary_target)
            if len(feature_rows) == batch_size:
                yield _build_batch(feature_rows, categories, binary_targets)
                feature_rows, categories, binary_targets = [], [], []
        if feature_rows:
            yield _build_batch(feature_rows, categories, binary_targets)


def _build_batch(
    feature_rows: list[list[float]], categories: list[str], binary_targets: list[int]
) -> EvaluationBatch:
    return EvaluationBatch(
        features=np.asarray(feature_rows, dtype=np.float64),
        categories=np.asarray(categories, dtype=np.str_),
        binary_targets=np.asarray(binary_targets, dtype=np.int64),
    )
