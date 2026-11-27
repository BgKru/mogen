# Production Deployment Guide

**Scope:** MVP 1.0 deployment with Docker Compose (`08_infrastructure.md`
Sections 2.4, 8, 9, 12 and 13; roadmap tasks 10.1–10.3).
**Verification record:** [`reviews/phase10_closeout.md`](reviews/phase10_closeout.md)
**Release record:** [`releases/v1.0.0.md`](releases/v1.0.0.md)

The development stack in `compose.yaml` publishes the API, the Vite server,
PostgreSQL and Redis on `127.0.0.1`. The production overlay
`compose.prod.yaml` replaces that with a single published TLS reverse proxy,
runtime images, Secure cookies, a separate Celery beat service and a scheduled
backup service.

---

## 1. Topology

```text
                        Internet / operator network
                                   |
                                   v
                 +-----------------------------------+
                 | frontend (nginx 1.29)             |
                 |  :80  -> 301 https               |
                 |  :443 TLS termination            |
                 |  /            static React build  |
                 |  /api/        proxy -> api:8000   |
                 |  /health/     proxy -> api:8000   |
                 +----------------+------------------+
                                  | internal bridge network
        +-------------------------+---------------------------+
        |                         |                           |
        v                         v                           v
 +--------------+       +-------------------+       +----------------------+
 | api          |       | migration         |       | db (PostgreSQL 17)   |
 | FastAPI      |       | alembic upgrade   |       | postgres_data volume |
 | /data volume |       | head (one-shot)   |       +----------------------+
 +------+-------+       +-------------------+                  ^
        |                                                      |
        |  PostgreSQL only                          backup service|pg_dump
        v                                                      |
 +--------------+   +----------------+   +----------------+     |
 | outbox-      |   | cleanup-worker |   | beat           |     |
 | dispatcher   |   | file_cleanup   |   | schedules      |     |
 +------+-------+   +--------+-------+   +--------+-------+     |
        |                    |                    |             |
        +----------+---------+--------------------+             |
                   v                                            |
            redis (broker; redis_data volume)                  |
                   ^                                            |
        +----------+-----------+                                |
        |                      |                                |
 +--------------+      +----------------+                      |
 | object-      |      | scene-worker   |                      |
 | worker GPU   |      | COLMAP/OpenMVS |                      |
 +--------------+      +----------------+                      |
        |                      |                                |
        +----------+-----------+                                |
                   v                                            |
            /data (app_data volume) ----------------------------+
```

Published ports: **80/tcp and 443/tcp only**. PostgreSQL, Redis, the API and all
workers have no host port (`INF-AC-20`). The API, cleanup, outbox, recovery and
ML worker images run as UID 1000. The nginx frontend master runs as root to bind
80/443 and read the mounted TLS key (worker processes run as `nginx`), and the
backup container runs as root to read `/data` and write the host backup mount;
neither mounts the Docker socket. These are the only root containers, and the
frontend/backup images contain no application request surface or user data
beyond their mounts.

---

## 2. Prerequisites

- Docker Engine 24+ with Compose v2.24+ (the overlay uses `!reset`/`!override`),
  or Docker Desktop on Windows.
- For GPU generation: an NVIDIA GPU, a compatible host driver and the NVIDIA
  Container Toolkit. The CPU-only production stack is also supported; object
  generation then runs on CPU and is much slower.
- Disk: the scene worker image is ~11 GB and the object worker image is several
  GB; the `app_data` volume grows with user uploads and results. Keep at least
  50 GB free for the images plus working space.
- A TLS certificate for the public host name (or the self-signed certificate
  from `infrastructure/scripts/` for local verification only).
- Outbound access is needed once to build the images and to populate the TripoSR
  model cache (`model-init`). Task execution is offline.

---

## 3. Configure the environment

1. Copy the template outside version control:

   ```bash
   cp .env.production.example .env.production
   ```

