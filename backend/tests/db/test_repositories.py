"""Repository behaviour against real PostgreSQL.

Traceability: DB-AC-03..12, DB-AC-15, DB-AC-20, DB-AC-21, DB-AC-23;
09_testing.md Section 8.2; TEST-AC-05.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import GenerationTask
from app.repositories import CleanupJobRepository

pytestmark = pytest.mark.integration

SHA256_SAMPLE = "0123456789abcdef" * 4


def _future(**offset: int) -> datetime:
    return datetime.now(UTC) + timedelta(**offset)


# --- users (Section 5) ----------------------------------------------------


def test_user_repository_create_and_lookup(user_repository) -> None:
    user = user_repository.create(email="repo-user@example.com", password_hash="hash")

    assert user.id is not None
    assert user.is_active is True
    assert user.created_at.tzinfo is not None
    assert user_repository.get(user.id).email == "repo-user@example.com"
    assert user_repository.get_by_email("repo-user@example.com").id == user.id
    assert user_repository.get_by_email("missing@example.com") is None


def test_base_repository_delete(user_repository) -> None:
    user = user_repository.create(email="delete-me@example.com", password_hash="hash")

    user_repository.delete(user)

    assert user_repository.get(user.id) is None


# --- sessions (Section 6) -------------------------------------------------


def test_session_repository_create_and_lookup(user_repository, session_repository) -> None:
    user = user_repository.create(email="session@example.com", password_hash="hash")
    token_hash = "a" * 64
    session = session_repository.create(
        user_id=user.id, token_hash=token_hash, expires_at=_future(days=1)
    )

    found = session_repository.get_by_token_hash(token_hash)

    assert found is not None
    assert found.id == session.id
    assert found.user_id == user.id
    assert [item.id for item in session_repository.list_for_user(user.id)] == [session.id]


def test_session_repository_marks_used_and_revoked(
    db_session, user_repository, session_repository
) -> None:
    user = user_repository.create(email="revoke@example.com", password_hash="hash")
    session = session_repository.create(
        user_id=user.id, token_hash="b" * 64, expires_at=_future(days=1)
    )
    moment = datetime.now(UTC)

    session_repository.mark_used(session, moment)
    session_repository.revoke(session, moment)
    db_session.expire_all()
    reloaded = session_repository.get(session.id)

    assert reloaded.last_used_at == moment
    assert reloaded.revoked_at == moment


def test_session_repository_deletes_expired_sessions(
    db_session, user_repository, session_repository
) -> None:
    user = user_repository.create(email="expired@example.com", password_hash="hash")
    now = datetime.now(UTC)
    session_repository.create(
        user_id=user.id, token_hash="c" * 64, expires_at=now + timedelta(minutes=1)
    )
    active = session_repository.create(
        user_id=user.id, token_hash="d" * 64, expires_at=now + timedelta(days=1)
    )

    deleted = session_repository.delete_expired(now + timedelta(hours=1))

    db_session.expire_all()
    assert deleted == 1
    assert session_repository.get_by_token_hash("c" * 64) is None
    assert session_repository.get(active.id).id == active.id


def test_session_repository_deletes_revoked_sessions(
    db_session, user_repository, session_repository
) -> None:
    user = user_repository.create(email="purge@example.com", password_hash="hash")
    session = session_repository.create(
        user_id=user.id, token_hash="e" * 64, expires_at=_future(days=1)
    )
    session_repository.revoke(session, datetime.now(UTC))

    deleted = session_repository.delete_revoked()

    db_session.expire_all()
    assert deleted == 1
    assert session_repository.get_by_token_hash("e" * 64) is None


# --- projects (Section 7) -------------------------------------------------


def test_project_repository_create_and_ownership(user_repository, project_repository) -> None:
    owner = user_repository.create(email="owner@example.com", password_hash="hash")
    stranger = user_repository.create(email="stranger@example.com", password_hash="hash")
    project = project_repository.create(user_id=owner.id, name="Chair", project_type="OBJECT")

    assert project.status == "CREATED"
    assert project_repository.get_active(project.id).id == project.id
    assert project_repository.get_active_for_user(project.id, owner.id).id == project.id
    assert project_repository.get_active_for_user(project.id, stranger.id) is None
    assert project_repository.get_active_for_update(project.id).id == project.id

    project_repository.set_status(project, "UPLOADING")

    assert project_repository.get_active(project.id).status == "UPLOADING"


def test_project_repository_soft_delete_hides_project(user_repository, project_repository) -> None:
    owner = user_repository.create(email="soft@example.com", password_hash="hash")
    project = project_repository.create(user_id=owner.id, name="Chair", project_type="OBJECT")

    project_repository.mark_deleted(project, datetime.now(UTC))

    assert project_repository.get_active(project.id) is None
    assert project_repository.list_for_user(owner.id, limit=10) == []
    assert project_repository.count_for_user(owner.id) == 0


def test_project_repository_filters_and_pagination(user_repository, project_repository) -> None:
    owner = user_repository.create(email="list@example.com", password_hash="hash")
    other = user_repository.create(email="other@example.com", password_hash="hash")
    created = [
        project_repository.create(
            user_id=owner.id, name=name, project_type=project_type, status=status
        )
        for name, project_type, status in (
            ("Object created", "OBJECT", "CREATED"),
            ("Scene created", "SCENE", "CREATED"),
            ("Object complete", "OBJECT", "COMPLETED"),
        )
    ]
    project_repository.create(user_id=other.id, name="Not mine", project_type="OBJECT")

    assert project_repository.count_for_user(owner.id) == 3
    assert project_repository.count_for_user(owner.id, project_type="OBJECT") == 2
    assert project_repository.count_for_user(owner.id, status="CREATED") == 2
    assert project_repository.count_for_user(owner.id, project_type="SCENE") == 1

    first_page = project_repository.list_for_user(owner.id, limit=2, offset=0)
    second_page = project_repository.list_for_user(owner.id, limit=2, offset=2)

    assert len(first_page) == 2
    assert len(second_page) == 1
    assert {project.id for project in first_page} | {project.id for project in second_page} == {
        project.id for project in created
    }
    assert all(project.user_id == owner.id for project in first_page)


# --- images (Section 8) ---------------------------------------------------


def test_image_repository_create_order_and_next_position(
    user_repository, project_repository, image_repository
) -> None:
    owner = user_repository.create(email="images@example.com", password_hash="hash")
    project = project_repository.create(user_id=owner.id, name="Scene", project_type="SCENE")

    def create_image(position: int):
        return image_repository.create(
            project_id=project.id,
            original_filename=f"photo-{position}.jpg",
            storage_key=f"projects/{project.id}/source/{uuid.uuid4().hex}.jpg",
            mime_type="image/jpeg",
            file_size_bytes=1024,
            sha256=SHA256_SAMPLE,
            width=640,
            height=480,
            position=position,
        )

    create_image(1)
    create_image(0)

    images = image_repository.list_for_project(project.id)

    assert [image.position for image in images] == [0, 1]
    assert image_repository.count_for_project(project.id) == 2
    assert image_repository.next_position(project.id) == 2


def test_image_repository_counts_by_project(
    user_repository, project_repository, image_repository
) -> None:
    owner = user_repository.create(email="counts@example.com", password_hash="hash")
    first = project_repository.create(user_id=owner.id, name="One", project_type="SCENE")
    second = project_repository.create(user_id=owner.id, name="Two", project_type="SCENE")

    for project, count in ((first, 2), (second, 1)):
        for position in range(count):
            image_repository.create(
                project_id=project.id,
                original_filename="photo.jpg",
                storage_key=f"projects/{project.id}/source/{uuid.uuid4().hex}.jpg",
                mime_type="image/jpeg",
                file_size_bytes=10,
                sha256=SHA256_SAMPLE,
                width=10,
                height=10,
                position=position,
            )

    assert image_repository.count_by_project_ids([first.id, second.id]) == {
        first.id: 2,
        second.id: 1,
    }
    assert image_repository.count_by_project_ids([]) == {}


def test_image_repository_get_for_project_is_project_scoped(
    user_repository, project_repository, image_repository
) -> None:
    owner = user_repository.create(email="scoped@example.com", password_hash="hash")
    first = project_repository.create(user_id=owner.id, name="One", project_type="OBJECT")
    second = project_repository.create(user_id=owner.id, name="Two", project_type="OBJECT")
    image = image_repository.create(
        project_id=first.id,
        original_filename="photo.jpg",
        storage_key=f"projects/{first.id}/source/{uuid.uuid4().hex}.jpg",
        mime_type="image/jpeg",
        file_size_bytes=10,
        sha256=SHA256_SAMPLE,
        width=10,
        height=10,
        position=0,
    )

    assert image_repository.get_for_project(image.id, first.id).id == image.id
    assert image_repository.get_for_project(image.id, second.id) is None
    assert image_repository.get_for_project(uuid.uuid4(), first.id) is None


# --- generation tasks (Sections 9 and 10) ---------------------------------


def test_task_repository_create_and_idempotency(
    user_repository, project_repository, task_repository
) -> None:
    owner = user_repository.create(email="tasks@example.com", password_hash="hash")
    first = project_repository.create(user_id=owner.id, name="One", project_type="OBJECT")
    second = project_repository.create(user_id=owner.id, name="Two", project_type="OBJECT")

    task = task_repository.create(
        project_id=first.id,
        task_type="OBJECT",
        idempotency_key="key-1",
        request_fingerprint="f" * 64,
        parameters={"algorithm": "TripoSR"},
    )

    assert task.status == "PENDING"
    assert task.attempt_count == 0
    assert task_repository.get_by_idempotency_key(first.id, "key-1").id == task.id
    assert task_repository.get_by_idempotency_key(second.id, "key-1") is None


def test_task_repository_active_task(user_repository, project_repository, task_repository) -> None:
    owner = user_repository.create(email="active@example.com", password_hash="hash")
    project = project_repository.create(user_id=owner.id, name="One", project_type="OBJECT")
    task = task_repository.create(
        project_id=project.id,
        task_type="OBJECT",
        idempotency_key="active-1",
        request_fingerprint="f" * 64,
        parameters={},
    )

    assert task_repository.get_active_for_project(project.id).id == task.id

    task_repository.set_status(task, "COMPLETED", finished_at=datetime.now(UTC))

    assert task_repository.get_active_for_project(project.id) is None
    replacement = task_repository.create(
        project_id=project.id,
        task_type="OBJECT",
        idempotency_key="active-2",
        request_fingerprint="e" * 64,
        parameters={},
    )
    assert task_repository.get_active_for_project(project.id).id == replacement.id

    task_repository.set_status(replacement, "PROCESSING")
    assert task_repository.get_active_for_project(project.id).id == replacement.id


def test_task_repository_history_and_pagination(
    user_repository, project_repository, task_repository
) -> None:
    owner = user_repository.create(email="history@example.com", password_hash="hash")
    project = project_repository.create(user_id=owner.id, name="One", project_type="OBJECT")

    for index, status in enumerate(("COMPLETED", "FAILED", "CANCELLED")):
        task_repository.create(
            project_id=project.id,
            task_type="OBJECT",
            idempotency_key=f"history-{index}",
            request_fingerprint=f"{index}" * 64,
            parameters={},
            status=status,
        )

    assert task_repository.count_for_project(project.id) == 3
    assert len(task_repository.list_for_project(project.id, limit=2)) == 2
    assert len(task_repository.list_for_project(project.id, limit=2, offset=2)) == 1


def test_task_repository_input_snapshot(
    user_repository, project_repository, image_repository, task_repository
) -> None:
    owner = user_repository.create(email="snapshot@example.com", password_hash="hash")
    project = project_repository.create(user_id=owner.id, name="Scene", project_type="SCENE")
    first_image = image_repository.create(
        project_id=project.id,
        original_filename="first.jpg",
        storage_key=f"projects/{project.id}/source/{uuid.uuid4().hex}.jpg",
        mime_type="image/jpeg",
        file_size_bytes=10,
        sha256=SHA256_SAMPLE,
        width=10,
        height=10,
        position=0,
    )
    second_image = image_repository.create(
        project_id=project.id,
        original_filename="second.jpg",
        storage_key=f"projects/{project.id}/source/{uuid.uuid4().hex}.jpg",
        mime_type="image/jpeg",
        file_size_bytes=10,
        sha256=SHA256_SAMPLE,
        width=10,
        height=10,
        position=1,
    )
    task = task_repository.create(
        project_id=project.id,
        task_type="SCENE",
        idempotency_key="snapshot-1",
        request_fingerprint="f" * 64,
        parameters={},
    )

    snapshot = task_repository.add_input_images(
        task_id=task.id,
        project_id=project.id,
        images=[second_image, first_image],
    )
    loaded = task_repository.list_input_images(task.id)

    assert [row.position for row in snapshot] == [0, 1]
    assert [row.image_id for row in loaded] == [second_image.id, first_image.id]
    assert loaded[0].image.id == second_image.id
    assert all(row.project_id == project.id for row in loaded)


def test_task_repository_image_is_referenced(
    user_repository, project_repository, image_repository, task_repository
) -> None:
    owner = user_repository.create(email="referenced@example.com", password_hash="hash")
    project = project_repository.create(user_id=owner.id, name="Scene", project_type="SCENE")

    def create_image(position: int):
        return image_repository.create(
            project_id=project.id,
            original_filename=f"photo-{position}.jpg",
            storage_key=f"projects/{project.id}/source/{uuid.uuid4().hex}.jpg",
            mime_type="image/jpeg",
            file_size_bytes=10,
            sha256=SHA256_SAMPLE,
            width=10,
            height=10,
            position=position,
        )

    snapshot_image = create_image(0)
    spare_image = create_image(1)
    task = task_repository.create(
        project_id=project.id,
        task_type="SCENE",
        idempotency_key="referenced-1",
        request_fingerprint="f" * 64,
        parameters={},
    )

    assert task_repository.is_image_referenced(snapshot_image.id) is False

    task_repository.add_input_images(
        task_id=task.id, project_id=project.id, images=[snapshot_image]
    )

    assert task_repository.is_image_referenced(snapshot_image.id) is True
    assert task_repository.is_image_referenced(spare_image.id) is False


def test_task_repository_latest_by_project(
    db_session, user_repository, project_repository, task_repository
) -> None:
    owner = user_repository.create(email="latest@example.com", password_hash="hash")
    project = project_repository.create(user_id=owner.id, name="One", project_type="OBJECT")
    other_project = project_repository.create(user_id=owner.id, name="Two", project_type="OBJECT")
    older = task_repository.create(
        project_id=project.id,
        task_type="OBJECT",
        idempotency_key="older",
        request_fingerprint="a" * 64,
        parameters={},
        status="COMPLETED",
    )
    newer = task_repository.create(
        project_id=project.id,
        task_type="OBJECT",
        idempotency_key="newer",
        request_fingerprint="b" * 64,
        parameters={},
        status="FAILED",
    )
    other = task_repository.create(
        project_id=other_project.id,
        task_type="OBJECT",
        idempotency_key="other",
        request_fingerprint="c" * 64,
        parameters={},
        status="FAILED",
    )
    db_session.execute(
        update(GenerationTask)
        .where(GenerationTask.id == older.id)
        .values(created_at=datetime(2026, 1, 1, tzinfo=UTC))
    )
    db_session.execute(
        update(GenerationTask)
        .where(GenerationTask.id == newer.id)
        .values(created_at=datetime(2026, 1, 2, tzinfo=UTC))
    )
    db_session.execute(
        update(GenerationTask)
        .where(GenerationTask.id == other.id)
        .values(created_at=datetime(2026, 1, 3, tzinfo=UTC))
    )

    latest = task_repository.latest_by_project_ids([project.id, other_project.id])

    assert latest[project.id].id == newer.id
    assert latest[other_project.id].id == other.id
    assert task_repository.latest_by_project_ids([]) == {}


# --- generation results (Section 11) --------------------------------------


def _completed_task(task_repository, project, key: str) -> GenerationTask:
    return task_repository.create(
        project_id=project.id,
        task_type="OBJECT",
        idempotency_key=key,
        request_fingerprint="f" * 64,
        parameters={},
        status="COMPLETED",
    )


def test_result_repository_current_result(
    user_repository, project_repository, task_repository, result_repository
) -> None:
    owner = user_repository.create(email="results@example.com", password_hash="hash")
    project = project_repository.create(user_id=owner.id, name="One", project_type="OBJECT")
    task = _completed_task(task_repository, project, "result-1")

    result = result_repository.create(
        project_id=project.id,
        task_id=task.id,
        format="GLB",
        mime_type="model/gltf-binary",
        storage_key=f"projects/{project.id}/results/{uuid.uuid4().hex}.glb",
        file_size_bytes=2048,
        sha256=SHA256_SAMPLE,
        metadata={"vertices_count": 100},
    )

    assert result.is_current is False
    assert result_repository.get_for_task(task.id).id == result.id
    assert result_repository.get_current_for_project(project.id) is None

    current = result_repository.create(
        project_id=project.id,
        task_id=_completed_task(task_repository, project, "result-2").id,
        format="GLB",
        mime_type="model/gltf-binary",
        storage_key=f"projects/{project.id}/results/{uuid.uuid4().hex}.glb",
        file_size_bytes=4096,
        sha256=SHA256_SAMPLE,
        is_current=True,
    )

    assert result_repository.get_current_for_project(project.id).id == current.id
    assert {item.id for item in result_repository.list_for_project(project.id)} == {
        result.id,
        current.id,
    }
    assert [
        item.id for item in result_repository.list_for_project(project.id, current_only=True)
    ] == [current.id]


def test_result_repository_replaces_current_result(
    user_repository, project_repository, task_repository, result_repository
) -> None:
    owner = user_repository.create(email="replace@example.com", password_hash="hash")
    project = project_repository.create(user_id=owner.id, name="One", project_type="OBJECT")
    previous = result_repository.create(
        project_id=project.id,
        task_id=_completed_task(task_repository, project, "replace-1").id,
        format="GLB",
        mime_type="model/gltf-binary",
        storage_key=f"projects/{project.id}/results/{uuid.uuid4().hex}.glb",
        file_size_bytes=100,
        sha256=SHA256_SAMPLE,
        is_current=True,
    )

    assert result_repository.clear_current(project.id) == 1
    assert result_repository.get_current_for_project(project.id) is None

    replacement = result_repository.create(
        project_id=project.id,
        task_id=_completed_task(task_repository, project, "replace-2").id,
        format="GLB",
        mime_type="model/gltf-binary",
        storage_key=f"projects/{project.id}/results/{uuid.uuid4().hex}.glb",
        file_size_bytes=200,
        sha256=SHA256_SAMPLE,
        is_current=True,
    )

    assert result_repository.get_current_for_project(project.id).id == replacement.id
    assert result_repository.get_for_task(previous.task_id).id == previous.id


def test_result_repository_current_by_project_ids(
    db_session, user_repository, project_repository, task_repository, result_repository
) -> None:
    owner = user_repository.create(email="bulk-results@example.com", password_hash="hash")
    projects = [
        project_repository.create(user_id=owner.id, name=f"P{index}", project_type="OBJECT")
        for index in range(2)
    ]
    for index, project in enumerate(projects):
        result_repository.create(
            project_id=project.id,
            task_id=_completed_task(task_repository, project, f"bulk-{index}").id,
            format="GLB",
            mime_type="model/gltf-binary",
            storage_key=f"projects/{project.id}/results/{uuid.uuid4().hex}.glb",
            file_size_bytes=10,
            sha256=SHA256_SAMPLE,
            is_current=True,
        )
    db_session.expire_all()

    current = result_repository.current_by_project_ids([project.id for project in projects])

    assert set(current) == {project.id for project in projects}
    assert all(result.is_current for result in current.values())
    assert result_repository.current_by_project_ids([]) == {}


# --- storage cleanup jobs (Section 12) ------------------------------------


def test_cleanup_job_repository_pending_and_history(
    user_repository, project_repository, cleanup_job_repository
) -> None:
    owner = user_repository.create(email="cleanup@example.com", password_hash="hash")
    project = project_repository.create(user_id=owner.id, name="One", project_type="OBJECT")
    pending = cleanup_job_repository.create(
        project_id=project.id,
        storage_key=f"projects/{project.id}/",
        target_type="DIRECTORY",
    )
    completed = cleanup_job_repository.create(
        project_id=project.id,
        storage_key=f"projects/{project.id}/old.glb",
        target_type="FILE",
        status="COMPLETED",
    )

    assert [job.id for job in cleanup_job_repository.list_pending(limit=10)] == [pending.id]
    assert {job.id for job in cleanup_job_repository.list_for_project(project.id)} == {
        pending.id,
        completed.id,
    }


def test_cleanup_job_repository_set_status(
    user_repository, project_repository, cleanup_job_repository
) -> None:
    owner = user_repository.create(email="cleanup-status@example.com", password_hash="hash")
    project = project_repository.create(user_id=owner.id, name="One", project_type="OBJECT")
    job = cleanup_job_repository.create(
        project_id=project.id,
        storage_key=f"projects/{project.id}/",
        target_type="DIRECTORY",
    )
    completed_at = datetime.now(UTC)

    cleanup_job_repository.set_status(
        job, "COMPLETED", completed_at=completed_at, last_error="previous failure"
    )

    assert job.status == "COMPLETED"
    assert job.completed_at == completed_at
    assert job.last_error == "previous failure"


def test_cleanup_job_repository_claims_skip_locked_jobs(
    db_session, user_repository, project_repository, cleanup_job_repository, migrated_engine
) -> None:
    """A locked job is invisible to a second worker instead of blocking it.

    This is the primitive the cleanup service relies on so two workers can
    claim different jobs concurrently (09_testing.md Section 8.5).
    """
    owner = user_repository.create(email="cleanup-claim@example.com", password_hash="hash")
    project = project_repository.create(user_id=owner.id, name="One", project_type="OBJECT")
    first = cleanup_job_repository.create(
        project_id=project.id,
        storage_key=f"projects/{project.id}/first.jpg",
        target_type="FILE",
    )
    second = cleanup_job_repository.create(
        project_id=project.id,
        storage_key=f"projects/{project.id}/second.jpg",
        target_type="FILE",
    )
    first.created_at = datetime.now(UTC) - timedelta(seconds=10)
    db_session.flush()
    db_session.commit()
    factory = sessionmaker(bind=migrated_engine, expire_on_commit=False, class_=Session)
    left = factory()
    right = factory()
    third = factory()
    try:
        claimed = CleanupJobRepository(left).get_pending_for_update()
        assert claimed is not None
        assert claimed.id == first.id

        other = CleanupJobRepository(right).get_pending_for_update()
        assert other is not None
        assert other.id == second.id

        # Both rows are locked by other transactions, so a third worker finds
        # nothing to claim instead of waiting.
        assert CleanupJobRepository(third).get_pending_for_update() is None
        # Excluding a job keeps it out of the next claim even when it is free.
        assert (
            CleanupJobRepository(left).get_pending_for_update(exclude_ids=[first.id, second.id])
            is None
        )
    finally:
        left.rollback()
        right.rollback()
        third.rollback()
        left.close()
        right.close()
        third.close()


# --- outbox messages (Section 13) -----------------------------------------


def test_outbox_repository_pending_and_aggregate(
    user_repository, project_repository, task_repository, outbox_repository
) -> None:
    owner = user_repository.create(email="outbox@example.com", password_hash="hash")
    project = project_repository.create(user_id=owner.id, name="One", project_type="OBJECT")
    task = task_repository.create(
        project_id=project.id,
        task_type="OBJECT",
        idempotency_key="outbox-1",
        request_fingerprint="f" * 64,
        parameters={},
    )
    now = datetime.now(UTC)
    due = outbox_repository.create(
        event_type="generation.requested",
        aggregate_type="GenerationTask",
        aggregate_id=task.id,
        payload={"task_id": str(task.id)},
        available_at=now - timedelta(minutes=1),
    )
    future = outbox_repository.create(
        event_type="generation.requested",
        aggregate_type="GenerationTask",
        aggregate_id=task.id,
        payload={"task_id": str(task.id)},
        available_at=now + timedelta(hours=1),
    )

    pending = outbox_repository.list_pending(now=now, limit=10)
    history = outbox_repository.list_by_aggregate("GenerationTask", task.id)

    assert [message.id for message in pending] == [due.id]
    assert {message.id for message in history} == {due.id, future.id}


def test_outbox_repository_defaults(
    user_repository, project_repository, task_repository, outbox_repository
) -> None:
    owner = user_repository.create(email="outbox-default@example.com", password_hash="hash")
    project = project_repository.create(user_id=owner.id, name="One", project_type="OBJECT")
    task = task_repository.create(
        project_id=project.id,
        task_type="OBJECT",
        idempotency_key="outbox-default-1",
        request_fingerprint="f" * 64,
        parameters={},
    )

    message = outbox_repository.create(
        event_type="generation.requested",
        aggregate_type="GenerationTask",
        aggregate_id=task.id,
        payload={},
    )

    assert message.status == "PENDING"
    assert message.schema_version == 1
    assert message.available_at is not None
    assert message.created_at is not None
