"""Scene reconstruction through the existing worker/result path.

These tests do not run COLMAP or OpenMVS: they prove that a SCENE task uses the
same Phase 4 claim/lease/result machinery as an object task, that the scene
result is stored as ``scene.glb`` and that a failed reconstruction preserves the
previous result (SCENE-AC-18/19/20, DB-AC-11, API-AC-13).
"""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db.models import GenerationResult, GenerationTask, Project
from app.db.models.enums import TaskType
from app.services.result_service import result_storage_key
from app.storage import LocalStorage
from app.tasks.generation_tasks import (
    GenerationFailure,
    PipelineArtifact,
    run_generation,
)

pytestmark = [pytest.mark.integration]


@pytest.fixture
def scene_settings(tmp_path: Path) -> Settings:
    return Settings(
        app_env="test",
        log_level="WARNING",
        storage_root=str(tmp_path / "storage"),
        task_lease_seconds=300,
        task_heartbeat_seconds=30,
        task_stale_threshold_seconds=900,
    )


def _artifact(task: GenerationTask, tmp_path: Path) -> PipelineArtifact:
    glb = tmp_path / "scene.glb"
    glb.write_bytes(b"glTF" + b"\x02\x00\x00\x00" + b"scene-bytes")
    data = glb.read_bytes()
    return PipelineArtifact(
        path=glb,
        sha256=hashlib.sha256(data).hexdigest(),
        file_size_bytes=len(data),
        format="GLB",
        mime_type="model/gltf-binary",
        metadata={
            "vertices_count": 1200,
            "faces_count": 800,
            "textures_count": 1,
            "bounding_box": {"width": 1.2, "height": 0.9, "depth": 1.1},
        },
        storage_key=result_storage_key(task.project_id, task.id, filename="scene.glb"),
    )


def test_a_scene_task_registers_a_scene_glb_result(
    db_session: Session,
    session_factory: sessionmaker[Session],
    make_user,
    make_project,
    make_task,
    scene_settings: Settings,
    tmp_path: Path,
) -> None:
    project = make_project(make_user(), type="SCENE", status="CREATED")
    task = make_task(project, task_type=TaskType.SCENE.value)
    db_session.commit()

    outcome = run_generation(
        settings=scene_settings,
        session_factory=session_factory,
        storage=LocalStorage(scene_settings.storage_root),
        task_id=task.id,
        task_type=TaskType.SCENE,
        worker_id="scene-worker-a",
        pipeline=lambda context: _artifact(context.task, tmp_path),
    )

    assert outcome.status == "completed"
    db_session.expire_all()
    reloaded = db_session.get(GenerationTask, task.id)
    assert reloaded is not None and reloaded.status == "COMPLETED"
    assert db_session.get(Project, project.id).status == "COMPLETED"
    result = db_session.scalar(select(GenerationResult).where(GenerationResult.task_id == task.id))
    assert result is not None
    assert result.is_current is True
    assert result.storage_key.endswith(f"/{task.id}/scene.glb")
    assert result.result_metadata["vertices_count"] == 1200
    assert LocalStorage(scene_settings.storage_root).exists(result.storage_key)


def test_a_failed_scene_attempt_preserves_the_previous_result(
    db_session: Session,
    session_factory: sessionmaker[Session],
    make_user,
    make_project,
    make_task,
    scene_settings: Settings,
    tmp_path: Path,
) -> None:
    project = make_project(make_user(), type="SCENE", status="CREATED")
    first = make_task(project, task_type=TaskType.SCENE.value)
    db_session.commit()
    run_generation(
        settings=scene_settings,
        session_factory=session_factory,
        storage=LocalStorage(scene_settings.storage_root),
        task_id=first.id,
        task_type=TaskType.SCENE,
        worker_id="scene-worker-a",
        pipeline=lambda context: _artifact(context.task, tmp_path),
    )
    db_session.expire_all()
    original = db_session.scalar(
        select(GenerationResult).where(GenerationResult.task_id == first.id)
    )
    assert original is not None
    original_id = original.id

    second = make_task(project, task_type=TaskType.SCENE.value)
    db_session.commit()

    def _failing(_context) -> None:
        raise GenerationFailure("TEXTURE_GENERATION_FAILED", "texturing failed")

    outcome = run_generation(
        settings=scene_settings,
        session_factory=session_factory,
        storage=LocalStorage(scene_settings.storage_root),
        task_id=second.id,
        task_type=TaskType.SCENE,
        worker_id="scene-worker-b",
        pipeline=_failing,
    )

    assert outcome.status == "failed"
    assert outcome.error_code == "TEXTURE_GENERATION_FAILED"
    db_session.expire_all()
    failed = db_session.get(GenerationTask, second.id)
    assert failed is not None and failed.status == "FAILED"
    current = db_session.scalar(
        select(GenerationResult).where(
            GenerationResult.project_id == project.id,
            GenerationResult.is_current.is_(True),
        )
    )
    assert current is not None
    assert current.id == original_id
    assert db_session.get(Project, project.id).status == "FAILED"


def test_two_scene_attempts_get_distinct_storage_keys(
    db_session: Session,
    session_factory: sessionmaker[Session],
    make_user,
    make_project,
    make_task,
    scene_settings: Settings,
    tmp_path: Path,
) -> None:
    project = make_project(make_user(), type="SCENE", status="CREATED")
    first = make_task(project, task_type=TaskType.SCENE.value)
    db_session.commit()
    run_generation(
        settings=scene_settings,
        session_factory=session_factory,
        storage=LocalStorage(scene_settings.storage_root),
        task_id=first.id,
        task_type=TaskType.SCENE,
        worker_id="scene-worker-a",
        pipeline=lambda context: _artifact(context.task, tmp_path),
    )
    second = make_task(project, task_type=TaskType.SCENE.value)
    db_session.commit()
    run_generation(
        settings=scene_settings,
        session_factory=session_factory,
        storage=LocalStorage(scene_settings.storage_root),
        task_id=second.id,
        task_type=TaskType.SCENE,
        worker_id="scene-worker-a",
        pipeline=lambda context: _artifact(context.task, tmp_path),
    )

    db_session.expire_all()
    results = db_session.scalars(
        select(GenerationResult).where(GenerationResult.project_id == project.id)
    ).all()
    assert len(results) == 2
    assert len({result.storage_key for result in results}) == 2
    current = [result for result in results if result.is_current]
    assert len(current) == 1
    assert current[0].task_id == second.id
    assert uuid.UUID(str(second.id)) == current[0].task_id
