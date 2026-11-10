"""Reliable HTTP download for the OpenMVS build stage.

BuildKit's ADD has no retry and a flaky connection fails the whole image build.
This helper retries with a per-read timeout and fails if the file stays empty.
It runs inside the disposable builder stage only.
"""

from __future__ import annotations

import sys
import time
import urllib.request

ATTEMPTS = 5
TIMEOUT_SECONDS = 120
CHUNK = 1024 * 1024


def download(url: str, destination: str) -> None:
    for attempt in range(1, ATTEMPTS + 1):
        try:
            with (
                urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as response,  # noqa: S310
                open(destination, "wb") as target,
            ):
                while chunk := response.read(CHUNK):
                    target.write(chunk)
            if not __import__("os").path.getsize(destination):
                raise OSError("empty download")
            print(f"downloaded {url} -> {destination}", flush=True)
            return
        except Exception as exc:  # noqa: BLE001 - retried and reported below
            print(f"attempt {attempt}/{ATTEMPTS} failed for {url}: {exc}", flush=True)
            if attempt == ATTEMPTS:
                raise
            time.sleep(3)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: fetch.py URL DESTINATION")
    download(sys.argv[1], sys.argv[2])
