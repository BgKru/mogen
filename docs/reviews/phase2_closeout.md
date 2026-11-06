# Phase 2 Close-Out Review

**Date:** 2026-11-06
**Scope:** Phase 2 ("Database and Backend Foundation") of `10_development_roadmap.md`, tasks 2.1–2.10 and the applicable `BE-AC-nn`, `DB-AC-nn`, `API-AC-nn` and `TEST-AC-nn` criteria.
**Verdict:** Phase 2 is complete. One API contract defect was found and fixed with a regression test; no other Phase 2 defect was found. Phase 3 was not started during this review; it is recorded separately in `HANDOFF.md`.

This is a review increment. Product code changed only for the defect described in Section 8.

---

## 1. Baseline verified before the review

The stack was already running. Every command below was executed, not inferred.

| Check | Result |
|---|---|
| `docker compose ps -a` | `db`, `redis`, `api`, `cleanup-worker`, `frontend` healthy; `migration` `Exited (0)` |
| `docker compose exec cleanup-worker celery -A app.tasks.celery_app:celery_app inspect ping` | `celery@…: OK`, 1 node online |
| `GET /health/ready` | 200 `{"status":"ready","checks":{"database":"ok"}}` |
| `GET /health/dependencies` | 200 `{"status":"ok","checks":{"database":"ok","redis":"ok"}}` |
| `GET http://127.0.0.1:5173/` | 200 |
| `GET http://127.0.0.1:5173/api/v1/probe` | 404 JSON `NOT_FOUND` (Vite proxy reaches uvicorn) |
| `GET /api/v1/auth/me`, `GET /api/v1/projects` without a session | 401 |
| `docker compose run --rm --no-deps api pytest` | **338 passed, 1 warning** in 74.42 s (before the defect fix) |
| `docker compose run --rm --no-deps api ruff check .` | clean |
| `docker compose run --rm --no-deps api ruff format --check .` | 79 files already formatted |
| `docker compose run --rm --no-deps api alembic check` | "No new upgrade operations detected." |
| `docker run --rm mogen-frontend:dev npm run lint` | clean |
| `docker run --rm mogen-frontend:dev npm run test:run` | 2 passed |
| `docker run --rm mogen-frontend:dev npm run build` | succeeds |
| `docker compose run --rm --no-deps api pip check` | "No broken requirements found." |

Suite breakdown measured with `pytest --collect-only -q`:

| Suite | Cases |
|---|---:|
| `tests/db` (integration) | 222 |
| `tests/unit` | 109 |
| `tests/api` (API shell) | 7 |
| **Total** | **338** |

Coverage measured with `pytest --cov=app`: 1805 statements, 26 missed, **99%**. Business services 95–100%, repositories 100%, API handlers 100%, image validation 100% — all above the initial targets in `09_testing.md` Section 19.2.

After the defect fix the suite is **339 passed** (222 / 109 / 8) and every gate above remains clean; see Section 8.

Runtime checks added by this review:

- Wrote `/data/review-probe/probe.txt` as `appuser`, force-recreated the `api` container (same `app_data` volume), read the file back, and removed it. The content survived, and the API was ready within 2 s. This verifies `BE-AC-21`.
- `GET /openapi.json` listed `/api/v1/auth/*`, `/api/v1/projects`, `/api/v1/projects/{project_id}`, `/api/v1/projects/{project_id}/images`, `.../images/{image_id}` and `.../content`; all business paths use the `/api/v1` prefix (`API-AC-01`, `API-AC-17`).
- `docker compose logs` showed single-line JSON records for the API (`timestamp`, `level`, `service`, `logger`, `message`, `operation`) and the worker (`cleanup_cycle_finished`, `operation=cleanup`); `cleanup-poll` ran every 15 s (`BE-AC-22`).
- The development database contained 0 users, projects, images, tasks, results, cleanup jobs, outbox messages and sessions after the review; `/data` contained only empty `projects/` and `temporary/` directories.

---

## 2. Phase 2 roadmap tasks

