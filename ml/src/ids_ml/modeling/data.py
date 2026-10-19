"""Memory-bounded materialization and group-aware validation partitions."""

from __future__ import annotations

import json
import warnings
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import numpy as np
from numpy.typing import NDArray
from sklearn.model_selection import StratifiedGroupKFold

from ids_ml.evaluation.data import iter_processed_batches


@dataclass(frozen=True)
class MaterializedSplit:
    features: NDArray[np.float32]
    binary_targets: NDArray[np.uint8]
    category_ids: NDArray[np.int8]


@dataclass(frozen=True)
class ValidationPartitions:
    tuning: NDArray[np.int64]
    calibration: NDArray[np.int64]
    selection: NDArray[np.int64]
    report: dict[str, Any]


def materialize_split(
    path: Path,
    required_features: list[str],
    categories: list[str],
    *,
    rows: int,
    batch_size: int,
    directory: Path,
    name: str,
) -> MaterializedSplit:
    """Convert a compressed split to typed temporary memory maps."""

    feature_array = np.memmap(
        directory / f"{name}-features.dat",
        mode="w+",
        dtype=np.float32,
        shape=(rows, len(required_features)),
    )
    binary_array = np.memmap(
        directory / f"{name}-binary.dat", mode="w+", dtype=np.uint8, shape=(rows,)
    )
    category_array = np.memmap(
        directory / f"{name}-category.dat", mode="w+", dtype=np.int8, shape=(rows,)
    )
    category_indexes = {category: index for index, category in enumerate(categories)}
    offset = 0
    for batch in iter_processed_batches(path, required_features, batch_size=batch_size):
        end = offset + batch.features.shape[0]
        if end > rows:
            raise ValueError(f"{path} contains more rows than its manifest")
        unknown = sorted(set(batch.categories.tolist()) - set(category_indexes))
        if unknown:
            raise ValueError(f"{path} contains unknown categories: {unknown}")
        feature_array[offset:end] = batch.features
        binary_array[offset:end] = batch.binary_targets
        category_array[offset:end] = [
            category_indexes[str(category)] for category in batch.categories
        ]
        offset = end
    if offset != rows:
        raise ValueError(f"{path} row count differs from its manifest: {offset} != {rows}")
    feature_array.flush()
    binary_array.flush()
    category_array.flush()
    return MaterializedSplit(feature_array, binary_array, category_array)


def _load_manifest(path: Path) -> dict[str, Any]:
    raw: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("split manifest must contain a JSON object")
    return raw


def build_validation_partitions(
    split_manifest_path: Path,
    category_ids: NDArray[np.int8],
    categories: list[str],
    *,
    random_seed: int,
    fold_count: int,
) -> ValidationPartitions:
    """Create disjoint tuning/calibration/selection folds from complete source groups."""

    manifest = _load_manifest(split_manifest_path)
    groups_raw = manifest.get("groups")
    if not isinstance(groups_raw, list):
        raise ValueError("split manifest must include group records")
    validation_groups = sorted(
        (
            cast(dict[str, Any], group)
            for group in groups_raw
            if isinstance(group, dict) and group.get("split") == "validation"
        ),
        # Phase 3 emits rows while iterating lexically sorted source paths, then
        # monotonically increasing windows within each source file. The manifest
        # itself is sorted by group ID, so reconstruct the writer order here.
        key=lambda group: (str(group["source_path"]), str(group["group_id"])),
    )
    row_groups = np.empty(category_ids.size, dtype=np.int32)
    group_ids: list[str] = []
    offset = 0
    for group_index, group in enumerate(validation_groups):
        rows = group.get("rows")
        support = group.get("category_support")
        if not isinstance(rows, int) or rows < 1 or not isinstance(support, dict):
            raise ValueError("validation group metadata is invalid")
        end = offset + rows
        if end > category_ids.size:
            raise ValueError("validation group rows exceed the processed validation split")
        actual = Counter(
            categories[int(category)] for category in category_ids[offset:end].tolist()
        )
        expected = Counter({str(key): int(value) for key, value in support.items()})
        if actual != expected:
            raise ValueError(
                "processed validation row order no longer matches the frozen group manifest"
            )
        row_groups[offset:end] = group_index
        group_ids.append(str(group["group_id"]))
        offset = end
    if offset != category_ids.size:
        raise ValueError("validation group rows do not cover the processed validation split")

    splitter = StratifiedGroupKFold(
        n_splits=fold_count,
        shuffle=True,
        random_state=random_seed,
    )
    placeholder = np.zeros((category_ids.size, 1), dtype=np.uint8)
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="The least populated class in y has only 1 members",
            category=UserWarning,
        )
        folds = [
            np.asarray(test_indexes, dtype=np.int64)
            for _, test_indexes in splitter.split(placeholder, category_ids, row_groups)
        ]
    infiltration_index = categories.index("INFILTRATION")
    calibration_fold = next(
        (
            index
            for index, indexes in enumerate(folds)
            if np.any(category_ids[indexes] == infiltration_index)
        ),
        1,
    )
    remaining = [index for index in range(fold_count) if index != calibration_fold]
    tuning_fold, selection_fold = remaining
    named = {
        "tuning": folds[tuning_fold],
        "calibration": folds[calibration_fold],
        "selection": folds[selection_fold],
    }
    assigned_groups: dict[str, set[int]] = {
        name: set(row_groups[indexes].tolist()) for name, indexes in named.items()
    }
    if (
        assigned_groups["tuning"] & assigned_groups["calibration"]
        or assigned_groups["tuning"] & assigned_groups["selection"]
        or assigned_groups["calibration"] & assigned_groups["selection"]
    ):
        raise AssertionError("validation source groups crossed selection partitions")
    report: dict[str, Any] = {}
    for name, indexes in named.items():
        support = Counter(categories[int(value)] for value in category_ids[indexes].tolist())
        report[name] = {
            "rows": int(indexes.size),
            "groups": len(assigned_groups[name]),
            "group_ids_sha256": _group_id_hash(
                [group_ids[index] for index in sorted(assigned_groups[name])]
            ),
            "category_support": {category: support[category] for category in categories},
        }
    return ValidationPartitions(
        tuning=named["tuning"],
        calibration=named["calibration"],
        selection=named["selection"],
        report=report,
    )


def _group_id_hash(group_ids: list[str]) -> str:
    import hashlib

    payload = "\n".join(group_ids).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
