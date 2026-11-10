"""Object-generation pipeline orchestration (06_object_generation.md Section 13).

This module is independent of Celery and PostgreSQL: the worker adapter supplies
bytes, a task-specific working directory and callbacks for real stage reporting,
heartbeats and cooperative cancellation. That keeps the pipeline directly
testable and makes the standalone 5.2 proof use exactly the production path.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import ObjectGenerationConfig
from .exceptions import (
    GLB_EXPORT_FAILED,
    ExportError,
    ObjectGenerationError,
)
from .exporter import export_glb
from .generator import TripoSRGenerator
from .model_loader import cleanup_gpu
from .preprocessing import (
    decode_image,
    get_rembg_session,
    prepare_model_input,
    save_intermediates,
)
from .validator import GLBValidation

logger = logging.getLogger(__name__)

# The only stages a pipeline may persist (06 Section 13.3). COMPLETED is a task
# status, never a stage.
STAGE_IMAGE_PREPARATION = "IMAGE_PREPARATION"
STAGE_MODEL_GENERATION = "MODEL_GENERATION"
STAGE_MODEL_EXPORT = "MODEL_EXPORT"
STAGE_RESULT_VALIDATION = "RESULT_VALIDATION"
STAGES = (
    STAGE_IMAGE_PREPARATION,
    STAGE_MODEL_GENERATION,
    STAGE_MODEL_EXPORT,
    STAGE_RESULT_VALIDATION,
)

DEFAULT_GLB_NAME = "model.glb"


@dataclass(frozen=True, slots=True)
class GeneratedAsset:
    """A validated GLB on disk, ready for transactional result registration."""

    path: Path
    sha256: str
    file_size_bytes: int
    format: str
    mime_type: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def validation(self) -> dict[str, Any] | None:
        """Return the stored validation metadata, if present."""
        value = self.metadata.get("glb_validation")
        return value if isinstance(value, dict) else None


@dataclass(slots=True)
class PipelineCallbacks:
    """Hooks the worker adapter provides; every hook is optional in tests."""

    report_stage: Callable[[str, str], None] = lambda stage, message: None
    heartbeat: Callable[[], None] = lambda: None
    raise_if_cancelled: Callable[[], None] = lambda: None


def _save_run_manifest(work_dir: Path, payload: dict[str, Any]) -> None:
    """Write diagnostics beside the intermediate images, never to storage."""
    try:
        (work_dir / "run.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8"
        )
    except OSError:
        logger.warning("generation_manifest_write_failed", extra={"operation": "object_generation"})


def run_object_generation(
    *,
    image_bytes: bytes,
    config: ObjectGenerationConfig,
    work_dir: Path,
    callbacks: PipelineCallbacks | None = None,
    generator: TripoSRGenerator | None = None,
    max_image_dimension: int = 8192,
) -> GeneratedAsset:
    """Run preprocessing, inference, extraction, export and validation.

    Returns the validated artifact. Raises :class:`ObjectGenerationError` for
    expected failures; unexpected exceptions propagate so the worker records
    ``GENERATION_FAILED`` and keeps the traceback in its log.
    """
    hooks = callbacks or PipelineCallbacks()
    started = time.monotonic()
    work_dir.mkdir(parents=True, exist_ok=True)
    output_dir = work_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "stages": [],
        "config": {
            "model_revision": config.model_revision,
            "device": config.device,
            "chunk_size": config.chunk_size,
            "mc_resolution": config.mc_resolution,
            "remove_background": config.remove_background,
            "foreground_ratio": config.foreground_ratio,
            "output_format": config.output_format,
            "bake_texture": config.bake_texture,
        },
    }

    try:
        hooks.raise_if_cancelled()
        hooks.heartbeat()
        hooks.report_stage(STAGE_IMAGE_PREPARATION, "Preparing the source photograph")
        image, source_format = decode_image(image_bytes, max_dimension=max_image_dimension)

        # rembg is initialized once per process and reused across tasks; when
        # background removal is disabled it is never loaded.
        session = get_rembg_session(config.rembg_model) if config.remove_background else None
        preprocess_started = time.perf_counter()
        preprocessed = prepare_model_input(
            image, config=config, session=session, source_format=source_format
        )
        preprocess_seconds = time.perf_counter() - preprocess_started
        processed_path = save_intermediates(
            work_dir=work_dir,
            original_bytes=image_bytes,
            result=preprocessed,
            suffix=f".{source_format.lower()}",
        )
        manifest["stages"].append(STAGE_IMAGE_PREPARATION)
        manifest["preprocessing"] = {
            "seconds": round(preprocess_seconds, 3),
            "source_width": preprocessed.source_width,
            "source_height": preprocessed.source_height,
            "foreground_bbox": list(preprocessed.foreground_bbox),
            "background_removed": preprocessed.background_removed,
            "input_width": preprocessed.width,
            "input_height": preprocessed.height,
        }

        hooks.raise_if_cancelled()
        hooks.heartbeat()
        hooks.report_stage(STAGE_MODEL_GENERATION, "Running TripoSR inference")
        active_generator = generator or TripoSRGenerator(config)
        generated = active_generator.generate(preprocessed.image, started_at=started)
        manifest["stages"].append(STAGE_MODEL_GENERATION)
        manifest["mesh"] = generated.stats.as_metadata()
        manifest["timing"] = {
            "preprocessing_seconds": round(preprocess_seconds, 3),
            "inference_seconds": round(generated.inference_seconds, 3),
            "extraction_seconds": round(generated.extraction_seconds, 3),
        }

        hooks.raise_if_cancelled()
        hooks.heartbeat()
        hooks.report_stage(STAGE_MODEL_EXPORT, "Exporting the GLB asset")
        glb_path = output_dir / DEFAULT_GLB_NAME
        export_started = time.perf_counter()
        validation = export_glb(generated.mesh, glb_path)
        export_seconds = time.perf_counter() - export_started
        manifest["stages"].append(STAGE_MODEL_EXPORT)
        manifest["timing"]["export_seconds"] = round(export_seconds, 3)

        hooks.raise_if_cancelled()
        hooks.heartbeat()
        hooks.report_stage(STAGE_RESULT_VALIDATION, "Validating the generated asset")
        final_validation = _final_validation(glb_path, validation)
        manifest["stages"].append(STAGE_RESULT_VALIDATION)
        manifest["glb_validation"] = final_validation.as_metadata()
        manifest["total_seconds"] = round(time.monotonic() - started, 3)
        _save_run_manifest(work_dir, manifest)

        return GeneratedAsset(
            path=glb_path,
            sha256=final_validation.sha256,
            file_size_bytes=final_validation.file_size_bytes,
            format="GLB",
            mime_type="model/gltf-binary",
            metadata={
                "vertices_count": final_validation.vertices_count,
                "faces_count": final_validation.faces_count,
                "meshes_count": final_validation.meshes_count,
                "primitives_count": final_validation.primitives_count,
                "materials_count": final_validation.materials_count,
                "textures_count": final_validation.textures_count,
                "has_vertex_colors": final_validation.has_vertex_colors,
                "bounding_box": final_validation.bounding_box,
                "glb_validation": final_validation.as_metadata(),
                "generation": manifest["config"],
                "source_image": {
                    "width": preprocessed.source_width,
                    "height": preprocessed.source_height,
                    "format": preprocessed.source_format,
                },
                "preprocessed_path": str(processed_path.name),
                "timing": manifest["timing"],
            },
        )
    except ObjectGenerationError:
        manifest["total_seconds"] = round(time.monotonic() - started, 3)
        _save_run_manifest(work_dir, manifest)
        raise
    except Exception:
        manifest["total_seconds"] = round(time.monotonic() - started, 3)
        _save_run_manifest(work_dir, manifest)
        raise
    finally:
        cleanup_gpu()


def _final_validation(path: Path, first: GLBValidation) -> GLBValidation:
    """Re-validate the exported file at the RESULT_VALIDATION stage."""
    from .validator import validate_glb

    try:
        final = validate_glb(path)
    except Exception as exc:
        raise ExportError(GLB_EXPORT_FAILED, "The exported GLB failed final validation.") from exc
    if final.sha256 != first.sha256 or final.file_size_bytes != first.file_size_bytes:
        raise ExportError(GLB_EXPORT_FAILED, "The exported GLB changed after validation.")
    return final


def build_config_from_settings(settings: Any) -> ObjectGenerationConfig:
    """Map validated backend settings onto the pipeline configuration.

    Kept in one place so the API and the worker cannot drift in their defaults.
    ``settings`` is duck-typed to keep this package independent of ``app``.
    """
    return ObjectGenerationConfig(
        model_dir=Path(settings.object_model_dir),
        model_revision=settings.object_model_revision,
        model_sha256=settings.object_model_sha256,
        device=settings.object_device,
        allow_cpu_fallback=settings.object_allow_cpu_fallback,
        chunk_size=settings.object_chunk_size,
        mc_resolution=settings.object_mc_resolution,
        remove_background=settings.object_remove_background,
        foreground_ratio=settings.object_foreground_ratio,
        output_format=settings.object_output_format,
        bake_texture=settings.object_bake_texture,
        texture_resolution=settings.object_texture_resolution,
        max_task_seconds=settings.object_max_task_seconds,
        rembg_model=settings.object_rembg_model,
        input_size=settings.object_input_size,
    )


__all__ = [
    "DEFAULT_GLB_NAME",
    "GeneratedAsset",
    "PipelineCallbacks",
    "STAGES",
    "STAGE_IMAGE_PREPARATION",
    "STAGE_MODEL_EXPORT",
    "STAGE_MODEL_GENERATION",
    "STAGE_RESULT_VALIDATION",
    "build_config_from_settings",
    "run_object_generation",
]
