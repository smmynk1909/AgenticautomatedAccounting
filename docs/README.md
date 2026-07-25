# Agentic Workforce Platform — Documentation Set

End-to-end design documentation for a fully local, multi-agent internal operations system (Admin, HR, Operations, Finance, Support) built on open-source SLMs from Hugging Face, MCP tool servers, and a LangGraph orchestration layer.

| # | Document | Contents |
|---|----------|----------|
| 00 | MASTER-ARCHITECTURE | Principles, topology, agent roster, inter-agent comms, stack, phased plan |
| 01 | MODEL-SELECTION | SLM pool (Qwen2.5 family + BGE), quantization, serving, LoRA-per-department path |
| 02 | AGENT-ORCH-0 | Orchestrator/router: intent registry, plan schema, validation, scheduling |
| 03 | AGENT-ADM-1 | Admin: assets, people registry, admin tickets, executive dashboard |
| 04 | AGENT-HR-1 | HR: sourcing, resume audit, shortlisting, negotiation, training, fairness rules |
| 05 | AGENT-OPS-1 | Operations: work tracking, project health, delivery risk, coding assistant |
| 06 | AGENT-FIN-1 | Finance: payroll, ledger, billing, tax, FP&A — deterministic FinCore + LLM orchestration |
| 07 | AGENT-SUP-1 | Support: ticket fabric, routing, SLA, status freshness, top-issues reporting |
| 08 | MCP-TOOLS-SPEC | All 9 MCP servers, tool schemas, scopes, approval-token mechanics |
| 09 | DATA-INFRA-SECURITY | DB schema, Docker deployment, security/injection defense, HITL gates, eval program, build order |
| 10 | HLD | Architectural decisions (AD-01..10), C4 context & container views, data flows DF-1..5, NFR table, capacity, risks |
| 11 | LLD | Implementation contracts: shared-lib signatures, agent/MCP skeletons, FinCore functions, REST/WS API, sequences, DDL details, config contracts, resilience matrix |
| 12 | SOLUTIONING-REPO | Requirement traceability, complete monorepo file tree, coding standards, CI/CD, 12-sprint plan with DoD, production-grade exit checklist, Cowork build instructions |

**How to use with Cowork / Claude Code:** follow the sprint plan in doc 12 §5 (supersedes 09 §8). Per session: load docs 10 (HLD) + 11 (LLD) + 12 (repo contract) plus the specific agent/MCP doc being implemented; generate files exactly at the tree paths in 12 §2; implement LLD signatures verbatim; write the acceptance tests first, then code to green.

**Key architectural decisions (read first):**
1. One shared model pool + role-configured agents (optionally LoRA adapters later) — not five separate fine-tuned models on day one.
2. LLMs never compute money or set policy; deterministic services do; LLMs orchestrate, extract, and draft.
3. Human approval is cryptographic (approval tokens verified by MCP servers), not prompt-based.
4. Support's ticket fabric and the audit log are shared infrastructure built first.
