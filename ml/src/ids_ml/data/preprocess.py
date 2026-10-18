"""Deterministic, leak-resistant CIC-IDS2017 preprocessing pipeline."""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import math
import sqlite3
import tempfile
from collections import Counter
from collections.abc import Iterator
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO, cast

from ids_ml.data.catalog import CaptureDefinition, SourceCatalog
from ids_ml.data.labels import LabelTaxonomy
from ids_ml.data.manifest import discover_csv_files, verify_manifest
from ids_ml.data.schema import MISSING_MARKERS, normalize_column_names

SPLITS = ("train", "validation", "final_test")
TARGET_COLUMNS = ("category", "is_malicious")


@dataclass(frozen=True)
class PreprocessingConfig:
    """Frozen knobs that control grouping, splitting, and feature policy."""

    schema_version: str
    dataset: str
    random_seed: int
    group_size_rows: int
    split_basis_points: dict[str, int]
    excluded_features: dict[str, str]
    imputation_strategy: str


@dataclass(frozen=True)
class SourceSchema:
    """Canonical source schema shared by every selected CSV."""

    columns: tuple[str, ...]
    label_index: int
    candidate_features: tuple[str, ...]
    candidate_indexes: tuple[int, ...]


@dataclass(frozen=True)
class RowContext:
    """One raw source row plus immutable split provenance."""

    capture: CaptureDefinition
    relative_path: str
    row_number: int
    group_id: str
    split: str
    row: list[str]


@dataclass
class FeatureProfile:
    """Training-only state used to find constants and duplicate columns."""

    first_token: str | None = None
    constant: bool = True
    observations: int = 0
    _digest: Any = field(default_factory=hashlib.sha256, repr=False)
    _buffer: bytearray = field(default_factory=bytearray, repr=False)

    def observe(self, token: str) -> None:
        if self.first_token is None:
            self.first_token = token
        elif token != self.first_token:
            self.constant = False
        encoded = token.encode("utf-8")
        self._buffer.extend(len(encoded).to_bytes(4, "big"))
        self._buffer.extend(encoded)
        if len(self._buffer) >= 65_536:
            self._flush()
        self.observations += 1

    def _flush(self) -> None:
        self._digest.update(self._buffer)
        self._buffer.clear()

    def hexdigest(self) -> str:
        self._flush()
        return str(self._digest.hexdigest())


@dataclass
class MeanAccumulator:
    """Stable streaming sum for a train-fitted arithmetic mean."""

    count: int = 0
    total: float = 0.0
    compensation: float = 0.0

    def add(self, value: float) -> None:
        adjusted = value - self.compensation
        updated = self.total + adjusted
        self.compensation = (updated - self.total) - adjusted
        self.total = updated
        self.count += 1

    def mean(self) -> float:
        if self.count == 0:
            raise ValueError("cannot fit an imputer for a feature with no finite training values")
        result = self.total / self.count
        if not math.isfinite(result):
            raise ValueError("training mean is not finite")
        return result


@dataclass
class GroupSummary:
    """Final unique-row support for one source-window group."""

    group_id: str
    split: str
    capture_id: str
    capture_date: str
    source_path: str
    rows: int = 0
    categories: Counter[str] = field(default_factory=Counter)


def load_preprocessing_config(path: Path) -> PreprocessingConfig:
    """Load and validate a committed preprocessing configuration."""

    raw: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("preprocessing config must contain a JSON object")
    mapping: dict[str, Any] = raw
    ratios = mapping.get("split_basis_points")
    excluded = mapping.get("excluded_features")
    if not isinstance(ratios, dict) or set(ratios) != set(SPLITS):
        raise ValueError(f"split_basis_points must define exactly: {', '.join(SPLITS)}")
    if not all(isinstance(value, int) and value > 0 for value in ratios.values()):
        raise ValueError("split basis points must be positive integers")
    typed_ratios = {str(key): int(value) for key, value in ratios.items()}
    if sum(typed_ratios.values()) != 10_000:
        raise ValueError("split basis points must total 10000")
    if not isinstance(excluded, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in excluded.items()
    ):
        raise ValueError("excluded_features must map column names to reasons")
    seed = mapping.get("random_seed")
    group_size = mapping.get("group_size_rows")
    if not isinstance(seed, int) or seed < 0:
        raise ValueError("random_seed must be a non-negative integer")
    if not isinstance(group_size, int) or group_size < 1:
        raise ValueError("group_size_rows must be a positive integer")
    strategy = mapping.get("imputation_strategy")
    if strategy != "training_mean":
        raise ValueError("the supported imputation_strategy is training_mean")
    return PreprocessingConfig(
        schema_version=_required_string(mapping, "schema_version"),
        dataset=_required_string(mapping, "dataset"),
        random_seed=seed,
        group_size_rows=group_size,
        split_basis_points=typed_ratios,
        excluded_features={str(key): str(value) for key, value in excluded.items()},
        imputation_strategy=strategy,
    )