| Task | Result | Evidence |
|---|---|---|
| 2.1 Database Models | Satisfied | `backend/app/db/models/` contains `user`, `user_session`, `project`, `project_image`, `generation_task`, `generation_task_image`, `generation_result`, `storage_cleanup_job`, `outbox_message`, plus `enums.py` and the package `__init__`. `tests/db/test_db_entities.py` (9 cases) and `tests/db/test_db_constraints.py` (54 cases) exercise entities, defaults, relationships, enums and constraints. |
| 2.2 Database Migrations | Satisfied | `backend/alembic/versions/1f302d830cf9_initial_schema.py` creates all nine tables with primary keys, foreign keys, unique/check constraints, composite ownership foreign keys, partial unique indexes and query indexes. `tests/db/test_db_migrations.py` (7 cases) verifies tables, indexes, partial predicates, composite FKs, checks, downgrade/upgrade and `alembic check`. Live `alembic check` reports no drift. |
| 2.3 Repository Layer | Satisfied | `backend/app/repositories/` has `BaseRepository` plus repositories for users, sessions, projects, images, tasks, results, cleanup jobs and outbox messages; `generation_task_images` SQL lives in `TaskRepository` (`add_input_images`, `list_input_images`, `is_image_referenced`) as required by `05` Section 19.3. `tests/db/test_repositories.py` (26) and `tests/unit/test_repository_dependencies.py` (9); repository coverage 100%. |
| 2.4 Authentication | Satisfied | `app/core/security.py` (Argon2id, SHA-256 session-token hash, signed session-bound CSRF), `app/services/auth_service.py`, `app/api/v1/endpoints/auth.py`, `app/api/dependencies.py`. `tests/db/test_auth_api.py` (20) and `tests/unit/test_security.py` (13) cover registration, login, logout, session expiry/revocation, inactive accounts, CSRF rotation and production guards. |
| 2.5 Project Management API | Satisfied | `app/schemas/project.py`, `app/services/project_service.py`, `app/api/v1/endpoints/projects.py`: create (201), list with pagination/filtering/sort, detail, asynchronous delete. `tests/db/test_projects_api.py` (34) covers the contract, clamping, filters, nested summaries, soft deletion, cancellation and cleanup scheduling. |
| 2.6 Authorization | Satisfied | Ownership is derived from the authenticated user; `ProjectRepository.get_active_for_user` and `ImageRepository.get_for_project` scope every lookup, and missing/soft-deleted/foreign resources return 404. Covered by `test_projects_api.py` (`test_get_returns_404_for_another_users_project`, `test_delete_is_scoped_to_the_owner`) and `test_images_api.py` (owner-only list/content/delete, cross-project image IDs). |
| 2.7 File Storage Abstraction | Satisfied | `app/storage/base.py` (`StorageBackend`), `keys.py` (relative keys, traversal/symlink containment), `local.py` (`LocalStorage` atomic save/open/delete/exists/get_size), `app/api/dependencies.py` (`get_storage`). `tests/unit/test_storage.py` (32) covers round-trips, atomicity, idempotent deletion, traversal, symlink escape and failure mapping. Persistence across container recreation was re-verified. |
| 2.8 Image Upload | Satisfied | `app/schemas/image.py`, `app/services/image_service.py`, `app/api/v1/endpoints/images.py`: multipart JPEG/PNG, decoded-content validation, 413/400/415 limits, SHA-256, generated storage keys, metadata persistence, OBJECT one-image and SCENE `MAX_SCENE_IMAGES` rules. `tests/db/test_images_api.py` (55) and `tests/unit/test_image_validation.py` (25). |
| 2.9 Cleanup Jobs | Satisfied (worker delivered early) | `storage_cleanup_jobs` table, repository, `app/services/cleanup_service.py`, `app/tasks/celery_app.py` and `cleanup_tasks.py`; the `cleanup-worker` service consumes the dedicated `file_cleanup` queue. `tests/db/test_cleanup_service.py` (17) covers completion, retries, `FAILED`, duplicate delivery, deferral and batching; `tests/unit/test_celery_config.py` (6). Runtime: worker ping healthy, beat poll every 15 s. |
| 2.10 Task Resilience and Ownership Metadata | Satisfied at its stated schema/ORM scope | `generation_tasks` persists `idempotency_key`, `request_fingerprint`, `worker_id`, `heartbeat_at`, `lease_expires_at`, `attempt_count` and `cancel_requested_at`, with the project-scoped idempotency index, single-active-task partial index and lease indexes. `generation_task_images` and `generation_results` use composite ownership foreign keys. `outbox_messages` exists with its repository and pending index. Covered by the constraint and migration tests. The transactional outbox insertion itself belongs to the Phase 4 generation endpoint and is not claimed here (see Section 9). |

