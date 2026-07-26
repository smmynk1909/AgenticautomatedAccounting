# Deviations from `docs/00`–`12`

Tracked so later sprints know exactly what to swap back when the "real"
infra becomes available, and why each shortcut is safe to take.

## 1. Model serving: Ollama instead of vLLM

Docs 00 §6/7, 01, 09 §3 specify vLLM (Linux+NVIDIA, AWQ quantization) behind
an nginx `model-gw`. This machine has no NVIDIA/Linux serving box, so
`serving/` targets **Ollama's OpenAI-compatible endpoint**
(`http://localhost:11434/v1`) directly — no nginx gateway container, Ollama
already multiplexes models by name over one port.

- `shared/awp_shared/llm.py` implements the exact `LLM` class contract from
  doc 11 §1.4 (`chat(messages, tools, guided_json, ...)`). Only the
  `base_url` and how `guided_json` is turned into a constraint differ
  internally (Ollama `format: json_schema` vs. vLLM `guided_json`). No
  caller code changes when vLLM is introduced later — swap `config/models.yaml`
  base URLs and the internal branch in `llm.py`.
- Model pool (`config/models.yaml`): `qwen2.5:7b-instruct` (M-GEN),
  `qwen2.5:3b-instruct` (M-SMALL), `qwen2.5-coder:7b-instruct` (M-CODE,
  pulled at Sprint 9/10), `bge-m3` (M-EMB, pulled at Sprint 7 when Qdrant
  lands). Sampling defaults unchanged from doc 01 §3.
- Ollama's tool-calling and `guided_json`/structured-output support is
  weaker than vLLM's `guided_decoding-backend outlines`. `llm.py` always
  does the repair-round-on-invalid-JSON dance from doc 11 §5.4 regardless of
  backend, so this is a quality risk to watch in evals (doc 09 §6), not a
  contract risk.

## 2. Auth: dev JWT instead of Keycloak

Docs 00 §7, 09 §4, 10 (AD-none but implied), 11 §1.2 specify Keycloak OIDC
for both human sessions and agent service-account JWTs, with `verify_jwt`
checking a JWKS endpoint.

Until Sprint 11 (hardening) stands up Keycloak, `shared/awp_shared/auth.py`:

- `verify_jwt` checks signature against a local HS256 secret
  (`AWP_DEV_JWT_SECRET` in `.env`) instead of fetching a JWKS.
- `mint_service_jwt(agent_id, scopes)` is unchanged — still returns a
  `Principal`-shaped JWT other code can't tell apart from a Keycloak one.
- Human principals come from `config/dev_users.yaml` (static list: id, roles)
  instead of a Keycloak realm — a `/api/dev/login` gateway route (Sprint 3)
  mints a session JWT for a chosen dev user, no password.
- **This is not safe for anything beyond a single trusted-developer machine.**
  Swapping to Keycloak later touches only `verify_jwt`'s key-source function
  and deletes `config/dev_users.yaml` / the dev-login route — no caller of
  `Principal`/`require_scopes` changes.

## 3. Trimmed Docker Compose, infra added per-sprint

`docs/09-DATA-INFRA-SECURITY.md` §3 lists one `docker-compose.yml` with every
service (Keycloak, Qdrant, Gitea, observability stack included) from day one.
This build introduces them when the sprint that needs them lands, which is
also roughly how the docs' own build sequence (doc 09 §8, doc 12 §5) is
ordered — this just makes it explicit in the compose files instead of
commenting services out:

| Compose file | Introduced | Adds |
|---|---|---|
| `deploy/docker-compose.dev.yml` | Sprint 1 | postgres, redis, minio, ollama, mcp-audit, mcp-approvals |
| same file, extended | Sprint 2 | mcp-erp |
| same file, extended | Sprint 3 (this build) | mcp-comms, gateway, orch0, sup1, scheduler (web/ runs via `make web`, not a container — no reason to containerize a Vite dev server) |
| same file, extended | Sprint 4–6 | remaining agent containers (adm1, hr1, ops1, fin1), mcp-finance, mcp-docs |
| same file, extended | Sprint 7 | qdrant, mcp-search, mcp-hrsourcing |
| same file, extended | Sprint 9 | gitea, mcp-projects |
| same file, extended | Sprint 11 | keycloak, prometheus, grafana, loki, otel-collector |

## 4. Host Python 3.14, containers pinned to 3.12

Doc 11 pins Python 3.12 for all services. Host machine has 3.14 (Windows
Store alias) and no system Python on PATH otherwise. All MCP servers, agents,
and the gateway run inside `python:3.12-slim` containers per the pin — the
host version is irrelevant to them. Local dev tooling (running tests outside
containers, `db/seed/generate_synthetic.py` ad hoc) uses a `uv`-managed 3.12
venv (`uv python install 3.12`, `uv sync` in `pyproject.toml`) so the host
Python version never actually gets used.

## 6. MCP transport: plain HTTP+JSON instead of MCP JSON-RPC/SSE

Doc 00 §7/08 §0 specify Python `mcp` SDK (FastMCP) over HTTP-SSE, JSON-RPC
2.0. That SDK's exact client/server API isn't something to guess correctly
from training knowledge alone without a live install to check against, and
getting it subtly wrong would silently break every tool call.

