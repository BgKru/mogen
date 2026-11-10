"""Preflight checks for the scene worker (07 Sections 4.8, 14.4 and 15).

The worker verifies its external tools and resources before COLMAP starts, so a
missing executable or an almost-full disk fails a task with a stable code
instead of producing a confusing tool error halfway through.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .config import SceneConfig
from .dataset import SceneDataset
from .exceptions import (
    EXTERNAL_TOOL_UNAVAILABLE,
    INSUFFICIENT_STORAGE,
    INVALID_SCENE_DATASET,
    DatasetError,
    ResourceError,
    ToolError,
)

REQUIRED_TOOLS: tuple[str, ...] = (
    "colmap",
    "InterfaceCOLMAP",
    "DensifyPointCloud",
    "ReconstructMesh",
    "RefineMesh",
    "TextureMesh",
    "TransformScene",
)

# OpenMVS prints its help and exits; COLMAP returns 0 for --help. A non-zero
# help exit is tolerated only when the process actually produced output.
_HELP_TIMEOUT_SECONDS = 60


@dataclass(frozen=True, slots=True)
class ToolInfo:
    """One verified executable and the version line it reported."""

    name: str
    path: Path
    version: str


@dataclass(frozen=True, slots=True)
class ToolchainReport:
    """The result of verifying every required external tool."""

    tools: tuple[ToolInfo, ...] = field(default_factory=tuple)

    @property
    def verified(self) -> bool:
        return len(self.tools) == len(REQUIRED_TOOLS)

    def as_dict(self) -> dict[str, str]:
        return {tool.name: tool.version for tool in self.tools}


def _version_line(name: str, output: str) -> str:
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped or "command line" in stripped.lower():
            continue
        lowered = stripped.lower()
        if any(marker in lowered for marker in ("openmvs", "colmap", "version", "build")):
            return stripped[:200]
    first = next(
        (
            line.strip()
            for line in output.splitlines()
            if line.strip() and "command line" not in line.lower()
        ),
        "",
    )
    return (first or f"{name} available")[:200]


def verify_toolchain(
    config: SceneConfig, *, timeout: int = _HELP_TIMEOUT_SECONDS
) -> ToolchainReport:
    """Verify that every required executable exists and can start.

    Raises :class:`ToolError` with ``EXTERNAL_TOOL_UNAVAILABLE`` for the first
    missing or non-runnable tool; SCENE-AC-01 requires detection at startup.
    """
    verified: list[ToolInfo] = []
    # OpenMVS writes a `<tool>-<timestamp>.log` file next to its working
    # directory on every start, including `--help`. Probes therefore run in a
    # throwaway directory: otherwise each worker restart would leave log files
    # in the worker's CWD (and a host-side run pollutes the source tree)
    # (07 Section 15.7).
    with tempfile.TemporaryDirectory(prefix="mogen-toolcheck-") as scratch:
        for name in REQUIRED_TOOLS:
            path = config.tool(name)
            if not path.is_file() or not (path.stat().st_mode & 0o111):
                raise ToolError(
                    EXTERNAL_TOOL_UNAVAILABLE, "A required reconstruction tool is unavailable."
                )
            try:
                completed = subprocess.run(  # noqa: S603 - fixed argument array, no shell
                    [str(path), "--help"],
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    cwd=scratch,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise ToolError(
                    EXTERNAL_TOOL_UNAVAILABLE, "A required reconstruction tool could not start."
                ) from exc
            output = f"{completed.stdout}\n{completed.stderr}".strip()
            if completed.returncode not in (0, 1) and not output:
                raise ToolError(
                    EXTERNAL_TOOL_UNAVAILABLE, "A required reconstruction tool could not start."
                )
            verified.append(ToolInfo(name=name, path=path, version=_version_line(name, output)))
    return ToolchainReport(tools=tuple(verified))


def check_disk_space(work_dir: Path, *, min_free_bytes: int) -> int:
    """Return the free bytes on the workspace filesystem or raise."""
    probe = Path(work_dir)
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        free = shutil.disk_usage(probe).free
    except OSError as exc:
        raise ResourceError(INSUFFICIENT_STORAGE, "The workspace disk is not available.") from exc
    if free < min_free_bytes:
        raise ResourceError(
            INSUFFICIENT_STORAGE, "The worker does not have enough free workspace storage."
        )
    return free


def check_dataset(dataset: SceneDataset, config: SceneConfig) -> None:
    """Re-check the prepared dataset before expensive processing starts."""
    if dataset.duplicates:
        raise DatasetError(INVALID_SCENE_DATASET, "The image set contains duplicate photographs.")
    if dataset.image_count < config.min_registered_images:
        raise DatasetError(
            INVALID_SCENE_DATASET, "The image set has fewer photographs than required."
        )
    for image in dataset.images:
        if not image.path.is_file() or image.path.stat().st_size <= 0:
            raise DatasetError(
                INVALID_SCENE_DATASET, "A prepared photograph is missing from the workspace."
            )


__all__ = [
    "REQUIRED_TOOLS",
    "ToolInfo",
    "ToolchainReport",
    "check_dataset",
    "check_disk_space",
    "verify_toolchain",
]
