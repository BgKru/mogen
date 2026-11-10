# Phase 8 Close-out — Reliability, Security and Optimization

**Verified:** 2026-11-09
**Scope:** roadmap Phase 8, tasks 8.1–8.8; milestone M8 (Quality Ready)
**Outcome:** Complete at its roadmap scope. No Phase 9+ work was started and no
Phase 2–7 behaviour was re-opened.

---

## 1. Baseline confirmed before work

The Phase 7 baseline from `HANDOFF.md` Section 5 was re-run on the running
eleven-service GPU stack before any change:

| Check | Result |
|---|---|
| `docker compose -f compose.yaml -f compose.gpu.yaml ps -a` | Nine services healthy; `migration` and `model-init` `Exited (0)` |
| Cleanup/object/scene worker `celery inspect ping` | 3/3 `pong` |
| Dispatcher/recovery heartbeat files | Fresh epoch values (`1794249843`, `1794249844` at query time) |
| `GET /health/ready`, `/health/dependencies` | `200`; `200` |
| Frontend and `/api` proxy | `200`; JSON `NOT_FOUND` 404 through the proxy |
| Object worker logs | `triposr_model_loaded`, `triposr_cuda_ready`, `object_generation_pipeline_ready` |
| Scene worker logs / tools | `scene_pipeline_ready`; `--verify-tools` reported COLMAP 4.2.1 and OpenMVS 2.4.0 for all six apps |
| Backend suite | **491 passed, 1 warning** (316 database/API, 167 unit, 8 API-shell) |
| Frontend suite | **130 passed** across 22 files |
| Scene ML suite | **74 passed, 1 skipped** (the opt-in real reconstruction) |
| Object ML suite | **35 passed, 1 skipped** (the opt-in real-model test) |
| `ruff check`, `ruff format --check`, `alembic check` | Clean, 109 files formatted, no drift |

**Documentation correction.** `HANDOFF.md` and `NEXT_SESSION.md` recorded the
object ML suite as "32 passed, 1 skipped". The baseline run collected and passed
**35** cases plus the skipped opt-in test; the earlier count was stale. The
handoff and the resume file are corrected.

No Phase 2–7 behaviour was re-implemented. The retained failed task
`379073b3-…` and its workspace `/data/work/scene/379073b3-…` were not touched.

---

## 2. Findings and fixes

| # | Finding | Severity | Fix | Evidence |
|---|---|---|---|---|
| F1 | `TaskExecutionService` could read a stale task from the SQLAlchemy identity map: the claim loads the row, and a cancellation request written by the API afterwards (project deletion) was invisible to `complete_with_result`/`complete`/`fail`. A deleted project could still register a result and end `COMPLETED` instead of `CANCELLED`. | **High** (data consistency, 8.3/8.8) | `TaskRepository.get_for_update` now uses `populate_existing`; new `get_refreshed` is used by `complete`/`fail`. | Regression test `test_project_deletion_during_processing_discards_the_new_asset`; the test failed before the fix (`completed` instead of `cancelled`). |
| F2 | A successful regeneration replaced the current result but never deleted the superseded GLB. The row stayed as history (correct) while its file became unreachable and permanent — unbounded growth of up to 16 MB per retry. | **High** (storage growth, 8.4/8.5; 05 §14.6, 07 §15.7) | `complete_with_result` now queues a `FILE` cleanup job plus a `cleanup.requested` outbox event, in the same transaction as the replacement, for the superseded storage key (skipped when the key is unchanged or a job is already in flight). | `test_a_successful_replacement_queues_the_superseded_file_for_cleanup` (job → worker → old file gone, current file intact); `test_a_failed_regeneration_queues_no_cleanup_job`. |
| F3 | Failed scene workspaces (`/data/work/scene/{task_id}`) were kept for diagnostics with no retention job: 6 retained workspaces / ~105 MB at baseline, unbounded over time. | **Medium** (resource management, 8.5; 07 §15.7) | New `SceneWorkspaceRetentionService` plus `cleanup_scene_workspaces_task` on the cleanup worker's beat (hourly). It only considers UUID-named direct children, never touches `PENDING`/`PROCESSING` tasks, queues expired terminal/orphan workspaces as `DIRECTORY` cleanup jobs, and logs `workspace_usage` (bytes, counts). `SCENE_WORKSPACE_RETENTION_HOURS=168` (0 disables). | 9 retention tests; live sweep reports `retained` for the six Phase 6/7 workspaces (all < 168 h old), so nothing was deleted during this phase. |
| F4 | `verify_toolchain` ran each OpenMVS `--help` probe in the process CWD, where OpenMVS writes `<tool>-<timestamp>.log`. Each scene-worker start left 7 files in `/app`; host-side runs left 60 files in `ml/scene_reconstruction/`. | **Low** (uncontrolled artifacts, 8.5) | Probes now run in a `tempfile.TemporaryDirectory`; the 60 generated host logs were removed and `.dockerignore` excludes future ones. | New preflight test with a fake tool that writes a log into CWD: no file remains. `--verify-tools` re-run clean. |
| F5 | `INF-AC-19` had no documented backup/restoration procedure for PostgreSQL and file storage. | **Medium** (infrastructure deliverable) | Added [`docs/operations/backup_restore.md`](../operations/backup_restore.md) and a runnable consistency checker [`verify_current_results.py`](../operations/verify_current_results.py). | Live dump/restore drill with identical row counts and migration revision; file tar restored with a matching GLB SHA-256; checker reports 4/4 current results with files. |
| F6 | Backend API tests that did not override `get_storage` fell back to the default `/data` root and wrote fixture uploads into the live application volume (54 orphan `projects/{uuid}` directories created during the Phase 8 test runs). | **Low** (test isolation / storage hygiene) | `API_TEST_SETTINGS` now sets `storage_root=/tmp/mogen-test-storage`, so a test client can never write into the shared `/data` volume. The 54 directories created during this session were verified not to belong to any project row and removed. | Re-ran the full suite: 509 passed and **zero** new directories under `/data/projects`. |

