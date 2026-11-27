"""Minimal COLMAP model reader with camera projection helpers.

The splat dataset adapter must use the *validated sparse model* produced by the
existing COLMAP stage. The pipeline's selector keeps only model statistics, so
this module reads the full cameras/images/points records from either the binary
(``cameras.bin``/``images.bin``/``points3D.bin``) or the text format that
``colmap model_converter`` writes.

It deliberately does not depend on pycolmap: the conversion and its projection
self-check stay testable in a plain Python environment, and the format is small
enough to read directly.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .exceptions import SPLAT_DATASET_CONVERSION_FAILED, SplatError

# COLMAP camera model id -> (name, number of parameters)
CAMERA_MODELS: dict[int, tuple[str, int]] = {
    0: ("SIMPLE_PINHOLE", 3),
    1: ("PINHOLE", 4),
    2: ("SIMPLE_RADIAL", 4),
    3: ("RADIAL", 5),
    4: ("OPENCV", 8),
    5: ("OPENCV_FISHEYE", 8),
    6: ("FULL_OPENCV", 12),
    7: ("FOV", 5),
    8: ("SIMPLE_RADIAL_FISHEYE", 4),
    9: ("RADIAL_FISHEYE", 5),
    10: ("THIN_PRISM_FISHEYE", 12),
}
MODEL_BY_NAME: dict[str, int] = {name: model_id for model_id, (name, _) in CAMERA_MODELS.items()}


@dataclass(frozen=True, slots=True)
class ColmapCamera:
    """One COLMAP camera record."""

    camera_id: int
    model: str
    width: int
    height: int
    params: tuple[float, ...]

    def intrinsics(self) -> tuple[float, float, float, float]:
        """Return ``(fx, fy, cx, cy)`` for the supported pinhole models."""
        if self.model == "SIMPLE_PINHOLE":
            if len(self.params) < 3:
                raise SplatError(SPLAT_DATASET_CONVERSION_FAILED, "A camera record is incomplete.")
            return (
                float(self.params[0]),
                float(self.params[0]),
                float(self.params[1]),
                float(self.params[2]),
            )
        if self.model == "PINHOLE":
            if len(self.params) < 4:
                raise SplatError(SPLAT_DATASET_CONVERSION_FAILED, "A camera record is incomplete.")
            return (
                float(self.params[0]),
                float(self.params[1]),
                float(self.params[2]),
                float(self.params[3]),
            )
        raise SplatError(
            SPLAT_DATASET_CONVERSION_FAILED,
            f"The splat path accepts undistorted pinhole cameras, not {self.model}.",
        )


@dataclass(frozen=True, slots=True)
class ColmapImage:
    """One registered image with its world-to-camera pose and 2D observations."""

    image_id: int
    name: str
    camera_id: int
    qvec: tuple[float, float, float, float]
    tvec: tuple[float, float, float]
    xys: np.ndarray
    point3d_ids: np.ndarray

    def rotation_matrix(self) -> np.ndarray:
        """Return the world-to-camera rotation from the scalar-first quaternion."""
        w, x, y, z = self.qvec
        return qvec_to_rotmat(w, x, y, z)

    def world_to_camera(self) -> np.ndarray:
        """Return the 4x4 world-to-camera matrix (COLMAP/OpenCV convention)."""
        matrix = np.eye(4, dtype=np.float64)
        matrix[:3, :3] = self.rotation_matrix()
        matrix[:3, 3] = np.asarray(self.tvec, dtype=np.float64)
        return matrix

    def camera_to_world(self) -> np.ndarray:
        """Return the 4x4 camera-to-world matrix in COLMAP coordinates."""
        return np.linalg.inv(self.world_to_camera())


@dataclass(frozen=True, slots=True)
class ColmapPoint:
    """One sparse 3D point."""

    point3d_id: int
    xyz: tuple[float, float, float]
    rgb: tuple[int, int, int]
    error: float


@dataclass(frozen=True, slots=True)
class ColmapModel:
    """A complete sparse model."""

    cameras: dict[int, ColmapCamera]
    images: dict[int, ColmapImage]
    points: dict[int, ColmapPoint]

    def camera_for(self, image: ColmapImage) -> ColmapCamera:
        camera = self.cameras.get(image.camera_id)
        if camera is None:
            raise SplatError(
                SPLAT_DATASET_CONVERSION_FAILED, "An image references a missing camera."
            )
        return camera

    def as_metadata(self) -> dict[str, Any]:
        return {
            "cameras": len(self.cameras),
            "images": len(self.images),
            "points": len(self.points),
            "camera_models": sorted({camera.model for camera in self.cameras.values()}),
        }


def qvec_to_rotmat(w: float, x: float, y: float, z: float) -> np.ndarray:
    """Convert a scalar-first quaternion into a rotation matrix (COLMAP convention)."""
    norm = math.sqrt(w * w + x * x + y * y + z * z)
    if not math.isfinite(norm) or norm < 1e-12:
        raise SplatError(SPLAT_DATASET_CONVERSION_FAILED, "A camera pose has an invalid rotation.")
    w, x, y, z = w / norm, x / norm, y / norm, z / norm
    return np.array(
        [
            [1 - 2 * y * y - 2 * z * z, 2 * x * y - 2 * z * w, 2 * x * z + 2 * y * w],
            [2 * x * y + 2 * z * w, 1 - 2 * x * x - 2 * z * z, 2 * y * z - 2 * x * w],
            [2 * x * z - 2 * y * w, 2 * y * z + 2 * x * w, 1 - 2 * x * x - 2 * y * y],
        ],
        dtype=np.float64,
    )


class _BinaryReader:
    """Bounded little-endian reader for COLMAP's binary model files."""

    def __init__(self, data: bytes) -> None:
        self._data = memoryview(data)
        self._offset = 0

    def _take(self, size: int) -> memoryview:
        if self._offset + size > len(self._data):
            raise SplatError(SPLAT_DATASET_CONVERSION_FAILED, "A sparse model file is truncated.")
        chunk = self._data[self._offset : self._offset + size]
        self._offset += size
        return chunk

    def uint64(self) -> int:
        return int(np.frombuffer(self._take(8), dtype="<u8")[0])

    def int32(self) -> int:
        return int(np.frombuffer(self._take(4), dtype="<i4")[0])

    def float64(self) -> float:
        return float(np.frombuffer(self._take(8), dtype="<f8")[0])

    def doubles(self, count: int) -> np.ndarray:
        return np.frombuffer(self._take(8 * count), dtype="<f8").astype(np.float64)

    def take(self, size: int) -> memoryview:
        """Skip or return ``size`` raw bytes (used for track payloads)."""
        return self._take(size)

    def bytes_until_nul(self) -> bytes:
        start = self._offset
        while self._offset < len(self._data) and self._data[self._offset] != 0:
            self._offset += 1
        if self._offset >= len(self._data):
            raise SplatError(
                SPLAT_DATASET_CONVERSION_FAILED, "A sparse model file has an unterminated name."
            )
        value = bytes(self._data[start : self._offset])
        self._offset += 1
        return value

    @property
    def remaining(self) -> int:
        return len(self._data) - self._offset


