"""Command-line entry point for Phase 5 selection and finalization."""

from __future__ import annotations

import argparse
from pathlib import Path

from ids_ml.data.labels import load_taxonomy
from ids_ml.modeling.config import load_model_selection_config
from ids_ml.modeling.pipeline import run_model_selection


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-processed-dir", type=Path, required=True)
    parser.add_argument("--port-processed-dir", type=Path, required=True)
    parser.add_argument("--feature-contract", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--baseline-artifact", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    parser.add_argument("--calibration-svg", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--selection-only", action="store_true")
    mode.add_argument("--finalize", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    report = run_model_selection(
        base_processed_dir=args.base_processed_dir,
        port_processed_dir=args.port_processed_dir,
        base_feature_contract_path=args.feature_contract,
        taxonomy=load_taxonomy(args.labels),
        taxonomy_path=args.labels,
        baseline_artifact_path=args.baseline_artifact,
        config=load_model_selection_config(args.config),
        config_path=args.config,
        artifact_dir=args.artifact_dir,
        report_json=args.json_output,
        report_markdown=args.markdown_output,
        calibration_svg=args.calibration_svg,
        finalize=bool(args.finalize),
    )
    print(
        "Phase 5 "
        f"{report['status']}: variant={report['selection']['feature_variant']}, "
        f"selection F1={report['selection']['metrics']['binary']['f1']:.6f}, "
        f"final={report['final_test']['status']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
