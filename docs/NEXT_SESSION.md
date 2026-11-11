# Continue in a New Session

**Last updated:** 2026-11-11 (end of Phase 10)
**Current phase:** Phases 2–10 complete; MVP 1.0.0 released and deployment-verified.
**Next phase:** post-MVP — one item from Section 11 of the roadmap, not started.
**Read first:** [`HANDOFF.md`](HANDOFF.md), then [`AI_DEVELOPMENT_GUIDE.md`](AI_DEVELOPMENT_GUIDE.md), then [`reviews/phase10_closeout.md`](reviews/phase10_closeout.md), [`releases/v1.0.0.md`](releases/v1.0.0.md) and the relevant Section 11 item.

This file is the short continuation entry point. `HANDOFF.md` remains the full source of project state.

> **Latest change (2026-11-11):** Phase 10 packaged and released the MVP as
> `1.0.0`. Production images (`mogen-api`, `mogen-object-worker`,
> `mogen-scene-worker`, `mogen-frontend`, `mogen-backup`) build from runtime
> targets; `compose.prod.yaml` publishes only nginx 80/443, enables Secure
> cookies and the production CSRF guard, separates Celery beat and adds a
> scheduled backup service. The deployment was verified end to end: **17/17
> Playwright tests against `https://localhost`**, real TripoSR object generation,
> real 11-image COLMAP/OpenMVS reconstruction (7.7 min), viewer and GLB download,
> failure/retry, data preservation (identical counts and result SHA-256), live
> 429 rate-limit probe, and a backup restore into a scratch database with
> matching counts and storage SHA-256. Final matrix: backend **525 passed**
> (87.80% lines), frontend **148 passed** (71.47% lines), scene ML **75 passed +
> 1 skipped**, object ML **35 passed + 1 skipped**. One production-packaging
> defect was fixed: the scene runtime lacked `packaging` (Kombu's Redis
> transport); `packaging==26.3` is now pinned. Report:
> [`reviews/phase10_closeout.md`](reviews/phase10_closeout.md).

---

## 0. Resume in one minute

1. Open `H:\Study\Univer\projects\mogen` and read this file plus `HANDOFF.md` Section 1, Section 5, Section 8 and Section 10.
2. Check the sandbox policy before running Docker (`HANDOFF.md` Section 6). Docker needs named-pipe access; with `danger-full-access` it runs directly. Starting Docker Desktop/WSL can require wider access; if approvals are disabled and Docker is genuinely blocked, report the baseline as **blocked**.
3. Check the stack: `docker compose -f compose.yaml -f compose.gpu.yaml ps -a`. Expected: nine healthy services, `migration` and `model-init` `Exited (0)`.
4. If the stack is not running, start it with `docker compose -f compose.yaml -f compose.gpu.yaml up -d` (add `--build` only if images are missing or source changed). Do **not** run `docker compose down -v`: the volumes contain user data and the pinned weights.
5. Confirm both workers are ready:
   - `docker compose logs object-worker | Select-String "triposr_model_loaded|object_generation_pipeline_ready"`.
   - `docker compose logs scene-worker | Select-String "scene_pipeline_ready"`.
   The object worker takes 4–5 minutes to load the 1.7 GB checkpoint.
6. Run the baseline commands in Section 3 and compare with Section 2. Fix a real failure before new work.
7. Read Section 4 (post-MVP scope) and choose **one** Section 11 item.

**Do not:** recreate the worker lifecycle, outbox, generation/result API, reconstruction pipelines, Phase 7 viewer or production packaging; replace the outbox with direct Redis publication; delete the development database/`/data/projects`/model cache; re-open Phases 2–10; change the viewer, result/download contract, outbox or reconstruction pipelines without a recorded finding.

---

## 1. Copy-paste prompt

> Working directory: `H:\Study\Univer\projects\mogen`. Read `docs/HANDOFF.md` first, then `docs/AI_DEVELOPMENT_GUIDE.md`, `docs/NEXT_SESSION.md`, `docs/reviews/phase10_closeout.md` and `docs/releases/v1.0.0.md`. Phases 2–10 are complete and the MVP is released as 1.0.0; do not redo them. Verify the Phase 10 baseline from Section 5 of the handoff (525 backend tests, 148 frontend tests, 75 scene ML + 1 skipped, 35 object ML + 1 skipped, nine healthy development services plus `migration` and `model-init` `Exited (0)`, three worker pings, the retention and session-cleanup tasks registered, fresh dispatcher/recovery heartbeat files, the real TripoSR model loaded, COLMAP 4.2.1 and OpenMVS 2.4.0 detected, and the production `:1.0.0` images present). Then choose one post-MVP item from Section 11 of `docs/specifications/10_development_roadmap.md`, write its plan and acceptance criteria, implement only that item, and follow the Definition of Done and report format from the guide. Do not implement multiple Section 11 items at once, do not re-open the released MVP behaviour, and update `docs/HANDOFF.md`, `docs/NEXT_SESSION.md` and add a close-out review for the work.

