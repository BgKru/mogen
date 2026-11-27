"""Enhancement manifests, dependency versions and source fingerprints.

The manifest is the checkpoint-invalidation key: operation settings, dependency
versions and the source asset fingerprint must all match before a cached
enhanced export may be reused (14 Sections 6 and 10.1).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import trimesh


class MeshEnhancementManifestError(Exception):
    """Raised when an enhancement manifest cannot be read."""


def dependency_versions() -> dict[str, str]:
    """Return the pinned versions that affect enhancement output."""
    from importlib.metadata import PackageNotFoundError, version

    result: dict[str, str] = {"trimesh": str(trimesh.__version__), "numpy": str(np.__version__)}
    for package in ("xatlas", "pillow", "scipy"):
        try:
            result[package] = version(package)
        except PackageNotFoundError:
            result[package] = "unavailable"
    result["python"] = _python_version()
    return result


def _python_version() -> str:
    import sys

    return f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"


def mesh_fingerprint(mesh: trimesh.Trimesh) -> str:
    """Hash geometry and appearance so a changed source invalidates a cache."""
    digest = hashlib.sha256()
    digest.update(np.ascontiguousarray(np.asarray(mesh.vertices, dtype="<f8")).tobytes())
    digest.update(np.ascontiguousarray(np.asarray(mesh.faces, dtype="<i8")).tobytes())
    try:
        kind = getattr(mesh.visual, "kind", None)
        digest.update(str(kind).encode("ascii", errors="replace"))
        uv = getattr(mesh.visual, "uv", None)
        if uv is not None:
            digest.update(np.ascontiguousarray(np.asarray(uv, dtype="<f8")).tobytes())
        if kind in {"vertex", "face"}:
            colors = np.asarray(mesh.visual.vertex_colors)
            digest.update(np.ascontiguousarray(colors).tobytes())
        material = getattr(mesh.visual, "material", None)
        image = getattr(material, "baseColorTexture", None) if material is not None else None
        if image is not None:
            digest.update(np.asarray(image).tobytes())
    except Exception:
        # Appearance hashing is best-effort; geometry always participates.
        pass
    return digest.hexdigest()


def build_enhancement_manifest(
    *,
    scope: str,
    settings: Mapping[str, Any],
    source_fingerprint: str,
) -> dict[str, Any]:
    """Build the JSON-safe manifest for one enhancement run."""
    return {
        "scope": scope,
        "version": 1,
        "settings": {key: _json_safe(value) for key, value in settings.items()},
        "dependencies": dependency_versions(),
        "source_fingerprint": source_fingerprint,
    }


def _json_safe(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return str(value)


def write_enhancement_manifest(path: Path, manifest: Mapping[str, Any]) -> None:
    """Write a manifest atomically enough for task-scoped diagnostics."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(target)


def read_enhancement_manifest(path: Path) -> dict[str, Any]:
    """Read a manifest, raising a stable error when it is absent/corrupt."""
    target = Path(path)
    try:
        loaded = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MeshEnhancementManifestError("The enhancement manifest is unreadable.") from exc
    if not isinstance(loaded, dict):
        raise MeshEnhancementManifestError("The enhancement manifest is not an object.")
    return loaded


__all__ = [
    "MeshEnhancementManifestError",
    "build_enhancement_manifest",
    "dependency_versions",
    "mesh_fingerprint",
    "read_enhancement_manifest",
    "write_enhancement_manifest",
]
