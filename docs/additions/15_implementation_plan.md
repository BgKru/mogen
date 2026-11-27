# Increment 15 — Implementation Plan and Acceptance Criteria

**Specification:** [`15_neural_scene_reconstruction.md`](15_neural_scene_reconstruction.md)
**Scope:** one post-MVP increment: an optional neural scene representation
(Nerfstudio **Splatfacto**, Gaussian PLY) alongside the unchanged, default
COLMAP + OpenMVS mesh path.
**Status:** Implemented (2026-11-27). Evidence:
[`../reviews/increment15_closeout.md`](../reviews/increment15_closeout.md).
**Date:** 2026-11-27.

## 1. Scope resolution

The addendum is an implementation specification: it names files to modify,
components to add, settings, error handling and testing requirements. It is
implemented in exactly one increment. Not re-opened: Phases 2–10 behaviour, the
mesh pipeline's algorithms, increment-11 thresholds, increment-12 feature
matching, increment-13 generators and increment-14 enhancement. No object
generation, viewer GLB path, task lifecycle, outbox contract semantics, download
authorization or database entity changes beyond the additive `PLY` result
format.

`mesh` remains the default representation. The neural path is opt-in through
deployment settings and is unreachable unless a dedicated neural worker image
and its preflight are present.

## 2. Baseline confirmation (before any change, 2026-11-27)

| Check | Result |
|---|---|
| Development stack (GPU overlay implicit via `.env`) | 11 services: nine healthy, `migration`/`model-init` `Exited (0)`; workers answer `celery inspect ping`; `/health/ready` 200 |
| Backend suite | **573 passed** (after fixing one failure, Section 2.1) |
| Object ML suite | **135 passed, 3 skipped** (138 collected), exit 0 |
| Scene ML suite | **136 passed, 2 skipped** (138 collected), exit 0 |
| Image-quality suite | **47 passed**, exit 0 |
| Frontend suite (working tree) | **148 passed** across the 24 tracked test files |
| `pip check` (scene worker) | clean |
| Ruff / format (backend) | clean |

### 2.1 Baseline defects and documentation corrections

**Backend test failure (fixed).**
`backend/tests/db/test_task_lifecycle.py::test_a_long_pipeline_is_heartbeated_automatically`
failed once in the first full run when four suites ran concurrently: the test
slept a fixed 1.3 s and then required the heartbeat thread to have renewed the
lease, which is a scheduling assumption, not a product requirement. The
heartbeat monitor itself is correct (the single test passes in isolation).
The test now polls for the renewal with a bounded 15 s deadline while the
pipeline stays running, so it proves the same behaviour without a tight timing
window, and the full suite passes. No production code was changed.

**Frontend count correction.** The handoff recorded **173 passed across 28
files**. Re-running the previously built frontend image reproduced 173, but the
current working tree contains only the **24 tracked** test files = **148**
tests (the Phase 9 count). Four untracked test files existed in the stale image
and are absent from the tree; they cannot be attributed to this increment and
are not silently re-counted. The verifiable pre-increment baseline is therefore
**148**, and increment 15 adds 13 viewer/splat tests (**161** across 25 files).

**Reporting correction.** The baseline commands in `HANDOFF.md`/`NEXT_SESSION.md`
pass `pytest -q` while `pyproject.toml` already sets `-q`; pytest 9 treats the
double `-q` as `-qq`, which suppresses the final summary line. Counts in this
plan were obtained without the extra `-q` (and JUnit XML where exact counts
matter). This is a reporting trap, not a test failure; the commands are
annotated in `NEXT_SESSION.md`.

## 3. Compatibility findings and constraints

| Item | Finding | Consequence |
|---|---|---|
| Target GPU | RTX 3060, 12 GB, driver supports CUDA 13.x; development stack runs torch 2.14.1+cu126 (object) and +cu130 (scene venv) | standard `splatfacto` only; `splatfacto-big` rejected by validation |
| Upstream Splatfacto memory | ~6 GB (standard) / ~12 GB (big) upstream **estimates**, not MOGEN measurements | never reported as measured; admission uses an explicit soft VRAM budget and real measurements when training runs |
| Nerfstudio 1.1.5 dependency graph | `ns-train`/`ns-export` pull `open3d`, `pymeshlab`, `nerfacc`, `tiny-cudann`, `timm==0.6.7`, `opencv-python-headless==4.10` and others | the neural runtime lives in a **dedicated venv inside a dedicated worker image**; the preflight imports only the modules the pinned training/export entry points need; `tinycudann` is optional in upstream (`TCNN_EXISTS`) and is not installed |
| Nerfstudio PLY dialect | 1.1.5 `ns-export gaussian-splat` writes binary little-endian PLY with `x y z nx ny nz f_dc_0..2 f_rest_0..44 opacity scale_0..2 rot_0..3` (45 `f_rest` for SH degree 3) | the independent validator accepts exactly this schema; a generic point cloud is rejected |
| COLMAP sparse model | `SIMPLE_RADIAL` cameras; `colmap image_undistorter` already produces the PINHOLE dense model + undistorted images used by OpenMVS | the adapter consumes the **undistorted** dense images/model, matching upstream `ns-process-data`; no second undistortion and no distortion reinterpretation |
| Scene image | 20.7 GB, contains COLMAP 4.2.1, pycolmap 4.2.1, trimesh, numpy, no SciPy | the neural image builds `FROM` the verified scene image and adds a separate venv; COLMAP sparse reconstruction is reused, OpenMVS is not run for splats |
| Disk | ~41 GB free before the increment; ML images are large | the neural image must reuse local layers; no new multi-GB base pull is required |
| Frontend | React 19 / R3F 9.8.2 / Three.js 0.187.0, GLB-only viewer | the splat renderer must be lazy-loaded, pinned, and must not alter the GLB path |

