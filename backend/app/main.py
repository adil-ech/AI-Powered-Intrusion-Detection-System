"""FastAPI application entry point."""

from typing import Literal

from fastapi import FastAPI, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Liveness response returned by the API process."""

    status: Literal["ok"]


class ReadinessResponse(BaseModel):
    """Readiness response used before a model artifact is available."""

    status: Literal["not_ready"]
    reason: Literal["model_not_loaded"]


def create_app() -> FastAPI:
    """Create the API application."""

    application = FastAPI(
        title="AI-Powered Intrusion Detection System",
        version="0.1.0",
        description="Network-flow intrusion detection API foundation.",
    )

    @application.get(
        "/health",
        response_model=HealthResponse,
        tags=["system"],
        summary="Process liveness",
    )
    def health() -> HealthResponse:
        return HealthResponse(status="ok")

    @application.get(
        "/ready",
        response_model=ReadinessResponse,
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        tags=["system"],
        summary="Model readiness",
    )
    def readiness() -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=ReadinessResponse(
                status="not_ready",
                reason="model_not_loaded",
            ).model_dump(),
        )

    return application


app = create_app()
