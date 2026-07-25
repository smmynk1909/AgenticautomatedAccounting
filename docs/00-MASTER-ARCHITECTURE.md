# Master Architecture — Local Agentic Workforce Platform (AWP)

**Version:** 1.0 · **Status:** Design Baseline · **Audience:** Development team (human + AI-assisted)

---

## 1. Purpose

Build a production-grade, fully local, multi-agent system that performs the internal operations of an IT services & product company across five departments — **Admin, HR, Operations, Finance, Support** — using open-source Small Language Models (SLMs) from Hugging Face. Agents communicate over the **Model Context Protocol (MCP)** and a lightweight internal message bus. Everything runs on a single on-prem server (or high-end laptop for dev), with no data leaving the premises except explicitly whitelisted external integrations (e.g., job boards for HR sourcing).

## 2. Design Principles

1. **Local-first.** All inference, storage, and orchestration on-prem. No cloud LLM API dependency at runtime.
2. **One shared model pool, many agents.** Agents are *not* one fine-tuned model each. They are role-configured runtimes (system prompt + tools + RAG scope + policies) sharing a small pool of served SLMs. This keeps VRAM realistic and maintenance sane. Department-specific behavior comes from prompts, retrieval scopes, and (optionally, phase 3) LoRA adapters per department.
3. **MCP as the tool boundary.** Every capability an agent can execute (DB writes, PDF generation, ticket updates, payroll runs) is an MCP tool exposed by a purpose-built MCP server. Agents never touch databases or files directly.
4. **Human-in-the-loop (HITL) for irreversible/financial actions.** Salary disbursement, offer approval, device write-offs, tax filings, and any external communication require an approval gate. Agents *prepare*, humans *approve*, agents *execute*.
5. **Deterministic core, probabilistic edge.** Payroll math, tax computation, double-entry postings, and ledger integrity are deterministic code (Python services). The SLM orchestrates, extracts, summarizes, drafts, and decides *which* deterministic tool to call — it never computes money by generation.
6. **Auditable by construction.** Every agent action is an immutable event in an audit log (who/which agent, tool, inputs hash, outputs hash, approver, timestamp).
7. **Fail safe, degrade gracefully.** If a model server is down, tools still work via the admin UI; queued agent tasks resume.

## 3. System Topology

```
┌────────────────────────────────────────────────────────────────────┐
│                        PRESENTATION LAYER                          │
│  Web App (React) · Executive Dashboard · Dept Consoles · Chat UI   │
└───────────────▲────────────────────────────────────────────────────┘
                │ REST/WebSocket (FastAPI Gateway, OIDC auth, RBAC)
┌───────────────┴────────────────────────────────────────────────────┐
│                     ORCHESTRATION LAYER                            │
│  ┌──────────────┐   ┌───────────────────────────────────────────┐  │
│  │ ORCH-0       │   │ Task Queue (Redis Streams) + Scheduler    │  │
│  │ Orchestrator │◄──┤ (APScheduler: payroll cron, SLA timers,   │  │
│  │ Agent        │   │  training reminders, dashboard refresh)   │  │
│  └──────┬───────┘   └───────────────────────────────────────────┘  │
│         │  routes tasks, decomposes goals, tracks state            │
│  ┌──────┴──────────────────────────────────────────────────────┐   │
│  │  DEPARTMENT AGENTS (LangGraph runtimes)                     │   │
│  │  ADM-1 Admin · HR-1 HR · OPS-1 Operations                   │   │
│  │  FIN-1 Finance · SUP-1 Support · (each with sub-agents)     │   │
│  └──────┬──────────────────────────────────────────────────────┘   │
└─────────┼──────────────────────────────────────────────────────────┘
          │ MCP (stdio/HTTP-SSE), JSON-RPC 2.0
┌─────────┴──────────────────────────────────────────────────────────┐
│                       MCP TOOL LAYER                               │
│  mcp-erp (people/assets/tickets DB) · mcp-finance (ledger,payroll) │
│  mcp-docs (PDF/xlsx/docx gen) · mcp-hrsourcing (resume parse,      │
│  job-board connectors) · mcp-projects (Git/Gitea, timelines)       │
│  mcp-comms (email/Slack-compatible chat) · mcp-search (RAG/vector) │
│  mcp-approvals (HITL gates) · mcp-audit (event log)                │
└─────────┬──────────────────────────────────────────────────────────┘
┌─────────┴──────────────────────────────────────────────────────────┐
│                        DATA & MODEL LAYER                          │
│  PostgreSQL (system of record) · Qdrant (vectors) · MinIO (files)  │
│  Redis (queue/cache) · vLLM / llama.cpp model pool:                │
│    M-GEN  general SLM (7–8B, Q4/AWQ)                               │
│    M-CODE coding SLM (7B coder)                                    │
│    M-EMB  embedding model · M-RERANK reranker (optional)           │
└────────────────────────────────────────────────────────────────────┘
```

