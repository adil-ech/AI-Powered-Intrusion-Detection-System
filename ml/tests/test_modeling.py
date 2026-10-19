"""Gate tests for Phase 5 selection, calibration, and artifact safety."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from ids_ml.data.labels import load_taxonomy
from ids_ml.evaluation.metrics import evaluate_binary
from ids_ml.modeling.artifact import (
    InferenceBundle,
    load_artifact,
    write_artifact,
)
from ids_ml.modeling.config import (
    ForestCandidate,
    VariantPolicy,
    load_model_selection_config,
)
from ids_ml.modeling.data import build_validation_partitions
from ids_ml.modeling.models import (
    build_forest,
    calibrate_binary,
    calibrate_family,
    choose_feature_variant,
    select_binary_threshold,
)
from ids_ml.modeling.pipeline import run_model_selection
from sklearn.dummy import DummyClassifier

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs/model-selection-v1.json"
LABELS = ROOT / "contracts/labels-v1.json"


def test_group_partitions_are_disjoint_complete_and_keep_rare_class_in_calibration(
    tmp_path: Path,
) -> None:
    categories = list(load_taxonomy(LABELS).categories)
    records: list[dict[str, object]] = []
    ordered: list[dict[str, object]] = []
    for index in range(9):
        source = "a.csv" if index % 2 else "z.csv"
        support = {"BENIGN": 1, "DOS_DDOS": 1}
        if index == 4:
            support["INFILTRATION"] = 1
        record: dict[str, object] = {
            "group_id": f"2017-07-{index + 1:02d}:capture:window-000000",
            "source_path": source,
            "split": "validation",
            "rows": sum(support.values()),
            "category_support": support,
        }
        records.append(record)
        ordered.append(record)
    ordered.sort(key=lambda item: (str(item["source_path"]), str(item["group_id"])))
    category_ids: list[int] = []
    for record in ordered:
        support = record["category_support"]
        assert isinstance(support, dict)
        for category, count in support.items():
            category_ids.extend([categories.index(str(category))] * int(count))
    manifest = tmp_path / "split-manifest.json"
    manifest.write_text(
        json.dumps({"groups": sorted(records, key=lambda item: str(item["group_id"]))}),
        encoding="utf-8",
    )
    partitions = build_validation_partitions(
        manifest,
        np.asarray(category_ids, dtype=np.int8),
        categories,
        random_seed=42,
        fold_count=3,
    )
    sets = [set(partitions.tuning), set(partitions.calibration), set(partitions.selection)]
    assert not sets[0] & sets[1]
    assert not sets[0] & sets[2]
    assert not sets[1] & sets[2]
    assert set.union(*sets) == set(range(len(category_ids)))
    infiltration = categories.index("INFILTRATION")
    assert np.any(np.asarray(category_ids, dtype=np.int8)[partitions.calibration] == infiltration)


def test_calibrators_are_finite_normalized_and_retain_absent_family_column() -> None:
    rng = np.random.default_rng(42)
    features = rng.normal(size=(180, 4)).astype(np.float32)
    binary = (features[:, 0] + features[:, 1] > 0).astype(np.uint8)
    binary_forest = build_forest(
        ForestCandidate("binary-test", 12, 6, 1, "sqrt", 1.0), random_seed=42
    )
    binary_forest.fit(features[:120], binary[:120])
    binary_calibrator = calibrate_binary(binary_forest, features[120:], binary[120:])
    binary_probability = binary_calibrator.predict_proba(features[:20])
    assert np.all(np.isfinite(binary_probability))
    assert np.allclose(np.sum(binary_probability, axis=1), 1.0)

    family_targets = np.tile(np.asarray([0, 1, 2], dtype=np.int64), 40)
    family_forest = build_forest(
        ForestCandidate("family-test", 12, 6, 1, "sqrt", 1.0), random_seed=42
    )
    family_forest.fit(features[:120], family_targets)
    calibration_binary = np.ones(40, dtype=np.uint8)
    calibration_categories = np.tile(np.asarray([1, 2], dtype=np.int8), 20)
    family_calibrator = calibrate_family(
        family_forest,
        features[120:160],
        calibration_binary,
        calibration_categories,
    )
    family_probability = family_calibrator.predict_proba(features[:20])
    assert family_probability.shape == (20, 3)
    assert np.all(np.isfinite(family_probability))
    assert np.allclose(np.sum(family_probability, axis=1), 1.0)
    assert np.all(family_probability[:, 2] >= 0.0)


def test_threshold_search_honors_false_positive_constraint() -> None:
    config = load_model_selection_config(CONFIG)
    targets = np.asarray([0, 0, 0, 0, 1, 1, 1, 1], dtype=np.uint8)
    probabilities = np.asarray([0.01, 0.02, 0.2, 0.7, 0.4, 0.6, 0.8, 0.9])
    threshold, metrics = select_binary_threshold(
        targets,
        probabilities,
        config,
        split="validation_calibration",
        model="known_threshold_example",
    )
    assert 0.0 < threshold < 1.0
    assert metrics["false_positive_rate"] <= config.threshold_search.maximum_false_positive_rate


def test_port_variant_requires_preregistered_family_gain() -> None:
    def result(binary_f1: float, family_f1: float) -> dict[str, object]:
        return {
            "binary": {"f1": binary_f1},
            "attack_family": {
                "macro_f1": family_f1,
                "support": {"DOS_DDOS": 10},
                "per_class": {"DOS_DDOS": {"recall": family_f1}},
            },
        }

    policy = VariantPolicy(0.01, 0.005, 0.05)
    selected, details = choose_feature_variant(result(0.98, 0.95), result(0.99, 0.95), policy)
    assert selected == "without_destination_port"
    assert details["port_qualifies"] is False
    selected, details = choose_feature_variant(result(0.98, 0.95), result(0.98, 0.97), policy)
    assert selected == "with_destination_port"
    assert details["port_qualifies"] is True


def test_artifact_integrity_column_reordering_and_batch_parity(tmp_path: Path) -> None:
    binary = DummyClassifier(strategy="prior").fit(
        np.asarray([[0.0, 0.0], [1.0, 1.0]]), np.asarray([0, 1])
    )
    family = DummyClassifier(strategy="prior").fit(
        np.asarray([[0.0, 0.0], [1.0, 1.0], [2.0, 2.0]]), np.asarray([0, 1, 2])
    )
    bundle = InferenceBundle(
        artifact_schema_version="1.0.0",
        model_version="test-v1",
        feature_schema_version="features-test",
        feature_schema_hash="a" * 64,
        required_features=("feature_a", "feature_b"),
        imputation_values=(0.0, 0.0),
        attack_labels=("A", "B", "C"),
        malicious_threshold=0.4,
        low_confidence_threshold=0.65,
        high_risk_threshold=0.85,
        binary_model=binary,
        attack_family_model=family,
    )
    feature_schema = tmp_path / "features.json"
    feature_schema.write_text(
        json.dumps(
            {
                "feature_schema_version": "features-test",
                "feature_schema_sha256": "a" * 64,
                "required_features": ["feature_a", "feature_b"],
            }
        ),
        encoding="utf-8",
    )
    taxonomy = tmp_path / "labels.json"
    taxonomy.write_text(json.dumps({"categories": ["BENIGN", "A", "B", "C"]}), encoding="utf-8")
    output = tmp_path / "artifact"
    write_artifact(
        output,
        bundle,
        metadata={
            "artifact_schema_version": "1.0.0",
            "model_version": "test-v1",
            "feature_schema_hash": "a" * 64,
        },
        metrics={"status": "test"},
        feature_schema_path=feature_schema,
        label_taxonomy_path=taxonomy,
    )
    loaded, _ = load_artifact(output)
    ordered = np.asarray([[1.0, 2.0], [3.0, 4.0]], dtype=np.float64)
    shuffled = ordered[:, ::-1]
    expected = loaded.predict_probabilities(ordered, ["feature_a", "feature_b"])
    actual = loaded.predict_probabilities(shuffled, ["feature_b", "feature_a"])
    assert np.allclose(expected[0], actual[0])
    assert np.allclose(expected[1], actual[1])
    single = loaded.predict_probabilities(ordered[:1], ["feature_a", "feature_b"])
    assert np.allclose(single[0], expected[0][:1])
    assert np.allclose(single[1], expected[1][:1])
    with pytest.raises(ValueError, match="missing: feature_b"):
        loaded.align_features(ordered[:, :1], ["feature_a"])
    with pytest.raises(ValueError, match="extra: feature_c"):
        loaded.align_features(
            np.column_stack((ordered, np.ones(ordered.shape[0]))),
            ["feature_a", "feature_b", "feature_c"],
        )
    (output / "metrics.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="integrity check failed for metrics.json"):
        load_artifact(output)


def test_random_forest_regression_is_reproducible() -> None:
    rng = np.random.default_rng(7)
    features = rng.normal(size=(240, 5)).astype(np.float32)
    targets = (features[:, 0] - features[:, 1] > 0).astype(np.uint8)
    candidate = ForestCandidate("regression", 20, 8, 1, "sqrt", 1.0)
    first = build_forest(candidate, random_seed=42).fit(features, targets)
    second = build_forest(candidate, random_seed=42).fit(features, targets)
    first_probability = np.asarray(first.predict_proba(features)[:, 1], dtype=np.float64)
    second_probability = np.asarray(second.predict_proba(features)[:, 1], dtype=np.float64)
    assert np.allclose(first_probability, second_probability, rtol=1e-12, atol=1e-12)
    metrics = evaluate_binary(
        np.asarray(targets, dtype=np.int64),
        first_probability,
        threshold=0.5,
        split="synthetic_regression",
        model="random_forest",
    )
    assert metrics["f1"] >= 0.98


def test_finalization_is_blocked_before_selection_freeze(tmp_path: Path) -> None:
    config = replace(
        load_model_selection_config(CONFIG), selection_frozen=False, frozen_selection=None
    )
    with pytest.raises(ValueError, match="selection must be frozen"):
        run_model_selection(
            base_processed_dir=tmp_path / "base",
            port_processed_dir=tmp_path / "port",
            base_feature_contract_path=tmp_path / "features.json",
            taxonomy=load_taxonomy(LABELS),
            taxonomy_path=LABELS,
            baseline_artifact_path=tmp_path / "baseline.joblib",
            config=config,
            config_path=CONFIG,
            artifact_dir=tmp_path / "artifact",
            report_json=tmp_path / "report.json",
            report_markdown=tmp_path / "report.md",
            calibration_svg=tmp_path / "calibration.svg",
            finalize=True,
        )
