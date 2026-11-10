"""Photogrammetry pipeline orchestration (07 Sections 3, 13 and 19).

The orchestrator owns the stage order, checkpointing and diagnostics. It is
independent of Celery and PostgreSQL: the worker adapter supplies the task's
image streams, a task-specific workspace and callbacks for real stage reporting,
heartbeat and cooperative cancellation.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .colmap_runner import ColmapRunner, model_is_present, read_database_stats
from .config import (
    STAGE_ASSET_EXPORT,
    STAGE_DENSE_RECONSTRUCTION,
    STAGE_FEATURE_EXTRACTION,
    STAGE_FEATURE_MATCHING,
    STAGE_IMAGE_PREPARATION,
    STAGE_IMAGE_UNDISTORTION,
    STAGE_MESH_GENERATION,
    STAGE_MESH_REFINEMENT,
    STAGE_OPENMVS_IMPORT,
    STAGE_RECONSTRUCTION_VALIDATION,
    STAGE_RESULT_VALIDATION,
    STAGE_SPARSE_RECONSTRUCTION,
    STAGE_TEXTURING,
    SceneConfig,
)
from .dataset import SceneDataset, SourceImage, prepare_dataset, workspace_paths
from .diagnostics import ReconstructionDiagnostics
from .exceptions import (
    GLB_EXPORT_FAILED,
    GLB_VALIDATION_FAILED,
    TOOL_TIMEOUT,
    SceneCancelled,
    SceneExportError,
    SceneReconstructionError,
    ToolError,
)
from .exporter import find_export_sources, repack_scene, summarize_raw_glb
from .mesh_processor import inspect_mesh
from .openmvs_runner import OpenMvsRunner
from .preflight import check_dataset, check_disk_space, verify_toolchain
from .reconstruction_selector import (
    ReconstructionSelection,
    inspect_model,
    select_reconstruction,
)
from .validator import validate_scene_glb

logger = logging.getLogger(__name__)

DEFAULT_GLB_NAME = "scene.glb"


@dataclass(frozen=True, slots=True)
class SceneArtifact:
    """A validated scene GLB ready for transactional result registration."""

    path: Path
    sha256: str
    file_size_bytes: int
    format: str
    mime_type: str
    metadata: dict[str, Any] = field(default_factory=dict)
    diagnostics_path: Path | None = None


@dataclass(slots=True)
class PipelineCallbacks:
    """Hooks the worker adapter provides; every hook is optional in tests."""

    report_stage: Callable[[str, str], None] = lambda stage, message: None
    heartbeat: Callable[[], None] = lambda: None
    raise_if_cancelled: Callable[[], None] = lambda: None


class PhotogrammetryReconstructor:
    """Run COLMAP and OpenMVS in the documented order for one task."""

    def __init__(
        self,
        config: SceneConfig,
        *,
        callbacks: PipelineCallbacks | None = None,
        colmap: ColmapRunner | None = None,
        openmvs: OpenMvsRunner | None = None,
    ) -> None:
        self._config = config
        self._callbacks = callbacks or PipelineCallbacks()
        self._colmap = colmap or ColmapRunner(config)
        self._openmvs = openmvs or OpenMvsRunner(config)
        self._diagnostics = ReconstructionDiagnostics()
        self._started = 0.0
        self._last_poll = 0.0
        self._dataset: SceneDataset | None = None

    # -- helpers ---------------------------------------------------------

    def _elapsed(self) -> float:
        return time.monotonic() - self._started

    def _poll(self, *, force_heartbeat: bool = False) -> None:
        """Heartbeat/cancellation hook.

        Cancellation is checked on every call so a stop request is observed
        promptly; the lease heartbeat is throttled to once every five seconds so
        a multi-hour reconstruction does not hammer PostgreSQL.
        """
        now = time.monotonic()
        self._callbacks.raise_if_cancelled()
        if force_heartbeat or now - self._last_poll >= 5.0:
            self._last_poll = now
            self._callbacks.heartbeat()
        if self._elapsed() > self._config.max_task_seconds:
            raise ToolError(
                TOOL_TIMEOUT, "The reconstruction exceeded the configured task time limit."
            )

    def _stage(self, stage: str, message: str) -> float:
        """Enter a stage: heartbeat, cancellation, real stage reporting."""
        self._poll(force_heartbeat=True)
        self._callbacks.report_stage(stage, message)
        logger.info(
            "scene_stage_started",
            extra={"operation": "scene_reconstruction", "stage": stage},
        )
        return time.monotonic()

    def _finish_stage(self, stage: str, started: float) -> None:
        duration = time.monotonic() - started
        self._diagnostics.record_stage(stage, duration)
        logger.info(
            "scene_stage_completed",
            extra={
                "operation": "scene_reconstruction",
                "stage": stage,
                "duration_seconds": round(duration, 3),
            },
        )

    def _log_path(self, paths: dict[str, Path], stage: str) -> Path:
        return paths["logs"] / f"{stage.lower()}.log"

    # -- checkpoint helpers ---------------------------------------------

    def _reuse(self, stage: str, valid: bool) -> bool:
        if valid:
            logger.info(
                "scene_stage_reused",
                extra={"operation": "scene_reconstruction", "stage": stage},
            )
        return valid

    # -- pipeline --------------------------------------------------------

    def reconstruct(
        self,
        sources: Sequence[SourceImage],
        *,
        work_dir: Path,
        min_images: int = 3,
        max_images: int = 100,
        max_image_dimension: int = 8192,
    ) -> SceneArtifact:
        """Execute the full reconstruction and return the validated GLB."""
        self._started = time.monotonic()
        plan = Path(work_dir)
        plan.mkdir(parents=True, exist_ok=True)
        paths = workspace_paths(plan)
        for name in ("images", "colmap", "openmvs", "output", "logs"):
            paths[name].mkdir(parents=True, exist_ok=True)

        try:
            dataset = self._prepare(
                sources,
                work_dir=plan,
                min_images=min_images,
                max_images=max_images,
                max_image_dimension=max_image_dimension,
            )
            check_disk_space(plan, min_free_bytes=self._config.min_free_disk_bytes)
            report = verify_toolchain(self._config)
            self._diagnostics.tool_versions = report.as_dict()

            self._sparse_stages(dataset, paths)
            scene_file = self._openmvs_stages(paths)
            artifact = self._export(paths, scene_file)
            self._diagnostics.total_seconds = self._elapsed()
            diagnostics_path = plan / "diagnostics.json"
            self._diagnostics.write(diagnostics_path)
            logger.info(
                "scene_reconstruction_completed",
                extra={
                    "operation": "scene_reconstruction",
                    "vertices": (
                        self._diagnostics.glb.vertices_count if self._diagnostics.glb else 0
                    ),
                    "faces": self._diagnostics.glb.faces_count if self._diagnostics.glb else 0,
                    "duration_seconds": round(self._diagnostics.total_seconds, 3),
                },
            )
            return SceneArtifact(
                path=artifact,
                sha256=self._diagnostics.glb.sha256 if self._diagnostics.glb else "",
                file_size_bytes=(
                    self._diagnostics.glb.file_size_bytes if self._diagnostics.glb else 0
                ),
                format="GLB",
                mime_type="model/gltf-binary",
                metadata=self._result_metadata(),
                diagnostics_path=diagnostics_path,
            )
        except SceneCancelled:
            self._diagnostics.total_seconds = self._elapsed()
            self._write_diagnostics(plan)
            raise
        except SceneReconstructionError as exc:
            self._diagnostics.warnings.append(exc.error_code)
            self._diagnostics.total_seconds = self._elapsed()
            self._write_diagnostics(plan)
            logger.error(
                "scene_reconstruction_failed",
                extra={
                    "operation": "scene_reconstruction",
                    "error_code": exc.error_code,
                    "stage": self._last_stage(),
                },
            )
            raise
        except Exception:
            self._diagnostics.total_seconds = self._elapsed()
            self._write_diagnostics(plan)
            logger.exception(
                "scene_reconstruction_crashed",
                extra={"operation": "scene_reconstruction", "stage": self._last_stage()},
            )
            raise

    def _last_stage(self) -> str | None:
        timings = self._diagnostics.stage_timings
        return next(reversed(timings), None) if timings else None

    def _write_diagnostics(self, work_dir: Path) -> None:
        try:
            self._diagnostics.write(Path(work_dir) / "diagnostics.json")
        except OSError:
            logger.warning(
                "scene_diagnostics_write_failed", extra={"operation": "scene_reconstruction"}
            )

    # -- stage implementations ------------------------------------------

    def _prepare(
        self,
        sources: Sequence[SourceImage],
        *,
        work_dir: Path,
        min_images: int,
        max_images: int,
        max_image_dimension: int,
    ) -> SceneDataset:
        started = self._stage(STAGE_IMAGE_PREPARATION, "Preparing the photograph set")
        dataset = prepare_dataset(
            sources,
            work_dir=work_dir,
            min_images=min_images,
            max_images=max_images,
            max_image_dimension=max_image_dimension,
        )
        check_dataset(dataset, self._config)
        self._dataset = dataset
        self._diagnostics.input_images = len(sources)
        self._diagnostics.unique_images = dataset.image_count
        self._diagnostics.image_formats = dataset.formats
        self._diagnostics.image_dimensions = tuple(
            (image.width, image.height) for image in dataset.images
        )
        self._diagnostics.duplicate_images = dataset.duplicates
        self._diagnostics.warnings.extend(dataset.warnings)
        self._finish_stage(STAGE_IMAGE_PREPARATION, started)
        return dataset

    def _sparse_stages(
        self, dataset: SceneDataset, paths: dict[str, Path]
    ) -> ReconstructionSelection:
        images_dir = paths["images"]
        database_path = paths["colmap"] / "database.db"
        sparse_dir = paths["colmap_sparse"]

        # 1. Feature extraction (reused only when the database is complete).
        started = self._stage(STAGE_FEATURE_EXTRACTION, "Extracting image features")
        reusable = False
        if database_path.is_file():
            try:
                stats = read_database_stats(database_path)
                reusable = stats.images == dataset.image_count and stats.keypoints > 0
            except SceneReconstructionError:
                reusable = False
        if self._reuse(STAGE_FEATURE_EXTRACTION, reusable):
            self._diagnostics.database = read_database_stats(database_path)
        else:
            # A partial or inconsistent database is never extended: restart the
            # stage from a clean database (07 Section 13.6).
            database_path.unlink(missing_ok=True)
            outcome = self._colmap.extract_features(
                images_dir=images_dir,
                database_path=database_path,
                log_path=self._log_path(paths, STAGE_FEATURE_EXTRACTION),
                expected_images=dataset.image_count,
                on_poll=self._poll,
            )
            self._diagnostics.database = outcome.database
        self._finish_stage(STAGE_FEATURE_EXTRACTION, started)

        # 2. Feature matching (reused when verified matches and connectivity exist).
        started = self._stage(STAGE_FEATURE_MATCHING, "Matching features across photographs")
        reusable = False
        if database_path.is_file():
            try:
                stats = read_database_stats(database_path)
                reusable = stats.verified_pairs > 0 and stats.largest_component >= 2
            except SceneReconstructionError:
                reusable = False
        if self._reuse(STAGE_FEATURE_MATCHING, reusable):
            self._diagnostics.database = read_database_stats(database_path)
        else:
            outcome = self._colmap.match_features(
                database_path=database_path,
                log_path=self._log_path(paths, STAGE_FEATURE_MATCHING),
                on_poll=self._poll,
            )
            self._diagnostics.database = outcome.database
        self._finish_stage(STAGE_FEATURE_MATCHING, started)

        # 3. Sparse reconstruction / camera estimation.
        started = self._stage(STAGE_SPARSE_RECONSTRUCTION, "Reconstructing camera poses")
        existing = (
            [model for model in sparse_dir.iterdir() if model.is_dir()]
            if sparse_dir.is_dir()
            else []
        )
        if self._reuse(STAGE_SPARSE_RECONSTRUCTION, bool(existing)):
            models = existing
        else:
            outcome = self._colmap.reconstruct_sparse(
                images_dir=images_dir,
                database_path=database_path,
                sparse_dir=sparse_dir,
                log_path=self._log_path(paths, STAGE_SPARSE_RECONSTRUCTION),
                on_poll=self._poll,
            )
            models = list(outcome.model_dirs)
        self._finish_stage(STAGE_SPARSE_RECONSTRUCTION, started)

        # 4. Inspection, component detection and selection.
        started = self._stage(
            STAGE_RECONSTRUCTION_VALIDATION, "Validating the sparse reconstruction"
        )
        text_root = paths["colmap"] / "models_txt"
        candidates = []
        for model_dir in sorted(models):
            text_dir = text_root / Path(model_dir).name
            if not all(
                (text_dir / name).is_file()
                for name in ("cameras.txt", "images.txt", "points3D.txt")
            ):
                self._colmap.convert_model(
                    model_dir=Path(model_dir),
                    output_dir=text_dir,
                    log_path=self._log_path(paths, STAGE_RECONSTRUCTION_VALIDATION),
                    on_poll=self._poll,
                )
            candidates.append(inspect_model(Path(model_dir), text_dir, dataset.image_count))
        selection = select_reconstruction(candidates, self._config)
        self._diagnostics.record_selection(selection)
        self._finish_stage(STAGE_RECONSTRUCTION_VALIDATION, started)

        # 5. Image undistortion for the selected model.
        started = self._stage(STAGE_IMAGE_UNDISTORTION, "Undistorting images for dense matching")
        dense_dir = paths["colmap_dense"]
        reusable = (
            (dense_dir / "images").is_dir()
            and any((dense_dir / "images").iterdir())
            and model_is_present(dense_dir / "sparse")
        )
        if not self._reuse(STAGE_IMAGE_UNDISTORTION, reusable):
            self._colmap.undistort(
                images_dir=images_dir,
                model_dir=selection.selected.model_dir,
                dense_dir=dense_dir,
                log_path=self._log_path(paths, STAGE_IMAGE_UNDISTORTION),
                on_poll=self._poll,
            )
        self._finish_stage(STAGE_IMAGE_UNDISTORTION, started)
        return selection

    def _openmvs_stages(
        self,
        paths: dict[str, Path],
    ) -> Path:
        check_disk_space(paths["root"], min_free_bytes=self._config.min_free_disk_bytes)
        dense_dir = paths["colmap_dense"]
        work = paths["openmvs"]
        scene_file = work / "scene.mvs"
        dense_scene = work / "scene_dense.mvs"
        mesh_path = work / "scene_dense_mesh.ply"
        refined_mesh = work / "scene_dense_mesh_refine.ply"
        textured_mesh = work / "scene_dense_mesh_refine_texture.ply"

        # 6. InterfaceCOLMAP import.
        started = self._stage(STAGE_OPENMVS_IMPORT, "Importing the reconstruction into OpenMVS")
        if not self._reuse(
            STAGE_OPENMVS_IMPORT, scene_file.is_file() and scene_file.stat().st_size > 0
        ):
            outcome = self._openmvs.import_scene(
                dense_dir=dense_dir,
                scene_file=scene_file,
                work_dir=work,
                log_path=self._log_path(paths, STAGE_OPENMVS_IMPORT),
                on_poll=self._poll,
            )
        self._finish_stage(STAGE_OPENMVS_IMPORT, started)

        # 7. Dense reconstruction.
        started = self._stage(STAGE_DENSE_RECONSTRUCTION, "Reconstructing the dense point cloud")
        if not self._reuse(
            STAGE_DENSE_RECONSTRUCTION, dense_scene.is_file() and dense_scene.stat().st_size > 0
        ):
            outcome = self._openmvs.densify(
                scene_file=scene_file,
                dense_scene=dense_scene,
                work_dir=work,
                log_path=self._log_path(paths, STAGE_DENSE_RECONSTRUCTION),
                on_poll=self._poll,
            )
            self._diagnostics.dense_points = outcome.dense_points
        self._finish_stage(STAGE_DENSE_RECONSTRUCTION, started)

        # 8. Mesh generation.
        started = self._stage(STAGE_MESH_GENERATION, "Generating the polygonal mesh")
        reusable = False
        if mesh_path.is_file():
            try:
                self._diagnostics.mesh = inspect_mesh(mesh_path)
                reusable = True
            except SceneReconstructionError:
                reusable = False
        if not self._reuse(STAGE_MESH_GENERATION, reusable):
            outcome = self._openmvs.reconstruct_mesh(
                dense_scene=dense_scene,
                mesh_path=mesh_path,
                work_dir=work,
                log_path=self._log_path(paths, STAGE_MESH_GENERATION),
                on_poll=self._poll,
            )
            self._diagnostics.mesh = outcome.mesh
        self._finish_stage(STAGE_MESH_GENERATION, started)

        # 9. Optional mesh refinement (produces a refined PLY mesh).
        if self._config.enable_mesh_refinement:
            started = self._stage(STAGE_MESH_REFINEMENT, "Refining the reconstructed mesh")
            reusable = False
            if refined_mesh.is_file():
                try:
                    self._diagnostics.refined_mesh = inspect_mesh(refined_mesh)
                    reusable = True
                except SceneReconstructionError:
                    reusable = False
            if not self._reuse(STAGE_MESH_REFINEMENT, reusable):
                outcome = self._openmvs.refine_mesh(
                    dense_scene=dense_scene,
                    mesh_path=mesh_path,
                    refined_mesh=refined_mesh,
                    work_dir=work,
                    log_path=self._log_path(paths, STAGE_MESH_REFINEMENT),
                    on_poll=self._poll,
                )
                self._diagnostics.refined_mesh = outcome.mesh
            self._finish_stage(STAGE_MESH_REFINEMENT, started)
            texture_mesh = refined_mesh
        else:
            logger.info(
                "scene_stage_skipped",
                extra={"operation": "scene_reconstruction", "stage": STAGE_MESH_REFINEMENT},
            )
            texture_mesh = mesh_path

        # 10. Optional texturing.
        if self._config.enable_texture_generation:
            started = self._stage(STAGE_TEXTURING, "Generating scene textures")
            reusable = False
            textures = [
                path
                for path in work.iterdir()
                if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg"}
            ]
            if textured_mesh.is_file() and textures:
                reusable = True
                self._diagnostics.texture_count = len(textures)
            if not self._reuse(STAGE_TEXTURING, reusable):
                outcome = self._openmvs.texture(
                    dense_scene=dense_scene,
                    mesh_path=texture_mesh,
                    textured_mesh=textured_mesh,
                    work_dir=work,
                    log_path=self._log_path(paths, STAGE_TEXTURING),
                    on_poll=self._poll,
                )
                texture_files = [
                    path
                    for path in outcome.artifacts
                    if path.suffix.lower() in {".png", ".jpg", ".jpeg"}
                ]
                self._diagnostics.texture_count = len(texture_files)
            self._finish_stage(STAGE_TEXTURING, started)
        else:
            logger.info(
                "scene_stage_skipped",
                extra={"operation": "scene_reconstruction", "stage": STAGE_TEXTURING},
            )

        return dense_scene

    def _export(self, paths: dict[str, Path], export_scene: Path) -> Path:
        work = paths["openmvs"]
        output = paths["output"] / DEFAULT_GLB_NAME
        require_textures = self._config.enable_texture_generation
        if require_textures:
            attach_mesh = work / "scene_dense_mesh_refine_texture.ply"
        elif self._config.enable_mesh_refinement:
            attach_mesh = work / "scene_dense_mesh_refine.ply"
        else:
            attach_mesh = work / "scene_dense_mesh.ply"

        started = self._stage(STAGE_ASSET_EXPORT, "Exporting the scene as GLB")
        if output.is_file() and output.stat().st_size > 0:
            try:
                self._diagnostics.glb = validate_scene_glb(
                    output, require_textures=require_textures
                )
                self._finish_stage(STAGE_ASSET_EXPORT, started)
                return output
            except SceneExportError:
                output.unlink(missing_ok=True)

        obj_dir = work / "export_obj"
        glb_dir = work / "export_glb"
        obj_dir.mkdir(parents=True, exist_ok=True)
        glb_dir.mkdir(parents=True, exist_ok=True)
        self._openmvs.transform(
            scene_file=export_scene,
            output_base=obj_dir / "scene",
            export_type="obj",
            work_dir=work,
            log_path=self._log_path(paths, STAGE_ASSET_EXPORT),
            on_poll=self._poll,
            mesh_file=attach_mesh,
        )
        self._openmvs.transform(
            scene_file=export_scene,
            output_base=glb_dir / "scene",
            export_type="glb",
            work_dir=work,
            log_path=self._log_path(paths, STAGE_ASSET_EXPORT),
            on_poll=self._poll,
            mesh_file=attach_mesh,
        )
        raw_glbs = find_export_sources(glb_dir, export_type="glb")
        if raw_glbs:
            try:
                self._diagnostics.raw_export = summarize_raw_glb(raw_glbs[0]).as_metadata()
            except SceneExportError:
                self._diagnostics.raw_export = {"error": GLB_VALIDATION_FAILED}

        sources = find_export_sources(obj_dir, export_type="obj") + raw_glbs
        validation = repack_scene(
            sources,
            output,
            require_textures=self._config.enable_texture_generation,
        )
        self._diagnostics.glb = validation
        self._finish_stage(STAGE_ASSET_EXPORT, started)

        # Final validation is an independently identifiable stage.
        started = self._stage(STAGE_RESULT_VALIDATION, "Validating the final scene asset")
        final = validate_scene_glb(output, require_textures=self._config.enable_texture_generation)
        if final.sha256 != validation.sha256 or final.file_size_bytes != validation.file_size_bytes:
            raise SceneExportError(GLB_EXPORT_FAILED, "The exported GLB changed after validation.")
        self._diagnostics.glb = final
        self._finish_stage(STAGE_RESULT_VALIDATION, started)
        return output

    def _result_metadata(self) -> dict[str, Any]:
        metadata = self._diagnostics.as_metadata()
        glb = self._diagnostics.glb
        if glb is not None:
            metadata.update(
                {
                    "vertices_count": glb.vertices_count,
                    "faces_count": glb.faces_count,
                    "materials_count": glb.materials_count,
                    "textures_count": glb.textures_count,
                    "bounding_box": glb.bounding_box,
                    "has_texture_coordinates": glb.has_texture_coordinates,
                }
            )
        metadata["reconstruction"] = self._config.as_manifest()
        metadata["format"] = "GLB"
        return metadata


def build_artifact_metadata(
    diagnostics: ReconstructionDiagnostics, config: SceneConfig
) -> dict[str, Any]:
    """Compatibility helper for callers that only hold diagnostics."""
    metadata = diagnostics.as_metadata()
    metadata["reconstruction"] = config.as_manifest()
    return metadata


__all__ = [
    "DEFAULT_GLB_NAME",
    "PhotogrammetryReconstructor",
    "PipelineCallbacks",
    "SceneArtifact",
    "build_artifact_metadata",
]
