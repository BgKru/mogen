"""Health and dependency endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy.engine import Engine

from app.core.config import Settings
from app.db.session import database_is_available

router = APIRouter(tags=["health"])


def _redis_is_available(redis_url: str) -> bool:
    """Return whether Redis answers a ping. Never raises."""
    client = Redis.from_url(redis_url, socket_connect_timeout=1, socket_timeout=1)
    try:
        return bool(client.ping())
    except (RedisError, OSError):
        return False
    finally:
        client.close()


@router.get("/health/live", summary="Process liveness")
def live(request: Request) -> dict[str, str]:
    """Report that the API process is running."""
    settings: Settings = request.app.state.settings
    return {"status": "ok", "service": settings.app_name, "version": settings.version}


@router.get("/health/ready", summary="Readiness of essential dependencies")
def ready(request: Request) -> JSONResponse:
    """Report whether essential dependencies are reachable.

    Returns 503 when PostgreSQL is unavailable, because the API cannot serve
    project or task requests without it.
    """
    engine: Engine = request.app.state.engine
    database_ok = database_is_available(engine)
    checks = {"database": "ok" if database_ok else "unavailable"}

    if not database_ok:
        return JSONResponse(status_code=503, content={"status": "unavailable", "checks": checks})
    return JSONResponse(status_code=200, content={"status": "ready", "checks": checks})


@router.get("/health/dependencies", summary="Dependency health report")
def dependencies(request: Request) -> dict[str, Any]:
    """Report every dependency without failing the request.

    A degraded broker must not make project management unavailable, so this
    endpoint always returns 200 with per-dependency detail.
    """
    settings: Settings = request.app.state.settings
    engine: Engine = request.app.state.engine

    checks = {
        "database": "ok" if database_is_available(engine) else "unavailable",
        "redis": "ok" if _redis_is_available(settings.redis_url) else "unavailable",
    }
    healthy = all(value == "ok" for value in checks.values())
    return {"status": "ok" if healthy else "degraded", "checks": checks}
