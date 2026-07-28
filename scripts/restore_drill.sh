#!/usr/bin/env bash
# Restore drill — doc 10 §6 NFR: "Durability: RPO 24h (nightly backup),
# RTO 4h — quarterly restore drill." Restores the most recent (or a named)
# `scripts/backup.sh` Postgres dump into a throwaway container on its own
# name/volume — never touches the real dev database — and verifies real
# seeded data round-trips correctly. This is the Postgres leg only:
# MinIO/Qdrant restore verification is a documented follow-up
# (DEVIATIONS.md #24) — their backups are captured by backup.sh, just not
# restore-drilled yet.
#
# Usage: scripts/restore_drill.sh [path/to/deploy/backups/<timestamp>]
#   (defaults to the most recent backup under deploy/backups/)
set -euo pipefail
cd "$(dirname "$0")/.."

# Git Bash (MSYS) auto-rewrites POSIX-looking absolute-path arguments
# (`/tmp/...`) into Windows paths before they ever reach `docker`, which
# silently breaks any container-internal path passed to `docker exec` —
# live-verified: `pg_restore` failed looking for
# `C:/Users/.../AppData/Local/Temp/restore.dump` instead of the
# container's own `/tmp/restore.dump`. `MSYS_NO_PATHCONV=1` disables that
# rewrite for this script. Harmless on native Linux/macOS bash (the var is
# simply unused there).
export MSYS_NO_PATHCONV=1

set -a
# shellcheck disable=SC1091
source .env
set +a

BACKUP_DIR="${1:-$(ls -d deploy/backups/*/ 2>/dev/null | sort | tail -1)}"
if [ -z "$BACKUP_DIR" ]; then
  echo "No backup found under deploy/backups/ — run scripts/backup.sh first." >&2
  exit 1
fi
DUMP_FILE="${BACKUP_DIR%/}/postgres.dump"
if [ ! -f "$DUMP_FILE" ]; then
  echo "No postgres.dump in ${BACKUP_DIR}" >&2
  exit 1
fi

echo "==> Restore drill using ${DUMP_FILE}"
START=$(date +%s)

DRILL_CONTAINER=pg-restore-drill
docker rm -f "$DRILL_CONTAINER" >/dev/null 2>&1 || true
docker run -d --name "$DRILL_CONTAINER" \
  -e POSTGRES_DB="${POSTGRES_DB}" \
  -e POSTGRES_USER="${POSTGRES_USER}" \
  -e POSTGRES_PASSWORD="${POSTGRES_PASSWORD}" \
  postgres:16 >/dev/null

echo "==> waiting for drill Postgres to accept connections"
until docker exec "$DRILL_CONTAINER" pg_isready -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" >/dev/null 2>&1; do
  sleep 1
done

echo "==> pg_restore"
docker cp "$DUMP_FILE" "${DRILL_CONTAINER}:/tmp/restore.dump"
docker exec "$DRILL_CONTAINER" pg_restore -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" /tmp/restore.dump

echo "==> verifying restored data"
COUNTS=$(docker exec "$DRILL_CONTAINER" psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -t -A -c "
select 'employees=' || count(*) from employees
union all select 'tickets=' || count(*) from tickets
union all select 'journal_entries=' || count(*) from journal_entries
union all select 'projects=' || count(*) from projects;
")
echo "$COUNTS"

END=$(date +%s)
ELAPSED=$((END - START))
echo "==> restore completed in ${ELAPSED}s (RTO budget: 4h / 14400s)"

docker rm -f "$DRILL_CONTAINER" >/dev/null
echo "==> drill container removed, live dev database was never touched"

if echo "$COUNTS" | grep -q "=0$"; then
  echo "FAIL: at least one table restored empty" >&2
  exit 1
fi
echo "PASS"
