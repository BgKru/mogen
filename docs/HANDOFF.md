# Session Handoff

**Purpose:** everything a new session needs to continue this project without re-deriving context. Read this first, then [`AI_DEVELOPMENT_GUIDE.md`](AI_DEVELOPMENT_GUIDE.md) and the roadmap.

Last updated: 2026-11-09.

> **Continue with:** Phase 9 (comprehensive testing and quality assurance), see Section 9, "Next: Phase 9".
> **Ready-to-paste continuation prompt:** [`NEXT_SESSION.md`](NEXT_SESSION.md).
> **Confirm first:** the Phase 8 baseline (eleven-service stack — nine healthy, `migration` and `model-init` `Exited (0)`; 509 backend tests; 130 frontend tests; 75 scene ML unit tests plus the skipped opt-in real-reconstruction test; 35 object ML unit tests plus the opt-in real-model test; object worker healthy with the real TripoSR model loaded; scene worker healthy with COLMAP 4.2.1 and OpenMVS 2.4.0 detected; dispatcher and recovery heartbeats fresh; backend lint/format and `alembic check` clean).
> **Detailed plan:** Section 9, "Phase 8 — reliability, security and optimization (complete)" and "Next: Phase 9".
> **Copy-paste prompt and resume checklist:** Section 10 and [`NEXT_SESSION.md`](NEXT_SESSION.md).

---

## 1. State

The project is a 3D generation web application (photographs to GLB objects and reconstructed scenes). Phase 0 (specifications and architecture decisions) and Phase 1 (infrastructure foundation) are complete. Phase 2 is complete: the close-out review verified roadmap tasks 2.1–2.10 and the applicable acceptance criteria, found and fixed one `API-AC-15` contract defect (field-validation details now expose `code` instead of `type`) with a regression test, and left no Phase 2 item open. The full evidence table is in [`reviews/phase2_closeout.md`](reviews/phase2_closeout.md). Phase 3 is complete: the React frontend now implements the application shell, registration/login/logout with CSRF-aware API calls and protected routes, the project dashboard, project creation with mode-dependent image selection, previews and sequential uploads, and project details with source-image management; generation was shown only as a disabled placeholder until Phase 5 enabled the real generation action. Increment 2a added the nine SQLAlchemy models and the initial Alembic migration, 2b the repository layer and its FastAPI dependencies, 2c cookie-based authentication with Argon2id, server sessions and signed double-submit CSRF, 2d the project API with ownership authorization (creation, paginated/filtered listing with nested summaries, detail and asynchronous deletion), 2e the storage abstraction (`StorageBackend` plus `LocalStorage`), 2f image upload and listing with content validation, size and dimension limits, SHA-256, object/scene count rules and file rollback, 2g private image content delivery and guarded image deletion, and 2h the cleanup worker that executes the queued `FILE`/`DIRECTORY` cleanup jobs on a dedicated Celery `file_cleanup` queue. A six-service Docker Compose stack ran at the end of Phase 3: PostgreSQL 17.11, Redis 7.4.12, an Alembic migration job, a FastAPI backend, a Celery cleanup worker (beat poll included for development), and a React + Vite frontend that proxies `/api` to the backend. The backend has 339 passing tests and clean lint; the frontend has 84 passing tests across 14 files and passes lint, typecheck, formatting, tests and production build (Section 5). There are no git commits yet. The next step is Phase 4 (generation task creation and lifecycle, transactional outbox and dispatcher, queue separation, worker containers and task recovery), then Phase 5 (TripoSR).

Phase 4 is complete at its roadmap scope: the Celery application now declares the three documented queues (`object_generation`, `scene_reconstruction`, `file_cleanup`), `POST /api/v1/projects/{id}/generate` creates a persistent task, its ordered input snapshot, the `PENDING` project transition and a `generation.requested` outbox event in one PostgreSQL transaction, and a standalone Outbox Dispatcher publishes committed events to Redis with bounded exponential backoff, expired-lock recovery and at-least-once semantics. Dedicated `object-worker`, `scene-worker`, `outbox-dispatcher` and `task-recovery` containers run alongside the existing API, cleanup worker, database, Redis, migration and frontend; each worker consumes only its own queue. `GET /api/v1/projects/{id}/status` returns the persisted project/task state, stage, progress only when real, error fields and result availability. Atomic claim/lease/heartbeat transitions, duplicate-delivery protection, worker interruption recovery through the outbox, dispatch-stall detection and cooperative cancellation are implemented; cleanup jobs are now dispatched through `cleanup.requested` while the beat scan remains the recovery path. The Phase 4 workers deliberately contained no ML pipeline: a claimed task failed honestly with `WORKER_UNAVAILABLE` until Phase 5 registered the TripoSR pipeline. Backend suite at the end of Phase 4: **451 passed** (294 database/API, 149 unit, 8 API-shell); frontend suite: **84 passed**; the ten-service stack was healthy.

Phase 5 is complete at its roadmap scope. A dedicated `mogen-object-worker:dev` image carries PyTorch 2.14.1/CUDA 12.6, TripoSR at pinned commit `d26e3318…`, pinned weights whose `model.ckpt` SHA-256 is verified, `torchmcubes` built for SM 86 and rembg. A one-shot `model-init` service populates the persistent `triposr_model_cache` volume; the worker runs with offline HF flags and loads the model once at startup. `generate_object_task` now resolves the real TripoSR pipeline through the existing Phase 4 `register_pipeline(TaskType.OBJECT, …)` hook; the pipeline decodes and preprocesses the snapshot image, runs inference, extracts and validates the mesh, exports a self-contained GLB with vertex colours, validates the container/geometry/appearance, and hands the asset back for transactional persistence. `TaskExecutionService.complete_with_result` clears the previous current result, inserts the new current row and completes the task and project in one transaction; a failed or cancelled attempt preserves the previous result and file. `GET /api/v1/projects/{id}/result` and `GET /api/v1/projects/{id}/download` serve the current validated GLB with ownership checks and the documented headers, and the project details page now starts generation, polls real status/stages, displays stable errors, supports retry and offers the authenticated download. The mandatory standalone proof produced a 1 528 660-byte GLB with 38 241 vertices / 76 315 faces that loaded in Three.js with zero glTF Validator errors; the live worker completed a real task in about 8 s with a warm model. Backend suite: **481 passed** (313 database/API, 160 unit, 8 API-shell); frontend suite: **92 passed** across 15 files; ML unit suite: **35 passed, 1 skipped** (recorded as 32 at the time; corrected during Phase 8) plus the opt-in real-model test **1 passed**; coverage 89%; the eleven-service stack is healthy with `migration` and `model-init` `Exited (0)`. Phase 6 is complete at its roadmap scope. A dedicated `mogen-scene-worker:dev` image carries COLMAP 4.2.1 (official CUDA-enabled image, digest-pinned), OpenMVS 2.4.0 built unmodified from commit `58117204…`, OpenCV 4.12 built from source, CGAL 6.0.1 and the Python orchestration package. The worker verifies every external executable at startup and logs `scene_pipeline_ready`; it registers `run_colmap_pipeline` through the existing Phase 4 `register_pipeline(TaskType.SCENE, …)` hook and executes the documented COLMAP/OpenMVS sequence with real stage reporting, heartbeats, cancellation, task-scoped workspaces and checkpoint reuse. The pipeline validates the input set (format, duplicates, dimensions), inspects every sparse model, selects one by measured properties, runs dense reconstruction, meshing, refinement and texturing, converts the scene with TransformScene, repacks the OBJ/MTL/PNG set into one self-contained GLB with embedded textures, validates it independently, and persists it through the existing `complete_with_result` transaction as `scene.glb`. The scene UI on the existing details page starts reconstruction, polls persisted stages, shows stable errors, retries and offers the authenticated download. The mandatory standalone proof reconstructed all 11 Sceaux Castle photographs (11/11 registered, 8 018 sparse points, 332 303 dense points, 16 539 vertices / 28 991 triangles) into a 959 504-byte GLB with one embedded texture that passed the Khronos glTF Validator with 0 errors and 0 warnings; a live worker task also completed and downloaded the same validated asset with the task-status lifecycle. Backend suite: **491 passed** (316 database/API, 167 unit, 8 API-shell); frontend suite: **94 passed** across 15 files; scene ML unit suite: **74 passed, 1 skipped** (the skip is the opt-in real-reconstruction test); the eleven-service stack is healthy with `migration` and `model-init` `Exited (0)`. Phase 7 (viewer and result management) has not started.

Phase 7 is complete at its roadmap scope. The unified Three.js viewer (React Three Fiber `9.8.2`, Drei `10.7.9`, Three.js `0.187.0`, pinned exactly) is an independent `frontend/src/features/model-viewer/` module used by the new protected route `/projects/{id}/result`. It reads the current result through the existing `GET /result` API, downloads the GLB through the authenticated `GET /download` endpoint, loads it through a temporary blob URL and `GLTFLoader`, centres it without altering the asset, and disposes geometry, materials and textures on result change and unmount. OrbitControls provide rotate, zoom and pan; the toolbar adds reset, fit-to-view, grid, background and fullscreen. The information panel shows project name, generation type, status, source-image count, format, file size, creation date and mesh/vertex/polygon/material/texture counts. Empty, processing and failed-regeneration states are explicit and keep the previous successful result visible. Both a real TripoSR object (23 039 vertices / 45 983 triangles, vertex colours) and the real COLMAP/OpenMVS scene (202 493 vertices / 297 813 triangles, one embedded texture) loaded and were inspected in the application viewer in Edge; both downloads matched the stored SHA-256. Frontend suite: **130 passed** across 22 files, including 35 viewer cases with a real GLB fixture.

Phase 8 is complete at its roadmap scope: authentication and file-security verification, generation reliability and recovery, data consistency, resource management, the performance baseline and infrastructure reliability (tasks 8.1–8.8). No Phase 9 work was started and no Phase 2–7 behaviour was re-opened. Six findings became fixes: (1) a **stale identity-map read** in `TaskExecutionService` could hide a cancellation request written after the worker claimed the task, so a project deleted mid-generation could still register a result — terminal transitions now refresh the task row (`get_for_update(populate_existing=True)`, `get_refreshed`); (2) **superseded result files were never deleted** after a successful regeneration, so every retry leaked a GLB — registration now queues a `FILE` cleanup job and `cleanup.requested` event in the same transaction; (3) **failed scene workspaces accumulated without bound** — a retention sweep now queues expired terminal workspaces for deletion and logs temporary-storage usage; (4) **scene toolchain probes wrote OpenMVS log files into the worker's CWD** — `verify_toolchain` now runs `--help` in a throwaway directory; (5) the **backup/restoration procedure was undocumented** — now in `docs/operations/` with a runnable consistency checker; (6) **backend API tests could write uploads into the live `/data` volume** — test clients now default to `/tmp/mogen-test-storage`. Phase 8 added 18 backend cases (509 total) and one scene-ML case (75 + the skipped opt-in test), live Redis/PostgreSQL outage drills, a PostgreSQL + file-storage backup/restore drill with identical counts and SHA-256, and a measured performance baseline. The full evidence table is in [`reviews/phase8_closeout.md`](reviews/phase8_closeout.md).

---

## 2. How to work on this project

The documentation is the source of truth, not the code.

1. Read [`AI_DEVELOPMENT_GUIDE.md`](AI_DEVELOPMENT_GUIDE.md). It defines the workflow, the Definition of Done (Section 20) and the completion-report format (Section 18.4).
2. Read [`10_development_roadmap.md`](specifications/10_development_roadmap.md) for the current phase and its acceptance criteria.
3. Read the subsystem specifications for the area you are changing.
4. Cite acceptance criteria by identifier in every report: `AC-nn`, `UI-AC-nn`, `FE-AC-nn`, `BE-AC-nn`, `DB-AC-nn`, `OBJ-AC-nn`, `SCENE-AC-nn`, `INF-AC-nn`, `TEST-AC-nn`, `API-AC-nn`, milestones `M0`–`M9`.
5. Never claim work that was not executed. Report checks as passed, failed, skipped, not executed or blocked.

Where the guide and a specification disagree, the specification wins. Where two specifications disagree, follow Section 4.5 of the guide and record the resolution; do not silently pick one.

---

## 3. Repository map

```text
mogen/
├── docs/                     guide, 11 specifications, 4 architecture records, close-out reviews, operations procedures, this handoff
├── backend/                  FastAPI application (Python 3.11)
├── frontend/                 React + Vite application (Node 24)
├── ml/
│   ├── object_generation/    TripoSR worker image, pipeline, tests, viewer proof (Phase 5, real)
│   ├── scene_reconstruction/ COLMAP/OpenMVS worker image, pipeline, tests, standalone proof (Phase 6, real)
│   └── workers/              placeholder
├── infrastructure/           empty placeholders (docker, nginx, scripts)
├── tests/                    placeholder for cross-component tests
├── compose.yaml              development stack, eleven services
├── compose.gpu.yaml          GPU reservation for the object and scene workers
├── .dockerignore             ML worker build context
├── .env.example              environment template
└── README.md
```

What is real: `backend/`, `frontend/`, `ml/object_generation/`, `ml/scene_reconstruction/`, `compose.yaml`, `compose.gpu.yaml`, `.dockerignore`, `.env.example`, all of `docs/`.
What is a placeholder: `ml/workers/`, `infrastructure/`, and `tests/` (`.gitkeep` only).

Key backend files:

| Path | Contents |
|---|---|
| `backend/app/main.py` | Application factory, lifespan, request-ID middleware, CORS, exception handlers (including `AppError`) |
| `backend/app/core/config.py` | `Settings` (pydantic-settings), validation, `redacted()` |
| `backend/app/core/logging.py` | JSON formatter, request-ID context variable |
| `backend/app/core/errors.py` | Error envelope, status-to-code mapping |
| `backend/app/db/session.py` | Engine, session factory, `session_scope`, `database_is_available` |
| `backend/app/db/base.py` | `Base` with naming convention for Alembic |
| `backend/app/db/models/` | One module per table, in dependency order, plus `enums.py` and the package `__init__.py` |
| `backend/app/repositories/` | One repository per entity; SQL only, never commits; exported from the package `__init__.py` |
| `backend/app/services/auth_service.py` | Registration, login, logout, session validation and CSRF issuance |
| `backend/app/services/project_service.py` | Project create/list/get/delete, name validation, pagination capping, deletion transaction |
| `backend/app/services/image_service.py` | Image validation, upload state, count rules, storage write and metadata persistence, content opening and guarded deletion with a `FILE` cleanup job |
| `backend/app/services/cleanup_service.py` | Cleanup job claiming, file/directory deletion, retry and failure recording, active-task deferral |
| `backend/app/tasks/celery_app.py` | Celery application: Redis broker, three queues and routes, per-pipeline time limits, visibility timeout, beat poll |
| `backend/app/tasks/cleanup_tasks.py` | `cleanup_storage_task`, the worker-cycle entry point and its process-wide runtime |
| `backend/app/tasks/generation_tasks.py` | `generate_object_task`/`reconstruct_scene_task`, the broker-free worker lifecycle, the heartbeat monitor, the pipeline registry and `PipelineArtifact` persistence |
| `backend/app/tasks/object_pipeline.py` | Worker-only TripoSR adapter: reads the source snapshot, runs `object_generation`, reports real stages and returns the validated artifact |
| `backend/app/tasks/scene_pipeline.py` | Worker-only COLMAP/OpenMVS adapter: reads the ordered image snapshot, verifies the toolchain, runs `PhotogrammetryReconstructor`, maps stable errors and returns the validated GLB artifact with a `scene.glb` storage key |
| `backend/app/tasks/outbox_publisher.py` | Maps outbox events onto Celery task names, queues and task IDs; validates payloads before publishing |
| `backend/app/tasks/outbox_dispatcher.py` | Standalone dispatcher process loop and its heartbeat file |
| `backend/app/tasks/task_recovery.py` | Standalone recovery process loop and its heartbeat file |
| `backend/app/services/generation_service.py` | Generation task creation, input validation, fingerprinting, idempotency, project transitions and the status view |
| `backend/app/services/result_service.py` | Current-result lookup, ownership checks, safe download name, streamed GLB delivery |
| `backend/app/services/outbox_events.py` | Payload builders and transactional event creation for `generation.requested` and `cleanup.requested` |
| `backend/app/services/outbox_service.py` | Dispatcher claim/publish/retry/expired-lock logic |
| `backend/app/services/task_execution_service.py` | Worker-side claim, heartbeat, progress, completion, `complete_with_result`, failure and cancellation |
| `backend/app/services/task_recovery_service.py` | Stale-lease requeue/fail/cancel and dispatch-stall detection |
| `backend/app/services/workspace_retention_service.py` | Scene-workspace retention sweep and temporary-storage usage report |
| `backend/app/schemas/generation.py` | Generation task, start and project-status response schemas |
| `backend/app/schemas/result.py` | Generation Result Response schema (api_contracts.md 5.8) |
| `backend/app/api/v1/endpoints/generation.py` | `POST /projects/{id}/generate` (202/200) and `GET /projects/{id}/status` |
| `backend/app/api/v1/endpoints/results.py` | `GET /projects/{id}/result` and `GET /projects/{id}/download` |
| `backend/app/storage/` | `StorageBackend` interface, `LocalStorage` backend, storage-key validation and root containment |
| `backend/app/core/security.py` | Argon2id hashing, session-token hashing, signed session-bound CSRF tokens |
| `backend/app/schemas/` | Pydantic request/response models (auth, user, project, image and generation) |
| `backend/app/api/v1/endpoints/auth.py` | Register, login, logout, current user, CSRF endpoints and cookie handling |
| `backend/app/api/v1/endpoints/projects.py` | Project create, list, detail and delete endpoints |
| `backend/app/api/v1/endpoints/images.py` | Image upload, listing, streamed content and deletion endpoints |
| `backend/app/api/dependencies.py` | Request-scoped session, storage, repository, auth, CSRF, project, image and generation-service dependencies |
| `backend/alembic/versions/1f302d830cf9_initial_schema.py` | Initial schema migration (9 tables, all constraints, indexes and partial unique indexes) |
| `backend/tests/db/` | Database integration tests: entities, constraints, repositories, auth/project/image API, generation API, task lifecycle, task recovery, outbox dispatcher, cleanup service and cleanup dispatch, deletion policies, migration round-trip |
| `backend/tests/unit/test_repository_dependencies.py` | Repository dependency wiring and `dependency_overrides` behaviour |
| `backend/tests/unit/test_security.py` | Password, session-token, CSRF and production-settings tests |
| `backend/tests/unit/test_project_validation.py` | Project name and page-limit validation helpers |
| `backend/tests/unit/test_image_validation.py` | Image format, dimension, filename, `Content-Disposition` and decompression-bomb validation |
| `backend/tests/unit/test_storage.py` | Storage round-trip, atomic write, deletion, key validation, traversal and failure handling |
| `backend/tests/unit/test_celery_config.py` | Three-queue routing, per-task time limits, visibility timeout, beat schedule, no result backend, task registration |
| `backend/tests/db/test_generation_api.py` | Generation start/status contract, snapshots, idempotency, conflicts, result preservation, transaction rollback |
| `backend/tests/db/test_task_lifecycle.py` | Atomic claim, heartbeat, progress, completion, failure, cancellation and the broker-free worker pipeline |
| `backend/tests/db/test_task_recovery.py` | Stale leases, requeue via outbox, recovery budget, cancellation, dispatch stalls |
| `backend/tests/db/test_outbox_dispatcher.py` | Claim/publish/retry/permanent-failure/expired-lock behaviour and the no-lock-during-publish probe |
| `backend/tests/db/test_cleanup_dispatch.py` | `cleanup.requested` creation, routing to `file_cleanup`, targeted worker execution |
| `backend/tests/db/test_result_api.py` | Result metadata/download contract, ownership, missing file, soft-deleted project, current-only selection, safe filename |
| `backend/tests/db/test_result_persistence.py` | Transactional result registration, current-result replacement, previous-result preservation, duplicate delivery, artifact/storage errors |
| `backend/tests/unit/test_result_service.py` | Result storage key, safe download names, `Content-Disposition`, stream closure |
| `backend/tests/unit/test_generation_fingerprint.py` | Canonical fingerprint and task parameter snapshots |
| `backend/tests/db/test_scene_generation.py` | SCENE task result registration, `scene.glb` key, failure preservation |
| `backend/tests/unit/test_scene_settings.py` | Scene settings validation (paths, strategy, thresholds, timeouts) |
| `backend/tests/unit/test_generation_validation.py` | OBJECT/SCENE input-count rules |
| `backend/tests/unit/test_outbox_publisher.py` | Event-to-queue mapping, payload validation and Celery publication |
| `backend/tests/unit/test_outbox_backoff.py` | Bounded exponential backoff with jitter |
| `backend/app/api/health.py` | Three health endpoints |
| `backend/app/api/v1/router.py` | Versioned router; authentication, projects, images, generation and results are registered |

