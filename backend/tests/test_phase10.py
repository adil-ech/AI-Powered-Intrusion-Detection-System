"""Unit checks for the Phase 10 benchmark and artifact reporting helpers."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path

import pytest

from scripts.benchmark_phase10 import (
    BUDGETS,
    EXPECTED_ARTIFACT_FILES,
    _artifact_metadata,
    _csv_payload,
    _size_bytes,
    _summary,
)


def test_benchmark_statistics_use_five_sample_nearest_rank_p95() -> None:
    summary = _summary([0.5, 0.1, 0.4, 0.2, 0.3])

    assert summary["median_seconds"] == 0.3
    assert summary["p95_seconds"] == 0.5
    assert BUDGETS["max_batch_p95_seconds"] == 10.0


@pytest.mark.parametrize(
    ("value", "expected"),
    [("128MiB", 128 * 1024**2), ("1.5GB", 1_500_000_000), ("900B", 900)],
)
def test_docker_memory_units_are_normalized(value: str, expected: int) -> None:
    assert _size_bytes(value) == expected


def test_maximum_csv_uses_compact_finite_values_below_request_limit() -> None:
    source = io.StringIO(newline="")
    writer = csv.writer(source, lineterminator="\n")
    writer.writerow(["row_id", *[f"feature_{index}" for index in range(63)]])
    writer.writerow(["template", *["123456789.123456789" for _index in range(63)]])

    payload, identifiers = _csv_payload(source.getvalue().encode("utf-8"), 10_000, prefix="maximum")

    assert len(payload) < 10 * 1024**2
    assert len(identifiers) == 10_000
    assert identifiers[0] == "maximum-00000"
    assert identifiers[-1] == "maximum-09999"


def test_artifact_metadata_verifies_every_manifest_hash(tmp_path: Path) -> None:
    files: dict[str, dict[str, object]] = {}
    for name in EXPECTED_ARTIFACT_FILES:
        content = f"stable-{name}\n".encode()
        (tmp_path / name).write_bytes(content)
        files[name] = {
            "sha256": hashlib.sha256(content).hexdigest(),
            "bytes": len(content),
        }
    manifest = {"model_version": "test-v1", "files": files}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    metadata = _artifact_metadata(tmp_path)

    assert metadata["model_version"] == "test-v1"
    assert metadata["files"] == files
    (tmp_path / "metrics.json").write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="integrity check failed"):
        _artifact_metadata(tmp_path)
