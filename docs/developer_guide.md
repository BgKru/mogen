# Developer Guide

**Application version:** 1.0.0 (see [`VERSION`](../VERSION) and
[`releases/v1.0.0.md`](releases/v1.0.0.md)).
**Authoritative requirements:** [`specifications/`](specifications/) and
[`architecture/`](architecture/). This guide is the practical entry point; where
it disagrees with a specification, the specification wins.

---

## 1. What the system does

A client-server application that turns photographs into downloadable GLB assets:

- **Object generation** — one photograph, TripoSR inference on a GPU worker.
- **Scene reconstruction** — multiple overlapping photographs, COLMAP sparse
  reconstruction and OpenMVS dense reconstruction/texturing on a scene worker.

Both modes run asynchronously through a transactional outbox and Celery queues.
The browser renders the current result with a React Three Fiber viewer and
downloads it through an authenticated endpoint.

```text
React + Vite (nginx in production)
        |  /api/v1 (same origin, session cookie + CSRF)
        v
FastAPI API  --->  PostgreSQL (authoritative state)
        |              ^
        | outbox        |
        v              |
Outbox Dispatcher --> Redis (broker) --> Celery workers
                                        object_generation / scene_reconstruction / file_cleanup
                                        |
                                        v
                                  /data volume (uploads + GLB results)
```

Redis is never the source of truth. The API does not connect to Redis; the
dispatcher publishes committed outbox rows and the recovery service reconciles
stale tasks (`INF-AC-21..25`).

---

## 2. Repository layout

```text
mogen/
├── backend/                 FastAPI application, Alembic migrations, tests
│   ├── app/api/             health + versioned endpoints
│   ├── app/core/            settings, logging, errors, security, rate limit
│   ├── app/db/              SQLAlchemy base, session, models
│   ├── app/repositories/    SQL-only data access
│   ├── app/services/        business rules and transactions
│   ├── app/storage/         StorageBackend + LocalStorage
│   ├── app/tasks/           Celery app, outbox dispatcher, recovery, ML adapters
│   └── tests/               unit, API-shell and PostgreSQL integration suites
├── frontend/                React 19 + Vite + TypeScript + R3F
│   ├── src/app/             providers, router, layout
│   ├── src/features/        auth, projects, image-upload, generation, model-viewer
│   ├── src/pages/           landing, auth, dashboard, create, details, viewer
│   ├── src/shared/          API client, DTO mappers, components, labels, config
│   └── nginx/               production reverse-proxy configuration
├── ml/
│   ├── object_generation/   TripoSR image, pipeline, tests, standalone proof
│   └── scene_reconstruction/ COLMAP/OpenMVS image, pipeline, tests, proof
├── infrastructure/
│   ├── backup/              scheduled backup image and script
│   ├── certs/               mounted TLS material (gitignored, README only)
│   └── scripts/             self-signed certificate helper
├── e2e/                     Playwright browser suite
├── docs/                    specifications, architecture, operations, reviews
├── compose.yaml             development stack (11 services)
├── compose.prod.yaml        production overlay (TLS proxy, runtime images, beat, backup)
├── compose.gpu.yaml         GPU reservation override
└── VERSION                  release version (1.0.0)
```

---

## 3. Prerequisites

- Docker Engine 24+ with Compose v2.24+ (or Docker Desktop).
- Windows: WSL2, Docker data root with ~50 GB free for the ML images.
- GPU path: NVIDIA GPU + driver + NVIDIA Container Toolkit. The base stack is
  CPU-capable; `compose.gpu.yaml` reserves the GPU for both ML workers. On a GPU
  host, put `COMPOSE_FILE=compose.yaml;compose.gpu.yaml` in `.env` (`:` on
  Linux/macOS) so plain `docker compose` commands include the overlay, or pass
  `-f compose.yaml -f compose.gpu.yaml`. With the overlay the object worker
  requires CUDA (`OBJECT_DEVICE=cuda:0`, `OBJECT_ALLOW_CPU_FALLBACK=false`) and
  COLMAP uses its GPU build.
- No host Python/Node is required for the normal workflow; every command runs
  inside the pinned images. Torch installed on the host is not used by the
  project — the containers carry their own CUDA PyTorch, and host-native ML runs
  are not a supported path.

