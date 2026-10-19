"""Versioned, integrity-checked inference artifact bundle."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from numpy.typing import NDArray

REQUIRED_FILES = (
    "pipeline.joblib",
    "metadata.json",
    "feature-schema.json",
    "label-taxonomy.json",
    "metrics.json",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json(path: Path) -> dict[str, Any]:
    raw: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return raw


@dataclass
class InferenceBundle:
    """All fitted state needed by the future API, with strict column alignment."""

    artifact_schema_version: str
    model_version: str
    feature_schema_version: str
    feature_schema_hash: str
    required_features: tuple[str, ...]
    imputation_values: tuple[float, ...]
    attack_labels: tuple[str, ...]
    malicious_threshold: float
    low_confidence_threshold: float
    high_risk_threshold: float
    binary_model: Any
    attack_family_model: Any

    def align_features(
        self,
        features: NDArray[np.float64] | NDArray[np.float32],
        columns: list[str] | tuple[str, ...],
    ) -> NDArray[np.float32]:
        """Reorder a complete feature matrix or fail with a precise schema error."""

        matrix = np.asarray(features)
        if matrix.ndim == 1:
            matrix = matrix.reshape(1, -1)
        if matrix.ndim != 2 or matrix.shape[1] != len(columns):
            raise ValueError("feature matrix width does not match the supplied columns")
        if len(columns) != len(set(columns)):
            raise ValueError("input columns contain duplicates")
        expected = set(self.required_features)
        supplied = set(columns)
        missing = sorted(expected - supplied)
        extra = sorted(supplied - expected)
        if missing or extra:
            details: list[str] = []
            if missing:
                details.append("missing: " + ", ".join(missing))
            if extra:
                details.append("extra: " + ", ".join(extra))
            raise ValueError("feature schema mismatch (" + "; ".join(details) + ")")
        indexes = {name: index for index, name in enumerate(columns)}
        ordered = np.asarray(
            matrix[:, [indexes[name] for name in self.required_features]], dtype=np.float32
        )
        if not np.all(np.isfinite(ordered)):
            raise ValueError("features must contain only finite numeric values")
        return ordered

    def predict_probabilities(
        self,
        features: NDArray[np.float64] | NDArray[np.float32],
        columns: list[str] | tuple[str, ...],
    ) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        ordered = self.align_features(features, columns)
        binary = np.asarray(self.binary_model.predict_proba(ordered)[:, 1], dtype=np.float64)
        raw_family = np.asarray(self.attack_family_model.predict_proba(ordered), dtype=np.float64)
        classes = np.asarray(self.attack_family_model.classes_, dtype=np.int64)
        family = np.zeros((ordered.shape[0], len(self.attack_labels)), dtype=np.float64)
        family[:, classes] = raw_family
        if not np.all(np.isfinite(binary)) or not np.all(np.isfinite(family)):
            raise ValueError("model produced non-finite probabilities")
        if np.any((binary < 0.0) | (binary > 1.0)) or np.any((family < 0.0) | (family > 1.0)):
            raise ValueError("model produced probabilities outside [0, 1]")
        if not np.allclose(np.sum(family, axis=1), 1.0, atol=1e-10):
            raise ValueError("attack-family probabilities are not normalized")
        return binary, family


def write_artifact(
    output_dir: Path,
    bundle: InferenceBundle,
    *,
    metadata: dict[str, Any],
    metrics: dict[str, Any],
    feature_schema_path: Path,
    label_taxonomy_path: Path,
) -> dict[str, Any]:
    """Write the immutable six-file bundle and return its manifest."""

    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(
            f"artifact directory already exists and will not be overwritten: {output_dir}"
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, output_dir / "pipeline.joblib", compress=3)
    (output_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    shutil.copyfile(feature_schema_path, output_dir / "feature-schema.json")
    shutil.copyfile(label_taxonomy_path, output_dir / "label-taxonomy.json")
    (output_dir / "metrics.json").write_text(
        json.dumps(metrics, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    manifest = {
        "artifact_schema_version": bundle.artifact_schema_version,
        "model_version": bundle.model_version,
        "files": {
            name: {
                "sha256": sha256_file(output_dir / name),
                "bytes": (output_dir / name).stat().st_size,
            }
            for name in REQUIRED_FILES
        },
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def load_artifact(output_dir: Path) -> tuple[InferenceBundle, dict[str, Any]]:
    """Verify every file hash and cross-file identity before deserializing."""

    manifest = _json(output_dir / "manifest.json")
    files = manifest.get("files")
    if not isinstance(files, dict) or set(files) != set(REQUIRED_FILES):
        raise ValueError("artifact manifest does not list the exact required files")
    for name in REQUIRED_FILES:
        item = files.get(name)
        if not isinstance(item, dict) or item.get("sha256") != sha256_file(output_dir / name):
            raise ValueError(f"artifact integrity check failed for {name}")
        if item.get("bytes") != (output_dir / name).stat().st_size:
            raise ValueError(f"artifact size check failed for {name}")
    metadata = _json(output_dir / "metadata.json")
    feature_schema = _json(output_dir / "feature-schema.json")
    raw: object = joblib.load(output_dir / "pipeline.joblib")
    if not isinstance(raw, InferenceBundle):
        raise ValueError("pipeline.joblib does not contain an InferenceBundle")
    bundle = raw
    checks = {
        "artifact_schema_version": bundle.artifact_schema_version,
        "model_version": bundle.model_version,
    }
    for key, value in checks.items():
        if manifest.get(key) != value or metadata.get(key) != value:
            raise ValueError(f"artifact {key} does not agree across files")
    if metadata.get("feature_schema_hash") != bundle.feature_schema_hash:
        raise ValueError("artifact feature schema hash does not agree with metadata")
    if feature_schema.get("feature_schema_sha256") != bundle.feature_schema_hash:
        raise ValueError("artifact feature schema file does not agree with the pipeline")
    if feature_schema.get("required_features") != list(bundle.required_features):
        raise ValueError("artifact required feature order does not agree with the pipeline")
    return bundle, manifest
