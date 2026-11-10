# Phase 6 Close-Out Review

**Date:** 2026-11-08
**Scope:** Phase 6 ("Scene Reconstruction — COLMAP and OpenMVS Integration") of `10_development_roadmap.md`, tasks 6.1–6.9 and the applicable `SCENE-AC-nn`, `BE-AC-nn`, `DB-AC-nn`, `API-AC-nn`, `INF-AC-nn` and `TEST-AC-nn` criteria.
**Verdict:** Phase 6 is complete at its roadmap scope. A dedicated scene worker performs real COLMAP 4.2.1 Structure-from-Motion and real OpenMVS 2.4.0 dense reconstruction, mesh generation, refinement and texturing. Every external stage is observable and persisted, the selected sparse model is validated against measured properties, the textured scene is repacked into one self-contained GLB, validated independently and stored as the project's current result through the existing transactional path. A live task reconstructed a real five-photograph set end to end, and a failed follow-up attempt preserved the previous result. The Phase 7 viewer was not started.

---

## 1. Baseline and final state

The Section 5 baseline was confirmed before any change: **481 backend tests** (313 database/API, 160 unit, 8 API-shell), **92 frontend tests**, **32 ML object-generation unit tests plus the opt-in real-model test**, nine healthy services plus `migration` and `model-init` `Exited (0)`, three responsive Celery workers, fresh dispatcher/recovery heartbeat files, and an object worker that had loaded the real TripoSR model (`triposr_model_loaded`, `object_generation_pipeline_ready`). The stack was already running and was verified rather than assumed.

Final state:

| Check | Result |
|---|---|
| `docker compose -f compose.yaml -f compose.gpu.yaml ps -a` | `db`, `redis`, `api`, `cleanup-worker`, `object-worker`, `scene-worker`, `outbox-dispatcher`, `task-recovery`, `frontend` healthy; `migration` `Exited (0)`; `model-init` `Exited (0)` |
| `docker compose run --rm --no-deps api pytest` | **491 passed, 1 warning** in 120.10 s |
| Backend suite breakdown | 316 database/API, 167 unit, 8 API-shell |
| `ruff check .` / `ruff format --check .` | clean / 109 files already formatted |
| `alembic check` | "No new upgrade operations detected." |
| `pip check` | "No broken requirements found." |
| Scene ML suite (`/opt/scene_reconstruction/tests`) | **74 passed, 1 skipped** (the skip is the gated real-reconstruction test) |
| Object ML suite (`/opt/object_generation/tests`) | **32 passed, 1 skipped** |
| Object real-model test (`RUN_REAL_MODEL_TESTS=1 -m real_model`) | **1 passed** |
| Frontend `lint`, `typecheck`, `format:check`, `test:run`, `build` | clean; **94 tests passed across 15 files**; production bundle 536.57 kB (167.74 kB gzip) |
| Scene toolchain in the final image | COLMAP 4.2.1 and OpenMVS x64 v2.4.0 for all six required OpenMVS tools |
| Coverage (`pytest --cov=app`) | **87%** (3 253 statements, 412 missed); `scene_pipeline` is 0% (worker-only, live-verified), `generation_tasks` 80% |

The final stack has the same eleven Compose services as Phase 5; `scene-worker` now runs the dedicated `mogen-scene-worker:dev` image instead of the API image.

---

## 2. Roadmap tasks