Pinned versions and licensing are recorded in
[`architecture/phase0_decisions.md`](architecture/phase0_decisions.md) and the
release record.

---

## 4. First development start

```bash
cp .env.example .env
docker compose config -q
docker compose up -d --build
```

The first build is long (CUDA PyTorch/`torchmcubes` for the object worker;
OpenCV/OpenMVS for the scene worker). `migration` runs `alembic upgrade head`
and exits 0; `model-init` downloads and verifies the pinned TripoSR checkpoint
into the `triposr_model_cache` volume and exits 0. The worker is offline at
runtime (`HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`). The object worker loads
the model once at startup (4–5 minutes; 600 s health start period).

URLs:

| Service | URL |
|---|---|
| Frontend (Vite) | http://127.0.0.1:5173 |
| API | http://127.0.0.1:8000 |
| Swagger | http://127.0.0.1:8000/docs |
| Health | `/health/live`, `/health/ready`, `/health/dependencies` |

Use `http://localhost:5173` for browser/API proofs: the CSRF origin allowlist is
`http://localhost:5173`, not `127.0.0.1`.

Stop with `docker compose down` (keeps volumes). Never use `down -v` unless you
intend to delete the database, uploads and model cache.

---

## 5. Configuration

All settings are environment variables read by
`backend/app/core/config.py` (pydantic-settings). `.env.example` documents every
development variable; `.env.production.example` documents the production subset.
Key groups:

| Group | Variables |
|---|---|
| Application | `APP_ENV`, `APP_VERSION`, `DEBUG`, `LOG_LEVEL`, `ENABLE_API_DOCS`, `API_V1_PREFIX` |
| Database / broker | `DATABASE_URL`, `REDIS_URL`, `CELERY_BROKER_URL` |
| Auth | `SESSION_TTL_HOURS`, `SESSION_COOKIE_SECURE`, `CSRF_SECRET`, `AUTH_RATE_LIMIT_*`, `PASSWORD_*` |
| Uploads | `MAX_UPLOAD_SIZE_MB`, `MAX_IMAGE_DIMENSION`, `MIN_SCENE_IMAGES`, `MAX_SCENE_IMAGES`, `MAX_PAGE_SIZE` |
| Storage | `STORAGE_ROOT` (absolute) |
| Outbox / leases | `OUTBOX_*`, `TASK_LEASE_SECONDS`, `TASK_HEARTBEAT_SECONDS`, `TASK_STALE_THRESHOLD_SECONDS`, `DISPATCH_STALL_TIMEOUT_SECONDS`, `TASK_RECOVERY_*` |
| Cleanup | `CLEANUP_*`, `SESSION_CLEANUP_INTERVAL_SECONDS`, `SCENE_WORKSPACE_*` |
| Object worker | `OBJECT_*` (model revision/checkpoint SHA, device, preprocessing, limits) |
| Scene worker | `SCENE_*` (tool paths, matching, quality thresholds, timeouts, retention) |
| Frontend build | `VITE_API_BASE_URL`, `VITE_TASK_POLL_INTERVAL`, `VITE_MAX_UPLOAD_SIZE_MB`, `VITE_MIN/MAX_SCENE_IMAGES` |

Production guards: `APP_ENV=production` rejects the development CSRF secret and
`SESSION_COOKIE_SECURE=false`. Do not weaken these checks.

---

## 6. Compose commands

```bash
# Development (CPU-capable; with COMPOSE_FILE in .env this is already the GPU stack)
docker compose up -d --build
docker compose -f compose.yaml -f compose.gpu.yaml up -d --build   # GPU, explicit

# Rebuild one service after code changes (no bind mounts)
docker compose up -d --build api
docker compose up -d --build frontend

# Production overlay (see docs/deployment.md)
docker compose --env-file .env.production \
  -f compose.yaml -f compose.prod.yaml -f compose.gpu.yaml up -d --build
```

The API/workers copy source into images. A host edit is not visible to a running
container until the image is rebuilt (tests/lint can mount source explicitly).

---

## 7. Backend development

