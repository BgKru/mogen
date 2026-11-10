# Phase 5 Close-Out Review

**Date:** 2026-11-07
**Scope:** Phase 5 ("Object Generation — TripoSR Integration") of `10_development_roadmap.md`, tasks 5.1–5.9 and the applicable `OBJ-AC-nn`, `BE-AC-nn`, `DB-AC-nn`, `API-AC-nn`, `INF-AC-nn` and `TEST-AC-nn` criteria.
**Verdict:** Phase 5 is complete at its roadmap scope. The real TripoSR model runs in the dedicated object worker, performs single-image inference, extracts a mesh, exports a validated self-contained GLB with vertex colours, persists it transactionally as the project's current result, and serves it through the authenticated result/download API. The generation UI starts the task and displays only real persisted stages, errors and result availability. Scene reconstruction (Phase 6) and the 3D viewer (Phase 7) were not started.

---

## 1. Baseline and final state

The Section 5 baseline was confirmed before any change: 451 backend tests (294 database/API, 149 unit, 8 API-shell), 84 frontend tests, nine healthy services plus `migration` `Exited (0)`, three responsive Celery workers, fresh dispatcher/recovery heartbeat files, clean `ruff check`/`ruff format --check`, no Alembic drift, clean frontend lint/typecheck/format/build. The stack was already running and was verified rather than recreated.

Final state:

| Check | Result |
|---|---|
| `docker compose -f compose.yaml -f compose.gpu.yaml ps -a` | `db`, `redis`, `api`, `cleanup-worker`, `object-worker`, `scene-worker`, `outbox-dispatcher`, `task-recovery`, `frontend` healthy; `migration` `Exited (0)`; `model-init` `Exited (0)` |
| `docker compose run --rm --no-deps api pytest` | **481 passed, 1 warning** in 204.89 s |
| Backend suite breakdown | 313 database/API, 160 unit, 8 API-shell |
| `ruff check .` / `ruff format --check .` | clean / 106 files already formatted |
| `alembic check` | "No new upgrade operations detected." |
| `pip check` | "No broken requirements found." |
| Frontend `lint`, `typecheck`, `format:check`, `test:run`, `build` | clean; **92 tests passed across 15 files** |
| ML unit suite (`/opt/object_generation/tests`) | **32 passed, 1 skipped** (the skip is the gated real-model test) |
| Real-model integration test (`RUN_REAL_MODEL_TESTS=1 -m real_model`) | **1 passed** |
| Coverage (`pytest --cov=app`) | see Section 8 |

The final stack has eleven Compose services: the ten Phase 4 services plus the one-shot `model-init` service. `model-init` is expected to exit 0 after verifying or populating the model cache; like `migration`, it is not a long-running service.

---

## 2. Roadmap tasks