No security defect was found in the authentication, CSRF, cookie or file-access
paths; the verification and its evidence are in Sections 3 and 4.

---

## 3. Task-by-task evidence

### 3.1 Authentication security (8.1)

| Check | Evidence |
|---|---|
| Session expiration | `test_expired_session_is_rejected` (401 `SESSION_EXPIRED`); `authenticate` compares `expires_at` with UTC now |
| Session revocation | `test_revoked_session_is_rejected`, `test_logout_revokes_the_session_and_clears_cookies` |
| CSRF protection | Missing/mismatched/tampered header rejected (403 `CSRF_VALIDATION_FAILED`); token rotates on a new session (`test_previous_session_csrf_token_is_rejected_after_login`); new **cross-session binding** test proves Alice's token cannot revoke Bob's session |
| Cookie configuration | `session` is `HttpOnly`, `SameSite=Lax`, `Path=/`, not `Secure` in development; `csrf_token` is readable by design; production settings require `Secure` and a 32+ char `csrf_secret` at startup |
| Authorization dependencies | Ownership-scoped project, image, generation, result and download routes; another user's project is always `404 PROJECT_NOT_FOUND` (34 project, 55 image, 24 generation and 9 result API cases) |
| Origin validation | Registration/login reject a disallowed `Origin`; authenticated state changes check it as well |

### 3.2 File security (8.2)

| Check | Evidence |
|---|---|
| File validation | Extension, declared media type and decoded format must agree; corrupt/empty/oversized/over-dimension inputs rejected; verified MIME and SHA-256 stored (55 image API + 25 image-helper cases) |
| Storage key handling | Keys are server-generated relative posix paths; `..`, `.`, absolute, backslash, colon, NUL, repeated separators and >512 chars rejected; containment re-checked after symlink resolution (32 storage unit cases) |
| Path traversal | `parse_storage_key` / `resolve_storage_path` reject traversal and symlink escape; a planted symlink cannot redirect an operation outside the root |
| Filesystem access restriction | Every container runs as UID 1000; storage is a named volume not exposed by any port; the API never returns a storage key or path (result/image contract tests; `API-AC-16`) |
| Unauthorized asset access | Image content, result metadata and GLB download are all session- and ownership-checked; missing stored file returns 404 and a filesystem failure 503 without internal details |
| Live confirmation | Storage round-trip SHA-256 matched across an API container recreation; a deleted image's file is removed by the cleanup worker after the metadata 404s immediately |

### 3.3 Generation reliability (8.3)

