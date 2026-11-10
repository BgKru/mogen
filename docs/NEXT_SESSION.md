# Continue in a New Session

**Last updated:** 2026-11-09 (end of Phase 8)
**Current phase:** Phases 2, 3, 4, 5, 6, 7 and 8 complete.
**Next phase:** Phase 9 — comprehensive testing and quality assurance.
**Read first:** [`HANDOFF.md`](HANDOFF.md), then [`AI_DEVELOPMENT_GUIDE.md`](AI_DEVELOPMENT_GUIDE.md), then this file and Phase 9 of [`10_development_roadmap.md`](specifications/10_development_roadmap.md).

This file is the short continuation entry point. `HANDOFF.md` remains the full source of project state; this file only tells the next session what to do first, what to reuse and where the boundaries are.

> **Latest change before this handoff (2026-11-09):** Phase 8 delivered the reliability, security and optimization work. Six findings were fixed: terminal task transitions could read a stale row (a mid-generation project deletion was masked); superseded result GLBs were never deleted; failed scene workspaces had no retention; OpenMVS tool probes left logs in the worker CWD; backup/restore was undocumented; and API tests could write uploads into the live `/data` volume. Backend suite is **509 passed**; frontend **130 passed**; scene ML **75 passed, 1 skipped**; object ML **35 passed, 1 skipped** (the previously recorded 32 was stale). Live drills: API recreation preserved an image byte-for-byte, Redis and PostgreSQL outages recovered with consistent state, and PostgreSQL + file-storage backup/restore matched counts and SHA-256. Report: [`reviews/phase8_closeout.md`](reviews/phase8_closeout.md).

---

## 0. Resume in one minute

1. Open `H:\Study\Univer\projects\mogen` and read this file plus `HANDOFF.md` Section 1, Section 5, Section 8 and Section 10.
2. Check the sandbox policy before running Docker (`HANDOFF.md` Section 6). Docker needs named-pipe access: with `danger-full-access` it runs directly; under `workspace-write` the CLI fails with "Access is denied" on `dockerDesktopLinuxEngine`. If approvals are disabled and Docker is blocked, report the baseline as **blocked** rather than guessing.
3. Check the stack: `docker compose -f compose.yaml -f compose.gpu.yaml ps -a`. Expected: nine healthy services, `migration` and `model-init` `Exited (0)`, `object-worker` and `scene-worker` healthy.
4. If the stack is not running, start it with `docker compose -f compose.yaml -f compose.gpu.yaml up -d` (add `--build` only if the images are missing or the source changed). Do **not** run `docker compose down -v`: the `app_data` and `triposr_model_cache` volumes contain user data and the pinned weights.
5. Confirm both workers are ready:
   - `docker compose logs object-worker | Select-String "triposr_model_loaded|object_generation_pipeline_ready"`.
   - `docker compose logs scene-worker | Select-String "scene_pipeline_ready"`.
   The object worker takes 4–5 minutes to load the 1.7 GB checkpoint on first start; the scene worker verifies its toolchain in a few seconds.
6. Run the baseline commands in Section 3 and compare with the expected counts in Section 2. Fix any real failure before writing code.
7. Read Section 2.1 (state left behind), Section 4 (Phase 9 scope), then use the prompt in Section 1.

**Do not:** recreate the worker lifecycle, outbox, generation/result API, reconstruction pipelines or the Phase 7 viewer; replace the outbox with direct Redis publication; delete the development database/`/data/projects`/model cache; change the viewer or the result/download contract unless a Phase 9 finding genuinely requires it; re-implement Phase 8's retention or cleanup. The next phase is Phase 9 (comprehensive testing and quality assurance).

---

## 1. Copy-paste prompt