---

## 3. Phase 2 acceptance criteria

| Criterion | Result | Evidence |
|---|---|---|
| Users can register and authenticate | Satisfied | `test_register_creates_user_and_authenticated_session`, `test_login_opens_a_new_session`, `test_me_requires_a_valid_session`; live 401 for anonymous `/auth/me`. |
| Users can create projects | Satisfied | `test_create_project_returns_the_documented_response`, `test_create_project_accepts_both_project_types`; live OpenAPI route. |
| Projects persist in PostgreSQL | Satisfied | The same tests inspect the committed row through a separate session; live database query shows the schema present. |
| Images are stored in persistent storage | Satisfied | `test_upload_persists_metadata_and_the_stored_file`; `/data` on the `app_data` volume; probe survived API container recreation. |
| Uploaded image metadata is persisted | Satisfied | Upload test asserts the row (size, SHA-256, verified MIME, dimensions, position) and the byte-identical stored file. |
| File validation works | Satisfied | `tests/unit/test_image_validation.py` (25) plus upload rejection cases for extension, declared type, format mismatch, corruption, empty content, 413 size and 400 dimensions. |
| Users cannot access other users' projects | Satisfied | Project list/get/delete and image upload/list/content/delete ownership tests all return 404 for a foreign owner. |
| All related unit and API tests pass | Satisfied | 339 passed, 1 warning after the fix; lint, format, `alembic check` and frontend checks clean. |

---

## 4. Backend acceptance criteria (`BE-AC-nn`)

| Criterion | Result | Evidence |
|---|---|---|
| BE-AC-01 Application Startup | Satisfied | `api` healthy; `test_liveness_reports_ok`. |
| BE-AC-02 Database Integration | Satisfied | `/health/ready` 200; migration applied; `test_initial_migration_creates_all_tables`; live `alembic check`. |
| BE-AC-03 Registration | Satisfied | Auth registration tests; Argon2id hash asserted (`$argon2id$`), duplicate-email and password-policy tests. |
| BE-AC-04 Authentication | Satisfied | Login tests; generic invalid credentials; inactive user rejected. |
| BE-AC-05 Session Security | Satisfied | HttpOnly/SameSite=Lax/Path=/ cookie assertions; expiry, revocation, logout and production `Secure` guard tests. |
| BE-AC-06 Authorization | Satisfied | Project and image ownership tests; 404 for foreign/soft-deleted resources. |
| BE-AC-07 Project Creation | Satisfied | 201 contract test; both OBJECT and SCENE; status `CREATED`; no generation task created. |
| BE-AC-08 Project Management | Satisfied | List/get/delete tests, pagination, filtering, sorting, soft deletion and repeat-delete 404. |
| BE-AC-09 Image Upload | Satisfied | Upload tests for JPEG and PNG; stored file byte-identical; metadata persisted; storage persistence probe. |
| BE-AC-10 File Validation | Satisfied | 25 validation unit cases and API cases for 400/413/415. |
| BE-AC-11 Object Upload Restrictions | Satisfied | `test_object_project_accepts_only_one_image`; replacement after deletion allowed. |
| BE-AC-12 Scene Upload Restrictions | Satisfied | `test_scene_project_enforces_the_maximum_image_count`; configurable limit. |
| BE-AC-13 Task Creation | Not applicable to Phase 2 | No generation endpoint exists; deferred to Phase 4. |
| BE-AC-14 Queue Separation | Not applicable to Phase 2 | Only the `file_cleanup` queue exists; object/scene queues arrive in Phase 4. |
| BE-AC-15 Task Status | Not applicable to Phase 2 | Task-status endpoints are Phase 4; project responses already expose the persisted `latest_task` summary (`test_list_includes_nested_summaries`). |
| BE-AC-16 Duplicate Protection | Partially satisfied (persistence half) | Single-active-task partial index and project-scoped idempotency index are enforced and tested; concurrent request handling is Phase 4. |
| BE-AC-17 ML Integration | Not applicable to Phase 2 | Phase 5/6. |
| BE-AC-18 Failure Handling | Not applicable to Phase 2 | Generation failure recording is Phase 4/5. |
| BE-AC-19 Result Management | Not applicable to Phase 2 | Result API and asset validation are Phase 4/7. |
| BE-AC-20 Model Download | Not applicable to Phase 2 | Phase 7. |
| BE-AC-21 Storage Persistence | Satisfied | `app_data` volume; probe survived API container recreation; upload tests read stored bytes. |
| BE-AC-22 Logging | Satisfied | Live single-line JSON API and worker logs with `service`, `operation` and identifiers; request ID is attached inside requests (`test_request_id_is_echoed_in_header_and_error`). |
| BE-AC-23 Testing | Satisfied | 339 passed; coverage 99%; targets met. |
| BE-AC-24 Docker Integration | Satisfied | `docker compose ps -a`: five healthy services, migration `Exited (0)`; worker ping healthy. |

