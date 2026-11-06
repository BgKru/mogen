# Session Handoff

**Purpose:** everything a new session needs to continue this project without re-deriving context. Read this first, then [`AI_DEVELOPMENT_GUIDE.md`](AI_DEVELOPMENT_GUIDE.md) and the roadmap.

Last updated: 2026-11-06.

> **Continue with:** Phase 5 object generation (TripoSR), see Section 9, "Next: Phase 5".
> **Ready-to-paste continuation prompt:** [`NEXT_SESSION.md`](NEXT_SESSION.md).
> **Confirm first:** the Section 5 baseline (healthy ten-service stack, 451 backend tests, 84 frontend tests, healthy object/scene/cleanup workers, dispatcher and recovery).
> **Detailed plan:** Section 9, "Phase 4 — background processing infrastructure (complete)" and "Next: Phase 5".
> **Copy-paste prompt and resume checklist:** Section 10 and [`NEXT_SESSION.md`](NEXT_SESSION.md).

---

## 1. State

The project is a 3D generation web application (photographs to GLB objects and reconstructed scenes). Phase 0 (specifications and architecture decisions) and Phase 1 (infrastructure foundation) are complete. Phase 2 is complete: the close-out review verified roadmap tasks 2.1–2.10 and the applicable acceptance criteria, found and fixed one `API-AC-15` contract defect (field-validation details now expose `code` instead of `type`) with a regression test, and left no Phase 2 item open. The full evidence table is in [`reviews/phase2_closeout.md`](reviews/phase2_closeout.md). Phase 3 is complete: the React frontend now implements the application shell, registration/login/logout with CSRF-aware API calls and protected routes, the project dashboard, project creation with mode-dependent image selection, previews and sequential uploads, and project details with source-image management; generation was shown only as a disabled placeholder until Phase 4 exposed the endpoint. Increment 2a added the nine SQLAlchemy models and the initial Alembic migration, 2b the repository layer and its FastAPI dependencies, 2c cookie-based authentication with Argon2id, server sessions and signed double-submit CSRF, 2d the project API with ownership authorization (creation, paginated/filtered listing with nested summaries, detail and asynchronous deletion), 2e the storage abstraction (`StorageBackend` plus `LocalStorage`), 2f image upload and listing with content validation, size and dimension limits, SHA-256, object/scene count rules and file rollback, 2g private image content delivery and guarded image deletion, and 2h the cleanup worker that executes the queued `FILE`/`DIRECTORY` cleanup jobs on a dedicated Celery `file_cleanup` queue. A six-service Docker Compose stack ran at the end of Phase 3: PostgreSQL 17.11, Redis 7.4.12, an Alembic migration job, a FastAPI backend, a Celery cleanup worker (beat poll included for development), and a React + Vite frontend that proxies `/api` to the backend. The backend has 339 passing tests and clean lint; the frontend has 84 passing tests across 14 files and passes lint, typecheck, formatting, tests and production build (Section 5). There are no git commits yet. The next step is Phase 4 (generation task creation and lifecycle, transactional outbox and dispatcher, queue separation, worker containers and task recovery), then Phase 5 (TripoSR).

