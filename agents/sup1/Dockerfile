# Build context MUST be the repo root (awp/), not this directory — see
# deploy/docker-compose.dev.yml's `build.context`. Worker process, no HTTP
# surface — see awp_agent_sup1/main.py's docstring.
FROM python:3.12-slim

WORKDIR /app

COPY shared/ shared/
COPY mcps/_base/ mcps/_base/
COPY agents/_base/ agents/_base/
COPY agents/sup1/ agents/sup1/
COPY config/ config/

RUN pip install --no-cache-dir ./shared ./mcps/_base ./agents/_base ./agents/sup1

ENV AWP_CONFIG_DIR=/app/config

CMD ["python", "-m", "awp_agent_sup1.main"]