Key frontend files:

| Path | Contents |
|---|---|
| `frontend/src/main.tsx` | Entry point |
| `frontend/src/app/providers/` | `AppProviders`, `QueryProvider`, `AuthProvider`/`auth-context`, `ToastProvider`/`toast-context` |
| `frontend/src/app/router/` | `AppRouter`, `ProtectedRoute`, `routes.ts` |
| `frontend/src/app/layout/` | `AppLayout` (sidebar, topbar, responsive navigation, outlet) |
| `frontend/src/features/auth/` | Auth API, Zod schemas, auth card |
| `frontend/src/features/projects/` | Projects API, query hooks, project card/preview, create schema |
| `frontend/src/features/image-upload/` | Images API, validation, selection hook, dropzone, preview grid, mode cards |
| `frontend/src/features/generation/` | Generation API, status polling hook, `GenerationPanel` (start/retry, real stages, errors, result download link) |
| `frontend/src/features/model-viewer/` | Unified Three.js viewer: `ModelViewer`/`ModelCanvas`/`ModelScene`/`ViewerToolbar`/`ModelInfoPanel`, authorized GLB loader, bounds/disposal utilities, viewer types and tests |
| `frontend/src/shared/api/` | Axios client, DTOs, mappers, error normalisation, query keys |
| `frontend/src/shared/components/` | Button, Input, Alert, badges, confirm dialog, spinner, empty state, page header |
| `frontend/src/shared/lib/` | Formatting, Russian labels, UUID check, Zod-to-RHF resolver, generation stage/error messages |
| `frontend/src/pages/` | Landing, Login, Register, Dashboard, Create Project, Project Details, Model Viewer, Not Found |
| `frontend/src/test/` | Vitest setup and provider-aware render helper |
| `frontend/src/app/styles/` | `globals.css`, `theme.css` with the UI palette as Tailwind tokens |

Key ML files:

| Path | Contents |
|---|---|
| `ml/object_generation/Dockerfile` | Dedicated CUDA worker image: PyTorch 2.14.1/CUDA 12.6, torchmcubes built for SM 86, backend runtime, TripoSR, pipeline package, development test stage |
| `ml/object_generation/download_models.py` | One-shot model-init: pinned TripoSR weights + DINO config + rembg model, checksum verification and manifest |
| `ml/object_generation/preprocessing.py` | Decode, EXIF, RGB/RGBA, rembg, foreground crop/pad/resize, neutral composite, original preservation |
| `ml/object_generation/model_loader.py` | Checksum/device verification, one-time `TSR` load, warm-up, CUDA cleanup |
| `ml/object_generation/generator.py` | `torch.inference_mode` TripoSR inference and mesh extraction |
| `ml/object_generation/mesh_processor.py` | Geometry validation and statistics |
| `ml/object_generation/exporter.py` | Vertex-colour-preserving GLB export |
| `ml/object_generation/validator.py` | Independent GLB container/accessor/geometry/appearance validator |
| `ml/object_generation/pipeline.py` | Production preprocessing → inference → export → validation orchestration with stage/heartbeat/cancel callbacks |
| `ml/object_generation/standalone.py` | Mandatory standalone inference/GLB proof CLI |
| `ml/object_generation/exceptions.py` | Stable object-generation error codes |
| `ml/object_generation/tests/` | 32 unit tests plus the opt-in real-model integration test and GLB fixtures |
| `ml/object_generation/testdata/` | Real photographs used by the proof and the real-model test |
| `ml/object_generation/viewer/` | Three.js `GLTFLoader` + Khronos glTF Validator proof for the exported GLB |
| `ml/scene_reconstruction/Dockerfile` | Dedicated scene worker image: COLMAP 4.2.1 (pinned official image), OpenMVS 2.4.0 built from source, OpenCV 4.12, CGAL 6.0.1, Eigen 3.4, VCGLib, Python venv, development test stage |
| `ml/scene_reconstruction/config.py` | Validated scene configuration, stage identifiers and per-stage timeouts |
| `ml/scene_reconstruction/dataset.py` | Ordered snapshot workspace, JPEG/PNG decode validation, duplicate/format/dimension rejection, original-byte preservation |
| `ml/scene_reconstruction/runner.py` | Controlled subprocess execution: argument arrays, timeout, log capture, process-group termination, cancellation |
| `ml/scene_reconstruction/colmap_runner.py` | COLMAP commands, database statistics (pair-id decoding) and stage output validation |
| `ml/scene_reconstruction/reconstruction_selector.py` | Sparse model parsing, component detection, diagnostics and selection by measured quality |
| `ml/scene_reconstruction/openmvs_runner.py` | InterfaceCOLMAP, DensifyPointCloud, ReconstructMesh, RefineMesh, TextureMesh and TransformScene commands and validation |
| `ml/scene_reconstruction/mesh_processor.py` | Mesh loading/statistics and geometry validation |
| `ml/scene_reconstruction/exporter.py` | OBJ/GLB repack into one self-contained GLB and raw-export diagnostics |
| `ml/scene_reconstruction/validator.py` | Independent GLB parser extended for embedded images, UVs, materials and textures |
| `ml/scene_reconstruction/pipeline.py` | `PhotogrammetryReconstructor`: ordered stages, checkpointing, diagnostics and result metadata |
| `ml/scene_reconstruction/standalone.py` | Standalone proof and `--verify-tools` CLI |
| `ml/scene_reconstruction/tests/` | 74 unit cases plus the opt-in real reconstruction test |
| `ml/scene_reconstruction/README.md` | Image layout, pinned versions, pipeline, proof and license notes |

---

## 4. Runtime

| Service | Image | Port (bound to 127.0.0.1) | Notes |
|---|---|---|---|
| `db` | `postgres:17@sha256:748a18a5…` | 5432 | health: `pg_isready` |
| `redis` | `redis:7.4-alpine@sha256:8da19c73…` | 6379 | AOF enabled, health: `redis-cli ping` |
| `migration` | `mogen-api:dev` | — | runs `alembic upgrade head`, exits 0; **`Exited (0)` is expected** |
| `model-init` | `mogen-object-worker:dev` | — | one-shot: verifies/populates the pinned TripoSR, DINO and rembg cache in `triposr_model_cache`; `Exited (0)` is expected |
| `api` | `mogen-api:dev` | 8000 | health: `GET /health/ready` |
| `cleanup-worker` | `mogen-api:dev` | — | Celery worker on queue `file_cleanup` with `--beat`; health: `celery inspect ping` |
| `object-worker` | `mogen-object-worker:dev` | — | Celery worker on queue `object_generation`, `--pool=solo --include=app.tasks.object_pipeline`; loads the real TripoSR model at startup; health: `celery inspect ping`; GPU via `compose.gpu.yaml` |
| `scene-worker` | `mogen-scene-worker:dev` | — | Celery worker on queue `scene_reconstruction`, `--include=app.tasks.scene_pipeline`; verifies COLMAP 4.2.1 and OpenMVS 2.4.0 at startup; health: `celery inspect ping`; GPU via `compose.gpu.yaml` |
| `outbox-dispatcher` | `mogen-api:dev` | — | Standalone outbox publishing loop; health: `/tmp/outbox-dispatcher.heartbeat` freshness |
| `task-recovery` | `mogen-api:dev` | — | Standalone stale-task recovery loop; health: `/tmp/task-recovery.heartbeat` freshness |
| `frontend` | `mogen-frontend:dev` | 5173 | health: `wget --spider /` |

All application images run as unprivileged users (`appuser` uid 1000 for the API/cleanup workers, `ubuntu` uid 1000 for the object and scene workers, `node` uid 1000 for the frontend). The object worker's base image already provides UID 1000 as `ubuntu`; the scene worker's COLMAP base image does as well, so the shared `app_data` volume stays writable by all.

Frontend routes: `/`, `/login`, `/register`, `/dashboard`, `/projects/new`, `/projects/{id}`, `/projects/{id}/result`. The dashboard, creation, details and result routes are protected and redirect unauthenticated users to `/login`; the backend still enforces authentication and ownership on every call. The UI language is Russian. The browser reaches the API through the same-origin `/api` proxy, so the session cookie and CSRF flow work without CORS.

Backend endpoints: `GET /health/live`, `GET /health/ready` (503 when PostgreSQL is unreachable), `GET /health/dependencies` (always 200, reports `degraded`). Swagger at `http://127.0.0.1:8000/docs`.

The cleanup worker consumes jobs from Redis DB 1 (the broker) and processes them against PostgreSQL and the shared `app_data` volume; it never opens a port. Its beat scan still runs every `CLEANUP_POLL_INTERVAL_SECONDS` (default 15) as the recovery path, but project and image deletion now insert a `cleanup.requested` outbox event in the same transaction and the Outbox Dispatcher publishes it to the `file_cleanup` queue for immediate targeted processing. The same worker also runs the hourly scene-workspace retention sweep (`cleanup_scene_workspaces_task`, `SCENE_WORKSPACE_SWEEP_INTERVAL_SECONDS`), which queues terminal workspaces older than `SCENE_WORKSPACE_RETENTION_HOURS` (default 168; `0` disables pruning) as `DIRECTORY` cleanup jobs and logs `workspace_usage`. Structured JSON logs include `project_id`, `cleanup_job_id` and `operation`.

The object worker is a real TripoSR environment: it loads the pinned model once at startup, verifies the cached weights, registers the object pipeline through `register_pipeline`, and executes preprocessing, inference, mesh extraction, GLB export, validation and result persistence. The scene worker is now a real COLMAP/OpenMVS environment: it verifies COLMAP 4.2.1 and OpenMVS 2.4.0 at startup, registers `run_colmap_pipeline`, executes the documented reconstruction sequence in a task-scoped workspace and persists the repacked, validated GLB through `complete_with_result`. The Outbox Dispatcher and Task Recovery run as independent processes; neither serves HTTP.

The v1 API prefix is `/api/v1`. Authentication is implemented under `/api/v1/auth/*`:

| Endpoint | Success | Notes |
|---|---|---|
| `POST /api/v1/auth/register` | 201 + `{"user": …}` | Sets the `session` (HttpOnly) and `csrf_token` cookies |
| `POST /api/v1/auth/login` | 200 + `{"user": …}` | Generic 401 for bad credentials or inactive accounts |
| `POST /api/v1/auth/logout` | 204 | Requires `X-CSRF-Token`; revokes the session and clears both cookies |
| `GET /api/v1/auth/me` | 200 + user | 401 when the session is missing, revoked or expired |
| `GET /api/v1/auth/csrf` | 200 + `{"csrf_token": …}` | Requires a session; sets the readable CSRF cookie |

Every other unimplemented `/api/v1/*` path still returns a `NOT_FOUND` error envelope; the generation start/status and result read/download endpoints are implemented. CSRF tokens are HMAC values bound to one session, so a new session (registration or login) rotates the token. Cookies use `SameSite=Lax`, `Path=/`, and `Secure` in production.

Projects are implemented under `/api/v1/projects`:

| Endpoint | Success | Notes |
|---|---|---|
| `POST /api/v1/projects` | 201 + Project Response | Requires `X-CSRF-Token`; body `{name, type}`; owner is the caller; status `CREATED`; never starts generation |
| `GET /api/v1/projects` | 200 + `{items, total_count, limit, offset}` | `limit` default 20 capped by `MAX_PAGE_SIZE` (100); `type`, `status`, `sort` filters |
| `GET /api/v1/projects/{project_id}` | 200 + Project Response | 404 for missing, soft-deleted or another user's project |
| `DELETE /api/v1/projects/{project_id}` | 202 + `{project_id, deletion_status}` | Requires `X-CSRF-Token`; soft delete + task cancellation + `DIRECTORY` cleanup job + `cleanup.requested` outbox event in one transaction |

`sort` accepts `created_at_desc` (default) and `created_at_asc`; any other value is rejected with 422. Unknown or malformed UUIDs are rejected with 422. Project responses embed `current_result` and `latest_task` summaries, and `result_available` follows the current result, not the project status.

Images are implemented under `/api/v1/projects/{project_id}/images`:

| Endpoint | Success | Notes |
|---|---|---|
| `POST /api/v1/projects/{project_id}/images` | 201 + Image Response | Requires `X-CSRF-Token`; `multipart/form-data` with one `file`; JPEG/PNG only |
| `GET /api/v1/projects/{project_id}/images` | 200 + `{items, total_count}` | Metadata only, upload order; 404 for an inaccessible project |
| `GET /api/v1/projects/{project_id}/images/{image_id}/content` | 200 + image bytes | Streamed with the verified `Content-Type`, `Content-Disposition: inline; filename="…"`, `Cache-Control: private` and `X-Content-Type-Options: nosniff`; no storage key or path |
| `DELETE /api/v1/projects/{project_id}/images/{image_id}` | 204 | Requires `X-CSRF-Token`; records a `FILE` cleanup job and a `cleanup.requested` event for the storage key and removes the metadata in one transaction |

Upload validation: extension, declared media type and the decoded actual format must agree; the verified MIME type and SHA-256 are stored. A file over `MAX_UPLOAD_SIZE_MB` returns 413; an image whose longest edge exceeds `MAX_IMAGE_DIMENSION` returns 400; invalid content returns 400; unsupported formats return 415. OBJECT projects accept exactly one image and SCENE projects at most `MAX_SCENE_IMAGES`; exceeding the count, or uploading while a generation task holds the project, returns 409.

Content retrieval: 401 without a session, 404 (`PROJECT_NOT_FOUND` / `IMAGE_NOT_FOUND`) for another user, an unknown image, an image of another project, a soft-deleted project, or a metadata row whose stored file has disappeared; 503 `STORAGE_UNAVAILABLE` when the filesystem itself fails.

Deletion: 404 for the same access failures and for a repeated deletion, 409 `IMAGE_REFERENCED` when any generation task snapshot uses the image, 409 `INVALID_PROJECT_STATE` while the project is `PENDING`/`PROCESSING` or an active task exists. The metadata disappears immediately, so content retrieval returns 404 at once; the stored file is deleted by the cleanup worker after the dispatcher wakes it (usually within a few seconds), and a missed event is still caught by the `CLEANUP_POLL_INTERVAL_SECONDS` beat scan. Scene positions are not renumbered after a deletion.

Generation is implemented under `/api/v1/projects/{project_id}`:

| Endpoint | Success | Notes |
|---|---|---|
| `POST /api/v1/projects/{project_id}/generate` | 202 new / 200 repeat + `{task: …}` | Requires `X-CSRF-Token` and a mandatory project-scoped `Idempotency-Key` header; optional empty JSON body. Creates the task, ordered snapshot, `PENDING` project and outbox event in one transaction; never publishes to Redis itself. Same key + same fingerprint returns the existing task with 200; a different fingerprint returns 409 `IDEMPOTENCY_KEY_REUSED`; another active task returns 409 `GENERATION_ALREADY_RUNNING`. |
| `GET /api/v1/projects/{project_id}/status` | 200 + `{project_id, project_status, result_available, latest_task}` | `latest_task` is null before generation; it reports only persisted status/stage/progress/error fields. `result_available` follows the current result, independent of the latest task. |

The generation API returns 409 `GENERATION_INPUT_MISSING` when an OBJECT project does not have exactly one image or a SCENE project is outside `MIN_SCENE_IMAGES`/`MAX_SCENE_IMAGES`, and 409 `INVALID_PROJECT_STATE` while the project is `UPLOADING`. A generation request accepted with 202 is dispatched by the Outbox Dispatcher; the object worker then executes the real TripoSR pipeline and the scene worker the real COLMAP/OpenMVS pipeline, each persisting its validated result. Manual retry uses a new idempotency key and creates a new task.

Results are implemented under `/api/v1/projects/{project_id}`:

| Endpoint | Success | Notes |
|---|---|---|
| `GET /api/v1/projects/{project_id}/result` | 200 + Generation Result Response | Returns only the current validated result: `id`, `project_id`, `task_id`, `format`, `mime_type`, `file_size_bytes`, `metadata`, `is_current`, `created_at`. No `storage_key` or path. 404 `RESULT_NOT_FOUND` when there is no result; 404 `PROJECT_NOT_FOUND` for another user's or a deleted project. |
| `GET /api/v1/projects/{project_id}/download` | 200 + GLB bytes | Requires authentication and ownership; streams `model/gltf-binary` in 64 KiB chunks with `Content-Disposition: attachment; filename="<safe>.glb"` (plus RFC 5987 `filename*`), `Cache-Control: private, no-store`, `X-Content-Type-Options: nosniff` and `Content-Length`. A missing stored file is 404 `RESULT_FILE_MISSING`; storage failure stays 503 `STORAGE_UNAVAILABLE`. |

A failed regeneration leaves the previous current result and its file in place; `result_available` therefore follows the current result, not the latest task status.

---

## 5. Verified baseline: confirm it before changing anything

```bash
# Phase 7 stack (GPU). The base compose.yaml is CPU-capable; this override
# reserves the GPU for the object worker and enables COLMAP's CUDA features in
# the scene worker. The first scene-worker build compiles OpenCV 4.12 and
# OpenMVS 2.4.0 (~30-45 min); later builds reuse layers.
docker compose -f compose.yaml -f compose.gpu.yaml up -d --build
docker compose -f compose.yaml -f compose.gpu.yaml ps -a           # nine healthy; migration and model-init Exited (0)
docker compose exec cleanup-worker celery -A app.tasks.celery_app:celery_app inspect ping
docker compose exec object-worker celery -A app.tasks.celery_app:celery_app inspect ping
docker compose exec scene-worker celery -A app.tasks.celery_app:celery_app inspect ping
docker compose exec outbox-dispatcher cat /tmp/outbox-dispatcher.heartbeat   # recent epoch
docker compose exec task-recovery cat /tmp/task-recovery.heartbeat           # recent epoch
curl http://127.0.0.1:8000/health/ready
curl http://127.0.0.1:8000/health/dependencies
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:5173/
curl -s http://127.0.0.1:5173/api/v1/probe   # JSON 404 from uvicorn proves the proxy
docker compose run --rm --no-deps api pytest        # 509 passed (332 are database/API integration tests)
docker compose run --rm --no-deps api ruff check .  # clean
docker compose run --rm --no-deps api ruff format --check . # 112 files formatted
docker compose run --rm --no-deps api alembic check # no schema drift
docker run --rm mogen-object-worker:dev python -m pytest /opt/object_generation/tests -q # 35 passed, 1 skipped
docker run --rm mogen-scene-worker:dev python -m pytest /opt/scene_reconstruction/tests -q # 75 passed, 1 skipped
docker run --rm mogen-scene-worker:dev python -m scene_reconstruction.standalone --verify-tools # COLMAP 4.2.1 + OpenMVS 2.4.0
docker run --rm mogen-frontend:dev npm run lint       # clean
docker run --rm mogen-frontend:dev npm run typecheck  # clean
docker run --rm mogen-frontend:dev npm run format:check # clean
docker run --rm mogen-frontend:dev npm run test:run   # 130 passed
docker run --rm mogen-frontend:dev npm run build      # succeeds
```

