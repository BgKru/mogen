"""Scene dataset preparation and validation (07 Sections 4 and 5).

The worker copies the task's immutable image snapshot into a task-specific
workspace, validates every file with Pillow and rejects duplicate or unusable
photographs before COLMAP runs. Original bytes are never re-encoded, so EXIF and
camera metadata stay available to COLMAP (07 Section 4.6).
"""

from __future__ import annotations

import hashlib
import io
import shutil
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

from PIL import Image, UnidentifiedImageError

from .exceptions import (
    DUPLICATE_IMAGES,
    IMAGE_DECODE_FAILED,
    INSUFFICIENT_IMAGES,
    INVALID_SCENE_DATASET,
    DatasetError,
)

SUPPORTED_FORMATS = frozenset({"JPEG", "PNG"})
_FORMAT_SUFFIX = {"JPEG": ".jpg", "PNG": ".png"}
_HASH_CHUNK = 1024 * 1024

# A decompression bomb is not a photograph this pipeline can process.
Image.MAX_IMAGE_PIXELS = 200_000_000


@dataclass(frozen=True, slots=True)
class SourceImage:
    """One image from the task snapshot, readable through the storage backend."""

    filename: str
    storage_key: str
    image_id: str
    opener: Callable[[], BinaryIO]

    @classmethod
    def from_bytes(
        cls, data: bytes, *, filename: str = "image.jpg", image_id: str = ""
    ) -> SourceImage:
        return cls(
            filename=filename,
            storage_key=filename,
            image_id=image_id,
            opener=lambda: io.BytesIO(data),
        )

    @classmethod
    def from_path(cls, path: Path) -> SourceImage:
        resolved = Path(path)

        def _open() -> BinaryIO:
            return resolved.open("rb")

        return cls(
            filename=resolved.name,
            storage_key=resolved.name,
            image_id=resolved.name,
            opener=_open,
        )


@dataclass(frozen=True, slots=True)
class PreparedImage:
    """A validated image copied into the workspace, unchanged and hashed."""

    path: Path
    filename: str
    original_filename: str
    image_id: str
    sha256: str
    size_bytes: int
    format: str
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class SceneDataset:
    """The ordered, validated image set for one reconstruction task."""

    work_dir: Path
    images_dir: Path
    images: tuple[PreparedImage, ...]
    duplicates: tuple[str, ...] = ()
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def image_count(self) -> int:
        return len(self.images)

    @property
    def total_bytes(self) -> int:
        return sum(image.size_bytes for image in self.images)

    @property
    def formats(self) -> dict[str, int]:
        return dict(Counter(image.format for image in self.images))


def workspace_paths(work_dir: Path) -> dict[str, Path]:
    """Return the documented per-task layout (07 Sections 4.7 and 13.6)."""
    root = Path(work_dir)
    return {
        "root": root,
        "images": root / "images",
        "colmap": root / "colmap",
        "colmap_sparse": root / "colmap" / "sparse",
        "colmap_dense": root / "colmap" / "dense",
        "openmvs": root / "openmvs",
        "output": root / "output",
        "logs": root / "logs",
        "diagnostics": root / "diagnostics",
    }


def create_workspace(work_dir: Path) -> dict[str, Path]:
    """Create an isolated workspace for this task only (SCENE-AC-03/21)."""
    paths = workspace_paths(work_dir)
    for name, path in paths.items():
        if name != "root":
            path.mkdir(parents=True, exist_ok=True)
    return paths


def _copy_and_hash(source: SourceImage, destination: Path) -> tuple[str, int]:
    """Copy the source stream to disk while hashing it; return (sha256, size)."""
    digest = hashlib.sha256()
    size = 0
    try:
        with source.opener() as stream, destination.open("wb") as target:
            while chunk := stream.read(_HASH_CHUNK):
                digest.update(chunk)
                size += len(chunk)
                target.write(chunk)
    except FileNotFoundError as exc:
        raise DatasetError(
            INVALID_SCENE_DATASET, "A source photograph is no longer available."
        ) from exc
    except OSError as exc:
        raise DatasetError(INVALID_SCENE_DATASET, "A source photograph could not be read.") from exc
    return digest.hexdigest(), size


