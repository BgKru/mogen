"""GLB export and repack (07 Section 11).

OpenMVS's glTF exporter embeds geometry buffers but writes the texture as a
sidecar file, so its GLB is not self-contained. The pipeline therefore runs the
OpenMVS conversion tool, then loads the OBJ/MTL/PNG set (or the raw GLB) with
trimesh and re-exports one single-file GLB with embedded images. The final asset
is validated independently before it can become a result.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import trimesh

from .exceptions import GLB_EXPORT_FAILED, SceneExportError
from .mesh_processor import scene_mesh_stats
from .validator import (
    SceneGLBValidation,
    read_glb_document,
    validate_scene_glb,
)

OBJ_SUFFIX = ".obj"
GLB_SUFFIX = ".glb"


@dataclass(frozen=True, slots=True)
class RawExportSummary:
    """What the OpenMVS conversion tool actually wrote (P0-FU-1 evidence)."""

    path: Path
    document: dict
    has_external_images: bool
    image_uris: tuple[str, ...]
    extensions_used: tuple[str, ...]

    def as_metadata(self) -> dict[str, object]:
        return {
            "file": self.path.name,
            "image_uris": list(self.image_uris),
            "has_external_images": self.has_external_images,
            "extensions_used": list(self.extensions_used),
        }


def summarize_raw_glb(path: Path) -> RawExportSummary:
    """Read the raw OpenMVS GLB and record whether the texture is a sidecar."""
    document, _ = read_glb_document(path)
    images = document.get("images") or []
    uris = tuple(
        str(image.get("uri")) for image in images if isinstance(image, dict) and image.get("uri")
    )
    extensions = document.get("extensionsUsed") or []
    return RawExportSummary(
        path=Path(path),
        document=document,
        has_external_images=bool(uris),
        image_uris=uris,
        extensions_used=tuple(str(value) for value in extensions),
    )


def find_export_sources(export_dir: Path, *, export_type: str) -> list[Path]:
    """Return the conversion outputs, preferring the OBJ/MTL/PNG set."""
    directory = Path(export_dir)
    if not directory.is_dir():
        return []
    suffix = f".{export_type.lower()}"
    candidates = [path for path in directory.rglob(f"*{suffix}") if path.is_file()]
    return sorted(candidates, key=lambda path: (-path.stat().st_size, str(path)))


def _load_scene(source: Path) -> trimesh.Scene:
    try:
        loaded = trimesh.load(str(source), force="scene")
    except Exception as exc:
        raise SceneExportError(
            GLB_EXPORT_FAILED, "The OpenMVS export could not be loaded for repacking."
        ) from exc
    if isinstance(loaded, trimesh.Scene):
        scene = loaded
    else:
        scene = trimesh.Scene()
        scene.add_geometry(loaded)
    if not scene.geometry:
        raise SceneExportError(GLB_EXPORT_FAILED, "The OpenMVS export contains no geometry.")
    return scene


def repack_scene(
    sources: list[Path],
    output_path: Path,
    *,
    require_textures: bool = True,
    enhance: Callable[[trimesh.Scene], tuple[trimesh.Scene, bool]] | None = None,
) -> SceneGLBValidation:
    """Load the first usable export source and write one embedded-texture GLB.

    ``enhance`` is the optional scene post-processing callback. It receives the
    loaded scene, mutates/replaces geometry in place (preserving the graph,
    transforms and materials) and returns ``(scene, include_normals)``. It is
    only called when post-processing is explicitly enabled.
    """
    if not sources:
        raise SceneExportError(GLB_EXPORT_FAILED, "The OpenMVS export produced no asset.")
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None
    for source in sources:
        try:
            scene = _load_scene(source)
            geometry = scene_mesh_stats(scene, source=str(source))
            if geometry.vertices < 3 or geometry.faces < 1:
                raise SceneExportError(
                    GLB_EXPORT_FAILED, "The exported scene contains no usable geometry."
                )
            include_normals = False
            if enhance is not None:
                scene, include_normals = enhance(scene)
                geometry = scene_mesh_stats(scene, source=str(source))
                if geometry.vertices < 3 or geometry.faces < 1:
                    raise SceneExportError(
                        GLB_EXPORT_FAILED,
                        "The enhanced scene contains no usable geometry.",
                    )
            export_options = {"file_type": "glb"}
            if include_normals:
                export_options["include_normals"] = True
            scene.export(str(output), **export_options)
            if not output.is_file() or output.stat().st_size <= 0:
                raise SceneExportError(GLB_EXPORT_FAILED, "The repacked GLB was not written.")
            validation = validate_scene_glb(output, require_textures=require_textures)
            return validation
        except Exception as exc:  # try the next candidate source
            last_error = exc
            if output.is_file():
                output.unlink(missing_ok=True)
            continue
    raise SceneExportError(
        GLB_EXPORT_FAILED,
        "The scene could not be repacked into a self-contained GLB.",
    ) from last_error


def write_export_manifest(path: Path, payload: dict) -> None:
    """Write the export evidence beside the intermediates (never to storage)."""
    import contextlib

    with contextlib.suppress(OSError):
        Path(path).write_text(
            json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8"
        )


__all__ = [
    "GLB_SUFFIX",
    "OBJ_SUFFIX",
    "RawExportSummary",
    "find_export_sources",
    "repack_scene",
    "summarize_raw_glb",
    "write_export_manifest",
]
