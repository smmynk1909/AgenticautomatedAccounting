# 11 — LOW-LEVEL DESIGN (LLD)

**Scope:** Implementation-level contracts: shared libraries, Pydantic schemas, LangGraph node signatures, MCP tool signatures (canonical), REST/WS API, DB DDL details, sequence diagrams, error handling, config formats. Code generators (Cowork/Claude Code) should treat every signature here as the contract to implement.

Python 3.12 · Pydantic v2 · SQLAlchemy 2 (async) + Alembic · FastAPI · LangGraph ≥ 0.2 · mcp (FastMCP) · redis-py (streams) · qdrant-client · authlib (JWT/JOSE).

---

## 1. Shared Library `shared/` (package `awp_shared`)

### 1.1 Core schemas (`awp_shared/schemas.py`)
```python
class Priority(str, Enum): P1="P1"; P2="P2"; P3="P3"; P4="P4"
class TaskStatus(str, Enum):
    PENDING="pending"; DISPATCHED="dispatched"; IN_PROGRESS="in_progress"
    BLOCKED="blocked"; AWAITING_APPROVAL="awaiting_approval"; DONE="done"; FAILED="failed"

class TaskEnvelope(BaseModel):
    task_id: UUID = Field(default_factory=uuid4)
    parent_task_id: UUID | None = None
    from_agent: AgentId          # Enum: ORCH0, ADM1, HR1, OPS1, FIN1, SUP1, HUMAN, SCHEDULER
    to_agent: AgentId
    intent: str                  # must exist in IntentRegistry
    payload: dict                # validated against intent's payload model at dispatch
    priority: Priority = Priority.P3
    sla_deadline: datetime | None
    requires_approval: bool      # overwritten from gates policy at dispatch (never trusted)
    trace_id: UUID
    idempotency_key: str         # f"{task_id}"
    created_at: datetime

class TaskResult(BaseModel):
    task_id: UUID; status: TaskStatus; summary: str
    artifacts: list[ArtifactRef] = []      # {kind, uri|id, scope}
    error: ErrorInfo | None = None

class ErrorInfo(BaseModel):
    code: Literal["VALIDATION","NOT_FOUND","PERMISSION_DENIED","CONFLICT",
                  "APPROVAL_REQUIRED","UPSTREAM","INTERNAL","TIMEOUT"]
    message: str; retryable: bool; details: dict = {}
```

### 1.2 Auth (`awp_shared/auth.py`)
```python
class Principal(BaseModel):
    sub: str; kind: Literal["agent","user"]; roles: list[str]; scopes: list[str]
def mint_service_jwt(agent_id: str, scopes: list[str], ttl_s=900) -> str
def verify_jwt(token: str) -> Principal          # Keycloak JWKS cached
def require_scopes(p: Principal, needed: list[str]) -> None  # raises PermissionDenied
class ApprovalToken(BaseModel):                  # verified by MCP servers
    jti: str; gate: str; payload_hash: str; approvers: list[str]; exp: datetime
def verify_approval_token(tok: str, gate: str, payload: dict) -> ApprovalToken
    # checks signature (mcp-approvals key), gate match, sha256(payload_canonical)==payload_hash,
    # single-use (Redis SETNX on jti), not expired. Raises ApprovalRequired otherwise.
```

### 1.3 Task bus (`awp_shared/bus.py`) — Redis Streams
```python
STREAM = "tasks.{agent}"          # consumer group per agent, consumer per replica
class TaskBus:
    async def dispatch(self, env: TaskEnvelope) -> None      # XADD + task row upsert
    async def consume(self, agent: AgentId, handler: Callable[[TaskEnvelope], Awaitable[TaskResult]])
        # XREADGROUP loop; dedupe: SETNX processed:{idempotency_key} EX 7d
        # handler exception → retry via delayed re-add (1m/5m/25m, attempt in msg meta)
        # attempt>3 → XADD tasks.dlq + auto SUP ticket + audit event
    async def ack(self, agent, msg_id); async def heartbeat(self, agent)  # SET hb:{agent} EX 120
```

