# Continue in a New Session

**Last updated:** 2026-11-06
**Current phase:** Phases 2, 3 and 4 complete.
**Next phase:** Phase 5 — object generation (TripoSR).
**Read first:** [`HANDOFF.md`](HANDOFF.md), then [`AI_DEVELOPMENT_GUIDE.md`](AI_DEVELOPMENT_GUIDE.md), then this file and Phase 5 of [`10_development_roadmap.md`](specifications/10_development_roadmap.md).

This file is the short continuation entry point. `HANDOFF.md` remains the full source of project state; this file only tells the next session what to do first, what to reuse and where the boundaries are.

---

## 1. Copy-paste prompt

> Working directory: `H:\Study\Univer\projects\mogen`. Read `docs/HANDOFF.md` first, then `docs/AI_DEVELOPMENT_GUIDE.md`, `docs/NEXT_SESSION.md` and Phase 5 of `docs/specifications/10_development_roadmap.md`. Phases 2, 3 and 4 are complete; do not redo them. Confirm the Section 5 baseline (expect 451 backend tests, 84 frontend tests, nine healthy services plus `migration` `Exited (0)`, three worker pings and fresh dispatcher/recovery heartbeat files; the stack may already be running, so verify rather than assume). Then implement Phase 5 incrementally: the TripoSR environment and pinned weights, the mandatory standalone inference/GLB proof, image preprocessing, model integration, mesh extraction, GLB export and validation, `generate_object_task` pipeline registration through the existing Phase 4 `register_pipeline` hook, result persistence, the result read/download API required by the Phase 5 acceptance criteria, and the generation UI (tasks 5.1–5.9), citing `OBJ-AC-01..18`, `BE-AC-17/19/20`, `DB-AC-07/08/10..12`, `API-AC-09..14`, `INF-AC-08/13` and `TEST-AC-12/14`. Reuse the Phase 4 worker lifecycle (`TaskContext` heartbeat/progress/cancellation), outbox dispatcher, generation API and generation-task model; do not recreate them or replace the outbox with direct Redis publication. Do not start Phase 6 scene reconstruction or the Phase 7 3D viewer. Follow the Definition of Done and report format from the guide; update `docs/HANDOFF.md` and add a Phase 5 close-out review.

---

## 2. Verified starting point

| Item | Value |
|---|---|
| Backend suite | **451 passed, 1 warning** (294 database/API, 149 unit, 8 API-shell); coverage 93% |
| Frontend suite | **84 passed** across 14 files; lint, typecheck, format check and build clean |
| Stack | ten Compose services: `db`, `redis`, `migration` (`Exited (0)`), `api`, `cleanup-worker`, `object-worker`, `scene-worker`, `outbox-dispatcher`, `task-recovery`, `frontend`; the other nine healthy |
| Generation API | `POST /api/v1/projects/{id}/generate` (202 new / 200 repeat) and `GET /api/v1/projects/{id}/status` |
| Workers | `object_generation` and `scene_reconstruction` workers claim, lease and fail a task with `WORKER_UNAVAILABLE` because no ML pipeline is registered |
| Outbox/recovery | Standalone dispatcher and recovery processes; heartbeat files under `/tmp` |
| Phase 4 review | [`reviews/phase4_closeout.md`](reviews/phase4_closeout.md) |

Do not treat the `WORKER_UNAVAILABLE` failure as a bug. It is the honest Phase 4 placeholder until Phase 5 registers a real pipeline.

---

## 3. First commands

Run from `H:\Study\Univer\projects\mogen`.

```powershell
docker compose ps -a
docker compose exec cleanup-worker sh -c 'celery -A app.tasks.celery_app:celery_app inspect ping -d celery@$HOSTNAME --timeout 5'
docker compose exec object-worker sh -c 'celery -A app.tasks.celery_app:celery_app inspect ping -d celery@$HOSTNAME --timeout 5'
docker compose exec scene-worker sh -c 'celery -A app.tasks.celery_app:celery_app inspect ping -d celery@$HOSTNAME --timeout 5'
docker compose exec outbox-dispatcher cat /tmp/outbox-dispatcher.heartbeat
docker compose exec task-recovery cat /tmp/task-recovery.heartbeat
docker compose run --rm --no-deps api pytest > "$env:TEMP\pytest.log" 2>&1
Get-Content "$env:TEMP\pytest.log" -Tail 2          # 451 passed, 1 warning
docker compose run --rm --no-deps api ruff check .
docker compose run --rm --no-deps api ruff format --check .
docker compose run --rm --no-deps api alembic check
docker run --rm mogen-frontend:dev npm run test:run  # 84 passed
```

