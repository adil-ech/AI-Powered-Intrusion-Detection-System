"""Streaming, deterministic audit for CIC-IDS2017 machine-learning CSV files."""

from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from ids_ml.data.catalog import SourceCatalog
from ids_ml.data.manifest import discover_csv_files, verify_manifest
from ids_ml.data.schema import normalize_column_names, normalize_label, numeric_value_kind

LEAKAGE_POLICIES: dict[str, tuple[str, str]] = {
    "flow_id": ("exclude", "Direct flow identifier"),
    "source_ip": ("exclude", "Lab-specific host identifier"),
    "destination_ip": ("exclude", "Lab-specific host identifier"),
    "timestamp": ("exclude", "Capture schedule and attack timing leakage"),
    "source_port": ("exclude", "Ephemeral or lab-specific endpoint identifier"),
    "destination_port": ("validation_experiment_only", "May memorize services in the lab setup"),
}

PHASE3_TREATMENT_PLAN = (
    "Replace positive and negative infinity with missing values before fitting.",
    "Remove exact duplicate rows before assigning any split.",
    "Fit missing-value handling on training data only.",
    "Exclude direct identifiers and source_port; retain capture identity only as split provenance.",
    "Exclude destination_port by default and evaluate it only in the preregistered "
    "validation experiment.",
    "Remove constants and exact duplicate columns using training data only.",
    "Reject unrecognized source labels instead of silently remapping them.",
    "Resolve source-schema differences by name before preprocessing; never align columns "
    "by position.",
)


@dataclass
class ColumnAudit:
    """Incremental statistics for one canonical column."""

    missing: int = 0
    positive_infinity: int = 0
    negative_infinity: int = 0
    invalid_numeric: int = 0
    first_non_missing: str | None = None
    constant: bool = True

    def observe(self, value: str, *, numeric: bool) -> None:
        stripped = value.strip()
        if stripped.casefold() in {"", "na", "n/a", "nan", "none", "null", "?"}:
            self.missing += 1
            return
        if self.first_non_missing is None:
            self.first_non_missing = stripped
        elif stripped != self.first_non_missing:
            self.constant = False
        if not numeric:
            return
        kind = numeric_value_kind(stripped)
        if kind == "missing":
            self.missing += 1
        elif kind == "positive_infinity":
            self.positive_infinity += 1
        elif kind == "negative_infinity":
            self.negative_infinity += 1
        elif kind == "invalid":
            self.invalid_numeric += 1

    def merge(self, other: ColumnAudit) -> None:
        """Merge completed per-file statistics into a dataset-wide statistic."""

        self.missing += other.missing
        self.positive_infinity += other.positive_infinity
        self.negative_infinity += other.negative_infinity
        self.invalid_numeric += other.invalid_numeric
        if other.first_non_missing is None:
            return
        if self.first_non_missing is None:
            self.first_non_missing = other.first_non_missing
        elif self.first_non_missing != other.first_non_missing:
            self.constant = False
        if not other.constant:
            self.constant = False


def _load_label_categories(path: Path) -> dict[str, str]:
    raw: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("categories"), list):
        raise ValueError("label contract must define a categories list")
    categories: dict[str, str] = {}
    for category in raw["categories"]:
        if not isinstance(category, dict):
            raise ValueError("each label category must be an object")
        name = category.get("name")
        source_labels = category.get("source_labels")
        if not isinstance(name, str) or not isinstance(source_labels, list):
            raise ValueError("label categories must define name and source_labels")
        for label in source_labels:
            if not isinstance(label, str):
                raise ValueError("source labels must be strings")
            normalized = normalize_label(label)
            if normalized in categories:
                raise ValueError(f"source label appears in multiple categories: {normalized}")
            categories[normalized] = name
    return categories


