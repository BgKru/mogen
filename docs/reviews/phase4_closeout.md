# Phase 4 Close-Out Review

**Date:** 2026-11-06
**Scope:** Phase 4 ("Background Processing Infrastructure") of `10_development_roadmap.md`, tasks 4.1–4.9 and the applicable `BE-AC-nn`, `DB-AC-nn`, `API-AC-nn`, `INF-AC-nn` and `TEST-AC-nn` criteria.
**Verdict:** Phase 4 is complete at its roadmap scope. The generation task lifecycle, transactional outbox and dispatcher, generation/status API, worker containers, failure/heartbeat recovery and cleanup-worker dispatch are implemented and verified. Real ML processing (Phase 5), the scene pipelines (Phase 6) and the 3D viewer (Phase 7) were not started.

---

## 1. Baseline and final state

The Section 5 baseline was confirmed before any change: 339 backend tests (222 database/API, 109 unit, 8 API-shell), 84 frontend tests, five healthy services plus `migration` `Exited (0)`, healthy cleanup worker, clean `ruff check`/`ruff format --check`, no Alembic drift.

Final state:

| Check | Result |
|---|---|
| `docker compose ps -a` | `db`, `redis`, `api`, `cleanup-worker`, `object-worker`, `scene-worker`, `outbox-dispatcher`, `task-recovery`, `frontend` healthy; `migration` `Exited (0)` |
| `docker compose run --rm --no-deps api pytest` | **451 passed, 1 warning** in 85.72 s |
| Suite breakdown (`--collect-only -q`) | 294 database/API integration, 149 unit, 8 API-shell |
| `ruff check .` / `ruff format --check .` | clean / 100 files already formatted |
| `alembic check` | "No new upgrade operations detected." |
| `pip check` | "No broken requirements found." |
| Frontend `lint`, `typecheck`, `format:check`, `test:run`, `build` | clean; 84 tests passed across 14 files |
| Coverage (`pytest --cov=app`) | 2736 statements, 202 missed, **93%** |

New-module coverage:

| Module | Coverage |
|---|---:|
| `app/api/v1/endpoints/generation.py` | 100% |
| `app/schemas/generation.py` | 100% |
| `app/tasks/outbox_publisher.py` | 100% |
| `app/services/generation_service.py` | 96% |
| `app/services/outbox_service.py` | 96% |
| `app/services/task_recovery_service.py` | 91% |
| `app/services/task_execution_service.py` | 89% |
| `app/tasks/generation_tasks.py` | 87% |
| `app/tasks/outbox_dispatcher.py`, `app/tasks/task_recovery.py` | 0% (thin process loops; logic lives in the covered services and was verified live) |

The four generation-state modules combined cover 396/437 statements (91%), against the 90% "generation state management" target in `09_testing.md` Section 19.2. The two process entry points are deliberately not unit-tested: their loops only wire configuration, signals and the covered service calls, and their health files were observed during the live run.

---

## 2. Roadmap tasks

