"""COLMAP → Nerfstudio dataset conversion for Splatfacto (15 Sections 4.3/5.2).

The adapter consumes the **validated** sparse model and the **undistorted**
images that the existing COLMAP stage already produced (the same ones OpenMVS
uses). It writes a task-local ``transforms.json``, the per-image training copies
and a sparse-points PLY in exactly the layout upstream ``ns-process-data``
writes, then measures:

* a reprojection self-check against COLMAP's own 2D observations;
* a numeric round-trip of the Nerfstudio transform back to the COLMAP pose;
* independent camera-convention checks (handedness, forward axis, up axis).

The original uploads and the shared COLMAP outputs are never modified.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import shutil
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from .colmap_model import ColmapCamera, ColmapImage, ColmapModel, project_points, read_colmap_model
from .dataset import PreparedImage, SceneDataset
from .exceptions import (
    SPLAT_DATASET_CONVERSION_FAILED,
    SPLAT_INSUFFICIENT_IMAGES,
    SPLAT_INSUFFICIENT_POINTS,
    SPLAT_INVALID_CAMERAS,
    SplatError,
)
from .splat_config import SplatConfig

logger = logging.getLogger(__name__)

DATASET_MANIFEST_NAME = "splat_dataset_manifest.json"
TRANSFORMS_NAME = "transforms.json"
SPARSE_POINTS_NAME = "sparse_pc.ply"
TRAINING_IMAGES_DIR = "images"
# Upstream ns-process-data rotates the COLMAP world to a z-up viewer frame. The
# same 3x4 transform is written to transforms.json and applied to the sparse
# points; keeping both in one place prevents the two from drifting apart.
_APPLIED_ROWS = (0, 2, 1)
_MAX_REPROJECTION_PX = 4.0


def applied_transform() -> np.ndarray:
    """Return the upstream 3x4 world transform for Nerfstudio datasets."""
    transform = np.eye(4)[:3, :].copy()
    transform = transform[list(_APPLIED_ROWS), :]
    transform[2, :] *= -1
    return transform


def colmap_camera_to_world(image: ColmapImage) -> np.ndarray:
    """Convert a COLMAP pose to the Nerfstudio camera-to-world matrix.

    This reproduces ``nerfstudio/process_data/colmap_utils.colmap_to_json``
    (1.1.5) verbatim: invert the world-to-camera matrix, flip the OpenCV camera
    Y/Z axes to OpenGL, then rotate the world to the z-up viewer frame.
    """
    c2w = image.camera_to_world()
    c2w[0:3, 1:3] *= -1
    c2w = c2w[np.array([0, 2, 1, 3]), :]
    c2w[2, :] *= -1
    return c2w


def _matrix_from_nerfstudio(c2w: np.ndarray) -> np.ndarray:
    """Invert :func:`colmap_camera_to_world` (used by the numeric self-check)."""
    flip = np.diag([1.0, -1.0, -1.0, 1.0])
    permutation = np.eye(4)[[0, 2, 1, 3], :]
    negation = np.diag([1.0, 1.0, -1.0, 1.0])
    # colmap_camera_to_world applies, in order: column flip, row permutation,
    # negation of the (already permuted) second row. As matrices that is
    # ``negation @ permutation @ c2w @ flip``.
    combined = negation @ permutation
    colmap_c2w = np.linalg.inv(combined) @ np.asarray(c2w, dtype=np.float64) @ np.linalg.inv(flip)
    return np.linalg.inv(colmap_c2w)


@dataclass(frozen=True, slots=True)
class CameraConventionReport:
    """Independent checks of the generated camera convention."""

    handedness_ok: bool
    forward_axis_ok: bool
    up_axis_ok: bool
    roundtrip_error: float
    reprojection_median_px: float
    reprojection_max_px: float
    observations: int
    warnings: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return (
            self.handedness_ok
            and self.forward_axis_ok
            and self.up_axis_ok
            and self.roundtrip_error <= 1e-6
            and self.reprojection_median_px <= _MAX_REPROJECTION_PX
        )

    def as_metadata(self) -> dict[str, Any]:
        return {
            "handedness_ok": self.handedness_ok,
            "forward_axis_ok": self.forward_axis_ok,
            "up_axis_ok": self.up_axis_ok,
            "roundtrip_error": round(self.roundtrip_error, 9),
            "reprojection_median_px": round(self.reprojection_median_px, 4),
            "reprojection_max_px": round(self.reprojection_max_px, 4),
            "observations": self.observations,
            "warnings": sorted(set(self.warnings)),
        }


@dataclass(frozen=True, slots=True)
class NerfstudioDataset:
    """A written Nerfstudio-format dataset inside the task workspace."""

    root: Path
    images_dir: Path
    transforms_path: Path
    points_path: Path
    manifest_path: Path
    registered_images: int
    camera_models: tuple[str, ...]
    image_scales: tuple[float, ...]
    sparse_points: int
    fingerprint: str
    convention: CameraConventionReport
    manifest: dict[str, Any] = field(default_factory=dict)

    def as_metadata(self) -> dict[str, Any]:
        """Return compact, path-free dataset facts for result metadata."""
        return {
            "image_count": self.registered_images,
            "camera_models": list(self.camera_models),
            "image_scale_min": round(min(self.image_scales), 6) if self.image_scales else 1.0,
            "image_scale_max": round(max(self.image_scales), 6) if self.image_scales else 1.0,
            "sparse_points": self.sparse_points,
            "fingerprint": self.fingerprint,
            "camera_checks": self.convention.as_metadata(),
            "schema": "nerfstudio_transforms_v1",
        }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _training_name(name: str) -> str:
    """Return a workspace-safe training filename derived from the COLMAP name."""
    if not name or name in {".", ".."}:
        raise SplatError(SPLAT_DATASET_CONVERSION_FAILED, "A registered image name is invalid.")
    if Path(name).name != name or "\\" in name or "/" in name:
        raise SplatError(
            SPLAT_DATASET_CONVERSION_FAILED,
            "A registered image name is not a plain filename.",
        )
    return name


def _scaled_intrinsics(camera: ColmapCamera, sx: float, sy: float) -> dict[str, float]:
    fx, fy, cx, cy = camera.intrinsics()
    return {
        "fl_x": float(fx * sx),
        "fl_y": float(fy * sy),
        "cx": float(cx * sx),
        "cy": float(cy * sy),
        "k1": 0.0,
        "k2": 0.0,
        "p1": 0.0,
        "p2": 0.0,
    }


def _write_training_image(
    source: Path, destination: Path, *, scale: float, max_dimension: int
) -> tuple[int, int, float, float]:
    """Copy or resize one image; return ``(width, height, sx, sy)``."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as opened:
        opened.load()
        width, height = opened.size
        target_scale = min(scale, max_dimension / max(width, height), 1.0)
        if target_scale >= 0.999:
            shutil.copyfile(source, destination)
            return width, height, 1.0, 1.0
        new_width = max(1, round(width * target_scale))
        new_height = max(1, round(height * target_scale))
        resized = opened.resize((new_width, new_height), Image.Resampling.LANCZOS)
        if opened.format == "JPEG":
            resized.convert("RGB").save(destination, format="JPEG", quality=95, subsampling=0)
        else:
            resized.save(destination, format="PNG", optimize=False)
        return new_width, new_height, new_width / width, new_height / height


