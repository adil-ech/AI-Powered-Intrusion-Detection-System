"""Stable, privacy-safe API errors."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


class APIError(Exception):
    """An expected client- or service-facing failure."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}


def request_id(request: Request) -> str:
    """Return the correlation identifier assigned by middleware."""

    value = getattr(request.state, "request_id", "req_unavailable")
    return str(value)


def error_response(request: Request, error: APIError) -> JSONResponse:
    """Render the v1 error envelope without request values or tracebacks."""

    identifier = request_id(request)
    payload: dict[str, Any] = {
        "error": {
            "code": error.code,
            "message": error.message,
            "details": error.details,
            "request_id": identifier,
        }
    }
    return JSONResponse(
        status_code=error.status_code,
        content=payload,
        headers={"X-Request-ID": identifier, "X-Error-Code": error.code},
    )