---

## 5. Database acceptance criteria (`DB-AC-nn`)

| Criterion | Result | Evidence |
|---|---|---|
| DB-AC-01 Database Initialization | Satisfied | PostgreSQL healthy; `/health/ready` 200. |
| DB-AC-02 Initial Schema | Satisfied | Nine tables via Alembic; `test_initial_migration_creates_all_tables`. |
| DB-AC-03 User Storage | Satisfied | Unique email, Argon2id hash; `test_duplicate_email_is_rejected`, `test_register_normalizes_the_email`. |
| DB-AC-04 Session Storage | Satisfied | `user_sessions` with expiry/revocation and token hash; session constraint and API tests. |
| DB-AC-05 Project Storage | Satisfied | `test_a_user_can_own_multiple_projects_of_each_type`. |
| DB-AC-06 Image Metadata | Satisfied | `project_images` columns/checks; `test_both_supported_image_mime_types_are_accepted`, upload tests. |
| DB-AC-07 Generation History | Satisfied | Multiple tasks per project; `test_task_repository_history_and_pagination`, `test_historical_results_may_accumulate`. |
| DB-AC-08 Task Input Snapshot | Satisfied | `generation_task_images`; `test_task_repository_input_snapshot`, `test_task_image_cannot_reference_the_same_image_twice`. |
| DB-AC-09 Task Constraints | Satisfied | `uq_generation_task_active_project`; `test_only_one_active_task_per_project`, `test_terminal_tasks_do_not_block_a_new_active_task`. |
| DB-AC-10 Result Storage | Satisfied | `generation_results` model + repository; entity and constraint tests. |
| DB-AC-11 Result Versioning | Satisfied | `uq_generation_results_current_project`; `test_only_one_current_result_per_project`, `test_historical_results_may_accumulate`. |
| DB-AC-12 Result Preservation | Satisfied | `test_failed_regeneration_preserves_the_current_result`; `05` lifecycle constraints. |
| DB-AC-13 Referential Integrity | Satisfied | FK/check constraint tests; `test_check_constraints_cover_the_enumerations`; deletion-policy tests. |
| DB-AC-14 File References | Satisfied | No binary columns; `storage_key`, size, checksum and metadata only. |
| DB-AC-15 Cleanup Management | Satisfied | Durable jobs, statuses, attempts, retries; `test_failed_delete_is_retried_and_then_marked_failed`, worker runtime tests. |
| DB-AC-16 Transaction Consistency | Satisfied | Services own transactions; upload rollback, deletion transaction and cleanup claim tests; repository layer never commits. |
| DB-AC-17 Query Performance | Satisfied | Required indexes asserted in `test_required_indexes_exist` and `test_partial_unique_indexes_have_the_specified_predicates`. |
| DB-AC-18 Migration Reliability | Satisfied | `test_downgrade_removes_the_schema_and_upgrade_restores_it`; live `alembic check`. |
| DB-AC-19 Testing | Satisfied | 222 database/API integration cases pass. |
| DB-AC-20 Outbox Persistence | Partially satisfied (schema half) | `outbox_messages` table, statuses, claim columns/index and repository exist and are tested; a committed generation request does not exist until Phase 4, and dispatcher lock recovery/publication retry are Phase 4 deliverables. |
| DB-AC-21 Project-Scoped Idempotency | Satisfied | `uq_generation_task_idempotency`; `test_idempotency_key_is_unique_within_a_project`, `test_idempotency_key_is_scoped_to_its_project`; `request_fingerprint` present. |
| DB-AC-22 Composite Ownership | Satisfied | Composite FKs; `test_task_image_cannot_mix_projects`, `test_result_task_must_belong_to_the_same_project`, `test_composite_ownership_foreign_keys_are_in_the_migration`. |
| DB-AC-23 Worker Leases | Satisfied (schema) | `worker_id`, `heartbeat_at`, `lease_expires_at`, `attempt_count` and `ix_generation_tasks_status_lease_expires_at`; `test_worker_lease_metadata_round_trips`. The recovery service that requeues expired leases is Phase 4. |

