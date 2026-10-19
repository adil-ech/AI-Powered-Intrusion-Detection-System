"""Build a same-row destination-port diagnostic from the frozen Phase 3 pipeline."""

from __future__ import annotations

import csv
import gzip
import json
import math
import tempfile
from collections import Counter
from contextlib import ExitStack
from pathlib import Path
from typing import Any, cast

from ids_ml.data.catalog import SourceCatalog
from ids_ml.data.labels import LabelTaxonomy
from ids_ml.data.preprocess import (
    SPLITS,
    TARGET_COLUMNS,
    MeanAccumulator,
    PreprocessingConfig,
    _canonical_numeric_token,
    _create_seen_database,
    _discover_schema,
    _insert_unseen,
    _iter_rows,
    _json_sha256,
    _open_deterministic_gzip,
    _row_digest,
    _sha256_file,
    parse_numeric,
)

PORT_FEATURE = "destination_port"


def _load_json(path: Path) -> dict[str, Any]:
    raw: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return raw


def _base_contract(path: Path) -> tuple[list[str], str]:
    contract = _load_json(path)
    features = contract.get("required_features")
    schema_hash = contract.get("feature_schema_sha256")
    if not isinstance(features, list) or not all(isinstance(item, str) for item in features):
        raise ValueError("base feature contract has invalid required_features")
    if not isinstance(schema_hash, str):
        raise ValueError("base feature contract has no schema hash")
    if PORT_FEATURE in features:
        raise ValueError("base feature contract already contains destination_port")
    return list(features), schema_hash


def _port_contract(base_contract: dict[str, Any], features: list[str]) -> dict[str, Any]:
    entries = [
        {"name": name, "dtype": "float64", "missing_value_policy": "training_mean"}
        for name in features
    ]
    excluded = [
        item
        for item in cast(list[dict[str, str]], base_contract["excluded_features"])
        if item["name"] != PORT_FEATURE
    ]
    return {
        "schema_version": "1.0.0",
        "feature_schema_version": "features-v1-with-destination-port",
        "dataset": base_contract["dataset"],
        "required_features": features,
        "features": entries,
        "excluded_features": excluded,
        "diagnostic_feature": {
            "name": PORT_FEATURE,
            "scope": "preregistered Phase 5 validation comparison",
        },
        "transform": base_contract["transform"],
        "parent_feature_schema_sha256": base_contract["feature_schema_sha256"],
        "feature_schema_sha256": _json_sha256(
            {
                "feature_schema_version": "features-v1-with-destination-port",
                "features": entries,
            }
        ),
    }


