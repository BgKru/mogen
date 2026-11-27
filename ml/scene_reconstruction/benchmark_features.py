"""Reproducible feature-matching benchmark (12 Section 10.3).

Compares the existing COLMAP SIFT strategies with the ALIKED + LightGlue
profiles on identical prepared images and hardware. It stops after the sparse
model is inspected; OpenMVS is not run, because the feature stages are the
subject of this increment. The script is a manual benchmark tool, not part of
the default unit-test suite.

Example (inside the scene worker image, GPU enabled):

    python -m scene_reconstruction.benchmark_features \
        --images /data/sceaux --output /proof/feature-benchmark.json \
        --device cuda
"""

from __future__ import annotations

import argparse
import json
import resource
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from .colmap_runner import ColmapRunner, model_is_present, read_database_stats
from .config import SceneConfig
from .dataset import SourceImage, prepare_dataset
from .exceptions import SceneReconstructionError
from .feature_matching import (
    build_feature_backend,
    build_feature_manifest,
    feature_manifest_path,
    manifest_matches,
    write_feature_manifest,
)
from .feature_profiles import BACKEND_ALIKED_LIGHTGLUE, BACKEND_COLMAP_SIFT
from .preflight import verify_toolchain
from .reconstruction_selector import inspect_model, select_reconstruction

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


@dataclass(frozen=True, slots=True)
class Variant:
    name: str
    backend: str
    profile: str
    strategy: str
    max_keypoints: int = 2048


VARIANTS = (
    Variant("sift_exhaustive", BACKEND_COLMAP_SIFT, "sift_default", "EXHAUSTIVE"),
    Variant("sift_sequential", BACKEND_COLMAP_SIFT, "sift_default", "SEQUENTIAL"),
    Variant("aliked_exhaustive", BACKEND_ALIKED_LIGHTGLUE, "aliked_lightglue", "EXHAUSTIVE"),
    Variant("aliked_sequential", BACKEND_ALIKED_LIGHTGLUE, "aliked_lightglue", "SEQUENTIAL"),
    Variant(
        "aliked_lightglue_fast_exhaustive",
        BACKEND_ALIKED_LIGHTGLUE,
        "aliked_lightglue_fast",
        "EXHAUSTIVE",
    ),
)


def _images(directory: Path) -> list[Path]:
    return sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    )


def _peak_rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