The opt-in real-model test is separate and needs the GPU plus the populated cache:

```bash
docker run --rm --gpus all -v mogen_triposr_model_cache:/models \
  -v "${PWD}/ml:/work/ml" -w /work/ml/object_generation \
  -e PYTHONPATH=/work/ml:/opt/triposr:/opt -e RUN_REAL_MODEL_TESTS=1 \
  mogen-object-worker:dev python -m pytest -m real_model -q   # 1 passed
```

The opt-in real scene reconstruction (the mandatory Phase 6 proof) needs the
sample photographs mounted at `/data/sceaux`:

```bash
docker run --rm --gpus all -v "${PWD}/.proof/sceaux:/data/sceaux:ro" -v "${PWD}/.proof:/proof" \
  mogen-scene-worker:dev python -m scene_reconstruction.standalone \
  --images /data/sceaux --work-dir /proof/scene-check --output /proof/scene-check.glb \
  --max-image-size 1200 --threads 8   # 11/11 registered, ~3-4 min on the reference GPU
```

If a check fails, fix the baseline before starting new work.

On Windows PowerShell, `curl` resolves to `curl.exe`: use `NUL` instead of `/dev/null`, and `${PWD}` for the working directory in `-v` mounts.

Current suite breakdown: 509 backend cases = 332 database/API integration cases under `tests/db` (they create their own scratch databases), 169 unit cases and 8 API-shell cases. Phase 8 added 18 cases: superseded-result cleanup 2, reliability regressions 3 (database failure during result registration, interrupted worker recovered and retried, project deletion during processing), scene-workspace retention 9, dispatcher crash-after-publish 1, cross-session CSRF binding 1, workspace-retention Celery schedule 1 and retention settings 1. Phase 6 added 10 cases: scene generation/task integration 3 and scene settings 7.

ML suites: **35** object-generation unit cases plus the opt-in real TripoSR test, and **75** scene-reconstruction cases plus one skipped opt-in real-reconstruction test in `ml/scene_reconstruction/tests`. The scene tests cover dataset validation, duplicate/format/dimension rejection, COLMAP and OpenMVS command construction, COLMAP database statistics and pair-id decoding, sparse-model inspection/selection, GLB validation, OBJ→GLB repack, process timeouts/cancellation, preflight (including the no-log-in-CWD probe), checkpoint reuse and the real toolchain check.

Frontend suite: **130** cases across 22 files (Vitest + React Testing Library). Phase 7 added the unified viewer module and the result page: 35 viewer cases (bounds, cleanup, loader, toolbar, viewer states, information panel and result page) plus a real triangle GLB fixture parsed with the same `GLTFLoader`; `ProjectDetailsPage` and `GenerationPanel` gained viewer-navigation assertions. The baseline 94 cases are unchanged. Run it with `docker run --rm mogen-frontend:dev npm run test:run` after rebuilding the image, or mount only `frontend/src` for iteration (Section 6).

Phase 7 browser verification is an out-of-tree proof (`.proof/viewer-tools/`, gitignored) using Playwright Core with the installed Edge: it logs in through the API, opens `/projects/{id}/result`, checks the canvas and model statistics, drags/zooms/resets/fits, toggles grid/background, downloads the GLB and compares its SHA-256 with the stored file. Object: 1.86 s to loaded, 45.6 fps, 23 039 vertices / 45 983 triangles, vertex colours. Medium scene: 1.82 s, 74.3 fps, 16 539 vertices / 28 991 triangles, one texture. Large scene: 2.43 s, 16.0 fps, 202 493 vertices / 297 813 triangles, one embedded texture. Headless Edge uses SwiftShader software WebGL, so the frame rates are software-renderer floors. The invalid-GLB error state and retry were verified in the same browser. Full evidence: [`reviews/phase7_closeout.md`](reviews/phase7_closeout.md).

---

## 6. Environment and tooling traps

These cost time in previous sessions. They are not obvious from the code.

**Sandbox and permissions.** Follow the runtime context of the session. With file policy `danger-full-access` and approvals disabled, run Docker commands directly. Under `workspace-write`, the Docker CLI can fail with "Access is denied" on `dockerDesktopLinuxEngine` because named-pipe access is blocked by the harness; that is a sandbox restriction, not a stopped engine (check for running `Docker Desktop` processes first). If approval prompts are enabled, retry the exact command with the narrowest wider mode; if they are disabled, the session needs full access before it can run the stack. Never request escalation when the session says approvals are disabled.

**No bind mounts in Compose services.** The services copy source into images; after changing backend or frontend code you must rebuild (`docker compose up -d --build api` or `--build frontend`). Lint, test and autogenerate commands may mount source into a one-off container with `docker run -v` or `docker compose run -v`, as shown below.

**Ruff fixes do not persist.** `docker compose run api ruff check --fix .` edits the container copy. To apply fixes, mount the source:

```bash
docker run --rm -v "${PWD}/backend:/app" -w /app mogen-api:dev ruff check --fix .
docker run --rm -v "${PWD}/backend:/app" -w /app mogen-api:dev ruff format .
```

**Windows quoting.** PowerShell strips double quotes when passing arguments to native programs. For anything non-trivial (`node -e`, shell loops), write a temporary script file and mount it into the container instead of inlining it.

**The PowerShell tool here is Windows PowerShell 5.1, not pwsh 7.** `-SkipHttpErrorCheck` and `[Microsoft.PowerShell.Commands.WebRequestSession]` do not exist, and `Invoke-WebRequest` fails in non-interactive mode. Drive HTTP smoke tests with `curl.exe`: write JSON bodies to temp files with `Set-Content`, use `-c`/`-b` for the cookie jar, and `-F "file=@..."` for multipart. Parenthesise a path before calling `-replace` on it (`(Join-Path $tmp 'x.json') -replace '\\','/'`), because PowerShell binds `-replace` to `Join-Path` otherwise.

**pytest's final summary line can vanish through a pipe.** When the pass count matters, redirect the whole run to a file (`... > "$env:TEMP\run.log" 2>&1`) and read the tail; `Tee-Object` or `Select-Object -Last N` sometimes drops the final "N passed" line. Exit code 0 plus the file is the reliable evidence.

**Never rewrite this handoff with PowerShell text cmdlets.** `Get-Content -Raw | Set-Content` decodes UTF-8 as the system ANSI code page (CP1251 on this host) and double-encodes em dashes, arrows and ellipses into mojibake such as `вЂ”`. Use the edit/write tools, which are UTF-8 clean. If mojibake appears, repair it with the CP1251→UTF-8 round trip and re-check the non-ASCII character set.

**Smoke tests that need a real image.** Generate a JPEG/PNG inside the container with Pillow (`python -c "from PIL import Image; Image.new(...).save('/tmp/probe.jpg','JPEG')"`), copy it out with `docker cp mogen-api-1:/tmp/probe.jpg <host path>`, then upload it with `curl.exe -F`. Remove smoke rows and files afterwards: delete the cleanup job, then the project (cascades images/tasks), sessions and user, and `rm -rf /data/projects/<id>`.

**psql with `-t -A -c` prints the command tag.** `psql -t -A -c "insert ... returning id"` returns the identifier *and* a trailing `INSERT 0 1`, so capturing it as a variable produces a broken UUID. Generate identifiers in PowerShell (`[guid]::NewGuid()`), insert the literal value, or follow the insert with a separate `select`. Deleting with an empty identifier also warns that it is not a UUID — always verify the resolved value before a destructive `rm -rf /data/projects/<id>`.

**Celery logging and stdout.** Celery hijacks the root logger and redirects child-process stdout by default; the worker disables both (`worker_hijack_root_logger=False`, `worker_redirect_stdouts=False`) so `configure_logging` at import owns the JSON formatter and application logs from task processes are visible. Beat keeps its schedule file in `/tmp` (`--schedule=/tmp/celerybeat-schedule`) because `/app` is not guaranteed writable, and development runs `--beat` inside the worker container; production separates beat.

**Worker healthcheck needs a shell.** The `cleanup-worker` healthcheck pings `celery@$HOSTNAME`; Compose's exec form does not expand variables, so the test must use `CMD-SHELL` with `$$HOSTNAME`. A running Celery process is not enough: the ping proves the worker answers on its queue. `object-worker` and `scene-worker` use the same pattern on their own queues.

**The dispatcher and recovery use heartbeat files, not pings.** They are plain Python processes, so their healthcheck reads `/tmp/outbox-dispatcher.heartbeat` or `/tmp/task-recovery.heartbeat` and fails when the file is older than 120 s. The file is rewritten after every loop cycle, including a failed cycle, so a process that is alive but stuck is reported unhealthy.

**Both generation workers now run real pipelines.** The object worker registers `run_triposr_pipeline` and loads the real TripoSR model at startup. The scene worker registers `run_colmap_pipeline`, verifies COLMAP/OpenMVS at startup and logs `scene_pipeline_ready`; if an image is broken it registers an honest `EXTERNAL_TOOL_UNAVAILABLE` pipeline instead of pretending to reconstruct.

**The scene image is large and slow to build.** It is based on the official COLMAP CUDA image, builds OpenCV 4.12 and OpenMVS 2.4.0 from source and installs CGAL 6.0.1; the first build takes roughly 30–45 minutes and produces an ~11 GB image. Subsequent builds reuse the cached layers (only the COPY/verification layers rerun) and take seconds to a few minutes.

**OpenMVS tool help exits with code 1.** `InterfaceCOLMAP --help` and the other OpenMVS apps print their help and return `EXIT_FAILURE` when no input file is supplied. The image build check and `preflight.verify_toolchain` therefore accept exit codes 0 and 1 when output was produced; treating 1 as failure rejects a working toolchain.

**COLMAP's `pair_id` encodes image ids.** Current COLMAP has no `image_id1`/`image_id2` columns in `two_view_geometries`; `pair_id = image_id1 * 2147483647 + image_id2`. `read_database_stats` decodes it. An earlier query silently returned `verified_pairs=0` and the pipeline failed with `NO_VALID_MATCHES`; if matching statistics look empty, inspect the schema before invalidating the dataset.

**OpenMVS mesh stages write PLY, not MVS.** `RefineMesh` and `TextureMesh` write `scene_dense_mesh_refine.ply` and `scene_dense_mesh_refine_texture.ply` (plus the texture atlas), ignoring a `.mvs` extension in `-o`. The pipeline treats the PLY as the stage artifact and attaches it to the dense scene with `TransformScene -m` at export time.

**Scene work dirs live on `/data`.** `/data/work/scene/{task_id}` is on the shared volume so a restarted worker can reuse validated checkpoints. A successful task removes its workspace; a failed task keeps it for diagnostics (no retention job yet). Do not place these under `/tmp`: container restarts would lose the checkpoints and the writable layer would grow.

**The development database and `/data/projects` are not empty.** The schema is migrated, and there is pre-existing development data plus a user-created project that the live Phase 5 stack generated successfully during verification. Phase 6 also left a historical SCENE task `379073b3-80d5-4b1d-b571-2ea689cc39ff` (its project was soft-deleted) that failed at `SPARSE_RECONSTRUCTION` on four low-texture PNGs; its diagnostics workspace `/data/work/scene/379073b3-80d5-4b1d-b571-2ea689cc39ff` is intentionally retained. Do not reset the database or delete files in bulk; remove only the rows and directories whose identifiers you just created and verified.

**`session_scope` is a context manager.** `app/db/session.py` exposes it as `@contextmanager`; `get_db` uses `with session_scope(...) as session: yield session` and the worker uses the same form. Do not restore the old bare generator (`yield from`): it cannot be used with `with`.

**Line endings.** The repository uses CRLF in `docs/`, root configs and `.gitattributes`-free defaults; `core.autocrlf=true`, so git warns "LF will be replaced by CRLF" on add. That warning is harmless. Backend and frontend sources are LF; the frontend tree had acquired mixed CRLF on the host during Phase 5 and was normalised back to LF so `prettier --check` matches the image. Do not reintroduce CRLF into `frontend/src`.

**Model cache and offline mode.** `triposr_model_cache` is mounted at `/models`; `model-init` is the only service allowed to download. The worker runs with `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`, so a missing DINO config or a bad cache ref turns into `MODEL_LOAD_FAILED`, not a silent download. `huggingface_hub` reads `models--facebook--dino-vitb16/refs/main` verbatim; it must contain the 40-character revision with **no trailing newline**. The initial initializer wrote a newline and broke offline model loading; this is fixed in `download_models.py`.

**Object-worker import path.** The pipeline package is `/opt/object_generation`, so the image and Compose set `PYTHONPATH=/app:/opt/triposr:/opt` (the parent `/opt`, not the package directory). The first image build used the package directory and `import object_generation` failed; use the parent path.

**The object-worker image is large and slow to build.** It carries CUDA PyTorch and compiles `torchmcubes` for SM 86; the first build can take 45–60 minutes and needs a lot of disk. Subsequent builds reuse layers. The worker loads the model at startup (about 4–5 minutes in the container), so its healthcheck has a 600 s start period. Do not lower it without measuring.

**Dependencies are pinned deliberately.** Do not run `npm install <pkg>@latest` or loosen requirements without recording the change. TypeScript is pinned at **5.9.3**, not the current 7.0.2, because `typescript-eslint@8.72.1` declares `typescript <6.1.0`. Phase 3 added the approved form stack as exact pins: `react-hook-form@7.91.0` and `zod@4.6.7`. `@hookform/resolvers` was deliberately not added; `frontend/src/shared/lib/zodResolver.ts` adapts Zod to React Hook Form.

**Frontend iteration without rebuilding.** The frontend image contains `node_modules` and the configs; mount only the sources to test edits quickly:

```powershell
docker run --rm -v "${PWD}\frontend\src:/app/src" -w /app mogen-frontend:dev npm run test:run
docker run --rm -v "${PWD}\frontend\src:/app/src" -w /app mogen-frontend:dev npm run typecheck
docker run --rm -v "${PWD}\frontend\src:/app/src" -w /app mogen-frontend:dev npm run lint
```

Rebuild (`docker compose build frontend`) and recreate the service before verifying the running application; the dev server serves the image copy, not the host tree.

**Database tests need the Compose stack.** `backend/tests/db/` is marked `integration` and creates the scratch databases `mogen_test` and `mogen_test_migration` on the `db` service, then drops them. Run the suite through Compose (`docker compose run --rm api pytest`), never with a host interpreter; a bare `pytest` outside the Compose network cannot resolve the `db` host name.

**Auth secrets and cookies.** `CSRF_SECRET` has a development default. With `APP_ENV=production` the application refuses to start unless it is replaced (32+ characters) and `SESSION_COOKIE_SECURE=true`. CSRF tokens are deterministic HMAC values bound to a session, so rotation happens when a new session is created, never within one session.

**Docker BuildKit cache.** A rebuild can fail with `failed to prepare extraction snapshot ... parent snapshot ... does not exist`. Retrying the identical build has succeeded; if it persists, prune the builder cache (`docker builder prune`) and rebuild. This is a host cache glitch, not a code failure.

**Disk.** The Docker data root is on `C:`. The scene-worker image is ~11 GB and the object-worker CUDA layers are large; `C:` had ~55 GB free at the start of Phase 6 and ~46 GB after the builds, so the stack plus caches fit, but a full rebuild of both ML images can consume most of it. Prune stale builders before a large rebuild and keep an eye on free space.

**Python on the host is 3.14.6 and is irrelevant.** The backend runs Python 3.11 inside the image, the object worker Python 3.12.3 (the PyTorch image runtime), and the scene worker Python 3.12 (Ubuntu 24.04 in `/opt/venv`). Never create a virtual environment with the host interpreter.

**`docker compose config` prunes unused named volumes.** `triposr_model_cache` is declared; it appears in the resolved output once the object-worker/model-init services mount it. This is correct Compose behaviour, not a mistake. Because the cache volume was created manually during verification, Compose prints a "volume … was not created by Docker Compose" warning; a fresh `up` creates it normally.

**Known warning.** FastAPI's `TestClient` emits `StarletteDeprecationWarning` suggesting `httpx2`. Harmless; revisit when dependencies are next re-pinned.

**The viewer canvas sizes asynchronously.** React Three Fiber measures its container with `ResizeObserver`; immediately after `data-viewer-state="loaded"` the browser canvas may still be the 300×150 default for a frame or two. Wait for a non-default canvas width before screenshotting or measuring in a browser proof. The viewer exposes `data-viewer-state` and `data-model-meshes/vertices/triangles/materials/textures/textured/vertex-colors` for exactly this kind of check; do not add a global debug object.

**Headless browser proof and origins.** The allowed CSRF origin is `http://localhost:5173`, not `http://127.0.0.1:5173`; API-driven proof scripts must use the former or registration/login is rejected with `CSRF_VALIDATION_FAILED`. Headless Edge needs `--enable-unsafe-swiftshader --use-angle=swiftshader` to expose WebGL 2 in this environment. Drive Edge through Playwright Core (`.proof/viewer-tools/`, gitignored); do not add a browser dependency to `frontend/package.json` for it.

**Host GPU contention can stall new OBJECT tasks.** During Phase 7 an unrelated host workload pinned the GPU at 100 % (with no CUDA compute process visible for the worker); a new OBJECT task stayed in `MODEL_GENERATION` while its heartbeat froze. The supported recovery is to delete the test project through the API, restart `object-worker`, and wait for `triposr_model_loaded` / `object_generation_pipeline_ready` again (4–5 minutes). Do not wait indefinitely or submit more object tasks. This is a host condition; the Phase 7 viewer proof used byte-identical copies of retained results rather than new inference for this reason. Phase 8 confirmed the condition (a game process was holding ~5 GB and ~39 % of the GPU) and therefore did not run a new generation either.

**Terminal task transitions must refresh the row.** `TaskExecutionService` used `Session.get`/`select` after `claim` had already loaded the task, so a cancellation request written by the API during the pipeline was masked by the SQLAlchemy identity map. `TaskRepository.get_for_update` now sets `populate_existing` and `get_refreshed` exists for the non-locking terminal paths. Any new transition that inspects `cancel_requested_at` must use one of them; otherwise a project deleted mid-generation can still register a result.

**Superseded result files are deleted asynchronously.** A successful regeneration marks the old result `is_current=false` and queues a `FILE` cleanup job plus a `cleanup.requested` event in the same transaction; the cleanup worker deletes the file, usually within a few seconds. Do not expect the file to disappear inside the registration transaction, and do not delete it inline: the job is the retry mechanism. A failed regeneration queues nothing.

**Scene workspaces have a retention policy.** The cleanup worker runs `cleanup_scene_workspaces_task` hourly (beat) and queues terminal `/data/work/scene/{task_id}` directories older than `SCENE_WORKSPACE_RETENTION_HOURS` (default 168; 0 disables) as `DIRECTORY` jobs. It only considers UUID-named direct children and never touches `PENDING`/`PROCESSING` tasks. The retained Phase 6 workspace `379073b3-…` is untouched now but becomes eligible after the default window; raise or disable retention if it must be kept forever. The sweep logs `workspace_usage` (bytes and counts) for temporary-storage monitoring.

**OpenMVS writes logs next to its working directory.** `InterfaceCOLMAP`, `DensifyPointCloud`, `ReconstructMesh`, `RefineMesh`, `TextureMesh` and `TransformScene` create `<tool>-<timestamp>.log` in the CWD at every start, including `--help`. `verify_toolchain` therefore runs probes in a throwaway temp directory; do not pass the process CWD again or each scene-worker restart will leave seven files in `/app`.

**The Phase 8 image rebuild can re-download shared CUDA layers.** `docker compose up -d --build` pulled several GB of CUDA base layers for the object and scene images even though the images existed, because BuildKit's layer cache did not contain them. It is slow but not a project failure; a later build reuses the layers. Budget 20–40 minutes if the builder cache was pruned.