def inspect_image(path: Path, *, max_dimension: int) -> tuple[str, int, int]:
    """Decode an image and return ``(format, width, height)``.

    Both ``verify()`` and a full ``load()`` are used: the first detects a broken
    container, the second proves the pixel data can actually be decoded
    (07 Section 4.5).
    """
    try:
        with Image.open(path) as image:
            image_format = (image.format or "").upper()
            if image_format not in SUPPORTED_FORMATS:
                raise DatasetError(
                    INVALID_SCENE_DATASET,
                    "Only JPEG and PNG photographs can be reconstructed.",
                )
            width, height = image.size
            image.verify()
        with Image.open(path) as image:
            image.load()
    except DatasetError:
        raise
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise DatasetError(
            IMAGE_DECODE_FAILED, "A source photograph could not be decoded."
        ) from exc
    except Image.DecompressionBombError as exc:  # pragma: no cover - defensive
        raise DatasetError(
            INVALID_SCENE_DATASET, "A source photograph exceeds the supported pixel count."
        ) from exc

    if width < 1 or height < 1:
        raise DatasetError(INVALID_SCENE_DATASET, "A source photograph has invalid dimensions.")
    if max(width, height) > max_dimension:
        raise DatasetError(
            INVALID_SCENE_DATASET,
            "A source photograph exceeds the configured maximum dimension.",
        )
    return image_format, width, height


def prepare_dataset(
    sources: Sequence[SourceImage],
    *,
    work_dir: Path,
    min_images: int = 3,
    max_images: int = 100,
    max_image_dimension: int = 8192,
) -> SceneDataset:
    """Validate and copy the ordered image snapshot into ``work_dir/images``.

    Raises :class:`DatasetError` with the documented code for an insufficient
    count, an invalid file, a duplicate image or an over-sized image. Nothing is
    written outside the task workspace.
    """
    if len(sources) < min_images:
        raise DatasetError(
            INSUFFICIENT_IMAGES,
            f"Scene reconstruction needs at least {min_images} photographs.",
        )
    if len(sources) > max_images:
        raise DatasetError(
            INVALID_SCENE_DATASET,
            f"Scene reconstruction accepts at most {max_images} photographs.",
        )

    paths = create_workspace(work_dir)
    images_dir = paths["images"]
    # Remove a previous attempt's images so a retried stage cannot mix datasets.
    for stale in images_dir.iterdir():
        if stale.is_file():
            stale.unlink()

    prepared: list[PreparedImage] = []
    by_hash: dict[str, list[str]] = {}
    duplicates: list[str] = []
    failures: list[DatasetError] = []

    for index, source in enumerate(sources, start=1):
        # The suffix is only a provisional name; the real extension is chosen
        # after the decoded format is known.
        provisional = images_dir / f"image_{index:03d}.upload"
        try:
            sha256, size = _copy_and_hash(source, provisional)
            if size == 0:
                raise DatasetError(IMAGE_DECODE_FAILED, "A source photograph is empty.")
            image_format, width, height = inspect_image(
                provisional, max_dimension=max_image_dimension
            )
        except DatasetError as exc:
            provisional.unlink(missing_ok=True)
            failures.append(exc)
            continue

        final = images_dir / f"image_{index:03d}{_FORMAT_SUFFIX[image_format]}"
        shutil.move(str(provisional), final)
        prepared.append(
            PreparedImage(
                path=final,
                filename=final.name,
                original_filename=source.filename,
                image_id=source.image_id,
                sha256=sha256,
                size_bytes=size,
                format=image_format,
                width=width,
                height=height,
            )
        )
        by_hash.setdefault(sha256, []).append(source.filename)

    duplicates = sorted({name for names in by_hash.values() if len(names) > 1 for name in names})
    if failures:
        # Report the first concrete problem; the message names no internal path.
        raise failures[0]
    if duplicates:
        raise DatasetError(
            DUPLICATE_IMAGES,
            "The image set contains exact duplicate photographs; remove the duplicates.",
        )

    warnings: list[str] = []
    smallest = min((min(image.width, image.height) for image in prepared), default=0)
    if smallest and smallest < 640:
        warnings.append("Some photographs have a short edge below 640 px.")
    if len(prepared) < 6:
        warnings.append("Fewer than six photographs usually give a fragile reconstruction.")

    return SceneDataset(
        work_dir=paths["root"],
        images_dir=images_dir,
        images=tuple(prepared),
        duplicates=tuple(duplicates),
        warnings=tuple(warnings),
    )


__all__ = [
    "PreparedImage",
    "SceneDataset",
    "SourceImage",
    "SUPPORTED_FORMATS",
    "create_workspace",
    "inspect_image",
    "prepare_dataset",
    "workspace_paths",
]
