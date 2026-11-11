# Backup and Restoration Procedures

**Scope:** development and MVP deployment of the 3D generation application.
**Requirements:** `08_infrastructure.md` Sections 12.1–12.5, `INF-AC-19` and the
Phase 8 deliverables (backup documentation, storage cleanup verification).
**Last verified:** 2026-11-11 (Phase 10; scheduled `backup` service and a live
backup/restore check; see `docs/reviews/phase10_closeout.md`).

The authoritative state is PostgreSQL plus the application file storage in the
`app_data` volume. Redis is a broker only: its AOF improves recovery but never
replaces the transactional outbox (`08` Section 12.3). The `triposr_model_cache`
volume holds pinned, re-downloadable weights; it is not user data and is
repopulated by the one-shot `model-init` service.

> A Docker volume is **not** a backup. Copy the artefacts off the host or into an
> independent backup location, and never commit them to the repository.

---

## 1. What to back up

| Item | Source | Notes |
|---|---|---|
| Database metadata | PostgreSQL service `db` | Users, sessions, projects, images, tasks, results, cleanup jobs, outbox |
| Uploaded photographs and generated GLBs | `app_data` volume (`/data`) | `projects/{project_id}/...`; scene workspaces under `work/` are diagnostic only |
| Model cache | `triposr_model_cache` volume | Optional; reproducible via `model-init` |
| Configuration | `.env` (never committed) | Environment-specific secrets |

Scene workspaces under `/data/work/scene` are intermediate diagnostics. They are
pruned by the retention sweep and are **not** required to restore a project; a
restored project keeps its current result from `/data/projects`.

---

## 2. PostgreSQL backup

Run from the repository root (PowerShell on Windows):

```powershell
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
docker compose exec -T db pg_dump -U app -d app -Fc -f "/tmp/app-$stamp.dump"
docker cp mogen-db-1:/tmp/app-$stamp.dump ".backups/app-$stamp.dump"
docker compose exec -T db rm -f "/tmp/app-$stamp.dump"
```

`-Fc` produces the compressed custom format used by `pg_restore`. A plain SQL
dump (`pg_dump ... > file.sql`) is also acceptable but must be written inside the
container first: PowerShell redirection would re-encode it and corrupt the file.

For a write-quiesced backup (recommended before a release), stop the writers
while the dump runs:

```powershell
docker compose stop api cleanup-worker object-worker scene-worker outbox-dispatcher task-recovery frontend
docker compose exec -T db pg_dump -U app -d app -Fc -f /tmp/app.dump
docker cp mogen-db-1:/tmp/app.dump .backups/app.dump
docker compose start db redis api cleanup-worker object-worker scene-worker outbox-dispatcher task-recovery frontend
```

Stopping the workers is safe: the outbox and task leases are durable, and the
recovery service requeues tasks whose lease expired.

---

## 3. File storage backup

`app_data` is a named volume. Copy a consistent snapshot with a one-off
container that mounts the same volume (do not `docker compose cp` from a running
worker: `docker cp` is not atomic for a live tree).

```powershell
docker run --rm `
  -v mogen_app_data:/data:ro `
  -v "${PWD}/.backups:/backup" `
  mogen-api:dev `
  tar -czf /backup/app-data-<stamp>.tgz -C /data projects
```

Include `work/` only if the diagnostic workspaces are needed; they are large and
not required for restoration.

---

## 4. Restoration

Restoration restores the database **and** the files. The result rows reference
storage keys, so restoring only one half produces missing-file errors.

1. Stop writers (same service list as above).
2. Restore PostgreSQL into a clean database:

   ```powershell
   docker compose exec -T db psql -U app -d postgres -c "DROP DATABASE IF EXISTS app WITH (FORCE); CREATE DATABASE app OWNER app;"
   docker cp .backups/app-<stamp>.dump mogen-db-1:/tmp/restore.dump
   docker compose exec -T db pg_restore -U app -d app --no-owner --role=app /tmp/restore.dump
   ```

3. Restore the files into the volume:

   ```powershell
   docker run --rm `
     -v mogen_app_data:/data `
     -v "${PWD}/.backups:/backup:ro" `
     mogen-api:dev `
     sh -c "rm -rf /data/projects && tar -xzf /backup/app-data-<stamp>.tgz -C /data"
   ```

4. Ensure the schema is at the expected revision and start the stack:

   ```powershell
   docker compose run --rm --no-deps api alembic upgrade head
   docker compose start db redis api cleanup-worker object-worker scene-worker outbox-dispatcher task-recovery frontend
   ```

5. Run the consistency checks in Section 5 before declaring the restore done.
6. Pending outbox messages are published by the dispatcher after it starts;
   stale `PROCESSING` tasks are requeued or failed by the task-recovery service.
   No manual intervention is required for either.

### Restoring a scheduled backup

The `backup` service writes one directory per run. Use its `database.dump` and
`app-data.tgz` in place of the manual artefacts above:

```powershell
$backup = ".backups/20261111T170345Z"     # the chosen timestamp directory
docker cp "$backup/database.dump" mogen-db-1:/tmp/restore.dump
docker compose exec -T db psql -U app -d postgres -c "DROP DATABASE IF EXISTS app WITH (FORCE); CREATE DATABASE app OWNER app;"
docker compose exec -T db pg_restore -U app -d app --no-owner --role=app /tmp/restore.dump
docker run --rm -v mogen_app_data:/data -v "${PWD}/$backup:/backup:ro" mogen-api:dev `
  sh -c "rm -rf /data/projects && tar -xzf /backup/app-data.tgz -C /data"
