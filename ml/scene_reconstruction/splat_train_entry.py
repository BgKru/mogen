"""Pinned Splatfacto training entry point for the neural scene worker (15 §5.1).

Nerfstudio's ``ns-train`` CLI imports every registered method, which drags in
compiled dependencies the Splatfacto path does not need. This entry point builds
the same ``TrainerConfig`` that the upstream ``splatfacto`` method registration
uses (copied from Nerfstudio 1.1.5), but imports only the dataparser,
datamanager, pipeline, model and trainer modules required for training.

It is executed as a controlled subprocess by
:mod:`scene_reconstruction.nerfstudio_runner`; nothing here is imported by the
COLMAP/OpenMVS pipeline. Two modes exist:

* ``--verify`` — print a JSON runtime fingerprint (versions, CUDA, gsplat kernel
  execution) and exit; used by the worker preflight and the image build;
* training — write the resolved configuration, train, and print a JSON summary.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path
from typing import Any

EXIT_TRAINING_FAILED = 2
EXIT_RUNTIME_UNAVAILABLE = 3


def _package_version(distribution: str, module: object) -> str:
    """Return an installed version, falling back to the module attribute."""
    try:
        from importlib.metadata import version  # noqa: PLC0415

        return version(distribution)
    except Exception:  # noqa: BLE001 - diagnostics must never fail the run
        return str(getattr(module, "__version__", "unknown"))


def _runtime_fingerprint() -> dict[str, Any]:
    """Return versions and CUDA facts without importing the training stack twice."""
    import gsplat  # noqa: PLC0415 - deliberately lazy
    import nerfstudio  # noqa: PLC0415
    import torch  # noqa: PLC0415

    fingerprint: dict[str, Any] = {
        "nerfstudio": _package_version("nerfstudio", nerfstudio),
        "gsplat": _package_version("gsplat", gsplat),
        "torch": torch.__version__,
        "cuda_build": torch.version.cuda,
        "python": sys.version.split()[0],
        "cuda_available": bool(torch.cuda.is_available()),
        "device_name": None,
        "kernel_executed": False,
    }
    if fingerprint["cuda_available"]:
        fingerprint["device_name"] = torch.cuda.get_device_name(0)
    return fingerprint


def _run_kernel_probe() -> bool:
    """Execute a one-Gaussian gsplat rasterization to prove the CUDA kernels run."""
    import torch  # noqa: PLC0415
    from gsplat.rendering import rasterization  # noqa: PLC0415

    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.float32
    means = torch.tensor([[0.0, 0.0, 2.0]], device=device, dtype=dtype)
    quats = torch.tensor([[1.0, 0.0, 0.0, 0.0]], device=device, dtype=dtype)
    scales = torch.full((1, 3), -2.0, device=device, dtype=dtype)
    opacities = torch.ones(1, device=device, dtype=dtype)
    colours = torch.zeros((1, 3), device=device, dtype=dtype)
    viewmats = torch.eye(4, device=device, dtype=dtype)[None]
    intrinsics = torch.tensor(
        [[[40.0, 0.0, 32.0], [0.0, 40.0, 32.0], [0.0, 0.0, 1.0]]], device=device, dtype=dtype
    )
    rendered, _alpha, _meta = rasterization(
        means,
        quats,
        scales,
        opacities,
        colours,
        viewmats,
        intrinsics,
        64,
        64,
        sh_degree=None,
    )
    return bool(torch.isfinite(rendered).all())


def verify_runtime(*, run_kernel: bool) -> dict[str, Any]:
    """Return the runtime fingerprint; raise when the pinned stack is unusable."""
    fingerprint = _runtime_fingerprint()
    if run_kernel:
        started = time.monotonic()
        fingerprint["kernel_executed"] = _run_kernel_probe()
        fingerprint["kernel_seconds"] = round(time.monotonic() - started, 3)
    return fingerprint


def _build_config(args: argparse.Namespace) -> Any:
    """Build the upstream 1.1.5 Splatfacto TrainerConfig for one dataset."""
    from nerfstudio.configs.base_config import (
        LocalWriterConfig,
        LoggingConfig,
        MachineConfig,
        ViewerConfig,
    )
    from nerfstudio.data.datamanagers.full_images_datamanager import FullImageDatamanagerConfig
    from nerfstudio.data.dataparsers.nerfstudio_dataparser import NerfstudioDataParserConfig
    from nerfstudio.engine.optimizers import AdamOptimizerConfig
    from nerfstudio.engine.schedulers import ExponentialDecaySchedulerConfig
    from nerfstudio.engine.trainer import TrainerConfig
    from nerfstudio.models.splatfacto import SplatfactoModelConfig
    from nerfstudio.pipelines.base_pipeline import VanillaPipelineConfig

    max_steps = args.max_iterations
    dataparser = NerfstudioDataParserConfig(
        data=Path(args.data),
        # The transforms.json is already in the documented z-up viewer frame
        # (applied_transform is baked into the poses and sparse points), so no
        # hidden re-orientation/centering/scaling is applied. This keeps the
        # exported PLY in the same world frame the dataset was validated in.
        orientation_method="none",
        center_method="none",
        auto_scale_poses=False,
        downscale_factor=1,
        load_3D_points=True,
        eval_mode="fraction",
        train_split_fraction=0.9,
    )
    model = SplatfactoModelConfig(sh_degree=args.sh_degree)
    pipeline = VanillaPipelineConfig(
        datamanager=FullImageDatamanagerConfig(
            dataparser=dataparser,
            cache_images_type="uint8",
        ),
        model=model,
    )
    return TrainerConfig(
        method_name="splatfacto",
        experiment_name="mogen_scene",
        project_name="mogen",
        output_dir=Path(args.output_dir),
        timestamp="run",
        steps_per_eval_image=max(1, max_steps // 2),
        steps_per_eval_batch=max_steps,
        steps_per_eval_all_images=max(1, max_steps // 2),
        steps_per_save=args.steps_per_save,
        max_num_iterations=max_steps,
        mixed_precision=False,
        save_only_latest_checkpoint=False,
        pipeline=pipeline,
        optimizers={
            "means": {
                "optimizer": AdamOptimizerConfig(lr=1.6e-4, eps=1e-15),
                "scheduler": ExponentialDecaySchedulerConfig(lr_final=1.6e-6, max_steps=max_steps),
            },
            "features_dc": {
                "optimizer": AdamOptimizerConfig(lr=0.0025, eps=1e-15),
                "scheduler": None,
            },
            "features_rest": {
                "optimizer": AdamOptimizerConfig(lr=0.0025 / 20, eps=1e-15),
                "scheduler": None,
            },
            "opacities": {
                "optimizer": AdamOptimizerConfig(lr=0.05, eps=1e-15),
                "scheduler": None,
            },
            "scales": {
                "optimizer": AdamOptimizerConfig(lr=0.005, eps=1e-15),
                "scheduler": None,
            },
            "quats": {"optimizer": AdamOptimizerConfig(lr=0.001, eps=1e-15), "scheduler": None},
            "camera_opt": {
                "optimizer": AdamOptimizerConfig(lr=1e-4, eps=1e-15),
                "scheduler": ExponentialDecaySchedulerConfig(
                    lr_final=5e-7, max_steps=max_steps, warmup_steps=1000, lr_pre_warmup=0
                ),
            },
            "bilateral_grid": {
                "optimizer": AdamOptimizerConfig(lr=2e-3, eps=1e-15),
                "scheduler": ExponentialDecaySchedulerConfig(
                    lr_final=1e-4, max_steps=max_steps, warmup_steps=1000, lr_pre_warmup=0
                ),
            },
        },
        machine=MachineConfig(device_type=args.device, seed=args.seed, num_devices=1),
        logging=LoggingConfig(
            relative_log_dir="./",
            steps_per_log=args.steps_per_log or 50,
            local_writer=LocalWriterConfig(enable=False),
        ),
        viewer=ViewerConfig(num_rays_per_chunk=1 << 15, quit_on_train_completion=True),
        vis="tensorboard",
    )


def _read_eval_metrics(base_dir: Path) -> dict[str, float]:
    """Read the last evaluation scalars from the run's TensorBoard events."""
    try:
        from tensorboard.backend.event_processing.event_accumulator import (  # noqa: PLC0415
            EventAccumulator,
        )
    except Exception:  # pragma: no cover - tensorboard is a pinned runtime dependency
        return {}
    metrics: dict[str, float] = {}
    try:
        for event_file in sorted(base_dir.rglob("events.out.tfevents.*")):
            accumulator = EventAccumulator(str(event_file), size_guidance={"scalars": 0})
            accumulator.Reload()
            for tag in accumulator.Tags().get("scalars", []):
                if not (
                    tag.startswith("Eval Images Metrics") or tag.startswith("Eval Metrics Dict")
                ):
                    continue
                if not any(
                    marker in tag.lower() for marker in ("psnr", "ssim", "lpips", "num_rays")
                ):
                    continue
                events = accumulator.Scalars(tag)
                if events:
                    metrics[tag] = round(float(events[-1].value), 6)
    except Exception:  # pragma: no cover - metrics are diagnostics only
        return metrics
    return metrics