| Task | Result | Evidence |
|---|---|---|
| 6.1 Environment Preparation | Satisfied | `ml/scene_reconstruction/Dockerfile` builds a dedicated `mogen-scene-worker:dev` image on the pinned official COLMAP image (`colmap/colmap:20260929.8466@sha256:c1de5161…`, COLMAP 4.2.1 with CUDA), with OpenMVS v2.4.0 (commit `58117204…`) built unmodified from source, OpenCV 4.12.0 from source (OpenMVS 2.4.0 needs `IMWRITE_JPEGXL_QUALITY`, added in OpenCV 4.11), CGAL 6.0.1, Eigen 3.4 and VCGLib `658ba36d…`. Python 3.12 runs in `/opt/venv` with the backend requirements plus trimesh 4.12.2. The build verifies all seven executables; the worker re-verifies them at startup and `--verify-tools` prints COLMAP 4.2.1 and OpenMVS x64 v2.4.0. |
| 6.2 Standalone COLMAP Pipeline | Satisfied | The standalone proof executed feature extraction (113 499 keypoints), exhaustive matching (55/55 geometrically verified pairs), sparse reconstruction (11/11 images registered, 8 018 points, mean reprojection error 0.566, one component), reconstruction validation/selection and image undistortion. |
| 6.3 Sparse Reconstruction Diagnostics | Satisfied | `reconstruction_selector.py` parses every `sparse/*` model (`cameras.txt`, `images.txt`, `points3D.txt`), records registered image count, ratio, point count, reprojection statistics, camera validity and connected components, and selects by measured ranking rather than directory order. Thresholds are configurable and invalid/unusable models raise `INSUFFICIENT_REGISTERED_IMAGES`, `INVALID_CAMERA_PARAMETERS` or `SPARSE_RECONSTRUCTION_FAILED`. Tests cover selection, fragmentation and rejection. |
| 6.4 OpenMVS Integration | Satisfied | `openmvs_runner.py` builds and executes InterfaceCOLMAP, DensifyPointCloud, ReconstructMesh, RefineMesh and TextureMesh with explicit arguments, timeouts, logs and output validation. The proof produced 332 303 dense points, a 5 029-vertex / 9 985-face mesh, a 14 205-vertex / 28 216-face refined mesh and one texture atlas image. |
| 6.5 GLB Export | Satisfied | `TransformScene` exports the scene as OBJ/MTL/PNG and as GLB; `exporter.py` repacks the OBJ set into one self-contained GLB with embedded texture. The independent validator checks the container, buffer, accessors, indices, finite geometry, positive bounds, embedded images, UVs, material-to-texture references and checksum. The raw OpenMVS GLB was recorded as a sidecar-texture asset (`scene_mesh_0.png`, `KHR_materials_unlit`); the repacked result has no external URI. |
| 6.6 Pipeline Orchestration | Satisfied | `PhotogrammetryReconstructor` executes `IMAGE_PREPARATION` → … → `RESULT_VALIDATION` in order, with per-stage configuration, timeouts, log files, output validation, cancellation checks, heartbeat throttling and stable error codes. A failed stage stops dependent stages. |
| 6.7 Checkpointing | Satisfied | Each task owns an isolated `/data/work/scene/{task_id}` workspace. Completed stages are reused only after their outputs pass the same validators; an inconsistent COLMAP database is deleted before re-extraction, and invalid meshes/textures are regenerated. Repeated standalone runs reused extraction, matching, sparse, dense and refinement outputs, and unit tests cover the reuse and forced-rerun paths. |
| 6.8 Celery Integration | Satisfied | `backend/app/tasks/scene_pipeline.py` registers `run_colmap_pipeline` through the existing `register_pipeline(TaskType.SCENE, …)` hook and uses `TaskContext.heartbeat`, `report_progress`, `raise_if_cancelled`, `GenerationFailure` and `GenerationCancelled`. Compose starts the worker with `-Q scene_reconstruction --include=app.tasks.scene_pipeline`; no direct Redis publication or new lifecycle was added. `reconstruct_scene_task` was already present and now resolves the real pipeline. |
| 6.9 Frontend Integration | Satisfied | The existing details-page `GenerationPanel` enables scene reconstruction once `MIN_SCENE_IMAGES` is reached, starts/retries the task with a fresh idempotency key, displays the persisted scene stages (`FEATURE_EXTRACTION` … `ASSET_EXPORT`), maps scene error codes to Russian messages, shows result availability and links the authenticated GLB download. It shows capture guidance and never presents the minimum count as a guarantee. |

---

## 3. Acceptance criteria

