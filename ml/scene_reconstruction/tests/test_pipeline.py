"""Pipeline orchestration, stage order, checkpointing and failure handling."""

from __future__ import annotations

import pytest

from scene_reconstruction import pipeline as pipeline_module
from scene_reconstruction.colmap_runner import StageOutcome, read_database_stats
from scene_reconstruction.dataset import SourceImage
from scene_reconstruction.exceptions import (
    TEXTURE_GENERATION_FAILED,
    SceneCancelled,
    SceneReconstructionError,
)
from scene_reconstruction.mesh_processor import inspect_mesh
from scene_reconstruction.openmvs_runner import OpenMvsOutcome
from scene_reconstruction.pipeline import (
    PhotogrammetryReconstructor,
    PipelineCallbacks,
)
from scene_reconstruction.preflight import ToolchainReport

from .helpers import (
    create_colmap_database,
    default_config,
    gradient_image_bytes,
    textured_png,
    textured_quad_obj,
    write_mesh_ply,
    write_ply_points,
    write_raw_glb,
    write_sparse_model,
)


class FakeColmap:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def extract_features(self, *, images_dir, database_path, log_path, expected_images, on_poll):
        self.calls.append("FEATURE_EXTRACTION")
        create_colmap_database(database_path, images=expected_images, verified_pairs=[])
        return StageOutcome(
            stage="FEATURE_EXTRACTION",
            duration_seconds=0.1,
            log_path=log_path,
            database=read_database_stats(database_path),
        )

    def match_features(self, *, database_path, log_path, on_poll):
        self.calls.append("FEATURE_MATCHING")
        stats = read_database_stats(database_path)
        create_colmap_database(
            database_path,
            images=stats.images,
            verified_pairs=[(index, index + 1) for index in range(1, stats.images)],
        )
        return StageOutcome(
            stage="FEATURE_MATCHING",
            duration_seconds=0.1,
            log_path=log_path,
            database=read_database_stats(database_path),
        )

    def reconstruct_sparse(self, *, images_dir, database_path, sparse_dir, log_path, on_poll):
        self.calls.append("SPARSE_RECONSTRUCTION")
        model = sparse_dir / "0"
        model.mkdir(parents=True, exist_ok=True)
        for name in ("cameras.bin", "images.bin", "points3D.bin"):
            (model / name).write_bytes(b"model")
        return StageOutcome(
            stage="SPARSE_RECONSTRUCTION",
            duration_seconds=0.1,
            log_path=log_path,
            model_dirs=(model,),
        )

    def convert_model(self, *, model_dir, output_dir, log_path, on_poll):
        self.calls.append("RECONSTRUCTION_VALIDATION")
        write_sparse_model(
            output_dir,
            images=[(index, 0.3) for index in range(1, 6)],
            points=[(index, 0.4, [1, 2, 3, 4, 5]) for index in range(1, 21)],
        )
        return StageOutcome(
            stage="RECONSTRUCTION_VALIDATION",
            duration_seconds=0.1,
            log_path=log_path,
        )

    def undistort(self, *, images_dir, model_dir, dense_dir, log_path, on_poll):
        self.calls.append("IMAGE_UNDISTORTION")
        (dense_dir / "images").mkdir(parents=True, exist_ok=True)
        (dense_dir / "images" / "image_001.jpg").write_bytes(b"undistorted")
        (dense_dir / "sparse").mkdir(parents=True, exist_ok=True)
        for name in ("cameras.bin", "images.bin", "points3D.bin"):
            (dense_dir / "sparse" / name).write_bytes(b"sparse")
        return StageOutcome(stage="IMAGE_UNDISTORTION", duration_seconds=0.1, log_path=log_path)


