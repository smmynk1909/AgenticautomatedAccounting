#!/usr/bin/env bash
# Nightly backup — doc 09 §3 "Ops runbook essentials: nightly pg_dump +
# MinIO mirror + Qdrant snapshot to encrypted disk (restore drill
# quarterly)". Encryption-at-rest for the backup archive is NOT done here
# (DEVIATIONS.md #24) — this dev machine has no KMS/secrets vault to hold
# an encryption key against, same class of gap as every other "single
# trusted-developer machine" simplification (DEVIATIONS.md #2). The
# backup contents (a full pg_dump of every table, including PII) are
# exactly as sensitive as the live database — never let this directory
# leave the machine unencrypted in a real deployment.
#
# Usage: scripts/backup.sh   (from repo root, stack up via `make up`)
# Output: deploy/backups/<UTC timestamp>/{postgres.dump, minio/, qdrant/}
set -euo pipefail
cd "$(dirname "$0")/.."

# See scripts/restore_drill.sh's comment — Git Bash (MSYS) can rewrite
# POSIX-looking absolute paths (`/tmp/...`) meant for a container's own
# filesystem into host Windows paths before `docker` ever sees them.
export MSYS_NO_PATHCONV=1

if [ ! -f .env ]; then
  echo "No .env found — copy .env.example first." >&2
  exit 1
fi
set -a
# shellcheck disable=SC1091
source .env
set +a

TS=$(date -u +%Y%m%dT%H%M%SZ)
OUT_DIR="deploy/backups/${TS}"
mkdir -p "$OUT_DIR"

echo "==> Postgres: pg_dump (custom format)"
docker exec deploy-postgres-1 pg_dump -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" --format=custom \
  > "${OUT_DIR}/postgres.dump"

echo "==> MinIO: mirror bucket ${MINIO_BUCKET}"
MIRROR_TMP="/tmp/backup_mirror_${TS}"
docker exec deploy-minio-1 sh -c "
  mc alias set local http://localhost:9000 '${MINIO_ROOT_USER}' '${MINIO_ROOT_PASSWORD}' >/dev/null &&
  mc mirror --overwrite 'local/${MINIO_BUCKET}' '${MIRROR_TMP}'
"
docker cp "deploy-minio-1:${MIRROR_TMP}" "${OUT_DIR}/minio"
docker exec deploy-minio-1 rm -rf "${MIRROR_TMP}"

echo "==> Qdrant: snapshot every collection"
mkdir -p "${OUT_DIR}/qdrant"
COLLECTIONS=$(curl -sf http://localhost:6333/collections \
  | python -c "import sys,json; print(' '.join(c['name'] for c in json.load(sys.stdin)['result']['collections']))")
for c in $COLLECTIONS; do
  SNAP_NAME=$(curl -sf -X POST "http://localhost:6333/collections/${c}/snapshots" \
    | python -c "import sys,json; print(json.load(sys.stdin)['result']['name'])")
  curl -sf "http://localhost:6333/collections/${c}/snapshots/${SNAP_NAME}" \
    -o "${OUT_DIR}/qdrant/${c}__${SNAP_NAME}"
done

echo "==> Backup complete: ${OUT_DIR}"
du -sh "${OUT_DIR}" 2>/dev/null || true