### 3.1 Scene reconstruction (`SCENE-AC-nn`)

| Criterion | Result | Evidence |
|---|---|---|
| SCENE-AC-01 Worker Initialization | Satisfied | The image build verifies all seven executables; worker startup logs `scene_pipeline_ready`; `--verify-tools` reports COLMAP 4.2.1 and OpenMVS x64 v2.4.0. |
| SCENE-AC-02 Input Validation | Satisfied | All source images are decoded with Pillow; only JPEG/PNG are accepted; empty, corrupt, unsupported and over-sized files raise `INVALID_SCENE_DATASET`/`IMAGE_DECODE_FAILED`; unit tests cover each path and the live API also enforces upload validation. |
| SCENE-AC-03 Dataset Preparation | Satisfied | `prepare_dataset` creates `images/`, `colmap/`, `openmvs/`, `output/` and `logs/` under a task-specific directory and never modifies the stored originals. |
| SCENE-AC-04 Feature Extraction | Satisfied | Real COLMAP extraction processed all 11 photographs and stored 113 499 keypoints. |
| SCENE-AC-05 Feature Matching | Satisfied | Real exhaustive matching produced 55 matched and 55 geometrically verified pairs; the database connectivity check reports one component. |
| SCENE-AC-06 Sparse Reconstruction | Satisfied | Real COLMAP mapper produced sparse model `0` with 11/11 registered images. |
| SCENE-AC-07 Camera Estimation | Satisfied | The sparse model records 11 cameras with finite, valid `SIMPLE_RADIAL` parameters and finite poses. |
| SCENE-AC-08 Sparse Model Selection | Satisfied | All candidate directories are inspected and ranked by registered images, ratio, points and mean error; unit tests prove a 6-image model in directory `10` wins over a 3-image model in directory `2`. |
| SCENE-AC-09 Image Undistortion | Satisfied | `colmap image_undistorter` produced `dense/images` and the dense sparse model; the stage validates both before OpenMVS import. |
| SCENE-AC-10 OpenMVS Import | Satisfied | `InterfaceCOLMAP` produced `scene.mvs` with 11 calibrated images and 8 025 sparse points. |
| SCENE-AC-11 Dense Reconstruction | Satisfied | `DensifyPointCloud` produced a dense point cloud with 332 303 points and a non-empty dense scene. |
| SCENE-AC-12 Mesh Generation | Satisfied | `ReconstructMesh` produced a 5 029-vertex / 9 985-face mesh; the mesh validator checks finite geometry and positive bounds. |
| SCENE-AC-13 Mesh Refinement | Satisfied | `RefineMesh` executed with conservative settings and produced a 14 205-vertex / 28 216-face refined mesh; unit tests cover the configurable on/off path. |
| SCENE-AC-14 Texture Generation | Satisfied | `TextureMesh` produced a textured mesh and a 2048-px atlas image; the final GLB contains one embedded texture and a material that references it. |
| SCENE-AC-15 GLB Export | Satisfied | `TransformScene` exported both OBJ and GLB; the OBJ set was repacked into a self-contained GLB. The raw OpenMVS GLB's sidecar reference was recorded, proving the mandatory repack requirement (`07` Section 11.2). |
| SCENE-AC-16 GLB Validation | Satisfied | The independent parser passes (container, one embedded buffer, accessors, indices, finite vertices, positive bounds, embedded images, `TEXCOORD_0`, material texture). The Khronos glTF Validator reports **0 errors and 0 warnings** on the final asset. |
| SCENE-AC-17 Task Status | Satisfied | Live status advanced `PENDING` → `PROCESSING` with real stages (`IMAGE_UNDISTORTION` → `DENSE_RECONSTRUCTION` → `MESH_REFINEMENT` → `ASSET_EXPORT` → `RESULT_VALIDATION`) → `COMPLETED`; a failed attempt reported `FAILED` with `SOURCE_IMAGE_NOT_FOUND`. |
| SCENE-AC-18 Result Persistence | Satisfied | The result row is stored under `projects/{project_id}/results/{task_id}/scene.glb`; the live download matched the stored file's SHA-256 and size byte for byte. |
| SCENE-AC-19 Error Handling | Satisfied | Stable codes exist for every documented failure class; the live missing-source attempt recorded `SOURCE_IMAGE_NOT_FOUND` with a user-safe message, and the traceback stayed in the worker log. Unit tests cover COLMAP/OpenMVS/export failures, timeouts and missing tools. |
| SCENE-AC-20 Previous Result Preservation | Satisfied | After the failed second attempt the project became `FAILED` while `result_available` stayed `true`, the same current result id remained and the download SHA-256 was unchanged. |
| SCENE-AC-21 Resource Isolation | Satisfied | Every task has a unique workspace under `/data/work/scene`; the successful and failed live tasks used distinct task-scoped directories, and database tests assert two attempts produce distinct `scene.glb` storage keys. |
| SCENE-AC-22 Browser Compatibility | Partially verified — deferred | The exported GLB passes the Khronos glTF Validator with 0 errors/0 warnings and contains one textured material with embedded images. Three.js `GLTFLoader` in Node cannot load embedded textures without browser DOM APIs; the application's Three.js viewer is Phase 7, so actual in-browser display is not claimed in Phase 6. |
| SCENE-AC-23 Real Reconstruction | Satisfied | 11 real Sceaux Castle photographs produced a complete textured GLB through the real binaries; a live five-photograph project also completed through the full worker path. |
| SCENE-AC-24 Docker Integration | Satisfied | `scene-worker` runs `mogen-scene-worker:dev` through Compose with the `app_data` volume, database/Redis access and GPU reservation under `compose.gpu.yaml`; the container is healthy and consumes only `scene_reconstruction`. |