> Working directory: `H:\Study\Univer\projects\mogen`. Read `docs/HANDOFF.md` first, then `docs/AI_DEVELOPMENT_GUIDE.md`, `docs/NEXT_SESSION.md` and Phase 9 of `docs/specifications/10_development_roadmap.md`. Phases 2–8 are complete; do not redo them. The stack was left running and healthy, and the Phase 8 images were rebuilt (see `NEXT_SESSION.md` Section 2.1); verify rather than assume, and if Docker is blocked by the sandbox report the baseline as blocked. Confirm the Section 5 baseline (expect 509 backend tests, 130 frontend tests, 75 scene ML unit tests plus the skipped opt-in real-reconstruction test, 35 object ML unit tests plus the opt-in real-model test, nine healthy services plus `migration` and `model-init` `Exited (0)`, three worker pings, the retention task registered in the cleanup worker, fresh dispatcher/recovery heartbeat files, an object worker that loaded the real TripoSR model and a scene worker that detected COLMAP 4.2.1 and OpenMVS 2.4.0; the Phase 7 real-browser viewer proof and the Phase 8 performance baseline are recorded in `docs/reviews/phase7_closeout.md` and `docs/reviews/phase8_closeout.md`, so do not run a new generation just to re-check delivery). Then implement Phase 9 (tasks 9.1–9.7) and close the remaining product acceptance criteria: run the complete frontend/backend/ML/security/performance/E2E matrix, add the committed CI quality gate (`TEST-AC-19`), decide the rate-limiting and session-cleanup open items, and produce the full test report, coverage report, ML/quality report, performance measurements, known-limitations list and release-readiness assessment, citing the applicable acceptance criteria. Do not re-open Phases 2–8 and do not change the viewer, result/download contract, outbox or reconstruction pipelines unless a Phase 9 finding genuinely requires it. Do not implement Phase 10+. Follow the Definition of Done and report format from the guide; update `docs/HANDOFF.md`, `docs/NEXT_SESSION.md` and add a Phase 9 close-out review.

---

## 2. Verified starting point

| Item | Value |
|---|---|
| Backend suite | **509 passed, 1 warning** (332 database/API, 169 unit, 8 API-shell) |
| Frontend suite | **130 passed** across 22 files; lint, typecheck, format check and build clean |
| Scene ML suite | **75 passed, 1 skipped**; the skip is the opt-in real reconstruction |
| Object ML suite | **35 passed, 1 skipped**; the opt-in real TripoSR test passed separately |
| Stack | eleven Compose services: `db`, `redis`, `migration` (`Exited (0)`), `model-init` (`Exited (0)`), `api`, `cleanup-worker`, `object-worker`, `scene-worker`, `outbox-dispatcher`, `task-recovery`, `frontend`; the other nine healthy |
| Object worker | Dedicated `mogen-object-worker:dev`, real TripoSR model loaded on CUDA, pipeline registered |
| Scene worker | Dedicated `mogen-scene-worker:dev`, COLMAP 4.2.1 and OpenMVS 2.4.0 verified, real pipeline registered |
| Viewer | `/projects/{id}/result`; R3F 9.8.2 / Drei 10.7.9 / Three.js 0.187.0; 35 viewer tests; real object, medium scene and large scene verified in Edge with SHA-identical downloads; metrics in `.proof/viewer/*-verify.json` (gitignored) |
| Model cache | `triposr_model_cache` volume populated; `model.ckpt` SHA-256 `429e2c6b22a0923967459de24d67f05962b235f79cde6b032aa7ed2ffcd970ee` |
| Data | Pre-existing development rows and a user-created project remain; do not reset or bulk-delete |
| Retained failed task | Task `379073b3-80d5-4b1d-b571-2ea689cc39ff` (project `3e3a52c1-c53d-48ed-8511-b21d8d162996`, now soft-deleted) is `FAILED` at `SPARSE_RECONSTRUCTION` for four low-texture PNGs. Its workspace `/data/work/scene/379073b3…` is retained for diagnostics. It becomes eligible for the retention sweep ~2026-11-14; do not delete it manually. |
| Generation/result API | `POST /generate` (202/200), `GET /status`, `GET /result`, `GET /download` |
| Phase 6 review | [`reviews/phase6_closeout.md`](reviews/phase6_closeout.md) |
| Phase 7 review | [`reviews/phase7_closeout.md`](reviews/phase7_closeout.md) |
| Phase 8 review | [`reviews/phase8_closeout.md`](reviews/phase8_closeout.md) |
| Operations | [`operations/backup_restore.md`](operations/backup_restore.md) and `operations/verify_current_results.py` |
| Performance baseline | Phase 8 close-out Section 3.6; raw JSON in `.proof/phase8/evidence/` (gitignored) |

Both generation modes are real and both result types render in the viewer. The Phase 7 fixture projects were deleted after verification; the repeatable viewer check is the unit suite (`frontend/src/features/model-viewer/**/*.test.ts*`), and the real-browser metrics remain in `.proof/viewer/`. Do not run a new object generation solely to re-verify the viewer or the Phase 8 baseline, especially while the host GPU is saturated.