def _write_sparse_points(path: Path, points: np.ndarray, colours: np.ndarray) -> None:
    """Write the upstream ASCII sparse-points PLY, already world-transformed."""
    with Path(path).open("w", encoding="utf-8") as handle:
        handle.write("ply\n")
        handle.write("format ascii 1.0\n")
        handle.write(f"element vertex {len(points)}\n")
        handle.write("property float x\n")
        handle.write("property float y\n")
        handle.write("property float z\n")
        handle.write("property uint8 red\n")
        handle.write("property uint8 green\n")
        handle.write("property uint8 blue\n")
        handle.write("end_header\n")
        for (x, y, z), (red, green, blue) in zip(points, colours, strict=True):
            handle.write(f"{x:8f} {y:8f} {z:8f} {int(red)} {int(green)} {int(blue)}\n")


def _transform_points(points: np.ndarray) -> np.ndarray:
    matrix = applied_transform()
    return points @ matrix[:3, :3].T + matrix[:3, 3]


def _finite_points(model: ColmapModel) -> tuple[np.ndarray, np.ndarray]:
    xyz: list[tuple[float, float, float]] = []
    rgb: list[tuple[int, int, int]] = []
    for point in model.points.values():
        if not all(math.isfinite(value) for value in point.xyz):
            continue
        xyz.append(point.xyz)
        rgb.append(point.rgb)
    if not xyz:
        return np.zeros((0, 3), dtype=np.float64), np.zeros((0, 3), dtype=np.uint8)
    return np.asarray(xyz, dtype=np.float64), np.asarray(rgb, dtype=np.uint8)