| Task | Result | Evidence |
|---|---|---|
| 5.1 Environment Preparation | Satisfied | Dedicated `ml/object_generation/Dockerfile` built on `pytorch/pytorch:2.14.1-cuda12.6-cudnn9-{devel,runtime}`; TripoSR pinned to commit `d26e33181947bbbc4c6fc0f5734e1ec6c080956e`, weights pinned to revision `5b521936b01fbe1890f6f9baed0254ab6351c04a` with `model.ckpt` SHA-256 `429e2c6b22a0923967459de24d67f05962b235f79cde6b032aa7ed2ffcd970ee` (1 677 246 742 bytes), DINO config pinned to revision `f205d5d8e640a89a2b8ef0369670dfc37cc07fc2`, torchmcubes pinned to commit `a9ac95aa329957ba646e7bb057f825f5dfa77f38`, compiled for SM 86. Python 3.12.3 is the PyTorch image runtime; the API remains Python 3.11. |
| 5.2 Standalone Inference | Satisfied | `python -m object_generation.standalone` on the real `car-1.jpg` photograph produced a 1 528 660-byte GLB with 38 241 vertices / 76 315 faces and vertex colours. The file loaded through Three.js `GLTFLoader` with the Khronos glTF Validator reporting **0 errors, 0 warnings**. Exact command and metrics in Section 4. |
| 5.3 Image Preprocessing | Satisfied | Decode, EXIF orientation, RGB/RGBA normalisation, rembg background removal, foreground bounding box/crop, square padding, `foreground_ratio` scaling, 512 px LANCZOS resize and neutral-gray compositing in `ml/object_generation/preprocessing.py`. Original bytes are preserved in the task work directory (OBJ-AC-05). Unit tests cover EXIF, PNG alpha, corrupt/oversized input, rembg failure and empty masks, cropping and the foreground ratio. |
| 5.4 Model Integration | Satisfied | `model_loader.py` verifies the cached checksum, resolves the CUDA device (no silent CPU fallback), loads `TSR` once per process, sets the chunk size, evaluates without gradients, warms CUDA at startup, and releases the CUDA cache after a task. `OBJECT_*` settings are validated in `app/core/config.py`. |
| 5.5 Mesh Extraction | Satisfied | `TripoSRGenerator.generate` runs `torch.inference_mode` inference and `extract_mesh` at the configured `mc_resolution`; `mesh_processor.validate_mesh` checks non-empty geometry, finite vertices, valid indices and a strictly positive bounding box, and records vertex/face/bounding-box statistics. |
| 5.6 GLB Export | Satisfied | `exporter.export_glb` preserves TripoSR vertex colours, writes a self-contained GLB through trimesh, and `validator.validate_glb_bytes` independently parses the GLB container, accessors, indices, bounds and `COLOR_0` before the result can be registered. Invalid output is removed and reported as `GLB_EXPORT_FAILED`/`GLB_VALIDATION_FAILED`. |
| 5.7 Celery Integration | Satisfied | `app/tasks/object_pipeline.py` registers `run_triposr_pipeline` through the Phase 4 `register_pipeline(TaskType.OBJECT, …)` hook, using `TaskContext.heartbeat`, `report_progress`, `raise_if_cancelled`, `GenerationFailure` and `GenerationCancelled`. The worker runs `--pool=solo --include=app.tasks.object_pipeline`; no direct Redis publication was added. |
| 5.8 Result Persistence | Satisfied | `PipelineArtifact` is stored through `StorageBackend` at `projects/{project_id}/results/{task_id}/model.glb`; `TaskExecutionService.complete_with_result` locks the task row, clears the old current result, inserts the new current result, completes the task and the project in one transaction. A failed or cancelled attempt leaves the previous result current. |
| 5.9 Frontend Integration | Satisfied | The existing details page now renders `GenerationPanel`: start action with a fresh idempotency key, real stage labels (`IMAGE_PREPARATION`, `MODEL_GENERATION`, `MODEL_EXPORT`, `RESULT_VALIDATION`), a percentage only when the worker persisted one, stable-code error messages, retry after failure, `result_available` and a `Скачать GLB` link to the authenticated download endpoint. Scene reconstruction remains disabled until Phase 6. |

---

## 3. Acceptance criteria

### 3.1 Object generation (`OBJ-AC-nn`)

