"""Train baselines, evaluate validation data, and write reproducible evidence."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import time
from pathlib import Path
from typing import Any, cast

import joblib
import numpy as np
from numpy.typing import NDArray

from ids_ml.data.labels import LabelTaxonomy
from ids_ml.evaluation.config import BaselineConfig
from ids_ml.evaluation.data import iter_processed_batches, load_required_features
from ids_ml.evaluation.metrics import evaluate_binary, evaluate_multiclass
from ids_ml.evaluation.models import BaselineBundle, fit_baselines


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    raw: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return raw


def _verify_processed_inputs(
    processed_dir: Path,
    split_manifest_path: Path,
    feature_schema_hash: str,
) -> tuple[dict[str, Any], dict[str, str]]:
    manifest = _load_json(split_manifest_path)
    if manifest.get("feature_schema_sha256") != feature_schema_hash:
        raise ValueError("split manifest and feature contract hashes do not match")
    splits = manifest.get("splits")
    if not isinstance(splits, dict):
        raise ValueError("split manifest must define splits")
    verified: dict[str, str] = {}
    for split in ("train", "validation", "final_test"):
        item = splits.get(split)
        if not isinstance(item, dict):
            raise ValueError(f"split manifest is missing {split}")
        filename = item.get("path")
        expected_hash = item.get("sha256")
        if not isinstance(filename, str) or not isinstance(expected_hash, str):
            raise ValueError(f"split manifest has invalid {split} metadata")
        path = processed_dir / filename
        actual_hash = _sha256_file(path)
        if actual_hash != expected_hash:
            raise ValueError(f"processed {split} hash does not match the split manifest")
        verified[split] = actual_hash
    return manifest, verified


def _sealed_final_test() -> dict[str, str]:
    return {
        "status": "sealed_not_evaluated",
        "reason": (
            "Final-test predictions remain unopened until Phase 5 freezes model, "
            "feature variant, calibration, and threshold selection."
        ),
    }


def _evaluate_validation(
    bundle: BaselineBundle,
    validation_path: Path,
    required_features: list[str],
    *,
    batch_size: int,
    threshold: float,
) -> tuple[dict[str, Any], dict[str, Any], NDArray[np.float64]]:
    targets: list[NDArray[np.int64]] = []
    dummy_probabilities: list[NDArray[np.float64]] = []
    logistic_probabilities: list[NDArray[np.float64]] = []
    family_targets: list[NDArray[np.str_]] = []
    family_probabilities: list[NDArray[np.float64]] = []
    inference_seconds = {
        "binary_dummy": 0.0,
        "binary_logistic": 0.0,
        "attack_family_prior": 0.0,
    }
    parity_features: NDArray[np.float64] | None = None
    for batch in iter_processed_batches(validation_path, required_features, batch_size=batch_size):
        if parity_features is None:
            parity_features = batch.features.copy()
        targets.append(batch.binary_targets)

        started = time.perf_counter()
        dummy_probability = bundle.binary_dummy.predict_proba(batch.features)[:, 1]
        inference_seconds["binary_dummy"] += time.perf_counter() - started
        dummy_probabilities.append(dummy_probability)

        started = time.perf_counter()
        logistic_probability = bundle.binary_logistic.predict_proba(batch.features)[:, 1]
        inference_seconds["binary_logistic"] += time.perf_counter() - started
        logistic_probabilities.append(logistic_probability)

        malicious = batch.binary_targets == 1
        if np.any(malicious):
            malicious_features = batch.features[malicious]
            started = time.perf_counter()
            family_probability = bundle.attack_family_prior.predict_proba(malicious_features)
            inference_seconds["attack_family_prior"] += time.perf_counter() - started
            family_probabilities.append(family_probability)
            family_targets.append(batch.categories[malicious])

    if parity_features is None:
        raise ValueError("validation split is empty")
    binary_targets = np.concatenate(targets)
    dummy_probability = np.concatenate(dummy_probabilities)
    logistic_probability = np.concatenate(logistic_probabilities)
    attack_targets = np.concatenate(family_targets)
    attack_probabilities = np.concatenate(family_probabilities)
    evaluation = {
        "binary_dummy": evaluate_binary(
            binary_targets,
            dummy_probability,
            threshold=threshold,
            split="validation",
            model="binary_dummy_prior",
        ),
        "binary_logistic": evaluate_binary(
            binary_targets,
            logistic_probability,
            threshold=threshold,
            split="validation",
            model="binary_logistic_sgd",
        ),
        "attack_family_prior": evaluate_multiclass(
            attack_targets,
            attack_probabilities,
            labels=list(bundle.attack_labels),
            split="validation_malicious_rows",
            model="attack_family_prior",
        ),
    }
    inference = {
        name: {
            "seconds": seconds,
            "rows": (
                int(attack_targets.size)
                if name == "attack_family_prior"
                else int(binary_targets.size)
            ),
            "rows_per_second": (
                (attack_targets.size if name == "attack_family_prior" else binary_targets.size)
                / seconds
                if seconds > 0
                else None
            ),
        }
        for name, seconds in inference_seconds.items()
    }
    return evaluation, inference, parity_features


def _serialization_parity(
    original: BaselineBundle,
    reloaded: BaselineBundle,
    features: NDArray[np.float64],
) -> dict[str, Any]:
    comparisons = {
        "binary_dummy": np.allclose(
            original.binary_dummy.predict_proba(features),
            reloaded.binary_dummy.predict_proba(features),
            rtol=0.0,
            atol=0.0,
        ),
        "binary_logistic": np.allclose(
            original.binary_logistic.predict_proba(features),
            reloaded.binary_logistic.predict_proba(features),
            rtol=1e-12,
            atol=1e-12,
        ),
        "attack_family_prior": np.allclose(
            original.attack_family_prior.predict_proba(features),
            reloaded.attack_family_prior.predict_proba(features),
            rtol=0.0,
            atol=0.0,
        ),
    }
    if not all(comparisons.values()):
        failed = ", ".join(name for name, passed in comparisons.items() if not passed)
        raise ValueError(f"serialized baseline prediction parity failed: {failed}")
    return {
        "rows_checked": int(features.shape[0]),
        "absolute_tolerance": 1e-12,
        "relative_tolerance": 1e-12,
        "models": comparisons,
    }


def _library_versions() -> dict[str, str]:
    return {
        name: importlib.metadata.version(name)
        for name in ("joblib", "numpy", "scikit-learn", "scipy")
    }


def run_baseline_evaluation(
    *,
    processed_dir: Path,
    feature_contract_path: Path,
    taxonomy: LabelTaxonomy,
    taxonomy_path: Path,
    split_manifest_path: Path,
    model_output: Path,
    report_json: Path,
    report_markdown: Path,
    calibration_svg: Path,
    config: BaselineConfig,
    config_path: Path,
) -> dict[str, Any]:
    """Create the complete Phase 4 validation-only baseline evidence bundle."""

    required_features, feature_schema_hash = load_required_features(feature_contract_path)
    split_manifest, verified_hashes = _verify_processed_inputs(
        processed_dir, split_manifest_path, feature_schema_hash
    )
    attack_labels = [category for category in taxonomy.categories if category != "BENIGN"]
    train_path = processed_dir / "train.csv.gz"
    validation_path = processed_dir / "validation.csv.gz"
    bundle, training = fit_baselines(
        train_path,
        required_features,
        attack_labels,
        random_seed=config.random_seed,
        batch_size=config.batch_size,
    )
    evaluation, inference, parity_features = _evaluate_validation(
        bundle,
        validation_path,
        required_features,
        batch_size=config.batch_size,
        threshold=config.binary_threshold,
    )

    model_output.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, model_output, compress=3)
    reloaded_raw: object = joblib.load(model_output)
    if not isinstance(reloaded_raw, BaselineBundle):
        raise ValueError("reloaded baseline artifact has an unexpected type")
    parity = _serialization_parity(bundle, reloaded_raw, parity_features)
    model_hash = _sha256_file(model_output)
    manifest_splits = cast(dict[str, dict[str, Any]], split_manifest["splits"])
    final_test = _sealed_final_test()
    report: dict[str, Any] = {
        "report_schema_version": "1.0.0",
        "status": "passed",
        "phase": 4,
        "baseline_version": config.baseline_version,
        "baseline_config_sha256": _sha256_file(config_path),
        "random_seed": config.random_seed,
        "data": {
            "feature_schema_sha256": feature_schema_hash,
            "feature_contract_sha256": _sha256_file(feature_contract_path),
            "label_taxonomy_sha256": _sha256_file(taxonomy_path),
            "split_manifest_sha256": _sha256_file(split_manifest_path),
            "verified_split_file_sha256": verified_hashes,
            "train_rows": training["train_rows"],
            "validation_rows": manifest_splits["validation"]["rows"],
            "final_test_rows": manifest_splits["final_test"]["rows"],
            "final_test_opened_for_predictions": False,
        },
        "training": training,
        "evaluation": {
            "validation": evaluation,
            "final_test": final_test,
        },
        "comparison": {
            "split": "validation",
            "same_rows": True,
            "threshold": config.binary_threshold,
            "logistic_minus_dummy": {
                metric: evaluation["binary_logistic"][metric] - evaluation["binary_dummy"][metric]
                for metric in ("precision", "recall", "f1", "pr_auc", "roc_auc")
            },
            "accuracy_is_secondary": True,
        },
        "inference": inference,
        "artifact": {
            "path": model_output.name,
            "bytes": model_output.stat().st_size,
            "sha256": model_hash,
            "serialization_parity": parity,
        },
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "libraries": _library_versions(),
        },
        "selection": {
            "status": "baselines_only_no_final_model_selected",
            "final_test_used_for_selection": False,
        },
    }
    report_json.parent.mkdir(parents=True, exist_ok=True)
    report_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_markdown.parent.mkdir(parents=True, exist_ok=True)
    report_markdown.write_text(_markdown_report(report), encoding="utf-8")
    calibration_svg.parent.mkdir(parents=True, exist_ok=True)
    calibration_svg.write_text(_calibration_svg(report), encoding="utf-8")
    return report


def _metric(value: object) -> str:
    return "not defined" if value is None else f"{float(cast(float, value)):.6f}"


def _markdown_report(report: dict[str, Any]) -> str:
    validation = report["evaluation"]["validation"]
    dummy = validation["binary_dummy"]
    logistic = validation["binary_logistic"]
    family = validation["attack_family_prior"]
    lines = [
        "# Phase 4 baseline evaluation",
        "",
        "- Status: **PASSED**",
        "- Headline split: **validation**",
        f"- Binary threshold: `{report['comparison']['threshold']}` "
        "(fixed baseline threshold, not tuned)",
        "- Final test: **SEALED — NOT EVALUATED**",
        "",
        "## Binary validation metrics",
        "",
        "| Model | Precision | Recall | F1 | PR AUC | ROC AUC | FPR | FNR |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, metrics in (("Dummy prior", dummy), ("Logistic SGD", logistic)):
        lines.append(
            f"| {name} | {_metric(metrics['precision'])} | {_metric(metrics['recall'])} | "
            f"{_metric(metrics['f1'])} | {_metric(metrics['pr_auc'])} | "
            f"{_metric(metrics['roc_auc'])} | {_metric(metrics['false_positive_rate'])} | "
            f"{_metric(metrics['false_negative_rate'])} |"
        )
    lines.extend(
        [
            "",
            "## Attack-family prior validation metrics",
            "",
            f"- Macro F1 over observed validation classes: {_metric(family['macro_f1'])}",
            f"- Weighted F1: {_metric(family['weighted_f1'])}",
            f"- Log loss: {_metric(family['calibration']['log_loss'])}",
            "",
            "| Category | Precision | Recall | F1 | Support |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for label in family["label_order"]:
        item = family["per_class"][label]
        lines.append(
            f"| {label} | {_metric(item['precision'])} | {_metric(item['recall'])} | "
            f"{_metric(item['f1'])} | {item['support']} |"
        )
    lines.extend(
        [
            "",
            "## Evaluation boundary",
            "",
            report["evaluation"]["final_test"]["reason"],
            "The artifact is a baseline bundle, not a selected production model.",
        ]
    )
    return "\n".join(lines) + "\n"


def _calibration_svg(report: dict[str, Any]) -> str:
    validation = report["evaluation"]["validation"]
    series = [
        (
            "Dummy prior",
            "#8c6ff0",
            validation["binary_dummy"]["calibration"]["reliability_bins"],
        ),
        (
            "Logistic SGD",
            "#00a896",
            validation["binary_logistic"]["calibration"]["reliability_bins"],
        ),
    ]
    left, top, size = 70.0, 45.0, 300.0
    elements = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="430" viewBox="0 0 640 430">',
        '<rect width="640" height="430" fill="#0b1020"/>',
        (
            '<text x="70" y="26" fill="#f2f5ff" font-family="system-ui" '
            'font-size="18">Binary validation reliability</text>'
        ),
        (
            f'<line x1="{left}" y1="{top + size}" x2="{left + size}" '
            f'y2="{top}" stroke="#718096" stroke-dasharray="5 5"/>'
        ),
        f'<rect x="{left}" y="{top}" width="{size}" height="{size}" fill="none" stroke="#718096"/>',
    ]
    for tick in range(6):
        value = tick / 5
        x = left + value * size
        y = top + size - value * size
        elements.extend(
            [
                (
                    f'<text x="{x}" y="{top + size + 22}" text-anchor="middle" '
                    f'fill="#aab4cf" font-family="system-ui" font-size="11">'
                    f"{value:.1f}</text>"
                ),
                (
                    f'<text x="{left - 12}" y="{y + 4}" text-anchor="end" '
                    f'fill="#aab4cf" font-family="system-ui" font-size="11">'
                    f"{value:.1f}</text>"
                ),
            ]
        )
    for series_index, (name, color, bins) in enumerate(series):
        points: list[str] = []
        for item in bins:
            if item["count"] and item["mean_probability"] is not None:
                x = left + float(item["mean_probability"]) * size
                y = top + size - float(item["observed_frequency"]) * size
                points.append(f"{x:.2f},{y:.2f}")
        if points:
            elements.append(
                f'<polyline points="{" ".join(points)}" fill="none" '
                f'stroke="{color}" stroke-width="2.5"/>'
            )
        legend_y = 75 + series_index * 30
        elements.extend(
            [
                (
                    f'<line x1="420" y1="{legend_y}" x2="455" y2="{legend_y}" '
                    f'stroke="{color}" stroke-width="3"/>'
                ),
                (
                    f'<text x="465" y="{legend_y + 4}" fill="#f2f5ff" '
                    f'font-family="system-ui" font-size="13">{name}</text>'
                ),
            ]
        )
    elements.extend(
        [
            (
                '<text x="220" y="410" text-anchor="middle" fill="#dce3f5" '
                'font-family="system-ui" font-size="13">'
                "Mean predicted malicious probability</text>"
            ),
            (
                '<text x="18" y="195" text-anchor="middle" '
                'transform="rotate(-90 18 195)" fill="#dce3f5" '
                'font-family="system-ui" font-size="13">'
                "Observed malicious frequency</text>"
            ),
            "</svg>",
        ]
    )
    return "\n".join(elements) + "\n"
