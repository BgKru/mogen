"""Reproducible scene enhancement benchmark (14 Sections 10.3 and 11).

Compares the unchanged OpenMVS repack with the optional post-reconstruction
cleanup/normal pass and the guarded simplification attempt. The scene graph,
transforms, materials and OpenMVS textures are preserved in every variant.

Run inside the scene-worker development image:

    /opt/venv/bin/python -m scene_reconstruction.benchmark_enhancement \
        --scene /proof/scene.glb --repetitions 2 \
        --output /proof/enhancement-scene.json
"""

from __future__ import annotations

import argparse
import json
import platform
import resource
import statistics
import tempfile
import time
from pathlib import Path
from typing import Any

import numpy as np
import trimesh

from scene_reconstruction.enhancement import (
    SceneEnhancementConfig,
    enhance_scene,
    scene_fingerprint,
)
from scene_reconstruction.exporter import repack_scene
from scene_reconstruction.validator import validate_scene_glb

VARIANTS = ("baseline", "cleanup_normals", "simplification_attempt")


def _peak_rss_mb() -> float:
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0, 1)


def _totals(scene: trimesh.Scene) -> dict[str, int]:
    vertices = sum(
        len(geometry.vertices)
        for geometry in scene.geometry.values()
        if isinstance(geometry, trimesh.Trimesh)
    )
    faces = sum(
        len(geometry.faces)
        for geometry in scene.geometry.values()
        if isinstance(geometry, trimesh.Trimesh)
    )
    return {"geometries": len(scene.geometry), "vertices_count": vertices, "faces_count": faces}


def _config(variant: str, total_faces: int) -> SceneEnhancementConfig:
    if variant == "cleanup_normals":
        return SceneEnhancementConfig(postprocess_enabled=True)
    if variant == "simplification_attempt":
        return SceneEnhancementConfig(
            postprocess_enabled=True,
            simplification_enabled=True,
            target_faces=max(1, total_faces // 2),
        )
    return SceneEnhancementConfig(postprocess_enabled=False)


def _run_once(source: Path, variant: str, require_textures: bool) -> dict[str, Any]:
    scene = trimesh.load(str(source), force="scene")
    if not isinstance(scene, trimesh.Scene):
        scene = trimesh.Scene(scene)
    totals = _totals(scene)
    config = _config(variant, totals["faces_count"])
    enhancement_result: dict[str, Any] | None = None
    enhancement_seconds = 0.0

    def enhance(current: trimesh.Scene) -> tuple[trimesh.Scene, bool]:
        nonlocal enhancement_result, enhancement_seconds
        started = time.perf_counter()
        result = enhance_scene(current, config)
        enhancement_seconds = time.perf_counter() - started
        enhancement_result = result.as_metadata()
        return current, result.normal_export

    with tempfile.TemporaryDirectory() as temporary:
        target = Path(temporary) / "scene.glb"
        repack_started = time.perf_counter()
        validation = repack_scene(
            [source],
            target,
            require_textures=require_textures,
            enhance=enhance if config.postprocess_enabled else None,
        )
        repack_seconds = time.perf_counter() - repack_started
        file_size = target.stat().st_size
        final = validate_scene_glb(target, require_textures=require_textures)
    assert final.sha256 == validation.sha256
    return {
        "variant": variant,
        "before": totals,
        "after": _totals(scene),
        "enhancement": enhancement_result,
        "enhancement_seconds": round(enhancement_seconds, 4),
        "repack_seconds": round(repack_seconds, 4),
        "total_seconds": round(enhancement_seconds + repack_seconds, 4),
        "file_size_bytes": file_size,
        "glb_validation": final.as_metadata(),
        "peak_rss_mb": _peak_rss_mb(),
    }


def _summarize(runs: list[dict[str, Any]]) -> dict[str, Any]:
    seconds = sorted(run["total_seconds"] for run in runs)
    sizes = sorted(run["file_size_bytes"] for run in runs)
    return {
        "runs": len(runs),
        "median_seconds": round(statistics.median(seconds), 4),
        "p95_seconds": round(seconds[min(len(seconds) - 1, int(len(seconds) * 0.95))], 4),
        "median_file_size_bytes": int(statistics.median(sizes)),
        "first": runs[0],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene", type=Path, required=True, help="source scene GLB")
    parser.add_argument("--repetitions", type=int, default=2)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--require-textures",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    args = parser.parse_args()
    if args.repetitions < 1:
        parser.error("--repetitions must be at least 1")
    if not args.scene.is_file():
        parser.error(f"source GLB not found: {args.scene}")

    source_scene = trimesh.load(str(args.scene), force="scene")
    document: dict[str, Any] = {
        "scope": "scene",
        "source": str(args.scene),
        "source_fingerprint": scene_fingerprint(source_scene),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "numpy": np.__version__,
            "trimesh": trimesh.__version__,
        },
        "require_textures": args.require_textures,
        "variants": {},
    }
    for variant in VARIANTS:
        runs = [
            _run_once(args.scene, variant, args.require_textures) for _ in range(args.repetitions)
        ]
        document["variants"][variant] = _summarize(runs)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({name: document["variants"][name]["median_seconds"] for name in VARIANTS}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