| Criterion | Result | Evidence |
|---|---|---|
| OBJ-AC-01 Worker Initialization | Satisfied | Live object-worker logs: `triposr_model_loaded`, `triposr_cuda_ready`, `object_generation_pipeline_ready` before `celery@… ready.` |
| OBJ-AC-02 Model Availability | Satisfied | `warm_up` calls `verify_model_files` before accepting tasks; `model.ckpt` size and SHA-256 were verified, and the checked-in default matches the Hugging Face value. `model-init` populates the persistent cache. |
| OBJ-AC-03 GPU Detection | Satisfied | Live worker selected `cuda:0` on the RTX 3060; `resolve_device` raises `GPU_UNAVAILABLE` when CUDA is unavailable and CPU fallback is disabled. Inference used the GPU (`torchmcubes.HAS_CUDA=True`). |
| OBJ-AC-04 Input Validation | Satisfied | `decode_image` accepts only decoded JPEG/PNG, rejects empty/corrupt/other formats and dimensions above the configured limit; unit tests cover each path; upload validation remains controller-level. |
| OBJ-AC-05 Original Image Preservation | Satisfied | `save_intermediates` writes a byte-for-byte copy of the upload; the pipeline test asserts the original bytes and the standalone result reports `source_image` dimensions without modifying the source. |
| OBJ-AC-06 Background Removal | Satisfied | `remove_background` uses rembg with a process-wide session, respects pre-existing PNG alpha, rejects an empty foreground mask, and composites over the official neutral background. The real proof ran background removal from the cached `u2net` model. |
| OBJ-AC-07 Single-Image Generation | Satisfied | Real `car-1.jpg` inference produced mesh geometry (38 241 vertices / 76 315 faces); live UI/API task produced the same validated asset. |
| OBJ-AC-08 Mesh Extraction | Satisfied | `validate_mesh` checks vertices, faces, indices, finiteness and bounds; the real mesh passed and recorded `width/height/depth` 0.878792/0.924969/0.314795. |
| OBJ-AC-09 GLB Export | Satisfied | `export_glb` produced a self-contained GLB; Three.js loaded it with zero glTF Validator errors and one mesh. |
| OBJ-AC-10 Appearance Preservation | Satisfied | The validator requires `COLOR_0`; the live result reports `has_vertex_colors=true`, and Three.js reports `coloredPrimitives=1` and one material. |
| OBJ-AC-11 Result Persistence | Satisfied | `generation_results` row is inserted as current alongside the stored GLB; live `/result` returned the row and `/download` the same bytes; tests cover storage and database persistence. |
| OBJ-AC-12 Task Status | Satisfied | Live status advanced `PENDING` → `PROCESSING` (`IMAGE_PREPARATION` → `MODEL_GENERATION` → `RESULT_VALIDATION`) → `COMPLETED`; no artificial percentage was written. |
| OBJ-AC-13 Error Handling | Satisfied | Stable codes for preprocessing, model, GPU, mesh and export failures; the live failure injection recorded `SOURCE_IMAGE_NOT_FOUND` with a user-safe message and the traceback only in worker logs. Tests cover `STORAGE_WRITE_FAILED` and `RESULT_PERSISTENCE_FAILED`. |
| OBJ-AC-14 GPU Memory Management | Satisfied | `cleanup_gpu` releases references, synchronises and empties the CUDA cache after every task; the worker processed a later task after the injected failure without restarting, and the model remained loaded. |
| OBJ-AC-15 Result Preservation | Satisfied | After the failed regeneration, the project became `FAILED` while `result_available` stayed `true`, the same current result id remained, and the download returned the identical SHA-256. Unit/integration tests cover the new-success replacement and the failed-attempt preservation. |
| OBJ-AC-16 Asynchronous Processing | Satisfied | Generation runs only in the `object-worker` Celery process; the API transaction creates the task and outbox event, and the dispatcher publishes it. No inference occurs in FastAPI. |
| OBJ-AC-17 Real Model Execution | Satisfied | Real pretrained weights loaded and real inference/export executed in the standalone proof and in the live worker; `TEST-AC-12` also passed. |
| OBJ-AC-18 Docker Integration | Satisfied | `mogen-object-worker:dev` is built from the committed Dockerfile with the pinned CUDA stack, mounted on `app_data` and `triposr_model_cache`, and started with `compose.gpu.yaml`; the worker is healthy and consumes only `object_generation`. |

### 3.2 Backend (`BE-AC-nn`)

| Criterion | Result | Evidence |
|---|---|---|
| BE-AC-17 ML Integration | Satisfied | The Phase 4 task architecture invokes the registered TripoSR pipeline through Celery; the live task executed real inference and export. |
| BE-AC-19 Result Management | Satisfied | The validated GLB is stored persistently and associated with the project and task; the result API returns only the current validated result without storage paths. |
| BE-AC-20 Model Download | Satisfied | `GET /api/v1/projects/{id}/download` requires authentication and ownership, streams `model/gltf-binary` with `attachment`, `private, no-store`, `nosniff`, `Content-Length` and a safe `.glb` filename. Live download matched the stored size and SHA-256. |

### 3.3 Database (`DB-AC-nn`)

| Criterion | Result | Evidence |
|---|---|---|
| DB-AC-07 Generation History | Satisfied | Two tasks (successful and failed) were retained for the smoke project; deleting the project removed the rows only after the explicit cleanup. Existing history tests still pass. |
| DB-AC-08 Task Input Snapshot | Satisfied | The worker reads the ordered `generation_task_images` snapshot; the snapshot remains after the source file is removed, which is how the failure was injected. |
| DB-AC-10 Result Storage | Satisfied | `generation_results` stores format, MIME type, storage key, byte size, SHA-256 and JSONB metadata; large binaries remain in storage. |
| DB-AC-11 Result Versioning | Satisfied | `clear_current` plus the partial unique current-result index leave exactly one current row; the replacement test keeps the old row and file. |
| DB-AC-12 Result Preservation | Satisfied | The failed attempt did not remove or invalidate the previous current result; the row stayed current and the file stayed downloadable. |