Instead, `shared/awp_shared/mcpc.py` (`MCP.call`) and `mcps/_base` speak
plain HTTP+JSON, one POST per tool call (`POST {server_url}/tools/{tool}`,
JSON body = args, JSON response = result or `{"error": {...}}`). Every
cross-cutting convention doc 08 §0 actually requires — bearer JWT auth,
`X-Trace-Id`/`X-Idempotency-Key` headers, the structured error envelope,
approval-token gating, audit middleware — is implemented exactly as
specified; only the wire framing differs from real MCP JSON-RPC/SSE.

`mcps/_base/awp_mcp_base/pipeline.py` (`ToolPipeline`) and `server.py`
(`AwpMcpServer`) are written transport-agnostic on purpose: tool handlers are
plain `async def handler(payload: dict, ctx: Ctx) -> dict` functions, so
swapping the HTTP adapter for a real FastMCP/SSE adapter later touches only
the adapter layer, not tool logic, scopes, gates, or tests. Flagged as a
verification item for whichever sprint first needs true MCP-protocol
interop (e.g. an off-the-shelf MCP-aware IDE client for OPS-1 CodeAssist,
doc 05 §2.4) — internal agent-to-MCP-server calls never need it.

## 7. Config directory resolution: env var, not `__file__` traversal

`awp_shared/config.py`'s `CONFIG_DIR` used to be
`Path(__file__).resolve().parents[2] / "config"` — correct only in an
editable/source checkout. The container Dockerfiles (`mcps/*/Dockerfile`,
and now `agents/*/Dockerfile`, `gateway/Dockerfile`, `scheduler/Dockerfile`)
`pip install` each package non-editably, which copies files into
site-packages and breaks that assumption silently (resolves to some
site-packages ancestor, not the repo). Fixed by checking `AWP_CONFIG_DIR`
first, falling back to the old heuristic only for local dev. Every container
sets `AWP_CONFIG_DIR=/app/config` explicitly; local `uv run`/pytest leave it
unset and get the fallback.

`awp_scheduler/jobs.py`'s `JOBS_YAML` had the exact same bug (a
`__file__`-relative path to `scheduler/jobs.yaml`) — same fix, `AWP_JOBS_YAML`
env var checked first, `scheduler/Dockerfile` sets it explicitly.

## 8. Web app: Vite dev server, not containerized

`web/` (React 18 + Vite + Tailwind per doc 12 §2) is scaffolded (Sprint 3):
chat, tickets, approvals inbox against the gateway's REST/WS API, dev-login
per DEVIATIONS.md #2. Run via `make web` (npm install + `vite dev`, proxies
`/api` and `/ws` to the gateway container at `:8000`) rather than its own
Compose service — a dev server with hot reload has no reason to run in a
container on a single-developer machine; add one only if/when this needs to
run in CI or be reachable from another machine.

## 9. Agent checkpointing: explicit save/load, not LangGraph's `BaseCheckpointSaver`

Doc 11 §2 describes `agent_checkpoints` as backing a "LangGraph checkpointer:
PostgresSaver (table `agent_checkpoints`) keyed by task_id". LangGraph's own
`BaseCheckpointSaver` protocol (`langgraph-checkpoint-postgres`) owns its own
migration-managed tables (`checkpoints`, `checkpoint_writes`,
`checkpoint_blobs`, ...) with a per-superstep write log — a different, much
larger shape than `agent_checkpoints`' single `(task_id, graph, state)` row
(doc 09 §1 / migration `0008_platform_dashboard`).

Instead, `agents/_base/awp_agent_base/checkpoint.py`'s `CheckpointStore` does
a coarser, explicit save/load: `AgentApp.handle` loads the whole `AgentState`
(pickled) before `graph.ainvoke` and saves it back after — resuming a
crashed/redelivered task from its last-saved state rather than LangGraph's
finer per-node resume. This is sufficient for the doc's actual guarantee
("crash-resume: unacked bus msg redelivered, graph resumes from last
checkpoint") because every node here is "≤ 1 LLM call" (doc 11 §2) and the
bus's own dedupe already makes redelivery idempotent-safe — there's no
in-flight multi-node transaction to protect. Revisit only if an agent graph
ever needs true mid-superstep resume (e.g. a single node spanning a very
expensive multi-step tool call) — at that point, swap `CheckpointStore` for
a real `BaseCheckpointSaver` implementation against new, LangGraph-owned
tables; `AgentApp`'s public interface (`handle(env) -> TaskResult`) doesn't
change either way.

## 10. mcp-comms: durable outbox, no real email/Slack/SMS delivery

Docs 07 §4 / 08 §1 list `mcp-comms` tools (`notify_user`, `send_reminder`,
`incident_broadcast`, plus Phase-2/3 `draft_external_email`,
`distribute_slip`, `poll_inbox`) as the department agents' one channel for
reaching humans. No actual delivery integration (SMTP, Slack webhook, SMS
gateway) exists yet — nothing in docs 00-12 specifies which one Phase 1
should use, and building against a real one prematurely would mean throwing
it away when the real choice is made.

`mcps/comms/awp_mcp_comms` (Sprint 3) implements only `notify_user`,
`send_reminder`, `incident_broadcast` — the three SUP-1 depends on
(StatusKeeper reminders, SLAWarden escalation, incident broadcast). Each
call is durably recorded to a new `comms_outbox` table (migration
`0010_comms_outbox`) instead of actually sent — same "swap the mechanism
later, keep the contract" pattern as the LLM gateway (Ollama vs vLLM) and
auth (dev JWT vs Keycloak) deviations. `draft_external_email`,
`distribute_slip`, and `poll_inbox` remain unimplemented (scopes.yaml
already marks them Sprint 3-4/Phase 2-3); swapping in a real channel later
touches only `tools_notify.py`'s `_record` helper (write-through instead of
write-only), never any caller's scope grant or tool signature.

