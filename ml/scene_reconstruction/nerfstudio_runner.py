"""Controlled Nerfstudio subprocess execution (15 Sections 4.4 and 5.1).

Training is never imported into the worker process: it runs through the same
argument-array/timeout/cancellation runner the COLMAP stages use, inside the
pinned neural virtual environment. This module only knows the pinned entry
point, its markers and where the checkpoint must appear.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import SceneConfig
from .exceptions import (
    SPLAT_CHECKPOINT_INVALID,
    SPLAT_RESOURCE_EXHAUSTED,
    SPLAT_RUNTIME_UNAVAILABLE,
    SPLAT_TRAINING_FAILED,
    SplatError,
)
from .runner import CommandRunner, tail_log

logger = logging.getLogger(__name__)

ENTRY_MODULE = "scene_reconstruction.splat_train_entry"
RUNTIME_MARKER = "MOGEN_SPLAT_RUNTIME "
TRAINING_MARKER = "MOGEN_SPLAT_TRAIN "
VERIFY_TIMEOUT_SECONDS = 900
_OOM_MARKERS = (
    "out of memory",
    "cuda error: out of memory",
    "cuda out of memory",
    "cublas_status_alloc_failed",
)


@dataclass(frozen=True, slots=True)
class RuntimeReport:
    """The verified neural runtime fingerprint."""

    versions: dict[str, Any]
    fingerprint: dict[str, Any]

    def as_metadata(self) -> dict[str, Any]:
        return {
            "nerfstudio": self.versions.get("nerfstudio"),
            "gsplat": self.versions.get("gsplat"),
            "torch": self.versions.get("torch"),
            "cuda_build": self.versions.get("cuda_build"),
            "cuda_available": bool(self.versions.get("cuda_available")),
            "device_name": self.versions.get("device_name"),
            "kernel_executed": bool(self.versions.get("kernel_executed")),
        }


@dataclass(frozen=True, slots=True)
class TrainingOutcome:
    """The result of one controlled training run."""

    summary: dict[str, Any]
    checkpoint_path: Path | None
    base_dir: Path
    duration_seconds: float
    log_path: Path

    @property
    def metrics(self) -> dict[str, Any]:
        values = self.summary.get("metrics")
        return values if isinstance(values, dict) else {}


def _find_marker(log_path: Path, marker: str) -> dict[str, Any] | None:
    try:
        content = Path(log_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in reversed(content.splitlines()):
        stripped = line.strip()
        index = stripped.find(marker)
        if index < 0:
            continue
        try:
            value = json.loads(stripped[index + len(marker) :])
        except json.JSONDecodeError:
            continue
        return value if isinstance(value, dict) else None
    return None


class NerfstudioRunner:
    """Run the pinned Splatfacto entry point in its own environment."""

    def __init__(
        self,
        config: SceneConfig,
        *,
        runner: CommandRunner | None = None,
        python_executable: Path | None = None,
    ) -> None:
        self._config = config
        self._runner = runner or CommandRunner()
        self._python = Path(python_executable or config.splat.python_executable)
        # The package lives in <source_root>/scene_reconstruction; the subprocess
        # needs that parent on PYTHONPATH exactly like the worker.
        self._source_root = Path(__file__).resolve().parent.parent

    def _environment(self) -> dict[str, str]:
        environment = dict(os.environ)
        existing = environment.get("PYTHONPATH", "")
        site_packages = Path(self._config.splat.site_packages)
        parts = [str(self._source_root)]
        if site_packages.is_dir():
            parts.insert(0, str(site_packages))
        parts.extend(part for part in existing.split(os.pathsep) if part)
        environment["PYTHONPATH"] = os.pathsep.join(dict.fromkeys(parts))
        environment["PYTHONUNBUFFERED"] = "1"
        environment.setdefault("TORCH_EXTENSIONS_DIR", "/opt/splat-cache/torch_extensions")
        # gsplat's JIT build finds nvcc by name on PATH, even with CUDA_HOME set;
        # keep the pinned toolkit ahead of the system path for a first-run build.
        nvcc_dir = site_packages / "nvidia" / "cu13" / "bin"
        if nvcc_dir.is_dir():
            environment["PATH"] = os.pathsep.join(
                dict.fromkeys([str(nvcc_dir), environment.get("PATH", "")])
            )
            environment.setdefault("CUDA_HOME", str(site_packages / "nvidia" / "cu13"))
        environment.setdefault("TORCH_CUDA_ARCH_LIST", "8.6")
        environment.setdefault("TORCH_HOME", "/opt/splat-cache/torch_home")
        return environment

    def _command(self, *arguments: str) -> list[str]:
        return [str(self._python), "-m", ENTRY_MODULE, *arguments]

    def verify_runtime(
        self, *, run_kernel: bool = True, timeout: int = VERIFY_TIMEOUT_SECONDS
    ) -> RuntimeReport:
        """Verify the neural stack and (optionally) that the gsplat kernel runs."""
        if not self._python.is_file():
            raise SplatError(
                SPLAT_RUNTIME_UNAVAILABLE, "The neural runtime is not installed in this worker."
            )
        log_path = Path("/tmp") / "mogen-splat-verify.log"
        arguments = self._command("--verify")
        if not run_kernel:
            arguments.append("--skip-kernel")
        outcome = self._runner.run(
            arguments,
            cwd=self._source_root,
            timeout=timeout,
            log_path=log_path,
            on_poll=None,
            env=self._environment(),
        )
        fingerprint = _find_marker(log_path, RUNTIME_MARKER)
        if outcome.exit_code != 0 or not fingerprint:
            logger.warning(
                "splat_runtime_verification_failed",
                extra={
                    "operation": "scene_reconstruction",
                    "exit_code": outcome.exit_code,
                    "log_tail": tail_log(log_path, lines=15),
                },
            )
            raise SplatError(
                SPLAT_RUNTIME_UNAVAILABLE,
                "The neural scene runtime is unavailable or failed its startup check.",
            )
        versions = {
            key: fingerprint.get(key)
            for key in (
                "nerfstudio",
                "gsplat",
                "torch",
                "cuda_build",
                "cuda_available",
                "device_name",
                "kernel_executed",
            )
        }
        return RuntimeReport(versions=versions, fingerprint=fingerprint)

    def train(
        self,
        *,
        dataset_dir: Path,
        run_dir: Path,
        log_path: Path,
        timeout: int,
        on_poll=None,
    ) -> TrainingOutcome:
        """Train Splatfacto inside the task workspace and return its checkpoint."""
        splat = self._config.splat
        run_dir.mkdir(parents=True, exist_ok=True)
        arguments = self._command(
            "--data",
            str(Path(dataset_dir)),
            "--output-dir",
            str(Path(run_dir)),
            "--max-iterations",
            str(splat.max_iterations),
            "--steps-per-save",
            str(splat.checkpoint_interval),
            "--sh-degree",
            str(splat.sh_degree),
            "--device",
            splat.device,
        )
        try:
            outcome = self._runner.run(
                arguments,
                cwd=self._source_root,
                timeout=timeout,
                log_path=Path(log_path),
                on_poll=on_poll,
                env=self._environment(),
            )
        except SplatError:
            raise
        # CommandRunner raises TOOL_TIMEOUT; the neural pipeline maps that to the
        # dedicated SPLAT_TIMEOUT code so the error contract stays explicit.

        summary = _find_marker(Path(log_path), TRAINING_MARKER)
        if outcome.exit_code != 0 or summary is None:
            self._raise_for_failure(Path(log_path), outcome.exit_code)
        base_dir = Path(str(summary.get("base_dir", "")))
        checkpoint = summary.get("checkpoint")
        checkpoint_path = Path(str(checkpoint)) if checkpoint else None
        if checkpoint_path is None or not checkpoint_path.is_file():
            raise SplatError(
                SPLAT_CHECKPOINT_INVALID, "Training finished without a usable checkpoint."
            )
        return TrainingOutcome(
            summary=summary,
            checkpoint_path=checkpoint_path,
            base_dir=base_dir,
            duration_seconds=float(summary.get("train_seconds", outcome.duration_seconds)),
            log_path=Path(log_path),
        )

    @staticmethod
    def _raise_for_failure(log_path: Path, exit_code: int) -> None:
        tail = tail_log(log_path, lines=40)
        lowered = tail.lower()
        if any(marker in lowered for marker in _OOM_MARKERS):
            raise SplatError(
                SPLAT_RESOURCE_EXHAUSTED, "The neural training run exhausted the GPU memory."
            )
        if exit_code == 3:
            raise SplatError(SPLAT_RUNTIME_UNAVAILABLE, "The neural scene runtime is unavailable.")
        raise SplatError(
            SPLAT_TRAINING_FAILED, "The neural training run did not produce a checkpoint."
        )


__all__ = [
    "ENTRY_MODULE",
    "NerfstudioRunner",
    "RUNTIME_MARKER",
    "RuntimeReport",
    "TRAINING_MARKER",
    "TrainingOutcome",
]