### 3.4 API (`API-AC-nn`)

| Criterion | Result | Evidence |
|---|---|---|
| API-AC-09 | Satisfied | Live `POST /generate` returned 202 for the first task and 202 for a new retry. |
| API-AC-10 | Satisfied | Existing generation tests cover the same-key/same-fingerprint 200 and the different-fingerprint 409; unchanged by Phase 5. |
| API-AC-11 | Satisfied | Existing active-task conflict tests cover 409 `GENERATION_ALREADY_RUNNING`; unchanged by Phase 5. |
| API-AC-12 | Satisfied | Live status returned only persisted project/task fields, real stages and null progress when no percentage was reported. |
| API-AC-13 | Satisfied | After the failed regeneration the project was `FAILED` while `result_available` was `true`, and the current result was still downloadable. |
| API-AC-14 | Satisfied | `/result` returned the documented metadata without `storage_key`; `/download` returned 1 528 660 bytes of GLB with the documented headers. |

### 3.5 Infrastructure (`INF-AC-nn`)

| Criterion | Result | Evidence |
|---|---|---|
| INF-AC-08 Object Worker Startup | Satisfied | The worker starts from the dedicated image, verifies the cache, loads the model on `cuda:0`, registers the pipeline and answers `celery inspect ping`. |
| INF-AC-13 GPU Access | Satisfied | `compose.gpu.yaml` reserves one NVIDIA GPU for `object-worker`; the container reports CUDA available and uses the GPU for inference. The base Compose file remains CPU-capable. |

### 3.6 Testing (`TEST-AC-nn`)

| Criterion | Result | Evidence |
|---|---|---|
| TEST-AC-12 TripoSR Integration | Satisfied | `RUN_REAL_MODEL_TESTS=1 pytest -m real_model` passed; the standalone proof and the live worker also ran real weights. |
| TEST-AC-14 GLB Validation | Satisfied | The independent parser validates container, JSON, accessors, finite positions, valid indices, positive bounds and `COLOR_0`; the Three.js/glTF Validator check reports zero errors, and the result API/servation tests cover the object result path. The scene half of TEST-AC-14 is Phase 6. |

---

## 4. Mandatory standalone proof (task 5.2)

Command executed (GPU, pinned weights, host-mounted pipeline source):

```powershell
docker run --rm --gpus all `
  -v mogen_triposr_model_cache:/models `
  -v "${PWD}/ml:/work/ml" `
  -v mogen_phase5_proof:/proof `
  -w /work/ml/object_generation `
  -e PYTHONPATH=/work/ml:/opt/triposr:/opt `
  mogen-object-worker:dev python -m object_generation.standalone `
    --image /work/ml/object_generation/testdata/car-1.jpg `
    --output-dir /proof --model-dir /models/triposr `
    --device cuda:0 `
    --model-sha256 429e2c6b22a0923967459de24d67f05962b235f79cde6b032aa7ed2ffcd970ee
```

Result:

| Fact | Value |
|---|---|
| GLB | `/proof/output/model.glb`, 1 528 660 bytes |
| SHA-256 | `79664ce9120c4820d0811da2f66a09c1852eaa47cea222e42e96a63ef8c43737` |
| Geometry | 38 241 vertices, 76 315 faces, 1 mesh, 1 primitive, vertex colours present |
| Bounding box | 0.878792 × 0.924969 × 0.314795 |
| Timings | preprocessing 1.413 s, inference 16.804 s, extraction 7.152 s, export 0.295 s |
| Device | `cuda:0` (RTX 3060, 12 GB) |
| Preprocessing | background removed (`u2net`), original preserved |

Viewer/validator check with the same Three.js loader the future viewer will use:

```powershell
docker run --rm -v "${PWD}/ml/object_generation/viewer:/viewer" `
  -v "${PWD}/.proof:/proof" -w /viewer mogen-frontend:dev `
  sh -c "npm install --no-audit --no-fund --silent && node load_glb.mjs /proof/model.glb"
```