Also check `http://127.0.0.1:8000/health/ready`, `http://127.0.0.1:5173/` and the proxy (`http://127.0.0.1:5173/api/v1/probe` must return a JSON `NOT_FOUND` 404). Fix any baseline failure before writing code. If the sandbox blocks Docker (for example `workspace-write` without named-pipe access), report the baseline as **blocked**; do not guess at results. `HANDOFF.md` Section 6 and Section 10.3 describe the policy in detail.

---

## 4. Phase 5 scope and order

Follow Phase 5 of the roadmap. The order matters because the standalone proof gates backend integration.

1. **5.1 Environment preparation.** Pin and document the TripoSR revision, Python/PyTorch/CUDA versions, weights and model cache. The current Docker data root is on `C:` with limited space; relocate it to `H:` before pulling large images/weights if necessary (see `HANDOFF.md` Section 6).
2. **5.2 Standalone inference.** Load a real photograph, run TripoSR, extract the mesh, export a GLB and open it in a viewer. This proof is mandatory before backend integration. Record the exact command and output.
3. **5.3 Image preprocessing.** Decode, EXIF correction, background removal, foreground detection, crop, resize, model input preparation.
4. **5.4–5.6 Model integration, mesh extraction, GLB export.** Model loader, persistent weight cache, CUDA device management, inference, mesh extraction and validation, GLB export and final asset validation. Never register an invalid or incomplete asset.
5. **5.7 Celery integration.** Register the pipeline with the existing hook:
   ```python
   from app.tasks.generation_tasks import register_pipeline
   from app.db.models.enums import TaskType

   register_pipeline(TaskType.OBJECT, run_triposr_pipeline)
   ```
   The pipeline receives a `TaskContext`; use `context.heartbeat()`, `context.report_progress(...)`, `context.raise_if_cancelled()`, `GenerationFailure(error_code, message)` and `GenerationCancelled`. Do not replace `run_generation`, the atomic claim, the lease/heartbeat monitor or the outbox.
6. **5.8 Result persistence and result API.** Store the validated GLB through `StorageBackend`, create the `GenerationResult` as current, clear the previous current result and set task/project `COMPLETED` in one transaction; on failure keep the previous result current. Implement the result read/download API required by the Phase 5 acceptance criteria: `GET /api/v1/projects/{project_id}/result` and `GET /api/v1/projects/{project_id}/download` (api_contracts.md Section 10), with ownership checks, a current-result check, a missing-file 404 and streamed `model/gltf-binary` content. This is the one intentional overlap with Phase 7: Phase 5 owns the persistence and the API-level download; Phase 7 owns the viewer, result-management UI and final download UX.
7. **5.9 Frontend integration.** Enable the disabled generation action on the existing details page, start generation with a new idempotency key, poll `GET /status`, display real stages/errors, show `result_available`, and offer retry after failure. Do not build the 3D viewer; that is Phase 7.

**Phase 5 acceptance criteria** (roadmap): a real photograph is processed through TripoSR; the model generates valid geometry; a valid GLB is exported; the result is stored persistently; task status updates correctly; a failed generation does not corrupt the project; the result can be downloaded through the API.

**Reading:** `06_object_generation.md`; `04_backend_specification.md` Section 12; `08_infrastructure.md` Sections 3.5, 4.3, 6 and 12; `09_testing.md` Sections 10, 12 and 13.4; `05_database_specification.md` Sections 11 and 16.5.

---

## 5. Phase 4 hooks to reuse