### 3.2 Backend, database, API and infrastructure

| Criterion | Result | Evidence |
|---|---|---|
| BE-AC-17 ML Integration | Satisfied | The scene pipeline is invoked through the Phase 4 Celery/task architecture; a live `SCENE` task executed real COLMAP/OpenMVS and completed. |
| BE-AC-19 Result Management | Satisfied | The validated GLB is stored persistently, associated with project and task, and exposed only as the current result without storage paths. |
| BE-AC-20 Model Download | Satisfied | The existing authenticated download endpoint served the scene GLB with the documented headers; its bytes and SHA-256 matched storage. |
| DB-AC-07/08/10/11/12 | Satisfied | Scene tasks use the existing generation history, immutable input snapshot, result storage/versioning and preservation rules; the two live tasks and their result rows were inspected before cleanup. |
| API-AC-09..14 | Satisfied | The existing generation/status/result/download contracts were exercised live for a `SCENE` project; no new endpoint or response shape was introduced. |
| INF-AC-02 Image Build | Satisfied | The scene image builds reproducibly from the committed Dockerfile and pinned sources; binary verification is part of the build. |
| INF-AC-09 Scene Worker Startup | Satisfied | The worker starts from its dedicated image, detects the toolchain, registers the pipeline and answers `celery inspect ping`. |
| INF-AC-10 Queue Separation | Satisfied | The worker consumes only `scene_reconstruction`; object and cleanup tasks are unaffected. |
| INF-AC-12 Shared Storage | Satisfied | `/data` is shared with the API and the other workers; results are readable by the API and downloadable. |
| INF-AC-13 GPU Access | Satisfied | `compose.gpu.yaml` reserves one NVIDIA GPU for `scene-worker` and sets `SCENE_COLMAP_USE_GPU=true`; the real proof used CUDA feature extraction. |
| INF-AC-14 CPU Configuration | Satisfied | `SCENE_MAX_THREADS` bounds COLMAP/OpenMVS threads; OpenMVS is built CPU-only (`SCENE_OPENMVS_USE_CUDA=false`). |
| INF-AC-17 Logging | Satisfied | Worker logs are single-line JSON with `project_id`, `task_id`, stage and error code; tool logs stay in the task workspace. |