**Git state.** Branch `main`, zero commits; the Phase 2 files are staged and all later phase files are untracked. Phase 6 added `ml/scene_reconstruction/` (Dockerfile, requirements, config, dataset, runners, selector, mesh processor, exporter, validator, pipeline, standalone, tests, viewer validator), `backend/app/tasks/scene_pipeline.py`, `backend/tests/db/test_scene_generation.py`, `backend/tests/unit/test_scene_settings.py`, `docs/reviews/phase6_closeout.md`, `ml/object_generation/viewer/validate_glb.mjs`, the `.proof/` proof scripts (gitignored) and modified `backend/app/core/config.py`, `backend/app/services/result_service.py`, `backend/app/tasks/scene_pipeline.py`, `compose.yaml`, `compose.gpu.yaml`, `.env.example`, `.dockerignore`, `docs/HANDOFF.md`, `docs/NEXT_SESSION.md` and the frontend generation panel, labels and tests. The increment 2a–2h files (`app/db/models/`, `app/repositories/`, `app/services/`, `app/tasks/`, `app/storage/`, `app/schemas/`, the auth, project and image endpoints, `app/api/dependencies.py`, the initial migration, `tests/db/`, `tests/unit/test_repository_dependencies.py`, `tests/unit/test_security.py`, `tests/unit/test_project_validation.py`, `tests/unit/test_image_validation.py`, `tests/unit/test_storage.py`, `tests/unit/test_celery_config.py`) are untracked and not yet in the index. The Phase 2 close-out added `docs/reviews/phase2_closeout.md` (untracked) and modified the already staged `backend/app/main.py` and `backend/tests/api/test_errors.py`. Phase 3 added the frontend modules under `frontend/src/{app/layout,app/providers,app/router,features,pages,shared,test}` (untracked) and modified `frontend/package.json`, `frontend/package-lock.json`, `.env.example`, `compose.yaml` and the frontend README. Phase 4 added the new backend modules under `backend/app/{services,tasks,schemas,api/v1/endpoints}`, the new tests listed in Section 3, `docs/reviews/phase4_closeout.md` (all untracked) and modified `backend/app/core/config.py`, `backend/app/api/dependencies.py`, `backend/app/api/v1/router.py`, `backend/app/services/project_service.py`, `backend/app/services/image_service.py`, `backend/app/tasks/celery_app.py`, `backend/app/repositories/{outbox_repository,task_repository}.py`, `backend/tests/unit/test_celery_config.py`, `backend/tests/db/conftest.py`, `.env.example` and `compose.yaml`. Phase 5 added `ml/object_generation/` (Dockerfile, requirements, pipeline, tests, testdata, viewer), `backend/app/tasks/object_pipeline.py`, `backend/app/services/result_service.py`, `backend/app/schemas/result.py`, `backend/app/api/v1/endpoints/results.py`, `backend/tests/db/test_result_{api,persistence}.py`, `backend/tests/unit/test_result_service.py`, `compose.gpu.yaml`, `.dockerignore`, `docs/reviews/phase5_closeout.md` and the frontend `features/generation/` modules (all untracked), and modified `backend/app/tasks/generation_tasks.py`, `backend/app/services/task_execution_service.py`, `backend/app/api/dependencies.py`, `backend/app/api/v1/router.py`, `backend/app/core/config.py`, `backend/app/repositories/task_repository.py`, `.env.example`, `compose.yaml`, the frontend shared API/types/labels/config and `frontend/src/pages/ProjectDetailsPage/`. Do not assume a clean history; `git diff` against the index shows working-tree changes only. Do not stage, commit or rewrite history unless the user asks.

**Phase 7 git state.** Phase 7 added everything under `frontend/src/features/model-viewer/` and `frontend/src/pages/ModelViewerPage/`, `docs/reviews/phase7_closeout.md`, the `.proof/` browser-proof scripts (gitignored) and modified `frontend/package.json`, `frontend/package-lock.json`, `frontend/src/app/router/AppRouter.tsx`, `frontend/src/pages/ProjectDetailsPage/ProjectDetailsPage.tsx` (and its test), `frontend/src/features/generation/components/GenerationPanel.tsx` (and its test), `frontend/src/features/projects/components/ProjectCard.tsx`, `frontend/src/shared/api/queryKeys.ts`, `docs/HANDOFF.md` and `docs/NEXT_SESSION.md`. All Phase 3–7 files remain untracked; the Phase 2 files are staged.

**Phase 8 git state.** Phase 8 added `backend/app/services/workspace_retention_service.py`, `backend/tests/db/test_workspace_retention.py`, `backend/tests/db/test_reliability_regressions.py`, `docs/operations/backup_restore.md`, `docs/operations/verify_current_results.py`, `docs/reviews/phase8_closeout.md`, the `.proof/phase8/` drill and measurement scripts (gitignored, plus `.proof/phase8.jpg` and `.proof/phase8-big.jpg`) and modified `backend/app/services/task_execution_service.py`, `backend/app/repositories/task_repository.py`, `backend/app/tasks/cleanup_tasks.py`, `backend/app/tasks/celery_app.py`, `backend/app/core/config.py`, `backend/app/core/logging.py`, `backend/tests/db/conftest.py`, `backend/tests/db/test_result_persistence.py`, `backend/tests/db/test_outbox_dispatcher.py`, `backend/tests/db/test_auth_api.py`, `backend/tests/unit/test_celery_config.py`, `backend/tests/unit/test_config.py`, `ml/scene_reconstruction/preflight.py`, `ml/scene_reconstruction/tests/test_preflight.py`, `compose.yaml`, `.env.example`, `.dockerignore`, `README.md`, `docs/HANDOFF.md` and `docs/NEXT_SESSION.md`. It also removed 60 generated OpenMVS log files from `ml/scene_reconstruction/` and 54 test-created orphan storage directories from `/data/projects`. No migration was added (no schema change). All Phase 3–8 files remain untracked; the Phase 2 files are staged.

---

## 7. Design decisions already made

Do not re-litigate these without a reason.

| Decision | Where it lives |
|---|---|
| Pinned dependencies, licenses, hardware profile | [`architecture/phase0_decisions.md`](architecture/phase0_decisions.md) |
| Celery broker uses Redis DB 1; direct Redis access uses DB 0 | `.env.example`, `08_infrastructure.md` Section 9.2 |
| API readiness ignores Redis, so a broker outage keeps project management available | `backend/app/api/health.py`, `04_backend_specification.md` Section 16.3 |
| Errors use one envelope: `{error: {code, message, details, request_id}}` | `backend/app/core/errors.py`, `04_backend_specification.md` Section 15.2 |
| Logs are single-line JSON with `request_id`, credentials redacted | `backend/app/core/logging.py` |
| `cors_origins` is a string with an `allowed_origins` property, because pydantic-settings JSON-parses complex types from environment variables | `backend/app/core/config.py` |
| Frontend calls the API through a same-origin dev proxy instead of absolute URLs and CORS | `frontend/vite.config.ts` |
| Alembic reads `DATABASE_URL` from the application settings, not from `alembic.ini` | `backend/alembic/env.py` |
| Passwords use Argon2id; only the SHA-256 hash of the session token is stored; emails are stored lowercase | `backend/app/core/security.py`, `05` Section 5.2 and 6 |
| CSRF is a stateless HMAC bound to the session identifier and creation time; no CSRF state is stored in PostgreSQL | `backend/app/core/security.py`, `api_contracts.md` Section 3.3 |
| Auth cookies use `SameSite=Lax`, `Path=/`, HttpOnly for `session` only, and `Secure` in production | `backend/app/api/v1/endpoints/auth.py` |
| Project listing `limit` is clamped to `MAX_PAGE_SIZE` (not rejected), so the response echoes the effective limit; `limit < 1` and `offset < 0` are 422 | `backend/app/services/project_service.py`, `backend/app/core/config.py` |
| Project `sort` accepts only `created_at_desc` and `created_at_asc`; the contract does not enumerate values, so unknown values are rejected with 422 instead of being silently ignored | `backend/app/schemas/project.py` |
| Ownership is derived from the authenticated user; another user's, soft-deleted and missing projects all return `404 PROJECT_NOT_FOUND`, never 403 | `backend/app/services/project_service.py`, `api_contracts.md` Section 11 |
| Project deletion is one transaction: row lock, `deleted_at`, PENDING→`CANCELLED`, `cancel_requested_at` on PROCESSING, one `DIRECTORY` cleanup job; a repeat request returns 404 | `backend/app/services/project_service.py`, `05` Section 12.4 |
| Project name policy (trim, non-empty, 150 characters) lives in the service and returns `PROJECT_NAME_INVALID`; the schema only imposes a 1024-character input guard | `backend/app/services/project_service.py`, `backend/app/schemas/project.py` |
| Storage keys are relative posix paths, server-generated only; `..`, `.`, absolute keys, backslashes, colons, NUL bytes, repeated separators and keys over 512 characters are rejected, and resolution re-checks containment after following symlinks | `backend/app/storage/keys.py`, `08_infrastructure.md` Section 17.4 |
| `LocalStorage` writes atomically (temporary file in the destination directory, `fsync`, then rename); deleting an absent target succeeds, matching the cleanup contract | `backend/app/storage/local.py`, `05` Section 12.3 |
| Filesystem failures become `503 STORAGE_UNAVAILABLE`; a missing object stays `FileNotFoundError` so callers can answer 404 | `backend/app/storage/local.py`, `api_contracts.md` Section 12.3 |
| `storage_root` must be an absolute path, so API and worker containers cannot resolve it against different working directories | `backend/app/core/config.py` |
| Images are pinned by digest, base images included | `compose.yaml`, Dockerfiles |
| Image uploads trust only the decoded content: extension, declared media type and Pillow's actual format must agree, and the verified MIME type is stored rather than the client declaration | `backend/app/services/image_service.py`, `05` Section 8.2 |
| Upload status transitions (`UPLOADING` → `CREATED`) happen inside one transaction under a project row lock, so a committed project is never left `UPLOADING` and failures leave the previous status untouched | `backend/app/services/image_service.py`, `04` Section 10.6 |
| A failed metadata write deletes the already stored file; a failed cleanup is logged and never masks the original error | `backend/app/services/image_service.py`, `05` Section 16.3 |
| Object projects accept exactly one source image; scene projects are bounded by `MIN_SCENE_IMAGES`/`MAX_SCENE_IMAGES` at generation time and `MAX_SCENE_IMAGES` at upload time | `backend/app/services/image_service.py`, `04` Sections 10.4–10.5 |
| Longest accepted image edge is configurable (`MAX_IMAGE_DIMENSION`, default 8192 px); oversized or decompression-bomb images return 400 `IMAGE_DIMENSIONS_EXCEEDED` | `backend/app/core/config.py`, `backend/app/services/image_service.py` |
| Image content is streamed in 64 KiB chunks with the verified MIME type, `Content-Disposition: inline` (ASCII fallback plus RFC 6266 `filename*`), `Cache-Control: private` and `nosniff`; the storage key and resolved path never reach the client | `backend/app/api/v1/endpoints/images.py`, `backend/app/services/image_service.py`, `api_contracts.md` 8.3 |
| A metadata row whose stored object has disappeared returns 404 `IMAGE_NOT_FOUND` and logs `image_content_missing`; a retry cannot fix a missing file, so a 5xx would mislead | `backend/app/services/image_service.py`, `api_contracts.md` 8.3 |
| Storage retrieval failures keep the storage layer's 503 `STORAGE_UNAVAILABLE` even though 8.3 lists 500 for "storage retrieval failure": 10.2 (result download, the analogue) and the status table document 503 for an unavailable dependency, and 500 stays the unexpected-error path | `backend/app/api/v1/endpoints/images.py`, `backend/app/storage/local.py`, `api_contracts.md` 8.3, 10.2, 11 |
| Image deletion is one transaction under the project row lock: generation-history reference check, project-state check, `FILE` cleanup job, metadata removal; a `RESTRICT` foreign-key violation from a concurrent snapshot is translated to the same 409 instead of a 500 | `backend/app/services/image_service.py`, `05_database_specification.md` 8.5, `api_contracts.md` 8.4 |
| Deletion uses a new code `IMAGE_REFERENCED` for generation history and the existing `INVALID_PROJECT_STATE` for a `PENDING`/`PROCESSING` project; 12.3 explicitly allows subsystem-specific codes | `backend/app/services/image_service.py`, `api_contracts.md` 12.3 |
| Deleted image metadata disappears immediately (content 404s at once) while the file waits for the cleanup worker; surviving scene images keep their positions, so no renumbering happens | `backend/app/services/image_service.py`, `api_contracts.md` 8.4 |
| Generation history protects its inputs: `generation_task_images` references block deletion, checked in the repository and enforced again by the database `RESTRICT` foreign key | `backend/app/repositories/task_repository.py`, `05_database_specification.md` 8.5 |
| Files are never deleted inside an API request: project and image deletion record `storage_cleanup_jobs` rows and a dedicated `cleanup-worker` executes them from the `file_cleanup` Celery queue | `backend/app/services/cleanup_service.py`, `backend/app/tasks/`, `08_infrastructure.md` 3.7 |
| A cleanup attempt holds the job row lock (`FOR UPDATE ... SKIP LOCKED`) until it commits, so a crash rolls the claim back to `PENDING` instead of stranding the job in `PROCESSING`; deleting an absent target counts as success | `backend/app/services/cleanup_service.py`, `backend/app/repositories/cleanup_job_repository.py`, `05_database_specification.md` 12.3 |
| `attempts` increments on every attempt; a failure records `last_error` and returns the job to `PENDING` until `CLEANUP_MAX_ATTEMPTS`, then marks it `FAILED`; each job is attempted at most once per worker cycle | `backend/app/services/cleanup_service.py`, `backend/app/core/config.py` |
| Directory jobs wait while their project still has a `PENDING`/`PROCESSING` generation task; file jobs never wait because their image metadata is already gone and deletion is refused while a task is active | `backend/app/services/cleanup_service.py`, `08_infrastructure.md` 3.7, `data_flow.md` 14.4 |
| The Outbox Dispatcher publishes `cleanup.requested` and the cleanup worker processes the targeted `job_id` immediately; the Celery beat scan remains the recovery path for an undispatched job | `backend/app/tasks/cleanup_tasks.py`, `backend/app/services/outbox_service.py` |
| Celery is pinned at 5.7.0 (verified to resolve against `redis==8.1.0`), uses Redis DB 1 as broker, has no result backend and routes only to `file_cleanup` | `backend/requirements.txt`, `backend/app/tasks/celery_app.py`, `08_infrastructure.md` 7.2–7.6 |
| The worker owns the JSON log configuration; Celery's root-logger hijack and stdout redirection are disabled so task-process logs keep the structured format | `backend/app/tasks/celery_app.py`, `backend/app/core/logging.py` |
| `session_scope` is a `@contextmanager` so request dependencies and the worker share one session lifecycle helper | `backend/app/db/session.py`, `backend/app/api/dependencies.py` |
| The Celery topology is three explicit queues (`object_generation`, `scene_reconstruction`, `file_cleanup`) with per-task routes and per-pipeline time limits; visibility timeout exceeds the longest task, there is no result backend, and the Celery task ID equals `GenerationTask.id` | `backend/app/tasks/celery_app.py`, `backend/app/tasks/outbox_publisher.py`, `data_flow.md` 7.1–7.2 |
| Generation creation resolves the idempotency key before the active-task and state checks, so a repeat while the task is already running still returns the existing task; task, ordered snapshot, project `PENDING` and the outbox event commit in one transaction | `backend/app/services/generation_service.py`, `05` 9.6/16.4, `api_contracts.md` 9.2 |
| The dispatcher claims with `FOR UPDATE SKIP LOCKED`, commits the claim, publishes to Redis and only then marks `PUBLISHED`; transient errors return to `PENDING` with full-jitter exponential backoff, permanent contract errors and an exhausted budget become `FAILED`, and expired `PROCESSING` locks are released first | `backend/app/services/outbox_service.py`, `backend/app/repositories/outbox_repository.py`, `05` 13.4–13.6 |
| A task is recoverable only when its lease expired and its heartbeat is older than `TASK_STALE_THRESHOLD_SECONDS`; recovery requeues through a new outbox event with `attempt_count` incremented, fails at the budget, and cancels rather than requeues a cancellation/deleted project | `backend/app/services/task_recovery_service.py`, `05` 9.11/13.6, `data_flow.md` 12.3 |
| The object worker registers the real TripoSR pipeline through `register_pipeline`; the scene worker registers the real COLMAP/OpenMVS pipeline the same way | `backend/app/tasks/object_pipeline.py`, `backend/app/tasks/scene_pipeline.py`, `backend/app/tasks/generation_tasks.py` |
| The object worker is a dedicated `mogen-object-worker:dev` image (PyTorch 2.14.1/CUDA 12.6, TripoSR, torchmcubes, rembg); the API image stays CUDA-free | `ml/object_generation/Dockerfile`, `compose.yaml` |
| Model weights, the DINO config and rembg weights live in the persistent `triposr_model_cache` volume, populated once by `model-init`; the worker is offline and verifies the checkpoint SHA-256 before accepting a task | `ml/object_generation/download_models.py`, `compose.yaml` |
| Result persistence is atomic with task completion: storage write first, then `complete_with_result` locks the task, clears the old current result, inserts the new current result and completes task/project in one transaction; failures and cancellations preserve the old result | `backend/app/services/task_execution_service.py`, `backend/app/tasks/generation_tasks.py` |
| The result read/download API serves only the current validated result, with ownership checks, streamed `model/gltf-binary`, `private, no-store`, `nosniff` and a safe RFC 5987 filename; no storage key or path is exposed | `backend/app/services/result_service.py`, `backend/app/api/v1/endpoints/results.py` |
| GLB validation is an independent binary parser (container, JSON, accessors, finite positions, index bounds, positive bounds, `COLOR_0`), not a trust-the-exporter check | `ml/object_generation/validator.py`, `06_object_generation.md` Section 12 |
| The scene worker is a dedicated `mogen-scene-worker:dev` image built on the pinned official COLMAP 4.2.1 image with OpenMVS 2.4.0 compiled unmodified from commit `58117204…`; the API and object worker images stay free of COLMAP/OpenMVS | `ml/scene_reconstruction/Dockerfile`, `compose.yaml`, `08_infrastructure.md` Sections 3.6 and 4.4 |
| OpenCV 4.12.0 and CGAL 6.0.1 are added as OpenMVS build dependencies: OpenMVS 2.4.0 needs `cv::IMWRITE_JPEGXL_QUALITY` (OpenCV 4.11+) and CGAL 6 headers (`CGAL/AABB_traits_3.h`); the OpenMVS source remains unmodified | `ml/scene_reconstruction/Dockerfile`, `docs/reviews/phase6_closeout.md` Section 4 |
| The worker verifies every external executable at startup (`colmap`, `InterfaceCOLMAP`, `DensifyPointCloud`, `ReconstructMesh`, `RefineMesh`, `TextureMesh`, `TransformScene`) and registers an honest `EXTERNAL_TOOL_UNAVAILABLE` pipeline if the toolchain is broken | `backend/app/tasks/scene_pipeline.py`, `ml/scene_reconstruction/preflight.py`, SCENE-AC-01 |
| Scene input is copied unchanged into `/data/work/scene/{task_id}/images`; format, decodability, dimensions, count and SHA-256 duplicates are validated before COLMAP | `ml/scene_reconstruction/dataset.py`, `07_scene_reconstruction.md` Sections 4.5-4.8 |
| Every sparse model is converted to TXT, measured and ranked; selection uses registered images, registration ratio, point count and reprojection error, never directory order, and records component diagnostics | `ml/scene_reconstruction/reconstruction_selector.py`, `07` Sections 8.5-8.7 |
| Mesh refinement and texturing write PLY meshes (not `.mvs`); `TransformScene -m` attaches the refined/textured mesh to the dense scene at export | `ml/scene_reconstruction/openmvs_runner.py`, `ml/scene_reconstruction/pipeline.py` |
| OpenMVS's GLB is not self-contained (sidecar texture, `KHR_materials_unlit`); the exporter repacks the OBJ/MTL/PNG set into one GLB with embedded buffers and images and validates UVs/materials/textures independently | `ml/scene_reconstruction/exporter.py`, `ml/scene_reconstruction/validator.py`, `07` Section 11.2 |
| Scene working directories live on the shared `/data` volume so checkpoints survive a worker restart; completed stages are reused only after their outputs pass the same validators | `ml/scene_reconstruction/pipeline.py`, `07` Sections 13.5-13.6 |
| The scene result uses the existing transactional result path with `projects/{project_id}/results/{task_id}/scene.glb`; `result_storage_key` gained an optional filename so the object path is unchanged | `backend/app/services/result_service.py`, `backend/app/tasks/scene_pipeline.py` |
| Scene reconstruction is enabled in the existing generation panel; it shows only persisted scene stages and errors and does not invent progress percentages | `frontend/src/features/generation/`, `frontend/src/shared/lib/labels.ts`, roadmap 6.9 |
| GPU access is a `compose.gpu.yaml` override that forces `cuda:0` and reserves one device; the base compose file stays CPU-capable | `compose.yaml`, `compose.gpu.yaml`, `08_infrastructure.md` Section 6.4 |
| The generation UI enables only the existing details-page action and real status polling; the Three.js viewer and result-management UI remain Phase 7 | `frontend/src/features/generation/`, `frontend/src/pages/ProjectDetailsPage/` |
| Cleanup jobs emit `cleanup.requested` in the deletion transaction and the dispatcher wakes the cleanup worker immediately; the 15 s beat scan remains the recovery path for an undispatched job | `backend/app/services/project_service.py`, `backend/app/services/image_service.py`, `backend/app/services/outbox_events.py` |
| The API never imports Celery or a Redis client: generation writes PostgreSQL only, so it accepts requests during a Redis outage and the dispatcher delivers later | `backend/app/api/v1/endpoints/generation.py`, `backend/app/services/generation_service.py`, INF-AC-23/24 |
| The status endpoint reports only persisted data; `progress_percent` stays null and `stage` is never a terminal status, and `result_available` follows the current result independently of the latest task | `backend/app/api/v1/endpoints/generation.py`, `api_contracts.md` 9.3–9.4 |
| The object and scene workers each have a dedicated image (`mogen-object-worker:dev`, `mogen-scene-worker:dev`); the cleanup worker reuses `mogen-api:dev` because it has no ML dependencies | `compose.yaml`, `08_infrastructure.md` 3.5–3.6 |
| The frontend UI is Russian, using the terminology in `02_ui_ux_specification.md` Section 11; dates and file sizes are formatted with `ru-RU` | `frontend/src/shared/lib/labels.ts`, `frontend/src/shared/lib/format.ts` |
| The CSRF token lives only in memory, is fetched after session initialisation/login/registration, and is attached by the Axios request interceptor to non-safe methods; it is never stored in `localStorage` or `sessionStorage` | `frontend/src/shared/api/client.ts`, `frontend/src/app/providers/AuthProvider.tsx` |
| API DTOs keep the backend snake_case shape; a mapping layer converts them to camelCase domain models before components see them | `frontend/src/shared/api/dto.ts`, `frontend/src/shared/api/mappers.ts` |
| Project creation and image upload are separate operations: the project is created first, images are validated locally and uploaded sequentially; partial failures preserve the project and successful images, and retry happens on the details page | `frontend/src/pages/CreateProjectPage/CreateProjectPage.tsx`, `frontend/src/pages/ProjectDetailsPage/ProjectDetailsPage.tsx` |
| Image previews use `URL.createObjectURL` and are revoked on removal, replacement, clear and unmount | `frontend/src/features/image-upload/hooks/useImageSelection.ts` |
| Generation controls are enabled on the details page; the panel starts/retries generation, polls real stages/errors and offers the authenticated GLB download, and never fabricates progress | `frontend/src/features/generation/`, `frontend/src/pages/ProjectDetailsPage/ProjectDetailsPage.tsx` |
| Client-side upload limits mirror the backend limits through `VITE_*` variables; the backend remains authoritative | `frontend/src/shared/config.ts`, `.env.example`, `compose.yaml` |
| The viewer uses React Three Fiber `9.8.2`, Drei `10.7.9` and Three.js `0.187.0`, all pinned exactly; R3F's React `>=19 <19.4` peer accepts the pinned React 19.3.1 | `frontend/package.json`, `frontend/package-lock.json` |
| GLB bytes are fetched through the shared authenticated Axios client, exposed through a temporary object URL, parsed by `GLTFLoader` and revoked immediately; no storage key or path is constructed | `frontend/src/features/model-viewer/api/resultApi.ts`, `hooks/useModelLoader.ts` |
| The result workspace is a protected `/projects/{id}/result` route linked from the project details header, the project card and the generation panel; it opens only for a validated current result | `frontend/src/app/router/AppRouter.tsx`, `pages/ModelViewerPage/`, UI-AC-09 |
| The model is centred by display offset and framed from its bounding sphere; the exported asset is never modified. Geometry, materials and textures are disposed on result change and unmount, and the canvas uses flat tone mapping so vertex colours and textures keep the worker-validated appearance | `frontend/src/features/model-viewer/components/ModelScene.tsx`, `utils/modelBounds.ts`, `utils/modelCleanup.ts`, FE-AC-17 |
| Metadata shows project/type/status, source-image count, format, size, creation date and live mesh/vertex/polygon/material/texture counts; a failed regeneration keeps the previous result visible and a project without a result gets an explanation rather than an empty canvas | `frontend/src/features/model-viewer/components/ModelInfoPanel.tsx`, `pages/ModelViewerPage/ModelViewerPage.tsx`, API-AC-13 |
| Viewer diagnostics are exposed as `data-model-*` attributes on the viewport for real-browser verification instead of a global debug object | `frontend/src/features/model-viewer/components/ModelViewer.tsx`, `.proof/viewer-tools/verify-viewer.mjs` |
| A successful regeneration queues a `FILE` cleanup job and `cleanup.requested` event for the superseded result in the same transaction; the old row stays as history, only its unreachable file is deleted later | `backend/app/services/task_execution_service.py`, 05 §14.6, 07 §15.7 |
| Terminal transitions refresh the task row (`populate_existing` / `get_refreshed`) so a cancellation request written after the claim is never masked by the identity map | `backend/app/repositories/task_repository.py`, `backend/app/services/task_execution_service.py` |
| Failed scene workspaces are bounded by a retention sweep (`SCENE_WORKSPACE_RETENTION_HOURS`, default 168; 0 disables) that queues `DIRECTORY` cleanup jobs and logs temporary-storage usage; active tasks are never touched | `backend/app/services/workspace_retention_service.py`, `backend/app/tasks/cleanup_tasks.py` |
| Scene toolchain `--help` probes run in a throwaway directory because OpenMVS writes its log into the CWD | `ml/scene_reconstruction/preflight.py` |
| Backup and restoration are documented in `docs/operations/backup_restore.md`; a runnable checker verifies that every active project's current result has a file of the recorded size | `docs/operations/` |
| API test clients default to `storage_root=/tmp/mogen-test-storage`, so a test that forgets a storage override can never write uploads into the live `/data` volume | `backend/tests/db/conftest.py` |

