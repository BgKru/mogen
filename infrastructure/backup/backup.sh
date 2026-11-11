#!/usr/bin/env bash
#
# Scheduled PostgreSQL + file-storage backup for the MVP (08_infrastructure.md
# Section 12, INF-AC-19, roadmap 10.3).
#
# One backup is a directory under $BACKUP_DIR:
#
#   <UTC timestamp>/
#     database.dump   pg_dump custom-format archive (pg_restore compatible)
#     app-data.tgz    tar.gz of /data/projects (uploads and current results)
#     SHA256SUMS      checksums of both artefacts
#     manifest.json   creation time, migration revision and sizes
#
# The service runs one backup immediately and then every
# BACKUP_INTERVAL_SECONDS. `--once` performs a single backup and exits, which is
# what the deployment checklist uses.
#
# A Docker volume is not a backup. BACKUP_HOST_DIR is bind-mounted from the
# host, outside the Docker data root; copy that directory off the host (or to
# independent storage) as part of the operations procedure.

set -Eeuo pipefail

BACKUP_DIR="${BACKUP_DIR:-/backups}"
STORAGE_DIR="${STORAGE_DIR:-/data}"
STORAGE_SUBDIR="${STORAGE_SUBDIR:-projects}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
INTERVAL_SECONDS="${BACKUP_INTERVAL_SECONDS:-86400}"
HEARTBEAT_FILE="${BACKUP_HEARTBEAT:-${BACKUP_DIR}/.backup-heartbeat}"

export PGHOST="${PGHOST:-db}"
export PGPORT="${PGPORT:-5432}"
export PGUSER="${PGUSER:-app}"
export PGDATABASE="${PGDATABASE:-app}"

TMP_DIR=""
cleanup() {
    if [[ -n "${TMP_DIR}" && -d "${TMP_DIR}" ]]; then
        rm -rf "${TMP_DIR}"
    fi
}
trap cleanup EXIT

log() {
    printf '%s backup %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"
}

usage() {
    cat <<'EOF'
Usage: backup.sh [--once]

Without arguments the process takes a backup every BACKUP_INTERVAL_SECONDS and
writes a heartbeat after each successful run.
EOF
}

prune_old_backups() {
    # Only timestamp-named backup directories are considered; .tmp-* leftovers
    # from a killed process are removed after one day.
    find "${BACKUP_DIR}" -mindepth 1 -maxdepth 1 -type d \
        -name '[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]T[0-9][0-9][0-9][0-9][0-9][0-9]Z' \
        -mtime "+${RETENTION_DAYS}" -exec rm -rf {} + 2>/dev/null || true
    find "${BACKUP_DIR}" -mindepth 1 -maxdepth 1 -type d \
        -name '.tmp-*' -mtime +1 -exec rm -rf {} + 2>/dev/null || true
}

run_backup() {
    local stamp tmp_dir final_dir database_sha database_bytes storage_sha
    local storage_bytes revision created_at

    mkdir -p "${BACKUP_DIR}"
    stamp="$(date -u +%Y%m%dT%H%M%SZ)"
    tmp_dir="${BACKUP_DIR}/.tmp-${stamp}"
    final_dir="${BACKUP_DIR}/${stamp}"
    TMP_DIR="${tmp_dir}"
    rm -rf "${tmp_dir}"
    mkdir -p "${tmp_dir}"

    created_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    log "started ${stamp}"

    pg_dump --format=custom --compress=9 --file "${tmp_dir}/database.dump"
    pg_restore --list "${tmp_dir}/database.dump" >/dev/null

    if [[ -d "${STORAGE_DIR}/${STORAGE_SUBDIR}" ]]; then
        tar -czf "${tmp_dir}/app-data.tgz" -C "${STORAGE_DIR}" "${STORAGE_SUBDIR}"
    else
        # A fresh deployment may not have created the directory yet.
        tar -czf "${tmp_dir}/app-data.tgz" --files-from=/dev/null
    fi
    tar -tzf "${tmp_dir}/app-data.tgz" >/dev/null

    revision="$(psql --no-psqlrc --tuples-only --no-align \
        -c 'select version_num from alembic_version' | tr -d '[:space:]')"
    if [[ -z "${revision}" ]]; then
        log "alembic_version is empty; refusing to record an unidentified schema"
        return 1
    fi

    database_sha="$(sha256sum "${tmp_dir}/database.dump" | cut -d' ' -f1)"
    storage_sha="$(sha256sum "${tmp_dir}/app-data.tgz" | cut -d' ' -f1)"
    database_bytes="$(stat -c %s "${tmp_dir}/database.dump")"
    storage_bytes="$(stat -c %s "${tmp_dir}/app-data.tgz")"

    (
        cd "${tmp_dir}"
        sha256sum database.dump app-data.tgz >SHA256SUMS
    )

    cat >"${tmp_dir}/manifest.json" <<EOF
{
  "created_at": "${created_at}",
  "application_version": "${APP_VERSION:-unknown}",
  "migration_revision": "${revision}",
  "postgres_version": "$(psql --no-psqlrc --tuples-only --no-align -c 'show server_version')",
  "database": {
    "file": "database.dump",
    "bytes": ${database_bytes},
    "sha256": "${database_sha}"
  },
  "storage": {
    "file": "app-data.tgz",
    "bytes": ${storage_bytes},
    "sha256": "${storage_sha}"
  }
}
EOF

    mv "${tmp_dir}" "${final_dir}"
    TMP_DIR=""
    printf '%s\n' "$(date +%s)" >"${HEARTBEAT_FILE}"
    log "completed ${final_dir}"
    prune_old_backups
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    usage
    exit 0
fi

if [[ "${1:-}" == "--once" ]]; then
    run_backup
    exit 0
elif [[ -n "${1:-}" ]]; then
    usage >&2
    exit 2
fi

while true; do
    if ! run_backup; then
        log "FAILED; the previous successful heartbeat is unchanged"
    fi
    sleep "${INTERVAL_SECONDS}"
done