### 1.4 LLM client (`awp_shared/llm.py`)
```python
class ModelBinding(BaseModel): planner: str="M-GEN"; extractor: str="M-SMALL"; coder: str|None
class LLM:
    def __init__(self, gateway_url: str, model: str, defaults: SamplingProfile)
    async def chat(self, messages, tools: list[ToolSchema]|None=None,
                   guided_json: type[BaseModel]|None=None, **overrides) -> LLMResponse
    # guided_json → vLLM guided_json / llama.cpp grammar from model_json_schema()
    # retries: 2x on transport; on schema-invalid output → 1 repair round with error appended
SAMPLING = {"plan":(0.1,.9,1024), "classify":(0.0,1,128), "draft":(0.6,.95,2048),
            "extract":(0.0,1,1536), "code":(0.2,.95,4096)}
```

### 1.5 MCP client (`awp_shared/mcpc.py`)
```python
class MCP:
    def __init__(self, servers: dict[str,str], principal_jwt_provider)
    async def call(self, server: str, tool: str, args: BaseModel|dict,
                   approval_token: str|None=None, idempotency_key: str|None=None) -> dict
    # attaches Authorization + X-Trace-Id + X-Idempotency-Key; maps error JSON→typed exceptions
```

### 1.6 Untrusted content wrapper (`awp_shared/trust.py`)
```python
def wrap_untrusted(label: str, content: str) -> str:
    return f"<untrusted source='{label}'>\n{escape(content)}\n</untrusted>"
# Standing system-prompt rule references this tag. All ticket bodies, resume text,
# invoice text, inbound email MUST pass through wrap_untrusted before prompt assembly.
```

### 1.7 Audit middleware (`awp_shared/audit_mw.py`)
FastMCP middleware: before/after every tool call → `mcp-audit.log_event` fire-and-forget with local disk spool fallback (guarantee: no lost events on audit downtime; replayed on recovery).

## 2. Agent Runtime Skeleton (`agents/_base/`)

```python
class AgentApp:
    """Common runtime: bus consumer + LangGraph executor + checkpointing."""
    def __init__(self, agent_id, graph: CompiledGraph, binding: ModelBinding, mcp: MCP)
    # LangGraph checkpointer: PostgresSaver (table agent_checkpoints) keyed by task_id
    # → crash-resume: unacked bus msg redelivered, graph resumes from last checkpoint
    async def handle(self, env: TaskEnvelope) -> TaskResult   # entry per task

class AgentState(TypedDict):        # base graph state, agents extend
    task: TaskEnvelope
    steps: list[StepRecord]         # tool calls + results (trimmed to last 12)
    scratch: dict                   # agent-specific
    result: TaskResult | None
    tool_budget: int                # default 25, decremented per call; 0 → fail BLOCKED
```

**Common graph nodes (library `agents/_base/nodes.py`):**
```python
async def n_validate_payload(state) -> state       # payload vs intent model
async def n_plan(state, llm, tools) -> state       # guided_json ToolPlan | direct tool_call
async def n_execute_tool(state, mcp) -> state      # validates plan step, calls MCP, records
async def n_check_approval(state) -> "wait"|"go"   # polls mcp-approvals w/ backoff+resume
async def n_summarize(state, llm) -> state         # final TaskResult.summary (draft profile)
async def n_fail(state, err) -> state
# Edge helper: route_on_validation_error → repair (≤1) → fail
```
Per-agent graphs (02–07 docs) are compositions of these + agent-specific nodes; every node ≤ 1 LLM call; loops bounded by `tool_budget` and `max_plan_repairs=1`.

## 3. MCP Server Skeleton (`mcps/_base/`)

```python
def make_server(name: str, scopes_cfg: Path) -> FastMCP:
    app = FastMCP(name)
    app.middleware(auth_mw)        # verify_jwt → Principal in ctx
    app.middleware(scope_mw)       # tool→required scopes from scopes.yaml
    app.middleware(audit_mw)
    app.middleware(idempotency_mw) # write tools: cache result by key 7d
    return app

# Tool pattern (every tool):
@app.tool()
async def assign_asset(args: AssignAssetIn, ctx: Ctx) -> AssignAssetOut:
    if needs_gate(args): verify_approval_token(ctx.approval_token, "asset_high_value", args.model_dump())
    async with uow() as u:                        # SQLAlchemy async unit-of-work
        ...
```
DB access via repository classes per aggregate (`EmployeeRepo`, `AssetRepo`, `TicketRepo`, `LedgerRepo` …) — no raw SQL in tools except reporting views.