---

## 6. API acceptance criteria (`API-AC-nn`)

| Criterion | Result | Evidence |
|---|---|---|
| API-AC-01 `/api/v1` prefix | Satisfied | Live OpenAPI; `test_openapi_documents_the_project_contract`. |
| API-AC-02 snake_case fields | Satisfied | Every response schema and contract test asserts snake_case keys. |
| API-AC-03 UTC ISO 8601 timestamps | Satisfied | `test_create_project_returns_the_documented_response` asserts a timezone-aware UTC offset; upload/user tests parse timestamps. Responses use `+00:00` (ISO 8601, UTC); the `Z` in the contract example is illustrative. |
| API-AC-04 Secure session cookies | Satisfied | HttpOnly, SameSite=Lax, Path=/, configurable Max-Age, `Secure` in production; asserted in `test_register_creates_user_and_authenticated_session` and the production-guard unit tests. |
| API-AC-05 CSRF validation | Satisfied | Register/login Origin guard; logout, create/delete project, upload/delete image require `X-CSRF-Token`; 403 tests. |
| API-AC-06 Project ownership | Satisfied | Ownership scoping in repositories/services; 404 (never 403) for foreign resources across project and image endpoints. |
| API-AC-07 Project creation 201 | Satisfied | `test_create_project_returns_the_documented_response`. |
| API-AC-08 multipart upload | Satisfied | `POST .../images` uses `multipart/form-data` with one `file`; upload tests. |
| API-AC-09 Generation 202 | Not applicable to Phase 2 | Phase 4. |
| API-AC-10 Idempotency | Not applicable to Phase 2 | Phase 4; only the database uniqueness and fingerprint columns exist now. |
| API-AC-11 Conflicting generation 409 | Not applicable to Phase 2 | Phase 4; the persistence-level single-active-task safeguard exists. |
| API-AC-12 Persisted task status | Not applicable to Phase 2 | Task endpoints are Phase 4; project responses return the persisted `latest_task` summary. |
| API-AC-13 Result availability independent | Satisfied | `test_result_availability_is_independent_of_project_status`; `ProjectView.result_available` follows the current result only. |
| API-AC-14 GLB download | Not applicable to Phase 2 | Phase 7. |
| API-AC-15 Common error schema | Satisfied after fix | Error envelope asserted throughout; the field-validation detail shape was corrected to `{field, code, message}` (Section 8). |
| API-AC-16 No secrets or storage paths | Satisfied | User responses omit hashes; project responses omit keys; image responses and content headers omit `storage_key`; tests assert this. |
| API-AC-17 OpenAPI consistency | Satisfied | Live `/openapi.json`; `test_openapi_documents_the_project_contract`, `test_openapi_documents_the_image_contract`. |

---

## 7. Testing acceptance criteria (`TEST-AC-nn`)