Phase 4 is complete at its roadmap scope: the Celery application now declares the three documented queues (`object_generation`, `scene_reconstruction`, `file_cleanup`), `POST /api/v1/projects/{id}/generate` creates a persistent task, its ordered input snapshot, the `PENDING` project transition and a `generation.requested` outbox event in one PostgreSQL transaction, and a standalone Outbox Dispatcher publishes committed events to Redis with bounded exponential backoff, expired-lock recovery and at-least-once semantics. Dedicated `object-worker`, `scene-worker`, `outbox-dispatcher` and `task-recovery` containers run alongside the existing API, cleanup worker, database, Redis, migration and frontend; each worker consumes only its own queue. `GET /api/v1/projects/{id}/status` returns the persisted project/task state, stage, progress only when real, error fields and result availability. Atomic claim/lease/heartbeat transitions, duplicate-delivery protection, worker interruption recovery through the outbox, dispatch-stall detection and cooperative cancellation are implemented; cleanup jobs are now dispatched through `cleanup.requested` while the beat scan remains the recovery path. The Phase 4 workers deliberately contain no ML pipeline: a claimed task fails honestly with `WORKER_UNAVAILABLE` until Phase 5 registers the TripoSR pipeline (Phase 6 adds COLMAP/OpenMVS). Backend suite: **451 passed** (294 database/API, 149 unit, 8 API-shell); frontend suite: **84 passed**; all static gates clean; the ten-service stack is healthy. Phase 5 (real object generation) and Phase 7 (viewer) have not started.

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
├── docs/                     guide, 11 specifications, 4 architecture records, close-out reviews, this handoff
├── backend/                  FastAPI application (Python 3.11)
├── frontend/                 React + Vite application (Node 24)
├── ml/                       empty placeholders (object_generation, scene_reconstruction, workers)
├── infrastructure/           empty placeholders (docker, nginx, scripts)
├── tests/                    placeholder for cross-component tests
├── compose.yaml              development stack, six services
├── .env.example              environment template, 40+ variables
└── README.md
```

What is real: `backend/`, `frontend/`, `compose.yaml`, `.env.example`, all of `docs/`.
What is a placeholder: everything under `ml/`, `infrastructure/`, and `tests/` (`.gitkeep` only).

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
| `backend/app/tasks/generation_tasks.py` | `generate_object_task`/`reconstruct_scene_task`, the broker-free worker lifecycle, the heartbeat monitor and the pipeline registry |
| `backend/app/tasks/outbox_publisher.py` | Maps outbox events onto Celery task names, queues and task IDs; validates payloads before publishing |
| `backend/app/tasks/outbox_dispatcher.py` | Standalone dispatcher process loop and its heartbeat file |
| `backend/app/tasks/task_recovery.py` | Standalone recovery process loop and its heartbeat file |
| `backend/app/services/generation_service.py` | Generation task creation, input validation, fingerprinting, idempotency, project transitions and the status view |
| `backend/app/services/outbox_events.py` | Payload builders and transactional event creation for `generation.requested` and `cleanup.requested` |
| `backend/app/services/outbox_service.py` | Dispatcher claim/publish/retry/expired-lock logic |
| `backend/app/services/task_execution_service.py` | Worker-side claim, heartbeat, progress, completion, failure and cancellation |
| `backend/app/services/task_recovery_service.py` | Stale-lease requeue/fail/cancel and dispatch-stall detection |
| `backend/app/schemas/generation.py` | Generation task, start and project-status response schemas |
| `backend/app/api/v1/endpoints/generation.py` | `POST /projects/{id}/generate` (202/200) and `GET /projects/{id}/status` |
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
| `backend/tests/unit/test_generation_fingerprint.py` | Canonical fingerprint and task parameter snapshots |
| `backend/tests/unit/test_generation_validation.py` | OBJECT/SCENE input-count rules |
| `backend/tests/unit/test_outbox_publisher.py` | Event-to-queue mapping, payload validation and Celery publication |
| `backend/tests/unit/test_outbox_backoff.py` | Bounded exponential backoff with jitter |
| `backend/app/api/health.py` | Three health endpoints |
| `backend/app/api/v1/router.py` | Versioned router; authentication, projects, images and generation are registered |

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
| `frontend/src/shared/api/` | Axios client, DTOs, mappers, error normalisation, query keys |
| `frontend/src/shared/components/` | Button, Input, Alert, badges, confirm dialog, spinner, empty state, page header |
| `frontend/src/shared/lib/` | Formatting, Russian labels, UUID check, Zod-to-RHF resolver |
| `frontend/src/pages/` | Landing, Login, Register, Dashboard, Create Project, Project Details, Not Found |
| `frontend/src/test/` | Vitest setup and provider-aware render helper |
| `frontend/src/app/styles/` | `globals.css`, `theme.css` with the UI palette as Tailwind tokens |

---

## 4. Runtime

| Service | Image | Port (bound to 127.0.0.1) | Notes |
|---|---|---|---|
| `db` | `postgres:17@sha256:748a18a5…` | 5432 | health: `pg_isready` |
| `redis` | `redis:7.4-alpine@sha256:8da19c73…` | 6379 | AOF enabled, health: `redis-cli ping` |
| `migration` | `mogen-api:dev` | — | runs `alembic upgrade head`, exits 0; **`Exited (0)` is expected** |
| `api` | `mogen-api:dev` | 8000 | health: `GET /health/ready` |
| `cleanup-worker` | `mogen-api:dev` | — | Celery worker on queue `file_cleanup` with `--beat`; health: `celery inspect ping` |
| `object-worker` | `mogen-api:dev` | — | Celery worker on queue `object_generation`; health: `celery inspect ping`; no ML pipeline until Phase 5 |
| `scene-worker` | `mogen-api:dev` | — | Celery worker on queue `scene_reconstruction`; health: `celery inspect ping`; no ML pipeline until Phase 6 |
| `outbox-dispatcher` | `mogen-api:dev` | — | Standalone outbox publishing loop; health: `/tmp/outbox-dispatcher.heartbeat` freshness |
| `task-recovery` | `mogen-api:dev` | — | Standalone stale-task recovery loop; health: `/tmp/task-recovery.heartbeat` freshness |
| `frontend` | `mogen-frontend:dev` | 5173 | health: `wget --spider /` |

All application images run as unprivileged users (`appuser` uid 1000, `node` uid 1000).

Frontend routes: `/`, `/login`, `/register`, `/dashboard`, `/projects/new`, `/projects/{id}`. The dashboard, creation and details routes are protected and redirect unauthenticated users to `/login`; the backend still enforces authentication and ownership on every call. The UI language is Russian. The browser reaches the API through the same-origin `/api` proxy, so the session cookie and CSRF flow work without CORS.

Backend endpoints: `GET /health/live`, `GET /health/ready` (503 when PostgreSQL is unreachable), `GET /health/dependencies` (always 200, reports `degraded`). Swagger at `http://127.0.0.1:8000/docs`.

The cleanup worker consumes jobs from Redis DB 1 (the broker) and processes them against PostgreSQL and the shared `app_data` volume; it never opens a port. Its beat scan still runs every `CLEANUP_POLL_INTERVAL_SECONDS` (default 15) as the recovery path, but project and image deletion now insert a `cleanup.requested` outbox event in the same transaction and the Outbox Dispatcher publishes it to the `file_cleanup` queue for immediate targeted processing. Structured JSON logs include `project_id`, `cleanup_job_id` and `operation`.