| Task | Result | Evidence |
|---|---|---|
| 4.1 Celery Configuration | Satisfied | `app/tasks/celery_app.py`: Redis DB 1 broker, JSON serialization, three explicit routes, per-pipeline soft/hard limits, visibility timeout above the longest task, `acks_late`, prefetch 1, no result backend, worker logging owned by the application. `tests/unit/test_celery_config.py` (10). |
| 4.2 Queue Separation | Satisfied | `object_generation`, `scene_reconstruction`, `file_cleanup` constants and routes. Live `celery inspect active_queues` showed each of the three workers consuming exactly its own queue. `tests/unit/test_outbox_publisher.py` (13). |
| 4.3 Worker Containers | Satisfied | New Compose services `object-worker` and `scene-worker` with `celery inspect ping` readiness, shared `app_data`, database/Redis/migration dependencies. No ML processing is simulated: a claimed task with no registered pipeline fails honestly with `WORKER_UNAVAILABLE`. Live workers healthy; object and scene tasks reached the correct worker. |
| 4.4 Transactional Outbox | Satisfied | Generation and cleanup events are inserted in the same transaction as the state change. `app/services/outbox_service.py` claims with `FOR UPDATE SKIP LOCKED`, commits the claim before publishing, marks PUBLISHED separately, applies full-jitter exponential backoff, fails permanently on contract errors, exhausts the bounded budget and releases expired dispatcher locks. `tests/db/test_outbox_dispatcher.py` (11) includes a `FOR UPDATE NOWAIT` probe proving no lock is held across the network call. Live Redis outage: rows stayed PENDING, retried (attempts 1→2→3), then published after recovery. |
| 4.5 Task Lifecycle | Satisfied | `app/services/generation_service.py` creates the task, ordered `generation_task_images` snapshot, project transition and outbox event in one transaction; mandatory project-scoped `Idempotency-Key` with a SHA-256 request fingerprint; one active task enforced by the project row lock and the partial unique index. `app/services/task_execution_service.py` owns atomic claiming, heartbeat, progress, completion, failure and cancellation. Tests: `test_generation_api.py` (24), `test_task_lifecycle.py` (19), `test_generation_fingerprint.py` (10). |
| 4.6 Task Status API | Satisfied | `POST /api/v1/projects/{id}/generate` returns 202 for a new task and 200 for an idempotent repeat; `GET /api/v1/projects/{id}/status` returns project status, latest persisted task, stage/progress only when real, error fields and `result_available`. Live object and scene requests, repeats and conflicts all behaved as documented; OpenAPI lists both routes. |
| 4.7 Failure Handling | Satisfied | Automatic per-pipeline heartbeat monitor, `heartbeat_at`/`lease_expires_at`, stable error recording, project status propagation and manual retry with a new key. Previous results remain current through a new attempt and a failure. Tests: heartbeat renewal, long-pipeline automatic heartbeat, failure codes, cancellation, retry, result preservation. |
| 4.8 Cleanup Worker | Satisfied | Image and project deletion now insert a `cleanup.requested` outbox event with the job; the dispatcher publishes it to `file_cleanup` and the existing cleanup worker executes the targeted job. The beat scan remains the recovery path for an undispatched job. Live: image job COMPLETED in 2.7 s, directory job in 1.4 s, both with `attempts=1`. |
| 4.9 Task Recovery and Lease Management | Satisfied | Dispatcher hardening (claim commit before publish, expired-lock release) and the independent `task-recovery` service: stale `PROCESSING` tasks are requeued via a new outbox event with `attempt_count` incremented, failed when the budget is exhausted, or cancelled when requested/deleted; stranded `PENDING` tasks without a dispatchable event are failed after `DISPATCH_STALL_TIMEOUT_SECONDS`. Live: a simulated stale task was requeued to PENDING (`attempt_count=1`, one task, two events) and then failed by the worker. Tests: `test_task_recovery.py` (13). |

---

## 3. Acceptance criteria

### 3.1 Backend (`BE-AC-nn`)

| Criterion | Result | Evidence |
|---|---|---|
| BE-AC-13 Task Creation | Satisfied | Generation API task creation, outbox insertion, dispatcher publication and worker consumption verified by tests and live runs. |
| BE-AC-14 Queue Separation | Satisfied | Three queues and explicit routes; live `active_queues` confirms one queue per worker; object and scene tasks reached different workers. |
| BE-AC-15 Task Status | Satisfied | The status endpoint reads PostgreSQL only and returns actual persisted project/task state, timestamps and error fields; no fabricated progress. |
| BE-AC-16 Duplicate Protection | Satisfied | Mandatory idempotency key, fingerprint mismatch 409, active-task 409, partial unique index, atomic conditional claim and duplicate-delivery skip tests. |
| BE-AC-17 ML Integration | Partially satisfied at the infrastructure boundary | The correct worker is invoked through Celery, but no ML pipeline is registered in Phase 4; the worker records `WORKER_UNAVAILABLE` instead of pretending. Actual TripoSR invocation is Phase 5. |
| BE-AC-18 Failure Handling | Satisfied at the Phase 4 scope | Failed tasks are persisted with stable error codes and exposed by the status API; worker interruption, expired lease, dispatch stall and retry budget are handled. ML-specific failure codes are Phase 5/6. |
| BE-AC-19 Result Management / BE-AC-20 Model Download | Not claimed | Result registration and the API-level download are Phase 5; the viewer and result-management UI are Phase 7. |
| BE-AC-21 Storage Persistence | Satisfied (unchanged) | `app_data` remains shared by the API and all workers; the Phase 2 persistence verification still applies. |
| BE-AC-22 Logging | Satisfied | Single-line JSON logs from the API, three workers, dispatcher and recovery service include service, operation, project/task/job identifiers and error codes. |
| BE-AC-23 Testing | Satisfied | 451 passing tests; lint/format clean. |
| BE-AC-24 Docker Integration | Satisfied | Ten-service Compose stack healthy; migration `Exited (0)`. |