### 3.3 Testing (`TEST-AC-nn`)

| Criterion | Result | Evidence |
|---|---|---|
| TEST-AC-13 Scene Reconstruction Integration | Satisfied | 74 scene unit/integration cases plus the real reconstruction proof and the live worker task. |
| TEST-AC-14 GLB Validation | Satisfied | The independent scene parser and the Khronos validator both pass on the generated asset. |
| TEST-AC-18 Previous Result Preservation | Satisfied | Live failure injection kept the same current result and download checksum; database tests cover replacement and preservation. |
| TEST-AC-10 Frontend Tests | Satisfied | 94 tests pass, including the enabled scene action and a real scene stage. |
| TEST-AC-15 End-to-End Testing | Partially verified | The complete API workflow (create → upload → generate → poll → result → download → failure preservation) was executed against the running stack through the frontend origin. A browser-driven Playwright scenario remains deferred with the Phase 7 viewer. |
| TEST-AC-16/19/20 | Not verified | Performance measurements beyond the recorded stage timings, CI and formal release validation are outside this phase; `TEST-AC-19` remains the known open quality item. |

---

## 4. Environment and pinned versions

| Component | Pin | Notes |
|---|---|---|
| COLMAP | `colmap/colmap:20260929.8466@sha256:c1de51615dff33066cd305071226b6343c1168324ef3bd622f0825e55feb5efe` | COLMAP 4.2.1, official CUDA-enabled image, BSD-3-Clause |
| OpenMVS | v2.4.0, commit `58117204c86bbb11a0b25b26a8987676cf11274d` | Built unmodified from source with `OpenMVS_USE_CUDA=OFF`, AGPL-3.0-only, invoked as separate executables |
| OpenCV | 4.12.0, built from source | Required because OpenMVS 2.4.0 references `cv::IMWRITE_JPEGXL_QUALITY`, added in OpenCV 4.11; Ubuntu ships 4.6 |
| CGAL | 6.0.1 (release library bundle) | OpenMVS 2.4.0 includes `CGAL/AABB_traits_3.h`, absent from Ubuntu's 5.6 |
| Eigen | 3.4 | Header-only |
| VCGLib | commit `658ba36d0a5666650da6e066b4794efc5a463407` | Header-only |
| Python / trimesh / numpy / Pillow | 3.12 / 4.12.2 / 2.3.5 / 13.0.0 | Worker venv `/opt/venv` |
| Base runtime | Ubuntu 24.04.2 (from the COLMAP image) | COLMAP image digest pinned |

**Recorded deviations from the Phase 0 pin table.** The Phase 0 table listed OpenMVS "built from source" without listing its transitive build dependencies; OpenCV and CGAL are new build dependencies required by the pinned OpenMVS 2.4.0 source. OpenCV 4.12.0 is added; CGAL 6.0.1 is installed from the official release library bundle instead of compiling the source tree because the source tarball download stalled repeatedly in this build network. The OpenMVS source itself is unmodified, preserving the AGPL analysis in `phase0_decisions.md` Section 8.

---

## 5. Mandatory standalone proof (tasks 6.1–6.5)

Dataset: **Sceaux Castle**, 11 real photographs (2832 × 2128), from `openMVG/ImageDataset_SceauxCastle`, mounted read-only at build/proof time and not committed to the repository.

Command executed inside the final image (baked code, GPU):

```bash
docker run --rm --gpus all \
  -v "${PWD}/.proof/sceaux:/data/sceaux:ro" -v "${PWD}/.proof:/proof" \
  mogen-scene-worker:dev python -m scene_reconstruction.standalone \
  --images /data/sceaux --work-dir /proof/sceaux-baked \
  --output /proof/sceaux-baked.glb --max-image-size 1200 --threads 8
```

Result (exit 0):

