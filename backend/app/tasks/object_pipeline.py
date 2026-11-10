"""Object-generation pipeline adapter for the Phase 4 worker.

This module is imported only by the Object Worker (Celery ``--include``). It
connects the TripoSR package to the existing worker lifecycle:

* the worker has already claimed the task and moved the project to
  ``PROCESSING`` before the pipeline runs;
* :class:`TaskContext` supplies heartbeat, stage reporting and cancellation;
* the pipeline returns a validated :class:`PipelineArtifact`, and
  ``run_generation`` stores it and registers the result transactionally.

The heavy ML dependencies (torch, TripoSR) live only in the object-worker
image; importing this module therefore fails in the FastAPI image by design.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from app.core.config import get_settings
from app.db.models.enums import TaskType
from app.repositories import TaskRepository
from app.services.result_service import result_storage_key
from app.tasks.generation_tasks import (
    GenerationCancelled,
    GenerationFailure,
    PipelineArtifact,
    TaskContext,
    register_pipeline,
)

logger = logging.getLogger(__name__)

SOURCE_IMAGE_NOT_FOUND = "SOURCE_IMAGE_NOT_FOUND"


def _source_image_bytes(context: TaskContext) -> bytes:
    """Read the task's immutable source image through the storage backend."""
    images = TaskRepository(context.session).list_input_images(context.task.id)
    if not images:
        raise GenerationFailure(SOURCE_IMAGE_NOT_FOUND, "The generation task has no source image.")
    image = images[0].image
    if image is None or not image.storage_key:
        raise GenerationFailure(SOURCE_IMAGE_NOT_FOUND, "The source image metadata is unavailable.")
    try:
        with context.storage.open(image.storage_key) as stream:
            data = stream.read()
    except FileNotFoundError as exc:
        raise GenerationFailure(
            SOURCE_IMAGE_NOT_FOUND, "The source photograph is no longer available."
        ) from exc
    if not data:
        raise GenerationFailure(SOURCE_IMAGE_NOT_FOUND, "The source photograph is empty.")
    return data


def run_triposr_pipeline(context: TaskContext) -> PipelineArtifact:
    """Execute the real TripoSR pipeline for one claimed task."""
    from object_generation.exceptions import ObjectGenerationError
    from object_generation.pipeline import (
        PipelineCallbacks,
        build_config_from_settings,
        run_object_generation,
    )

    config = build_config_from_settings(context.settings)
    image_bytes = _source_image_bytes(context)

    work_root = Path(context.settings.object_work_dir)
    work_dir = work_root / str(context.task.id)
    shutil.rmtree(work_dir, ignore_errors=True)
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

    try:
        asset = run_object_generation(
            image_bytes=image_bytes,
            config=config,
            work_dir=work_dir,
            callbacks=callbacks,
            max_image_dimension=context.settings.max_image_dimension,
        )
    except ObjectGenerationError as exc:
        logger.error(
            "object_generation_failed",
            extra={
                "operation": "object_generation",
                "task_id": str(context.task.id),
                "project_id": str(context.task.project_id),
                "error_code": exc.error_code,
            },
        )
        shutil.rmtree(work_dir, ignore_errors=True)
        raise GenerationFailure(exc.error_code, str(exc)) from exc
    except Exception:
        logger.exception(
            "object_generation_crashed",
            extra={
                "operation": "object_generation",
                "task_id": str(context.task.id),
                "project_id": str(context.task.project_id),
            },
        )
        shutil.rmtree(work_dir, ignore_errors=True)
        raise

    return PipelineArtifact(
        path=asset.path,
        sha256=asset.sha256,
        file_size_bytes=asset.file_size_bytes,
        format=asset.format,
        mime_type=asset.mime_type,
        metadata=asset.metadata,
        storage_key=result_storage_key(context.task.project_id, context.task.id),
        cleanup_dir=work_dir,
    )


def _bootstrap() -> None:
    """Initialize the model and register the pipeline in the worker process."""
    settings = get_settings()
    if not settings.object_generation_enabled:
        logger.warning(
            "object_generation_disabled",
            extra={"operation": "object_generation", "worker_service_name": "object-worker"},
        )
        return

    from object_generation.model_loader import warm_up
    from object_generation.pipeline import build_config_from_settings

    config = build_config_from_settings(settings)
    # OBJ-AC-01/02/03: verify the cache and initialize the configured device
    # before the worker accepts a task. A failure here stops the worker instead
    # of failing every task later.
    model = warm_up(config)
    logger.info(
        "object_generation_pipeline_ready",
        extra={
            "operation": "object_generation",
            "device": model.device.device,
            "device_name": model.device.name,
            "model_revision": settings.object_model_revision,
        },
    )
    register_pipeline(TaskType.OBJECT, run_triposr_pipeline)


_bootstrap()


__all__ = ["run_triposr_pipeline", "SOURCE_IMAGE_NOT_FOUND"]
