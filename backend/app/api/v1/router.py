"""Versioned API router.

Endpoints are registered as they are implemented. Authentication, projects,
images, generation and results belong here, each in its own module under
``endpoints/``.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.endpoints import auth, generation, images, projects, results

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(projects.router)
api_router.include_router(images.router)
api_router.include_router(generation.router)
api_router.include_router(results.router)
