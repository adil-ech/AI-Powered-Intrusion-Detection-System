"""Artifact loading, input validation, and response formatting."""

from __future__ import annotations

import csv
import io
import json
import math
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

import numpy as np
from ids_ml.data.schema import normalize_column_name
from ids_ml.modeling.artifact import InferenceBundle, load_artifact

from backend.app.errors import APIError
from backend.app.schemas import (
    AttackCategory,
    BatchPredictionResponse,
    ModelResponse,
    Prediction,
    PredictionInputRecord,
    PredictionSummary,
    ResponseModelIdentity,
    RowError,
    Thresholds,
)

ALLOWED_CATEGORIES = {
    "BENIGN",
    "DOS_DDOS",
    "PORT_SCAN",
    "BRUTE_FORCE",
    "WEB_ATTACK",
    "BOTNET",
    "INFILTRATION",
    "RARE_OTHER",
}


def _check_deadline(deadline: float | None) -> None:
    if deadline is not None and time.monotonic() > deadline:
        raise APIError(
            504,
            "PROCESSING_TIMEOUT",
            "The request exceeded the configured processing time limit.",
        )


@dataclass(frozen=True)
class ValidatedRow:
    row_id: str
    values: tuple[float, ...]


@dataclass(frozen=True)
class ValidatedBatch:
    total_rows: int
    rows: tuple[ValidatedRow, ...]
    row_errors: tuple[RowError, ...]
    warnings: tuple[str, ...]


def _metadata_string(metadata: dict[str, Any], name: str) -> str:
    value = metadata.get(name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"artifact metadata field {name!r} must be a non-empty string")
    return value


def _canonical_names(names: list[str]) -> tuple[list[str], list[str]]:
    canonical = [normalize_column_name(name) for name in names]
    counts = Counter(canonical)
    duplicates = sorted(name for name, count in counts.items() if count > 1)
    return canonical, duplicates


def _extra_warning(extra: set[str]) -> str:
    return "Ignored extra columns: " + ", ".join(sorted(extra)) + "."


