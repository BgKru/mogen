"""Optional neural scene reconstruction: dataset, training and export (increment 15).

This module orchestrates the Splatfacto path but does not own stage reporting:
the existing ``PhotogrammetryReconstructor`` reports the shared COLMAP stages
and the three neural stages. Everything here is opt-in and imports no Nerfstudio
code in the worker process — training runs through
:class:`scene_reconstruction.nerfstudio_runner.NerfstudioRunner`.
"""

from __future__ import annotations

import json
import logging
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import SceneConfig
from .dataset import SceneDataset
from .exceptions import (
    SPLAT_ARTIFACT_TOO_LARGE,
    SPLAT_CUDA_UNAVAILABLE,
    SPLAT_RESOURCE_EXHAUSTED,
    SPLAT_TIMEOUT,
    TOOL_TIMEOUT,
    SplatError,
)
from .nerfstudio_dataset import NerfstudioDataset, build_nerfstudio_dataset
from .nerfstudio_runner import NerfstudioRunner, RuntimeReport, TrainingOutcome
from .splat_config import (
    METHOD_SPLATFACTO,
    REPRESENTATION_GAUSSIAN_SPLAT,
    SPLAT_FORMAT,
    SPLAT_MIME_TYPE,
    SplatConfig,
)
from .splat_exporter import SplatExportResult, export_splat_ply
from .splat_validator import validate_splat_ply

logger = logging.getLogger(__name__)

SPLAT_MANIFEST_NAME = "splat_manifest.json"
SPLAT_METADATA_NAME = "splat_metadata.json"
SPLAT_MANIFEST_SCHEMA = "mogen_splat_manifest_v1"

# Runtime verification is per process: the gsplat kernel probe is cheap only
# because the image bakes the compiled extensions, but it must not run per task.
_runtime_cache: dict[str, RuntimeReport] = {}


@dataclass(frozen=True, slots=True)
class VramReport:
    """GPU admission facts (never persisted with transient free memory)."""

    device_name: str
    total_mb: int
    free_mb: int
    required_mb: int

    def as_metadata(self) -> dict[str, Any]:
        return {
            "device_name": self.device_name,
            "total_vram_mb": self.total_mb,
            "free_vram_mb_at_admission": self.free_mb,
            "required_vram_mb": self.required_mb,
        }


@dataclass(frozen=True, slots=True)
class SplatArtifact:
    """A validated Gaussian PLY ready for transactional result registration."""

    path: Path
    sha256: str
    file_size_bytes: int
    metadata: dict[str, Any] = field(default_factory=dict)
    reused: bool = False
    format: str = SPLAT_FORMAT
    mime_type: str = SPLAT_MIME_TYPE


def build_splat_manifest(
    *, dataset: NerfstudioDataset, runtime: RuntimeReport, splat: SplatConfig
) -> dict[str, Any]:
    """Return the checkpoint-reuse key for one training run.

    Only output-affecting values participate: resource budgets and timeouts do
    not invalidate a checkpoint, while the dataset fingerprint, the runtime
    versions and every training setting do. Transient free-memory values are
    deliberately absent (15 Section 6).
    """
    settings = splat.as_manifest()
    for key in ("timeout_seconds", "max_vram_mb", "max_artifact_bytes", "min_registered_images"):
        settings.pop(key, None)
    settings["seed"] = 42
    runtime_versions = {
        "nerfstudio": runtime.versions.get("nerfstudio"),
        "gsplat": runtime.versions.get("gsplat"),
        "torch": runtime.versions.get("torch"),
        "cuda_build": runtime.versions.get("cuda_build"),
        "device_name": runtime.versions.get("device_name"),
    }
    return {
        "schema": SPLAT_MANIFEST_SCHEMA,
        "dataset_fingerprint": dataset.fingerprint,
        "settings": settings,
        "runtime": runtime_versions,
    }


def read_splat_manifest(path: Path) -> dict[str, Any] | None:
    try:
        loaded = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def manifest_matches(path: Path, expected: dict[str, Any]) -> bool:
    """Return True only when the stored manifest equals the expected one."""
    stored = read_splat_manifest(path)
    return stored is not None and stored == expected


