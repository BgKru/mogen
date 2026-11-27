"""Reproducible object enhancement benchmark (14 Sections 10.3 and 11).

Compares the legacy vertex-colour export, conservative cleanup + normals, and
optional vertex-colour baking on the same source GLB. Timing excludes source
loading but includes enhancement, export and independent validation.

Run inside the object-worker development image:

    python -m object_generation.benchmarks.run_enhancement_benchmark \
        --object /proof/object.glb --repetitions 3 \
        --output /proof/enhancement-object.json
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

import trimesh
from mesh_enhancement import measure_mesh, mesh_fingerprint

from object_generation.enhancement import EnhancementConfig, enhance_object
from object_generation.exporter import export_glb

VARIANTS = ("baseline", "cleanup_normals", "baked")


def _peak_rss_mb() -> float:
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0, 1)


def _config(variant: str, texture_resolution: int) -> EnhancementConfig:
    if variant == "baseline":
        return EnhancementConfig(cleanup_enabled=False, normals_enabled=False)
    if variant == "cleanup_normals":
        return EnhancementConfig()
    return EnhancementConfig(bake_texture=True, texture_resolution=texture_resolution)


def _run_once(source: Path, variant: str, texture_resolution: int) -> dict[str, Any]:
    mesh = trimesh.load(str(source), force="mesh")
    before = measure_mesh(mesh)
    started = time.perf_counter()
    result = enhance_object(mesh, _config(variant, texture_resolution))
    enhancement_seconds = time.perf_counter() - started
    with tempfile.TemporaryDirectory() as temporary:
        target = Path(temporary) / "model.glb"
        export_started = time.perf_counter()
        validation = export_glb(result.mesh, target, include_normals=result.normal_export)
        export_seconds = time.perf_counter() - export_started
        file_size = target.stat().st_size
    return {
        "variant": variant,
        "before": before.as_metadata(),
        "after": result.after.as_metadata(),
        "operations": result.operations,
        "skipped": result.skipped,
        "appearance_mode": result.appearance_mode,
        "normal_export": result.normal_export,
        "enhancement_seconds": round(enhancement_seconds, 4),
        "export_seconds": round(export_seconds, 4),
        "total_seconds": round(enhancement_seconds + export_seconds, 4),
        "file_size_bytes": file_size,
        "glb_validation": validation.as_metadata(),
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
    parser.add_argument("--object", type=Path, required=True, help="source object GLB")
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--texture-resolution", type=int, default=512)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if args.repetitions < 1:
        parser.error("--repetitions must be at least 1")
    if not args.object.is_file():
        parser.error(f"source GLB not found: {args.object}")

    source_mesh = trimesh.load(str(args.object), force="mesh")
    document: dict[str, Any] = {
        "scope": "object",
        "source": str(args.object),
        "source_fingerprint": mesh_fingerprint(source_mesh),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "trimesh": trimesh.__version__,
        },
        "texture_resolution": args.texture_resolution,
        "variants": {},
    }
    for variant in VARIANTS:
        runs = [
            _run_once(args.object, variant, args.texture_resolution)
            for _ in range(args.repetitions)
        ]
        document["variants"][variant] = _summarize(runs)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({name: document["variants"][name]["median_seconds"] for name in VARIANTS}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
