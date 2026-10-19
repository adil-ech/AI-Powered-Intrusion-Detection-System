"""Command-line entry point for Phase 4 baseline reproduction."""

from __future__ import annotations

import argparse
from pathlib import Path

from ids_ml.data.labels import load_taxonomy
from ids_ml.evaluation.config import load_baseline_config
from ids_ml.evaluation.report import run_baseline_evaluation


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Train and evaluate frozen-split baselines")
    parser.add_argument("--processed-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--feature-contract", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--split-manifest", type=Path, required=True)
    parser.add_argument("--model-output", type=Path, required=True)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    parser.add_argument("--calibration-svg", type=Path, required=True)
    return parser


def main() -> int:
    """Train and evaluate all Phase 4 baselines."""

    arguments = _build_parser().parse_args()
    report = run_baseline_evaluation(
        processed_dir=arguments.processed_dir,
        feature_contract_path=arguments.feature_contract,
        taxonomy=load_taxonomy(arguments.labels),
        taxonomy_path=arguments.labels,
        split_manifest_path=arguments.split_manifest,
        model_output=arguments.model_output,
        report_json=arguments.json_output,
        report_markdown=arguments.markdown_output,
        calibration_svg=arguments.calibration_svg,
        config=load_baseline_config(arguments.config),
        config_path=arguments.config,
    )
    logistic = report["evaluation"]["validation"]["binary_logistic"]
    print(
        "Baseline evaluation PASSED: "
        f"validation logistic F1={logistic['f1']:.6f}, "
        "final test sealed"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
