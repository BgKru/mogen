"""Perceptual near-duplicate detection for scene datasets.

Byte-identical photographs remain the responsibility of the existing SHA-256
dataset validation (07 Section 4.5). This module only generates *candidates*
from a perceptual hash and confirms them with SSIM when a threshold is
configured. It never rejects, removes or rewrites a photograph
(11 Section 5.2).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from PIL import Image

from . import metrics
from .models import NearDuplicateCluster, NearDuplicatePair, NearDuplicates

# pHash input and the thumbnail size kept for SSIM confirmation. The thumbnail
# is a bounded grayscale copy (256x256 uint8 = 64 KiB per image), never the
# original pixels, so a 100-image dataset stays well under 7 MiB.
HASH_EDGE = 32
THUMBNAIL_EDGE = 256


@dataclass(frozen=True, slots=True)
class ImageFingerprint:
    """The bounded evidence kept per image for the duplicate comparison."""

    image_id: str
    filename: str
    hash: int
    thumbnail: np.ndarray


def fingerprint(image: Image.Image, *, image_id: str, filename: str) -> ImageFingerprint:
    """Compute the perceptual hash and SSIM thumbnail for one image."""
    hash_value = metrics.perceptual_hash(metrics.square_gray(image, HASH_EDGE))
    thumbnail = np.clip(np.rint(metrics.square_gray(image, THUMBNAIL_EDGE)), 0, 255).astype(
        np.uint8
    )
    return ImageFingerprint(
        image_id=image_id,
        filename=filename,
        hash=hash_value,
        thumbnail=thumbnail,
    )


def _as_float(thumbnail: np.ndarray) -> np.ndarray:
    return thumbnail.astype(np.float64)


def find_near_duplicates(
    fingerprints: Sequence[ImageFingerprint],
    *,
    max_images: int,
    hash_distance_threshold: int,
    ssim_threshold: float | None,
) -> NearDuplicates:
    """Return bounded candidate pairs and clusters.

    At most ``max_images`` fingerprints are compared, so the pair count is
    bounded by ``max_images * (max_images - 1) / 2``. SSIM is computed only for
    hash candidates. Pairs below the SSIM threshold are discarded when SSIM
    confirmation is enabled.
    """
    if max_images < 2:
        message = "max_images must be at least 2"
        raise ValueError(message)
    selected = list(fingerprints[:max_images])
    truncated = len(fingerprints) > len(selected)
    pairs: list[NearDuplicatePair] = []
    for left_index in range(len(selected)):
        left = selected[left_index]
        for right_index in range(left_index + 1, len(selected)):
            right = selected[right_index]
            distance = metrics.hamming_distance(left.hash, right.hash)
            if distance > hash_distance_threshold:
                continue
            ssim_value: float | None = None
            if ssim_threshold is not None:
                ssim_value = round(
                    metrics.structural_similarity(
                        _as_float(left.thumbnail), _as_float(right.thumbnail)
                    ),
                    4,
                )
                if ssim_value < ssim_threshold:
                    continue
            pairs.append(
                NearDuplicatePair(
                    left_id=left.image_id,
                    right_id=right.image_id,
                    left_filename=left.filename,
                    right_filename=right.filename,
                    hash_distance=distance,
                    ssim=ssim_value,
                )
            )

    index_of = {item.image_id: index for index, item in enumerate(selected)}
    by_index = {index: item for index, item in enumerate(selected)}
    clusters: list[NearDuplicateCluster] = []
    parent = list(range(len(selected)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for pair in pairs:
        union(index_of[pair.left_id], index_of[pair.right_id])
    groups: dict[int, list[int]] = {}
    for index in range(len(selected)):
        groups.setdefault(find(index), []).append(index)
    for members in groups.values():
        if len(members) < 2:
            continue
        clusters.append(
            NearDuplicateCluster(
                image_ids=tuple(by_index[index].image_id for index in members),
                filenames=tuple(by_index[index].filename for index in members),
            )
        )

    return NearDuplicates(
        pairs=tuple(pairs),
        clusters=tuple(clusters),
        images_compared=len(selected),
        hash_distance_threshold=hash_distance_threshold,
        ssim_threshold=ssim_threshold,
        ssim_applied=ssim_threshold is not None,
        truncated=truncated,
        max_images=max_images,
    )


__all__ = [
    "HASH_EDGE",
    "ImageFingerprint",
    "THUMBNAIL_EDGE",
    "find_near_duplicates",
    "fingerprint",
]
