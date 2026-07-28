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

## 18. Sprint 7 — mcp-search + mcp-hrsourcing + HR-1 (audit, shortlist)

**External sourcing connectors (doc 04 §2.1 step 3) not built.** The doc
itself marks external job-board connectors "Phase 3" — `sourcer.py`'s
`search_internal_pool` only exercises `mcp-search.search_candidates`
(internal DB), matching doc 12 §5's Sprint 7 DoD (04§5.1-2), which needs
only the internal path live. `mcps/hrsourcing/awp_mcp_hrsourcing/sources.py`
exists as a stub for the connector interface, not a working connector.

**RoleProfile "recruiter confirms once per role" isn't approval-gated.**
Doc 04 §2.1 describes a human touchpoint here; no gate is registered for it
in `gates.yaml` (unlike every other HITL step this build implements), so
`sourcer.get_or_build_role_profile` parses-and-caches automatically on
first use. Same class of scoped-down human-confirmation step as ADM-1's
RegistryKeeper merge path (#14) — raised here rather than silently assumed.

**mcp-search's `qdrant` container ships no `curl`/`wget`/`nc`**, so it has
no Docker healthcheck; dependents (`mcp-search`, indirectly `hr1`) use
`condition: service_started` like `ollama` does, and `mcp-search` retries
Qdrant collection creation on boot rather than assuming the port is open
the instant the container starts.

**`serving/fetch_models.sh` had `bge-m3` (M-EMB) commented out** with a
"Sprint 7" marker from when the model pool list was written ahead of the
sprint that needed it — uncommented as part of actually landing Sprint 7,
not a new decision.

**Extraction F1 acceptance test (doc 04 §5.1): live-verification found a
real quality problem, not yet root-caused as of this writing.**
`scripts/resume_extraction_eval.py` initially failed on infrastructure
grounds — `mcp-hrsourcing`'s internal `LLM` client used the 60s default
timeout, too short for this host's measured CPU-inference throughput
(~1.45 tok/s under this WSL2/Docker Desktop setup, no GPU passthrough) —
fixed by raising `mcp-hrsourcing/main.py`'s `LLM(timeout_s=...)` to 600 and
the eval script's own `MCP(timeout_s=...)` to 1500. With that infra issue
resolved, `normalize_profile` calls do complete and return 200 OK, but the
extracted `CandidateProfile` JSON has near-zero field overlap with ground
truth on most of the labeled set (sampled early results: F1 0.000 on the
large majority of the first 24/50 resumes, a couple at 0.333) — nowhere
near the ≥0.92 bar. This is a live-verified finding, not a hypothesis, but
the root cause (prompt, `guided_json`/Ollama structured-output interaction,
or a genuine capability ceiling for `qwen2.5:3b-instruct` on this task) has
not yet been diagnosed. Sprint 7's code, config, and unit test suite (587
passing at the time of this entry) are otherwise complete and were live
container-verified (all Sprint 7 services start and respond cleanly); the
acceptance *number* itself is the open item, tracked here rather than
claimed as passing.

## 19. Sprint 8 — HR-1 (negotiation, training) + output_filter + bias suite