The two generation workers are Phase 4 environments without ML dependencies: they claim tasks atomically, maintain a lease and heartbeat, and fail a claimed task with `WORKER_UNAVAILABLE` because no pipeline is registered. This is deliberate and must not be read as a broken worker; Phase 5 registers the TripoSR pipeline and Phase 6 the COLMAP/OpenMVS pipeline. The Outbox Dispatcher and Task Recovery run as independent processes; neither serves HTTP.

The v1 API prefix is `/api/v1`. Authentication is implemented under `/api/v1/auth/*`:

| Endpoint | Success | Notes |
|---|---|---|
| `POST /api/v1/auth/register` | 201 + `{"user": …}` | Sets the `session` (HttpOnly) and `csrf_token` cookies |
| `POST /api/v1/auth/login` | 200 + `{"user": …}` | Generic 401 for bad credentials or inactive accounts |
| `POST /api/v1/auth/logout` | 204 | Requires `X-CSRF-Token`; revokes the session and clears both cookies |
| `GET /api/v1/auth/me` | 200 + user | 401 when the session is missing, revoked or expired |
| `GET /api/v1/auth/csrf` | 200 + `{"csrf_token": …}` | Requires a session; sets the readable CSRF cookie |

Every other unimplemented `/api/v1/*` path still returns a `NOT_FOUND` error envelope; the generation start/status endpoints are implemented and the result read/download endpoints are Phase 5. CSRF tokens are HMAC values bound to one session, so a new session (registration or login) rotates the token. Cookies use `SameSite=Lax`, `Path=/`, and `Secure` in production.

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

The generation API returns 409 `GENERATION_INPUT_MISSING` when an OBJECT project does not have exactly one image or a SCENE project is outside `MIN_SCENE_IMAGES`/`MAX_SCENE_IMAGES`, and 409 `INVALID_PROJECT_STATE` while the project is `UPLOADING`. A generation request accepted with 202 is dispatched by the Outbox Dispatcher; the Phase 4 workers then claim it and, with no ML pipeline registered, record `WORKER_UNAVAILABLE` with project status `FAILED`. Manual retry uses a new idempotency key and creates a new task.

---

## 5. Verified baseline: confirm it before changing anything

```bash
docker compose up -d --build          # ~2 min; migration exits 0
docker compose ps -a                  # nine healthy; migration Exited (0)
docker compose exec cleanup-worker celery -A app.tasks.celery_app:celery_app inspect ping
docker compose exec object-worker celery -A app.tasks.celery_app:celery_app inspect ping
docker compose exec scene-worker celery -A app.tasks.celery_app:celery_app inspect ping
docker compose exec outbox-dispatcher cat /tmp/outbox-dispatcher.heartbeat   # recent epoch
docker compose exec task-recovery cat /tmp/task-recovery.heartbeat           # recent epoch
curl http://127.0.0.1:8000/health/ready
curl http://127.0.0.1:8000/health/dependencies
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:5173/
curl -s http://127.0.0.1:5173/api/v1/probe   # JSON 404 from uvicorn proves the proxy
docker compose run --rm --no-deps api pytest        # 451 passed (294 are database/API integration tests)
docker compose run --rm --no-deps api ruff check .  # clean
docker compose run --rm --no-deps api alembic check # no schema drift
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/api/v1/auth/me  # 401
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/api/v1/projects # 401
docker run --rm mogen-frontend:dev npm run lint       # clean
docker run --rm mogen-frontend:dev npm run typecheck  # clean
docker run --rm mogen-frontend:dev npm run format:check # clean
docker run --rm mogen-frontend:dev npm run test:run   # 84 passed
docker run --rm mogen-frontend:dev npm run build      # succeeds
```

If a check fails, fix the baseline before starting new work.

On Windows PowerShell, `curl` resolves to `curl.exe`: use `NUL` instead of `/dev/null`, and `${PWD}` for the working directory in `-v` mounts.

Current suite breakdown: 451 backend cases = 294 database/API integration cases under `tests/db` (they create their own scratch databases), 149 unit cases and 8 API-shell cases. Run subsets with `docker compose run --rm --no-deps api pytest tests/unit`, `... tests/db` or `... tests/api`. Phase 4 suites: generation API 24, task lifecycle 19, task recovery 13, outbox dispatcher 11, cleanup dispatch 6, generation validation 11 unit, outbox publisher 13 unit, outbox backoff 4 unit, generation fingerprint 10 unit, Celery config 10 unit. Existing suites: project API 34, image API 55, cleanup worker 17, repository 26, storage 32, image helper 25, API-shell 8.

Frontend suite: 84 cases across 14 files (Vitest + React Testing Library), covering formatting, API error mapping, image validation and object-URL cleanup, badges, cards, the dropzone, auth forms, auth initialisation, the dashboard, project creation and project details. Run it with `docker run --rm mogen-frontend:dev npm run test:run` after rebuilding the image, or mount only `frontend/src` for iteration (Section 6).

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

**The Phase 4 generation workers fail every claimed task on purpose.** No ML pipeline is registered yet, so `run_generation` records `WORKER_UNAVAILABLE` and the status API shows `FAILED`. This is the honest Phase 4 behaviour, not a defect: Phase 5 registers the TripoSR pipeline with `register_pipeline` and Phase 6 the COLMAP/OpenMVS pipeline. Do not add fake processing to make the status green.