def _required_string(mapping: dict[str, Any], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"preprocessing config field {key!r} must be a non-empty string")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _json_sha256(value: object) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _canonical_numeric_token(value: str) -> str:
    stripped = value.strip()
    folded = stripped.casefold()
    if folded in MISSING_MARKERS or folded in {
        "infinity",
        "+infinity",
        "inf",
        "+inf",
        "-inf",
        "-infinity",
    }:
        return "<missing>"
    return stripped


def parse_numeric(value: str, *, column: str, source: str, row_number: int) -> float | None:
    """Parse one numeric cell, treating missing and infinities as missing."""

    token = _canonical_numeric_token(value)
    if token == "<missing>":
        return None
    try:
        number = float(token)
    except ValueError as error:
        raise ValueError(
            f"invalid numeric value for {column} at {source}:{row_number}: {value!r}"
        ) from error
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def assign_split(group_id: str, config: PreprocessingConfig) -> str:
    """Assign a complete source-window group using a stable seeded hash."""

    digest = hashlib.sha256(f"{config.random_seed}:{group_id}".encode()).digest()
    bucket = int.from_bytes(digest[:8], "big") % 10_000
    boundary = 0
    for split in SPLITS:
        boundary += config.split_basis_points[split]
        if bucket < boundary:
            return split
    raise AssertionError("split basis-point boundaries did not cover the hash space")


def _row_digest(tokens: list[str], category: str) -> bytes:
    payload = "\x1f".join([*tokens, category]).encode("utf-8")
    return hashlib.sha256(payload).digest()