## 4. Agent Roster (build order)

| ID | Agent | Doc | Phase |
|----|-------|-----|-------|
| ORCH-0 | Orchestrator / Router | 02 | 1 |
| SUP-1 | Support & Ticketing (shared ticket fabric) | 07 | 1 |
| ADM-1 | Admin (devices, internal DB, exec dashboard) | 03 | 1 |
| FIN-1 | Finance (payroll, accounting, billing, tax) | 06 | 2 |
| HR-1 | HR (sourcing, CV audit, negotiation, training) | 04 | 2 |
| OPS-1 | Operations (delivery, timelines, coding assistant) | 05 | 3 |

Each department agent contains **sub-agents** (specialized graph nodes with narrower prompts/tools) documented in its own file. Sub-agents share the department's model binding and RAG scope.

## 5. Inter-Agent Communication

Two channels, used for different purposes:

**A. Task Bus (asynchronous, durable).** Redis Streams topic per agent (`tasks.hr`, `tasks.finance`, …). Messages are `TaskEnvelope` JSON:

```json
{
  "task_id": "uuid",
  "parent_task_id": "uuid|null",
  "from_agent": "ORCH-0",
  "to_agent": "FIN-1",
  "intent": "generate_salary_slips",
  "payload": {"month": "2026-07", "employee_ids": "all_active"},
  "priority": "P2",
  "sla_deadline": "2026-07-28T18:00:00+05:30",
  "requires_approval": true,
  "trace_id": "uuid",
  "created_at": "..."
}
```

Rules: at-least-once delivery; consumers must be idempotent (dedupe on `task_id`); every state change emitted to `mcp-audit`. Dead-letter stream `tasks.dlq` with alerting to SUP-1.

**B. MCP tool calls (synchronous).** When Agent A needs a *capability* owned by Agent B's domain (e.g., HR needs a candidate record), it calls the MCP server directly (`mcp-erp.get_candidate`) — not the other agent. Agents delegate *judgment work* over the task bus; they access *data/capabilities* over MCP. This prevents chatty LLM↔LLM loops.

**Cross-department example — new hire onboarding:**
1. HR-1 marks candidate `hired` → emits `tasks.orchestrator: intent=onboard_employee`.
2. ORCH-0 fans out: `tasks.admin: provision_device+accounts`, `tasks.finance: setup_payroll`, `tasks.operations: assign_project`, `tasks.support: create_onboarding_ticket_bundle`.
3. Each agent completes its subtask, reports status; ORCH-0 aggregates and closes the parent task; ADM-1's exec dashboard shows the rollup.

## 6. Model Pool Strategy (summary — full detail in doc 01)

| Slot | Role | Default model (HF) | Served by | Approx VRAM (Q4) |
|------|------|--------------------|-----------|------------------|
| M-GEN | All dept agents' reasoning/tool-calling | `Qwen/Qwen2.5-7B-Instruct` | vLLM (AWQ) or llama.cpp GGUF | ~6–8 GB |
| M-CODE | OPS coding assistant | `Qwen/Qwen2.5-Coder-7B-Instruct` | same server, second model or swap | ~6–8 GB |
| M-EMB | RAG embeddings | `BAAI/bge-m3` or `nomic-ai/nomic-embed-text-v1.5` | ONNX/CPU or GPU | ~2 GB |
| M-SMALL | Cheap classification/routing (optional) | `Qwen/Qwen2.5-3B-Instruct` or `microsoft/Phi-4-mini-instruct` | llama.cpp CPU | ~3 GB |

