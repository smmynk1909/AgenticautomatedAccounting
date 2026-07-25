#!/usr/bin/env bash
# One-shot local bring-up: compose up -> migrate -> seed -> smoke.
# Mirrors `make bootstrap`. Requires Docker Desktop, Ollama, and uv already
# installed (see README.md Prerequisites) and `.env` copied from `.env.example`.
set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo "No .env found — copying .env.example. Review it before continuing." >&2
  cp .env.example .env
fi

echo "==> uv sync"
uv sync

echo "==> docker compose up"
docker compose -f deploy/docker-compose.dev.yml --env-file .env up -d

echo "==> waiting for postgres/redis health checks"
for svc in postgres redis; do
  until [ "$(docker compose -f deploy/docker-compose.dev.yml --env-file .env ps -q "$svc" | xargs docker inspect -f '{{.State.Health.Status}}' 2>/dev/null)" = "healthy" ]; do
    sleep 2
  done
done

echo "==> alembic upgrade head"
uv run alembic -c db/alembic.ini upgrade head

echo "==> seeding synthetic data"
uv run python db/seed/generate_synthetic.py

echo "==> pulling model pool"
bash serving/fetch_models.sh

echo "==> model-gateway smoke test"
uv run python serving/smoke/test_toolcall.py

echo "Bootstrap complete."