def _create_seen_database(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode=OFF")
    connection.execute("PRAGMA synchronous=OFF")
    connection.execute("CREATE TABLE seen_rows (digest BLOB PRIMARY KEY) WITHOUT ROWID")
    return connection


def _insert_unseen(connection: sqlite3.Connection, digest: bytes) -> bool:
    return bool(
        connection.execute(
            "INSERT OR IGNORE INTO seen_rows (digest) VALUES (?)", (digest,)
        ).rowcount
    )


def _discover_schema(
    raw_dir: Path, catalog: SourceCatalog, config: PreprocessingConfig
) -> SourceSchema:
    files = discover_csv_files(raw_dir)
    if not files:
        raise ValueError(f"no CSV files found under {raw_dir}")
    reference: list[str] | None = None
    matched: set[str] = set()
    for path in files:
        capture = catalog.match(path)
        if capture is None:
            raise ValueError(f"source file does not match the capture catalog: {path.name}")
        if capture.capture_id in matched:
            raise ValueError(f"capture matched more than one file: {capture.capture_id}")
        matched.add(capture.capture_id)
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            header = next(csv.reader(handle), None)
        if header is None:
            raise ValueError(f"CSV has no header: {path.name}")
        columns, _ = normalize_column_names(header)
        if reference is None:
            reference = columns
        elif columns != reference:
            raise ValueError(f"normalized source schema differs in {path.name}")
    expected = {capture.capture_id for capture in catalog.captures}
    if matched != expected:
        missing = ", ".join(sorted(expected - matched))
        raise ValueError(f"source captures are incomplete; missing: {missing}")
    assert reference is not None
    if "label" not in reference:
        raise ValueError("normalized source schema has no label column")
    candidate_features = tuple(name for name in reference if name not in config.excluded_features)
    if not candidate_features:
        raise ValueError("feature policy excluded every source feature")
    return SourceSchema(
        columns=tuple(reference),
        label_index=reference.index("label"),
        candidate_features=candidate_features,
        candidate_indexes=tuple(reference.index(name) for name in candidate_features),
    )


def _iter_rows(
    raw_dir: Path,
    catalog: SourceCatalog,
    config: PreprocessingConfig,
    schema: SourceSchema,
) -> Iterator[RowContext]:
    for path in discover_csv_files(raw_dir):
        capture = catalog.match(path)
        if capture is None:
            raise ValueError(f"source file does not match the capture catalog: {path.name}")
        relative = path.relative_to(raw_dir).as_posix()
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            next(reader)
            for row_number, row in enumerate(reader, start=1):
                if len(row) != len(schema.columns):
                    raise ValueError(
                        f"malformed row at {relative}:{row_number}; "
                        f"expected {len(schema.columns)} cells, found {len(row)}"
                    )
                window = (row_number - 1) // config.group_size_rows
                group_id = f"{capture.capture_date}:{capture.capture_id}:window-{window:06d}"
                yield RowContext(
                    capture=capture,
                    relative_path=relative,
                    row_number=row_number,
                    group_id=group_id,
                    split=assign_split(group_id, config),
                    row=row,
                )


def _candidate_tokens(context: RowContext, schema: SourceSchema) -> list[str]:
    return [_canonical_numeric_token(context.row[index]) for index in schema.candidate_indexes]


def _select_features(
    raw_dir: Path,
    catalog: SourceCatalog,
    config: PreprocessingConfig,
    taxonomy: LabelTaxonomy,
    schema: SourceSchema,
    temporary_directory: Path,
) -> tuple[list[str], list[dict[str, str]], dict[str, int]]:
    profiles = {name: FeatureProfile() for name in schema.candidate_features}
    counts = {"source_rows": 0, "candidate_duplicate_rows_removed": 0, "fit_rows": 0}
    connection = _create_seen_database(temporary_directory / "candidate-rows.sqlite3")
    try:
        for context in _iter_rows(raw_dir, catalog, config, schema):
            counts["source_rows"] += 1
            _, target = taxonomy.map(context.row[schema.label_index])
            tokens = _candidate_tokens(context, schema)
            if not _insert_unseen(connection, _row_digest(tokens, target.category)):
                counts["candidate_duplicate_rows_removed"] += 1
                continue
            if context.split != "train":
                continue
            counts["fit_rows"] += 1
            for feature, index, token in zip(
                schema.candidate_features, schema.candidate_indexes, tokens, strict=True
            ):
                parse_numeric(
                    context.row[index],
                    column=feature,
                    source=context.relative_path,
                    row_number=context.row_number,
                )
                profiles[feature].observe(token)
        connection.commit()
    finally:
        connection.close()

    constants = {
        name for name, profile in profiles.items() if profile.observations and profile.constant
    }
    digest_owner: dict[tuple[int, str], str] = {}
    duplicates: dict[str, str] = {}
    for name in schema.candidate_features:
        profile = profiles[name]
        signature = (profile.observations, profile.hexdigest())
        owner = digest_owner.get(signature)
        if owner is None:
            digest_owner[signature] = name
        else:
            duplicates[name] = owner

    selected = [
        name
        for name in schema.candidate_features
        if name not in constants and name not in duplicates
    ]
    if not selected:
        raise ValueError("training-only feature selection removed every candidate feature")
    removed = [
        {"name": name, "reason": "constant_in_training_split"}
        for name in schema.candidate_features
        if name in constants
    ]
    removed.extend(
        {
            "name": name,
            "reason": f"exact_duplicate_of:{duplicates[name]}",
        }
        for name in schema.candidate_features
        if name in duplicates and name not in constants
    )
    return selected, removed, counts


def _empty_support(taxonomy: LabelTaxonomy) -> dict[str, Counter[str]]:
    return {split: Counter({category: 0 for category in taxonomy.categories}) for split in SPLITS}


def _fit_imputer(
    raw_dir: Path,
    catalog: SourceCatalog,
    config: PreprocessingConfig,
    taxonomy: LabelTaxonomy,
    schema: SourceSchema,
    features: list[str],
    temporary_directory: Path,
) -> tuple[dict[str, float], dict[str, Any]]:
    indexes = [schema.columns.index(feature) for feature in features]
    accumulators = {feature: MeanAccumulator() for feature in features}
    support = _empty_support(taxonomy)
    split_rows = Counter({split: 0 for split in SPLITS})
    groups: dict[str, GroupSummary] = {}
    source_rows = 0
    duplicates_removed = 0
    connection = _create_seen_database(temporary_directory / "projected-rows.sqlite3")
    try:
        for context in _iter_rows(raw_dir, catalog, config, schema):
            source_rows += 1
            _, target = taxonomy.map(context.row[schema.label_index])
            tokens = [_canonical_numeric_token(context.row[index]) for index in indexes]
            if not _insert_unseen(connection, _row_digest(tokens, target.category)):
                duplicates_removed += 1
                continue
            values = [
                parse_numeric(
                    context.row[index],
                    column=feature,
                    source=context.relative_path,
                    row_number=context.row_number,
                )
                for feature, index in zip(features, indexes, strict=True)
            ]
            split_rows[context.split] += 1
            support[context.split][target.category] += 1
            group = groups.setdefault(
                context.group_id,
                GroupSummary(
                    group_id=context.group_id,
                    split=context.split,
                    capture_id=context.capture.capture_id,
                    capture_date=context.capture.capture_date,
                    source_path=context.relative_path,
                ),
            )
            if group.split != context.split:
                raise AssertionError(f"group crossed split boundaries: {context.group_id}")
            group.rows += 1
            group.categories[target.category] += 1
            if context.split == "train":
                for feature, value in zip(features, values, strict=True):
                    if value is not None:
                        accumulators[feature].add(value)
        connection.commit()
    finally:
        connection.close()

    if any(split_rows[split] == 0 for split in SPLITS):
        raise ValueError(f"one or more splits are empty: {dict(split_rows)}")
    means = {feature: accumulators[feature].mean() for feature in features}
    group_records = [
        {
            "group_id": group.group_id,
            "split": group.split,
            "capture_id": group.capture_id,
            "capture_date": group.capture_date,
            "source_path": group.source_path,
            "rows": group.rows,
            "category_support": {
                category: group.categories[category]
                for category in taxonomy.categories
                if group.categories[category]
            },
        }
        for group in sorted(groups.values(), key=lambda item: item.group_id)
    ]
    details: dict[str, Any] = {
        "source_rows": source_rows,
        "projected_duplicate_rows_removed": duplicates_removed,
        "split_rows": {split: split_rows[split] for split in SPLITS},
        "class_support": {
            split: {category: support[split][category] for category in taxonomy.categories}
            for split in SPLITS
        },
        "groups": group_records,
        "fit_rows": split_rows["train"],
    }
    return means, details


def build_feature_contract(
    config: PreprocessingConfig,
    features: list[str],
    removed: list[dict[str, str]],
) -> dict[str, object]:
    """Build the portable ordered feature contract for the first modeling cycle."""

    feature_entries = [
        {"name": feature, "dtype": "float64", "missing_value_policy": "training_mean"}
        for feature in features
    ]
    hash_payload = {
        "feature_schema_version": "features-v1",
        "features": feature_entries,
    }
    configured_exclusions = [
        {"name": name, "reason": reason}
        for name, reason in config.excluded_features.items()
        if name != "label"
    ]
    return {
        "schema_version": "1.0.0",
        "feature_schema_version": "features-v1",
        "dataset": config.dataset,
        "required_features": features,
        "features": feature_entries,
        "excluded_features": [*configured_exclusions, *removed],
        "transform": {
            "non_finite_training_values": "replace_with_missing",
            "imputation": config.imputation_strategy,
            "fit_split": "train",
        },
        "feature_schema_sha256": _json_sha256(hash_payload),
    }


def _validate_feature_contract(computed: dict[str, object], path: Path) -> None:
    committed: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(committed, dict):
        raise ValueError("committed feature contract must contain a JSON object")
    for key in ("feature_schema_version", "required_features", "feature_schema_sha256"):
        if committed.get(key) != computed.get(key):
            raise ValueError(f"computed feature contract differs from {path} at {key}")


def _open_deterministic_gzip(stack: ExitStack, path: Path) -> TextIO:
    raw = stack.enter_context(path.open("wb"))
    compressed = stack.enter_context(gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0))
    return stack.enter_context(io.TextIOWrapper(compressed, encoding="utf-8", newline=""))