def build_destination_port_variant(
    *,
    raw_dir: Path,
    catalog: SourceCatalog,
    taxonomy: LabelTaxonomy,
    preprocessing_config: PreprocessingConfig,
    preprocessing_config_path: Path,
    base_processed_dir: Path,
    base_feature_contract_path: Path,
    output_dir: Path,
    report_path: Path,
) -> dict[str, Any]:
    """Append destination_port while preserving every frozen Phase 3 row exactly."""

    base_contract = _load_json(base_feature_contract_path)
    base_features, base_schema_hash = _base_contract(base_feature_contract_path)
    base_manifest = _load_json(base_processed_dir / "split-manifest.json")
    base_state = _load_json(base_processed_dir / "preprocessing-state.json")
    if base_manifest.get("feature_schema_sha256") != base_schema_hash:
        raise ValueError("base split manifest does not match the feature contract")
    if base_state.get("feature_schema_sha256") != base_schema_hash:
        raise ValueError("base preprocessing state does not match the feature contract")
    imputation_raw = base_state.get("imputation_values")
    if not isinstance(imputation_raw, dict):
        raise ValueError("base preprocessing state has no imputation values")
    base_means = {feature: float(imputation_raw[feature]) for feature in base_features}
    schema = _discover_schema(raw_dir, catalog, preprocessing_config)
    if PORT_FEATURE not in schema.columns:
        raise ValueError("source schema has no destination_port")
    base_indexes = [schema.columns.index(feature) for feature in base_features]
    port_index = schema.columns.index(PORT_FEATURE)

    with tempfile.TemporaryDirectory(prefix="ids-port-variant-") as temporary:
        temporary_directory = Path(temporary)
        projected = _create_seen_database(temporary_directory / "fit-projected.sqlite3")
        port_accumulator = MeanAccumulator()
        try:
            for context in _iter_rows(raw_dir, catalog, preprocessing_config, schema):
                _, target = taxonomy.map(context.row[schema.label_index])
                tokens = [_canonical_numeric_token(context.row[index]) for index in base_indexes]
                if not _insert_unseen(projected, _row_digest(tokens, target.category)):
                    continue
                port = parse_numeric(
                    context.row[port_index],
                    column=PORT_FEATURE,
                    source=context.relative_path,
                    row_number=context.row_number,
                )
                if context.split == "train" and port is not None:
                    port_accumulator.add(port)
            projected.commit()
        finally:
            projected.close()
        port_mean = port_accumulator.mean()

        output_dir.mkdir(parents=True, exist_ok=True)
        paths = {split: output_dir / f"{split}.csv.gz" for split in SPLITS}
        rows_written: Counter[str] = Counter({split: 0 for split in SPLITS})
        port_replacements = 0
        projected = _create_seen_database(temporary_directory / "output-projected.sqlite3")
        transformed_seen = _create_seen_database(temporary_directory / "output-transformed.sqlite3")
        try:
            with ExitStack() as stack:
                writers: dict[str, Any] = {}
                base_readers: dict[str, Any] = {}
                for split, path in paths.items():
                    output = _open_deterministic_gzip(stack, path)
                    writer = csv.writer(output, lineterminator="\n")
                    writer.writerow([*base_features, PORT_FEATURE, *TARGET_COLUMNS])
                    writers[split] = writer
                    base_handle = stack.enter_context(
                        gzip.open(base_processed_dir / f"{split}.csv.gz", "rt", newline="")
                    )
                    reader = csv.reader(base_handle)
                    if next(reader, None) != [*base_features, *TARGET_COLUMNS]:
                        raise ValueError(f"base {split} header does not match its contract")
                    base_readers[split] = reader

                for context in _iter_rows(raw_dir, catalog, preprocessing_config, schema):
                    _, target = taxonomy.map(context.row[schema.label_index])
                    raw_tokens = [
                        _canonical_numeric_token(context.row[index]) for index in base_indexes
                    ]
                    if not _insert_unseen(projected, _row_digest(raw_tokens, target.category)):
                        continue
                    transformed: list[str] = []
                    for feature, index in zip(base_features, base_indexes, strict=True):
                        value = parse_numeric(
                            context.row[index],
                            column=feature,
                            source=context.relative_path,
                            row_number=context.row_number,
                        )
                        if value is None:
                            value = base_means[feature]
                        transformed.append(format(value, ".17g"))
                    if not _insert_unseen(
                        transformed_seen, _row_digest(transformed, target.category)
                    ):
                        continue
                    expected = [*transformed, target.category, str(target.is_malicious)]
                    base_row = next(base_readers[context.split], None)
                    if base_row != expected:
                        raise ValueError(
                            "destination-port diagnostic diverged from the frozen base row order"
                        )
                    port = parse_numeric(
                        context.row[port_index],
                        column=PORT_FEATURE,
                        source=context.relative_path,
                        row_number=context.row_number,
                    )
                    if port is None:
                        port = port_mean
                        port_replacements += 1
                    if not math.isfinite(port):
                        raise ValueError("destination_port transform produced a non-finite value")
                    writers[context.split].writerow(
                        [*transformed, format(port, ".17g"), target.category, target.is_malicious]
                    )
                    rows_written[context.split] += 1
                for split, reader in base_readers.items():
                    if next(reader, None) is not None:
                        raise ValueError(f"destination-port diagnostic omitted base {split} rows")
            projected.commit()
            transformed_seen.commit()
        finally:
            projected.close()
            transformed_seen.close()

    base_splits = cast(dict[str, dict[str, Any]], base_manifest["splits"])
    for split in SPLITS:
        if rows_written[split] != int(base_splits[split]["rows"]):
            raise ValueError(f"destination-port diagnostic changed {split} row support")
    features = [*base_features, PORT_FEATURE]
    feature_contract = _port_contract(base_contract, features)
    (output_dir / "feature-schema.json").write_text(
        json.dumps(feature_contract, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    state = {
        **base_state,
        "feature_schema_sha256": feature_contract["feature_schema_sha256"],
        "parent_feature_schema_sha256": base_schema_hash,
        "preprocessing_config_sha256": _sha256_file(preprocessing_config_path),
        "imputation_values": {**base_means, PORT_FEATURE: port_mean},
        "destination_port_replacements": port_replacements,
        "same_rows_as_parent": True,
    }
    (output_dir / "preprocessing-state.json").write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    outputs = {
        split: {
            "path": paths[split].name,
            "rows": rows_written[split],
            "bytes": paths[split].stat().st_size,
            "sha256": _sha256_file(paths[split]),
            "parent_sha256": base_splits[split]["sha256"],
        }
        for split in SPLITS
    }
    manifest = {
        **base_manifest,
        "feature_schema_sha256": feature_contract["feature_schema_sha256"],
        "parent_feature_schema_sha256": base_schema_hash,
        "parent_split_manifest_sha256": _sha256_file(base_processed_dir / "split-manifest.json"),
        "same_rows_as_parent": True,
        "splits": outputs,
    }
    (output_dir / "split-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    report = {
        "status": "passed",
        "variant": "with_destination_port",
        "same_rows_as_parent": True,
        "parent_feature_schema_sha256": base_schema_hash,
        "feature_schema_sha256": feature_contract["feature_schema_sha256"],
        "destination_port_training_mean": port_mean,
        "destination_port_replacements": port_replacements,
        "splits": outputs,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report