### 3.2 Database (`DB-AC-nn`)

| Criterion | Result | Evidence |
|---|---|---|
| DB-AC-16 Transaction Consistency | Satisfied | Task, snapshot, project transition and outbox event commit together; the rollback test fails the outbox insert and verifies no task/project/event remains. |
| DB-AC-19 Testing | Satisfied | Entity, constraint, repository, lifecycle, recovery and migration tests all pass. |
| DB-AC-20 Outbox Persistence | Satisfied | Durable row per committed request, expired-lock recovery, transient retry, permanent/exhausted FAILED, duplicate publication safety, dispatch-stall detection. |
| DB-AC-21 Project-Scoped Idempotency | Satisfied | `(project_id, idempotency_key)` uniqueness and the stored 64-hex fingerprint; same key/different request returns 409. |
| DB-AC-22 Composite Ownership | Satisfied | Generation snapshots use the composite `(task_id, project_id)` / `(image_id, project_id)` foreign keys; the existing constraint tests still pass. |
| DB-AC-23 Worker Leases | Satisfied | `worker_id`, `heartbeat_at`, `lease_expires_at` and `attempt_count` are written on claim, renewed by heartbeat and used by recovery. |

### 3.3 API (`API-AC-nn`)

| Criterion | Result | Evidence |
|---|---|---|
| API-AC-09 | Satisfied | A new generation returns HTTP 202; a repeat returns 200. |
| API-AC-10 | Satisfied | Same key + same fingerprint returns the existing task without a second task or event; a different fingerprint returns 409 `IDEMPOTENCY_KEY_REUSED`. |
| API-AC-11 | Satisfied | A second key while a task is active returns 409 `GENERATION_ALREADY_RUNNING`. |
| API-AC-12 | Satisfied | Status responses contain only persisted processing information; `progress_percent` stays null unless reported. |
| API-AC-17 | Satisfied for the new routes | OpenAPI lists `/api/v1/projects/{project_id}/generate` and `/status`, with the documented schemas. |

### 3.4 Infrastructure (`INF-AC-nn`)

| Criterion | Result | Evidence |
|---|---|---|
| INF-AC-10 Queue Separation | Satisfied | Three queues; each worker consumes only its own queue (live `active_queues`). |
| INF-AC-15 Health Checks | Satisfied | Ping checks for all three workers; heartbeat-file checks for the dispatcher and recovery loops. |
| INF-AC-16 Dependency Ordering | Satisfied | Workers depend on healthy db/redis and completed migration; recovery depends on db and migration. |
| INF-AC-17 Logging | Satisfied | Docker Compose exposes structured logs from every service. |
| INF-AC-18 Recovery | Satisfied | Workers, dispatcher and recovery restarted cleanly through the Redis outage and worker stop/start; committed work resumed. |
| INF-AC-21 Outbox Dispatcher Independence | Satisfied | Standalone `outbox-dispatcher`; recovers pending messages and its own expired locks. |
| INF-AC-22 Task Recovery Independence | Satisfied | Standalone `task-recovery`; requeues/fails stale tasks without the API or dispatcher. |
| INF-AC-23 API Without Direct Redis Access | Satisfied | The API imports no Celery or Redis client; generation only writes PostgreSQL. Generation succeeded while Redis was stopped. |
| INF-AC-24 Recoverability During Redis Outage | Satisfied | Committed generation requests stayed PENDING throughout the outage and were published after Redis returned. |
| INF-AC-25 Persistent Worker Lease State | Satisfied | Lease fields are persisted in `generation_tasks` and survive worker restarts. |
| INF-AC-08 / INF-AC-09 / INF-AC-13 | Not claimed | TripoSR/COLMAP/OpenMVS environments and GPU access are Phases 5–6. |

### 3.5 Testing (`TEST-AC-nn`)

