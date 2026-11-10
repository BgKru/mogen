# syntax=docker/dockerfile:1.7
#
# Scene-reconstruction worker image (08_infrastructure.md Sections 3.6 and 4.4).
#
# It is independent from backend/Dockerfile: only this image carries COLMAP and
# OpenMVS and their native dependencies. The FastAPI image must not install any
# of them (04_backend_specification.md Section 12.1).
#
# Build context is the repository root:
#   docker build -f ml/scene_reconstruction/Dockerfile -t mogen-scene-worker:dev .
#
# Pinned components (docs/architecture/phase0_decisions.md Section 6):
#   * COLMAP 4.2.1, official image colmap/colmap:20260929.8466 (CUDA-enabled
#     build, BSD-3-Clause), already present in the runtime base image.
#   * OpenMVS v2.4.0, commit 58117204c86bbb11a0b25b26a8987676cf11274d, built
#     from source (AGPL-3.0-only; invoked as separate executables only).
#   * CGAL v6.0.1, Eigen 3.4, VCGLib commit 658ba36d...: build dependencies.
#
# OpenMVS is built with OpenMVS_USE_CUDA=OFF: SCENE_OPENMVS_USE_CUDA defaults to
# false (07_scene_reconstruction.md Section 16) and a CPU-only binary keeps the
# image smaller and free of a second CUDA toolchain.

ARG UBUNTU_IMAGE=ubuntu:24.04@sha256:fe81560990fae86dc4743202b2cb4d3df98d0bcf949173cecef15ce1127ef852
ARG COLMAP_IMAGE=colmap/colmap:20260929.8466@sha256:c1de51615dff33066cd305071226b6343c1168324ef3bd622f0825e55feb5efe

# ---------------------------------------------------------------------------
# Build stage: OpenMVS 2.4.0 from source on Ubuntu 24.04. The exact package
# and CMake recipe follows OpenMVS's own docker/buildInDocker.sh for v2.4.0,
# with every source pinned by commit or tag.
# ---------------------------------------------------------------------------
FROM ${UBUNTU_IMAGE} AS openmvs-build

ARG OPENMVS_COMMIT=58117204c86bbb11a0b25b26a8987676cf11274d
ARG VCG_COMMIT=658ba36d0a5666650da6e066b4794efc5a463407
ARG EIGEN_VERSION=3.4

ENV DEBIAN_FRONTEND=noninteractive