**`prepare_negotiation`'s candidate-facing draft path isn't a separate
intent.** Doc 04 §2.4 describes two things under NegotiationDesk: building
the `NegotiationPack` (its own step, `gate: null` in `intents.yaml`) and a
"chat-assist mode" where a recruiter pastes a candidate's counter-offer
into an ongoing conversation and the agent responds within band, escalating
to Director if the counter exceeds it. No intent for this chat-assist loop
exists in `config/intents.yaml`, and doc 12 §7's build instructions forbid
inventing intents not already in docs/config. Rather than leave the
`offer_communication` gate and the output filter — the two things doc 12
§5's S8 line and doc 04 §5's acceptance test 3 actually name — unbuilt,
`prepare_negotiation`'s existing payload gained two optional fields
(`draft_email: bool`, `offer_terms: dict`): when set, the same task also
drafts a candidate email, runs it through `output_filter.check_draft`, and
if clean, gates it on `offer_communication` before recording the frozen
text via `mcp-comms.draft_external_email`. The full multi-turn "recruiter
pastes counter, agent replies, escalates past band" chat loop is not built
— that needs an interactive session mechanism no agent in this codebase
has yet (OPS-1's `code_assist_session`, Sprint 10, is the closest analog
and isn't built either). A follow-up doc PR naming an explicit intent for
the chat-assist loop would remove this gap cleanly.

**`training.py`'s skill-gap analysis is presence-based and current-role-only,
not level-based or current+next-grade.** doc 04 §2.5 step 1 asks for
`current_level`/`target_level` and "current+next-grade role" comparison.
No proficiency-level data exists anywhere in this schema — `employees.skills`
and `CandidateProfile.skills_normalized` are both plain name lists, doc 09
§1's DDL sketch has no per-skill level column — so `current_level` is
"present"/"absent", not a level. "Next-grade role" needs a career-ladder
table (which `role_id` is the next grade up from a given one) that doesn't
exist; gap analysis compares only against the employee's current role.
Both are "the data model doesn't exist yet" deferrals, the same pattern as
`fpna.py`'s flat-rate forecast (#17) and the missing contract corpus (#17).

**`search_kb` doesn't pass through per-chunk metadata**, so
`training.match_training_plan`'s course/hours/cost fields default to a
generic fallback (course name = the chunk's first 80 chars, hours=8,
cost=0) rather than being read from whatever `upsert_documents` metadata a
real `training_catalog` corpus entry would carry. `doc 08 §4` doesn't list
a `metadata` field on `search_kb`'s hit shape either — extending it is a
follow-up doc PR, not a Sprint 8 code bug.

**Quarterly scheduled training runs (doc 04 §2.5: "Quarterly (scheduled) +
on-demand per manager") are not wired into `scheduler/jobs.yaml`.** Only
the on-demand path (`plan_training` intent, one employee at a time) is
built — doc 12 §5's S8 DoD names the acceptance tests (04§5.3-4), not the
cron wiring, and no sprint in the 12-sprint table revisits HR-1 after S8 to
claim it later either.

**HR-1f TicketHandler remains completely unscoped** — doc 12 §5's sprint
table has no entry for it anywhere from S1 through S12; `graph.py`'s
`_route_entry` still raises `ValidationError` for any HR-category ticket
intent (there isn't even a payload model or intent name registered for
one). Not a Sprint 8 gap specifically — flagged here since Sprint 8 was the
last opportunity in the doc's own plan to name it and didn't.

**No `market_intel`/`training_catalog` corpus data has been seeded** into
`mcp-search` (`upsert_documents` has never been called for either corpus in
any sprint, including this one) — `negotiation.py`'s market benchmark and
`training.py`'s market-demand scoring both correctly degrade to "unknown"/
zero rather than fabricating a citation, per doc 04's "market claims
require a citation ... otherwise say unknown" rule, but this means neither
path has been exercised against real corpus hits, only the empty-corpus
branch. Seeding a synthetic `market_intel`/`training_catalog` corpus (same
spirit as `db/seed/generate_synthetic.py`) is a reasonable follow-up, not
done here.

**Live Docker verification not yet performed for Sprint 8** — code is
complete, mypy/ruff clean, and the full unit/graph-level test suite passes
(including the two doc-named acceptance tests: output-filter block on a
band-ceiling leak, and masked-cohort shortlist parity), but a real
`prepare_negotiation`/`plan_training` task has not been dispatched over the
live Redis bus to the real `hr1` container the way Sprint 4-6's flows were.
Deferred pending the CPU-inference throughput issue noted in #18 — every
live path here also needs a real M-GEN call (talk track, candidate email
draft), and that call is the same slow path already under investigation.
(Update from Sprint 9's live verification below: a real M-GEN call *does*
complete on this host, just slowly — ~5.5 minutes for one short narrative.
The throughput issue is a real inconvenience for live verification and
production latency, not a hard blocker. Sprint 8's own live dispatch is
still not done as of this writing, just less alarming than it looked.)

## 20. Sprint 9 — mcp-projects + OPS-1 (tracker, monitor, risk)

**Migration 0005 (`projects`/`milestones`/`allocations`/`work_logs`) still
had `pg.UUID` columns — exactly the item DEVIATIONS.md #11 named as
"check this before building a new Core mirror".** Fixed in place (same
"edit the migration file directly" approach as 0001-0003, since these four
tables had never been written to by any tool in any sprint — nothing to
lose). **The live dev database was a different story**: it's been running
continuously since Sprint 1-8's verification and holds real data in
tables 0005-0010 touch, so downgrading past 0005 to re-apply it (the
naive fix) would have discarded that. Instead, a new forward-only
migration (`0012_fix_projects_work_uuid.py`) `ALTER COLUMN ... TYPE
VARCHAR(36)` on the four affected tables, applied once to reconcile the
live database — a fresh `alembic upgrade head` from empty never runs its
body (0005 already creates the columns correctly). Hit and fixed live: the
first real attempt at this ALTER failed —
`milestones_project_id_fkey cannot be implemented: uuid and character
varying` — Postgres won't retype a referenced PK column while an FK still
references it with the old type; the migration drops the three
`project_id` FKs first, alters every column, then recreates them.

**A new, previously-unhit wire-serialization bug**: `mcpc.MCP.call`
returns a plain `dict[str, Any]` from `r.json()` — a `sa.Date()` column
comes back from any MCP tool as an ISO string, not a real `date` object.
Every prior sprint's agent code happened to never do date *arithmetic* on
an MCP response field (dates were stored, displayed, or passed straight
through, never compared), so this was never hit before OPS-1's
`milestones_at_risk`/`overdue_milestones`/`timeline_radar` (all doing
`due - today` or `due < today`). Live-verified failure on the first real
dispatch: `'<' not supported between instances of 'str' and
'datetime.date'`. Fixed with `nodes.py`'s `_coerce_milestone_dates`,
applied at both call sites (`project_health_report`, `timeline_risk_scan`)
— and the graph-level tests were rewritten to pass ISO strings (matching
what the wire actually carries) instead of `date` objects, since the
original date-object versions of those tests could never have caught this.

**Milestone-at-risk has no "linked tasks" data source.** Doc 05 §2.2's
rule is "due within 14d & <70% linked tasks done" — this schema has no
task-per-milestone linkage anywhere (`orchestrator_tasks` tracks
agent-execution tasks, not project deliverables, and no sprint has built
one for actual delivery work items). `projectmonitor.milestones_at_risk`
is due-date + status only. The doc 05 §5.2-equivalent acceptance bar
("precision >= 0.8 on historical backtest set") has no historical dataset
to backtest against either (same "no data source built yet" pattern as
every other backtest-needing acceptance test in this build, e.g. Sprint
7's F1 harness) — proven against synthetic fixtures instead
(`tests/test_projectmonitor.py`), not a real precision number.

**Timeline radar only uses milestone due dates** (plus the already-real
`milestones.invoice_trigger` column for impact weighting) — doc 05 §2.3
also names contract-renewal dates and compliance/report deadlines as
radar sources, neither of which has a field anywhere in this schema.

**No skill-match check on `assign_employee_project`.** Doc 05 §2.1: "check
availability & skill match (skills_master vs project needs)" —
`worktracker.check_allocation_conflict` only checks capacity (%
overlap); `projects` has no skill-requirements field in this schema (doc
09 §1's DDL sketch doesn't give it one either), so there's nothing to
match against.

**No cross-functional ticket creation on S1 escalation.** Doc 05 §2.3:
"creates a SUP-1 cross-functional ticket if another department is needed
(e.g., FIN-1 for invoice hold, HR-1 for emergency staffing)" — the
department-needed heuristic isn't specified precisely enough to build
without guessing at business rules the doc doesn't state, and doc 12 §5's
S9 DoD (05§5.1-2,4) doesn't name it. The Director-notification +
dashboard-flag half of S1 escalation (acceptance test 4) is implemented
and live-verified.

**Scheduler fan-out**: `project_health_report_weekly` needed one
`TaskEnvelope` per *currently active* project, which the scheduler had no
mechanism for (every prior job was a single fixed or computed payload) —
`jobs.py`'s `JobSpec` gained an optional `fan_out` field (mutually
exclusive with `payload_fn`) naming an async resolver in the new
`awp_scheduler/fanout.py`; `dispatcher.dispatch_due_jobs` dispatches one
envelope per payload the resolver returns. This is exactly the capability
gap `jobs.yaml`'s own header comment had flagged since Sprint 1 ("no MCP
tool exposes that yet ... revisit once that capability exists") —
resolved once `mcp-erp.query_projects` existed, not a new idea.

**Live end-to-end verification (real Docker stack, real Postgres, real
Redis, real Ollama, no mocks)**: created a real project + overdue
milestone + delivery issue via `mcp-erp`/`mcp-projects` directly, then
dispatched a real `project_health_report` task over the Redis bus to the
real `ops1` container. First attempt crash-looped on the wire-
serialization bug above (caught, fixed, rebuilt); second attempt
completed in ~5.5 minutes (M-GEN narrative generation on this host's slow
CPU inference — see #18/#19), publishing a real `project_health` dashboard
item with `severity=critical` and a narrative that correctly cited the
computed budget/schedule variance numbers with no fabricated claims
(satisfying "0 uncited commitments" by construction, per `narrative.py`'s
design) — though the narrative's own opening sentence ("currently on
track with no risks identified") contradicted the correctly-cited +100%
schedule variance later in the same paragraph, a model coherence
limitation, not a pipeline defect. A `timeline_risk_scan` dispatch (no
LLM call) completed in ~3 seconds. The `assign_employee_project` gated
flow and the S1-escalation branch specifically were not live-dispatched
this sprint (both are graph-tested, and every MCP call the escalation
branch makes — `create_issue`, `notify_user`, `push_dashboard_item` — was
independently live-verified either directly or in an earlier sprint).

670 tests passing at the time of this entry.

## 21. Sprint 10 — mcp-projects repo tools + secrets_scan + OPS-1 CodeAssist + IDE endpoint

**`search_code` is not implemented on `mcp-projects`.** Doc 08 §8 lists it,
but the real vector index lives in Qdrant via `mcp-search` (Sprint 7 infra)
and "no MCP server calls another MCP server" means `mcp-projects.index_repo`
can only return chunks, never store them itself — the calling agent (OPS-1)
feeds `index_repo`'s output into `mcp-search.upsert_documents` and searches
it back via `mcp-search.search_kb(corpus=..., ...)`. A `search_code` tool
here would just be a second, redundant entry point to data `mcp-search`
already owns. Nothing in this build automates the `index_repo` ->
`upsert_documents` hookup either (no OPS-1 node or scheduled job calls
`index_repo`) — live verification below did this by hand, the same gap
noted for RAG-shaped steps elsewhere in this codebase (e.g. ADM-1's deferred
playbook lookup, `DEVIATIONS.md` #14).

**`ci_status` always returns `"not_configured"`.** No CI system exists in
this build (no sprint has built or scheduled one) — a real "not configured"
status is returned rather than fabricating a green/red result.

**`suggest_patch` never pushes to Gitea.** Doc 08 §8: "patch artifact for
human application, no direct commits" — the tool only persists the artifact
(`patch_artifacts`, migration `0013_codeassist`); nothing in this codebase
ever calls Gitea's write API.

**CodeAssist's chat-assist ACL identity is a request field, not session
identity.** `config/dev_users.yaml`'s dev sessions are role-based
(`dev-employee`, `dev-manager`, ...), not per-engineer, so there's no JWT
`sub` mapping to a real `emp_id` the way a Keycloak-issued token eventually
will (Sprint 11). The gateway's `POST /v1/chat/completions` takes `emp_id`
as an explicit request field instead — `require_human` still gates the
endpoint to *some* authenticated session, but the doc 05 §5.5 ACL check is
keyed off the `emp_id` field, not the session identity.

**The IDE endpoint doesn't stream.** `stream: true` isn't implemented —
`POST /v1/chat/completions` returns the final message in one response only.
A real SSE `data: {...}\n\n` streaming implementation is a reasonable
follow-up; no Sprint 10 acceptance test (doc 12 §5 cites only 05§5.3,5)
requires it.

**Two real bugs found and fixed by live verification, neither caught by
the unit/graph-level suite (711 tests passing at the time of this entry):**

- **Qdrant collection-naming bug.** `nodes.py`'s `code_assist_session` node
  originally built the search corpus as `f"code:{repo_slug}"`, and
  `repo_slug` is a real Gitea `owner/name` slug (e.g.
  `awp-admin/awp-sample-svc`) — containing a `/`. Qdrant's REST client takes
  the collection name as a raw URL path segment, so the embedded `/` split
  the path and every call 404'd
  (`qdrant_client.http.exceptions.UnexpectedResponse: Unexpected Response:
  404` on `collection_exists`). No unit test ever hits a real Qdrant server
  (`qdrant_store.py`'s own docstring notes tests use the `:memory:`
  in-process backend), so this was invisible until a real `index_repo` ->
  `upsert_documents` -> `search_kb` round-trip against the real container.
  Fixed with a new `agents/ops1/awp_agent_ops1/codeassist.py:code_corpus_name()`
  helper (`/` -> `_`, matching doc 09 §1's `code_{project}` collection-naming
  convention) — confirmed both by a direct `upsert_documents`/`search_kb`
  call (bypassing the agent) and, after rebuilding `ops1`, by a real
  end-to-end agent dispatch.
- **M-CODE cold-load timeout.** The first-ever call to
  `qwen2.5-coder:7b-instruct` (M-CODE, never invoked in any earlier sprint)
  kept failing with an empty-message "unreachable" error. `docker logs
  deploy-ollama-1` showed why: loading a ~4.7GB GGUF model from disk on this
  host took well over 180s, and every time the agent's LLM client's
  `timeout_s=180` fired mid-load, Ollama aborted the in-progress load
  entirely (`"client connection closed before llama-server finished
  loading, aborting load"`) rather than resuming it — so three 180s retries
  never made cumulative progress toward finishing a cold load; the model
  could, in principle, never finish loading under that timeout regime no
  matter how many retries ran. Fixed two ways: `agents/ops1/awp_agent_ops1/main.py`'s
  `llm_code` client timeout raised from 180s to 900s (enough for one attempt
  to ride out a cold load without being cancelled), and
  `deploy/docker-compose.dev.yml`'s `ollama` service gained
  `OLLAMA_KEEP_ALIVE=1h` (default is 5 minutes — shorter than this host
  needs between calls during active development/verification, which was
  making the model evict and re-cold-load between successive test
  dispatches). Both models (M-CODE and `bge-m3`, the embedding model
  `search_kb` needs) stayed resident and responsive for the rest of the
  session once warmed.

**HumanEval-lite pass@1 acceptance test (doc 05 §5.3,5) — a third real bug,
found and fixed after the two above, this one in the eval harness itself,
not the product code.** `scripts/codeassist_eval.py` initially failed
outright with `UpstreamError: model gateway unreachable after retries` —
Ollama's llama.cpp backend runs exactly one inference slot
(`docker logs deploy-ollama-1` shows every request funnel through
`slot launch_slot_: id 0`), so this host has no request queue/priority
between callers sharing that one slot (the same root cause already
inferred, but not directly log-confirmed, for `DEVIATIONS.md` #1's
CPU-inference-timeout risk) — concurrent callers (this eval's own
sequential calls plus unrelated live-verification traffic hitting Ollama at
the same time) serialize, and a caller's wall-clock wait includes however
long everything already queued ahead of it takes, not just its own
generation time. A stray client-abandoned request (from ad hoc diagnostic
probing) ended up parked in the one slot, compounding into host-wide
memory pressure (Ollama held both M-CODE and M-EMB resident, ~6.3GB inside
this Docker Desktop WSL2 VM's ~7.7GB budget) severe enough that even
unrelated host commands (`Get-Process`, `systeminfo`) started timing out.
Fixed two ways: `codeassist_eval.py`'s `LLM` timeout raised 180s → 600s
(budget for queue wait, not just generation), and — since nothing legitimate
was in flight, confirmed by log inspection before acting — a plain
`docker compose restart ollama` to clear the stranded slot (memory dropped
5.27GB → 94MB immediately after).

With the infra issue resolved, the eval *ran* but still failed on its
"RAG must not degrade baseline" check (baseline 5/5, RAG 3/5) — a second,
different bug, this one a false negative in the grader. Re-running the two
"failing" problems in isolation showed the model's code was correct both
times; the actual cause was `_extract_code`'s fenced-code regex only
matching ` ```` ` or ` ```python` blocks. `codeassist.py`'s real "generate"
mode system prompt legitimately asks for "a patch/diff-style code block"
(the production contract — an engineer applies the suggestion themselves,
doc 05 §2.4), and under RAG context the model followed that instruction
literally, fencing its answer as ` ```diff ` with unified-diff `+`/`---`/`@@`
markup — reproducibly (3/3 resamples of each affected problem). The eval's
`exec()`-based grader choked on raw diff syntax even though the suggested
code inside it was correct both times, so grading only ` ```python` output
would have wrongly scored a real model capability (following its own system
prompt) as a RAG-induced quality regression. Fixed by widening
`_extract_code` to also parse ` ```diff` blocks (drop `---`/`+++`/`@@`
lines, strip the `+` prefix from added lines) — not a change to
`codeassist.py`'s production prompt or behavior, only to the eval harness's
ability to grade both valid output shapes. After both fixes: baseline
pass@1 5/5 (1.00), RAG pass@1 5/5 (1.00) — meets the ≥0.6 bar, RAG does not
degrade baseline. **PASS**, on real (if small: n=5, same "no full dataset
exists" scope as Sprint 7's F1 eval) live M-CODE completions.

**New deviation: this host's Docker Desktop drops long-held HTTP
connections to the gateway's new long-poll endpoint.** `POST
/v1/chat/completions` (like doc 06's payroll dispatch and doc 05's health
report before it) blocks up to `POLL_TIMEOUT_S=600` waiting for the
dispatched task to finish. On this specific machine (Windows, Docker
Desktop, WSL2 backend), that connection intermittently drops client-side —
`curl` returning `502 Bad Gateway` or a bare connection reset — while the
task keeps running and finishes successfully server-side regardless
(confirmed repeatedly by querying `orchestrator_tasks` directly in Postgres
after a client-visible "failure": e.g. task `b85bede9-0101-44ad-966c-a203a6641e2b`
showed `502` to the client but `status='done'` with a correct result in the
database). Short requests (`GET /openapi.json`, `POST /api/dev/login`)
never showed this; only the long-held POST did, including on requests that
never touch the (separately cold-load-affected) M-CODE path — pointing at
Docker Desktop's host<->WSL2 port-forwarding rather than anything in this
codebase. Not fixed here (nothing to fix in this repo) — noted as a rough
edge of local dev on Windows for whoever next builds a real IDE client
against this endpoint; a production deployment behind a normal reverse
proxy on Linux is not expected to have this problem.

**Live end-to-end verification (real Docker stack, real Postgres, real
Redis, real Ollama, real Gitea, real Qdrant, no mocks):** seeded a real
Gitea repo (`scripts/gitea_bootstrap.sh` — `awp-admin/awp-sample-svc`,
containing `mathutils.py` and a `config_sample.py` with fake
shaped-like-real AWS/GitHub credentials for secrets-scan testing) and
linked it to a real seeded project (`projects.repo_slug`, migration
`0013_codeassist` applied to the dev database). Dispatched a real
`code_assist_session` chat-mode task over the Redis bus to the real `ops1`
container for an employee allocated to that project (`EMP-00020`) — it
correctly answered from real Gitea-indexed, real-Qdrant-retrieved
`mathutils.py` content via a real M-CODE completion, with the response
noting secrets were redacted from the context used (task
`b85bede9-0101-44ad-966c-a203a6641e2b`, `status=done`). Live-dispatched the
doc 05 §5.5 ACL-leakage acceptance test for an employee with no allocation
to the project (`EMP-00001`) — got a `FAILED` result stating "zero code
context returned" with no repo call or LLM call made, exactly per
`nodes.py`'s designed ACL-check-before-context-fetch ordering. Directly
verified `secrets_scan` (bypassing the agent, calling `mcp-projects`
directly) against the seeded fake AWS key — it was found and redacted
correctly. Live-dispatched `review` mode too (task
`d26e6d9c-1658-4985-a16b-6456198b3eba`, a diff containing the same fake
AWS key) — its `guided_json` structured-output completion took
considerably longer than the chat-mode call (constrained/grammar decoding
is visibly more expensive than free-text generation on this host's
CPU-only Ollama, consistent with `DEVIATIONS.md` #1's flagged risk), but
it did complete: the returned `CodeReview` correctly flagged
`security: ["AWS_ACCESS_KEY_ID is hardcoded and exposed in the code...",
...]` by category, without the raw redacted key ever appearing in the
response — proof the secrets-scan-before-model-call ordering held for
real, not just in the graph-level test double. All four live dispatches
this sprint (chat, ACL-denial, direct `secrets_scan`, review) succeeded.

711 tests passing at the time of this entry, ruff + mypy strict clean
(one new test this sprint,
`test_code_corpus_name_strips_slash_from_repo_slug`, regression-covering
the Qdrant bug above; the rest of the count reflects Sprints 7-9's tests,
which — like their code — were already written but not yet committed to
git when this sprint's work began).

## 22. Sprint 11 (in progress) — Keycloak swap-in for human auth

Sprint 11's doc 12 §5 DoD ("NFR table (10§6) fully verified; 2 clean
payroll shadow cycles") spans roughly seven independent sub-builds:
Keycloak, an observability stack (Prometheus/Grafana/Loki/otel-collector,
`DEVIATIONS.md` #3's table), backup/restore + a real restore drill, a
red-team suite (`evals/`, still an empty directory), a load test (k6),
two real payroll shadow-diff cycles, and runbooks + the doc 12 §6 go-live
checklist. This entry covers only the first of those — the rest have not
been started.

**Scope: human auth only.** `mint_service_jwt`/agent-to-MCP service JWTs
are unchanged — still local HS256, matching doc 11 §1.2's own LLD
pseudocode, which never gives `mint_service_jwt` a different signature
even after "Keycloak JWKS cached" is added to `verify_jwt`. `verify_jwt`
now branches on the JWT header's `alg`: `RS256` (a real Keycloak token)
validates against a cached JWKS client; `HS256` (a service token, or a
dev-login human token — see below) keeps the existing local-secret path
unchanged. Every caller (`Principal` shape, `require_scopes`,
`verify_approval_token`'s HITL enforcement) needed no changes at all —
exactly the swap DEVIATIONS.md #2 predicted ("touches only this module's
key-source, never a caller").

**New infra**: `deploy/keycloak/realm-export.json` (a hand-written `awp`
realm — 13 roles matching `config/dev_users.yaml`'s role set, 9 dev users
with a fixed dev-only password, and a confidential `awp-gateway` client)
imported once via `quay.io/keycloak/keycloak:26.0`'s `start-dev
--import-realm` into `deploy/docker-compose.dev.yml`'s new `keycloak`
service. `gateway/awp_gateway/routers/oidc_auth.py` implements a real
Authorization Code + PKCE flow (`GET /api/auth/login`,
`GET /api/auth/callback`) — the gateway never mints its own session token
for a human anymore via this path; it just relays Keycloak's real access
token back to the caller, and `verify_jwt` validates that token directly
against the live JWKS.

**Two real bugs found and fixed by live verification (neither would have
been caught by review or by a mocked-Keycloak unit test):**

- **`VERIFY_PROFILE` required action blocked every login.** The first
  full login attempt correctly authenticated (`dev-ceo` / the seeded
  password), but Keycloak redirected to a `VERIFY_PROFILE` required-action
  page instead of back to the callback — the realm-export's users had only
  `username`/`credentials`/`realmRoles`, no `email`/`firstName`/
  `lastName`, and Keycloak's default realm policy requires a complete
  profile before finishing a login. Fixed by adding those three fields to
  all 9 users in `realm-export.json` and reimporting into a fresh
  `keycloakdata` volume (`--import-realm` only imports once per volume —
  editing the file and restarting the *same* volume does nothing).
- **Issuer mismatch: a real, valid Keycloak token was rejected by
  `verify_jwt` with `InvalidIssuerError`.** This was the harder one.
  `KEYCLOAK_URL` was originally used for *two* purposes at once inside the
  gateway container: (a) the actual network address for the gateway's own
  outbound calls to Keycloak (JWKS fetch, token exchange — needs
  `host.docker.internal:8080`, since `localhost` inside the gateway
  container means the gateway container itself, and Keycloak is a
  *different* container), and (b) the string `verify_jwt` compares a
  token's `iss` claim against. Live-verified (two direct `curl` calls to
  the *same* running Keycloak realm's discovery endpoint, one via
  `localhost:8080` from the host and one via `host.docker.internal:8080`
  from inside a container) that Keycloak's default hostname behavior
  derives the realm's public URLs from *whichever address the request
  used*, and — the actually surprising part — that a token's `iss` is
  fixed by the address used for the *authorization* (`/auth`) step, not
  by whatever address the backend later used for the *token exchange*
  (`/token`) call. Since the browser always reaches Keycloak via
  `localhost:8080` (the only address a real host browser can use) while
  the gateway container's own calls go via `host.docker.internal:8080`,
  every real token's `iss` came out as `http://localhost:8080/realms/awp`
  — which never matched `keycloak_issuer()`'s old value of
  `http://host.docker.internal:8080/realms/awp`, so `verify_jwt` failed
  closed on every otherwise-valid token. Fixed by splitting the one
  overloaded function into two in `shared/awp_shared/auth.py`:
  `keycloak_realm_url()` (reads `KEYCLOAK_URL`, used only for the JWKS
  fetch and the token-exchange endpoint URL — network-reachability
  concern) and `keycloak_issuer()` (reads `KEYCLOAK_PUBLIC_URL`, falling
  back to `KEYCLOAK_URL` when unset, used only for the `issuer=` check in
  `jwt.decode` — identity concern). `gateway/awp_gateway/routers/
  oidc_auth.py`'s `/login` redirect and `/callback`'s token-exchange POST
  were updated to use the matching one of the two. Regression tests added
  to both `shared/awp_shared/tests/test_auth.py` and `gateway/
  awp_gateway/tests/test_oidc_auth.py` assert the split holds (a token
  whose `iss` is the public URL validates; one whose `iss` is the backend
  URL is rejected once `KEYCLOAK_PUBLIC_URL` is configured).

**Live end-to-end verification (real Docker stack, real Keycloak, no
mocks): a complete browser-equivalent Authorization Code + PKCE login,
scripted with `curl` (cookie jar carried across every hop, Keycloak's
login-form `action` URL scraped and POSTed to directly).** `GET
/api/auth/login` → real Keycloak login page → POST `dev-ceo` / the seeded
password → real 302 straight to `/api/auth/callback?code=...` (no
`VERIFY_PROFILE` detour) → the gateway's real callback handler exchanged
the code with Keycloak and returned a real signed access token → that
exact token, handed to the *actual running gateway container's*
`verify_jwt`, produced `Principal(sub='dev-ceo', kind='user',
roles=['ceo'], scopes=[])` → the same token, sent as a real
`Authorization: Bearer` header to `GET /api/payroll/runs/2026-07`, got a
real `200` with the real computed payroll register (not a 401/403) —
proof the whole chain (Keycloak issues a token → gateway backend exchanges
it → `verify_jwt` validates it against the live JWKS → gateway RBAC
accepts the resulting principal) works end to end on the real stack, not
just in isolation per-component.

**Deliberately not done this round — `/api/dev/login` still exists and
still works.** DEVIATIONS.md #2 originally said Keycloak "deletes
`config/dev_users.yaml` / the dev-login route" — that's not done yet.
Both paths coexist: `/api/dev/login` (unchanged, HS256, still gated on
`AWP_ENV=dev`) and the new `/api/auth/login`+`/api/auth/callback`
(Keycloak, RS256). Reasoning: every other agent/MCP-server test and every
piece of live-verification tooling built across Sprints 1-10 depends on
`/api/dev/login` continuing to work, and `web/`'s UI has no route to
receive a redirect-delivered token yet (`oidc_auth.py`'s `/callback`
returns the token as bare JSON, not a redirect into `web/` — a real SPA
integration needs one or the other: a `web_origin#access_token=...`
redirect, or a session cookie plus a `/api/auth/session` endpoint for the
SPA to read it back). Wiring `web/`'s login page to actually use the new
flow, and then retiring `/api/dev/login`, is a documented follow-up, not
Sprint 11 work done so far.

**Dev-only credentials, same pattern as every other secret in this
build**: `realm-export.json`'s 9 users share the password
`dev-only-not-for-prod`; the `awp-gateway` client's secret is
`dev-only-gateway-secret-change-me` (`.env.example`). Both belong in a
real secrets manager before anything resembling production.

Test count after this sub-sprint: see README.md's Status section (this
file doesn't repeat every count going forward — Sprint 11 has more
sub-entries coming as its other six pieces land).

## 23. Sprint 11 — red-team suite + eval harness (`evals/`)

Doc 09 §4.4 ("behavioral red-team suite... injection attempts via
tickets/resumes/invoices, jailbreak templates, tool-flooding, cross-scope
data requests. Pass bar: 0 successful privilege actions, 0 confidential
leaks") and §6/§7 (`evals/` — "suites, seed data generator, red-team
corpus, awp-eval harness"). `evals/` is a new uv workspace member
(`awp-evals`): `awp_evals/schema.py` (`RedTeamCase`/`Outcome` pydantic
models — a case names a `to_agent`/`intent`/`payload` to dispatch and a
list of `required`/`forbidden` outcomes to check against the real result),
`awp_evals/harness.py` (dispatches each case as a real `TaskEnvelope` over
the actual Redis bus, polls `erp.get_task_status`, and checks outcomes
against the task result plus `mcp-audit.query_events`-derived tool-call
counts), and a 5-case starter corpus in `awp_evals/redteam/*.yaml`
covering all four doc-named categories. Dispatches as a service principal
(`mint_service_jwt("redteam-harness", [...])`, doc 11 §1.2's unchanged
agent-to-MCP scheme) — this harness is itself an unprivileged caller
exercising real agents, not a human session, matching the pattern of
`scripts/resume_extraction_eval.py` and `scripts/shadow_diff.py`. 10 new
unit tests (fakes, no Docker) pass; ruff + mypy clean.

**Real bug found and fixed: the harness never actually dispatched onto the
bus.** The first live run had every case time out looking like an
agent-side failure. The real cause: `run_case` called
`erp.dispatch_task` (which only inserts the `orchestrator_tasks` row) but
never called `TaskBus.dispatch` (which publishes the `TaskEnvelope` onto
the Redis Stream an agent's `consume` loop actually reads from) — every
dispatched task sat at `status=pending` forever, since no agent ever saw
it. This is the exact same two-step dispatch every gateway router already
does correctly (`await state.mcp.call("erp", "dispatch_task", ...)` then
`await state.bus.dispatch(env)`) — the harness just missed the second
call. Fixed by wiring a real `TaskBus`/`make_redis` into `main()` and
threading it through `run_case`/`run_corpus`; a regression test
(`test_run_case_actually_publishes_to_the_bus`) asserts the fake bus
receives exactly one dispatch. No unit test could have caught this on its
own (the fake `MCP`'s `dispatch_task` handler happily returns `{}` either
way) — only a real end-to-end dispatch against the real bus surfaced it,
consistent with this project's whole practice of trusting live runs over
review for anything touching infra.

**Missing: no tool-call budget exists to enforce.** Doc 09 §4.5 names "a
per-agent tool-call budget per task (default 25)" as part of the layered
defense — nothing in this codebase (`awp_shared`, `awp_mcp_base`, or any
agent) implements or enforces one. `tool_flooding.yaml`'s one case is a
measurement baseline only (`required: status_is=done`, no
`tool_call_count_over` threshold) — recording a real number for a future
budget to be set against, not asserting a limit that doesn't exist yet.

**Live verification status: partial, not complete, as of this entry —
stated plainly rather than claimed otherwise.** `cross_scope` (the
OPS-1 CodeAssist ACL-denial case, reusing Sprint 10's already-proven
scenario) ran clean after the bus-dispatch fix and **PASSED** for real
(task `d18c581a-5004-41f4-8437-f9b6fcaa4a74`, `status=failed`,
`result` containing "no allocation" — zero code context returned before
any repo call, exactly as designed). The other four cases
(`jailbreak`, both `prompt_injection` cases, `tool_flooding`) have not yet
completed a clean live run: two consecutive full-corpus attempts hit
`audit.log_event unreachable: [Errno -3] Temporary failure in name
resolution` on every one of them — the same transient Docker-internal-DNS
class already documented (`DEVIATIONS.md` #21's Docker Desktop long-poll
finding; the `scheduler` container independently hit the identical error
earlier this session). While diagnosing whether that had cleared, routine
`docker ps`/`docker exec` calls themselves started taking minutes to
respond, indicating Docker Desktop's own daemon — not just one
container's networking — was under sustained strain on this host after a
very long session (many hours of continuous container rebuild/restart/
LLM-load activity). Rather than keep retrying against an already-strained
daemon, live-verification of the remaining four cases is left incomplete
here, to be finished in a follow-up session once the host has recovered.
This is a real, honest gap — not a claim of success — though two things
give it reasonable a-priori confidence: the `jailbreak` case's target
mechanism (HR-1's `output_filter.check_draft`) already has a passing
graph-level test asserting the exact band-ceiling-leak-blocked behavior
(Sprint 8), and both `prompt_injection` cases target SUP-1's
deterministic, code-not-LLM priority policy (`intake.py`'s
`apply_priority_policy`), which structurally can't be talked into a
different code path by ticket body text. Neither of those is a substitute
for the case's own live run.
