"""Schema and migration tests against a real PostgreSQL database.

The tests drive the real Alembic CLI, so they verify the migration rather than
``Base.metadata.create_all``. Traceability: DB-AC-02, DB-AC-17, DB-AC-18,
DB-AC-21, DB-AC-22; 09_testing.md Sections 8.1 and 8.6; TEST-AC-05.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

pytestmark = pytest.mark.integration

EXPECTED_TABLES = {
    "users",
    "user_sessions",
    "projects",
    "project_images",
    "generation_tasks",
    "generation_task_images",
    "generation_results",
    "storage_cleanup_jobs",
    "outbox_messages",
}


@pytest.fixture
def schema_at_head(migration_database_url: str, migration_alembic) -> Iterator[str]:
    """Reset the scratch database and migrate it to head before each test."""
    migration_alembic(["downgrade", "base"], migration_database_url)
    migration_alembic(["upgrade", "head"], migration_database_url)
    try:
        yield migration_database_url
    finally:
        migration_alembic(["downgrade", "base"], migration_database_url)


@pytest.fixture
def engine(schema_at_head: str) -> Iterator[Engine]:
    engine = create_engine(schema_at_head, pool_pre_ping=True)
    try:
        yield engine
    finally:
        engine.dispose()


def _index_definitions(engine: Engine) -> dict[str, str]:
    query = text("SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public'")
    with engine.connect() as connection:
        return {name: definition for name, definition in connection.execute(query).all()}


def _constraint_definitions(engine: Engine) -> dict[str, str]:
    query = text(
        """
        SELECT conname, pg_get_constraintdef(oid)
        FROM pg_constraint
        WHERE connamespace = 'public'::regnamespace
        """
    )
    with engine.connect() as connection:
        return {name: definition for name, definition in connection.execute(query).all()}


def test_initial_migration_creates_all_tables(engine: Engine) -> None:
    """DB-AC-02 and DB-AC-18: the initial migration creates the whole schema."""
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())

    assert tables >= EXPECTED_TABLES
    assert tables - EXPECTED_TABLES <= {"alembic_version"}
    for table in EXPECTED_TABLES:
        assert inspector.get_pk_constraint(table)["constrained_columns"], table


def test_required_indexes_exist(engine: Engine) -> None:
    """DB-AC-17: indexes required for project listing, task and result lookup."""
    indexes = _index_definitions(engine)

    required = {
        "ix_projects_user_created_at",
        "ix_projects_user_status",
        "ix_projects_type",
        "ix_projects_deleted_at",
        "ix_project_images_project_position",
        "ix_generation_tasks_project_created_at",
        "ix_generation_tasks_status_created_at",
        "ix_generation_tasks_status_lease_expires_at",
        "ix_generation_tasks_worker_id",
        "ix_generation_task_images_image_project",
        "ix_generation_results_project_id",
        "ix_storage_cleanup_jobs_project_id",
        "ix_storage_cleanup_jobs_status_created_at",
        "ix_outbox_aggregate",
    }
    assert required <= set(indexes)
    assert "created_at DESC" in indexes["ix_projects_user_created_at"]
    assert "created_at DESC" in indexes["ix_generation_tasks_project_created_at"]
    assert indexes["ix_generation_task_images_image_project"].endswith("(image_id, project_id)")


def test_partial_unique_indexes_have_the_specified_predicates(engine: Engine) -> None:
    """DB-AC-09, DB-AC-11, DB-AC-20 and DB-AC-21: partial and scoped uniqueness."""
    indexes = _index_definitions(engine)

    assert (
        "CREATE UNIQUE INDEX uq_generation_task_active_project"
        in indexes["uq_generation_task_active_project"]
    )
    assert "WHERE" in indexes["uq_generation_task_active_project"]
    assert "PENDING" in indexes["uq_generation_task_active_project"]
    assert "PROCESSING" in indexes["uq_generation_task_active_project"]

    assert (
        "CREATE UNIQUE INDEX uq_generation_results_current_project"
        in indexes["uq_generation_results_current_project"]
    )
    assert "is_current = true" in indexes["uq_generation_results_current_project"]

    assert "ix_outbox_pending" in indexes
    assert "WHERE" in indexes["ix_outbox_pending"]
    assert "PENDING" in indexes["ix_outbox_pending"]

    idempotency = indexes["uq_generation_task_idempotency"]
    assert "CREATE UNIQUE INDEX" in idempotency
    assert "(project_id, idempotency_key)" in idempotency


def test_composite_ownership_foreign_keys_are_in_the_migration(engine: Engine) -> None:
    """DB-AC-22: composite ownership FKs are declared in the initial migration."""
    constraints = _constraint_definitions(engine)

    task_fk = constraints["fk_generation_task_images_task_project"]
    assert "FOREIGN KEY (task_id, project_id)" in task_fk
    assert "generation_tasks(id, project_id)" in task_fk
    assert "ON DELETE CASCADE" in task_fk

    image_fk = constraints["fk_generation_task_images_image_project"]
    assert "FOREIGN KEY (image_id, project_id)" in image_fk
    assert "project_images(id, project_id)" in image_fk
    assert "ON DELETE RESTRICT" in image_fk

    result_fk = constraints["fk_generation_results_task_project"]
    assert "FOREIGN KEY (task_id, project_id)" in result_fk
    assert "generation_tasks(id, project_id)" in result_fk

    assert "ON DELETE SET NULL" in constraints["fk_storage_cleanup_jobs_project_id_projects"]
    assert "ON DELETE CASCADE" in constraints["fk_user_sessions_user_id_users"]
    assert "ON DELETE RESTRICT" in constraints["fk_projects_user_id_users"]


def test_check_constraints_cover_the_enumerations(engine: Engine) -> None:
    """DB-AC-13: required CHECK constraints are part of the schema."""
    constraints = _constraint_definitions(engine)

    expected_checks = {
        "ck_projects_type",
        "ck_projects_status",
        "ck_projects_name_not_empty",
        "ck_user_sessions_expires_after_created",
        "ck_project_images_file_size_positive",
        "ck_project_images_width_positive",
        "ck_project_images_height_positive",
        "ck_project_images_position_non_negative",
        "ck_project_images_sha256_format",
        "ck_project_images_mime_type",
        "ck_generation_tasks_task_type",
        "ck_generation_tasks_status",
        "ck_generation_tasks_progress_percent_range",
        "ck_generation_task_images_position_non_negative",
        "ck_generation_results_format",
        "ck_generation_results_file_size_positive",
        "ck_generation_results_sha256_format",
        "ck_storage_cleanup_jobs_target_type",
        "ck_storage_cleanup_jobs_status",
        "ck_outbox_messages_event_type",
        "ck_outbox_messages_status",
    }
    assert expected_checks <= set(constraints)

    assert "CANCELLED" in constraints["ck_generation_tasks_status"]
    progress_check = constraints["ck_generation_tasks_progress_percent_range"]
    assert "progress_percent IS NULL" in progress_check
    assert "0" in progress_check
    assert "100" in progress_check
    assert "expires_at > created_at" in constraints["ck_user_sessions_expires_after_created"]
    assert "PUBLISHED" in constraints["ck_outbox_messages_status"]


def test_downgrade_removes_the_schema_and_upgrade_restores_it(
    engine: Engine, migration_database_url: str, migration_alembic
) -> None:
    """DB-AC-18: migrations can be reversed and re-applied on a clean database."""
    migration_alembic(["downgrade", "base"], migration_database_url)
    remaining = set(inspect(engine).get_table_names())
    assert remaining & EXPECTED_TABLES == set()

    migration_alembic(["upgrade", "head"], migration_database_url)
    restored = set(inspect(engine).get_table_names())
    assert restored >= EXPECTED_TABLES


def test_alembic_check_reports_no_model_drift(schema_at_head: str, migration_alembic) -> None:
    """The committed migration is in sync with the ORM metadata."""
    result = migration_alembic(["check"], schema_at_head)
    assert "No new upgrade operations detected" in result.stdout
