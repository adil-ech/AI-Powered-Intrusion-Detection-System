"""Loading and applying the versioned attack-family taxonomy."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ids_ml.data.schema import normalize_label


@dataclass(frozen=True)
class LabelTarget:
    """Product category and binary target for one normalized source label."""

    category: str
    is_malicious: int


@dataclass(frozen=True)
class LabelTaxonomy:
    """Validated, closed-world mapping used by training and evaluation."""

    schema_version: str
    categories: tuple[str, ...]
    targets: dict[str, LabelTarget]

    def map(self, source_label: str) -> tuple[str, LabelTarget]:
        normalized = normalize_label(source_label)
        target = self.targets.get(normalized)
        if target is None:
            raise ValueError(f"unrecognized source label: {normalized or '<empty>'}")
        return normalized, target


def _require_string(mapping: dict[str, Any], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"label contract field {key!r} must be a non-empty string")
    return value


def load_taxonomy(path: Path) -> LabelTaxonomy:
    """Load a label contract and reject ambiguous or incomplete mappings."""

    raw: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("label contract must contain a JSON object")
    mapping: dict[str, Any] = raw
    categories_raw = mapping.get("categories")
    if not isinstance(categories_raw, list) or not categories_raw:
        raise ValueError("label contract must define a non-empty categories list")

    categories: list[str] = []
    targets: dict[str, LabelTarget] = {}
    for index, item in enumerate(categories_raw):
        if not isinstance(item, dict):
            raise ValueError(f"label category {index} must be an object")
        category = _require_string(item, "name")
        binary_target = _require_string(item, "binary_target")
        if binary_target not in {"benign", "malicious"}:
            raise ValueError(f"category {category} has invalid binary_target {binary_target!r}")
        source_labels = item.get("source_labels")
        if not isinstance(source_labels, list) or not source_labels:
            raise ValueError(f"category {category} must define source_labels")
        if category in categories:
            raise ValueError(f"duplicate category: {category}")
        categories.append(category)
        for source_label in source_labels:
            if not isinstance(source_label, str):
                raise ValueError(f"category {category} contains a non-string source label")
            normalized = normalize_label(source_label)
            if normalized in targets:
                raise ValueError(f"source label appears in multiple categories: {normalized}")
            targets[normalized] = LabelTarget(
                category=category,
                is_malicious=int(binary_target == "malicious"),
            )

    return LabelTaxonomy(
        schema_version=_require_string(mapping, "schema_version"),
        categories=tuple(categories),
        targets=targets,
    )
