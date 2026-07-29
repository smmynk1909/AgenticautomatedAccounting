# Build context MUST be the repo root (awp/) — see deploy/docker-compose.dev.yml.
# xhtml2pdf/openpyxl/pdfplumber/python-docx are all pure-Python (no native
# system libraries needed) — see DEVIATIONS.md #13 for why that mattered.
FROM python:3.12-slim

WORKDIR /app

COPY shared/ shared/
COPY mcps/_base/ mcps/_base/
COPY mcps/docs/ mcps/docs/
COPY config/ config/

RUN pip install --no-cache-dir './shared[otel]' ./mcps/_base ./mcps/docs

ENV AWP_CONFIG_DIR=/app/config

EXPOSE 8000
CMD ["uvicorn", "awp_mcp_docs.main:app", "--host", "0.0.0.0", "--port", "8000"]
