"""Sparse reconstruction inspection and selection (07 Sections 8.5-8.7).

COLMAP may write several independent models under ``sparse/``. The worker
inspects every candidate, selects the most useful coherent one and validates it
against the immutable image snapshot; the directory name is never the criterion.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

from .config import SceneConfig
from .exceptions import (
    INSUFFICIENT_REGISTERED_IMAGES,
    INVALID_CAMERA_PARAMETERS,
    SPARSE_RECONSTRUCTION_FAILED,
    ReconstructionError,
)


@dataclass(frozen=True, slots=True)
class ModelCandidate:
    """Measured properties of one COLMAP sparse model."""

    model_dir: Path
    text_dir: Path
    registered_images: int
    camera_count: int
    points: int
    mean_reprojection_error: float
    components: int
    largest_component: int
    cameras_valid: bool
    poses_valid: bool
    warnings: tuple[str, ...] = field(default_factory=tuple)
    total_images: int = 0

    @property
    def registration_ratio(self) -> float:
        if self.total_images <= 0:
            return 0.0
        return self.registered_images / self.total_images

    @property
    def usable(self) -> bool:
        return self.cameras_valid and self.poses_valid and self.registered_images > 0

    def as_metadata(self) -> dict[str, object]:
        return {
            "model": self.model_dir.name,
            "registered_images": self.registered_images,
            "registration_ratio": round(self.registration_ratio, 4),
            "points": self.points,
            "mean_reprojection_error": round(self.mean_reprojection_error, 6),
            "components": self.components,
            "largest_component": self.largest_component,
            "camera_count": self.camera_count,
            "cameras_valid": self.cameras_valid,
            "poses_valid": self.poses_valid,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True, slots=True)
class ReconstructionSelection:
    """The selected model and the evidence used to choose it."""

    selected: ModelCandidate
    candidates: tuple[ModelCandidate, ...]
    reason: str
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def as_metadata(self) -> dict[str, object]:
        return {
            "selected_model": self.selected.model_dir.name,
            "selection_reason": self.reason,
            "candidates": [candidate.as_metadata() for candidate in self.candidates],
        }


def _read_lines(path: Path) -> list[str]:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        raise ReconstructionError(
            SPARSE_RECONSTRUCTION_FAILED, "A sparse model file is not readable."
        ) from exc


def parse_cameras(path: Path) -> tuple[dict[int, str], bool, tuple[str, ...]]:
    """Parse ``cameras.txt``; return ``(cameras, valid, warnings)``."""
    cameras: dict[int, str] = {}
    valid = True
    warnings: list[str] = []
    for line in _read_lines(path):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        fields = stripped.split()
        if len(fields) < 5:
            warnings.append("A camera record is malformed.")
            valid = False
            continue
        try:
            camera_id = int(fields[0])
            model = fields[1]
            width, height = int(fields[2]), int(fields[3])
            params = [float(value) for value in fields[4:]]
        except ValueError:
            warnings.append("A camera record contains non-numeric values.")
            valid = False
            continue
        if width <= 0 or height <= 0 or not all(math.isfinite(value) for value in params):
            valid = False
            warnings.append("A camera has invalid dimensions or parameters.")
        if model == "SIMPLE_RADIAL" and len(params) < 3:
            valid = False
            warnings.append("A SIMPLE_RADIAL camera has incomplete parameters.")
        cameras[camera_id] = model
    if not cameras:
        valid = False
        warnings.append("The model has no cameras.")
    return cameras, valid, tuple(sorted(set(warnings)))


def parse_images(
    path: Path, cameras: dict[int, str]
) -> tuple[dict[int, str], int, bool, tuple[str, ...]]:
    """Parse ``images.txt``; return ``(images, count, valid, warnings)``.

    The file has two lines per registered image. Only the image line carries the
    pose and camera reference; the second line lists 2D observations.
    """
    images: dict[int, str] = {}
    valid = True
    warnings: list[str] = []
    data_lines = [line for line in _read_lines(path) if not line.lstrip().startswith("#")]
    index = 0
    while index < len(data_lines):
        line = data_lines[index].strip()
        index += 2  # skip the observation line that follows
        if not line:
            continue
        fields = line.split()
        if len(fields) < 10:
            warnings.append("An image record is malformed.")
            valid = False
            continue
        try:
            image_id = int(fields[0])
            pose = [float(value) for value in fields[1:8]]
            camera_id = int(fields[8])
        except ValueError:
            warnings.append("An image record contains non-numeric values.")
            valid = False
            continue
        name = " ".join(fields[9:])
        quaternion_norm = math.sqrt(sum(value * value for value in pose[:4]))
        if not all(math.isfinite(value) for value in pose) or quaternion_norm < 1e-8:
            valid = False
            warnings.append("A camera pose is invalid.")
        if camera_id not in cameras:
            valid = False
            warnings.append("An image references a camera that is not in the model.")
        images[image_id] = name
    if not images:
        valid = False
        warnings.append("No image was registered.")
    return images, len(images), valid, tuple(sorted(set(warnings)))


@dataclass(frozen=True, slots=True)
class PointStatistics:
    points: int
    mean_error: float
    max_error: float
    edges: tuple[tuple[int, int], ...]


def parse_points(path: Path) -> PointStatistics:
    """Parse ``points3D.txt`` and derive image connectivity from the tracks."""
    total = 0
    error_sum = 0.0
    max_error = 0.0
    edges: set[tuple[int, int]] = set()
    for line in _read_lines(path):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        fields = stripped.split()
        if len(fields) < 8:
            continue
        try:
            error = float(fields[7])
            track = [int(value) for value in fields[8:]]
        except ValueError:
            continue
        if not math.isfinite(error):
            continue
        total += 1
        error_sum += error
        max_error = max(max_error, error)
        image_ids = track[0::2]
        first = image_ids[0] if image_ids else None
        for other in image_ids[1:]:
            if first is not None and other != first:
                edges.add((min(first, other), max(first, other)))
    mean_error = round(error_sum / total, 6) if total else 0.0
    return PointStatistics(
        points=total, mean_error=mean_error, max_error=max_error, edges=tuple(sorted(edges))
    )


def _components(registered: set[int], edges: tuple[tuple[int, int], ...]) -> tuple[int, int]:
    """Return connected components among registered images."""
    active = set(registered)
    adjacency: dict[int, set[int]] = {image_id: set() for image_id in active}
    for left, right in edges:
        if left in active and right in active:
            adjacency[left].add(right)
            adjacency[right].add(left)
    seen: set[int] = set()
    components = 0
    largest = 0
    for image_id in active:
        if image_id in seen:
            continue
        components += 1
        size = 0
        stack = [image_id]
        seen.add(image_id)
        while stack:
            current = stack.pop()
            size += 1
            for neighbour in adjacency[current]:
                if neighbour not in seen:
                    seen.add(neighbour)
                    stack.append(neighbour)
        largest = max(largest, size)
    return components, largest


def inspect_model(model_dir: Path, text_dir: Path, total_images: int) -> ModelCandidate:
    """Measure one sparse model from its converted text representation."""
    cameras, cameras_valid, camera_warnings = parse_cameras(text_dir / "cameras.txt")
    images, registered, poses_valid, image_warnings = parse_images(text_dir / "images.txt", cameras)
    points = parse_points(text_dir / "points3D.txt")
    components, largest = _components(set(images), points.edges)

    warnings = list(camera_warnings) + list(image_warnings)
    if components > 1:
        warnings.append(f"The reconstruction is fragmented into {components} components.")
    ratio = registered / total_images if total_images else 0.0
    if 0 < ratio < 0.75:
        warnings.append("A large fraction of the photographs was not registered.")
    if points.points < 100:
        warnings.append("The sparse point cloud is small.")

    return ModelCandidate(
        model_dir=model_dir,
        text_dir=text_dir,
        registered_images=registered,
        camera_count=len(cameras),
        points=points.points,
        mean_reprojection_error=points.mean_error,
        components=components,
        largest_component=largest,
        cameras_valid=cameras_valid,
        poses_valid=poses_valid,
        warnings=tuple(sorted(set(warnings))),
        total_images=total_images,
    )


def select_reconstruction(
    candidates: list[ModelCandidate], config: SceneConfig
) -> ReconstructionSelection:
    """Select and validate the best sparse model, or raise the documented error.

    Ranking uses registered images, then registration ratio, then point count,
    then the lower mean reprojection error. Directory order is irrelevant.
    """
    if not candidates:
        raise ReconstructionError(
            SPARSE_RECONSTRUCTION_FAILED, "COLMAP produced no sparse reconstruction."
        )

    usable = [candidate for candidate in candidates if candidate.usable]
    if not usable:
        if any(not candidate.cameras_valid for candidate in candidates):
            raise ReconstructionError(
                INVALID_CAMERA_PARAMETERS, "The reconstructed cameras are invalid."
            )
        raise ReconstructionError(
            SPARSE_RECONSTRUCTION_FAILED, "No sparse model contains a valid camera pose."
        )

    best = max(
        usable,
        key=lambda candidate: (
            candidate.registered_images,
            candidate.registration_ratio,
            candidate.points,
            -candidate.mean_reprojection_error,
        ),
    )
    if best.registered_images < config.min_registered_images:
        raise ReconstructionError(
            INSUFFICIENT_REGISTERED_IMAGES,
            "Too few photographs were registered in the reconstruction.",
        )
    if best.registration_ratio < config.min_registration_ratio:
        raise ReconstructionError(
            INSUFFICIENT_REGISTERED_IMAGES,
            "The registered-image ratio is below the configured threshold.",
        )
    if best.points < config.min_sparse_points:
        raise ReconstructionError(
            SPARSE_RECONSTRUCTION_FAILED,
            "The sparse point cloud is too small to continue.",
        )
    if not best.cameras_valid:
        raise ReconstructionError(
            INVALID_CAMERA_PARAMETERS, "The selected reconstruction has invalid cameras."
        )

    reason = (
        f"selected model {best.model_dir.name}: "
        f"{best.registered_images}/{best.total_images} images registered, "
        f"{best.points} points, mean reprojection error {best.mean_reprojection_error}"
    )
    return ReconstructionSelection(
        selected=best,
        candidates=tuple(
            sorted(
                candidates,
                key=lambda candidate: (-candidate.registered_images, candidate.model_dir.name),
            )
        ),
        reason=reason,
        warnings=best.warnings,
    )


__all__ = [
    "ModelCandidate",
    "PointStatistics",
    "ReconstructionSelection",
    "inspect_model",
    "parse_cameras",
    "parse_images",
    "parse_points",
    "select_reconstruction",
]
