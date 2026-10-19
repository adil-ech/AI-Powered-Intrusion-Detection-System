"""End-to-end Phase 5 selection and one-time finalization workflow."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import joblib
import numpy as np
from numpy.typing import NDArray
from sklearn.ensemble import RandomForestClassifier

from ids_ml.data.labels import LabelTaxonomy
from ids_ml.evaluation.data import load_required_features
from ids_ml.evaluation.metrics import evaluate_binary, evaluate_multiclass
from ids_ml.evaluation.models import BaselineBundle
from ids_ml.evaluation.report import _verify_processed_inputs
from ids_ml.modeling.artifact import (
    InferenceBundle,
    load_artifact,
    sha256_file,
    write_artifact,
)
from ids_ml.modeling.config import ForestCandidate, ModelSelectionConfig
from ids_ml.modeling.data import (
    MaterializedSplit,
    ValidationPartitions,
    build_validation_partitions,
    materialize_split,
)
from ids_ml.modeling.models import (
    BinaryPlattCalibrator,
    MulticlassTemperatureCalibrator,
    build_forest,
    calibrate_binary,
    calibrate_family,
    choose_feature_variant,
    evaluate_selected_models,
    select_binary_threshold,
    tune_binary_forest,
    tune_family_forest,
)


@dataclass
class VariantRun:
    binary_forest: RandomForestClassifier
    family_forest: RandomForestClassifier
    binary_model: BinaryPlattCalibrator
    family_model: MulticlassTemperatureCalibrator
    threshold: float
    calibration: dict[str, Any]
    selection: dict[str, Any]
    timing: dict[str, float]


def _load_json(path: Path) -> dict[str, Any]:
    raw: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return raw


def _sha256_json(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _split_rows(manifest: dict[str, Any], split: str) -> int:
    splits = manifest.get("splits")
    if not isinstance(splits, dict) or not isinstance(splits.get(split), dict):
        raise ValueError(f"split manifest is missing {split}")
    rows = splits[split].get("rows")
    if not isinstance(rows, int):
        raise ValueError(f"split manifest has invalid {split} row count")
    return rows


def _partition(split: MaterializedSplit, indexes: NDArray[np.int64]) -> MaterializedSplit:
    return MaterializedSplit(
        np.asarray(split.features[indexes], dtype=np.float32),
        np.asarray(split.binary_targets[indexes], dtype=np.uint8),
        np.asarray(split.category_ids[indexes], dtype=np.int8),
    )


def _fit_variant(
    train: MaterializedSplit,
    validation: MaterializedSplit,
    partitions: ValidationPartitions,
    binary_candidate: ForestCandidate,
    family_candidate: ForestCandidate,
    attack_labels: list[str],
    config: ModelSelectionConfig,
    *,
    variant: str,
    binary_forest: RandomForestClassifier | None = None,
    family_forest: RandomForestClassifier | None = None,
) -> VariantRun:
    timing: dict[str, float] = {}
    if binary_forest is None:
        binary_forest = build_forest(binary_candidate, random_seed=config.random_seed)
        started = time.perf_counter()
        binary_forest.fit(train.features, train.binary_targets)
        timing["binary_forest_fit"] = time.perf_counter() - started
    if family_forest is None:
        family_forest = build_forest(family_candidate, random_seed=config.random_seed)
        train_malicious = train.binary_targets == 1
        family_targets = np.asarray(train.category_ids[train_malicious], dtype=np.int64) - 1
        if np.any(family_targets < 0):
            raise ValueError("malicious training rows have invalid family targets")
        started = time.perf_counter()
        family_forest.fit(train.features[train_malicious], family_targets)
        timing["family_forest_fit"] = time.perf_counter() - started

    calibration = _partition(validation, partitions.calibration)
    started = time.perf_counter()
    binary_model = calibrate_binary(binary_forest, calibration.features, calibration.binary_targets)
    timing["binary_calibration_fit"] = time.perf_counter() - started
    started = time.perf_counter()
    family_model = calibrate_family(
        family_forest,
        calibration.features,
        calibration.binary_targets,
        calibration.category_ids,
    )
    timing["family_calibration_fit"] = time.perf_counter() - started
    calibration_probability = np.asarray(
        binary_model.predict_proba(calibration.features)[:, 1], dtype=np.float64
    )
    threshold, threshold_metrics = select_binary_threshold(
        calibration.binary_targets,
        calibration_probability,
        config,
        split="validation_calibration",
        model=f"random_forest_binary:{variant}",
    )
    calibration_metrics = evaluate_selected_models(
        binary_model,
        family_model,
        calibration.features,
        calibration.binary_targets,
        calibration.category_ids,
        attack_labels,
        threshold=threshold,
        split="validation_calibration",
        variant=variant,
    )
    calibration_metrics["threshold_selection"] = threshold_metrics
    calibration_metrics["parameters"] = {
        "binary_platt_coefficient": float(binary_model.calibrator.coef_[0, 0]),
        "binary_platt_intercept": float(binary_model.calibrator.intercept_[0]),
        "attack_family_temperature": family_model.temperature,
    }
    selection = _partition(validation, partitions.selection)
    selection_metrics = evaluate_selected_models(
        binary_model,
        family_model,
        selection.features,
        selection.binary_targets,
        selection.category_ids,
        attack_labels,
        threshold=threshold,
        split="validation_selection_holdout",
        variant=variant,
    )
    return VariantRun(
        binary_forest=binary_forest,
        family_forest=family_forest,
        binary_model=binary_model,
        family_model=family_model,
        threshold=threshold,
        calibration=calibration_metrics,
        selection=selection_metrics,
        timing=timing,
    )


def _evaluate_baselines(
    path: Path,
    features: NDArray[np.float32],
    binary_targets: NDArray[np.uint8],
    category_ids: NDArray[np.int8],
    attack_labels: list[str],
) -> dict[str, Any]:
    raw: object = joblib.load(path)
    if not isinstance(raw, BaselineBundle):
        raise ValueError("Phase 4 baseline artifact has an unexpected type")
    bundle = raw
    baseline_features = np.asarray(features, dtype=np.float64)
    dummy = np.asarray(bundle.binary_dummy.predict_proba(baseline_features)[:, 1], dtype=np.float64)
    logistic = np.asarray(
        bundle.binary_logistic.predict_proba(baseline_features)[:, 1], dtype=np.float64
    )
    malicious = binary_targets == 1
    prior = np.asarray(bundle.attack_family_prior.predict_proba(baseline_features[malicious]))
    names = np.asarray(attack_labels, dtype=np.str_)[
        np.asarray(category_ids[malicious], dtype=np.int64) - 1
    ]
    return {
        "binary_dummy": evaluate_binary(
            np.asarray(binary_targets, dtype=np.int64),
            dummy,
            threshold=0.5,
            split="validation_selection_holdout",
            model="binary_dummy_prior",
        ),
        "binary_logistic": evaluate_binary(
            np.asarray(binary_targets, dtype=np.int64),
            logistic,
            threshold=0.5,
            split="validation_selection_holdout",
            model="binary_logistic_sgd",
        ),
        "attack_family_prior": evaluate_multiclass(
            names,
            prior,
            labels=attack_labels,
            split="validation_selection_holdout_malicious_rows",
            model="attack_family_prior",
        ),
    }


def _acceptance(
    selected: dict[str, Any], baselines: dict[str, Any], config: ModelSelectionConfig
) -> dict[str, Any]:
    binary = selected["binary"]
    family = selected["attack_family"]
    checks = {
        "binary_f1_beats_dummy": float(binary["f1"]) > float(baselines["binary_dummy"]["f1"]),
        "binary_f1_beats_logistic": float(binary["f1"]) > float(baselines["binary_logistic"]["f1"]),
        "binary_recall_target": float(binary["recall"]) >= config.acceptance.minimum_binary_recall,
        "binary_false_positive_rate_target": float(binary["false_positive_rate"])
        <= config.acceptance.maximum_binary_false_positive_rate,
        "family_macro_f1_target": float(family["macro_f1"])
        >= config.acceptance.minimum_family_macro_f1,
        "family_macro_f1_beats_prior": float(family["macro_f1"])
        > float(baselines["attack_family_prior"]["macro_f1"]),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "targets": asdict(config.acceptance),
    }


def _versions() -> dict[str, str]:
    return {
        name: importlib.metadata.version(name)
        for name in ("joblib", "numpy", "scikit-learn", "scipy")
    }


def _write_report(
    report: dict[str, Any], json_path: Path, markdown_path: Path, svg_path: Path
) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(_markdown_report(report), encoding="utf-8")
    svg_path.parent.mkdir(parents=True, exist_ok=True)
    svg_path.write_text(_calibration_svg(report), encoding="utf-8")


def _verify_existing_artifact(
    artifact_dir: Path,
    report_json: Path,
    report_markdown: Path,
    calibration_svg: Path,
) -> dict[str, Any]:
    bundle, manifest = load_artifact(artifact_dir)
    metrics = _load_json(artifact_dir / "metrics.json")
    report = {
        **metrics,
        "status": "verified_existing_artifact",
        "artifact": {
            "path": artifact_dir.name,
            "manifest": manifest,
            "manifest_sha256": sha256_file(artifact_dir / "manifest.json"),
        },
        "final_test_reopened_for_predictions": False,
        "verified_model_version": bundle.model_version,
    }
    _write_report(report, report_json, report_markdown, calibration_svg)
    return report


def run_model_selection(
    *,
    base_processed_dir: Path,
    port_processed_dir: Path,
    base_feature_contract_path: Path,
    taxonomy: LabelTaxonomy,
    taxonomy_path: Path,
    baseline_artifact_path: Path,
    config: ModelSelectionConfig,
    config_path: Path,
    artifact_dir: Path,
    report_json: Path,
    report_markdown: Path,
    calibration_svg: Path,
    finalize: bool,
) -> dict[str, Any]:
    """Tune on one fold, calibrate on another, and select on a third."""

    if finalize and (artifact_dir / "manifest.json").is_file():
        return _verify_existing_artifact(
            artifact_dir, report_json, report_markdown, calibration_svg
        )
    if artifact_dir.exists() and any(artifact_dir.iterdir()):
        raise FileExistsError("incomplete Phase 5 artifact exists; refusing to overwrite it")
    if finalize and not config.selection_frozen:
        raise ValueError("selection must be frozen in config before final-test evaluation")

    base_features, base_schema_hash = load_required_features(base_feature_contract_path)
    base_manifest, base_hashes = _verify_processed_inputs(
        base_processed_dir,
        base_processed_dir / "split-manifest.json",
        base_schema_hash,
    )
    port_contract_path = port_processed_dir / "feature-schema.json"
    port_features, port_schema_hash = load_required_features(port_contract_path)
    port_manifest, port_hashes = _verify_processed_inputs(
        port_processed_dir,
        port_processed_dir / "split-manifest.json",
        port_schema_hash,
    )
    if port_manifest.get("same_rows_as_parent") is not True:
        raise ValueError("destination-port variant is not certified as the same rows")
    categories = list(taxonomy.categories)
    attack_labels = categories[1:]
    with tempfile.TemporaryDirectory(prefix="ids-model-selection-") as temporary:
        temp = Path(temporary)
        base_train = materialize_split(
            base_processed_dir / "train.csv.gz",
            base_features,
            categories,
            rows=_split_rows(base_manifest, "train"),
            batch_size=config.batch_size,
            directory=temp,
            name="base-train",
        )
        base_validation = materialize_split(
            base_processed_dir / "validation.csv.gz",
            base_features,
            categories,
            rows=_split_rows(base_manifest, "validation"),
            batch_size=config.batch_size,
            directory=temp,
            name="base-validation",
        )
        partitions = build_validation_partitions(
            base_processed_dir / "split-manifest.json",
            base_validation.category_ids,
            categories,
            random_seed=config.random_seed,
            fold_count=config.validation_folds,
        )
        tuning = _partition(base_validation, partitions.tuning)
        binary_forest, binary_candidate, binary_tuning = tune_binary_forest(
            base_train.features,
            base_train.binary_targets,
            tuning.features,
            tuning.binary_targets,
            config.binary_candidates,
            random_seed=config.random_seed,
        )
        family_forest, family_candidate, family_tuning = tune_family_forest(
            base_train.features,
            base_train.binary_targets,
            base_train.category_ids,
            tuning.features,
            tuning.binary_targets,
            tuning.category_ids,
            config.family_candidates,
            attack_labels,
            random_seed=config.random_seed,
        )
        without_port = _fit_variant(
            base_train,
            base_validation,
            partitions,
            binary_candidate,
            family_candidate,
            attack_labels,
            config,
            variant="without_destination_port",
            binary_forest=binary_forest,
            family_forest=family_forest,
        )

        port_train = materialize_split(
            port_processed_dir / "train.csv.gz",
            port_features,
            categories,
            rows=_split_rows(port_manifest, "train"),
            batch_size=config.batch_size,
            directory=temp,
            name="port-train",
        )
        port_validation = materialize_split(
            port_processed_dir / "validation.csv.gz",
            port_features,
            categories,
            rows=_split_rows(port_manifest, "validation"),
            batch_size=config.batch_size,
            directory=temp,
            name="port-validation",
        )
        if not np.array_equal(
            base_train.binary_targets, port_train.binary_targets
        ) or not np.array_equal(base_train.category_ids, port_train.category_ids):
            raise ValueError("destination-port training targets diverged from the base rows")
        if not np.array_equal(
            base_validation.binary_targets, port_validation.binary_targets
        ) or not np.array_equal(base_validation.category_ids, port_validation.category_ids):
            raise ValueError("destination-port validation targets diverged from the base rows")
        with_port = _fit_variant(
            port_train,
            port_validation,
            partitions,
            binary_candidate,
            family_candidate,
            attack_labels,
            config,
            variant="with_destination_port",
        )
        selected_variant, variant_decision = choose_feature_variant(
            without_port.selection, with_port.selection, config.variant_policy
        )
        selected_run = with_port if selected_variant == "with_destination_port" else without_port
        selection_partition = _partition(base_validation, partitions.selection)
        baselines = _evaluate_baselines(
            baseline_artifact_path,
            selection_partition.features,
            selection_partition.binary_targets,
            selection_partition.category_ids,
            attack_labels,
        )
        acceptance = _acceptance(selected_run.selection, baselines, config)
        report: dict[str, Any] = {
            "report_schema_version": "1.0.0",
            "phase": 5,
            "status": "selection_ready_not_finalized",
            "model_version": config.model_version,
            "model_selection_config_sha256": sha256_file(config_path),
            "random_seed": config.random_seed,
            "data": {
                "base_feature_schema_sha256": base_schema_hash,
                "port_feature_schema_sha256": port_schema_hash,
                "base_verified_split_sha256": base_hashes,
                "port_verified_split_sha256": port_hashes,
                "split_manifest_sha256": sha256_file(base_processed_dir / "split-manifest.json"),
                "validation_partitions": partitions.report,
                "final_test_opened_for_predictions": False,
            },
            "tuning": {
                "split": "validation_tuning",
                "binary_candidates": binary_tuning,
                "family_candidates": family_tuning,
                "selected_binary_candidate": binary_candidate.candidate_id,
                "selected_family_candidate": family_candidate.candidate_id,
            },
            "calibration": {
                "method": config.calibration_method,
                "split": "validation_calibration",
                "without_destination_port": without_port.calibration,
                "with_destination_port": with_port.calibration,
            },
            "feature_variant_comparison": {
                "split": "validation_selection_holdout",
                "same_rows": True,
                "without_destination_port": without_port.selection,
                "with_destination_port": with_port.selection,
                "decision": variant_decision,
            },
            "selection": {
                "feature_variant": selected_variant,
                "binary_candidate": binary_candidate.candidate_id,
                "family_candidate": family_candidate.candidate_id,
                "threshold": selected_run.threshold,
                "metrics": selected_run.selection,
                "baselines_same_rows": baselines,
                "acceptance": acceptance,
                "final_test_used_for_selection": False,
                "selection_lock_sha256": _sha256_json(
                    {
                        "feature_variant": selected_variant,
                        "binary_candidate": binary_candidate.candidate_id,
                        "family_candidate": family_candidate.candidate_id,
                        "threshold": selected_run.threshold,
                        "config_sha256": sha256_file(config_path),
                    }
                ),
            },
            "final_test": {
                "status": "sealed_not_evaluated",
                "reason": "Selection-only run; finalization requires a matching committed freeze.",
            },
            "timing_seconds": {
                "without_destination_port": without_port.timing,
                "with_destination_port": with_port.timing,
            },
            "environment": {
                "python": platform.python_version(),
                "platform": platform.platform(),
                "libraries": _versions(),
            },
        }
        if not acceptance["passed"]:
            _write_report(report, report_json, report_markdown, calibration_svg)
            raise ValueError("Phase 5 model acceptance targets were not met on selection holdout")
        if not finalize:
            _write_report(report, report_json, report_markdown, calibration_svg)
            return report
        assert config.frozen_selection is not None
        actual_selection = (
            selected_variant,
            binary_candidate.candidate_id,
            family_candidate.candidate_id,
        )
        expected_selection = (
            config.frozen_selection.feature_variant,
            config.frozen_selection.binary_candidate,
            config.frozen_selection.family_candidate,
        )
        if actual_selection != expected_selection:
            raise ValueError(
                f"computed selection {actual_selection} differs from frozen {expected_selection}"
            )

        selected_processed = (
            port_processed_dir
            if selected_variant == "with_destination_port"
            else base_processed_dir
        )
        selected_features = (
            port_features if selected_variant == "with_destination_port" else base_features
        )
        selected_manifest = (
            port_manifest if selected_variant == "with_destination_port" else base_manifest
        )
        selected_contract = (
            port_contract_path
            if selected_variant == "with_destination_port"
            else base_feature_contract_path
        )
        final_split = materialize_split(
            selected_processed / "final_test.csv.gz",
            selected_features,
            categories,
            rows=_split_rows(selected_manifest, "final_test"),
            batch_size=config.batch_size,
            directory=temp,
            name="selected-final-test",
        )
        final_started = time.perf_counter()
        final_metrics = evaluate_selected_models(
            selected_run.binary_model,
            selected_run.family_model,
            final_split.features,
            final_split.binary_targets,
            final_split.category_ids,
            attack_labels,
            threshold=selected_run.threshold,
            split="final_test",
            variant=selected_variant,
        )
        final_inference_seconds = time.perf_counter() - final_started
        state = _load_json(selected_processed / "preprocessing-state.json")
        imputation = cast(dict[str, float], state["imputation_values"])
        feature_contract = _load_json(selected_contract)
        bundle = InferenceBundle(
            artifact_schema_version="1.0.0",
            model_version=config.model_version,
            feature_schema_version=str(feature_contract["feature_schema_version"]),
            feature_schema_hash=str(feature_contract["feature_schema_sha256"]),
            required_features=tuple(selected_features),
            imputation_values=tuple(float(imputation[name]) for name in selected_features),
            attack_labels=tuple(attack_labels),
            malicious_threshold=selected_run.threshold,
            low_confidence_threshold=config.low_confidence_threshold,
            high_risk_threshold=config.high_risk_threshold,
            binary_model=selected_run.binary_model,
            attack_family_model=selected_run.family_model,
        )
        created_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        metadata = {
            "artifact_schema_version": bundle.artifact_schema_version,
            "model_name": "cicids2017-two-stage-random-forest",
            "model_version": bundle.model_version,
            "created_at": created_at,
            "training_dataset": "CIC-IDS2017",
            "source_manifest_sha256": base_manifest["source_manifest_sha256"],
            "split_manifest_sha256": sha256_file(base_processed_dir / "split-manifest.json"),
            "preprocessing_state_sha256": sha256_file(
                selected_processed / "preprocessing-state.json"
            ),
            "feature_schema_version": bundle.feature_schema_version,
            "feature_schema_hash": bundle.feature_schema_hash,
            "required_features": list(bundle.required_features),
            "attack_categories": ["BENIGN", *attack_labels],
            "feature_variant": selected_variant,
            "selected_candidates": {
                "binary": asdict(binary_candidate),
                "attack_family": asdict(family_candidate),
            },
            "thresholds": {
                "malicious": selected_run.threshold,
                "low_confidence": config.low_confidence_threshold,
                "high_risk": config.high_risk_threshold,
            },
            "calibration_method": config.calibration_method,
            "random_seed": config.random_seed,
            "library_versions": _versions(),
            "final_test_metrics": final_metrics,
        }
        artifact_metrics = {
            **report,
            "status": "passed",
            "data": {
                **report["data"],
                "final_test_opened_for_predictions": True,
            },
            "final_test": {
                "status": "evaluated_once_after_selection_freeze",
                "metrics": final_metrics,
                "inference_seconds": final_inference_seconds,
                "rows_per_second": (
                    final_split.features.shape[0] / final_inference_seconds
                    if final_inference_seconds > 0
                    else None
                ),
            },
        }
        manifest = write_artifact(
            artifact_dir,
            bundle,
            metadata=metadata,
            metrics=artifact_metrics,
            feature_schema_path=selected_contract,
            label_taxonomy_path=taxonomy_path,
        )
        reloaded, _ = load_artifact(artifact_dir)
        parity_partition = (
            _partition(port_validation, partitions.selection)
            if selected_variant == "with_destination_port"
            else selection_partition
        )
        parity_rows = min(8192, parity_partition.features.shape[0])
        parity_features = np.asarray(parity_partition.features[:parity_rows], dtype=np.float32)
        original_probabilities = bundle.predict_probabilities(parity_features, selected_features)
        reloaded_probabilities = reloaded.predict_probabilities(parity_features, selected_features)
        parity = {
            "rows": parity_rows,
            "absolute_tolerance": 1e-12,
            "binary": bool(
                np.allclose(
                    original_probabilities[0],
                    reloaded_probabilities[0],
                    rtol=1e-12,
                    atol=1e-12,
                )
            ),
            "attack_family": bool(
                np.allclose(
                    original_probabilities[1],
                    reloaded_probabilities[1],
                    rtol=1e-12,
                    atol=1e-12,
                )
            ),
        }
        if not parity["binary"] or not parity["attack_family"]:
            raise ValueError("serialized Phase 5 artifact changed predictions")
        report = {
            **artifact_metrics,
            "artifact": {
                "path": artifact_dir.name,
                "manifest": manifest,
                "manifest_sha256": sha256_file(artifact_dir / "manifest.json"),
                "serialization_parity": parity,
            },
            "final_test_reopened_for_predictions": False,
        }
        _write_report(report, report_json, report_markdown, calibration_svg)
        return report


def _metric(value: object) -> str:
    return "not defined" if value is None else f"{float(cast(float, value)):.6f}"


def _markdown_report(report: dict[str, Any]) -> str:
    selection = report["selection"]
    binary = selection["metrics"]["binary"]
    family = selection["metrics"]["attack_family"]
    lines = [
        "# Phase 5 model selection",
        "",
        f"- Status: **{str(report['status']).upper()}**",
        f"- Model version: `{report['model_version']}`",
        f"- Selected feature variant: `{selection['feature_variant']}`",
        f"- Selected binary candidate: `{selection['binary_candidate']}`",
        f"- Selected family candidate: `{selection['family_candidate']}`",
        f"- Malicious threshold: `{selection['threshold']}`",
        f"- Selection acceptance: **{'PASS' if selection['acceptance']['passed'] else 'FAIL'}**",
        "",
        "## Selection-holdout metrics",
        "",
        "| Binary precision | Recall | F1 | PR AUC | ROC AUC | FPR | FNR |",
        "|---:|---:|---:|---:|---:|---:|---:|",
        f"| {_metric(binary['precision'])} | {_metric(binary['recall'])} | "
        f"{_metric(binary['f1'])} | {_metric(binary['pr_auc'])} | "
        f"{_metric(binary['roc_auc'])} | {_metric(binary['false_positive_rate'])} | "
        f"{_metric(binary['false_negative_rate'])} |",
        "",
        f"- Attack-family macro F1: {_metric(family['macro_f1'])}",
        f"- Attack-family weighted F1: {_metric(family['weighted_f1'])}",
        "",
        "## Final-test boundary",
        "",
        f"- Status: **{report['final_test']['status']}**",
    ]
    if "metrics" in report["final_test"]:
        final_binary = report["final_test"]["metrics"]["binary"]
        final_family = report["final_test"]["metrics"]["attack_family"]
        lines.extend(
            [
                f"- Binary recall: {_metric(final_binary['recall'])}",
                f"- Binary F1: {_metric(final_binary['f1'])}",
                f"- Binary false-positive rate: {_metric(final_binary['false_positive_rate'])}",
                f"- Attack-family macro F1: {_metric(final_family['macro_f1'])}",
            ]
        )
    else:
        lines.append(f"- Reason: {report['final_test']['reason']}")
    return "\n".join(lines) + "\n"


def _calibration_svg(report: dict[str, Any]) -> str:
    bins = report["selection"]["metrics"]["binary"]["calibration"]["reliability_bins"]
    left, top, size = 70.0, 45.0, 300.0
    points = [
        (
            left + float(item["mean_probability"]) * size,
            top + size - float(item["observed_frequency"]) * size,
        )
        for item in bins
        if item["mean_probability"] is not None and item["observed_frequency"] is not None
    ]
    elements = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="520" height="430" viewBox="0 0 520 430">',
        '<rect width="520" height="430" fill="#0b1020"/>',
        (
            '<text x="70" y="26" fill="#f2f5ff" font-family="system-ui" '
            'font-size="18">Selected model reliability</text>'
        ),
        (
            f'<line x1="{left}" y1="{top + size}" x2="{left + size}" y2="{top}" '
            'stroke="#718096" stroke-dasharray="5 5"/>'
        ),
        f'<rect x="{left}" y="{top}" width="{size}" height="{size}" fill="none" stroke="#718096"/>',
    ]
    if points:
        path = " ".join(
            f"{'M' if index == 0 else 'L'} {x:.2f} {y:.2f}" for index, (x, y) in enumerate(points)
        )
        elements.append(f'<path d="{path}" fill="none" stroke="#22d3a6" stroke-width="3"/>')
        elements.extend(
            f'<circle cx="{x:.2f}" cy="{y:.2f}" r="4" fill="#22d3a6"/>' for x, y in points
        )
    elements.extend(
        [
            (
                '<text x="220" y="395" text-anchor="middle" fill="#aab4cf" '
                'font-family="system-ui" font-size="12">Mean predicted probability</text>'
            ),
            (
                '<text x="18" y="205" transform="rotate(-90 18 205)" '
                'text-anchor="middle" fill="#aab4cf" font-family="system-ui" '
                'font-size="12">Observed malicious frequency</text>'
            ),
            "</svg>",
        ]
    )
    return "\n".join(elements) + "\n"