---

## 8. Open items

| Item | Status | Notes |
|---|---|---|
| Phase 2 close-out | Complete | All tasks 2.1–2.10 and the applicable Phase 2 criteria verified with evidence; see [`reviews/phase2_closeout.md`](reviews/phase2_closeout.md) |
| Phase 3 frontend integration | Complete | Tasks 3.1–3.6 and the Phase 3 acceptance criteria verified; 84 frontend tests; live smoke through the frontend proxy |
| Phase 4 background processing | Complete | Tasks 4.1–4.9 and the applicable criteria verified; report in [`reviews/phase4_closeout.md`](reviews/phase4_closeout.md); 451 backend tests; live object/scene/outbox/recovery/cleanup smoke |
| Phase 5 object generation | Complete | Tasks 5.1–5.9 and the applicable `OBJ-AC`, `BE-AC-17/19/20`, `DB-AC-07/08/10..12`, `API-AC-09..14`, `INF-AC-08/13` and `TEST-AC-12/14` criteria verified; report in [`reviews/phase5_closeout.md`](reviews/phase5_closeout.md); 481 backend, 92 frontend and 32 ML tests; real standalone and live GPU generation |
| Generation task creation/status, outbox insertion and dispatcher | Complete | `POST /projects/{id}/generate` (202/200), `GET /projects/{id}/status`, transactional outbox, dispatcher, workers, recovery; `BE-AC-13..16`, `API-AC-09..12`, `DB-AC-20..23` verified |
| `compose.gpu.yaml` and dedicated ML worker images | Complete | Dedicated TripoSR and COLMAP/OpenMVS images are in use; the GPU override reserves one device for each worker |
| Production frontend image (nginx, static build) | Deferred | Phase 4 of `08_infrastructure.md`; the Dockerfile already has a `build` stage |
| Generation UI, status polling and result link | Complete | The details page starts/retries generation, polls real status and links the authenticated download; the interactive viewer and result-management UI remain Phase 7 |
| 3D viewer and result-management UI | Complete | Phase 7: unified R3F viewer, authorized GLB loading, controls, lighting, disposal, information panel, download and result management; report in [`reviews/phase7_closeout.md`](reviews/phase7_closeout.md) |
| Phase 7 viewer and result management | Complete | Tasks 7.1–7.7 and the applicable `FE-AC-14..17/19`, `UI-AC-09..11/14`, `API-AC-13/14/16`, `INF-AC-02/07/15`, `TEST-AC-10/11` and `SCENE-AC-22` criteria verified; 130 frontend tests; real Edge proof against both asset types |
| Phase 8 reliability, security and optimization | Complete | Tasks 8.1–8.8 and the applicable `AC-08/09/12/13`, `BE-AC-05/06/10/15/18/19/21/22/23`, `DB-AC-20/21/23`, `INF-AC-10/11/12/15/18/19/20/21/22/23/24/25`, `API-AC-12/13/15/16` and `TEST-AC-04/06/07/08/09/16/17/18` criteria verified; report in [`reviews/phase8_closeout.md`](reviews/phase8_closeout.md); 509 backend tests, 130 frontend, 75 scene and 35 object ML; live Redis/PostgreSQL outage, API recreation, backup/restore and performance drills |
| Superseded result files | Complete | A successful regeneration queues a `FILE` cleanup job for the old GLB; a failed regeneration keeps it |
| Scene workspace retention | Complete | Hourly `cleanup_scene_workspaces_task`; `SCENE_WORKSPACE_RETENTION_HOURS` (168 default, 0 disables); `workspace_usage` logged |
| Backup and restoration documentation | Complete | [`operations/backup_restore.md`](operations/backup_restore.md) with executed PostgreSQL and file-storage drills and a runnable consistency checker |
| Performance baseline | Complete | API/upload/download/cleanup/viewer/memory measurements plus persisted TripoSR and COLMAP/OpenMVS stage timings; see the Phase 8 close-out |
| Frontend bundle size | Known limitation | Three.js raises the production bundle to ~1.54 MB (436 kB gzip); Vite warns about the chunk. Route-level splitting is deferred |
| Live object generation during Phase 7/8 | Environment note | A new OBJECT smoke task hung in `MODEL_GENERATION` under host GPU load in an unrelated workload; the test project was deleted and the worker restarted with its model loaded. Phase 8 did not run new inference for the same reason; GPU/RAM failures are covered by simulated stable codes and the recorded real runs |
| Playwright E2E | Partially addressed | Phase 7 added an out-of-tree Playwright Core + installed-Edge proof (`.proof/`, gitignored) for both result types and the invalid-GLB state; Phase 8 reused Playwright for the viewer memory baseline; a committed Playwright suite in CI remains deferred |
| Phase 6 scene reconstruction | Complete | Tasks 6.1–6.9 and the applicable `SCENE-AC`, `BE-AC-17/19/20`, `DB-AC-07/08/10..12`, `API-AC-09..14`, `INF-AC-02/09/10/12/13/14/17` and `TEST-AC-13/14/18` criteria verified; report in [`reviews/phase6_closeout.md`](reviews/phase6_closeout.md); 491 backend, 94 frontend and 74 scene ML tests plus the real 11-image proof and live worker E2E |
| CI pipeline and coverage measurement | Not started | `TEST-AC-19`, the only unmet `TEST-AC` after the Phase 2 review; coverage targets in `09_testing.md` Section 19; Phase 5 coverage 89% with the `generation_tasks` shortfall reported; Phase 8 did not add a pipeline |
| Rate limiting on auth endpoints | Not implemented | API contract lists 429; needs shared counters (Redis) and middleware |
| Cleanup-job processing | Implemented | The `cleanup-worker` claims `PENDING` jobs, deletes the target, records `COMPLETED`/`last_error`/`attempts` and retries until `CLEANUP_MAX_ATTEMPTS` |
| Broker-driven cleanup dispatch | Complete | Image/project deletion insert a `cleanup.requested` outbox event; the dispatcher publishes it to `file_cleanup` and the cleanup worker processes the targeted job immediately. The beat scan remains the recovery path. |
| Celery beat separation | Deferred | Development still runs `--beat` in the cleanup-worker container; production needs a dedicated beat service |
| Expired processing artifacts | Complete | The scene-workspace retention sweep is the producer and remover of expired intermediate artifacts (`07` Section 15.7); object work dirs are removed on success and failure |
| Worker health beyond the process | Partially complete | Workers answer `celery inspect ping`; the dispatcher and recovery prove their loops with heartbeat files. Task-level metrics, dead-letter handling and per-task health remain deferred |
| Session cleanup scheduling | Not scheduled | `SessionRepository.delete_expired`/`delete_revoked` exist; a periodic job would fit the cleanup worker's beat schedule. A few expired rows are present, but the table is small |
| Redis licensing (RSALv2/SSPLv1) | Open | Needs legal acceptance or an approved broker change; see `phase0_decisions.md` Section 8 |
| Docker data root relocation | No longer required | The scene build fits on `C:`; the two ML images are large. Phase 8's rebuild re-downloaded shared CUDA layers, so keep an eye on free space before a cold rebuild |
| First git commit | Pending | 82 files were staged at the Phase 2 close-out; every Phase 3–8 file listed in Section 6 is untracked |
| `ml/`, `infrastructure/`, `tests/` directories | Partially real | `ml/object_generation/` and `ml/scene_reconstruction/` are the real workers; `ml/workers/`, `infrastructure/` and `tests/` remain placeholders |
| Failed scene workspaces | Bounded | `/data/work/scene/{task_id}` is kept after a failed task for diagnostics and pruned after `SCENE_WORKSPACE_RETENTION_HOURS` (default 168) unless set to 0. The retained Phase 6 workspace becomes eligible ~2026-11-14 |

---

## 9. Phase 2–8 progress; next task

Phases 2, 3, 4, 5, 6, 7 and 8 are complete. The increments below record what was delivered; the Phase 2 close-out review is recorded at the end of the Phase 2 section, and the Phase 3, 4, 5, 6, 7 and 8 summaries and their close-out review links follow it. Phase 9 (comprehensive testing and quality assurance) is next.

**Read first:** `05_database_specification.md` (all of it — it is the authority for this phase), `04_backend_specification.md` Sections 7 and 20, `api_contracts.md` for response shapes, `09_testing.md` Sections 7 and 8, and Phase 2 in `10_development_roadmap.md`.

### Increment 2a — models and migration (complete)

Delivered and verified:

- `backend/app/db/models/` — one module per table, in dependency order: `user`, `user_session`, `project`, `project_image`, `generation_task`, `generation_task_image`, `generation_result`, `storage_cleanup_job`, `outbox_message`, plus `enums.py` and the package `__init__.py` that registers them in `Base.metadata`.
- `backend/alembic/versions/1f302d830cf9_initial_schema.py` — the single initial migration; `alembic check` reports no drift from the models.
- `backend/tests/db/` — 70 integration tests: entities, defaults and relationships; constraints, composite ownership and deletion policies; schema and migration round-trip.
- Full backend suite at that point: 84 passed; `ruff check` and `ruff format --check` clean; migration applied, downgraded and re-applied on both the development database and a scratch database.

The composite ownership foreign keys, single-active-task index, single-current-result index, project-scoped idempotency index, lease metadata and outbox table from increment 2a are all present and tested. Do not re-create them.

### Increment 2b — repository layer (complete)

Delivered and verified:

- `backend/app/repositories/` — `BaseRepository` plus one repository per entity: users, sessions, projects, images, tasks, results, cleanup jobs and outbox messages. Repositories encapsulate SQL, never commit, and expose query/persistence primitives only.
- Dashboard support without N+1: per-project image counts, current results and latest tasks are fetched in bulk for project listings.
- `backend/app/api/dependencies.py` — `get_db` plus a repository provider for each entity, usable through `Depends` and overridable in tests.
- `backend/tests/db/test_repositories.py` (23 tests) and `backend/tests/unit/test_repository_dependencies.py` (9 cases, including `dependency_overrides`).
- Full backend suite at that point: 116 passed; repository coverage 99% (target 75%); `ruff check` and `ruff format --check` clean; stack healthy.

Repositories deliberately omit business rules: allowed state transitions, idempotency decisions, image count limits, outbox claiming/retry and project deletion orchestration belong to services (project API onward) and the Phase 4 dispatcher.

### Increment 2c — authentication (complete)

Delivered and verified:

- `backend/app/core/security.py` — Argon2id password hashing, opaque session tokens with SHA-256 storage hash, and stateless HMAC CSRF tokens bound to a session.
- `backend/app/services/auth_service.py` — registration with normalization and duplicate handling, generic-error login with timing mitigation, logout revocation, session validation, CSRF issuance.
- `backend/app/api/v1/endpoints/auth.py` — `register`, `login`, `logout`, `me` and `csrf` with HttpOnly `session` and readable `csrf_token` cookies.
- `backend/app/api/dependencies.py` — `get_auth_service`, `get_current_auth`, `get_current_user`, `require_allowed_origin` and `require_csrf`.
- Production configuration guards: startup fails when `APP_ENV=production` uses the development CSRF secret or leaves cookies non-Secure.
- Tests: 13 security/config unit tests and 20 auth API tests against PostgreSQL. Full suite 149 passed; auth modules 95–100% covered (98% combined); `ruff` clean; stack healthy with auth routes live.

CSRF is deterministic per session, so a token rotates exactly when a new session is created (registration/login). No CSRF state is stored. Login/registration validate a present `Origin` header; requests without one (non-browser clients) still need the CSRF token for authenticated state changes.

### Increment 2d — project API and authorization (complete)

Delivered and verified:

- `backend/app/schemas/project.py` — `ProjectCreateRequest`, `ProjectResponse` with `current_result`/`latest_task` summaries, `ProjectListResponse`, `ProjectDeleteResponse`, and the `ProjectSort` values.
- `backend/app/services/project_service.py` — `normalize_project_name`, `clamp_page_limit`, create/list/get/delete, ownership checks and transaction boundaries.
- `backend/app/api/v1/endpoints/projects.py` — `POST/GET /projects`, `GET/DELETE /projects/{project_id}`, registered in `app/api/v1/router.py`; `get_project_service` added to `app/api/dependencies.py`.
- `backend/app/core/config.py` — `max_page_size` (default 100) with validation, exposed as `MAX_PAGE_SIZE` in `.env.example` and the `api` service in `compose.yaml`, and included in `redacted()`.
- Repository additions used by deletion: `TaskRepository.cancel_pending_for_project`, `TaskRepository.request_cancellation_for_processing`, `CleanupJobRepository.get_active_for_target`; `PROJECT_NAME_MAX_LENGTH` is exported from the project model.
- `backend/tests/db/conftest.py` — shared `api_client_factory`, `api_client`, `register_client` and `registered_client` fixtures; `test_auth_api.py` now consumes them.
- `backend/tests/db/test_projects_api.py` (34 tests) and `backend/tests/unit/test_project_validation.py` (9 tests), plus a `max_page_size` settings test.
- Full backend suite: 193 passed; project service, project schemas, project endpoint, dependencies and all repositories at 100% coverage (total 98%); `ruff check` and `ruff format --check` clean; `alembic check` reports no drift; the rebuilt stack is healthy and the endpoints were exercised over HTTP.

