# Continue in a New Session

- **Last updated:** 2026-11-27 (post-MVP increment 15 implemented and verified; no later increment started)
- **Current phase:** Phases 2–10 complete; MVP 1.0.0 released. Increments 11 (image quality), 12 (ALIKED + LightGlue), 13 (advanced object generation), 14 (mesh/texture enhancement) and 15 (optional neural scene reconstruction) are implemented.
- **Next step:** no new increment. If continuing the neural representation, rebuild the canonical `ml/scene_reconstruction/Dockerfile` (mesh worker) and measure a full 30 000-iteration / 1 600 px Splatfacto artifact before tightening the 512 MiB artifact default. Do not start increment 16.
- **Read first:** [`HANDOFF.md`](HANDOFF.md) Sections 1/5/10, then [`AI_DEVELOPMENT_GUIDE.md`](AI_DEVELOPMENT_GUIDE.md), then [`reviews/increment15_closeout.md`](reviews/increment15_closeout.md) and [`additions/15_implementation_plan.md`](additions/15_implementation_plan.md).

This file is the short continuation entry point. `HANDOFF.md` remains the full source of project state.

> **Latest change (2026-11-27):** increment 15 adds an optional Nerfstudio
> Splatfacto Gaussian-PLY representation beside the unchanged COLMAP + OpenMVS
> mesh path. The representation is persisted in the task, routed to the
> dedicated `scene_gaussian_splat` queue, produced by a dedicated worker image
> (`Dockerfile.splat`, isolated `/opt/splat-site`, baked LPIPS weights and
> compiled gsplat kernels), exported in the exact `ns-export` dialect and
> validated independently. `ResultFormat.PLY` is a forward-only migration
> (`7c5d9a1b4e20`); PLY downloads use `application/octet-stream` and a `.ply`
> filename. The frontend dispatches on `format` and lazy-loads the splat
> renderer. Verified: backend **619**, scene ML **172 + 3 skipped**, object ML
> **135 + 3 skipped** (unchanged), image-quality **47**, frontend **161**; real
> Splatfacto smoke (300 iters/800 px: 8 015 Gaussians, 1.99 MB), live API task
> (3 000 iters/800 px: 208 582 Gaussians, 51.7 MB, PSNR 14.37/SSIM 0.478/LPIPS
> 0.521), independent re-validation, Edge viewer proof and a mesh-vs-splat
> benchmark. The production 30 000-iteration/1 600 px profile was not executed
> end-to-end. Frontend baseline correction: **148 tracked tests**, not 173.
>
> **Prior change (2026-11-26, SF3D):** increment-13 real evidence completed
> (gated weights, 2/2 real tests, live task, 12/12 benchmark). Do not repeat it
> unless the pin or the SF3D image changes.

---

## 0. Resume in one minute

1. Open `H:\Study\Univer\projects\mogen` and read this file, `HANDOFF.md`
   Sections 1/5/10, [`reviews/increment15_closeout.md`](reviews/increment15_closeout.md)
   and the increment-15 addendum/plan.
2. Confirm the base development stack:
   `docker compose ps -a` (the gitignored `.env` sets
   `COMPOSE_FILE=compose.yaml;compose.gpu.yaml`). Nine services healthy;
   `migration`/`model-init` `Exited (0)`. The default object worker is TripoSR on
   `cuda:0`; the default scene worker has `SCENE_MESH_POSTPROCESS_ENABLED=false`
   and **no** splat capability. The default representation is `mesh`.
3. Run the baseline in Section 2 before changing anything.
4. The optional splat stack is an overlay, not part of the default stack:
   `docker compose -f compose.yaml -f compose.gpu.yaml -f compose.splat.yaml up -d`
   (build `scene-worker` first; the neural image layers on it). Stop it and
   recreate `api` from the base files to return to mesh defaults.
5. Implement only the next requested change; update `HANDOFF.md`, this file and
   add a close-out review under `docs/reviews/`.

---

## 1. Repository map (current focus)

