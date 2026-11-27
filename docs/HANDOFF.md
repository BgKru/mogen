# Session Handoff

**Purpose:** everything a new session needs to continue this project without re-deriving context. Read this first, then [`AI_DEVELOPMENT_GUIDE.md`](AI_DEVELOPMENT_GUIDE.md) and the roadmap.

Last updated: 2026-11-27.

> **Continue with:** Phases 2–10 are complete and the MVP is released (1.0.0).
> Post-MVP increments 11 (advisory image-quality analysis), 12 (optional ALIKED +
> LightGlue matching), 13 (advanced object generation) and 14 (mesh/texture
> enhancement) are implemented. **Increment 15 (optional neural scene
> representation, Nerfstudio Splatfacto + Gaussian PLY) is implemented and
> verified**: the released COLMAP + OpenMVS mesh path remains the default; a
> deployment-selected `GAUSSIAN_SPLAT` representation is persisted in the task,
> routed to a dedicated `scene_gaussian_splat` queue, trained by the pinned
> Splatfacto stack in a dedicated worker image, exported to the exact Nerfstudio
> Gaussian PLY dialect, validated independently and rendered by the lazy-loaded
> frontend renderer. Real evidence on the RTX 3060: a 300-iteration smoke PLY
> (8 015 Gaussians, 1.99 MB), a live API task (3 000 iterations, 800 px,
> 208 582 Gaussians, 51.7 MB PLY, PSNR 14.37/SSIM 0.478/LPIPS 0.521), an Edge
> viewer proof and a mesh-vs-splat benchmark. The production 30 000-iteration /
> 1 600 px profile is documented but was not executed end-to-end.
> **Ready-to-paste continuation prompt:** [`NEXT_SESSION.md`](NEXT_SESSION.md).
> **Confirm first:** backend **619 passed**, scene ML **172 passed + 3 skipped**
> (175 collected), object ML **135 passed + 3 skipped** (138 collected),
> image-quality **47 passed**, frontend **161 passed**; Ruff/format clean for
> changed code, `alembic check` clean, Compose base+GPU+splat `config -q` pass;
> the eleven-service base development stack healthy (`migration`/`model-init`
> `Exited (0)`); the splat worker starts with `splat_pipeline_ready` and the
> baked gsplat kernel probe succeeds.
> **Detailed plan:** [`additions/15_implementation_plan.md`](additions/15_implementation_plan.md),
> specification [`additions/15_neural_scene_reconstruction.md`](additions/15_neural_scene_reconstruction.md),
> close-out review [`reviews/increment15_closeout.md`](reviews/increment15_closeout.md).
> **Next increment:** none started. The remaining optional work is a canonical
> scene-worker image rebuild and a full 30 000-iteration artifact measurement;
> do not start increment 16.
> **Copy-paste prompt and resume checklist:** Section 10 and [`NEXT_SESSION.md`](NEXT_SESSION.md).

---

## 1. State

The project is a 3D generation web application (photographs to GLB objects and reconstructed scenes). Phase 0 (specifications and architecture decisions) and Phase 1 (infrastructure foundation) are complete. Phase 2 is complete: the close-out review verified roadmap tasks 2.1–2.10 and the applicable acceptance criteria, found and fixed one `API-AC-15` contract defect (field-validation details now expose `code` instead of `type`) with a regression test, and left no Phase 2 item open. The full evidence table is in [`reviews/phase2_closeout.md`](reviews/phase2_closeout.md). Phase 3 is complete: the React frontend now implements the application shell, registration/login/logout with CSRF-aware API calls and protected routes, the project dashboard, project creation with mode-dependent image selection, previews and sequential uploads, and project details with source-image management; generation was shown only as a disabled placeholder until Phase 5 enabled the real generation action. Increment 2a added the nine SQLAlchemy models and the initial Alembic migration, 2b the repository layer and its FastAPI dependencies, 2c cookie-based authentication with Argon2id, server sessions and signed double-submit CSRF, 2d the project API with ownership authorization (creation, paginated/filtered listing with nested summaries, detail and asynchronous deletion), 2e the storage abstraction (`StorageBackend` plus `LocalStorage`), 2f image upload and listing with content validation, size and dimension limits, SHA-256, object/scene count rules and file rollback, 2g private image content delivery and guarded image deletion, and 2h the cleanup worker that executes the queued `FILE`/`DIRECTORY` cleanup jobs on a dedicated Celery `file_cleanup` queue. A six-service Docker Compose stack ran at the end of Phase 3: PostgreSQL 17.11, Redis 7.4.12, an Alembic migration job, a FastAPI backend, a Celery cleanup worker (beat poll included for development), and a React + Vite frontend that proxies `/api` to the backend. The backend has 339 passing tests and clean lint; the frontend has 84 passing tests across 14 files and passes lint, typecheck, formatting, tests and production build (Section 5). There are no git commits yet. The next step is Phase 4 (generation task creation and lifecycle, transactional outbox and dispatcher, queue separation, worker containers and task recovery), then Phase 5 (TripoSR).

Phase 4 is complete at its roadmap scope: the Celery application now declares the three documented queues (`object_generation`, `scene_reconstruction`, `file_cleanup`), `POST /api/v1/projects/{id}/generate` creates a persistent task, its ordered input snapshot, the `PENDING` project transition and a `generation.requested` outbox event in one PostgreSQL transaction, and a standalone Outbox Dispatcher publishes committed events to Redis with bounded exponential backoff, expired-lock recovery and at-least-once semantics. Dedicated `object-worker`, `scene-worker`, `outbox-dispatcher` and `task-recovery` containers run alongside the existing API, cleanup worker, database, Redis, migration and frontend; each worker consumes only its own queue. `GET /api/v1/projects/{id}/status` returns the persisted project/task state, stage, progress only when real, error fields and result availability. Atomic claim/lease/heartbeat transitions, duplicate-delivery protection, worker interruption recovery through the outbox, dispatch-stall detection and cooperative cancellation are implemented; cleanup jobs are now dispatched through `cleanup.requested` while the beat scan remains the recovery path. The Phase 4 workers deliberately contained no ML pipeline: a claimed task failed honestly with `WORKER_UNAVAILABLE` until Phase 5 registered the TripoSR pipeline. Backend suite at the end of Phase 4: **451 passed** (294 database/API, 149 unit, 8 API-shell); frontend suite: **84 passed**; the ten-service stack was healthy.

Phase 5 is complete at its roadmap scope. A dedicated `mogen-object-worker:dev` image carries PyTorch 2.14.1/CUDA 12.6, TripoSR at pinned commit `d26e3318…`, pinned weights whose `model.ckpt` SHA-256 is verified, `torchmcubes` built for SM 86 and rembg. A one-shot `model-init` service populates the persistent `triposr_model_cache` volume; the worker runs with offline HF flags and loads the model once at startup. `generate_object_task` now resolves the real TripoSR pipeline through the existing Phase 4 `register_pipeline(TaskType.OBJECT, …)` hook; the pipeline decodes and preprocesses the snapshot image, runs inference, extracts and validates the mesh, exports a self-contained GLB with vertex colours, validates the container/geometry/appearance, and hands the asset back for transactional persistence. `TaskExecutionService.complete_with_result` clears the previous current result, inserts the new current row and completes the task and project in one transaction; a failed or cancelled attempt preserves the previous result and file. `GET /api/v1/projects/{id}/result` and `GET /api/v1/projects/{id}/download` serve the current validated GLB with ownership checks and the documented headers, and the project details page now starts generation, polls real status/stages, displays stable errors, supports retry and offers the authenticated download. The mandatory standalone proof produced a 1 528 660-byte GLB with 38 241 vertices / 76 315 faces that loaded in Three.js with zero glTF Validator errors; the live worker completed a real task in about 8 s with a warm model. Backend suite: **481 passed** (313 database/API, 160 unit, 8 API-shell); frontend suite: **92 passed** across 15 files; ML unit suite: **35 passed, 1 skipped** (recorded as 32 at the time; corrected during Phase 8) plus the opt-in real-model test **1 passed**; coverage 89%; the eleven-service stack is healthy with `migration` and `model-init` `Exited (0)`. Phase 6 is complete at its roadmap scope. A dedicated `mogen-scene-worker:dev` image carries COLMAP 4.2.1 (official CUDA-enabled image, digest-pinned), OpenMVS 2.4.0 built unmodified from commit `58117204…`, OpenCV 4.12 built from source, CGAL 6.0.1 and the Python orchestration package. The worker verifies every external executable at startup and logs `scene_pipeline_ready`; it registers `run_colmap_pipeline` through the existing Phase 4 `register_pipeline(TaskType.SCENE, …)` hook and executes the documented COLMAP/OpenMVS sequence with real stage reporting, heartbeats, cancellation, task-scoped workspaces and checkpoint reuse. The pipeline validates the input set (format, duplicates, dimensions), inspects every sparse model, selects one by measured properties, runs dense reconstruction, meshing, refinement and texturing, converts the scene with TransformScene, repacks the OBJ/MTL/PNG set into one self-contained GLB with embedded textures, validates it independently, and persists it through the existing `complete_with_result` transaction as `scene.glb`. The scene UI on the existing details page starts reconstruction, polls persisted stages, shows stable errors, retries and offers the authenticated download. The mandatory standalone proof reconstructed all 11 Sceaux Castle photographs (11/11 registered, 8 018 sparse points, 332 303 dense points, 16 539 vertices / 28 991 triangles) into a 959 504-byte GLB with one embedded texture that passed the Khronos glTF Validator with 0 errors and 0 warnings; a live worker task also completed and downloaded the same validated asset with the task-status lifecycle. Backend suite: **491 passed** (316 database/API, 167 unit, 8 API-shell); frontend suite: **94 passed** across 15 files; scene ML unit suite: **74 passed, 1 skipped** (the skip is the opt-in real-reconstruction test); the eleven-service stack is healthy with `migration` and `model-init` `Exited (0)`. Phase 7 (viewer and result management) has not started.

Phase 7 is complete at its roadmap scope. The unified Three.js viewer (React Three Fiber `9.8.2`, Drei `10.7.9`, Three.js `0.187.0`, pinned exactly) is an independent `frontend/src/features/model-viewer/` module used by the new protected route `/projects/{id}/result`. It reads the current result through the existing `GET /result` API, downloads the GLB through the authenticated `GET /download` endpoint, loads it through a temporary blob URL and `GLTFLoader`, centres it without altering the asset, and disposes geometry, materials and textures on result change and unmount. OrbitControls provide rotate, zoom and pan; the toolbar adds reset, fit-to-view, grid, background and fullscreen. The information panel shows project name, generation type, status, source-image count, format, file size, creation date and mesh/vertex/polygon/material/texture counts. Empty, processing and failed-regeneration states are explicit and keep the previous successful result visible. Both a real TripoSR object (23 039 vertices / 45 983 triangles, vertex colours) and the real COLMAP/OpenMVS scene (202 493 vertices / 297 813 triangles, one embedded texture) loaded and were inspected in the application viewer in Edge; both downloads matched the stored SHA-256. Frontend suite: **130 passed** across 22 files, including 35 viewer cases with a real GLB fixture.

Phase 8 is complete at its roadmap scope: authentication and file-security verification, generation reliability and recovery, data consistency, resource management, the performance baseline and infrastructure reliability (tasks 8.1–8.8). No Phase 9 work was started during Phase 8, and no Phase 2–7 behaviour was re-opened. Six findings became fixes: (1) a **stale identity-map read** in `TaskExecutionService` could hide a cancellation request written after the worker claimed the task, so a project deleted mid-generation could still register a result — terminal transitions now refresh the task row (`get_for_update(populate_existing=True)`, `get_refreshed`); (2) **superseded result files were never deleted** after a successful regeneration, so every retry leaked a GLB — registration now queues a `FILE` cleanup job and `cleanup.requested` event in the same transaction; (3) **failed scene workspaces accumulated without bound** — a retention sweep now queues expired terminal workspaces for deletion and logs temporary-storage usage; (4) **scene toolchain probes wrote OpenMVS log files into the worker's CWD** — `verify_toolchain` now runs `--help` in a throwaway directory; (5) the **backup/restoration procedure was undocumented** — now in `docs/operations/` with a runnable consistency checker; (6) **backend API tests could write uploads into the live `/data` volume** — test clients now default to `/tmp/mogen-test-storage`. Phase 8 added 18 backend cases (509 total) and one scene-ML case (75 + the skipped opt-in test), live Redis/PostgreSQL outage drills, a PostgreSQL + file-storage backup/restore drill with identical counts and SHA-256, and a measured performance baseline. The full evidence table is in [`reviews/phase8_closeout.md`](reviews/phase8_closeout.md).

Phase 9 is complete at its roadmap scope (tasks 9.1–9.7): the full frontend, backend, ML, end-to-end, security and performance matrix was executed and the two Phase 8 open items were decided and implemented. Auth rate limiting is now an in-process fixed-window limiter for `POST /auth/login` and `POST /auth/register` (`AUTH_RATE_LIMIT_*`, 10/minute, `429 RATE_LIMITED` with `Retry-After`); Redis was deliberately not used so the API still accepts requests during a broker outage (`INF-AC-23`). `cleanup_sessions_task` now runs hourly on the cleanup worker's beat and removes only expired/revoked sessions (`SESSION_CLEANUP_INTERVAL_SECONDS`). A repository Playwright suite (`e2e/`, 17 tests; working tree, not yet git-committed) covers registration/login/logout, project creation/listing/deletion, both real generation workflows with viewer interaction and download, failure/retry, deletion during processing, two-user isolation, CSRF and upload validation. The `TEST-AC-19` gate is present as three GitHub Actions workflow files in the working tree (`ci.yml` fast gate, `e2e.yml` browser, `ml-validation.yml` self-hosted GPU); every command was executed locally but no remote CI runner exists in this environment. Frontend coverage tooling was added (`@vitest/coverage-v8`), with new DTO-mapper and API-client interceptor tests. Final counts: **525 backend tests** (339 database/API, 178 unit, 8 API-shell; 87.80% line coverage), **148 frontend tests** (24 files; 71.47% line coverage), **75 scene ML + 1 skipped**, **35 object ML + 1 skipped**, **17/17 E2E**. Real evidence: opt-in TripoSR real-model test passed; real 11-image COLMAP/OpenMVS reconstruction completed in 406.2 s through the worker; object generation 7.6 s for both a 480×360 and a 987×1481 photograph; viewer load ~1.0 s; Khronos glTF Validator 0 errors/0 warnings for object and 100-image scene assets. No critical defect was found; the viewer, result/download contract, outbox and reconstruction pipelines were not changed. The full evidence table and the known limitations (per-process rate limiter, frontend business-logic coverage shortfall, dataset-dependent scene E2E, unobserved remote CI) are in [`reviews/phase9_closeout.md`](reviews/phase9_closeout.md).

