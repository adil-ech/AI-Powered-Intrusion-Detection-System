"""Gate tests for deterministic, training-only preprocessing."""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import pytest
from ids_ml.data.catalog import load_catalog
from ids_ml.data.labels import load_taxonomy
from ids_ml.data.manifest import build_manifest, write_manifest
from ids_ml.data.preprocess import (
    PreprocessingConfig,
    assign_split,
    load_preprocessing_config,
    run_preprocessing,
)

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "data/samples/cic_ids2017_synthetic.csv"
LABELS = ROOT / "contracts/labels-v1.json"


def _write_catalog(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "dataset": "CIC-IDS2017-TEST",
                "archive_name": "synthetic.zip",
                "source_url": "https://example.invalid/synthetic",
                "captures": [
                    {
                        "id": "synthetic",
                        "capture_date": "2017-07-03",
                        "description": "Synthetic preprocessing fixture",
                        "filename_token_groups": [["synthetic"]],
                        "expected_labels": ["BENIGN", "DDOS"],
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_config(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "dataset": "CIC-IDS2017-TEST",
                "random_seed": 42,
                "group_size_rows": 1,
                "split_basis_points": {
                    "train": 6000,
                    "validation": 2000,
                    "final_test": 2000,
                },
                "excluded_features": {
                    "label": "target",
                    "destination_port": "port leakage",
                },
                "imputation_strategy": "training_mean",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_rows(path: Path, *, unknown_label: bool = False) -> None:
    with SAMPLE.open(encoding="utf-8", newline="") as handle:
        sample_rows = list(csv.reader(handle))
    header = sample_rows[0]
    flow_duration = header.index(" Flow Duration")
    label = header.index(" Label")
    rows: list[list[str]] = []
    for index in range(90):
        row = sample_rows[1].copy()
        row[flow_duration] = "Infinity" if index == 7 else str(index + 1)
        row[label] = "DDoS" if index % 3 == 0 else "BENIGN"
        rows.append(row)
    rows.append(rows[5].copy())
    if unknown_label:
        rows[20][label] = "new unmapped attack"
    with path.open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle, lineterminator="\n").writerows([header, *rows])


def _prepare(tmp_path: Path, *, unknown_label: bool = False) -> dict[str, Path]:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir(parents=True)
    _write_rows(raw_dir / "synthetic.csv", unknown_label=unknown_label)
    catalog_path = tmp_path / "catalog.json"
    config_path = tmp_path / "config.json"
    manifest_path = tmp_path / "manifest.json"
    _write_catalog(catalog_path)
    _write_config(config_path)
    catalog = load_catalog(catalog_path)
    write_manifest(build_manifest(raw_dir, catalog, "2026-10-18"), manifest_path)
    return {
        "raw_dir": raw_dir,
        "catalog": catalog_path,
        "config": config_path,
        "manifest": manifest_path,
    }


def _run(paths: dict[str, Path], root: Path, contract: Path | None = None) -> dict[str, object]:
    output = root / "processed"
    report_json = root / "report.json"
    report_markdown = root / "report.md"
    contract_output = root / "features.json" if contract is None else None
    return run_preprocessing(
        raw_dir=paths["raw_dir"],
        catalog=load_catalog(paths["catalog"]),
        manifest_path=paths["manifest"],
        taxonomy=load_taxonomy(LABELS),
        taxonomy_path=LABELS,
        config=load_preprocessing_config(paths["config"]),
        config_path=paths["config"],
        output_dir=output,
        feature_contract_path=contract,
        feature_contract_output=contract_output,
        report_json=report_json,
        report_markdown=report_markdown,
    )


def _load_json(path: Path) -> dict[str, Any]:
    value: object = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_split_assignment_is_stable_and_group_scoped() -> None:
    config = PreprocessingConfig(
        schema_version="1.0.0",
        dataset="test",
        random_seed=1701,
        group_size_rows=4096,
        split_basis_points={"train": 7000, "validation": 1500, "final_test": 1500},
        excluded_features={},
        imputation_strategy="training_mean",
    )
    group = "2017-07-03:monday:window-000001"
    assert assign_split(group, config) == assign_split(group, config)


def test_pipeline_is_deterministic_finite_and_leak_resistant(tmp_path: Path) -> None:
    paths = _prepare(tmp_path / "fixture")
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first = _run(paths, first_root)
    contract = first_root / "features.json"
    second = _run(paths, second_root, contract)

    assert first == second
    for name in (
        "split-manifest.json",
        "preprocessing-state.json",
        "train.csv.gz",
        "validation.csv.gz",
        "final_test.csv.gz",
    ):
        assert (first_root / "processed" / name).read_bytes() == (
            second_root / "processed" / name
        ).read_bytes()
    assert (first_root / "report.json").read_bytes() == (second_root / "report.json").read_bytes()

    feature_contract = _load_json(contract)
    features = feature_contract["required_features"]
    assert features == ["flow_duration"]
    assert feature_contract["features"] == [
        {
            "dtype": "float64",
            "missing_value_policy": "training_mean",
            "name": "flow_duration",
        }
    ]

    manifest = _load_json(first_root / "processed/split-manifest.json")
    group_ids = [group["group_id"] for group in manifest["groups"]]
    assert len(group_ids) == len(set(group_ids))
    assert {group["split"] for group in manifest["groups"]} == {
        "train",
        "validation",
        "final_test",
    }

    digests: dict[str, set[str]] = {}
    for split in ("train", "validation", "final_test"):
        rows: set[str] = set()
        with gzip.open(first_root / f"processed/{split}.csv.gz", "rt", newline="") as handle:
            reader = csv.DictReader(handle)
            assert reader.fieldnames == ["flow_duration", "category", "is_malicious"]
            for row in reader:
                assert math.isfinite(float(row["flow_duration"]))
                digest = hashlib.sha256(
                    f"{row['flow_duration']}|{row['category']}".encode()
                ).hexdigest()
                assert digest not in rows
                rows.add(digest)
        digests[split] = rows
    assert digests["train"].isdisjoint(digests["validation"])
    assert digests["train"].isdisjoint(digests["final_test"])
    assert digests["validation"].isdisjoint(digests["final_test"])

    for split in ("train", "validation", "final_test"):
        assert set(first["splits"][split]["class_support"]) == set(load_taxonomy(LABELS).categories)
    assert first["leakage_checks"] == {
        "group_overlap": 0,
        "row_digest_overlap": 0,
        "duplicate_feature_label_rows_across_splits": 0,
        "final_test_rows_used_for_fitting": 0,
        "non_finite_output_values": 0,
    }
    state = _load_json(first_root / "processed/preprocessing-state.json")
    assert state["fit_split"] == "train"
    assert state["fit_rows"] >= first["splits"]["train"]["rows"]


def test_final_test_values_do_not_change_fitted_imputer(tmp_path: Path) -> None:
    paths = _prepare(tmp_path / "fixture")
    baseline_root = tmp_path / "baseline"
    _run(paths, baseline_root)
    baseline = _load_json(baseline_root / "processed/preprocessing-state.json")

    source = paths["raw_dir"] / "synthetic.csv"
    with source.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    config = load_preprocessing_config(paths["config"])
    final_row = next(
        row_number
        for row_number in range(1, len(rows))
        if assign_split(f"2017-07-03:synthetic:window-{row_number - 1:06d}", config) == "final_test"
    )
    rows[final_row][1] = "999999999"
    with source.open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle, lineterminator="\n").writerows(rows)
    catalog = load_catalog(paths["catalog"])
    write_manifest(build_manifest(paths["raw_dir"], catalog, "2026-10-18"), paths["manifest"])

    changed_root = tmp_path / "changed"
    _run(paths, changed_root, baseline_root / "features.json")
    changed = _load_json(changed_root / "processed/preprocessing-state.json")
    assert baseline["imputation_values"] == changed["imputation_values"]
    assert baseline["fit_rows"] == changed["fit_rows"]


def test_unknown_source_label_fails_loudly(tmp_path: Path) -> None:
    paths = _prepare(tmp_path / "fixture", unknown_label=True)
    with pytest.raises(ValueError, match="unrecognized source label: NEW_UNMAPPED_ATTACK"):
        _run(paths, tmp_path / "run")
