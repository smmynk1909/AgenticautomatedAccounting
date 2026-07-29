# Build context MUST be the repo root (awp/) — see deploy/docker-compose.dev.yml.
FROM python:3.12-slim

WORKDIR /app

COPY shared/ shared/
COPY fincore/ fincore/
COPY mcps/_base/ mcps/_base/
COPY mcps/finance/ mcps/finance/
COPY config/ config/

RUN pip install --no-cache-dir './shared[otel]' ./fincore ./mcps/_base ./mcps/finance

ENV AWP_CONFIG_DIR=/app/config

EXPOSE 8000
CMD ["uvicorn", "awp_mcp_finance.main:app", "--host", "0.0.0.0", "--port", "8000"]