| Area | Path |
|---|---|
| Backend API/workers | `backend/app/` (`services/scene_methods.py`, `tasks/outbox_publisher.py`, `tasks/scene_pipeline.py`, `services/result_service.py`) |
| DB models/migration | `backend/app/db/models/`, `backend/alembic/versions/7c5d9a1b4e20_add_ply_result_format.py` |
| Scene ML | `ml/scene_reconstruction/` (`pipeline.py`, `neural_pipeline.py`, `nerfstudio_dataset.py`, `nerfstudio_runner.py`, `splat_train_entry.py`, `splat_exporter.py`, `splat_validator.py`, `colmap_model.py`, `splat_config.py`, `benchmark_splat.py`) |
| Neural image | `ml/scene_reconstruction/Dockerfile.splat`, `requirements-splat.txt`, `compose.splat.yaml` |
| Frontend viewer | `frontend/src/features/model-viewer/` (`splat/splatPly.ts`, `splat/splatAdapter.ts`, `hooks/useModelLoader.ts`, `components/ModelInfoPanel.tsx`) |
| Increment-15 evidence | `docs/reviews/increment15_closeout.md`, `.proof/increment15/` (gitignored: real smoke JSON, live PLY/summary, browser proof, benchmark) |
| Prior increments | `docs/reviews/increment{11,12,13,14}_closeout.md`, `docs/additions/` |

---

## 2. Baseline commands (run before and after changes)

Use the documented containers; do **not** pass `-q` twice (the pytest config
already sets it, and `-qq` hides the summary line, which caused a reporting
mistake in earlier sessions).

```powershell
# Stack
docker compose ps -a
curl.exe -s -o NUL -w "%{http_code}`n" http://127.0.0.1:8000/health/ready
curl.exe -s -o NUL -w "%{http_code}`n" http://127.0.0.1:5173/

# Backend (619 expected; scratch DB tests are included)
docker compose run --rm --no-deps api pytest

# Scene/neural ML (172 passed, 3 skipped; 175 collected)
docker run --rm mogen-splat-worker:dev /opt/venv/bin/python -m pytest /opt/scene_reconstruction/tests -p no:cacheprovider
# without the neural image:
docker run --rm mogen-scene-worker:dev /opt/venv/bin/python -m pytest /opt/scene_reconstruction/tests -p no:cacheprovider

# Image quality (47)
docker run --rm mogen-splat-worker:dev /opt/venv/bin/python -m pytest /opt/image_quality/tests -p no:cacheprovider

# Object ML (unchanged by increment 15: 135 passed + 3 skipped)
docker run --rm mogen-object-worker:dev python -m pytest /opt/object_generation/tests

# Frontend (161 passed / 25 files)
docker run --rm mogen-frontend:dev npm run test:run
# Typecheck/lint/format for changed files
docker run --rm -v "${PWD}/frontend/src:/app/src" -w /app mogen-frontend:dev npm run typecheck
docker run --rm -v "${PWD}/frontend/src:/app/src" -w /app mogen-frontend:dev npm run lint

# Backend lint/format/migration
docker compose run --rm --no-deps api ruff check .
docker compose run --rm --no-deps api ruff format --check .
docker compose run --rm api alembic check
docker compose -f compose.yaml -f compose.gpu.yaml -f compose.splat.yaml config -q
```

**Opt-in real Splatfacto check** (GPU, retained Sceaux COLMAP workspace):

```powershell
docker run --rm --gpus all -v "${PWD}/.proof:/proof" `
  -e RUN_SPLAT_REAL_TESTS=1 -e SPLAT_REAL_WORKSPACE=/proof/scene-check-iq `
  -e SPLAT_REAL_ITERATIONS=200 mogen-splat-worker:dev `
  env PYTHONPATH=/opt/splat-site:/opt /opt/venv/bin/python -m pytest `
  /opt/scene_reconstruction/tests/test_real_splat.py -m real_splat