Output: `threejs: loaded`, `gltfValidatorErrors: 0`, `gltfValidatorWarnings: 0`, `meshes: 1`, `vertices: 38241`, `triangles: 76315`, `coloredPrimitives: 1`, `materials: 1`. The GLB is a valid, self-contained, coloured asset.

The real-model pytest (`RUN_REAL_MODEL_TESTS=1 -m real_model`) passed separately and asserts the same file loads through trimesh, satisfying the permanent `TEST-AC-12` regression test.

---

## 5. Live end-to-end evidence

Through the running stack with the GPU override:

| Step | Result |
|---|---|
| Register | 201 |
| Create OBJECT project | 201 |
| Upload `car-1.jpg` (480×360 JPEG) | 201 |
| `POST /generate` | 202 |
| Status | `PENDING` → `PROCESSING` / `IMAGE_PREPARATION` → `MODEL_GENERATION` → `RESULT_VALIDATION` → `COMPLETED` |
| `GET /result` | 200, `GLB`, 1 528 660 bytes, 38 241 vertices, 76 315 faces, `has_vertex_colors=true` |
| `GET /download` | 200, 1 528 660 bytes, SHA-256 `79664ce9…`, identical to the standalone proof |
| Worker log | `Task generate_object_task[… ] received`, `mesh_validated`, `triposr_inference_complete`, `glb_exported`, task completed |

The result was stored at the server-generated key `projects/{project_id}/results/{task_id}/model.glb`; the API response exposed neither the storage key nor a filesystem path.

---

## 6. Failure and previous-result preservation (OBJ-AC-13/15, DB-AC-12)

After the successful result, the object worker was paused, a second generation was started with a new idempotency key, the task's source file was removed from storage, and the worker was resumed. The worker received the task and failed in 1.4 s with:

```text
error_code = SOURCE_IMAGE_NOT_FOUND
status_message = The source photograph is no longer available.
```

The status endpoint then reported `project_status=FAILED`, `result_available=true`, and the latest task `FAILED`. The current result id remained unchanged (`517bf95f-…`), the previous GLB remained current, and `/download` still returned 200 with the identical SHA-256. The project was then deleted through the API; the `DIRECTORY` cleanup job completed with `attempts=1` and the project directory was removed. The smoke user, project, tasks, result, images, sessions, cleanup job and outbox rows created by the test were deleted; pre-existing development data was not touched.

---

## 7. Deviations, decisions and fixes

- **No version conflict for PyTorch.** `pytorch/pytorch:2.14.1-cuda12.6-cudnn9-*` and PyPI `torch==2.14.1` exist; the Phase 0 pin was valid. The worker image runs Python 3.12.3 (the PyTorch image runtime) while the API stays on Python 3.11. This is the one Phase 0 deviation and is recorded here.
- **`object_generation` import path.** The package lives at `/opt/object_generation`, so the image must put `/opt` (its parent), not `/opt/object_generation`, on `PYTHONPATH`. The first build exposed this and it was fixed in the Dockerfile and Compose environment.
- **DINO cache ref format.** `huggingface_hub` reads `refs/main` verbatim and does not strip a newline. The initial `download_models.py` wrote `revision + "\n"`, so offline `hf_hub_download` could not resolve the cached DINO config and model loading failed with `MODEL_LOAD_FAILED`. The ref is now written without a newline; the fix was applied to the cache and to `download_models.py`, and model loading was re-verified.
- **Transformers version.** The upstream TripoSR requirement pins `transformers==4.35.0`; the worker uses `transformers==4.46.3` for a supported Python 3.12 install. Real inference and the ViT tokenizer path were verified with the chosen version.
- **Base image pinning.** The ML base images are pinned by exact version tags (as recorded in Phase 0) rather than digest. Digest pinning remains desirable before production; it was not added in this increment because the verified target is the amd64 runtime and a digest change would force another CUDA rebuild.
- **Torchmcubes architecture.** The extension is compiled for SM 86 (RTX 3060). Deploying on a different compute capability requires changing `CUDA_ARCHITECTURES` and rebuilding the image; this is documented in the worker README.
- **Model cache.** `triposr_model_cache` is a persistent named volume mounted at `/models`; `model-init` is the only component that downloads, and the worker runs with `HF_HUB_OFFLINE=1`/`TRANSFORMERS_OFFLINE=1`. A task never downloads weights.
- **CPU/GPU split.** The base `compose.yaml` is CPU-capable (`OBJECT_DEVICE=cpu`, explicit fallback) so the stack starts without NVIDIA hardware; `compose.gpu.yaml` forces `cuda:0` and reserves one GPU. GPU remains the verified production path.
- **Frontend line endings.** The host frontend tree had mixed CRLF/LF while the image copy was LF, which made `format:check` fail on host-mounted sources. The 60 affected frontend source/config files were normalised to LF (content unchanged); the rebuilt image passes all frontend gates.
- **Live-run image.** The canonical `ml/object_generation/Dockerfile` build completed successfully. Because the first canonical build was still running when the live smoke started, an incremental overlay of the final application code was used for that run; the final stack was then recreated from the canonical `mogen-object-worker:dev` image. The overlay was a development convenience and is not part of the committed design.

