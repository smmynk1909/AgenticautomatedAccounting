# Build context MUST be the repo root (awp/) — see deploy/docker-compose.dev.yml.
FROM python:3.12-slim

WORKDIR /app

COPY shared/ shared/
COPY mcps/_base/ mcps/_base/
COPY mcps/hrsourcing/ mcps/hrsourcing/
COPY config/ config/

RUN pip install --no-cache-dir ./shared ./mcps/_base ./mcps/hrsourcing

ENV AWP_CONFIG_DIR=/app/config

EXPOSE 8000
CMD ["uvicorn", "awp_mcp_hrsourcing.main:app", "--host", "0.0.0.0", "--port", "8000"]
