"""Scene representation and method persistence (increment 15).

Traceability: I15-AC-01, I15-AC-03, I15-AC-09, I15-AC-11 and the addendum's
Sections 4.2 and 7: the representation is a deployment setting, but the task
carries it from creation so routing/retries cannot be re-targeted by a later
environment change.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.db.models.enums import TaskType
from app.services.scene_methods import (
    GAUSSIAN_SPLAT,
    MESH,
    SceneMethod,
    SceneRepresentation,
    configured_representation,
    parameters_for_representation,
    persisted_method,
    persisted_representation,
    result_format_for,
    task_matches_capability,
    task_parameters_for,
)


def _settings(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "scene_representation": "mesh",
        "scene_splat_enabled": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_mesh_is_the_default_representation() -> None:
    assert configured_representation(_settings()) is SceneRepresentation.MESH
    assert parameters_for_representation(SceneRepresentation.MESH) == {
        "algorithm": "COLMAP_OPENMVS",
        "output_format": "GLB",
        "representation": MESH,
        "method": "COLMAP_OPENMVS",
    }


def test_gaussian_splat_requires_the_explicit_capability_gate() -> None:
    with pytest.raises(ValueError, match="scene_splat_enabled"):
        configured_representation(_settings(scene_representation="gaussian_splat"))
    assert (
        configured_representation(
            _settings(scene_representation="gaussian_splat", scene_splat_enabled=True)
        )
        is SceneRepresentation.GAUSSIAN_SPLAT
    )


def test_unknown_representation_is_rejected() -> None:
    with pytest.raises(ValueError, match="scene_representation"):
        configured_representation(_settings(scene_representation="mesh_v2"))


def test_splat_parameters_are_explicit_and_routable() -> None:
    parameters = parameters_for_representation(SceneRepresentation.GAUSSIAN_SPLAT)
    assert parameters == {
        "algorithm": "COLMAP_SPLATFACTO",
        "output_format": "PLY",
        "representation": GAUSSIAN_SPLAT,
        "method": "NERFSTUDIO_SPLATFACTO",
    }
    assert SceneMethod.NERFSTUDIO_SPLATFACTO.value == "NERFSTUDIO_SPLATFACTO"
    assert result_format_for(SceneRepresentation.GAUSSIAN_SPLAT) == "PLY"
    assert result_format_for(SceneRepresentation.MESH) == "GLB"


def test_object_parameters_are_unchanged() -> None:
    assert task_parameters_for(TaskType.OBJECT) == {
        "algorithm": "TripoSR",
        "output_format": "GLB",
    }


def test_scene_task_parameters_follow_the_deployment_setting() -> None:
    mesh = task_parameters_for(TaskType.SCENE, _settings())
    splat = task_parameters_for(
        TaskType.SCENE, _settings(scene_representation="gaussian_splat", scene_splat_enabled=True)
    )
    assert mesh["representation"] == MESH and mesh["output_format"] == "GLB"
    assert splat["representation"] == GAUSSIAN_SPLAT and splat["output_format"] == "PLY"


def test_legacy_tasks_without_a_representation_resolve_to_mesh() -> None:
    assert persisted_representation(None) is SceneRepresentation.MESH
    assert persisted_representation({}) is SceneRepresentation.MESH
    assert persisted_representation({"algorithm": "COLMAP_OPENMVS"}) is SceneRepresentation.MESH
    assert persisted_method(None) == "COLMAP_OPENMVS"


def test_persisted_representation_is_read_back_exactly() -> None:
    parameters = {"representation": "gaussian_splat", "method": "nerfstudio_splatfacto"}
    assert persisted_representation(parameters) is SceneRepresentation.GAUSSIAN_SPLAT
    assert persisted_method(parameters) == "NERFSTUDIO_SPLATFACTO"


def test_unknown_persisted_representation_is_rejected() -> None:
    with pytest.raises(ValueError, match="persisted scene representation"):
        persisted_representation({"representation": "NERF"})


def test_worker_capability_matching_rejects_the_other_representation() -> None:
    mesh_parameters = parameters_for_representation(SceneRepresentation.MESH)
    splat_parameters = parameters_for_representation(SceneRepresentation.GAUSSIAN_SPLAT)

    assert task_matches_capability(mesh_parameters, MESH) is True
    assert task_matches_capability(mesh_parameters, GAUSSIAN_SPLAT) is False
    assert task_matches_capability(splat_parameters, GAUSSIAN_SPLAT) is True
    assert task_matches_capability(splat_parameters, MESH) is False
    # A legacy task is a mesh task, so a splat worker must refuse it.
    assert task_matches_capability(None, MESH) is True
    assert task_matches_capability(None, GAUSSIAN_SPLAT) is False


def test_unknown_worker_capability_is_rejected() -> None:
    with pytest.raises(ValueError, match="capability"):
        task_matches_capability({}, "GAUSSIAN")
