#!/usr/bin/env bash
# One-shot Gitea bootstrap for mcp-projects (Sprint 10, doc 08 §8/doc 10's
# C12 dependency) — creates the dev admin user + API token mcp-projects
# authenticates with, and one seed repo (`awp-sample-svc`) for CodeAssist
# live verification. Idempotent: safe to re-run, skips whatever's already
# done. Requires `gitea` already up (`make up` / `docker compose up gitea`).
set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo "No .env found — copying .env.example. Review it before continuing." >&2
  cp .env.example .env
fi

set -a
# shellcheck disable=SC1091
source .env
set +a

ADMIN_USER=${GITEA_ADMIN_USER:-awp-admin}
ADMIN_PASSWORD=${GITEA_ADMIN_PASSWORD:-dev-only-change-me-32bytes-min}
ADMIN_EMAIL=${GITEA_ADMIN_EMAIL:-admin@awp.local}
TOKEN_NAME=mcp-projects
GITEA_URL=${GITEA_URL:-http://localhost:3000}
SEED_REPO=awp-sample-svc

echo "==> waiting for gitea health"
until curl -sf "$GITEA_URL/api/healthz" >/dev/null 2>&1; do sleep 2; done

CID=$(docker compose -f deploy/docker-compose.dev.yml --env-file .env ps -q gitea)
if [ -z "$CID" ]; then
  echo "gitea container not found — is 'make up' running?" >&2
  exit 1
fi

if ! docker exec -u git "$CID" gitea admin user list | grep -q " $ADMIN_USER "; then
  echo "==> creating gitea admin user '$ADMIN_USER'"
  docker exec -u git "$CID" gitea admin user create \
    --username "$ADMIN_USER" --password "$ADMIN_PASSWORD" --email "$ADMIN_EMAIL" \
    --admin --must-change-password=false
fi

if grep -q "^GITEA_ADMIN_TOKEN=" .env 2>/dev/null; then
  TOKEN=$(grep "^GITEA_ADMIN_TOKEN=" .env | cut -d= -f2-)
else
  echo "==> generating gitea API token"
  TOKEN=$(docker exec -u git "$CID" gitea admin user generate-access-token \
    --username "$ADMIN_USER" --token-name "$TOKEN_NAME" \
    --scopes "write:repository,write:issue,read:repository,read:issue,read:user,write:user" \
    | sed -n 's/.*successfully created: //p')
  if [ -z "$TOKEN" ]; then
    echo "failed to generate a gitea access token" >&2
    exit 1
  fi
  echo "GITEA_ADMIN_TOKEN=$TOKEN" >> .env
  echo "==> wrote GITEA_ADMIN_TOKEN to .env"
fi

echo "==> ensuring seed repo '$SEED_REPO' exists"
if ! curl -sf -H "Authorization: token $TOKEN" \
    "$GITEA_URL/api/v1/repos/$ADMIN_USER/$SEED_REPO" >/dev/null 2>&1; then
  curl -sf -X POST -H "Authorization: token $TOKEN" -H "Content-Type: application/json" \
    -d "{\"name\":\"$SEED_REPO\",\"description\":\"seed repo for CodeAssist live verification\",\"private\":false,\"auto_init\":true}" \
    "$GITEA_URL/api/v1/user/repos" >/dev/null

  echo "==> seeding files into '$SEED_REPO'"
  while IFS= read -r -d '' file; do
    rel="${file#scripts/gitea_seed/}"
    content_b64=$(base64 -w0 "$file")
    curl -sf -X POST -H "Authorization: token $TOKEN" -H "Content-Type: application/json" \
      -d "{\"content\":\"$content_b64\",\"message\":\"seed: add $rel\",\"branch\":\"main\"}" \
      "$GITEA_URL/api/v1/repos/$ADMIN_USER/$SEED_REPO/contents/$rel" >/dev/null
  done < <(find scripts/gitea_seed -type f -print0)
fi

echo "Gitea bootstrap complete. GITEA_ADMIN_TOKEN is in .env."