```

`SHA256SUMS` and the checksums in `manifest.json` prove the artefacts are
unmodified; verify them before restoring (`sha256sum -c SHA256SUMS` inside the
backup directory). The manifest's `migration_revision` must match the release
being restored; `alembic upgrade head` after the restore applies any later
revision.

---

## 5. Post-restore consistency verification

`08` Section 12.5 requires these checks. Run them after every restore and after
any infrastructure incident.

```sql
-- 1. Every project has at most one current result. The partial unique index
--    enforces this; more than one row means the index is missing.
select project_id, count(*) from generation_results
where is_current group by project_id having count(*) > 1;

-- 2. A current result must belong to a COMPLETED task. A row here means a
--    result was registered without a successful terminal transition.
select r.id, t.status from generation_results r
join generation_tasks t on t.id = r.task_id
where r.is_current and t.status <> 'COMPLETED';

-- 3. No task is stuck in PROCESSING with an expired lease for longer than the
--    stale threshold; task-recovery should drain this.
select id, project_id, lease_expires_at from generation_tasks
where status = 'PROCESSING' and lease_expires_at < now() - interval '15 minutes';

-- 4. Pending cleanup jobs remain available and are not stranded in PROCESSING.
select status, count(*) from storage_cleanup_jobs group by status;

-- 5. Unpublished outbox messages, and no message stuck in PROCESSING with an
--    expired lock (the dispatcher releases locks older than OUTBOX_LOCK_TIMEOUT_SECONDS).
select status, count(*) from outbox_messages group by status;
select id from outbox_messages
where status = 'PROCESSING' and locked_at < now() - interval '5 minutes';
```

Then verify the files themselves, because SQL cannot see the filesystem:

```powershell
docker cp docs/operations/verify_current_results.py mogen-api-1:/tmp/verify.py
docker compose exec -T -e PYTHONPATH=/app api python /tmp/verify.py
```

It prints `{"checked_current_results": N, "missing_or_mismatched": []}` and exits
0 when every current result is backed by a file of the recorded size. A non-empty
list means the database and file storage were restored from different points in
time; restore the matching file snapshot before exposing the project.

Finally check availability:

```powershell
curl.exe -s -o NUL -w "ready=%{http_code}`n" http://127.0.0.1:8000/health/ready
curl.exe -s -o NUL -w "frontend=%{http_code}`n" http://127.0.0.1:5173/
docker compose exec -T cleanup-worker sh -c 'celery -A app.tasks.celery_app:celery_app inspect ping -d celery@$HOSTNAME --timeout 5'
```

A restored environment is consistent when checks 1–5 return no rows, the file
check reports an empty list, the three worker pings answer, and both health
endpoints are ready.

---

## 6. Retention and cleanup

The cleanup worker deletes superseded result files (after a successful
regeneration) and pruned scene workspaces through durable `storage_cleanup_jobs`
entries. Failed jobs remain as history; inspect them with:

```sql
select id, storage_key, target_type, status, attempts, last_error
from storage_cleanup_jobs where status = 'FAILED' order by created_at desc;
```

`SCENE_WORKSPACE_RETENTION_HOURS` (default 168) bounds diagnostic workspaces;
`0` disables pruning. `/data/projects` grows only with live projects, because
project deletion schedules a `DIRECTORY` cleanup job for the whole tree.

---

## 7. Scheduling

Phase 10 ships a scheduled backup service in `compose.prod.yaml`
(`mogen-backup:1.0.0`, built from `infrastructure/backup/`). It runs one backup
immediately after the migration completes and then every
`BACKUP_INTERVAL_SECONDS` (default 86400 = daily). Each run writes:

```text
$BACKUP_HOST_DIR/<UTC timestamp>/
  database.dump     pg_dump custom-format archive
  app-data.tgz      tar.gz of /data/projects
  SHA256SUMS        checksums of both artefacts
  manifest.json     created_at, application_version, migration_revision,
                    PostgreSQL version, sizes and checksums
```

The service verifies every dump with `pg_restore --list` and every archive with
`tar -tzf` before publishing the directory, writes `.backup-heartbeat` on
success, and prunes timestamp-named directories older than
`BACKUP_RETENTION_DAYS` (default 14). Its Compose health check fails when the
heartbeat is older than two intervals.

```powershell
# Production stack; the same --env-file / -f list as the deployment.
docker compose --env-file .env.production -f compose.yaml -f compose.prod.yaml ps backup
docker compose --env-file .env.production -f compose.yaml -f compose.prod.yaml logs --tail 20 backup
# On-demand backup outside the schedule:
docker compose --env-file .env.production -f compose.yaml -f compose.prod.yaml run --rm backup --once
```

`BACKUP_HOST_DIR` is a host bind mount (default `./.backups`), outside the
Docker data root, but it is still on the same machine. Copy it to independent
storage on the same schedule (or configure a second copy step) and periodically
restore one backup into a scratch environment using Sections 2–5. A Docker
volume or a same-host directory is not a backup.

The development stack does not run the backup service; use the manual Section 2
and Section 3 procedures there, or add the production overlay to a machine that
has the required `.env.production`.
