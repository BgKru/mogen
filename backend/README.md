# Backend

FastAPI application for the 3D generation platform.

## Layout

```text
backend/
├── app/
│   ├── main.py            application factory, middleware, error handlers
│   ├── api/               health endpoints and versioned API routers
│   ├── core/              configuration, logging, errors, security primitives
│   ├── db/                engine, session factory, base and ORM models
│   ├── repositories/      database access, one module per entity
│   ├── schemas/           Pydantic request and response models
│   ├── services/          business rules and transaction boundaries
│   └── tasks/             Celery application and the cleanup worker task
├── alembic/               migrations (initial schema in versions/)
├── tests/                 unit, API and database tests
├── requirements.txt       runtime dependencies, pinned
├── requirements-dev.txt   test and lint tooling
├── pyproject.toml         ruff and pytest configuration
└── Dockerfile             runtime and development targets
```

## Local checks

Run inside the development image so the pinned Python and dependencies are used:

```bash
docker compose run --rm api pytest
docker compose run --rm api ruff check .
docker compose run --rm api ruff format --check .
```

## Health endpoints

| Endpoint | Purpose | Failure mode |
|---|---|---|
| `GET /health/live` | Process is running | Never fails while the process lives |
| `GET /health/ready` | PostgreSQL is reachable | `503` when it is not |
| `GET /health/dependencies` | PostgreSQL and Redis report | Always `200`, `degraded` when a dependency is down |

`/health/ready` intentionally ignores Redis: a broker outage must not make project management unavailable.

## Database migrations

Alembic uses the same `DATABASE_URL` as the API. Migrations are applied by the `migration` Compose service before the API starts; the API never migrates on startup.

```bash
docker compose run --rm api alembic upgrade head
docker compose run --rm api alembic current
docker compose run --rm api alembic check
docker compose run --rm api alembic downgrade base
```

The initial migration (`alembic/versions/1f302d830cf9_initial_schema.py`) creates
all nine MVP tables, their constraints and their indexes, as defined by
`docs/specifications/05_database_specification.md`.

## Database tests

Tests under `tests/db/` are marked `integration`. They create and drop the
dedicated databases `mogen_test` (entity, constraint and relationship tests)
and `mogen_test_migration` (schema and migration round-trip tests) on the
Compose PostgreSQL server, and they drive the real Alembic CLI. The API test
container has no Docker socket, so Testcontainers is not used; this is the
documented alternative from `09_testing.md` Section 3.3 and
`docs/HANDOFF.md` Section 9.

```bash
docker compose run --rm api pytest tests/db -m integration
```

The tests read `DATABASE_URL` and never touch the development database.

## Cleanup worker

Project and image deletion never touch the filesystem inside a request: they
remove metadata and record a `storage_cleanup_jobs` row. The `cleanup-worker`
Compose service consumes those jobs from the dedicated Celery `file_cleanup`
queue.

`app/services/cleanup_service.py` claims the oldest pending job with
`FOR UPDATE ... SKIP LOCKED` and keeps the transaction open until the job
finishes, so a crash rolls the claim back instead of stranding the job in
`PROCESSING`. A successful delete marks the job `COMPLETED`; a failure records
`last_error` and either returns it to `PENDING` or, after
`CLEANUP_MAX_ATTEMPTS` attempts, marks it `FAILED`. Deleting an already absent
file counts as success, so retries are safe. Directory jobs wait while the
project still has a `PENDING` or `PROCESSING` generation task.

`app/tasks/celery_app.py` configures the broker (`CELERY_BROKER_URL`, Redis DB 1),
the queue routing and the beat poll. `app/tasks/cleanup_tasks.py` exposes
`cleanup_storage_task`, which runs one scan cycle when called without arguments
and can process a single dispatched job when called with `job_id`.

| Variable | Default | Notes |
|---|---|---|
| `CELERY_BROKER_URL` | `redis://redis:6379/1` | Broker database, separate from direct Redis access |
| `CLEANUP_BATCH_SIZE` | `20` | Jobs attempted per cycle |
| `CLEANUP_POLL_INTERVAL_SECONDS` | `15` | Beat interval for the scan |
| `CLEANUP_MAX_ATTEMPTS` | `3` | Failed attempts before a job is `FAILED` |
| `CLEANUP_TASK_TIME_LIMIT_SECONDS` | `600` | Hard Celery time limit |

```bash
docker compose logs -f cleanup-worker
docker compose exec cleanup-worker celery -A app.tasks.celery_app:celery_app inspect ping
```

Development runs the beat scheduler inside the worker container (`--beat`).
Production should split beat into its own service.

## Repositories

`app/repositories/` contains one repository per entity (users, sessions,
projects, images, tasks, results, cleanup jobs and outbox messages).
Repositories encapsulate SQL and never commit: services own business rules and
transaction boundaries. Endpoints receive them through the dependency
providers in `app/api/dependencies.py`, so tests can override them with
`app.dependency_overrides`.

## Authentication

Session authentication lives in `app/services/auth_service.py`,
`app/core/security.py` and `app/api/v1/endpoints/auth.py`.

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/auth/register` | Create a user and an authenticated session |
| `POST /api/v1/auth/login` | Verify credentials and open a session |
| `POST /api/v1/auth/logout` | Revoke the session and clear both cookies |
| `GET /api/v1/auth/me` | Return the authenticated user |
| `GET /api/v1/auth/csrf` | Return the session-bound CSRF token |

Passwords are hashed with Argon2id (`argon2-cffi`, MIT); emails are validated with
`email-validator` (Unlicense) and normalized to lowercase. The raw 256-bit session token is
sent in the HttpOnly `session` cookie and only its SHA-256 hash is stored. The
readable `csrf_token` cookie carries an HMAC token bound to the session and
must be copied into the `X-CSRF-Token` header for state-changing requests.

Authentication settings:

| Variable | Default | Notes |
|---|---|---|
| `SESSION_TTL_HOURS` | `24` | Session and cookie lifetime |
| `CSRF_SECRET` | development value | Must be overridden with 32+ characters in production |
| `SESSION_COOKIE_SECURE` | `false` | Must be `true` in production (HTTPS) |
| `PASSWORD_MIN_LENGTH` | `8` | Minimum accepted password length |
| `PASSWORD_MAX_LENGTH` | `128` | Maximum accepted password length |

The application refuses to start with `APP_ENV=production` while the CSRF
secret is the development default or cookies are not marked Secure.