| Criterion | Result | Evidence |
|---|---|---|
| TEST-AC-01 Test infrastructure | Partially satisfied (Phase 2 scope) | Backend `tests/unit`, `tests/api`, `tests/db` and frontend Vitest are organized; ML and E2E suites belong to later phases. |
| TEST-AC-02 Unit tests | Satisfied | 109 unit cases run without PostgreSQL or ML. |
| TEST-AC-03 API tests | Satisfied | 222 integration cases include 34 project, 55 image and 20 auth API cases with success and failure paths. |
| TEST-AC-04 Authorization tests | Satisfied | Ownership cases across projects and images. |
| TEST-AC-05 Database tests | Satisfied | 54 constraint, 9 entity and 7 migration cases; real PostgreSQL. |
| TEST-AC-06 Task lifecycle tests | Not applicable to Phase 2 | Phase 4. |
| TEST-AC-07 Duplicate protection | Partially satisfied (persistence half) | Single-active-task and idempotency uniqueness tested; concurrent generation requests are Phase 4. |
| TEST-AC-08 Outbox reliability | Not applicable to Phase 2 | Phase 4. |
| TEST-AC-09 Storage tests | Satisfied | 32 storage unit cases, upload/content/delete cases, cleanup retry/deferral cases, persistence probe. |
| TEST-AC-10 Frontend tests | Not yet (Phase 3/9) | Only the two application-shell tests exist; full component coverage is Phase 3. |
| TEST-AC-11 Viewer tests | Not applicable | Phase 7. |
| TEST-AC-12 TripoSR integration | Not applicable | Phase 5. |
| TEST-AC-13 Scene reconstruction integration | Not applicable | Phase 6. |
| TEST-AC-14 GLB validation | Not applicable | Phase 5/7. |
| TEST-AC-15 End-to-end testing | Not applicable | Phase 9. |
| TEST-AC-16 Performance measurement | Not applicable | Phase 9. |
| TEST-AC-17 Failure recovery | Partially satisfied (Phase 2 scope) | Cleanup retry, exhaustion, duplicate-delivery and active-task deferral are tested; generation worker recovery is Phase 4. |
| TEST-AC-18 Previous result preservation | Satisfied at database level | `test_failed_regeneration_preserves_the_current_result`; end-to-end regeneration is Phase 4. |
| TEST-AC-19 CI/CD integration | Not satisfied — open item | No CI pipeline exists; tracked in `HANDOFF.md` Section 8, planned for the quality phase. |
| TEST-AC-20 Release validation | Not applicable | Phase 10. |

---

## 8. Defect found and fixed

**Finding.** `RequestValidationError` responses exposed detail objects as
`{"field", "message", "type"}`, for example:

```json
{"error":{"code":"VALIDATION_ERROR","message":"The request is invalid.","details":[{"field":"password","message":"Field required","type":"missing"}]}}
```

`api_contracts.md` Section 12.2 defines field-validation details as
`{"field", "code", "message"}` with a stable uppercase code, so `API-AC-15`
("All JSON errors follow the common error schema") was not fully satisfied.

**Fix.** `backend/app/main.py` now emits `code` (the Pydantic error type,
uppercased) instead of `type`.

**Regression test.** `backend/tests/api/test_errors.py::test_field_validation_errors_use_the_documented_detail_schema`
asserts the exact detail keys and `code == "MISSING"`.

**Verification.** Rebuilt the images with `docker compose up -d --build`; the live
response is now:

```json
{"error":{"code":"VALIDATION_ERROR","message":"The request is invalid.","details":[{"field":"password","code":"MISSING","message":"Field required"}],"request_id":"…"}}
```

Full baseline re-run after the fix: **339 passed, 1 warning**; `ruff check` clean;
`ruff format --check` clean (79 files); `alembic check` no drift; frontend lint,
2 tests and build clean; all five services healthy and `migration` `Exited (0)`.

---

## 9. Deferred items (not Phase 2 gaps)

These are intentionally outside Phase 2 and are already tracked in `HANDOFF.md`
Section 8:

- Generation task creation/status, idempotency conflict handling, queue separation, and the
  transactional outbox insertion and dispatcher (Phase 4). This is why `BE-AC-13..20`,
  `API-AC-09..12` and the behavioral half of `DB-AC-20` are not claimed as complete here.
- ML pipelines and result registration/download (Phases 5–7).
- Frontend integration and its test coverage (Phase 3).
- CI pipeline (`TEST-AC-19`), rate limiting, and E2E tests (quality phase).

No Phase 2 roadmap task or Phase 2 acceptance criterion remains open.