Phase 10 is complete at its roadmap scope (tasks 10.1–10.6): the MVP is packaged and released as 1.0.0. `compose.prod.yaml` builds runtime images behind a pinned nginx TLS reverse proxy (only 80/443 published), sets `APP_ENV=production`, disables API docs, enforces Secure cookies and the production CSRF secret, separates Celery beat from the cleanup worker, and adds a scheduled backup service. The production stack was built, deployed and verified: registration/login, project creation, uploads, a real TripoSR object task, a real 11-image COLMAP/OpenMVS reconstruction (7.7 min), the browser viewer, authenticated GLB download, failure/retry and delete-during-processing. The full Playwright suite passed **17/17 against the production HTTPS stack**, the live auth limiter returned 429 with `Retry-After` after 10 attempts, API docs answered 404, and only the proxy ports were reachable. Data preservation was proved by identical counts (2 users, 19 projects, 17 tasks, 10 results, 141 images) and an unchanged current-result SHA-256 before and after deployment. The scheduled backup service ran and its dump/archive were restored into a scratch database and storage tree with matching counts and SHA-256. `docs/deployment.md`, `docs/developer_guide.md`, `docs/user_guide.md`, `docs/api.md`, `docs/releases/v1.0.0.md` and [`reviews/phase10_closeout.md`](reviews/phase10_closeout.md) record the configuration, procedures, versions and evidence. One production-packaging defect was found and fixed: Kombu's Redis transport imports `packaging`, which the isolated scene-worker venv lacked while the development image obtained it through `pytest`; `packaging==26.3` is now pinned explicitly and the API/scene images rebuilt. The viewer, result/download contract, outbox and reconstruction pipelines were not changed. `M9` (MVP Released) is achieved.

Phase 10 was the last MVP phase. Post-MVP improvements belong to Section 11 (Future Development) of the roadmap; the first post-MVP increment is described next, and later increments have not been started.

