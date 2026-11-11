#!/usr/bin/env bash
#
# Generate a self-signed TLS certificate for local deployment verification.
# Docker supplies OpenSSL, so no host dependency is needed. This is NOT a
# production certificate; see ../certs/README.md.

set -Eeuo pipefail

CERT_DIR="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../certs" && pwd)}"
HOST_NAME="${2:-localhost}"
DAYS="${3:-365}"
# Same pinned Debian slim base as the backend image; it provides the OpenSSL CLI.
IMAGE="python:3.11-slim@sha256:65bd3d9f1d7fa268dd1909973ba7eb4bdf41f6dcf2cfbe76ba9528b170f3fd79"

mkdir -p "${CERT_DIR}"

echo "Generating a self-signed certificate for ${HOST_NAME} in ${CERT_DIR}"
docker run --rm -v "${CERT_DIR}:/certs" --entrypoint openssl "${IMAGE}" \
    req -x509 -nodes -newkey rsa:2048 -sha256 -days "${DAYS}" \
    -keyout /certs/tls.key -out /certs/tls.crt \
    -subj "/CN=${HOST_NAME}" \
    -addext "subjectAltName=DNS:${HOST_NAME},IP:127.0.0.1"

docker run --rm -v "${CERT_DIR}:/certs:ro" --entrypoint openssl "${IMAGE}" \
    x509 -in /certs/tls.crt -noout -subject -dates -ext subjectAltName

echo "Done. compose.prod.yaml mounts ${CERT_DIR} at /etc/nginx/certs."