## 4. Design decisions

1. **Two representations, one task lifecycle.** `SCENE_REPRESENTATION` is a
   deployment setting (`mesh` default, `gaussian_splat` opt-in). The selected
   representation **and** method are persisted in `GenerationTask.parameters` at
   creation, so retries, recovery and routing cannot disagree with a later
   environment change. Tasks without the field resolve to `mesh`.
2. **Deterministic routing, capability-checked workers.** A splat task is
   published to the dedicated `scene_gaussian_splat` queue and a mesh task to
   `scene_reconstruction`; the queue is chosen from the persisted payload, not
   from the worker's environment. Each scene worker registers exactly one
   capability and rejects a task persisted for the other representation with a
   stable `SCENE_WORKER_INCOMPATIBLE` failure instead of silently producing the
   wrong artifact.
3. **Shared preparation and sparse reconstruction.** The splat path runs the
   existing `IMAGE_PREPARATION` (including advisory image quality), feature
   extraction/matching, sparse reconstruction, model selection and
   undistortion. It then stops: no `OPENMVS_*`, `DENSE_RECONSTRUCTION`,
   `MESH_GENERATION`, `MESH_REFINEMENT`, `TEXTURING` or GLB export runs.
4. **Nerfstudio dataset conversion is ours and validated.** `transforms.json`
   and a sparse-points PLY are written into the task workspace from the
   validated COLMAP dense model and undistorted images. Camera poses are
   converted COLMAP (world-to-camera, OpenCV) → Nerfstudio
   (camera-to-world, OpenGL) exactly once; intrinsics are scaled when (and only
   when) an image is resized. A pure-NumPy **projection test** re-projects the
   sparse points through the generated transforms and compares them with
   COLMAP's own projections (error < 1 px), which validates handedness,
   forward axis, transform direction and intrinsics before training.
5. **Training is a controlled subprocess.** A pinned Python entry point
   (allowed by addendum Section 5.1) builds `TrainerConfig` +
   `SplatfactoModelConfig` directly instead of importing the CLI's full method
   registry, so unnecessary compiled dependencies are not dragged in. It runs
   through the existing `CommandRunner` (argument array, timeout, process-group
   termination, cancellation polls, log capture).
6. **Resolved configuration and checkpoint manifest.** The effective
   configuration (not only CLI flags), dataset fingerprint, runtime versions
   (`nerfstudio`, `gsplat`, `torch`, CUDA), image scale and Gaussian count are
   recorded. A checkpoint is reused only when the dataset fingerprint, runtime
   versions and every output-affecting setting match; transient free-memory
   values are excluded.
7. **Independent Gaussian PLY validation before registration.** A standalone
   binary-PLY parser checks the pinned schema/property order, file-size vs
   vertex-count consistency, finite values, Gaussian count bounds, quaternion
   norms, log-scale/opacity ranges and the configured maximum artifact size. A
   partial, truncated or wrong-dialect PLY is never registered.
8. **Export is deterministic and atomic.** The exporter reads the trained
   checkpoint tensors and writes the **official 1.1.5 property order and
   dtypes** to a temporary file, filters non-finite and sub-threshold-opacity
   Gaussians exactly like the pinned `ns-export` implementation, validates,
   hashes, then atomically renames into the task result path. When the neural
   runtime is present, an opt-in conformance test compares the PLY header and
   values with `ns-export gaussian-splat` output.
9. **Result format is additive.** `ResultFormat` gains `PLY`, a forward-only
   Alembic migration extends the CHECK constraint, existing `GLB`/`OBJ`/`STL`
   rows stay valid, and the response schema is unchanged (`format` is already a
   string). The download filename extension is derived from the result format
   and `PLY` is served as `application/octet-stream`, never as
   `model/gltf-binary` and never with a `.glb` name.
