"""FastAPI application entry point for versioned IDS inference."""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path, PurePath
from typing import Annotated, Any, cast

from fastapi import FastAPI, File, Request, UploadFile, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse, Response
from starlette.datastructures import Headers, MutableHeaders
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from backend.app.config import Settings
from backend.app.errors import APIError, error_response, request_id
from backend.app.inference import InferenceService
from backend.app.schemas import (
    BatchPredictionResponse,
    HealthResponse,
    ModelResponse,
    PredictionRequest,
    ReadinessReady,
    ReadinessUnavailable,
)

LOGGER = logging.getLogger("ids_api")
ACCESS_LOGGER = logging.getLogger("ids_api.access")
CSV_MEDIA_TYPES = {"text/csv", "application/csv", "application/vnd.ms-excel"}
PREDICTION_PATHS = {"/api/v1/predictions", "/api/v1/predictions/file"}
MULTIPART_OVERHEAD_BYTES = 256 * 1024


class RequestGuardMiddleware:
    """Bound request bodies, add correlation/security headers, and log metadata only."""

    def __init__(self, app: ASGIApp, *, settings: Settings) -> None:
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        identifier = f"req_{uuid.uuid4().hex}"
        scope.setdefault("state", {})["request_id"] = identifier
        headers = Headers(scope=scope)
        path = str(scope.get("path", ""))
        method = str(scope.get("method", ""))
        protected = method == "POST" and path in PREDICTION_PATHS
        request_limit = self.settings.max_upload_bytes + MULTIPART_OVERHEAD_BYTES
        status_code = 500
        error_code: str | None = None
        response_started = False

        async def guarded_send(message: Message) -> None:
            nonlocal status_code, error_code, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status_code = int(message["status"])
                response_headers = MutableHeaders(scope=message)
                response_headers["X-Request-ID"] = identifier
                response_headers["X-Content-Type-Options"] = "nosniff"
                response_headers["X-Frame-Options"] = "DENY"
                response_headers["Referrer-Policy"] = "no-referrer"
                response_headers["Cache-Control"] = "no-store"
                error_code = response_headers.get("X-Error-Code")
            await send(message)

        def too_large() -> APIError:
            return APIError(
                413,
                "FILE_TOO_LARGE",
                "The request exceeds the configured byte limit.",
                details={"maximum_request_bytes": request_limit},
            )

        async def reject(error: APIError) -> None:
            request = Request(scope)
            await error_response(request, error)(scope, receive, guarded_send)

        content_length = headers.get("content-length")
        if protected and content_length is not None:
            try:
                declared_size = int(content_length)
            except ValueError:
                declared_size = -1
            if declared_size < 0:
                await reject(
                    APIError(
                        400,
                        "INVALID_REQUEST",
                        "Content-Length must be a non-negative integer.",
                    )
                )
                self._log(identifier, method, path, status_code, error_code)
                return
            if declared_size > request_limit:
                await reject(too_large())
                self._log(identifier, method, path, status_code, error_code)
                return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if protected and message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > request_limit:
                    raise too_large()
            return message

        try:
            await self.app(scope, limited_receive, guarded_send)
        except APIError as error:
            if response_started:
                raise
            await reject(error)
        finally:
            self._log(identifier, method, path, status_code, error_code)

    @staticmethod
    def _log(
        identifier: str,
        method: str,
        path: str,
        status_code: int,
        error_code: str | None,
    ) -> None:
        ACCESS_LOGGER.info(
            json.dumps(
                {
                    "event": "request_complete",
                    "request_id": identifier,
                    "method": method,
                    "path": path,
                    "status_code": status_code,
                    "error_code": error_code,
                },
                sort_keys=True,
            )
        )


def _unavailable() -> APIError:
    return APIError(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "MODEL_UNAVAILABLE",
        "The inference model is not available.",
    )