## 4. FinCore (`fincore/`) — deterministic, LLM-free

```python
# fincore/payroll.py
def compute_payroll(snapshot: PayrollSnapshot, tables: TaxTables) -> PayrollRegister
    # pure function; PayrollSnapshot frozen (employees, comp, attendance, declarations)
def compute_line(emp: EmpComp, att: Attendance, t: TaxTables) -> PayrollLine
    # earnings: basic, hra, special, variable; lop = round(gross/days*lop_days, 2)
    # pf = min(basic,15000)*0.12 (configurable per tables); esi if gross<=threshold
    # pt = state slab; tds = annual_projection.remaining/months_left (recomputed monthly)
# fincore/tax.py
def project_tds(fy, regime, income: AnnualIncome, decl: Declarations, t) -> TDSProjection
def compare_regimes(...) -> RegimeComparison
# fincore/ledger.py
def validate_entry(e: JournalEntry) -> None   # balance, open period, valid accounts
def post(e) -> PostedEntry                    # inside repo txn
# fincore/invoice.py, fincore/depreciation.py (WDV/SLM per asset class), fincore/cashflow.py
# fincore/tables.py: load YAML → TaxTables(version, effective range); refuse if period uncovered
```
Testing contract: property tests (hypothesis) — TB balance invariant, payroll monotonicity (more LOP ⇒ ≤ net), rounding = round-half-up 2dp, regime comparison symmetric; golden files per FY.

## 5. Gateway API (`gateway/`) — REST + WS (OpenAPI generated)

```
POST /api/chat/{agent_id}            {message, context_refs[]} → {task_id}   (dispatch to bus)
GET  /api/tasks/{task_id}            → TaskEnvelope+status+result
WS   /ws/stream?trace_id=            server pushes StepRecord + final TaskResult
GET  /api/tickets?filters            POST /api/tickets              PATCH /api/tickets/{id}
GET  /api/dashboard/{role}           → panels[] (materialized views)   SSE /api/dashboard/stream
GET  /api/approvals/inbox            POST /api/approvals/{id}/approve|reject {comment}
     # approve → mcp-approvals mint (server-side, user JWT roles checked against gate)
GET  /api/files/{uri}                (MinIO presign, scope-checked)
POST /api/uploads                    (resume/invoice/statement → MinIO + kickoff intent optional)
GET  /api/payroll/runs/{month}       GET /api/reports/{kind}         (role-gated)
Auth: OIDC code flow → session JWT; RBAC map roles.yaml; rate limit 60 rpm/user.
```

### 5.4 LLM tool-call validation loop (used by all agents)
```
resp = llm.chat(msgs, tools=schemas)
if resp.tool_calls: for c in calls: Pydantic-validate → ok? execute : append error msg, retry once
if still invalid → StepRecord(error) → n_fail or human ticket per agent policy
Metric: tool_call_validity = valid/total  (SLO ≥ 0.98, alert < 0.95 hourly)
```

## 6. Key Sequences (implementation-level)

### 6.1 Payroll run (DF-3 detail)
```
scheduler→bus: {intent:run_payroll, month}
FIN-1 graph: validate → mcp-finance.freeze_payroll_inputs(month)→snapshot_id
 → compute_payroll(snapshot_id)→register_id
 → anomaly node: SQL deltas; unexplained>±15% → scratch.review_list
 → mcp-docs.render_pdf(salary_slip_v1, per line, scope=emp)   [batched 20/call]
 → mcp-approvals.request_approval(gate=payroll_run, payload={register_id, totals, anomalies_hash},
    approver_roles=[finance_head,director], n_required=2) → approval_id
 → n_check_approval poll (30s→5m backoff; checkpoint; resume on approve webhook)
 approved(token) → mcp-finance.generate_disbursement_file(register_id, approval_token)
 → mcp-finance.post_journal(salary_entries, approval_token)   [same token, same payload_hash family]
 → mcp-comms.distribute_slip(each) → TaskResult(done, artifacts=[vault_uri, register])
Failure paths: freeze conflict (already frozen) → CONFLICT → attach existing snapshot;
approval rejected → status FAILED + reasons → dashboard; partial slip render → retry failed subset only.
```