def _read_cameras_binary(path: Path) -> dict[int, ColmapCamera]:
    reader = _BinaryReader(Path(path).read_bytes())
    count = reader.uint64()
    if count > 1_000_000:
        raise SplatError(
            SPLAT_DATASET_CONVERSION_FAILED, "A sparse model declares too many cameras."
        )
    cameras: dict[int, ColmapCamera] = {}
    for _ in range(count):
        camera_id = reader.int32()
        model_id = reader.int32()
        width = reader.uint64()
        height = reader.uint64()
        model = CAMERA_MODELS.get(model_id)
        if model is None:
            raise SplatError(
                SPLAT_DATASET_CONVERSION_FAILED, "A camera uses an unsupported COLMAP model."
            )
        name, parameter_count = model
        params = tuple(float(value) for value in reader.doubles(parameter_count))
        cameras[camera_id] = ColmapCamera(
            camera_id=camera_id,
            model=name,
            width=int(width),
            height=int(height),
            params=params,
        )
    return cameras


def _read_images_binary(path: Path) -> dict[int, ColmapImage]:
    reader = _BinaryReader(Path(path).read_bytes())
    count = reader.uint64()
    if count > 1_000_000:
        raise SplatError(
            SPLAT_DATASET_CONVERSION_FAILED, "A sparse model declares too many images."
        )
    images: dict[int, ColmapImage] = {}
    for _ in range(count):
        image_id = reader.int32()
        qvec = tuple(float(value) for value in reader.doubles(4))
        tvec = tuple(float(value) for value in reader.doubles(3))
        camera_id = reader.int32()
        name = reader.bytes_until_nul().decode("utf-8", errors="replace")
        point_count = reader.uint64()
        if point_count > 100_000_000:
            raise SplatError(
                SPLAT_DATASET_CONVERSION_FAILED, "A sparse model declares too many observations."
            )
        # COLMAP interleaves each observation as (x: double, y: double, id: int64).
        record = np.dtype([("x", "<f8"), ("y", "<f8"), ("point3d_id", "<i8")])
        block = np.frombuffer(reader.take(24 * int(point_count)), dtype=record)
        xys = np.stack([block["x"], block["y"]], axis=1).astype(np.float64)
        ids = block["point3d_id"].astype(np.int64)
        images[image_id] = ColmapImage(
            image_id=image_id,
            name=name,
            camera_id=camera_id,
            qvec=qvec,  # type: ignore[arg-type]
            tvec=tvec,  # type: ignore[arg-type]
            xys=xys,
            point3d_ids=ids,
        )
    return images