**The development database and `/data/projects` are not empty.** The schema is migrated, and there is pre-existing development data (one user, two projects, one image, one session and two completed cleanup jobs at the time of writing) plus orphaned project directories from earlier sessions. Do not reset the database or delete files in bulk; remove only the rows and directories whose identifiers you just created and verified.

**`session_scope` is a context manager.** `app/db/session.py` exposes it as `@contextmanager`; `get_db` uses `with session_scope(...) as session: yield session` and the worker uses the same form. Do not restore the old bare generator (`yield from`): it cannot be used with `with`.

**Line endings.** The repository uses CRLF in `docs/`, root configs and `.gitattributes`-free defaults; `core.autocrlf=true`, so git warns "LF will be replaced by CRLF" on add. That warning is harmless. Backend and frontend sources are LF and `ruff format` requires no conversion.

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

**Disk.** The Docker data root is on `C:`, which has roughly 10 GB free. That is enough for the current images but not for the PyTorch or COLMAP/OpenMVS images in Phases 5–6. Relocate the Docker data root to `H:` (305 GB free) before then.

**Python on the host is 3.14.6 and is irrelevant.** The backend runs Python 3.11 inside the image. Never create a virtual environment with the host interpreter.

**`docker compose config` prunes unused named volumes.** `triposr_model_cache` is declared but does not appear in the resolved output until a service mounts it. This is correct Compose behaviour, not a mistake.

**Known warning.** FastAPI's `TestClient` emits `StarletteDeprecationWarning` suggesting `httpx2`. Harmless; revisit when dependencies are next re-pinned.

**Git state.** Branch `main`, zero commits, 82 files staged. The increment 2a–2h files (`app/db/models/`, `app/repositories/`, `app/services/`, `app/tasks/`, `app/storage/`, `app/schemas/`, the auth, project and image endpoints, `app/api/dependencies.py`, the initial migration, `tests/db/`, `tests/unit/test_repository_dependencies.py`, `tests/unit/test_security.py`, `tests/unit/test_project_validation.py`, `tests/unit/test_image_validation.py`, `tests/unit/test_storage.py`, `tests/unit/test_celery_config.py`) are untracked and not yet in the index. The Phase 2 close-out added `docs/reviews/phase2_closeout.md` (untracked) and modified the already staged `backend/app/main.py` and `backend/tests/api/test_errors.py`. Phase 3 added the frontend modules under `frontend/src/{app/layout,app/providers,app/router,features,pages,shared,test}` (untracked) and modified `frontend/package.json`, `frontend/package-lock.json`, `.env.example`, `compose.yaml` and the frontend README. Phase 4 added the new backend modules under `backend/app/{services,tasks,schemas,api/v1/endpoints}`, the new tests listed in Section 3, `docs/reviews/phase4_closeout.md` (all untracked) and modified `backend/app/core/config.py`, `backend/app/api/dependencies.py`, `backend/app/api/v1/router.py`, `backend/app/services/project_service.py`, `backend/app/services/image_service.py`, `backend/app/tasks/celery_app.py`, `backend/app/repositories/{outbox_repository,task_repository}.py`, `backend/tests/unit/test_celery_config.py`, `backend/tests/db/conftest.py`, `.env.example` and `compose.yaml`. Do not assume a clean history; `git diff` against the index shows working-tree changes only. Do not stage, commit or rewrite history unless the user asks.

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
| Phase 4 object/scene workers claim and track tasks but run no ML pipeline; a claimed task fails with `WORKER_UNAVAILABLE` instead of simulating work, and a per-pipeline heartbeat thread renews the lease while a pipeline runs | `backend/app/tasks/generation_tasks.py`, `backend/app/services/task_execution_service.py` |
| Cleanup jobs emit `cleanup.requested` in the deletion transaction and the dispatcher wakes the cleanup worker immediately; the 15 s beat scan remains the recovery path for an undispatched job | `backend/app/services/project_service.py`, `backend/app/services/image_service.py`, `backend/app/services/outbox_events.py` |
| The API never imports Celery or a Redis client: generation writes PostgreSQL only, so it accepts requests during a Redis outage and the dispatcher delivers later | `backend/app/api/v1/endpoints/generation.py`, `backend/app/services/generation_service.py`, INF-AC-23/24 |
| The status endpoint reports only persisted data; `progress_percent` stays null and `stage` is never a terminal status, and `result_available` follows the current result independently of the latest task | `backend/app/api/v1/endpoints/generation.py`, `api_contracts.md` 9.3–9.4 |
| The initial object/scene workers reuse `mogen-api:dev` because they have no ML dependencies; dedicated TripoSR/COLMAP/OpenMVS images and `compose.gpu.yaml` belong to Phases 5–6 (08 Sections 4.3–4.4) | `compose.yaml`, `08_infrastructure.md` 3.5–3.6 |
| The frontend UI is Russian, using the terminology in `02_ui_ux_specification.md` Section 11; dates and file sizes are formatted with `ru-RU` | `frontend/src/shared/lib/labels.ts`, `frontend/src/shared/lib/format.ts` |
| The CSRF token lives only in memory, is fetched after session initialisation/login/registration, and is attached by the Axios request interceptor to non-safe methods; it is never stored in `localStorage` or `sessionStorage` | `frontend/src/shared/api/client.ts`, `frontend/src/app/providers/AuthProvider.tsx` |
| API DTOs keep the backend snake_case shape; a mapping layer converts them to camelCase domain models before components see them | `frontend/src/shared/api/dto.ts`, `frontend/src/shared/api/mappers.ts` |
| Project creation and image upload are separate operations: the project is created first, images are validated locally and uploaded sequentially; partial failures preserve the project and successful images, and retry happens on the details page | `frontend/src/pages/CreateProjectPage/CreateProjectPage.tsx`, `frontend/src/pages/ProjectDetailsPage/ProjectDetailsPage.tsx` |
| Image previews use `URL.createObjectURL` and are revoked on removal, replacement, clear and unmount | `frontend/src/features/image-upload/hooks/useImageSelection.ts` |
| Generation controls are visible but disabled until the Phase 4 endpoint exists; the UI never fabricates progress or results | `frontend/src/pages/ProjectDetailsPage/ProjectDetailsPage.tsx` |
| Client-side upload limits mirror the backend limits through `VITE_*` variables; the backend remains authoritative | `frontend/src/shared/config.ts`, `.env.example`, `compose.yaml` |