| Scenario | Evidence |
|---|---|
| Interrupted worker | `test_a_worker_interruption_is_recovered_and_the_retry_completes`: claim by `worker-dead`, stale threshold passed, recovery requeues (`attempt_count` 1, project `PENDING`), a new worker claims and completes; the previous result survives |
| Task retries | `test_retry_after_failure_creates_a_new_task`; recovery budget fails a task after `TASK_RECOVERY_MAX_ATTEMPTS` (`test_the_recovery_budget_marks_the_task_failed`) |
| Duplicate delivery | Claim is conditional `PENDING → PROCESSING`; duplicate `run_generation` returns `skipped` and creates no second result (`test_a_duplicate_delivery_does_not_create_a_second_result`); dispatcher duplicate covered by `test_a_message_is_published_only_once` and the crash-after-publish test |
| GPU failure | `GPU_OUT_OF_MEMORY` from a pipeline is recorded verbatim, the task ends `FAILED`, the previous result and file are preserved (`test_a_failed_pipeline_preserves_the_previous_current_result`) |
| Insufficient RAM | Pipeline and tool failures carry stable codes (`INSUFFICIENT_STORAGE`, `TOOL_TIMEOUT`, ML error codes); resource faults are recorded, never retried in a loop; the scene preflight checks free space before starting |
| Storage failures | `STORAGE_WRITE_FAILED` on save failure; `RESULT_PERSISTENCE_FAILED` when the registered asset cannot be recorded; the stored file is removed and no result row remains |
| Stale task recovery | 13 task-recovery cases (stale lease + quiet heartbeat, live lease untouched, heartbeat-recent untouched, budget, cancelled, deleted project, idempotency, stalled dispatch with/without an outbox event) |
| Live drill | A generation accepted while Redis was down stayed recoverable; after Redis restarted the event was published and a cancelled task was never executed |

### 3.4 Data consistency (8.4)

| Check | Evidence |
|---|---|
| Outbox recovery | Crash after publish (before `PUBLISHED`): the message stays `PROCESSING`, the expired lock is released after the timeout, the same message is published again (`attempts` 2) and marked `PUBLISHED`; nothing is lost |
| Task/project status consistency | Recovery sets the project back to `PENDING` on requeue and to `FAILED` on budget exhaustion; terminal transitions update both rows in one transaction; deleted projects are never resurrected |
| Result replacement | New current row inserted, old row `is_current=false`, all in one transaction under the task row lock |
| Previous result preservation | Failed and cancelled attempts leave the previous current result and file untouched (2 dedicated tests in this phase plus the Phase 5/7 cases) |
| Cleanup operations | Superseded result file, image file and project directory jobs all complete through the cleanup worker; directory jobs defer while an active task exists; repeated deletion is a no-op |

### 3.5 Resource management (8.5)

| Check | Evidence |
|---|---|
| Worker concurrency | Object worker `--pool=solo` (one process, one GPU); scene worker `--concurrency=1`, prefetch 1 (live `inspect stats`: `max-concurrency: 1`); cleanup worker `--concurrency=2`, prefetch 1 (live: `max-concurrency: 2`) |
| Processing timeouts | Per-pipeline Celery hard/soft limits (object 3600 s, scene 7200 s, cleanup 600 s, 30 s soft margin); scene per-stage timeouts (COLMAP 3600, OpenMVS 5400, export 1800); object `OBJECT_MAX_TASK_SECONDS` 900; a timeout terminates the process group (`CommandRunner._terminate`) |
| Temporary storage monitoring | The retention sweep logs `workspace_usage` (scanned/retained/queued/already-queued/bytes) on every run; `check_disk_space` fails a scene task before processing when free space is below the floor |
| Intermediate file cleanup | Object work dirs are removed on success **and** failure; successful scene workspaces are removed after the asset is stored; failed scene workspaces are bounded by the retention policy |
| GPU memory recovery | `cleanup_gpu` releases references and empties the CUDA cache; two consecutive real OBJECT tasks completed in the same worker process on 2026-11-09 (18:20:06 and 18:24:02) with no OOM and no worker restart |

### 3.6 Performance baseline (8.6)

Measured against the live stack on 2026-11-09; scripts and raw JSON in
`.proof/phase8/` (gitignored).

