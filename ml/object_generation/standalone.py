"""Standalone inference/GLB proof (roadmap task 5.2).

This CLI runs exactly the production pipeline — the same preprocessing, model,
mesh extraction, exporter and validator the Celery worker uses — without a
database or Redis. It exists to satisfy the mandatory standalone proof before
backend integration and can be rerun at any time:

    python -m object_generation.standalone \
        --image /testdata/car-1.jpg \
        --output-dir /tmp/triposr-proof \
        --model-dir /models/triposr

The resulting GLB is validated inside the pipeline and then loaded again with
trimesh by ``tests/test_real_inference.py`` and with the Three.js
``GLTFLoader`` by ``viewer/load_glb.mjs``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .config import ObjectGenerationConfig
from .exceptions import ObjectGenerationError
from .pipeline import PipelineCallbacks, run_object_generation


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Standalone TripoSR inference and GLB export")
    parser.add_argument("--image", required=True, type=Path, help="Real source photograph")
    parser.add_argument("--output-dir", required=True, type=Path, help="Working/output directory")
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=Path(os.environ.get("TRIPOSR_MODEL_DIR", "/models/triposr")),
    )
    parser.add_argument("--device", default=os.environ.get("OBJECT_DEVICE", "cuda:0"))
    parser.add_argument("--allow-cpu-fallback", action="store_true")
    parser.add_argument("--chunk-size", type=int, default=8192)
    parser.add_argument("--mc-resolution", type=int, default=256)
    parser.add_argument("--foreground-ratio", type=float, default=0.85)
    parser.add_argument("--no-remove-background", action="store_true")
    parser.add_argument("--max-seconds", type=int, default=1800)
    parser.add_argument("--model-sha256", default=os.environ.get("TRIPOSR_MODEL_SHA256", ""))
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the pipeline and print a machine-readable summary."""
    args = _parser().parse_args(argv)
    if not args.image.is_file():
        print(f"source image not found: {args.image}", file=sys.stderr)
        return 2
    config = ObjectGenerationConfig(
        model_dir=args.model_dir,
        model_revision=os.environ.get("TRIPOSR_MODEL_REVISION", "standalone"),
        model_sha256=args.model_sha256,
        device=args.device,
        allow_cpu_fallback=args.allow_cpu_fallback,
        chunk_size=args.chunk_size,
        mc_resolution=args.mc_resolution,
        remove_background=not args.no_remove_background,
        foreground_ratio=args.foreground_ratio,
        max_task_seconds=args.max_seconds,
    )

    def report(stage: str, message: str) -> None:
        print(f"[stage] {stage}: {message}", flush=True)

    try:
        asset = run_object_generation(
            image_bytes=args.image.read_bytes(),
            config=config,
            work_dir=args.output_dir,
            callbacks=PipelineCallbacks(report_stage=report),
        )
    except ObjectGenerationError as exc:
        print(f"[error] {exc.error_code}: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "glb_path": str(asset.path),
                "sha256": asset.sha256,
                "file_size_bytes": asset.file_size_bytes,
                "format": asset.format,
                "mime_type": asset.mime_type,
                "metadata": asset.metadata,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