### 2.1. State left behind by the Phase 8 session

- **The stack is running and was left healthy.** Nine services healthy; `migration` and `model-init` `Exited (0)`; object worker healthy with TripoSR loaded; scene worker healthy. Do not recreate it just to "start clean".
- **Images:** `mogen-api:dev`, `mogen-object-worker:dev` and `mogen-scene-worker:dev` were rebuilt with the Phase 8 code (verified by inspecting the images, not by assuming); `mogen-frontend:dev` is unchanged. The single `up -d --build` invocation was stopped while Compose was redundantly rebuilding the same object-worker Dockerfile for `model-init`, after the three images had been built; the services were then recreated with `--no-deps --force-recreate`. A cold rebuild can re-download shared CUDA layers (20–40 minutes on this host).
- **Final verification numbers:** backend 509 passed in ~101 s; ruff/format clean (112 files); `alembic check` no drift; `pip check` clean; frontend 130; scene ML 75 + 1 skipped; object ML 35 + 1 skipped; `--verify-tools` COLMAP 4.2.1 + OpenMVS 2.4.0.
- **Evidence (gitignored):** `.proof/phase8/evidence/drill-summary.json` (outage/persistence drills), `performance-summary.json` (API/upload/download/cleanup/viewer numbers), `viewer-memory.json`, the PostgreSQL dump sample, and the restored file sample. The drill and measurement scripts are `.proof/phase8/drill.ps1` and `.proof/phase8/measure.ps1`; the viewer-memory script is `.proof/viewer-tools/measure-phase8-memory.mjs`. They create their own fixture rows and clean them up — read the scripts before running them and verify the "remaining_rows" output.
- **Test isolation change:** `backend/tests/db/conftest.py` now sets `storage_root=/tmp/mogen-test-storage` for API test clients. Do not remove it: without it, tests write fixture uploads into the live `/data/projects` volume.
- **Retention is active:** the cleanup worker runs `cleanup_scene_workspaces_task` hourly (beat). The retained Phase 6 workspace `/data/work/scene/379073b3-…` is untouched now but becomes eligible after `SCENE_WORKSPACE_RETENTION_HOURS` (default 168, ~2026-11-14). Set it to `0` if that workspace must be preserved indefinitely.
- **Open items Phase 9 must decide:** `TEST-AC-19` CI gate (still missing), auth rate limiting (429), scheduled session cleanup, scheduled backups, and the fact that Phase 8's `M8` is only partially achieved (reliability passes; the comprehensive matrix is Phase 9). See `HANDOFF.md` Section 8 and the Phase 8 close-out Section 7.
- **Host GPU:** an unrelated game process was holding ~5 GB and ~39 % of the GPU during Phase 8; this is why no new inference was run. Check `nvidia-smi` before deciding to run real object generation.
- **No fixture credentials are retained.** The Phase 7 fixture projects were deleted; do not rely on `.proof/viewer/fixtures.json`. For API-driven checks, register a fresh user through `http://localhost:5173/api/v1/...` with `Origin: http://localhost:5173` (not `127.0.0.1`), keep the cookie jar, and send `X-CSRF-Token` on unsafe methods. Remove the rows/files you create.

---

## 3. First commands

Run from `H:\Study\Univer\projects\mogen`.

```powershell
docker compose -f compose.yaml -f compose.gpu.yaml config -q
docker compose -f compose.yaml -f compose.gpu.yaml ps -a
docker compose exec cleanup-worker sh -c 'celery -A app.tasks.celery_app:celery_app inspect ping -d celery@$HOSTNAME --timeout 5'
docker compose exec object-worker sh -c 'celery -A app.tasks.celery_app:celery_app inspect ping -d celery@$HOSTNAME --timeout 5'
docker compose exec scene-worker sh -c 'celery -A app.tasks.celery_app:celery_app inspect ping -d celery@$HOSTNAME --timeout 5'
docker compose exec cleanup-worker sh -c 'celery -A app.tasks.celery_app:celery_app inspect registered -d celery@$HOSTNAME --timeout 5'   # cleanup_storage_task + cleanup_scene_workspaces_task
docker compose exec outbox-dispatcher cat /tmp/outbox-dispatcher.heartbeat
docker compose exec task-recovery cat /tmp/task-recovery.heartbeat
docker compose run --rm --no-deps api pytest > "$env:TEMP\pytest.log" 2>&1
Get-Content "$env:TEMP\pytest.log" -Tail 2          # 509 passed, 1 warning
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
docker run --rm mogen-frontend:dev npm run test:run  # 130 passed
docker run --rm mogen-frontend:dev npm run build
```