---

## 8. Open items

| Item | Status | Notes |
|---|---|---|
| Phase 2 close-out | Complete | All tasks 2.1–2.10 and the applicable Phase 2 criteria verified with evidence; see [`reviews/phase2_closeout.md`](reviews/phase2_closeout.md) |
| Phase 3 frontend integration | Complete | Tasks 3.1–3.6 and the Phase 3 acceptance criteria verified; 84 frontend tests; live smoke through the frontend proxy |
| Phase 4 background processing | Complete | Tasks 4.1–4.9 and the applicable criteria verified; report in [`reviews/phase4_closeout.md`](reviews/phase4_closeout.md); 451 backend tests; live object/scene/outbox/recovery/cleanup smoke |
| Generation task creation/status, outbox insertion and dispatcher | Complete | `POST /projects/{id}/generate` (202/200), `GET /projects/{id}/status`, transactional outbox, dispatcher, workers, recovery; `BE-AC-13..16`, `API-AC-09..12`, `DB-AC-20..23` verified |
| `compose.gpu.yaml` and dedicated ML worker images | Deferred | The Phase 4 workers have no ML dependencies; add the GPU/COLMAP images with Phase 5/6 |
| Production frontend image (nginx, static build) | Deferred | Phase 4 of `08_infrastructure.md`; the Dockerfile already has a `build` stage |
| Playwright E2E | Deferred | Quality phase; a script that cannot run was deliberately not added |
| Generation UI, status polling and result viewer | Not started | The backend API exists; enabling the disabled generation action and polling is Phase 5, the viewer and downloads are Phase 7 |
| CI pipeline and coverage measurement | Not started | `TEST-AC-19`, the only unmet `TEST-AC` after the Phase 2 review; coverage targets in `09_testing.md` Section 19 |
| Rate limiting on auth endpoints | Not implemented | API contract lists 429; needs shared counters (Redis) and middleware |
| Cleanup-job processing | Implemented | The `cleanup-worker` claims `PENDING` jobs, deletes the target, records `COMPLETED`/`last_error`/`attempts` and retries until `CLEANUP_MAX_ATTEMPTS` |
| Broker-driven cleanup dispatch | Complete | Image/project deletion insert a `cleanup.requested` outbox event; the dispatcher publishes it to `file_cleanup` and the cleanup worker processes the targeted job immediately. The beat scan remains the recovery path. |
| Celery beat separation | Deferred | Development still runs `--beat` in the cleanup-worker container; production needs a dedicated beat service |
| Expired processing artifacts | Not started | `08_infrastructure.md` 3.7 lists "clean up expired processing artifacts"; no producer of such artifacts exists yet |
| Worker health beyond the process | Partially complete | Workers answer `celery inspect ping`; the dispatcher and recovery prove their loops with heartbeat files. Task-level metrics, dead-letter handling and per-task health remain deferred |
| Session cleanup scheduling | Not scheduled | `SessionRepository.delete_expired`/`delete_revoked` exist; a periodic job comes with background processing |
| Redis licensing (RSALv2/SSPLv1) | Open | Needs legal acceptance or an approved broker change; see `phase0_decisions.md` Section 8 |
| Docker data root relocation | Pending | Required before Phase 5/6 |
| First git commit | Pending | 82 files staged; every increment file listed in Section 6 is untracked |
| `ml/`, `infrastructure/`, `tests/` directories | Placeholders | Created in Phase 1, filled in later phases |

---

## 9. Phase 2, 3 and 4 progress; next task

Phases 2, 3 and 4 are complete. The increments below record what was delivered; the Phase 2 close-out review is recorded at the end of the Phase 2 section, the Phase 3 summary follows it, and the Phase 4 summary and its close-out review link follow that. Phase 5 has not been started.

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

### Next: Phase 5 — object generation (TripoSR)

