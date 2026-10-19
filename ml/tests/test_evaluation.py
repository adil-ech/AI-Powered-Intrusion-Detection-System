"""Gate tests for shared metrics, reproducibility, and baseline artifacts."""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
from pathlib import Path

import joblib
import numpy as np
import pytest
from ids_ml.data.labels import load_taxonomy
from ids_ml.evaluation.config import BaselineConfig
from ids_ml.evaluation.metrics import evaluate_binary, evaluate_multiclass
from ids_ml.evaluation.models import BaselineBundle, fit_baselines
from ids_ml.evaluation.report import run_baseline_evaluation

ROOT = Path(__file__).resolve().parents[2]
LABELS = ROOT / "contracts/labels-v1.json"
FEATURES = ["feature_a", "feature_b"]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_split(path: Path, rows: int, offset: int) -> None:
    with (
        path.open("wb") as output,
        gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=0) as raw,
        io.TextIOWrapper(raw, encoding="utf-8", newline="") as handle,
    ):
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow([*FEATURES, "category", "is_malicious"])
        for index in range(rows):
            value = index + offset
            malicious = int(value % 4 == 0 or value % 7 == 0)
            category = "DOS_DDOS" if malicious else "BENIGN"
            writer.writerow(
                [
                    float(value % 17) + malicious * 8.0,
                    float((value * 3) % 11) - malicious * 5.0,
                    category,
                    malicious,
                ]
            )


def _fixture(tmp_path: Path) -> dict[str, Path]:
    processed = tmp_path / "processed"
    processed.mkdir()
    counts = {"train": 240, "validation": 80, "final_test": 70}
    offsets = {"train": 0, "validation": 1000, "final_test": 2000}
    splits: dict[str, dict[str, object]] = {}
    for split in counts:
        path = processed / f"{split}.csv.gz"
        _write_split(path, counts[split], offsets[split])
        splits[split] = {
            "path": path.name,
            "rows": counts[split],
            "sha256": _sha256(path),
            "bytes": path.stat().st_size,
        }
    feature_contract = tmp_path / "features.json"
    feature_contract.write_text(
        json.dumps(
            {
                "feature_schema_sha256": "a" * 64,
                "required_features": FEATURES,
            }
        ),
        encoding="utf-8",
    )
    split_manifest = tmp_path / "split-manifest.json"
    split_manifest.write_text(
        json.dumps(
            {
                "feature_schema_sha256": "a" * 64,
                "splits": splits,
            }
        ),
        encoding="utf-8",
    )
    return {
        "processed": processed,
        "features": feature_contract,
        "manifest": split_manifest,
    }


def test_binary_metrics_use_stable_order_and_explicit_rates() -> None:
    result = evaluate_binary(
        np.asarray([0, 0, 1, 1], dtype=np.int64),
        np.asarray([0.1, 0.8, 0.7, 0.2], dtype=np.float64),
        threshold=0.5,
        split="validation",
        model="known_example",
    )
    assert result["confusion_matrix"]["labels"] == [0, 1]
    assert result["confusion_matrix"]["values"] == [[1, 1], [1, 1]]
    assert result["precision"] == pytest.approx(0.5)
    assert result["recall"] == pytest.approx(0.5)
    assert result["f1"] == pytest.approx(0.5)
    assert result["false_positive_rate"] == pytest.approx(0.5)
    assert result["false_negative_rate"] == pytest.approx(0.5)
    assert result["support"] == {"total": 4, "benign": 2, "malicious": 2}


def test_binary_absent_class_has_explicit_undefined_metrics() -> None:
    result = evaluate_binary(
        np.asarray([0, 0, 0], dtype=np.int64),
        np.asarray([0.1, 0.2, 0.3], dtype=np.float64),
        threshold=0.5,
        split="validation",
        model="absent_positive",
    )
    assert result["pr_auc"] is None
    assert result["roc_auc"] is None
    assert result["false_negative_rate"] is None
    assert result["false_positive_rate"] == 0.0
    assert result["confusion_matrix"]["values"] == [[3, 0], [0, 0]]