| Measurement | Result |
|---|---|
| API, `/auth/me` | p50 215 ms, p95 225 ms (20 requests) |
| API, project list | p50 226 ms, p95 237 ms |
| API, project detail | p50 225 ms, p95 230 ms |
| API, generation status | p50 221 ms, p95 241 ms |
| API, result metadata | p50 224 ms, p95 231 ms |
| Image upload (5.42 MB JPEG) | cold 6.07 s; warm 0.69 s and 0.61 s (~8.3 MB/s warm); mean 2.21 MB/s including the cold start |
| GLB download (16 124 872 bytes) | 0.336–0.374 s, mean 0.358 s (~43 MB/s); SHA-256 matched the stored result |
| Cleanup latency (delete → `COMPLETED`) | 2.29 s |
| Viewer load, large scene | 1.899 s to `data-viewer-state="loaded"` with a non-default canvas (778×690) |
| Browser memory, large scene | JS heap 61.0 MB before → 100.3 MB after (+39.2 MB); CDP `JSHeapUsedSize` 38.4 MB; 202 493 vertices / 297 813 triangles / 1 embedded texture |
| TripoSR (persisted metadata, 7 real results) | preprocessing 0.32–0.91 s, inference 0.04–2.33 s, extraction 3.46–13.48 s, export 0.12–0.38 s; task total 4.95–15.43 s (warm model) |
| COLMAP/OpenMVS, 100-image scene (persisted metadata) | total 3719 s: extraction 9.3 s, exhaustive matching 70.7 s, sparse 122.6 s, undistortion 2.8 s, dense 1238.8 s, mesh 3.5 s, refinement 2183.2 s, texturing 63.2 s, export 12.5 s |
| COLMAP/OpenMVS, 11-image proof (Phase 6) | total 231.5 s (dense 130.6 s, refinement 60.3 s) |

Notes: API timings go through the Vite development proxy and include one
`curl.exe` process start per request, so they are an upper bound; they are well
inside the 2 s `NFR-PERF-01` target. Browser numbers are headless Edge with
SwiftShader software WebGL, so they are software-renderer floors.

### 3.7 Infrastructure reliability (8.7)

| Check | Result |
|---|---|
| API container recreation | `up -d --force-recreate api` → `ready` 200; an uploaded image fetched before and after had the same SHA-256 (`EAB1D458…`) |
| Redis outage | `stop redis`: API stayed `ready` 200 and accepted a generation (202) plus a project deletion (202); the committed event was delivered (`PUBLISHED`) after `start redis`; task `CANCELLED`; cleanup job `COMPLETED` |
| PostgreSQL outage | `stop db`: `/health/ready` returned 503; `start db`: 200; row counts `18/15/7` before and after; cleanup and scene workers answered `pong` afterwards |
| Worker restart | Every worker was recreated by the final image build and answered its queue ping; the object worker re-loaded TripoSR and re-registered the pipeline |
| Storage persistence | Proven by the API recreation check and by the file-storage restore |
| Backup and restoration | `pg_dump -Fc` 60 850 bytes restored into a scratch database with identical counts (users 2, projects 17, tasks 14, results 7, images 139, outbox 31, cleanup 14) and the same Alembic revision `1f302d830cf9`; a `tar.gz` of one project directory restored a GLB whose SHA-256 (`437896ab…`) equals the live file |

### 3.8 Regression scenarios (8.8)

| Scenario | Result |
|---|---|
| CSRF token rotation and session binding | New test: a token signed for session A is rejected for session B (403) and does not revoke B; rotation on login covered |
| Worker termination during processing | Recovery test above; live termination was not forced because a new OBJECT task would contend with the host GPU (see Limitations) |
| Project deletion during active generation | New test: the pipeline deletes the project and sets the cancellation flag mid-run; the worker discards the stored artifact, the task ends `CANCELLED`, the previous result stays current |
| Redis interruption after PostgreSQL commit | Live drill: 202 accepted, event persisted, delivered after recovery, task cancelled before execution |
| Duplicate delivery after dispatcher interruption | New test: publish-then-crash → lock expiry → second publish → one logical delivery; the worker's atomic claim makes the duplicate harmless |
| Database failure during result registration | New test: `ResultRepository.create` raises; the transaction rolls back, the stored artifact is deleted, the task ends `FAILED` with `RESULT_PERSISTENCE_FAILED`, the previous result is untouched |

---

## 4. Acceptance criteria

### 4.1 Roadmap Phase 8 acceptance criteria