| Metric | Value |
|---|---|
| Input images | 11 (all unique, JPEG) |
| Sparse reconstruction | 11/11 registered, 8 018 points, mean reprojection error 0.566, 1 component |
| Matching | 55 matched pairs, 55 verified pairs, 113 499 keypoints |
| Dense point cloud | 332 303 points |
| Mesh | 5 029 vertices / 9 985 faces |
| Refined mesh | 14 205 vertices / 28 216 faces |
| Textures | 1 atlas (2048 px) |
| Final GLB | 959 504 bytes, SHA-256 `9f9992ee4ef86e50c9ea405e41a60bfdc10f82ff2f9d5b486b104fb424944c96` |
| Final geometry | 16 539 vertices / 28 991 triangles, 1 material, embedded textures |
| Total processing time | 231.48 s (dense reconstruction 130.6 s, refinement 60.3 s, all other stages < 10 s each) |

Independent validation of the exported GLB:

```text
Khronos glTF Validator: 0 errors, 0 warnings, 3 hints (bufferView.target not set)
version 2.0 · generator trimesh · 1 draw call · 16 539 vertices · 28 991 triangles
1 material · hasTextures: true · hasDefaultScene: true
```

The raw OpenMVS GLB (`scene_mesh.glb`) referenced `scene_mesh_0.png` as an external image and used `KHR_materials_unlit`; the repacked result has no external URI and no unlit extension, which is the `P0-FU-1` repack evidence required by the specification.

A second clean run (mounted working tree, 11 images) produced 950 912 bytes with SHA-256 `3cf7b0bf58e3aa87ba1a64cd713de56bb15f4456f34556f93ceff1d3213e9abd` (16 204 vertices / 28 216 faces, 218.65 s). The two runs differ only in mesh extraction details, which is expected for a non-deterministic dense pipeline; both validate.

---

## 6. Live worker end-to-end

A five-photograph SCENE project was created through the frontend origin (`http://127.0.0.1:5173/api/v1`), the images uploaded, and reconstruction started with a project-scoped idempotency key.

| Observation | Value |
|---|---|
| Task | `b316f18b-065a-4a31-acd9-d06a44403720` |
| Persisted stages | `PENDING` → `PROCESSING` (`IMAGE_UNDISTORTION` → `DENSE_RECONSTRUCTION` → `MESH_REFINEMENT` → `ASSET_EXPORT` → `RESULT_VALIDATION`) → `COMPLETED` |
| Elapsed | 00:10:17 → 00:12:47 (≈2 min 20 s) |
| Result | 1 619 116-byte GLB, SHA-256 `756561746ae8ec7d92f6a89034f46b4d9fe3f1a8df4556ae906c6808d2baaac5` |
| Stored key | `projects/57cc53da…/results/b316f18b…/scene.glb` |
| Download | Byte-identical to the stored file (same SHA-256 and size) |
| Khronos validator | 0 errors, 0 warnings; 6 702 vertices, 12 015 triangles, 1 texture |

Failure preservation was then exercised on the same project: the source files were removed from `/data`, a second task was started with a new idempotency key, and the worker failed it at `IMAGE_PREPARATION` with `SOURCE_IMAGE_NOT_FOUND`. The project became `FAILED`, `result_available` stayed `true`, the current result id and 1 619 116-byte download were unchanged, and the download SHA-256 was still `75656174…`. The smoke project's cleanup job completed (`attempts=1`) and its storage directory was removed; the smoke database rows and files were then deleted, leaving the pre-existing development data untouched.

---

## 7. Tests executed

| Suite | Result |
|---|---|
| Backend (`docker compose run --rm --no-deps api pytest`) | **491 passed, 1 warning** |
| Scene unit (`mogen-scene-worker:dev python -m pytest /opt/scene_reconstruction/tests -q`) | **74 passed, 1 skipped** |
| Object unit (`mogen-object-worker:dev python -m pytest /opt/object_generation/tests -q`) | **32 passed, 1 skipped** |
| Object real-model (opt-in) | **1 passed** |
| Frontend (`npm run test:run`) | **94 passed across 15 files** |
| Frontend lint/typecheck/format/build | clean; bundle 536.57 kB |
| Backend ruff/format | clean; 109 files formatted |
| Scene ruff/format (image context) | clean; 29 files formatted |
| `alembic check`, `pip check` | no drift, no broken requirements |
| Khronos glTF Validator | 0 errors, 0 warnings |

