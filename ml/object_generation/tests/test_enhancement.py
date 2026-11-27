"""Enhancement unit tests (14 Sections 5.1-5.3 and 10.1)."""

from __future__ import annotations

import numpy as np
import pytest
import trimesh
from mesh_enhancement import (
    CleanupError,
    build_enhancement_manifest,
    cleanup_mesh,
    ensure_normals,
    measure_mesh,
    mesh_fingerprint,
    simplify_mesh,
)

import object_generation.enhancement as enhancement_module
from object_generation.enhancement import EnhancementConfig, enhance_object
from object_generation.exceptions import EnhancementError, ExportError
from tests.helpers import colored_box, textured_box


def _open_mesh() -> trimesh.Trimesh:
    vertices = np.array(
        [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 1.0, 0.0], [0.0, 1.0, 0.0]],
        dtype=float,
    )
    faces = np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int64)
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    mesh.visual.vertex_colors = np.tile(
        np.array([[20, 40, 60, 255]], dtype=np.uint8), (len(vertices), 1)
    )
    return mesh


def test_cleanup_removes_degenerate_faces_and_unreferenced_vertices() -> None:
    mesh = colored_box()
    vertices = np.vstack([mesh.vertices, [[9.0, 9.0, 9.0]]])
    faces = np.vstack([mesh.faces, [[0, 0, 1]], [[8, 8, 0]]])
    broken = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    broken.visual.vertex_colors = np.tile(
        np.array([[100, 10, 10, 255]], dtype=np.uint8), (len(vertices), 1)
    )
    before = measure_mesh(broken)

    outcome = cleanup_mesh(broken, merge_tolerance_ratio=0.0)

    after = measure_mesh(outcome.mesh)
    assert before.degenerate_faces == 2
    assert after.degenerate_faces == 0
    assert after.unreferenced_vertices == 0
    assert outcome.faces_removed == 2
    assert after.faces == len(mesh.faces)
    assert after.has_vertex_colors is True


def test_cleanup_preserves_open_non_manifold_geometry_and_components() -> None:
    mesh = _open_mesh()
    # Duplicate the triangle set as a second component; it must survive by default.
    vertices = np.vstack([mesh.vertices, mesh.vertices + [3.0, 0.0, 0.0]])
    faces = np.vstack([mesh.faces, mesh.faces + 4])
    combined = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    combined.visual.vertex_colors = np.tile(
        np.array([[10, 20, 30, 255]], dtype=np.uint8), (len(vertices), 1)
    )

    outcome = cleanup_mesh(combined, remove_small_components=False)
    metrics = measure_mesh(outcome.mesh)

    assert metrics.faces == 4
    assert metrics.components == 2
    assert metrics.boundary_edges > 0
    assert metrics.is_watertight is False


def test_cleanup_removes_small_components_only_when_configured() -> None:
    main = trimesh.creation.icosphere(subdivisions=2)
    main.visual.vertex_colors = np.tile(
        np.array([[100, 100, 100, 255]], dtype=np.uint8), (len(main.vertices), 1)
    )
    tiny = trimesh.creation.icosphere(subdivisions=0, radius=0.01)
    tiny.apply_translation([5.0, 0.0, 0.0])
    tiny.visual.vertex_colors = np.tile(
        np.array([[10, 10, 10, 255]], dtype=np.uint8), (len(tiny.vertices), 1)
    )
    combined = trimesh.util.concatenate([main, tiny])

    preserved = cleanup_mesh(combined, remove_small_components=False)
    removed = cleanup_mesh(combined, remove_small_components=True, small_component_faces=32)

    assert measure_mesh(preserved.mesh).components == 2
    assert measure_mesh(removed.mesh).components == 1
    assert removed.components_removed == 1


def test_cleanup_never_merges_across_uv_seams() -> None:
    mesh = textured_box()
    before = len(mesh.vertices)

    outcome = cleanup_mesh(mesh, merge_tolerance_ratio=1e-3)

    assert len(outcome.mesh.vertices) == before
    assert "duplicate_merge_skipped_uv_seams" in outcome.skipped
    assert outcome.mesh.visual.uv is not None
    assert len(outcome.mesh.visual.uv) == len(outcome.mesh.vertices)


def test_cleanup_rejects_an_empty_mesh() -> None:
    empty = trimesh.Trimesh(
        vertices=np.array([[0.0, 0.0, 0.0]]), faces=np.zeros((0, 3)), process=False
    )
    with pytest.raises(CleanupError):
        cleanup_mesh(empty)


def test_normals_are_finite_and_open_winding_is_not_flipped() -> None:
    mesh = _open_mesh()

    outcome = ensure_normals(mesh)

    assert outcome.normals.shape == (len(mesh.vertices), 3)
    assert np.isfinite(outcome.normals).all()
    assert (np.linalg.norm(outcome.normals, axis=1) > 0).all()
    assert "open_or_multibody_winding_unverified" in outcome.skipped


