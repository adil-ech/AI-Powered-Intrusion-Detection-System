"""Command-line interface for raw-data integrity and audit operations."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
from typing import cast

from ids_ml.data.audit import audit_dataset, write_audit_reports
from ids_ml.data.catalog import load_catalog
from ids_ml.data.manifest import build_manifest, write_manifest


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


def main() -> int:
    """Parse command arguments and return a process exit status."""

    arguments = _build_parser().parse_args()
    if arguments.command == "manifest":
        return _run_manifest(arguments)
    return _run_audit(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
