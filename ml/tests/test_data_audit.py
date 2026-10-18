"""Tests for deterministic source manifests and dataset audits."""

from __future__ import annotations

import csv
import json
import re
import shutil
from pathlib import Path

from ids_ml.data.audit import audit_dataset, write_audit_reports
from ids_ml.data.catalog import load_catalog
from ids_ml.data.manifest import build_manifest, verify_manifest, write_manifest
from ids_ml.data.schema import normalize_column_names, normalize_label, numeric_value_kind

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "data/samples/cic_ids2017_synthetic.csv"
LABELS = ROOT / "contracts/labels-v1.json"


def _write_test_catalog(path: Path) -> None:
    catalog = {
        "schema_version": "1.0.0",
        "dataset": "CIC-IDS2017-TEST",
        "archive_name": "synthetic.zip",
        "source_url": "https://example.invalid/synthetic",
        "captures": [
            {
                "id": "synthetic",
                "capture_date": "2017-07-03",
                "description": "Safe synthetic audit fixture",
                "filename_token_groups": [["synthetic"]],
                "expected_labels": ["BENIGN", "DDOS"],
            }
        ],
    }
    path.write_text(json.dumps(catalog), encoding="utf-8")


def test_source_normalization_handles_repeated_headers_and_values() -> None:
    columns, duplicates = normalize_column_names(
        [" Destination Port", " Fwd Header Length", " Fwd Header Length", " Label"]
    )
    assert columns == ["destination_port", "fwd_header_length", "fwd_header_length_2", "label"]
    assert duplicates == {"fwd_header_length": [1, 2]}
    assert normalize_label(" Web Attack – Brute Force ") == "WEB_ATTACK_BRUTE_FORCE"
    assert numeric_value_kind("Infinity") == "positive_infinity"
    assert numeric_value_kind("-Infinity") == "negative_infinity"


def test_committed_catalog_covers_all_eight_captures() -> None:
    catalog = load_catalog(ROOT / "data/source_catalog.json")
    assert len(catalog.captures) == 8
    assert {capture.capture_id for capture in catalog.captures} == {
        "monday",
        "tuesday",
        "wednesday",
        "thursday_morning",
        "thursday_afternoon",
        "friday_morning",
        "friday_port_scan",
        "friday_ddos",
    }


def test_safe_fixture_matches_machine_learning_schema() -> None:
    with SAMPLE.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    assert len(rows[0]) == 79
    assert all(len(row) == 79 for row in rows[1:])
    normalized, duplicates = normalize_column_names(rows[0])
    assert "label" in normalized
    assert duplicates == {"fwd_header_length": [34, 55]}
    assert not {"flow_id", "source_ip", "destination_ip", "timestamp", "source_port"}.intersection(
        normalized
    )
    text = SAMPLE.read_text(encoding="utf-8")
    assert re.search(r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)", text) is None


def test_manifest_detects_source_drift(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    source = raw_dir / "synthetic.csv"
    shutil.copyfile(SAMPLE, source)
    catalog_path = tmp_path / "catalog.json"
    manifest_path = tmp_path / "manifest.json"
    _write_test_catalog(catalog_path)
    catalog = load_catalog(catalog_path)
    write_manifest(build_manifest(raw_dir, catalog, "2026-10-18"), manifest_path)
    assert verify_manifest(raw_dir, manifest_path, catalog.dataset).valid

    source.write_text(source.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    verification = verify_manifest(raw_dir, manifest_path, catalog.dataset)
    assert not verification.valid
    assert any("size mismatch" in error for error in verification.errors)
    assert any("sha256 mismatch" in error for error in verification.errors)


def test_audit_is_deterministic_and_reports_quality_findings(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    shutil.copyfile(SAMPLE, raw_dir / "synthetic.csv")
    catalog_path = tmp_path / "catalog.json"
    manifest_path = tmp_path / "manifest.json"
    _write_test_catalog(catalog_path)
    catalog = load_catalog(catalog_path)
    write_manifest(build_manifest(raw_dir, catalog, "2026-10-18"), manifest_path)

    first = audit_dataset(raw_dir, catalog, manifest_path, LABELS)
    second = audit_dataset(raw_dir, catalog, manifest_path, LABELS)
    assert first == second
    assert first["status"] == "passed"
    assert first["summary"] == {
        "rows": 4,
        "normalized_column_count": 79,
        "schema_variant_count": 1,
        "exact_duplicate_rows": 1,
        "labels": 2,
    }
    assert first["quality"]["positive_infinity"] == {"flow_bytes_s": 1}
    assert first["quality"]["negative_infinity"] == {"flow_packets_s": 1}
    assert first["quality"]["missing_cells"] == {"fwd_iat_mean": 1}
    duplicate_columns = first["files"][0]["duplicate_source_columns"]
    assert duplicate_columns == [
        {
            "base_name": "fwd_header_length",
            "source_indexes": [34, 55],
            "values_are_exact_duplicates": True,
        }
    ]

    first_json = tmp_path / "first.json"
    first_markdown = tmp_path / "first.md"
    second_json = tmp_path / "second.json"
    second_markdown = tmp_path / "second.md"
    write_audit_reports(first, first_json, first_markdown)
    write_audit_reports(second, second_json, second_markdown)
    assert first_json.read_bytes() == second_json.read_bytes()
    assert first_markdown.read_bytes() == second_markdown.read_bytes()


def test_incomplete_audit_lists_exact_missing_capture(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    catalog_path = tmp_path / "catalog.json"
    _write_test_catalog(catalog_path)
    report = audit_dataset(raw_dir, load_catalog(catalog_path), tmp_path / "missing.json", LABELS)
    assert report["status"] == "incomplete"
    assert report["coverage"]["missing_capture_ids"] == ["synthetic"]
    assert report["coverage"]["found_files"] == 0
