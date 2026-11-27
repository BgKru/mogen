# Increment 15 close-out review — neural scene reconstruction (Nerfstudio Splatfacto)

**Date:** 2026-11-27
**Specification:** [`docs/additions/15_neural_scene_reconstruction.md`](../additions/15_neural_scene_reconstruction.md)
**Plan and acceptance criteria:** [`docs/additions/15_implementation_plan.md`](../additions/15_implementation_plan.md)
**Scope:** one post-MVP increment. An optional Gaussian-splat scene representation
is added beside the unchanged COLMAP + OpenMVS mesh path. No other increment was
started; increment-11 thresholds, increment-12 feature matching, the released
MVP behaviour, the viewer GLB path, the outbox semantics and the reconstruction
algorithms were not re-opened.

## 1. Summary

The increment adds a representation-aware scene pipeline: a deployment-selected
representation is persisted in each generation task, splat tasks are routed to a
dedicated neural queue, the same validated COLMAP cameras/points are converted
to the Nerfstudio layout, standard Splatfacto trains in a controlled subprocess,
the checkpoint is exported to the pinned Gaussian PLY dialect, and the artifact
is validated independently and registered as `format=PLY`. The frontend
dispatches on the result format and lazy-loads a Gaussian-splat renderer.

**Real evidence on the target card (RTX 3060, 12 GB):** standard Splatfacto
trained and exported a valid Gaussian PLY both in a pipeline smoke run and in a
live task through the public API; the PLY rendered in the existing viewer and
downloaded as `application/octet-stream` with a `.ply` name. A mesh-vs-splat
benchmark recorded representation-appropriate metrics.

### Verified after the change

| Check | Result |
|---|---|
| Backend suite | **619 passed** (573 baseline + 46 new) |
| Scene ML suite | **172 passed, 3 skipped** (175 collected; 136 baseline + 36 new tests, 1 opt-in real test skipped) |
| Image-quality suite | **47 passed** |
| Frontend suite | **161 passed** across 25 files (148 tracked baseline + 13 new) |
| Real Splatfacto smoke (300 iterations, 800 px, 11 images) | **completed**: 8 015 Gaussians, 1 989 312-byte PLY, independent validation, PSNR 13.41 / SSIM 0.643 / LPIPS 0.739 |
| Live API task (3 000 iterations, 800 px, 11 images) | **COMPLETED in 205 s**: 208 582 Gaussians, 51 729 930-byte PLY, `format=PLY`, `mime_type=application/octet-stream`, `representation=GAUSSIAN_SPLAT`, PSNR 14.37 / SSIM 0.478 / LPIPS 0.521 |
| Independent PLY re-validation | downloaded live PLY re-read: 208 582 Gaussians, SHA-256 matches the registered result, pinned property order |
| Edge browser proof | **passed**: viewer kind `SPLAT`, 208 582 Gaussians, SH 3, 2 966 ms load, rotation/zoom deltas 9.73/8.65, `.ply` download with `ply` magic, PLY info panel and label |
| Mesh-vs-splat benchmark | mesh 16 486 vertices / 28 832 faces / 941 152 B; splat 205 462 Gaussians / 50 956 170 B / 56.2 s training; PSNR 14.68, SSIM 0.507, LPIPS 0.486 (3 000 iters, 800 px) |
| Ruff / format | clean for all backend and ML changed code |
| `alembic check` | no schema drift after the PLY migration |
| Compose validation | base + GPU + splat overlay `config -q` pass |
| `pip check` | clean for the base scene environment; the isolated splat target is import-verified |

**Baseline corrections recorded before the work:**

* The heartbeat test flaked only when four suites ran concurrently; it now polls
  with a bounded deadline and the full backend suite passes (no product change).
* The documented frontend baseline "173 passed / 28 files" was **not
  reproducible from the working tree**: 4 untracked test files existed only in a
  stale image. The verifiable tracked baseline is **148 passed / 24 files**;
  increment 15 adds 13 tests (161 / 25). This is a documentation correction, like
  the earlier scene-count correction.
* `pytest -q` with `pyproject.toml` already containing `-q` is `-qq`, which hides
  the summary. Counts here come from runs without the extra `-q`.

## 2. Compatibility findings

