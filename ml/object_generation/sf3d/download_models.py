"""Controlled, offline-capable Stable Fast 3D model download.

Run once by the opt-in ``sf3d-model-init`` Compose service before the SF3D
worker starts (13_advanced_object_generation.md Sections 5.1 and 6). It:

1. downloads ``config.yaml`` and ``model.safetensors`` from the pinned, gated
   Hugging Face repository revision into a dedicated cache;
2. computes and writes a checksum manifest that the worker verifies before
   loading;
3. refuses to run without a pinned revision and never logs the access token.

The runtime image is offline (``HF_HUB_OFFLINE=1``); this initializer is the
only component allowed to use the network, and only during controlled
initialization. The gated repository requires a Hugging Face token whose
account has accepted the Stability AI Community License.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

os.environ["HF_HUB_OFFLINE"] = "0"
os.environ["TRANSFORMERS_OFFLINE"] = "0"

MODEL_ID = os.environ.get("OBJECT_SF3D_MODEL_ID") or "stabilityai/stable-fast-3d"
MODEL_REVISION = os.environ.get("OBJECT_SF3D_MODEL_REVISION", "")
MODEL_DIR = Path(os.environ.get("OBJECT_SF3D_MODEL_DIR") or "/models/sf3d")
MANIFEST_PATH = Path(
    os.environ.get("OBJECT_SF3D_MANIFEST_PATH") or (MODEL_DIR / "model-manifest.json")
)
FILES = ("config.yaml", "model.safetensors", "LICENSE.md")
# SF3D loads two public auxiliary models besides its gated checkpoint: the DINOv2
# image tokenizer named in ``config.yaml`` and the open_clip ViT-B-32 LAION
# weights used by the material estimator. The worker runs with
# ``HF_HUB_OFFLINE=1``, so the initializer has to seed those caches too;
# otherwise the first task fails at model load with a missing-cache error.
TOKENIZER_MODEL_ID = os.environ.get("OBJECT_SF3D_TOKENIZER_MODEL_ID") or "facebook/dinov2-large"
CLIP_MODEL = "ViT-B-32"
CLIP_PRETRAINED = "laion2b_s34b_b79k"


def require_revision(value: str) -> str:
    """Reject an unpinned, branch-like revision."""
    if not value or value.lower() in {"main", "master", "head"}:
        message = f"OBJECT_SF3D_MODEL_REVISION must be a concrete revision, got {value!r}"
        raise SystemExit(message)
    return value


def sha256_file(path: Path) -> str:
    """Return the hex SHA-256 of a file, streaming it in 4 MiB blocks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def download(force: bool) -> None:
    """Download the pinned files into MODEL_DIR (idempotent)."""
    from huggingface_hub import snapshot_download

    revision = require_revision(MODEL_REVISION)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    present = all((MODEL_DIR / name).is_file() for name in FILES[:2])
    if force or not present:
        print(f"downloading {MODEL_ID}@{revision} -> {MODEL_DIR}", flush=True)
        try:
            snapshot_download(
                repo_id=MODEL_ID,
                revision=revision,
                local_dir=str(MODEL_DIR),
                allow_patterns=list(FILES),
            )
        except Exception as exc:  # gated access must fail clearly, never silently
            message = (
                "SF3D download failed. The repository is gated: accept the "
                "Stability AI Community License at "
                f"https://huggingface.co/{MODEL_ID} and provide a read token "
                "(HF_TOKEN) for the initializer. No token value is logged."
            )
            raise SystemExit(f"{message} ({type(exc).__name__})") from exc

    missing = [name for name in FILES[:2] if not (MODEL_DIR / name).is_file()]
    if missing:
        raise SystemExit(f"SF3D files missing after download: {missing}")


def download_auxiliary_models() -> dict[str, object]:
    """Cache the public tokenizer and CLIP weights SF3D loads on first use.

    The cache is reused when the host is temporarily offline: the downloads are
    retried with ``local_files_only`` and only a genuinely missing cache is an
    error.
    """
    from huggingface_hub import snapshot_download

    print(
        f"caching auxiliary models: {TOKENIZER_MODEL_ID}, open_clip {CLIP_MODEL}/{CLIP_PRETRAINED}",
        flush=True,
    )
    try:
        tokenizer_snapshot = snapshot_download(repo_id=TOKENIZER_MODEL_ID)
        import open_clip

        open_clip.create_model_and_transforms(CLIP_MODEL, pretrained=CLIP_PRETRAINED)
    except Exception as exc:
        try:
            tokenizer_snapshot = snapshot_download(
                repo_id=TOKENIZER_MODEL_ID, local_files_only=True
            )
            import open_clip

            open_clip.create_model_and_transforms(CLIP_MODEL, pretrained=CLIP_PRETRAINED)
        except Exception as offline_exc:
            raise SystemExit(
                "SF3D auxiliary model download failed and no complete cache exists "
                f"({type(exc).__name__}/{type(offline_exc).__name__}). The worker is "
                "offline; rerun the initializer with network access."
            ) from offline_exc
        print("auxiliary model cache complete; continuing offline", flush=True)
    return {
        "image_tokenizer": {"model_id": TOKENIZER_MODEL_ID, "snapshot": tokenizer_snapshot},
        "clip": {"model": CLIP_MODEL, "pretrain": CLIP_PRETRAINED},
    }


def write_manifest(auxiliary: dict[str, object] | None = None) -> dict[str, object]:
    """Write the checksum manifest the worker verifies before loading."""
    files: dict[str, dict[str, object]] = {}
    for name in FILES[:2]:
        path = MODEL_DIR / name
        files[name] = {"sha256": sha256_file(path), "bytes": path.stat().st_size}
    manifest: dict[str, object] = {
        "model_id": MODEL_ID,
        "model_revision": MODEL_REVISION,
        "files": files,
        "source": "https://github.com/Stability-AI/stable-fast-3d",
        "license": "Stability AI Community License",
        "generated_at": datetime.now(UTC).isoformat(),
    }
    if auxiliary:
        manifest["auxiliary"] = auxiliary
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    print(f"SF3D manifest written to {MANIFEST_PATH}")
    return manifest


def main() -> int:
    """Populate the SF3D cache and write its manifest."""
    force = os.environ.get("OBJECT_SF3D_FORCE_DOWNLOAD", "").lower() in {"1", "true", "yes"}
    require_revision(MODEL_REVISION)
    download(force=force)
    manifest = write_manifest(download_auxiliary_models())
    print(
        f"SF3D ready: {manifest['model_id']}@{manifest['model_revision']} "
        f"({manifest['files']['model.safetensors']['bytes']} bytes)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