| Criterion | Result | Evidence |
|---|---|---|
| TEST-AC-06 Task Lifecycle Tests | Satisfied | Claim, duplicate claim, heartbeat, progress, complete, fail, cancel, worker pipeline execution, cancellation and registry tests. |
| TEST-AC-07 Duplicate Protection | Satisfied | Idempotent repeat, fingerprint mismatch, active-task conflict, database fallback, concurrent claim barrier test. |
| TEST-AC-08 Outbox Reliability | Satisfied | Successful dispatch, Redis failure/retry, exhausted budget, permanent failure, duplicate dispatch, expired lock, claim-before-publish, plus live Redis outage. |
| TEST-AC-17 Failure Recovery | Satisfied | Expired lease, stale heartbeat, cancelled/deleted task, dispatch stall, retry budget and requeue tests; live recovery run. |
| TEST-AC-18 Previous Result Preservation | Satisfied at the Phase 4 scope | A current result stays current and available while a new task runs and after it fails. |
| TEST-AC-01–05, TEST-AC-09 | Satisfied | Existing suites still pass; new outbox/cleanup tests extend storage-cleanup coverage. |
| TEST-AC-19 CI/CD Integration | Not satisfied | No CI pipeline exists yet; unchanged from Phase 2. |
| TEST-AC-10/11/15/16 | Not claimed | Frontend/viewer/E2E/performance work belongs to later phases; the frontend is unchanged and its 84 tests still pass. |

---

## 4. Live verification

All commands below were executed against the rebuilt ten-service stack.

| Scenario | Result |
|---|---|
| Worker queue isolation | `celery inspect active_queues` reported exactly one queue per worker: `object_generation`, `scene_reconstruction`, `file_cleanup`. |
| Object generation | Register 201, project 201, upload 201, generate **202**, repeat **200** with the same task id, second key **409** `GENERATION_ALREADY_RUNNING`; outbox `PENDING:0` → `PUBLISHED:1`; object worker claimed the task (`started_at`/`finished_at`), recorded `WORKER_UNAVAILABLE`; retry with a new key **202** created a second task. |
| Scene generation | Three uploads, generate **202**, snapshot 3 images at positions 0,1,2; the scene worker (different node) consumed `reconstruct_scene_task`; the object worker log contained no reference to the scene task. |
| Redis outage | Redis stopped; generate **202**, project PENDING, API unaffected; the outbox retried attempts 1→2→3 (`delay=1.9`, `2.8`); after Redis restarted all events were PUBLISHED and the worker completed the lifecycle with FAILED `WORKER_UNAVAILABLE`. |
| Stale-task recovery | A PROCESSING task with a 20-minute-old heartbeat and an expired lease was requeued to PENDING, `attempt_count=1`, one task, two outbox events; the recovery log recorded `task_requeued_after_lease_expiry`; starting the worker produced FAILED with the same task id. |
| Cleanup dispatch | Image delete **204** → FILE cleanup job COMPLETED (`attempts=1`) in 2.7 s, file gone, `cleanup.requested` PUBLISHED; project delete **202** → DIRECTORY job COMPLETED in 1.4 s, project tree gone; the cleanup worker log recorded `cleanup_completed` with the job id. |
| Smoke cleanup | The smoke user's 6 projects, 7 task outbox events, 2 cleanup events/jobs, sessions and user were deleted; only the six verified `/data/projects/<id>` directories were removed; the development database returned to 0 users/projects/tasks for the smoke account. |

---

## 5. Known limitations and deferred items

- **No ML pipeline in Phase 4.** A claimed generation task fails with `WORKER_UNAVAILABLE` and the message "Generation processing is not available in this deployment." This is intentional and is not simulated ML. Phase 5 registers the TripoSR pipeline with `register_pipeline`; Phase 6 does the same for COLMAP/OpenMVS.
- **Worker images are the backend image.** The initial object/scene workers have no ML dependencies, so they reuse `mogen-api:dev`; the dedicated GPU/COLMAP images and `compose.gpu.yaml` are Phase 5/6 deliverables.
- **Process entry points are not unit-tested.** `outbox_dispatcher.py` and `task_recovery.py` are thin loops around covered services; they are verified through Compose health files and live logs.
- **`last_error` is cleared on successful publication.** Retry evidence is retained in the dispatcher log rather than the row after success.
- **Frontend generation controls remain disabled.** Enabling the generation action and status polling is Phase 5; the viewer is Phase 7.
- **CI/CD and coverage reporting** (`TEST-AC-19`) remain unimplemented.
- **Worker-level metrics and dead-letter handling** are still deferred; the healthcheck proves the process answers on its queue, and the dispatcher/recovery health files prove their loops run.