class FakeOpenMvs:
    def __init__(self, calls: list[str], *, fail_texture: bool = False) -> None:
        self.calls = calls
        self.fail_texture = fail_texture

    def import_scene(self, *, dense_dir, scene_file, work_dir, log_path, on_poll):
        self.calls.append("OPENMVS_IMPORT")
        scene_file.write_bytes(b"scene")
        return OpenMvsOutcome("OPENMVS_IMPORT", 0.1, log_path, (scene_file,))

    def densify(self, *, scene_file, dense_scene, work_dir, log_path, on_poll):
        self.calls.append("DENSE_RECONSTRUCTION")
        dense_scene.write_bytes(b"dense scene")
        write_ply_points(work_dir / "scene_dense.ply", vertices=5000)
        return OpenMvsOutcome(
            "DENSE_RECONSTRUCTION", 0.1, log_path, (dense_scene,), dense_points=5000
        )

    def reconstruct_mesh(self, *, dense_scene, mesh_path, work_dir, log_path, on_poll):
        self.calls.append("MESH_GENERATION")
        write_mesh_ply(mesh_path)
        return OpenMvsOutcome(
            "MESH_GENERATION", 0.1, log_path, (mesh_path,), mesh=inspect_mesh(mesh_path)
        )

    def refine_mesh(self, *, dense_scene, mesh_path, refined_mesh, work_dir, log_path, on_poll):
        self.calls.append("MESH_REFINEMENT")
        write_mesh_ply(refined_mesh)
        return OpenMvsOutcome(
            "MESH_REFINEMENT",
            0.1,
            log_path,
            (refined_mesh,),
            mesh=inspect_mesh(refined_mesh),
        )

    def texture(self, *, dense_scene, mesh_path, textured_mesh, work_dir, log_path, on_poll):
        self.calls.append("TEXTURING")
        if self.fail_texture:
            raise SceneReconstructionError(
                TEXTURE_GENERATION_FAILED, "Texturing failed for the test."
            )
        write_mesh_ply(textured_mesh)
        texture = textured_png(work_dir / "scene_texture0.png")
        return OpenMvsOutcome("TEXTURING", 0.1, log_path, (textured_mesh, texture))

    def transform(
        self,
        *,
        scene_file,
        output_base,
        export_type,
        work_dir,
        log_path,
        on_poll,
        mesh_file=None,
    ):
        self.calls.append(f"ASSET_EXPORT:{export_type}")
        if export_type == "obj":
            obj = textured_quad_obj(output_base.parent)
            return OpenMvsOutcome("ASSET_EXPORT", 0.1, log_path, (obj,))
        glb = write_raw_glb(output_base.parent / "scene_mesh.glb")
        return OpenMvsOutcome("ASSET_EXPORT", 0.1, log_path, (glb,))


def _sources(count: int = 5) -> list[SourceImage]:
    return [
        SourceImage.from_bytes(
            gradient_image_bytes(seed=index), filename=f"photo_{index}.jpg", image_id=str(index)
        )
        for index in range(1, count + 1)
    ]


def _install_fakes(monkeypatch, calls, *, fail_texture: bool = False):
    colmap = FakeColmap(calls)
    openmvs = FakeOpenMvs(calls, fail_texture=fail_texture)
    monkeypatch.setattr(
        pipeline_module,
        "verify_toolchain",
        lambda config: ToolchainReport(tools=()),
    )
    return colmap, openmvs


def _reconstructor(colmap, openmvs, callbacks=None) -> PhotogrammetryReconstructor:
    config = default_config(min_registered_images=3, min_sparse_points=10)
    return PhotogrammetryReconstructor(config, callbacks=callbacks, colmap=colmap, openmvs=openmvs)


def test_full_pipeline_runs_the_documented_stage_order(tmp_path, monkeypatch):
    calls: list[str] = []
    colmap, openmvs = _install_fakes(monkeypatch, calls)
    stages: list[str] = []
    callbacks = PipelineCallbacks(report_stage=lambda stage, message: stages.append(stage))

    artifact = _reconstructor(colmap, openmvs, callbacks).reconstruct(
        _sources(), work_dir=tmp_path / "task"
    )

    assert artifact.path.is_file()
    assert artifact.format == "GLB"
    assert artifact.file_size_bytes > 0
    assert len(artifact.sha256) == 64
    assert artifact.metadata["vertices_count"] >= 3
    assert artifact.metadata["faces_count"] >= 1
    assert artifact.metadata["reconstruction"]["matching_strategy"] == "EXHAUSTIVE"
    assert artifact.diagnostics_path is not None and artifact.diagnostics_path.is_file()
    assert calls == [
        "FEATURE_EXTRACTION",
        "FEATURE_MATCHING",
        "SPARSE_RECONSTRUCTION",
        "RECONSTRUCTION_VALIDATION",
        "IMAGE_UNDISTORTION",
        "OPENMVS_IMPORT",
        "DENSE_RECONSTRUCTION",
        "MESH_GENERATION",
        "MESH_REFINEMENT",
        "TEXTURING",
        "ASSET_EXPORT:obj",
        "ASSET_EXPORT:glb",
    ]
    assert stages == [
        "IMAGE_PREPARATION",
        "FEATURE_EXTRACTION",
        "FEATURE_MATCHING",
        "SPARSE_RECONSTRUCTION",
        "RECONSTRUCTION_VALIDATION",
        "IMAGE_UNDISTORTION",
        "OPENMVS_IMPORT",
        "DENSE_RECONSTRUCTION",
        "MESH_GENERATION",
        "MESH_REFINEMENT",
        "TEXTURING",
        "ASSET_EXPORT",
        "RESULT_VALIDATION",
    ]