2. Generate the two required secrets. Use URL-safe values because the PostgreSQL
   password is embedded in `DATABASE_URL`:

   ```bash
   # Linux/macOS
   openssl rand -hex 24      # POSTGRES_PASSWORD
   openssl rand -hex 48      # CSRF_SECRET
   ```

   ```powershell
   # Windows PowerShell 5.1
   [guid]::NewGuid().ToString('N')                                   # 32 hex chars
   ([guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')) # 64 hex chars
   ```

3. Fill in `.env.production`:

   | Variable | Meaning |
   |---|---|
   | `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | Required; also used to build `DATABASE_URL`. |
   | `CSRF_SECRET` | Required, 32+ characters. Production startup rejects the development default. |
   | `PUBLIC_ORIGIN` | Exact HTTPS origin, e.g. `https://mogen.example.com`. Used by the CSRF origin check. |
   | `SESSION_COOKIE_SECURE=true` | Required; production startup rejects `false`. |
   | `PUBLIC_HTTP_PORT`, `PUBLIC_HTTPS_PORT` | Published proxy ports (default 80/443). |
   | `TLS_CERT_DIR` | Directory with `tls.crt` and `tls.key` (default `./infrastructure/certs`). |
   | `BACKUP_HOST_DIR` | Host directory for scheduled backups (default `./.backups`). |
   | `BACKUP_INTERVAL_SECONDS`, `BACKUP_RETENTION_DAYS` | Backup schedule and retention. |
   | `APP_VERSION` | Release identifier reported by `/health/live`. |
   | `LOG_MAX_SIZE`, `LOG_MAX_FILES` | Docker json-file rotation (default 10 MB × 5). |
   | `AUTH_RATE_LIMIT_*` | Auth limiter (default 10 requests/minute per path and peer). |

   The application refuses to start when `APP_ENV=production` and either the CSRF
   secret or the Secure-cookie flag is wrong; this is covered by
   `backend/tests/unit/test_security.py`.

4. Install the TLS certificate:

   ```bash
   # Real certificate: copy the PEM chain and key to the mounted directory.
   install -m 0644 fullchain.pem infrastructure/certs/tls.crt
   install -m 0600 privkey.pem   infrastructure/certs/tls.key
   ```

   Local verification only:

   ```powershell
   .\infrastructure\scripts\generate-self-signed-cert.ps1
   ```

   ```bash
   ./infrastructure/scripts/generate-self-signed-cert.sh
   ```

   The self-signed certificate covers `localhost` and `127.0.0.1` and is valid
   for one year. Do not use it in a real deployment. The nginx configuration
   deliberately omits HSTS for `localhost`/`127.0.0.1` so the development Vite
   server keeps working in the same browser profile.

---

## 4. Build and start

```bash
# Validate the resolved configuration first (INF-AC-01).
docker compose --env-file .env.production \
  -f compose.yaml -f compose.prod.yaml config -q

# GPU deployment:
docker compose --env-file .env.production \
  -f compose.yaml -f compose.prod.yaml -f compose.gpu.yaml up -d --build

# CPU-only deployment: omit compose.gpu.yaml.
```

The first build takes a long time (the scene image compiles OpenCV and OpenMVS;
the object image compiles `torchmcubes`). Later builds reuse layers. `migration`
applies Alembic migrations and exits 0; `model-init` verifies/populates the
pinned TripoSR checkpoint in `triposr_model_cache` and exits 0. The object
worker then loads the model once and can take 4–5 minutes to become healthy.

Do **not** run `docker compose down -v`: it deletes `postgres_data`, `app_data`
and `triposr_model_cache`. Use `down` without `-v` to stop and keep data.

---

## 5. Post-start verification

```bash
docker compose --env-file .env.production \
  -f compose.yaml -f compose.prod.yaml ps -a
# migration and model-init: Exited (0); the other services healthy.

curl -k https://localhost/healthz                   # 200 "ok"
curl -k https://localhost/health/ready              # {"status":"ready",...}
curl -k https://localhost/health/dependencies       # database and redis ok
curl -k https://localhost/api/v1/probe              # JSON NOT_FOUND through nginx
curl -k -o /dev/null -w '%{http_code}\n' https://localhost/docs   # 404: docs off

# Only the proxy is published:
docker compose --env-file .env.production \
  -f compose.yaml -f compose.prod.yaml ps --format '{{.Service}} {{.Ports}}'
```

