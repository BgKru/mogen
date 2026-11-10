# syntax=docker/dockerfile:1.7
#
# Object-generation worker image (08_infrastructure.md Sections 3.5 and 4.3).
#
# It is deliberately independent from backend/Dockerfile: only this image
# carries PyTorch, TripoSR, torchmcubes and the image/mesh libraries. The
# FastAPI image must stay small (04_backend_specification.md Section 12).
#
# Build context is the repository root:
#   docker build -f ml/object_generation/Dockerfile -t mogen-object-worker:dev .

# Pinned base images (phase0_decisions.md). The devel stage compiles
# torchmcubes against the exact torch/CUDA pair used at runtime.
ARG PYTORCH_DEVEL_IMAGE=pytorch/pytorch:2.14.1-cuda12.6-cudnn9-devel
ARG PYTORCH_RUNTIME_IMAGE=pytorch/pytorch:2.14.1-cuda12.6-cudnn9-runtime

# TripoSR repository is pinned by commit: it has no tags or releases and the
# default branch moves. Keep this in sync with phase0_decisions.md.
ARG TRIPOSR_COMMIT=d26e33181947bbbc4c6fc0f5734e1ec6c080956e
# torchmcubes is a compiled CUDA extension, pinned by commit.
ARG TORCHMCUBES_COMMIT=a9ac95aa329957ba646e7bb057f825f5dfa77f38
# RTX 3060 is the verified target (hardware profile: 12 GB NVIDIA). Building
# only this architecture keeps the extension build bounded.
ARG CUDA_ARCHITECTURES=86

FROM ${PYTORCH_DEVEL_IMAGE} AS torchmcubes-build

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_BREAK_SYSTEM_PACKAGES=1 \
    PYTHONUNBUFFERED=1

ARG TORCHMCUBES_COMMIT
ARG CUDA_ARCHITECTURES

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY ml/object_generation/requirements-build.txt /tmp/requirements-build.txt
RUN python -m pip install --no-cache-dir -r /tmp/requirements-build.txt

RUN CMAKE_ARGS="-DCMAKE_CUDA_ARCHITECTURES=${CUDA_ARCHITECTURES}" \
    python -m pip wheel \
    --no-build-isolation \
    --no-deps \
    --wheel-dir /wheels \
    "torchmcubes @ git+https://github.com/tatsy/torchmcubes.git@${TORCHMCUBES_COMMIT}" \
    && ls -l /wheels

FROM ${PYTORCH_RUNTIME_IMAGE} AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_BREAK_SYSTEM_PACKAGES=1 \
    PIP_DEFAULT_TIMEOUT=300 \
    HF_HOME=/models/hf \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    U2NET_HOME=/models/u2net

ARG TRIPOSR_COMMIT

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# The PyTorch base image already provides UID/GID 1000 as `ubuntu`. Reusing it
# keeps the shared `app_data` volume writable by the API (also UID 1000).
WORKDIR /app

# Backend runtime dependencies and application code (Celery, SQLAlchemy,
# Psycopg, Pydantic settings, storage and the Phase 4 worker lifecycle).
COPY backend/requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app

# Object-generation dependencies.
COPY ml/object_generation/requirements.txt ./requirements-object.txt
RUN python -m pip install --no-cache-dir -r requirements-object.txt

# Compiled torchmcubes wheel from the build stage. --no-deps keeps the torch
# already present in the runtime image.
COPY --from=torchmcubes-build /wheels /tmp/wheels
RUN python -m pip install --no-cache-dir --no-deps /tmp/wheels/*.whl \
    && rm -rf /tmp/wheels

# Pinned TripoSR source (MIT). It has no packaging metadata, so it lives on
# PYTHONPATH and is imported as `tsr`.
ADD https://github.com/VAST-AI-Research/TripoSR/archive/${TRIPOSR_COMMIT}.tar.gz /tmp/triposr.tar.gz
RUN mkdir -p /opt \
    && tar -xzf /tmp/triposr.tar.gz -C /tmp \
    && mv "/tmp/TripoSR-${TRIPOSR_COMMIT}" /opt/triposr \
    && rm -f /tmp/triposr.tar.gz

# Our pipeline modules (no external packaging; imported as `object_generation`).
COPY ml/object_generation /opt/object_generation

# `object_generation` is a package directly under /opt, so /opt is the parent
# that must be importable; /opt/triposr makes the pinned `tsr` package available.
ENV PYTHONPATH=/app:/opt/triposr:/opt

RUN mkdir -p /data /models \
    && chown -R ubuntu:ubuntu /app /data /models /opt/object_generation

USER ubuntu

# The worker has no HTTP port; Compose runs Celery with this image.
CMD ["celery", "-A", "app.tasks.celery_app:celery_app", "worker", "-Q", "object_generation", "--pool=solo", "--include=app.tasks.object_pipeline", "--loglevel=INFO"]

# Development target adds the test/lint tooling used for the ML suites.
FROM runtime AS development

USER root

COPY backend/requirements-dev.txt ./requirements-dev.txt
RUN python -m pip install --no-cache-dir -r requirements-dev.txt

COPY ml/object_generation/pyproject.toml /opt/object_generation/pyproject.toml
COPY ml/object_generation/tests /opt/object_generation/tests

RUN chown -R ubuntu:ubuntu /opt/object_generation

USER ubuntu
