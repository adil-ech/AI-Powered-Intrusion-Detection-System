"""Versioned request and response schemas for the inference API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

AttackCategory = Literal[
    "BENIGN",
    "DOS_DDOS",
    "PORT_SCAN",
    "BRUTE_FORCE",
    "WEB_ATTACK",
    "BOTNET",
    "INFILTRATION",
    "RARE_OTHER",
]


class StrictModel(BaseModel):
    """Reject misspelled envelope fields while leaving feature keys model-driven."""

    model_config = ConfigDict(extra="forbid")


class HealthResponse(StrictModel):
    status: Literal["ok"]


class ReadinessReady(StrictModel):
    status: Literal["ready"]
    model_version: str


class ReadinessUnavailable(StrictModel):
    status: Literal["not_ready"]
    reason: Literal["model_not_loaded"]


class Thresholds(StrictModel):
    malicious: float
    low_confidence: float
    high_risk: float


class ModelResponse(StrictModel):
    model_name: str
    model_version: str
    artifact_status: Literal["READY"]
    training_dataset: str
    feature_schema_version: str
    feature_schema_hash: str
    required_features: list[str]
    attack_categories: list[AttackCategory]
    thresholds: Thresholds
    created_at: str


class PredictionInputRecord(StrictModel):
    row_id: str | None = Field(default=None, min_length=1, max_length=128)
    features: dict[str, Any]


class PredictionRequest(StrictModel):
    records: list[PredictionInputRecord]


class ResponseModelIdentity(StrictModel):
    name: str
    version: str
    feature_schema_version: str


class PredictionSummary(StrictModel):
    total_rows: int
    valid_rows: int
    invalid_rows: int
    benign_rows: int
    suspicious_rows: int
    high_risk_rows: int
    category_counts: dict[str, int]


class Prediction(StrictModel):
    row_id: str
    is_suspicious: bool
    predicted_category: AttackCategory
    malicious_probability: float
    category_confidence: float | None
    confidence: float
    confidence_status: Literal["OK", "LOW_CONFIDENCE"]
    risk_level: Literal["LOW", "MEDIUM", "HIGH"]
    warnings: list[str]


class RowError(StrictModel):
    row_id: str
    code: str
    message: str
    fields: list[str]


class BatchPredictionResponse(StrictModel):
    request_id: str
    status: Literal["COMPLETE", "PARTIAL_SUCCESS"]
    model: ResponseModelIdentity
    summary: PredictionSummary
    predictions: list[Prediction]
    row_errors: list[RowError]
    warnings: list[str]