| Item | Finding | Resolution |
|---|---|---|
| Target runtime | Python 3.12.3, torch 2.14.1+cu130, torchvision 0.29.2, RTX 3060 12 GB | pinned neural target layered on the verified scene image |
| Nerfstudio 1.1.5 import chain | `ns-train` imports `method_configs` and heavy optional packages; Splatfacto itself does not need `tinycudann` | a controlled Python entry point builds the upstream `TrainerConfig` directly (allowed by addendum 5.1) |
| Missing runtime deps found by real runs | `docstring_parser`, `rawpy` (cp312/NumPy-2 wheel), `nerfacc`, `pyquaternion`, `scikit-learn` (+`joblib`,`threadpoolctl`,`cloudpickle`,`narwhals`), `lpips` (AlexNet weights), `open3d` (+`plotly`,`dash`,`janus`) | all pinned in `requirements-splat.txt` with versions resolved once and recorded |
| CUDA 13 split toolchain | nvcc 13.0 + ptxas 13.0 but `nvidia-cuda-crt`/`nvidia-nvvm` 13.5 produced PTX 9.5 → `ptxas fatal: Unsupported .version 9.5` | align `crt`/`nvvm`/`nvcc`/`ptxas` at 13.0.88 |
| CUDA 13 headers | `cuda_fp16.h` needs `nv/target` from CCCL | pin `nvidia-cuda-cccl==13.0.85` |
| Linker | the runtime wheel ships `libcudart.so.13` but no `libcudart.so` | create the symlink during the image build and add the directory to `LD_LIBRARY_PATH` |
| Host compiler | the runtime scene image has no compiler | `build-essential` + `python3.12-dev` only in the neural image |
| gsplat build | JIT build needs `ninja`, nvcc on `PATH`, a host compiler and ~10 min | kernels are compiled and baked at image build (`MAX_JOBS=3`), verified by `backend._C is not None` |
| Checkpoint layout | 1.1.5 stores Gaussian parameters in `_model.gauss_params.*`; LPIPS weights are also in the pipeline state | exporter accepts both `_model.gauss_params.*` and `model.*` |
| `torch.load(weights_only=True)` | a NumPy scalar/dtype in the checkpoint is rejected | narrow `add_safe_globals` for NumPy scalar/reconstruct/dtype classes only |
| Quaternion norms | trained Splatfacto quaternions are unnormalized; some are far below 1e-3 | validator accepts any finite non-zero norm (rejects only denormal/zero) |
| PLY dialect | 1.1.5 `ns-export gaussian-splat` binary little-endian, 59 float properties at SH 3 | validator enforces the exact property set/order and file size |
| Frontend renderer | `@mkkellogg/gaussian-splats-3d@0.4.7` (MIT, peer three>=0.160) uses SharedArrayBuffer by default | `sharedMemoryForWorkers: false` avoids requiring COOP/COEP headers, lazy import keeps GLB routes unchanged |
| Disk / Docker | the neural image is 22.5 GB (layers shared with the 20.7 GB scene image); concurrent builds/tests exhausted Docker Desktop on this host | builds/tests were serialised; documented as operational guidance |

## 3. Implemented behaviour

1. **Representation contract.** `SCENE_REPRESENTATION=mesh|gaussian_splat`
   (default `mesh`). A splat selection requires `SCENE_SPLAT_ENABLED=true` and
   `SCENE_OUTPUT_FORMAT=PLY`; invalid combinations fail at startup. The selected
   representation and method are written to `GenerationTask.parameters` at
   creation (`app/services/scene_methods.py`), so retries and recovery cannot be
   re-targeted by a later environment change.
2. **Deterministic routing.** Splat tasks publish to `scene_gaussian_splat`
   (deployment-configurable); mesh tasks stay on `scene_reconstruction`. The
   queue is chosen from the persisted outbox payload. Each scene worker registers
   one capability and rejects the other representation with
   `SCENE_WORKER_INCOMPATIBLE`.
3. **Shared sparse stages, no OpenMVS for splats.** The splat path runs image
   preparation, feature extraction/matching, sparse reconstruction, selection and
   undistortion, then `SPLAT_DATASET_PREPARATION`, `SPLAT_TRAINING`,
   `SPLAT_EXPORT`. No `OPENMVS_*`, dense, mesh, texturing or GLB stage runs.
4. **Nerfstudio dataset adapter.** Reads the undistorted COLMAP model (binary or
   text) directly; writes `transforms.json`, per-frame intrinsics, the upstream
   `applied_transform` and `sparse_pc.ply`; resizes only when configured and
   scales intrinsics accordingly. It validates image identity, camera models,
   poses, principal points and sparse points, then performs an independent
   handedness/forward/up check and a reprojection self-check against COLMAP
   observations (median 0.18–0.31 px on the retained scene).
5. **Controlled training.** `nerfstudio_runner.py` invokes a pinned entry point
   inside the isolated site directory through the existing `CommandRunner`
   (argument array, timeout, process-group termination, cancellation polls,
   logs). The entry point builds the upstream 1.1.5 Splatfacto `TrainerConfig`,
   records the resolved configuration and a training summary, and never imports
   the neural stack into the worker process.
