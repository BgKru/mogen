"""Unit tests for the optional Gaussian-splat representation (increment 15).

Covers the COLMAP model reader, the Nerfstudio dataset adapter (including the
camera-convention/projection self-check), the independent Gaussian PLY
validator, the checkpoint exporter, checkpoint manifest reuse, VRAM admission,
routing through the pipeline and the controlled Nerfstudio runner.

No Nerfstudio or training is required: the real training path is an opt-in test
(`test_real_splat.py`). Traceability: I15-AC-03..I15-AC-09, I15-AC-12, I15-AC-13.
"""

from __future__ import annotations

import hashlib
import math
import struct
import uuid
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from scene_reconstruction import neural_pipeline as neural
from scene_reconstruction.colmap_model import (
    MODEL_BY_NAME,
    ColmapCamera,
    ColmapImage,
    ColmapPoint,
    qvec_to_rotmat,
    read_colmap_model,
)
from scene_reconstruction.config import (
    STAGE_SPLAT_DATASET_PREPARATION,
    STAGE_SPLAT_EXPORT,
    STAGE_SPLAT_TRAINING,
    SceneConfig,
    build_config_from_settings,
)
from scene_reconstruction.dataset import PreparedImage, SceneDataset
from scene_reconstruction.exceptions import SplatError
from scene_reconstruction.nerfstudio_dataset import build_nerfstudio_dataset, colmap_camera_to_world
from scene_reconstruction.nerfstudio_runner import NerfstudioRunner
from scene_reconstruction.runner import CommandOutcome
from scene_reconstruction.splat_config import (
    SPLAT_FORMAT,
    SplatConfig,
    splat_ply_properties,
)
from scene_reconstruction.splat_exporter import export_splat_ply
from scene_reconstruction.splat_validator import (
    read_splat_ply_header,
    validate_splat_ply,
    write_splat_ply,
    write_test_splat_ply,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# synthetic COLMAP models
# ---------------------------------------------------------------------------


def _rotmat_to_qvec(rotation: np.ndarray) -> tuple[float, float, float, float]:
    trace = float(rotation[0, 0] + rotation[1, 1] + rotation[2, 2])
    if trace > 0:
        scale = math.sqrt(trace + 1.0) * 2.0
        w = 0.25 * scale
        x = (rotation[2, 1] - rotation[1, 2]) / scale
        y = (rotation[0, 2] - rotation[2, 0]) / scale
        z = (rotation[1, 0] - rotation[0, 1]) / scale
    elif rotation[0, 0] > rotation[1, 1] and rotation[0, 0] > rotation[2, 2]:
        scale = math.sqrt(1.0 + rotation[0, 0] - rotation[1, 1] - rotation[2, 2]) * 2.0
        w = (rotation[2, 1] - rotation[1, 2]) / scale
        x = 0.25 * scale
        y = (rotation[0, 1] + rotation[1, 0]) / scale
        z = (rotation[0, 2] + rotation[2, 0]) / scale
    elif rotation[1, 1] > rotation[2, 2]:
        scale = math.sqrt(1.0 + rotation[1, 1] - rotation[0, 0] - rotation[2, 2]) * 2.0
        w = (rotation[0, 2] - rotation[2, 0]) / scale
        x = (rotation[0, 1] + rotation[1, 0]) / scale
        y = 0.25 * scale
        z = (rotation[1, 2] + rotation[2, 1]) / scale
    else:
        scale = math.sqrt(1.0 + rotation[2, 2] - rotation[0, 0] - rotation[1, 1]) * 2.0
        w = (rotation[1, 0] - rotation[0, 1]) / scale
        x = (rotation[0, 2] + rotation[2, 0]) / scale
        y = (rotation[1, 2] + rotation[2, 1]) / scale
        z = 0.25 * scale
    norm = math.sqrt(w * w + x * x + y * y + z * z)
    return (w / norm, x / norm, y / norm, z / norm)


def _look_at(centre: np.ndarray, target: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(c2w rotation, w2c)`` for a camera looking from centre to target.

    The synthetic world uses ``-Y`` as physical up (the usual COLMAP world), so
    the Nerfstudio z-up conversion has something physically meaningful to check.
    The camera frame is an orthonormal OpenCV frame: x right, y down, z forward.
    """
    forward = target - centre
    forward = forward / np.linalg.norm(forward)
    world_up = np.array([0.0, -1.0, 0.0])
    up = world_up - forward * float(np.dot(forward, world_up))
    norm = np.linalg.norm(up)
    up = np.array([1.0, 0.0, 0.0]) if norm < 1e-8 else up / norm
    down = -up
    right = np.cross(down, forward)
    right = right / np.linalg.norm(right)
    down = np.cross(forward, right)
    rotation = np.stack([right, down, forward], axis=1)
    world_to_camera = np.eye(4)
    world_to_camera[:3, :3] = rotation.T
    world_to_camera[:3, 3] = -rotation.T @ centre
    return rotation, world_to_camera


def _synthetic_model(
    *,
    count: int = 6,
    width: int = 320,
    height: int = 240,
    radius: float = 3.0,
    height_y: float = -1.0,
    look_away: bool = False,
    candidates: int = 240,
    seed: int = 11,
    camera_model: str = "PINHOLE",
) -> tuple[dict[int, ColmapCamera], dict[int, ColmapImage], dict[int, ColmapPoint]]:
    rng = np.random.default_rng(seed)
    points_xyz = rng.uniform(-1.2, 1.2, size=(candidates, 3))
    points = {
        index + 1: ColmapPoint(
            point3d_id=index + 1,
            xyz=tuple(float(value) for value in xyz),
            rgb=(120, 130, 140),
            error=0.1,
        )
        for index, xyz in enumerate(points_xyz)
    }
    cameras: dict[int, ColmapCamera] = {}
    images: dict[int, ColmapImage] = {}
    fx = fy = 260.0
    cx, cy = width / 2.0, height / 2.0
    tracks: dict[int, list[tuple[int, int]]] = {pid: [] for pid in points}
    for index in range(count):
        angle = 2.0 * math.pi * index / count
        centre = np.array([radius * math.cos(angle), height_y, radius * math.sin(angle)])
        target = np.array([0.0, 0.0, 0.0])
        if look_away:
            target = centre * 2.0
        rotation, world_to_camera = _look_at(centre, target)
        camera_id = index + 1
        if camera_model == "PINHOLE":
            params: tuple[float, ...] = (fx, fy, cx, cy)
        elif camera_model == "SIMPLE_RADIAL":
            params = (fx, cx, cy, 0.0)
        else:  # pragma: no cover - only the two models above are used
            raise ValueError(f"unsupported synthetic camera model {camera_model}")
        camera = ColmapCamera(
            camera_id=camera_id,
            model=camera_model,
            width=width,
            height=height,
            params=params,
        )
        cameras[camera_id] = camera
        observations: list[tuple[float, float, int]] = []
        for point_id, point in points.items():
            xyz = np.asarray(point.xyz)
            camera_point = rotation.T @ xyz + world_to_camera[:3, 3]
            if camera_point[2] <= 0.2:
                continue
            u = fx * camera_point[0] / camera_point[2] + cx
            v = fy * camera_point[1] / camera_point[2] + cy
            if 0.0 <= u < width and 0.0 <= v < height:
                observations.append((u, v, point_id))
                tracks[point_id].append((camera_id, len(observations) - 1))
        images[camera_id] = ColmapImage(
            image_id=camera_id,
            name=f"image_{index + 1:03d}.jpg",
            camera_id=camera_id,
            # COLMAP stores the world-to-camera rotation and translation.
            qvec=_rotmat_to_qvec(rotation.T),
            tvec=tuple(float(value) for value in world_to_camera[:3, 3]),
            xys=np.asarray([(u, v) for u, v, _ in observations], dtype=np.float64).reshape(-1, 2),
            point3d_ids=np.asarray([pid for _, _, pid in observations], dtype=np.int64),
        )
    return cameras, images, points


def _camera_model_id(name: str) -> int:
    return MODEL_BY_NAME[name]


def write_colmap_binary_model(
    root: Path,
    cameras: dict[int, ColmapCamera],
    images: dict[int, ColmapImage],
    points: dict[int, ColmapPoint],
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    with (root / "cameras.bin").open("wb") as handle:
        handle.write(struct.pack("<Q", len(cameras)))
        for camera in cameras.values():
            handle.write(struct.pack("<ii", camera.camera_id, _camera_model_id(camera.model)))
            handle.write(struct.pack("<QQ", camera.width, camera.height))
            for value in camera.params:
                handle.write(struct.pack("<d", value))
    observations: dict[int, list[tuple[int, int]]] = {pid: [] for pid in points}
    with (root / "images.bin").open("wb") as handle:
        handle.write(struct.pack("<Q", len(images)))
        for image in images.values():
            handle.write(struct.pack("<i", image.image_id))
            for value in image.qvec:
                handle.write(struct.pack("<d", value))
            for value in image.tvec:
                handle.write(struct.pack("<d", value))
            handle.write(struct.pack("<i", image.camera_id))
            handle.write(image.name.encode("utf-8") + b"\x00")
            handle.write(struct.pack("<Q", image.xys.shape[0]))
            for index in range(image.xys.shape[0]):
                handle.write(struct.pack("<dd", image.xys[index, 0], image.xys[index, 1]))
                point_id = int(image.point3d_ids[index])
                handle.write(struct.pack("<Q", point_id))
                if point_id in observations:
                    observations[point_id].append((image.image_id, index))
    with (root / "points3D.bin").open("wb") as handle:
        handle.write(struct.pack("<Q", len(points)))
        for point in points.values():
            handle.write(struct.pack("<Q", point.point3d_id))
            for value in point.xyz:
                handle.write(struct.pack("<d", value))
            handle.write(bytes(point.rgb))
            handle.write(struct.pack("<d", point.error))
            track = observations.get(point.point3d_id, [])
            handle.write(struct.pack("<Q", len(track)))
            for image_id, index in track:
                handle.write(struct.pack("<ii", image_id, index))


def write_colmap_text_model(
    root: Path,
    cameras: dict[int, ColmapCamera],
    images: dict[int, ColmapImage],
    points: dict[int, ColmapPoint],
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    lines = ["# cameras"]
    for camera in cameras.values():
        params = " ".join(str(value) for value in camera.params)
        lines.append(f"{camera.camera_id} {camera.model} {camera.width} {camera.height} {params}")
    (root / "cameras.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    lines = ["# images"]
    for image in images.values():
        pose = " ".join(str(value) for value in (*image.qvec, *image.tvec))
        lines.append(f"{image.image_id} {pose} {image.camera_id} {image.name}")
        observations = " ".join(
            f"{image.xys[index, 0]} {image.xys[index, 1]} {int(image.point3d_ids[index])}"
            for index in range(image.xys.shape[0])
        )
        lines.append(observations)
    (root / "images.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    lines = ["# points"]
    for point in points.values():
        xyz = " ".join(str(value) for value in point.xyz)
        lines.append(
            f"{point.point3d_id} {xyz} {point.rgb[0]} {point.rgb[1]} {point.rgb[2]} {point.error}"
        )
    (root / "points3D.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _make_dataset(
    root: Path,
    names: list[str],
    *,
    size: tuple[int, int] = (320, 240),
) -> SceneDataset:
    source_dir = root / "source_images"
    source_dir.mkdir(parents=True, exist_ok=True)
    prepared: list[PreparedImage] = []
    for index, name in enumerate(names, start=1):
        path = source_dir / name
        Image.new("RGB", size, color=(index * 10 % 255, 40, 80)).save(path, format="JPEG")
        content = path.read_bytes()
        prepared.append(
            PreparedImage(
                path=path,
                filename=name,
                original_filename=name,
                image_id=str(uuid.uuid4()),
                sha256=hashlib.sha256(content).hexdigest(),
                size_bytes=len(content),
                format="JPEG",
                width=size[0],
                height=size[1],
            )
        )
    return SceneDataset(work_dir=root, images_dir=source_dir, images=tuple(prepared))


def _files_for(cameras, images, root: Path) -> Path:
    """Write the image files matching the model's names into ``root``."""
    root.mkdir(parents=True, exist_ok=True)
    for image in images.values():
        Image.new("RGB", (cameras[image.camera_id].width, cameras[image.camera_id].height)).save(
            root / image.name, format="JPEG"
        )
    return root


def _splat_config(**overrides: object) -> SplatConfig:
    values: dict[str, object] = {
        "enabled": True,
        "min_registered_images": 3,
        "max_image_dimension": 512,
        "max_iterations": 100,
        "checkpoint_interval": 100,
        "sh_degree": 3,
    }
    values.update(overrides)
    return SplatConfig(**values)


def _converted_dataset(tmp_path: Path, **model_overrides: object):
    cameras, images, points = _synthetic_model(**model_overrides)
    model_dir = tmp_path / "colmap_dense" / "sparse"
    write_colmap_binary_model(model_dir, cameras, images, points)
    dense_images = _files_for(cameras, images, tmp_path / "colmap_dense" / "images")
    dataset = _make_dataset(tmp_path, [image.name for image in images.values()])
    converted = build_nerfstudio_dataset(
        dataset,
        model_dir=model_dir,
        images_dir=dense_images,
        output_dir=tmp_path / "splat" / "dataset",
        splat=_splat_config(),
        min_sparse_points=10,
    )
    return dataset, converted, cameras, images, points


# ---------------------------------------------------------------------------
# COLMAP model reader
# ---------------------------------------------------------------------------


def test_the_binary_model_round_trips(tmp_path: Path) -> None:
    cameras, images, points = _synthetic_model(count=4)
    root = tmp_path / "sparse"
    write_colmap_binary_model(root, cameras, images, points)

    parsed = read_colmap_model(root)

    assert parsed.as_metadata()["cameras"] == 4
    assert parsed.as_metadata()["images"] == 4
    assert parsed.as_metadata()["points"] == len(points)
    first = parsed.images[1]
    assert first.name == "image_001.jpg"
    assert np.allclose(qvec_to_rotmat(*first.qvec), images[1].rotation_matrix())
    assert parsed.points[1].xyz == pytest.approx(points[1].xyz)
    assert parsed.points[1].rgb == points[1].rgb


def test_the_text_model_round_trips(tmp_path: Path) -> None:
    cameras, images, points = _synthetic_model(count=3)
    root = tmp_path / "sparse"
    write_colmap_text_model(root, cameras, images, points)

    parsed = read_colmap_model(root)

    assert len(parsed.images) == 3
    assert parsed.images[2].xys.shape == images[2].xys.shape
    assert np.allclose(parsed.images[2].xys, images[2].xys)
    assert parsed.cameras[1].model == "PINHOLE"


def test_a_missing_model_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(SplatError, match="sparse model"):
        read_colmap_model(tmp_path / "missing")


def test_a_truncated_model_is_rejected(tmp_path: Path) -> None:
    cameras, images, points = _synthetic_model(count=2)
    root = tmp_path / "sparse"
    write_colmap_binary_model(root, cameras, images, points)
    data = (root / "images.bin").read_bytes()
    (root / "images.bin").write_bytes(data[: len(data) // 2])

    with pytest.raises(SplatError):
        read_colmap_model(root)


# ---------------------------------------------------------------------------
# Nerfstudio dataset conversion
# ---------------------------------------------------------------------------


def test_the_dataset_conversion_preserves_identity_intrinsics_and_poses(
    tmp_path: Path,
) -> None:
    dataset, converted, cameras, images, points = _converted_dataset(tmp_path)

    assert converted.registered_images == len(images)
    assert converted.camera_models == ("PINHOLE",)
    assert converted.convention.ok
    assert converted.convention.reprojection_median_px < 1.0
    assert converted.convention.roundtrip_error < 1e-6
    assert converted.convention.forward_axis_ok and converted.convention.up_axis_ok
    assert converted.sparse_points == len(points)

    import json

    transforms = json.loads(converted.transforms_path.read_text(encoding="utf-8"))
    assert transforms["camera_model"] == "OPENCV"
    assert transforms["ply_file_path"] == "sparse_pc.ply"
    assert len(transforms["frames"]) == len(images)
    frame = transforms["frames"][0]
    assert frame["file_path"].startswith("images/")
    assert frame["w"] == 320 and frame["h"] == 240
    assert frame["fl_x"] == pytest.approx(260.0)
    assert frame["k1"] == 0.0
    assert (converted.images_dir / "image_001.jpg").is_file()
    assert converted.points_path.is_file()

    manifest = json.loads(converted.manifest_path.read_text(encoding="utf-8"))
    source = manifest["images"][0]
    assert source["source_sha256"] == dataset.images[0].sha256
    assert (
        source["training_sha256"]
        == hashlib.sha256((converted.images_dir / "image_001.jpg").read_bytes()).hexdigest()
    )


def test_a_resized_dataset_scales_intrinsics_consistently(tmp_path: Path) -> None:
    cameras, images, points = _synthetic_model(count=4, width=640, height=480)
    model_dir = tmp_path / "sparse"
    write_colmap_binary_model(model_dir, cameras, images, points)
    dense_images = _files_for(cameras, images, tmp_path / "dense")
    dataset = _make_dataset(tmp_path, [image.name for image in images.values()], size=(640, 480))

    converted = build_nerfstudio_dataset(
        dataset,
        model_dir=model_dir,
        images_dir=dense_images,
        output_dir=tmp_path / "out",
        splat=_splat_config(image_scale=0.5, max_image_dimension=4096),
        min_sparse_points=10,
    )

    import json

    frame = json.loads(converted.transforms_path.read_text(encoding="utf-8"))["frames"][0]
    assert frame["w"] == 320 and frame["h"] == 240
    assert frame["fl_x"] == pytest.approx(130.0)
    assert frame["cx"] == pytest.approx(160.0)
    assert converted.convention.ok


def test_max_image_dimension_bounds_the_training_image(tmp_path: Path) -> None:
    cameras, images, points = _synthetic_model(count=4, width=800, height=600)
    model_dir = tmp_path / "sparse"
    write_colmap_binary_model(model_dir, cameras, images, points)
    dense_images = _files_for(cameras, images, tmp_path / "dense")
    dataset = _make_dataset(tmp_path, [image.name for image in images.values()], size=(800, 600))

    converted = build_nerfstudio_dataset(
        dataset,
        model_dir=model_dir,
        images_dir=dense_images,
        output_dir=tmp_path / "out",
        splat=_splat_config(max_image_dimension=400),
        min_sparse_points=10,
    )

    import json

    frame = json.loads(converted.transforms_path.read_text(encoding="utf-8"))["frames"][0]
    assert max(frame["w"], frame["h"]) == 400
    assert converted.convention.ok


def test_too_few_registered_images_fail_before_training(tmp_path: Path) -> None:
    cameras, images, points = _synthetic_model(count=3)
    model_dir = tmp_path / "sparse"
    write_colmap_binary_model(model_dir, cameras, images, points)
    dense_images = _files_for(cameras, images, tmp_path / "dense")
    dataset = _make_dataset(tmp_path, [image.name for image in images.values()])
    splat = _splat_config(min_registered_images=8)

    with pytest.raises(SplatError) as error:
        build_nerfstudio_dataset(
            dataset,
            model_dir=model_dir,
            images_dir=dense_images,
            output_dir=tmp_path / "out",
            splat=splat,
            min_sparse_points=10,
        )
    assert error.value.error_code == "SPLAT_INSUFFICIENT_IMAGES"


def test_too_few_sparse_points_fail_before_training(tmp_path: Path) -> None:
    cameras, images, points = _synthetic_model(count=4)
    # Keep only two points; the observations of the removed ids are ignored.
    keep = dict(list(points.items())[:2])
    model_dir = tmp_path / "sparse"
    write_colmap_binary_model(model_dir, cameras, images, keep)
    dense_images = _files_for(cameras, images, tmp_path / "dense")
    dataset = _make_dataset(tmp_path, [image.name for image in images.values()])

    with pytest.raises(SplatError) as error:
        build_nerfstudio_dataset(
            dataset,
            model_dir=model_dir,
            images_dir=dense_images,
            output_dir=tmp_path / "out",
            splat=_splat_config(),
            min_sparse_points=100,
        )
    assert error.value.error_code == "SPLAT_INSUFFICIENT_POINTS"


def test_a_distorted_camera_model_is_rejected(tmp_path: Path) -> None:
    cameras, images, points = _synthetic_model(count=4, camera_model="SIMPLE_RADIAL")
    model_dir = tmp_path / "sparse"
    write_colmap_binary_model(model_dir, cameras, images, points)
    dense_images = _files_for(cameras, images, tmp_path / "dense")
    dataset = _make_dataset(tmp_path, [image.name for image in images.values()])

    with pytest.raises(SplatError) as error:
        build_nerfstudio_dataset(
            dataset,
            model_dir=model_dir,
            images_dir=dense_images,
            output_dir=tmp_path / "out",
            splat=_splat_config(),
            min_sparse_points=10,
        )
    assert error.value.error_code == "SPLAT_INVALID_CAMERAS"


def test_a_missing_training_image_is_rejected(tmp_path: Path) -> None:
    cameras, images, points = _synthetic_model(count=4)
    model_dir = tmp_path / "sparse"
    write_colmap_binary_model(model_dir, cameras, images, points)
    dense_images = _files_for(cameras, images, tmp_path / "dense")
    (dense_images / "image_002.jpg").unlink()
    dataset = _make_dataset(tmp_path, [image.name for image in images.values()])

    with pytest.raises(SplatError) as error:
        build_nerfstudio_dataset(
            dataset,
            model_dir=model_dir,
            images_dir=dense_images,
            output_dir=tmp_path / "out",
            splat=_splat_config(),
            min_sparse_points=10,
        )
    assert error.value.error_code == "SPLAT_DATASET_CONVERSION_FAILED"


def test_an_image_outside_the_prepared_dataset_is_rejected(tmp_path: Path) -> None:
    cameras, images, points = _synthetic_model(count=4)
    model_dir = tmp_path / "sparse"
    write_colmap_binary_model(model_dir, cameras, images, points)
    dense_images = _files_for(cameras, images, tmp_path / "dense")
    dataset = _make_dataset(tmp_path, ["other_001.jpg", "other_002.jpg"])

    with pytest.raises(SplatError) as error:
        build_nerfstudio_dataset(
            dataset,
            model_dir=model_dir,
            images_dir=dense_images,
            output_dir=tmp_path / "out",
            splat=_splat_config(),
            min_sparse_points=10,
        )
    assert error.value.error_code == "SPLAT_DATASET_CONVERSION_FAILED"


def test_cameras_looking_away_fail_the_convention_check(tmp_path: Path) -> None:
    cameras, images, points = _synthetic_model(count=4, look_away=True)
    model_dir = tmp_path / "sparse"
    write_colmap_binary_model(model_dir, cameras, images, points)
    dense_images = _files_for(cameras, images, tmp_path / "dense")
    dataset = _make_dataset(tmp_path, [image.name for image in images.values()])

    with pytest.raises(SplatError) as error:
        build_nerfstudio_dataset(
            dataset,
            model_dir=model_dir,
            images_dir=dense_images,
            output_dir=tmp_path / "out",
            splat=_splat_config(),
            min_sparse_points=10,
        )
    assert error.value.error_code == "SPLAT_INVALID_CAMERAS"


def test_the_camera_to_world_conversion_matches_the_upstream_formula() -> None:
    _, images, _ = _synthetic_model(count=2)
    image = images[1]

    c2w = colmap_camera_to_world(image)

    # The camera centre survives the transform; the rotation stays proper.
    centre = image.camera_to_world()[:3, 3]
    np.testing.assert_allclose(c2w[:3, 3], centre[[0, 2, 1]] * np.array([1.0, 1.0, -1.0]))
    assert np.linalg.det(c2w[:3, :3]) == pytest.approx(1.0)
    # OpenGL convention: the camera looks along its local -Z axis.
    forward = -c2w[:3, 2]
    expected = np.array([0.0, 0.0, 0.0]) - image.camera_to_world()[:3, 3]
    assert float(np.dot(forward, expected)) > 0


# ---------------------------------------------------------------------------
# Gaussian PLY validation and export
# ---------------------------------------------------------------------------


def test_a_valid_gaussian_ply_passes_independent_validation(tmp_path: Path) -> None:
    path = tmp_path / "splat.ply"
    count = write_test_splat_ply(path, count=48)

    validation = validate_splat_ply(path, sh_degree=3)

    assert validation.gaussian_count == count
    assert validation.sh_degree == 3
    assert validation.properties == splat_ply_properties(3)
    metadata = validation.as_metadata()
    assert metadata["schema"] == "nerfstudio_gaussian_splat_v1"
    assert metadata["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert "path" not in metadata
    assert read_splat_ply_header(path).vertex_count == count


def test_a_wrong_property_set_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "bad.ply"
    properties = splat_ply_properties(3)
    values = {
        name: np.zeros(4, dtype=np.float32) + (1.0 if name.startswith("rot") else 0.0)
        for name in properties
    }
    write_splat_ply(path, properties=properties, values=values)
    text = path.read_bytes().replace(b"property float f_rest_0\n", b"property double f_rest_0\n")
    path.write_bytes(text)

    with pytest.raises(SplatError) as error:
        validate_splat_ply(path)
    assert error.value.error_code == "SPLAT_PLY_INVALID"


def test_a_truncated_ply_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "splat.ply"
    write_test_splat_ply(path, count=16)
    data = path.read_bytes()
    path.write_bytes(data[:-16])

    with pytest.raises(SplatError):
        validate_splat_ply(path)


def test_non_finite_values_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "nan.ply"
    write_test_splat_ply(path, count=8)
    data = bytearray(path.read_bytes())
    header = data.find(b"end_header\n") + len(b"end_header\n")
    struct.pack_into("<f", data, header, float("nan"))
    path.write_bytes(bytes(data))

    with pytest.raises(SplatError, match="non-finite"):
        validate_splat_ply(path)


def test_an_ascii_or_big_endian_ply_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "ascii.ply"
    path.write_text(
        "ply\nformat ascii 1.0\nelement vertex 1\nend_header\n0 0 0\n", encoding="utf-8"
    )

    with pytest.raises(SplatError, match="little-endian"):
        validate_splat_ply(path)


def test_the_artifact_size_limit_is_enforced(tmp_path: Path) -> None:
    path = tmp_path / "splat.ply"
    write_test_splat_ply(path, count=32)

    with pytest.raises(SplatError) as error:
        validate_splat_ply(path, max_artifact_bytes=128)
    assert error.value.error_code == "SPLAT_ARTIFACT_TOO_LARGE"


def test_the_expected_sh_degree_is_enforced(tmp_path: Path) -> None:
    path = tmp_path / "splat.ply"
    write_test_splat_ply(path, count=8, sh_degree=0)

    with pytest.raises(SplatError, match="SH degree"):
        validate_splat_ply(path, sh_degree=3)


def test_small_unnormalized_quaternions_are_accepted(tmp_path: Path) -> None:
    """Splatfacto stores unnormalized quaternions; only zero is invalid."""
    properties = splat_ply_properties(3)
    count = 4
    values = {name: np.zeros(count, dtype=np.float32) for name in properties}
    for index in range(4):
        values[f"rot_{index}"] = np.full(count, 1.0e-4, dtype=np.float32)
    for index in range(3):
        values[f"scale_{index}"] = np.full(count, -2.0, dtype=np.float32)
    values["opacity"] = np.full(count, 2.0, dtype=np.float32)
    path = tmp_path / "small-quat.ply"
    write_splat_ply(path, properties=properties, values=values)

    validation = validate_splat_ply(path, sh_degree=3)
    assert validation.quaternion_norm_min > 0

    zero = {name: np.array(value, copy=True) for name, value in values.items()}
    for index in range(4):
        zero[f"rot_{index}"] = np.zeros(count, dtype=np.float32)
    zero_path = tmp_path / "zero-quat.ply"
    write_splat_ply(zero_path, properties=properties, values=zero)
    with pytest.raises(SplatError, match="rotation quaternions"):
        validate_splat_ply(zero_path, sh_degree=3)


def _synthetic_checkpoint(tmp_path: Path, *, count: int = 12, sh_degree: int = 3) -> Path:
    import torch

    rng = np.random.default_rng(3)
    means = torch.tensor(rng.normal(size=(count, 3)), dtype=torch.float32)
    scales = torch.tensor(rng.normal(-2.0, 0.2, size=(count, 3)), dtype=torch.float32)
    quats = torch.tensor(rng.normal(size=(count, 4)), dtype=torch.float32)
    quats = quats / quats.norm(dim=1, keepdim=True)
    opacities = torch.tensor(rng.normal(2.0, 0.4, size=(count, 1)), dtype=torch.float32)
    features_dc = torch.tensor(rng.normal(size=(count, 3)), dtype=torch.float32)
    rest = {0: 0, 1: 9, 2: 24, 3: 45}[sh_degree]
    features_rest = torch.tensor(
        rng.normal(scale=0.05, size=(count, max(1, rest // 3) if rest else 0, 3)),
        dtype=torch.float32,
    )
    if rest == 0:
        features_rest = torch.zeros((count, 0, 3), dtype=torch.float32)
    pipeline = {
        "model.means": means,
        "model.scales": scales,
        "model.quats": quats,
        "model.opacities": opacities,
        "model.features_dc": features_dc,
        "model.features_rest": features_rest,
    }
    path = tmp_path / "step-000000100.ckpt"
    torch.save(
        {"step": 100, "pipeline": pipeline, "optimizers": {}, "schedulers": {}, "scalers": {}}, path
    )
    return path


def test_the_exporter_writes_the_pinned_nerfstudio_schema(tmp_path: Path) -> None:
    checkpoint = _synthetic_checkpoint(tmp_path, count=12)
    output = tmp_path / "out" / "scene.ply"

    result = export_splat_ply(checkpoint, output, sh_degree=3, max_artifact_bytes=1 << 20)

    assert result.path == output
    assert result.gaussian_count == 12
    assert result.training_step == 100
    assert result.sha256 == hashlib.sha256(output.read_bytes()).hexdigest()
    header = read_splat_ply_header(output)
    assert header.properties == splat_ply_properties(3)
    validation = validate_splat_ply(output, sh_degree=3)
    assert validation.gaussian_count == 12
    # No temporary file is left behind.
    assert list(output.parent.glob("*.tmp")) == []


def test_the_exporter_filters_low_opacity_and_non_finite_gaussians(tmp_path: Path) -> None:
    import torch

    checkpoint = _synthetic_checkpoint(tmp_path, count=10)
    state = torch.load(checkpoint, weights_only=True)
    state["pipeline"]["model.opacities"][0] = -20.0  # below logit(1/255)
    state["pipeline"]["model.means"][1, 0] = float("nan")
    torch.save(state, checkpoint)

    result = export_splat_ply(checkpoint, tmp_path / "scene.ply")

    assert result.gaussian_count_before_filter == 10
    assert result.gaussian_count == 8


def test_a_missing_or_corrupt_checkpoint_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(SplatError) as missing:
        export_splat_ply(tmp_path / "missing.ckpt", tmp_path / "out.ply")
    assert missing.value.error_code == "SPLAT_CHECKPOINT_INVALID"

    corrupt = tmp_path / "corrupt.ckpt"
    corrupt.write_bytes(b"not a checkpoint")
    with pytest.raises(SplatError) as error:
        export_splat_ply(corrupt, tmp_path / "out.ply")
    assert error.value.error_code == "SPLAT_CHECKPOINT_INVALID"


def test_a_checkpoint_with_the_wrong_sh_layout_is_rejected(tmp_path: Path) -> None:
    checkpoint = _synthetic_checkpoint(tmp_path, count=6, sh_degree=3)

    with pytest.raises(SplatError) as error:
        export_splat_ply(checkpoint, tmp_path / "out.ply", sh_degree=0)
    assert error.value.error_code == "SPLAT_CHECKPOINT_INVALID"


# ---------------------------------------------------------------------------
# Manifests, reuse and VRAM admission
# ---------------------------------------------------------------------------


def _runtime_report() -> neural.RuntimeReport:
    from scene_reconstruction.nerfstudio_runner import RuntimeReport

    return RuntimeReport(
        versions={
            "nerfstudio": "1.1.5",
            "gsplat": "1.4.0",
            "torch": "2.14.1",
            "cuda_build": "12.6",
            "cuda_available": True,
            "device_name": "RTX 3060",
            "kernel_executed": True,
        },
        fingerprint={},
    )


def _converted(tmp_path: Path):
    return _converted_dataset(tmp_path)[1]


def test_the_checkpoint_manifest_excludes_resource_settings(tmp_path: Path) -> None:
    dataset = _converted(tmp_path)
    base = _splat_config()
    manifest = neural.build_splat_manifest(dataset=dataset, runtime=_runtime_report(), splat=base)

    assert manifest["schema"] == neural.SPLAT_MANIFEST_SCHEMA
    assert manifest["dataset_fingerprint"] == dataset.fingerprint
    for key in ("timeout_seconds", "max_vram_mb", "max_artifact_bytes", "min_registered_images"):
        assert key not in manifest["settings"]
    assert manifest["runtime"]["nerfstudio"] == "1.1.5"

    changed = neural.build_splat_manifest(
        dataset=dataset,
        runtime=_runtime_report(),
        splat=_splat_config(max_iterations=500, checkpoint_interval=100),
    )
    assert changed != manifest


def test_a_matching_manifest_reuses_a_validated_artifact(tmp_path: Path) -> None:
    dataset = _converted(tmp_path)
    config = SceneConfig(
        representation="GAUSSIAN_SPLAT", output_format="PLY", splat=_splat_config()
    )
    reconstructor = neural.NeuralReconstructor(
        config, vram_probe=lambda: ("RTX 3060", 12288, 11000)
    )
    manifest = neural.build_splat_manifest(
        dataset=dataset, runtime=_runtime_report(), splat=config.splat
    )
    work_dir = tmp_path / "work"
    splat_dir = work_dir / "splat"
    (splat_dir / "output").mkdir(parents=True)
    write_test_splat_ply(splat_dir / "output" / "scene.ply", count=16)
    (splat_dir / neural.SPLAT_MANIFEST_NAME).write_text(
        __import__("json").dumps(manifest), encoding="utf-8"
    )
    (splat_dir / neural.SPLAT_METADATA_NAME).write_text(
        __import__("json").dumps({"representation": "GAUSSIAN_SPLAT"}), encoding="utf-8"
    )

    artifact = reconstructor.reuse_existing(work_dir=work_dir, expected_manifest=manifest)

    assert artifact is not None and artifact.reused is True
    assert artifact.metadata["reused"] is True
    assert artifact.metadata["artifact"]["gaussian_count"] == 16
    assert artifact.format == SPLAT_FORMAT

    changed = neural.build_splat_manifest(
        dataset=dataset,
        runtime=_runtime_report(),
        splat=_splat_config(max_iterations=500, checkpoint_interval=100),
    )
    assert reconstructor.reuse_existing(work_dir=work_dir, expected_manifest=changed) is None


def test_vram_admission_enforces_the_soft_budget() -> None:
    config = SceneConfig(
        representation="GAUSSIAN_SPLAT", output_format="PLY", splat=_splat_config()
    )
    enough = neural.NeuralReconstructor(
        config, vram_probe=lambda: ("RTX 3060", 12288, 11000)
    ).check_vram()
    assert isinstance(enough, neural.VramReport)
    assert enough.required_mb == 9000
    assert enough.as_metadata()["free_vram_mb_at_admission"] == 11000

    tight = neural.NeuralReconstructor(config, vram_probe=lambda: ("RTX 3060", 12288, 7000))
    with pytest.raises(SplatError) as error:
        tight.check_vram()
    assert error.value.error_code == "SPLAT_RESOURCE_EXHAUSTED"

    tiny = neural.NeuralReconstructor(config, vram_probe=lambda: ("GPU", 512, 100))
    with pytest.raises(SplatError) as error:
        tiny.check_vram()
    assert error.value.error_code == "SPLAT_CUDA_UNAVAILABLE"


def test_cpu_configuration_skips_gpu_admission() -> None:
    config = SceneConfig(
        representation="GAUSSIAN_SPLAT", output_format="PLY", splat=_splat_config(device="cpu")
    )
    reconstructor = neural.NeuralReconstructor(config, vram_probe=lambda: ("GPU", 0, 0))
    assert reconstructor.check_vram() is None


# ---------------------------------------------------------------------------
# Controlled runner
# ---------------------------------------------------------------------------


class _FakeRunner:
    def __init__(self, *, exit_code: int = 0, log_text: str = "") -> None:
        self.exit_code = exit_code
        self.log_text = log_text
        self.calls: list[list[str]] = []

    def run(self, command, *, cwd, timeout, log_path, on_poll=None, env=None):
        self.calls.append(list(command))
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        Path(log_path).write_text(self.log_text, encoding="utf-8")
        return CommandOutcome(
            command=tuple(command),
            exit_code=self.exit_code,
            duration_seconds=0.0,
            log_path=Path(log_path),
        )


def test_the_runner_parses_the_training_marker(tmp_path: Path) -> None:
    checkpoint = tmp_path / "run" / "nerfstudio_models" / "step-000000100.ckpt"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_bytes(b"checkpoint")
    summary = {
        "status": "completed",
        "base_dir": str(tmp_path / "run" / "mogen_scene" / "splatfacto" / "run"),
        "checkpoint": str(checkpoint),
        "checkpoint_count": 1,
        "iterations": 100,
        "train_seconds": 12.5,
        "metrics": {"eval/psnr": 18.2},
    }
    log = "some output\nMOGEN_SPLAT_TRAIN " + __import__("json").dumps(summary) + "\n"
    config = SceneConfig(
        representation="GAUSSIAN_SPLAT", output_format="PLY", splat=_splat_config()
    )
    runner = NerfstudioRunner(config, runner=_FakeRunner(log_text=log))

    outcome = runner.train(
        dataset_dir=tmp_path, run_dir=tmp_path / "run", log_path=tmp_path / "log.txt", timeout=60
    )

    assert outcome.checkpoint_path == checkpoint
    assert outcome.metrics == {"eval/psnr": 18.2}
    assert outcome.duration_seconds == 12.5


def test_the_runner_maps_oom_and_missing_checkpoints(tmp_path: Path) -> None:
    config = SceneConfig(
        representation="GAUSSIAN_SPLAT", output_format="PLY", splat=_splat_config()
    )
    oom = NerfstudioRunner(config, runner=_FakeRunner(exit_code=2, log_text="CUDA out of memory\n"))
    with pytest.raises(SplatError) as error:
        oom.train(dataset_dir=tmp_path, run_dir=tmp_path, log_path=tmp_path / "log.txt", timeout=60)
    assert error.value.error_code == "SPLAT_RESOURCE_EXHAUSTED"

    failed = NerfstudioRunner(config, runner=_FakeRunner(exit_code=2, log_text="boom\n"))
    with pytest.raises(SplatError) as error:
        failed.train(
            dataset_dir=tmp_path, run_dir=tmp_path, log_path=tmp_path / "log.txt", timeout=60
        )
    assert error.value.error_code == "SPLAT_TRAINING_FAILED"

    no_checkpoint = NerfstudioRunner(
        config,
        runner=_FakeRunner(
            log_text=(
                'MOGEN_SPLAT_TRAIN {"checkpoint": null, "base_dir": "/x", "train_seconds": 1}\n'
            )
        ),
    )
    with pytest.raises(SplatError) as error:
        no_checkpoint.train(
            dataset_dir=tmp_path, run_dir=tmp_path, log_path=tmp_path / "log.txt", timeout=60
        )
    assert error.value.error_code == "SPLAT_CHECKPOINT_INVALID"


def test_a_missing_neural_python_is_reported_as_unavailable(tmp_path: Path) -> None:
    config = SceneConfig(
        representation="GAUSSIAN_SPLAT",
        output_format="PLY",
        splat=_splat_config(python_executable=tmp_path / "missing-python"),
    )
    runner = NerfstudioRunner(config, runner=_FakeRunner())

    with pytest.raises(SplatError) as error:
        runner.verify_runtime(run_kernel=False)
    assert error.value.error_code == "SPLAT_RUNTIME_UNAVAILABLE"


def test_a_failed_runtime_probe_is_reported_as_unavailable(tmp_path: Path) -> None:
    python = tmp_path / "python"
    python.write_text("#!/bin/sh\n", encoding="utf-8")
    python.chmod(0o755)
    config = SceneConfig(
        representation="GAUSSIAN_SPLAT",
        output_format="PLY",
        splat=_splat_config(python_executable=python),
    )
    runner = NerfstudioRunner(config, runner=_FakeRunner(exit_code=3, log_text="traceback\n"))

    with pytest.raises(SplatError) as error:
        runner.verify_runtime(run_kernel=True)
    assert error.value.error_code == "SPLAT_RUNTIME_UNAVAILABLE"


# ---------------------------------------------------------------------------
# Configuration mapping and pipeline dispatch
# ---------------------------------------------------------------------------


def test_settings_map_to_the_scene_and_splat_configuration() -> None:
    from types import SimpleNamespace

    settings = SimpleNamespace(
        scene_colmap_executable="/usr/local/bin/colmap",
        scene_openmvs_bin_dir="/usr/local/bin/OpenMVS",
        scene_matching_strategy="EXHAUSTIVE",
        scene_colmap_use_gpu=True,
        scene_colmap_max_features=8192,
        scene_colmap_camera_model="SIMPLE_RADIAL",
        scene_max_image_size=2000,
        scene_max_threads=4,
        scene_openmvs_use_cuda=False,
        scene_enable_mesh_refinement=True,
        scene_enable_texture_generation=True,
        scene_min_registered_images=3,
        scene_min_registration_ratio=0.5,
        scene_min_sparse_points=100,
        scene_min_dense_points=100,
        scene_max_task_seconds=14400,
        scene_work_dir="/data/work/scene",
        scene_representation="gaussian_splat",
        scene_output_format="PLY",
        scene_splat_enabled=True,
        scene_splat_model="splatfacto",
        scene_splat_max_iterations=500,
        scene_splat_image_scale=0.5,
        scene_splat_max_image_dimension=1024,
        scene_splat_checkpoint_interval=100,
        scene_splat_max_vram_mb=8000,
        scene_splat_device="cuda",
        scene_splat_max_artifact_bytes=200 * 1024 * 1024,
        scene_splat_timeout_seconds=3600,
        scene_splat_min_registered_images=4,
        scene_splat_sh_degree=2,
        scene_splat_python="/opt/venv/bin/python",
        scene_splat_site_packages="/opt/splat-site",
    )
    config = build_config_from_settings(settings)

    assert config.representation == "GAUSSIAN_SPLAT"
    assert config.output_format == "PLY"
    assert config.splat.max_iterations == 500
    assert config.splat.image_scale == 0.5
    assert config.splat.sh_degree == 2
    assert config.timeout_for(STAGE_SPLAT_TRAINING) == 3600
    manifest = config.as_manifest()
    assert manifest["representation"] == "GAUSSIAN_SPLAT"
    assert manifest["method"] == "NERFSTUDIO_SPLATFACTO"
    assert manifest["splat"]["model"] == "splatfacto"

    forced = build_config_from_settings(settings, representation="MESH")
    assert forced.representation == "MESH"
    assert forced.output_format == "GLB"


def test_the_splat_pipeline_skips_openmvs_and_reports_neural_stages(
    tmp_path: Path, monkeypatch
) -> None:
    from scene_reconstruction import pipeline as pipeline_module
    from scene_reconstruction.pipeline import PhotogrammetryReconstructor

    started: list[str] = []
    calls: dict[str, object] = {}

    class _FakeNeural:
        def __init__(self, config):
            calls["config"] = config

        def check_vram(self):
            return None

        def runtime_report(self):
            return _runtime_report()

        def prepare(self, dataset, **kwargs):
            calls["prepare"] = kwargs
            return type(
                "Converted",
                (),
                {
                    "fingerprint": "abc",
                    "convention": type(
                        "C", (), {"warnings": (), "ok": True, "as_metadata": lambda self: {}}
                    )(),
                    "as_metadata": lambda self: {"image_count": 3},
                },
            )()

        def reuse_existing(self, **kwargs):
            return None

        def clear_stale_outputs(self, work_dir):
            calls["cleared"] = True

        def train(self, **kwargs):
            calls["trained"] = True
            return type(
                "Training",
                (),
                {
                    "checkpoint_path": tmp_path / "ckpt",
                    "duration_seconds": 1.0,
                    "summary": {"iterations": 100, "train_seconds": 1.0},
                    "metrics": {},
                },
            )()

        def export(self, **kwargs):
            path = tmp_path / "scene.ply"
            write_test_splat_ply(path, count=8)
            calls["exported"] = True
            return type(
                "Export",
                (),
                {
                    "path": path,
                    "sha256": "a" * 64,
                    "file_size_bytes": path.stat().st_size,
                    "training_step": 100,
                    "gaussian_count_before_filter": 8,
                    "as_metadata": lambda self: {"gaussian_count": 8},
                },
            )()

        def build_artifact(self, **kwargs):
            calls["built"] = True
            path = kwargs["export"].path
            return neural.SplatArtifact(
                path=path,
                sha256="a" * 64,
                file_size_bytes=path.stat().st_size,
                metadata={"representation": "GAUSSIAN_SPLAT", "artifact": {"gaussian_count": 8}},
            )

    monkeypatch.setattr(pipeline_module, "NeuralReconstructor", _FakeNeural)
    monkeypatch.setattr(
        pipeline_module,
        "verify_toolchain",
        lambda config, **kwargs: type(
            "Report", (), {"as_dict": lambda self: {"colmap": "4.2.1"}}
        )(),
    )
    monkeypatch.setattr(
        pipeline_module,
        "model_is_present",
        lambda path: True,
    )
    monkeypatch.setattr(
        pipeline_module,
        "prepare_dataset",
        lambda *args, **kwargs: SceneDataset(work_dir=tmp_path, images_dir=tmp_path, images=()),
    )
    monkeypatch.setattr(
        pipeline_module,
        "check_dataset",
        lambda dataset, config: None,
    )

    config = SceneConfig(
        representation="GAUSSIAN_SPLAT", output_format="PLY", splat=_splat_config()
    )

    class _Reconstructor(PhotogrammetryReconstructor):
        def _prepare(
            self, sources, *, work_dir, min_images, max_images, max_image_dimension, paths
        ):
            from scene_reconstruction.dataset import SceneDataset as SD

            return SD(work_dir=work_dir, images_dir=paths["images"], images=())

        def _sparse_stages(self, dataset, paths):
            return None

    reconstructor = _Reconstructor(
        config,
        callbacks=pipeline_module.PipelineCallbacks(
            report_stage=lambda stage, message: started.append(stage)
        ),
    )
    artifact = reconstructor.reconstruct([], work_dir=tmp_path / "work")

    assert artifact.format == "PLY"
    assert STAGE_SPLAT_DATASET_PREPARATION in started
    assert STAGE_SPLAT_TRAINING in started
    assert STAGE_SPLAT_EXPORT in started
    assert not any(stage.startswith("OPENMVS") for stage in started)
    assert not any(stage in {"DENSE_RECONSTRUCTION", "MESH_GENERATION"} for stage in started)
    assert calls["trained"] is True and calls["exported"] is True and calls["built"] is True