Project responses expose only `id`, `name`, `type`, `status`, `source_image_count`, `result_available`, `current_result`, `latest_task`, `created_at` and `updated_at`; no storage keys or paths are returned. Listing fetches image counts, current results and latest tasks in bulk, so a page costs a fixed number of queries.

### Increment 2e — file storage abstraction (complete)

Delivered and verified:

- `backend/app/storage/base.py` — `StorageBackend` interface: `save`, `open`, `delete`, `exists`, `get_size` (`04` Section 10.10).
- `backend/app/storage/keys.py` — `STORAGE_KEY_MAX_LENGTH` (512, matching the columns), `parse_storage_key` and `resolve_storage_path`; rejects empty keys, absolute paths, `.`/`..` segments, repeated separators, backslashes, colons, NUL bytes and over-long keys, and re-checks containment after resolving symlinks.
- `backend/app/storage/local.py` — `LocalStorage`: atomic save (temporary file in the destination directory, `fsync`, then `os.replace`), binary `open`, file/tree `delete` where an absent target succeeds, `exists`, `get_size`; missing objects raise `FileNotFoundError`, other filesystem failures become `503 STORAGE_UNAVAILABLE`.
- `backend/app/storage/__init__.py` and `backend/app/api/dependencies.py` — `get_storage`, overridable with a temporary root.
- `backend/app/core/config.py` — `storage_root` must be absolute, so containers cannot resolve it differently.
- `backend/tests/unit/test_storage.py` (32 cases) and a `storage_root` settings test: round-trip, stream input, directory creation, atomic failure cleanup, missing-object behaviour, file/tree deletion, key validation, symlink escape (skipped only where symlinks are unavailable), unreadable/unremovable failure mapping, dependency wiring.
- Full backend suite: 226 passed; every storage module 100% covered (total 98%); `ruff check` and `ruff format --check` clean; `alembic check` no drift; stack rebuilt and healthy.
- Runtime verification in the rebuilt `api` container: `LocalStorage('/data')` saved, read and deleted a probe as `appuser`; the probe survived `docker compose up -d --force-recreate api` (the `app_data` volume), and a `../` key was rejected.

Storage keys stay relative and opaque (`projects/{project_id}/source/{image_id}.jpg`); callers supply generated filenames, never client filenames, and no resolved filesystem path is exposed through the API.

### Increment 2f — image upload and listing (roadmap 2.8, complete)

Delivered and verified:

- `backend/app/schemas/image.py` — `ImageResponse` (contract 5.6) and `ImageListResponse`.
- `backend/app/services/image_service.py` — `clean_filename`, `validate_image_bytes` and `ImageService.upload_image`/`list_images`. Validation checks the extension, the declared media type and Pillow's decoded format, decodes the pixels, rejects empty/corrupt content, caps dimensions and maps decompression bombs to `IMAGE_DIMENSIONS_EXCEEDED`.
- Upload flow: project row lock, `UPLOADING`→`CREATED` inside the transaction, status/active-task checks, size limit (413), OBJECT one-image / SCENE `max_scene_images` rules (409), generated key `projects/{project_id}/source/{image_id}.{ext}`, verified MIME, SHA-256, next position, storage write before metadata insert, and file rollback (logged) when the database write fails.
- `backend/app/api/v1/endpoints/images.py` — `POST`/`GET /projects/{project_id}/images`; `get_image_service` dependency; router registration.
- `backend/app/repositories/image_repository.py` — optional `image_id` so the storage key can be derived before the row exists.
- `backend/app/core/config.py` — `max_image_dimension` (default 8192) with validation, `MAX_IMAGE_DIMENSION` in `.env.example` and the `api` service in `compose.yaml`.
- Tests: 30 image API cases and 17 validation unit cases; full suite 273 passed; image modules 100% covered (total 98%); `ruff check`/`ruff format --check` clean; `alembic check` no drift; stack healthy.
- Runtime verification: a 640×480 JPEG uploaded as `appuser`, stored byte-identical under `/data/projects/{id}/source/{image_id}.jpg`, listed without exposing `storage_key`, reflected in `source_image_count`, rejected a second OBJECT image with 409 and a corrupt file with 400; the smoke rows/files were then removed.

### Increment 2g — image content retrieval and deletion (api_contracts 8.3 and 8.4, complete)

Delivered and verified:

- `backend/app/api/v1/endpoints/images.py` — `GET /projects/{project_id}/images/{image_id}/content` and `DELETE /projects/{project_id}/images/{image_id}`. Content streams through a chunked generator that always closes the file handle; deletion is a CSRF-protected 204.
- `backend/app/services/image_service.py` — `open_image_content` and `delete_image`, plus `ImageContent` and the `content_disposition` helper. Content verifies ownership, scopes the lookup to the project, opens through `StorageBackend`, maps a missing object to 404 and keeps filesystem failures at 503. Deletion locks the project row, refuses a task-referenced image (409 `IMAGE_REFERENCED`) or a generation-held project (409 `INVALID_PROJECT_STATE`), records a `FILE` cleanup job and deletes the metadata in one transaction.
- `backend/app/repositories/image_repository.py` — `get_for_project(image_id, project_id)`, so an identifier from another project is treated as absent.
- `backend/app/repositories/task_repository.py` — `is_image_referenced(image_id)` over `generation_task_images`.
- `backend/app/services/image_service.py` — upload and deletion now share one `_ensure_source_modification_allowed` guard instead of duplicating the status/task checks.
- Tests: 25 new image API cases (content bytes, MIME and headers, non-ASCII and injection-safe filenames, 401/404/503 paths, deletion with cleanup job, repeated deletion, CSRF, ownership, task reference, project state, foreign-key race, unrelated database errors), 8 `Content-Disposition` unit cases and 2 repository cases. Full suite 308 passed; `images.py`, `image_service.py`, `image_repository.py` and `task_repository.py` at 100% coverage (total 98%); `ruff check`/`ruff format --check` clean; `alembic check` no drift; stack healthy.
- Runtime verification over HTTP against the rebuilt stack: a 640×480 JPEG uploaded and retrieved byte-identically (SHA-256 match) with `Content-Type: image/jpeg`, `Content-Disposition: inline; filename="probe.jpg"`, `Cache-Control: private` and no storage key in the headers; anonymous content 401; delete without CSRF 403; delete 204 with the metadata removed, one `FILE`/`PENDING` cleanup job for the exact key and a subsequent content 404; repeat delete 404; 409 `IMAGE_REFERENCED` for a task-referenced image and 409 `INVALID_PROJECT_STATE` for a `PENDING` project, with 204 once reset to `CREATED`. All smoke rows, jobs, sessions, the user and `/data/projects/*` were removed afterwards.

Contract resolutions recorded in Section 7: a missing stored object is 404 `IMAGE_NOT_FOUND`, a filesystem failure stays 503, and generation history uses the new `IMAGE_REFERENCED` code. The stored file outlives the metadata until the cleanup worker deletes it.

### Increment 2h — cleanup-job processing and the `file_cleanup` worker (roadmap 2.9 / 4.8, complete)

Delivered and verified:

- `backend/app/services/cleanup_service.py` — `CleanupService.process_pending`/`process_next`/`process_job` plus `CleanupOutcome` and `CleanupSummary`. A job is claimed with `FOR UPDATE ... SKIP LOCKED` and the transaction stays open until the attempt finishes, so a crash rolls back to `PENDING` instead of stranding `PROCESSING`. Success marks `COMPLETED` with `completed_at`; a failure records `last_error`, increments `attempts` and returns the job to `PENDING` until `CLEANUP_MAX_ATTEMPTS`, then marks it `FAILED`. An absent target completes. Directory jobs are deferred while their project still has a `PENDING`/`PROCESSING` task, and each job is attempted at most once per cycle so a retry waits for the next poll.
- `backend/app/repositories/cleanup_job_repository.py` — `get_pending_for_update(exclude_ids)` (`SKIP LOCKED`, deterministic creation order) and `get_for_update(job_id)`.
- `backend/app/tasks/celery_app.py` — Celery application: Redis DB 1 broker, `file_cleanup` queue routing for `cleanup_storage_task`, no result backend, hard/soft time limits, `acks_late`, prefetch 1, beat poll every `CLEANUP_POLL_INTERVAL_SECONDS`, JSON logging owned by the app.
- `backend/app/tasks/cleanup_tasks.py` — `cleanup_storage_task` (optional `job_id` for targeted dispatch) and `run_cleanup`, the broker-free cycle used by tests; one process-wide engine/session factory/storage.
- `backend/app/core/config.py` — `celery_broker_url`, `celery_task_ignore_result`, `cleanup_batch_size` (20), `cleanup_poll_interval_seconds` (15), `cleanup_max_attempts` (3), `cleanup_task_time_limit_seconds` (600), all validated and redacted.
- `backend/app/db/session.py` — `session_scope` is now a `@contextmanager`; `get_db` uses it, and the worker shares the same lifecycle helper.
- `compose.yaml` — `cleanup-worker` service (same image, `app_data` volume, `file_cleanup` queue, `--beat`, `celery inspect ping` healthcheck) with `depends_on` db/redis healthy and migration completed. `.env.example` documents the new cleanup variables.
- `backend/requirements.txt` — `celery==5.7.0` (Kombu 5.7), verified against the pinned `redis==8.1.0`; `pip check` reports no broken requirements.
- Tests: 17 cleanup worker integration cases (completion, absent target, directory tree, retry then `FAILED`, immediate failure, duplicate delivery, targeted dispatch, unknown id, active-task deferral, file job not deferred, starvation guard, batch limit, worker entry point, worker runtime, API-to-worker end to end), 6 Celery configuration unit cases, 1 repository claim case and 6 settings cases. Full suite 338 passed; `cleanup_service.py`, `cleanup_tasks.py` and `celery_app.py` at 100% coverage (total 99%); `ruff check`/`ruff format --check` clean; `alembic check` no drift.
- Runtime verification over HTTP against the rebuilt stack: image deletion → job `PENDING` → worker `COMPLETED` (attempts 1), file gone and content 404; project deletion → `DIRECTORY` job `COMPLETED` and the project tree removed; with a `PROCESSING` task the directory job stayed `PENDING` with attempts 0 and files present, then completed after the task was `CANCELLED`. Worker logs are single-line JSON containing `project_id`, `cleanup_job_id` and `operation`; the worker healthcheck reports healthy; all smoke rows, jobs and files were removed.

### Phase 2 close-out (complete)

Verified on 2026-11-06 against the running stack and **339 passing backend tests**. The task-by-task and criterion-by-criterion tables are in [`reviews/phase2_closeout.md`](reviews/phase2_closeout.md).

**Result**

- All roadmap tasks 2.1–2.10 are satisfied at their Phase 2 scope. Task 2.10's outbox table, idempotency/lease/cancellation columns and composite ownership foreign keys are present and tested; the transactional outbox insertion, dispatcher and generation endpoints are Phase 4.
- All eight Phase 2 acceptance criteria are satisfied. `BE-AC-01..12`, `BE-AC-21..24`, `DB-AC-01..19`, `DB-AC-21..23`, `API-AC-01..08`, `API-AC-13` and `API-AC-15..17` are verified. `TEST-AC-02..05`, `TEST-AC-09` are verified and `TEST-AC-18` is verified at the database level; `TEST-AC-01`, `TEST-AC-07` and `TEST-AC-17` are verified only for the Phase 2 scope (ML/E2E suites, concurrent generation and generation-worker recovery are later phases). `BE-AC-13..20`, `API-AC-09..12`, the behavioral half of `DB-AC-20` and the later ML/E2E/CI criteria are deferred to their roadmap phases and are named as such in the report.
- No Phase 3 or Phase 4 work was started.

**Defect found and fixed**

`RequestValidationError` responses exposed `details[].type`; `api_contracts.md` Section 12.2 requires `details[].code` (a stable uppercase code), so `API-AC-15` was not fully satisfied. `backend/app/main.py` now emits `code`; regression test `backend/tests/api/test_errors.py::test_field_validation_errors_use_the_documented_detail_schema` covers it. Suite 338 → 339; live response confirmed.

**Baseline re-run after the fix**

339 passed, 1 warning (222 database/API, 109 unit, 8 API-shell) in 77.17 s; `ruff check` clean; `ruff format --check` clean (79 files); `alembic check` no drift; five services healthy and `migration` `Exited (0)`; worker ping OK; frontend lint, 2 tests and build clean; coverage 99% (1805 statements, 26 missed).

### Phase 3 — frontend integration (complete)

Verified on 2026-11-06 against the running stack with **84 passing frontend tests**. The implementation follows `03_frontend_specification.md` and `02_ui_ux_specification.md`.

**Delivered**

- **Application shell (3.1):** `AppLayout` with sidebar, topbar, responsive mobile navigation, user block and logout; dark theme tokens; routes `/`, `/login`, `/register`, `/dashboard`, `/projects/new`, `/projects/:id`; `ProtectedRoute` redirects unauthenticated users to login with a return path.
- **Authentication (3.2):** `AuthProvider`/`useAuth` initialise the session through `/auth/me`, fetch a CSRF token into memory through `/auth/csrf`, and expose login, registration and logout; forms use React Hook Form with Zod schemas; API field errors are mapped onto form fields; logout clears the query cache.
- **Dashboard (3.3):** `useProjects` (limit 100), project cards with type/status/date/result-availability, loading/empty/error states, delete confirmation and optimistic removal.
- **Project creation (3.4):** generation-mode cards, name validation, mode-dependent upload interface, scene guidance panel, create-then-upload sequence, duplicate-submit guard and partial-failure handling.
- **Image upload (3.5):** `ImageDropzone` with drag and drop, JPEG/PNG and size validation, decoded-image verification, previews with `URL.createObjectURL`, revocation on removal/replacement/clear/unmount, single/multiple modes, sequential uploads with progress and per-file retry.
- **Project details (3.6):** metadata, status, source-image grid, image deletion, additional scene uploads, object-image replacement guidance, empty/error states and a clearly disabled generation placeholder; no fabricated generation availability.

**Verification**

- 84 frontend tests across 14 files: formatting, API error mapping, image validation and object-URL lifecycle, status/type badges, project card, dropzone, auth forms, auth initialisation, dashboard, project creation and project details.
- `npm run lint`, `npm run typecheck`, `npm run format:check` and `npm run build` pass; production bundle is ~526 kB (164 kB gzip) and Vite warns about the chunk size (route-level splitting is a later optimisation).
- Live smoke through the frontend origin (`http://127.0.0.1:5173`): register 201, `/auth/me` 200, `/auth/csrf` 200, create project 201, upload 201 (640×480 JPEG), list 1, content 200 `image/jpeg`, detail `source_image_count=1`, delete 202, subsequent detail 404. Database and storage were cleaned afterwards.
- The running frontend serves the new sources (Russian landing heading and `AuthProvider` present) and still proxies `/api` to uvicorn.

**Criteria:** all seven Phase 3 acceptance criteria are satisfied. `FE-AC-01..10`, `FE-AC-13`, `FE-AC-17..20` and `UI-AC-01..07`, `UI-AC-12..14` are satisfied; `FE-AC-11/12/14/15/16` and `UI-AC-08..11` depend on Phase 4 generation endpoints and the Phase 7 viewer and are not claimed here.

### Phase 4 — background processing infrastructure (complete)

Verified on 2026-11-06 against the running ten-service stack and **451 passing backend tests**. The task-by-task and criterion-by-criterion tables are in [`reviews/phase4_closeout.md`](reviews/phase4_closeout.md).

**Increment 4a — Celery topology and worker containers (4.1–4.3)**
`celery_app.py` now declares the three documented queues with explicit task routes, per-pipeline soft/hard time limits, a visibility timeout above the longest task, `acks_late`, prefetch 1, no result backend and application-owned JSON logging. Compose adds `object-worker` (queue `object_generation`), `scene-worker` (queue `scene_reconstruction`), `outbox-dispatcher` and `task-recovery`; the three Celery workers use `celery inspect ping` healthchecks and the two process services use heartbeat files. No ML pipeline is registered: a claimed task fails with `WORKER_UNAVAILABLE` rather than simulating work. `tests/unit/test_celery_config.py` (10) and `tests/unit/test_outbox_publisher.py` (13); live `active_queues` showed one queue per worker.

**Increment 4b — transactional outbox and dispatcher (4.4)**
`app/services/outbox_events.py` builds the documented payloads and inserts the event in the caller's transaction. `OutboxRepository` claims with `FOR UPDATE SKIP LOCKED`, releases expired `PROCESSING` locks and marks published/retry/failed. `app/services/outbox_service.py` commits the claim before publishing, applies full-jitter exponential backoff, distinguishes permanent contract failures from transient broker errors and exhausts a bounded budget; `app/tasks/outbox_dispatcher.py` is the standalone loop. `tests/db/test_outbox_dispatcher.py` (11) includes a `FOR UPDATE NOWAIT` probe proving no row lock is held during publication; `tests/unit/test_outbox_backoff.py` (4). Live: a Redis outage left the message PENDING and retried attempts 1→2→3 before publishing after recovery.

**Increment 4c — generation lifecycle and API (4.5–4.7)**
`app/services/generation_service.py` validates the project type, source images and state, enforces the mandatory project-scoped `Idempotency-Key` with a 64-hex request fingerprint, and creates the task, ordered `generation_task_images` snapshot, `PENDING` project and outbox event in one transaction. `app/services/task_execution_service.py` performs the atomic `PENDING`→`PROCESSING` claim with `worker_id`/lease, heartbeat, progress, completion, failure and cancellation. `app/tasks/generation_tasks.py` exposes the broker-free worker path, a heartbeat monitor and a pipeline registry for Phase 5/6. The API adds `POST /projects/{id}/generate` (202 new, 200 repeat) and `GET /projects/{id}/status`. `tests/db/test_generation_api.py` (24), `test_task_lifecycle.py` (19), `test_generation_fingerprint.py` (10), `test_generation_validation.py` (11) and updated `tests/unit/test_celery_config.py`.

**Increment 4d — recovery and cleanup dispatch (4.8, 4.9)**
`app/services/task_recovery_service.py` requeues stale tasks through a new outbox event with `attempt_count` incremented, fails them at the recovery budget, cancels requested/deleted tasks after their worker stopped, and fails stranded `PENDING` tasks with no dispatchable event after `DISPATCH_STALL_TIMEOUT_SECONDS`. `app/tasks/task_recovery.py` is the standalone loop. Cleanup jobs from image/project deletion now insert `cleanup.requested` in the same transaction; the dispatcher targets the existing `cleanup_storage_task(job_id)`, and the beat scan remains the recovery path. `tests/db/test_task_recovery.py` (13) and `test_cleanup_dispatch.py` (6). Live: a simulated stale task was requeued to PENDING (`attempt_count=1`, one task, two events) and then failed by the worker; an image cleanup job completed in 2.7 s and a directory job in 1.4 s.

