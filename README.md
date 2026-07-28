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

Sprints 1–6, 9, 10 complete and live-verified; Sprint 7 code/tests/config
complete and live container-verified, extraction F1 acceptance number
under investigation (`DEVIATIONS.md` #18); Sprint 8 code/tests complete,
live Docker verification pending (`DEVIATIONS.md` #19); Sprint 11 in
progress — Keycloak swap-in for human auth done and live-verified
(`DEVIATIONS.md` #22), its other six pieces (observability, backup/
restore, red-team, load test, payroll shadow cycles, runbooks) not yet
started (`docs/12-SOLUTIONING-REPO.md` §5).

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
`web/` app (chat, tickets, approvals inbox).

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

Sprint 5: `fincore` (top-level, LLM-free — `payroll.py`/`tax.py`/`ledger.py`/
`invoice.py`/`depreciation.py`/`reconcile.py`/`cashflow.py`, doc 06's prime
directive "the LLM never computes money") and `mcp-finance` (the ~20 doc 08
§2 tools wrapping it: post_journal/get_trial_balance/get_ledger/get_pnl/
get_balance_sheet/close_period/reopen_period, payroll run/compute/
disbursement, invoice compute/issue with gapless numbering, TDS projection/
regime comparison/GST worksheet/advance-tax estimate, bank reconciliation,
depreciation, 13-week cashflow — `DEVIATIONS.md` #16 for what's scoped
down, including several tools that take source data as direct input rather
than reaching into other services, matching the "no MCP server calls
another MCP server" convention). `fincore`: 56 tests, **100% source
coverage**, hypothesis property tests for the ledger balance invariant
(1000 fuzzed examples), payroll LOP monotonicity, round-half-up rounding,
and regime-comparison consistency. `HR-1`/`OPS-1` and the remaining three
MCP servers (`mcp-hrsourcing`, `mcp-search`, `mcp-projects`) are
scaffolded in the tree below but not yet implemented — see the sprint
backlog in the doc.

Verified live: `mcp-finance` built and joined the running stack at zero
restarts. This is the first sprint where the dev Postgres already had the
affected migration (`0004_finance`) applied from Sprint 1 with the
now-fixed-in-source `pg.UUID` columns — live-verified by actually posting
a real journal entry through `mcp-finance.post_journal` against the real
container, which surfaced two more real bugs no unit test could reach (a
stale `UUID`-typed PL/pgSQL variable in the balance-check trigger function,
and — caught by `test_compute_payroll_accumulates_tds_across_months` before
it ever reached Docker — a wrong JSON field path that silently zeroed out
month-over-month TDS accumulation). Both fixed; the live database was
patched to match (`DEVIATIONS.md` #16), and a real post_journal call now
both succeeds when balanced and is rejected by the same Postgres trigger
when it isn't.

Sprint 6: `FIN-1` (doc 06 — payroll run/reissue, expense bookkeeping,
month-close, invoice creation, tax worksheets, financial-requirement
projection, all as approval-gated LangGraph flows reusing the ADM-1-
style optimistic-call/`ApprovalRequiredError`/resume pattern), the doc
06 §7.1 shadow-diff harness (`scripts/shadow_diff.py` — tested against
synthetic fixtures; no real manual-payroll data exists yet to validate
against, that's a Sprint 11 gate), and a `GET /api/payroll/runs/{month}`
gateway route + `web/` Payroll tab. Per-employee compensation is derived
from `salary_bands` (grade → band midpoint, 50/20/30 basic/HRA/special
split) as a stand-in for real `comp_structures` decryption, which doesn't
exist yet anywhere in the codebase — a user-confirmed simplification,
`DEVIATIONS.md` #17. A new `finance.get_payroll_run` tool (not in doc 08
§2's original list) was added once both slip-reissue and the payroll UI
turned out to need one.

Verified live: `fin1` built and joined the running stack at zero
restarts. Dispatched a real `run_payroll` task for month `2026-07` over
the Redis bus — processed all 40 real seeded employees end-to-end
through real `fincore` tax math (`gross=3,550,000.00`,
`net=3,045,911.20`, `tds=424,088.80`), rendered all 40 salary slip PDFs
via `mcp-docs` (fetched one back from MinIO and confirmed it's a genuine
1-page PDF, not just a nonzero byte count), and requested a real 2-
approver `payroll_run` gate confirmed via a direct Postgres query. A
`compute_tax` dispatch completed with no error. This surfaced a real FY-
scoping bug in month-over-month TDS accumulation, caught by a purpose-
built regression test before it ever reached Docker — see `DEVIATIONS.md`
#17.

527 tests passing (`uv run pytest -q`), ruff + mypy strict clean across
every implemented package (`make test`).

Sprint 7: `mcp-search` (search_kb hybrid retrieval, search_candidates,
Qdrant-backed vectors + embed/cluster), `mcp-hrsourcing` (extract_resume via
pdfplumber, normalize_profile via M-SMALL guided-JSON extraction into
`CandidateProfile`, skill_normalize), and HR-1's Sourcer/ResumeAuditor/
Shortlister (`source_candidates`, `audit_resume`, `shortlist_role` — the
last gated on `shortlist_publish`, same optimistic-call/resume pattern as
every other gated flow in this build). External sourcing connectors and
the RoleProfile human-confirm step are scoped down — `DEVIATIONS.md` #18.

Verified live: all three new containers (`mcp-search`, `mcp-hrsourcing`,
`hr1`) plus `qdrant` built and joined the running stack at zero restarts.
The doc 04 §5.1 acceptance test (extraction F1 ≥ 0.92 on a 50-resume
labeled set, `scripts/resume_extraction_eval.py`) surfaced a real
CPU-inference timeout bug (fixed — `DEVIATIONS.md` #18) and, once that was
fixed, a genuine extraction-quality shortfall that has not yet been root-
caused: early live results are far below the ≥0.92 bar. Flagged, not
hidden — see `DEVIATIONS.md` #18 for the specifics gathered so far.

Sprint 8: HR-1's NegotiationDesk (`prepare_negotiation` — deterministic
`open`/`target`/`walk_away` off `salary_bands`, an LLM-drafted recruiter
talk track, and an optional candidate-facing email draft gated on
`offer_communication`) and TrainingPlanner (`plan_training` — presence-
based skill-gap report vs. the employee's current role, matched against
`training_catalog` via `search_kb`, gated on `training_plan`), plus
`output_filter.py` (doc 09 §4.3's confidential-field denylist, checked in
code before any candidate-facing draft reaches the approval gate). Chat-
assist counter-offer negotiation, level-based/next-grade skill gaps, the
quarterly training cron, and HR-1f TicketHandler remain out of scope —
`DEVIATIONS.md` #19.

Both doc 04 §5 acceptance tests named for this sprint are asserted directly:
test 3 (a band-ceiling number in a draft is blocked by the output filter)
in `agents/hr1/awp_agent_hr1/tests/test_output_filter.py`, and test 4
(masked-cohort shortlist parity) in
`agents/hr1/awp_agent_hr1/tests/test_bias_suite.py` — the latter runs the
real `shortlister.rank_candidates` code against two cohorts identical on
every scored dimension and differing only by name, proving parity holds
structurally rather than by assertion. Live Docker verification (a real
`prepare_negotiation`/`plan_training` dispatch over the Redis bus) is
pending — `DEVIATIONS.md` #19.

615 tests passing, ruff + mypy strict clean across every implemented
package.

Sprint 9: `mcp-erp` gained `tools_projects.py` (projects/milestones/
allocations/work_logs CRUD — deliberately dumb, no business logic), a new
`mcp-projects` server (delivery-issue tracking; repo indexing/CodeAssist
tools are Sprint 10), and OPS-1's WorkTracker (`assign_employee_project`,
gated on `allocation_change`), ProjectMonitor (`project_health_report` —
deterministic burn/schedule variance + milestone-at-risk, an LLM-drafted
narrative constrained to restate only computed facts, and an S1
delivery-issue auto-escalation to Director on an overdue invoice-triggering
milestone), and DeliveryRisk (`timeline_risk_scan`'s timeline radar). The
scheduler gained fan-out support (`jobs.yaml`'s new `fan_out` field) so
`project_health_report_weekly` can dispatch one task per active project —
closing a gap `jobs.yaml` had flagged since Sprint 1. Migration 0005's
`pg.UUID` columns (flagged but not yet fixed since Sprint 1 — DEVIATIONS.md
#11) were fixed as part of building the first real Core mirror against
them; a live, already-running dev database needed a separate forward
migration (`0012`) rather than a destructive downgrade — DEVIATIONS.md #20.

Verified live: `mcp-projects` and `ops1` joined the running stack at zero
restarts. Created a real project/milestone/issue via `mcp-erp`/
`mcp-projects`, then dispatched real `project_health_report` and
`timeline_risk_scan` tasks over the Redis bus to the real `ops1` container.
This surfaced (and fixed) a real bug no unit test had caught: MCP tool
responses carry dates as JSON strings, not Python `date` objects, and
OPS-1 is the first agent in this codebase to do date *arithmetic* on one —
see DEVIATIONS.md #20. After the fix, both tasks completed for real (the
health report took ~5.5 minutes — M-GEN narrative generation on this
host's slow CPU inference, DEVIATIONS.md #18) and published real dashboard
items with correctly-cited numbers.

670 tests passing, ruff + mypy strict clean across every implemented
package.

Sprint 10: `mcp-projects` gained Gitea-backed repo tools (`list_repos`,
`get_file`, `get_diff`, `index_repo`, `ci_status` — `search_code` is
deliberately not implemented, doc 08 §8/`DEVIATIONS.md` #21), a
`secrets_scan` tool (regex-based credential detection + redaction) and
`suggest_patch` (a stored patch artifact for human application, never a
direct commit — new `patch_artifacts` table, migration `0013_codeassist`,
also adds `projects.repo_slug`). OPS-1 gained CodeAssist
(`code_assist_session` — chat/review/generate/explain/refactor modes,
per-project ACL via the existing `allocations` table, `output_filter`-style
secrets-scan-before-context enforcement) and the gateway gained an
OpenAI-compatible `POST /v1/chat/completions` IDE endpoint (doc 05 §2.4 —
so IDE plugins like Continue can point at it directly), dispatching through
the normal task-bus path but polling to a synchronous HTTP response since
IDE clients expect one. `DEVIATIONS.md` #21 covers what's scoped down
(external CI, streaming responses, real per-engineer session identity).

Verified live: `mcp-projects` and `ops1` rebuilt and rejoined the running
stack; a real `code_assist_session` chat-mode task was dispatched over the
Redis bus against a real seeded Gitea repo (`awp-admin/awp-sample-svc`,
`scripts/gitea_bootstrap.sh`) — `index_repo` pulled real file content from
Gitea, `mcp-search.upsert_documents`/`search_kb` round-tripped it through a
real Qdrant collection, and the agent's M-CODE (`qwen2.5-coder:7b-instruct`)
call returned a real, correctly-grounded answer citing the seeded
`mathutils.py` code (task `b85bede9-...`). The ACL-leakage acceptance test
(doc 05 §5.5) was also live-dispatched: an employee with no allocation to
the project got a zero-context `FAILED` result before any repo call was
made. `review` mode was also live-dispatched against a diff containing a
seeded fake AWS key — its `guided_json` structured output took
considerably longer than chat mode's free-text generation (constrained
decoding is visibly more expensive on this host's CPU-only Ollama), but
returned a correct `CodeReview` flagging the hardcoded credential by
category without the raw key ever appearing in the response, proving the
secrets-scan-before-model-call ordering held for real. This surfaced and
fixed two real bugs — a Qdrant collection-naming bug and an M-CODE
cold-load timeout issue, both in `DEVIATIONS.md` #21 — and one new
deviation (Docker Desktop's port-forwarding intermittently drops
long-held HTTP connections to the new IDE endpoint on this host,
`DEVIATIONS.md` #21).

711 tests passing, ruff + mypy strict clean across every implemented
package.

Sprint 11 (in progress — doc 12 §5's hardening sprint spans roughly seven
independent sub-builds; only the first is done so far): Keycloak swap-in
for human auth. `deploy/keycloak/realm-export.json` (roles matching
`config/dev_users.yaml`, 9 dev users, a confidential `awp-gateway` client)
imports into a new `keycloak` service; `verify_jwt` now branches on JWT
header `alg` (`RS256` validates against a live, cached Keycloak JWKS;
`HS256` keeps the existing local-secret path for agent service tokens,
unchanged per doc 11 §1.2); the gateway gained a real Authorization
Code + PKCE flow (`GET /api/auth/login` / `GET /api/auth/callback`),
alongside — not yet replacing — the existing dev-login route
(`DEVIATIONS.md` #22 explains why both coexist for now).

Verified live: a full Authorization Code + PKCE login, scripted end to
end with `curl` (real Keycloak login page, real credential POST, real
redirect chain) against the real running stack, produced a real Keycloak
access token; that exact token was accepted by the *actual running
gateway container's* `verify_jwt` and, sent as a real bearer token,
returned a real `200` with real computed payroll data from
`GET /api/payroll/runs/2026-07` — the whole chain (Keycloak issues a
token → gateway exchanges it → `verify_jwt` validates it against the live
JWKS → gateway RBAC accepts the principal) proven end to end, not just
per-component. This surfaced and fixed two real bugs — a `VERIFY_PROFILE`
required-action block (the realm export was missing `email`/`firstName`/
`lastName` per user) and an issuer-mismatch bug (`KEYCLOAK_URL` was doing
double duty as both the gateway's own network address for calling
Keycloak *and* the string validated against a token's `iss` claim, which
turned out to be two genuinely different values behind Docker) — both in
`DEVIATIONS.md` #22.

725 tests passing, ruff + mypy strict clean across every implemented
package.

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
mcps/       one FastMCP server per capability domain (_base + audit + approvals + erp + comms + docs + finance so far)
agents/     one LangGraph runtime per agent (_base + orch0 + sup1 + adm1 + fin1 so far; HR-1/OPS-1 not yet implemented)
fincore/    deterministic finance engine — payroll/tax/ledger/invoice/depreciation/reconcile/cashflow
gateway/    FastAPI + WebSocket API — chat/tasks/tickets/approvals, dev-login, RBAC
web/        React frontend — chat, tickets, approvals inbox
scheduler/  cron -> TaskEnvelope dispatch + ORCH-0 DAG reconcile sweep
serving/    Ollama model pull + gateway smoke tests
evals/      eval harness + red-team corpus (not yet implemented)
deploy/     docker-compose, backup scripts, runbooks
scripts/    dev bootstrap, one-off tooling
```