```

**Live task/browser proof scripts (gitignored):** `.proof/increment15/live_splat.ps1`
(API task, downloads the PLY and writes `live-splat-summary.json`) and
`.proof/viewer-tools/proof-splat.mjs` (Edge proof against a completed PLY
project; requires `SPLAT_PROJECT_ID`/`SPLAT_EMAIL`).

---

## 3. Baseline counts and corrections

| Suite | Current baseline | Notes |
|---|---|---|
| Backend | 619 passed | 573 + 46 increment-15 cases |
| Scene ML | 172 passed, 3 skipped (175 collected) | 136 + 2 baseline; +36 tests; 1 opt-in real test skipped |
| Object ML | 135 passed, 3 skipped (138 collected) | unchanged by increment 15 |
| Image-quality | 47 passed | unchanged |
| Frontend | 161 passed / 25 files | verifiable tracked baseline was **148 / 24**; the old "173 / 28" came from four untracked tests that existed only in a stale image |

---

## 4. Known traps and decisions (read before editing)

1. **The splat overlay needs rebuilt containers, not just rebuilt images.**
   Running containers keep the image they were created with. The first live
   attempt was routed to the mesh worker because the outbox dispatcher and scene
   worker containers predated the new images; `api` and `splat-worker` were
   correct. Recreate every service whose code changed:
   `docker compose ... up -d --force-recreate <services>`.
2. **The neural image layers on the scene worker image.** `Dockerfile.splat`
   `FROM mogen-scene-worker:dev`; build/verify `scene-worker` first. Application
   sources are copied *after* the CUDA compile so source-only rebuilds are cheap.
3. **Do not pass `pytest -q` twice.** `pyproject.toml` already sets `-q`; the
   double flag is `-qq` and hides the summary. Use JUnit XML where exact counts
   matter.
4. **Docker Desktop on this host is memory-sensitive.** A 15–22 GB neural build
   plus parallel suites plus a game exhausted the VM twice (HTTP 500 from the
   Docker API). Run heavy builds and suites serially; restart Docker Desktop if
   the engine stops answering.
5. **CUDA 13 toolchain pinning.** gsplat builds with `nvidia-cuda-nvcc`,
   `nvidia-cuda-crt`, `nvidia-nvvm` and ptxas **all at 13.0.88**, plus
   `nvidia-cuda-cccl==13.0.85` (`nv/target`) and an unversioned `libcudart.so`
   symlink. Mixing 13.5 components yields `ptxas fatal: Unsupported .version 9.5`.
6. **Splatfacto runtime dependencies are empirical.** Real training also needs
   `scikit-learn` (+ cloudpickle/narwhals), `lpips` with baked AlexNet weights,
   and `open3d` (+ plotly/dash/janus) for sparse-point loading. Import-only
   checks do not reveal these.
7. **Checkpoint export.** 1.1.5 uses `_model.gauss_params.*`; `torch.load(
   weights_only=True)` needs narrow NumPy safe-globals; quaternions are
   unnormalized (the validator accepts any finite non-zero norm).
8. **Browser isolation.** `@mkkellogg/gaussian-splats-3d` defaults to
   SharedArrayBuffer, which requires COOP/COEP. The adapter sets
   `sharedMemoryForWorkers: false`; do not remove it without adding the headers to
   Vite and nginx.
9. **The canonical mesh-worker rebuild is outstanding.** The Close-out used a
   derived runtime image for the mesh worker because a canonical rebuild
   recompiles OpenCV/OpenMVS; the splat image itself was built canonically.
10. **Line endings.** The frontend tree contains pre-existing CRLF files; the full
    `prettier --check` flags them. Only changed files are expected to be clean.
    Never rewrite sources with PowerShell `Set-Content` (BOM/encoding damage).

---

## 5. Where to continue

If a follow-up is requested, the only identified remaining work is:

1. Rebuild `ml/scene_reconstruction/Dockerfile` canonically (mesh scene worker)
   and recreate the stack.
2. Run one 30 000-iteration / 1 600 px Splatfacto task on the retained Sceaux
   dataset; record the artifact size/Gaussian count and, if needed, raise or
   tighten `SCENE_SPLAT_MAX_ARTIFACT_BYTES`.
3. Remove the increment-15 test users/projects after capturing evidence (the
   successful live project is `e4287c69-7161-49e6-bc03-3ce807477f04` from the
   recorded session; do not delete data you did not create).

Do not start increment 16 or re-open the mesh algorithms, increment-11
thresholds, increment-12 matching or the released MVP contract.

---

## 6. Definition of Done and reporting

Follow `AI_DEVELOPMENT_GUIDE.md` Section 20 and Section 18.4. Run the baseline
commands in Section 2 after changes. Add a close-out review in `docs/reviews/`
with task-by-task and criterion-by-criterion evidence, update `HANDOFF.md`, this
file, the affected ML README and configuration examples. Report only checks that
were actually executed, and distinguish passed, failed, skipped, blocked and not
executed.

For image changes, note that the canonical object build needs the ~6.4 GB
PyTorch devel layer, the canonical scene build recompiles OpenCV/OpenMVS and the
canonical neural build compiles gsplat; a derived runtime image is acceptable
only as explicitly documented interim evidence.
