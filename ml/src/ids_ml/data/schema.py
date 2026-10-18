"""Deterministic source-name and source-value inspection helpers."""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter

NON_ALPHANUMERIC = re.compile(r"[^0-9A-Za-z]+")
MISSING_MARKERS = frozenset({"", "na", "n/a", "nan", "none", "null", "?"})


def normalize_column_name(value: str) -> str:
    """Normalize a source header without discarding duplicate-column identity."""

    normalized = unicodedata.normalize("NFKC", value).strip()
    normalized = NON_ALPHANUMERIC.sub("_", normalized).strip("_").lower()
    return normalized


def normalize_column_names(values: list[str]) -> tuple[list[str], dict[str, list[int]]]:
    """Return unique canonical names and the indexes of repeated source names."""

    bases = [normalize_column_name(value) for value in values]
    totals = Counter(bases)
    occurrences: Counter[str] = Counter()
    names: list[str] = []
    duplicates: dict[str, list[int]] = {}

    for index, base in enumerate(bases):
        occurrences[base] += 1
        occurrence = occurrences[base]
        names.append(base if occurrence == 1 else f"{base}_{occurrence}")
        if totals[base] > 1:
            duplicates.setdefault(base, []).append(index)

    return names, duplicates


def normalize_label(value: str) -> str:
    """Apply the frozen labels-v1 normalization rule."""

    normalized = unicodedata.normalize("NFKC", value).strip().upper()
    return NON_ALPHANUMERIC.sub("_", normalized).strip("_")


def numeric_value_kind(value: str) -> str:
    """Classify a source cell for audit purposes without transforming it."""

    stripped = value.strip()
    if stripped.casefold() in MISSING_MARKERS:
        return "missing"
    try:
        number = float(stripped)
    except ValueError:
        return "invalid"
    if math.isnan(number):
        return "missing"
    if math.isinf(number):
        return "positive_infinity" if number > 0 else "negative_infinity"
    return "finite"