| Criterion | Status | Evidence |
|---|---|---|
| Critical authorization tests pass | Satisfied | Ownership tests for projects, images, generation, result and download; cross-session CSRF test; live 404s for a foreign project |
| Worker failures do not permanently corrupt project state | Satisfied | Recovery test and 13 recovery cases; `populate_existing` fix (F1); deleted projects stay deleted and are never completed |
| Previous successful results remain accessible | Satisfied | Preservation tests for failure and cancellation; the superseded-file fix only removes files after the replacement is durable |
| Background tasks can recover from supported interruptions | Satisfied | Lease/heartbeat recovery, outbox crash-after-publish test, Redis drill, dispatch-stall detection |
| Persistent data survives container restarts | Satisfied | API recreation SHA match; DB restart counts; named volumes for PostgreSQL, Redis and `/data` |
| No critical uncontrolled storage growth remains | Satisfied | F2 (superseded GLBs) and F3 (workspace retention) close the two unbounded paths; project/image deletion already queued cleanup; `/data` baseline 307 MB with bounded growth |
| Security-sensitive operations are adequately tested | Satisfied | Authentication, CSRF, cookie, origin, upload validation, traversal, ownership and private-asset tests; no security defect found |

### 4.2 Requirement identifiers

| Identifier | Status | Evidence |
|---|---|---|
| `AC-08` Task status | Satisfied | Persisted status, stage and error fields; live drill |
| `AC-09` Task failure | Satisfied | Stable error codes, failed task/project, preserved result |
| `AC-12` Project isolation | Satisfied | Foreign project returns 404 on every resource route |
| `AC-13` Project deletion | Satisfied | Soft delete, cancellation, `DIRECTORY` cleanup job; live completion |
| `BE-AC-05` Session security | Satisfied | Expiry, revocation, cookie attributes, CSRF binding |
| `BE-AC-06` Authorization | Satisfied | Ownership enforced in services, not only the UI |
| `BE-AC-10` File validation | Satisfied | Format/size/dimension/content validation |
| `BE-AC-15` Task status | Satisfied | Status contract tests |
| `BE-AC-18` Failure handling | Satisfied | Failure recording and status exposure |
| `BE-AC-19` Result management | Satisfied | Validated storage and association; replacement |
| `BE-AC-21` Storage persistence | Satisfied | API recreation and restore drills |
| `BE-AC-22` Logging | Satisfied | Structured JSON with request/task/project/job identifiers; `workspace_usage` added |
| `BE-AC-23` Testing | Satisfied | 509 backend tests, including authorization and integration |
| `DB-AC-20` Outbox durability | Satisfied | Crash-after-publish and expired-lock tests |
| `DB-AC-21` Cleanup durability | Satisfied | Cleanup jobs, retries and history |
| `DB-AC-23` Task metadata | Satisfied | Lease/heartbeat/cancellation persist across restarts (`INF-AC-25`) |
| `INF-AC-10` Queue separation | Satisfied | Live `inspect active_queues`: one queue per worker |
| `INF-AC-11` Persistent storage | Satisfied | API recreation SHA match |
| `INF-AC-12` Shared storage | Satisfied | API and workers resolve the same `/data` keys |
| `INF-AC-15` Health checks | Satisfied | Nine healthy services; dependency and worker checks |
| `INF-AC-18` Recovery | Satisfied | Redis/PostgreSQL outage drills and worker restart |
| `INF-AC-19` Backup | Satisfied | [`backup_restore.md`](../operations/backup_restore.md) plus the executed dump/restore drill |
| `INF-AC-20` Security | Satisfied | Ports bound to `127.0.0.1`; no worker port; unprivileged users |
| `INF-AC-21` Dispatcher independence | Satisfied | Standalone process and heartbeat; crash/expired-lock handling |
| `INF-AC-22` Task recovery independence | Satisfied | Standalone process; 13 recovery tests |
| `INF-AC-23` API without direct Redis | Satisfied | API imports no Celery/Redis client; generation accepted during the outage |
| `INF-AC-24` Recoverability during Redis outage | Satisfied | Live drill: committed event delivered after recovery |
| `INF-AC-25` Persistent lease state | Satisfied | Lease/heartbeat in PostgreSQL; recovery after restart |
| `API-AC-12` Status contract | Satisfied | Persisted fields only; no simulated progress |
| `API-AC-13` Current result independent of latest task | Satisfied | Viewer and result tests |
| `API-AC-15` Error envelope | Satisfied | Single envelope; Phase 2 defect remains fixed |
| `API-AC-16` No storage paths | Satisfied | No key/path in any response or log exposed to clients |
| `TEST-AC-04` Authorization tests | Satisfied | Ownership suites |
| `TEST-AC-06` Task lifecycle tests | Satisfied | 19 lifecycle cases |
| `TEST-AC-07` Duplicate protection | Satisfied | Claim index + conditional claim + tests |
| `TEST-AC-08` Outbox reliability | Satisfied | Redis interruption and duplicate-publish tests |
| `TEST-AC-09` Storage tests | Satisfied | Upload/download/persistence/cleanup |
| `TEST-AC-16` Performance measurement | Satisfied | Baseline in Section 3.6 and `.proof/phase8/` |
| `TEST-AC-17` Failure recovery | Satisfied | Recovery, cancellation and crash scenarios |
| `TEST-AC-18` Previous result preservation | Satisfied | Failure/cancellation tests |
| `TEST-AC-19` CI/CD integration | **Not satisfied** | No CI pipeline exists; unchanged from earlier phases and deferred to Phase 9/10 |
| `M8` Quality Ready | **Partially achieved** | The Phase 8 reliability criteria pass; `TEST-AC-19` and the comprehensive Phase 9 suite remain |

