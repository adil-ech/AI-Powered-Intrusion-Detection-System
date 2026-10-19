"""Command-line entry point for the same-row destination-port diagnostic."""

from __future__ import annotations

import argparse
from pathlib import Path

from ids_ml.data.catalog import load_catalog
from ids_ml.data.labels import load_taxonomy
from ids_ml.data.preprocess import load_preprocessing_config
from ids_ml.evaluation.data import load_required_features
from ids_ml.evaluation.report import _verify_processed_inputs
from ids_ml.modeling.port_variant import build_destination_port_variant


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--preprocessing-config", type=Path, required=True)
    parser.add_argument("--base-processed-dir", type=Path, required=True)
    parser.add_argument("--base-feature-contract", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    manifest = args.output_dir / "split-manifest.json"
    feature_contract = args.output_dir / "feature-schema.json"
    if manifest.is_file() and feature_contract.is_file():
        _, schema_hash = load_required_features(feature_contract)
        loaded, _ = _verify_processed_inputs(args.output_dir, manifest, schema_hash)
        if loaded.get("same_rows_as_parent") is not True:
            raise ValueError("cached destination-port variant has no same-row certification")
        print("Destination-port diagnostic verified: cached same-row variant is valid")
        return 0
    report = build_destination_port_variant(
        raw_dir=args.raw_dir,
        catalog=load_catalog(args.catalog),
        taxonomy=load_taxonomy(args.labels),
        preprocessing_config=load_preprocessing_config(args.preprocessing_config),
        preprocessing_config_path=args.preprocessing_config,
        base_processed_dir=args.base_processed_dir,
        base_feature_contract_path=args.base_feature_contract,
        output_dir=args.output_dir,
        report_path=args.report,
    )
    print(
        "Destination-port diagnostic PASSED: "
        f"same_rows={report['same_rows_as_parent']}, "
        f"schema={report['feature_schema_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
