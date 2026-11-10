"""OpenMVS command construction and stage validation (07 Section 10).

The pipeline uses the documented sequence: InterfaceCOLMAP, DensifyPointCloud,
ReconstructMesh, RefineMesh, TextureMesh and TransformScene. Each command is a
plain argument array built from validated configuration.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .config import SceneConfig
from .exceptions import (
    DENSE_RECONSTRUCTION_FAILED,
    GLB_EXPORT_FAILED,
    INSUFFICIENT_DENSE_POINTS,
    MESH_GENERATION_FAILED,
    MESH_REFINEMENT_FAILED,
    OPENMVS_IMPORT_FAILED,
    TEXTURE_GENERATION_FAILED,
    ReconstructionError,
)
from .mesh_processor import MeshStats, count_ply_vertices, inspect_mesh
from .runner import CommandOutcome, CommandRunner

TEXTURE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg"})


@dataclass(frozen=True, slots=True)
class OpenMvsOutcome:
    """One executed OpenMVS stage, its log and the artifacts it created."""

    stage: str
    duration_seconds: float
    log_path: Path
    artifacts: tuple[Path, ...] = field(default_factory=tuple)
    mesh: MeshStats | None = None
    dense_points: int | None = None


def interface_colmap_command(
    config: SceneConfig, *, dense_dir: Path, scene_file: Path
) -> list[str]:
    """Build ``InterfaceCOLMAP`` for the undistorted COLMAP workspace."""
    return [
        str(config.tool("InterfaceCOLMAP")),
        "-i",
        str(dense_dir),
        "-o",
        str(scene_file),
        "--image-folder",
        str(dense_dir / "images"),
        "--max-threads",
        str(config.max_threads),
    ]


def densify_command(config: SceneConfig, *, scene_file: Path) -> list[str]:
    """Build ``DensifyPointCloud`` for the imported scene."""
    return [
        str(config.tool("DensifyPointCloud")),
        str(scene_file),
        "--max-threads",
        str(config.max_threads),
    ]


def reconstruct_mesh_command(
    config: SceneConfig, *, dense_scene: Path, mesh_path: Path
) -> list[str]:
    """Build ``ReconstructMesh`` from the dense point cloud."""
    return [
        str(config.tool("ReconstructMesh")),
        str(dense_scene),
        "-p",
        str(mesh_path),
        "--max-threads",
        str(config.max_threads),
    ]


def refine_mesh_command(
    config: SceneConfig, *, dense_scene: Path, mesh_path: Path, refined_mesh: Path
) -> list[str]:
    """Build ``RefineMesh`` with the conservative settings from the MVP spec."""
    return [
        str(config.tool("RefineMesh")),
        str(dense_scene),
        "-m",
        str(mesh_path),
        "-o",
        str(refined_mesh),
        "--scales",
        "1",
        "--max-face-area",
        "16",
        "--max-threads",
        str(config.max_threads),
    ]


def texture_mesh_command(
    config: SceneConfig, *, dense_scene: Path, mesh_path: Path, textured_mesh: Path
) -> list[str]:
    """Build ``TextureMesh`` for the refined mesh."""
    return [
        str(config.tool("TextureMesh")),
        str(dense_scene),
        "-m",
        str(mesh_path),
        "-o",
        str(textured_mesh),
        "--max-threads",
        str(config.max_threads),
    ]


def transform_scene_command(
    config: SceneConfig,
    *,
    scene_file: Path,
    output_base: Path,
    export_type: str,
    mesh_file: Path | None = None,
) -> list[str]:
    """Build ``TransformScene`` as the GLB/OBJ conversion tool.

    ``--normalize-coordinates 2`` centres and scales the scene and makes the
    command a valid export (TransformScene rejects an invocation without a
    transformation). No undocumented geometry transformation is applied.
    """
    command = [
        str(config.tool("TransformScene")),
        str(scene_file),
    ]
    if mesh_file is not None:
        command.extend(["-m", str(mesh_file)])
    command.extend(
        [
            "-o",
            str(output_base),
            "--normalize-coordinates",
            "2",
            "--export-type",
            export_type,
            "--max-threads",
            str(config.max_threads),
        ]
    )
    return command


def _snapshot(directory: Path) -> dict[Path, int]:
    if not directory.is_dir():
        return {}
    return {path: path.stat().st_size for path in directory.rglob("*") if path.is_file()}


def _new_artifacts(before: dict[Path, int], directory: Path) -> list[Path]:
    after = _snapshot(directory)
    return sorted(
        (path for path, size in after.items() if before.get(path) != size),
        key=lambda path: (-path.stat().st_size, str(path)),
    )


class OpenMvsRunner:
    """Execute OpenMVS stages and validate their outputs."""

    def __init__(self, config: SceneConfig, runner: CommandRunner | None = None) -> None:
        self._config = config
        self._runner = runner or CommandRunner()

    def _execute(
        self,
        *,
        command: list[str],
        cwd: Path,
        timeout: int,
        log_path: Path,
        on_poll: Callable[[], None] | None,
        error_code: str,
        error_message: str,
        watch_dir: Path,
    ) -> tuple[CommandOutcome, list[Path]]:
        before = _snapshot(watch_dir)
        outcome = self._runner.run(
            command, cwd=cwd, timeout=timeout, log_path=log_path, on_poll=on_poll
        )
        if not outcome.succeeded:
            raise ReconstructionError(
                error_code, f"{error_message} (exit code {outcome.exit_code})"
            )
        return outcome, _new_artifacts(before, watch_dir)

    def import_scene(
        self,
        *,
        dense_dir: Path,
        scene_file: Path,
        work_dir: Path,
        log_path: Path,
        on_poll: Callable[[], None] | None = None,
    ) -> OpenMvsOutcome:
        command = interface_colmap_command(self._config, dense_dir=dense_dir, scene_file=scene_file)
        outcome, artifacts = self._execute(
            command=command,
            cwd=work_dir,
            timeout=self._config.timeout_for("OPENMVS_IMPORT"),
            log_path=log_path,
            on_poll=on_poll,
            error_code=OPENMVS_IMPORT_FAILED,
            error_message="OpenMVS could not import the COLMAP reconstruction.",
            watch_dir=work_dir,
        )
        if not scene_file.is_file() or scene_file.stat().st_size <= 0:
            raise ReconstructionError(OPENMVS_IMPORT_FAILED, "OpenMVS did not create a scene file.")
        return OpenMvsOutcome(
            stage="OPENMVS_IMPORT",
            duration_seconds=outcome.duration_seconds,
            log_path=log_path,
            artifacts=tuple(artifacts) + (scene_file,),
        )

    def densify(
        self,
        *,
        scene_file: Path,
        dense_scene: Path,
        work_dir: Path,
        log_path: Path,
        on_poll: Callable[[], None] | None = None,
    ) -> OpenMvsOutcome:
        command = densify_command(self._config, scene_file=scene_file)
        outcome, artifacts = self._execute(
            command=command,
            cwd=work_dir,
            timeout=self._config.timeout_for("DENSE_RECONSTRUCTION"),
            log_path=log_path,
            on_poll=on_poll,
            error_code=DENSE_RECONSTRUCTION_FAILED,
            error_message="OpenMVS dense reconstruction failed.",
            watch_dir=work_dir,
        )
        if not dense_scene.is_file() or dense_scene.stat().st_size <= 0:
            raise ReconstructionError(
                DENSE_RECONSTRUCTION_FAILED, "OpenMVS produced no dense scene."
            )
        dense_points = count_ply_vertices(work_dir / f"{dense_scene.stem}.ply")
        if dense_points is not None and dense_points < self._config.min_dense_points:
            raise ReconstructionError(
                INSUFFICIENT_DENSE_POINTS,
                "The dense point cloud contains too few points.",
            )
        return OpenMvsOutcome(
            stage="DENSE_RECONSTRUCTION",
            duration_seconds=outcome.duration_seconds,
            log_path=log_path,
            artifacts=tuple(artifacts) + (dense_scene,),
            dense_points=dense_points,
        )

    def reconstruct_mesh(
        self,
        *,
        dense_scene: Path,
        mesh_path: Path,
        work_dir: Path,
        log_path: Path,
        on_poll: Callable[[], None] | None = None,
    ) -> OpenMvsOutcome:
        command = reconstruct_mesh_command(
            self._config, dense_scene=dense_scene, mesh_path=mesh_path
        )
        outcome, artifacts = self._execute(
            command=command,
            cwd=work_dir,
            timeout=self._config.timeout_for("MESH_GENERATION"),
            log_path=log_path,
            on_poll=on_poll,
            error_code=MESH_GENERATION_FAILED,
            error_message="OpenMVS mesh reconstruction failed.",
            watch_dir=work_dir,
        )
        if not mesh_path.is_file():
            raise ReconstructionError(MESH_GENERATION_FAILED, "OpenMVS did not create a mesh.")
        mesh = inspect_mesh(mesh_path, error_code=MESH_GENERATION_FAILED)
        return OpenMvsOutcome(
            stage="MESH_GENERATION",
            duration_seconds=outcome.duration_seconds,
            log_path=log_path,
            artifacts=tuple(artifacts) + (mesh_path,),
            mesh=mesh,
        )

    def refine_mesh(
        self,
        *,
        dense_scene: Path,
        mesh_path: Path,
        refined_mesh: Path,
        work_dir: Path,
        log_path: Path,
        on_poll: Callable[[], None] | None = None,
    ) -> OpenMvsOutcome:
        command = refine_mesh_command(
            self._config,
            dense_scene=dense_scene,
            mesh_path=mesh_path,
            refined_mesh=refined_mesh,
        )
        outcome, artifacts = self._execute(
            command=command,
            cwd=work_dir,
            timeout=self._config.timeout_for("MESH_REFINEMENT"),
            log_path=log_path,
            on_poll=on_poll,
            error_code=MESH_REFINEMENT_FAILED,
            error_message="OpenMVS mesh refinement failed.",
            watch_dir=work_dir,
        )
        # RefineMesh writes a mesh file (PLY) rather than a scene archive, even
        # when the -o name carries another extension. Accept the path it reports
        # by falling back to the matching PLY name.
        produced = refined_mesh if refined_mesh.is_file() else refined_mesh.with_suffix(".ply")
        if not produced.is_file():
            raise ReconstructionError(
                MESH_REFINEMENT_FAILED, "OpenMVS did not create a refined mesh."
            )
        mesh = inspect_mesh(produced, error_code=MESH_REFINEMENT_FAILED)
        return OpenMvsOutcome(
            stage="MESH_REFINEMENT",
            duration_seconds=outcome.duration_seconds,
            log_path=log_path,
            artifacts=tuple(artifacts) + (produced,),
            mesh=mesh,
        )

    def texture(
        self,
        *,
        dense_scene: Path,
        mesh_path: Path,
        textured_mesh: Path,
        work_dir: Path,
        log_path: Path,
        on_poll: Callable[[], None] | None = None,
    ) -> OpenMvsOutcome:
        command = texture_mesh_command(
            self._config,
            dense_scene=dense_scene,
            mesh_path=mesh_path,
            textured_mesh=textured_mesh,
        )
        outcome, artifacts = self._execute(
            command=command,
            cwd=work_dir,
            timeout=self._config.timeout_for("TEXTURING"),
            log_path=log_path,
            on_poll=on_poll,
            error_code=TEXTURE_GENERATION_FAILED,
            error_message="OpenMVS texture generation failed.",
            watch_dir=work_dir,
        )
        textures = [
            path
            for path in work_dir.iterdir()
            if path.is_file() and path.suffix.lower() in TEXTURE_SUFFIXES
        ]
        # TextureMesh writes a textured mesh (PLY) plus its atlas image, even
        # when the -o name carries another extension.
        produced = textured_mesh if textured_mesh.is_file() else textured_mesh.with_suffix(".ply")
        if not produced.is_file():
            raise ReconstructionError(
                TEXTURE_GENERATION_FAILED, "OpenMVS did not create a textured scene."
            )
        if self._config.enable_texture_generation and not textures:
            raise ReconstructionError(
                TEXTURE_GENERATION_FAILED, "OpenMVS did not write a texture image."
            )
        return OpenMvsOutcome(
            stage="TEXTURING",
            duration_seconds=outcome.duration_seconds,
            log_path=log_path,
            artifacts=tuple(artifacts) + tuple(textures) + (produced,),
        )

    def transform(
        self,
        *,
        scene_file: Path,
        output_base: Path,
        export_type: str,
        work_dir: Path,
        log_path: Path,
        on_poll: Callable[[], None] | None = None,
        mesh_file: Path | None = None,
    ) -> OpenMvsOutcome:
        command = transform_scene_command(
            self._config,
            scene_file=scene_file,
            output_base=output_base,
            export_type=export_type,
            mesh_file=mesh_file,
        )
        outcome, artifacts = self._execute(
            command=command,
            cwd=work_dir,
            timeout=self._config.timeout_for("ASSET_EXPORT"),
            log_path=log_path,
            on_poll=on_poll,
            error_code=GLB_EXPORT_FAILED,
            error_message="OpenMVS could not export the scene.",
            watch_dir=output_base.parent,
        )
        exported = [path for path in artifacts if path.suffix.lower() == f".{export_type.lower()}"]
        if not exported:
            raise ReconstructionError(GLB_EXPORT_FAILED, "The OpenMVS export produced no asset.")
        return OpenMvsOutcome(
            stage="ASSET_EXPORT",
            duration_seconds=outcome.duration_seconds,
            log_path=log_path,
            artifacts=tuple(artifacts),
        )


__all__ = [
    "OpenMvsOutcome",
    "OpenMvsRunner",
    "TEXTURE_SUFFIXES",
    "densify_command",
    "interface_colmap_command",
    "reconstruct_mesh_command",
    "refine_mesh_command",
    "texture_mesh_command",
    "transform_scene_command",
]