**Criteria:** `BE-AC-13..16` and `BE-AC-18` are satisfied at the Phase 4 scope; `BE-AC-17` is satisfied only at the worker-invocation boundary (no ML pipeline yet) and `BE-AC-19/20` are not claimed. `DB-AC-16` and `DB-AC-20..23`, `API-AC-09..12`, `INF-AC-10/15/16/17/18/21/22/23/24/25`, `TEST-AC-06/07/08/17/18` are satisfied; `TEST-AC-19` (CI) remains unimplemented. Frontend, viewer and result-download criteria are unchanged and not claimed.

**Coverage:** total 93% (2736 statements, 202 missed). New modules: generation service 96%, outbox service 96%, task recovery service 91%, task execution service 89%, generation tasks 87%, API/schema/publisher 100%. The two process loops are 0% unit coverage but were verified live through their health files and logs.

### Phase 5 — object generation (complete)

Verified on 2026-11-07 against the running eleven-service GPU stack, **481 passing backend tests**, **92 passing frontend tests** and **32 passing ML unit tests plus the real-model test**. The task-by-task and criterion-by-criterion tables are in [`reviews/phase5_closeout.md`](reviews/phase5_closeout.md).

**Increment 5.1–5.2 — environment, pinned weights and standalone proof**
`ml/object_generation/Dockerfile` builds a dedicated `mogen-object-worker:dev` image on `pytorch/pytorch:2.14.1-cuda12.6-cudnn9-{devel,runtime}`. TripoSR is pinned to commit `d26e33181947bbbc4c6fc0f5734e1ec6c080956e`, weights to revision `5b521936b01fbe1890f6f9baed0254ab6351c04a` with `model.ckpt` SHA-256 `429e2c6b…`, DINO to `f205d5d8…`, torchmcubes to `a9ac95aa…` compiled for SM 86. `model-init` populates `triposr_model_cache:/models` and verifies the checksum; the worker is offline. The standalone proof on `car-1.jpg` produced a 1 528 660-byte GLB with 38 241 vertices / 76 315 faces and vertex colours; it loaded through Three.js `GLTFLoader` with the Khronos glTF Validator reporting 0 errors and 0 warnings. Real-model pytest (`RUN_REAL_MODEL_TESTS=1 -m real_model`) passed.

**Increment 5.3 — preprocessing**
`preprocessing.py` decodes and EXIF-corrects the upload, normalises RGB/RGBA, removes the background with a process-wide rembg session, rejects an empty mask, crops/pads the foreground, applies `foreground_ratio`, resizes to 512 px and composites over the neutral background. The original bytes are copied unchanged to the task work directory.

**Increment 5.4–5.6 — model, mesh and GLB**
`model_loader.py` verifies the cached checksum, resolves `cuda:0` without silent CPU fallback, loads `TSR` once per process and cleans the CUDA cache after a task. `generator.py` runs `torch.inference_mode` inference and marching-cubes extraction; `mesh_processor.py` validates geometry and bounds; `exporter.py` preserves vertex colours and writes a self-contained GLB; `validator.py` independently parses the container/accessors/indices/bounds/`COLOR_0` and rejects invalid output.

**Increment 5.7 — pipeline registration**
`app/tasks/object_pipeline.py` registers `run_triposr_pipeline` through the Phase 4 `register_pipeline(TaskType.OBJECT, …)` hook and uses `TaskContext.heartbeat`, `report_progress`, `raise_if_cancelled`, `GenerationFailure` and `GenerationCancelled`. The worker runs `--pool=solo --include=app.tasks.object_pipeline`; no direct Redis publication or new lifecycle was introduced.

**Increment 5.8 — result persistence and API**
`PipelineArtifact` is stored at `projects/{project_id}/results/{task_id}/model.glb`; `TaskExecutionService.complete_with_result` locks the task, clears the old current result, inserts the new current result and completes the task and project in one transaction. A failure or cancellation preserves the previous result and file. `GET /projects/{id}/result` returns the current result metadata without storage paths, and `GET /projects/{id}/download` streams the GLB with ownership checks and the documented headers.

**Increment 5.9 — generation UI**
The existing details page now renders `GenerationPanel`, starts generation with a fresh idempotency key, polls the persisted status only while active, shows real stage labels and only a real percentage, maps stable error codes to Russian messages, offers retry after failure, and links the authenticated download. Scene reconstruction was enabled in Phase 6.

**Criteria:** `OBJ-AC-01..18`, `BE-AC-17/19/20`, `DB-AC-07/08/10/11/12`, `API-AC-09..14`, `INF-AC-08/13` and `TEST-AC-12/14` are satisfied. Live evidence: a real project completed `IMAGE_PREPARATION → MODEL_GENERATION → RESULT_VALIDATION → COMPLETED` with a 1 528 660-byte result matching the standalone SHA-256; a second attempt with the source removed failed with `SOURCE_IMAGE_NOT_FOUND` while the project showed `FAILED`, `result_available=true`, the same current result id and an unchanged download SHA. The project cleanup job completed with `attempts=1`. A user-created project (`Мой 3D-проект`) was also generated successfully through the running app and was left untouched.

**Coverage:** total 89% (3102 statements, 329 missed); results endpoint 100%, result service 99%, task execution service 86%, generation tasks 80%, object pipeline 0% (worker-only, live-verified). The `generation_tasks` shortfall against the 90% generation-state target is reported in the close-out.

### Phase 6 — scene reconstruction (complete)

Verified on 2026-11-08 against the running eleven-service GPU stack, **491 passing backend tests**, **94 passing frontend tests** and **74 passing scene ML tests plus the skipped opt-in real-reconstruction test**. The task-by-task and criterion-by-criterion tables are in [`reviews/phase6_closeout.md`](reviews/phase6_closeout.md).

**Increment 6.1–6.2 — environment, pinned toolchain and standalone proof**
`ml/scene_reconstruction/Dockerfile` builds a dedicated `mogen-scene-worker:dev` image on the pinned official COLMAP image (`colmap/colmap:20260929.8466@sha256:c1de5161…`, COLMAP 4.2.1 with CUDA). OpenMVS v2.4.0 (commit `58117204…`) is built unmodified from source with CUDA off, against OpenCV 4.12.0 (built from source because OpenMVS needs `IMWRITE_JPEGXL_QUALITY`), CGAL 6.0.1, Eigen 3.4 and VCGLib `658ba36d…`. The build verifies all seven executables; the worker re-verifies them at startup. The standalone proof reconstructed all 11 Sceaux Castle photographs: 11/11 registered, 8 018 sparse points, 332 303 dense points, a 5 029/9 985 mesh, a 14 205/28 216 refined mesh and one texture atlas; the final repacked GLB was 959 504 bytes with 16 539 vertices / 28 991 triangles and passed the Khronos glTF Validator with 0 errors and 0 warnings.

**Increment 6.3 — dataset preparation**
`dataset.py` copies the ordered snapshot byte-for-byte into `/data/work/scene/{task_id}/images`, decodes every file with Pillow, rejects unsupported formats, corrupt files, over-sized dimensions, too few/too many images and SHA-256 duplicates, and records formats, dimensions and warnings.

**Increment 6.4–6.6 — COLMAP and OpenMVS**
`colmap_runner.py` builds and validates `feature_extractor`, `exhaustive_matcher`/`sequential_matcher`, `mapper` and `image_undistorter`, and reads COLMAP's SQLite statistics (including ``pair_id`` decoding and image connectivity). `reconstruction_selector.py` inspects every sparse model, computes registered count/ratio, points, reprojection error and connected components, and selects the best candidate by measured properties. `openmvs_runner.py` runs InterfaceCOLMAP, DensifyPointCloud, ReconstructMesh, RefineMesh and TextureMesh with validated outputs. `runner.py` enforces argument arrays, timeouts, log capture, process-group termination and cooperative cancellation.

**Increment 6.7 — orchestration and checkpointing**
`pipeline.PhotogrammetryReconstructor` executes the thirteen documented stages in order, reports each real stage through the worker callbacks, throttles heartbeat database writes, enforces the total task budget, reuses completed stages only after their outputs pass the same validators, and writes `diagnostics.json` with the input/sparse/dense/mesh/output metrics.

**Increment 6.8 — GLB export and persistence**
`TransformScene` produces OBJ/MTL/PNG and a raw GLB. OpenMVS's GLB references the texture as a sidecar (`scene_mesh_0.png`) and uses `KHR_materials_unlit`; `exporter.py` repacks the OBJ set into one self-contained GLB with embedded buffers and images, and `validator.py` independently checks the container, accessors, indices, bounds, embedded images, `TEXCOORD_0` and material-to-texture references. The validated asset is stored at `projects/{project_id}/results/{task_id}/scene.glb` and registered through `complete_with_result`.

**Increment 6.9 — Celery and frontend**
`app/tasks/scene_pipeline.py` registers `run_colmap_pipeline` through the existing Phase 4 hook and maps `SceneReconstructionError`/`SceneCancelled` onto the existing task lifecycle; the Compose worker runs `--include=app.tasks.scene_pipeline` and verifies the toolchain before registering. The existing details-page panel now enables scene reconstruction, shows the persisted scene stages/errors, supports retry and links the authenticated download.

**Criteria:** `SCENE-AC-01..21` and `SCENE-AC-23/24` are satisfied; `SCENE-AC-22` (in-browser display) was deferred at the Phase 6 close-out and is now closed by the Phase 7 viewer. `BE-AC-17/19/20`, `DB-AC-07/08/10/11/12`, `API-AC-09..14`, `INF-AC-02/09/10/12/13/14/17` and `TEST-AC-13/14/18` are satisfied at the Phase 6 scope. Live evidence: a five-photograph SCENE task completed real reconstruction in about 2 min 20 s (stages persisted, 1 619 116-byte result, download SHA matching storage); after the source files were removed, a second task failed with `SOURCE_IMAGE_NOT_FOUND` while the project showed `FAILED`, `result_available=true`, the same current result id and an unchanged download checksum.

A live low-texture four-PNG project failed in the mapper (five of six pairs verified, but no good initial pair); diagnosis confirmed an input-quality failure, and the mapper failure was corrected to raise `INSUFFICIENT_REGISTERED_IMAGES` with an actionable message instead of exposing an exit code (see the Phase 6 close-out).

**Known limitations:** the scene image is ~11 GB and first build takes 30–45 minutes; OpenMVS is CPU-only; failed-task workspaces under `/data/work/scene` have no retention job yet; backend coverage is 87% (`scene_pipeline` 0% worker-only, `generation_tasks` 80%, both live-verified); `SCENE-AC-22` was closed in Phase 7; `TEST-AC-16/19/20` remain open.

### Phase 7 — 3D viewer and result management (complete)

Verified on 2026-11-09 against the running eleven-service stack, **491 passing backend tests**, **130 passing frontend tests**, **74 passing scene ML tests** and **35 passing object ML tests** (recorded as 32 at the time; corrected during Phase 8) plus their skipped opt-in tests. The task-by-task and criterion-by-criterion tables are in [`reviews/phase7_closeout.md`](reviews/phase7_closeout.md).

**Increment 7.1–7.2 — integration and model loading**
Added React Three Fiber `9.8.2`, Drei `10.7.9` and Three.js `0.187.0` as exact pins and a standalone `frontend/src/features/model-viewer/` module. The current result is read through the existing `GET /result`; the GLB is fetched through the authenticated shared client, exposed as a temporary blob URL, parsed with `GLTFLoader` and the URL is revoked immediately. `useModelLoader` owns loading/loaded/error state, stable `DOWNLOAD_FAILED` / `PARSE_FAILED` / `EMPTY_MODEL` / `UNSUPPORTED_ASSET` codes and disposal of geometries, materials and textures on result change and unmount.

**Increment 7.3 — viewer controls**
`ModelScene` centres the model by display offset, derives camera distance/near/far from its bounding sphere and uses Drei `OrbitControls` for rotate, zoom and pan. The toolbar exposes reset, fit-to-view, grid, dark/light background and fullscreen, all with accessible labels; `ModelCanvas` uses neutral hemisphere/directional lighting and flat tone mapping.

**Increment 7.4–7.6 — information, download and result management**
The protected `/projects/{id}/result` page (`ModelViewerPage`) shows project name, type, status, source-image count, format, file size, creation date and live mesh/vertex/polygon/material/texture counts. Download uses the existing authenticated endpoint. A project without a result gets an explanation instead of a canvas; a processing task is announced; a failed regeneration keeps the previous successful result visible. The result page is linked from the project details header, the dashboard card and the generation panel.

**Increment 7.7 — performance and browser proof**
Verified in installed Edge through Playwright Core against a real TripoSR object, a medium reconstructed scene and the real 100-photo COLMAP/OpenMVS scene: object 1.86 s to loaded / 45.6 fps / 23 039 vertices / 45 983 triangles with vertex colours; medium scene 1.82 s / 74.3 fps / 16 539 vertices / 28 991 triangles with one texture; large scene 2.43 s / 16.0 fps / 202 493 vertices / 297 813 triangles with one embedded texture. All downloads matched the stored SHA-256 exactly; an invalid GLB produced the readable error state with a working retry; rotate, zoom, reset, fit, grid and background changes were confirmed by pixel differences. Headless Edge uses SwiftShader, so frame rates are software-renderer floors.

**Criteria:** `FE-AC-14..17/19`, `UI-AC-09..11/14`, `API-AC-13/14/16`, `INF-AC-02/07/15`, `TEST-AC-10/11`, `SCENE-AC-22` and `M7` are satisfied. `UI-AC-12` is only partially verified for the viewer (responsive layout exists; no tablet measurement). `TEST-AC-19` (CI) remains open.

**Known limitations:** the production bundle is ~1.54 MB (436 kB gzip) because of Three.js and route-level splitting is deferred; the browser proof used software WebGL; fullscreen and tablet layouts were not measured on a physical display; the committed test suite covers the viewer in jsdom, while the real-browser proof remains out-of-tree in `.proof/` (gitignored). A new OBJECT smoke generation could not be completed during this session because the host GPU was saturated by an unrelated workload; the viewer was validated against the retained real Phase 5 object and Phase 6 scene assets (byte-identical, SHA-verified copies) and the worker's model load was re-verified after restart.

### Phase 8 — reliability, security and optimization (complete)

Verified on 2026-11-09 against the running eleven-service stack, **509 passing backend tests**, **130 passing frontend tests**, **75 passing scene ML tests** and **35 passing object ML tests** plus their skipped opt-in tests. The task-by-task and criterion-by-criterion tables are in [`reviews/phase8_closeout.md`](reviews/phase8_closeout.md).

**Delivered**
- **8.1 Authentication security.** Session expiration and revocation, cookie attributes, CSRF rotation and cross-session binding, origin validation and authorization dependencies re-verified; one new cross-session CSRF test. No defect found.
- **8.2 File security.** Validation, storage-key handling, traversal and containment, unprivileged containers, private asset access and the absence of paths in responses re-verified; no defect found.
- **8.3 Generation reliability.** Interrupted-worker recovery, retries, duplicate delivery, GPU/RAM/storage failures and stale-task recovery covered by tests and by a live Redis-outage drill; a **stale identity-map read** that could hide a mid-generation cancellation was found and fixed.
- **8.4 Data consistency.** Outbox recovery (including publish-then-crash), status consistency, result replacement and previous-result preservation verified; superseded result files are now queued for deletion instead of leaking.
- **8.5 Resource management.** Worker concurrency and timeouts verified live (object solo, scene 1, cleanup 2); object work dirs are removed on success and failure; failed scene workspaces are bounded by a retention sweep with `workspace_usage` logging; GPU memory recovery evidenced by consecutive real inferences.
- **8.6 Performance baseline.** Measured API p50 215–226 ms through the dev proxy, 5.42 MB upload ~8.3 MB/s warm, 16.1 MB GLB download ~43 MB/s, cleanup 2.29 s, viewer load 1.899 s with +39.2 MB JS heap; persisted TripoSR stage timings (inference 0.04–2.33 s, total 4.95–15.43 s) and COLMAP/OpenMVS stage timings (100 images: 3719 s; 11-image proof: 231.5 s).
- **8.7 Infrastructure reliability.** API recreation preserved an uploaded image byte-for-byte; Redis stop/start kept the API ready and recovered a committed generation; PostgreSQL stop/start produced 503 then 200 with identical row counts and live worker pings; PostgreSQL dump/restore and a file-storage tar/restore matched counts, migration revision and SHA-256.
- **8.8 Regression scenarios.** CSRF rotation/binding, worker termination, project deletion during generation, Redis interruption after commit, duplicate delivery after dispatcher interruption and database failure during result registration all covered, the last three by new deterministic tests.

**Criteria:** `AC-08/09/12/13`, `BE-AC-05/06/10/15/18/19/21/22/23`, `DB-AC-20/21/23`, `INF-AC-10/11/12/15/18/19/20/21/22/23/24/25`, `API-AC-12/13/15/16` and `TEST-AC-04/06/07/08/09/16/17/18` are satisfied. `TEST-AC-19` (CI) remains open and `TEST-AC-12/13/14/15` remain the earlier phases' real-run evidence. `M8` is partially achieved: the reliability criteria pass, the comprehensive suite is Phase 9.

**Known limitations:** no new real generation was run (host GPU busy; the Phase 7 handoff forbids re-running it just to re-check delivery), so GPU/RAM failures are simulated and ML timing comes from persisted metadata and earlier real proofs; API latency includes the Vite proxy and process startup; browser figures use software WebGL; retention will prune the retained Phase 6 workspace after the default window; auth rate limiting, scheduled session cleanup and CI remain open; backups are documented and drilled but not scheduled.

### Next: Phase 9 — comprehensive testing and quality assurance

**Read:** Phase 9 in `10_development_roadmap.md` (tasks 9.1–9.7), `09_testing.md` (all of it), `04_backend_specification.md`, `08_infrastructure.md`, `api_contracts.md` and [`reviews/phase8_closeout.md`](reviews/phase8_closeout.md).

Phase 9 executes the complete test matrix (frontend, backend, ML integration, end-to-end, security and performance), establishes the CI quality gate (`TEST-AC-19`), and produces the release-readiness assessment. Do not re-open Phases 2–8; reuse their suites, drills and `.proof/` scripts. Add the remaining product acceptance criteria (`AC-01..14` not already covered by real runs) and decide on rate limiting and session cleanup, which Phase 8 left open.

### Increments after that

Phase 10 (MVP release and documentation): production configuration, deployment verification, backup scheduling, user/developer documentation and a versioned release.

### Definition of done for each increment

- Models and migrations match `05_database_specification.md` exactly; cite the relevant `DB-AC-nn`.
- New code passes `ruff check .` and `ruff format --check .`.
- Frontend changes pass `npm run lint`, `npm run typecheck`, `npm run format:check`, `npm run test:run` and `npm run build`.
- Tests added and executed: at minimum constraint tests (composite FKs, partial unique index, checks), migration round-trip, and repository behaviour. Cite `TEST-AC-nn` where applicable.
- `docker compose up -d --build` still yields a healthy stack and a clean `alembic upgrade head`.
- Rebuild images after code changes; verify, do not assume.

### Testing infrastructure decision (resolved)

`09_testing.md` lists Testcontainers, which needs Docker socket access that the API test container does not have. Option (a) was chosen: integration tests run against the Compose `db` service using the dedicated databases `mogen_test` (entities and constraints) and `mogen_test_migration` (schema and migration round-trip), created and dropped by `backend/tests/db/conftest.py`. The tests drive the real Alembic CLI and never touch the development database. Add a Docker socket mount (option b) only if a future test genuinely needs container control.

---

## 10. Continuing in a new session

### 10.0. Resume in one minute

The state below was verified at the end of Phase 8. **Continuation point:** Phases 2–8 are complete. Phase 9 (comprehensive testing and quality assurance) is next; the viewer/result page, worker lifecycle, pipeline registry, outbox dispatcher, recovery service, result persistence/download path, scene pipeline, generation UI, superseded-result cleanup and scene-workspace retention are the starting point. The working tree is uncommitted (Section 6) — do not reset, stage or commit it.