**Read:** [`NEXT_SESSION.md`](NEXT_SESSION.md), Phase 5 in `10_development_roadmap.md` (tasks 5.1–5.9), `06_object_generation.md`, `04_backend_specification.md` Section 12, `08_infrastructure.md` Sections 3.5, 4.3 and 6, `09_testing.md` Sections 10 and 13.4, and the Phase 4 close-out review.

Implement the TripoSR environment, standalone inference/export proof, preprocessing, model integration, mesh extraction, GLB export, the `generate_object_task` pipeline registration, result persistence, the result read/download API and the generation UI. Use the Phase 4 `register_pipeline(TaskType.OBJECT, …)` hook and the `TaskContext` heartbeat/progress/cancellation helpers; do not replace the worker lifecycle or the outbox. Phase 5's acceptance criterion "the result can be downloaded through the API" means `GET /projects/{id}/result` and `GET /projects/{id}/download` belong to task 5.8; Phase 7 owns the viewer and result-management UI, not the API-level download. Do not start Phase 6 scene reconstruction or Phase 7 viewer work.

### Increments after that

Phase 5 (TripoSR object generation), Phase 6 (COLMAP/OpenMVS scene reconstruction), Phase 7 (viewer and results).

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

The state below was verified at the end of Phase 4. **Continuation point:** Phases 2, 3 and 4 are complete. Phase 5 (TripoSR object generation) has not been started; the Phase 4 worker lifecycle, pipeline registry, outbox dispatcher, recovery service and generation API are the starting point. The working tree is uncommitted (Section 6) — do not reset, stage or commit it.

1. **Do not re-derive the project.** Read this handoff in full, then [`NEXT_SESSION.md`](NEXT_SESSION.md), [`AI_DEVELOPMENT_GUIDE.md`](AI_DEVELOPMENT_GUIDE.md), then Phase 5 of [`10_development_roadmap.md`](specifications/10_development_roadmap.md) and the Phase 5 reading list below.
2. **Check the sandbox policy** (Section 6): Docker needs `danger-full-access`; under `workspace-write` it fails with "Access is denied". If approvals are enabled, retry the exact command with the narrowest wider mode; if they are disabled and Docker is blocked, report the baseline as **blocked**.
3. **Confirm the baseline** (Section 5): `docker compose ps -a`, the three worker pings, the dispatcher/recovery heartbeat files, the backend suite (451 passed), the frontend suite (84 passed), lint, format, `alembic check`, the API health endpoints and the frontend checks. Fix a failing baseline before any new work.
4. **Do the next increment** (Section 9, "Next: Phase 5"): TripoSR environment, standalone inference, preprocessing, model integration, mesh extraction, GLB export, pipeline registration, result persistence and generation UI. Do not bypass the Phase 4 worker lifecycle; do not start Phase 6 or Phase 7.
5. **Update the handoff and report** in the guide's format (Section 18.4) with the identifiers actually verified.

**Phase 5 reading:** [`NEXT_SESSION.md`](NEXT_SESSION.md); `06_object_generation.md`; `04_backend_specification.md` Section 12; `08_infrastructure.md` Sections 3.5, 4.3 and 6; `09_testing.md` Sections 10 and 13.4; `10_development_roadmap.md` Phase 5; [`reviews/phase4_closeout.md`](reviews/phase4_closeout.md) for the worker hooks.

If the stack is already running (it was left healthy), step 3 can start with `docker compose ps -a`; the URLs are `http://127.0.0.1:8000` (API), `http://127.0.0.1:5173` (frontend) and `http://127.0.0.1:8000/docs` (Swagger). If Docker is unavailable, report the baseline as **blocked** rather than guessing.

### 10.1. State snapshot

