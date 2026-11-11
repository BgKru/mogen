# Phase 10 Close-out — MVP Release and Documentation

**Verified:** 2026-11-11
**Scope:** roadmap Phase 10, tasks 10.1–10.6; milestone `M9` (MVP Released)
**Outcome:** Complete. The MVP was packaged for production, deployed behind
nginx over HTTPS, verified end to end against the production stack, given
scheduled backups, documented for users and developers, and recorded as release
1.0.0. The viewer, result/download contract, outbox and reconstruction pipelines
were not changed.

---

## 1. Baseline confirmed before work

| Check | Result |
|---|---|
| `docker compose -f compose.yaml -f compose.gpu.yaml ps -a` | Nine healthy; `migration` and `model-init` `Exited (0)` |
| Cleanup/object/scene `celery inspect ping` | 3/3 `pong` |
| Cleanup worker registered tasks | `cleanup_storage_task`, `cleanup_scene_workspaces_task`, `cleanup_sessions_task`, `generate_object_task`, `reconstruct_scene_task` |
| Dispatcher/recovery heartbeat files | Fresh epoch values |
| Backend suite | **525 passed, 1 warning** in 163.48 s |
| Frontend suite | **148 passed** across 24 files; lint, typecheck, format and build clean |
| Scene ML | **75 passed, 1 skipped**; `--verify-tools` COLMAP 4.2.1 + OpenMVS 2.4.0 |
| Object ML | **35 passed, 1 skipped**; real TripoSR loaded by the running worker |
| `ruff check`, `ruff format --check`, `alembic check`, `pip check` | Clean (117 files), no drift, no broken requirements |
| Health and proxy | `/health/ready` 200; frontend 200; `/api/v1/probe` JSON 404 |
| Worker logs | `triposr_model_loaded`, `object_generation_pipeline_ready`, `scene_pipeline_ready` |

No baseline failure was found. The retained failed task, development data and
`/data/projects` were not touched.

---

## 2. Findings and fixes

