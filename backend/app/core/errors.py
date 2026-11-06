"""Consistent API error responses."""

from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse

from app.core.logging import get_request_id

DEFAULT_ERROR_CODES: dict[int, str] = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    415: "UNSUPPORTED_MEDIA_TYPE",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
    500: "INTERNAL_SERVER_ERROR",
    503: "SERVICE_UNAVAILABLE",
}


def error_code_for_status(status_code: int) -> str:
    """Map an HTTP status code to a stable machine-readable error code."""
    return DEFAULT_ERROR_CODES.get(status_code, f"HTTP_{status_code}")


def error_payload(
    code: str,
    message: str,
    *,
    details: Any = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Build the documented error envelope."""
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details,
            "request_id": request_id if request_id is not None else get_request_id(),
        }
    }


def error_response(
    status_code: int,
    code: str,
    message: str,
    *,
    details: Any = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Build a JSON error response using the documented envelope."""
    return JSONResponse(
        status_code=status_code,
        content=error_payload(code, message, details=details),
        headers=headers,
    )
