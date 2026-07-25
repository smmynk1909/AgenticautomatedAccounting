# AWP — Agentic Workforce Platform

A locally hosted, multi-agent system that runs the internal operations of an IT
services company — Admin, HR, Operations, Finance, Support — on open-source
LLMs. Agents talk over a durable task bus and never touch data directly; every
capability is a scoped, audited MCP tool call. Money math is deterministic
code, never LLM generation. Human approval is a cryptographic token, not a
prompt.

Full design: [`docs/00-MASTER-ARCHITECTURE.md`](docs/00-MASTER-ARCHITECTURE.md)
and the rest of `docs/00`–`12`. Deviations this build takes from those docs
(Ollama instead of vLLM, trimmed Compose, dev-mode auth) are in
[`DEVIATIONS.md`](DEVIATIONS.md).

## Status

Sprints 1–2 of the 12-sprint plan (`docs/12-SOLUTIONING-REPO.md` §5): shared
library, DB schema + seed data, `mcp-audit`, `mcp-approvals`, `mcp-erp`
(people/assets/tickets/tasks/dashboard/policies), and the dev Compose/Ollama
stack. Everything else (ORCH-0, the department agents, the other six MCP
servers, the web app) is scaffolded in the tree below but not yet
implemented — see the sprint backlog in the doc.

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (`winget install Docker.DockerDesktop`)
- [Ollama](https://ollama.com/) (`winget install Ollama.Ollama`)
- [uv](https://docs.astral.sh/uv/) (`winget install astral-sh.uv`) — manages the Python 3.12 workspace venv
- Python 3.12 (uv will fetch it if missing: `uv python install 3.12`)

## Quickstart

```bash
cp .env.example .env
uv sync                                  # creates .venv with all workspace members
make up                                  # docker compose up postgres redis minio ollama mcp-audit mcp-approvals mcp-erp
make models                              # ollama pull the model pool (serving/fetch_models.sh)
make migrate                             # alembic upgrade head
make seed                                # db/seed/generate_synthetic.py
make test                                # ruff + mypy + unit + contract tests
```

See `Makefile` for the full target list and `scripts/dev_bootstrap.sh` for the
one-shot version of the above.

## Repository layout

Matches `docs/12-SOLUTIONING-REPO.md` §2. Top level:

```
config/     intents/gates/scopes/routing/sla/models — schema-validated at boot
shared/     awp_shared: schemas, auth, task bus, LLM client, MCP client, audit mw
db/         Alembic migrations, DDL extras, synthetic seed generator
mcps/       one FastMCP server per capability domain (_base + audit + approvals + erp so far)
agents/     one LangGraph runtime per agent (not yet implemented)
fincore/    deterministic finance engine (not yet implemented)
gateway/    FastAPI + WebSocket API (not yet implemented)
web/        React frontend (not yet implemented)
serving/    Ollama model pull + gateway smoke tests
evals/      eval harness + red-team corpus (not yet implemented)
deploy/     docker-compose, backup scripts, runbooks
scripts/    dev bootstrap, one-off tooling
```
