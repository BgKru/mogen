# ---------------------------------------------------------------------------
# Scheduled backup image (08_infrastructure.md Section 12, roadmap 10.3).
#
# Built from the same pinned PostgreSQL client image as the database service, so
# pg_dump/pg_restore match the server major version. The script is the only
# application content in this image; user data is mounted read-only at /data and
# the backup destination is a host bind mount at /backups.
# ---------------------------------------------------------------------------

ARG POSTGRES_IMAGE=postgres:17@sha256:748a18a54d3842d43bc156f0840d78029b8d349e0feca98c12b9c4ce3404a6b3

FROM ${POSTGRES_IMAGE}

COPY backup.sh /usr/local/bin/mogen-backup

RUN chmod 0755 /usr/local/bin/mogen-backup

ENTRYPOINT ["/usr/local/bin/mogen-backup"]
