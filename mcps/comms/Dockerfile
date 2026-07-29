# Build context MUST be the repo root (awp/), not this directory — see
# deploy/docker-compose.dev.yml's `build.context`. Each local package is
# `pip install`-ed non-editably, in dependency order; awp_shared.config
# resolves config/ via $AWP_CONFIG_DIR (see DEVIATIONS.md #7), not by
# guessing a path relative to its own (now site-packages) location.
FROM python:3.12-slim

WORKDIR /app

COPY shared/ shared/
COPY mcps/_base/ mcps/_base/
COPY mcps/comms/ mcps/comms/
COPY config/ config/

RUN pip install --no-cache-dir './shared[otel]' ./mcps/_base ./mcps/comms

ENV AWP_CONFIG_DIR=/app/config

EXPOSE 8000
CMD ["uvicorn", "awp_mcp_comms.main:app", "--host", "0.0.0.0", "--port", "8000"]
