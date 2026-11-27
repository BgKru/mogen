# Scene reconstruction worker (Phase 6)

Photogrammetric reconstruction of an environment from several photographs using
**COLMAP 4.2.1** (feature extraction, matching, sparse reconstruction, image
undistortion) and **OpenMVS 2.4.0** (dense reconstruction, meshing, refinement,
texturing, GLB/OBJ conversion).

This package is imported only inside `mogen-scene-worker:dev`. The FastAPI image
never installs COLMAP, OpenMVS, trimesh or their native dependencies
(`08_infrastructure.md` Sections 3.6 and 4.4, `04_backend_specification.md`
Section 12.1).

## Image layout

- Base/runtime: `colmap/colmap:20260929.8466` (Ubuntu 24.04, COLMAP 4.2.1 with
  CUDA support, pinned by digest).
- Build stage: OpenMVS `v2.4.0` at commit `58117204…`, built from source with
  `OpenMVS_USE_CUDA=OFF` against CGAL `v6.0.1`, Eigen `3.4` and VCGLib
  `658ba36d…`.
- Python: Ubuntu's Python 3.12 in `/opt/venv`, with `backend/requirements.txt`
  and `requirements.txt` (trimesh `4.12.2`, numpy `2.3.5`, Pillow `13.0.0`).

Binary verification is part of the image build and of worker startup: the build
fails if any of `colmap`, `InterfaceCOLMAP`, `DensifyPointCloud`,
`ReconstructMesh`, `RefineMesh`, `TextureMesh` or `TransformScene` is missing or
cannot print its help (`08` Section 4.4, `SCENE-AC-01`). At startup the worker
verifies the same list and logs `scene_pipeline_ready` with the versions.

## Pipeline

The worker runs the documented sequence and persists one real
`GenerationTask.stage` per step (`07` Section 13.3):

```text
IMAGE_PREPARATION
FEATURE_EXTRACTION
FEATURE_MATCHING
SPARSE_RECONSTRUCTION
RECONSTRUCTION_VALIDATION
IMAGE_UNDISTORTION
OPENMVS_IMPORT
DENSE_RECONSTRUCTION
MESH_GENERATION
MESH_REFINEMENT
TEXTURING
ASSET_EXPORT
RESULT_VALIDATION
```

Each task gets an isolated workspace:

```text
/data/work/scene/{task_id}/
├── images/               original bytes, never re-encoded
├── colmap/
│   ├── database.db
│   ├── feature_manifest.json  feature-backend checkpoint fingerprint (addendum 12)
│   ├── features.npz           neural keypoints/descriptors (neural mode only)
│   ├── pairs.txt              deterministic neural pair list (neural mode only)
│   ├── sparse/           all candidate models
│   ├── models_txt/       converted models used for selection
│   └── dense/            undistorted images + sparse model
├── openmvs/              scene.mvs, dense scene, mesh, refined, textured
├── output/scene.glb      the validated result asset
├── logs/                 one log per stage
├── diagnostics.json      metrics, timings and warnings
└── diagnostics/image_quality.json  advisory image-quality report (addendum 11)
```

Completed stages are reused on a restarted task only after their outputs pass
the same validators (`07` Section 13.6). Invalid or partial outputs are rerun.

`IMAGE_PREPARATION` also runs the shared advisory analyzer from
`ml/image_quality/`: per-image technical findings plus perceptual
near-duplicate candidates are written to `diagnostics/image_quality.json` and
attached to the result diagnostics. The analyzer never removes a photograph or
blocks COLMAP (see `docs/additions/11_image_quality_analysis.md`).

## Optional learned feature matching (increment 12)

`FEATURE_EXTRACTION` and `FEATURE_MATCHING` run through a small backend
contract (`feature_matching.py`). The default is still the unchanged COLMAP SIFT
path. Setting `SCENE_FEATURE_BACKEND=ALIKED_LIGHTGLUE` with
`SCENE_FEATURE_PROFILE=aliked_lightglue` (or `aliked_lightglue_fast`) selects:

```text
ALIKED-N16 (128-d descriptors) -> LightGlue -> pycolmap 4.2.1 import
    -> pycolmap.verify_matches -> existing colmap mapper -> unchanged downstream
```

The adapter imports keypoints, matches and verified two-view geometries into a
temporary COLMAP database through pycolmap 4.2.1's supported API (the same calls
HLoc uses), validates it with `read_database_stats`, and replaces `database.db`
atomically. It never runs COLMAP's feature extractor/matcher after neural
features were imported, so feature sets are never mixed.

Pinned neural stack (installed only in this image, see
`requirements-neural.txt` and `download_neural_models.py`):

| Component | Version / revision | License |
|---|---|---|
| PyTorch / torchvision | 2.14.1 / 0.29.2 | BSD-3-Clause |
| Kornia | 0.9.2 | Apache-2.0 |
| OpenCV (Python) | 5.1.0.95 | Apache-2.0 |
| Matplotlib | 3.11.2 | PSF-based (matplotlib license) |
| pycolmap | 4.2.1 | BSD-3-Clause |
| LightGlue | commit `5a650c44…` | Apache-2.0 |
| ALIKED weights | `aliked-n16.pth`, SHA-256 `5be87048…` | BSD-3-Clause |
| LightGlue weights | `aliked_lightglue_v0-1_arxiv.pth`, SHA-256 `d975e965…` | Apache-2.0 |

