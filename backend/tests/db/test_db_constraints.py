"""Constraint, referential-integrity and ownership tests.

Each test asserts a specific database rule from 05_database_specification.md.
Traceability: DB-AC-09, DB-AC-11, DB-AC-12, DB-AC-13, DB-AC-15, DB-AC-21,
DB-AC-22, DB-AC-23; 09_testing.md Sections 8.3 and 8.5; TEST-AC-05,
TEST-AC-07.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import (
    GenerationResult,
    GenerationTask,
    GenerationTaskImage,
    OutboxMessage,
    Project,
    ProjectImage,
    StorageCleanupJob,
    User,
    UserSession,
)

pytestmark = pytest.mark.integration


@contextmanager
def raises_integrity_error(db_session: Session) -> Iterator[None]:
    """Assert a statement violates a database constraint without poisoning the session."""
    with pytest.raises(IntegrityError), db_session.begin_nested():
        yield


def count(db_session: Session, model: type) -> int:
    return db_session.scalar(select(func.count()).select_from(model)) or 0


# --- users and user_sessions (Sections 5 and 6) ---------------------------


def test_duplicate_email_is_rejected(db_session, make_user) -> None:
    make_user(email="duplicate@example.com")
    with raises_integrity_error(db_session):
        make_user(email="duplicate@example.com")


def test_duplicate_session_token_hash_is_rejected(db_session, make_user, make_session) -> None:
    user = make_user()
    make_session(user, token_hash="a" * 64)
    with raises_integrity_error(db_session):
        make_session(user, token_hash="a" * 64)


def test_session_expiry_must_be_later_than_creation(db_session, make_user, make_session) -> None:
    user = make_user()
    with raises_integrity_error(db_session):
        make_session(user, expires_at=datetime.now(UTC) - timedelta(hours=1))


def test_session_requires_an_existing_user(db_session) -> None:
    with raises_integrity_error(db_session):
        db_session.add(
            UserSession(
                user_id=uuid.uuid4(),
                token_hash="b" * 64,
                expires_at=datetime.now(UTC) + timedelta(days=1),
            )
        )
        db_session.flush()


# --- projects (Section 7) -------------------------------------------------


def test_project_type_must_be_supported(db_session, make_user) -> None:
    user = make_user()
    with raises_integrity_error(db_session):
        make_project_with(db_session, user, type="VIDEO")


def test_project_status_must_be_supported(db_session, make_user) -> None:
    user = make_user()
    with raises_integrity_error(db_session):
        make_project_with(db_session, user, status="ARCHIVED")


def test_project_name_must_not_be_blank(db_session, make_user) -> None:
    user = make_user()
    with raises_integrity_error(db_session):
        make_project_with(db_session, user, name="   ")


def test_project_requires_an_existing_owner(db_session) -> None:
    with raises_integrity_error(db_session):
        db_session.add(
            Project(
                user_id=uuid.uuid4(),
                name="Orphan",
                type="OBJECT",
                status="CREATED",
            )
        )
        db_session.flush()


# --- project_images (Section 8) -------------------------------------------


def test_image_requires_an_existing_project(db_session) -> None:
    with raises_integrity_error(db_session):
        db_session.add(
            ProjectImage(
                project_id=uuid.uuid4(),
                original_filename="photo.jpg",
                storage_key="projects/orphan/source/image.jpg",
                mime_type="image/jpeg",
                file_size_bytes=10,
                sha256="c" * 64,
                width=10,
                height=10,
                position=0,
            )
        )
        db_session.flush()


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("file_size_bytes", 0),
        ("file_size_bytes", -1),
        ("width", 0),
        ("height", 0),
        ("position", -1),
    ],
)
def test_image_rejects_out_of_range_values(
    db_session, make_user, make_project, make_image, column, value
) -> None:
    user = make_user()
    project = make_project(user)
    with raises_integrity_error(db_session):
        make_image(project, **{column: value})


def test_image_mime_type_must_be_jpeg_or_png(
    db_session, make_user, make_project, make_image
) -> None:
    user = make_user()
    project = make_project(user)
    with raises_integrity_error(db_session):
        make_image(project, mime_type="image/gif")


def test_image_sha256_must_be_a_hex_digest(db_session, make_user, make_project, make_image) -> None:
    user = make_user()
    project = make_project(user)
    with raises_integrity_error(db_session):
        make_image(project, sha256="not-a-checksum")


def test_image_storage_key_must_be_unique(db_session, make_user, make_project, make_image) -> None:
    user = make_user()
    project = make_project(user)
    image = make_image(project)
    with raises_integrity_error(db_session):
        make_image(project, storage_key=image.storage_key)


# --- generation_tasks (Section 9) -----------------------------------------


def test_task_type_must_be_supported(db_session, make_user, make_project) -> None:
    user = make_user()
    project = make_project(user)
    with raises_integrity_error(db_session):
        make_task_with(db_session, project, task_type="VIDEO")


def test_task_status_must_be_supported(db_session, make_user, make_project) -> None:
    user = make_user()
    project = make_project(user)
    with raises_integrity_error(db_session):
        make_task_with(db_session, project, status="QUEUED")


@pytest.mark.parametrize("progress", [-1, 101])
def test_task_progress_must_be_between_0_and_100(
    db_session, make_user, make_project, progress
) -> None:
    user = make_user()
    project = make_project(user)
    with raises_integrity_error(db_session):
        make_task_with(db_session, project, progress_percent=progress)


def test_idempotency_key_is_unique_within_a_project(
    db_session, make_user, make_project, make_task
) -> None:
    owner = make_user()
    project = make_project(owner)
    make_task(project, idempotency_key="same-key")
    with raises_integrity_error(db_session):
        make_task(project, idempotency_key="same-key")


def test_idempotency_key_is_scoped_to_its_project(
    db_session, make_user, make_project, make_task
) -> None:
    owner = make_user()
    first = make_project(owner)
    second = make_project(owner)
    make_task(first, idempotency_key="shared-key")
    make_task(second, idempotency_key="shared-key")

    assert count(db_session, GenerationTask) == 2


def test_only_one_active_task_per_project(db_session, make_user, make_project, make_task) -> None:
    owner = make_user()
    project = make_project(owner)
    first = make_task(project, status="PENDING")
    with raises_integrity_error(db_session):
        make_task(project, status="PENDING")
    with raises_integrity_error(db_session):
        make_task(project, status="PROCESSING")

    db_session.execute(
        update(GenerationTask).where(GenerationTask.id == first.id).values(status="COMPLETED")
    )
    db_session.flush()
    make_task(project, status="PENDING")
    assert count(db_session, GenerationTask) == 2


def test_terminal_tasks_do_not_block_a_new_active_task(
    db_session, make_user, make_project, make_task
) -> None:
    owner = make_user()
    project = make_project(owner)
    make_task(project, status="FAILED")
    make_task(project, status="CANCELLED")
    make_task(project, status="COMPLETED")
    make_task(project, status="PENDING")

    assert count(db_session, GenerationTask) == 4


def test_celery_task_id_must_be_unique(db_session, make_user, make_project, make_task) -> None:
    owner = make_user()
    project = make_project(owner)
    make_task(project, celery_task_id="celery-1")
    with raises_integrity_error(db_session):
        make_task(project, celery_task_id="celery-1")


def test_task_requires_an_existing_project(db_session) -> None:
    with raises_integrity_error(db_session):
        db_session.add(
            GenerationTask(
                project_id=uuid.uuid4(),
                task_type="OBJECT",
                status="PENDING",
                idempotency_key="key",
                request_fingerprint="d" * 64,
                parameters={},
            )
        )
        db_session.flush()


def test_worker_lease_metadata_round_trips(db_session, make_user, make_project, make_task) -> None:
    """DB-AC-23: identity, heartbeat, lease and cancellation metadata persist."""
    owner = make_user()
    project = make_project(owner)
    task = make_task(project, status="PROCESSING")
    heartbeat = datetime.now(UTC)
    lease = heartbeat + timedelta(minutes=5)
    cancel = heartbeat + timedelta(seconds=30)

    db_session.execute(
        update(GenerationTask)
        .where(GenerationTask.id == task.id)
        .values(
            worker_id="worker-7",
            started_at=heartbeat,
            heartbeat_at=heartbeat,
            lease_expires_at=lease,
            attempt_count=2,
            cancel_requested_at=cancel,
        )
    )
    db_session.expire_all()
    reloaded = db_session.get(GenerationTask, task.id)

    assert reloaded is not None
    assert reloaded.worker_id == "worker-7"
    assert reloaded.heartbeat_at == heartbeat
    assert reloaded.lease_expires_at == lease
    assert reloaded.attempt_count == 2
    assert reloaded.cancel_requested_at == cancel


# --- generation_task_images (Section 10) ----------------------------------


def test_task_image_cannot_mix_projects(
    db_session, make_user, make_project, make_image, make_task, make_task_image
) -> None:
    """DB-AC-22: the composite foreign keys reject cross-project references."""
    owner = make_user()
    project_with_task = make_project(owner, name="With task")
    project_with_image = make_project(owner, name="With image")
    task = make_task(project_with_task)
    image = make_image(project_with_image)

    with raises_integrity_error(db_session):
        make_task_image(task, image)


def test_task_image_cannot_reference_the_same_image_twice(
    db_session, make_user, make_project, make_image, make_task, make_task_image
) -> None:
    owner = make_user()
    project = make_project(owner)
    task = make_task(project)
    image = make_image(project)
    make_task_image(task, image, position=0)
    with raises_integrity_error(db_session):
        make_task_image(task, image, position=1)


def test_task_image_position_must_be_non_negative(
    db_session, make_user, make_project, make_image, make_task, make_task_image
) -> None:
    owner = make_user()
    project = make_project(owner)
    task = make_task(project)
    image = make_image(project)
    with raises_integrity_error(db_session):
        make_task_image(task, image, position=-1)


# --- generation_results (Section 11) --------------------------------------


def test_result_task_must_belong_to_the_same_project(
    db_session, make_user, make_project, make_task, make_result
) -> None:
    """DB-AC-22: a result cannot point at another project's task."""
    owner = make_user()
    project_with_task = make_project(owner, name="With task")
    other_project = make_project(owner, name="Other")
    task = make_task(project_with_task)

    with raises_integrity_error(db_session):
        make_result(other_project, task)