- Python 3.11, FastAPI, SQLAlchemy 2, Alembic, pydantic-settings.
- Layers: endpoint → service → repository → model. Repositories never commit;
  services own transactions.
- Errors use the envelope `{error: {code, message, details, request_id}}`
  (`api_contracts.md` Section 12).
- Generation never runs inside a request: `POST /generate` inserts the task,
  ordered input snapshot, project transition and outbox message in one
  transaction. The dispatcher publishes; workers claim with a lease.
- Terminal task transitions must refresh the row (`populate_existing` /
  `get_refreshed`) so a concurrent cancellation is not hidden by the identity
  map.

Run the suite through Compose (PostgreSQL is required):

```bash
docker compose run --rm --no-deps api pytest
docker compose run --rm --no-deps api pytest --cov=app --cov-report=term-missing
docker compose run --rm --no-deps api ruff check .
docker compose run --rm --no-deps api ruff format --check .
docker compose run --rm --no-deps api alembic check
docker compose run --rm --no-deps api pip check
```

Integration tests create and drop the scratch databases `mogen_test` and
`mogen_test_migration` on the `db` service; they never touch the development
database. Test uploads go to `/tmp/mogen-test-storage`.

Schema changes: add an Alembic revision under `backend/alembic/versions/`, run
`alembic upgrade head`, and confirm `alembic check` reports no drift. The MVP
schema is revision `1f302d830cf9`.

---

## 8. Frontend development

React 19.3.1, TypeScript 5.9.3, Vite 8, TanStack Query, React Hook Form + Zod,
React Three Fiber 9.8.2 / Drei 10.7.9 / Three.js 0.187.0 (exact pins).

- `src/shared/api/` is the only HTTP boundary; DTOs stay snake_case and mappers
  convert to camelCase domain models.
- CSRF token lives in memory and is attached by the Axios interceptor.
- The UI language is Russian; labels live in `src/shared/lib/labels.ts`.
- The viewer is an independent feature module; it loads the GLB through the
  authenticated client and disposes GPU resources on unmount.

```bash
docker run --rm mogen-frontend:dev npm run lint
docker run --rm mogen-frontend:dev npm run typecheck
docker run --rm mogen-frontend:dev npm run format:check
docker run --rm mogen-frontend:dev npm run test:run
docker run --rm mogen-frontend:dev npm run build
```

For fast iteration without rebuilding, mount only `frontend/src` (and
`vitest.config.ts` when measuring coverage) into the dev image.

---

## 9. ML workers

### Object generation (TripoSR)

- Image: `mogen-object-worker:1.0.0` (development tag `:dev`), PyTorch
  2.14.1/CUDA 12.6, TripoSR pinned by commit
  `d26e33181947bbbc4c6fc0f5734e1ec6c080956e`, `torchmcubes` pinned and compiled
  for SM 86.
- Weights: Hugging Face revision `5b521936b01fbe1890f6f9baed0254ab6351c04a`,
  `model.ckpt` SHA-256 `429e2c6b…`; DINO `f205d5d8…`.
- `model-init` is the only process allowed to download; it populates
  `triposr_model_cache:/models`. Workers run offline and verify the checksum.
- The worker loads the model once (`--pool=solo`) and registers the pipeline via
  `register_pipeline(TaskType.OBJECT, ...)`.

```bash
# Unit suite (no GPU)
docker run --rm mogen-object-worker:dev python -m pytest /opt/object_generation/tests -q

# Opt-in real inference (GPU + populated cache)
docker run --rm --gpus all -v mogen_triposr_model_cache:/models \
  -v "${PWD}/ml:/work/ml" -w /work/ml/object_generation \
  -e PYTHONPATH=/work/ml:/opt/triposr:/opt -e RUN_REAL_MODEL_TESTS=1 \
  mogen-object-worker:dev python -m pytest -m real_model -q
```

### Scene reconstruction (COLMAP + OpenMVS)

- Image: `mogen-scene-worker:1.0.0` based on the pinned official COLMAP 4.2.1
  CUDA image; OpenMVS 2.4.0 built unmodified from commit
  `58117204c86bbb11a0b25b26a8987676cf11274d`, with OpenCV 4.12.0, CGAL 6.0.1,
  Eigen 3.4 and VCGLib `658ba36d…`.