---

## 2. Verified starting point

| Item | Value |
|---|---|
| Release | **1.0.0** (`VERSION`, `/health/live`, `docs/releases/v1.0.0.md`) |
| Backend suite | **525 passed, 1 warning** (339 database/API, 178 unit, 8 API-shell); 87.80% line coverage |
| Frontend suite | **148 passed** across 24 files; 71.47% line coverage; lint, typecheck, format check and build clean |
| Scene ML suite | **75 passed, 1 skipped**; the skip is the opt-in real reconstruction |
| Object ML suite | **35 passed, 1 skipped**; the opt-in real TripoSR test passed separately |
| E2E suite | **17/17 passed against the production HTTPS stack** (`e2e/`, Playwright + Edge locally; Chromium in CI) |
| Development stack | eleven services: `db`, `redis`, `migration` (`Exited (0)`), `model-init` (`Exited (0)`), `api`, `cleanup-worker`, `object-worker`, `scene-worker`, `outbox-dispatcher`, `task-recovery`, `frontend`; nine healthy |
| Production images | `mogen-api:1.0.0`, `mogen-object-worker:1.0.0`, `mogen-scene-worker:1.0.0`, `mogen-frontend:1.0.0`, `mogen-backup:1.0.0` built and verified; not currently running |
| Viewer | `/projects/{id}/result`; R3F 9.8.2 / Drei 10.7.9 / Three.js 0.187.0; 35 viewer tests; real object and scene loads |
| Model cache | `triposr_model_cache` volume populated; `model.ckpt` SHA-256 `429e2c6b22a0923967459de24d67f05962b235f79cde6b032aa7ed2ffcd970ee` |
| Database | Migration revision `1f302d830cf9`; 2 users / 19 projects / 17 tasks / 10 results / 141 images (pre-existing development data) |
| Local secrets/config | gitignored `.env` (development DB password), `.env.production` (production verification), `infrastructure/certs/tls.{crt,key}`, `.backups/` |
| Docs | `docs/deployment.md`, `docs/developer_guide.md`, `docs/user_guide.md`, `docs/api.md`, `docs/operations/backup_restore.md`, `docs/releases/v1.0.0.md` |

Both generation modes are real and both result types render in the viewer. Do not run a new generation solely to re-verify delivery; the repository E2E suite and the Phase 9/10 evidence are the repeatable checks.

### 2.1. State left behind by the Phase 10 session

- **The development stack is running and was left healthy.** Nine services healthy; `migration` and `model-init` `Exited (0)`; object worker with TripoSR loaded; scene worker healthy.
- **Images:** `mogen-api:dev` and `mogen-frontend:dev` were rebuilt with the Phase 10 code and the `packaging` pin; the dev object/scene images are unchanged. Production `:1.0.0` images are built. Verify by inspection/behaviour, not assumption.
- **Database password:** the existing `postgres_data` volume's `app` role password was changed to the production secret so the same volume could be deployed. A gitignored `.env` now carries `POSTGRES_PASSWORD`/`DATABASE_URL` for the development stack. Do not delete `.env`; a fresh deployment initialises its own volume from `.env.production`.
- **TLS and backups:** `infrastructure/certs/tls.crt`/`tls.key` are self-signed and local-only. `.backups/` holds scheduled/manual backup directories; copy them off-host for real retention.
- **Evidence (gitignored):** `.proof/phase10/evidence/` includes `e2e-prod.log`, `prod-ps.txt`, `prod-images.txt`, `backup-manifest.json`, `predeploy.json` and the restore-drill scripts. Phase 9 evidence remains in `.proof/phase9/`.
- **Git state:** branch `main` has three commits. Phase 9 and Phase 10 work is unstaged/untracked. Do not commit or rewrite history unless the user asks.
- **Auth limiter:** enabled by default on the development API. A production-like E2E run needs `AUTH_RATE_LIMIT_ENABLED=false`; the live 429 probe with the limiter enabled is recorded in the Phase 10 close-out.
- **No fixture credentials are retained.** Register a fresh user through `http://localhost:5173/api/v1/...` with `Origin: http://localhost:5173` (not `127.0.0.1`) and remove the rows/files you create.

---

## 3. First commands

Run from `H:\Study\Univer\projects\mogen`.