def run_variant(
    variant: Variant,
    paths: list[Path],
    *,
    work_root: Path,
    device: str,
    colmap_version: str,
) -> dict[str, object]:
    workspace = work_root / variant.name
    if workspace.exists():
        shutil.rmtree(workspace)
    config = SceneConfig(
        feature_backend=variant.backend,
        feature_profile=variant.profile,
        feature_pair_strategy=variant.strategy,
        feature_device=device,
        feature_max_keypoints=variant.max_keypoints,
        work_root=work_root,
    )
    started = time.monotonic()
    dataset = prepare_dataset([SourceImage.from_path(path) for path in paths], work_dir=workspace)
    backend = build_feature_backend(config)
    runtime = backend.verify_runtime(config)
    colmap_dir = workspace / "colmap"
    colmap_dir.mkdir(parents=True, exist_ok=True)
    database = colmap_dir / "database.db"
    manifest = build_feature_manifest(
        dataset, config, backend=backend.name, colmap_version=colmap_version
    )
    extraction = backend.extract_features(
        dataset,
        images_dir=workspace / "images",
        database_path=database,
        work_dir=workspace,
        on_poll=lambda: None,
    )
    matching = backend.match_features(
        dataset,
        images_dir=workspace / "images",
        database_path=database,
        work_dir=workspace,
        on_poll=lambda: None,
    )
    write_feature_manifest(feature_manifest_path(colmap_dir), manifest)
    stats = read_database_stats(database)
    runner = ColmapRunner(config)
    sparse_dir = workspace / "colmap" / "sparse"
    sparse_seconds = 0.0
    registered = 0
    points = 0
    reprojection = None
    model_name = None
    try:
        sparse = runner.reconstruct_sparse(
            images_dir=workspace / "images",
            database_path=database,
            sparse_dir=sparse_dir,
            log_path=workspace / "logs" / "mapping.log",
        )
        sparse_seconds = sparse.duration_seconds
        models = [model for model in sparse.model_dirs if model_is_present(model)]
        if models:
            text_root = workspace / "colmap" / "models_txt"
            candidates = []
            for model_dir in models:
                text_dir = text_root / model_dir.name
                runner.convert_model(
                    model_dir=model_dir,
                    output_dir=text_dir,
                    log_path=workspace / "logs" / "convert.log",
                )
                candidates.append(inspect_model(model_dir, text_dir, dataset.image_count))
            selection = select_reconstruction(candidates, config)
            model_name = selection.selected.model_dir.name
            registered = selection.selected.registered_images
            points = selection.selected.points
            reprojection = selection.selected.mean_reprojection_error
    except SceneReconstructionError as exc:
        return {
            "variant": variant.name,
            "success": False,
            "error": exc.error_code,
            "extraction_seconds": round(extraction.seconds, 3),
            "matching_seconds": round(matching.seconds, 3),
            "sparse_seconds": round(sparse_seconds, 3),
            "total_seconds": round(time.monotonic() - started, 3),
        }
    return {
        "variant": variant.name,
        "backend": backend.name,
        "profile": variant.profile,
        "strategy": variant.strategy,
        "device": runtime.device,
        "versions": runtime.versions,
        "images": dataset.image_count,
        "keypoints_total": extraction.keypoints_total,
        "keypoints_min": extraction.keypoints_min,
        "keypoints_max": extraction.keypoints_max,
        "pairs": matching.pairs,
        "pairs_with_matches": matching.pairs_with_matches,
        "tentative_matches": stats.matched_pairs,
        "verified_pairs": stats.verified_pairs,
        "components": stats.components,
        "largest_component": stats.largest_component,
        "registered_images": registered,
        "registration_ratio": round(registered / dataset.image_count, 4),
        "points": points,
        "mean_reprojection_error": reprojection,
        "model": model_name,
        "success": True,
        "extraction_seconds": round(extraction.seconds, 3),
        "matching_seconds": round(matching.seconds, 3),
        "sparse_seconds": round(sparse_seconds, 3),
        "total_seconds": round(time.monotonic() - started, 3),
        "peak_vram_mb": matching.peak_vram_mb or extraction.peak_vram_mb,
        "process_peak_rss_mb": round(_peak_rss_mb(), 1),
        "manifest_matches": manifest_matches(feature_manifest_path(colmap_dir), manifest),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Feature-matching benchmark")
    parser.add_argument("--images", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("feature-benchmark.json"))
    parser.add_argument("--work-root", type=Path, default=Path("/tmp/feature-benchmark"))
    parser.add_argument("--device", choices=("auto", "cuda", "cpu"), default="auto")
    parser.add_argument("--colmap", default="/usr/local/bin/colmap")
    parser.add_argument("--openmvs-dir", default="/usr/local/bin/OpenMVS")
    args = parser.parse_args(argv)

    paths = _images(args.images)
    if len(paths) < 3:
        parser.error("at least three photographs are required")
    config = SceneConfig(
        colmap_executable=Path(args.colmap),
        openmvs_bin_dir=Path(args.openmvs_dir),
    )
    toolchain = verify_toolchain(config)
    colmap_version = toolchain.as_dict().get("colmap", "")
    args.work_root.mkdir(parents=True, exist_ok=True)
    results = []
    for variant in VARIANTS:
        print(f"[benchmark] {variant.name}", flush=True)
        result = run_variant(
            variant,
            paths,
            work_root=args.work_root,
            device=args.device,
            colmap_version=colmap_version,
        )
        print(json.dumps(result, indent=2), flush=True)
        results.append(result)
    document = {
        "images": [path.name for path in paths],
        "image_count": len(paths),
        "device": args.device,
        "colmap": colmap_version,
        "variants": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2), encoding="utf-8")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
