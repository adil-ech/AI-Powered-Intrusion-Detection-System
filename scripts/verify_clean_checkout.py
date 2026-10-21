#!/usr/bin/env python3
"""Build and benchmark Phase 10 from an archive of the committed checkout."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--model-dir", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/generated/performance/phase10.json"),
    )
    return parser.parse_args()


def _run(
    command: list[str],
    *,
    cwd: Path,
    environment: dict[str, str] | None = None,
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        check=True,
        capture_output=capture_output,
        text=True,
    )


def main() -> int:
    arguments = _arguments()
    project_root = arguments.project_root.resolve()
    configured_model = os.environ.get("IDS_MODEL_HOST_DIR")
    model_source = arguments.model_dir or (
        Path(configured_model) if configured_model else project_root / "models/ids-rf-v1"
    )
    model_dir = model_source.resolve()
    output = arguments.output
    if not output.is_absolute():
        output = project_root / output
    status = _run(
        ["git", "status", "--porcelain=v1", "--untracked-files=normal"],
        cwd=project_root,
        capture_output=True,
    ).stdout
    if status:
        raise RuntimeError("Phase 10 clean-checkout verification requires a clean Git checkout")
    if not (model_dir / "manifest.json").is_file():
        raise FileNotFoundError(
            "The trusted model artifact is missing; set IDS_MODEL_HOST_DIR "
            "or run make finalize-model"
        )

    with tempfile.TemporaryDirectory(prefix="ids-phase10-") as temporary:
        temporary_path = Path(temporary)
        archive = temporary_path / "checkout.tar"
        checkout = temporary_path / "checkout"
        checkout.mkdir()
        _run(
            ["git", "archive", "--format=tar", "--output", str(archive), "HEAD"],
            cwd=project_root,
        )
        with tarfile.open(archive) as handle:
            handle.extractall(checkout, filter="data")
        if any(checkout.rglob(".env")):
            raise RuntimeError("clean checkout unexpectedly contains a local environment file")

        environment = os.environ.copy()
        environment["IDS_MODEL_HOST_DIR"] = str(model_dir)
        environment["COMPOSE_PROJECT_NAME"] = "ids_phase10_clean"
        compose = [
            "docker",
            "compose",
            "--project-directory",
            str(checkout),
            "--env-file",
            str(checkout / ".env.example"),
        ]
        try:
            started = time.perf_counter()
            _run(
                [*compose, "build", "--no-cache", "--pull"],
                cwd=checkout,
                environment=environment,
            )
            build_seconds = time.perf_counter() - started
            _run(
                [
                    sys.executable,
                    str(checkout / "scripts/benchmark_phase10.py"),
                    "--project-root",
                    str(checkout),
                    "--model-dir",
                    str(model_dir),
                    "--output",
                    str(output),
                    "--build-seconds",
                    str(build_seconds),
                ],
                cwd=checkout,
                environment=environment,
            )
        finally:
            subprocess.run(
                [*compose, "down", "--remove-orphans"],
                cwd=checkout,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
            )
    print("Clean committed checkout built, benchmarked, restarted, and removed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