Also check the object worker logs for `triposr_model_loaded` and `object_generation_pipeline_ready`, the scene worker log for `scene_pipeline_ready`, `http://127.0.0.1:8000/health/ready`, `http://127.0.0.1:5173/` and the proxy (`http://127.0.0.1:5173/api/v1/probe` must return a JSON `NOT_FOUND` 404). Fix any baseline failure before writing code. If the sandbox blocks Docker, report the baseline as **blocked**; do not guess at results. `HANDOFF.md` Section 6 and Section 10.3 describe the policy in detail.

**Known environment caveat carried over from Phase 7/8.** A new OBJECT task can stall in `MODEL_GENERATION` when an unrelated host process pins the GPU (`nvidia-smi` shows a game and no CUDA compute process for the worker). If the task heartbeat stops advancing while the stage stays `MODEL_GENERATION`, delete the test project through the API, restart `object-worker`, and wait for `triposr_model_loaded` again; do not wait indefinitely or start more object tasks. Phase 8 confirmed the condition (a game process holding ~5 GB and ~39 % of the GPU) and deliberately did not run new inference. This is a host condition, not a code defect; report it if it recurs.

---

## 4. Phase 9 scope and order

Follow Phase 9 of the roadmap (tasks 9.1–9.7) and its deliverables.

1. **9.1 Frontend tests.** Run unit, component, API-interaction, viewer tests, typecheck and lint; add missing primary-component coverage.
2. **9.2 Backend tests.** Run unit, API, database, authorization, storage, Celery and outbox suites; keep the Phase 8 additions.
3. **9.3 ML integration.** Execute real TripoSR inference, real COLMAP/OpenMVS processing, GLB validation and processing-performance tests.
4. **9.4 End-to-end.** Registration, login, project creation, object and scene uploads, both generations, status, visualization, download, failure, retry, failed regeneration with previous-result preservation, deletion during processing and recovery after worker interruption.
5. **9.5 Security.** Authentication, authorization, CSRF, file upload validation, user isolation and private-asset access.
6. **9.6 Performance.** Object (small and large), scene (small and complex) and GLB loading; reuse the Phase 8 baseline and fill its gaps (no small/large object split was measured yet).
7. **9.7 Final fixes and release readiness.** Then the CI gate and the release-readiness assessment.

**Phase 9 deliverables (report them explicitly):**

- Full test report.
- Code coverage report (targets in `09_testing.md` Section 19; Phase 5 measured 89 % with the `generation_tasks` shortfall).
- ML processing report and reconstruction quality report.
- Performance measurements for both object sizes and both scene sizes.
- List of known limitations.
- Release-readiness assessment.

**Phase 9 acceptance criteria (cite each):**

- All mandatory automated tests pass.
- Both real ML pipelines have been executed successfully.
- Both workflows passed end-to-end validation.
- Generated GLB files pass validation.
- All mandatory product acceptance criteria (`AC-01..14`) are satisfied.
- No known unresolved critical defects remain.

**Known gaps to close or explicitly decide:**

- `TEST-AC-19` — a committed CI quality gate; none exists yet. This is the only unmet `TEST-AC`.
- Auth rate limiting (the API contract lists `429`); either implement it or record it as an accepted MVP limitation with justification.
- Scheduled session cleanup (`SessionRepository.delete_expired`/`delete_revoked` exist but no periodic job runs them).
- Scheduled backups (the procedure exists in `docs/operations/backup_restore.md`; no scheduler is installed).
- A committed Playwright E2E suite; all browser proofs are out-of-tree in `.proof/`.
- `M8` is only partially achieved because the comprehensive matrix is Phase 9.

**Reading:** Phase 9 in `10_development_roadmap.md`; all of `09_testing.md`; `04_backend_specification.md`; `08_infrastructure.md`; `api_contracts.md`; `reviews/phase8_closeout.md`.

---

## 5. Hooks to reuse

