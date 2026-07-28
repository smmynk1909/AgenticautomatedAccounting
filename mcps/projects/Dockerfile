# Build context MUST be the repo root (awp/) — see deploy/docker-compose.dev.yml.
FROM python:3.12-slim

WORKDIR /app

COPY shared/ shared/
COPY mcps/_base/ mcps/_base/
COPY mcps/projects/ mcps/projects/
COPY config/ config/

RUN pip install --no-cache-dir ./shared ./mcps/_base ./mcps/projects

ENV AWP_CONFIG_DIR=/app/config

EXPOSE 8000
CMD ["uvicorn", "awp_mcp_projects.main:app", "--host", "0.0.0.0", "--port", "8000"]
