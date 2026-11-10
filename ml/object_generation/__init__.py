"""TripoSR object-generation pipeline (Phase 5).

Public surface:

* :func:`run_object_generation` — preprocessing, inference, mesh extraction,
  GLB export and validation, independent of Celery/PostgreSQL.
* :func:`build_config_from_settings` — maps validated backend settings.
* :func:`download_models` — controlled weight/cache initialization.
"""

from __future__ import annotations

from .config import ObjectGenerationConfig
from .exceptions import ObjectGenerationError
from .pipeline import (
    STAGES,
    GeneratedAsset,
    PipelineCallbacks,
    build_config_from_settings,
    run_object_generation,
)

__all__ = [
    "STAGES",
    "GeneratedAsset",
    "ObjectGenerationConfig",
    "ObjectGenerationError",
    "PipelineCallbacks",
    "build_config_from_settings",
    "run_object_generation",
]

__version__ = "1.0.0"
