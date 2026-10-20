"""Environment-backed API configuration with conservative defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _positive_int(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default))
    try:
        value = int(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be a positive integer") from error
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _positive_float(name: str, default: float) -> float:
    raw = os.environ.get(name, str(default))
    try:
        value = float(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be a positive number") from error
    if value <= 0:
        raise ValueError(f"{name} must be a positive number")
    return value


def _validate_origin(origin: str) -> str:
    if origin == "*":
        raise ValueError("IDS_CORS_ORIGINS must not contain a wildcard")
    parsed = urlsplit(origin)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("IDS_CORS_ORIGINS entries must be HTTP(S) origins without paths")
    return origin.rstrip("/")


@dataclass(frozen=True)
class Settings:
    """Runtime settings that can change without rebuilding the service."""

    artifact_dir: Path
    cors_origins: tuple[str, ...]
    json_max_rows: int = 1_000
    csv_max_rows: int = 10_000
    max_upload_bytes: int = 10 * 1024 * 1024
    max_columns: int = 120
    processing_timeout_seconds: float = 15.0

    @classmethod
    def from_env(cls) -> Settings:
        artifact_dir = Path(
            os.environ.get("IDS_MODEL_DIR", PROJECT_ROOT / "models/ids-rf-v1")
        ).expanduser()
        origins = tuple(
            _validate_origin(origin.strip())
            for origin in os.environ.get(
                "IDS_CORS_ORIGINS",
                "http://localhost:5173,http://localhost:8080",
            ).split(",")
            if origin.strip()
        )
        if not origins:
            raise ValueError("IDS_CORS_ORIGINS must contain at least one origin")
        if len(origins) != len(set(origins)):
            raise ValueError("IDS_CORS_ORIGINS must not contain duplicate origins")
        return cls(
            artifact_dir=artifact_dir,
            cors_origins=origins,
            json_max_rows=_positive_int("IDS_JSON_MAX_ROWS", 1_000),
            csv_max_rows=_positive_int("IDS_CSV_MAX_ROWS", 10_000),
            max_upload_bytes=_positive_int("IDS_MAX_UPLOAD_BYTES", 10 * 1024 * 1024),
            max_columns=_positive_int("IDS_MAX_COLUMNS", 120),
            processing_timeout_seconds=_positive_float("IDS_PROCESSING_TIMEOUT_SECONDS", 15.0),
        )