def test_multiclass_metrics_keep_absent_contract_class() -> None:
    result = evaluate_multiclass(
        np.asarray(["A", "A", "B"], dtype=np.str_),
        np.asarray(
            [
                [0.8, 0.1, 0.1],
                [0.2, 0.7, 0.1],
                [0.1, 0.8, 0.1],
            ],
            dtype=np.float64,
        ),
        labels=["A", "B", "C"],
        split="validation_malicious_rows",
        model="known_family_example",
    )
    assert result["confusion_matrix"]["labels"] == ["A", "B", "C"]
    assert result["confusion_matrix"]["values"] == [[1, 1, 0], [0, 1, 0], [0, 0, 0]]
    assert result["per_class"]["C"] == {
        "precision": 0.0,
        "recall": 0.0,
        "f1": 0.0,
        "support": 0,
    }
    assert result["macro_f1"] > result["macro_f1_all_contract_classes"]


def test_training_is_reproducible_and_serialization_preserves_predictions(
    tmp_path: Path,
) -> None:
    paths = _fixture(tmp_path)
    attack_labels = [
        category for category in load_taxonomy(LABELS).categories if category != "BENIGN"
    ]
    first, _ = fit_baselines(
        paths["processed"] / "train.csv.gz",
        FEATURES,
        attack_labels,
        random_seed=42,
        batch_size=32,
    )
    second, _ = fit_baselines(
        paths["processed"] / "train.csv.gz",
        FEATURES,
        attack_labels,
        random_seed=42,
        batch_size=32,
    )
    assert np.allclose(
        first.binary_logistic.classifier.coef_,
        second.binary_logistic.classifier.coef_,
        rtol=1e-12,
        atol=1e-12,
    )
    sample = np.asarray([[2.0, 1.0], [12.0, -3.0]], dtype=np.float64)
    artifact = tmp_path / "baseline.joblib"
    joblib.dump(first, artifact)
    loaded: object = joblib.load(artifact)
    assert isinstance(loaded, BaselineBundle)
    assert np.allclose(
        first.binary_logistic.predict_proba(sample),
        loaded.binary_logistic.predict_proba(sample),
        rtol=1e-12,
        atol=1e-12,
    )


def test_report_uses_validation_and_keeps_final_test_sealed(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    report = run_baseline_evaluation(
        processed_dir=paths["processed"],
        feature_contract_path=paths["features"],
        taxonomy=load_taxonomy(LABELS),
        taxonomy_path=LABELS,
        split_manifest_path=paths["manifest"],
        model_output=tmp_path / "models/baseline.joblib",
        report_json=tmp_path / "reports/baseline.json",
        report_markdown=tmp_path / "reports/baseline.md",
        calibration_svg=tmp_path / "reports/calibration.svg",
        config=BaselineConfig(
            schema_version="1.0.0",
            baseline_version="baselines-v1-test",
            random_seed=42,
            batch_size=32,
            binary_threshold=0.5,
        ),
        config_path=ROOT / "configs/baselines-v1.json",
    )
    assert report["evaluation"]["validation"]["binary_logistic"]["split"] == "validation"
    assert report["evaluation"]["final_test"]["status"] == "sealed_not_evaluated"
    assert report["data"]["final_test_opened_for_predictions"] is False
    assert report["comparison"]["same_rows"] is True
    assert report["artifact"]["serialization_parity"]["models"] == {
        "binary_dummy": True,
        "binary_logistic": True,
        "attack_family_prior": True,
    }
    markdown = (tmp_path / "reports/baseline.md").read_text(encoding="utf-8")
    assert "Headline split: **validation**" in markdown
    assert "Final test: **SEALED — NOT EVALUATED**" in markdown
    assert (
        (tmp_path / "reports/calibration.svg")
        .read_text(encoding="utf-8")
        .startswith('<svg xmlns="http://www.w3.org/2000/svg"')
    )
    loaded: object = json.loads((tmp_path / "reports/baseline.json").read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