10. **Frontend dispatch is explicit and lazy.** `format` (with a validated
    `metadata.representation` fallback) selects the renderer. GLB keeps the
    current `GLTFLoader` path byte-for-byte; `PLY` lazy-loads a pinned
    Three.js-compatible Gaussian-splat renderer, shows Gaussian count/artifact
    size instead of triangle statistics, and disposes renderer, GPU buffers,
    workers and object URLs on result change, failure and unmount.
11. **Resource policy is explicit.** One neural task at a time on the GPU; a
    soft VRAM budget gates admission; `max_image_dimension`/`image_scale` bound
    the dataset; a maximum artifact size bounds the download; OOM/timeout
    produce stable codes and no silent CPU fallback; the training process can be
    cancelled through the existing process-group mechanism.
12. **Honest unavailability.** If the dedicated runtime cannot be built or the
    pinned stack cannot train on the target hardware, the runtime preflight
    fails with a stable code, `gaussian_splat` remains unavailable, and the
    close-out records the measured blocker. The mesh path is unaffected.

## 5. Implementation tasks

| ID | Task | Files |
|---|---|---|
| I15-01 | Baseline confirmation, compatibility study, this plan and acceptance criteria | `docs/` |
| I15-02 | Representation and splat settings with validation; worker mapping; env examples | `backend/app/core/config.py`, `ml/scene_reconstruction/config.py`, `splat_config.py`, `.env.example`, `.env.production.example`, `compose.yaml` |
| I15-03 | Persist representation/method; outbox payload + deterministic queue routing; recovery keeps the persisted representation; worker capability rejection | `backend/app/services/generation_service.py`, `outbox_events.py`, `tasks/outbox_publisher.py`, `tasks/celery_app.py`, `tasks/scene_pipeline.py`, `tasks/generation_tasks.py` |
| I15-04 | `PLY` result format: model enum, forward-only migration, MIME/extension-aware download name, storage key, cleanup/retention compatibility | `backend/app/db/models/enums.py`, `alembic/versions/*`, `services/result_service.py`, `api/v1/endpoints/results.py`, tests |
| I15-05 | COLMAP → Nerfstudio dataset adapter: transforms.json, sparse PLY, resize/intrinsics, image identity manifest, dataset fingerprint, camera/sparse validation, projection self-check | `ml/scene_reconstruction/nerfstudio_dataset.py` |
| I15-06 | Independent Gaussian PLY schema validator (pinned dialect, limits, finiteness, quaternions, sizes) | `ml/scene_reconstruction/splat_validator.py` |
| I15-07 | Checkpoint → Gaussian PLY exporter with atomic publish, official property order and upstream equivalent filtering | `ml/scene_reconstruction/splat_exporter.py` |
| I15-08 | Neural pipeline orchestration: preflight, VRAM admission, training subprocess, resolved config, checkpoint manifest/reuse, export, validation, cancellation, metadata | `ml/scene_reconstruction/neural_pipeline.py`, `nerfstudio_runner.py`, `splat_train_entry.py` |
| I15-09 | Representation-aware dispatcher in the existing reconstructor; mesh path unchanged; splat path stops before OpenMVS | `ml/scene_reconstruction/pipeline.py`, `diagnostics.py`, `exceptions.py`, `preflight.py` |
| I15-10 | Dedicated neural worker image/venv, Compose overlay, startup verification and gsplat cache warm-up, queue service | `ml/scene_reconstruction/Dockerfile.splat`, `requirements-splat.txt`, `compose.splat.yaml`, `compose.yaml` |
| I15-11 | Backend tests: settings, persistence/fingerprint, routing, worker rejection, PLY migration/API/download, previous-result preservation | `backend/tests/unit/`, `backend/tests/db/` |
| I15-12 | ML tests: conversion/projection, camera validation, fingerprints, PLY validator, exporter, pipeline success/failure/timeout/cancel, opt-in real training | `ml/scene_reconstruction/tests/` |
| I15-13 | Frontend format dispatch, lazy splat renderer, splat statistics, capability/error states, disposal, tests | `frontend/src/features/model-viewer/`, `frontend/package.json` |
| I15-14 | Browser proof, reproducible benchmark, README/spec/deployment/API docs, close-out review, HANDOFF/NEXT_SESSION updates | `docs/`, `.proof/`, `ml/scene_reconstruction/README.md` |

## 6. Acceptance criteria

