"""Local raw-source checksum manifest creation and verification."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ids_ml.data.catalog import SourceCatalog


@dataclass(frozen=True)
class ManifestVerification:
    """Manifest verification result used by the audit report."""

    valid: bool
    errors: tuple[str, ...]
    unlisted_files: tuple[str, ...]
    listed_files: tuple[str, ...]


def discover_csv_files(raw_dir: Path) -> list[Path]:
    """Return every CSV below the raw directory in deterministic order."""

    if not raw_dir.exists():
        return []
    return sorted(
        (path for path in raw_dir.rglob("*") if path.is_file() and path.suffix.lower() == ".csv"),
        key=lambda path: path.relative_to(raw_dir).as_posix().casefold(),
    )


def sha256_file(path: Path) -> str:
    """Hash a file without loading it into memory."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(raw_dir: Path, catalog: SourceCatalog, retrieved_at: str) -> dict[str, object]:
    """Build a deterministic manifest for the locally acquired CSV files."""

    files = discover_csv_files(raw_dir)
    if not files:
        raise ValueError(f"no CSV files found under {raw_dir}")

    entries: list[dict[str, object]] = []
    for path in files:
        capture = catalog.match(path)
        entries.append(
            {
                "path": path.relative_to(raw_dir).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                "capture_id": capture.capture_id if capture else None,
            }
        )

    return {
        "schema_version": "1.0.0",
        "dataset": catalog.dataset,
        "source_url": catalog.source_url,
        "archive_name": catalog.archive_name,
        "retrieved_at": retrieved_at,
        "files": entries,
    }


def write_manifest(manifest: dict[str, object], output: Path) -> None:
    """Write a stable JSON manifest."""

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _safe_manifest_path(raw_dir: Path, relative: str) -> Path:
    candidate = (raw_dir / relative).resolve()
    root = raw_dir.resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError(f"manifest path escapes raw directory: {relative}")
    return candidate


def verify_manifest(raw_dir: Path, manifest_path: Path, dataset: str) -> ManifestVerification:
    """Verify every listed CSV and reject unlisted source files."""

    discovered = {path.relative_to(raw_dir).as_posix() for path in discover_csv_files(raw_dir)}
    if not manifest_path.exists():
        return ManifestVerification(
            valid=False,
            errors=(f"manifest is missing: {manifest_path}",),
            unlisted_files=tuple(sorted(discovered)),
            listed_files=(),
        )

    errors: list[str] = []
    raw: object = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return ManifestVerification(False, ("manifest must contain a JSON object",), (), ())
    mapping: dict[str, Any] = raw
    if mapping.get("dataset") != dataset:
        errors.append(f"manifest dataset must be {dataset}")
    entries = mapping.get("files")
    if not isinstance(entries, list):
        return ManifestVerification(
            False, tuple(errors + ["manifest files must be a list"]), (), ()
        )

    listed: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append(f"manifest file entry {index} must be an object")
            continue
        relative = entry.get("path")
        expected_size = entry.get("size_bytes")
        expected_sha = entry.get("sha256")
        if not isinstance(relative, str):
            errors.append(f"manifest file entry {index} has no valid path")
            continue
        if relative in listed:
            errors.append(f"manifest lists {relative} more than once")
            continue
        listed.add(relative)
        try:
            path = _safe_manifest_path(raw_dir, relative)
        except ValueError as error:
            errors.append(str(error))
            continue
        if not path.is_file():
            errors.append(f"manifest file is missing: {relative}")
            continue
        if not isinstance(expected_size, int) or path.stat().st_size != expected_size:
            errors.append(f"size mismatch: {relative}")
        if not isinstance(expected_sha, str) or sha256_file(path) != expected_sha:
            errors.append(f"sha256 mismatch: {relative}")

    unlisted = tuple(sorted(discovered - listed))
    for relative in unlisted:
        errors.append(f"CSV is not listed in manifest: {relative}")
    for relative in sorted(listed - discovered):
        if f"manifest file is missing: {relative}" not in errors:
            errors.append(f"manifest file is missing: {relative}")

    return ManifestVerification(
        valid=not errors,
        errors=tuple(errors),
        unlisted_files=unlisted,
        listed_files=tuple(sorted(listed)),
    )