def test_rerunning_the_same_task_reuses_validated_stages(tmp_path, monkeypatch):
    calls: list[str] = []
    colmap, openmvs = _install_fakes(monkeypatch, calls)
    work_dir = tmp_path / "task"
    _reconstructor(colmap, openmvs).reconstruct(_sources(), work_dir=work_dir)
    calls.clear()

    _reconstructor(colmap, openmvs).reconstruct(_sources(), work_dir=work_dir)

    assert "FEATURE_EXTRACTION" not in calls
    assert "FEATURE_MATCHING" not in calls
    assert "SPARSE_RECONSTRUCTION" not in calls
    assert "DENSE_RECONSTRUCTION" not in calls
    assert "TEXTURING" not in calls


def test_a_failed_stage_stops_the_pipeline_and_writes_diagnostics(tmp_path, monkeypatch):
    calls: list[str] = []
    colmap, openmvs = _install_fakes(monkeypatch, calls, fail_texture=True)
    with pytest.raises(SceneReconstructionError) as exc:
        _reconstructor(colmap, openmvs).reconstruct(_sources(), work_dir=tmp_path / "task")
    assert exc.value.error_code == TEXTURE_GENERATION_FAILED
    assert "ASSET_EXPORT:obj" not in calls
    diagnostics = (tmp_path / "task" / "diagnostics.json").read_text(encoding="utf-8")
    assert "TEXTURE_GENERATION_FAILED" in diagnostics
    assert not (tmp_path / "task" / "output" / "scene.glb").exists()


def test_cancellation_stops_before_any_tool_runs(tmp_path, monkeypatch):
    calls: list[str] = []
    colmap, openmvs = _install_fakes(monkeypatch, calls)
    counter = {"value": 0}

    def raise_if_cancelled() -> None:
        counter["value"] += 1
        if counter["value"] > 1:
            raise SceneCancelled("cancelled")

    callbacks = PipelineCallbacks(raise_if_cancelled=raise_if_cancelled)
    with pytest.raises(SceneCancelled):
        _reconstructor(colmap, openmvs, callbacks).reconstruct(
            _sources(), work_dir=tmp_path / "task"
        )
    assert calls == []


def test_disabling_refinement_and_texturing_still_exports_the_mesh(tmp_path, monkeypatch):
    calls: list[str] = []
    colmap, openmvs = _install_fakes(monkeypatch, calls)
    config = default_config(
        min_registered_images=3,
        min_sparse_points=10,
        enable_mesh_refinement=False,
        enable_texture_generation=False,
    )

    artifact = PhotogrammetryReconstructor(config, colmap=colmap, openmvs=openmvs).reconstruct(
        _sources(), work_dir=tmp_path / "task"
    )

    assert "MESH_REFINEMENT" not in calls
    assert "TEXTURING" not in calls
    assert "ASSET_EXPORT:obj" in calls
    assert artifact.path.is_file()


def test_artifact_metadata_is_json_serialisable(tmp_path, monkeypatch):
    import json

    calls: list[str] = []
    colmap, openmvs = _install_fakes(monkeypatch, calls)
    artifact = _reconstructor(colmap, openmvs).reconstruct(_sources(), work_dir=tmp_path / "task")
    json.dumps(artifact.metadata)
