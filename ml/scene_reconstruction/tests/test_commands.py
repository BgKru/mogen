"""COLMAP/OpenMVS command construction (07 Sections 6-11, 14)."""

from __future__ import annotations

from pathlib import Path

from scene_reconstruction.colmap_runner import (
    feature_extraction_command,
    feature_matching_command,
    image_undistorter_command,
    mapper_command,
    model_converter_command,
)
from scene_reconstruction.openmvs_runner import (
    densify_command,
    interface_colmap_command,
    reconstruct_mesh_command,
    refine_mesh_command,
    texture_mesh_command,
    transform_scene_command,
)

from .helpers import default_config


def test_feature_extraction_command_uses_validated_options():
    config = default_config(colmap_use_gpu=True, colmap_max_features=1234, max_threads=6)
    command = feature_extraction_command(
        config, images_dir=Path("/work/images"), database_path=Path("/work/colmap/database.db")
    )
    assert command[0] == "/usr/local/bin/colmap"
    assert command[1] == "feature_extractor"
    assert command[command.index("--database_path") + 1] == "/work/colmap/database.db"
    assert command[command.index("--image_path") + 1] == "/work/images"
    assert command[command.index("--SiftExtraction.max_num_features") + 1] == "1234"
    assert command[command.index("--FeatureExtraction.use_gpu") + 1] == "1"
    assert command[command.index("--FeatureExtraction.num_threads") + 1] == "6"
    assert command[command.index("--ImageReader.single_camera") + 1] == "0"


def test_matching_command_switches_strategy():
    config = default_config(matching_strategy="EXHAUSTIVE", colmap_use_gpu=False)
    assert feature_matching_command(config, database_path=Path("/db"))[1] == "exhaustive_matcher"
    sequential = default_config(matching_strategy="SEQUENTIAL")
    assert (
        feature_matching_command(sequential, database_path=Path("/db"))[1] == "sequential_matcher"
    )
    command = feature_matching_command(config, database_path=Path("/db"))
    assert command[command.index("--FeatureMatching.use_gpu") + 1] == "0"


def test_mapper_and_undistorter_commands():
    config = default_config(max_threads=3)
    mapper = mapper_command(
        config,
        images_dir=Path("/work/images"),
        database_path=Path("/work/colmap/database.db"),
        sparse_dir=Path("/work/colmap/sparse"),
    )
    assert mapper[1] == "mapper"
    assert mapper[mapper.index("--output_path") + 1] == "/work/colmap/sparse"
    assert mapper[mapper.index("--Mapper.num_threads") + 1] == "3"

    undistorter = image_undistorter_command(
        config,
        images_dir=Path("/work/images"),
        model_dir=Path("/work/colmap/sparse/1"),
        dense_dir=Path("/work/colmap/dense"),
    )
    assert undistorter[1] == "image_undistorter"
    assert undistorter[undistorter.index("--input_path") + 1] == "/work/colmap/sparse/1"
    assert undistorter[undistorter.index("--max_image_size") + 1] == "2000"
    assert undistorter[undistorter.index("--output_type") + 1] == "COLMAP"


def test_model_converter_command_writes_text():
    command = model_converter_command(
        default_config(), model_dir=Path("/sparse/0"), output_dir=Path("/sparse-txt/0")
    )
    assert command[1] == "model_converter"
    assert command[command.index("--output_type") + 1] == "TXT"


def test_openmvs_command_sequence_matches_the_documented_pipeline():
    config = default_config(max_threads=2)
    interface = interface_colmap_command(
        config, dense_dir=Path("/work/colmap/dense"), scene_file=Path("/work/openmvs/scene.mvs")
    )
    assert interface[0].endswith("InterfaceCOLMAP")
    assert interface[interface.index("--image-folder") + 1] == "/work/colmap/dense/images"

    densify = densify_command(config, scene_file=Path("/work/openmvs/scene.mvs"))
    assert densify[0].endswith("DensifyPointCloud")

    mesh = reconstruct_mesh_command(
        config, dense_scene=Path("/work/openmvs/scene_dense.mvs"), mesh_path=Path("/work/mesh.ply")
    )
    assert mesh[mesh.index("-p") + 1] == "/work/mesh.ply"

    refine = refine_mesh_command(
        config,
        dense_scene=Path("/work/openmvs/scene_dense.mvs"),
        mesh_path=Path("/work/mesh.ply"),
        refined_mesh=Path("/work/refined.ply"),
    )
    assert refine[1:].index("--scales") >= 0
    assert refine[refine.index("--max-face-area") + 1] == "16"

    texture = texture_mesh_command(
        config,
        dense_scene=Path("/work/openmvs/scene_dense.mvs"),
        mesh_path=Path("/work/refined.ply"),
        textured_mesh=Path("/work/textured.ply"),
    )
    assert texture[texture.index("-m") + 1] == "/work/refined.ply"


def test_transform_scene_exports_with_normalization_and_type():
    command = transform_scene_command(
        default_config(),
        scene_file=Path("/work/textured.mvs"),
        output_base=Path("/out/scene"),
        export_type="glb",
    )
    assert command[0].endswith("TransformScene")
    assert command[command.index("--normalize-coordinates") + 1] == "2"
    assert command[command.index("--export-type") + 1] == "glb"


def test_transform_scene_can_attach_a_mesh():
    command = transform_scene_command(
        default_config(),
        scene_file=Path("/work/scene_dense.mvs"),
        output_base=Path("/out/scene"),
        export_type="obj",
        mesh_file=Path("/work/mesh.ply"),
    )
    assert command[command.index("-m") + 1] == "/work/mesh.ply"


def test_commands_never_use_a_shell_string():
    command = feature_extraction_command(
        default_config(), images_dir=Path("/work/images with space"), database_path=Path("/db")
    )
    assert all(isinstance(part, str) for part in command)
    assert command[command.index("--image_path") + 1] == "/work/images with space"