def _check_cameras(
    model: ColmapModel, transforms: dict[int, np.ndarray], transformed_points: np.ndarray
) -> CameraConventionReport:
    """Validate handedness/forward/up and the numeric transform round-trip."""
    if transformed_points.shape[0] < 1:
        raise SplatError(SPLAT_INSUFFICIENT_POINTS, "The sparse model has no usable points.")
    centroid = transformed_points.mean(axis=0)
    handedness = True
    forward_ok = True
    up_dots: list[float] = []
    roundtrip = 0.0

    for image_id, c2w in transforms.items():
        image = model.images[image_id]
        rotation = c2w[:3, :3]
        if abs(float(np.linalg.det(rotation)) - 1.0) > 1e-6:
            handedness = False
        centre = c2w[:3, 3]
        forward = -rotation[:, 2]
        direction = centroid - centre
        if float(np.dot(forward, direction)) <= 0.0:
            forward_ok = False
        up_dots.append(float(rotation[:, 1][2]))
        recovered = _matrix_from_nerfstudio(c2w)
        roundtrip = max(roundtrip, float(np.max(np.abs(recovered - image.world_to_camera()))))

    up_ok = bool(up_dots) and float(np.mean(up_dots)) > 0.0

    # Reprojection uses COLMAP's own observations and pose, so it measures the
    # selected model's quality and proves the image/camera pairing.
    ids_sorted = np.asarray(sorted(model.points), dtype=np.int64)
    xyz_sorted = (
        np.asarray([model.points[int(pid)].xyz for pid in ids_sorted], dtype=np.float64)
        if ids_sorted.size
        else np.zeros((0, 3), dtype=np.float64)
    )
    errors: list[np.ndarray] = []
    for image in model.images.values():
        camera = model.camera_for(image)
        valid = image.point3d_ids > 0
        if not np.any(valid):
            continue
        ids = image.point3d_ids[valid]
        observed = image.xys[valid]
        if ids_sorted.size == 0:
            continue
        indices = np.searchsorted(ids_sorted, ids)
        indices = np.clip(indices, 0, ids_sorted.size - 1)
        matched = ids_sorted[indices] == ids
        if not np.any(matched):
            continue
        points = xyz_sorted[indices[matched]]
        keep = np.isfinite(points).all(axis=1)
        if not np.any(keep):
            continue
        uv, depth = project_points(camera, image, points[keep])
        in_front = depth[keep] > 1e-9
        if not np.any(in_front):
            continue
        residuals = np.linalg.norm(uv[in_front] - observed[matched][keep][in_front], axis=1)
        residuals = residuals[np.isfinite(residuals)]
        if residuals.size:
            errors.append(residuals)

    warnings: list[str] = []
    if errors:
        combined = np.concatenate(errors)
        median = float(np.median(combined))
        maximum = float(np.max(combined))
        observations = int(combined.size)
    else:
        median = maximum = 0.0
        observations = 0
        warnings.append("SPLAT_NO_REPROJECTION_OBSERVATIONS")
    if median > _MAX_REPROJECTION_PX:
        warnings.append("SPLAT_HIGH_REPROJECTION_ERROR")

    return CameraConventionReport(
        handedness_ok=handedness,
        forward_axis_ok=forward_ok,
        up_axis_ok=up_ok,
        roundtrip_error=roundtrip,
        reprojection_median_px=median,
        reprojection_max_px=maximum,
        observations=observations,
        warnings=tuple(warnings),
    )


