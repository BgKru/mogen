"""Explicit generator factory (13_advanced_object_generation.md Section 4.2).

A small allowlist is enough: there is no plugin framework, no model marketplace
and no per-request selection. The configured generator is resolved once per
worker process and cached, so the request path never re-loads weights or races a
second model onto the GPU.
"""

from __future__ import annotations

import contextlib
import threading

from .config import BLOCKED_GENERATORS, SUPPORTED_GENERATORS, ObjectGenerationConfig
from .exceptions import GENERATOR_NOT_AVAILABLE, GeneratorUnavailableError
from .generator_base import ObjectGenerator

_generator_lock = threading.Lock()
_generator_cache: dict[tuple[str, str, str, str], ObjectGenerator] = {}


def available_generators() -> tuple[str, ...]:
    """Return the generator names this build can actually instantiate."""
    return SUPPORTED_GENERATORS


def _cache_key(config: ObjectGenerationConfig) -> tuple[str, str, str, str]:
    name = config.generator.strip().lower()
    model_dir = str(config.sf3d.model_dir) if name == "sf3d" else str(config.model_dir)
    revision = config.sf3d.model_revision if name == "sf3d" else config.model_revision
    return (name, model_dir, revision, config.device)


def _build(config: ObjectGenerationConfig) -> ObjectGenerator:
    name = (config.generator or "").strip().lower()
    if name in BLOCKED_GENERATORS:
        message = (
            "The Hunyuan3D adapter is not available in this build. Its licence "
            "and 12 GB hardware checks were not satisfied, so it cannot be "
            "selected (13_advanced_object_generation.md Section 5.2)."
        )
        raise GeneratorUnavailableError(GENERATOR_NOT_AVAILABLE, message)
    if name == "triposr":
        from .generator import TripoSRAdapter

        return TripoSRAdapter(config)
    if name == "sf3d":
        # Imported lazily so a TripoSR-only deployment never imports torch's
        # SF3D dependency set (13 Section 7).
        from .sf3d.adapter import SF3DAdapter

        return SF3DAdapter(config)
    message = (
        f"Object generator {config.generator!r} is not installed; "
        f"available generators are {_available_text()}"
    )
    raise GeneratorUnavailableError(GENERATOR_NOT_AVAILABLE, message)


def _available_text() -> str:
    return ", ".join(SUPPORTED_GENERATORS)


def create_generator(
    config: ObjectGenerationConfig,
    *,
    load: bool = True,
) -> ObjectGenerator:
    """Return the configured generator, loading it once per process.

    ``load=False`` is used by unit tests and by callers that only need the
    contract; the pipeline calls ``load()`` (idempotent) before inference.
    """
    name = (config.generator or "").strip().lower()
    if name not in SUPPORTED_GENERATORS and name not in BLOCKED_GENERATORS:
        message = (
            f"Object generator {config.generator!r} is not installed; "
            f"available generators are {_available_text()}"
        )
        raise GeneratorUnavailableError(GENERATOR_NOT_AVAILABLE, message)

    key = _cache_key(config)
    with _generator_lock:
        generator = _generator_cache.get(key)
        created = generator is None
        if generator is None:
            generator = _build(config)
            _generator_cache[key] = generator
    try:
        if load:
            generator.load()
    except Exception:
        if created:
            with _generator_lock:
                _generator_cache.pop(key, None)
        raise
    return generator


def reset_generators() -> None:
    """Drop cached adapters (tests and worker shutdown)."""
    with _generator_lock:
        for generator in _generator_cache.values():
            with contextlib.suppress(Exception):
                generator.unload()
        _generator_cache.clear()


__all__ = [
    "available_generators",
    "create_generator",
    "reset_generators",
]