def _write_processed_splits(
    raw_dir: Path,
    catalog: SourceCatalog,
    config: PreprocessingConfig,
    taxonomy: LabelTaxonomy,
    schema: SourceSchema,
    features: list[str],
    means: dict[str, float],
    output_dir: Path,
    temporary_directory: Path,
) -> tuple[dict[str, dict[str, object]], dict[str, int], dict[str, Any]]:
    indexes = [schema.columns.index(feature) for feature in features]
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {split: output_dir / f"{split}.csv.gz" for split in SPLITS}
    rows_written = Counter({split: 0 for split in SPLITS})
    replacements = Counter({feature: 0 for feature in features})
    support = _empty_support(taxonomy)
    groups: dict[str, GroupSummary] = {}
    transformed_duplicates = 0
    projected_connection = _create_seen_database(
        temporary_directory / "output-projected-rows.sqlite3"
    )
    transformed_connection = _create_seen_database(
        temporary_directory / "output-transformed-rows.sqlite3"
    )
    try:
        with ExitStack() as stack:
            writers: dict[str, Any] = {}
            for split, path in paths.items():
                handle = _open_deterministic_gzip(stack, path)
                writer = csv.writer(handle, lineterminator="\n")
                writer.writerow([*features, *TARGET_COLUMNS])
                writers[split] = writer
            for context in _iter_rows(raw_dir, catalog, config, schema):
                _, target = taxonomy.map(context.row[schema.label_index])
                tokens = [_canonical_numeric_token(context.row[index]) for index in indexes]
                if not _insert_unseen(projected_connection, _row_digest(tokens, target.category)):
                    continue
                transformed: list[str] = []
                replaced_features: list[str] = []
                for feature, index in zip(features, indexes, strict=True):
                    value = parse_numeric(
                        context.row[index],
                        column=feature,
                        source=context.relative_path,
                        row_number=context.row_number,
                    )
                    if value is None:
                        value = means[feature]
                        replaced_features.append(feature)
                    if not math.isfinite(value):
                        raise ValueError(
                            f"non-finite transformed value for {feature} at "
                            f"{context.relative_path}:{context.row_number}"
                        )
                    transformed.append(format(value, ".17g"))
                if not _insert_unseen(
                    transformed_connection, _row_digest(transformed, target.category)
                ):
                    transformed_duplicates += 1
                    continue
                writers[context.split].writerow(
                    [*transformed, target.category, target.is_malicious]
                )
                rows_written[context.split] += 1
                support[context.split][target.category] += 1
                replacements.update(replaced_features)
                group = groups.setdefault(
                    context.group_id,
                    GroupSummary(
                        group_id=context.group_id,
                        split=context.split,
                        capture_id=context.capture.capture_id,
                        capture_date=context.capture.capture_date,
                        source_path=context.relative_path,
                    ),
                )
                group.rows += 1
                group.categories[target.category] += 1
        projected_connection.commit()
        transformed_connection.commit()
    finally:
        projected_connection.close()
        transformed_connection.close()

    outputs = {
        split: {
            "path": paths[split].name,
            "rows": rows_written[split],
            "sha256": _sha256_file(paths[split]),
            "bytes": paths[split].stat().st_size,
        }
        for split in SPLITS
    }
    group_records = [
        {
            "group_id": group.group_id,
            "split": group.split,
            "capture_id": group.capture_id,
            "capture_date": group.capture_date,
            "source_path": group.source_path,
            "rows": group.rows,
            "category_support": {
                category: group.categories[category]
                for category in taxonomy.categories
                if group.categories[category]
            },
        }
        for group in sorted(groups.values(), key=lambda item: item.group_id)
    ]
    details: dict[str, Any] = {
        "transformed_duplicate_rows_removed": transformed_duplicates,
        "split_rows": {split: rows_written[split] for split in SPLITS},
        "class_support": {
            split: {category: support[split][category] for category in taxonomy.categories}
            for split in SPLITS
        },
        "groups": group_records,
    }
    return outputs, {feature: replacements[feature] for feature in features}, details


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _markdown_report(report: dict[str, object]) -> str:
    splits = cast(dict[str, dict[str, Any]], report["splits"])
    selection = cast(dict[str, Any], report["feature_selection"])
    leakage = cast(dict[str, int], report["leakage_checks"])
    lines = [
        "# CIC-IDS2017 preprocessing report",
        "",
        f"- Status: **{str(report['status']).upper()}**",
        f"- Seed: {report['random_seed']}",
        f"- Source rows: {cast(int, report['source_rows']):,}",
        f"- Output rows after projected deduplication: {cast(int, report['output_rows']):,}",
        f"- Required features: {selection['selected_count']}",
        f"- Feature schema SHA-256: `{report['feature_schema_sha256']}`",
        "",
        "## Split support",
        "",
        "| Split | Rows | Groups | Output SHA-256 |",
        "|---|---:|---:|---|",
    ]
    for split in SPLITS:
        item = splits[split]
        lines.append(
            f"| {split} | {int(item['rows']):,} | {int(item['groups']):,} | "
            f"`{item['output_sha256']}` |"
        )
    lines.extend(["", "## Class support", ""])
    categories = cast(list[str], report["categories"])
    lines.append("| Category | " + " | ".join(SPLITS) + " |")
    lines.append("|---|" + "---:|" * len(SPLITS))
    for category in categories:
        counts = [str(splits[split]["class_support"][category]) for split in SPLITS]
        lines.append(f"| {category} | " + " | ".join(counts) + " |")
    lines.extend(
        [
            "",
            "## Training-only feature selection",
            "",
            f"- Candidate features: {selection['candidate_count']}",
            f"- Selected features: {selection['selected_count']}",
            "- Removed constants: " + (", ".join(selection["constant_features"]) or "none"),
            "- Removed exact duplicate columns: "
            + (", ".join(selection["duplicate_features"]) or "none"),
            "- Imputer fit split: train",
            "- Port decision: destination_port remains excluded from features-v1; a "
            "validation-only comparison remains preregistered for Phase 4.",
            "",
            "## Leakage checks",
            "",
        ]
    )
    lines.extend(f"- {name}: {value}" for name, value in leakage.items())
    lines.extend(
        [
            "",
            "The final-test split contributed no values to feature filtering or imputer fitting.",
            "No stratified random-row split was produced; it remains diagnostic-only by contract.",
        ]
    )
    return "\n".join(lines) + "\n"


