"""Request fingerprint and parameter snapshot (05 Section 9.6, roadmap 4.5).

Traceability: DB-AC-21 (project-scoped idempotency key plus request
fingerprint), API-AC-10 (a reused key with a different request is rejected),
TEST-AC-06 (task lifecycle and idempotency tests).
"""

from __future__ import annotations

import uuid

import pytest

from app.db.models.enums import TaskType
from app.services.generation_service import (
    compute_request_fingerprint,
    task_parameters_for,
)

pytestmark = pytest.mark.unit

PROJECT_ID = uuid.UUID("550e8400-e29b-41d4-a716-446655440000")
IMAGE_A = uuid.UUID("550e8400-e29b-41d4-a716-446655440001")
IMAGE_B = uuid.UUID("550e8400-e29b-41d4-a716-446655440002")


def _fingerprint(
    *,
    task_type: TaskType = TaskType.OBJECT,
    image_ids: list[uuid.UUID] | None = None,
    parameters: dict[str, str] | None = None,
) -> str:
    return compute_request_fingerprint(
        project_id=PROJECT_ID,
        task_type=task_type,
        image_ids=image_ids if image_ids is not None else [IMAGE_A],
        parameters=parameters if parameters is not None else task_parameters_for(task_type),
    )


def test_object_parameters_match_the_documented_snapshot() -> None:
    assert task_parameters_for(TaskType.OBJECT) == {
        "algorithm": "TripoSR",
        "output_format": "GLB",
    }


def test_scene_parameters_match_the_documented_snapshot() -> None:
    assert task_parameters_for(TaskType.SCENE) == {
        "algorithm": "COLMAP_OPENMVS",
        "output_format": "GLB",
    }


def test_parameters_are_returned_as_a_copy() -> None:
    parameters = task_parameters_for(TaskType.OBJECT)
    parameters["algorithm"] = "changed"

    assert task_parameters_for(TaskType.OBJECT)["algorithm"] == "TripoSR"


def test_fingerprint_is_a_sha256_hex_digest() -> None:
    fingerprint = _fingerprint()

    assert len(fingerprint) == 64
    assert all(character in "0123456789abcdef" for character in fingerprint)


def test_fingerprint_is_stable_for_the_same_request() -> None:
    assert _fingerprint() == _fingerprint()


def test_fingerprint_changes_with_the_image_order() -> None:
    assert _fingerprint(image_ids=[IMAGE_A, IMAGE_B]) != _fingerprint(image_ids=[IMAGE_B, IMAGE_A])


def test_fingerprint_changes_with_the_task_type() -> None:
    assert _fingerprint(task_type=TaskType.OBJECT) != _fingerprint(task_type=TaskType.SCENE)


def test_fingerprint_changes_with_a_parameter() -> None:
    parameters = task_parameters_for(TaskType.OBJECT)
    parameters["output_format"] = "OBJ"

    assert _fingerprint(parameters=parameters) != _fingerprint()


def test_fingerprint_changes_with_the_project() -> None:
    baseline = _fingerprint()
    other = compute_request_fingerprint(
        project_id=uuid.uuid4(),
        task_type=TaskType.OBJECT,
        image_ids=[IMAGE_A],
        parameters=task_parameters_for(TaskType.OBJECT),
    )

    assert other != baseline