| ID | Criterion | Verification |
|---|---|---|
| I15-AC-01 | COLMAP + OpenMVS remains the default representation and produces the same GLB contract; existing GLB results, viewer behaviour and result/download APIs are unchanged. | Existing suites re-run; live/default mesh path regression; GLB download test |
| I15-AC-02 | Neural reconstruction is opt-in and isolated: the API and the existing object/scene images import no Nerfstudio/gsplat; enabling requires the dedicated runtime and validated settings. | Import checks, image diff review, settings rejection tests, Compose validation |
| I15-AC-03 | Splatfacto consumes the validated COLMAP cameras and sparse initialization without duplicating feature extraction or camera estimation; no OpenMVS stage runs for a splat result. | Pipeline tests asserting stage order/absence; diagnostics show reused COLMAP stages |
| I15-AC-04 | Dataset conversion preserves image identity, intrinsics, distortion/dimensions and coordinate transforms; resize scales intrinsics consistently. | Projection self-check (< 1 px) on a synthetic and a real sparse model; unit tests for resize/missing/unsupported cases |
| I15-AC-05 | Standard Splatfacto trains and exports a valid Gaussian PLY on the target worker hardware under a documented configuration, **or** the feature is explicitly marked unsupported with measured blocker evidence. | Opt-in real integration run (short-iteration smoke + export + independent parse), or recorded build/runtime probe and stable unavailability code |
| I15-AC-06 | PLY schema, MIME type, storage key, filename and API metadata are correct; no PLY is mislabeled as GLB; partial/malformed artifacts are rejected. | Validator/exporter tests; migration + API/download tests; body magic/extension assertions |
| I15-AC-07 | The frontend renders the exported PLY through a dedicated, lazy-loaded splat renderer, reports splat-appropriate statistics and releases GPU/object-URL resources; the GLB path is untouched. | Frontend unit tests (dispatch, states, cleanup) + browser proof with a schema-valid fixture |
| I15-AC-08 | Result-format migration is forward-only and backward compatible; legacy GLB rows and responses are preserved. | Migration round-trip test on a scratch database; existing result API tests |
| I15-AC-09 | Representation persists across retries and recovery, routing is deterministic, a worker rejects the other representation, cancellation/timeout stop the training process group, and a failed splat attempt preserves the previous current result. | Backend routing/recovery tests; ML cancellation/timeout tests; result-preservation test |
| I15-AC-10 | Benchmarks compare mesh and splat on identical images/cameras using representation-appropriate metrics (time, peak VRAM/RAM, Gaussian count/PLY size, view quality where reproducible); no mesh-polygon vs Gaussian-count equivalence is claimed. | Reproducible benchmark script + recorded JSON and report |
| I15-AC-11 | No automatic representation replacement: users/deployment select explicitly; mesh remains the fallback default. | Settings defaults, routing tests, docs |
| I15-AC-12 | Resource controls are enforced: soft VRAM budget/admission, bounded image scale/dimension, iteration/checkpoint bounds, maximum artifact size, stable OOM/timeout errors, no silent CPU fallback, one GPU task at a time. | Settings bounds tests, admission/OOM tests, artifact-size test, Compose single-concurrency check |
| I15-AC-13 | Errors are stable and safe: neural unavailable, runtime/extension mismatch, camera/dataset failure, insufficient poses/points, timeout/cancellation, OOM, checkpoint mismatch, export failure, malformed PLY, oversized artifact; no paths/tensors/logs in metadata. | Error-code tests; metadata key review; diagnostics written only to the workspace |
| I15-AC-14 | Only the relevant documentation is updated (README, specification note, deployment/API docs, plan, close-out, HANDOFF, NEXT_SESSION) and no unrelated change is introduced. | Diff review; documentation links |

## 7. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Nerfstudio 1.1.5 is not importable/runnable on the pinned torch 2.14/CUDA 13 host | dedicated venv + pinned stack; import/preflight probe recorded; stable `SPLAT_RUNTIME_UNAVAILABLE`; feature stays explicitly unsupported if measured infeasible |
| gsplat/nerfacc CUDA extension compilation fails or is slow | build-time warm-up with a versioned `TORCH_EXTENSIONS_DIR`; startup probe executes a tiny kernel; no runtime compilation inside a user task |
| Camera conversion error yields a silently bad reconstruction | pure-NumPy reprojection self-check before training; coordinate-convention tests on synthetic fixtures |
| GPU memory pressure from a second model | one neural task per GPU, object worker stopped for benchmark runs, explicit VRAM admission, bounded image scale |
| Large PLY artifacts break the browser | maximum artifact size validated server-side and mirrored client-side; renderer requires bounded buffers |
| PLY dialect confusion | validator accepts only the pinned property set/order; explicit schema version; generic point-cloud PLY rejected |
| Result-format migration breaks legacy rows | additive CHECK constraint migration with round-trip test; no column/type change |
| Neural image build is heavy (open3d etc.) | install only the modules the pinned entry points import; document disk/cost; reuse existing scene-image layers |