Minimum viable hardware: 1× 24 GB GPU (RTX 3090/4090) or Apple Silicon 32–64 GB unified memory. CPU-only fallback works with 3B models at reduced throughput.

## 7. Technology Stack

- **Agent framework:** LangGraph (Python) — explicit state machines per agent; deterministic control flow around LLM nodes.
- **Serving:** vLLM (Linux+NVIDIA) or llama.cpp/Ollama (Mac/CPU), OpenAI-compatible endpoint at `http://model-gw:8000/v1`.
- **MCP servers:** Python `mcp` SDK (FastMCP), one repo per server, HTTP-SSE transport inside the cluster.
- **API Gateway/UI backend:** FastAPI + Pydantic v2; React + Tailwind frontend; WebSocket for live dashboards.
- **Storage:** PostgreSQL 16 (system of record), Qdrant (vectors), MinIO (documents/artifacts), Redis 7 (queue, cache, locks).
- **AuthN/Z:** Keycloak (OIDC) with roles: `ceo, director, manager, hr, finance, admin, ops, support, employee`. Agents get service accounts with least-privilege tool scopes.
- **Deployment:** Docker Compose (single node) → optional k3s later. All images pinned; offline-capable registry mirror.
- **Observability:** OpenTelemetry traces (every task_id = trace), Prometheus + Grafana, Loki logs. LLM calls logged with prompt/response hashes (full text stored encrypted, PII-redacted views for debugging).

## 8. Security & Compliance Baseline

- Prompt-injection defense: all retrieved/user content wrapped as data; tool allowlists per agent; MCP servers validate every input against Pydantic schemas; no agent can call `mcp-approvals.approve` (humans only).
- PII: employee/candidate PII encrypted at rest (pgcrypto columns), masked in logs, RAG chunks tagged with ACLs and filtered at query time by requesting agent's scope.
- Money movement: FIN-1 can *prepare* bank files (NEFT/NACH format) but export requires two human approvals (maker-checker) via `mcp-approvals`.
- Backups: nightly pg_dump + MinIO snapshot to encrypted external disk; restore drill quarterly.

## 9. Phased Delivery Plan

- **Phase 1 (weeks 1–6):** Data layer + mcp-erp + mcp-audit + mcp-approvals; ORCH-0; SUP-1 ticket fabric; ADM-1 core (assets, people DB, dashboard v1). Milestone: tickets flow end-to-end with agent triage.
- **Phase 2 (weeks 7–12):** FIN-1 (payroll engine, slips, ledger, billing, tax tables for India FY 2026-27); HR-1 (resume RAG, shortlisting, negotiation prep). Milestone: one full payroll cycle in shadow mode, reconciled against manual run.
- **Phase 3 (weeks 13–18):** OPS-1 (project health, timelines, coding assistant with M-CODE); external connectors (job boards, email); per-department LoRA fine-tuning if eval gaps justify it. Milestone: exec dashboard fed by all five agents; go-live with HITL gates.

## 10. Document Map

- `01-MODEL-SELECTION.md` — SLM shortlist, quantization, serving, fine-tuning path
- `02-AGENT-ORCH-0.md` — Orchestrator
- `03-AGENT-ADM-1.md` — Admin · `04-AGENT-HR-1.md` — HR · `05-AGENT-OPS-1.md` — Operations · `06-AGENT-FIN-1.md` — Finance · `07-AGENT-SUP-1.md` — Support
- `08-MCP-TOOLS-SPEC.md` — All MCP servers & tool schemas
- `09-DATA-INFRA-SECURITY.md` — DB schema, deployment, HITL, evals, runbooks
