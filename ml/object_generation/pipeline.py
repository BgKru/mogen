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
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from image_quality import (
    QUALITY_ANALYSIS_UNAVAILABLE,
    analyze_image,
    metric_algorithms,
    quality_config_from_settings,
)
from PIL import Image

from .config import ObjectGenerationConfig, SF3DConfig
from .enhancement import EnhancementConfig, enhance_object
from .exceptions import (
    GLB_EXPORT_FAILED,
    QUALITY_ANALYSIS_FAILED,
    ExportError,
    ImageQualityAnalysisError,
    ObjectGenerationError,
)
from .exporter import export_glb
from .generator_base import (
    GeneratorResult,
    ObjectGenerator,
    PreprocessingCapabilities,
)
from .generator_factory import create_generator
from .model_loader import cleanup_gpu
from .normalization import normalize_output
from .preprocessing import (
    decode_image,
    get_rembg_session,
    prepare_model_input,
    prepare_rgba_input,
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


def _analyze_original_image(
    image: Image.Image,
    *,
    config: ObjectGenerationConfig,
    image_id: str,
    filename: str,
) -> dict[str, Any] | None:
    """Run the advisory analyzer on the decoded original (11 Section 8.2).

    The analysis inspects the decoded photograph before background removal,
    cropping or resizing. A failure is advisory by default and is recorded as
    ``QUALITY_ANALYSIS_UNAVAILABLE``; only an explicitly required analysis
    raises, and then with the analysis-stage code, never an image rejection.
    """
    quality_config = config.image_quality
    if not quality_config.enabled:
        return None
    started = time.perf_counter()
    try:
        report = analyze_image(
            image,
            image_id=image_id,
            filename=filename,
            config=quality_config,
        )
    except Exception as exc:
        if quality_config.required:
            logger.exception(
                "image_quality_analysis_failed",
                extra={"operation": "object_generation"},
            )
            raise ImageQualityAnalysisError(
                QUALITY_ANALYSIS_FAILED,
                "The image quality analysis stage failed.",
            ) from exc
        logger.warning(
            "image_quality_analysis_unavailable",
            extra={"operation": "object_generation"},
        )
        return {"status": "UNAVAILABLE", "error_code": QUALITY_ANALYSIS_UNAVAILABLE}
    return {
        "status": "OK",
        "report": report.as_dict(),
        "thresholds": quality_config.as_thresholds(),
        "algorithms": metric_algorithms(),
        "seconds": round(time.perf_counter() - started, 4),
    }


def run_object_generation(
    *,
    image_bytes: bytes,
    config: ObjectGenerationConfig,
    work_dir: Path,
    callbacks: PipelineCallbacks | None = None,
    generator: ObjectGenerator | Any | None = None,
    max_image_dimension: int = 8192,
    image_id: str = "",
    filename: str = "",
) -> GeneratedAsset:
    """Run preprocessing, inference, normalization, export and validation.

    Returns the validated artifact. Raises :class:`ObjectGenerationError` for
    expected failures; unexpected exceptions propagate so the worker records
    ``GENERATION_FAILED`` and keeps the traceback in its log.

    ``generator`` is an optional test hook. Production passes ``None`` and the
    configured adapter is resolved once by the generator factory.
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
            "image_quality": config.image_quality.as_metadata(),
            # 13 Section 5.5: the selected generator policy is part of the run.
            "generator": config.generator,
            "generator_fallback": config.generator_fallback,
            "enhancement": config.enhancement.as_manifest(),
        },
    }

    try:
        hooks.raise_if_cancelled()
        hooks.heartbeat()
        hooks.report_stage(STAGE_IMAGE_PREPARATION, "Preparing the source photograph")
        image, source_format = decode_image(image_bytes, max_dimension=max_image_dimension)

        # 11 Section 8.2: analyze the decoded original before preprocessing. The
        # analysis works on bounded in-memory copies and never changes ``image``.
        quality_section = _analyze_original_image(
            image,
            config=config,
            image_id=image_id,
            filename=filename,
        )
        if quality_section is not None:
            manifest["image_quality"] = quality_section

        # Resolve the generator before preprocessing: a pre-inference fallback
        # must select the matching preprocessing contract, never feed TripoSR
        # an SF3D-shaped image (13 Section 4.2).
        active_generator, fallback = _resolve_generator(generator, config)
        capabilities = _capabilities_for(active_generator, config)
        manifest["config"]["generator_capabilities"] = capabilities.as_metadata()

        # rembg is initialized once per process and reused across tasks; when
        # background removal is disabled it is never loaded.
        session = get_rembg_session(config.rembg_model) if config.remove_background else None
        preprocess_started = time.perf_counter()
        if capabilities.mode == "rgba_foreground":
            # SF3D keeps the alpha channel and resizes internally; no composite,
            # exactly one background-removal/foreground pass (13 Section 5.4).
            preprocessed = prepare_rgba_input(
                image, config=config, session=session, source_format=source_format
            )
        else:
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
            "input_mode": capabilities.mode,
        }

        hooks.raise_if_cancelled()
        hooks.heartbeat()
        hooks.report_stage(
            STAGE_MODEL_GENERATION,
            f"Running the {getattr(active_generator, 'name', config.generator)} generator",
        )
        produced = active_generator.generate(preprocessed.image, started_at=started)
        generated = _as_generator_result(produced, active_generator, config)
        manifest["stages"].append(STAGE_MODEL_GENERATION)
        normalized = normalize_output(generated.mesh, generator=generated.name)
        manifest["mesh"] = normalized.stats.as_metadata()

        # 14 Section 4.1: enhancement runs between generator output and export.
        # It is inside MODEL_GENERATION so no persisted stage identifier changes;
        # every optional operation polls cancellation/heartbeat.
        hooks.raise_if_cancelled()
        hooks.heartbeat()

        def _enhancement_poll() -> None:
            hooks.raise_if_cancelled()
            hooks.heartbeat()

        enhancement = enhance_object(
            normalized.mesh,
            config.enhancement,
            on_poll=_enhancement_poll,
        )
        manifest["enhancement"] = enhancement.as_metadata()
        if enhancement.after is not None:
            manifest["mesh_after_enhancement"] = enhancement.after.as_metadata()

        generator_block: dict[str, Any] = generated.metadata()
        generator_block["preprocessing_capabilities"] = capabilities.as_metadata()
        generator_block["normalization"] = normalized.as_metadata()
        if fallback is not None:
            generator_block["fallback"] = fallback
        manifest["generator"] = generator_block
        manifest["timing"] = {
            "preprocessing_seconds": round(preprocess_seconds, 3),
            "inference_seconds": round(generated.inference_seconds, 3),
            "postprocessing_seconds": round(generated.postprocessing_seconds, 3),
        }
        if generated.name == "triposr":
            # Keep the Phase 5 key for TripoSR results.
            manifest["timing"]["extraction_seconds"] = round(generated.postprocessing_seconds, 3)

        hooks.raise_if_cancelled()
        hooks.heartbeat()
        hooks.report_stage(STAGE_MODEL_EXPORT, "Exporting the GLB asset")
        glb_path = output_dir / DEFAULT_GLB_NAME
        export_started = time.perf_counter()
        validation = export_glb(
            enhancement.mesh,
            glb_path,
            include_normals=enhancement.normal_export,
        )
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
                "has_textures": final_validation.has_textures,
                "bounding_box": final_validation.bounding_box,
                "glb_validation": final_validation.as_metadata(),
                "generation": manifest["config"],
                "generator": generator_block,
                "normalization": normalized.as_metadata(),
                "enhancement": enhancement.as_metadata(),
                "source_image": {
                    "width": preprocessed.source_width,
                    "height": preprocessed.source_height,
                    "format": preprocessed.source_format,
                },
                "preprocessed_path": str(processed_path.name),
                "timing": manifest["timing"],
                **({"image_quality": quality_section} if quality_section is not None else {}),
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


def _capabilities_for(
    generator: ObjectGenerator | Any | None, config: ObjectGenerationConfig
) -> PreprocessingCapabilities:
    """Return the prepared-image contract of the configured or injected adapter."""
    if generator is not None:
        capabilities = getattr(generator, "capabilities", None)
        if callable(capabilities):
            return capabilities()
        name = str(getattr(generator, "name", "") or config.generator).strip().lower()
    else:
        name = (config.generator or "").strip().lower()
    if name == "sf3d":
        # Without an injected adapter we can still describe what SF3D needs
        # before the model is loaded, which keeps preprocessing single-pass.
        return PreprocessingCapabilities(
            mode="rgba_foreground",
            background_removal=config.remove_background,
            alpha=True,
            foreground_crop=True,
            foreground_ratio=True,
            input_size=None,
            color_mode="RGBA",
        )
    return PreprocessingCapabilities(
        mode="rgb_composite",
        background_removal=config.remove_background,
        alpha=False,
        foreground_crop=True,
        foreground_ratio=True,
        input_size=config.input_size,
        color_mode="RGB",
    )


def _resolve_generator(
    generator: ObjectGenerator | Any | None, config: ObjectGenerationConfig
) -> tuple[ObjectGenerator | Any, dict[str, Any] | None]:
    """Resolve the configured adapter, applying only a pre-inference fallback."""
    if generator is not None:
        load = getattr(generator, "load", None)
        if callable(load):
            load()
        return generator, None

    try:
        return create_generator(config), None
    except ObjectGenerationError as exc:
        requested = (config.generator or "").strip().lower()
        if not config.generator_fallback or requested == "triposr":
            raise
        reason = getattr(exc, "error_code", "GENERATOR_NOT_AVAILABLE")
        logger.warning(
            "object_generator_fallback",
            extra={
                "operation": "object_generation",
                "requested_generator": requested,
                "fallback_generator": "triposr",
                "reason": reason,
            },
        )
        # Fallback happens before inference starts; once a generator ran, a
        # failure is reported as a task error (13 Section 4.2).
        return create_generator(replace(config, generator="triposr")), {
            "used": True,
            "reason": reason,
            "requested_generator": requested,
            "actual_generator": "triposr",
        }


def _as_generator_result(
    produced: Any, adapter: Any, config: ObjectGenerationConfig
) -> GeneratorResult:
    """Normalize a contract result or a legacy ``GeneratedMesh`` test double."""
    if isinstance(produced, GeneratorResult):
        return produced
    mesh = getattr(produced, "mesh", None)
    if mesh is None:
        message = "The generator returned an unsupported result type."
        raise TypeError(message)
    return GeneratorResult(
        mesh=mesh,
        name=getattr(adapter, "name", config.generator),
        revision=getattr(adapter, "revision", ""),
        model_id=getattr(adapter, "model_id", config.model_id),
        model_revision=getattr(adapter, "model_revision", config.model_revision),
        inference_seconds=float(getattr(produced, "inference_seconds", 0.0)),
        postprocessing_seconds=float(getattr(produced, "extraction_seconds", 0.0)),
        diagnostics={"legacy_generator_result": True},
    )


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
        model_id=settings.object_model_id,
        device=settings.object_device,
        allow_cpu_fallback=settings.object_allow_cpu_fallback,
        chunk_size=settings.object_chunk_size,
        mc_resolution=settings.object_mc_resolution,
        remove_background=settings.object_remove_background,
        foreground_ratio=settings.object_foreground_ratio,
        output_format=settings.object_output_format,
        max_task_seconds=settings.object_max_task_seconds,
        rembg_model=settings.object_rembg_model,
        input_size=settings.object_input_size,
        image_quality=quality_config_from_settings(settings),
        generator=settings.object_generator,
        generator_fallback=settings.object_generator_fallback,
        sf3d=SF3DConfig(
            enabled=settings.object_sf3d_enabled,
            model_id=settings.object_sf3d_model_id,
            model_revision=settings.object_sf3d_model_revision,
            model_dir=Path(settings.object_sf3d_model_dir),
            manifest_path=Path(settings.object_sf3d_manifest_path),
            texture_resolution=settings.object_sf3d_texture_resolution,
            remesh=settings.object_sf3d_remesh,
            target_vertex_count=settings.object_sf3d_target_vertex_count,
        ),
        bake_texture=settings.object_bake_texture,
        texture_resolution=settings.object_texture_resolution,
        enhancement=EnhancementConfig(
            cleanup_enabled=getattr(settings, "object_mesh_cleanup_enabled", True),
            merge_tolerance=getattr(settings, "object_mesh_merge_tolerance", 1e-6),
            remove_small_components=getattr(settings, "object_mesh_remove_small_components", False),
            small_component_faces=getattr(settings, "object_mesh_small_component_faces", 32),
            normals_enabled=getattr(settings, "object_mesh_normals_enabled", True),
            simplification_enabled=getattr(settings, "object_mesh_simplification_enabled", False),
            target_faces=getattr(settings, "object_mesh_target_faces", 0),
            max_deviation=getattr(settings, "object_mesh_max_deviation", 0.01),
            smoothing_iterations=getattr(settings, "object_mesh_smoothing_iterations", 0),
            generate_uv=getattr(settings, "object_generate_uv", False),
            uv_resolution=getattr(settings, "object_uv_resolution", 1024),
            uv_padding=getattr(settings, "object_uv_padding", 2),
            bake_texture=settings.object_bake_texture,
            texture_resolution=settings.object_texture_resolution,
            texture_padding=getattr(settings, "object_texture_padding", 4),
            ai_texture_enabled=getattr(settings, "object_ai_texture_enabled", False),
            ai_texture_backend=getattr(settings, "object_ai_texture_backend", "disabled"),
            fallback_to_original=getattr(settings, "enhancement_fallback_to_original", True),
            max_memory_mb=getattr(settings, "mesh_enhancement_max_memory_mb", 4096),
            device=getattr(settings, "texture_enhancement_device", "cpu"),
        ),
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