def _nvidia_smi_vram() -> tuple[str, int, int]:
    """Return ``(device, total_mb, free_mb)`` from nvidia-smi."""
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argument array, no shell
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,memory.used",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SplatError(
            SPLAT_CUDA_UNAVAILABLE, "The GPU is not reachable in this worker."
        ) from exc
    line = (completed.stdout or "").strip().splitlines()
    if completed.returncode != 0 or not line:
        raise SplatError(SPLAT_CUDA_UNAVAILABLE, "The GPU is not reachable in this worker.")
    parts = [part.strip() for part in line[0].split(",")]
    if len(parts) < 3:
        raise SplatError(SPLAT_CUDA_UNAVAILABLE, "The GPU could not be queried.")
    try:
        total, used = int(float(parts[1])), int(float(parts[2]))
    except ValueError as exc:
        raise SplatError(SPLAT_CUDA_UNAVAILABLE, "The GPU could not be queried.") from exc
    return parts[0], total, max(0, total - used)


class NeuralReconstructor:
    """Dataset conversion, training and export for one splat task."""

    def __init__(
        self,
        config: SceneConfig,
        *,
        runner: NerfstudioRunner | None = None,
        vram_probe: Callable[[], tuple[str, int, int]] | None = None,
    ) -> None:
        self._config = config
        self._runner = runner or NerfstudioRunner(config)
        self._vram_probe = vram_probe or _nvidia_smi_vram

    @property
    def splat(self) -> SplatConfig:
        return self._config.splat

    def runtime_report(self) -> RuntimeReport:
        """Verify (once per process) that the pinned neural stack really runs."""
        key = f"{self.splat.python_executable}|{self.splat.device}"
        cached = _runtime_cache.get(key)
        if cached is None:
            cached = self._runner.verify_runtime(run_kernel=True)
            _runtime_cache[key] = cached
        return cached

    def check_vram(self) -> VramReport | None:
        """Enforce the soft VRAM admission rule before a 12 GB GPU is used."""
        if self.splat.device != "cuda":
            return None
        device, total, free = self._vram_probe()
        if total < 1024:
            raise SplatError(SPLAT_CUDA_UNAVAILABLE, "The GPU is too small for neural training.")
        # Keep 1 GiB for the display/driver and never require more than the
        # configured budget; the floor avoids a pointlessly low admission bar.
        required = min(self.splat.max_vram_mb, max(2048, total - 1024))
        if free < required:
            raise SplatError(
                SPLAT_RESOURCE_EXHAUSTED,
                "The GPU does not have enough free memory for a neural scene task.",
            )
        return VramReport(device_name=device, total_mb=total, free_mb=free, required_mb=required)

    def prepare(
        self,
        dataset: SceneDataset,
        *,
        model_dir: Path,
        images_dir: Path,
        work_dir: Path,
        runtime: RuntimeReport,
        on_poll: Callable[[], None] | None = None,
    ) -> NerfstudioDataset:
        """Convert the validated COLMAP output into a Nerfstudio dataset."""
        return build_nerfstudio_dataset(
            dataset,
            model_dir=model_dir,
            images_dir=images_dir,
            output_dir=Path(work_dir) / "splat" / "dataset",
            splat=self.splat,
            min_registered_images=self.splat.min_registered_images,
            min_sparse_points=max(100, self._config.min_sparse_points),
            runtime_versions={
                "nerfstudio": str(runtime.versions.get("nerfstudio")),
                "gsplat": str(runtime.versions.get("gsplat")),
                "torch": str(runtime.versions.get("torch")),
            },
            on_poll=on_poll,
        )

    def train(
        self,
        *,
        dataset: NerfstudioDataset,
        work_dir: Path,
        timeout: int,
        on_poll: Callable[[], None] | None = None,
    ) -> TrainingOutcome:
        """Run Splatfacto in the neural venv, bounded by the task budget."""
        log_path = Path(work_dir) / "logs" / "splat_training.log"
        try:
            return self._runner.train(
                dataset_dir=dataset.root,
                run_dir=Path(work_dir) / "splat" / "run",
                log_path=log_path,
                timeout=min(int(timeout), int(self.splat.timeout_seconds)),
                on_poll=on_poll,
            )
        except SplatError as exc:
            if exc.error_code == TOOL_TIMEOUT:
                raise SplatError(
                    SPLAT_TIMEOUT, "The neural training run exceeded its time budget."
                ) from exc
            raise

    def export(
        self,
        *,
        checkpoint_path: Path,
        work_dir: Path,
    ) -> SplatExportResult:
        """Export a validated Gaussian PLY from a completed checkpoint."""
        return export_splat_ply(
            checkpoint_path,
            Path(work_dir) / "splat" / "output" / "scene.ply",
            sh_degree=self.splat.sh_degree,
            max_artifact_bytes=self.splat.max_artifact_bytes,
        )

    def reuse_existing(
        self,
        *,
        work_dir: Path,
        expected_manifest: dict[str, Any],
    ) -> SplatArtifact | None:
        """Return a previously validated artifact when the manifest matches."""
        splat_dir = Path(work_dir) / "splat"
        output = splat_dir / "output" / "scene.ply"
        manifest_path = splat_dir / SPLAT_MANIFEST_NAME
        metadata_path = splat_dir / SPLAT_METADATA_NAME
        if not output.is_file() or not manifest_matches(manifest_path, expected_manifest):
            return None
        try:
            validation = validate_splat_ply(
                output,
                sh_degree=self.splat.sh_degree,
                max_artifact_bytes=self.splat.max_artifact_bytes,
            )
        except SplatError:
            output.unlink(missing_ok=True)
            return None
        metadata = self._read_metadata(metadata_path) or {}
        metadata["reused"] = True
        metadata["artifact"] = validation.as_metadata()
        logger.info(
            "splat_artifact_reused",
            extra={
                "operation": "scene_reconstruction",
                "gaussian_count": validation.gaussian_count,
            },
        )
        return SplatArtifact(
            path=output,
            sha256=validation.sha256,
            file_size_bytes=validation.file_size_bytes,
            metadata=metadata,
            reused=True,
        )

    def build_artifact(
        self,
        *,
        export: SplatExportResult,
        dataset: NerfstudioDataset,
        training: TrainingOutcome,
        runtime: RuntimeReport,
        vram: VramReport | None,
        work_dir: Path,
        expected_manifest: dict[str, Any],
    ) -> SplatArtifact:
        """Persist the run manifest/metadata and return the registrable artifact."""
        splat_dir = Path(work_dir) / "splat"
        splat_dir.mkdir(parents=True, exist_ok=True)
        metadata: dict[str, Any] = {
            "representation": REPRESENTATION_GAUSSIAN_SPLAT,
            "method": METHOD_SPLATFACTO,
            "model": self.splat.model,
            "format": SPLAT_FORMAT,
            "dataset": dataset.as_metadata(),
            "training": {
                "iterations": self.splat.max_iterations,
                "checkpoint_interval": self.splat.checkpoint_interval,
                "training_step": export.training_step,
                "seconds": round(float(training.duration_seconds), 3),
                "gaussian_count_before_filter": export.gaussian_count_before_filter,
                "metrics": training.metrics,
                "reused": False,
            },
            "runtime": runtime.as_metadata(),
            "device": {
                "device": self.splat.device,
                **(vram.as_metadata() if vram is not None else {"device_name": "cpu"}),
            },
            "artifact": export.as_metadata(),
            "warnings": sorted(
                set(dataset.convention.warnings)
                | set(export.validation.warnings)
                | (set() if dataset.convention.ok else {"SPLAT_CAMERA_CHECK_FAILED"})
            ),
        }
        self._write_json(splat_dir / SPLAT_METADATA_NAME, metadata)
        self._write_json(splat_dir / SPLAT_MANIFEST_NAME, expected_manifest)
        return SplatArtifact(
            path=export.path,
            sha256=export.sha256,
            file_size_bytes=export.file_size_bytes,
            metadata=metadata,
        )

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text(
                json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8"
            )
        except OSError:
            logger.warning(
                "splat_metadata_write_failed", extra={"operation": "scene_reconstruction"}
            )

    @staticmethod
    def _read_metadata(path: Path) -> dict[str, Any] | None:
        try:
            loaded = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return loaded if isinstance(loaded, dict) else None

    def clear_stale_outputs(self, work_dir: Path) -> None:
        """Remove a stale artifact/manifest before a fresh run.

        The converted dataset is deliberately kept: it was just rebuilt for this
        attempt and is overwritten by :meth:`prepare` on the next run.
        """
        splat_dir = Path(work_dir) / "splat"
        for relative in ("output/scene.ply", SPLAT_MANIFEST_NAME, SPLAT_METADATA_NAME):
            (splat_dir / relative).unlink(missing_ok=True)


def check_artifact_size(path: Path, *, max_bytes: int) -> None:
    """Raise the documented error when an artifact exceeds the viewer limit."""
    if Path(path).stat().st_size > max_bytes:
        raise SplatError(
            SPLAT_ARTIFACT_TOO_LARGE, "The Gaussian PLY exceeds the configured size limit."
        )


__all__ = [
    "NeuralReconstructor",
    "SPLAT_MANIFEST_NAME",
    "SPLAT_MANIFEST_SCHEMA",
    "SPLAT_METADATA_NAME",
    "SplatArtifact",
    "VramReport",
    "build_splat_manifest",
    "check_artifact_size",
    "manifest_matches",
    "read_splat_manifest",
]
