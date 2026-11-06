"""Unit tests for project validation helpers (no database required).

Traceability: BE-AC-07 (project creation validation), API-AC-02 and API-AC-15
(error envelope consistency), TEST-AC-02.
"""

from __future__ import annotations

import pytest

from app.core.exceptions import AppError
from app.services.project_service import clamp_page_limit, normalize_project_name


def test_normalize_project_name_trims_surrounding_whitespace() -> None:
    assert normalize_project_name("  My 3D Project  ") == "My 3D Project"


def test_normalize_project_name_accepts_the_maximum_length() -> None:
    name = "x" * 150

    assert normalize_project_name(name) == name


@pytest.mark.parametrize("name", ["", "   ", "\t\n  "])
def test_normalize_project_name_rejects_blank_names(name: str) -> None:
    with pytest.raises(AppError) as exc_info:
        normalize_project_name(name)

    error = exc_info.value
    assert error.status_code == 422
    assert error.code == "PROJECT_NAME_INVALID"
    assert error.details[0]["field"] == "name"
    assert error.details[0]["code"] == "STRING_TOO_SHORT"


def test_normalize_project_name_rejects_overlong_names() -> None:
    with pytest.raises(AppError) as exc_info:
        normalize_project_name("x" * 151)

    error = exc_info.value
    assert error.status_code == 422
    assert error.code == "PROJECT_NAME_INVALID"
    assert error.details[0]["code"] == "STRING_TOO_LONG"


def test_normalize_project_name_ignores_whitespace_when_measuring() -> None:
    assert normalize_project_name(f"  {'x' * 150}  ") == "x" * 150


def test_clamp_page_limit_caps_at_the_configured_maximum() -> None:
    assert clamp_page_limit(20, 100) == 20
    assert clamp_page_limit(100, 100) == 100
    assert clamp_page_limit(1000, 100) == 100
    assert clamp_page_limit(5, 3) == 3


def test_clamp_page_limit_never_returns_zero() -> None:
    assert clamp_page_limit(0, 100) == 1
