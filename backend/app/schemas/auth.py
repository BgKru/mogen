"""Authentication request and response schemas (api_contracts.md Section 6)."""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field

from app.schemas.user import UserResponse

# Hard upper bound that protects the hashing path; the configurable policy is
# enforced by AuthService (password_min_length/password_max_length).
_MAX_PASSWORD_INPUT = 1024


class RegisterRequest(BaseModel):
    """Registration payload; password confirmation is client-side only."""

    email: EmailStr
    password: str = Field(min_length=1, max_length=_MAX_PASSWORD_INPUT)


class LoginRequest(BaseModel):
    """Login payload."""

    email: EmailStr
    password: str = Field(min_length=1, max_length=_MAX_PASSWORD_INPUT)


class AuthResponse(BaseModel):
    """Response returned by registration and login."""

    user: UserResponse


class CsrfResponse(BaseModel):
    """Response returned by ``GET /api/v1/auth/csrf``."""

    csrf_token: str
