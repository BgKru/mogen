"""Scene enhancement tests (14 Sections 4.2, 5.1-5.3 and 10.1)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import trimesh
from PIL import Image

from scene_reconstruction.config import SceneConfig
from scene_reconstruction.enhancement import (
    SceneEnhancementConfig,
    enhance_scene,
    scene_fingerprint,
)
from scene_reconstruction.exporter import repack_scene
from scene_reconstruction.pipeline import PhotogrammetryReconstructor
from scene_reconstruction.validator import validate_scene_glb

from .helpers import default_config, textured_glb


def _scene() -> trimesh.Scene:
    box = trimesh.creation.box()
    uv = np.random.default_rng(4).random((len(box.vertices), 2))
    box.visual = trimesh.visual.TextureVisuals(
        uv=uv,
        material=trimesh.visual.material.PBRMaterial(
            baseColorTexture=Image.new("RGB", (32, 32), (200, 120, 60)),
            metallicFactor=0.1,
            roughnessFactor=0.6,
        ),
    )
    sphere = trimesh.creation.icosphere(subdivisions=1)
    sphere.visual.vertex_colors = np.tile(
        np.array([[20, 200, 20, 255]], dtype=np.uint8), (len(sphere.vertices), 1)
    )
    scene = trimesh.Scene()
    scene.add_geometry(
        box,
        node_name="textured",
        geom_name="textured",
        transform=trimesh.transformations.translation_matrix([1.0, 2.0, 3.0]),
    )
    scene.add_geometry(sphere, node_name="sphere", geom_name="sphere")
    return scene


def test_scene_enhancement_preserves_textures_transforms_and_materials() -> None:
    scene = _scene()
    transform_before = scene.graph["textured"][0].copy()
    texture_before = scene.geometry["textured"].visual.material.baseColorTexture

    result = enhance_scene(scene, SceneEnhancementConfig(postprocess_enabled=True))

    assert result.normal_export is True
    assert result.before["vertices_count"] > 0
    assert result.after["vertices_count"] > 0
    assert result.after["geometries"] == 2
    textured = scene.geometry["textured"]
    assert textured.visual.material.baseColorTexture is texture_before
    assert np.allclose(scene.graph["textured"][0], transform_before)
    assert result.as_metadata()["scope"] == "scene"
    assert result.manifest["dependencies"]["trimesh"]


def test_scene_simplification_skips_textured_geometry() -> None:
    scene = _scene()

    result = enhance_scene(
        scene,
        SceneEnhancementConfig(
            postprocess_enabled=True,
            simplification_enabled=True,
            target_faces=1,
        ),
        simplifier=lambda mesh, target: trimesh.creation.icosphere(subdivisions=0),
    )

    reasons = {entry["reason"] for entry in result.skipped}
    assert "TEXTURED_GEOMETRY_PRESERVED" in reasons


def test_scene_enhancement_requires_geometry() -> None:
    with pytest.raises(Exception) as excinfo:
        enhance_scene(trimesh.Scene(), SceneEnhancementConfig(postprocess_enabled=True))
    assert excinfo.value.error_code == "MEMORY_LIMIT_EXCEEDED"


def test_scene_fingerprint_tracks_graph_transforms() -> None:
    scene = _scene()
    first = scene_fingerprint(scene)
    scene.graph.update(
        frame_to="textured",
        matrix=trimesh.transformations.translation_matrix([9.0, 9.0, 9.0]),
    )
    assert scene_fingerprint(scene) != first


def test_enhancement_export_round_trip_is_self_contained(tmp_path: Path) -> None:
    source = textured_glb(tmp_path / "source.glb")
    output = tmp_path / "out.glb"

    validation = repack_scene(
        [source],
        output,
        require_textures=True,
        enhance=lambda scene: (scene, True),
    )

    assert validation.has_texture_coordinates is True
    assert validation.has_embedded_textures is True
    assert validation.has_normals is True
    assert validate_scene_glb(output).sha256 == validation.sha256
    document = validate_scene_glb(output)
    assert document.images_count >= 1


def test_scene_enhancement_checkpoint_invalidation(tmp_path: Path) -> None:
    config = default_config(
        enhancement=SceneEnhancementConfig(
            postprocess_enabled=True,
            target_faces=1000,
            simplification_enabled=True,
        )
    )
    reconstructor = PhotogrammetryReconstructor(config)
    source = textured_glb(tmp_path / "source.glb")
    expected = reconstructor._expected_enhancement_manifest(source)
    assert expected is not None
    manifest_path = tmp_path / "manifest.json"
    metadata_path = tmp_path / "metadata.json"
    metadata_path.write_text("{}", encoding="utf-8")
    from mesh_enhancement import write_enhancement_manifest

    write_enhancement_manifest(manifest_path, expected)
    assert reconstructor._enhancement_cache_matches(manifest_path, metadata_path, expected) is True

    changed = default_config(
        enhancement=SceneEnhancementConfig(
            postprocess_enabled=True,
            target_faces=500,
            simplification_enabled=True,
        )
    )
    other = PhotogrammetryReconstructor(changed)._expected_enhancement_manifest(source)
    assert other != expected
    assert reconstructor._enhancement_cache_matches(manifest_path, metadata_path, other) is False


@pytest.mark.parametrize(
    "kwargs",
    [
        {"target_faces": -1},
        {"simplification_enabled": True, "target_faces": 0},
        {"max_deviation": 0.0},
        {"generate_uv": True},
        {"ai_texture_enabled": True},
        {"device": "cuda:0"},
        {"max_memory_mb": 128},
    ],
)
def test_scene_enhancement_config_rejects_invalid_values(kwargs) -> None:
    with pytest.raises(ValueError):
        SceneEnhancementConfig(**kwargs)


def test_scene_config_disables_enhancement_by_default() -> None:
    config = SceneConfig()
    assert config.enhancement.postprocess_enabled is False
    assert config.enhancement.generate_uv is False
    assert config.enhancement.ai_texture_enabled is False


def test_backend_settings_map_into_the_scene_enhancement_config() -> None:
    from types import SimpleNamespace

    from scene_reconstruction.config import build_config_from_settings

    settings = SimpleNamespace(
        scene_colmap_executable="/usr/local/bin/colmap",
        scene_openmvs_bin_dir="/usr/local/bin/OpenMVS",
        scene_matching_strategy="EXHAUSTIVE",
        scene_colmap_use_gpu=False,
        scene_colmap_max_features=1024,
        scene_colmap_camera_model="SIMPLE_RADIAL",
        scene_max_image_size=1024,
        scene_max_threads=1,
        scene_openmvs_use_cuda=False,
        scene_enable_mesh_refinement=True,
        scene_enable_texture_generation=True,
        scene_min_registered_images=2,
        scene_min_registration_ratio=0.5,
        scene_min_sparse_points=10,
        scene_min_dense_points=10,
        scene_max_task_seconds=60,
        scene_work_dir="/tmp/scene",
        scene_colmap_timeout_seconds=60,
        scene_openmvs_timeout_seconds=60,
        scene_export_timeout_seconds=60,
        scene_feature_backend="COLMAP_SIFT",
        scene_feature_profile="sift_default",
        scene_feature_fallback_to_sift=True,
        scene_feature_max_keypoints=512,
        scene_feature_image_max_size=512,
        scene_feature_pair_strategy="EXHAUSTIVE",
        scene_feature_sequential_overlap=3,
        scene_feature_min_matches=20,
        scene_feature_match_threshold=0.2,
        scene_feature_device="cpu",
        scene_feature_max_vram_mb=1024,
        scene_feature_max_pairs=100,
        scene_mesh_postprocess_enabled=True,
        scene_mesh_cleanup_enabled=False,
        scene_normals_enabled=False,
        scene_mesh_simplification_enabled=True,
        scene_mesh_target_faces=1000,
        scene_mesh_max_deviation=0.02,
        scene_generate_uv=False,
        scene_ai_texture_enabled=False,
        enhancement_fallback_to_original=False,
        mesh_enhancement_max_memory_mb=1024,
        texture_enhancement_device="cpu",
    )

    config = build_config_from_settings(settings)

    assert config.enhancement.postprocess_enabled is True
    assert config.enhancement.cleanup_enabled is False
    assert config.enhancement.normals_enabled is False
    assert config.enhancement.simplification_enabled is True
    assert config.enhancement.target_faces == 1000
    assert config.enhancement.max_deviation == 0.02
    assert config.enhancement.fallback_to_original is False
    assert config.enhancement.max_memory_mb == 1024