**Post-MVP increment 11 verification and rebuild (2026-11-25).** Both worker
images were rebuilt (`mogen-object-worker:dev` and `mogen-scene-worker:dev` now
import `/opt/image_quality`). Verified: 47 image-quality tests in both images,
object ML 39 passed + 1 skipped, scene ML **82 passed + 1 skipped** (the
documentation's earlier "83 passed" was off by one; corrected in the addendum),
backend 526 passed, Ruff clean for changed code. A real OBJECT task and a real
SCENE task completed with `image_quality.status = "OK"`; the opt-in real TripoSR
test passed and the real COLMAP/OpenMVS proof completed. Calibration
observations (studio-backdrop shadow clipping; bright-sky highlight clipping)
were recorded without retuning thresholds. Evidence: Sections 13.5–13.7 of the
increment-11 addendum.

**Post-MVP increment 13: advanced object generation (2026-11-25).** TripoSR
remains the production default and regression baseline. `ml/object_generation/`
now has a typed generator contract (`generator_base.py`), an explicit allowlist
factory (`generator_factory.py`), a TripoSR adapter and an opt-in Stable Fast 3D
adapter (`sf3d/`). SF3D weights are manifest-verified and loaded from a separate
`/models/sf3d` cache; its conflicting dependencies are installed into
`/opt/sf3d-site` (PYTHONPATH) by a dedicated `sf3d` Dockerfile target, so the
TripoSR runtime is untouched. Output normalization plus a textured GLB
export/validation path preserve UVs, PBR material and the embedded base-colour
texture; the TripoSR vertex-colour path is unchanged. Result metadata gains a
`generator` block with the adapter name, pinned source/model revisions, timings,
preprocessing profile and measured peak CUDA bytes; a pre-inference fallback to
TripoSR is opt-in and recorded. `compose.sf3d.yaml` switches the single object
worker policy and adds `sf3d-model-init`. The API image has no ML dependency and
no public API, frontend, task-lifecycle, viewer or result contract changed.
Hunyuan3D is blocked after the licence/territory (EU/UK/South Korea exclusion),
12 GB VRAM and PyTorch 2.5.1/CUDA 12.4 conflict review; its settings validate
and refuse to initialise it. Verification: object ML **76 passed + 3 skipped**,
real TripoSR inference **1 passed**, backend **552 passed**, Ruff clean for
changed files, Khronos glTF Validator **0 errors/0 warnings** on the textured
fixture, benchmark TripoSR **12/12** runs (median 5.545 s, peak 4.45 GB).
**Completed 2026-11-26:** the gated repository was opened with a classic read
token, `/models/sf3d` was populated and checksum-verified, the real SF3D tests
passed (2/2), a live SF3D task completed through the API (664 464-byte textured
GLB, 2.648 s inference, peak 5.44 GB), the Edge viewer loaded it with 2 textures
in 1.19 s, and the benchmark recorded TripoSR **12/12** (median 7.595 s) versus
SF3D **12/12** (median 2.714 s, all textured, peak 5.48 GB). The real run exposed
and fixed three defects: the `sf3d` package shadowing the upstream checkout under
`pytest`, missing DINOv2/CLIP caches in the offline worker, and a `texture_baker`
wheel compiled without CUDA kernels. Full evidence:
[`reviews/increment13_closeout.md`](reviews/increment13_closeout.md), Section 8.

**Post-MVP increment 14: mesh/texture enhancement (2026-11-26).** A shared CPU
package `ml/mesh_enhancement/` now provides before/after metrics, conservative
cleanup, area-weighted normals, a guarded/injectable simplification boundary and
the enhancement manifest. Object generation runs the optional stage between the
normalized generator output and GLB export: cleanup + normal validation are on by
default; xatlas UV generation and deterministic vertex-colour baking are opt-in
and produce an embedded base-colour texture with a PBR metallic-roughness
material; a generator texture is preserved, not rebaked; simplification safely
skips because no quadric simplifier is pinned; AI texture is a disabled protocol
with output validation. Scene post-processing is off by default, mutates geometry
in place, preserves OpenMVS UVs/atlases/materials/transforms, and never repeats
`RefineMesh`/`TextureMesh`; scene UV/AI generation is rejected by configuration.
Validators now check `NORMAL`, finite UVs, PBR factors/references and embedded
image integrity while keeping legacy vertex-colour and scene assets valid.
Result metadata gains a compact `enhancement` block; no public API, frontend,
database, persisted stage, viewer or download contract changed. Verification:
backend **573 passed**, object **135 passed + 3 skipped**, scene **136 passed +
2 skipped**, image-quality **47 passed**, frontend **173 passed**, real TripoSR
**1 passed**, Ruff/format clean, `pip check` clean, Khronos **0 errors/0
warnings** on both enhanced fixtures, Three.js/Edge viewer load passed, live
object (cleanup+normals) and live scene (post-process enabled) tasks completed.
The 4 096 MB soft memory budget was found too low for the worker's resident
model and raised to 8 192 MB. Full evidence:
[`reviews/increment14_closeout.md`](reviews/increment14_closeout.md).

**Post-MVP increment 12: advanced feature matching (2026-11-25).** `COLMAP SIFT`
remains the production default and fallback. `ml/scene_reconstruction/` now has a
small feature-backend contract (`feature_matching.py`), validated profiles
(`feature_profiles.py`) and an opt-in ALIKED-N16 + LightGlue adapter
(`neural_features.py`) that imports keypoints/matches through pycolmap 4.2.1 and
runs `pycolmap.verify_matches` before the existing COLMAP mapper. Pair
generation is deterministic (exhaustive/sequential, bounded); checkpoints are
gated by `colmap/feature_manifest.json` covering image hashes, backend/profile,
models, parameters, pairing, resize, verification and runtime versions;
recoverable neural failures can fall back to a clean SIFT database with the
reason and actual backend recorded. Diagnostics gain a compact `features` block;
no public API, frontend, result contract or OpenMVS stage changed. The scene
image now pins torch 2.14.1, torchvision 0.29.2, kornia 0.9.2, opencv-python
5.1.0.95, matplotlib 3.11.2, pycolmap 4.2.1 and LightGlue commit `5a650c44…`,
with ALIKED/LightGlue checkpoints baked under `/opt/neural_models` and
checksum-verified. Verification: scene suite **117 passed + 2 skipped** (119
collected), actual-binary interoperability **1 passed**, backend **541 passed**, image-quality
**47 passed**, `pip check` clean, Ruff clean for changed code; a live GPU scene
task completed (11/11, 34/34 verified pairs, no fallback) and a no-GPU fallback
drill rebuilt SIFT and completed. The five-variant Sceaux benchmark kept SIFT as
the default (no demonstrated quality improvement from neural matching on that
scene). One pre-existing clock-initialisation defect was found and fixed during
final verification (direct stage calls could falsely trip the task budget after
~4 h of host uptime). Full evidence: [`reviews/increment12_closeout.md`](reviews/increment12_closeout.md).

**Post-MVP increment: advisory image-quality analysis (2026-11-24).** `ml/image_quality/` now implements [`additions/11_image_quality_analysis.md`](additions/11_image_quality_analysis.md) as a shared, deterministic analyzer built only on the already-pinned NumPy/Pillow (no dependency added, no Python OpenCV). Scene reconstruction runs it inside the existing `IMAGE_PREPARATION` stage after dataset preparation and before COLMAP, attaches the report to `ReconstructionDiagnostics`, writes `diagnostics/image_quality.json`, and reports pHash/SSIM near-duplicate candidates without removing or rejecting any photograph. Object generation analyzes the decoded original before TripoSR preprocessing and adds the report to `run.json` and the result metadata. Thresholds are provisional, validated and configurable through `IMAGE_QUALITY_*` (`.env.example`, Compose worker environments); advisory failures record `QUALITY_ANALYSIS_UNAVAILABLE`, only an explicitly required analysis raises `QUALITY_ANALYSIS_FAILED`, and no new public endpoint, frontend workflow or persisted stage was introduced. Verification: **47** image-quality tests, **82 passed + 1 skipped** scene ML cases, **39 passed + 1 skipped** object ML cases, **526 passed** backend cases, Ruff clean for the changed code (four untouched object test modules carry a pre-existing `I001`). Both worker images were rebuilt on 2026-11-25 and now import `/opt/image_quality`; a real OBJECT and a real SCENE task completed with `image_quality.status = "OK"`, and the opt-in real TripoSR and COLMAP/OpenMVS checks passed. Full details, the corrected scene-test count and the live evidence are in Sections 13.5–13.7 of the addendum.

**Post-MVP increment: neural scene reconstruction (2026-11-27).** [`additions/15_neural_scene_reconstruction.md`](additions/15_neural_scene_reconstruction.md) is implemented as an **optional** Gaussian-splat representation beside the released mesh path. `SCENE_REPRESENTATION` (`mesh` default, `gaussian_splat` opt-in) requires `SCENE_SPLAT_ENABLED=true` and `SCENE_OUTPUT_FORMAT=PLY`; the representation and method are persisted in `GenerationTask.parameters`, so retries/recovery are never re-targeted by a later setting change. Splat tasks route to `scene_gaussian_splat`; each scene worker registers one capability and rejects the other representation. The splat path runs the existing image preparation/feature/sparse/undistortion stages, then `SPLAT_DATASET_PREPARATION` → `SPLAT_TRAINING` → `SPLAT_EXPORT`; no OpenMVS or GLB stage runs. `ml/scene_reconstruction/` gained `colmap_model.py`, `nerfstudio_dataset.py` (upstream transforms.json/sparse PLY, resize-aware intrinsics and a reprojection self-check), `nerfstudio_runner.py`/`splat_train_entry.py` (pinned 1.1.5 Splatfacto in a controlled subprocess), `splat_exporter.py`/`splat_validator.py` (exact `ns-export` dialect, atomic publish, independent validation), `neural_pipeline.py` (VRAM admission, checkpoint manifest/reuse), `benchmark_splat.py`, `requirements-splat.txt` and `Dockerfile.splat` (verified scene base + isolated `/opt/splat-site`, baked LPIPS weights and compiled gsplat kernels). Backend: `ResultFormat.PLY` with migration `7c5d9a1b4e20`, representation-aware outbox payload/routing, `scene_methods.py`, extension/MIME-aware download, and a splat-capability worker bootstrap. Frontend: format dispatch, lazy `@mkkellogg/gaussian-splats-3d` renderer, splat statistics and disposal. Verified: backend **619**, scene ML **172 + 3 skipped** (175 collected), image-quality **47**, frontend **161**; real Splatfacto smoke (300 iters/800 px: 8 015 Gaussians, 1 989 312 B, PSNR 13.41/SSIM 0.643/LPIPS 0.739), live API task (3 000 iters/800 px: 208 582 Gaussians, 51 729 930 B, PSNR 14.37/SSIM 0.478/LPIPS 0.521), independent re-validation of the downloaded PLY, Edge viewer proof (SPLAT, 208 582, controls, `.ply` download) and a mesh-vs-splat benchmark. The production 30 000-iteration/1 600 px profile was **not** executed end-to-end; the canonical mesh-worker rebuild was replaced by a documented derived runtime image. Corrections found by this increment: the splat renderer needs `sharedMemoryForWorkers: false` without COOP/COEP; the documented frontend baseline was 148 tracked tests, not 173; `pytest -q` must not be passed twice. Full evidence and defects: [`reviews/increment15_closeout.md`](reviews/increment15_closeout.md).

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
├── e2e/                      Playwright browser suite (Phase 9, working tree)
├── .github/workflows/        CI quality gate, E2E and ML-validation workflows (Phase 9)
├── compose.yaml              development stack, eleven services
├── compose.gpu.yaml          GPU reservation for the object and scene workers
├── .dockerignore             ML worker build context
├── .env.example              environment template
└── README.md
```

What is real: `backend/`, `frontend/`, `ml/object_generation/`, `ml/scene_reconstruction/`, `e2e/`, `.github/workflows/`, `compose.yaml`, `compose.gpu.yaml`, `.dockerignore`, `.env.example`, all of `docs/`.
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
| `backend/app/core/rate_limit.py` | In-process fixed-window auth limiter (`AUTH_RATE_LIMIT_*`) |
| `backend/app/services/session_cleanup_service.py` | Hourly deletion of expired/revoked sessions |
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
| `ml/object_generation/generator_base.py` | Object-generator protocol, preprocessing capabilities and normalized result type (increment 13) |
| `ml/object_generation/generator_factory.py` | Explicit generator allowlist, process-wide adapter cache and blocked-name errors (increment 13) |
| `ml/object_generation/normalization.py` | Appearance-aware output normalization: vertex colours or UV/texture, rejects lossy output (increment 13) |
| `ml/object_generation/sf3d/` | Stable Fast 3D adapter, manifest-verified loader, controlled weight initializer (increment 13) |
| `ml/object_generation/requirements-sf3d.txt` | Isolated SF3D dependency set installed into `/opt/sf3d-site` (increment 13) |
| `ml/object_generation/benchmarks/run_benchmark.py` | Reproducible generator benchmark with median/p95, VRAM, mesh and failure metrics (increment 13) |
| `ml/object_generation/enhancement.py` | Object enhancement orchestration: cleanup, normals, simplification, UV/bake, PBR, fallback, memory budget and metadata (increment 14) |
| `ml/object_generation/texture_baking.py` | xatlas unwrap, vectorised vertex-colour rasterisation, embedded PBR atlas, material normalisation (increment 14) |
| `ml/object_generation/texture_generation.py` | AI texture backend protocol, lazy disabled backend and output validation (increment 14) |
| `ml/object_generation/benchmarks/run_enhancement_benchmark.py` | Reproducible baseline/cleanup+bake benchmark with GLB validation facts (increment 14) |
| `ml/object_generation/standalone.py` | Mandatory standalone inference/GLB proof CLI |
| `ml/object_generation/exceptions.py` | Stable object-generation and enhancement error codes |
| `ml/object_generation/tests/` | 135 passed + 3 skipped cases plus the opt-in real-model integration test and GLB fixtures |
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
| `ml/scene_reconstruction/enhancement.py` | Conservative post-reconstruction scene processing; preserves graph/transforms/materials/textures (increment 14) |
| `ml/scene_reconstruction/benchmark_enhancement.py` | Reproducible baseline/cleanup+normals/simplification-attempt scene benchmark (increment 14) |
| `ml/scene_reconstruction/standalone.py` | Standalone proof and `--verify-tools` CLI |
| `ml/scene_reconstruction/tests/` | 172 passed + 3 skipped cases (175 collected) including the neural-representation coverage, plus the opt-in real Splatfacto test |
| `ml/scene_reconstruction/README.md` | Image layout, pinned versions, pipeline, proof and license notes |
| `ml/image_quality/` | Shared advisory image-quality analyzer (NumPy/Pillow): per-image technical findings, scene-only pHash/SSIM near-duplicate candidates, validated `IMAGE_QUALITY_*` configuration and 47 unit tests |
| `ml/mesh_enhancement/` | Shared CPU metrics, conservative cleanup, area-weighted normals, guarded simplification and enhancement manifest (increment 14) |
| `ml/scene_reconstruction/feature_matching.py` | Feature-backend contract, SIFT adapter, factory, deterministic pair generator and checkpoint manifest (increment 12) |
| `ml/scene_reconstruction/feature_profiles.py` | Validated SIFT/ALIKED profiles, pinned model identifiers/checksums and backend/profile cross-checks |
| `ml/scene_reconstruction/neural_features.py` | ALIKED-N16 + LightGlue adapter: lazy runtime, coordinate restoration, pycolmap import/verification, atomic database replacement, VRAM/OOM handling |
| `ml/scene_reconstruction/download_neural_models.py` | Build-time download + SHA-256 verification of the baked ALIKED/LightGlue checkpoints |
| `ml/scene_reconstruction/benchmark_features.py` | Reproducible five-variant feature-matching benchmark |
| `ml/scene_reconstruction/requirements-neural.txt` | Scene-worker-only pinned neural dependency set |

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

**Production overlay (1.0.0).** `compose.prod.yaml` layers on `compose.yaml` (plus `compose.gpu.yaml` for GPU) and builds `mogen-api:1.0.0`, `mogen-object-worker:1.0.0`, `mogen-scene-worker:1.0.0`, `mogen-frontend:1.0.0` (nginx production stage) and `mogen-backup:1.0.0`. Only `frontend` publishes `${PUBLIC_HTTP_PORT:-80}`/`${PUBLIC_HTTPS_PORT:-443}`; PostgreSQL, Redis, the API and workers are internal. The stack also runs a dedicated `beat` service and a `backup` service (`BACKUP_INTERVAL_SECONDS`, default daily). Start it with `docker compose --env-file .env.production -f compose.yaml -f compose.prod.yaml -f compose.gpu.yaml up -d --build`; see [`deployment.md`](deployment.md). The development stack is the one currently running in this workspace.

The development application images run as unprivileged users (`appuser` uid 1000 for the API/cleanup workers, `ubuntu` uid 1000 for the object and scene workers, `node` uid 1000 for the frontend). The object worker's base image already provides UID 1000 as `ubuntu`; the scene worker's COLMAP base image does as well, so the shared `app_data` volume stays writable by all. In the production overlay the backend and ML images keep the same UID 1000 users, while the nginx frontend starts its master as root to bind 80/443 and read the mounted TLS key (its worker processes run as `nginx`), and the backup container runs as root to read `/data` and write the host backup mount. These two exceptions are documented in `docs/deployment.md`; do not mount the Docker socket into any of them.

Frontend routes: `/`, `/login`, `/register`, `/dashboard`, `/projects/new`, `/projects/{id}`, `/projects/{id}/result`. The dashboard, creation, details and result routes are protected and redirect unauthenticated users to `/login`; the backend still enforces authentication and ownership on every call. The UI language is Russian. The browser reaches the API through the same-origin `/api` proxy, so the session cookie and CSRF flow work without CORS.

Backend endpoints: `GET /health/live`, `GET /health/ready` (503 when PostgreSQL is unreachable), `GET /health/dependencies` (always 200, reports `degraded`). Swagger at `http://127.0.0.1:8000/docs`.

The cleanup worker consumes jobs from Redis DB 1 (the broker) and processes them against PostgreSQL and the shared `app_data` volume; it never opens a port. Its beat scan still runs every `CLEANUP_POLL_INTERVAL_SECONDS` (default 15) as the recovery path, but project and image deletion now insert a `cleanup.requested` outbox event in the same transaction and the Outbox Dispatcher publishes it to the `file_cleanup` queue for immediate targeted processing. The same worker also runs the hourly scene-workspace retention sweep (`cleanup_scene_workspaces_task`, `SCENE_WORKSPACE_SWEEP_INTERVAL_SECONDS`), which queues terminal workspaces older than `SCENE_WORKSPACE_RETENTION_HOURS` (default 168; `0` disables pruning) as `DIRECTORY` cleanup jobs and logs `workspace_usage`. Structured JSON logs include `project_id`, `cleanup_job_id` and `operation`.

The object worker is a real single-image generator environment: by default it loads the pinned TripoSR model once at startup, verifies the cached weights, registers `run_object_pipeline` through `register_pipeline`, and executes preprocessing, inference, normalization, optional mesh/texture enhancement (cleanup + normals by default; baking opt-in) and GLB export/validation. With `compose.sf3d.yaml` the same service runs the opt-in Stable Fast 3D target instead: it verifies the SF3D manifest/checksums, loads the pinned model, and writes a textured GLB; the queue, task type and result contract are unchanged. The scene worker is now a real COLMAP/OpenMVS environment: it verifies COLMAP 4.2.1 and OpenMVS 2.4.0 at startup, registers `run_colmap_pipeline`, executes the documented reconstruction sequence in a task-scoped workspace, and persists the repacked, validated GLB through `complete_with_result`; optional post-processing is off by default and preserves OpenMVS textures. The Outbox Dispatcher and Task Recovery run as independent processes; neither serves HTTP.

**Opt-in SF3D overlay (increment 13).** `compose.sf3d.yaml` layers on the development stack and rebuilds the single `object-worker` from the `sf3d` Dockerfile target (`mogen-object-worker:sf3d`), sets `OBJECT_GENERATOR=sf3d` and adds a one-shot `sf3d-model-init` service. The default `compose.yaml` stack is untouched and keeps TripoSR. The SF3D source lives at `/opt/sf3d-src` (not `/opt/sf3d`: the upstream checkout has no `sf3d/__init__.py`, so a directory named `sf3d` is shadowed by the ComfyUI root `__init__.py` through `/opt` on `PYTHONPATH`), its extra dependencies live in `/opt/sf3d-site`, and its weights live in `/models/sf3d` inside the existing model-cache volume.

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

> **Increment-14 note (2026-11-26):** the commands below are the Phase 7
> baseline; the current counts are object ML **135 passed + 3 skipped** (138
> collected), scene ML **136 passed + 2 skipped** (138 collected), image-quality
> **47 passed**, backend **573 passed**, frontend **173 passed**, actual-binary
> feature interoperability **1 passed**, real TripoSR **1 passed**, `pip check`
> clean. The scene suite collects **119** cases before increment 14 and the
> increment-12/13 docs' "119 passed + 2 skipped" over-counted by two; the correct
> pre-increment baseline was **117 passed + 2 skipped**. The object/scene suites
> must be run in their worker images (or a host mount with
> `PYTHONPATH=/work/ml:/opt/triposr:/opt`). Enhancement is covered by
> `ml/mesh_enhancement/` tests through both worker suites and by the benchmark
> scripts; see [`reviews/increment14_closeout.md`](reviews/increment14_closeout.md).

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
docker compose exec cleanup-worker sh -c 'celery -A app.tasks.celery_app:celery_app inspect registered -d celery@$HOSTNAME --timeout 5'  # includes cleanup_sessions_task
docker compose run --rm --no-deps api pytest        # 619 passed
docker compose run --rm --no-deps api pytest --cov=app --cov-report=term-missing # coverage recorded in Phase 9; neural paths are worker-only
docker compose run --rm --no-deps api ruff check .  # clean
docker compose run --rm --no-deps api ruff format --check . # clean
docker compose run --rm --no-deps api alembic check # no schema drift
docker compose run --rm --no-deps api pip check     # no broken requirements
docker run --rm mogen-object-worker:dev python -m pytest /opt/object_generation/tests # 135 passed, 3 skipped
docker run --rm mogen-splat-worker:dev /opt/venv/bin/python -m pytest /opt/scene_reconstruction/tests # 172 passed, 3 skipped
docker run --rm mogen-splat-worker:dev /opt/venv/bin/python -m pytest /opt/image_quality/tests # 47 passed
docker run --rm mogen-scene-worker:dev python -m scene_reconstruction.standalone --verify-tools # COLMAP 4.2.1 + OpenMVS 2.4.0
docker run --rm mogen-frontend:dev npm run lint       # clean
docker run --rm mogen-frontend:dev npm run typecheck  # clean
docker run --rm mogen-frontend:dev npm run format:check # pre-existing CRLF files only; changed files individually clean
docker run --rm mogen-frontend:dev npm run test:run   # 161 passed
docker run --rm mogen-frontend:dev npm run test:coverage # recorded in Phase 9
docker run --rm mogen-frontend:dev npm run build      # succeeds
```

The enhancement benchmark commands are:

```powershell
docker run --rm -v "${PWD}/ml:/work/ml:ro" -v "${PWD}/.proof:/proof" `
  -e PYTHONPATH=/work/ml:/opt/triposr:/opt -w /work/ml/object_generation `
  mogen-object-worker:dev python -m object_generation.benchmarks.run_enhancement_benchmark `
  --object /proof/increment13/live/triposr-gpu-20261125-214838/model.glb `
  --repetitions 3 --texture-resolution 512 `
  --output /proof/increment14/benchmark/enhancement-object.json
docker run --rm -v "${PWD}/ml:/work/ml:ro" -v "${PWD}/.proof:/proof" `
  -e PYTHONPATH=/work/ml:/opt -w /work/ml/scene_reconstruction `
  mogen-scene-worker:dev /opt/venv/bin/python -m scene_reconstruction.benchmark_enhancement `
  --scene /proof/scene-check-iq.glb --repetitions 2 `
  --output /proof/increment14/benchmark/enhancement-scene.json
```

The production release was verified separately on 2026-11-11; the reproducible
checks are:

```bash
docker compose --env-file .env.production -f compose.yaml -f compose.prod.yaml config -q
docker compose --env-file .env.production -f compose.yaml -f compose.prod.yaml -f compose.gpu.yaml up -d --build
docker compose --env-file .env.production -f compose.yaml -f compose.prod.yaml -f compose.gpu.yaml ps -a
curl -k https://localhost/health/ready
curl -k https://localhost/health/dependencies
curl -k -o /dev/null -w "%{http_code}\n" https://localhost/docs        # 404
cd e2e && E2E_BASE_URL=https://localhost E2E_IGNORE_HTTPS_ERRORS=true node node_modules/playwright/cli.js test
docker compose --env-file .env.production -f compose.yaml -f compose.prod.yaml run --rm backup --once
```

Expected: production services healthy with `migration`/`model-init` `Exited (0)`,
only `frontend` publishing 80/443, E2E **17/17**, and a backup directory with
`database.dump`, `app-data.tgz`, `SHA256SUMS` and `manifest.json`. The E2E run
needs `AUTH_RATE_LIMIT_ENABLED=false` and `E2E_SCENE_IMAGES`; restore the default
limiter afterwards. Full evidence is in
[`reviews/phase10_closeout.md`](reviews/phase10_closeout.md).

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

Current suite breakdown: 525 backend cases = 339 database/API integration cases under `tests/db` (they create their own scratch databases), 178 unit cases and 8 API-shell cases. Phase 10 added no new backend cases: it packages the same behaviour and its deployment/backup checks are integration evidence, not unit tests. Phase 9 added 16 cases: rate-limiter unit 6, auth rate-limit API 4, session cleanup 3, session-cleanup Celery route/beat 1 and new settings 2. Phase 8 added 18 cases: superseded-result cleanup 2, reliability regressions 3, scene-workspace retention 9, dispatcher crash-after-publish 1, cross-session CSRF binding 1, workspace-retention Celery schedule 1 and retention settings 1. Phase 6 added 10 cases: scene generation/task integration 3 and scene settings 7. Backend coverage is **87.80%** of 3 508 statements (428 missed).

ML suites: **35** object-generation unit cases plus the opt-in real TripoSR test, and **75** scene-reconstruction cases plus one skipped opt-in real-reconstruction test in `ml/scene_reconstruction/tests`. The scene tests cover dataset validation, duplicate/format/dimension rejection, COLMAP and OpenMVS command construction, COLMAP database statistics and pair-id decoding, sparse-model inspection/selection, GLB validation, OBJ→GLB repack, process timeouts/cancellation, preflight (including the no-log-in-CWD probe), checkpoint reuse and the real toolchain check.

Frontend suite: **148** cases across 24 files (Vitest + React Testing Library), with **71.47%** line coverage. Phase 9 added the DTO-mapper (11) and API-client interceptor (7) cases and the `@vitest/coverage-v8` tooling. Phase 7 added the unified viewer module and the result page: 35 viewer cases (bounds, cleanup, loader, toolbar, viewer states, information panel and result page) plus a real triangle GLB fixture parsed with the same `GLTFLoader`; `ProjectDetailsPage` and `GenerationPanel` gained viewer-navigation assertions. Run it with `docker run --rm mogen-frontend:dev npm run test:run` after rebuilding the image, or mount only `frontend/src` for iteration (Section 6).

The browser verification is a repository Playwright suite (working tree, not yet git-committed) in [`e2e/`](../e2e/README.md) (17 tests, installed Edge locally, Chromium in CI). It covers registration/login/logout, project creation/listing/deletion, both real generation workflows (viewer load, orbit/zoom/fit/reset, download size and `glTF` magic), failure/retry, deletion during processing, two-user isolation, CSRF and upload validation. It passed **17/17 against the production HTTPS stack** on 2026-11-11 (`E2E_BASE_URL=https://localhost`, `E2E_IGNORE_HTTPS_ERRORS=true`, the Sceaux dataset, `AUTH_RATE_LIMIT_ENABLED=false`). The Phase 7 out-of-tree proof remains in `.proof/viewer-tools/`; Phase 9 performance evidence is in `.proof/phase9/` and Phase 10 deployment evidence in `.proof/phase10/evidence/`; the reports are [`reviews/phase9_closeout.md`](reviews/phase9_closeout.md) and [`reviews/phase10_closeout.md`](reviews/phase10_closeout.md).

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

**pytest's final summary line can vanish through a pipe.** When the pass count matters, redirect the whole run to a file (`... > "$env:TEMP\run.log" 2>&1`) and read the tail; `Tee-Object` or `Select-Object -Last N` sometimes drops the final "N passed" line. Exit code 0 plus the file is the reliable evidence. Also **never pass `-q` twice**: both `pyproject.toml` files already set it, so `pytest -q` is `-qq` and suppresses the summary entirely.

**Neural (splat) image traps (increment 15).** The gsplat JIT build needs a host compiler and Python headers (`build-essential`, `python3.12-dev`), CUDA 13 CCCL (`nvidia-cuda-cccl`, for `nv/target`), and a *consistent* CUDA 13.0 toolchain (`nvidia-cuda-nvcc`, `-crt`, `-nvvm` all 13.0.88; 13.5 components emit PTX 9.5 that ptxas 13.0 rejects). It also needs an unversioned `libcudart.so` symlink in `$CUDA_HOME/lib`, `nvcc` on `PATH` (gsplat probes `nvcc` by name) and `MAX_JOBS` bounded on a shared host. Real training additionally needs `scikit-learn`, `lpips` with cached AlexNet weights (`TORCH_HOME`) and `open3d` for sparse-point loading. Splatfacto checkpoints use `_model.gauss_params.*` keys and need narrow NumPy safe-globals for `torch.load(weights_only=True)`; quaternions are unnormalized. The frontend renderer needs `sharedMemoryForWorkers: false` unless the app sends COOP/COEP headers. Finally, **rebuilding an image does not update running containers**: recreate every changed service (`up -d --force-recreate`) or the dispatcher/workers keep executing the old code and route a splat task to the mesh pipeline.

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

**The ML worker images must be rebuilt for increment 11.** Both Dockerfiles now copy `ml/image_quality` to `/opt/image_quality`. A mount-only check (`-v "${PWD}/ml:/work/ml"`) proves the code but not the image; `docker compose build object-worker scene-worker` is required before `up`, otherwise `object_generation.config` and `scene_reconstruction.config` fail to import the shared analyzer at worker startup. The object worker also reloads the 1.7 GB model after the rebuild (4–5 minutes).

**The scene image now carries a CUDA 13 neural stack (increment 12).** `torch==2.14.1` from PyPI resolves to the CUDA 13 wheels (`+cu130`, torchvision `+cu132`) and pulls roughly 3.5 GB of NVIDIA libraries; the final image is ~20.7 GB (image ID `sha256:9302854844a9…`) and a neural-layer rebuild takes ~25–30 minutes (the COLMAP/OpenMVS layers stay cached). The driver here supports CUDA 13.4. `pip check` must stay clean: LightGlue declares `opencv-python` and `matplotlib`, so both are installed as pinned direct dependencies even though the adapter only needs `cv2` transitively. Do not install `opencv-python-headless` instead: it does not satisfy that metadata and `pip check` fails.

**Neural checkpoints are baked, not downloaded at task time.** `download_neural_models.py` populates `/opt/neural_models/hub/checkpoints` during the build and verifies both SHA-256 values; `neural_features.verify_model_files()` re-verifies before every neural stage. `TORCH_HOME=/opt/neural_models` is set in the image. If the worker reports `NEURAL_MODEL_UNAVAILABLE`, the image predates the bake or a checksum changed; rebuild rather than letting torch.hub download.

**pycolmap 4.2.1 is deliberately the exact COLMAP version.** The adapter imports images and keypoints through `pycolmap.Database`/`import_images`, writes matches, and calls `pycolmap.verify_matches`; the pinned `colmap mapper` then consumes the database. Do not hand-write SQLite tables and do not upgrade pycolmap independently of the COLMAP base image. The interoperability test (`tests/test_feature_interop.py`, `RUN_FEATURE_INTEROP_TEST=1`) is the guard; a mocked database is not acceptable evidence.

**Do not run the neural suite or interop test in a GPU-less container unless the test explicitly targets CPU.** The code supports `auto` → CPU, but SIFT fallback on a CPU-only host needs `SCENE_COLMAP_USE_GPU=false` (otherwise COLMAP's GPU extractor fails). An 8-thread CPU SIFT extraction at 8 192 features was OOM-killed on this host during a drill; the worker's configured `SCENE_MAX_THREADS=4` fits.

**The pipeline clock is initialised in `__init__` (fixed 2026-11-25).** Stage methods are callable directly by tests; with `_started=0.0` a call after ~4 h of host uptime falsely raised `TOOL_TIMEOUT`. `reconstruct()` still resets the clock. Do not reintroduce a zero default.

**A neural workspace can be large.** `features.npz` holds keypoints/descriptors for all images (roughly 1 MB per image at 2 048 keypoints), and the database plus sparse/dense stages follow. Successful tasks delete their workspace; failed ones keep it for diagnostics/retention as before.

**The SF3D source must not live in a directory named `sf3d`.** The upstream checkout has no `sf3d/__init__.py`, so `/opt/sf3d/sf3d` is only a namespace package; the ComfyUI root `__init__.py` at `/opt/sf3d/__init__.py` is a regular package and wins when `/opt` is on `PYTHONPATH` (`import sf3d` then tries `comfy.model_management`). The image keeps the source at `/opt/sf3d-src` and puts that on `PYTHONPATH`. Do not "fix" this by deleting the root `__init__.py` at build time unless the pin changes; the current layout is intentional and covered by the build preflight.

**SF3D weights are gated; access was granted on 2026-11-26.** Anonymous requests return 401 and the cached OAuth token used in the first attempt returned 403. A **classic read token** created on the account that accepted the Stability AI Community License returns 200 for `config.yaml` and `model.safetensors`; it is stored as `HF_TOKEN` in the gitignored `.env` and is consumed only by the opt-in `sf3d-model-init` service. Never bypass the gate with a mirror, and never log the token. The initializer also seeds `facebook/dinov2-large` and open_clip `ViT-B-32`/`laion2b_s34b_b79k`, because the offline worker instantiates both at model start; without them the first task fails with `LocalEntryNotFoundError`.

**This host runs the development stack with the GPU overlay implicit (2026-11-26).** The gitignored `.env` sets `COMPOSE_FILE=compose.yaml;compose.gpu.yaml`, so a plain `docker compose ps|up|run` already includes the NVIDIA device reservation, `OBJECT_DEVICE=cuda:0`, `OBJECT_ALLOW_CPU_FALLBACK=false` and `SCENE_COLMAP_USE_GPU=true`; `docker compose config` shows them without `-f` flags. The base `compose.yaml` stays CPU-capable for other hosts — remove that line (or pass an explicit `-f` list without the overlay) for a CPU-only run. `TEXTURE_ENHANCEMENT_DEVICE` remains `cpu` deliberately: this build rejects any other value, so mesh cleanup, UV unwrap and baking are not GPU stages. Torch installed on the Windows host (3.15, cu134) is not used by the project; all ML runs inside the pinned CUDA images, and host-native ML execution is unsupported.

**`pytest` can shadow the upstream `sf3d` package with MOGEN's own subpackage (fixed 2026-11-26).** The object-generation module is itself named `sf3d`, and `pytest` inserts its directory on `sys.path` (the module's `pythonpath = ["."]` setting), so a plain `import sf3d` resolved `object_generation/sf3d` and failed with a relative-import error. Upstream is a namespace package, so path order alone cannot win. `loader.import_sf3d_system()` registers `/opt/sf3d-src/sf3d` under `sf3d` explicitly (dropping only MOGEN's shadowing module) before importing `SF3D`; `SF3D_SOURCE_ROOT` overrides the path. Real-model tests and the worker both go through it.

**The SF3D dependency set is isolated on purpose.** `requirements-sf3d.txt` is installed with `--no-deps --target /opt/sf3d-site`; it deliberately does not apply upstream's `numpy 1.26.4` / `transformers 4.42.3` / `trimesh 4.4.1` pins, which conflict with the torch 2.14.1 / numpy 2.3.5 runtime. `gpytoolbox` is pinned to `0.3.8` because upstream `0.2.0` has no CPython 3.12 wheel; only the optional remesh paths call its API. Do not install these into the TripoSR site-packages.

**The SF3D image build needs the PyTorch devel base.** Both native extensions (`texture_baker`, `uv_unwrapper`) compile in the `sf3d-native-build` stage on `pytorch/pytorch:2.14.1-cuda12.6-cudnn9-devel`; the first build pulls ~10 GB and the host download was slow (20–35 min) and re-pulled after a cache prune. Do not prune the builder cache immediately before an SF3D rebuild. `TORCH_CUDA_ARCH_LIST=8.6` and `USE_NATIVE_ARCH=0` keep the wheels portable and bounded, and **`USE_CUDA=1` is mandatory** (fixed 2026-11-26): upstream `setup.py` defaults `USE_CUDA` to `torch.cuda.is_available()`, which is False in the GPU-less builder, so without it the wheel registers only the CPU kernels and every textured task fails with `rasterize` unavailable for CUDA. The final image imports `SF3D`, `TextureBaker` and `Unwrapper` as a build preflight; that preflight does not prove the CUDA dispatch table, so check `torch._C._dispatch_dump("texture_baker_cpp::rasterize")` for a `CUDA:` row after a rebuild.

**Textured GLB validation is an increment-13 extension, not a relaxation of OBJ-AC-10.** TripoSR assets still must carry `COLOR_0`; the validator additionally accepts a textured PBR material only when `TEXCOORD_0` and an embedded `baseColorTexture` image (bufferView, no `uri`) are present. A GLB with neither still fails with `GLB_VALIDATION_FAILED`. The exporter keeps the TripoSR vertex-colour normalization unchanged; the textured path never flattens to vertex colours.

**The enhancement memory budget must exceed the resident model.** The increment-14 soft budget was initially 4 096 MB; the first live object task correctly skipped enhancement because the worker process peak RSS (model + backend + mesh) was ~4.4 GB. `MESH_ENHANCEMENT_MAX_MEMORY_MB` now defaults to **8 192** for both workers. Do not lower it to a value near the Python/model baseline, and remember the metric is process peak RSS, not per-operation allocation.

**xatlas unwrap dominates optional texture baking.** On the retained 76 313-face TripoSR mesh, a 512 px bake took ~38 s: xatlas was ~39 s and the vectorised colour rasteriser <1 s. A per-face Python rasteriser or a 76k-call Pillow polygon pass was much slower and was replaced. Baking is off by default; do not enable it by default without budget/quality evidence.

**The canonical image rebuild can be slow or blocked.** The object Dockerfile needs the ~6.4 GB PyTorch devel layer for `torchmcubes`/SF3D native wheels; this host pulled it at <0.3 MB/s. The scene Dockerfile recompiles OpenCV/OpenMVS when its build cache is absent. During increment-14 verification the runtime code was proven in derived images (`FROM mogen-object-worker:dev` / `FROM mogen-scene-worker:dev` plus the changed source), and the canonical Dockerfile changes were only Compose-validated. Do not present a derived image as a completed canonical build; rerun the canonical build when the layer pull/cache is practical.

**Scene normals must not use trimesh's lazy SciPy fallback.** The scene image has no SciPy, so `mesh.vertex_normals` falls back to a dense O(vertices × faces) computation (tens of seconds on a 16k-vertex scene). `ml/mesh_enhancement/normals.py` computes area-weighted normals in NumPy and stores them in the trimesh cache; `measure_mesh` only reads an existing cache. Keep this path for scene post-processing. Scene post-processing is off by default and never unwraps/rebakes OpenMVS textures.

**`.env` files must stay BOM-free and CRLF-consistent.** Editing them with Windows PowerShell `Set-Content -Encoding utf8` adds a BOM and can mix line endings; this happened during increment 14 and was repaired. Use the edit/write tools or .NET `UTF8Encoding($false)` when a script must rewrite them.

**One GPU-heavy model at a time, including benchmarks.** The running object worker holds its model in VRAM (~5.6 GB) while host desktop applications hold another 5–7 GB. A second TripoSR run (the benchmark) produced transient CUDA allocator OOM warnings during warm-up; stop `object-worker` (`docker compose stop object-worker`) before a benchmark or an SF3D drill, and restart it afterwards. The benchmark's measured runs succeeded; warm-up runs are excluded from its statistics.

**The benchmark counts only measured runs.** `benchmarks/run_benchmark.py` runs one warm-up per image and excludes it from the success/latency aggregates; a generator that is disabled, blocked or missing weights is recorded as a variant with its error code, never as a fabricated success. Its `--generators` list is explicit.

**Ruff on a read-only mount needs `--no-cache`.** `ruff check`/`ruff format` create `.ruff_cache` under the working directory and fail with "Read-only file system" when the source tree is mounted `:ro`. Add `--no-cache` (and `--no-cache` to `format --check`) or mount writable. The worker image's Ruff also reports four pre-existing `I001` issues in untouched `ml/object_generation/tests/*.py`; they are not caused by increment 11.

**The pytest summary line can vanish through a pipe.** Use `--collect-only -q` and sum the per-file counts, or redirect to a file and inspect the exit code, when the exact pass count matters. This was already true for the Phase 10 suite and still applies.

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

**Auth rate limiting is in-process.** `FixedWindowRateLimiter` lives in `app/core/rate_limit.py` and is created per FastAPI app (`app.state.auth_rate_limiter`); it is not shared between processes. `POST /auth/login` and `POST /auth/register` return `429 RATE_LIMITED` with `Retry-After` after `AUTH_RATE_LIMIT_ATTEMPTS` (10) hits per `AUTH_RATE_LIMIT_WINDOW_SECONDS` (60), keyed by path and socket peer. Ordinary backend API tests disable it via `API_TEST_SETTINGS`; the dedicated tests enable it per client. Do not add a Redis dependency to the API to share counters: the API must keep working during a broker outage (`INF-AC-23`).

**Session cleanup runs on the cleanup worker's beat.** `cleanup_sessions_task` is scheduled every `SESSION_CLEANUP_INTERVAL_SECONDS` (3600) and deletes only `expires_at <= now` and `revoked_at IS NOT NULL` rows. It never logs out an active session. Trigger it manually with `docker compose exec cleanup-worker celery -A app.tasks.celery_app:celery_app call cleanup_sessions_task`; the worker logs `session_cleanup_finished`.

**The backend image contains the tests.** `docker compose run --rm --no-deps api pytest` uses the image copy of `app/` and `tests/`, not the host tree. After changing backend code or tests, rebuild `mogen-api:dev` (fast) before running the suite; use `docker run -v "${PWD}/backend:/app" …` only for iteration/linting. A formatted host file can differ from the image until the rebuild.

**Frontend coverage needs a container copy-out.** `npm run test:coverage` writes `/app/coverage`. Do not bind-mount that directory: Vitest removes it and fails with `EBUSY`. Create a named container, start it, then `docker cp mogen-coverage:/app/coverage <host>` (the Phase 9 scripts do this). To iterate without rebuilding, mount both `frontend/src` and `frontend/vitest.config.ts`.

**Repository E2E suite (working tree).** Run `node node_modules/playwright/cli.js test` from `e2e/` (Windows `npx` misquotes the CLI). Use `http://localhost:5173`, not `127.0.0.1` (CSRF origin), and disable the auth limiter for the stack (`AUTH_RATE_LIMIT_ENABLED=false`) because the suite registers many users from one address in seconds. The real scene test needs `E2E_SCENE_IMAGES` pointing at a directory of overlapping photographs; without it the test skips. Tests are serial (`workers: 1`) because they share one stack and one GPU.

**CI workflow files are present but no CI remote exists here.** `.github/workflows/ci.yml` is the fast gate (it now also validates the production overlay, the nginx image and `nginx -t`); `e2e.yml` runs the browser smoke suite on a hosted runner and both real workflows on a self-hosted GPU runner; `ml-validation.yml` runs the real ML proofs. Validate the YAML and run the commands locally; do not claim automatic remote execution was observed.

**Production overlay requires Compose ≥ 2.24.** `compose.prod.yaml` uses `!reset []` (remove the development host ports) and `!override` (replace the Vite frontend port). Older Compose versions reject those tags. The overlay also uses required-variable syntax (`${CSRF_SECRET:?…}`), so `docker compose config` fails until `.env.production` (or an explicit `--env-file`) supplies `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `CSRF_SECRET` and `PUBLIC_ORIGIN`.

**The production frontend is the TLS reverse proxy.** `frontend` builds the nginx `production` stage and is the only published service. It serves the static SPA, redirects HTTP to HTTPS, proxies `/api/` and `/health/`, returns 404 for `/docs`/`/openapi.json`, and mounts `TLS_CERT_DIR` read-only at `/etc/nginx/certs` (`tls.crt`, `tls.key`). The self-signed helper is for local verification only; a real deployment installs a trusted certificate. HSTS is deliberately omitted for `localhost`/`127.0.0.1` so the development Vite server keeps working in the same browser profile.

**The nginx proxy overwrites `X-Forwarded-For`.** It must not use `$proxy_add_x_forwarded_for`: the API trusts forwarded headers for the auth rate limiter, so appending a client-supplied value would let a caller rotate the limiter key. The proxy sets `X-Real-IP` and `X-Forwarded-For` to `$remote_addr`; `uvicorn` runs with `--proxy-headers --forwarded-allow-ips=*` because nginx is the only reachable peer.

**The scene worker runtime needs `packaging`.** Kombu's Redis transport imports `packaging.version`. The development image got it transitively from `pytest`, which hid the gap in every earlier suite; the first production scene-worker runtime crashed with `ModuleNotFoundError: No module named 'packaging'`. `packaging==26.3` is now an explicit `backend/requirements.txt` pin. If the scene worker restarts with this error, the image predates the fix; rebuild it.

**Re-pulling the PyTorch devel base is slow.** `mogen-object-worker:1.0.0` builds `torchmcubes` from `pytorch/pytorch:2.14.1-cuda12.6-cudnn9-devel` (a ~10 GB pull) and the devel image is not retained. Avoid unnecessary object-worker rebuilds; the object runtime and scene images are large. The production object image was built before the `packaging` pin but already contains packaging 26.3 (verified).

**The database password changed locally.** The existing `postgres_data` volume was initialised with the development default; Phase 10 changed the `app` role password to the production secret so the same volume could be deployed. A gitignored `.env` now carries `POSTGRES_PASSWORD`/`DATABASE_URL` for the development stack, and `.env.production` carries the production values. Do not delete either file; a fresh deployment initialises the volume from `.env.production`.

**Production verification artefacts are local.** `.env.production`, `infrastructure/certs/tls.{crt,key}` and `.backups/` are gitignored. The `backup` service writes timestamped directories with `database.dump`, `app-data.tgz`, `SHA256SUMS` and `manifest.json`; a host directory is not an off-host backup, so copy it away. The production E2E run needs `E2E_BASE_URL=https://localhost`, `E2E_IGNORE_HTTPS_ERRORS=true` (self-signed certificate), `E2E_SCENE_IMAGES`, and `AUTH_RATE_LIMIT_ENABLED=false` on the stack; restore the limiter afterwards.

**The committed `plants-1.jpg` fixture is a PNG.** The backend and frontend correctly reject the extension/content mismatch, so E2E uses real JPEGs (`animal-2.jpg`, `car-1.jpg`, `car-2.jpg`) for failure scenarios and the performance script uploads it as `plants-1.png` with `image/png`. Do not rename Phase 5 test data casually.

**Git state.** Branch `main` has three commits (`0349404`, `356ff10`, `7aa7269`); the working tree was clean when Phase 9 began and the Phase 9 changes are currently unstaged/untracked. Earlier phase notes below describe the historical index state. Phase 6 added `ml/scene_reconstruction/` (Dockerfile, requirements, config, dataset, runners, selector, mesh processor, exporter, validator, pipeline, standalone, tests, viewer validator), `backend/app/tasks/scene_pipeline.py`, `backend/tests/db/test_scene_generation.py`, `backend/tests/unit/test_scene_settings.py`, `docs/reviews/phase6_closeout.md`, `ml/object_generation/viewer/validate_glb.mjs`, the `.proof/` proof scripts (gitignored) and modified `backend/app/core/config.py`, `backend/app/services/result_service.py`, `backend/app/tasks/scene_pipeline.py`, `compose.yaml`, `compose.gpu.yaml`, `.env.example`, `.dockerignore`, `docs/HANDOFF.md`, `docs/NEXT_SESSION.md` and the frontend generation panel, labels and tests. The increment 2a–2h files (`app/db/models/`, `app/repositories/`, `app/services/`, `app/tasks/`, `app/storage/`, `app/schemas/`, the auth, project and image endpoints, `app/api/dependencies.py`, the initial migration, `tests/db/`, `tests/unit/test_repository_dependencies.py`, `tests/unit/test_security.py`, `tests/unit/test_project_validation.py`, `tests/unit/test_image_validation.py`, `tests/unit/test_storage.py`, `tests/unit/test_celery_config.py`) are untracked and not yet in the index. The Phase 2 close-out added `docs/reviews/phase2_closeout.md` (untracked) and modified the already staged `backend/app/main.py` and `backend/tests/api/test_errors.py`. Phase 3 added the frontend modules under `frontend/src/{app/layout,app/providers,app/router,features,pages,shared,test}` (untracked) and modified `frontend/package.json`, `frontend/package-lock.json`, `.env.example`, `compose.yaml` and the frontend README. Phase 4 added the new backend modules under `backend/app/{services,tasks,schemas,api/v1/endpoints}`, the new tests listed in Section 3, `docs/reviews/phase4_closeout.md` (all untracked) and modified `backend/app/core/config.py`, `backend/app/api/dependencies.py`, `backend/app/api/v1/router.py`, `backend/app/services/project_service.py`, `backend/app/services/image_service.py`, `backend/app/tasks/celery_app.py`, `backend/app/repositories/{outbox_repository,task_repository}.py`, `backend/tests/unit/test_celery_config.py`, `backend/tests/db/conftest.py`, `.env.example` and `compose.yaml`. Phase 5 added `ml/object_generation/` (Dockerfile, requirements, pipeline, tests, testdata, viewer), `backend/app/tasks/object_pipeline.py`, `backend/app/services/result_service.py`, `backend/app/schemas/result.py`, `backend/app/api/v1/endpoints/results.py`, `backend/tests/db/test_result_{api,persistence}.py`, `backend/tests/unit/test_result_service.py`, `compose.gpu.yaml`, `.dockerignore`, `docs/reviews/phase5_closeout.md` and the frontend `features/generation/` modules (all untracked), and modified `backend/app/tasks/generation_tasks.py`, `backend/app/services/task_execution_service.py`, `backend/app/api/dependencies.py`, `backend/app/api/v1/router.py`, `backend/app/core/config.py`, `backend/app/repositories/task_repository.py`, `.env.example`, `compose.yaml`, the frontend shared API/types/labels/config and `frontend/src/pages/ProjectDetailsPage/`. Do not assume a clean history; `git diff` against the index shows working-tree changes only. Do not stage, commit or rewrite history unless the user asks.

**Phase 7 git state.** Phase 7 added everything under `frontend/src/features/model-viewer/` and `frontend/src/pages/ModelViewerPage/`, `docs/reviews/phase7_closeout.md`, the `.proof/` browser-proof scripts (gitignored) and modified `frontend/package.json`, `frontend/package-lock.json`, `frontend/src/app/router/AppRouter.tsx`, `frontend/src/pages/ProjectDetailsPage/ProjectDetailsPage.tsx` (and its test), `frontend/src/features/generation/components/GenerationPanel.tsx` (and its test), `frontend/src/features/projects/components/ProjectCard.tsx`, `frontend/src/shared/api/queryKeys.ts`, `docs/HANDOFF.md` and `docs/NEXT_SESSION.md`. All Phase 3–7 files remain untracked; the Phase 2 files are staged.

**Phase 8 git state.** Phase 8 added `backend/app/services/workspace_retention_service.py`, `backend/tests/db/test_workspace_retention.py`, `backend/tests/db/test_reliability_regressions.py`, `docs/operations/backup_restore.md`, `docs/operations/verify_current_results.py`, `docs/reviews/phase8_closeout.md`, the `.proof/phase8/` drill and measurement scripts (gitignored, plus `.proof/phase8.jpg` and `.proof/phase8-big.jpg`) and modified `backend/app/services/task_execution_service.py`, `backend/app/repositories/task_repository.py`, `backend/app/tasks/cleanup_tasks.py`, `backend/app/tasks/celery_app.py`, `backend/app/core/config.py`, `backend/app/core/logging.py`, `backend/tests/db/conftest.py`, `backend/tests/db/test_result_persistence.py`, `backend/tests/db/test_outbox_dispatcher.py`, `backend/tests/db/test_auth_api.py`, `backend/tests/unit/test_celery_config.py`, `backend/tests/unit/test_config.py`, `ml/scene_reconstruction/preflight.py`, `ml/scene_reconstruction/tests/test_preflight.py`, `compose.yaml`, `.env.example`, `.dockerignore`, `README.md`, `docs/HANDOFF.md` and `docs/NEXT_SESSION.md`. It also removed 60 generated OpenMVS log files from `ml/scene_reconstruction/` and 54 test-created orphan storage directories from `/data/projects`. No migration was added (no schema change). All Phase 3–8 files remain untracked; the Phase 2 files are staged.

**Phase 9 git state.** Phase 9 added `backend/app/core/rate_limit.py`, `backend/app/services/session_cleanup_service.py`, `backend/tests/unit/test_rate_limit.py`, `backend/tests/db/test_auth_rate_limit.py`, `backend/tests/db/test_session_cleanup.py`, `frontend/src/shared/api/mappers.test.ts`, `frontend/src/shared/api/client.test.ts`, the repository `e2e/` suite (working tree), `.github/workflows/{ci,e2e,ml-validation}.yml`, `docs/reviews/phase9_closeout.md` and the gitignored `.proof/phase9/` evidence/scripts. It modified `backend/app/core/config.py`, `backend/app/api/dependencies.py`, `backend/app/api/v1/endpoints/auth.py`, `backend/app/main.py`, `backend/app/tasks/celery_app.py`, `backend/app/tasks/cleanup_tasks.py`, `backend/tests/db/conftest.py`, `backend/tests/unit/test_celery_config.py`, `backend/tests/unit/test_config.py`, `compose.yaml`, `.env.example`, `frontend/package.json`, `frontend/package-lock.json`, `frontend/vitest.config.ts`, `.gitignore`, `docs/HANDOFF.md`, `docs/NEXT_SESSION.md` and `ml/object_generation/viewer/package-lock.json` was left untouched (the validator's `npm ci` only created gitignored `node_modules`). No migration was added. All Phase 9 files are unstaged; the repository has three commits and the pre-Phase 9 tree was clean.

**Phase 10 git state.** Phase 10 added `compose.prod.yaml`, `frontend/nginx/default.conf`, the nginx `production` stage in `frontend/Dockerfile`, `infrastructure/backup/{Dockerfile,backup.sh}`, `infrastructure/certs/README.md`/`.gitkeep`, `infrastructure/scripts/generate-self-signed-cert.{ps1,sh}`, `.env.production.example`, `VERSION`, `docs/deployment.md`, `docs/developer_guide.md`, `docs/user_guide.md`, `docs/api.md`, `docs/releases/v1.0.0.md`, `docs/reviews/phase10_closeout.md` and the gitignored `.proof/phase10/` evidence. It modified `backend/app/core/config.py` (version 1.0.0), `backend/requirements.txt` (`packaging==26.3`), `.env.example`, `.gitignore`, `.github/workflows/ci.yml`, `e2e/playwright.config.ts`, `e2e/README.md`, `README.md`, `frontend/README.md`, `frontend/package.json`, `frontend/package-lock.json`, `docs/operations/backup_restore.md`, `docs/HANDOFF.md` and `docs/NEXT_SESSION.md`. Local-only, gitignored files created during deployment verification: `.env`, `.env.production`, `infrastructure/certs/tls.crt`/`tls.key` and `.backups/`. The production images are tagged `:1.0.0`; production containers were stopped and the development stack restored. No migration was added; no viewer, result/download, outbox or reconstruction-pipeline code was changed.

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
| COLMAP SIFT remains the default scene feature backend; ALIKED + LightGlue is opt-in through validated worker settings, never through the API or a per-project choice | `ml/scene_reconstruction/feature_matching.py`, `backend/app/core/config.py`, `12_advanced_feature_matching.md` Section 7 |
| The neural adapter uses pycolmap 4.2.1's public database/import/verification API directly instead of adding the HLoc package; the actual-binary interoperability test is mandatory | `ml/scene_reconstruction/neural_features.py`, `tests/test_feature_interop.py` |
| Feature checkpoints are valid only when `feature_manifest.json` matches image hashes, backend/profile, models, parameters, pairing, resize, verification and runtime versions; a change invalidates extraction, matching and dependent outputs | `ml/scene_reconstruction/feature_matching.py`, `pipeline.py` |
| Neural failures fall back to a clean SIFT rebuild only when configured and recoverable; fallback reason and actual backend are always visible in diagnostics | `ml/scene_reconstruction/pipeline.py`, `exceptions.py`, `diagnostics.py` |
| Neural checkpoints are baked into the scene image under `TORCH_HOME` and checksum-verified; the worker never downloads models at task time | `download_neural_models.py`, `Dockerfile` |
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
| Auth endpoints use an in-process fixed-window limiter (10/min per path and peer), returning `429 RATE_LIMITED` with `Retry-After`; Redis is deliberately not a dependency of the API request path | `backend/app/core/rate_limit.py`, `backend/app/api/dependencies.py`, `backend/app/main.py` |
| Expired and revoked sessions are deleted hourly by `cleanup_sessions_task` on the cleanup worker; active sessions are never touched | `backend/app/services/session_cleanup_service.py`, `backend/app/tasks/cleanup_tasks.py`, `backend/app/tasks/celery_app.py` |
| The fast CI gate is present in the working tree (backend/frontend/Compose); browser and real-ML pipelines are separate workflows requiring a hosted/self-hosted runner | `.github/workflows/ci.yml`, `e2e.yml`, `ml-validation.yml` |
| Browser E2E is a repository Playwright suite (unstaged); it disables the auth limiter for the run and skips the scene test when no dataset is provided | `e2e/`, `e2e/README.md` |
| Frontend coverage uses the official v8 provider; type-only modules are excluded | `frontend/vitest.config.ts`, `frontend/package.json` |
| Production is a `compose.prod.yaml` overlay: runtime image targets, `APP_ENV=production`, `DEBUG=false`, API docs off, Secure cookies, required secrets, only nginx 80/443 published, bounded json-file logs | `compose.prod.yaml`, `docs/deployment.md`, `INF-AC-20` |
| The production frontend is a pinned nginx image serving the Vite build and terminating TLS; `/docs`/`/openapi.json` are explicit 404s; HSTS is skipped for localhost | `frontend/Dockerfile`, `frontend/nginx/default.conf` |
| The proxy overwrites `X-Forwarded-For` with the peer address because the API trusts forwarded headers for the rate limiter | `frontend/nginx/default.conf`, `compose.prod.yaml` |
| Celery beat is a dedicated service in production; the cleanup worker no longer runs `--beat` | `compose.prod.yaml`, `08_infrastructure.md` Section 7 |
| Backup is a scheduled `mogen-backup:1.0.0` service writing pg_dump + `/data/projects` archives with checksums and a manifest to `BACKUP_HOST_DIR`; retention is configurable | `infrastructure/backup/`, `compose.prod.yaml`, `docs/operations/backup_restore.md` |
| `packaging==26.3` is pinned explicitly because Kombu's Redis transport imports it; the isolated scene-worker venv proved the dependency was undeclared | `backend/requirements.txt`, Phase 10 close-out F1 |
| Application version 1.0.0 is recorded in `VERSION`, `Settings.version`, `APP_VERSION`, the frontend package and the release record | `VERSION`, `backend/app/core/config.py`, `docs/releases/v1.0.0.md` |

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
| Production frontend image (nginx, static build) | Complete | Task 10.1: pinned nginx production stage serves the static build, terminates TLS and proxies `/api/`/`/health/`; only 80/443 are published |
| Generation UI, status polling and result link | Complete | The details page starts/retries generation, polls real status and links the authenticated download; the interactive viewer and result-management UI remain Phase 7 |
| 3D viewer and result-management UI | Complete | Phase 7: unified R3F viewer, authorized GLB loading, controls, lighting, disposal, information panel, download and result management; report in [`reviews/phase7_closeout.md`](reviews/phase7_closeout.md) |
| Phase 7 viewer and result management | Complete | Tasks 7.1–7.7 and the applicable `FE-AC-14..17/19`, `UI-AC-09..11/14`, `API-AC-13/14/16`, `INF-AC-02/07/15`, `TEST-AC-10/11` and `SCENE-AC-22` criteria verified; 130 frontend tests; real Edge proof against both asset types |
| Phase 8 reliability, security and optimization | Complete | Tasks 8.1–8.8 and the applicable `AC-08/09/12/13`, `BE-AC-05/06/10/15/18/19/21/22/23`, `DB-AC-20/21/23`, `INF-AC-10/11/12/15/18/19/20/21/22/23/24/25`, `API-AC-12/13/15/16` and `TEST-AC-04/06/07/08/09/16/17/18` criteria verified; report in [`reviews/phase8_closeout.md`](reviews/phase8_closeout.md); 509 backend tests, 130 frontend, 75 scene and 35 object ML; live Redis/PostgreSQL outage, API recreation, backup/restore and performance drills |
| Phase 9 comprehensive testing and quality assurance | Complete | Tasks 9.1–9.7 and the applicable `AC-01..14` and `TEST-AC-01..20` criteria verified; report in [`reviews/phase9_closeout.md`](reviews/phase9_closeout.md); 525 backend, 148 frontend, 75 scene + 1 skipped, 35 object + 1 skipped, 17/17 E2E; real TripoSR and real 11-image COLMAP/OpenMVS runs; Khronos 0 errors; CI workflows, auth rate limiting and scheduled session cleanup delivered |
| Phase 10 MVP release and documentation | Complete | Tasks 10.1–10.6 and all ten Phase 10 acceptance functions verified; report in [`reviews/phase10_closeout.md`](reviews/phase10_closeout.md); release 1.0.0; production overlay/images, nginx TLS, Secure cookies, separate beat, scheduled backups, deployment verification (17/17 E2E against HTTPS, real object and 11-image scene), user/developer docs and release record; `M9` achieved |
| Superseded result files | Complete | A successful regeneration queues a `FILE` cleanup job for the old GLB; a failed regeneration keeps it |
| Scene workspace retention | Complete | Hourly `cleanup_scene_workspaces_task`; `SCENE_WORKSPACE_RETENTION_HOURS` (168 default, 0 disables); `workspace_usage` logged |
| Backup and restoration documentation | Complete | [`operations/backup_restore.md`](operations/backup_restore.md) with the scheduled `backup` service, executed PostgreSQL and file-storage restores, and a runnable consistency checker |
| Performance baseline | Complete | API/upload/download/cleanup/viewer/memory measurements plus persisted TripoSR and COLMAP/OpenMVS stage timings; see the Phase 8 close-out |
| Frontend bundle size | Known limitation | Three.js raises the production bundle to ~1.54 MB (436 kB gzip); Vite warns about the chunk. Route-level splitting is deferred |
| Live object generation during Phase 7/8 | Historical environment note | A new OBJECT smoke task hung in `MODEL_GENERATION` under host GPU load in an unrelated workload; the test project was deleted and the worker restarted with its model loaded. Phase 8 did not run new inference for the same reason. Phase 9 ran real generations successfully (object E2E and performance runs); GPU/RAM failures remain covered by simulated stable codes and the recorded real runs |
| Playwright E2E | Complete | Repository suite in `e2e/` (17 tests) covering auth, projects, security, both real generations, viewer interaction/download, failure/retry and deletion during processing; **17/17 passed against the production HTTPS stack** on 2026-11-11; the Phase 7/8 out-of-tree proofs remain in `.proof/` |
| CI pipeline and coverage measurement | Implemented; remote execution not observed | `TEST-AC-19` is satisfied by workflow files in the working tree (`.github/workflows/ci.yml`, `e2e.yml`, `ml-validation.yml`); every command was executed locally. Backend coverage 87.80%, frontend 71.47%; shortfalls recorded in the Phase 9 close-out. No CI remote exists in this environment |
| Rate limiting on auth endpoints | Implemented | In-process fixed-window limiter on login/register (10/min per path and peer), 429 `RATE_LIMITED` + `Retry-After`; live probe and 10 tests; per-process scope documented |
| Phase 6 scene reconstruction | Complete | Tasks 6.1–6.9 and the applicable `SCENE-AC`, `BE-AC-17/19/20`, `DB-AC-07/08/10..12`, `API-AC-09..14`, `INF-AC-02/09/10/12/13/14/17` and `TEST-AC-13/14/18` criteria verified; report in [`reviews/phase6_closeout.md`](reviews/phase6_closeout.md); 491 backend, 94 frontend and 74 scene ML tests plus the real 11-image proof and live worker E2E |
| Cleanup-job processing | Implemented | The `cleanup-worker` claims `PENDING` jobs, deletes the target, records `COMPLETED`/`last_error`/`attempts` and retries until `CLEANUP_MAX_ATTEMPTS` |
| Broker-driven cleanup dispatch | Complete | Image/project deletion insert a `cleanup.requested` outbox event; the dispatcher publishes it to `file_cleanup` and the cleanup worker processes the targeted job immediately. The beat scan remains the recovery path. |
| Celery beat separation | Complete | Production runs a dedicated `beat` service; the cleanup worker command no longer includes `--beat` (`compose.prod.yaml`) |
| Expired processing artifacts | Complete | The scene-workspace retention sweep is the producer and remover of expired intermediate artifacts (`07` Section 15.7); object work dirs are removed on success and failure |
| Worker health beyond the process | Partially complete | Workers answer `celery inspect ping`; the dispatcher and recovery prove their loops with heartbeat files. Task-level metrics, dead-letter handling and per-task health remain deferred |
| Session cleanup scheduling | Complete | Hourly `cleanup_sessions_task` deletes expired and revoked sessions; live run removed 4 expired + 9 revoked and left 28 active |
| Redis licensing (RSALv2/SSPLv1) | Open | Needs legal acceptance or an approved broker change; see `phase0_decisions.md` Section 8 |
| Increment 14 canonical image rebuild | Blocked/partial | Runtime verified in derived images; canonical object build needs the ~6.4 GB devel layer and the scene build recompiles OpenCV/OpenMVS. Dockerfile and Compose changes are in place and `config -q` passes |
| Increment 14 quadric simplification | Known limitation | No simplifier is pinned; production records `SIMPLIFIER_UNAVAILABLE` and keeps the source. The guard is tested with an injected simplifier |
| Increment 14 AI texture generation | Intentionally disabled | Protocol/factory/output validation implemented; no model passed the licence, compatibility, cache and 12 GB review. Enabling it fails settings validation |
| Increment 14 scene UV/AI | Intentionally disabled | OpenMVS owns scene UV/atlas work; `SCENE_GENERATE_UV` and `SCENE_AI_TEXTURE_ENABLED` are rejected |
| Increment 14 live baking task | Not executed | Baking is proven by unit/export/Khronos/Edge-viewer and benchmark evidence, not a second live task; the live object task used cleanup+normals |
| Docker data root relocation | No longer required | The scene build fits on `C:`; the two ML images are large. Phase 8's rebuild re-downloaded shared CUDA layers, so keep an eye on free space before a cold rebuild |
| First git commit | Partially resolved | The repository now has three commits; the Phase 9 and Phase 10 changes are unstaged/untracked. Do not stage or commit unless the user asks |
| `ml/`, `infrastructure/`, `tests/` directories | Partially real | `ml/object_generation/` and `ml/scene_reconstruction/` are the real workers; `infrastructure/` now holds the backup image and certificate scripts; `ml/workers/` and `tests/` remain placeholders |
| Failed scene workspaces | Bounded | `/data/work/scene/{task_id}` is kept after a failed task for diagnostics and pruned after `SCENE_WORKSPACE_RETENTION_HOURS` (default 168) unless set to 0. The retained Phase 6 workspace becomes eligible ~2026-11-14 |
| Historical orphan storage directories | Known dev artifact | ~414 UUID-named directories (~204 MB) under `/data/projects` have no project row and predate Phase 9 (API tests before the `/tmp/mogen-test-storage` isolation). Verified against the `projects` table but not bulk-deleted; Phase 10 left them untouched and did not prune them. Remove only with per-directory verification |

---

## 9. Phase 2–10 progress; next task

Phases 2, 3, 4, 5, 6, 7, 8, 9 and 10 are complete. The increments below record what was delivered; the Phase 2 close-out review is recorded at the end of the Phase 2 section, and the Phase 3–10 summaries and their close-out review links follow it. Phase 10 (MVP release and documentation) is complete and `M9` is achieved; the next work is a post-MVP Section 11 item.

**Read first for post-MVP work:** the relevant specification, `10_development_roadmap.md` Section 11, [`reviews/phase10_closeout.md`](reviews/phase10_closeout.md) and [`releases/v1.0.0.md`](releases/v1.0.0.md).

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

### Phase 9 — comprehensive testing and quality assurance (complete)

Verified on 2026-11-10 against the running stack, **525 backend**, **148 frontend**, **75 scene ML + 1 skipped**, **35 object ML + 1 skipped** and **17/17 E2E** tests. The task-by-task, criterion-by-criterion, coverage, ML-quality, performance, security and limitation tables are in [`reviews/phase9_closeout.md`](reviews/phase9_closeout.md).

**9.1 Frontend:** 148 cases across 24 files; lint, typecheck, format and build clean; 71.47% line coverage; new DTO-mapper and API-client interceptor cases.
**9.2 Backend:** 525 passed (339 database/API, 178 unit, 8 API-shell); 87.80% line coverage; ruff/format/alembic/pip clean.
**9.3 ML:** opt-in real TripoSR test passed; real 11-image COLMAP/OpenMVS reconstruction completed through the worker in 406.2 s with 233 543 dense points and a 31 573-face textured mesh; Khronos validator 0 errors/0 warnings for object and 100-image scene GLBs.
**9.4 E2E:** repository Playwright suite 17/17; registration/login/logout, project lifecycle, both real generation workflows, status, viewer interaction, download, failure/retry, deletion during processing, recovery covered by backend tests and Phase 8 drills.
**9.5 Security:** two-user isolation, CSRF (missing and cross-session), upload validation, traversal filename neutralization, private assets; live rate-limit probe 10×401 → 429; no critical issue.
**9.6 Performance:** object 7.61 s (480×360) and 7.59 s (987×1481), viewer ~1.0 s, downloads 328–338 ms; 11-image scene 406.2 s; 100-image scene 3 719 s (persisted real Phase 8 run).
**9.7 Fixes:** no critical product defect; the Phase 8 open items were decided (rate limiting and session cleanup implemented), CI/E2E/coverage tooling added, and the E2E fixture mismatch corrected.

**Criteria:** all six Phase 9 acceptance criteria, `AC-01..AC-14`, `TEST-AC-01..TEST-AC-20` (with CI remote execution unobserved) and `M8` are satisfied. `M9` is not claimed; Phase 10 release engineering remains.

### Phase 10 — MVP release and documentation (complete)

Verified on 2026-11-11 against the production stack and the returned development
stack. The task-by-task, criterion-by-criterion, deployment, backup, security and
limitation tables are in [`reviews/phase10_closeout.md`](reviews/phase10_closeout.md).

**10.1 Release configuration:** `compose.prod.yaml` builds runtime images
(`mogen-api:1.0.0`, `mogen-object-worker:1.0.0`, `mogen-scene-worker:1.0.0`,
`mogen-frontend:1.0.0`, `mogen-backup:1.0.0`), publishes only nginx 80/443,
sets `APP_ENV=production`/`DEBUG=false`/API docs off/Secure cookies/required
secrets, adds a dedicated `beat`, bounded log rotation, TLS termination and the
scheduled `backup` service. `frontend/nginx/default.conf`, `.env.production.example`
and the certificate helpers were added.

**10.2 Deployment verification:** production stack healthy with `migration` and
`model-init` `Exited (0)`; only 80/443 reachable; HTTPS health checks, Secure
cookies, 404 API docs; direct API smoke (register 201, auth/me, create project,
upload and byte-identical private content, delete 202); real TripoSR object task
(32.4 s through E2E) and real 11-image COLMAP/OpenMVS reconstruction (7.7 min
through E2E); full viewer and authenticated GLB download; failure/retry and
delete-during-processing; data preservation with identical counts and result
SHA-256; live rate-limit probe 10×401 → 429. **Playwright 17/17 against
`https://localhost`.**

**10.3 Backups:** scheduled service produced pg_dump + `/data/projects`
archives with checksums and a manifest; a final backup restored into a scratch
database with identical counts (2/19/17/10/141) and a matching result SHA-256
for the storage archive.

**10.4 User documentation:** [`user_guide.md`](user_guide.md).

**10.5 Developer documentation:** [`developer_guide.md`](developer_guide.md),
[`deployment.md`](deployment.md), [`api.md`](api.md), updated `README.md`, env
templates and CI production validation.

**10.6 Release:** [`releases/v1.0.0.md`](releases/v1.0.0.md) records the
application version, migration revision `1f302d830cf9`, model/tool pins and image
identifiers. `VERSION` and `/health/live` report 1.0.0.

**Finding fixed:** the production scene-worker runtime lacked `packaging`
(Kombu's Redis transport imports it; the development image got it through
`pytest`). `packaging==26.3` is now pinned explicitly and the API/scene images
were rebuilt.

**Criteria:** all ten Phase 10 acceptance functions, `AC-01..AC-14`,
`INF-AC-01..25` at the Phase 10 scope, `TEST-AC-01..18/20` and the locally
executed `TEST-AC-19` are satisfied; `M9` (MVP Released) is achieved.

### Next: post-MVP (Section 11 of the roadmap)

Phase 10 is the last MVP phase. No Phase 11 implementation has started and no
Section 11 feature is in the working tree. Candidate post-MVP work is listed in
`10_development_roadmap.md` Section 11: horizontal scaling, object storage,
richer monitoring/dead-letter handling, route-level bundle splitting, shared
rate limiting, remote CI runners and further reconstruction quality tuning.

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

The state below was verified at the end of increment 15 on 2026-11-27. **Continuation point:** Phases 2–10 are complete; the MVP is released as 1.0.0 and deployment-verified; post-MVP increments 11 (image quality), 12 (feature matching), 13 (advanced object generation), 14 (mesh/texture enhancement) and 15 (optional neural scene representation) are implemented. The development stack was returned to the running, healthy **mesh-default** state with the default TripoSR object worker and scene post-processing off; the splat worker is stopped/removed and `api` is back on `mesh`/`GLB`. The working tree is uncommitted (Section 6) — do not reset, stage or commit it.

1. **Do not re-derive the project.** Read this handoff in full, then [`NEXT_SESSION.md`](NEXT_SESSION.md), [`AI_DEVELOPMENT_GUIDE.md`](AI_DEVELOPMENT_GUIDE.md), and the relevant specification / Section 11 of [`10_development_roadmap.md`](specifications/10_development_roadmap.md) before starting post-MVP work.
2. **Check the sandbox policy** (Section 6): Docker needs `danger-full-access`; under `workspace-write` it fails with "Access is denied". If Docker Desktop is not running, start it first (the missing pipe is a stopped engine, not necessarily a denial). If approvals are enabled, retry the exact command with the narrowest wider mode; if they are disabled and Docker is genuinely blocked, report the baseline as **blocked**.
3. **Confirm the baseline** (Section 5): `docker compose -f compose.yaml -f compose.gpu.yaml ps -a`, the three worker pings, the `cleanup_scene_workspaces_task` and `cleanup_sessions_task` registrations, the dispatcher/recovery heartbeat files, the object worker's `triposr_model_loaded`/`object_generation_pipeline_ready` logs and the scene worker's `scene_pipeline_ready` log, the backend suite (**619 passed**), the frontend suite (**161 passed / 25 files**), the scene ML suite (**172 passed, 3 skipped**; 175 collected), the object ML suite (**135 passed, 3 skipped**), image-quality (**47**), lint, format, `alembic check`, `pip check`, the API health endpoints and the frontend checks. Fix a failing baseline before any new work. Do not pass `-q` twice to pytest (the config already sets it; `-qq` hides the summary).
4. **Do not re-open Phases 2–10.** The MVP is released; post-MVP work must start from Section 11 of the roadmap, with its own plan and acceptance criteria. Do not change the viewer, result/download contract, outbox, reconstruction pipelines or production packaging unless a new finding genuinely requires it.
5. **Update the handoff and report** in the guide's format (Section 18.4) with the identifiers actually verified.

**Phase 10 reading:** [`reviews/phase10_closeout.md`](reviews/phase10_closeout.md), [`releases/v1.0.0.md`](releases/v1.0.0.md), [`deployment.md`](deployment.md), [`developer_guide.md`](developer_guide.md), [`user_guide.md`](user_guide.md), [`api.md`](api.md) and `docs/operations/backup_restore.md`.

If the stack is already running (it was left healthy), step 3 can start with `docker compose -f compose.yaml -f compose.gpu.yaml ps -a`; the URLs are `http://127.0.0.1:8000` (API), `http://127.0.0.1:5173` (frontend) and `http://127.0.0.1:8000/docs` (Swagger). If Docker is unavailable, report the baseline as **blocked** rather than guessing.

**State left behind by increment 15:** the development stack is running with rebuilt `mogen-api:dev` (increment-15 code and migration applied), `mogen-frontend:dev` (splat renderer dependency), and a scene-worker image that contains the increment-15 source (derived from the verified runtime base because the canonical rebuild recompiles OpenCV/OpenMVS). Nine services are healthy and `migration`/`model-init` are `Exited (0)`; the object worker uses the default TripoSR policy and the scene worker has `SCENE_MESH_POSTPROCESS_ENABLED=false`, `SCENE_REPRESENTATION=mesh`. The dedicated splat worker (`mogen-splat-worker:dev`) is built (22.5 GB, shared layers with the scene image) but **stopped/removed**; recreate it with `compose.splat.yaml` when needed. The increment-15 live evidence project `e4287c69-7161-49e6-bc03-3ce807477f04` (user `splat-live-fdbd74d492@example.com`) is retained with its 51.7 MB PLY; `.proof/increment15/` holds the smoke/live/benchmark/viewer evidence (gitignored). Failed/cancelled test projects were deleted. The SF3D cache `/models/sf3d` (plus the DINOv2/CLIP HF caches under `/models/hf`) remains populated and manifest-verified, and `mogen-object-worker:sf3d-cuda` carries the CUDA-enabled texture baker. Production images `:1.0.0` are built but not running and do **not** include increment 15. `.env.production`, `infrastructure/certs/tls.{crt,key}`, `.backups/` and `.env` exist locally and are gitignored. `backend/tests/db/conftest.py` still routes test uploads to `/tmp/mogen-test-storage`. The retained `/data/work/scene/379073b3-…` workspace is beyond the default retention window; the sweep may prune it unless `SCENE_WORKSPACE_RETENTION_HOURS` is raised or set to `0`.

### 10.1. State snapshot

| Item | Value |
|---|---|
| Phase / increment | Phases 2–10 complete; **MVP 1.0.0 released and deployment-verified; increments 11–15 implemented; no increment 16 started** |
| Stack | eleven Compose services; `db`, `redis`, `api`, `cleanup-worker`, `object-worker`, `scene-worker`, `outbox-dispatcher`, `task-recovery`, `frontend` healthy; `migration` and `model-init` Exited (0) |
| Backend suite | **619 passed**: 573 increment-14 baseline + 46 increment-15 representation/routing/PLY cases |
| Frontend suite | **161 passed across 25 files** (verifiable tracked baseline was **148 / 24**; the old 173/28 count included four untracked tests present only in a stale image); lint, typecheck and format check for changed files clean |
| ML suites | Scene **172 passed, 3 skipped** (175 collected); object **135 passed, 3 skipped** (unchanged); image-quality **47 passed**; real Splatfacto **completed** (smoke + live task); real TripoSR **1 passed** (baseline); real SF3D **2 passed** (2026-11-26) |
| Increment 11 | Advisory image-quality analysis; thresholds not retuned; both worker images rebuilt |
| Increment 12 | Optional ALIKED + LightGlue feature matching; COLMAP SIFT default; pre-increment scene suite **117 passed + 2 skipped** (119 collected), interop 1 passed |
| Increment 13 | Generator contract, TripoSR adapter, opt-in SF3D adapter/image/overlay, textured GLB path, generator metadata, fallback; Hunyuan3D blocked; real SF3D weight/inference/live-task/benchmark **completed 2026-11-26** (TripoSR 12/12 median 7.595 s vs SF3D 12/12 median 2.714 s) |
| Increment 14 | Shared `mesh_enhancement`; conservative cleanup/normals; guarded simplification; xatlas UV/bake; PBR validation; disabled AI texture; scene post-process preserving OpenMVS textures; compact metadata; benchmarks; live object and scene tasks |
| Increment 15 | Optional `GAUSSIAN_SPLAT` representation (Nerfstudio Splatfacto + gsplat, dedicated worker image/queue), `ResultFormat.PLY` migration, independent PLY validation, PLY download/API handling, lazy splat renderer; mesh remains default; real smoke/live/benchmark/browser evidence in [`reviews/increment15_closeout.md`](reviews/increment15_closeout.md) |
| E2E | repository `e2e/` Playwright suite, **17/17 passed against the production HTTPS stack**; real object and real 11-image scene workflows |
| Phase 2 close-out | Complete; report in [`reviews/phase2_closeout.md`](reviews/phase2_closeout.md) |
| Phase 3 integration | Complete; auth, dashboard, creation, uploads and details verified; live smoke through the frontend proxy |
| Phase 4 background processing | Complete; report in [`reviews/phase4_closeout.md`](reviews/phase4_closeout.md); outbox, dispatcher, workers, generation API, recovery and cleanup dispatch verified |
| Phase 5 object generation | Complete; report in [`reviews/phase5_closeout.md`](reviews/phase5_closeout.md); real TripoSR GPU worker, standalone GLB proof, transactional result persistence, result/download API and generation UI verified |
| Phase 6 scene reconstruction | Complete; report in [`reviews/phase6_closeout.md`](reviews/phase6_closeout.md); real COLMAP/OpenMVS worker, 11-image standalone proof, live 5-image worker run, failure preservation and scene UI verified |
| Phase 7 viewer and result management | Complete; report in [`reviews/phase7_closeout.md`](reviews/phase7_closeout.md); unified R3F viewer, authorized GLB loading, controls, information panel, download/result management and real Edge proof against object and scene assets |
| Phase 8 reliability, security and optimization | Complete; report in [`reviews/phase8_closeout.md`](reviews/phase8_closeout.md); security/authorization verification, superseded-result cleanup, scene-workspace retention, stale-read fix, Redis/PostgreSQL outage drills, backup/restore drill and performance baseline |
| Phase 9 testing and quality assurance | Complete; report in [`reviews/phase9_closeout.md`](reviews/phase9_closeout.md); full matrix, real ML runs, CI workflows, rate limiting, session cleanup, coverage and release-readiness assessment |
| Phase 10 MVP release and documentation | Complete; report in [`reviews/phase10_closeout.md`](reviews/phase10_closeout.md); production images/overlay, nginx HTTPS, Secure cookies, separate beat, scheduled backups, 17/17 production E2E, real object and scene runs, docs and release 1.0.0; `M9` achieved |
| Production stack | `compose.prod.yaml`: `mogen-api:1.0.0`, `mogen-object-worker:1.0.0`, `mogen-scene-worker:1.0.0`, `mogen-frontend:1.0.0`, `mogen-backup:1.0.0`; only nginx 80/443 published; `beat` and `backup` services; built but not currently running |
| Quality gates | `ruff check` clean, `ruff format --check` clean (117 backend files), `alembic check` no drift, `pip check` clean; frontend lint/typecheck/format/build clean (bundle ~1.54 MB / 436 kB gzip, Vite chunk warning) |
| Live API | `/health/*`, `/api/v1/auth/*`, `/api/v1/projects`, `/api/v1/projects/{id}/images` (POST/GET), `.../images/{image_id}/content` (GET), `.../images/{image_id}` (DELETE), `POST /api/v1/projects/{id}/generate`, `GET /api/v1/projects/{id}/status`, `GET /api/v1/projects/{id}/result`, `GET /api/v1/projects/{id}/download` |
| Generation workers | `object-worker` loads the real TripoSR model once and processes `object_generation`; `scene-worker` verifies COLMAP 4.2.1/OpenMVS 2.4.0 and processes `scene_reconstruction` with the real pipeline |
| Outbox dispatcher | Standalone process; claims committed events, publishes to the three queues, retries with backoff, releases expired locks; heartbeat file `/tmp/outbox-dispatcher.heartbeat` |
| Task recovery | Standalone process; requeues/fails stale tasks and detects dispatch stalls; heartbeat file `/tmp/task-recovery.heartbeat` |
| Cleanup worker | Celery 5.7.0 on queue `file_cleanup`, beat poll every 15 s as recovery, targeted `cleanup_storage_task(job_id)` from the dispatcher, hourly `cleanup_scene_workspaces_task` retention sweep and hourly `cleanup_sessions_task`, `celery inspect ping` healthy |
| Configuration | `AUTH_RATE_LIMIT_ENABLED=true`, `AUTH_RATE_LIMIT_ATTEMPTS=10`, `AUTH_RATE_LIMIT_WINDOW_SECONDS=60`, `SESSION_CLEANUP_INTERVAL_SECONDS=3600`, `MAX_PAGE_SIZE=100`, `MAX_UPLOAD_SIZE_MB=20`, `MAX_IMAGE_DIMENSION=8192`, `MIN_SCENE_IMAGES=3`, `MAX_SCENE_IMAGES=100`, `CLEANUP_*`, `SCENE_WORKSPACE_RETENTION_HOURS=168`, `SCENE_WORKSPACE_SWEEP_INTERVAL_SECONDS=3600`, `OUTBOX_*`, `TASK_LEASE_SECONDS=300`, `TASK_HEARTBEAT_SECONDS=30`, `TASK_STALE_THRESHOLD_SECONDS=900`, `DISPATCH_STALL_TIMEOUT_SECONDS=900`, `TASK_RECOVERY_*`, `OBJECT_*`, `SCENE_RECONSTRUCTION_ENABLED=true`, `SCENE_COLMAP_EXECUTABLE=/usr/local/bin/colmap`, `SCENE_OPENMVS_BIN_DIR=/usr/local/bin/OpenMVS`, `SCENE_WORK_DIR=/data/work/scene`, `SCENE_MATCHING_STRATEGY=EXHAUSTIVE`, `SCENE_COLMAP_USE_GPU=false` (base; GPU override true), `SCENE_COLMAP_MAX_FEATURES=8192`, `SCENE_COLMAP_CAMERA_MODEL=SIMPLE_RADIAL`, `SCENE_MAX_IMAGE_SIZE=2000`, `SCENE_MAX_THREADS=4`, `SCENE_OPENMVS_USE_CUDA=false`, `SCENE_ENABLE_MESH_REFINEMENT=true`, `SCENE_ENABLE_TEXTURE_GENERATION=true`, `SCENE_MIN_REGISTERED_IMAGES=3`, `SCENE_MIN_REGISTRATION_RATIO=0.5`, `SCENE_MIN_SPARSE_POINTS=100`, `SCENE_MIN_DENSE_POINTS=100`, `SCENE_MAX_TASK_SECONDS=14400`, `SCENE_COLMAP_TIMEOUT_SECONDS=3600`, `SCENE_OPENMVS_TIMEOUT_SECONDS=5400`, `SCENE_EXPORT_TIMEOUT_SECONDS=1800`; frontend mirrors upload limits through `VITE_MAX_UPLOAD_SIZE_MB`, `VITE_MIN_SCENE_IMAGES`, `VITE_MAX_SCENE_IMAGES`, `VITE_TASK_POLL_INTERVAL`; enhancement defaults `OBJECT_MESH_CLEANUP_ENABLED=true`, `OBJECT_MESH_NORMALS_ENABLED=true`, `OBJECT_MESH_MERGE_TOLERANCE=0.000001`, `OBJECT_MESH_SIMPLIFICATION_ENABLED=false`, `OBJECT_GENERATE_UV=false`, `OBJECT_BAKE_TEXTURE=false`, `OBJECT_UV_RESOLUTION=1024`, `OBJECT_TEXTURE_RESOLUTION=1024`, `OBJECT_AI_TEXTURE_ENABLED=false`, `SCENE_MESH_POSTPROCESS_ENABLED=false`, `SCENE_MESH_SIMPLIFICATION_ENABLED=false`, `SCENE_GENERATE_UV=false`, `SCENE_AI_TEXTURE_ENABLED=false`, `ENHANCEMENT_FALLBACK_TO_ORIGINAL=true`, `MESH_ENHANCEMENT_MAX_MEMORY_MB=8192`, `TEXTURE_ENHANCEMENT_DEVICE=cpu`; neural defaults `SCENE_REPRESENTATION=mesh`, `SCENE_SPLAT_ENABLED=false`, `SCENE_SPLAT_WORKER_QUEUE=scene_gaussian_splat`, `SCENE_SPLAT_MODEL=splatfacto`, `SCENE_SPLAT_MAX_ITERATIONS=30000`, `SCENE_SPLAT_IMAGE_SCALE=1.0`, `SCENE_SPLAT_MAX_IMAGE_DIMENSION=1600`, `SCENE_SPLAT_CHECKPOINT_INTERVAL=5000`, `SCENE_SPLAT_MAX_VRAM_MB=9000`, `SCENE_SPLAT_DEVICE=cuda`, `SCENE_SPLAT_MAX_ARTIFACT_BYTES=536870912`, `SCENE_SPLAT_TIMEOUT_SECONDS=7200`, `SCENE_SPLAT_MIN_REGISTERED_IMAGES=8`, `SCENE_SPLAT_SH_DEGREE=3`, `SCENE_SPLAT_PYTHON=/opt/venv/bin/python`, `SCENE_SPLAT_SITE_PACKAGES=/opt/splat-site`, `SCENE_SPLAT_WORKER=false` |
| Storage | `/data` on the `app_data` volume, shared by the API, cleanup worker and object/scene workers; source keys like `projects/{project_id}/source/{image_id}.jpg`, object results at `projects/{project_id}/results/{task_id}/model.glb`, mesh scene results at `.../scene.glb`, splat scene results at `.../scene.ply`; scene workspaces at `/data/work/scene/{task_id}` (pruned after the retention window); `triposr_model_cache:/models` holds the pinned weights/DINO/rembg cache |
| Database content | Phase 7–10 smoke/fixture rows are removed where they belonged to deleted projects; pre-existing development data, the user-created projects and the historical SCENE task `379073b3…` (soft-deleted project, retained workspace) remain; do not delete these. Phase 10 cleaned its E2E/deployment-check users and returned the counts to 2 users / 19 projects / 17 tasks / 10 results / 141 images. |
| Cleanup jobs | Dispatched as `cleanup.requested`; executed by the worker (`PENDING` → `PROCESSING` → `COMPLETED`/`FAILED`), with `attempts` and `last_error`; superseded result files, expired scene workspaces and expired/revoked sessions are producers |
| Git | branch `main`, three commits; Phases 9–10 and post-MVP increments 11–15 changes are unstaged/untracked |
| Frontend | Russian UI, auth, dashboard, creation, uploads, details, generation/scene panel and unified 3D result viewer with GLB and lazy Gaussian-PLY dispatch; 161 tests; lint/typecheck/format (changed files) clean |

### 10.2. Copy-paste prompt

> Working directory: `H:\Study\Univer\projects\mogen`. Read `docs/HANDOFF.md` first, then `docs/AI_DEVELOPMENT_GUIDE.md`, `docs/NEXT_SESSION.md`, `docs/reviews/increment15_closeout.md`, `docs/additions/15_implementation_plan.md` and `docs/additions/15_neural_scene_reconstruction.md`. Phases 2–10 are complete and the MVP is released as 1.0.0; post-MVP increments 11 (image quality), 12 (feature matching), 13 (advanced object generation), 14 (mesh/texture enhancement) and 15 (optional neural scene representation) are implemented. Increment 13's real SF3D evidence and increment 15's real Splatfacto evidence (smoke, live task, browser proof, benchmark) were completed; do not rerun them unless the pins or images change. Do not redo increments 11–15 and do not re-open the viewer GLB path, result/download contract, outbox semantics, mesh algorithms or released MVP behaviour. Verify the current baseline (619 backend tests, 161 frontend tests, 172 scene ML + 3 skipped, 135 object ML + 3 skipped, 47 image-quality tests, nine healthy development services plus `migration` and `model-init` `Exited (0)`, three worker pings, fresh dispatcher/recovery heartbeats, the real TripoSR model loaded, COLMAP 4.2.1 and OpenMVS 2.4.0 detected). The only identified follow-up is rebuilding the canonical mesh scene-worker image and measuring a full 30 000-iteration / 1 600 px splat artifact; do not start increment 16. Update `docs/HANDOFF.md`, `docs/NEXT_SESSION.md` and add a close-out review for any further work.

### 10.3. Session-start checklist

1. **Check the sandbox policy first** (Section 6). Docker needs named-pipe access: with `danger-full-access` run it directly; with `workspace-write` the CLI fails with "Access is denied" on `dockerDesktopLinuxEngine`. If Docker Desktop is not running at all, the pipe is absent: start Docker Desktop before concluding the engine is blocked, and never request escalation when the session says approvals are disabled.
2. **Confirm the Section 5 baseline end to end** before writing code:

   ```powershell
   docker compose -f compose.yaml -f compose.gpu.yaml ps -a          # nine healthy; migration/model-init Exited (0)
   docker compose exec cleanup-worker celery -A app.tasks.celery_app:celery_app inspect ping
   docker compose exec object-worker celery -A app.tasks.celery_app:celery_app inspect ping
   docker compose exec scene-worker celery -A app.tasks.celery_app:celery_app inspect ping
   docker compose exec cleanup-worker sh -c 'celery -A app.tasks.celery_app:celery_app inspect registered -d celery@$HOSTNAME --timeout 5'  # includes cleanup_scene_workspaces_task and cleanup_sessions_task
   docker compose exec outbox-dispatcher cat /tmp/outbox-dispatcher.heartbeat
   docker compose exec task-recovery cat /tmp/task-recovery.heartbeat
   docker compose run --rm --no-deps api pytest > "$env:TEMP\pytest.log" 2>&1
   Get-Content "$env:TEMP\pytest.log" -Tail 2        # 619 passed
   docker compose run --rm --no-deps api ruff check .
   docker compose run --rm --no-deps api ruff format --check .
   docker compose run --rm --no-deps api alembic check
   docker compose run --rm --no-deps api pip check
   docker run --rm mogen-object-worker:dev python -m pytest /opt/object_generation/tests  # 135 passed, 3 skipped
   docker run --rm mogen-splat-worker:dev /opt/venv/bin/python -m pytest /opt/scene_reconstruction/tests # 172 passed, 3 skipped
   docker run --rm mogen-splat-worker:dev /opt/venv/bin/python -m pytest /opt/image_quality/tests # 47 passed
   docker run --rm mogen-scene-worker:dev python -m scene_reconstruction.standalone --verify-tools
   docker run --rm mogen-frontend:dev npm run lint
   docker run --rm mogen-frontend:dev npm run typecheck
   docker run --rm mogen-frontend:dev npm run format:check   # pre-existing CRLF files; changed files are clean
   docker run --rm mogen-frontend:dev npm run test:run   # 161 passed
   docker run --rm mogen-frontend:dev npm run build
   ```

   Also check `http://127.0.0.1:8000/health/ready`, `http://127.0.0.1:5173/` and the proxy (`http://127.0.0.1:5173/api/v1/probe` must return a JSON `NOT_FOUND` 404), the object worker logs (`triposr_model_loaded`, `object_generation_pipeline_ready`) and the scene worker log (`scene_pipeline_ready`). Immediately after `up` a service can still report `health: starting`; the object worker may take 4–5 minutes to load the model (600 s start period). Fix any failure before building on it.
3. **Read the Phase 10 close-out and the release record** (`reviews/phase10_closeout.md`, `releases/v1.0.0.md`, `deployment.md`, `developer_guide.md`). The documentation is the source of truth, not the current code.
4. **Choose one post-MVP item from Section 11** of `10_development_roadmap.md`, write its plan and acceptance criteria, then implement only that item. Do not re-open Phases 2–10 or change the released MVP behaviour without a recorded finding.
5. **Re-run the baseline after any change** and confirm the documented counts match.
6. **Update this handoff**: Section 1 state, Section 5 counts and breakdown, Section 7 decisions, Section 8 open items, Section 9 status and next increment, and Section 10 if resume steps change.
7. **Report with the guide's completion format** (Section 18.4) and cite only identifiers that were actually verified.

### 10.4. Working agreement

- Do not stage, commit or rewrite git history unless the user asks. `git diff` against the index shows working-tree changes only.
- Do not recreate the cleanup worker, Celery application, outbox table/repository, generation-task/result models, the Phase 4/5/6 worker lifecycle, the generation/result API or the Phase 7 viewer. They are delivered and tested. Phase 9 tested them comprehensively and added rate limiting, session cleanup, CI and the repository E2E suite; Phase 10 packaged the same application for release and verified the production deployment.
- Do not treat Redis as the source of truth: task and outbox state live in PostgreSQL; Redis is only the broker.
- Do not change the TripoSR or COLMAP/OpenMVS pipelines, the viewer, the result/download contract, the outbox or the production packaging unless a new finding genuinely requires it; document any such finding before changing behaviour.
- The object generation panel, scene reconstruction panel, authenticated download, unified viewer, superseded-result cleanup, workspace-retention sweep, auth limiter and session-cleanup task are implemented. The MVP production configuration is in `compose.prod.yaml`; post-MVP work starts from Section 11.
- `ml/workers/` and `tests/` at the repository root remain placeholders; `infrastructure/` now contains the backup image and certificate scripts. Fill only what a post-MVP task actually needs.
- Do not loosen pinned dependencies; the viewer pins Three.js `0.187.0`, React Three Fiber `9.8.2` and Drei `10.7.9`. Record and justify any dependency change.
- Do not modify `docs/specifications/` or `docs/architecture/` to match the implementation; if the two disagree, follow the specification and record the resolution.
- Report checks as passed, failed, skipped, not executed or blocked. Never present an unexecuted check as passed.

### 10.5. Work remaining in Phases 2–10

None. Phase 2 is closed out in [`reviews/phase2_closeout.md`](reviews/phase2_closeout.md), Phase 3 was completed and verified with 84 frontend tests, Phase 4 is closed out in [`reviews/phase4_closeout.md`](reviews/phase4_closeout.md) with 451 backend tests, Phase 5 is closed out in [`reviews/phase5_closeout.md`](reviews/phase5_closeout.md) with 481 backend, 92 frontend and 35 object ML tests plus the real-model proof, Phase 6 is closed out in [`reviews/phase6_closeout.md`](reviews/phase6_closeout.md) with 491 backend, 94 frontend and 74 scene ML tests plus the real reconstruction and live worker proofs, Phase 7 is closed out in [`reviews/phase7_closeout.md`](reviews/phase7_closeout.md) with 130 frontend and the ML suites plus the real Edge viewer proof for both asset types, Phase 8 is closed out in [`reviews/phase8_closeout.md`](reviews/phase8_closeout.md) with 509 backend, 130 frontend, 75 scene and 35 object ML tests plus the reliability/security drills, Phase 9 is closed out in [`reviews/phase9_closeout.md`](reviews/phase9_closeout.md) with 525 backend, 148 frontend, 75 scene + 1 skipped, 35 object + 1 skipped and 17/17 E2E tests plus real ML, coverage, performance, security and release-readiness evidence, and Phase 10 is closed out in [`reviews/phase10_closeout.md`](reviews/phase10_closeout.md) with the production images, HTTPS deployment verification (17/17 E2E), real object and scene runs, scheduled-backup restore drill, documentation and release 1.0.0.

### 10.6. Next phase

The MVP is released. The next work is a post-MVP item from Section 11 (Future
Development) of `10_development_roadmap.md`; no Phase 11 implementation has
started. Candidate items: horizontal scaling and object storage, richer
worker/task monitoring and dead-letter handling, route-level bundle splitting,
shared rate limiting for multiple API replicas, remote CI runners, and further
reconstruction quality/performance tuning. Choose one item, define its acceptance
criteria, and do not re-open the released MVP behaviour without a recorded
finding.