def build_nerfstudio_dataset(
    dataset: SceneDataset,
    *,
    model_dir: Path,
    images_dir: Path,
    output_dir: Path,
    splat: SplatConfig,
    min_registered_images: int | None = None,
    min_sparse_points: int = 100,
    runtime_versions: dict[str, str] | None = None,
    on_poll: Callable[[], None] | None = None,
) -> NerfstudioDataset:
    """Convert the validated COLMAP model into a Nerfstudio dataset.

    Raises :class:`SplatError` with a stable code for insufficient registered
    images, invalid cameras/poses, an unsupported camera model, too few sparse
    points, a missing image or a failed self-check.
    """
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    training_images = root / TRAINING_IMAGES_DIR
    if training_images.is_dir():
        shutil.rmtree(training_images)
    training_images.mkdir(parents=True, exist_ok=True)

    model = read_colmap_model(model_dir)
    required = (
        splat.min_registered_images if min_registered_images is None else min_registered_images
    )
    if len(model.images) < required:
        raise SplatError(
            SPLAT_INSUFFICIENT_IMAGES,
            f"Gaussian-splat training needs at least {required} registered images.",
        )

    prepared_by_name: dict[str, PreparedImage] = {image.filename: image for image in dataset.images}
    frames: list[dict[str, Any]] = []
    manifest_images: list[dict[str, Any]] = []
    transforms: dict[int, np.ndarray] = {}
    image_scales: list[float] = []
    camera_models: set[str] = set()
    seen: set[str] = set()
    fingerprint_parts: list[Any] = []

    for image_id in sorted(model.images):
        if on_poll is not None:
            on_poll()
        image = model.images[image_id]
        camera = model.camera_for(image)
        if camera.model not in {"SIMPLE_PINHOLE", "PINHOLE"}:
            raise SplatError(
                SPLAT_INVALID_CAMERAS,
                "Gaussian-splat training requires the undistorted pinhole COLMAP model.",
            )
        source_name = _training_name(image.name)
        if source_name not in prepared_by_name:
            raise SplatError(
                SPLAT_DATASET_CONVERSION_FAILED,
                "A registered image does not belong to the prepared dataset.",
            )
        if source_name in seen:
            raise SplatError(SPLAT_DATASET_CONVERSION_FAILED, "Two cameras reference one image.")
        seen.add(source_name)
        source_path = Path(images_dir) / source_name
        if not source_path.is_file():
            raise SplatError(
                SPLAT_DATASET_CONVERSION_FAILED, "An undistorted training image is missing."
            )
        destination = training_images / source_name
        width, height, sx, sy = _write_training_image(
            source_path,
            destination,
            scale=splat.image_scale,
            max_dimension=splat.max_image_dimension,
        )
        if width != round(camera.width * sx) or height != round(camera.height * sy):
            raise SplatError(
                SPLAT_INVALID_CAMERAS,
                "The training image dimensions do not match the camera record.",
            )
        intrinsics = _scaled_intrinsics(camera, sx, sy)
        _validate_camera_values(image, intrinsics, width, height)
        camera_models.add(camera.model)
        image_scales.append(sx)
        c2w = colmap_camera_to_world(image)
        transforms[image_id] = c2w
        frames.append(
            {
                "file_path": f"{TRAINING_IMAGES_DIR}/{source_name}",
                "transform_matrix": c2w.tolist(),
                "colmap_im_id": int(image_id),
                **intrinsics,
                "w": int(width),
                "h": int(height),
            }
        )
        manifest_images.append(
            {
                "image_id": int(image_id),
                "source_name": source_name,
                "training_name": f"{TRAINING_IMAGES_DIR}/{source_name}",
                "source_sha256": prepared_by_name[source_name].sha256,
                "training_sha256": _sha256_file(destination),
                "camera_id": int(image.camera_id),
                "width": int(width),
                "height": int(height),
                "scale": round(sx, 9),
            }
        )
        fingerprint_parts.append(
            {
                "name": source_name,
                "training_sha256": manifest_images[-1]["training_sha256"],
                "width": int(width),
                "height": int(height),
                "intrinsics": [round(value, 6) for value in intrinsics.values()],
                "pose": [round(float(value), 8) for value in c2w.ravel()],
            }
        )

    if len(model.images) != len(seen):
        raise SplatError(SPLAT_DATASET_CONVERSION_FAILED, "A registered image was not converted.")

    points, colours = _finite_points(model)
    if points.shape[0] < min_sparse_points:
        raise SplatError(
            SPLAT_INSUFFICIENT_POINTS,
            f"Gaussian-splat training needs at least {min_sparse_points} sparse points.",
        )
    transformed = _transform_points(points)
    convention = _check_cameras(model, transforms, transformed)
    if not convention.ok:
        raise SplatError(
            SPLAT_INVALID_CAMERAS,
            "The converted camera model failed its handedness, forward-axis or "
            "reprojection checks.",
        )

    points_path = root / SPARSE_POINTS_NAME
    _write_sparse_points(points_path, transformed, colours)
    if on_poll is not None:
        on_poll()

    transforms_doc = {
        "camera_model": "OPENCV",
        "applied_transform": applied_transform().tolist(),
        "ply_file_path": SPARSE_POINTS_NAME,
        "frames": frames,
    }
    transforms_path = root / TRANSFORMS_NAME
    transforms_path.write_text(
        json.dumps(transforms_doc, indent=2, sort_keys=True), encoding="utf-8"
    )

    fingerprint = _fingerprint(fingerprint_parts, transformed)
    manifest = {
        "schema": "nerfstudio_transforms_v1",
        "fingerprint": fingerprint,
        "settings": {
            "image_scale": splat.image_scale,
            "max_image_dimension": splat.max_image_dimension,
            "sh_degree": splat.sh_degree,
        },
        "registered_images": len(frames),
        "camera_models": sorted(camera_models),
        "applied_transform": applied_transform().tolist(),
        "sparse_points": int(points.shape[0]),
        "camera_checks": convention.as_metadata(),
        "images": manifest_images,
        "runtime_versions": dict(runtime_versions or {}),
    }
    manifest_path = root / DATASET_MANIFEST_NAME
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    logger.info(
        "splat_dataset_ready",
        extra={
            "operation": "scene_reconstruction",
            "registered_images": len(frames),
            "sparse_points": int(points.shape[0]),
            "reprojection_median_px": round(convention.reprojection_median_px, 4),
        },
    )
    return NerfstudioDataset(
        root=root,
        images_dir=training_images,
        transforms_path=transforms_path,
        points_path=points_path,
        manifest_path=manifest_path,
        registered_images=len(frames),
        camera_models=tuple(sorted(camera_models)),
        image_scales=tuple(image_scales),
        sparse_points=int(points.shape[0]),
        fingerprint=fingerprint,
        convention=convention,
        manifest=manifest,
    )


