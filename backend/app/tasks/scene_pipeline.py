"""Scene-reconstruction pipeline adapter for the Phase 4 worker.

This module is imported only by the Scene Worker (Celery ``--include``). It
connects :mod:`scene_reconstruction` to the existing worker lifecycle:

* the worker has already claimed the task and moved the project to
  ``PROCESSING`` before the pipeline runs;
* :class:`TaskContext` supplies heartbeat, stage reporting and cancellation;
* the pipeline returns a validated :class:`PipelineArtifact`, and
  ``run_generation`` stores it and registers the result transactionally.

COLMAP and OpenMVS live only in the scene-worker image, so importing this
module fails in the FastAPI image by design (08 Section 3.6).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import BinaryIO

from app.core.config import get_settings
from app.db.models.enums import TaskType
from app.repositories import TaskRepository
from app.services.result_service import result_storage_key
from app.services.scene_methods import (
    GAUSSIAN_SPLAT,
    MESH,
    SceneRepresentation,
    persisted_representation,
    task_matches_capability,
)
from app.tasks.generation_tasks import (
    GenerationCancelled,
    GenerationFailure,
    PipelineArtifact,
    TaskContext,
    register_pipeline,
)

logger = logging.getLogger(__name__)

SOURCE_IMAGE_NOT_FOUND = "SOURCE_IMAGE_NOT_FOUND"
EXTERNAL_TOOL_UNAVAILABLE = "EXTERNAL_TOOL_UNAVAILABLE"
SPLAT_RUNTIME_UNAVAILABLE = "SPLAT_RUNTIME_UNAVAILABLE"
SCENE_WORKER_INCOMPATIBLE = "SCENE_WORKER_INCOMPATIBLE"
SCENE_RESULT_FILENAME = "scene.glb"
SPLAT_RESULT_FILENAME = "scene.ply"


def _task_representation(context: TaskContext) -> SceneRepresentation:
    return persisted_representation(context.task.parameters)


def _source_images(context: TaskContext) -> list:
    """Return the task's immutable image snapshot as pipeline inputs."""
    from scene_reconstruction.dataset import SourceImage

    entries = TaskRepository(context.session).list_input_images(context.task.id)
    if not entries:
        raise GenerationFailure(SOURCE_IMAGE_NOT_FOUND, "The generation task has no source images.")
    sources: list[SourceImage] = []
    for entry in entries:
        image = entry.image
        if image is None or not image.storage_key:
            raise GenerationFailure(
                SOURCE_IMAGE_NOT_FOUND, "A source image metadata record is unavailable."
            )
        if not context.storage.exists(image.storage_key):
            raise GenerationFailure(
                SOURCE_IMAGE_NOT_FOUND, "A source photograph is no longer available."
            )

        def _open(key: str = image.storage_key) -> BinaryIO:
            return context.storage.open(key)

        sources.append(
            SourceImage(
                filename=image.original_filename,
                storage_key=image.storage_key,
                image_id=str(image.id),
                opener=_open,
            )
        )
    return sources


def _run_scene_pipeline(
    context: TaskContext, *, capability: SceneRepresentation
) -> PipelineArtifact:
    """Execute the representation this worker owns, rejecting the other one.

    The representation is read from the persisted task, never from the current
    environment: a task queued as ``GAUSSIAN_SPLAT`` must never be executed by a
    mesh worker (and vice versa), even if the deployment settings changed after
    the task was created (15 Sections 4.2 and 7).
    """
    from scene_reconstruction.config import build_config_from_settings
    from scene_reconstruction.exceptions import (
        SceneCancelled,
        SceneReconstructionError,
    )
    from scene_reconstruction.pipeline import (
        PhotogrammetryReconstructor,
        PipelineCallbacks,
    )

    stored = _task_representation(context)
    if not task_matches_capability(context.task.parameters, capability.value):
        raise GenerationFailure(
            SCENE_WORKER_INCOMPATIBLE,
            "This worker cannot execute the representation persisted for the task.",
        )

    config = build_config_from_settings(context.settings, representation=stored.value)
    sources = _source_images(context)
    work_dir = Path(context.settings.scene_work_dir) / str(context.task.id)
    work_dir.mkdir(parents=True, exist_ok=True)

    def report_stage(stage: str, message: str) -> None:
        if not context.report_progress(stage=stage, status_message=message):
            raise GenerationCancelled("The worker lease is no longer valid.")

    def heartbeat() -> None:
        if not context.heartbeat():
            raise GenerationCancelled("The worker lease is no longer valid.")

    def raise_if_cancelled() -> None:
        context.raise_if_cancelled()

    callbacks = PipelineCallbacks(
        report_stage=report_stage,
        heartbeat=heartbeat,
        raise_if_cancelled=raise_if_cancelled,
    )
    reconstructor = PhotogrammetryReconstructor(config, callbacks=callbacks)

    try:
        asset = reconstructor.reconstruct(
            sources,
            work_dir=work_dir,
            min_images=context.settings.min_scene_images,
            max_images=context.settings.max_scene_images,
            max_image_dimension=context.settings.max_image_dimension,
        )
    except SceneCancelled as exc:
        raise GenerationCancelled("cancellation requested") from exc
    except SceneReconstructionError as exc:
        logger.error(
            "scene_reconstruction_failed",
            extra={
                "operation": "scene_reconstruction",
                "task_id": str(context.task.id),
                "project_id": str(context.task.project_id),
                "error_code": exc.error_code,
            },
        )
        raise GenerationFailure(exc.error_code, str(exc)) from exc
    except Exception:
        logger.exception(
            "scene_reconstruction_crashed",
            extra={
                "operation": "scene_reconstruction",
                "task_id": str(context.task.id),
                "project_id": str(context.task.project_id),
            },
        )
        raise

    filename = SPLAT_RESULT_FILENAME if asset.format == "PLY" else SCENE_RESULT_FILENAME
    return PipelineArtifact(
        path=asset.path,
        sha256=asset.sha256,
        file_size_bytes=asset.file_size_bytes,
        format=asset.format,
        mime_type=asset.mime_type,
        metadata=asset.metadata,
        storage_key=result_storage_key(context.task.project_id, context.task.id, filename=filename),
        cleanup_dir=work_dir,
    )