- The worker verifies all seven executables at startup and registers an honest
  `EXTERNAL_TOOL_UNAVAILABLE` pipeline if the toolchain is broken.
- Workspaces live on `/data/work/scene/{task_id}` so checkpoints survive a
  restart; the retention sweep prunes terminal workspaces.

```bash
docker run --rm mogen-scene-worker:dev python -m pytest /opt/scene_reconstruction/tests -q
docker run --rm mogen-scene-worker:dev python -m scene_reconstruction.standalone --verify-tools
```

The real 11-image proof is documented in
[`reviews/phase6_closeout.md`](reviews/phase6_closeout.md) and
[`reviews/phase10_closeout.md`](reviews/phase10_closeout.md).

---

## 10. End-to-end tests

The repository Playwright suite drives the real UI and both generation modes.

```bash
cd e2e
npm ci                              # first time only
# Development stack:
node node_modules/playwright/cli.js test
# Production HTTPS stack (self-signed certificate):
$env:E2E_BASE_URL='https://localhost'
$env:E2E_IGNORE_HTTPS_ERRORS='true'
node node_modules/playwright/cli.js test
```

The suite registers many users from one address, so start the stack with
`AUTH_RATE_LIMIT_ENABLED=false` for the run and restore the default afterwards.
`E2E_SCENE_IMAGES` must point at overlapping photographs or the real scene test
skips. Tests are serial (`workers: 1`) because they share one stack and one GPU.

---

## 11. API documentation

The API contract is [`architecture/api_contracts.md`](architecture/api_contracts.md).
The endpoint summary is in [`api.md`](api.md). In development, Swagger UI is at
`/docs` and the OpenAPI document at `/openapi.json`; production disables both
(`ENABLE_API_DOCS=false`).

Every endpoint except health and auth requires the `session` cookie; state
changes additionally require `X-CSRF-Token`. Generation creation requires a
project-scoped `Idempotency-Key`.

---

## 12. CI and quality gates

`.github/workflows/ci.yml` is the fast gate: backend lint/format/migrations/pytest
with coverage, frontend lint/typecheck/format/tests/coverage/build, and Compose
validation. `e2e.yml` runs the browser suite; `ml-validation.yml` runs the real
ML proofs on a self-hosted GPU runner. The workflows are validated locally; no
remote runner is available in this environment.

Before reporting work complete:

```bash
docker compose run --rm --no-deps api pytest
docker compose run --rm --no-deps api ruff check .
docker compose run --rm --no-deps api ruff format --check .
docker compose run --rm --no-deps api alembic check
docker compose run --rm --no-deps api pip check
docker run --rm mogen-object-worker:dev python -m pytest /opt/object_generation/tests -q
docker run --rm mogen-scene-worker:dev python -m pytest /opt/scene_reconstruction/tests -q
docker run --rm mogen-frontend:dev npm run lint
docker run --rm mogen-frontend:dev npm run typecheck
docker run --rm mogen-frontend:dev npm run format:check
docker run --rm mogen-frontend:dev npm run test:run
docker run --rm mogen-frontend:dev npm run build
```

Expected counts after increment 12 (2026-11-25): **541 backend**, **173 frontend**,
**119 scene ML + 2 skipped**, **39 object ML + 1 skipped**, **47 image-quality**,
**1 feature interoperability** (opt-in), **17/17 E2E** (last run at 1.0.0). The
scene suite now requires the rebuilt neural-capable `mogen-scene-worker:dev`.

---

## 13. Common traps

The full list is in [`HANDOFF.md`](HANDOFF.md) Section 6. The ones that cost the
most time:

- Rebuild images after code changes; the running container serves the image copy.
- Use `http://localhost:5173`, not `127.0.0.1`, for CSRF-protected browser calls.
- OpenMVS writes a log into the CWD; probes run in a throwaway directory.
- COLMAP `pair_id` encodes two image ids (`id1 * 2147483647 + id2`).
- `session_scope` is a context manager; use `with`.
- Do not reset the development database or delete `/data/projects` in bulk.
- The object worker needs 4–5 minutes to load the model; do not lower the health
  start period without measuring.