def _validate_camera_values(
    image: ColmapImage,
    intrinsics: dict[str, float],
    width: int,
    height: int,
) -> None:
    """Reject non-finite or implausible intrinsics/extrinsics before training."""
    values = [
        intrinsics["fl_x"],
        intrinsics["fl_y"],
        intrinsics["cx"],
        intrinsics["cy"],
        *image.qvec,
        *image.tvec,
    ]
    if not all(math.isfinite(value) for value in values):
        raise SplatError(SPLAT_INVALID_CAMERAS, "A camera record contains non-finite values.")
    if intrinsics["fl_x"] <= 0 or intrinsics["fl_y"] <= 0:
        raise SplatError(SPLAT_INVALID_CAMERAS, "A camera has a non-positive focal length.")
    if not (0.0 <= intrinsics["cx"] <= width and 0.0 <= intrinsics["cy"] <= height):
        raise SplatError(
            SPLAT_INVALID_CAMERAS, "A camera principal point lies outside the training image."
        )


def _fingerprint(frames: Sequence[dict[str, Any]], points: np.ndarray) -> str:
    digest = hashlib.sha256()
    payload = json.dumps(
        {
            "frames": list(frames),
            "applied_transform": applied_transform().tolist(),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest.update(payload)
    digest.update(np.ascontiguousarray(points, dtype="<f8").tobytes())
    return digest.hexdigest()


__all__ = [
    "CameraConventionReport",
    "DATASET_MANIFEST_NAME",
    "NerfstudioDataset",
    "SPARSE_POINTS_NAME",
    "TRANSFORMS_NAME",
    "applied_transform",
    "build_nerfstudio_dataset",
    "colmap_camera_to_world",
]
