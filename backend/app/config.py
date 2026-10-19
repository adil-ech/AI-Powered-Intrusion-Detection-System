"""Environment-backed API configuration with conservative defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    """Runtime settings that can change without rebuilding the service."""

    artifact_dir: Path
    cors_origins: tuple[str, ...]
    json_max_rows: int = 1_000
    csv_max_rows: int = 10_000
    max_upload_bytes: int = 10 * 1024 * 1024
    max_columns: int = 120

    @classmethod
    def from_env(cls) -> Settings:
        artifact_dir = Path(
            os.environ.get("IDS_MODEL_DIR", PROJECT_ROOT / "models/ids-rf-v1")
        ).expanduser()
        origins = tuple(
            origin.strip()
            for origin in os.environ.get(
                "IDS_CORS_ORIGINS",
                "http://localhost:5173,http://localhost:8080",
            ).split(",")
            if origin.strip()
        )
        if not origins:
            raise ValueError("IDS_CORS_ORIGINS must contain at least one origin")
        return cls(artifact_dir=artifact_dir, cors_origins=origins)
