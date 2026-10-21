#!/usr/bin/env python3
"""Verify clean-checkout and artifact identity requirements for the release gate."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from scripts.benchmark_phase10 import _artifact_metadata

EXPECTED_MANIFEST_SHA256 = "dfa7678b89009aa03af89957dde958af20af6f969decdd295ba7209eaa6c3601"
EXPECTED_MODEL_VERSION = "ids-rf-v1.0.0"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--model-dir", type=Path)
    return parser.parse_args()


def main() -> int:
    arguments = _arguments()
    project_root = arguments.project_root.resolve()
    status = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=normal"],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    if status:
        raise RuntimeError("release verification requires a clean committed checkout")

    configured_model = os.environ.get("IDS_MODEL_HOST_DIR")
    model_source = arguments.model_dir or (
        Path(configured_model) if configured_model else project_root / "models/ids-rf-v1"
    )
    metadata = _artifact_metadata(model_source.resolve())
    if metadata["model_version"] != EXPECTED_MODEL_VERSION:
        raise ValueError("release model version does not match the documented version")
    if metadata["manifest_sha256"] != EXPECTED_MANIFEST_SHA256:
        raise ValueError("release model manifest does not match the documented artifact")

    tracked = subprocess.run(
        ["git", "ls-files"],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    forbidden = [
        path
        for path in tracked
        if path.startswith(("data/raw/", "data/processed/", "models/", "reports/generated/"))
        and not path.endswith("README.md")
    ]
    if forbidden:
        raise RuntimeError("release tracks generated or private files: " + ", ".join(forbidden))

    print(
        "Release verification passed: checkout clean, repository boundary clear, "
        f"and {EXPECTED_MODEL_VERSION} manifest identity verified."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, RuntimeError, ValueError) as error:
        print(f"Release verification failed: {error}", file=sys.stderr)
        raise SystemExit(1) from None