---

## 8. Coverage and known limitations

Coverage is **89%** (3102 statements, 329 missed) for the backend `app` package. New/changed modules:

| Module | Coverage |
|---|---:|
| `app/api/v1/endpoints/results.py` | 100% |
| `app/services/result_service.py` | 99% |
| `app/services/task_execution_service.py` | 86% |
| `app/tasks/generation_tasks.py` | 80% |
| `app/tasks/object_pipeline.py` | 0% (worker-only; verified live) |

The 90% "generation state management" target in `09_testing.md` Section 19.2 is **not fully met** for `generation_tasks.py`; its remaining uncovered branches are defensive error/logging paths that require a live worker or a failing dependency. `object_pipeline.py` is a thin worker adapter whose behaviour was verified live and whose underlying pipeline has 32 ML unit tests plus the real-model integration test. This shortfall is reported rather than hidden.

Known limitations:

- CPU inference is supported but was not performance-tested end-to-end; GPU is the verified mode.
- Texture baking is deliberately disabled for the MVP (`OBJECT_BAKE_TEXTURE=false`); the delivered asset uses vertex colours.
- The viewer is not part of Phase 5. Task 5.9 delivers the result link in the existing details page; the interactive Three.js viewer is Phase 7.
- The 3D viewer/result-management UI and the production nginx frontend image remain deferred.
- CI (`TEST-AC-19`), Playwright E2E (`TEST-AC-15`), rate limiting and session cleanup scheduling remain unchanged from the Phase 4 state.
- `torchmcubes` and the model cache make the object-worker image large and its first build slow (CUDA compilation); subsequent builds reuse layers.
- The base ML images are version-tagged, not digest-pinned (see Section 7).
- The canonical build's multi-stage cache can re-download the PyTorch devel base after a Docker cache prune; the image itself is reproducible from the pinned tags and commit SHAs.

---

## 9. Verification commands executed

```powershell
# Baseline and final stack
docker compose ps -a
docker compose -f compose.yaml -f compose.gpu.yaml ps -a

# Backend
docker compose run --rm --no-deps api pytest
docker compose run --rm --no-deps api ruff check .
docker compose run --rm --no-deps api ruff format --check .
docker compose run --rm --no-deps api alembic check
docker compose run --rm --no-deps api pip check
docker compose run --rm --no-deps api pytest --cov=app --cov-report=term

# ML
docker run --rm mogen-object-worker:dev python -m pytest /opt/object_generation/tests -q
docker run --rm --gpus all -v mogen_triposr_model_cache:/models `
  -v "${PWD}/ml:/work/ml" -w /work/ml/object_generation `
  -e PYTHONPATH=/work/ml:/opt/triposr:/opt -e RUN_REAL_MODEL_TESTS=1 `
  mogen-object-worker:dev python -m pytest -m real_model -q

# Frontend
docker run --rm mogen-frontend:dev npm run lint
docker run --rm mogen-frontend:dev npm run typecheck
docker run --rm mogen-frontend:dev npm run format:check
docker run --rm mogen-frontend:dev npm run test:run
docker run --rm mogen-frontend:dev npm run build

# Live proof and smoke (commands in Sections 4–6)
```

All checks above passed except the explicitly reported coverage shortfall. No test was skipped silently: the one skipped ML test is the opt-in real-model test, which was executed separately and passed.
