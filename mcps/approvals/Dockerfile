# Build context MUST be the repo root (awp/) — see deploy/docker-compose.dev.yml.
FROM python:3.12-slim

WORKDIR /app

COPY shared/ shared/
COPY mcps/_base/ mcps/_base/
COPY mcps/approvals/ mcps/approvals/
COPY config/ config/

RUN pip install --no-cache-dir './shared[otel]' ./mcps/_base ./mcps/approvals

ENV AWP_CONFIG_DIR=/app/config

EXPOSE 8000
CMD ["uvicorn", "awp_mcp_approvals.main:app", "--host", "0.0.0.0", "--port", "8000"]
