"""Structured JSON logging with request correlation."""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar, Token
from datetime import UTC, datetime
from typing import Any

REQUEST_ID: ContextVar[str | None] = ContextVar("request_id", default=None)
SERVICE_NAME: ContextVar[str] = ContextVar("service_name", default="api")

EXTRA_FIELDS = (
    "user_id",
    "project_id",
    "task_id",
    "cleanup_job_id",
    "operation",
    "error_code",
    "settings",
    # Workspace retention monitoring (roadmap 8.5, 07 Section 15.7).
    "workspace_usage",
)

_configured = False


def set_request_id(value: str) -> Token[str | None]:
    """Bind a request identifier to the current context."""
    return REQUEST_ID.set(value)


def reset_request_id(token: Token[str | None]) -> None:
    """Restore the previous request identifier."""
    REQUEST_ID.reset(token)


def get_request_id() -> str | None:
    """Return the request identifier bound to the current context, if any."""
    return REQUEST_ID.get()


class JsonFormatter(logging.Formatter):
    """Render log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "service": SERVICE_NAME.get(),
            "logger": record.name,
            "message": record.getMessage(),
        }

        request_id = REQUEST_ID.get()
        if request_id is not None:
            payload["request_id"] = request_id

        for field in EXTRA_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value

        if record.exc_info is not None:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False)


def configure_logging(service_name: str = "api", level: str = "INFO") -> None:
    """Configure process-wide structured logging.

    Safe to call more than once; only the level is updated on later calls.
    """
    global _configured  # noqa: PLW0603 - process-wide logging is a singleton

    SERVICE_NAME.set(service_name)
    root = logging.getLogger()

    if not _configured:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        root.handlers.clear()
        root.addHandler(handler)
        for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
            logger = logging.getLogger(name)
            logger.handlers.clear()
            logger.propagate = True
        _configured = True

    root.setLevel(level)
