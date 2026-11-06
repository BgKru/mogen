"""Per-type source image requirements (04 Sections 10.4-10.5, roadmap 4.5).

Traceability: BE-AC-11/12 (object and scene upload restrictions),
GENERATION_INPUT_MISSING in api_contracts.md Section 9.2.
"""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.core.exceptions import AppError
from app.db.models.enums import TaskType
from app.services.generation_service import validate_generation_inputs

pytestmark = pytest.mark.unit


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": "test",
        "min_scene_images": 3,
        "max_scene_images": 5,
    }
    values.update(overrides)
    return Settings(**values)


@pytest.mark.parametrize("count", [0, 2, 3])
def test_an_object_project_needs_exactly_one_image(count: int) -> None:
    with pytest.raises(AppError) as error:
        validate_generation_inputs(TaskType.OBJECT, image_count=count, settings=_settings())

    assert error.value.status_code == 409
    assert error.value.code == "GENERATION_INPUT_MISSING"


def test_an_object_project_with_one_image_is_accepted() -> None:
    validate_generation_inputs(TaskType.OBJECT, image_count=1, settings=_settings())


@pytest.mark.parametrize("count", [0, 1, 2])
def test_a_scene_project_below_the_minimum_is_rejected(count: int) -> None:
    with pytest.raises(AppError) as error:
        validate_generation_inputs(TaskType.SCENE, image_count=count, settings=_settings())

    assert error.value.code == "GENERATION_INPUT_MISSING"


@pytest.mark.parametrize("count", [3, 4, 5])
def test_a_scene_project_within_the_bounds_is_accepted(count: int) -> None:
    validate_generation_inputs(TaskType.SCENE, image_count=count, settings=_settings())


def test_a_scene_project_above_the_maximum_is_rejected() -> None:
    with pytest.raises(AppError) as error:
        validate_generation_inputs(TaskType.SCENE, image_count=6, settings=_settings())

    assert error.value.status_code == 409
    assert error.value.code == "GENERATION_INPUT_MISSING"