def train(args: argparse.Namespace) -> dict[str, Any]:
    """Run training and return a JSON-safe summary."""
    config = _build_config(args)
    config.set_timestamp()
    base_dir = config.get_base_dir()
    base_dir.mkdir(parents=True, exist_ok=True)
    config.save_config()
    started = time.monotonic()
    trainer = config.setup(local_rank=0, world_size=1)
    trainer.setup()
    trainer.train()
    duration = round(time.monotonic() - started, 3)
    checkpoint_dir = config.get_checkpoint_dir()
    checkpoints = sorted(checkpoint_dir.glob("step-*.ckpt"))
    summary = {
        "status": "completed",
        "base_dir": str(base_dir),
        "checkpoint_dir": str(checkpoint_dir),
        "checkpoint": str(checkpoints[-1]) if checkpoints else None,
        "checkpoint_count": len(checkpoints),
        "iterations": int(config.max_num_iterations),
        "steps_per_save": int(config.steps_per_save),
        "train_seconds": duration,
        "sh_degree": int(args.sh_degree),
        "seed": int(args.seed),
        "device": args.device,
        "metrics": _read_eval_metrics(base_dir),
    }
    (base_dir / "training_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mogen-splat-train")
    parser.add_argument("--data", type=Path, help="Nerfstudio dataset directory (transforms.json)")
    parser.add_argument("--output-dir", type=Path, help="Run output directory inside the workspace")
    parser.add_argument("--max-iterations", type=int, default=30_000)
    parser.add_argument("--steps-per-save", type=int, default=5000)
    parser.add_argument("--sh-degree", type=int, default=3)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    parser.add_argument("--steps-per-log", type=int, default=50)
    parser.add_argument("--verify", action="store_true", help="Print the runtime fingerprint")
    parser.add_argument(
        "--skip-kernel", action="store_true", help="Skip the gsplat kernel probe in --verify"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.verify:
        try:
            fingerprint = verify_runtime(run_kernel=not args.skip_kernel)
        except Exception:
            traceback.print_exc()
            return EXIT_RUNTIME_UNAVAILABLE
        print("MOGEN_SPLAT_RUNTIME " + json.dumps(fingerprint, sort_keys=True))
        if args.skip_kernel:
            return 0 if fingerprint.get("cuda_available") else EXIT_RUNTIME_UNAVAILABLE
        return 0 if fingerprint.get("kernel_executed") else EXIT_RUNTIME_UNAVAILABLE
    if args.data is None or args.output_dir is None:
        print("--data and --output-dir are required for training", file=sys.stderr)
        return EXIT_TRAINING_FAILED
    try:
        summary = train(args)
    except Exception:
        traceback.print_exc()
        return EXIT_TRAINING_FAILED
    print("MOGEN_SPLAT_TRAIN " + json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - subprocess entry point
    raise SystemExit(main())
