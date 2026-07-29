# Build context MUST be the repo root (awp/), not this directory — see
# deploy/docker-compose.dev.yml's `build.context`. Depends on
# `mcps/approvals` directly (not over HTTP) — see
# `awp_gateway/routers/approvals.py`'s docstring.
FROM python:3.12-slim

WORKDIR /app

COPY shared/ shared/
COPY mcps/_base/ mcps/_base/
COPY mcps/approvals/ mcps/approvals/
COPY gateway/ gateway/
COPY config/ config/

RUN pip install --no-cache-dir './shared[otel]' ./mcps/_base ./mcps/approvals ./gateway

ENV AWP_CONFIG_DIR=/app/config

EXPOSE 8000
CMD ["uvicorn", "awp_gateway.main:app", "--host", "0.0.0.0", "--port", "8000"]