```powershell
docker compose -f compose.yaml -f compose.gpu.yaml config -q
docker compose -f compose.yaml -f compose.gpu.yaml ps -a
docker compose exec cleanup-worker sh -c 'celery -A app.tasks.celery_app:celery_app inspect ping -d celery@$HOSTNAME --timeout 5'
docker compose exec object-worker sh -c 'celery -A app.tasks.celery_app:celery_app inspect ping -d celery@$HOSTNAME --timeout 5'
docker compose exec scene-worker sh -c 'celery -A app.tasks.celery_app:celery_app inspect ping -d celery@$HOSTNAME --timeout 5'
docker compose exec cleanup-worker sh -c 'celery -A app.tasks.celery_app:celery_app inspect registered -d celery@$HOSTNAME --timeout 5'   # cleanup_storage_task, cleanup_scene_workspaces_task, cleanup_sessions_task
docker compose exec outbox-dispatcher cat /tmp/outbox-dispatcher.heartbeat
docker compose exec task-recovery cat /tmp/task-recovery.heartbeat
docker compose run --rm --no-deps api pytest > "$env:TEMP\pytest.log" 2>&1
Get-Content "$env:TEMP\pytest.log" -Tail 2          # 525 passed, 1 warning
docker compose run --rm --no-deps api ruff check .
docker compose run --rm --no-deps api ruff format --check .
docker compose run --rm --no-deps api alembic check
docker compose run --rm --no-deps api pip check
docker run --rm mogen-object-worker:dev python -m pytest /opt/object_generation/tests -o addopts="--strict-markers" -q  # 35 passed, 1 skipped
docker run --rm mogen-scene-worker:dev python -m pytest /opt/scene_reconstruction/tests -o addopts="--strict-markers" -q # 75 passed, 1 skipped
docker run --rm mogen-scene-worker:dev python -m scene_reconstruction.standalone --verify-tools
docker run --rm mogen-frontend:dev npm run lint
docker run --rm mogen-frontend:dev npm run typecheck
docker run --rm mogen-frontend:dev npm run format:check
docker run --rm mogen-frontend:dev npm run test:run   # 148 passed
docker run --rm mogen-frontend:dev npm run build
```

Also check `http://127.0.0.1:8000/health/ready`, `http://127.0.0.1:5173/` and the proxy (`http://127.0.0.1:5173/api/v1/probe` must return a JSON `NOT_FOUND` 404), the object worker logs (`triposr_model_loaded`, `object_generation_pipeline_ready`) and the scene worker log (`scene_pipeline_ready`). Immediately after `up` a service can still report `health: starting`; the object worker may take 4–5 minutes to load the model.

The production configuration can be validated without starting it:

```powershell
docker compose --env-file .env.production -f compose.yaml -f compose.prod.yaml -f compose.gpu.yaml config -q
```

Do not start the production stack on ports 80/443 while another service owns them. A production E2E run uses `E2E_BASE_URL=https://localhost` and `E2E_IGNORE_HTTPS_ERRORS=true`; see `docs/deployment.md`.

---

## 4. Post-MVP scope

Phase 10 is the last MVP phase. Choose **one** item from Section 11 (Future
Development) of `10_development_roadmap.md`, for example horizontal scaling and
object storage, worker/task monitoring and dead-letter handling, route-level
bundle splitting, shared rate limiting for multiple API replicas, or remote CI
runners. Define the item's acceptance criteria and tests before implementing.

**Guardrails**

- Do not re-open Phases 2–10 or change released behaviour without a recorded
  finding.
- Keep the production overlay, TLS/cookie configuration, backup service and
  release record consistent if the change affects deployment.
- Keep dependencies pinned; record and justify any change.
- Do not modify `docs/specifications/` or `docs/architecture/` to match the
  implementation; follow the specification and record any conflict.
- Do not delete pre-existing development rows, `/data/projects`, the retained
  failed-task workspace or `.proof/`.
- Do not stage, commit or rewrite git history unless the user asks.

---

## 5. Hooks to reuse

| Need | Where |
|---|---|
| Production compose overlay | `compose.prod.yaml` |
| Production frontend / TLS proxy | `frontend/Dockerfile` (`production` stage), `frontend/nginx/default.conf` |
| Scheduled backup | `infrastructure/backup/`, `compose.prod.yaml` (`backup`) |
| Deployment procedure | `docs/deployment.md` |
| Developer setup and testing | `docs/developer_guide.md` |
| User workflows | `docs/user_guide.md` |
| API summary | `docs/api.md` |
| Release record | `docs/releases/v1.0.0.md` |
| Viewer module and result page | `frontend/src/features/model-viewer/`, `frontend/src/pages/ModelViewerPage/` |
| Result metadata / download | `GET /api/v1/projects/{id}/result`, `GET /api/v1/projects/{id}/download` |
| Generation status | `GET /api/v1/projects/{id}/status` |
| Outbox/recovery/worker lifecycle | `backend/app/tasks/`, `backend/app/services/` |
| Cleanup, retention and session cleanup | `backend/app/services/cleanup_service.py`, `workspace_retention_service.py`, `session_cleanup_service.py` |
| Repository browser suite | `e2e/` |
| CI workflows | `.github/workflows/{ci,e2e,ml-validation}.yml` |

---

## 6. Definition of Done and reporting

Follow `AI_DEVELOPMENT_GUIDE.md` Section 20 and Section 18.4. Run the baseline
commands in Section 3 after changes, then update `HANDOFF.md` (state, counts,
decisions, open items, next increment), this file, and add a close-out review
with task-by-task and criterion-by-criterion evidence. Report only checks that
were actually executed.