| Need | Where |
|---|---|
| Pipeline registration and `TaskContext` | [`backend/app/tasks/generation_tasks.py`](../backend/app/tasks/generation_tasks.py): `register_pipeline`, `resolve_pipeline`, `TaskContext`, `GenerationFailure`, `GenerationCancelled` |
| Worker claim/heartbeat/complete/fail | [`backend/app/services/task_execution_service.py`](../backend/app/services/task_execution_service.py) |
| Task creation, idempotency and status | [`backend/app/services/generation_service.py`](../backend/app/services/generation_service.py) |
| Result repository | [`backend/app/repositories/result_repository.py`](../backend/app/repositories/result_repository.py): `create`, `clear_current`, `get_current_for_project`, `get_for_task` |
| Result model and constraints | [`backend/app/db/models/generation_result.py`](../backend/app/db/models/generation_result.py) |
| Storage abstraction | [`backend/app/storage/`](../backend/app/storage) (`save`, `open`, `delete`, `exists`, `get_size`) |
| Status endpoint | [`backend/app/api/v1/endpoints/generation.py`](../backend/app/api/v1/endpoints/generation.py) |
| Outbox and dispatcher | [`backend/app/services/outbox_events.py`](../backend/app/services/outbox_events.py), [`backend/app/services/outbox_service.py`](../backend/app/services/outbox_service.py) |
| Frontend details page | [`frontend/src/pages/ProjectDetailsPage/ProjectDetailsPage.tsx`](../frontend/src/pages/ProjectDetailsPage/ProjectDetailsPage.tsx) |
| Frontend query/API patterns | [`frontend/src/features/projects/`](../frontend/src/features/projects) and [`frontend/src/shared/api/`](../frontend/src/shared/api) |

A pipeline runs after the Phase 4 worker has already claimed the task and set the project to `PROCESSING`. Call `context.report_progress(stage=..., status_message=...)` with only real stages; do not fabricate percentages. Call `context.heartbeat()` during long stages or rely on the automatic heartbeat monitor. Raise `GenerationCancelled` on a cooperative stop and `GenerationFailure` with a stable code for expected failures; let unexpected exceptions propagate so the worker records `GENERATION_FAILED` and the trace remains in the logs.

---

## 6. Guardrails

- Do not redo Phases 2–4 or recreate the cleanup worker, Celery application, outbox table/repository, generation-task model, worker lifecycle or generation API.
- Do not publish Celery messages directly from the API or worker; generation creation already inserts the outbox event and the dispatcher publishes it.
- Do not mark a task `COMPLETED` without a validated, stored result; preserve the previous current result on failure.
- Do not simulate ML. The standalone 5.2 proof is mandatory before integration; a mock is acceptable only in isolated tests, never in the running worker.
- Do not start Phase 6 scene reconstruction or the Phase 7 viewer.
- Do not expose storage keys, absolute paths, stack traces or model internals through the API.
- Keep dependencies pinned; record any new TripoSR/PyTorch dependency and its license in the completion report.
- The frontend enables only the generation action/status polling in Phase 5; do not build the viewer.
- Do not delete the pre-existing development database rows or `/data/projects` directories. Remove only the rows/files you create and verify.
- Do not stage, commit or rewrite git history unless the user asks.
- Do not modify `docs/specifications/` or `docs/architecture/` to match the implementation; record any specification conflict and its resolution.

---

## 7. Definition of Done and reporting

Follow `AI_DEVELOPMENT_GUIDE.md` Section 20 (Definition of Done) and Section 18.4 (completion report). Before reporting:

```powershell
docker compose up -d --build
docker compose ps -a
docker compose run --rm --no-deps api pytest
docker compose run --rm --no-deps api ruff check .
docker compose run --rm --no-deps api ruff format --check .
docker compose run --rm --no-deps api alembic check
docker run --rm mogen-frontend:dev npm run lint
docker run --rm mogen-frontend:dev npm run typecheck
docker run --rm mogen-frontend:dev npm run format:check
docker run --rm mogen-frontend:dev npm run test:run
docker run --rm mogen-frontend:dev npm run build
```

Then update [`HANDOFF.md`](HANDOFF.md) (state, baseline counts, decisions, open items, next phase), add `docs/reviews/phase5_closeout.md` with task-by-task and criterion-by-criterion evidence, and report only checks that were actually executed. The next phase after Phase 5 is Phase 6 (COLMAP/OpenMVS scene reconstruction), followed by Phase 7 (viewer and results).