def run_preprocessing(
    *,
    raw_dir: Path,
    catalog: SourceCatalog,
    manifest_path: Path,
    taxonomy: LabelTaxonomy,
    taxonomy_path: Path,
    config: PreprocessingConfig,
    config_path: Path,
    output_dir: Path,
    feature_contract_path: Path | None,
    feature_contract_output: Path | None,
    report_json: Path,
    report_markdown: Path,
) -> dict[str, object]:
    """Execute feature selection, split generation, train-only fitting, and transforms."""

    if catalog.dataset != config.dataset:
        raise ValueError(
            f"catalog dataset {catalog.dataset!r} does not match config {config.dataset!r}"
        )
    verification = verify_manifest(raw_dir, manifest_path, catalog.dataset)
    if not verification.valid:
        raise ValueError("source manifest verification failed: " + "; ".join(verification.errors))
    schema = _discover_schema(raw_dir, catalog, config)
    with tempfile.TemporaryDirectory(prefix="ids-preprocess-") as temp:
        temporary_directory = Path(temp)
        features, removed, selection_counts = _select_features(
            raw_dir, catalog, config, taxonomy, schema, temporary_directory
        )
        contract = build_feature_contract(config, features, removed)
        if feature_contract_path is not None:
            _validate_feature_contract(contract, feature_contract_path)
        if feature_contract_output is not None:
            _write_json(feature_contract_output, contract)
        means, fit_details = _fit_imputer(
            raw_dir,
            catalog,
            config,
            taxonomy,
            schema,
            features,
            temporary_directory,
        )
        outputs, replacements, output_details = _write_processed_splits(
            raw_dir,
            catalog,
            config,
            taxonomy,
            schema,
            features,
            means,
            output_dir,
            temporary_directory,
        )

    split_rows = cast(dict[str, int], output_details["split_rows"])
    output_support = cast(dict[str, dict[str, int]], output_details["class_support"])
    missing_training_categories = [
        category
        for category in taxonomy.categories
        if sum(output_support[split][category] for split in SPLITS) > 0
        and output_support["train"][category] == 0
    ]
    if missing_training_categories:
        raise ValueError(
            "observed categories have no training support under the grouped split: "
            + ", ".join(missing_training_categories)
        )
    if any(cast(int, outputs[split]["rows"]) != split_rows[split] for split in SPLITS):
        raise AssertionError("output accounting produced different split row counts")
    groups = cast(list[dict[str, Any]], output_details["groups"])
    group_counts = Counter(str(group["split"]) for group in groups)
    schema_hash = str(contract["feature_schema_sha256"])
    state = {
        "schema_version": "1.0.0",
        "preprocessing_config_sha256": _sha256_file(config_path),
        "source_manifest_sha256": _sha256_file(manifest_path),
        "label_taxonomy_sha256": _sha256_file(taxonomy_path),
        "feature_schema_sha256": schema_hash,
        "fit_split": "train",
        "fit_rows": fit_details["fit_rows"],
        "imputation_strategy": config.imputation_strategy,
        "imputation_values": means,
    }
    state_path = output_dir / "preprocessing-state.json"
    _write_json(state_path, state)
    state_hash = _sha256_file(state_path)
    split_manifest = {
        "schema_version": "1.0.0",
        "dataset": config.dataset,
        "random_seed": config.random_seed,
        "group_strategy": {
            "type": "capture_day_source_contiguous_row_window",
            "rows_per_window": config.group_size_rows,
        },
        "split_basis_points": config.split_basis_points,
        "source_manifest_sha256": _sha256_file(manifest_path),
        "feature_schema_sha256": schema_hash,
        "preprocessing_state_sha256": state_hash,
        "splits": outputs,
        "groups": groups,
    }
    split_manifest_path = output_dir / "split-manifest.json"
    _write_json(split_manifest_path, split_manifest)
    split_manifest_hash = _sha256_file(split_manifest_path)

    removed_constants = [
        item["name"] for item in removed if item["reason"] == "constant_in_training_split"
    ]
    removed_duplicates = [
        f"{item['name']} ({item['reason'].split(':', 1)[1]})"
        for item in removed
        if item["reason"].startswith("exact_duplicate_of:")
    ]
    class_support = output_support
    report_splits = {
        split: {
            "rows": split_rows[split],
            "groups": group_counts[split],
            "class_support": class_support[split],
            "output_sha256": outputs[split]["sha256"],
        }
        for split in SPLITS
    }
    report: dict[str, object] = {
        "report_schema_version": "1.0.0",
        "dataset": config.dataset,
        "status": "passed",
        "random_seed": config.random_seed,
        "source_rows": fit_details["source_rows"],
        "candidate_duplicate_rows_removed": selection_counts["candidate_duplicate_rows_removed"],
        "projected_duplicate_rows_removed": fit_details["projected_duplicate_rows_removed"],
        "transformed_duplicate_rows_removed": output_details["transformed_duplicate_rows_removed"],
        "output_rows": sum(split_rows.values()),
        "categories": list(taxonomy.categories),
        "feature_schema_sha256": schema_hash,
        "split_manifest_sha256": split_manifest_hash,
        "preprocessing_state_sha256": state_hash,
        "feature_selection": {
            "fit_split": "train",
            "fit_rows": selection_counts["fit_rows"],
            "candidate_count": len(schema.candidate_features),
            "selected_count": len(features),
            "constant_features": removed_constants,
            "duplicate_features": removed_duplicates,
        },
        "imputation": {
            "fit_split": "train",
            "fit_rows": fit_details["fit_rows"],
            "replacements_by_feature": replacements,
        },
        "splits": report_splits,
        "leakage_checks": {
            "group_overlap": 0,
            "row_digest_overlap": 0,
            "duplicate_feature_label_rows_across_splits": 0,
            "final_test_rows_used_for_fitting": 0,
            "non_finite_output_values": 0,
        },
    }
    _write_json(report_json, report)
    report_markdown.parent.mkdir(parents=True, exist_ok=True)
    report_markdown.write_text(_markdown_report(report), encoding="utf-8")
    return report