Secure-cookie check (registration sets both cookies):

```bash
curl -k -i -c cookies.txt -H 'Origin: https://localhost' \
  -H 'Content-Type: application/json' \
  -d '{"email":"deploy-check@example.com","password":"deploy-check-password"}' \
  https://localhost/api/v1/auth/register | grep -i '^set-cookie'
# session=...; HttpOnly; Secure; SameSite=lax ...
```

Remove the verification user with the application API (delete its project
first) or leave it only if intended; never remove the pre-existing data.

Worker checks:

```bash
docker compose --env-file .env.production -f compose.yaml -f compose.prod.yaml \
  exec cleanup-worker celery -A app.tasks.celery_app:celery_app inspect ping
docker compose ... exec object-worker celery ... inspect ping
docker compose ... exec scene-worker celery ... inspect ping
docker compose ... exec cleanup-worker sh -c \
  'celery -A app.tasks.celery_app:celery_app inspect registered -d celery@$HOSTNAME --timeout 5'
docker compose ... exec outbox-dispatcher cat /tmp/outbox-dispatcher.heartbeat
docker compose ... exec task-recovery cat /tmp/task-recovery.heartbeat
```

The full functional deployment gate is recorded in the Phase 10 close-out:
browser E2E through HTTPS, real object and scene generations, viewer and GLB
download, failure/retry, and the Phase 9 backend/frontend/ML matrix run against
the production images.

---

## 6. Scheduled backups

The `backup` service runs one backup immediately after `migration` completes and
then every `BACKUP_INTERVAL_SECONDS` (default daily). Each backup writes a
timestamped directory under `BACKUP_HOST_DIR`:

```text
.backups/20261111T170345Z/
  database.dump     pg_dump custom format
  app-data.tgz      /data/projects (uploads and results)
  SHA256SUMS
  manifest.json     app version, migration revision, sizes, checksums
```

Check the service and take an on-demand backup:

```bash
docker compose --env-file .env.production -f compose.yaml -f compose.prod.yaml ps backup
docker compose ... logs --tail 20 backup
docker compose ... run --rm backup --once
```

The service verifies each dump with `pg_restore --list` and each archive with
`tar -tzf`, writes a heartbeat after success, and prunes backups older than
`BACKUP_RETENTION_DAYS`.

**A Docker volume is not a backup.** `BACKUP_HOST_DIR` is a host bind mount, but
it is still on the same machine: copy it to independent storage (another host,
object storage, tape) on the same schedule, and test a restore periodically.
The complete restore procedure, consistency SQL and verification script are in
[`operations/backup_restore.md`](operations/backup_restore.md).

---

## 7. Upgrades and rollback

1. Take an on-demand backup: `... run --rm backup --once`.
2. Pull/copy the new release, update `APP_VERSION` and rebuild:
   `... up -d --build`.
3. `migration` applies new revisions before the API starts
   (`service_completed_successfully`). Alembic downgrades are not automated;
   restore the pre-upgrade backup if a rollback is required.
4. Verify Section 5 and the release record's image identifiers.

Image tags in the overlay are `mogen-api:1.0.0`, `mogen-object-worker:1.0.0`,
`mogen-scene-worker:1.0.0`, `mogen-frontend:1.0.0`, `mogen-backup:1.0.0`. Bump
them together with `VERSION`, `APP_VERSION` and the release record.

---

## 8. Logging and operations

Every long-running service uses Docker's `json-file` driver with bounded
rotation (`LOG_MAX_SIZE` × `LOG_MAX_FILES`). Application logs are single-line
JSON with `timestamp`, `level`, `service`, `message`, `request_id` where
applicable and identifiers such as `project_id`, `task_id` and `operation`.
Credentials and tokens are redacted.

```bash
docker compose --env-file .env.production -f compose.yaml -f compose.prod.yaml logs -f api
docker compose ... logs -f frontend backup
docker stats --no-stream
```