## 11. Migration id/FK columns: `sa.String(36)`, not `pg.UUID` — check this before building a new Core mirror

Migrations 0001, 0002, 0003, 0008, 0010 originally declared every id/FK
column `pg.UUID(as_uuid=True)`. Every one of those tables' SQLAlchemy Core
mirror (`mcps/*/tables.py`, `agents/_base/awp_agent_base/tables.py`)
deliberately uses generic `sa.String(36)` instead, so the same table object
works against sqlite in unit tests too (documented in each `tables.py`'s own
header) — and every insert through that mirror serializes ids as
`str(uuid4())`, never a native UUID. A Postgres `uuid`-typed column rejects
a string parameter outright (`asyncpg.exceptions.DatatypeMismatchError`),
which is exactly what happened the first time this migration set ran
against a real Postgres (this dev box didn't have Docker until Sprint 3) —
`mcp-erp.create_ticket`, `dispatch_task`, and `AgentApp`'s own checkpoint
save all failed in turn until each column was fixed. sqlite-based unit
tests never caught this (sqlite doesn't enforce column types), and
`db/seed/generate_synthetic.py` reflects the live schema rather than using
any `tables.py` import, so it never exercised the mismatch either.

**Fixed**: 0001 (departments/skills_master/salary_bands/roles/candidates/
employees/comp_structures), 0002 (assets/asset_assignments), 0003
(tickets/ticket_events/orchestrator_tasks), 0008 (dashboard_items/
kb_documents/agent_checkpoints), 0010 (comms_outbox).

**Not yet fixed — still `pg.UUID` in 0004 (finance), 0005 (projects/work),
0006 (training)**: these tables have no `tables.py` Core mirror anywhere in
the codebase yet (no mcp-finance, mcp-projects, or mcp-hrsourcing built —
Sprint 5+/7+/9+), so there's nothing to conflict with today. Whoever builds
that mirror should default to `sa.String(36)` to match the established
convention and check the migration matches *before* writing tools against
it, rather than rediscovering this the same way.

## 12. Live end-to-end verification findings (Sprint 3): the first real DF-1 run

Once ORCH-0/SUP-1/scheduler actually ran as containers against real
Postgres/Redis/Ollama and the gateway dispatched a real chat message all the
way through (`POST /api/chat/ORCH-0` -> bus -> ORCH-0's LangGraph -> real
LLM -> `mcp-erp.create_ticket` -> status mirrored back), several more
latent bugs surfaced that no sqlite/fakeredis/`dispatch_raw`-based unit test
could have caught — every one of these is a "first real integration"
finding, not a design change:

- **`mcps/_base/awp_mcp_base/asgi.py`'s `call_tool` didn't JSON-encode raw
  dict results.** Every test calls `AwpMcpServer.dispatch_raw(...)` directly
  (Python objects in, Python objects out — no serialization needed), never
  through this ASGI layer. Any tool returning a raw DB row containing a
  `datetime`/`Decimal`/`UUID` value (e.g. `get_task_status`, `get_ticket`)
  crashed with `TypeError: Object of type datetime is not JSON serializable`
  the first time it was ever called over real HTTP. Fixed with
  `fastapi.encoders.jsonable_encoder`.
- **`awp_shared/bus.py`'s `make_redis` never set `socket_timeout`.**
  redis-py's default client-side socket timeout races
  `XREADGROUP ... BLOCK <ms>`'s server-side timeout and raises a spurious
  `redis.exceptions.TimeoutError` on every "no new messages" poll —
  crash-looping ORCH-0/SUP-1 (both call `TaskBus.consume`) continuously.
  `fakeredis` doesn't model real socket timeouts, so no unit test ever hit
  this. Fixed two ways: `socket_timeout=None` on the client, and
  `TaskBus.consume`'s loop now catches `TimeoutError`/`ConnectionError`
  around the blocking read and retries after a short backoff instead of
  propagating (defense in depth — a long-running bus consumer must survive
  a transient hiccup, not crash-loop over it).
- **`scheduler/awp_scheduler/main.py`'s tick loop had the same shape of
  bug**: an unhandled exception from `_tick` (e.g. mcp-erp briefly
  unreachable mid-restart) crash-looped the whole scheduler process instead
  of logging and retrying next minute. Fixed the same way — catch, log,
  continue.
- **`AgentApp` had no way to reflect a graph-level crash back onto the
  caller's own durable state.** `make_respond_node` (ORCH-0) only updates
  `orchestrator_tasks.status` when the graph actually *reaches* the respond
  node — but a crash before that (e.g. every LLM retry exhausted) returns a
  `FAILED` `TaskResult` from `AgentApp.handle` that nothing ever persists;
  the row stays `"pending"` forever even though the bus correctly ack'd the
  message as handled. Fixed by adding an `on_result` hook to `AgentApp`
  (called with every `TaskResult` it produces — success, crash, or
  missing-result — best-effort, never re-raises); both `agents/orch0` and
  `agents/sup1` wire it to `erp.update_task`.
- **ORCH-0/SUP-1's own JWT `SCOPES` lists in `main.py` were missing
  `erp.tasks.write`** (needed for `update_task`) — silently swallowed by
  the (now-removed) blanket exception handler that used to guard the
  status-mirroring call, so this had been failing since the call was first
  added and nothing surfaced it until the new `on_result` hook's own
  (non-silent) warning log exposed it.
- **CPU-only LLM inference (no GPU, DEVIATIONS.md #1) is genuinely slow**:
  ~30-35s for ORCH-0's classify/plan calls (full intent list + system
  prompt) on first request, faster once the model is warm in RAM. `LLM`'s
  60s default `timeout_s` was tight enough to force a needless retry on the
  very first real request. `agents/orch0` and `agents/sup1`'s `main.py` now
  construct their `LLM` client with `timeout_s=180`.
- **Nothing above was found by review** — every one of them required
  actually running the full stack (`docker compose up`, a real chat
  message, watching container logs/restart counts) to surface. Consistent
  with this project's own standing practice (see `awp_build_status.md`
  memory / this file's git history): trust real runs over static review for
  anything touching infra, serialization, or process lifecycle.

## 13. mcp-docs PDF rendering: `xhtml2pdf` instead of WeasyPrint

Doc 08 §3 doesn't mandate a specific PDF library, but WeasyPrint is the
obvious default for Jinja2-HTML-to-PDF and was tried first. It requires
native GTK/Pango/Cairo shared libraries (`libgobject-2.0-0` etc.) that
aren't present on Windows without a separate GTK3 runtime install —
confirmed empirically, not assumed: `HTML(string="<h1>test</h1>").write_pdf(...)`
raised `OSError: cannot load library 'libgobject-2.0-0'` on this dev
machine. The container would have these libraries (a `python:3.12-slim`
base doesn't, but they could be `apt-get install`ed), so this could have
been "works in Docker, silently broken on host" instead of a hard
incompatibility — either way, a second native dependency for one MCP
server wasn't worth it.

Switched to `xhtml2pdf` (pure Python, same Jinja2-renders-HTML-then-PDF
contract — `render_pdf` in `mcps/docs/awp_mcp_docs/tools_render.py` just
calls `xhtml2pdf.pisa.CreatePDF(html, dest=buf)` instead of
`HTML(string=html).write_pdf(...)`). Verified working on Windows before
committing to it as a dependency. Trade-off: xhtml2pdf's CSS support is
noticeably weaker than WeasyPrint's (older/partial flexbox, no CSS grid) —
fine for doc 08 §3's simple table-based forms (`issuance_form_v1`); would
need revisiting if a future template needs richer layout.

`python-docx`, `openpyxl`, `pdfplumber`, and `minio` were all also
verified to install and import cleanly on Windows (`uv run --with <pkg>
python -c "import <pkg>"`) before being added to
`mcps/docs/pyproject.toml` — no other native-library surprises found.

mcp-docs has no Postgres table (doc 12 §2's tree lists none for it) —
`store_file`'s `scope` (a list of role names, or the literal `"public"`)
is round-tripped as MinIO object metadata instead
(`mcps/docs/awp_mcp_docs/storage.py`), since there's nowhere else for it
to live between a `store_file` and a later `get_file` call. Test coverage
uses an in-memory `FakeMinio` stand-in
(`mcps/docs/awp_mcp_docs/tests/fake_minio.py`), not a real MinIO
server — same pattern as sqlite-for-Postgres / fakeredis-for-Redis
elsewhere in the test suite. One non-obvious wrinkle worth flagging for
whoever next writes a MinIO fake: real MinIO/S3 echoes user metadata back
from `stat_object`/`get_object` prefixed with `x-amz-meta-`, so a fake
that stores keys verbatim (`"awp-scope"` instead of
`"x-amz-meta-awp-scope"`) makes every metadata lookup silently miss and
fall through to defaults — this exact bug briefly made the scope-check
test pass for the wrong reason (`get_file` always resolved scope as
`"public"`, so the deny-path assertion never actually exercised the
deny path) until the fake was fixed to prefix keys on write.

**Found only by `docker compose build` (Sprint 4 live verification), not by
`uv sync`/`pytest`**: `mcps/docs/pyproject.toml`'s `[tool.hatch.build.
targets.wheel]` had both `packages = ["awp_mcp_docs"]` (which already
picks up `templates/` — it's a subdirectory of the package) *and* a
`force-include` entry for the same path. `uv sync`'s local build absorbed
the duplicate silently on this Windows dev machine; a fresh `pip install`
in the Linux container image hard-failed with hatchling's "A second file
is being added to the wheel archive at the same path" the first time the
image was actually built. Fixed by dropping the redundant `force-include`
— `packages` alone is sufficient. Another entry for the running list of
"this needed a real build/run to surface, not review."

## 14. ADM-1 (doc 03): approval-resume trigger, RegistryKeeper's merge path, and other scoped-down leaves

`agents/adm1` is the first agent whose own graph nodes call a 🔒-gated
`mcp-erp` tool (`assign_asset` for `issue_device`, `upsert_employee` for
`update_employee_record`) — ORCH-0 only sets `requires_approval` on the
sub-tasks *it dispatches*, and SUP-1 has no gated intents at all, so
neither exercised this path before. A few real gaps and scoping decisions
came out of building it:

- **Who re-triggers a paused approval flow isn't wired yet.** `nodes.py`'s
  gated nodes call the ERP tool optimistically (no `approval_token`); on
  `ApprovalRequiredError` they call `approvals.request_approval`, stash
  what's needed to finish (`reservation_id`/`employee_record`,
  `approval_id`) into `state["scratch"]`, and return
  `TaskStatus.AWAITING_APPROVAL`. `graph.py`'s entry routing correctly
  resumes from there — a re-invoked task with
  `scratch["awaiting_approval_for"]` set routes straight to the matching
  `check_*_approval` node instead of re-running the intent node (which
  would re-reserve the asset / re-submit the record). What's missing is the
  *trigger*: `gateway/awp_gateway/routers/approvals.py`'s `approve_endpoint`
  calls `service.approve()` and returns the token to the human's browser,
  but nothing re-dispatches a `TaskEnvelope` with the same `task_id` back
  onto the bus so `AgentApp.handle` reloads the checkpoint and the graph
  actually resumes. Every resume-path node above is written and
  graph-level tested directly (`tests/test_graph_acceptance.py`,
  `tests/test_nodes.py` construct the post-approval state by hand) — this
  is a real, separate integration task (gateway approve route -> re-dispatch),
  not something ADM-1 itself is missing.
- **`awp_agent_base/nodes.py`'s `make_check_approval_node` never captured
  the approval token.** It recorded `approval_status` from
  `get_approval_status`'s response but dropped the `token` field entirely
  — harmless while nothing used it (no agent had a gated flow yet), but it
  would have silently stranded every future gated flow at "approved" with
  no way to actually finish. Fixed by also setting
  `state["scratch"]["approval_token"]` when present; ADM-1's own
  `check_issue_device_approval`/`check_update_employee_approval` nodes
  don't reuse this shared node as-is (they need to finalize with the token,
  not just record status), but the fix benefits any future agent that does.
- **Duplicate-candidate handling doesn't call `propose_merge`.**
  `mcp-erp.upsert_candidate` already refuses to insert on a detected
  duplicate (`ConflictError` with match evidence, doc 08 §1) — that's the
  actual "zero silent overwrites" enforcement, not something ADM-1 adds.
  But `propose_merge` merges two *existing* candidate rows; the just-rejected
  new candidate never got an id, so it structurally doesn't fit that tool.
  `registry.py`'s `add_candidate_record` path instead pushes a
  `registry`-panel dashboard item with the match evidence for an admin to
  review — the "merge proposal, human confirms" artifact doc 03 §6 test 2
  asks for, just not literally a `propose_merge` call.
- **DashboardComposer ships one panel (asset register), not the full
  Executive Action Dashboard.** The CEO/Director/Manager panel sets in doc
  03 §2.4 (payroll-due flags, delivery risk, headcount vs plan, pending
  device-acknowledgment count) depend on FIN-1/OPS-1's own
  `push_dashboard_item` calls (neither agent exists yet) and, for
  acknowledgments specifically, a query tool that doesn't exist either — no
  `mcp-erp` tool exposes "assets issued but not yet acknowledged" across
  assets (`get_asset`'s `history` is per-asset only). No LLM call was added
  for this one panel either: doc 03 §4 rule 1 reserves the LLM for
  summarizing/prioritizing *across* panels, and there's only one so far —
  same reasoning SUP-1's Reporter used to skip its own weekly-report LLM
  step (doc 07 §3.5).
- **TicketHandler classifies off `summary_current`, not a full ticket
  body.** `mcp-erp`'s `tickets` table has no `body`/`subject` column at all
  (`mcps/erp/awp_mcp_erp/tables.py`) — `create_ticket` only ever persists a
  120-char `summary_current` derived from what it's given. This is an
  existing schema gap from Sprint 2, not something introduced here; a
  future sprint that needs the original text back needs a schema change,
  not a workaround in `tickets.py`.
- **`resolve_admin_ticket` is a new intent** (`config/intents.yaml`,
  `ResolveAdminTicketIn` in `shared/awp_shared/intent_models.py`) added so
  TicketHandler is reachable and testable as a real graph node rather than
  dead code — doc 03 doesn't name it, but §2.3's ticket-resolution workflow
  needs *some* dispatch shape, and nothing currently auto-routes a
  SUP-1-created `category=device` ticket into it (that real-time
  ticket-fabric-to-ADM-1 wiring is out of scope for this build, same as the
  approval-resume trigger above).
- **RAG playbook lookup (doc 03 §2.3's "check playbook") is deferred.** No
  `mcp-search` exists yet (Sprint 7) to search SOPs against — same
  deferral SUP-1's Reporter took for its own RAG-shaped step (doc 07 §3.5).

## 15. web/'s Playwright test mocks the gateway API instead of running against a live stack

Doc 12 §5's Sprint 4 line item is "Playwright ticket flow." `web/e2e/
ticket-flow.spec.ts` drives a real Chromium browser through the actual
React app (dev login -> Tickets tab -> create ticket -> see it in the
list, plus an error-path test), but `page.route()` intercepts every
`/api/*` call instead of hitting a running gateway/Postgres/Redis stack.

Reasoning: doc 11 §10's testing pyramid already has a dedicated e2e tier
(compose-up, DF-1..5, k6 load) that's explicitly deferred pending a real
test runner for it (`README.md`'s Status section, `Makefile`'s `eval`
placeholder) — building *that* just to satisfy "Playwright ticket flow"
would mean every `web-e2e` run needs the full Docker stack up, turning a
UI-wiring check into a second `make bootstrap`. What this test actually
verifies — does the DevLogin -> Tickets flow call the right endpoints with
the right bodies and render what comes back, including the error path —
doesn't need a real backend to verify, only a real browser. `make
web-e2e` installs Chromium (`npx playwright install --with-deps chromium`)
and runs `npm run test:e2e`; `playwright.config.ts` starts its own `vite
dev` server, so this doesn't need `make up` first. If/when the real
compose-up e2e tier gets built, this test stays as the fast UI-contract
check underneath it, not a replacement for it.

## 16. Sprint 5 — fincore + mcp-finance

`fincore/` (top-level, doc 12 §2's tree — not under `mcps/`, no Postgres
access, no LLM) implements payroll/tax/ledger/invoice/depreciation/
reconciliation/cashflow as pure functions over frozen dataclasses
(`fincore/fincore/models.py`), matching doc 06's prime directive ("the LLM
never computes money"). `mcps/finance` wraps it as the ~20 doc 08 §2 tools
against the real `accounts`/`journal_entries`/`journal_lines`/... tables
from `db/migrations/versions/0004_finance.py`.

**Found live, not by any test — a second real bug in migration 0004,
distinct from the UUID/String(36) convention fix below**: `0004_finance`'s
`check_journal_balance()` trigger function declared its `v_entry_id`
local variable as `UUID`. Fixing `journal_lines.entry_id` from `pg.UUID`
to `sa.String(36)` (see next paragraph) left that PL/pgSQL variable
declaration stale — comparing a `varchar` column against a `uuid`-typed
variable fails with `operator does not exist: character varying = uuid`
**at COMMIT time** (the trigger is `DEFERRABLE INITIALLY DEFERRED`), which
surfaces as a bare "Internal Server Error" with no structured `AwpError`
envelope — the exception happens after `dispatch()`'s own try/except
window, during the session commit. No sqlite-backed unit test could ever
catch this (sqlite doesn't run Postgres trigger functions at all); only
found by an actual `post_journal` call against the real Postgres container
inside `docker compose up`. Fixed in the migration source
(`v_entry_id VARCHAR(36)`) and applied to the already-migrated dev
database by hand (`ALTER FUNCTION` + the column-type `ALTER TABLE`s below,
inside one transaction with the two affected foreign keys dropped and
re-added around them, since Postgres won't let an FK constraint span
mismatched column types even transiently).

**`db/migrations/versions/0004_finance.py`'s id/FK columns were still
`pg.UUID`** (DEVIATIONS.md #11 already flagged this file specifically:
"whoever builds that mirror should default to `sa.String(36)`... rather
than rediscovering this the same way" — this is that rediscovery, now
done). Fixed the same way as 0001/0002/0003/0006/0008: `sa.String(36)` in
both the migration and `mcps/finance/awp_mcp_finance/tables.py`'s Core
mirror. Unlike those earlier fixes (which only ever needed to apply to a
*fresh* migration run, since nothing had used those tables yet), this dev
Postgres already had 0004 applied with the old types from Sprint 1 — a
full `alembic downgrade`+`upgrade` cycle would have cascaded through
0005-0010 and dropped tables three other running containers actively use
(`agent_checkpoints`, `dashboard_items`, `comms_outbox`, ...), so the live
database was patched surgically instead (`ALTER TABLE ... ALTER COLUMN ...
TYPE varchar(36) USING ...::text`, scoped to only the finance tables) —
verified afterward with a real `post_journal` call that both posts
successfully *and* still gets rejected when unbalanced (the whole point of
the trigger).

**mcp-finance calls no other MCP server** (same architectural convention
observed everywhere else in this build — only agents/gateway call MCP
servers, never server-to-server). This shapes several tools:
- `freeze_payroll_inputs`/`run_depreciation`/`reconcile_bank`/
  `cashflow_model` all take their source data (employee comp/attendance,
  asset register, bank statement lines, AR/AP/payroll projections) as
  direct tool input rather than fetching it from `mcp-erp`/`mcp-docs`
  themselves — gathering that data across services is FIN-1's job
  (Sprint 6), not built yet.
- `generate_disbursement_file` returns its CSV content as base64 directly
  instead of a MinIO URI — vaulting it via `mcp-docs.store_file` is the
  calling agent's job.
- Doc 11 §6.1's payroll sequence names two different ids
  (`freeze_payroll_inputs` -> `snapshot_id`, `compute_payroll` ->
  `register_id`), implying a separate snapshot store, but doc 09 §1's
  actual schema has only one finance table for this (`payroll_runs`, no
  `payroll_snapshots`). `snapshot_id` and `register_id` are the same
  identifier (one `payroll_runs` row's `id`) at two lifecycle stages, not
  two different rows — see `tools_payroll.py`'s docstring.

**Found by a real test, not review**: `PayrollRunRepo.
tds_deducted_so_far_by_emp` read `register["lines"]`, but the stored JSON
shape is `{"snapshot": {...}, "computed": {"lines": [...]}}` — the lines
are nested under `"computed"`, not top-level. This meant every month's
payroll computation saw "zero TDS deducted so far" regardless of prior
months, silently breaking the "spread the *remaining* annual liability
over the *remaining* months" logic doc 06 §2.1 step 2 describes (every
month would have recomputed as if it were the first). Caught by
`test_tools_payroll.py::test_compute_payroll_accumulates_tds_across_months`,
which asserts May's and June's TDS deduction differ correctly once May's
is accounted for — it initially failed with June computing the same
figure as if May had never run. Fixed the field path.

**Other scope reductions, each documented at the point they're made**:
`gst_worksheet`/`advance_tax_estimate` (`tools_tax.py`) produce an
account-level liability/credit summary and a flat-rate estimate, not a
filing-ready return or a real FPnA-forecast-driven figure — doc 06 §2.4
itself scopes tax output to "worksheets... reviewed by the company's human
accountant," and the real cashflow-forecast input doesn't exist until
FPnA does (later sprint). `fincore/tables.py` treats PF/ESI/PT/GST/TDS
tables as single current versions (not date-ranged like `it_slabs_*.yaml`)
even though doc 09's `tax_tables` schema models every `kind` as
independently versioned — a scope reduction, not a bug, since IT slabs are
what genuinely changes and matters most for correctness.

Two DB-backed repo classes were written and then deleted before landing
(`ExpenseRepo`, `RecurringExpenseRepo`) — built to match `db/migrations/
versions/0004_finance.py`'s `expenses`/`recurring_expenses` tables, but no
doc 08 §2 tool actually exposes expense-intake or recurring-expense
lookups yet (that's FIN-1 Bookkeeper's job, Sprint 6); the tables stay in
`tables.py` (mirroring the real schema is still correct), but the
speculative repo code for them didn't ship.

Added the `recon_confirm` gate to `config/gates.yaml` — doc 08 §2 names it
on `confirm_matches` ("🔒recon_confirm (human)") but it was never actually
registered in Sprint 1's gate table.

371 -> 472 tests passing (fincore: 56, 100% source coverage; mcp-finance:
45, ~92%). `fincore`'s coverage figure is the one doc 12 §5's Sprint 5 DoD
("property/golden 95% cov; ledger fuzz invariant") names directly.

## 17. Sprint 6 — FIN-1 (doc 06), payroll shadow diff (doc 06 §7.1), payroll UI

**Compensation source: `salary_bands` proxy, not `comp_structures`.**
`RunPayrollIn`'s payload is only `{month}` — doc 06's payroll flow expects
each employee's basic/HRA/special breakdown to come from somewhere, but
`mcp-erp`'s real per-employee table for this, `comp_structures`, stores
`components_encrypted` (`LargeBinary`) and no decrypt utility exists
anywhere in the codebase (not built in any sprint so far). Rather than
block FIN-1 entirely or build encryption infra out-of-scope, this was
raised to the user directly (three options: build a minimal decrypt path,
skip compensation breakdown and pay flat gross, or use `salary_bands` —
grade -> band midpoint — as a stand-in). The user chose the `salary_bands`
proxy: `agents/fin1/awp_agent_fin1/payroll_flow.py`'s
`build_comp_snapshot_row` calls `erp.query_policies(domain=salary_bands,
grade=...)` and splits the band's `mid` 50% basic / 20% HRA / 30% special
(falls back to a flat 600000 annual if no band matches the employee's
grade). This is a real simplification with real consequences — computed
gross/TDS won't match any actual comp letter until `comp_structures`
decryption is built — and should be swapped out the moment that infra
exists; nothing else in the payroll flow depends on the proxy shape, so
the swap is localized to this one function.

**`finance.get_payroll_run` — a new tool, not in doc 08 §2's original
list.** Two needs surfaced only once payroll flows were actually being
built: `generate_salary_slips` (re-issuing slips for an already-computed
month) and the payroll UI (`web/src/pages/Payroll.tsx`) both need to read
back an already-computed register, and no doc 08 §2 tool does that
(`compute_payroll` computes-and-returns but nothing re-fetches). Added
`get_payroll_run(month)` returning `{register_id, month, status,
register}` where `register` is the `computed` half of the stored JSON
(the `snapshot` half — pre-computation inputs — is intentionally not
exposed here, since nothing external needs it). Scoped under the existing
`finance.read` permission, no new scope needed.

**`SalaryBandRepo.query` and `query_policies`'s `salary_bands` domain are
also new** — `mcp-erp` had the `salary_bands` table (doc 09) and a repo
class for other uses, but no `query_policies` domain branch exposed it to
callers before FIN-1 needed to read bands by grade.

**Found by a real test, not review**: `PayrollRunRepo.
tds_deducted_so_far_by_emp`'s FY-scoping filter only checked `month >=
before_month: continue`, with no lower bound — meaning a payroll run from
a *different, later* financial year would still be treated as "prior
months of this FY" if its month string happened to sort before
`before_month` in isolation. Fixed to bound by both `fy_start_month <=
month < before_month`. Caught alongside the `register["lines"]` vs
`register["computed"]["lines"]` nesting bug (same function — see #16)
by `test_compute_payroll_accumulates_tds_across_months`.

**`anomaly.py`'s anomaly checks are sanity-only, not month-over-month.**
`flag_anomalies` currently flags `net <= 0` and `tds/gross > 0.50` per
line — real anomaly detection (this month's gross/net vs last month's,
per doc 06 §2.1) needs a prior register to diff against. It was written
before `get_payroll_run` existed; now that the tool exists, a real
month-over-month comparison is straightforward to add but wasn't — out of
scope for closing out this sprint, left as a documented follow-up rather
than silently claimed as done.

**`scripts/shadow_diff.py` — the doc 06 §7.1 harness exists and is
tested, but has never been run against real manual-payroll data.** There
is no manual/legacy payroll export to diff against yet in this build (no
prior system being replaced) — that comparison is Sprint 11's live gate,
per doc 12 §5. The comparator itself (`compare(computed_lines,
manual_lines)` -> `ShadowDiffReport`) is fully unit-tested (clean match,
paisa-level mismatch, missing-employee-both-directions, malformed-line
raise) against synthetic fixtures, and its CLI entry point works — but
"the harness runs" and "the harness has validated real payroll" are two
different claims, and only the first is true today.

**No attendance/LOP data source exists**, so `freeze_payroll_inputs` is
always called with an empty attendance list — every employee's `lop_days`
is implicitly zero this sprint. Confirmed live: the 40-employee payroll
run's totals show `'lop': '0.00'`. Building attendance intake is out of
scope for Sprint 6 (not named in doc 12 §5's Sprint 6 DoD).

**`fpna.py`'s cashflow projection is a flat-rate estimate, not a real
forecast model.** `project_weekly_flows` derives a constant weekly outflow
from `finance.get_pnl`'s expense total divided by 4.33 and assumes zero
inflow (deliberately conservative) — doc 06 §2.5 scopes FPnA's financial
requirement analysis to feeding `finance.cashflow_model` a reasonable
opening balance and burn rate, not building a full forecasting model; a
real model is a plausible later-sprint upgrade, not a Sprint 6 DoD item.

**`create_invoice`'s contract/billing-terms corpus doesn't exist.**
`biller.build_invoice_lines` takes line items directly as input rather
than deriving them from a contract document (no contract corpus has been
built in any sprint so far) — matches the same "no data source built yet"
pattern as attendance/LOP above.

**Live end-to-end verification (real Docker stack, real Postgres, real
MinIO, no mocks)**: dispatched a real `run_payroll` task for month
`2026-07` over the Redis bus to the real `fin1` container. It processed
all 40 real seeded employees, resolved comp via the `salary_bands` proxy,
computed a full register via real `fincore` tax math
(`gross=3,550,000.00`, `net=3,045,911.20`, `tds=424,088.80`,
`pf=72,000.00`, `pt=8,000.00`, `esi=0.00`, `lop=0.00`), rendered all 40
salary slip PDFs via `mcp-docs` and confirmed each is a genuine
non-corrupt PDF (fetched one back from MinIO — `PDF document, version
1.4, 1 page(s)`, not just a nonzero byte count), and requested a real
`payroll_run` approval (`status=pending`, `approver_roles=[finance_head,
director]`, `n_required=2` — matching `config/gates.yaml`) confirmed via
a direct Postgres query. A separate `compute_tax` dispatch (regime
comparison, no persisted output to read back) completed with no error.
The approval-resume half of `run_payroll` (approving the gate, then
confirming `generate_disbursement_file` + `post_journal` + `notify_user`
fire on resume) was not live-dispatched this sprint — the resume
mechanism itself (conditional entry routing off `scratch
["awaiting_approval_for"]`) is structurally identical to the pattern
already live-verified for ADM-1 in Sprint 4, not new code being proven
for the first time.

472 -> 527 tests passing (mcp-erp +1, mcp-docs +2, mcp-finance +3,
`agents/fin1`: 41 new, `scripts/shadow_diff`: 4 new).