def _read_points_binary(path: Path) -> dict[int, ColmapPoint]:
    reader = _BinaryReader(Path(path).read_bytes())
    count = reader.uint64()
    if count > 50_000_000:
        raise SplatError(
            SPLAT_DATASET_CONVERSION_FAILED, "A sparse model declares too many points."
        )
    points: dict[int, ColmapPoint] = {}
    for _ in range(count):
        point_id = reader.uint64()
        xyz = tuple(float(value) for value in reader.doubles(3))
        rgb = tuple(int(value) for value in np.frombuffer(reader._take(3), dtype=np.uint8))
        error = reader.float64()
        track_length = reader.uint64()
        if track_length > 10_000_000:
            raise SplatError(
                SPLAT_DATASET_CONVERSION_FAILED, "A sparse point has an invalid track."
            )
        reader.take(8 * int(track_length))
        points[point_id] = ColmapPoint(
            point3d_id=point_id,
            xyz=xyz,
            rgb=rgb,
            error=error,  # type: ignore[arg-type]
        )
    return points


def _read_cameras_text(path: Path) -> dict[int, ColmapCamera]:
    cameras: dict[int, ColmapCamera] = {}
    for line in _text_lines(path):
        fields = line.split()
        if len(fields) < 5:
            raise SplatError(SPLAT_DATASET_CONVERSION_FAILED, "A camera record is malformed.")
        try:
            camera_id = int(fields[0])
            model = fields[1].upper()
            width, height = int(fields[2]), int(fields[3])
            params = tuple(float(value) for value in fields[4:])
        except ValueError as exc:
            raise SplatError(
                SPLAT_DATASET_CONVERSION_FAILED, "A camera record is malformed."
            ) from exc
        if model not in MODEL_BY_NAME:
            raise SplatError(
                SPLAT_DATASET_CONVERSION_FAILED, "A camera uses an unsupported COLMAP model."
            )
        cameras[camera_id] = ColmapCamera(
            camera_id=camera_id, model=model, width=width, height=height, params=params
        )
    return cameras


