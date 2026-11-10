"""Standalone scene-reconstruction proof (roadmap 6.2 and 6.1 verification).

Runs exactly the production pipeline outside Celery and PostgreSQL, so a real
COLMAP/OpenMVS reconstruction can be executed and inspected before the worker is
integrated:

    python -m scene_reconstruction.standalone --images /data/SceauxCastle \
        --work-dir /tmp/scene-proof --output /tmp/scene-proof/scene.glb

``--verify-tools`` only checks the external executables and prints their
versions, which is the evidence required by 08_infrastructure.md Section 4.4.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import shutil
import sys
from pathlib import Path

from .config import SceneConfig
from .dataset import SourceImage
from .exceptions import SceneCancelled, SceneReconstructionError
from .pipeline import PhotogrammetryReconstructor, PipelineCallbacks
from .preflight import verify_toolchain

IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png"})


def _collect_images(arguments: list[str]) -> list[Path]:
    collected: list[Path] = []
    for argument in arguments:
        path = Path(argument)
        if path.is_dir():
            collected.extend(
                sorted(
                    child
                    for child in path.iterdir()
                    if child.is_file() and child.suffix.lower() in IMAGE_SUFFIXES
                )
            )
        elif path.is_file():
            collected.append(path)
        else:
            raise SystemExit(f"Not an image file or directory: {argument}")
    return collected


def _config_from_args(args: argparse.Namespace) -> SceneConfig:
    config = SceneConfig(
        colmap_executable=Path(args.colmap),
        openmvs_bin_dir=Path(args.openmvs_dir),
        matching_strategy=args.matching,
        colmap_use_gpu=not args.no_gpu,
        max_image_size=args.max_image_size,
        max_threads=args.threads,
        enable_mesh_refinement=not args.no_refine,
        enable_texture_generation=not args.no_texture,
    )
    if args.min_registered_images is not None or args.min_registration_ratio is not None:
        config = dataclasses.replace(
            config,
            min_registered_images=(
                args.min_registered_images
                if args.min_registered_images is not None
                else config.min_registered_images
            ),
            min_registration_ratio=(
                args.min_registration_ratio
                if args.min_registration_ratio is not None
                else config.min_registration_ratio
            ),
        )
    return config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Standalone COLMAP/OpenMVS proof")
    parser.add_argument(
        "--images",
        nargs="*",
        default=[],
        help="image files or directories (required unless --verify-tools is used)",
    )
    parser.add_argument("--work-dir", type=Path, default=Path("/tmp/mogen-scene-proof"))
    parser.add_argument("--output", type=Path, default=None, help="copy the GLB here")
    parser.add_argument("--colmap", default="/usr/local/bin/colmap")
    parser.add_argument("--openmvs-dir", default="/usr/local/bin/OpenMVS")
    parser.add_argument("--matching", choices=("EXHAUSTIVE", "SEQUENTIAL"), default="EXHAUSTIVE")
    parser.add_argument("--max-image-size", type=int, default=2000)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--min-images", type=int, default=3)
    parser.add_argument("--max-images", type=int, default=100)
    parser.add_argument("--min-registered-images", type=int, default=None)
    parser.add_argument("--min-registration-ratio", type=float, default=None)
    parser.add_argument("--no-gpu", action="store_true", help="disable COLMAP GPU features")
    parser.add_argument("--no-refine", action="store_true")
    parser.add_argument("--no-texture", action="store_true")
    parser.add_argument(
        "--verify-tools",
        action="store_true",
        help="only verify the external executables and exit",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = _config_from_args(args)

    if args.verify_tools:
        report = verify_toolchain(config)
        print(json.dumps({"verified": report.verified, "tools": report.as_dict()}, indent=2))
        return 0

    if not args.images:
        parser.error("--images is required unless --verify-tools is used")

    images = _collect_images(args.images)
    sources = [SourceImage.from_path(path) for path in images]

    def report_stage(stage: str, message: str) -> None:
        print(f"[stage] {stage}: {message}", file=sys.stderr)

    callbacks = PipelineCallbacks(report_stage=report_stage)
    reconstructor = PhotogrammetryReconstructor(config, callbacks=callbacks)
    try:
        artifact = reconstructor.reconstruct(
            sources, work_dir=args.work_dir, min_images=args.min_images, max_images=args.max_images
        )
    except SceneCancelled:
        print(json.dumps({"status": "cancelled"}), file=sys.stderr)
        return 130
    except SceneReconstructionError as exc:
        print(
            json.dumps({"status": "failed", "error_code": exc.error_code, "message": str(exc)}),
            file=sys.stderr,
        )
        return 1

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(artifact.path, args.output)

    print(
        json.dumps(
            {
                "status": "completed",
                "glb": str(artifact.path),
                "output": str(args.output) if args.output else None,
                "sha256": artifact.sha256,
                "file_size_bytes": artifact.file_size_bytes,
                "metadata": artifact.metadata,
            },
            indent=2,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