def test_a_task_can_have_at_most_one_result(
    db_session, make_user, make_project, make_task, make_result
) -> None:
    owner = make_user()
    project = make_project(owner)
    task = make_task(project)
    make_result(project, task)
    with raises_integrity_error(db_session):
        make_result(project, task)


def test_only_one_current_result_per_project(
    db_session, make_user, make_project, make_task, make_result
) -> None:
    """DB-AC-11: the partial unique index allows exactly one current result."""
    owner = make_user()
    project = make_project(owner)
    first = make_result(project, make_task(project, status="COMPLETED"), is_current=True)
    with raises_integrity_error(db_session):
        make_result(project, make_task(project, status="COMPLETED"), is_current=True)

    db_session.expire_all()
    assert db_session.get(GenerationResult, first.id).is_current is True


def test_historical_results_may_accumulate(
    db_session, make_user, make_project, make_task, make_result
) -> None:
    owner = make_user()
    project = make_project(owner)
    old = make_result(project, make_task(project, status="COMPLETED"), is_current=False)
    new = make_result(project, make_task(project, status="COMPLETED"), is_current=False)

    db_session.execute(
        update(GenerationResult).where(GenerationResult.id == new.id).values(is_current=True)
    )
    db_session.flush()

    db_session.expire_all()
    assert db_session.get(GenerationResult, old.id).is_current is False
    assert db_session.get(GenerationResult, new.id).is_current is True