| Item | Value |
|---|---|
| Phase / increment | Phases 2–4 complete; **next Phase 5 object generation (TripoSR)** |
| Stack | ten Compose services; `db`, `redis`, `api`, `cleanup-worker`, `object-worker`, `scene-worker`, `outbox-dispatcher`, `task-recovery`, `frontend` healthy, `migration` Exited (0) |
| Backend suite | **451 passed, 1 warning**: 294 database/API, 149 unit, 8 API-shell |
| Frontend suite | **84 passed** across 14 files; lint, typecheck, format check and production build clean |
| Phase 2 close-out | Complete; report in [`reviews/phase2_closeout.md`](reviews/phase2_closeout.md) |
| Phase 3 integration | Complete; auth, dashboard, creation, uploads and details verified; live smoke through the frontend proxy |
| Phase 4 background processing | Complete; report in [`reviews/phase4_closeout.md`](reviews/phase4_closeout.md); outbox, dispatcher, workers, generation API, recovery and cleanup dispatch verified |
| Quality gates | `ruff check` clean, `ruff format --check` clean, `alembic check` no drift, `pip check` clean; frontend lint/typecheck/format/build clean; coverage 93% |
| Live API | `/health/*`, `/api/v1/auth/*`, `/api/v1/projects`, `/api/v1/projects/{id}/images` (POST/GET), `.../images/{image_id}/content` (GET), `.../images/{image_id}` (DELETE), `POST /api/v1/projects/{id}/generate`, `GET /api/v1/projects/{id}/status`; the result read/download endpoints are Phase 5 |
| Generation workers | Object and scene workers on `object_generation`/`scene_reconstruction`; they claim, lease and fail a task with `WORKER_UNAVAILABLE` because no ML pipeline is registered yet |
| Outbox dispatcher | Standalone process; claims committed events, publishes to the three queues, retries with backoff, releases expired locks; heartbeat file `/tmp/outbox-dispatcher.heartbeat` |
| Task recovery | Standalone process; requeues/fails stale tasks and detects dispatch stalls; heartbeat file `/tmp/task-recovery.heartbeat` |
| Cleanup worker | Celery 5.7.0 on queue `file_cleanup`, beat poll every 15 s as recovery, targeted `cleanup_storage_task(job_id)` from the dispatcher, `celery inspect ping` healthy |
| Configuration | `MAX_PAGE_SIZE=100`, `MAX_UPLOAD_SIZE_MB=20`, `MAX_IMAGE_DIMENSION=8192`, `MIN_SCENE_IMAGES=3`, `MAX_SCENE_IMAGES=100`, `CLEANUP_MAX_ATTEMPTS=3`, `CLEANUP_POLL_INTERVAL_SECONDS=15`, `CLEANUP_BATCH_SIZE=20`, `OUTBOX_BATCH_SIZE=50`, `OUTBOX_POLL_INTERVAL_SECONDS=2`, `OUTBOX_RETRY_BASE_SECONDS=2`, `OUTBOX_RETRY_MAX_SECONDS=300`, `OUTBOX_MAX_ATTEMPTS=10`, `OUTBOX_LOCK_TIMEOUT_SECONDS=60`, `TASK_LEASE_SECONDS=300`, `TASK_HEARTBEAT_SECONDS=30`, `TASK_STALE_THRESHOLD_SECONDS=900`, `DISPATCH_STALL_TIMEOUT_SECONDS=900`, `TASK_RECOVERY_MAX_ATTEMPTS=3`, `RECOVERY_BATCH_SIZE=50`, `RECOVERY_POLL_INTERVAL_SECONDS=30`, `OBJECT_TASK_TIME_LIMIT_SECONDS=3600`, `SCENE_TASK_TIME_LIMIT_SECONDS=7200`; frontend mirrors upload limits through `VITE_MAX_UPLOAD_SIZE_MB`, `VITE_MIN_SCENE_IMAGES`, `VITE_MAX_SCENE_IMAGES` |
| Storage | `/data` on the `app_data` volume, shared by the API, cleanup worker and object/scene workers; keys like `projects/{project_id}/source/{image_id}.jpg` |
| Database content | Smoke data removed. Pre-existing development data was left untouched: 1 user, 2 projects (one soft-deleted), 1 image, 2 completed cleanup jobs and 1 session. No smoke users/projects/tasks remain. |
| Cleanup jobs | Dispatched as `cleanup.requested`; executed by the worker (`PENDING` → `PROCESSING` → `COMPLETED`/`FAILED`), with `attempts` and `last_error` |
| Git | branch `main`, zero commits, 82 files staged; the Phase 2 review, Phase 3 frontend modules, Phase 4 backend modules and the Phase 4 review are untracked (Section 6) |
| Frontend | Phase 3 implementation: Russian UI, auth, dashboard, creation, uploads, details; 84 tests, lint/typecheck/format/build clean; generation controls remain disabled until Phase 5 |

### 10.2. Copy-paste prompt

> Working directory: `H:\Study\Univer\projects\mogen`. Read `docs/HANDOFF.md` first, then `docs/AI_DEVELOPMENT_GUIDE.md`, `docs/NEXT_SESSION.md` and Phase 5 of `docs/specifications/10_development_roadmap.md`. Phases 2–4 are complete; do not redo them. Confirm the baseline from Section 5 of the handoff (expect 451 backend tests, 84 frontend tests, nine healthy services plus `migration` `Exited (0)`, three healthy worker pings and fresh dispatcher/recovery heartbeat files; the stack may already be running, so verify rather than assume). Then implement Phase 5 incrementally: the TripoSR environment and pinned weights, the mandatory standalone inference/GLB proof, image preprocessing, model integration, mesh extraction, GLB export and validation, `generate_object_task` pipeline registration through the existing Phase 4 `register_pipeline` hook, result persistence, the result read/download API required by the Phase 5 acceptance criteria, and the generation UI (tasks 5.1–5.9), citing the applicable `BE-AC-nn`, `DB-AC-nn`, `API-AC-nn`, `INF-AC-nn`, `OBJ-AC-nn` and `TEST-AC-nn` criteria. Reuse the Phase 4 worker lifecycle (`TaskContext` heartbeat/progress/cancellation), outbox dispatcher, generation API and generation-task model; do not recreate them or replace the outbox with direct Redis publication. Do not start Phase 6 scene reconstruction or the Phase 7 3D viewer. Follow the Definition of Done and report format from the guide.

### 10.3. Session-start checklist

