# 10 — HIGH-LEVEL DESIGN (HLD)

**Project:** Agentic Workforce Platform (AWP) · **Version:** 1.0 · **Status:** Approved-for-build
**Traceability:** Requirements → 00-MASTER-ARCHITECTURE §1; Models → 01; Agents → 02–07; Tools → 08; Data/Sec → 09; LLD → 11; Repo → 12.

---

## 1. Solution Overview

AWP is a locally hosted multi-agent system that executes the internal operations of an IT services & product company across Admin, HR, Operations, Finance, and Support. It is composed of six autonomous agent runtimes (1 orchestrator + 5 department agents), nine MCP tool servers, a deterministic finance engine, a shared data platform, and a web application, all served by a pool of open-source SLMs (Qwen2.5 family + BGE) running on a single on-prem GPU server.

## 2. Architectural Style & Rationale

| Decision | Choice | Rationale | Rejected alternative |
|---|---|---|---|
| AD-01 | Layered: UI → Gateway → Agents → MCP → Data/Models | Clear trust boundaries; agents can't bypass tool layer | Agents with direct DB drivers (unauditable) |
| AD-02 | Shared model pool + role-configured agents | Fits 24 GB VRAM; single maintenance surface | 5 fine-tuned models (5× VRAM, 5× drift) |
| AD-03 | LangGraph explicit state machines | Deterministic control flow; resumable; testable | Free-running ReAct loops (unbounded) |
| AD-04 | MCP (JSON-RPC/HTTP-SSE) as sole capability boundary | Uniform auth/audit/validation; language-agnostic | Ad-hoc REST per service |
| AD-05 | Redis Streams task bus for agent↔agent delegation | Durable, at-least-once, consumer groups | Direct LLM↔LLM chat (chatty, lossy) |
| AD-06 | Deterministic FinCore for all money math | Correctness, auditability, CA sign-off | LLM arithmetic (unacceptable risk) |
| AD-07 | Cryptographic approval tokens for HITL | Injection-proof by construction | Prompt-level "ask permission" (bypassable) |
| AD-08 | PostgreSQL single system of record + Qdrant vectors + MinIO blobs | Boring, restorable, RLS-capable | Polyglot microservice DBs |
| AD-09 | Docker Compose single node (k3s optional later) | Matches "one server/laptop" requirement | Kubernetes-first (overhead) |
| AD-10 | OpenAI-compatible model gateway | Swap models/servers without agent code change | Direct HF pipeline embedding in agents |

## 3. Context Diagram (C4 Level 1)

```
[Employees/Managers] ──┐
[HR/Finance/Admin staff]├── HTTPS ──► [AWP Web App] ──► [API Gateway]
[CEO/Directors]  ──────┘                                    │
                                                            ▼
[Company CA (human)] ◄── worksheets/registers ──── [AWP Core (agents+MCP+data)]
[Bank portal (human-operated)] ◄── disbursement files (manual upload) ─┘
[Licensed job-board APIs] ◄── mcp-hrsourcing connectors (Phase 3, whitelisted)
[Email server (SMTP/IMAP)] ◄── mcp-comms (internal notify; external = human-send)
[Gitea (in-cluster)] ◄── mcp-projects (read + patch suggestions)
```
External surfaces are deliberately minimal: no cloud LLM, no banking API, no auto external email in Phases 1–2.

## 4. Container Diagram (C4 Level 2) — deployable units

| # | Container | Tech | Responsibility | Depends on |
|---|---|---|---|---|
| C1 | web | React 18 + Vite + Tailwind | Dept consoles, chat, exec dashboard, approvals inbox | C2 |
| C2 | gateway | FastAPI + WebSocket | AuthN (OIDC), RBAC, REST/WS API, SSE dashboard feed | C3,C10,Keycloak |
| C3 | agent-orch0 … agent-sup1 (6) | Python 3.12, LangGraph | Agent runtimes; task-bus consumers | C4–C12, Redis, model-gw |
| C4 | mcp-erp | FastMCP | People/assets/tickets/tasks/dashboard/policies | Postgres, Redis |
| C5 | mcp-finance | FastMCP + fincore lib | Deterministic finance tools | Postgres, MinIO |
| C6 | mcp-docs | FastMCP + WeasyPrint/openpyxl/Tesseract | Extract/render/store documents | MinIO |
| C7 | mcp-search | FastMCP | RAG, hybrid search, embeddings, clustering | Qdrant, Postgres, tei-emb |
| C8 | mcp-approvals | FastMCP + JOSE | HITL gates, token minting (human UI approves) | Postgres, Keycloak |
| C9 | mcp-comms | FastMCP | Internal notify, drafts/outbox, slip distribution | SMTP, Postgres |
| C10 | mcp-audit | FastMCP | Append-only event log, hash-chain, queries | Postgres |
| C11 | mcp-hrsourcing | FastMCP | Resume extraction/normalization, source connectors | C6,C7, model-gw |
| C12 | mcp-projects | FastMCP | Repo read, code index, issues, CI status, patch artifacts | Gitea, Qdrant |
| C13 | model-gw | nginx | Route /v1 by model name | C14–C16 |
| C14 | vllm-gen (+vllm-code Ph3) | vLLM | M-GEN / M-CODE serving (AWQ) | GPU |
| C15 | llamacpp-small | llama.cpp server | M-SMALL (CPU) | — |
| C16 | tei-emb | HF TEI | M-EMB embeddings | CPU/GPU |
| C17 | scheduler | APScheduler svc | Crons → task bus | Redis |
| C18 | infra | Postgres16, Redis7, Qdrant, MinIO, Keycloak, Gitea | Platform | — |
| C19 | observability | Prometheus, Grafana, Loki, otel-collector | Metrics/logs/traces | all |