---

## 5. Verification executed

| Command | Result |
|---|---|
| `docker compose -f compose.yaml -f compose.gpu.yaml up -d --build` | `mogen-api:dev`, `mogen-scene-worker:dev` and `mogen-object-worker:dev` rebuilt and verified to contain the Phase 8 code; `compose.yaml` and `.env.example` changed, so the stack was then recreated (`--no-deps --force-recreate`) from the built images |
| `docker compose ... ps -a` | Nine healthy; `migration` and `model-init` `Exited (0)` |
| `docker compose run --rm --no-deps api pytest` | **509 passed, 1 warning** in 101.17 s (332 database/API, 169 unit, 8 API-shell) |
| `... api ruff check .` | All checks passed |
| `... api ruff format --check .` | 112 files already formatted |
| `... api alembic check` | No new upgrade operations |
| `... api pip check` | No broken requirements |
| `docker run --rm mogen-object-worker:dev python -m pytest /opt/object_generation/tests -q` | 35 passed, 1 skipped |
| `docker run --rm mogen-scene-worker:dev python -m pytest /opt/scene_reconstruction/tests -q` | 75 passed, 1 skipped |
| `docker run --rm mogen-scene-worker:dev python -m scene_reconstruction.standalone --verify-tools` | COLMAP 4.2.1 + OpenMVS 2.4.0 |
| `docker run --rm mogen-frontend:dev npm run lint / typecheck / format:check` | Clean |
| `docker run --rm mogen-frontend:dev npm run test:run` | **130 passed** across 22 files |
| `docker run --rm mogen-frontend:dev npm run build` | Built; Vite chunk-size warning unchanged |
| `docker compose ... ps -a` after recreation | Nine healthy; `migration` and `model-init` `Exited (0)`; 3/3 worker pings; fresh heartbeat files; `ready`/`dependencies`/frontend 200; proxy JSON 404 |
| Live drill `.proof/phase8/drill.ps1` | Storage persistence, Redis outage, PostgreSQL outage — results in Section 3.7 |
| Backup/restore drill | PostgreSQL dump/restore and file tar/extract — results in Section 3.7 |
| Performance run `.proof/phase8/measure.ps1` | Results in Section 3.6 |
| Viewer memory run `.proof/viewer-tools/measure-phase8-memory.mjs` | Results in Section 3.6 |

---

## 6. Files

**Created**

- `backend/app/services/workspace_retention_service.py` — retention policy and
  usage report.
- `backend/tests/db/test_workspace_retention.py` (9 cases).
- `backend/tests/db/test_reliability_regressions.py` (3 cases).
- `docs/operations/backup_restore.md` — backup, restore and consistency checks.
- `docs/operations/verify_current_results.py` — runnable file/DB consistency
  checker.
- `docs/reviews/phase8_closeout.md` (this file).

**Modified**

- `backend/app/services/task_execution_service.py` — superseded-result cleanup;
  refreshed terminal reads.
- `backend/app/repositories/task_repository.py` — `populate_existing` on the
  locking read; new `get_refreshed`.
- `backend/app/services/workspace_retention_service.py` wiring in
  `backend/app/tasks/cleanup_tasks.py` and `backend/app/tasks/celery_app.py`.
