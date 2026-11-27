"""Single-image object-generation pipeline (Phase 5, extended by increment 13).

Public surface:

* :func:`run_object_generation` — preprocessing, generator inference, output
  normalization, GLB export and validation, independent of Celery/PostgreSQL.
* :func:`build_config_from_settings` — maps validated backend settings.
* :func:`create_generator` — resolves the configured generator allowlist.
* :func:`object_generation.download_models` / ``sf3d.download_models`` —
  controlled weight/cache initialization.
"""

from __future__ import annotations

from .config import ObjectGenerationConfig, SF3DConfig
from .exceptions import ObjectGenerationError
from .generator_factory import available_generators, create_generator
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
    "SF3DConfig",
    "available_generators",
    "build_config_from_settings",
    "create_generator",
    "run_object_generation",
]

__version__ = "1.0.0"