6. **Checkpoint reuse.** `splat_manifest.json` keys reuse on the dataset
   fingerprint (image bytes, intrinsics, poses, points), runtime versions and all
   output-affecting settings; resource budgets/timeouts are excluded. Reuse
   re-validates the PLY before accepting it.
7. **Export and independent validation.** The exporter writes the exact pinned
   dialect in streamed chunks, filters non-finite and sub-threshold-opacity
   Gaussians like upstream, validates the temporary file, atomically publishes it
   and re-hashes the published file. The validator checks schema/order, size vs
   vertex count, finiteness, count/artifact limits, plausible positions/scales/
   opacity and non-zero quaternions.
8. **Result contract.** `ResultFormat.PLY` with a forward-only CHECK-constraint
   migration; `PLY` results are served as `application/octet-stream` with a
   `.ply` filename; metadata carries representation, dataset/camera checks,
   training metrics, runtime/device facts and artifact facts, never paths or
   tensors. Existing GLB results and download behaviour are unchanged.
9. **Frontend.** Result `format` selects the renderer. GLB keeps `GLTFLoader`;
   PLY is parsed for bounds/count/SH degree, then rendered by the lazily imported
   splat renderer inside the existing R3F canvas, with disposal on change/failure/
   unmount, splat-specific info rows, a `.ply` download label, and clear errors
   for malformed/oversized/WebGL failures.
10. **Worker image.** `Dockerfile.splat` layers on the verified scene image,
    installs the pinned neural stack into `/opt/splat-site` with `--no-deps`,
    bakes the LPIPS AlexNet weights and the compiled gsplat kernels, and exposes
    the queue/representation settings. Application sources are copied after the
    expensive layers, so source-only rebuilds do not recompile CUDA.
11. **Benchmark.** `benchmark_splat.py` compares the representations on the same
    COLMAP model/images and records representation-appropriate metrics; it never
    claims polygon/Gaussian equivalence.

## 4. Task evidence

| Task | Evidence |
|---|---|
| I15-01 | Baseline re-confirmed; plan/AC document written; compatibility study in this review |
| I15-02 | `SCENE_*` settings validated (unit tests), env examples, redacted logging |
| I15-03 | Persisted representation + outbox `representation` + queue routing + capability rejection (unit/DB tests) |
| I15-04 | `PLY` enum + Alembic `7c5d9a1b4e20` + constraint test; download extension/MIME + API tests |
| I15-05 | `colmap_model.py`, `nerfstudio_dataset.py`, camera/projection checks and resize tests |
| I15-06 | `splat_validator.py` with schema/size/range/quaternion tests |
| I15-07 | `splat_exporter.py`; real checkpoint export; schema and filter tests |
| I15-08 | `neural_pipeline.py`, `nerfstudio_runner.py`, `splat_train_entry.py`; manifest reuse, VRAM, OOM/timeout tests |
| I15-09 | Representation dispatcher; stage-order test (no OpenMVS for splats) |
| I15-10 | `Dockerfile.splat`, `requirements-splat.txt`, `compose.splat.yaml`; real build + runtime preflight + baked kernels |
| I15-11 | 46 new backend cases (settings, representation, routing, PLY result/migration, recovery, API task) |
| I15-12 | 36 new ML cases + opt-in `test_real_splat.py`; real smoke run |
| I15-13 | Format dispatch, lazy renderer, splat info panel, disposal, error states; 13 new frontend tests |
| I15-14 | Browser proof, benchmark, README/deployment/API/spec notes, this review, HANDOFF/NEXT_SESSION |

## 5. Acceptance criteria traceability