1. **Check the sandbox policy first** (Section 6). Docker needs named-pipe access: with `danger-full-access` run it directly; with `workspace-write` the CLI fails with "Access is denied" on `dockerDesktopLinuxEngine`. Never request escalation when the session says approvals are disabled.
2. **Confirm the Section 5 baseline end to end** before writing code:

   ```powershell
   docker compose ps -a                              # nine healthy, migration Exited (0)
   docker compose exec cleanup-worker celery -A app.tasks.celery_app:celery_app inspect ping
   docker compose exec object-worker celery -A app.tasks.celery_app:celery_app inspect ping
   docker compose exec scene-worker celery -A app.tasks.celery_app:celery_app inspect ping
   docker compose exec outbox-dispatcher cat /tmp/outbox-dispatcher.heartbeat
   docker compose exec task-recovery cat /tmp/task-recovery.heartbeat
   docker compose run --rm --no-deps api pytest > "$env:TEMP\pytest.log" 2>&1
   Get-Content "$env:TEMP\pytest.log" -Tail 2        # 451 passed, 1 warning
   docker compose run --rm --no-deps api ruff check .
   docker compose run --rm --no-deps api ruff format --check .
   docker compose run --rm --no-deps api alembic check
   docker compose logs --tail 5 cleanup-worker        # beat is sending cleanup-poll
   docker compose logs --tail 5 outbox-dispatcher     # published/retry cycles
   docker run --rm mogen-frontend:dev npm run lint
   docker run --rm mogen-frontend:dev npm run typecheck
   docker run --rm mogen-frontend:dev npm run format:check
   docker run --rm mogen-frontend:dev npm run test:run   # 84 passed
   docker run --rm mogen-frontend:dev npm run build
   ```

   Also check `http://127.0.0.1:8000/health/ready`, `http://127.0.0.1:5173/` and the proxy (`http://127.0.0.1:5173/api/v1/probe` must return a JSON `NOT_FOUND` 404). Immediately after `up` a service can still report `health: starting`; wait until all nine report `healthy` (start periods are 10–30 s). Fix any failure before building on it.
3. **Read the Section 9 "Next: Phase 5" plan** and the Phase 5 reading list in Section 10.0. The documentation is the source of truth, not the current code.
4. **Implement Phase 5 in this order**, citing criteria and adding tests at each step:
   1. 5.1–5.2 — TripoSR environment, pinned weights and the mandatory standalone inference/GLB proof. Do not proceed to backend integration until real inference and export are demonstrated.
   2. 5.3 — image preprocessing (decode, EXIF, background removal, crop, resize).
   3. 5.4–5.6 — model loader, inference, mesh extraction, GLB export and asset validation.
   4. 5.7 — register the pipeline with `register_pipeline(TaskType.OBJECT, …)`; use `TaskContext.heartbeat`, `report_progress`, `raise_if_cancelled`, `GenerationFailure` and `GenerationCancelled`. Do not replace the Phase 4 claim/lease/outbox lifecycle.
   5. 5.8 — result persistence (validated GLB to storage, `GenerationResult` as current, task/project `COMPLETED`), preserving previous results on failure.
   6. 5.9 — enable the generation action and status polling in the existing details page, with real stage/error display.

   Do not start Phase 6 scene reconstruction or the Phase 7 viewer. Do not simulate ML work: Phase 5 must perform real TripoSR inference and export.
5. **Re-run the baseline after any change** and confirm the documented counts match (`docker compose run --rm --no-deps api pytest`, `docker run --rm mogen-frontend:dev npm run test:run`).
6. **Update this handoff**: Section 1 state, Section 5 counts and breakdown, Section 7 decisions, Section 8 open items, Section 9 status and next increment, and Section 10 if resume steps change.
7. **Report with the guide's completion format** (Section 18.4) and cite only identifiers that were actually verified.

### 10.4. Working agreement

- Do not stage, commit or rewrite git history unless the user asks. `git diff` against the index shows working-tree changes only.
- Do not recreate the cleanup worker, Celery application, outbox table/repository, generation-task model or Phase 4 worker lifecycle; they are delivered and tested. Phase 5 registers an object pipeline through `register_pipeline` and persists results through the existing services.
- Do not treat Redis as the source of truth: task and outbox state live in PostgreSQL; Redis is only the broker.
- Do not simulate ML processing. The Phase 4 workers fail an unregistered pipeline honestly with `WORKER_UNAVAILABLE`; Phase 5 must replace that with a real TripoSR implementation, not a mock result.
- The frontend generation controls are deliberately disabled; Phase 5 enables the start action and status polling once the real pipeline and result persistence exist. Do not build a viewer in Phase 5 (that is Phase 7).
- `ml/`, `infrastructure/` and `tests/` at the repository root are placeholders created in Phase 1; do not fill them speculatively.
- Do not loosen pinned dependencies; record and justify any dependency change.
- Do not modify `docs/specifications/` or `docs/architecture/` to match the implementation; if the two disagree, follow the specification and record the resolution.
- Report checks as passed, failed, skipped, not executed or blocked. Never present an unexecuted check as passed.

### 10.5. Work remaining in Phases 2, 3 and 4

None. Phase 2 is closed out in [`reviews/phase2_closeout.md`](reviews/phase2_closeout.md), Phase 3 was completed and verified with 84 frontend tests, and Phase 4 is closed out in [`reviews/phase4_closeout.md`](reviews/phase4_closeout.md) with 451 backend tests.

### 10.6. Next phase

Phase 5 object generation: TripoSR environment, standalone inference proof, preprocessing, mesh extraction, GLB export/validation, pipeline registration through the Phase 4 `register_pipeline` hook, result persistence and the generation UI. Then Phase 6 (COLMAP/OpenMVS), Phase 7 (viewer and results).

Do not re-open Phases 2–4 by re-implementing delivered functionality; the next increment is Phase 5.