Weights are baked under `/opt/neural_models` at image build and re-verified
before every neural stage; the worker never downloads models at task time.

Checkpoint reuse requires `colmap/feature_manifest.json` to match the ordered
image SHA-256 set, backend/profile, model/checkpoint identifiers, keypoint
budget, resize limit, pair strategy/overlap, thresholds, verification settings
and COLMAP/runtime versions. Any mismatch deletes the feature and dependent
sparse/dense outputs and rebuilds them. A neural database is never reused as a
SIFT database.

A recoverable neural failure (runtime/model/CUDA/OOM, extraction, matching,
verification, import, insufficient verified pairs) falls back to a clean SIFT
database only when `SCENE_FEATURE_FALLBACK_TO_SIFT=true`; the fallback reason
and the actual backend are recorded in diagnostics. Invalid datasets and
deterministic configuration errors never fall back.

The pair generator is deterministic: `EXHAUSTIVE` uses the sorted image names,
`SEQUENTIAL` uses upload order with `SCENE_FEATURE_SEQUENTIAL_OVERLAP`
neighbours, and the configured `SCENE_FEATURE_MAX_PAIRS` limit is enforced
before a model is loaded. Keypoints returned by ALIKED in the resized inference
image are restored to original pixel coordinates before the COLMAP import.

Run the reproducible benchmark (SIFT exhaustive/sequential, ALIKED
exhaustive/sequential and the fast profile) with:

```bash
docker run --rm --gpus all -v /path/to/dataset:/data/dataset \
  -v /path/to/output:/proof mogen-scene-worker:dev \
  python -m scene_reconstruction.benchmark_features \
  --images /data/dataset --output /proof/feature-benchmark.json --device cuda
```

## Optional scene enhancement (increment 14)

`scene_mesh_postprocess_enabled` is off by default. When enabled, the exporter
runs one optional pass on the loaded scene after `RefineMesh`/`TextureMesh` and
before the GLB repack:

- conservative cleanup (degenerate faces, unreferenced vertices; UV seams are
  never merged and textured components are never rebuilt);
- fast area-weighted normals with winding correction only for a watertight
  single component, exported as `NORMAL`;
- optional simplification, skipped for textured geometry and safely skipped in
  this image because no quadric simplifier is pinned;
- UV regeneration and AI texture generation are rejected by configuration:
  OpenMVS owns the UV/atlas pipeline and its textures must be preserved.

Geometry objects are replaced in place, so node transforms, material
assignments and embedded texture references survive. A settings/dependency/source
fingerprint manifest (`enhancement_manifest.json`) invalidates a cached enhanced
GLB. Measured on a retained 16 486-vertex / 28 832-face OpenMVS scene: baseline
0.20 s, cleanup+normals 1.23 s, with textures and UVs preserved and 0 Khronos
errors/warnings.

## Export and validation

`TransformScene` writes the OpenMVS glTF/OBJ set. OpenMVS's GLB references the
texture as a sidecar file, so the exporter stage repacks the OBJ/MTL/PNG set
(or the raw GLB) with trimesh into one self-contained `output/scene.glb`. An
independent binary parser (`validator.py`) then requires:

- a valid GLB 2.0 container with exactly one embedded buffer and BIN chunk;
- at least one mesh primitive with finite `POSITION` data and valid indices;
- positive bounding-box extents;
- embedded texture images (no `images[].uri`) with `TEXCOORD_0` and a material
  that references the texture when texturing is enabled.

The raw OpenMVS GLB is kept only as `diagnostics.json` evidence (sidecar
detection, `extensionsUsed`); it is never registered as a result.

## Standalone proof

```bash
docker run --rm mogen-scene-worker:dev \
  python -m scene_reconstruction.standalone --verify-tools

docker run --rm -v /path/to/dataset:/data/dataset \
  mogen-scene-worker:dev python -m scene_reconstruction.standalone \
  --images /data/dataset --work-dir /tmp/scene-proof \
  --output /tmp/scene-proof/scene.glb
```

The standalone command uses the production pipeline. `--no-refine`,
`--no-texture`, `--no-gpu`, `--matching SEQUENTIAL` and the threshold flags exist
for diagnostic runs; the worker uses the backend settings instead.

## Tests

```bash
docker run --rm mogen-scene-worker:dev python -m pytest /opt/scene_reconstruction/tests -q
```

Unit tests cover dataset validation, command construction, model selection,
GLB validation/repack, runner timeouts/cancellation, preflight, the advisory
quality stage (findings, near-duplicate candidates and advisory/required
failure) and the whole orchestration with fake tool runners. The real
reconstruction test is opt-in:

```bash
docker run --rm -e RUN_SCENE_RECONSTRUCTION_TEST=1 \
  -e SCENE_TEST_IMAGES=/data/SceauxCastle \
  -v /path/to/SceauxCastle:/data/SceauxCastle:ro \
  mogen-scene-worker:dev python -m pytest /opt/scene_reconstruction/tests -m scene_binaries -q
```

## Optional neural representation: Nerfstudio Splatfacto + Gaussian PLY

Increment 15 adds an opt-in scene representation that keeps the validated COLMAP
cameras and sparse points but replaces the OpenMVS/GLB stages with Nerfstudio
standard **Splatfacto** training and a Gaussian PLY export. The COLMAP + OpenMVS
mesh path remains the default; the selection is a deployment setting and is
persisted in each task, so a retry cannot be re-targeted by a later change.

**Pipeline.** `IMAGE_PREPARATION` (including advisory image quality) → feature
extraction/matching → sparse reconstruction → model selection → image
undistortion → `SPLAT_DATASET_PREPARATION` → `SPLAT_TRAINING` → `SPLAT_EXPORT`.
No `OPENMVS_*`, dense/mesh/texturing or GLB stage runs for a splat task.
`nerfstudio_dataset.py` converts the undistorted dense model to the upstream
`transforms.json`/`sparse_pc.ply` layout, applies the same COLMAP→OpenGL
transform as `ns-process-data`, and validates handedness/forward/up axes plus a
reprojection self-check before training.

**Dedicated runtime.** `Dockerfile.splat` layers on the verified scene image and
installs the pinned neural stack into `/opt/splat-site` with
`requirements-splat.txt`; the worker process keeps its released PYTHONPATH and
the directory is added only to the training/export subprocess. The image bakes
the gsplat CUDA kernels (`TORCH_EXTENSIONS_DIR=/opt/splat-cache/torch_extensions`)
so a user task never compiles them. Build the base first:

```bash
docker compose build scene-worker
docker build -f ml/scene_reconstruction/Dockerfile.splat -t mogen-splat-worker:dev .
# or, with the overlay:
docker compose -f compose.yaml -f compose.gpu.yaml -f compose.splat.yaml up -d --build
```

**Artifact contract.** The result is a binary little-endian Gaussian PLY with the
exact Nerfstudio 1.1.5 `ns-export gaussian-splat` property set
(`x y z nx ny nz f_dc_0..2 f_rest_0..44 opacity scale_0..2 rot_0..3` for SH
degree 3). `splat_validator.py` re-reads it independently and rejects a generic
point cloud, truncated data, non-finite values or an oversized artifact;
`splat_exporter.py` filters non-finite/sub-threshold-opacity Gaussians like the
pinned exporter and publishes atomically. The result is registered as
`format=PLY`, `mime_type=application/octet-stream`.

**Settings** (backend `SCENE_SPLAT_*`, mapped by `build_config_from_settings`):
standard `splatfacto` only (`splatfacto-big` is rejected for the 12 GB profile),
bounded iterations/image scale/dimension, a soft VRAM admission budget, a
maximum artifact size and a timeout bounded by the task limit. Checkpoints are
reused only when the dataset fingerprint, runtime versions and every
output-affecting setting match (`splat_manifest.json`).

**Viewer.** The frontend dispatches on the result `format`; PLY assets are
validated (header, count, bounds) and rendered through the lazily loaded
`@mkkellogg/gaussian-splats-3d` renderer, while GLB keeps `GLTFLoader`.

**Tests/benchmark.**

```bash
docker run --rm mogen-splat-worker:dev /opt/venv/bin/python -m pytest \
  /opt/scene_reconstruction/tests -k splat           # unit coverage, no GPU
docker run --rm --gpus all -v "${PWD}/.proof:/proof" mogen-splat-worker:dev \
  sh -c 'PYTHONPATH=/opt/splat-site:/opt /opt/venv/bin/python \
    /proof/increment15/real_splat_smoke.py 300 800'
```

The real smoke reuses the retained Sceaux COLMAP model, trains standard
Splatfacto for the requested short budget and exports/validates the PLY. The
production profile is 30 000 iterations at 1600 px; the benchmark
(`scene_reconstruction.benchmark_splat`) records mesh facts and splat facts with
representation-appropriate metrics only.

## Licenses

- COLMAP: BSD-3-Clause, used unmodified from the official image.
- OpenMVS: AGPL-3.0-only, built unmodified and invoked as separate executables;
  no OpenMVS library is linked into application code (`phase0_decisions.md`
  Section 8).
- CGAL: LGPL-3.0-or-later (build dependency, headers).
- Eigen: MPL-2.0 (header-only).
- VCGLib: GPL-3.0 (header-only build dependency).
- trimesh: MIT. numpy: BSD-3-Clause. Pillow: HPND.
- Nerfstudio: Apache-2.0; gsplat: Apache-2.0; `@mkkellogg/gaussian-splats-3d`:
  MIT. All are opt-in neural-runtime dependencies and are not part of the
  default API or COLMAP/OpenMVS environments.