| ID | Status | Evidence |
|---|---|---|
| I15-AC-01 | **Passed** | Mesh default unchanged; GLB result/download tests and the mesh scene suite pass; no mesh stage or contract changed |
| I15-AC-02 | **Passed** | API/object/scene images import no Nerfstudio/gsplat; neural packages isolated in `/opt/splat-site`; settings reject a splat selection without the gate/PLY |
| I15-AC-03 | **Passed** | Stage-order test and live diagnostics: shared COLMAP stages, no OpenMVS stage for splats; COLMAP cameras sparse points reused |
| I15-AC-04 | **Passed** | Projection self-check on synthetic fixtures and the real model (median 0.18–0.31 px), resize/intrinsics tests, identity manifest |
| I15-AC-05 | **Passed** | Standard Splatfacto trained and exported on the RTX 3060 (smoke 300 iters/800 px and live 3 000 iters/800 px); the production profile is documented as 30 000 iters/1600 px |
| I15-AC-06 | **Passed** | Exact pinned PLY schema, `application/octet-stream`, `.ply` filename, PLY DB format; malformed/truncated/oversized PLY rejected |
| I15-AC-07 | **Passed** | Frontend tests + Edge proof: SPLAT kind, 208 582 Gaussians, SH 3, controls, `.ply` download, disposal |
| I15-AC-08 | **Passed** | Migration round-trip and constraint test; legacy GLB rows/API tests unchanged |
| I15-AC-09 | **Passed** | Representation persisted through task recovery; deterministic queue routing (unit tests); worker capability rejection (unit-tested helper used by the adapter); cancellation/timeout process-group termination and checkpoint-manifest tests; the cancelled live task's project deletion was accepted and the worker was recreated; failed attempts preserve the previous current result by the unchanged transactional result service |
| I15-AC-10 | **Passed** | Benchmark JSON with mesh geometry facts and splat training/quality facts; no equivalence claim; reproducible command documented |
| I15-AC-11 | **Passed** | Mesh remains the default; splat requires explicit settings and the overlay; no automatic replacement |
| I15-AC-12 | **Passed** | Bounded iterations/scale/dimension/artifact/timeout; VRAM admission; stable OOM/timeout codes; one task at a time; no silent CPU fallback |
| I15-AC-13 | **Passed** | Stable `SPLAT_*`/`SCENE_WORKER_INCOMPATIBLE` codes; errors tested; result metadata contains no paths/tensors/logs |
| I15-AC-14 | **Passed** | README, deployment, API, spec note, plan, this review, HANDOFF and NEXT_SESSION updated |

## 6. Defects found and fixed during verification

1. Alembic constraint name was double-prefixed by the naming convention; fixed
   with `op.f(...)` (migration failed before any test ran).
2. The neural image lacked a compiler and Python headers; gsplat could not build
   (`nvcc: gcc not found`, `Python.h` missing).
3. CUDA 13 requires CCCL (`nv/target`); pinned `nvidia-cuda-cccl`.
4. `nvidia-cuda-crt`/`nvidia-nvvm` 13.5 produced PTX 9.5 rejected by ptxas 13.0;
   all CUDA components aligned at 13.0.88.
5. The runtime wheel has no unversioned `libcudart.so`; the link failed until the
   symlink was added.
6. gsplat's build found nvcc only by name on `PATH`; the image now puts the
   toolkit `bin` first and the runner adds it for any first-run build.
7. Real training needed `scikit-learn` (seed initialization), `lpips` with cached
   AlexNet weights (metric construction), and `open3d` (sparse-point loading);
   none of these were visible from static import analysis.
8. `torch.load(weights_only=True)` rejected NumPy scalars/dtypes in the
   checkpoint; narrow safe-globals were added.
9. The exporter assumed `model.*` keys; the real 1.1.5 checkpoint uses
   `_model.gauss_params.*`.
10. The validator's 1e-3 quaternion-norm floor rejected a legitimate 3 000-
    iteration checkpoint; the floor is now 1e-6 (zero/denormal still rejected).
11. The splat renderer threw `SharedArrayBuffer ... requires crossOriginIsolated`
    in Edge; `sharedMemoryForWorkers: false` fixes it without COOP/COEP.
12. The first live attempt executed the mesh pipeline because the dispatcher and
    scene worker containers predated the new images; recreating them with the new
    images made routing/capability checks effective (operational finding).

## 7. Known limitations and honest gaps

* **Production iteration profile not executed end-to-end.** The live task used
  3 000 iterations at 800 px (205 s total) to fit verification time; 30 000
  iterations at 1600 px remains the documented production default. The same code
  path is exercised; only the budget differs. The measured quality figures are
  therefore short-budget smoke values, not quality claims.
* **Canonical mesh-worker rebuild not completed.** Rebuilding
  `ml/scene_reconstruction/Dockerfile` recompiles OpenCV/OpenMVS and did not
  finish in the available time; the mesh worker used a **derived runtime image**
  (base layers + refreshed `/app` and `/opt/scene_reconstruction`) as documented
  interim evidence. The splat image itself was built canonically.
* **Artifact size at the production profile** may approach the 512 MiB default
  cap (3000 iterations produced 50.9 MB / 205 k Gaussians). The limit is
  configurable and enforced before registration; a 30k-iteration measurement is
  still owed if the default is to be tightened.
* **Nerfstudio license/runtime** (`Apache-2.0`, gsplat `Apache-2.0`) is an
  opt-in image only; the default stack remains unchanged.
* The frontend full-tree `prettier --check` still reports pre-existing CRLF files
  unrelated to this increment; all changed files pass.

## 8. Next step

Increment 15 is complete. Rebuild the canonical scene-worker image and measure a
full 30 000-iteration splat artifact when time/GPU allows (only the budget and
artifact-size default would change). Increment-11/12 behaviour, the mesh
algorithms, the released MVP contract and later increments were not modified.