| Need | Where |
|---|---|
| Viewer module and result page | `frontend/src/features/model-viewer/`, `frontend/src/pages/ModelViewerPage/` |
| Result metadata | `GET /api/v1/projects/{id}/result` — `backend/app/api/v1/endpoints/results.py` |
| Authorized GLB bytes | `GET /api/v1/projects/{id}/download` |
| Generation status | `GET /api/v1/projects/{id}/status` |
| Frontend API client and DTO mapping | `frontend/src/shared/api/` |
| Generation panel and details page | `frontend/src/features/generation/`, `frontend/src/pages/ProjectDetailsPage/` |
| Outbox/recovery/worker lifecycle | `backend/app/tasks/`, `backend/app/services/` |
| Cleanup and retention | `backend/app/services/cleanup_service.py`, `backend/app/services/workspace_retention_service.py` |
| Phase 7 browser proof scripts | `.proof/viewer-tools/` (gitignored) |
| Phase 8 drills and measurements | `.proof/phase8/` (gitignored) |
| Backup/restore and consistency checks | `docs/operations/backup_restore.md`, `docs/operations/verify_current_results.py` |

---

## 6. Guardrails

- Do not change the backend generation/result contracts, the outbox, the reconstruction pipelines or the Phase 7 viewer unless a Phase 9 finding genuinely requires it; record the finding first.
- Do not undo the Phase 8 hardening: refreshed terminal reads (`populate_existing`/`get_refreshed`), superseded-result cleanup jobs, scene-workspace retention, the preflight scratch directory, or the test storage root (`/tmp/mogen-test-storage`). Each fixed a real finding; see the Phase 8 close-out.
- Do not expose storage keys, absolute paths or stack traces through the UI/API.
- Keep dependencies pinned; do not loosen the viewer pins without recording why.
- Do not delete the pre-existing development database rows, `/data/projects` directories or the retained failed-task workspace `/data/work/scene/379073b3…`. Remove only the rows/files you create and verify.
- Do not delete `.proof/` (gitignored): it holds the Phase 7 browser proof and the Phase 8 drill/measurement evidence. `.proof/phase8.jpg` and `.proof/phase8-big.jpg` are reusable upload fixtures.
- Do not present the recorded TripoSR/COLMAP/OpenMVS timings or a copied GLB as a fresh run; Phase 9 must execute the real pipelines for its ML acceptance evidence.
- Do not stage, commit or rewrite git history unless the user asks.
- Do not modify `docs/specifications/` or `docs/architecture/` to match the implementation; record any specification conflict and its resolution.

---

## 7. Definition of Done and reporting

Follow `AI_DEVELOPMENT_GUIDE.md` Section 20 (Definition of Done) and Section 18.4 (completion report). Before reporting:

```powershell
docker compose -f compose.yaml -f compose.gpu.yaml config -q
docker compose -f compose.yaml -f compose.gpu.yaml up -d --build   # cold build can take 20-40 min; see Section 2.1
docker compose -f compose.yaml -f compose.gpu.yaml ps -a
docker compose exec cleanup-worker sh -c 'celery -A app.tasks.celery_app:celery_app inspect ping -d celery@$HOSTNAME --timeout 5'
docker compose exec object-worker sh -c 'celery -A app.tasks.celery_app:celery_app inspect ping -d celery@$HOSTNAME --timeout 5'
docker compose exec scene-worker sh -c 'celery -A app.tasks.celery_app:celery_app inspect ping -d celery@$HOSTNAME --timeout 5'
docker compose run --rm --no-deps api pytest
docker compose run --rm --no-deps api ruff check .
docker compose run --rm --no-deps api ruff format --check .
docker compose run --rm --no-deps api alembic check
docker compose run --rm --no-deps api pip check
docker run --rm mogen-object-worker:dev python -m pytest /opt/object_generation/tests -q
docker run --rm mogen-scene-worker:dev python -m pytest /opt/scene_reconstruction/tests -q
docker run --rm mogen-scene-worker:dev python -m scene_reconstruction.standalone --verify-tools
docker run --rm mogen-frontend:dev npm run lint
docker run --rm mogen-frontend:dev npm run typecheck
docker run --rm mogen-frontend:dev npm run format:check
docker run --rm mogen-frontend:dev npm run test:run
docker run --rm mogen-frontend:dev npm run build
```

Then update [`HANDOFF.md`](HANDOFF.md) (state, baseline counts, decisions, open items, next phase), **update this file** for the next continuation point, add `docs/reviews/phase9_closeout.md` with task-by-task and criterion-by-criterion evidence, and report only checks that were actually executed.
