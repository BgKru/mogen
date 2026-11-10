"""COLMAP command construction and stage validation (07 Sections 5-9).

Commands are pure functions so unit tests can assert the exact argument array.
The runner adds execution, output validation and diagnostics.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .config import SceneConfig
from .exceptions import (
    FEATURE_EXTRACTION_FAILED,
    FEATURE_MATCHING_FAILED,
    IMAGE_UNDISTORTION_FAILED,
    INSUFFICIENT_REGISTERED_IMAGES,
    NO_VALID_MATCHES,
    SPARSE_RECONSTRUCTION_FAILED,
    ReconstructionError,
    SceneReconstructionError,
)
from .runner import CommandOutcome, CommandRunner, tail_log

logger = logging.getLogger(__name__)

# Binary sparse model files written by COLMAP's mapper/undistorter.
SPARSE_MODEL_FILES = ("cameras.bin", "images.bin", "points3D.bin")
_COMAP_MODEL_SUFFIXES = (".bin", ".txt")


@dataclass(frozen=True, slots=True)
class DatabaseStats:
    """Facts read from the COLMAP SQLite database."""

    images: int
    keypoints: int
    matched_pairs: int
    verified_pairs: int
    components: int = 0
    largest_component: int = 0


@dataclass(frozen=True, slots=True)
class StageOutcome:
    """One executed COLMAP stage and the metrics used to validate it."""

    stage: str
    duration_seconds: float
    log_path: Path
    database: DatabaseStats | None = None
    model_dirs: tuple[Path, ...] = ()
    artifacts: tuple[Path, ...] = field(default_factory=tuple)


def feature_extraction_command(
    config: SceneConfig, *, images_dir: Path, database_path: Path
) -> list[str]:
    """Build ``colmap feature_extractor`` with validated configuration only."""
    return [
        str(config.tool("colmap")),
        "feature_extractor",
        "--database_path",
        str(database_path),
        "--image_path",
        str(images_dir),
        "--ImageReader.camera_model",
        config.colmap_camera_model,
        "--ImageReader.single_camera",
        "0",
        "--SiftExtraction.max_num_features",
        str(config.colmap_max_features),
        "--FeatureExtraction.use_gpu",
        "1" if config.colmap_use_gpu else "0",
        "--FeatureExtraction.num_threads",
        str(config.max_threads),
    ]


def feature_matching_command(config: SceneConfig, *, database_path: Path) -> list[str]:
    """Build the configured matcher: exhaustive (default) or sequential."""
    matcher = (
        "sequential_matcher" if config.matching_strategy == "SEQUENTIAL" else "exhaustive_matcher"
    )
    return [
        str(config.tool("colmap")),
        matcher,
        "--database_path",
        str(database_path),
        "--FeatureMatching.use_gpu",
        "1" if config.colmap_use_gpu else "0",
        "--FeatureMatching.num_threads",
        str(config.max_threads),
    ]


def mapper_command(
    config: SceneConfig, *, images_dir: Path, database_path: Path, sparse_dir: Path
) -> list[str]:
    """Build ``colmap mapper`` for incremental Structure-from-Motion."""
    return [
        str(config.tool("colmap")),
        "mapper",
        "--database_path",
        str(database_path),
        "--image_path",
        str(images_dir),
        "--output_path",
        str(sparse_dir),
        "--Mapper.num_threads",
        str(config.max_threads),
    ]


def image_undistorter_command(
    config: SceneConfig, *, images_dir: Path, model_dir: Path, dense_dir: Path
) -> list[str]:
    """Build ``colmap image_undistorter`` for the selected sparse model."""
    return [
        str(config.tool("colmap")),
        "image_undistorter",
        "--image_path",
        str(images_dir),
        "--input_path",
        str(model_dir),
        "--output_path",
        str(dense_dir),
        "--output_type",
        "COLMAP",
        "--max_image_size",
        str(config.max_image_size),
    ]


def model_converter_command(config: SceneConfig, *, model_dir: Path, output_dir: Path) -> list[str]:
    """Build ``colmap model_converter`` used to read sparse statistics."""
    return [
        str(config.tool("colmap")),
        "model_converter",
        "--input_path",
        str(model_dir),
        "--output_path",
        str(output_dir),
        "--output_type",
        "TXT",
    ]


def list_model_dirs(sparse_dir: Path) -> list[Path]:
    """Return every candidate model directory, sorted numerically."""
    if not sparse_dir.is_dir():
        return []

    def _key(path: Path) -> tuple[int, str]:
        try:
            return (int(path.name), path.name)
        except ValueError:
            return (10**6, path.name)

    return sorted((candidate for candidate in sparse_dir.iterdir() if candidate.is_dir()), key=_key)


def model_is_present(model_dir: Path) -> bool:
    """Return True when a directory contains a readable COLMAP sparse model."""
    return any(
        (Path(model_dir) / f"{stem}{suffix}").is_file()
        for stem in ("cameras", "images", "points3D")
        for suffix in _COMAP_MODEL_SUFFIXES
    )


def _connected_components(images: int, edges: list[tuple[int, int]]) -> tuple[int, int]:
    """Return ``(component_count, largest_component_size)`` over image ids."""
    parent = list(range(images + 1))
    size = [1] * (images + 1)

    def find(node: int) -> int:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(left: int, right: int) -> None:
        root_left, root_right = find(left), find(right)
        if root_left == root_right:
            return
        if size[root_left] < size[root_right]:
            root_left, root_right = root_right, root_left
        parent[root_right] = root_left
        size[root_left] += size[root_right]

    for left, right in edges:
        if 1 <= left <= images and 1 <= right <= images:
            union(left, right)

    roots: dict[int, int] = {}
    for image_id in range(1, images + 1):
        root = find(image_id)
        roots[root] = roots.get(root, 0) + 1
    if not roots:
        return (0, 0)
    return (len(roots), max(roots.values()))


# COLMAP encodes the two image ids of a matched pair in ``pair_id`` as
# ``image_id1 * kMaxNumImages + image_id2``; current releases have no image_id
# columns in two_view_geometries.
COLMAP_MAX_IMAGES = 2147483647


def _pair_image_ids(pair_id: int) -> tuple[int, int]:
    """Decode a COLMAP ``pair_id`` into its two image identifiers."""
    return (pair_id // COLMAP_MAX_IMAGES, pair_id % COLMAP_MAX_IMAGES)


def read_database_stats(database_path: Path) -> DatabaseStats:
    """Read image, keypoint and verified-pair counts from the COLMAP database."""
    if not Path(database_path).is_file():
        raise ReconstructionError(
            FEATURE_EXTRACTION_FAILED, "COLMAP did not create a feature database."
        )
    try:
        connection = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
        try:
            cursor = connection.cursor()
            images = int(cursor.execute("SELECT COUNT(*) FROM images").fetchone()[0])
            keypoints = 0
            try:
                keypoints = int(
                    cursor.execute("SELECT COALESCE(SUM(rows), 0) FROM keypoints").fetchone()[0]
                )
            except sqlite3.DatabaseError:
                # Older/newer schemas may not store a row count; the image count
                # is still authoritative for "were all photographs processed".
                keypoints = 0
            matched_pairs = 0
            verified_pairs = 0
            edges: list[tuple[int, int]] = []
            try:
                matched_pairs = int(cursor.execute("SELECT COUNT(*) FROM matches").fetchone()[0])
            except sqlite3.DatabaseError:
                matched_pairs = 0
            columns = {
                str(row[1]) for row in cursor.execute("PRAGMA table_info(two_view_geometries)")
            }
            if {"image_id1", "image_id2"} <= columns:
                rows = cursor.execute(
                    "SELECT image_id1, image_id2 FROM two_view_geometries WHERE rows > 0"
                ).fetchall()
                verified_pairs = len(rows)
                edges = [(int(left), int(right)) for left, right in rows]
            else:
                pair_rows = cursor.execute(
                    "SELECT pair_id FROM two_view_geometries WHERE rows > 0"
                ).fetchall()
                verified_pairs = len(pair_rows)
                edges = [_pair_image_ids(int(pair_id)) for (pair_id,) in pair_rows]
        finally:
            connection.close()
    except sqlite3.DatabaseError as exc:
        raise ReconstructionError(
            FEATURE_EXTRACTION_FAILED, "The COLMAP feature database is not readable."
        ) from exc

    components, largest_component = _connected_components(images, edges)
    return DatabaseStats(
        images=images,
        keypoints=keypoints,
        matched_pairs=matched_pairs,
        verified_pairs=verified_pairs,
        components=components,
        largest_component=largest_component,
    )


class ColmapRunner:
    """Execute COLMAP stages and reject outputs that cannot be used."""

    def __init__(self, config: SceneConfig, runner: CommandRunner | None = None) -> None:
        self._config = config
        self._runner = runner or CommandRunner()

    def _execute(
        self,
        stage: str,
        command: list[str],
        *,
        cwd: Path,
        timeout: int,
        log_path: Path,
        on_poll: Callable[[], None] | None,
        error_code: str,
        error_message: str,
    ) -> CommandOutcome:
        outcome = self._runner.run(
            command, cwd=cwd, timeout=timeout, log_path=log_path, on_poll=on_poll
        )
        if not outcome.succeeded:
            # The exit code and tool output stay in the worker log and the stage
            # log file; the API only ever sees the user-safe message (07 17.4).
            logger.error(
                "scene_tool_failed",
                extra={
                    "operation": "scene_reconstruction",
                    "stage": stage,
                    "exit_code": outcome.exit_code,
                    "log_path": str(log_path),
                },
            )
            raise ReconstructionError(error_code, error_message)
        return outcome

    def extract_features(
        self,
        *,
        images_dir: Path,
        database_path: Path,
        log_path: Path,
        expected_images: int,
        on_poll: Callable[[], None] | None = None,
    ) -> StageOutcome:
        command = feature_extraction_command(
            self._config, images_dir=images_dir, database_path=database_path
        )
        outcome = self._execute(
            "FEATURE_EXTRACTION",
            command,
            cwd=images_dir.parent,
            timeout=self._config.timeout_for("FEATURE_EXTRACTION"),
            log_path=log_path,
            on_poll=on_poll,
            error_code=FEATURE_EXTRACTION_FAILED,
            error_message="COLMAP feature extraction failed.",
        )
        stats = read_database_stats(database_path)
        if stats.images != expected_images:
            raise ReconstructionError(
                FEATURE_EXTRACTION_FAILED,
                "COLMAP did not process every photograph in the snapshot.",
            )
        return StageOutcome(
            stage="FEATURE_EXTRACTION",
            duration_seconds=outcome.duration_seconds,
            log_path=log_path,
            database=stats,
            artifacts=(database_path,),
        )

    def match_features(
        self,
        *,
        database_path: Path,
        log_path: Path,
        on_poll: Callable[[], None] | None = None,
    ) -> StageOutcome:
        command = feature_matching_command(self._config, database_path=database_path)
        outcome = self._execute(
            "FEATURE_MATCHING",
            command,
            cwd=database_path.parent,
            timeout=self._config.timeout_for("FEATURE_MATCHING"),
            log_path=log_path,
            on_poll=on_poll,
            error_code=FEATURE_MATCHING_FAILED,
            error_message="COLMAP feature matching failed.",
        )
        stats = read_database_stats(database_path)
        if stats.verified_pairs <= 0 or stats.largest_component < 2:
            raise ReconstructionError(
                NO_VALID_MATCHES,
                "The photographs have no geometrically verified matches.",
            )
        return StageOutcome(
            stage="FEATURE_MATCHING",
            duration_seconds=outcome.duration_seconds,
            log_path=log_path,
            database=stats,
            artifacts=(database_path,),
        )

    def reconstruct_sparse(
        self,
        *,
        images_dir: Path,
        database_path: Path,
        sparse_dir: Path,
        log_path: Path,
        on_poll: Callable[[], None] | None = None,
    ) -> StageOutcome:
        sparse_dir.mkdir(parents=True, exist_ok=True)
        command = mapper_command(
            self._config,
            images_dir=images_dir,
            database_path=database_path,
            sparse_dir=sparse_dir,
        )
        outcome = self._runner.run(
            command,
            cwd=sparse_dir.parent,
            timeout=self._config.timeout_for("SPARSE_RECONSTRUCTION"),
            log_path=log_path,
            on_poll=on_poll,
        )
        models = [model for model in list_model_dirs(sparse_dir) if model_is_present(model)]
        if not models:
            stats = None
            try:
                stats = read_database_stats(database_path)
            except SceneReconstructionError:
                stats = None
            # A mapper that exits without a model means it could not register a
            # usable initial pair: that is a data/overlap problem, not an
            # internal failure. Report the documented insufficient-registration
            # code with an actionable message; the tool log stays internal.
            logger.error(
                "scene_sparse_reconstruction_failed",
                extra={
                    "operation": "scene_reconstruction",
                    "stage": "SPARSE_RECONSTRUCTION",
                    "exit_code": outcome.exit_code,
                    "verified_pairs": stats.verified_pairs if stats else None,
                    "log_path": str(log_path),
                    "log_tail": tail_log(log_path, lines=8),
                },
            )
            raise ReconstructionError(
                INSUFFICIENT_REGISTERED_IMAGES,
                "COLMAP could not determine camera positions for enough photographs. "
                "The photographs may not overlap enough or may contain too little visual detail.",
            )
        if not outcome.succeeded:
            logger.warning(
                "scene_sparse_reconstruction_partial",
                extra={
                    "operation": "scene_reconstruction",
                    "stage": "SPARSE_RECONSTRUCTION",
                    "exit_code": outcome.exit_code,
                    "models": [model.name for model in models],
                },
            )
        return StageOutcome(
            stage="SPARSE_RECONSTRUCTION",
            duration_seconds=outcome.duration_seconds,
            log_path=log_path,
            model_dirs=tuple(models),
            artifacts=tuple(models),
        )

    def undistort(
        self,
        *,
        images_dir: Path,
        model_dir: Path,
        dense_dir: Path,
        log_path: Path,
        on_poll: Callable[[], None] | None = None,
    ) -> StageOutcome:
        dense_dir.mkdir(parents=True, exist_ok=True)
        command = image_undistorter_command(
            self._config, images_dir=images_dir, model_dir=model_dir, dense_dir=dense_dir
        )
        outcome = self._execute(
            "IMAGE_UNDISTORTION",
            command,
            cwd=dense_dir.parent,
            timeout=self._config.timeout_for("IMAGE_UNDISTORTION"),
            log_path=log_path,
            on_poll=on_poll,
            error_code=IMAGE_UNDISTORTION_FAILED,
            error_message="COLMAP image undistortion failed.",
        )
        undistorted_images = dense_dir / "images"
        sparse_dense = dense_dir / "sparse"
        if (
            not undistorted_images.is_dir()
            or not any(undistorted_images.iterdir())
            or not model_is_present(sparse_dense)
        ):
            raise ReconstructionError(
                IMAGE_UNDISTORTION_FAILED,
                "The undistorted workspace is incomplete.",
            )
        return StageOutcome(
            stage="IMAGE_UNDISTORTION",
            duration_seconds=outcome.duration_seconds,
            log_path=log_path,
            artifacts=(undistorted_images, sparse_dense),
        )

    def convert_model(
        self,
        *,
        model_dir: Path,
        output_dir: Path,
        log_path: Path,
        on_poll: Callable[[], None] | None = None,
    ) -> StageOutcome:
        """Convert one sparse model to text for diagnostics and selection."""
        output_dir.mkdir(parents=True, exist_ok=True)
        command = model_converter_command(self._config, model_dir=model_dir, output_dir=output_dir)
        outcome = self._execute(
            "RECONSTRUCTION_VALIDATION",
            command,
            cwd=output_dir.parent,
            timeout=self._config.timeout_for("RECONSTRUCTION_VALIDATION"),
            log_path=log_path,
            on_poll=on_poll,
            error_code=SPARSE_RECONSTRUCTION_FAILED,
            error_message="The sparse reconstruction could not be inspected.",
        )
        files = tuple(output_dir / name for name in ("cameras.txt", "images.txt", "points3D.txt"))
        if not all(path.is_file() for path in files):
            raise ReconstructionError(
                SPARSE_RECONSTRUCTION_FAILED,
                "The sparse reconstruction is missing model files.",
            )
        return StageOutcome(
            stage="RECONSTRUCTION_VALIDATION",
            duration_seconds=outcome.duration_seconds,
            log_path=log_path,
            artifacts=files,
        )


def failure_hint(log_path: Path) -> str:
    """Return the tail of a failed tool log for the worker log."""
    return tail_log(log_path)


__all__ = [
    "ColmapRunner",
    "DatabaseStats",
    "SPARSE_MODEL_FILES",
    "StageOutcome",
    "failure_hint",
    "feature_extraction_command",
    "feature_matching_command",
    "image_undistorter_command",
    "list_model_dirs",
    "mapper_command",
    "model_converter_command",
    "model_is_present",
    "read_database_stats",
]