def test_failed_regeneration_preserves_the_current_result(
    db_session, make_user, make_project, make_task, make_result
) -> None:
    """DB-AC-12: an unsuccessful attempt leaves the previous current result intact."""
    owner = make_user()
    project = make_project(owner)
    previous = make_result(project, make_task(project, status="COMPLETED"), is_current=True)
    failed_task = make_task(project, status="FAILED")

    db_session.expire_all()

    assert db_session.get(GenerationResult, previous.id).is_current is True
    assert db_session.get(GenerationTask, failed_task.id).status == "FAILED"
    new_results = db_session.scalar(
        select(func.count())
        .select_from(GenerationResult)
        .where(GenerationResult.task_id == failed_task.id)
    )
    assert new_results == 0


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("file_size_bytes", 0),
        # PLY became a valid format in increment 15; an unlisted value stays
        # rejected by the extended CHECK constraint.
        ("format", "SPLAT"),
        ("sha256", "short"),
    ],
)
def test_result_rejects_invalid_values(
    db_session, make_user, make_project, make_task, make_result, column, value
) -> None:
    owner = make_user()
    project = make_project(owner)
    task = make_task(project)
    with raises_integrity_error(db_session):
        make_result(project, task, **{column: value})


def test_result_storage_key_must_be_unique(
    db_session, make_user, make_project, make_task, make_result
) -> None:
    owner = make_user()
    project = make_project(owner)
    result = make_result(project, make_task(project, status="COMPLETED"))
    with raises_integrity_error(db_session):
        make_result(project, make_task(project, status="COMPLETED"), storage_key=result.storage_key)


