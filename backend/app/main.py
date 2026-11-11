"""FastAPI application factory."""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.health import router as health_router
from app.api.v1.router import api_router
from app.core import logging as app_logging
from app.core.config import Settings, get_settings
from app.core.errors import error_code_for_status, error_response
from app.core.exceptions import AppError
from app.core.rate_limit import FixedWindowRateLimiter
from app.db.session import create_db_engine, create_session_factory

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Create and release process-wide resources."""
    settings: Settings = app.state.settings
    engine = create_db_engine(settings)
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)

    logger.info(
        "application_started",
        extra={"operation": "startup", "settings": settings.redacted()},
    )
    try:
        yield
    finally:
        engine.dispose()
        logger.info("application_stopped", extra={"operation": "shutdown"})


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI application.

    A settings instance can be injected for tests; production uses the
    environment-derived singleton.
    """
    settings = settings or get_settings()
    app_logging.configure_logging(service_name="api", level=settings.log_level)

    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        debug=False,
        lifespan=_lifespan,
        docs_url="/docs" if settings.enable_api_docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.enable_api_docs else None,
    )
    app.state.settings = settings
    # One limiter per application instance keeps counters isolated between
    # tests and API processes (Phase 9 decision; see app/core/rate_limit.py).
    app.state.auth_rate_limiter = (
        FixedWindowRateLimiter(
            limit=settings.auth_rate_limit_attempts,
            window_seconds=settings.auth_rate_limit_window_seconds,
        )
        if settings.auth_rate_limit_enabled
        else None
    )

    if settings.allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.allowed_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=[settings.request_id_header],
        )

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next) -> Response:
        """Correlate logs, errors and responses with a request identifier."""
        request_id = request.headers.get(settings.request_id_header) or uuid.uuid4().hex
        token = app_logging.set_request_id(request_id)
        try:
            response = await call_next(request)
        finally:
            app_logging.reset_request_id(token)
        response.headers[settings.request_id_header] = request_id
        return response

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> Response:
        """Render expected service failures through the standard envelope."""
        return error_response(
            exc.status_code,
            exc.code,
            exc.message,
            details=exc.details,
            headers=exc.headers,
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> Response:
        message = (
            exc.detail if isinstance(exc.detail, str) else "The request could not be completed."
        )
        return error_response(
            exc.status_code,
            error_code_for_status(exc.status_code),
            message,
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> Response:
        # api_contracts.md Section 12.2 defines field-validation details as
        # {field, code, message} with a stable uppercase code.
        details = [
            {
                "field": ".".join(str(part) for part in error.get("loc", ())[1:]) or None,
                "code": str(error.get("type", "value_error")).upper(),
                "message": error.get("msg", "Invalid value"),
            }
            for error in exc.errors()
        ]
        return error_response(
            422,
            "VALIDATION_ERROR",
            "The request is invalid.",
            details=details,
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> Response:
        logger.exception("unhandled_exception", extra={"operation": "request"})
        return error_response(
            500,
            "INTERNAL_SERVER_ERROR",
            "An unexpected error occurred.",
        )

    app.include_router(health_router)
    app.include_router(api_router, prefix=settings.api_v1_prefix)
    return app


app = create_app()