def _schema_hash(columns: list[str]) -> str:
    payload = json.dumps(columns, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _row_digest(columns: list[str], row: list[str]) -> bytes:
    pairs = sorted(zip(columns, (value.strip() for value in row), strict=True))
    payload = json.dumps(pairs, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).digest()


def _nonzero_counts(stats: dict[str, ColumnAudit], attribute: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for name in sorted(stats):
        value = int(getattr(stats[name], attribute))
        if value:
            result[name] = value
    return result


def _duplicate_source_columns(
    duplicate_indexes: dict[str, list[int]], exact_matches: dict[str, bool]
) -> list[dict[str, object]]:
    return [
        {
            "base_name": name,
            "source_indexes": indexes,
            "values_are_exact_duplicates": exact_matches[name],
        }
        for name, indexes in sorted(duplicate_indexes.items())
    ]


def audit_dataset(
    raw_dir: Path,
    catalog: SourceCatalog,
    manifest_path: Path,
    labels_path: Path,
) -> dict[str, object]:
    """Audit all source CSVs with bounded memory and a disk-backed global duplicate index."""

    files = discover_csv_files(raw_dir)
    verification = verify_manifest(raw_dir, manifest_path, catalog.dataset)
    label_categories = _load_label_categories(labels_path)
    file_results: list[dict[str, object]] = []
    global_stats: dict[str, ColumnAudit] = {}
    global_labels: Counter[str] = Counter()
    global_categories: Counter[str] = Counter()
    schema_files: dict[str, list[str]] = {}
    found_capture_ids: list[str] = []
    unmatched_files: list[str] = []
    errors = list(verification.errors)
    duplicate_rows = 0
    duplicate_source_summary: dict[str, dict[str, Any]] = {}
    total_rows = 0
    union_columns: set[str] = set()
    intersection_columns: set[str] | None = None

    with tempfile.TemporaryDirectory(prefix="ids-audit-") as temporary_directory:
        duplicate_db = Path(temporary_directory) / "rows.sqlite3"
        connection = sqlite3.connect(duplicate_db)
        connection.execute("PRAGMA journal_mode=OFF")
        connection.execute("PRAGMA synchronous=OFF")
        connection.execute("CREATE TABLE seen_rows (digest BLOB PRIMARY KEY) WITHOUT ROWID")

        for path in files:
            relative = path.relative_to(raw_dir).as_posix()
            try:
                capture = catalog.match(path)
            except ValueError as error:
                capture = None
                errors.append(str(error))
            if capture is None:
                unmatched_files.append(relative)
            else:
                found_capture_ids.append(capture.capture_id)

            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.reader(handle)
                raw_header = next(reader, None)
                if raw_header is None:
                    errors.append(f"CSV has no header: {relative}")
                    continue
                columns, duplicate_indexes = normalize_column_names(raw_header)
                if any(not column for column in columns):
                    errors.append(f"CSV has an empty normalized column name: {relative}")
                if "label" not in columns:
                    errors.append(f"CSV has no label column: {relative}")
                    continue
                label_index = columns.index("label")
                schema = _schema_hash(columns)
                schema_files.setdefault(schema, []).append(relative)
                union_columns.update(columns)
                current_columns = set(columns)
                intersection_columns = (
                    current_columns
                    if intersection_columns is None
                    else intersection_columns & current_columns
                )

                file_stats = {column: ColumnAudit() for column in columns}
                file_labels: Counter[str] = Counter()
                local_digests: set[bytes] = set()
                file_duplicates = 0
                malformed_rows = 0
                row_count = 0
                exact_duplicate_columns = {name: True for name in duplicate_indexes}

                for row in reader:
                    if len(row) != len(columns):
                        malformed_rows += 1
                        continue
                    row_count += 1
                    total_rows += 1
                    digest = _row_digest(columns, row)
                    if digest in local_digests:
                        file_duplicates += 1
                    else:
                        local_digests.add(digest)
                    inserted = connection.execute(
                        "INSERT OR IGNORE INTO seen_rows (digest) VALUES (?)", (digest,)
                    ).rowcount
                    if inserted == 0:
                        duplicate_rows += 1

                    for column, value in zip(columns, row, strict=True):
                        numeric = column != "label"
                        file_stats[column].observe(value, numeric=numeric)
                    for name, indexes in duplicate_indexes.items():
                        values = {row[index].strip() for index in indexes}
                        if len(values) > 1:
                            exact_duplicate_columns[name] = False

                    label = normalize_label(row[label_index])
                    file_labels[label] += 1
                    global_labels[label] += 1
                    category = label_categories.get(label)
                    if category is None:
                        global_categories["UNRECOGNIZED"] += 1
                    else:
                        global_categories[category] += 1

                connection.commit()
                for column, stats in file_stats.items():
                    global_stats.setdefault(column, ColumnAudit()).merge(stats)
                if malformed_rows:
                    errors.append(f"{relative} has {malformed_rows} malformed rows")
                observed_labels = set(file_labels)
                missing_expected = (
                    sorted(set(capture.expected_labels) - observed_labels) if capture else []
                )
                unexpected_labels = (
                    sorted(observed_labels - set(capture.expected_labels))
                    if capture
                    else sorted(observed_labels)
                )
                if missing_expected:
                    errors.append(
                        f"{relative} is missing expected labels: {', '.join(missing_expected)}"
                    )
                if unexpected_labels:
                    errors.append(
                        f"{relative} has unexpected labels: {', '.join(unexpected_labels)}"
                    )
                for name, indexes in duplicate_indexes.items():
                    summary = duplicate_source_summary.setdefault(
                        name,
                        {
                            "base_name": name,
                            "source_indexes": indexes,
                            "files": [],
                            "values_are_exact_duplicates": True,
                        },
                    )
                    summary["files"].append(relative)
                    summary["values_are_exact_duplicates"] = bool(
                        summary["values_are_exact_duplicates"] and exact_duplicate_columns[name]
                    )

                file_results.append(
                    {
                        "path": relative,
                        "capture_id": capture.capture_id if capture else None,
                        "capture_date": capture.capture_date if capture else None,
                        "rows": row_count,
                        "columns": len(columns),
                        "schema_sha256": schema,
                        "labels": dict(sorted(file_labels.items())),
                        "missing_expected_labels": missing_expected,
                        "unexpected_labels": unexpected_labels,
                        "duplicate_rows_within_file": file_duplicates,
                        "malformed_rows": malformed_rows,
                        "missing_cells": _nonzero_counts(file_stats, "missing"),
                        "positive_infinity": _nonzero_counts(file_stats, "positive_infinity"),
                        "negative_infinity": _nonzero_counts(file_stats, "negative_infinity"),
                        "invalid_numeric": _nonzero_counts(file_stats, "invalid_numeric"),
                        "constant_columns": sorted(
                            name
                            for name, stats in file_stats.items()
                            if stats.first_non_missing is not None and stats.constant
                        ),
                        "duplicate_source_columns": _duplicate_source_columns(
                            duplicate_indexes, exact_duplicate_columns
                        ),
                    }
                )
        connection.close()

    capture_counts = Counter(found_capture_ids)
    duplicate_captures = sorted(name for name, count in capture_counts.items() if count > 1)
    expected_capture_ids = {capture.capture_id for capture in catalog.captures}
    missing_captures = sorted(expected_capture_ids - set(found_capture_ids))
    if duplicate_captures:
        errors.append(f"capture IDs matched more than one file: {', '.join(duplicate_captures)}")
    if unmatched_files:
        errors.append(f"unmatched CSV files: {', '.join(sorted(unmatched_files))}")
    if len(schema_files) > 1:
        errors.append(f"source CSVs contain {len(schema_files)} normalized schema variants")

    unknown_labels = sorted(label for label in global_labels if label not in label_categories)
    if unknown_labels:
        errors.append(f"unrecognized labels: {', '.join(unknown_labels)}")

    leakage_review = [
        {"column": column, "action": action, "reason": reason}
        for column, (action, reason) in LEAKAGE_POLICIES.items()
        if column in union_columns
    ]
    label_rows = sum(global_labels.values())
    label_distribution = [
        {
            "label": label,
            "category": label_categories.get(label, "UNRECOGNIZED"),
            "rows": count,
            "share": count / label_rows if label_rows else 0.0,
        }
        for label, count in sorted(global_labels.items())
    ]
    if global_labels:
        majority_label, majority_rows = max(global_labels.items(), key=lambda item: item[1])
        minority_label, minority_rows = min(global_labels.items(), key=lambda item: item[1])
        class_imbalance: dict[str, object] = {
            "majority_label": majority_label,
            "majority_rows": majority_rows,
            "minority_label": minority_label,
            "minority_rows": minority_rows,
            "majority_to_minority_ratio": majority_rows / minority_rows,
        }
    else:
        class_imbalance = {}

    incomplete = not files or bool(missing_captures) or not manifest_path.exists()
    status = "incomplete" if incomplete else ("failed" if errors else "passed")
    return {
        "audit_schema_version": "1.0.0",
        "dataset": catalog.dataset,
        "status": status,
        "source": {
            "official_url": catalog.source_url,
            "archive_name": catalog.archive_name,
            "manifest_path": manifest_path.name,
            "manifest_valid": verification.valid,
            "manifest_errors": list(verification.errors),
        },
        "coverage": {
            "expected_files": len(catalog.captures),
            "found_files": len(files),
            "expected_capture_ids": sorted(expected_capture_ids),
            "found_capture_ids": sorted(found_capture_ids),
            "missing_capture_ids": missing_captures,
            "duplicate_capture_ids": duplicate_captures,
            "unmatched_files": sorted(unmatched_files),
        },
        "summary": {
            "rows": total_rows,
            "normalized_column_count": len(union_columns),
            "schema_variant_count": len(schema_files),
            "exact_duplicate_rows": duplicate_rows,
            "labels": len(global_labels),
        },
        "schema": {
            "union_columns": sorted(union_columns),
            "intersection_columns": sorted(intersection_columns or set()),
            "variants": [
                {"schema_sha256": schema, "files": sorted(paths)}
                for schema, paths in sorted(schema_files.items())
            ],
        },
        "labels": label_distribution,
        "categories": dict(sorted(global_categories.items())),
        "class_imbalance": class_imbalance,
        "quality": {
            "missing_cells": _nonzero_counts(global_stats, "missing"),
            "positive_infinity": _nonzero_counts(global_stats, "positive_infinity"),
            "negative_infinity": _nonzero_counts(global_stats, "negative_infinity"),
            "invalid_numeric": _nonzero_counts(global_stats, "invalid_numeric"),
            "constant_columns": sorted(
                name
                for name, stats in global_stats.items()
                if stats.first_non_missing is not None and stats.constant
            ),
            "duplicate_source_columns": [
                duplicate_source_summary[name] for name in sorted(duplicate_source_summary)
            ],
        },
        "leakage_review": leakage_review,
        "files": file_results,
        "phase3_treatment_plan": list(PHASE3_TREATMENT_PLAN),
        "errors": sorted(set(errors)),
    }


def _count_total(mapping: dict[str, Any]) -> int:
    return sum(int(value) for value in mapping.values())


def _markdown_report(report: dict[str, object]) -> str:
    summary = cast(dict[str, Any], report["summary"])
    coverage = cast(dict[str, Any], report["coverage"])
    source = cast(dict[str, Any], report["source"])
    quality = cast(dict[str, Any], report["quality"])
    labels = cast(list[dict[str, Any]], report["labels"])
    leakage_review = cast(list[dict[str, Any]], report["leakage_review"])
    class_imbalance = cast(dict[str, Any], report["class_imbalance"])
    treatment_plan = cast(list[str], report["phase3_treatment_plan"])
    errors = cast(list[str], report["errors"])
    lines = [
        f"# {report['dataset']} data audit",
        "",
        f"- Status: **{str(report['status']).upper()}**",
        f"- Source files: {coverage['found_files']} of {coverage['expected_files']}",
        f"- Manifest verified: {'yes' if source['manifest_valid'] else 'no'}",
        f"- Rows: {int(summary['rows']):,}",
        f"- Normalized columns: {summary['normalized_column_count']}",
        f"- Schema variants: {summary['schema_variant_count']}",
        f"- Exact duplicate rows: {int(summary['exact_duplicate_rows']):,}",
        (
            f"- Label imbalance: {class_imbalance['majority_label']} has "
            f"{float(class_imbalance['majority_to_minority_ratio']):,.1f}× the rows of "
            f"{class_imbalance['minority_label']}"
            if class_imbalance
            else "- Label imbalance: unavailable"
        ),
        "",
        "## Source coverage",
        "",
    ]
    missing_captures = coverage["missing_capture_ids"]
    lines.append(
        "All expected capture files were found."
        if not missing_captures
        else f"Missing captures: {', '.join(missing_captures)}"
    )
    lines.extend(
        [
            "",
            "## Label distribution",
            "",
            "| Source label | Category | Rows | Share |",
            "|---|---|---:|---:|",
        ]
    )
    for item in labels:
        lines.append(
            f"| {item['label']} | {item['category']} | {int(item['rows']):,} | "
            f"{float(item['share']):.4%} |"
        )
    lines.extend(
        [
            "",
            "## Data quality",
            "",
            f"- Missing cells: {_count_total(quality['missing_cells']):,}",
            f"- Positive infinity: {_count_total(quality['positive_infinity']):,}",
            f"- Negative infinity: {_count_total(quality['negative_infinity']):,}",
            f"- Invalid numeric cells: {_count_total(quality['invalid_numeric']):,}",
            "- Dataset-wide constant columns: "
            + (", ".join(quality["constant_columns"]) or "none"),
            "- Repeated source columns: "
            + (
                ", ".join(
                    f"{item['base_name']} at indexes {item['source_indexes']}"
                    for item in quality["duplicate_source_columns"]
                )
                or "none"
            ),
            "",
            "## Leakage review",
            "",
            "| Column | Planned action | Reason |",
            "|---|---|---|",
        ]
    )
    for item in leakage_review:
        lines.append(f"| {item['column']} | {item['action']} | {item['reason']} |")
    lines.extend(["", "## Phase 3 treatment plan", ""])
    lines.extend(f"- {item}" for item in treatment_plan)
    lines.extend(["", "## Blocking findings", ""])
    if errors:
        lines.extend(f"- {error}" for error in errors)
    else:
        lines.append("None.")
    return "\n".join(lines) + "\n"


def write_audit_reports(
    report: dict[str, object], json_output: Path, markdown_output: Path
) -> None:
    """Write stable machine-readable and human-readable audit evidence."""

    json_output.parent.mkdir(parents=True, exist_ok=True)
    markdown_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_output.write_text(_markdown_report(report), encoding="utf-8")