# Same dependency set as OpenMVS's official build script. The dev packages are
# needed to compile; the runtime stage installs the runtime counterparts.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        cmake \
        git \
        libpng-dev \
        libjpeg-dev \
        libtiff-dev \
        libglu1-mesa-dev \
        libglew-dev \
        libglfw3-dev \
        libboost-filesystem-dev \
        libboost-iostreams-dev \
        libboost-program-options-dev \
        libboost-serialization-dev \
        libboost-system-dev \
        libboost-thread-dev \
        libopencv-dev \
        libgmp-dev \
        libmpfr-dev \
        zlib1g-dev \
        python3-dev \
    && rm -rf /var/lib/apt/lists/*

# OpenMVS v2.4.0 adds nanoflann and JPEG XL to its dependency set (vcpkg.json);
# Boost.Math is header-heavy and needs its dev package. Kept in a separate layer
# so the large base package layer stays cached.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libboost-math-dev \
        libjxl-dev \
        libnanoflann-dev \
        pkg-config \
    && rm -rf /var/lib/apt/lists/*

# OpenCV 4.12 (BSD-3-Clause). OpenMVS v2.4.0 references
# cv::IMWRITE_JPEGXL_QUALITY, which OpenCV added in 4.11 (Ubuntu 24.04 ships
# 4.6). Building OpenCV keeps the pinned OpenMVS source unmodified. Only the
# modules OpenMVS needs are built, without tests, apps, Python bindings or
# FFmpeg/GStreamer. Downloads use a retrying helper because BuildKit's HTTP
# fetcher has no retry and a flaky connection otherwise fails the whole build.
ARG OPENCV_VERSION=4.12.0
COPY ml/scene_reconstruction/docker/fetch.py /tmp/fetch.py
RUN python3 /tmp/fetch.py \
        https://codeload.github.com/opencv/opencv/tar.gz/refs/tags/${OPENCV_VERSION} /tmp/opencv.tar.gz \
    && mkdir -p /src/opencv \
    && tar -xzf /tmp/opencv.tar.gz -C /src/opencv --strip-components=1 \
    && rm -f /tmp/opencv.tar.gz \
    && cmake -S /src/opencv -B /tmp/opencv-build \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_INSTALL_PREFIX=/usr/local \
        -DBUILD_SHARED_LIBS=ON \
        -DBUILD_LIST=core,imgproc,imgcodecs,calib3d,features2d,flann,highgui,video,videoio,photo,stitching \
        -DBUILD_TESTS=OFF \
        -DBUILD_PERF_TESTS=OFF \
        -DBUILD_EXAMPLES=OFF \
        -DBUILD_opencv_apps=OFF \
        -DBUILD_opencv_python3=OFF \
        -DWITH_JPEGXL=OFF \
        -DWITH_IPP=OFF \
        -DWITH_OPENCL=OFF \
        -DWITH_FFMPEG=OFF \
        -DWITH_GSTREAMER=OFF \
        -DWITH_V4L=OFF \
    && cmake --build /tmp/opencv-build -j"$(nproc)" \
    && cmake --install /tmp/opencv-build \
    && rm -rf /tmp/opencv-build

# Eigen 3.4 (header-only, MIT).
ADD https://gitlab.com/libeigen/eigen/-/archive/${EIGEN_VERSION}/eigen-${EIGEN_VERSION}.tar.gz /tmp/eigen.tar.gz
RUN mkdir -p /src/eigen \
    && tar -xzf /tmp/eigen.tar.gz -C /src/eigen --strip-components=1 \
    && cmake -S /src/eigen -B /tmp/eigen-build -DCMAKE_BUILD_TYPE=Release \
    && cmake --build /tmp/eigen-build -j"$(nproc)" \
    && cmake --install /tmp/eigen-build \
    && rm -rf /tmp/eigen.tar.gz /tmp/eigen-build

# CGAL 6.0.1 header-only library bundle (LGPL-3.0-or-later). OpenMVS v2.4.0
# includes CGAL 6 headers (CGAL/AABB_traits_3.h), which Ubuntu's 5.6 does not
# provide. The release's small library bundle is downloaded and installed
# without compiling anything.
ARG CGAL_VERSION=6.0.1
RUN python3 /tmp/fetch.py \
        https://github.com/CGAL/cgal/releases/download/v${CGAL_VERSION}/CGAL-${CGAL_VERSION}-library.tar.xz \
        /tmp/cgal.tar.xz \
    && mkdir -p /tmp/cgal \
    && tar -xJf /tmp/cgal.tar.xz -C /tmp/cgal --strip-components=1 \
    && cp -a /tmp/cgal/include/CGAL /usr/local/include/ \
    && mkdir -p /usr/local/lib/cmake \
    && cp -a /tmp/cgal/lib/cmake/CGAL /usr/local/lib/cmake/ \
    && cp -a /tmp/cgal/cmake /usr/local/cmake \
    && rm -rf /tmp/cgal /tmp/cgal.tar.xz

# VCGLib (GPL-3.0), pinned by commit; OpenMVS consumes it as headers.
RUN python3 /tmp/fetch.py \
        https://codeload.github.com/cdcseacave/VCG/tar.gz/${VCG_COMMIT} /tmp/vcglib.tar.gz \
    && mkdir -p /src/vcglib \
    && tar -xzf /tmp/vcglib.tar.gz -C /src/vcglib --strip-components=1 \
    && rm -f /tmp/vcglib.tar.gz

# OpenMVS v2.4.0 (AGPL-3.0-only), built unmodified from the pinned commit.
RUN python3 /tmp/fetch.py \
        https://codeload.github.com/cdcseacave/openMVS/tar.gz/${OPENMVS_COMMIT} /tmp/openmvs.tar.gz \
    && mkdir -p /src/openmvs \
    && tar -xzf /tmp/openmvs.tar.gz -C /src/openmvs --strip-components=1 \
    && rm -f /tmp/openmvs.tar.gz \
    && cmake -S /src/openmvs -B /tmp/openmvs-build \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_INSTALL_PREFIX=/usr/local \
        -DVCG_ROOT=/src/vcglib \
        -DOpenCV_DIR=/usr/local/lib/cmake/opencv4 \
        -DOpenMVS_USE_CUDA=OFF \
        -DOpenMVS_USE_PYTHON=OFF \
    && cmake --build /tmp/openmvs-build -j"$(nproc)" \
    && cmake --install /tmp/openmvs-build \
    && ldconfig \
    && rm -rf /tmp/openmvs-build

# 08 Section 4.4: a successful build is not proof that the executables work.
# Fail the image build if any required binary is missing or cannot print help.
# OpenMVS apps return exit code 1 after printing their help when no input file
# is given, so 0 and 1 with non-empty output are both accepted.
RUN for tool in InterfaceCOLMAP DensifyPointCloud ReconstructMesh RefineMesh TextureMesh TransformScene; do \
        test -x "/usr/local/bin/OpenMVS/${tool}" || { echo "missing ${tool}"; exit 1; }; \
        rc=0; \
        "/usr/local/bin/OpenMVS/${tool}" --help >/tmp/help.txt 2>&1 || rc=$?; \
        if [ "${rc}" -gt 1 ] || [ ! -s /tmp/help.txt ]; then \
            echo "${tool} does not start (rc=${rc}, bytes=$(wc -c </tmp/help.txt))"; \
            head -5 /tmp/help.txt; \
            exit 1; \
        fi; \
    done

# ---------------------------------------------------------------------------
# Runtime stage: CUDA-enabled COLMAP 4.2.1 from the official image plus the
# OpenMVS binaries, Python and the application/worker code.
# ---------------------------------------------------------------------------
FROM ${COLMAP_IMAGE} AS runtime

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app:/opt \
    PATH=/opt/venv/bin:/usr/local/bin/OpenMVS:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

# Runtime libraries for OpenMVS. The dev packages are installed deliberately:
# they are the portable way to satisfy OpenCV/Boost/GL sonames without guessing
# individual package names across Ubuntu point releases.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        python3 \
        python3-venv \
        libpng-dev \
        libjpeg-dev \
        libtiff-dev \
        libglu1-mesa-dev \
        libglew-dev \
        libglfw3-dev \
        libboost-filesystem-dev \
        libboost-iostreams-dev \
        libboost-program-options-dev \
        libboost-serialization-dev \
        libboost-system-dev \
        libboost-thread-dev \
        libopencv-dev \
        libgmp-dev \
        libmpfr-dev \
        zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# Runtime shared library for OpenMVS's JPEG XL support (kept separate so the
# main runtime package layer stays cached).
RUN apt-get update \
    && apt-get install -y --no-install-recommends libjxl-dev \
    && rm -rf /var/lib/apt/lists/*

COPY --from=openmvs-build /usr/local/bin/OpenMVS /usr/local/bin/OpenMVS
COPY --from=openmvs-build /usr/local/lib/ /usr/local/lib/
# Install CGAL/Eigen headers as well: they are header-only and make it possible
# to rebuild or inspect an OpenMVS-related tool inside the image later.
# The runtime PATH intentionally lists the application directories first; the
# minimal COLMAP base image does not export a PATH, so /sbin is addressed
# explicitly where the dynamic linker cache must be refreshed.
COPY --from=openmvs-build /usr/local/include/ /usr/local/include/
RUN /sbin/ldconfig

WORKDIR /app

# Backend runtime dependencies (Celery, SQLAlchemy, Psycopg, Pydantic settings,
# Pillow, storage and the Phase 4 worker lifecycle) in an isolated venv.
COPY backend/requirements.txt ./requirements.txt
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/python -m pip install --upgrade pip \
    && /opt/venv/bin/python -m pip install -r requirements.txt

COPY backend/app ./app

# Scene-reconstruction dependencies (trimesh 4.x for the GLB repack, pinned to
# the same version the object worker uses).
COPY ml/scene_reconstruction/requirements.txt /opt/scene_reconstruction-requirements.txt
RUN /opt/venv/bin/python -m pip install -r /opt/scene_reconstruction-requirements.txt

# The pipeline package is imported as `scene_reconstruction`, so /opt is the
# parent that must be on PYTHONPATH.
COPY ml/scene_reconstruction /opt/scene_reconstruction

RUN mkdir -p /data/work/scene \
    && chown -R ubuntu:ubuntu /app /data /opt/scene_reconstruction

USER ubuntu

# The worker has no HTTP port; Compose overrides this with its own queue and
# include flags, but the image is runnable on its own as well.
CMD ["celery", "-A", "app.tasks.celery_app:celery_app", "worker", "-Q", "scene_reconstruction", "--concurrency=1", "--include=app.tasks.scene_pipeline", "--loglevel=INFO"]

# Development target adds the lint/test tooling used for the ML suite.
FROM runtime AS development

USER root

COPY backend/requirements-dev.txt ./requirements-dev.txt
RUN /opt/venv/bin/python -m pip install --no-cache-dir -r requirements-dev.txt

COPY ml/scene_reconstruction/pyproject.toml /opt/scene_reconstruction/pyproject.toml
COPY ml/scene_reconstruction/tests /opt/scene_reconstruction/tests

RUN chown -R ubuntu:ubuntu /opt/scene_reconstruction

USER ubuntu
