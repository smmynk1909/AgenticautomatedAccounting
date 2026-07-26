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

Sprints 1–4 complete and live-verified (`docs/12-SOLUTIONING-REPO.md` §5).

Sprints 1–2: shared library, DB schema + seed data, `mcp-audit`,
`mcp-approvals`, `mcp-erp` (people/assets/tickets/tasks/dashboard/policies),
and the dev Compose/Ollama stack — verified end-to-end against real Docker
(`scripts/dev_bootstrap.sh`) and real Postgres (`db/tests/test_migrations.py`,
previously Docker-skipped, now green).

Sprint 3: `agents/_base` (LangGraph runtime, checkpointing), `ORCH-0`
(intent classify/plan/validate/dispatch/reconcile), `SUP-1` (ticket intake,
routing, status freshness, SLA warden, daily reporting — weekly clustering
report deferred, see `DEVIATIONS.md`), `scheduler/` (cron dispatch + ORCH-0
DAG reconcile sweep), a minimal `mcp-comms` (notify/reminder/incident
outbox — no real email/Slack delivery yet, `DEVIATIONS.md` #10), gateway
core (REST + poll-based WS, dev-login, ticket-category RBAC), and a minimal
`web/` app (chat, tickets, approvals inbox). `HR-1`/`OPS-1`/`FIN-1`,
`fincore`, and the remaining four MCP servers are scaffolded in the tree
below but not yet implemented — see the sprint backlog in the doc.

Verified live, not just unit-tested: `make bootstrap` brings up all 12
containers (Postgres, Redis, MinIO, Ollama, 4 MCP servers, gateway, ORCH-0,
SUP-1, scheduler) with zero restarts, and a real chat message round-trips
end-to-end — gateway → Redis Streams → ORCH-0's LangGraph → real Ollama
LLM call → `mcp-erp` ticket creation → status mirrored back — the DF-1/DF-4
data flows from `docs/10-HLD.md`. This surfaced (and fixed) a number of
integration bugs no sqlite/fakeredis-backed unit test could reach —
see `DEVIATIONS.md` #11-12.

Sprint 4: `mcp-docs` (extract_text, render_pdf/docx/xlsx, store_file/
get_file over MinIO — PDF rendering via `xhtml2pdf`, not WeasyPrint,
`DEVIATIONS.md` #13), `ADM-1` (AssetKeeper device issuance/return/repair
including the `asset_high_value` approval-gate flow, RegistryKeeper people-
record stewardship, a minimal TicketHandler, DashboardComposer's first
panel — doc 03 §6's 5 acceptance tests covered at the graph level,
`DEVIATIONS.md` #14 for what's scoped down), a `GET /api/dashboard/{role}`
gateway route + a `web/` Dashboard tab, and a Playwright ticket-flow test
(`web/e2e/` — mocked gateway API, not a live-backend e2e run,
`DEVIATIONS.md` #15).

Verified live: both new containers (`mcp-docs`, `adm1`) built, joined the
running Sprint 1–3 stack, and stayed at zero restarts. Live-dispatched two
real `TaskEnvelope`s over the actual Redis bus — `dashboard_refresh`
(ADM-1 called mcp-erp's real `asset_audit_report`/`push_dashboard_item`,
numbers matched the seeded DB exactly) and `issue_device` against a real
seeded employee with no assets in stock (exercised the out-of-stock →
procurement-ticket path for real, doc 03 §6 acceptance test 3) — and
called `mcp-docs.render_pdf` over real HTTP, fetching the resulting PDF
back out of the real MinIO container to confirm it's a genuine PDF
(`%PDF-` header, non-trivial byte count). This surfaced one more
container-build-only bug (a duplicate wheel-archive entry in
`mcps/docs/pyproject.toml`, `DEVIATIONS.md` #13) that no `uv sync`/`pytest`
run on the dev host could have caught.

371 tests passing (`uv run pytest -q`), ruff + mypy strict clean across
every implemented package (`make test`).

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (`winget install Docker.DockerDesktop`)
- [Ollama](https://ollama.com/) (`winget install Ollama.Ollama`)
- [uv](https://docs.astral.sh/uv/) (`winget install astral-sh.uv`) — manages the Python 3.12 workspace venv
- Python 3.12 (uv will fetch it if missing: `uv python install 3.12`)

## Quickstart

```bash
cp .env.example .env
uv sync                                  # creates .venv with all workspace members
make up                                  # docker compose up postgres redis minio ollama mcp-audit mcp-approvals mcp-erp mcp-comms gateway
make models                              # ollama pull the model pool (serving/fetch_models.sh)
make migrate                             # alembic upgrade head
make seed                                # db/seed/generate_synthetic.py
make test                                # ruff + mypy + unit + contract tests
make web                                 # npm install + vite dev server (needs `make up`)
```

Note (`.env.example`): `POSTGRES_PORT` defaults to `5433`, not Postgres' usual
`5432` — several dev boxes have a native (non-Docker) PostgreSQL service
already bound to `5432`, which silently wins the port and makes every
host-side client (alembic, seed script, tests) authenticate against the
wrong server. Change it back to `5432` if nothing else on your machine uses
it; containers always talk to each other over the Docker network regardless.

See `Makefile` for the full target list and `scripts/dev_bootstrap.sh` for the
one-shot version of the above.

## Repository layout

Matches `docs/12-SOLUTIONING-REPO.md` §2. Top level:

```
config/     intents/gates/scopes/routing/sla/models — schema-validated at boot
shared/     awp_shared: schemas, auth, task bus, LLM client, MCP client, audit mw
db/         Alembic migrations, DDL extras, synthetic seed generator
mcps/       one FastMCP server per capability domain (_base + audit + approvals + erp + comms + docs so far)
agents/     one LangGraph runtime per agent (_base + orch0 + sup1 + adm1 so far; HR-1/OPS-1/FIN-1 not yet implemented)
fincore/    deterministic finance engine (not yet implemented)
gateway/    FastAPI + WebSocket API — chat/tasks/tickets/approvals, dev-login, RBAC
web/        React frontend — chat, tickets, approvals inbox
scheduler/  cron -> TaskEnvelope dispatch + ORCH-0 DAG reconcile sweep
serving/    Ollama model pull + gateway smoke tests
evals/      eval harness + red-team corpus (not yet implemented)
deploy/     docker-compose, backup scripts, runbooks
scripts/    dev bootstrap, one-off tooling
```