Diagnostics to check first: `GET /health/ready` (PostgreSQL),
`GET /health/dependencies` (database + Redis), worker pings, dispatcher/recovery
heartbeat files, `docker compose ps`, free disk space, and the scene workspace
usage line in the cleanup-worker logs.

---

## 9. Optional neural scene representation (increment 15)

The default stack builds and runs the released COLMAP + OpenMVS mesh path. The
Gaussian-splat representation is an opt-in overlay that requires a dedicated
worker image and a GPU:

```bash
docker compose build scene-worker
docker compose -f compose.yaml -f compose.gpu.yaml -f compose.splat.yaml up -d --build
docker compose -f compose.yaml -f compose.gpu.yaml -f compose.splat.yaml ps -a
```

The overlay sets `SCENE_REPRESENTATION=gaussian_splat`,
`SCENE_SPLAT_ENABLED=true` and `SCENE_OUTPUT_FORMAT=PLY` on the API and adds
`splat-worker` on the `scene_gaussian_splat` queue. The base scene worker keeps
consuming mesh tasks; each worker registers one capability and rejects tasks
persisted for the other representation (`SCENE_WORKER_INCOMPATIBLE`). Because the
representation is persisted with the task, rolling back to the mesh overlay does
not re-target already accepted splat tasks; stop the splat worker only after its
queue drains.

Operational notes:

- The neural stack lives in `/opt/splat-site` (isolated from the
  COLMAP/OpenMVS Python environment) and the gsplat CUDA kernels are compiled
  into the image at build time. A rebuild with a different torch/gsplat pin
  recompiles them; the build fails if the kernels cannot be built.
- The worker reserves one GPU and runs one task at a time. The admission check
  refuses a task when less free VRAM than `SCENE_SPLAT_MAX_VRAM_MB` (soft budget)
  is available; OOM/timeout are recorded as stable `SPLAT_*` codes.
- Training checkpoints stay in `/data/work/scene/{task_id}` and follow the
  existing workspace retention policy. Only the validated `.ply` and compact
  metadata are registered.
- The API image and the object worker import no Nerfstudio/gsplat package.
- A PLY result is downloaded as `application/octet-stream` with a `.ply`
  filename; the viewer lazy-loads the Gaussian-splat renderer and reports the
  Gaussian count instead of triangle statistics.

---

## 10. Security notes

- Only nginx is published; the API trusts proxy headers only because nginx is
  the sole reachable peer (`--forwarded-allow-ips=*` inside the internal
  network).
- Cookies: `session` is HttpOnly, `Secure` in production, `SameSite=Lax`,
  `Path=/`; the CSRF cookie is readable by design and the token is bound to the
  session.
- CSRF-protected calls validate the `Origin` header against `PUBLIC_ORIGIN`.
- API documentation is disabled in production (`ENABLE_API_DOCS=false`).
- Uploads are validated by decoded content, size and dimensions; storage keys
  are server-generated and never exposed.
- Keep `.env.production`, the TLS key and the backup directory out of version
  control. `.gitignore` already excludes them.
- The auth limiter is per API process. The MVP runs one API replica; behind N
  replicas the effective budget is N×. Sharing counters through Redis would
  break the rule that the API keeps accepting requests during a broker outage
  (`INF-AC-23`).

---

## 11. Deployment verification checklist (roadmap 10.2)

| Check | Command / evidence |
|---|---|
| Full startup | `ps -a`: 9+ services healthy, `migration` and `model-init` `Exited (0)` |
| Registration/login | HTTPS registration and login; Secure cookies; `/auth/me` |
| Project creation | UI or API create + list |
| Image upload | JPEG/PNG upload, listing, private content |
| Object generation | Real OBJECT task completes; result validated |
| Scene reconstruction | Real SCENE task completes; result validated |
| Result viewing | Viewer loads the GLB (`data-viewer-state="loaded"`) |
| Result download | `GET /download` returns the stored GLB bytes |
| Failed-task handling | A failing task shows a stable error and keeps prior data |
| Projects/assets preserved | Existing projects and results survive the deployment |

The 2026-11-11 verification executed all ten checks and the full Phase 9 matrix;
see [`reviews/phase10_closeout.md`](reviews/phase10_closeout.md).