| # | Finding | Fix | Evidence |
|---|---|---|---|
| F1 | **Production scene-worker runtime lacked `packaging`.** The first runtime image (`target: runtime`) crashed at startup: `kombu/transport/redis.py` imports `packaging.version`; the development image had it transitively through `pytest`, so every earlier suite masked the gap. | Pinned `packaging==26.3` explicitly in `backend/requirements.txt` (Kombu's Redis transport is a direct importer), rebuilt the API and scene-worker production images and the development API image. | Traceback captured from `mogen-scene-worker-1`; `python -c "import packaging"` now returns 26.3 in the scene venv; scene worker healthy and `scene_pipeline_ready` |
| F2 | **The reverse proxy initially appended `X-Forwarded-For`.** The API trusts forwarded headers for the auth rate limiter, so a client-supplied header could rotate the limiter key. | nginx overwrites `X-Forwarded-For` with `$remote_addr` for both proxied locations; `X-Real-IP` is also set. | nginx config; live limiter probe 10×401 → 429 with `Retry-After: 59` through HTTPS |
| F3 | **`/docs` was served by the SPA fallback** instead of showing that API documentation is disabled. | Explicit nginx `location = /docs` and `location = /openapi.json` return 404 in production. | `curl -k https://localhost/docs` → 404; `openapi.json` → 404; root `/healthz`, `/health/*` and `/api/` still work |
| F4 | The self-signed certificate helper first used the nginx Alpine image, which has no `openssl` binary. | The helper uses the pinned `python:3.11-slim` image (OpenSSL CLI present) and passes arguments without a shell, avoiding Windows quoting problems. | `infrastructure/scripts/generate-self-signed-cert.ps1` generated a cert with `DNS:localhost, IP:127.0.0.1`; nginx `-t` succeeds |
| F5 | The existing development `postgres_data` volume was initialised with the development password, while the production template requires a strong `POSTGRES_PASSWORD`. | The `app` role password was changed to the production secret and a gitignored `.env` was written so the development stack keeps working. This is a deployment/data-migration step, not a product defect. | `ALTER ROLE` succeeded; TCP auth check; both stacks started and all suites passed |

F1 is a genuine production-packaging defect. F2 and F3 are production hardening
found during the deployment review. No pipeline, viewer, result/download or
outbox behaviour was changed.

---

## 3. Task-by-task evidence

### 3.1 Task 10.1 — Release configuration

**Delivered**

- `compose.prod.yaml` production overlay: runtime image targets, nginx frontend,
  only 80/443 published, database/Redis/API/workers internal, `APP_ENV=production`,
  `DEBUG=false`, API docs off, Secure cookies, required production secrets,
  HTTPS redirect, bounded `json-file` logs.
- `frontend/Dockerfile` gained a pinned `nginx:1.29-alpine` `production` stage;
  `frontend/nginx/default.conf` serves the static SPA, redirects HTTP, terminates
  TLS, proxies `/api/` and `/health/`, sets security headers and handles SPA
  routes.
- Separate Celery `beat` service; the production cleanup worker no longer runs
  `--beat`.
- Scheduled `backup` service (`infrastructure/backup/`), host bind mount outside
  the Docker data root, retention and heartbeat health check.
- `.env.production.example`, TLS certificate helper and documentation.
- `VERSION=1.0.0`, `Settings.version=1.0.0`, frontend package version 1.0.0.

**Verification**

| Criterion | Evidence |
|---|---|
| `INF-AC-01` Compose validation | `docker compose --env-file .env.production -f compose.yaml -f compose.prod.yaml -f compose.gpu.yaml config -q` exit 0; the example env also validates |
| `INF-AC-02` Image build | `mogen-api:1.0.0`, `mogen-object-worker:1.0.0`, `mogen-scene-worker:1.0.0`, `mogen-frontend:1.0.0`, `mogen-backup:1.0.0` built; image IDs in Section 7 |
| `INF-AC-05` Migrations | `migration` `Exited (0)`; deployed `alembic current` = `1f302d830cf9 (head)`; `alembic check` no drift |
| `INF-AC-06` API startup | `api` healthy; `/health/ready` 200 through HTTPS |
| `INF-AC-07` Frontend startup | `frontend` healthy; static SPA served over TLS; `/api/v1/probe` reaches the API |
| `INF-AC-15` Health checks | API, frontend, backup, beat, all workers and the two loops healthy; `migration`/`model-init` exited 0 |
| `INF-AC-16` Dependency ordering | `migration` and `model-init` complete before API/workers; `backup` waits for migration |
| `INF-AC-17` Logging | JSON application logs plus Docker rotation (`LOG_MAX_SIZE` × `LOG_MAX_FILES`); beat now reports `service=beat` |
| `INF-AC-20` Security | Only `0.0.0.0:80` and `0.0.0.0:443` listen; host probes for 5432/6379/8000/5173 are closed |
| Secure cookies | Registration response: `session=…; HttpOnly; …; SameSite=lax; Secure` and `csrf_token=…; …; Secure` |
| Production secrets | Startup refuses the development CSRF secret and non-Secure cookies (existing unit tests); production env sets a 64-char secret and `SESSION_COOKIE_SECURE=true` |

### 3.2 Task 10.2 — Deployment verification

The production stack was started with the production overlay and GPU override
against the existing volumes. All services became healthy; `migration` and
`model-init` exited 0.

| MVP function (Phase 10 acceptance) | Evidence |
|---|---|
| 1. Registration and authentication | Production browser E2E auth tests (4/4); direct HTTPS registration 201 with Secure cookies, `/auth/me` 200, logout/CSRF tests |
| 2. Project creation and management | E2E project tests (2/2); direct HTTPS create 201, image list 200, delete 202, subsequent detail 404 |
| 3. Uploading photographs | E2E upload tests; direct HTTPS multipart upload 201, list 200, content 200 `image/jpeg`; downloaded bytes SHA-256 equal to the source; private headers present |
| 4. TripoSR object generation | E2E `object-generation` passed in 32.4 s; production worker logged `mesh_validated`, `glb_exported`, `generation_task_completed` |
| 5. COLMAP/OpenMVS scene reconstruction | E2E `scene-reconstruction` passed in 7.7 min; production worker logged `scene_reconstruction_completed` and `generation_task_completed` |
| 6. Asynchronous task tracking | E2E polls persisted status/stages; backend generation/status tests remain green |
| 7. Browser viewing | E2E viewer asserts `data-viewer-state="loaded"`, non-zero mesh statistics, orbit/zoom/fit/reset |
| 8. GLB download | E2E download asserts `.glb`, `glTF` magic and size equal to `GET /result` metadata |
| 9. Failed-task handling | E2E failure/retry and delete-during-processing passed; previous-result preservation covered by backend tests |
| 10. Preserved projects and assets | Pre-deployment and post-deployment counts identical (2 users, 19 projects, 17 tasks, 10 results, 141 images); current result SHA-256 unchanged (`342808cf…`) |

Production browser suite: **17/17 passed in 9.0 min** against
`https://localhost` with `E2E_IGNORE_HTTPS_ERRORS=true` (self-signed certificate).
The full log is in `.proof/phase10/evidence/e2e-prod.log` (gitignored). The suite
ran with `AUTH_RATE_LIMIT_ENABLED=false` because it registers many users from one
address in seconds; the production default was restored immediately afterwards
and verified live:

```text
codes=401,401,401,401,401,401,401,401,401,401,429
{"error":{"code":"RATE_LIMITED",...}}
HTTP/1.1 429 Too Many Requests
retry-after: 59
```

Additional production checks:

- `GET https://localhost/health/live` → `{"version":"1.0.0",...}`.
- `GET /health/dependencies` → database and Redis `ok`.
- `GET /docs` and `/openapi.json` → 404 (disabled).
- `docker compose ps` → only `frontend` publishes `80/443`.
- Host TCP probes to 5432, 6379, 8000 and 5173 all closed.

### 3.3 Task 10.3 — Backup procedures

**Delivered**

- `infrastructure/backup/{Dockerfile,backup.sh}`: one backup per run containing
  `database.dump` (pg_dump custom format), `app-data.tgz` (`/data/projects`),
  `SHA256SUMS` and `manifest.json` (application version, migration revision,
  PostgreSQL version, sizes, checksums).
- `backup` service in `compose.prod.yaml`: runs immediately after migration and
  then every `BACKUP_INTERVAL_SECONDS` (default daily), with retention and a
  heartbeat health check.
- `docs/operations/backup_restore.md` updated for the scheduled format and
  production commands.

**Verification**

| Check | Result |
|---|---|
| Scheduled service | `backup` healthy; automatic runs produced `20261111T174248Z` and `20261111T175653Z`; an on-demand run produced `20261111T181012Z` |
| Artefact validation | `pg_restore --list` and `tar -tzf` passed inside the script; manifest revision `1f302d830cf9`, app version 1.0.0 |
| Database restore | Restored the final dump into scratch database `app_restore_check`: users 2, projects 19, tasks 17, results 10, images 141 — identical to live; 9 current results belong to `COMPLETED` tasks; scratch DB dropped |
| Storage restore | Extracted `app-data.tgz` (1 515 entries) and compared the active current result: restored SHA-256 = live SHA-256 = `342808cf8084319f0e9bf4b3f5aba8c67cfc6f85bc8a2dbdd3e9067debefa408` |
| Retention | Timestamp-directory pruning and `.tmp-*` cleanup are implemented and exercised by the script path; full 14-day expiry was not waited out |

`INF-AC-19` is satisfied. The remaining operational caveat (same-host backup
directory must be copied off-host) is documented.

### 3.4 Task 10.4 — User documentation

`docs/user_guide.md` covers registration/sign-in, project creation, preparing
object and scene photographs, starting and tracking generation, the viewer
controls, GLB download, failures/retry, data retention, limits and
troubleshooting. UI labels are quoted in Russian to match the application.

### 3.5 Task 10.5 — Developer documentation

- `README.md` rewritten for 1.0.0: status, stack, repository map, development and
  production quick starts, tests and documentation index.
- `docs/developer_guide.md`: architecture, repository layout, first start,
  configuration table, Compose commands, backend/frontend conventions, ML worker
  setup and real-model commands, testing matrix, CI and common traps.
- `docs/deployment.md`: production topology diagram, prerequisites, environment,
  TLS, build/start, verification, backups, upgrades/rollback, logging, security
  and the 10.2 checklist.
- `docs/api.md`: endpoint summary, cookies/CSRF, error envelope and status codes,
  linking to the normative `api_contracts.md`.
- `.env.production.example` and `infrastructure/certs/README.md`.
- CI `.github/workflows/ci.yml` now also validates the production overlay, builds
  the production frontend and backup images, and runs `nginx -t` with a temporary
  certificate.

### 3.6 Task 10.6 — Release

`docs/releases/v1.0.0.md` records the application version, Alembic revision,
TripoSR source and weight revisions, checkpoint SHA-256, DINO revision, rembg
model, PyTorch/CUDA, `torchmcubes`, COLMAP/OpenMVS/OpenCV/CGAL/Eigen/VCGLib,
runtime versions and the Docker image identifiers. `VERSION` is `1.0.0`;
`/health/live` reports `1.0.0`.

Image identifiers built and verified in this phase:

| Image | Image ID |
|---|---|
| `mogen-api:1.0.0` | `sha256:caf5ec746b5503fe1a25756105cbacda1d284fd5f9cfac8a3232420b31a6c3dd` |
| `mogen-object-worker:1.0.0` | `sha256:805422fe390c7054bac34ceeaae5b96440fd9819e5273f4616043a1c27ae6ec6` |
| `mogen-scene-worker:1.0.0` | `sha256:fd645d6197b22b9b20deee8f1b48f4f5acb76ad4dde6c65a7865809cabc9a1f3` |
| `mogen-frontend:1.0.0` | `sha256:b8b28244e2aefd9dd0ff9d9e248f9f0e0842231abcf65b4622e69e30f5591d76` |
| `mogen-backup:1.0.0` | `sha256:b8698e38a0511a8ea6adab0a5d7b63f566e5943ade8b038080ae24cef39b7be4` |

---

## 4. Final quality gate (after all changes)

The repository was returned to the development stack after production
verification; the final gate uses the rebuilt development images and the same
code that the production runtime images execute.

| Command | Result |
|---|---|
| `docker compose run --rm --no-deps api pytest` | **525 passed, 1 warning** in 165.14 s |
| `docker compose run --rm --no-deps api ruff check .` | All checks passed |
| `docker compose run --rm --no-deps api ruff format --check .` | 117 files already formatted |
| `docker compose run --rm --no-deps api alembic check` | No new upgrade operations |
| `docker compose run --rm --no-deps api pip check` | No broken requirements |
| `docker run --rm mogen-object-worker:dev python -m pytest /opt/object_generation/tests -o addopts=… -q` | **35 passed, 1 skipped** |
| `docker run --rm mogen-scene-worker:dev python -m pytest /opt/scene_reconstruction/tests -o addopts=… -q` | **75 passed, 1 skipped** |
| `python -m scene_reconstruction.standalone --verify-tools` | COLMAP 4.2.1 + OpenMVS 2.4.0 |
| Frontend lint / typecheck / format / test / build | Clean; **148 passed**; build succeeds with the known chunk warning |
| Production browser suite | **17/17 passed** (9.0 min) |
| Development stack | Nine healthy; `migration`/`model-init` `Exited (0)`; 3 worker pings; retention and session tasks registered; fresh heartbeats |

The production API image is a runtime image: `/app` contains only `alembic`,
`alembic.ini`, `app` and `requirements.txt` (no tests or dev tooling).

---

## 5. Security verification

| Area | Result |
|---|---|
| Network exposure | Only nginx 80/443; host probes to 5432/6379/8000/5173 closed |
| TLS | TLS 1.2/1.3, HTTP→HTTPS redirect, HSTS for non-localhost hosts |
| Cookies | `session` HttpOnly + Secure + SameSite=Lax; CSRF cookie Secure and session-bound |
| CSRF origin | Production `PUBLIC_ORIGIN=https://localhost`; browser E2E CSRF tests pass |
| Rate limiting | Live 10×401 → 429 with `Retry-After: 59` through the proxy; spoofed `X-Forwarded-For` cannot rotate the key (F2) |
| API docs | Disabled and explicitly 404 through the proxy |
| Private assets | Image content is ownership-scoped and byte-identical; download is authenticated |
| Isolation | E2E two-user isolation and hostile-filename tests pass |
| Containers | API/cleanup/outbox/recovery/ML workers run as UID 1000; nginx master runs as root to bind 80/443 and read the TLS key (workers as `nginx`); backup runs as root to read `/data`/write the host mount; no Docker socket is mounted |

No critical security issue remains.

---

## 6. Known limitations

1. The auth rate limiter is per API process; the production overlay runs one API
   replica. The E2E suite disables it for its many registrations; the default was
   restored and live-verified.
2. The production deployment verification reused the existing development
   volumes. The database role password was changed to the production secret and a
   gitignored `.env` was written; a fresh deployment initialises the volume with
   `POSTGRES_PASSWORD` from `.env.production`.
3. `mogen-object-worker:1.0.0` was built before `packaging==26.3` was pinned. It
   already contains packaging 26.3 (verified) and runs; the pin makes the
   dependency explicit for the scene worker and future rebuilds.
4. CI workflows are present and every command was executed locally; no remote CI
   runner exists in this environment (`TEST-AC-19` remote execution unobserved).
5. Scheduled backups default to a same-host directory; copy them off-host and
   test restores periodically.
6. The local production verification uses a self-signed certificate; a real
   deployment must install a trusted certificate.
7. The retained Phase 9 coverage shortfalls (frontend business logic 63.9%,
   generation-state 88.6%/85%) remain documented, not release blockers.
8. Historical orphan storage directories under `/data/projects` were verified but
   not bulk-deleted, per the data-safety rule.
9. The MVP remains single-host Compose; horizontal scaling, object storage and
   Kubernetes are Section 11 post-MVP work.

---

## 7. Files

**Created**

- `compose.prod.yaml`
- `frontend/nginx/default.conf`
- `infrastructure/backup/Dockerfile`, `infrastructure/backup/backup.sh`
- `infrastructure/certs/README.md`, `infrastructure/certs/.gitkeep`
- `infrastructure/scripts/generate-self-signed-cert.ps1`,
  `infrastructure/scripts/generate-self-signed-cert.sh`
- `.env.production.example`
- `VERSION`
- `docs/deployment.md`, `docs/developer_guide.md`, `docs/user_guide.md`,
  `docs/api.md`
- `docs/releases/v1.0.0.md`
- `docs/reviews/phase10_closeout.md` (this file)
- `.proof/phase10/` evidence (gitignored): E2E log, production status/images,
  backup manifest and restore-drill scripts

**Modified**

- `frontend/Dockerfile` — nginx production stage; `frontend/package.json` and
  `frontend/package-lock.json` — 1.0.0.
- `backend/app/core/config.py` — default version 1.0.0.
- `backend/requirements.txt` — explicit `packaging==26.3` (F1).
- `compose.yaml` untouched; `.env.example` — `APP_VERSION`; `.gitignore` — TLS,
  backup and production-env exceptions.
- `.github/workflows/ci.yml` — production Compose/nginx/backup validation.
- `e2e/playwright.config.ts`, `e2e/README.md` — HTTPS/self-signed run support.
- `README.md`, `docs/operations/backup_restore.md`, `docs/HANDOFF.md`,
  `docs/NEXT_SESSION.md`.

No migration was added; no viewer, result/download contract, outbox,
reconstruction-pipeline or ML behaviour was changed.

---

## 8. Acceptance criteria and milestone

### Phase 10 acceptance (the deployed MVP provides all ten)

1. User registration and authentication — **satisfied** (E2E 4/4 + HTTPS smoke).
2. Project creation and management — **satisfied** (E2E 2/2 + HTTPS smoke).
3. Uploading photographs — **satisfied** (E2E + HTTPS multipart smoke).
4. Generating 3D objects using TripoSR — **satisfied** (real E2E + worker logs).
5. Reconstructing scenes using COLMAP and OpenMVS — **satisfied** (real E2E,
   7.7 min, toolchain re-verified).
6. Tracking asynchronous generation tasks — **satisfied** (persisted status,
   stages and polling).
7. Viewing 3D objects and scenes in a browser — **satisfied** (viewer E2E).
8. Downloading GLB assets — **satisfied** (E2E size/magic checks).
9. Handling failed generation tasks — **satisfied** (failure/retry E2E and
   previous-result preservation tests).
10. Preserving user projects and generated assets — **satisfied** (identical
    counts and result SHA before/after deployment; backup restore matches).

### Infrastructure criteria

`INF-AC-01`, `INF-AC-02`, `INF-AC-05`, `INF-AC-06`, `INF-AC-07`, `INF-AC-08`,
`INF-AC-09`, `INF-AC-10`, `INF-AC-11`, `INF-AC-12`, `INF-AC-13`, `INF-AC-14`
(base stack validated, GPU overlay in use), `INF-AC-15`, `INF-AC-16`,
`INF-AC-17`, `INF-AC-19`, `INF-AC-20`, `INF-AC-21`, `INF-AC-22`, `INF-AC-23`,
`INF-AC-24` and `INF-AC-25` are satisfied at the Phase 10 scope. `INF-AC-18`
remains covered by the Phase 8 drills (unchanged code).

### Product and test criteria

`AC-01..AC-14` remain satisfied and were re-exercised end to end against the
production deployment. `TEST-AC-01..TEST-AC-18` and `TEST-AC-20` are satisfied by
the executed matrix; `TEST-AC-19` is satisfied locally (workflow files validated
and their commands executed) but remote CI execution was not observed.

### Milestone

**`M9` — MVP Released is achieved.** The application is deployable behind HTTPS,
all ten MVP functions were verified against the production configuration, the
release record and backup procedures exist, and no critical defect remains.

---

## 9. Next

Phase 10 is the last MVP phase. The remaining ideas are Section 11 (Future
Development) of the roadmap — horizontal scaling, object storage, richer
monitoring, route-level bundle splitting, shared rate limiting and remote CI
runners. They are post-MVP and were not implemented.
