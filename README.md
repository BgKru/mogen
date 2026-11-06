# mogen — 3D Generation Web Application

Client-server application for generating 3D models from photographs.

Two generation modes:

- **Object generation** — a single 3D object from one photograph, using TripoSR.
- **Scene reconstruction** — an environment from multiple photographs, using COLMAP and OpenMVS.

Generated assets are delivered as GLB and visualized in the browser.

## Project status

Phase 0 (specification consolidation), Phase 1 (infrastructure foundation), Phase 2 (database and backend foundation) and Phase 3 (frontend application and backend integration) are complete. Phase 4 (background processing infrastructure) is next.

| Component | Status |
|---|---|
| PostgreSQL 17.11 service | Running and healthy |
| Redis 7.4.12 service | Running and healthy |
| Backend API (FastAPI) | Implemented: authentication, projects, image upload/content/deletion, health endpoints, cleanup jobs |
| Migration service | Implemented: applies Alembic migrations before the API starts |
| Frontend (React + Vite) | Implemented: auth, dashboard, project creation, image upload, project details, tests |
| Cleanup worker | Implemented: Celery `file_cleanup` worker executing queued storage cleanup jobs |
| Generation workers and dispatcher | Not implemented (Phase 4) |
| 3D viewer and result download | Not implemented (later phases) |

The Compose file defines the data services, the migration service, the API, the frontend and the cleanup worker. Generation workers and the outbox dispatcher are added with Phase 4.

Verified on the reference machine: Compose validation and image builds; PostgreSQL, Redis and API health checks; PostgreSQL data survival across container recreation; Redis AOF survival across a restart; readiness returning 503 while PostgreSQL is down and recovering afterwards; Redis isolation, where a broker outage degrades the dependency report but keeps readiness healthy; structured JSON logs with redacted credentials; the API running as an unprivileged user with a writable storage volume; the frontend served on port 5173 and proxying `/api` to the API; 339 passing backend tests; 84 passing frontend tests; and frontend lint, type check, formatting and production build passing.

## Technology stack

| Layer | Technology |
|---|---|
| Frontend | React, TypeScript, Vite, Tailwind CSS, Three.js |
| Backend | Python 3.11, FastAPI, SQLAlchemy, Alembic |
| Database | PostgreSQL 17 |
| Broker | Redis 7.4 |
| Background processing | Celery |
| Object generation | TripoSR |
| Scene reconstruction | COLMAP, OpenMVS |
| Infrastructure | Docker, Docker Compose |

Pinned versions, licensing decisions and hardware requirements are recorded in [`docs/architecture/phase0_decisions.md`](docs/architecture/phase0_decisions.md).

## Repository layout

```text
mogen/
├── docs/                     specifications, architecture records, reviews, agent guide
├── frontend/                 React application
├── backend/                  FastAPI application
├── ml/                       object generation, scene reconstruction, workers
├── infrastructure/           docker, nginx, scripts
├── tests/                    cross-component tests
├── compose.yaml              development stack
├── .env.example              environment template
└── README.md
```

## Prerequisites

- Docker Engine 24 or newer with Compose v2, or Docker Desktop on Windows.
- Windows only: WSL2 with the Docker data root on a drive with at least 50 GB free.
- GPU work requires an NVIDIA GPU, a compatible driver and the NVIDIA Container Toolkit. The application must also run CPU-only, with explicit errors when hardware is missing.

## Quick start

1. Create the local environment file:

   ```bash
   cp .env.example .env
   ```

2. Validate the configuration:

   ```bash
   docker compose config
   ```

3. Build and start the stack:

   ```bash
   docker compose up -d --build
   ```

   The `migration` service applies Alembic migrations and exits; the API starts only after it succeeds.

4. Check health:

   ```bash
   docker compose ps
   curl http://127.0.0.1:8000/health/ready
   curl http://127.0.0.1:8000/health/dependencies
   docker compose exec db pg_isready -U app -d app
   docker compose exec redis redis-cli ping
   ```

   The application is served at `http://127.0.0.1:5173`. Interactive API documentation is at `http://127.0.0.1:8000/docs` in development.

5. Run tests and lint:

   ```bash
   docker compose run --rm --no-deps api pytest
   docker compose run --rm --no-deps api ruff check .
   docker run --rm mogen-frontend:dev npm run lint
   docker run --rm mogen-frontend:dev npm run typecheck
   docker run --rm mogen-frontend:dev npm run test:run
   ```

6. Stop:

   ```bash
   docker compose down
   ```

`docker compose down -v` also deletes the data volumes. It is destructive: use it only when you intend to lose local data.

## Documentation

| Document | Purpose |
|---|---|
| [`docs/AI_DEVELOPMENT_GUIDE.md`](docs/AI_DEVELOPMENT_GUIDE.md) | Workflow, quality gates and rules for implementation work |
| [`docs/HANDOFF.md`](docs/HANDOFF.md) | Current project state, tooling traps and the next task, for a new session |
| [`docs/specifications/`](docs/specifications/) | Product, UI, frontend, backend, database, ML, infrastructure and testing specifications |
| [`docs/specifications/10_development_roadmap.md`](docs/specifications/10_development_roadmap.md) | Implementation order and milestones |
| [`docs/architecture/`](docs/architecture/) | System architecture, API contracts, data flows, Phase 0 decisions |

The specifications are the source of truth. Where this file and a specification disagree, the specification governs.
