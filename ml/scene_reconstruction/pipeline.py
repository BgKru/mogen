"""Photogrammetry pipeline orchestration (07 Sections 3, 13 and 19).

The orchestrator owns the stage order, checkpointing and diagnostics. It is
independent of Celery and PostgreSQL: the worker adapter supplies the task's
image streams, a task-specific workspace and callbacks for real stage reporting,
heartbeat and cooperative cancellation.
"""

from __future__ import annotations

import json
import logging
import shutil
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from image_quality import (
    EXACT_DUPLICATE,
    QUALITY_ANALYSIS_UNAVAILABLE,
    QualityInput,
    analyze_images,
)
from mesh_enhancement import (
    MeshEnhancementManifestError,
    build_enhancement_manifest,
    read_enhancement_manifest,
    write_enhancement_manifest,
)
from PIL import Image

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
    STAGE_SPLAT_DATASET_PREPARATION,
    STAGE_SPLAT_EXPORT,
    STAGE_SPLAT_TRAINING,
    STAGE_TEXTURING,
    SceneConfig,
)
from .dataset import SceneDataset, SourceImage, prepare_dataset, workspace_paths
from .diagnostics import ReconstructionDiagnostics
from .enhancement import enhance_scene
from .exceptions import (
    GLB_EXPORT_FAILED,
    GLB_VALIDATION_FAILED,
    QUALITY_ANALYSIS_FAILED,
    TOOL_TIMEOUT,
    SceneCancelled,
    SceneExportError,
    SceneReconstructionError,
    ToolError,
    is_recoverable_feature_failure,
)
from .exporter import find_export_sources, repack_scene, summarize_raw_glb
from .feature_matching import (
    FeatureBackend,
    build_feature_backend,
    build_feature_manifest,
    feature_manifest_path,
    manifest_matches,
    write_feature_manifest,
)
from .feature_profiles import (
    BACKEND_COLMAP_SIFT,
    PROFILE_SIFT_DEFAULT,
)
from .mesh_processor import inspect_mesh
from .neural_pipeline import NeuralReconstructor, SplatArtifact, build_splat_manifest
from .openmvs_runner import OpenMvsRunner
from .preflight import check_dataset, check_disk_space, verify_toolchain
from .reconstruction_selector import (
    ReconstructionSelection,
    inspect_model,
    select_reconstruction,
)
from .splat_config import REPRESENTATION_GAUSSIAN_SPLAT, SPLAT_FORMAT, SPLAT_MIME_TYPE
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
        # Stage methods are also exercised directly by tests and by tooling that
        # skips reconstruct(); initialise the clock here so a direct call cannot
        # inherit a zero start time and falsely trip the task budget.
        self._started = time.monotonic()
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
        """Execute the configured representation and return its validated asset.

        ``mesh`` runs the released COLMAP + OpenMVS path unchanged. ``gaussian_splat``
        shares image preparation, feature extraction/matching, sparse
        reconstruction, selection and undistortion, then trains Splatfacto and
        exports a Gaussian PLY; no OpenMVS or GLB stage runs (15 Section 4.1).
        """
        if self._config.is_gaussian_splat:
            return self._reconstruct_splat(
                sources,
                work_dir=work_dir,
                min_images=min_images,
                max_images=max_images,
                max_image_dimension=max_image_dimension,
            )
        return self._reconstruct_mesh(
            sources,
            work_dir=work_dir,
            min_images=min_images,
            max_images=max_images,
            max_image_dimension=max_image_dimension,
        )

    def _new_workspace(self, work_dir: Path, *, splat: bool) -> tuple[Path, dict[str, Path]]:
        plan = Path(work_dir)
        plan.mkdir(parents=True, exist_ok=True)
        paths = workspace_paths(plan)
        names = ["images", "colmap", "openmvs", "output", "logs"]
        if splat:
            names = ["images", "colmap", "output", "logs"]
        for name in names:
            paths[name].mkdir(parents=True, exist_ok=True)
        return plan, paths

    def _reconstruct_mesh(
        self,
        sources: Sequence[SourceImage],
        *,
        work_dir: Path,
        min_images: int = 3,
        max_images: int = 100,
        max_image_dimension: int = 8192,
    ) -> SceneArtifact:
        """Execute the full mesh reconstruction and return the validated GLB."""
        self._started = time.monotonic()
        self._diagnostics.representation = "MESH"
        self._diagnostics.method = "COLMAP_OPENMVS"
        plan, paths = self._new_workspace(work_dir, splat=False)

        try:
            dataset = self._prepare(
                sources,
                work_dir=plan,
                min_images=min_images,
                max_images=max_images,
                max_image_dimension=max_image_dimension,
                paths=paths,
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

    def _reconstruct_splat(
        self,
        sources: Sequence[SourceImage],
        *,
        work_dir: Path,
        min_images: int = 3,
        max_images: int = 100,
        max_image_dimension: int = 8192,
    ) -> SceneArtifact:
        """Share COLMAP sparse reconstruction, then train and export a splat."""
        self._started = time.monotonic()
        self._diagnostics.representation = REPRESENTATION_GAUSSIAN_SPLAT
        self._diagnostics.method = self._config.method
        plan, paths = self._new_workspace(work_dir, splat=True)
        try:
            dataset = self._prepare(
                sources,
                work_dir=plan,
                min_images=min_images,
                max_images=max_images,
                max_image_dimension=max_image_dimension,
                paths=paths,
            )
            check_disk_space(plan, min_free_bytes=self._config.min_free_disk_bytes)
            # Only COLMAP is needed: OpenMVS must never be invoked for a splat.
            report = verify_toolchain(self._config, include_openmvs=False)
            self._diagnostics.tool_versions = report.as_dict()

            self._sparse_stages(dataset, paths)
            dense_images = paths["colmap_dense"] / "images"
            dense_model = paths["colmap_dense"] / "sparse"
            if not model_is_present(dense_model):
                raise SceneExportError(
                    GLB_EXPORT_FAILED, "The undistorted COLMAP model is unavailable."
                )

            neural = NeuralReconstructor(self._config)
            # Admission happens before any GPU allocation; the runtime probe
            # proves the pinned stack can execute kernels in this worker.
            vram = neural.check_vram()
            runtime = neural.runtime_report()
            self._diagnostics.splat_runtime = runtime.as_metadata()
            self._diagnostics.splat_device = (
                vram.as_metadata() if vram is not None else {"device": "cpu"}
            )

            started = self._stage(
                STAGE_SPLAT_DATASET_PREPARATION, "Preparing the splat training dataset"
            )
            nerfstudio_dataset = neural.prepare(
                dataset,
                model_dir=dense_model,
                images_dir=dense_images,
                work_dir=plan,
                runtime=runtime,
                on_poll=self._poll,
            )
            self._diagnostics.splat_dataset = nerfstudio_dataset.as_metadata()
            expected_manifest = build_splat_manifest(
                dataset=nerfstudio_dataset, runtime=runtime, splat=self._config.splat
            )
            artifact: SplatArtifact | None = neural.reuse_existing(
                work_dir=plan, expected_manifest=expected_manifest
            )
            self._finish_stage(STAGE_SPLAT_DATASET_PREPARATION, started)

            if artifact is None:
                neural.clear_stale_outputs(plan)
                started = self._stage(STAGE_SPLAT_TRAINING, "Training the Gaussian splat")
                remaining = max(60, int(self._config.max_task_seconds - self._elapsed()))
                training = neural.train(
                    dataset=nerfstudio_dataset,
                    work_dir=plan,
                    timeout=min(self._config.timeout_for(STAGE_SPLAT_TRAINING), remaining),
                    on_poll=self._poll,
                )
                self._diagnostics.splat_training = {
                    key: training.summary.get(key)
                    for key in (
                        "iterations",
                        "steps_per_save",
                        "train_seconds",
                        "sh_degree",
                        "seed",
                        "device",
                        "checkpoint_count",
                        "metrics",
                    )
                }
                self._finish_stage(STAGE_SPLAT_TRAINING, started)

                started = self._stage(
                    STAGE_SPLAT_EXPORT, "Exporting and validating the Gaussian PLY"
                )
                export = neural.export(checkpoint_path=training.checkpoint_path, work_dir=plan)
                self._diagnostics.splat_artifact = export.as_metadata()
                artifact = neural.build_artifact(
                    export=export,
                    dataset=nerfstudio_dataset,
                    training=training,
                    runtime=runtime,
                    vram=vram,
                    work_dir=plan,
                    expected_manifest=expected_manifest,
                )
                self._finish_stage(STAGE_SPLAT_EXPORT, started)
            else:
                self._diagnostics.splat_artifact = artifact.metadata.get("artifact")

            self._diagnostics.total_seconds = self._elapsed()
            diagnostics_path = plan / "diagnostics.json"
            self._diagnostics.write(diagnostics_path)
            logger.info(
                "splat_reconstruction_completed",
                extra={
                    "operation": "scene_reconstruction",
                    "gaussians": artifact.metadata.get("artifact", {}).get("gaussian_count"),
                    "duration_seconds": round(self._diagnostics.total_seconds, 3),
                    "reused": artifact.reused,
                },
            )
            return SceneArtifact(
                path=artifact.path,
                sha256=artifact.sha256,
                file_size_bytes=artifact.file_size_bytes,
                format=SPLAT_FORMAT,
                mime_type=SPLAT_MIME_TYPE,
                metadata=self._splat_result_metadata(artifact),
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
                "splat_reconstruction_failed",
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
                "splat_reconstruction_crashed",
                extra={"operation": "scene_reconstruction", "stage": self._last_stage()},
            )
            raise

    def _splat_result_metadata(self, artifact: SplatArtifact) -> dict[str, Any]:
        """Merge shared diagnostics with the neural artifact's compact metadata."""
        metadata = self._diagnostics.as_metadata()
        # A splat is not a mesh: drop the mesh-only keys instead of persisting
        # nulls that could be mistaken for measured values.
        for key in (
            "glb_validation",
            "mesh",
            "refined_mesh",
            "dense_points",
            "texture_count",
            "raw_export",
            "enhancement",
        ):
            metadata.pop(key, None)
        metadata.update(artifact.metadata)
        metadata["format"] = SPLAT_FORMAT
        metadata["representation"] = REPRESENTATION_GAUSSIAN_SPLAT
        metadata["reconstruction"] = self._config.as_manifest()
        return metadata

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
        paths: dict[str, Path],
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
        # 11 Section 8.1: analysis runs after the immutable snapshot has been
        # copied and validated, and before COLMAP feature extraction starts.
        self._analyze_quality(dataset, paths)
        self._finish_stage(STAGE_IMAGE_PREPARATION, started)
        return dataset

    def _analyze_quality(self, dataset: SceneDataset, paths: dict[str, Path]) -> None:
        """Run the advisory analyzer and persist its task-local report.

        Exact duplicates never reach this point: ``prepare_dataset`` rejects
        them with ``DUPLICATE_IMAGES`` through its SHA-256 check. This stage only
        adds technical findings and perceptual near-duplicate candidates; it
        never removes an image or blocks COLMAP.
        """
        quality_config = self._config.image_quality
        if not quality_config.enabled:
            return
        started = time.monotonic()

        def inputs():
            for prepared in dataset.images:
                with Image.open(prepared.path) as opened:
                    opened.load()
                    # ``copy`` detaches the loaded pixels from the file handle,
                    # so the analyzer never keeps 100 full-size images open.
                    yield QualityInput(
                        opened.copy(),
                        image_id=prepared.image_id,
                        filename=prepared.original_filename,
                    )

        try:
            result = analyze_images(
                inputs(),
                config=quality_config,
                on_progress=lambda _index, _total: self._poll(),
            )
        except (SceneCancelled, SceneReconstructionError):
            raise
        except Exception as exc:
            self._diagnostics.image_quality_seconds = time.monotonic() - started
            if quality_config.required:
                logger.exception(
                    "scene_quality_analysis_failed",
                    extra={"operation": "scene_reconstruction"},
                )
                raise SceneReconstructionError(
                    QUALITY_ANALYSIS_FAILED,
                    "The image quality analysis stage failed.",
                ) from exc
            logger.warning(
                "scene_quality_analysis_unavailable",
                extra={"operation": "scene_reconstruction"},
            )
            self._diagnostics.image_quality = {
                "status": "UNAVAILABLE",
                "error_code": QUALITY_ANALYSIS_UNAVAILABLE,
            }
            self._diagnostics.warnings.append(QUALITY_ANALYSIS_UNAVAILABLE)
            return

        document = result.as_dict()
        document["status"] = "OK"
        # State the exact/near distinction explicitly. SHA-256 byte duplicates
        # are handled by the dataset preparation step above and are absent
        # here by construction.
        document["exact_duplicates"] = {
            "detector": "sha256",
            "finding_code": EXACT_DUPLICATE,
            "handled_by": "dataset_preparation",
        }
        self._diagnostics.image_quality = document
        self._diagnostics.image_quality_seconds = time.monotonic() - started
        self._write_quality_report(paths["diagnostics"] / "image_quality.json", document)

    def _write_quality_report(self, path: Path, document: dict[str, Any]) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(document, indent=2, sort_keys=True), encoding="utf-8")
        except OSError:
            logger.warning(
                "scene_quality_report_write_failed",
                extra={"operation": "scene_reconstruction"},
            )

    def _sparse_stages(
        self, dataset: SceneDataset, paths: dict[str, Path]
    ) -> ReconstructionSelection:
        images_dir = paths["images"]
        database_path = paths["colmap"] / "database.db"
        sparse_dir = paths["colmap_sparse"]
        manifest_path = feature_manifest_path(paths["colmap"])
        colmap_version = self._diagnostics.tool_versions.get("colmap", "")
        profile = self._config.resolved_feature_profile
        backend = build_feature_backend(self._config, colmap_runner=self._colmap)
        self._diagnostics.feature_backend = self._config.feature_backend
        self._diagnostics.feature_profile = profile.name
        self._diagnostics.feature_actual_backend = backend.name
        expected_manifest = build_feature_manifest(
            dataset, self._config, backend=backend.name, colmap_version=colmap_version
        )

        # 1. Feature extraction (reused only when the manifest and database match).
        started = self._stage(STAGE_FEATURE_EXTRACTION, "Extracting image features")
        stats = self._database_stats(database_path)
        reusable = (
            manifest_matches(manifest_path, expected_manifest)
            and stats is not None
            and stats.images == dataset.image_count
            and stats.keypoints > 0
        )
        if self._reuse(STAGE_FEATURE_EXTRACTION, reusable):
            self._diagnostics.database = stats
        else:
            # A partial, inconsistent or differently configured database is
            # never extended: rebuild from a clean workspace (07 Section 13.6).
            self._invalidate_feature_outputs(paths)
            try:
                backend, expected_manifest = self._prepare_feature_backend(
                    backend=backend,
                    dataset=dataset,
                    paths=paths,
                    expected_manifest=expected_manifest,
                    colmap_version=colmap_version,
                )
                extraction = backend.extract_features(
                    dataset,
                    images_dir=images_dir,
                    database_path=database_path,
                    work_dir=paths["root"],
                    on_poll=self._poll,
                )
            except SceneCancelled:
                raise
            except SceneReconstructionError as exc:
                backend, expected_manifest = self._maybe_feature_fallback(
                    exc,
                    backend=backend,
                    dataset=dataset,
                    paths=paths,
                    expected_manifest=expected_manifest,
                    colmap_version=colmap_version,
                )
                self._invalidate_feature_outputs(paths)
                extraction = backend.extract_features(
                    dataset,
                    images_dir=images_dir,
                    database_path=database_path,
                    work_dir=paths["root"],
                    on_poll=self._poll,
                )
            self._diagnostics.feature_extraction = extraction.as_metadata()
            self._diagnostics.database = read_database_stats(database_path)
            write_feature_manifest(manifest_path, expected_manifest)
        self._finish_stage(STAGE_FEATURE_EXTRACTION, started)

        # 2. Feature matching (reused when the manifest, verified matches and
        # connectivity exist). A backend/profile change invalidates both stages.
        started = self._stage(STAGE_FEATURE_MATCHING, "Matching features across photographs")
        stats = self._database_stats(database_path)
        reusable = (
            manifest_matches(manifest_path, expected_manifest)
            and stats is not None
            and stats.verified_pairs > 0
            and stats.largest_component >= 2
        )
        if self._reuse(STAGE_FEATURE_MATCHING, reusable):
            self._diagnostics.database = stats
        else:
            self._invalidate_sparse_outputs(paths)
            try:
                matching = backend.match_features(
                    dataset,
                    images_dir=images_dir,
                    database_path=database_path,
                    work_dir=paths["root"],
                    on_poll=self._poll,
                )
            except SceneCancelled:
                raise
            except SceneReconstructionError as exc:
                backend, expected_manifest = self._maybe_feature_fallback(
                    exc,
                    backend=backend,
                    dataset=dataset,
                    paths=paths,
                    expected_manifest=expected_manifest,
                    colmap_version=colmap_version,
                )
                # Fallback requires a clean SIFT database and clean dependants.
                self._invalidate_feature_outputs(paths)
                extraction = backend.extract_features(
                    dataset,
                    images_dir=images_dir,
                    database_path=database_path,
                    work_dir=paths["root"],
                    on_poll=self._poll,
                )
                self._diagnostics.feature_extraction = extraction.as_metadata()
                write_feature_manifest(manifest_path, expected_manifest)
                matching = backend.match_features(
                    dataset,
                    images_dir=images_dir,
                    database_path=database_path,
                    work_dir=paths["root"],
                    on_poll=self._poll,
                )
            self._diagnostics.feature_matching = matching.as_metadata()
            self._diagnostics.database = read_database_stats(database_path)
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

    def _database_stats(self, database_path: Path):
        """Return database statistics or ``None`` when the database is unusable."""
        if not Path(database_path).is_file():
            return None
        try:
            return read_database_stats(database_path)
        except SceneReconstructionError:
            return None

    def _prepare_feature_backend(
        self,
        *,
        backend: FeatureBackend,
        dataset: SceneDataset,
        paths: dict[str, Path],
        expected_manifest: dict[str, Any],
        colmap_version: str,
    ) -> tuple[FeatureBackend, dict[str, Any]]:
        """Verify the backend runtime before the first expensive stage runs."""
        runtime = backend.verify_runtime(self._config)
        self._diagnostics.feature_versions = dict(runtime.versions)
        return backend, expected_manifest

    def _maybe_feature_fallback(
        self,
        error: SceneReconstructionError,
        *,
        backend: FeatureBackend,
        dataset: SceneDataset,
        paths: dict[str, Path],
        expected_manifest: dict[str, Any],
        colmap_version: str,
    ) -> tuple[FeatureBackend, dict[str, Any]]:
        """Return a clean SIFT backend when fallback is configured and safe.

        Invalid datasets, deterministic configuration errors and disabled
        fallback are re-raised unchanged so they are not hidden behind SIFT.
        """
        if backend.name == BACKEND_COLMAP_SIFT:
            raise error
        if not self._config.feature_fallback_to_sift or not is_recoverable_feature_failure(error):
            raise error
        reason = getattr(error, "error_code", "FEATURE_BACKEND_FAILED")
        logger.warning(
            "feature_fallback_to_sift",
            extra={
                "operation": "scene_reconstruction",
                "requested_backend": backend.name,
                "reason": reason,
            },
        )
        self._diagnostics.feature_fallback_used = True
        self._diagnostics.feature_fallback_reason = reason
        sift_config = replace(
            self._config,
            feature_backend=BACKEND_COLMAP_SIFT,
            feature_profile=PROFILE_SIFT_DEFAULT,
        )
        sift_backend = build_feature_backend(sift_config, colmap_runner=self._colmap)
        self._diagnostics.feature_actual_backend = sift_backend.name
        manifest = build_feature_manifest(
            dataset, sift_config, backend=sift_backend.name, colmap_version=colmap_version
        )
        return sift_backend, manifest

    def _invalidate_feature_outputs(self, paths: dict[str, Path]) -> None:
        """Delete feature checkpoints and every output that depends on them."""
        colmap_dir = paths["colmap"]
        for name in (
            "database.db",
            "database.db.tmp",
            "features.npz",
            "features.npz.tmp",
            "feature_manifest.json",
            "feature_manifest.json.tmp",
            "pairs.txt",
        ):
            (colmap_dir / name).unlink(missing_ok=True)
        self._invalidate_sparse_outputs(paths)

    def _invalidate_sparse_outputs(self, paths: dict[str, Path]) -> None:
        """Delete sparse/dense/OpenMVS outputs that consumed the features.

        The workspace directories are recreated because later stages expect
        them to exist even when their previous contents were invalidated.
        """
        for key in ("colmap_sparse", "colmap_dense", "openmvs", "output"):
            target = paths.get(key)
            if target is None:
                continue
            if Path(target).is_dir():
                shutil.rmtree(target, ignore_errors=True)
            Path(target).mkdir(parents=True, exist_ok=True)
        text_root = paths["colmap"] / "models_txt"
        if text_root.is_dir():
            shutil.rmtree(text_root, ignore_errors=True)
        (paths["colmap"] / "pairs.txt").unlink(missing_ok=True)

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
        enhancement_enabled = self._config.enhancement.postprocess_enabled
        if require_textures:
            attach_mesh = work / "scene_dense_mesh_refine_texture.ply"
        elif self._config.enable_mesh_refinement:
            attach_mesh = work / "scene_dense_mesh_refine.ply"
        else:
            attach_mesh = work / "scene_dense_mesh.ply"
        enhancement_manifest_path = work / "enhancement_manifest.json"
        enhancement_metadata_path = work / "enhancement_metadata.json"
        expected_manifest = self._expected_enhancement_manifest(attach_mesh)

        started = self._stage(STAGE_ASSET_EXPORT, "Exporting the scene as GLB")
        if output.is_file() and output.stat().st_size > 0:
            try:
                cached = validate_scene_glb(output, require_textures=require_textures)
            except SceneExportError:
                output.unlink(missing_ok=True)
            else:
                if not enhancement_enabled or self._enhancement_cache_matches(
                    enhancement_manifest_path, enhancement_metadata_path, expected_manifest
                ):
                    self._diagnostics.glb = cached
                    if enhancement_enabled:
                        self._diagnostics.enhancement = self._read_enhancement_metadata(
                            enhancement_metadata_path
                        )
                    self._finish_stage(STAGE_ASSET_EXPORT, started)
                    return output
                # The enhancement settings, dependency versions or the source
                # mesh changed: the cached post-processed GLB is invalid.
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

        enhancement_result: Any = None

        def _enhance(scene: Any) -> tuple[Any, bool]:
            nonlocal enhancement_result
            enhancement_result = enhance_scene(
                scene,
                self._config.enhancement,
                on_poll=self._poll,
            )
            return scene, enhancement_result.normal_export

        sources = find_export_sources(obj_dir, export_type="obj") + raw_glbs
        validation = repack_scene(
            sources,
            output,
            require_textures=self._config.enable_texture_generation,
            enhance=_enhance if enhancement_enabled else None,
        )
        self._diagnostics.glb = validation
        if enhancement_enabled and enhancement_result is not None:
            self._diagnostics.enhancement = enhancement_result.as_metadata()
            if expected_manifest is not None:
                write_enhancement_manifest(enhancement_manifest_path, expected_manifest)
            self._write_enhancement_metadata(
                enhancement_metadata_path, self._diagnostics.enhancement
            )
        self._finish_stage(STAGE_ASSET_EXPORT, started)

        # Final validation is an independently identifiable stage.
        started = self._stage(STAGE_RESULT_VALIDATION, "Validating the final scene asset")
        final = validate_scene_glb(output, require_textures=self._config.enable_texture_generation)
        if final.sha256 != validation.sha256 or final.file_size_bytes != validation.file_size_bytes:
            raise SceneExportError(GLB_EXPORT_FAILED, "The exported GLB changed after validation.")
        self._diagnostics.glb = final
        self._finish_stage(STAGE_RESULT_VALIDATION, started)
        return output

    def _expected_enhancement_manifest(self, attach_mesh: Path) -> dict[str, Any] | None:
        """Return the cache key for the post-processed export, when enabled."""
        if not self._config.enhancement.postprocess_enabled:
            return None
        return build_enhancement_manifest(
            scope="scene_reconstruction",
            settings=self._config.enhancement.as_manifest(),
            source_fingerprint=self._file_fingerprint(attach_mesh),
        )

    @staticmethod
    def _file_fingerprint(path: Path) -> str:
        import hashlib

        digest = hashlib.sha256()
        try:
            with Path(path).open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError:
            return "missing"
        return digest.hexdigest()

    def _enhancement_cache_matches(
        self,
        manifest_path: Path,
        metadata_path: Path,
        expected: dict[str, Any] | None,
    ) -> bool:
        if expected is None or not Path(metadata_path).is_file():
            return False
        try:
            stored = read_enhancement_manifest(manifest_path)
        except MeshEnhancementManifestError:
            return False
        return stored == expected

    def _write_enhancement_metadata(self, path: Path, metadata: dict[str, Any]) -> None:
        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text(
                json.dumps(metadata, indent=2, sort_keys=True, default=str),
                encoding="utf-8",
            )
        except OSError:
            logger.warning(
                "scene_enhancement_metadata_write_failed",
                extra={"operation": "scene_reconstruction"},
            )

    def _read_enhancement_metadata(self, path: Path) -> dict[str, Any] | None:
        try:
            loaded = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return loaded if isinstance(loaded, dict) else None

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
