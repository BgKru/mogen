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
│   ├── sparse/           all candidate models
│   ├── models_txt/       converted models used for selection
│   └── dense/            undistorted images + sparse model
├── openmvs/              scene.mvs, dense scene, mesh, refined, textured
├── output/scene.glb      the validated result asset
├── logs/                 one log per stage
└── diagnostics.json      metrics, timings and warnings
```

Completed stages are reused on a restarted task only after their outputs pass
the same validators (`07` Section 13.6). Invalid or partial outputs are rerun.

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
GLB validation/repack, runner timeouts/cancellation, preflight and the whole
orchestration with fake tool runners. The real reconstruction test is opt-in:

```bash
docker run --rm -e RUN_SCENE_RECONSTRUCTION_TEST=1 \
  -e SCENE_TEST_IMAGES=/data/SceauxCastle \
  -v /path/to/SceauxCastle:/data/SceauxCastle:ro \
  mogen-scene-worker:dev python -m pytest /opt/scene_reconstruction/tests -m scene_binaries -q
```

## Licenses

- COLMAP: BSD-3-Clause, used unmodified from the official image.
- OpenMVS: AGPL-3.0-only, built unmodified and invoked as separate executables;
  no OpenMVS library is linked into application code (`phase0_decisions.md`
  Section 8).
- CGAL: LGPL-3.0-or-later (build dependency, headers).
- Eigen: MPL-2.0 (header-only).
- VCGLib: GPL-3.0 (header-only build dependency).
- trimesh: MIT. numpy: BSD-3-Clause. Pillow: HPND.
