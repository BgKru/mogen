"""Reproducible object-generation benchmark (13 Section 10.3).

Compares the configured generators on identical photographs and hardware. It is
not part of the production request path: it calls the same pipeline entry point
and records measured values, one warm-up plus N measured repetitions per image.

    python -m object_generation.benchmarks.run_benchmark \
        --images testdata --generators triposr,sf3d \
        --repetitions 3 --device cuda:0 --output /proof/benchmark.json

A generator that is disabled, blocked or whose weights are missing is recorded
as a failed variant with its stable error code, never as a fabricated success.
"""

from __future__ import annotations

import argparse
import json
import shutil
import statistics
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from object_generation.exceptions import ObjectGenerationError
from object_generation.generator_factory import create_generator, reset_generators
from object_generation.pipeline import build_config_from_settings, run_object_generation

SUPPORTED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


def _config(device: str, generator: str, texture_resolution: int, remesh: str):
    """Build the production configuration from the worker settings."""
    import os

    from app.core.config import Settings

    manifest_path = Path(
        os.environ.get("OBJECT_SF3D_MANIFEST_PATH", "/models/sf3d/model-manifest.json")
    )
    revision = os.environ.get("OBJECT_SF3D_MODEL_REVISION", "") or _manifest_revision(manifest_path)
    settings = Settings(
        object_device=device,
        object_generator=generator,
        object_sf3d_enabled=generator == "sf3d",
        object_sf3d_model_revision=revision,
        object_sf3d_manifest_path=manifest_path,
        object_sf3d_texture_resolution=texture_resolution,
        object_sf3d_remesh=remesh,
    )
    return build_config_from_settings(settings)


def _manifest_revision(manifest_path: Path) -> str:
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    return str(payload.get("model_revision") or "")


def _images(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(
        item for item in path.iterdir() if item.suffix.lower() in SUPPORTED_IMAGE_SUFFIXES
    )


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return round(ordered[index], 3)


def _run_once(config, image: Path) -> dict[str, Any]:
    work_dir = Path(tempfile.mkdtemp(prefix="mogen-bench-"))
    started = time.perf_counter()
    try:
        asset = run_object_generation(
            image_bytes=image.read_bytes(),
            config=config,
            work_dir=work_dir,
        )
        elapsed = time.perf_counter() - started
        return {
            "ok": True,
            "seconds": round(elapsed, 3),
            "file_size_bytes": asset.file_size_bytes,
            "sha256": asset.sha256,
            "vertices_count": asset.metadata["vertices_count"],
            "faces_count": asset.metadata["faces_count"],
            "textures_count": asset.metadata["textures_count"],
            "has_textures": asset.metadata.get("has_textures", False),
            "timing": asset.metadata.get("timing", {}),
            "generator": asset.metadata.get("generator", {}),
        }
    except ObjectGenerationError as exc:
        return {
            "ok": False,
            "seconds": round(time.perf_counter() - started, 3),
            "error_code": exc.error_code,
            "message": str(exc),
        }
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _variant(config, image_paths: list[Path], repetitions: int, warmup: int) -> dict[str, Any]:
    generator = create_generator(config, load=True)
    identity = {
        "name": generator.name,
        "revision": generator.revision,
        "model_id": generator.model_id,
        "model_revision": generator.model_revision,
        "device": getattr(generator, "device", config.device),
        "settings": config.sf3d.as_metadata() if generator.name == "sf3d" else {},
    }
    results: list[dict[str, Any]] = []
    for index, image in enumerate(image_paths):
        for _ in range(warmup):
            _run_once(config, image)
        for _ in range(repetitions):
            outcome = _run_once(config, image)
            outcome["image"] = image.name
            outcome["index"] = index
            results.append(outcome)

    successes = [item for item in results if item["ok"]]
    latencies = [item["seconds"] for item in successes]
    peaks = [
        item["generator"].get("peak_cuda_allocated_bytes")
        for item in successes
        if item["generator"].get("peak_cuda_allocated_bytes") is not None
    ]
    return {
        **identity,
        "runs": len(results),
        "successes": len(successes),
        "failures": len(results) - len(successes),
        "failure_rate": round((len(results) - len(successes)) / max(1, len(results)), 4),
        "error_codes": sorted({item["error_code"] for item in results if not item["ok"]}),
        "median_seconds": round(statistics.median(latencies), 3) if latencies else None,
        "p95_seconds": _percentile(latencies, 0.95),
        "mean_file_size_bytes": round(
            sum(item["file_size_bytes"] for item in successes) / max(1, len(successes))
        )
        if successes
        else None,
        "mean_vertices": round(
            sum(item["vertices_count"] for item in successes) / max(1, len(successes))
        )
        if successes
        else None,
        "mean_faces": round(sum(item["faces_count"] for item in successes) / max(1, len(successes)))
        if successes
        else None,
        "textured_outputs": sum(1 for item in successes if item["has_textures"]),
        "peak_cuda_allocated_bytes_max": max(peaks) if peaks else None,
        "per_image": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Object generator benchmark")
    parser.add_argument("--images", type=Path, required=True)
    parser.add_argument("--generators", default="triposr,sf3d")
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--texture-resolution", type=int, default=1024)
    parser.add_argument("--remesh", default="none")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    images = _images(args.images)
    if not images:
        parser.error(f"no supported images under {args.images}")
    names = [item.strip().lower() for item in args.generators.split(",") if item.strip()]

    report: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "images": [item.name for item in images],
        "repetitions": args.repetitions,
        "warmup": args.warmup,
        "device": args.device,
        "variants": [],
    }
    for name in names:
        try:
            config = _config(args.device, name, args.texture_resolution, args.remesh)
            variant = _variant(config, images, args.repetitions, args.warmup)
        except Exception as exc:  # an unavailable generator is a reported variant
            variant = {
                "name": name,
                "error": type(exc).__name__,
                "message": str(exc),
            }
        report["variants"].append(variant)
        reset_generators()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
