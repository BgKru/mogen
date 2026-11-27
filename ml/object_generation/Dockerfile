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
# Stable Fast 3D (increment 13) is pinned by source commit. Its two native
# extensions are built in the sf3d-native-build stage below.
ARG SF3D_COMMIT=ff21fc491b4dc5314bf6734c7c0dabd86b5f5bb2
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

# Stable Fast 3D native extensions (increment 13). texture_baker bakes the
# albedo/normal maps and uv_unwrapper performs the UV unwrap; both compile
# against the same torch/CUDA pair as the runtime and are copied as wheels.
FROM ${PYTORCH_DEVEL_IMAGE} AS sf3d-native-build

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_BREAK_SYSTEM_PACKAGES=1 \
    PYTHONUNBUFFERED=1

ARG SF3D_COMMIT

ADD https://github.com/Stability-AI/stable-fast-3d/archive/${SF3D_COMMIT}.tar.gz /tmp/sf3d.tar.gz
RUN mkdir -p /opt/sf3d-src \
    && tar -xzf /tmp/sf3d.tar.gz -C /tmp \
    && cp -a "/tmp/stable-fast-3d-${SF3D_COMMIT}/." /opt/sf3d-src/ \
    && rm -rf /tmp/sf3d.tar.gz "/tmp/stable-fast-3d-${SF3D_COMMIT}"

# USE_NATIVE_ARCH=0 keeps the wheel portable across hosts with the same GPU
# architecture instead of baking the builder's CPU tuning.
# USE_CUDA=1 is required: texture_baker/setup.py defaults USE_CUDA to
# `torch.cuda.is_available()`, which is False in a GPU-less build container, so
# the wheel would otherwise register only the CPU kernels and every textured
# SF3D task would fail at bake time with `rasterize` unavailable for CUDA.
RUN USE_CUDA=1 TORCH_CUDA_ARCH_LIST="8.6" USE_NATIVE_ARCH=0 \
    python -m pip wheel --no-build-isolation --no-deps --wheel-dir /wheels \
        /opt/sf3d-src/texture_baker \
        /opt/sf3d-src/uv_unwrapper \
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
# Shared image-quality analyzer (11_image_quality_analysis.md). Imported as
# `image_quality`; it is the same package the scene worker installs.
COPY ml/image_quality /opt/image_quality
# Shared mesh-enhancement utilities (14_mesh_texture_enhancement.md). Imported
# as `mesh_enhancement`; it is the same package the scene worker installs.
COPY ml/mesh_enhancement /opt/mesh_enhancement

# `object_generation` is a package directly under /opt, so /opt is the parent
# that must be importable; /opt/triposr makes the pinned `tsr` package available.
ENV PYTHONPATH=/app:/opt/triposr:/opt

RUN mkdir -p /data /models \
    && chown -R ubuntu:ubuntu /app /data /models /opt/object_generation /opt/image_quality /opt/mesh_enhancement

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

# Stable Fast 3D worker target (increment 13). It is opt-in and starts only
# through compose.sf3d.yaml, so the default deployment keeps the TripoSR image
# and its dependency set unchanged. SF3D's conflicting requirements live in an
# isolated --target directory injected before site-packages; the TripoSR
# environment is not modified.
FROM development AS sf3d

USER root

COPY ml/object_generation/requirements-sf3d.txt /tmp/requirements-sf3d.txt
RUN python -m pip install --no-cache-dir --no-deps --target /opt/sf3d-site \
        -r /tmp/requirements-sf3d.txt

COPY --from=sf3d-native-build /wheels /tmp/sf3d-wheels
RUN python -m pip install --no-cache-dir --no-deps --target /opt/sf3d-site \
        /tmp/sf3d-wheels/*.whl \
    && rm -rf /tmp/sf3d-wheels

COPY --from=sf3d-native-build /opt/sf3d-src /opt/sf3d-src

# The upstream checkout has no sf3d/__init__.py (it is a namespace package), so
# the source must not live in a directory named `sf3d`: the ComfyUI root
# __init__.py would otherwise shadow the package. Keeping it under
# /opt/sf3d-src makes `import sf3d` resolve to /opt/sf3d-src/sf3d.
ENV PYTHONPATH=/opt/sf3d-site:/opt/sf3d-src:/app:/opt/triposr:/opt

# Build-time preflight: the model package and both native extensions must
# import in the final image, so a broken wheel fails the build, not a task.
RUN python - <<'PY'
import importlib.util
import sys

sys.path.insert(0, "/opt/sf3d-site")
import torch
from sf3d.system import SF3D
from texture_baker import TextureBaker
from uv_unwrapper import Unwrapper

assert importlib.util.find_spec("sf3d") is not None
print(
    "sf3d preflight ok:",
    torch.__version__,
    SF3D.__name__,
    TextureBaker.__name__,
    Unwrapper.__name__,
)
PY

RUN chown -R ubuntu:ubuntu /opt/sf3d-src /opt/sf3d-site

USER ubuntu