def _numeric_value(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


class InferenceService:
    """A verified immutable model bundle plus its public metadata."""

    def __init__(self, bundle: InferenceBundle, metadata: dict[str, Any]) -> None:
        self.bundle = bundle
        self.metadata = metadata
        categories = metadata.get("attack_categories")
        thresholds = metadata.get("thresholds")
        if categories != ["BENIGN", *bundle.attack_labels]:
            raise ValueError("artifact attack categories do not agree with the pipeline")
        if not isinstance(categories, list) or not set(categories).issubset(ALLOWED_CATEGORIES):
            raise ValueError("artifact contains categories outside API v1")
        if not isinstance(thresholds, dict):
            raise ValueError("artifact metadata thresholds must be an object")
        expected_thresholds = {
            "malicious": bundle.malicious_threshold,
            "low_confidence": bundle.low_confidence_threshold,
            "high_risk": bundle.high_risk_threshold,
        }
        if thresholds != expected_thresholds:
            raise ValueError("artifact thresholds do not agree with the pipeline")
        if not (
            0.0 <= bundle.malicious_threshold <= 1.0
            and 0.0 <= bundle.low_confidence_threshold < bundle.high_risk_threshold <= 1.0
        ):
            raise ValueError("artifact thresholds are outside the supported range")
        if not bundle.required_features or len(bundle.required_features) != len(
            set(bundle.required_features)
        ):
            raise ValueError("artifact required features are empty or duplicated")
        if len(bundle.required_features) != len(bundle.imputation_values):
            raise ValueError("artifact imputation state does not match required features")
        if not all(math.isfinite(value) for value in bundle.imputation_values):
            raise ValueError("artifact imputation state contains a non-finite value")
        for name in (
            "model_name",
            "model_version",
            "training_dataset",
            "feature_schema_version",
            "feature_schema_hash",
            "created_at",
        ):
            _metadata_string(metadata, name)
        if metadata.get("required_features") != list(bundle.required_features):
            raise ValueError("artifact metadata required features do not agree with the pipeline")

    @classmethod
    def load(cls, artifact_dir: Path) -> InferenceService:
        bundle, _ = load_artifact(artifact_dir)
        raw: object = json.loads((artifact_dir / "metadata.json").read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("artifact metadata must contain an object")
        return cls(bundle, raw)

    @property
    def model_version(self) -> str:
        return self.bundle.model_version

    def model_response(self) -> ModelResponse:
        categories = cast(list[AttackCategory], self.metadata["attack_categories"])
        return ModelResponse(
            model_name=_metadata_string(self.metadata, "model_name"),
            model_version=self.bundle.model_version,
            artifact_status="READY",
            training_dataset=_metadata_string(self.metadata, "training_dataset"),
            feature_schema_version=self.bundle.feature_schema_version,
            feature_schema_hash=self.bundle.feature_schema_hash,
            required_features=list(self.bundle.required_features),
            attack_categories=categories,
            thresholds=Thresholds(
                malicious=self.bundle.malicious_threshold,
                low_confidence=self.bundle.low_confidence_threshold,
                high_risk=self.bundle.high_risk_threshold,
            ),
            created_at=_metadata_string(self.metadata, "created_at"),
        )

    def template_csv(self) -> str:
        stream = io.StringIO(newline="")
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(["row_id", *self.bundle.required_features])
        writer.writerow(["synthetic-example", *self.bundle.imputation_values])
        return stream.getvalue()

    def json_example(self) -> dict[str, object]:
        return {
            "records": [
                {
                    "row_id": "synthetic-example",
                    "features": dict(
                        zip(
                            self.bundle.required_features,
                            self.bundle.imputation_values,
                            strict=True,
                        )
                    ),
                }
            ]
        }

    def validate_json(
        self,
        records: list[PredictionInputRecord],
        *,
        max_rows: int,
        deadline: float | None = None,
    ) -> ValidatedBatch:
        _check_deadline(deadline)
        if not records:
            raise APIError(400, "EMPTY_INPUT", "At least one record is required.")
        if len(records) > max_rows:
            raise APIError(
                413,
                "TOO_MANY_ROWS",
                f"JSON requests may contain at most {max_rows} records.",
                details={"maximum_rows": max_rows},
            )
        row_ids = [record.row_id or str(index) for index, record in enumerate(records, 1)]
        self._reject_duplicate_row_ids(row_ids)
        expected = set(self.bundle.required_features)
        valid: list[ValidatedRow] = []
        errors: list[RowError] = []
        extras: set[str] = set()
        for row_id, record in zip(row_ids, records, strict=True):
            _check_deadline(deadline)
            raw_names = list(record.features)
            names, duplicates = _canonical_names(raw_names)
            if duplicates:
                errors.append(
                    RowError(
                        row_id=row_id,
                        code="DUPLICATE_COLUMNS",
                        message="Feature names collide after canonicalization.",
                        fields=duplicates,
                    )
                )
                continue
            canonical = dict(zip(names, record.features.values(), strict=True))
            missing = sorted(expected - set(canonical))
            if missing:
                errors.append(
                    RowError(
                        row_id=row_id,
                        code="MISSING_REQUIRED_COLUMNS",
                        message="The record is missing required features.",
                        fields=missing,
                    )
                )
                continue
            extras.update(set(canonical) - expected)
            values: list[float] = []
            invalid: list[str] = []
            for feature in self.bundle.required_features:
                number = _numeric_value(canonical[feature])
                if number is None:
                    invalid.append(feature)
                else:
                    values.append(number)
            if invalid:
                errors.append(
                    RowError(
                        row_id=row_id,
                        code="INVALID_FEATURE_VALUE",
                        message="One or more feature values are invalid.",
                        fields=invalid,
                    )
                )
            else:
                valid.append(ValidatedRow(row_id=row_id, values=tuple(values)))
        warnings = (_extra_warning(extras),) if extras else ()
        return self._finish_validation(len(records), valid, errors, warnings)

    def validate_csv(
        self,
        payload: bytes,
        *,
        max_rows: int,
        max_columns: int,
        deadline: float | None = None,
    ) -> ValidatedBatch:
        _check_deadline(deadline)
        if not payload:
            raise APIError(400, "EMPTY_INPUT", "The uploaded CSV is empty.")
        try:
            text = payload.decode("utf-8-sig", errors="strict")
        except UnicodeDecodeError as error:
            raise APIError(
                415,
                "UNSUPPORTED_ENCODING",
                "The uploaded CSV must use UTF-8 encoding.",
            ) from error
        if "\x00" in text:
            raise APIError(400, "INVALID_CSV", "The uploaded file is not a valid CSV.")
        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        try:
            raw_header = next(reader)
        except StopIteration as error:
            raise APIError(400, "EMPTY_INPUT", "The uploaded CSV has no header.") from error
        except (csv.Error, UnicodeError) as error:
            raise APIError(400, "INVALID_CSV", "The uploaded file is not a valid CSV.") from error
        if not raw_header or not any(cell.strip() for cell in raw_header):
            raise APIError(400, "EMPTY_INPUT", "The uploaded CSV has no header.")
        if len(raw_header) > max_columns:
            raise APIError(
                413,
                "TOO_MANY_COLUMNS",
                f"CSV files may contain at most {max_columns} columns.",
                details={"maximum_columns": max_columns},
            )
        header, duplicates = _canonical_names(raw_header)
        if not all(header):
            raise APIError(400, "INVALID_CSV", "CSV headers must not be empty.")
        if duplicates:
            raise APIError(
                400,
                "DUPLICATE_COLUMNS",
                "CSV headers must be unique after canonicalization.",
                details={"columns": duplicates},
            )
        expected = set(self.bundle.required_features)
        supplied = set(header)
        missing = sorted(expected - supplied)
        if missing:
            raise APIError(
                422,
                "MISSING_REQUIRED_COLUMNS",
                "The uploaded CSV is missing required columns.",
                details={"columns": missing},
            )
        data_rows: list[list[str]] = []
        try:
            for row in reader:
                _check_deadline(deadline)
                if not row or not any(cell.strip() for cell in row):
                    continue
                data_rows.append(row)
                if len(data_rows) > max_rows:
                    raise APIError(
                        413,
                        "TOO_MANY_ROWS",
                        f"CSV files may contain at most {max_rows} data rows.",
                        details={"maximum_rows": max_rows},
                    )
        except APIError:
            raise
        except (csv.Error, UnicodeError) as error:
            raise APIError(400, "INVALID_CSV", "The uploaded file is not a valid CSV.") from error
        if not data_rows:
            raise APIError(400, "EMPTY_INPUT", "The uploaded CSV has no data rows.")
        if any(len(row) != len(header) for row in data_rows):
            raise APIError(
                400,
                "INVALID_CSV",
                "Every CSV row must contain the same number of columns as the header.",
            )
        indexes = {name: index for index, name in enumerate(header)}
        row_ids = [
            row[indexes["row_id"]].strip() or str(index) if "row_id" in indexes else str(index)
            for index, row in enumerate(data_rows, 1)
        ]
        self._reject_duplicate_row_ids(row_ids)
        extras = supplied - expected - {"row_id"}
        valid: list[ValidatedRow] = []
        errors: list[RowError] = []
        for row_id, row in zip(row_ids, data_rows, strict=True):
            _check_deadline(deadline)
            values: list[float] = []
            invalid: list[str] = []
            for feature in self.bundle.required_features:
                token = row[indexes[feature]].strip()
                try:
                    number = float(token)
                except ValueError:
                    number = math.nan
                if not math.isfinite(number):
                    invalid.append(feature)
                else:
                    values.append(number)
            if invalid:
                errors.append(
                    RowError(
                        row_id=row_id,
                        code="INVALID_FEATURE_VALUE",
                        message="One or more feature values are invalid.",
                        fields=invalid,
                    )
                )
            else:
                valid.append(ValidatedRow(row_id=row_id, values=tuple(values)))
        warnings = (_extra_warning(extras),) if extras else ()
        return self._finish_validation(len(data_rows), valid, errors, warnings)

    @staticmethod
    def _reject_duplicate_row_ids(row_ids: list[str]) -> None:
        duplicates = sorted(name for name, count in Counter(row_ids).items() if count > 1)
        if duplicates:
            raise APIError(
                422,
                "DUPLICATE_ROW_ID",
                "Row identifiers must be unique within a request.",
                details={"row_ids": duplicates},
            )

    @staticmethod
    def _finish_validation(
        total_rows: int,
        valid: list[ValidatedRow],
        errors: list[RowError],
        warnings: tuple[str, ...],
    ) -> ValidatedBatch:
        if not valid:
            raise APIError(
                422,
                "NO_VALID_ROWS",
                "No rows contained a complete set of finite numeric features.",
                details={
                    "row_errors": [error.model_dump(mode="json") for error in errors],
                },
            )
        return ValidatedBatch(
            total_rows=total_rows,
            rows=tuple(valid),
            row_errors=tuple(errors),
            warnings=warnings,
        )

    def predict(
        self,
        batch: ValidatedBatch,
        *,
        request_id: str,
        deadline: float | None = None,
    ) -> BatchPredictionResponse:
        _check_deadline(deadline)
        matrix = np.asarray([row.values for row in batch.rows], dtype=np.float64)
        binary, families = self.bundle.predict_probabilities(
            matrix, list(self.bundle.required_features)
        )
        _check_deadline(deadline)
        predictions: list[Prediction] = []
        counts: Counter[str] = Counter()
        high_risk = 0
        suspicious_rows = 0
        for index, row in enumerate(batch.rows):
            _check_deadline(deadline)
            malicious_probability = float(binary[index])
            suspicious = malicious_probability >= self.bundle.malicious_threshold
            category_confidence: float | None = None
            if suspicious:
                family_index = int(np.argmax(families[index]))
                category = self.bundle.attack_labels[family_index]
                category_confidence = float(families[index, family_index])
                confidence = malicious_probability * category_confidence
                suspicious_rows += 1
            else:
                category = "BENIGN"
                confidence = 1.0 - malicious_probability
            confidence_status: Literal["OK", "LOW_CONFIDENCE"] = (
                "OK" if confidence >= self.bundle.low_confidence_threshold else "LOW_CONFIDENCE"
            )
            if not suspicious or confidence < self.bundle.low_confidence_threshold:
                risk: Literal["LOW", "MEDIUM", "HIGH"] = "LOW"
            elif confidence < self.bundle.high_risk_threshold:
                risk = "MEDIUM"
            else:
                risk = "HIGH"
                high_risk += 1
            counts[category] += 1
            warnings = (
                []
                if confidence_status == "OK"
                else ["Prediction confidence is below the model threshold."]
            )
            predictions.append(
                Prediction(
                    row_id=row.row_id,
                    is_suspicious=suspicious,
                    predicted_category=cast(AttackCategory, category),
                    malicious_probability=malicious_probability,
                    category_confidence=category_confidence,
                    confidence=float(confidence),
                    confidence_status=confidence_status,
                    risk_level=risk,
                    warnings=warnings,
                )
            )
        valid_rows = len(batch.rows)
        invalid_rows = len(batch.row_errors)
        return BatchPredictionResponse(
            request_id=request_id,
            status="PARTIAL_SUCCESS" if invalid_rows else "COMPLETE",
            model=ResponseModelIdentity(
                name=_metadata_string(self.metadata, "model_name"),
                version=self.bundle.model_version,
                feature_schema_version=self.bundle.feature_schema_version,
            ),
            summary=PredictionSummary(
                total_rows=batch.total_rows,
                valid_rows=valid_rows,
                invalid_rows=invalid_rows,
                benign_rows=valid_rows - suspicious_rows,
                suspicious_rows=suspicious_rows,
                high_risk_rows=high_risk,
                category_counts=dict(sorted(counts.items())),
            ),
            predictions=predictions,
            row_errors=list(batch.row_errors),
            warnings=list(batch.warnings),
        )
