# Build context MUST be the repo root (awp/), not this directory — see
# deploy/docker-compose.dev.yml's `build.context`. Worker process, no HTTP
# surface. Depends on `agents/orch0` directly for `reconcile.py`/
# `IntentRegistry` (same shared-registry reasoning as awp_agent_orch0
# itself), not over HTTP.
FROM python:3.12-slim

WORKDIR /app

COPY shared/ shared/
COPY mcps/_base/ mcps/_base/
COPY agents/_base/ agents/_base/
COPY agents/orch0/ agents/orch0/
COPY scheduler/ scheduler/
COPY config/ config/

RUN pip install --no-cache-dir './shared[otel]' ./mcps/_base ./agents/_base ./agents/orch0 ./scheduler

ENV AWP_CONFIG_DIR=/app/config
ENV AWP_JOBS_YAML=/app/scheduler/jobs.yaml

CMD ["python", "-m", "awp_scheduler.main"]
