"""Versioned capture catalog loading and file matching."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ids_ml.data.schema import normalize_column_name, normalize_label


@dataclass(frozen=True)
class CaptureDefinition:
    """One expected CIC-IDS2017 machine-learning CSV capture."""

    capture_id: str
    capture_date: str
    description: str
    filename_token_groups: tuple[tuple[str, ...], ...]
    expected_labels: tuple[str, ...]

    def matches(self, path: Path) -> bool:
        tokens = set(normalize_column_name(path.name).split("_"))
        return all(
            any(option in tokens for option in group) for group in self.filename_token_groups
        )


@dataclass(frozen=True)
class SourceCatalog:
    """Validated source identity and capture expectations."""

    schema_version: str
    dataset: str
    archive_name: str
    source_url: str
    captures: tuple[CaptureDefinition, ...]

    def match(self, path: Path) -> CaptureDefinition | None:
        matches = [capture for capture in self.captures if capture.matches(path)]
        if len(matches) > 1:
            names = ", ".join(capture.capture_id for capture in matches)
            raise ValueError(f"{path.name} matches multiple capture definitions: {names}")
        return matches[0] if matches else None


def _require_string(mapping: dict[str, Any], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"catalog field {key!r} must be a non-empty string")
    return value


def _require_string_list(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value or not all(isinstance(item, str) for item in value):
        raise ValueError(f"catalog field {field!r} must be a non-empty string list")
    return tuple(str(item) for item in value)


def load_catalog(path: Path) -> SourceCatalog:
    """Load and validate the committed source catalog."""

    raw: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("source catalog must contain a JSON object")
    mapping: dict[str, Any] = raw
    captures_raw = mapping.get("captures")
    if not isinstance(captures_raw, list) or not captures_raw:
        raise ValueError("source catalog captures must be a non-empty list")

    captures: list[CaptureDefinition] = []
    for index, item in enumerate(captures_raw):
        if not isinstance(item, dict):
            raise ValueError(f"capture {index} must be an object")
        capture_mapping: dict[str, Any] = item
        groups_raw = capture_mapping.get("filename_token_groups")
        if not isinstance(groups_raw, list) or not groups_raw:
            raise ValueError(f"capture {index} must define filename_token_groups")
        groups = tuple(
            tuple(
                normalize_column_name(token) for token in _require_string_list(group, "token group")
            )
            for group in groups_raw
        )
        expected_labels = tuple(
            normalize_label(label)
            for label in _require_string_list(
                capture_mapping.get("expected_labels"), "expected_labels"
            )
        )
        captures.append(
            CaptureDefinition(
                capture_id=_require_string(capture_mapping, "id"),
                capture_date=_require_string(capture_mapping, "capture_date"),
                description=_require_string(capture_mapping, "description"),
                filename_token_groups=groups,
                expected_labels=expected_labels,
            )
        )

    capture_ids = [capture.capture_id for capture in captures]
    if len(capture_ids) != len(set(capture_ids)):
        raise ValueError("source catalog capture IDs must be unique")

    return SourceCatalog(
        schema_version=_require_string(mapping, "schema_version"),
        dataset=_require_string(mapping, "dataset"),
        archive_name=_require_string(mapping, "archive_name"),
        source_url=_require_string(mapping, "source_url"),
        captures=tuple(captures),
    )