## 5. Primary Data Flows (HLD sequences; step-level detail in LLD §6)

**DF-1 Interactive request:** User → web → gateway (JWT) → target agent inbox (Redis) → agent LangGraph run → MCP tool calls → response → gateway WS → user. All hops carry `trace_id`.

**DF-2 Cross-department goal (onboarding):** HR-1 emits `onboard_employee` → ORCH-0 plans DAG → fan-out tasks → dept agents execute (each with own approvals) → ORCH-0 aggregates → dashboard + requester.

**DF-3 Payroll (money path):** scheduler → FIN-1 → `freeze_payroll_inputs` → `compute_payroll` (FinCore) → anomaly pass → slips render → `request_approval(payroll_run, n=2)` → humans approve in web → token minted → `generate_disbursement_file(token)` → vault URI → human uploads to bank → journal post → slips distributed.

**DF-4 Ticket lifecycle:** any channel → SUP-1a classify → route (matrix) → owning agent resolves via its tools → events → SUP-1c summary refresh → SLA timers (code) → close on requester confirm.

**DF-5 RAG query:** agent → mcp-search (caller scope attached) → server-side ACL filter → hybrid retrieve (+rerank) → chunks with citation ids → agent must cite → faithfulness checker in evals.

## 6. Non-Functional Requirements (binding)

| NFR | Target | Verified by |
|---|---|---|
| Availability | 99% business hours, single node | uptime probe, monthly report |
| Latency | p95 interactive turn < 12 s; classifier < 1.5 s | k6 + eval harness |
| Throughput | 50 concurrent users; 1,000 tickets/day; payroll 500 employees < 10 min | load test |
| Durability | RPO 24h (nightly backup), RTO 4h | quarterly restore drill |
| Security | 0 privileged actions from red-team suite; RLS on PII | CI red-team job |
| Auditability | 100% tool calls logged; daily hash-chain verifiable | audit verifier job |
| Accuracy | Payroll parity to the rupee (2 shadow cycles); TB always balanced | shadow diff, DB invariant |
| Tool-call validity | ≥ 98% schema-valid LLM tool calls | eval suite gate |
| Model swap | New checkpoint behind gateway with zero agent code change | swap drill |

## 7. Environments & Promotion
`dev` (laptop, Ollama, seeded synthetic co.) → `staging` (prod hardware clone or same box separate compose project, shadow mode) → `prod`. Promotion gate: full eval suite + red-team pass + human sign-off (FIN/HR changes require dept head). Config via `.env` per environment + mounted `config/*.yaml`; no secrets in git.

## 8. Capacity & Sizing (prod-min)
RTX 4090 24 GB: M-GEN AWQ ~7 GB + KV budget 6 GB (≈8 concurrent 8k-ctx streams) + M-CODE loaded Phase 3 via swap or second GPU. RAM 64 GB (Postgres 8, Qdrant 6, services 12, cache/headroom). Disk 2 TB NVMe (models 60 GB, DB growth ~5 GB/yr @500 emp, MinIO docs ~50 GB/yr). CPU 16 cores (llama.cpp M-SMALL pinned to 6).

## 9. Risks & Mitigations
R1 SLM tool-call errors → constrained decoding + validator retry loop (LLD §5.4) + M-GEN fallback for M-SMALL failures. R2 GPU single point of failure → CPU degraded mode auto-switch (M-SMALL everywhere), queue-park for heavy drafting. R3 Tax-rule drift → versioned tables + CA PR review + period-guard in FinCore. R4 Prompt injection via resumes/tickets → layered defense 09§4, structural approvals. R5 Scope creep into external autonomy → external_send stays gated behind Phase-3 whitelist decision.

## 10. HLD Acceptance
This HLD is satisfied when: all C1–C19 containers deploy from `deploy/docker-compose.yml` on prod-min hardware; DF-1..DF-5 demonstrated end-to-end on seeded data; NFR table verified by the listed methods; every AD decision reflected in code structure per doc 12.