def run_colmap_pipeline(context: TaskContext) -> PipelineArtifact:
    """Execute the default COLMAP/OpenMVS mesh pipeline for one claimed task."""
    return _run_scene_pipeline(context, capability=SceneRepresentation.MESH)


def run_splat_pipeline(context: TaskContext) -> PipelineArtifact:
    """Execute the opt-in Splatfacto pipeline for one claimed task."""
    return _run_scene_pipeline(context, capability=SceneRepresentation.GAUSSIAN_SPLAT)


def _unavailable_pipeline(context: TaskContext) -> PipelineArtifact:
    """Fail honestly when the image is missing a required external tool."""
    raise GenerationFailure(
        EXTERNAL_TOOL_UNAVAILABLE, "The reconstruction tools are not available in this worker."
    )


def _unavailable_splat_pipeline(context: TaskContext) -> PipelineArtifact:
    """Fail honestly when the neural runtime is missing or broken."""
    raise GenerationFailure(
        SPLAT_RUNTIME_UNAVAILABLE, "The neural scene runtime is not available in this worker."
    )


def _bootstrap() -> None:
    """Verify this worker's capability and register its pipeline."""
    settings = get_settings()
    if not settings.scene_reconstruction_enabled:
        logger.warning(
            "scene_reconstruction_disabled",
            extra={"operation": "scene_reconstruction", "worker_service_name": "scene-worker"},
        )
        return

    if settings.scene_splat_worker:
        _bootstrap_splat(settings)
        return

    try:
        from scene_reconstruction.config import build_config_from_settings
        from scene_reconstruction.preflight import verify_toolchain

        report = verify_toolchain(build_config_from_settings(settings))
    except Exception:
        # SCENE-AC-01: the worker must detect the configured binaries. A broken
        # image must not pretend to reconstruct; every task fails with the
        # documented EXTERNAL_TOOL_UNAVAILABLE code instead of WORKER_UNAVAILABLE.
        logger.exception(
            "scene_pipeline_unavailable",
            extra={"operation": "scene_reconstruction", "worker_service_name": "scene-worker"},
        )
        register_pipeline(TaskType.SCENE, _unavailable_pipeline)
        return

    logger.info(
        "scene_pipeline_ready",
        extra={
            "operation": "scene_reconstruction",
            "representation": MESH,
            "tool_versions": report.as_dict(),
        },
    )
    register_pipeline(TaskType.SCENE, run_colmap_pipeline)


def _bootstrap_splat(settings) -> None:
    """Verify COLMAP plus the pinned neural runtime before accepting tasks."""
    try:
        from scene_reconstruction.config import build_config_from_settings
        from scene_reconstruction.neural_pipeline import NeuralReconstructor
        from scene_reconstruction.preflight import verify_toolchain

        config = build_config_from_settings(settings, representation=GAUSSIAN_SPLAT)
        report = verify_toolchain(config, include_openmvs=False)
        runtime = NeuralReconstructor(config).runtime_report()
    except Exception:
        logger.exception(
            "splat_pipeline_unavailable",
            extra={"operation": "scene_reconstruction", "worker_service_name": "splat-worker"},
        )
        register_pipeline(TaskType.SCENE, _unavailable_splat_pipeline)
        return

    logger.info(
        "splat_pipeline_ready",
        extra={
            "operation": "scene_reconstruction",
            "representation": GAUSSIAN_SPLAT,
            "tool_versions": report.as_dict(),
            "runtime": runtime.as_metadata(),
        },
    )
    register_pipeline(TaskType.SCENE, run_splat_pipeline)


_bootstrap()


__all__ = [
    "SCENE_RESULT_FILENAME",
    "SPLAT_RESULT_FILENAME",
    "run_colmap_pipeline",
    "run_splat_pipeline",
]