def test_injected_simplifier_applies_within_the_deviation_budget() -> None:
    source = trimesh.creation.icosphere(subdivisions=2)
    source.visual.vertex_colors = np.tile(
        np.array([[90, 120, 150, 255]], dtype=np.uint8), (len(source.vertices), 1)
    )
    target = 80

    def simplifier(_mesh, _target):
        candidate = trimesh.creation.icosphere(subdivisions=1)
        candidate.visual.vertex_colors = np.tile(
            np.array([[90, 120, 150, 255]], dtype=np.uint8), (len(candidate.vertices), 1)
        )
        return candidate

    outcome = simplify_mesh(
        source, target_faces=target, max_deviation_ratio=0.5, simplifier=simplifier
    )

    assert outcome.applied is True
    assert outcome.mesh is not None
    assert len(outcome.mesh.faces) <= target
    assert outcome.deviation_ratio is not None


def test_simplification_rejects_excessive_deviation() -> None:
    source = trimesh.creation.icosphere(subdivisions=2)
    source.visual.vertex_colors = np.tile(
        np.array([[90, 120, 150, 255]], dtype=np.uint8), (len(source.vertices), 1)
    )

    def simplifier(_mesh, _target):
        candidate = trimesh.creation.box(extents=(4.0, 4.0, 4.0))
        candidate.visual.vertex_colors = np.tile(
            np.array([[90, 120, 150, 255]], dtype=np.uint8), (len(candidate.vertices), 1)
        )
        return candidate

    outcome = simplify_mesh(
        source, target_faces=100, max_deviation_ratio=0.01, simplifier=simplifier
    )

    assert outcome.applied is False
    assert outcome.reason == "DEVIATION_BUDGET_EXCEEDED"


def test_simplification_skips_when_attributes_are_lost() -> None:
    source = trimesh.creation.icosphere(subdivisions=2)
    source.visual.vertex_colors = np.tile(
        np.array([[90, 120, 150, 255]], dtype=np.uint8), (len(source.vertices), 1)
    )

    def simplifier(_mesh, _target):
        return trimesh.creation.icosphere(subdivisions=1)

    outcome = simplify_mesh(
        source, target_faces=100, max_deviation_ratio=0.5, simplifier=simplifier
    )

    assert outcome.applied is False
    assert outcome.reason == "ATTRIBUTES_NOT_PRESERVED"


def test_missing_simplifier_is_a_safe_skip() -> None:
    source = trimesh.creation.icosphere(subdivisions=2)
    outcome = simplify_mesh(source, target_faces=10, max_deviation_ratio=0.5)
    assert outcome.applied is False
    assert outcome.reason == "SIMPLIFIER_UNAVAILABLE"


def test_default_enhancement_cleans_and_export_ready_normals() -> None:
    mesh = colored_box()

    result = enhance_object(mesh, EnhancementConfig())

    assert result.operations == ["mesh_cleanup", "normal_correction"]
    assert result.normal_export is True
    assert result.appearance_mode == "vertex_colors"
    assert result.after.has_normals is True
    assert result.before.as_metadata()["vertices_count"] >= result.after.vertices
    assert result.manifest["scope"] == "object_generation"
    assert result.manifest["source_fingerprint"] == mesh_fingerprint(mesh)


def test_texture_baking_is_opt_in_and_produces_metadata() -> None:
    mesh = colored_box()

    result = enhance_object(
        mesh,
        EnhancementConfig(bake_texture=True, texture_resolution=128, uv_padding=2),
    )

    assert "uv_generation" in result.operations
    assert "texture_baking" in result.operations
    assert result.appearance_mode == "texture"
    assert result.baking is not None
    assert result.baking["coverage_ratio"] > 0
    assert result.after.has_textures is True
    assert result.after.has_uvs is True


def test_textured_source_is_preserved_instead_of_rebaked() -> None:
    mesh = textured_box()

    result = enhance_object(mesh, EnhancementConfig(bake_texture=True))

    assert result.skipped == [{"operation": "texture_baking", "reason": "source_texture_preserved"}]
    assert result.appearance_mode == "texture"
    assert result.baking is None


def test_baking_failure_falls_back_to_the_vertex_colour_asset(monkeypatch) -> None:
    def broken(*_args, **_kwargs):
        raise ExportError("TEXTURE_BAKING_FAILED", "bake failed")

    monkeypatch.setattr(enhancement_module, "bake_vertex_colors", broken)

    result = enhance_object(
        colored_box(), EnhancementConfig(bake_texture=True, texture_resolution=128)
    )

    assert result.fallback_used is True
    assert {"operation": "texture_baking", "reason": "TEXTURE_BAKING_FAILED"} in result.skipped
    assert result.appearance_mode == "vertex_colors"


def test_baking_failure_is_fatal_when_fallback_is_disabled(monkeypatch) -> None:
    def broken(*_args, **_kwargs):
        raise ExportError("TEXTURE_BAKING_FAILED", "bake failed")

    monkeypatch.setattr(enhancement_module, "bake_vertex_colors", broken)

    with pytest.raises(EnhancementError) as excinfo:
        enhance_object(
            colored_box(),
            EnhancementConfig(
                bake_texture=True,
                texture_resolution=128,
                fallback_to_original=False,
            ),
        )

    assert excinfo.value.error_code == "TEXTURE_BAKING_FAILED"


