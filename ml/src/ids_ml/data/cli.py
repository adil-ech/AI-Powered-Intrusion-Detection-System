"""Command-line interface for raw-data integrity and audit operations."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
from typing import cast

from ids_ml.data.audit import audit_dataset, write_audit_reports
from ids_ml.data.catalog import load_catalog
from ids_ml.data.labels import load_taxonomy
from ids_ml.data.manifest import build_manifest, write_manifest
from ids_ml.data.preprocess import load_preprocessing_config, run_preprocessing


def _path(value: str) -> Path:
    return Path(value)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CIC-IDS2017 data integrity and audit tools")
    subparsers = parser.add_subparsers(dest="command", required=True)

    manifest = subparsers.add_parser("manifest", help="record local raw CSV checksums")
    manifest.add_argument("--raw-dir", type=_path, required=True)
    manifest.add_argument("--catalog", type=_path, required=True)
    manifest.add_argument("--retrieved-at", required=True)
    manifest.add_argument("--output", type=_path, required=True)

    audit = subparsers.add_parser("audit", help="verify and audit the complete raw dataset")
    audit.add_argument("--raw-dir", type=_path, required=True)
    audit.add_argument("--catalog", type=_path, required=True)
    audit.add_argument("--manifest", type=_path, required=True)
    audit.add_argument("--labels", type=_path, required=True)
    audit.add_argument("--json-output", type=_path, required=True)
    audit.add_argument("--markdown-output", type=_path, required=True)

    preprocess = subparsers.add_parser(
        "preprocess", help="build deterministic, leak-resistant model inputs"
    )
    preprocess.add_argument("--raw-dir", type=_path, required=True)
    preprocess.add_argument("--catalog", type=_path, required=True)
    preprocess.add_argument("--manifest", type=_path, required=True)
    preprocess.add_argument("--labels", type=_path, required=True)
    preprocess.add_argument("--config", type=_path, required=True)
    preprocess.add_argument("--output-dir", type=_path, required=True)
    contract = preprocess.add_mutually_exclusive_group(required=True)
    contract.add_argument("--feature-contract", type=_path)
    contract.add_argument("--write-feature-contract", type=_path)
    preprocess.add_argument("--json-output", type=_path, required=True)
    preprocess.add_argument("--markdown-output", type=_path, required=True)
    return parser


def _run_manifest(arguments: argparse.Namespace) -> int:
    retrieved_at = str(arguments.retrieved_at)
    date.fromisoformat(retrieved_at)
    catalog = load_catalog(arguments.catalog)
    manifest = build_manifest(arguments.raw_dir, catalog, retrieved_at)
    write_manifest(manifest, arguments.output)
    files = cast(list[dict[str, object]], manifest["files"])
    print(f"Recorded {len(files)} source files in {arguments.output}")
    return 0


def _run_audit(arguments: argparse.Namespace) -> int:
    catalog = load_catalog(arguments.catalog)
    report = audit_dataset(arguments.raw_dir, catalog, arguments.manifest, arguments.labels)
    write_audit_reports(report, arguments.json_output, arguments.markdown_output)
    summary = cast(dict[str, object], report["summary"])
    coverage = cast(dict[str, object], report["coverage"])
    print(
        f"Dataset audit {str(report['status']).upper()}: "
        f"{summary['rows']} rows across {coverage['found_files']} files"
    )
    if report["status"] == "passed":
        return 0
    return 2 if report["status"] == "incomplete" else 1


def _run_preprocess(arguments: argparse.Namespace) -> int:
    report = run_preprocessing(
        raw_dir=arguments.raw_dir,
        catalog=load_catalog(arguments.catalog),
        manifest_path=arguments.manifest,
        taxonomy=load_taxonomy(arguments.labels),
        taxonomy_path=arguments.labels,
        config=load_preprocessing_config(arguments.config),
        config_path=arguments.config,
        output_dir=arguments.output_dir,
        feature_contract_path=arguments.feature_contract,
        feature_contract_output=arguments.write_feature_contract,
        report_json=arguments.json_output,
        report_markdown=arguments.markdown_output,
    )
    splits = cast(dict[str, dict[str, int]], report["splits"])
    selection = cast(dict[str, object], report["feature_selection"])
    rows = sum(split["rows"] for split in splits.values())
    print(
        f"Preprocessing {str(report['status']).upper()}: {rows} unique rows, "
        f"{selection['selected_count']} features"
    )
    return 0


def main() -> int:
    """Parse command arguments and return a process exit status."""

    arguments = _build_parser().parse_args()
    if arguments.command == "manifest":
        return _run_manifest(arguments)
    if arguments.command == "audit":
        return _run_audit(arguments)
    return _run_preprocess(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