def create_app(
    settings: Settings | None = None,
    service_factory: Callable[[Path], InferenceService] | None = None,
) -> FastAPI:
    """Create an isolated application for production or contract tests."""

    runtime = settings or Settings.from_env()
    loader = service_factory or InferenceService.load

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        try:
            application.state.model_service = loader(runtime.artifact_dir)
            application.state.model_error = None
            application.openapi_schema = None
            LOGGER.info(
                "model_ready model_version=%s",
                application.state.model_service.model_version,
            )
        except Exception as error:  # startup must preserve liveness while reporting not-ready
            application.state.model_service = None
            application.state.model_error = type(error).__name__
            LOGGER.error("model_unavailable error_type=%s", type(error).__name__)
        yield
        application.state.model_service = None

    application = FastAPI(
        title="AI-Powered Intrusion Detection System",
        version="1.0.0",
        description=(
            "Versioned batch inference for CIC-IDS2017-compatible network-flow features. "
            "Scores are decision support, not proof of an attack."
        ),
        lifespan=lifespan,
        debug=False,
    )
    application.state.model_service = None
    application.state.model_error = "model_not_loaded"
    application.state.settings = runtime
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(runtime.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
        expose_headers=[
            "X-Request-ID",
            "X-Model-Version",
            "X-Feature-Schema-Version",
            "X-Feature-Schema-Hash",
        ],
    )
    application.add_middleware(RequestGuardMiddleware, settings=runtime)

    @application.exception_handler(APIError)
    async def handle_api_error(request: Request, error: APIError) -> JSONResponse:
        return error_response(request, error)

    @application.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        fields = sorted(
            {
                ".".join(str(part) for part in item["loc"] if part not in {"body", "query"})
                for item in error.errors()
            }
        )
        return error_response(
            request,
            APIError(
                422,
                "INVALID_REQUEST",
                "The request body does not match the API schema.",
                details={"fields": fields},
            ),
        )

    @application.exception_handler(StarletteHTTPException)
    async def handle_http_error(request: Request, error: StarletteHTTPException) -> JSONResponse:
        return error_response(
            request,
            APIError(
                error.status_code,
                "INVALID_REQUEST",
                "The HTTP request could not be processed.",
            ),
        )

    @application.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, error: Exception) -> JSONResponse:
        LOGGER.error(
            "request_failed request_id=%s error_type=%s",
            request_id(request),
            type(error).__name__,
        )
        return error_response(
            request,
            APIError(500, "INFERENCE_FAILED", "The request could not be completed safely."),
        )

    def service() -> InferenceService:
        loaded = application.state.model_service
        if not isinstance(loaded, InferenceService):
            raise _unavailable()
        return loaded

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
        response_model=ReadinessReady,
        responses={503: {"model": ReadinessUnavailable}},
        tags=["system"],
        summary="Model readiness",
    )
    def readiness() -> ReadinessReady | JSONResponse:
        loaded = application.state.model_service
        if not isinstance(loaded, InferenceService):
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content=ReadinessUnavailable(
                    status="not_ready", reason="model_not_loaded"
                ).model_dump(),
            )
        return ReadinessReady(status="ready", model_version=loaded.model_version)

    @application.get(
        "/api/v1/model",
        response_model=ModelResponse,
        responses={503: {"description": "The artifact is unavailable or incompatible."}},
        tags=["model"],
        summary="Active model metadata",
    )
    def model_metadata() -> ModelResponse:
        return service().model_response()

    @application.get(
        "/api/v1/input-template",
        response_class=Response,
        responses={
            200: {
                "content": {"text/csv": {"schema": {"type": "string"}}},
                "description": "Required headers and one synthetic example row.",
            }
        },
        tags=["model"],
        summary="Download a model-compatible CSV template",
    )
    def input_template() -> Response:
        loaded = service()
        return Response(
            content=loaded.template_csv(),
            media_type="text/csv",
            headers={
                "Content-Disposition": 'attachment; filename="ids-input-template.csv"',
                "X-Model-Version": loaded.bundle.model_version,
                "X-Feature-Schema-Version": loaded.bundle.feature_schema_version,
                "X-Feature-Schema-Hash": loaded.bundle.feature_schema_hash,
            },
        )

    @application.post(
        "/api/v1/predictions",
        response_model=BatchPredictionResponse,
        responses={
            400: {"description": "Empty or malformed input."},
            413: {"description": "Request or row limit exceeded."},
            422: {"description": "No usable records."},
            500: {"description": "Safe inference failure."},
            503: {"description": "Model unavailable."},
        },
        tags=["predictions"],
        summary="Score JSON flow-feature records",
    )
    def predict_json(payload: PredictionRequest, request: Request) -> BatchPredictionResponse:
        loaded = service()
        deadline = time.monotonic() + runtime.processing_timeout_seconds
        batch = loaded.validate_json(
            payload.records,
            max_rows=runtime.json_max_rows,
            deadline=deadline,
        )
        try:
            return loaded.predict(
                batch,
                request_id=request_id(request),
                deadline=deadline,
            )
        except APIError:
            raise
        except Exception as error:
            raise APIError(
                500,
                "INFERENCE_FAILED",
                "The model could not score this request.",
            ) from error

    @application.post(
        "/api/v1/predictions/file",
        response_model=BatchPredictionResponse,
        responses={
            400: {"description": "Empty or malformed CSV."},
            413: {"description": "File, row, or column limit exceeded."},
            415: {"description": "Unsupported media type or encoding."},
            422: {"description": "No usable CSV rows."},
            500: {"description": "Safe inference failure."},
            503: {"description": "Model unavailable."},
        },
        tags=["predictions"],
        summary="Score an uploaded CSV",
    )
    async def predict_file(
        request: Request,
        file: Annotated[
            UploadFile,
            File(description="UTF-8 CSV with the active model's required fields."),
        ],
    ) -> BatchPredictionResponse:
        loaded = service()
        deadline = time.monotonic() + runtime.processing_timeout_seconds
        try:
            filename = file.filename or ""
            if "/" in filename or "\\" in filename or PurePath(filename).name != filename:
                raise APIError(
                    400,
                    "INVALID_FILENAME",
                    "The uploaded filename must not contain a path.",
                )
            if PurePath(filename).suffix.casefold() != ".csv":
                raise APIError(
                    415,
                    "UNSUPPORTED_FILE_TYPE",
                    "The uploaded file must have a .csv extension.",
                )
            media_type = (file.content_type or "").split(";", maxsplit=1)[0].strip().lower()
            if media_type not in CSV_MEDIA_TYPES:
                raise APIError(
                    415,
                    "UNSUPPORTED_MEDIA_TYPE",
                    "The uploaded file must use a CSV media type.",
                )
            payload = await file.read(runtime.max_upload_bytes + 1)
            if len(payload) > runtime.max_upload_bytes:
                raise APIError(
                    413,
                    "FILE_TOO_LARGE",
                    "CSV files may not exceed the configured byte limit.",
                    details={"maximum_bytes": runtime.max_upload_bytes},
                )
            if time.monotonic() > deadline:
                raise APIError(
                    504,
                    "PROCESSING_TIMEOUT",
                    "The request exceeded the configured processing time limit.",
                )
            batch = loaded.validate_csv(
                payload,
                max_rows=runtime.csv_max_rows,
                max_columns=runtime.max_columns,
                deadline=deadline,
            )
            try:
                return loaded.predict(
                    batch,
                    request_id=request_id(request),
                    deadline=deadline,
                )
            except APIError:
                raise
            except Exception as error:
                raise APIError(
                    500,
                    "INFERENCE_FAILED",
                    "The model could not score this request.",
                ) from error
        finally:
            await file.close()

    def custom_openapi() -> dict[str, Any]:
        if application.openapi_schema is not None:
            return application.openapi_schema
        schema = get_openapi(
            title=application.title,
            version=application.version,
            description=application.description,
            routes=application.routes,
        )
        loaded = application.state.model_service
        if isinstance(loaded, InferenceService):
            paths = cast(dict[str, Any], schema["paths"])
            json_operation = paths["/api/v1/predictions"]["post"]
            json_operation["requestBody"]["content"]["application/json"]["example"] = (
                loaded.json_example()
            )
            model_operation = paths["/api/v1/model"]["get"]
            model_operation["responses"]["200"]["content"]["application/json"]["example"] = (
                loaded.model_response().model_dump(mode="json")
            )
        application.openapi_schema = schema
        return schema

    application.openapi = custom_openapi  # type: ignore[method-assign]
    return application


app = create_app()