def test_memory_budget_skips_optional_operations(monkeypatch) -> None:
    monkeypatch.setattr(enhancement_module, "_peak_rss_mb", lambda: 10_000.0)

    result = enhance_object(colored_box(), EnhancementConfig(max_memory_mb=512))

    assert result.operations == []
    assert result.fallback_used is False
    assert result.skipped[0]["reason"] == "ENHANCEMENT_RESOURCE_EXHAUSTED"


def test_cancellation_poll_is_checked_before_work() -> None:
    def cancelled() -> None:
        raise RuntimeError("cancelled")

    with pytest.raises(RuntimeError):
        enhance_object(colored_box(), EnhancementConfig(), on_poll=cancelled)


def test_enhancement_manifest_changes_with_settings() -> None:
    mesh = colored_box()
    first = enhance_object(mesh, EnhancementConfig(merge_tolerance=1e-6))
    second = enhance_object(mesh, EnhancementConfig(merge_tolerance=1e-5))

    assert first.manifest["settings"] != second.manifest["settings"]
    assert first.manifest["source_fingerprint"] == second.manifest["source_fingerprint"]


def test_manifest_builder_includes_dependency_versions() -> None:
    manifest = build_enhancement_manifest(
        scope="object_generation",
        settings={"cleanup_enabled": True},
        source_fingerprint="abc",
    )
    assert manifest["dependencies"]["trimesh"]
    assert manifest["dependencies"]["numpy"]
    assert manifest["settings"]["cleanup_enabled"] is True


@pytest.mark.parametrize(
    "kwargs",
    [
        {"merge_tolerance": -0.1},
        {"simplification_enabled": True, "target_faces": 0},
        {"max_deviation": 0.0},
        {"smoothing_iterations": 1},
        {"uv_resolution": 32},
        {"texture_resolution": 8192},
        {"uv_padding": 65},
        {"device": "cuda:0"},
        {"max_memory_mb": 128},
        {"ai_texture_enabled": True},
        {"ai_texture_backend": "generic"},
    ],
)
def test_enhancement_config_rejects_invalid_values(kwargs) -> None:
    with pytest.raises(ValueError):
        EnhancementConfig(**kwargs)


def test_measure_mesh_reports_open_and_degenerate_facts() -> None:
    metrics = measure_mesh(_open_mesh())
    assert metrics.components == 1
    assert metrics.boundary_edges == 4
    assert metrics.is_watertight is False
    assert metrics.degenerate_faces == 0


def test_backend_settings_map_into_the_object_enhancement_config() -> None:
    from types import SimpleNamespace

    from object_generation.pipeline import build_config_from_settings

    settings = SimpleNamespace(
        object_model_dir="/models/triposr",
        object_model_revision="revision",
        object_model_sha256="hash",
        object_model_id="stabilityai/TripoSR",
        object_device="cpu",
        object_allow_cpu_fallback=False,
        object_chunk_size=1024,
        object_mc_resolution=64,
        object_remove_background=False,
        object_foreground_ratio=0.85,
        object_output_format="glb",
        object_bake_texture=True,
        object_texture_resolution=256,
        object_max_task_seconds=60,
        object_rembg_model="u2net",
        object_input_size=128,
        object_generator="triposr",
        object_generator_fallback=False,
        object_sf3d_enabled=False,
        object_sf3d_model_id="stabilityai/stable-fast-3d",
        object_sf3d_model_revision="",
        object_sf3d_model_dir="/models/sf3d",
        object_sf3d_manifest_path="/models/sf3d/manifest.json",
        object_sf3d_texture_resolution=1024,
        object_sf3d_remesh="none",
        object_sf3d_target_vertex_count=-1,
        object_mesh_cleanup_enabled=False,
        object_mesh_normals_enabled=False,
        object_mesh_simplification_enabled=True,
        object_mesh_target_faces=500,
        object_generate_uv=True,
        object_uv_resolution=512,
        object_uv_padding=3,
        object_texture_padding=5,
        object_ai_texture_enabled=False,
        object_ai_texture_backend="disabled",
        enhancement_fallback_to_original=False,
        mesh_enhancement_max_memory_mb=2048,
        texture_enhancement_device="cpu",
    )

    config = build_config_from_settings(settings)

    assert config.enhancement.cleanup_enabled is False
    assert config.enhancement.normals_enabled is False
    assert config.enhancement.simplification_enabled is True
    assert config.enhancement.target_faces == 500
    assert config.enhancement.generate_uv is True
    assert config.enhancement.bake_texture is True
    assert config.enhancement.texture_resolution == 256
    assert config.enhancement.uv_resolution == 512
    assert config.enhancement.fallback_to_original is False
    assert config.enhancement.max_memory_mb == 2048