Phase 6 added 10 backend cases (`backend/tests/db/test_scene_generation.py`, `backend/tests/unit/test_scene_settings.py`) and 75 scene ML cases (74 executed, one opt-in). The scene suite covers dataset validation, command construction, COLMAP database statistics and pair-id decoding, sparse selection, GLB validation/repack, process timeouts/cancellation, preflight, checkpoint reuse, `--verify-tools`, and an opt-in full real reconstruction.

---

## 8. Known issues and limitations

**Defect found after close-out and fixed (2026-11-08).** A live SCENE project with four PNG photographs (1 492×1 190, 1 863×1 256, 1 578×1 174, 1 875×1 272; mean grey ≈ 191–199, grey standard deviation 22–31, only 10 988 keypoints in total) failed in the mapper: five of six pairs were geometrically verified, but COLMAP found no good initial image pair even after relaxing the initialisation constraints. That is a genuine input-quality failure (low texture/contrast, insufficient usable overlap), not a pipeline defect. The response was wrong in two ways: the task failed with `SPARSE_RECONSTRUCTION_FAILED` instead of the more accurate `INSUFFICIENT_REGISTERED_IMAGES`, and the user-visible message contained the internal `(exit code 1)`. Fixed in `colmap_runner.py`: a mapper run that produces no model now raises `INSUFFICIENT_REGISTERED_IMAGES` with an actionable message (“photographs may not overlap enough or may contain too little visual detail”), exit codes and log tails stay in the worker log, and a mapper that writes a valid model despite a non-zero exit is accepted with a warning. Three regression tests were added (`tests/test_colmap_runner.py`); the scene suite is now **74 passed, 1 skipped**.

1. **Phase 7 viewer.** `SCENE-AC-22` is only partially verified: the GLB is valid and textured but is not yet displayed in the application's Three.js viewer. The roadmap's "scene can be displayed in the browser" acceptance is Phase 7 work; Three.js `GLTFLoader` cannot load embedded textures in Node without DOM APIs, so no in-browser claim is made here.
2. **Failed-task workspaces.** A failed task keeps `/data/work/scene/{task_id}` for diagnostics. No retention/cleanup producer removes these directories yet; the open items list records it.
3. **Image size and build cost.** The scene image is about 11 GB (CUDA COLMAP base, source-built OpenCV, OpenMVS, CGAL headers). The first build takes roughly 30–45 minutes on the reference machine; cached rebuilds are fast.
4. **CPU dense reconstruction.** OpenMVS is CPU-only (`SCENE_OPENMVS_USE_CUDA=false`); dense reconstruction dominates runtime (130 s for 11 images at 1200 px, 45 s for 5 images at 2000 px). The configurable `SCENE_MAX_IMAGE_SIZE` is the main lever.
5. **Scope of the texture claim.** Textures cover the surface visible in the photographs; occluded or unphotographed surfaces are absent or approximate, as required by `07` Section 10.12.
6. **Coverage.** Backend coverage is 87% (3 253 statements, 412 missed). The worker-only `scene_pipeline.py` is 0% and `generation_tasks.py` 80% because the real worker path is live-verified instead of unit-tested; the 90% generation-state target is therefore not fully met and is reported rather than hidden.
7. **CI and formal performance measurement** (`TEST-AC-16`, `TEST-AC-19`, `TEST-AC-20`) remain outside this phase; stage timings are recorded but no benchmark suite exists.

---

## 9. Next step

Phase 7 — 3D viewer and result management: the Three.js viewer, authorized GLB loading, camera controls, model information, download UI and result management, validated against object and scene results. `SCENE-AC-22` should be closed there with a real browser test.
