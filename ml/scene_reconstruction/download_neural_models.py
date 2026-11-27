"""Download and verify the pinned neural feature checkpoints at image build.

The worker is offline at task time: ALIKED and LightGlue weights are baked into
the scene image under ``TORCH_HOME`` by this script, then re-verified by
``neural_features.verify_model_files`` before every neural stage.

Run with ``--verify-only`` to inspect a built image without network access.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path

DEFAULT_TORCH_HOME = Path("/opt/neural_models")
ALIKED_URL = "https://github.com/Shiaoming/ALIKED/raw/main/models/aliked-n16.pth"
LIGHTGLUE_URL = "https://github.com/cvg/LightGlue/releases/download/v0.1_arxiv/aliked_lightglue.pth"
ALIKED_FILENAME = "aliked-n16.pth"
ALIKED_SHA256 = "5be8704840ed662d9d8c561bf7279c222092674e7eb05fd0feab94899e9d82f2"
LIGHTGLUE_FILENAME = "aliked_lightglue_v0-1_arxiv.pth"
LIGHTGLUE_SHA256 = "d975e965b105311a6143194852297dff4f02aea5cc2e10cecfed966ca0e22503"
_CHUNK = 1024 * 1024


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def checkpoint_dir() -> Path:
    torch_home = Path(os.environ.get("TORCH_HOME", str(DEFAULT_TORCH_HOME)))
    return torch_home / "hub" / "checkpoints"


def verify(checks: dict[str, str]) -> int:
    directory = checkpoint_dir()
    failed = False
    for filename, expected in checks.items():
        path = directory / filename
        if not path.is_file():
            print(f"missing: {path}", file=sys.stderr)
            failed = True
            continue
        actual = sha256(path)
        status = "ok" if actual == expected else "MISMATCH"
        print(f"{status}: {path} {actual}")
        failed = failed or actual != expected
    return 1 if failed else 0


def download() -> int:
    checks = {ALIKED_FILENAME: ALIKED_SHA256, LIGHTGLUE_FILENAME: LIGHTGLUE_SHA256}
    directory = checkpoint_dir()
    directory.mkdir(parents=True, exist_ok=True)
    if verify(checks) == 0:
        print("neural checkpoints already present and verified")
        return 0

    import torch.hub

    os.environ.setdefault("TORCH_HOME", str(DEFAULT_TORCH_HOME))
    for url, filename in ((ALIKED_URL, ALIKED_FILENAME), (LIGHTGLUE_URL, LIGHTGLUE_FILENAME)):
        path = directory / filename
        if path.is_file() and sha256(path) == checks[filename]:
            continue
        print(f"downloading {filename}")
        torch.hub.load_state_dict_from_url(
            url, file_name=filename, map_location="cpu", check_hash=False
        )
    return verify(checks)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--verify-only", action="store_true", help="verify existing checkpoints only"
    )
    args = parser.parse_args()
    checks = {ALIKED_FILENAME: ALIKED_SHA256, LIGHTGLUE_FILENAME: LIGHTGLUE_SHA256}
    return verify(checks) if args.verify_only else download()


if __name__ == "__main__":
    raise SystemExit(main())