def _read_images_text(path: Path) -> dict[int, ColmapImage]:
    lines = _text_lines(path)
    images: dict[int, ColmapImage] = {}
    index = 0
    while index < len(lines):
        fields = lines[index].split()
        index += 1
        if len(fields) < 10:
            raise SplatError(SPLAT_DATASET_CONVERSION_FAILED, "An image record is malformed.")
        try:
            image_id = int(fields[0])
            qvec = tuple(float(value) for value in fields[1:5])
            tvec = tuple(float(value) for value in fields[5:8])
            camera_id = int(fields[8])
        except ValueError as exc:
            raise SplatError(
                SPLAT_DATASET_CONVERSION_FAILED, "An image record is malformed."
            ) from exc
        name = " ".join(fields[9:])
        observations: list[float] = []
        if index < len(lines):
            observation_line = lines[index].strip()
            if observation_line:
                try:
                    observations = [float(value) for value in observation_line.split()]
                except ValueError as exc:
                    raise SplatError(
                        SPLAT_DATASET_CONVERSION_FAILED, "An observation record is malformed."
                    ) from exc
                index += 1
        if len(observations) % 3 != 0:
            raise SplatError(SPLAT_DATASET_CONVERSION_FAILED, "An observation record is malformed.")
        values = np.asarray(observations, dtype=np.float64).reshape(-1, 3)
        images[image_id] = ColmapImage(
            image_id=image_id,
            name=name,
            camera_id=camera_id,
            qvec=qvec,  # type: ignore[arg-type]
            tvec=tvec,  # type: ignore[arg-type]
            xys=values[:, :2].copy() if len(values) else np.zeros((0, 2), dtype=np.float64),
            point3d_ids=values[:, 2].astype(np.int64)
            if len(values)
            else np.zeros(0, dtype=np.int64),
        )
    return images


def _read_points_text(path: Path) -> dict[int, ColmapPoint]:
    points: dict[int, ColmapPoint] = {}
    for line in _text_lines(path):
        fields = line.split()
        if len(fields) < 8:
            continue
        try:
            point_id = int(fields[0])
            xyz = (float(fields[1]), float(fields[2]), float(fields[3]))
            rgb = (int(fields[4]), int(fields[5]), int(fields[6]))
            error = float(fields[7])
        except ValueError as exc:
            raise SplatError(
                SPLAT_DATASET_CONVERSION_FAILED, "A sparse point record is malformed."
            ) from exc
        points[point_id] = ColmapPoint(point3d_id=point_id, xyz=xyz, rgb=rgb, error=error)
    return points


def _text_lines(path: Path) -> list[str]:
    try:
        content = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise SplatError(
            SPLAT_DATASET_CONVERSION_FAILED, "A sparse model file is not readable."
        ) from exc
    return [
        line.strip()
        for line in content.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def read_colmap_model(model_dir: Path) -> ColmapModel:
    """Read a COLMAP sparse model, preferring the binary representation."""
    root = Path(model_dir)
    if not root.is_dir():
        raise SplatError(SPLAT_DATASET_CONVERSION_FAILED, "The sparse model directory is missing.")
    if (root / "cameras.bin").is_file() and (root / "images.bin").is_file():
        cameras = _read_cameras_binary(root / "cameras.bin")
        images = _read_images_binary(root / "images.bin")
        points = (
            _read_points_binary(root / "points3D.bin") if (root / "points3D.bin").is_file() else {}
        )
    elif (root / "cameras.txt").is_file() and (root / "images.txt").is_file():
        cameras = _read_cameras_text(root / "cameras.txt")
        images = _read_images_text(root / "images.txt")
        points = (
            _read_points_text(root / "points3D.txt") if (root / "points3D.txt").is_file() else {}
        )
    else:
        raise SplatError(SPLAT_DATASET_CONVERSION_FAILED, "The sparse model has no cameras/images.")
    if not cameras or not images:
        raise SplatError(SPLAT_DATASET_CONVERSION_FAILED, "The sparse model is empty.")
    return ColmapModel(cameras=cameras, images=images, points=points)


def project_points(
    camera: ColmapCamera,
    image: ColmapImage,
    points: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Project world points into an image; return ``(uv, depth)``.

    Only the undistorted pinhole models are supported; a distorted model is
    rejected by :meth:`ColmapCamera.intrinsics` instead of being reinterpreted.
    """
    fx, fy, cx, cy = camera.intrinsics()
    xyz = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    camera_points = (image.rotation_matrix() @ xyz.T).T + np.asarray(image.tvec, dtype=np.float64)
    depth = camera_points[:, 2]
    safe = np.where(np.abs(depth) < 1e-12, np.nan, depth)
    uv = np.stack(
        [fx * camera_points[:, 0] / safe + cx, fy * camera_points[:, 1] / safe + cy], axis=1
    )
    return uv, depth


__all__ = [
    "CAMERA_MODELS",
    "ColmapCamera",
    "ColmapImage",
    "ColmapModel",
    "ColmapPoint",
    "MODEL_BY_NAME",
    "project_points",
    "qvec_to_rotmat",
    "read_colmap_model",
]
