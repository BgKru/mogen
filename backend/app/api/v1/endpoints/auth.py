"""Authentication endpoints (api_contracts.md Section 6)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from app.api.dependencies import (
    get_auth_service,
    get_current_auth,
    get_settings,
    require_allowed_origin,
    require_csrf,
)
from app.core.config import Settings
from app.core.security import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME
from app.schemas.auth import AuthResponse, CsrfResponse, LoginRequest, RegisterRequest
from app.schemas.user import UserResponse
from app.services.auth_service import AuthContext, AuthService

router = APIRouter(prefix="/auth", tags=["authentication"])


def _cookie_max_age(settings: Settings) -> int:
    return settings.session_ttl_hours * 3600


def _set_csrf_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=token,
        max_age=_cookie_max_age(settings),
        path="/",
        secure=settings.session_cookie_secure,
        httponly=False,
        samesite="lax",
    )


def _set_auth_cookies(
    response: Response,
    *,
    session_token: str,
    csrf_token: str,
    settings: Settings,
) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_token,
        max_age=_cookie_max_age(settings),
        path="/",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="lax",
    )
    _set_csrf_cookie(response, csrf_token, settings)


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    response.delete_cookie(CSRF_COOKIE_NAME, path="/")


@router.post(
    "/register",
    status_code=201,
    response_model=AuthResponse,
    dependencies=[Depends(require_allowed_origin)],
    summary="Register a user",
)
def register(
    payload: RegisterRequest,
    response: Response,
    service: Annotated[AuthService, Depends(get_auth_service)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthResponse:
    """Create an account and immediately establish an authenticated session."""
    user, session_token, csrf_token = service.register(payload.email, payload.password)
    _set_auth_cookies(
        response,
        session_token=session_token,
        csrf_token=csrf_token,
        settings=settings,
    )
    return AuthResponse(user=UserResponse.model_validate(user))


@router.post(
    "/login",
    status_code=200,
    response_model=AuthResponse,
    dependencies=[Depends(require_allowed_origin)],
    summary="Log in",
)
def login(
    payload: LoginRequest,
    response: Response,
    service: Annotated[AuthService, Depends(get_auth_service)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthResponse:
    """Verify credentials, open a session and set the auth cookies."""
    user, session_token, csrf_token = service.login(payload.email, payload.password)
    _set_auth_cookies(
        response,
        session_token=session_token,
        csrf_token=csrf_token,
        settings=settings,
    )
    return AuthResponse(user=UserResponse.model_validate(user))


@router.post(
    "/logout",
    status_code=204,
    dependencies=[Depends(require_csrf)],
    summary="Log out",
)
def logout(
    response: Response,
    auth: Annotated[AuthContext, Depends(get_current_auth)],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> None:
    """Revoke the current session and clear both cookies."""
    service.logout(auth.session)
    _clear_auth_cookies(response)


@router.get("/me", response_model=UserResponse, summary="Current user")
def current_user(
    auth: Annotated[AuthContext, Depends(get_current_auth)],
) -> UserResponse:
    """Return the authenticated user, or 401 when the session is invalid."""
    return UserResponse.model_validate(auth.user)


@router.get("/csrf", response_model=CsrfResponse, summary="Obtain a CSRF token")
def csrf_token(
    request: Request,
    response: Response,
    auth: Annotated[AuthContext, Depends(get_current_auth)],
    service: Annotated[AuthService, Depends(get_auth_service)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> CsrfResponse:
    """Return the session-bound CSRF token and set its readable cookie.

    The token is deterministic per session, so an already valid cookie is
    re-used and only its lifetime is refreshed.
    """
    existing_token = request.cookies.get(CSRF_COOKIE_NAME)
    if existing_token and service.csrf_token_is_valid(auth.session, existing_token):
        token = existing_token
    else:
        token = service.issue_csrf_token(auth.session)
    _set_csrf_cookie(response, token, settings)
    return CsrfResponse(csrf_token=token)
