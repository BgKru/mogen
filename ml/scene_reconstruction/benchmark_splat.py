"""Reproducible mesh-vs-splat benchmark (increment 15 Section 10.4).

The benchmark compares the two scene representations on the **same** validated
COLMAP cameras and image set:

* mesh: the existing COLMAP + OpenMVS result (facts are read from a validated
  GLB; running the whole mesh pipeline is optional with ``--run-mesh``);
* splat: Nerfstudio Splatfacto with the configured iteration/image budget, then
  the Gaussian PLY export.

It records representation-appropriate metrics only: mesh geometry counts are
never compared with Gaussian count as if they were the same quality measure.
Rendered quality is reported from the trainer's held-out evaluation split when
available (PSNR/SSIM logged by Nerfstudio); it is marked unavailable otherwise.

Example (inside the neural worker image, GPU, retained Sceaux workspace):

    python -m scene_reconstruction.benchmark_splat \
        --workspace /proof/scene-check-iq \
        --mesh-glb /proof/scene-check-iq/output/scene.glb \
        --iterations 3000 --max-dimension 800 --repetitions 1 \
        --output /proof/increment15/benchmark/splat-benchmark.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import time
from pathlib import Path
from typing import Any

from PIL import Image

from .config import SceneConfig
from .dataset import PreparedImage, SceneDataset
from .neural_pipeline import NeuralReconstructor, build_splat_manifest
from .splat_config import SplatConfig
from .validator import validate_scene_glb


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _scene_dataset(workspace: Path, images_dir: Path) -> SceneDataset:
    prepared = []
    for path in sorted(images_dir.iterdir()):
        if not path.is_file():
            continue
        with Image.open(path) as image:
            width, height = image.size
            image_format = (image.format or "JPEG").upper()
        prepared.append(
            PreparedImage(
                path=path,
                filename=path.name,
                original_filename=path.name,
                image_id=path.stem,
                sha256=_sha256(path),
                size_bytes=path.stat().st_size,
                format=image_format,
                width=width,
                height=height,
            )
        )
    return SceneDataset(work_dir=workspace, images_dir=images_dir, images=tuple(prepared))


def _mesh_facts(workspace: Path, mesh_glb: Path | None) -> dict[str, Any] | None:
    if mesh_glb is None or not Path(mesh_glb).is_file():
        return None
    validation = validate_scene_glb(Path(mesh_glb), require_textures=False)
    return {
        "representation": "MESH",
        "method": "COLMAP_OPENMVS",
        "source": str(mesh_glb),
        "file_size_bytes": validation.file_size_bytes,
        "sha256": validation.sha256,
        "vertices": validation.vertices_count,
        "faces": validation.faces_count,
        "materials": validation.materials_count,
        "textures": validation.textures_count,
        "note": "facts read from the validated retained GLB; no polygon/Gaussian equivalence",
    }


def _splat_run(
    workspace: Path,
    *,
    iterations: int,
    max_dimension: int,
    run_dir: Path,
) -> dict[str, Any]:
    splat = SplatConfig(
        enabled=True,
        min_registered_images=3,
        max_iterations=iterations,
        checkpoint_interval=max(100, iterations // 3),
        max_image_dimension=max_dimension,
        image_scale=1.0,
        sh_degree=3,
        device="cuda",
    )
    config = SceneConfig(
        representation="GAUSSIAN_SPLAT",
        output_format="PLY",
        splat=splat,
        work_root=run_dir,
        min_registered_images=3,
    )
    dataset = _scene_dataset(workspace, workspace / "colmap" / "dense" / "images")
    reconstructor = NeuralReconstructor(config)
    started = time.monotonic()
    vram = reconstructor.check_vram()
    runtime = reconstructor.runtime_report()
    converted = reconstructor.prepare(
        dataset,
        model_dir=workspace / "colmap" / "dense" / "sparse",
        images_dir=workspace / "colmap" / "dense" / "images",
        work_dir=run_dir,
        runtime=runtime,
    )
    manifest = build_splat_manifest(dataset=converted, runtime=runtime, splat=splat)
    training = reconstructor.train(dataset=converted, work_dir=run_dir, timeout=7200)
    export = reconstructor.export(checkpoint_path=training.checkpoint_path, work_dir=run_dir)
    total = time.monotonic() - started
    return {
        "representation": "GAUSSIAN_SPLAT",
        "method": "NERFSTUDIO_SPLATFACTO",
        "dataset_fingerprint": converted.fingerprint,
        "registered_images": converted.registered_images,
        "sparse_points": converted.sparse_points,
        "reprojection_median_px": round(converted.convention.reprojection_median_px, 4),
        "iterations": iterations,
        "max_image_dimension": max_dimension,
        "train_seconds": round(float(training.duration_seconds), 3),
        "total_seconds": round(total, 3),
        "gaussian_count": export.gaussian_count,
        "ply_file_size_bytes": export.file_size_bytes,
        "training_metrics": training.metrics,
        "vram": vram.as_metadata() if vram is not None else None,
        "runtime": runtime.as_metadata(),
        "manifest_sha256": hashlib.sha256(
            json.dumps(manifest, sort_keys=True).encode("utf-8")
        ).hexdigest(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mogen-splat-benchmark")
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--mesh-glb", type=Path, default=None)
    parser.add_argument("--iterations", type=int, default=3000)
    parser.add_argument("--max-dimension", type=int, default=800)
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    workspace = Path(args.workspace)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "benchmark": "mesh_vs_gaussian_splat",
        "schema": "mogen_splat_benchmark_v1",
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "workspace": str(workspace),
        },
        "mesh": _mesh_facts(workspace, args.mesh_glb),
        "splat": [],
        "notes": [
            "Both representations consume the same validated COLMAP dense model.",
            "Mesh facts are geometry/appearance facts; Gaussian count is not compared "
            "with polygon count as a quality measure.",
            "Rendered PSNR/SSIM come from the trainer's held-out 10% evaluation split "
            "when the pinned Nerfstudio build logs them.",
        ],
    }
    for repetition in range(max(1, args.repetitions)):
        run_dir = output.parent / f"splat-run-{repetition}"
        if run_dir.exists():
            import shutil

            shutil.rmtree(run_dir)
        started = time.monotonic()
        try:
            result = _splat_run(
                workspace,
                iterations=args.iterations,
                max_dimension=args.max_dimension,
                run_dir=run_dir,
            )
            result["status"] = "completed"
        except Exception as exc:  # benchmark records failures honestly
            result = {
                "representation": "GAUSSIAN_SPLAT",
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
                "total_seconds": round(time.monotonic() - started, 3),
            }
        result["repetition"] = repetition
        report["splat"].append(result)
        print(json.dumps(result, indent=2, sort_keys=True, default=str))

    completed = [run for run in report["splat"] if run.get("status") == "completed"]
    if completed:
        report["summary"] = {
            "successful_runs": len(completed),
            "failed_runs": len(report["splat"]) - len(completed),
            "median_total_seconds": round(
                statistics.median(float(run["total_seconds"]) for run in completed), 3
            ),
            "median_train_seconds": round(
                statistics.median(float(run["train_seconds"]) for run in completed), 3
            ),
            "median_gaussian_count": int(
                statistics.median(int(run["gaussian_count"]) for run in completed)
            ),
            "median_ply_bytes": int(
                statistics.median(int(run["ply_file_size_bytes"]) for run in completed)
            ),
        }
    output.write_text(json.dumps(report, indent=2, sort_keys=True, default=str), encoding="utf-8")
    print(f"benchmark written to {output}")
    return 0 if completed else 1


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
