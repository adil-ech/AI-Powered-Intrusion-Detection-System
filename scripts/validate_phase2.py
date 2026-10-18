#!/usr/bin/env python3
"""Validate committed Phase 2 data-source and safe-fixture invariants."""

from __future__ import annotations

import csv
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_FILES = (
    "docs/data/cic-ids2017.md",
    "data/source_catalog.json",
    "data/samples/cic_ids2017_synthetic.csv",
    "ml/src/ids_ml/data/audit.py",
    "ml/src/ids_ml/data/cli.py",
)
DIRECT_IDENTIFIERS = {"flow_id", "source_ip", "destination_ip", "timestamp", "source_port"}
IPV4 = re.compile(r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)")
MAC = re.compile(r"(?i)(?<![0-9a-f])(?:[0-9a-f]{2}:){5}[0-9a-f]{2}(?![0-9a-f])")
EMAIL = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b")


def fail(errors: list[str], message: str) -> None:
    errors.append(message)


def normalize(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z]+", "_", value.strip()).strip("_").lower()


def load_json(relative: str) -> dict[str, Any]:
    raw: object = json.loads((ROOT / relative).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{relative} must contain a JSON object")
    return raw


def validate_required_files(errors: list[str]) -> None:
    for relative in REQUIRED_FILES:
        if not (ROOT / relative).is_file():
            fail(errors, f"missing required Phase 2 file: {relative}")


def validate_catalog(errors: list[str]) -> None:
    catalog = load_json("data/source_catalog.json")
    captures = catalog.get("captures")
    if not isinstance(captures, list) or len(captures) != 8:
        fail(errors, "source catalog must define exactly eight capture files")
        return
    capture_ids: list[str] = []
    catalog_labels: set[str] = set()
    for capture in captures:
        if not isinstance(capture, dict):
            fail(errors, "every source catalog capture must be an object")
            continue
        capture_id = capture.get("id")
        if isinstance(capture_id, str):
            capture_ids.append(capture_id)
        labels = capture.get("expected_labels")
        if isinstance(labels, list):
            catalog_labels.update(str(label) for label in labels)
    if len(capture_ids) != len(set(capture_ids)):
        fail(errors, "source catalog capture IDs must be unique")

    contract = load_json("contracts/labels-v1.json")
    categories = contract.get("categories")
    contract_labels: set[str] = set()
    if isinstance(categories, list):
        for category in categories:
            if isinstance(category, dict) and isinstance(category.get("source_labels"), list):
                contract_labels.update(str(label) for label in category["source_labels"])
    if catalog_labels != contract_labels:
        fail(errors, "source catalog labels must exactly cover labels-v1")


def validate_fixture(errors: list[str]) -> None:
    path = ROOT / "data/samples/cic_ids2017_synthetic.csv"
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    if len(rows) < 3:
        fail(errors, "synthetic fixture must include a header and multiple rows")
        return
    header = rows[0]
    if len(header) != 79:
        fail(errors, f"synthetic fixture must use the 79-column ML schema, found {len(header)}")
    if any(len(row) != len(header) for row in rows[1:]):
        fail(errors, "synthetic fixture rows must match its header width")
    normalized = [normalize(value) for value in header]
    if DIRECT_IDENTIFIERS.intersection(normalized):
        fail(errors, "synthetic fixture contains direct network identifier columns")
    if normalized.count("fwd_header_length") != 2:
        fail(
            errors, "synthetic fixture must preserve the source's repeated Fwd Header Length column"
        )
    text = path.read_text(encoding="utf-8")
    for pattern, description in ((IPV4, "IPv4"), (MAC, "MAC"), (EMAIL, "email")):
        if pattern.search(text):
            fail(errors, f"synthetic fixture contains a possible real {description} identifier")


def validate_docs(errors: list[str]) -> None:
    text = (ROOT / "docs/data/cic-ids2017.md").read_text(encoding="utf-8")
    required = (
        "https://www.unb.ca/cic/datasets/ids-2017.html",
        "MachineLearningCSV.zip",
        "4f83860afbf29cac8163854095bf6cf7",
        "c3f26274b36c837ccf28ffd2dbf4582941c30b3ee70a635c6e5b2f87c4727928",
        "make data-manifest",
        "make audit-data",
        "Sharafaldin",
    )
    for value in required:
        if value not in text:
            fail(errors, f"dataset guide is missing required provenance detail: {value}")


def validate_raw_git_boundary(errors: list[str]) -> None:
    result = subprocess.run(
        ["git", "ls-files", "--", "data/raw"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    tracked = [line for line in result.stdout.splitlines() if line]
    if tracked != ["data/raw/README.md"]:
        fail(errors, f"raw data tracking boundary violated: {tracked}")


def main() -> int:
    errors: list[str] = []
    validate_required_files(errors)
    if not errors:
        validate_catalog(errors)
        validate_fixture(errors)
        validate_docs(errors)
        validate_raw_git_boundary(errors)
    if errors:
        print("Phase 2 validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(
        "Phase 2 repository validation passed: 8 captures, 79-column safe fixture, "
        "raw data ignored."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