# --- storage_cleanup_jobs (Section 12) ------------------------------------


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("target_type", "SYMLINK"),
        ("status", "SCHEDULED"),
    ],
)
def test_cleanup_job_rejects_invalid_enumerations(
    db_session, make_user, make_project, make_cleanup_job, column, value
) -> None:
    owner = make_user()
    project = make_project(owner)
    with raises_integrity_error(db_session):
        make_cleanup_job(project, **{column: value})


def test_cleanup_job_may_be_project_independent(db_session, make_cleanup_job) -> None:
    job = make_cleanup_job(None, storage_key="orphaned/file.glb")
    assert job.project_id is None
    assert job.status == "PENDING"


def test_only_one_active_cleanup_per_storage_key(
    db_session, make_user, make_project, make_cleanup_job
) -> None:
    owner = make_user()
    project = make_project(owner)
    key = f"projects/{project.id}/"
    first = make_cleanup_job(project, storage_key=key)
    with raises_integrity_error(db_session):
        make_cleanup_job(project, storage_key=key)

    db_session.execute(
        update(StorageCleanupJob).where(StorageCleanupJob.id == first.id).values(status="COMPLETED")
    )
    db_session.flush()
    make_cleanup_job(project, storage_key=key)
    assert count(db_session, StorageCleanupJob) == 2


# --- outbox_messages (Section 13) -----------------------------------------


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("status", "SCHEDULED"),
        ("event_type", "generation.unknown"),
    ],
)
def test_outbox_rejects_invalid_enumerations(
    db_session, make_user, make_project, make_task, make_outbox_message, column, value
) -> None:
    owner = make_user()
    project = make_project(owner)
    task = make_task(project)
    with raises_integrity_error(db_session):
        make_outbox_message(task, **{column: value})


def test_outbox_allows_repeated_messages_for_one_aggregate(
    db_session, make_user, make_project, make_task, make_outbox_message
) -> None:
    """At-least-once dispatch must be able to enqueue a retry (Section 13.4)."""
    owner = make_user()
    project = make_project(owner)
    task = make_task(project)
    make_outbox_message(task)
    make_outbox_message(task)

    assert count(db_session, OutboxMessage) == 2


# --- deletion policies (Section 14) ---------------------------------------


def test_user_delete_cascades_sessions(db_session, make_user, make_session) -> None:
    user = make_user()
    make_session(user)

    db_session.execute(delete(User).where(User.id == user.id))
    db_session.flush()

    assert count(db_session, UserSession) == 0


def test_user_delete_is_restricted_while_projects_exist(
    db_session, make_user, make_project
) -> None:
    user = make_user()
    make_project(user)

    with raises_integrity_error(db_session):
        db_session.execute(delete(User).where(User.id == user.id))


