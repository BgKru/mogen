"""Application errors that map directly onto the API error envelope."""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """An expected failure with a stable machine-readable error code.

    Services raise ``AppError``; the application handler renders it through
    ``app.core.errors.error_response`` (04 Section 15.2).
    """

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        details: Any = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details
        self.headers = headers
