# mogen — 3D Generation Web Application

Client-server application for generating 3D models from photographs.

- **Object generation** — one photograph, TripoSR inference, GLB with vertex
  colours.
- **Scene reconstruction** — multiple overlapping photographs, COLMAP sparse
  reconstruction + OpenMVS dense reconstruction and texturing, self-contained
  textured GLB.

Generation runs asynchronously on dedicated GPU workers. Results are stored
durably, rendered in a browser (React Three Fiber) and downloadable.

**Current release: 1.0.0** — see [`VERSION`](VERSION) and
[`docs/releases/v1.0.0.md`](docs/releases/v1.0.0.md).

## Status

Phases 0–10 are complete. The MVP provides registration/authentication, project
management, image upload, real TripoSR object generation, real COLMAP/OpenMVS
scene reconstruction, asynchronous task tracking, browser viewing, GLB download,
failure/retry handling and durable projects/assets. Phase 10 added the
production images and overlay, the nginx TLS reverse proxy, Secure cookies,
scheduled backups, the deployment verification, user/developer documentation and
the versioned release record.

| Component | Status |
|---|---|
| PostgreSQL 17.11 | Persistent metadata; Alembic revision `1f302d830cf9` |
| Redis 7.4.12 | Celery broker only (DB 1); never the source of truth |
| Backend API (FastAPI) | Auth, projects, uploads, generation/status, result/download, health |
| Migration service | `alembic upgrade head` before the API/workers start |
| Frontend | React 19 + Vite; auth, dashboard, creation, uploads, details, generation panels, 3D viewer |
| Object worker | Real TripoSR on CUDA in `mogen-object-worker:1.0.0` |
| Scene worker | Real COLMAP 4.2.1 + OpenMVS 2.4.0 in `mogen-scene-worker:1.0.0` |
| Outbox dispatcher / task recovery | Independent processes with heartbeat health checks |
| Production release | nginx TLS proxy + static build, runtime images, separate beat, scheduled backup (`compose.prod.yaml`) |

Verified matrix at 1.0.0: **525 backend**, **148 frontend**, **75 scene ML + 1
skipped**, **35 object ML + 1 skipped**, **17/17 browser E2E**. The production
deployment verification is recorded in
[`docs/reviews/phase10_closeout.md`](docs/reviews/phase10_closeout.md).

## Technology stack

| Layer | Technology |
|---|---|
| Frontend | React 19.3.1, TypeScript 5.9.3, Vite 8, Tailwind CSS 4, Three.js 0.187.0 / React Three Fiber 9.8.2 / Drei 10.7.9 |
| Backend | Python 3.11, FastAPI, SQLAlchemy 2, Alembic, Pydantic |
| Database | PostgreSQL 17.11 |
| Broker | Redis 7.4.12 |
| Background processing | Celery 5.7.0 |
| Object generation | TripoSR (pinned commit/checkpoint), PyTorch 2.14.1/CUDA 12.6 |
| Scene reconstruction | COLMAP 4.2.1, OpenMVS 2.4.0, OpenCV 4.12, CGAL 6.0.1 |
| Infrastructure | Docker, Docker Compose, nginx |

Pinned versions, licensing decisions and the hardware profile are in
[`docs/architecture/phase0_decisions.md`](docs/architecture/phase0_decisions.md)
and [`docs/releases/v1.0.0.md`](docs/releases/v1.0.0.md).

## Repository layout

```text
mogen/
├── backend/                  FastAPI application + Alembic + tests
├── frontend/                 React application + nginx production config
├── ml/
│   ├── object_generation/    TripoSR worker image and pipeline
│   ├── scene_reconstruction/ COLMAP/OpenMVS worker image and pipeline
│   └── workers/              reserved placeholder
├── infrastructure/
│   ├── backup/               scheduled backup image and script
│   ├── certs/                mounted TLS material (gitignored)
│   └── scripts/              self-signed certificate helper
├── e2e/                      Playwright browser suite
├── docs/                     specifications, architecture, operations, reviews, guides
├── compose.yaml              development stack (eleven services)
├── compose.prod.yaml         production overlay
├── compose.gpu.yaml          GPU reservation override
├── .env.example              development environment template
├── .env.production.example   production environment template
└── VERSION                   1.0.0
```

## Prerequisites

- Docker Engine 24+ with Compose v2.24+ (or Docker Desktop on Windows).
- Windows: WSL2 and a Docker data root with at least ~50 GB free for the ML
  images.
- GPU deployment: NVIDIA GPU, compatible driver and NVIDIA Container Toolkit.
  The base stack runs CPU-only; `compose.gpu.yaml` reserves the GPU for both ML
  workers.

## Development quick start

```bash
cp .env.example .env
docker compose config -q
docker compose up -d --build          # add -f compose.gpu.yaml for GPU
```

The `migration` service applies the schema and exits 0; `model-init` populates
the pinned TripoSR cache and exits 0. The object worker loads the model once
(4–5 minutes; 600 s health start period).

| Endpoint | URL |
|---|---|
| Application | http://localhost:5173 |
| API | http://127.0.0.1:8000 |
| Swagger | http://127.0.0.1:8000/docs |
| Readiness | http://127.0.0.1:8000/health/ready |

Use `http://localhost:5173` (not `127.0.0.1`) for browser flows: the CSRF origin
allowlist matches that origin.

Stop with `docker compose down`; **never** `down -v` unless you intend to delete
the database, uploads and model cache.

## Production deployment

```bash
cp .env.production.example .env.production    # fill secrets and PUBLIC_ORIGIN
# install infrastructure/certs/tls.crt + tls.key (or generate a self-signed pair)
docker compose --env-file .env.production \
  -f compose.yaml -f compose.prod.yaml -f compose.gpu.yaml up -d --build
```

Only nginx publishes ports (80/443). PostgreSQL, Redis, the API and the workers
are internal. API docs are disabled, cookies are Secure, and a `backup` service
writes PostgreSQL dumps plus `/data/projects` archives to `BACKUP_HOST_DIR`.
The complete procedure, verification commands, upgrade/rollback notes and
troubleshooting are in [`docs/deployment.md`](docs/deployment.md).

## Tests

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
docker run --rm mogen-frontend:dev npm run test:run
docker run --rm mogen-frontend:dev npm run build
```

The browser suite is in [`e2e/`](e2e/README.md); CI workflow files are in
`.github/workflows/`.

## Documentation

| Document | Purpose |
|---|---|
| [`docs/user_guide.md`](docs/user_guide.md) | Registration, projects, photograph preparation, generation, viewer, download |
| [`docs/deployment.md`](docs/deployment.md) | Production configuration, TLS, startup, verification, backups, upgrades |
| [`docs/developer_guide.md`](docs/developer_guide.md) | Repository map, environment, Compose, ML workers, testing |
| [`docs/api.md`](docs/api.md) | Endpoint summary and error/cookie conventions |
| [`docs/operations/backup_restore.md`](docs/operations/backup_restore.md) | Manual and scheduled backup, restoration and consistency checks |
| [`docs/specifications/`](docs/specifications/) | Product, UI, frontend, backend, database, ML, infrastructure, testing, roadmap |
| [`docs/architecture/`](docs/architecture/) | System architecture, API contracts, data flows, Phase 0 decisions |
| [`docs/reviews/`](docs/reviews/) | Phase close-out reviews with evidence |
| [`docs/HANDOFF.md`](docs/HANDOFF.md) | Session continuation state and tooling traps |
| [`docs/NEXT_SESSION.md`](docs/NEXT_SESSION.md) | Short next-session entry point |

The specifications are the source of truth. Where this file and a specification
disagree, the specification governs.