1. **Do not re-derive the project.** Read this handoff in full, then [`NEXT_SESSION.md`](NEXT_SESSION.md), [`AI_DEVELOPMENT_GUIDE.md`](AI_DEVELOPMENT_GUIDE.md), then Phase 9 of [`10_development_roadmap.md`](specifications/10_development_roadmap.md) and the Phase 9 reading list below.
2. **Check the sandbox policy** (Section 6): Docker needs `danger-full-access`; under `workspace-write` it fails with "Access is denied". If approvals are enabled, retry the exact command with the narrowest wider mode; if they are disabled and Docker is blocked, report the baseline as **blocked**.
3. **Confirm the baseline** (Section 5): `docker compose -f compose.yaml -f compose.gpu.yaml ps -a`, the three worker pings, the `cleanup_scene_workspaces_task` registration in the cleanup worker, the dispatcher/recovery heartbeat files, the object worker's `triposr_model_loaded`/`object_generation_pipeline_ready` logs and the scene worker's `scene_pipeline_ready` log, the backend suite (509 passed), the frontend suite (130 passed), the scene ML suite (75 passed, 1 skipped), the object ML suite (35 passed, 1 skipped), lint, format, `alembic check`, `pip check`, the API health endpoints and the frontend checks. Fix a failing baseline before any new work.
4. **Do the next increment** (Section 9, "Next: Phase 9"): execute the complete testing matrix, add the CI quality gate and produce the release-readiness assessment. Do not re-open Phases 2–8.
5. **Update the handoff and report** in the guide's format (Section 18.4) with the identifiers actually verified.

**Phase 9 reading:** Phase 9 in `10_development_roadmap.md` (tasks 9.1–9.7); `09_testing.md` (all of it, especially Sections 6–21); `04_backend_specification.md`; `08_infrastructure.md`; `api_contracts.md`; [`reviews/phase8_closeout.md`](reviews/phase8_closeout.md) for the current performance baseline, drills and known limitations.

If the stack is already running (it was left healthy), step 3 can start with `docker compose -f compose.yaml -f compose.gpu.yaml ps -a`; the URLs are `http://127.0.0.1:8000` (API), `http://127.0.0.1:5173` (frontend) and `http://127.0.0.1:8000/docs` (Swagger). If Docker is unavailable, report the baseline as **blocked** rather than guessing.

**State left behind by Phase 8:** the API, object-worker and scene-worker images were rebuilt with the Phase 8 code and verified by inspection; the services were recreated from them and left healthy. `.proof/phase8/evidence/` holds the outage/backup/performance evidence (gitignored). `backend/tests/db/conftest.py` now routes test uploads to `/tmp/mogen-test-storage`; keep that isolation. The cleanup worker's hourly retention sweep is active, and the retained `/data/work/scene/379073b3-…` workspace becomes eligible ~2026-11-14 unless `SCENE_WORKSPACE_RETENTION_HOURS` is raised or set to `0`.

### 10.1. State snapshot

| Item | Value |
|---|---|
| Phase / increment | Phases 2–8 complete; **next Phase 9 comprehensive testing and quality assurance** |
| Stack | eleven Compose services; `db`, `redis`, `api`, `cleanup-worker`, `object-worker`, `scene-worker`, `outbox-dispatcher`, `task-recovery`, `frontend` healthy; `migration` and `model-init` Exited (0) |
| Backend suite | **509 passed, 1 warning**: 332 database/API, 169 unit, 8 API-shell |
| Frontend suite | **130 passed** across 22 files, including 35 viewer cases with a real GLB fixture; lint, typecheck, format check and production build clean |
| ML suites | Scene **75 passed, 1 skipped** (the skip is the opt-in real reconstruction); object **35 passed, 1 skipped** plus the opt-in real-model test passing separately |
| Phase 2 close-out | Complete; report in [`reviews/phase2_closeout.md`](reviews/phase2_closeout.md) |
| Phase 3 integration | Complete; auth, dashboard, creation, uploads and details verified; live smoke through the frontend proxy |
| Phase 4 background processing | Complete; report in [`reviews/phase4_closeout.md`](reviews/phase4_closeout.md); outbox, dispatcher, workers, generation API, recovery and cleanup dispatch verified |
| Phase 5 object generation | Complete; report in [`reviews/phase5_closeout.md`](reviews/phase5_closeout.md); real TripoSR GPU worker, standalone GLB proof, transactional result persistence, result/download API and generation UI verified |
| Phase 6 scene reconstruction | Complete; report in [`reviews/phase6_closeout.md`](reviews/phase6_closeout.md); real COLMAP/OpenMVS worker, 11-image standalone proof, live 5-image worker run, failure preservation and scene UI verified |
| Phase 7 viewer and result management | Complete; report in [`reviews/phase7_closeout.md`](reviews/phase7_closeout.md); unified R3F viewer, authorized GLB loading, controls, information panel, download/result management and real Edge proof against object and scene assets |
| Phase 8 reliability, security and optimization | Complete; report in [`reviews/phase8_closeout.md`](reviews/phase8_closeout.md); security/authorization verification, superseded-result cleanup, scene-workspace retention, stale-read fix, Redis/PostgreSQL outage drills, backup/restore drill and performance baseline |
| Quality gates | `ruff check` clean, `ruff format --check` clean (112 backend files), `alembic check` no drift, `pip check` clean; frontend lint/typecheck/format/build clean (bundle ~1.54 MB / 436 kB gzip, Vite chunk warning); backend coverage 89% (Phase 5 measurement; not re-measured in Phase 8) |
| Live API | `/health/*`, `/api/v1/auth/*`, `/api/v1/projects`, `/api/v1/projects/{id}/images` (POST/GET), `.../images/{image_id}/content` (GET), `.../images/{image_id}` (DELETE), `POST /api/v1/projects/{id}/generate`, `GET /api/v1/projects/{id}/status`, `GET /api/v1/projects/{id}/result`, `GET /api/v1/projects/{id}/download` |
| Generation workers | `object-worker` loads the real TripoSR model once and processes `object_generation`; `scene-worker` verifies COLMAP 4.2.1/OpenMVS 2.4.0 and processes `scene_reconstruction` with the real pipeline |
| Outbox dispatcher | Standalone process; claims committed events, publishes to the three queues, retries with backoff, releases expired locks; heartbeat file `/tmp/outbox-dispatcher.heartbeat` |
| Task recovery | Standalone process; requeues/fails stale tasks and detects dispatch stalls; heartbeat file `/tmp/task-recovery.heartbeat` |
| Cleanup worker | Celery 5.7.0 on queue `file_cleanup`, beat poll every 15 s as recovery, targeted `cleanup_storage_task(job_id)` from the dispatcher, hourly `cleanup_scene_workspaces_task` retention sweep, `celery inspect ping` healthy |
| Configuration | `MAX_PAGE_SIZE=100`, `MAX_UPLOAD_SIZE_MB=20`, `MAX_IMAGE_DIMENSION=8192`, `MIN_SCENE_IMAGES=3`, `MAX_SCENE_IMAGES=100`, `CLEANUP_*`, `SCENE_WORKSPACE_RETENTION_HOURS=168`, `SCENE_WORKSPACE_SWEEP_INTERVAL_SECONDS=3600`, `OUTBOX_*`, `TASK_LEASE_SECONDS=300`, `TASK_HEARTBEAT_SECONDS=30`, `TASK_STALE_THRESHOLD_SECONDS=900`, `DISPATCH_STALL_TIMEOUT_SECONDS=900`, `TASK_RECOVERY_*`, `OBJECT_*`, `SCENE_RECONSTRUCTION_ENABLED=true`, `SCENE_COLMAP_EXECUTABLE=/usr/local/bin/colmap`, `SCENE_OPENMVS_BIN_DIR=/usr/local/bin/OpenMVS`, `SCENE_WORK_DIR=/data/work/scene`, `SCENE_MATCHING_STRATEGY=EXHAUSTIVE`, `SCENE_COLMAP_USE_GPU=false` (base; GPU override true), `SCENE_COLMAP_MAX_FEATURES=8192`, `SCENE_COLMAP_CAMERA_MODEL=SIMPLE_RADIAL`, `SCENE_MAX_IMAGE_SIZE=2000`, `SCENE_MAX_THREADS=4`, `SCENE_OPENMVS_USE_CUDA=false`, `SCENE_ENABLE_MESH_REFINEMENT=true`, `SCENE_ENABLE_TEXTURE_GENERATION=true`, `SCENE_MIN_REGISTERED_IMAGES=3`, `SCENE_MIN_REGISTRATION_RATIO=0.5`, `SCENE_MIN_SPARSE_POINTS=100`, `SCENE_MIN_DENSE_POINTS=100`, `SCENE_MAX_TASK_SECONDS=14400`, `SCENE_COLMAP_TIMEOUT_SECONDS=3600`, `SCENE_OPENMVS_TIMEOUT_SECONDS=5400`, `SCENE_EXPORT_TIMEOUT_SECONDS=1800`; frontend mirrors upload limits through `VITE_MAX_UPLOAD_SIZE_MB`, `VITE_MIN_SCENE_IMAGES`, `VITE_MAX_SCENE_IMAGES`, `VITE_TASK_POLL_INTERVAL` |
| Storage | `/data` on the `app_data` volume, shared by the API, cleanup worker and object/scene workers; source keys like `projects/{project_id}/source/{image_id}.jpg`, object results at `projects/{project_id}/results/{task_id}/model.glb`, scene results at `.../scene.glb`; scene workspaces at `/data/work/scene/{task_id}` (pruned after the retention window); `triposr_model_cache:/models` holds the pinned weights/DINO/rembg cache |
| Database content | Phase 7 and Phase 8 smoke/fixture data removed. Pre-existing development data plus the user-created projects remain, and the historical SCENE task `379073b3…` (soft-deleted project) is retained with its diagnostics workspace; do not delete these. |
| Cleanup jobs | Dispatched as `cleanup.requested`; executed by the worker (`PENDING` → `PROCESSING` → `COMPLETED`/`FAILED`), with `attempts` and `last_error`; superseded result files and expired scene workspaces are now producers |
| Git | branch `main`, zero commits; the Phase 2 files are staged and the Phase 2–8 files listed in Section 6 are untracked |
| Frontend | Russian UI, auth, dashboard, creation, uploads, details, generation/scene panel and unified 3D result viewer; 130 tests; lint/typecheck/format/build clean |

### 10.2. Copy-paste prompt

> Working directory: `H:\Study\Univer\projects\mogen`. Read `docs/HANDOFF.md` first, then `docs/AI_DEVELOPMENT_GUIDE.md`, `docs/NEXT_SESSION.md` and Phase 9 of `docs/specifications/10_development_roadmap.md`. Phases 2–8 are complete; do not redo them. Confirm the baseline from Section 5 of the handoff (expect 509 backend tests, 130 frontend tests, 75 scene ML unit tests plus the skipped opt-in real-reconstruction test, 35 object ML unit tests plus the opt-in real-model test, nine healthy services plus `migration` and `model-init` `Exited (0)`, three healthy worker pings, fresh dispatcher/recovery heartbeat files, an object worker that loaded the real TripoSR model, a scene worker that detected COLMAP 4.2.1 and OpenMVS 2.4.0; the Phase 7 real-browser viewer proof and the Phase 8 performance baseline are recorded in `docs/reviews/phase7_closeout.md` and `docs/reviews/phase8_closeout.md`, so do not run a new generation just to re-check delivery; the stack may already be running, so verify rather than assume). Then implement Phase 9 (tasks 9.1–9.7) and close the remaining product acceptance criteria: run the complete frontend/backend/ML/security/performance/E2E matrix, add the committed CI quality gate (`TEST-AC-19`), decide the rate-limiting and session-cleanup open items, and produce the full test report, coverage report, ML/quality report, performance measurements and release-readiness assessment, citing the applicable acceptance criteria. Do not re-open Phases 2–8 and do not change the viewer, result/download contract, outbox or reconstruction pipelines unless a Phase 9 finding genuinely requires it. Do not implement Phase 10+. Follow the Definition of Done and report format from the guide; update `docs/HANDOFF.md` and add a Phase 9 close-out review.

### 10.3. Session-start checklist

1. **Check the sandbox policy first** (Section 6). Docker needs named-pipe access: with `danger-full-access` run it directly; with `workspace-write` the CLI fails with "Access is denied" on `dockerDesktopLinuxEngine`. Never request escalation when the session says approvals are disabled.
2. **Confirm the Section 5 baseline end to end** before writing code:

   ```powershell
   docker compose -f compose.yaml -f compose.gpu.yaml ps -a          # nine healthy; migration/model-init Exited (0)
   docker compose exec cleanup-worker celery -A app.tasks.celery_app:celery_app inspect ping
   docker compose exec object-worker celery -A app.tasks.celery_app:celery_app inspect ping
   docker compose exec scene-worker celery -A app.tasks.celery_app:celery_app inspect ping
   docker compose exec cleanup-worker sh -c 'celery -A app.tasks.celery_app:celery_app inspect registered -d celery@$HOSTNAME --timeout 5'  # includes cleanup_scene_workspaces_task
   docker compose exec outbox-dispatcher cat /tmp/outbox-dispatcher.heartbeat
   docker compose exec task-recovery cat /tmp/task-recovery.heartbeat
   docker compose run --rm --no-deps api pytest > "$env:TEMP\pytest.log" 2>&1
   Get-Content "$env:TEMP\pytest.log" -Tail 2        # 509 passed, 1 warning
   docker compose run --rm --no-deps api ruff check .
   docker compose run --rm --no-deps api ruff format --check .
   docker compose run --rm --no-deps api alembic check
   docker compose run --rm --no-deps api pip check
   docker run --rm mogen-object-worker:dev python -m pytest /opt/object_generation/tests -q  # 35 passed, 1 skipped
   docker run --rm mogen-scene-worker:dev python -m pytest /opt/scene_reconstruction/tests -q # 75 passed, 1 skipped
   docker run --rm mogen-scene-worker:dev python -m scene_reconstruction.standalone --verify-tools
   docker run --rm mogen-frontend:dev npm run lint
   docker run --rm mogen-frontend:dev npm run typecheck
   docker run --rm mogen-frontend:dev npm run format:check
   docker run --rm mogen-frontend:dev npm run test:run   # 130 passed
   docker run --rm mogen-frontend:dev npm run build
   ```

   Also check `http://127.0.0.1:8000/health/ready`, `http://127.0.0.1:5173/` and the proxy (`http://127.0.0.1:5173/api/v1/probe` must return a JSON `NOT_FOUND` 404), the object worker logs (`triposr_model_loaded`, `object_generation_pipeline_ready`) and the scene worker log (`scene_pipeline_ready`). Immediately after `up` a service can still report `health: starting`; the object worker may take 4–5 minutes to load the model (600 s start period). Fix any failure before building on it.
3. **Read the Section 9 "Next: Phase 9" plan** and the Phase 9 reading list in Section 10.0. The documentation is the source of truth, not the current code.
4. **Implement Phase 9 in this order**, citing criteria and adding tests at each step:
   1. 9.1 — frontend tests: unit, component, API interaction, viewer, type check, lint.
   2. 9.2 — backend tests: unit, API, database, authorization, storage, Celery, outbox.
   3. 9.3 — ML integration: real TripoSR, real COLMAP/OpenMVS, GLB validation, performance.
   4. 9.4 — end-to-end user workflows, including failure, retry, previous-result preservation, deletion during processing and worker-interruption recovery.
   5. 9.5 — security testing: authentication, authorization, CSRF, upload validation, user isolation and private assets.
   6. 9.6 — performance testing for both object and scene sizes and GLB loading.
   7. 9.7 — final bug fixes, then the `TEST-AC-19` CI gate and the release-readiness assessment.

   Reuse the Phase 7/8 `.proof/` scripts and the Phase 8 drills; do not re-open Phases 2–8 or change the generation pipelines, the viewer/result/download contract or the outbox unless a Phase 9 finding genuinely requires it. Do not implement Phase 10+.
5. **Re-run the baseline after any change** and confirm the documented counts match.
6. **Update this handoff**: Section 1 state, Section 5 counts and breakdown, Section 7 decisions, Section 8 open items, Section 9 status and next increment, and Section 10 if resume steps change.
7. **Report with the guide's completion format** (Section 18.4) and cite only identifiers that were actually verified.

### 10.4. Working agreement

- Do not stage, commit or rewrite git history unless the user asks. `git diff` against the index shows working-tree changes only.
- Do not recreate the cleanup worker, Celery application, outbox table/repository, generation-task/result models, the Phase 4/5/6 worker lifecycle, the generation/result API or the Phase 7 viewer. They are delivered and tested. Phase 8 hardened them (refreshed terminal reads, superseded-result cleanup, workspace retention, probe scratch directory); Phase 9 tests them; neither replaces them.
- Do not treat Redis as the source of truth: task and outbox state live in PostgreSQL; Redis is only the broker.
- Do not change the TripoSR or COLMAP/OpenMVS pipelines, the viewer, the result/download contract or the outbox unless a Phase 9 finding genuinely requires it; document any such finding before changing behaviour.
- The object generation panel, scene reconstruction panel, authenticated download, unified viewer, superseded-result cleanup and workspace-retention sweep are implemented. Phase 9 adds the comprehensive test matrix and the CI gate.
- `ml/workers/`, `infrastructure/` and `tests/` at the repository root remain placeholders; fill only what Phase 9 actually needs.
- Do not loosen pinned dependencies; the viewer pins Three.js `0.187.0`, React Three Fiber `9.8.2` and Drei `10.7.9`. Record and justify any dependency change.
- Do not modify `docs/specifications/` or `docs/architecture/` to match the implementation; if the two disagree, follow the specification and record the resolution.
- Report checks as passed, failed, skipped, not executed or blocked. Never present an unexecuted check as passed.

### 10.5. Work remaining in Phases 2–8

None. Phase 2 is closed out in [`reviews/phase2_closeout.md`](reviews/phase2_closeout.md), Phase 3 was completed and verified with 84 frontend tests, Phase 4 is closed out in [`reviews/phase4_closeout.md`](reviews/phase4_closeout.md) with 451 backend tests, Phase 5 is closed out in [`reviews/phase5_closeout.md`](reviews/phase5_closeout.md) with 481 backend, 92 frontend and 35 object ML tests plus the real-model proof, Phase 6 is closed out in [`reviews/phase6_closeout.md`](reviews/phase6_closeout.md) with 491 backend, 94 frontend and 74 scene ML tests plus the real reconstruction and live worker proofs, Phase 7 is closed out in [`reviews/phase7_closeout.md`](reviews/phase7_closeout.md) with 491 backend, 130 frontend and the ML suites plus the real Edge viewer proof for both asset types, and Phase 8 is closed out in [`reviews/phase8_closeout.md`](reviews/phase8_closeout.md) with 509 backend, 130 frontend, 75 scene and 35 object ML tests plus the reliability/security drills and the performance baseline.

### 10.6. Next phase

Phase 9 (comprehensive testing and quality assurance): the complete frontend/backend/ML/E2E/security/performance matrix, the `TEST-AC-19` CI quality gate, the remaining product acceptance criteria and the release-readiness assessment, per tasks 9.1–9.7 of `10_development_roadmap.md`.

Deliverables: full test report, code coverage report, ML processing and reconstruction quality reports, performance measurements for small/large objects and small/complex scenes, known-limitations list and release-readiness assessment. Acceptance criteria: all mandatory automated tests pass; both real ML pipelines executed successfully; both workflows pass end-to-end validation; generated GLBs pass validation; all mandatory product acceptance criteria are satisfied; no unresolved critical defects remain.

Open items Phase 9 must close or explicitly decide: `TEST-AC-19` (CI), auth rate limiting (`429`), scheduled session cleanup, scheduled backups and a committed Playwright E2E suite. `M8` (Quality Ready) is only partially achieved until the Phase 9 matrix passes.

Do not re-open Phases 2–8 by re-implementing delivered functionality; the next increment is Phase 9.