def test_task_delete_cascades_its_image_snapshot(
    db_session,
    make_user,
    make_project,
    make_image,
    make_task,
    make_task_image,
) -> None:
    owner = make_user()
    project = make_project(owner)
    task = make_task(project)
    image = make_image(project)
    make_task_image(task, image)

    db_session.execute(delete(GenerationTask).where(GenerationTask.id == task.id))
    db_session.flush()

    assert count(db_session, GenerationTaskImage) == 0


def test_task_delete_cascades_its_result(
    db_session, make_user, make_project, make_task, make_result
) -> None:
    owner = make_user()
    project = make_project(owner)
    task = make_task(project, status="COMPLETED")
    make_result(project, task, is_current=True)

    db_session.execute(delete(GenerationTask).where(GenerationTask.id == task.id))
    db_session.flush()

    assert count(db_session, GenerationResult) == 0


def test_image_delete_is_restricted_while_a_task_references_it(
    db_session,
    make_user,
    make_project,
    make_image,
    make_task,
    make_task_image,
) -> None:
    owner = make_user()
    project = make_project(owner)
    task = make_task(project)
    image = make_image(project)
    make_task_image(task, image)

    with raises_integrity_error(db_session):
        db_session.execute(delete(ProjectImage).where(ProjectImage.id == image.id))

    db_session.execute(delete(GenerationTaskImage).where(GenerationTaskImage.image_id == image.id))
    db_session.flush()
    db_session.execute(delete(ProjectImage).where(ProjectImage.id == image.id))
    db_session.flush()

    assert count(db_session, ProjectImage) == 0


def test_project_delete_cascades_images_tasks_and_results(
    db_session, make_user, make_project, make_image, make_task, make_result
) -> None:
    owner = make_user()
    project = make_project(owner)
    make_image(project)
    task = make_task(project)
    make_result(project, task)

    db_session.execute(delete(Project).where(Project.id == project.id))
    db_session.flush()

    assert count(db_session, ProjectImage) == 0
    assert count(db_session, GenerationTask) == 0
    assert count(db_session, GenerationResult) == 0


def test_project_physical_deletion_order_and_cleanup_history(
    db_session,
    make_user,
    make_project,
    make_image,
    make_task,
    make_task_image,
    make_result,
    make_cleanup_job,
) -> None:
    """Section 12.4: delete children first; cleanup history survives."""
    owner = make_user()
    project = make_project(owner)
    image = make_image(project)
    task = make_task(project)
    make_task_image(task, image)
    make_result(project, task)
    cleanup = make_cleanup_job(project)

    db_session.execute(
        delete(GenerationTaskImage).where(GenerationTaskImage.project_id == project.id)
    )
    db_session.execute(delete(GenerationResult).where(GenerationResult.project_id == project.id))
    db_session.execute(delete(GenerationTask).where(GenerationTask.project_id == project.id))
    db_session.execute(delete(ProjectImage).where(ProjectImage.project_id == project.id))
    db_session.execute(delete(Project).where(Project.id == project.id))
    db_session.flush()

    db_session.expire_all()
    assert db_session.get(Project, project.id) is None
    assert count(db_session, GenerationTask) == 0
    assert db_session.get(StorageCleanupJob, cleanup.id).project_id is None


def make_project_with(db_session: Session, owner: User, **values) -> Project:
    """Insert a project with defaults, for negative tests that override one field."""
    defaults = {"name": "Test project", "type": "OBJECT", "status": "CREATED"}
    defaults.update(values)
    project = Project(user_id=owner.id, **defaults)
    db_session.add(project)
    db_session.flush()
    return project


def make_task_with(db_session: Session, project: Project, **values) -> GenerationTask:
    """Insert a task bypassing the factory defaults, for negative tests."""
    defaults = {
        "task_type": "OBJECT",
        "status": "PENDING",
        "idempotency_key": uuid.uuid4().hex,
        "request_fingerprint": uuid.uuid4().hex + uuid.uuid4().hex,
        "parameters": {},
    }
    defaults.update(values)
    task = GenerationTask(project_id=project.id, **defaults)
    db_session.add(task)
    db_session.flush()
    return task
