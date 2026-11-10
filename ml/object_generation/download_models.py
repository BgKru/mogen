"""Controlled, offline-capable model download for the Object Worker.

Run once by the ``model-init`` Compose service before the worker starts
(06_object_generation.md Section 4.5). It:

1. downloads the TripoSR ``config.yaml`` and ``model.ckpt`` at the pinned
   Hugging Face revision into the persistent ``/models`` volume;
2. verifies the checkpoint SHA-256 against ``TRIPOSR_MODEL_SHA256``;
3. seeds the Hugging Face cache with the pinned ``facebook/dino-vitb16``
   config so TripoSR never needs the network during a task;
4. downloads the rembg ``u2net`` background-removal weights;
5. writes a manifest describing exactly what is cached.

The worker image sets ``HF_HUB_OFFLINE=1``; this script is the only component
allowed to use the network, and only during controlled initialization.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

# The runtime image is offline by default. Initialization is the one controlled
# exception, so lift the offline flags before huggingface_hub is imported.
os.environ["HF_HUB_OFFLINE"] = "0"
os.environ["TRANSFORMERS_OFFLINE"] = "0"

TRIPOSR_REPO_ID = (
    os.environ.get("OBJECT_MODEL_ID") or os.environ.get("TRIPOSR_MODEL_ID") or "stabilityai/TripoSR"
)
TRIPOSR_REVISION = os.environ.get("OBJECT_MODEL_REVISION") or os.environ.get(
    "TRIPOSR_MODEL_REVISION", ""
)
TRIPOSR_SHA256 = (
    (os.environ.get("OBJECT_MODEL_SHA256") or os.environ.get("TRIPOSR_MODEL_SHA256", ""))
    .strip()
    .lower()
)
MODEL_DIR = Path(
    os.environ.get("OBJECT_MODEL_DIR") or os.environ.get("TRIPOSR_MODEL_DIR", "/models/triposr")
)
DINO_REPO_ID = (
    os.environ.get("OBJECT_DINO_MODEL_ID")
    or os.environ.get("TRIPOSR_DINO_MODEL_ID")
    or "facebook/dino-vitb16"
)
DINO_REVISION = os.environ.get("OBJECT_DINO_REVISION") or os.environ.get(
    "TRIPOSR_DINO_REVISION", ""
)
HF_HOME = Path(os.environ.get("HF_HOME", "/models/hf"))
REMBG_MODEL = os.environ.get("OBJECT_REMBG_MODEL", "u2net")
U2NET_HOME = Path(os.environ.get("U2NET_HOME", "/models/u2net"))
MANIFEST_PATH = Path(os.environ.get("TRIPOSR_MANIFEST_PATH", "/models/model-manifest.json"))


def sha256_file(path: Path) -> str:
    """Return the hex SHA-256 of a file, streaming it in 4 MiB blocks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def require_revision(value: str, name: str) -> str:
    """Reject an unpinned, branch-like revision."""
    if not value or value in {"main", "master", "HEAD"}:
        message = f"{name} must be a concrete commit/revision, got {value!r}"
        raise SystemExit(message)
    return value


def download_triposr() -> dict[str, str]:
    """Download the pinned weights and verify the checkpoint checksum."""
    from huggingface_hub import snapshot_download

    revision = require_revision(TRIPOSR_REVISION, "TRIPOSR_MODEL_REVISION")
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    checkpoint = MODEL_DIR / "model.ckpt"
    config = MODEL_DIR / "config.yaml"

    expected_ok = checkpoint.is_file() and config.is_file()
    if expected_ok and TRIPOSR_SHA256:
        expected_ok = sha256_file(checkpoint) == TRIPOSR_SHA256
    if not expected_ok:
        print(f"downloading {TRIPOSR_REPO_ID}@{revision} -> {MODEL_DIR}", flush=True)
        snapshot_download(
            repo_id=TRIPOSR_REPO_ID,
            revision=revision,
            local_dir=str(MODEL_DIR),
            allow_patterns=["config.yaml", "model.ckpt"],
        )

    for required in (config, checkpoint):
        if not required.is_file():
            message = f"model file missing after download: {required}"
            raise SystemExit(message)

    checksum = sha256_file(checkpoint)
    if TRIPOSR_SHA256 and checksum != TRIPOSR_SHA256:
        message = f"TripoSR checkpoint checksum mismatch: expected {TRIPOSR_SHA256}, got {checksum}"
        raise SystemExit(message)
    print(f"TripoSR model.ckpt sha256={checksum} size={checkpoint.stat().st_size}")
    return {"checkpoint_sha256": checksum, "checkpoint_bytes": str(checkpoint.stat().st_size)}


def seed_dino_config() -> str:
    """Cache the pinned DINO config where offline ``hf_hub_download`` finds it.

    TripoSR's image tokenizer calls ``hf_hub_download`` without a revision for
    ``facebook/dino-vitb16/config.json``. Seeding ``refs/main`` with the pinned
    commit makes that call resolve locally in offline mode while keeping the
    pinned content.
    """
    from huggingface_hub import snapshot_download

    revision = require_revision(DINO_REVISION, "TRIPOSR_DINO_REVISION")
    cache_dir = HF_HOME / "hub"
    repo_cache = cache_dir / "models--facebook--dino-vitb16"
    ref_file = repo_cache / "refs" / "main"
    snapshot_config = repo_cache / "snapshots" / revision / "config.json"

    if not (ref_file.is_file() and snapshot_config.is_file()):
        print(f"downloading {DINO_REPO_ID}@{revision} config -> {cache_dir}", flush=True)
        snapshot_download(
            repo_id=DINO_REPO_ID,
            revision=revision,
            cache_dir=str(cache_dir),
            allow_patterns=["config.json"],
        )
        if not snapshot_config.is_file():
            message = f"DINO config missing after download: {snapshot_config}"
            raise SystemExit(message)
        ref_file.parent.mkdir(parents=True, exist_ok=True)
        # huggingface_hub reads the ref file verbatim (no strip), so it must
        # contain exactly the commit and no trailing newline.
        ref_file.write_text(revision, encoding="utf-8")
    elif ref_file.read_text(encoding="utf-8") != revision:
        ref_file.write_text(revision, encoding="utf-8")

    print(f"DINO config cached at {snapshot_config}")
    return str(snapshot_config)


def download_rembg_model() -> str:
    """Download the rembg session weights into U2NET_HOME."""
    U2NET_HOME.mkdir(parents=True, exist_ok=True)
    from rembg import new_session

    # Constructing the session downloads the model when it is absent and
    # validates it with pooch's built-in checksum.
    session = new_session(REMBG_MODEL)
    print(f"rembg model {REMBG_MODEL!r} ready in {U2NET_HOME} ({type(session).__name__})")
    return REMBG_MODEL


def main() -> int:
    """Populate the model cache and write the manifest."""
    require_revision(TRIPOSR_REVISION, "TRIPOSR_MODEL_REVISION")
    triposr = download_triposr()
    dino = seed_dino_config()
    rembg_model = download_rembg_model()

    manifest = {
        "model_id": TRIPOSR_REPO_ID,
        "model_revision": TRIPOSR_REVISION,
        "checkpoint_sha256": triposr["checkpoint_sha256"],
        "checkpoint_bytes": int(triposr["checkpoint_bytes"]),
        "dino_model_id": DINO_REPO_ID,
        "dino_revision": DINO_REVISION,
        "dino_config": dino,
        "rembg_model": rembg_model,
        "generated_at": datetime.now(UTC).isoformat(),
    }
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    print(f"model manifest written to {MANIFEST_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