- `backend/app/core/config.py` — `scene_workspace_retention_hours`,
  `scene_workspace_sweep_interval_seconds`.
- `backend/app/core/logging.py` — `workspace_usage` structured field.
- `backend/tests/db/test_result_persistence.py` (+2 cases),
  `backend/tests/db/test_outbox_dispatcher.py` (+1),
  `backend/tests/db/test_auth_api.py` (+1),
  `backend/tests/unit/test_celery_config.py` (+1),
  `backend/tests/unit/test_config.py` (+1).
- `backend/tests/db/conftest.py` — `storage_root` for API test clients so tests
  cannot write into the live `/data` volume (F6).
- `ml/scene_reconstruction/preflight.py` — probe scratch directory;
  `ml/scene_reconstruction/tests/test_preflight.py` (+1 case).
- `compose.yaml`, `.env.example` — retention settings for the cleanup worker.
- `.dockerignore` — exclude generated OpenMVS log files.
- `README.md`, `docs/HANDOFF.md`, `docs/NEXT_SESSION.md` — state, counts,
  decisions, open items and next phase.
- Removed 60 generated OpenMVS log files from `ml/scene_reconstruction/`
  (untracked artefacts, not source) and 54 orphan storage directories under
  `/data/projects` that the Phase 8 test runs had created (each verified not to
  be a project row before removal).

No viewer, result/download contract, outbox schema, migration or reconstruction
pipeline behaviour was changed. The result-registration transaction now also
queues cleanup, and terminal reads refresh the task row; both are internal.

---

## 7. Limitations and known issues

1. **No new real object generation was executed.** The host GPU was carrying an
   unrelated workload (`nvidia-smi`: ~39 % utilisation, a game process) and the
   Phase 7 handoff explicitly forbids re-running generation just to re-check
   delivery. GPU/RAM failure handling is therefore verified with simulated
   stable error codes and the recorded real runs from Phase 5/7, not by forcing
   an out-of-memory condition. GPU memory recovery is evidenced by two
   consecutive real inferences in one worker process.
2. **ML performance comes from persisted metadata and recorded proofs**, not a
   new benchmark run; the numbers are real task metadata from the seven
   completed results and the Phase 6 11-image proof.
3. **API latency includes the Vite dev proxy and process startup** (~200 ms
   floor); it is an upper bound, not a backend-only measurement.
4. **Browser figures use SwiftShader software WebGL**; frame rates and memory
   are software-renderer observations, not device-GPU expectations.
5. **Retention will eventually prune the retained diagnostic workspace.** The
   Phase 6 workspace `/data/work/scene/379073b3-…` is untouched now (about two
   days old), but with the default 168 h it becomes eligible on ~2026-11-14. Set
   `SCENE_WORKSPACE_RETENTION_HOURS=0`, or keep the directory outside
   `/data/work/scene`, if it must be preserved indefinitely.
6. **Rate limiting on auth endpoints is still absent** (`429` is documented in
   the contract). This is the same open item as before Phase 8; it needs shared
   counters and middleware and is not implemented here.
7. **Session cleanup is not scheduled.** `SessionRepository.delete_expired` /
   `delete_revoked` exist and a few expired rows were present; no periodic job
   deletes them yet. The table is tiny and bounded by usage, so this is not a
   storage risk, but it remains open.
8. **CI (`TEST-AC-19`) is still missing.** All checks are executed manually in
   this environment; a committed CI pipeline remains Phase 9/10 work.
9. **Backups are documented and drilled, not scheduled.** Section 7 of the
   operations document states the scheduling requirement.
10. **The image rebuild re-downloaded shared CUDA base layers** (several GB)
    because the local BuildKit layer cache did not contain them; subsequent
    builds are expected to reuse the layers. This is host cache behaviour, not a
    project change. The single `up -d --build` invocation was stopped after the
    three application images had been built and verified, while Compose was
    redundantly rebuilding the same object-worker Dockerfile for `model-init`;
    the services were then recreated with `--no-deps --force-recreate` from the
    built images.

---

## 8. Next

Phase 9 (comprehensive testing and quality assurance) per
`10_development_roadmap.md`: the full frontend/backend/ML/E2E/security/
performance matrix, the remaining `TEST-AC-19` CI gate, and release-readiness
assessment. Phase 8 deliberately did not start it.