### 6.2 Ticket intake→resolution (DF-4 detail)
```
POST /api/tickets → mcp-erp.create_ticket(status=new) → bus tasks.support{classify_ticket}
SUP-1a: M-SMALL guided_json TicketClass → priority = policy_engine(class, entities)  [code override]
 → mcp-erp.update_ticket(triaged) → route via routing.yaml → bus tasks.{owner}
Owner agent resolves (its playbook) → append_ticket_event(resolution) → SUP-1c regen summary
 → notify requester → confirm? closed : auto-resolve policy (07 §3.3)
SLAWarden: apscheduler job/min scans due timers (SQL) → escalation ladder (no LLM).
```

### 6.3 Candidate sourcing→shortlist (docs 04 §2.1–2.3 detail)
```
HR-1a: RoleProfile cached? else M-GEN guided_json + recruiter confirm gate
 → mcp-search.search_candidates(profile, filters, k=50) → ids+evidence
HR-1c: score() in code (weights in config/shortlist.yaml) → top N
 → per candidate: M-GEN justification (context = profile fields only, protected attrs stripped by server)
 → request_approval(shortlist_publish) → on approve: mark candidates shortlisted, report artifact.
```

## 7. Database DDL specifics (delta over 09 §1)
- All money `NUMERIC(14,2)`; rates `NUMERIC(7,4)`; FY strings `'2026-27'`.
- `journal_lines` trigger `trg_balance` DEFERRABLE INITIALLY DEFERRED: per-entry Σdr=Σcr else raise.
- Invoice numbers: `invoice_seq_{fy}` sequences created at FY open; assignment inside `issue_invoice` txn (gapless via row lock on `fy_counters`).
- RLS: `employees`, `comp_structures`, `candidates`, `payroll_runs`, `tickets(confidential)` — policies keyed on `current_setting('awp.principal_roles')` set by repo layer per request.
- Indexes: tickets(status,category,priority), work_logs(emp_id,date), journal_lines(account,entry_id), candidates USING gin(profile jsonb_path_ops), trigram on candidates((profile->>'name')).
- `agent_checkpoints(task_id pk, graph, state bytea, updated_at)`; `processed_keys(key pk, ts)` mirror of Redis dedupe for audit.

## 8. Config file contracts (`config/`)
```yaml
# intents.yaml
- intent: run_payroll
  agent: FIN-1
  payload_model: RunPayrollIn        # importable path resolved in shared/intent_models.py
  gate: payroll_run                  # authoritative requires_approval source
  sla_hours: 24
# gates.yaml: {gate: {roles:[], n:1, ttl_h:24, payload_model:}}
# scopes.yaml: {server.tool: [scope,...]} ; agent→scopes in agents/*/config.yaml
# routing.yaml: {category: {owner: ADM-1|human:queue, subrules:[]}}
# sla.yaml, shortlist.yaml, entitlements.yaml, sources.yaml, models.yaml (name→gateway url)
```
All configs schema-validated at service boot (fail-fast) by `awp_shared/config.py`.

## 9. Error handling & resilience matrix
| Failure | Detection | Behavior |
|---|---|---|
| Model server down | httpx errors ×2 | agent → degraded: M-SMALL fallback for classify/extract; drafting tasks parked (BLOCKED, reason surfaced) |
| MCP server down | typed UPSTREAM | step retry 3×; then task BLOCKED + SUP ticket |
| Approval expired | token exp | re-request with fresh payload hash; audit both |
| Redis restart | AOF persistence | consumer groups resume; heartbeat gap alarms |
| Postgres failover (single node) | health probe | gateway 503 + status page; agents park |
| Schema-invalid LLM output | Pydantic | 1 repair round → fail path |
| Duplicate delivery | idempotency mw | cached result returned |

## 10. Testing pyramid (maps to CI in repo doc 12)
Unit (fincore property/golden, repos, schemas) → Contract (each MCP tool: schema, scope-denial, idempotency, gate-enforcement) → Graph (LangGraph runs with mocked MCP/LLM fixtures per acceptance test in docs 02–07) → E2E (compose-up, seeded DB, DF-1..5 scenarios, k6 load) → Eval/Red-team (awp-eval nightly + on model/prompt change). Coverage gates: fincore 95%, mcps 85%, agents graph-paths 100% of defined edges.
