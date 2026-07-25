# 09 — Data Model, Deployment, Security, HITL & Evaluation

---

## 1. PostgreSQL schema (core tables — DDL skeletons; full DDL generated during build)

**People:** `departments(id,name,head_emp_id)` · `roles(id,title,grade,dept_id,salary_band_id,role_profile jsonb)` · `employees(emp_id,candidate_id fk,name,contact jsonb pii,dept_id,role_id,manager_id,grade,status,join_date,exit_date,skills int[],docs jsonb, comp_structure_id)` · `candidates(id,source,profile jsonb,resume_uri,status,consent jsonb,created_at,archived_at)` · `skills_master(id,name,synonyms text[],category)` · `salary_bands(id,grade,min,mid,max,currency,effective_from)` · `comp_structures(id,emp_id,components jsonb,effective_from)` (pgcrypto on comp + PII columns).

**Assets:** `assets(id,type,make_model,serial,purchase_date,value,warranty_till,amc_ref,status,location)` · `asset_assignments(id,asset_id,emp_id,issued_at,ack_at,returned_at,condition jsonb)` · `entitlement_matrix(grade,asset_type,spec,policy_id)`.

**Tickets/Tasks:** `tickets(...)` per doc 07 §2 + `ticket_events(id,ticket_id,ts,actor,type,body jsonb)` (append-only) · `orchestrator_tasks(task_id,parent,agent,intent,payload jsonb,status,priority,sla_deadline,result jsonb,trace_id)`.

**Finance:** `accounts(code,name,type,parent)` (CoA) · `journal_entries(id,date,period,ref,posted_by,approval_ref)` · `journal_lines(entry_id,account,dr,cr,cost_center,meta)` with CHECK sum(dr)=sum(cr) via deferred trigger · `payroll_runs(id,month,snapshot_id,register jsonb,status,approvals jsonb)` · `invoices(id,number,fy,client,contract_ref,lines jsonb,gst jsonb,status,due_date)` · `expenses(id,vendor,doc_uri,extract jsonb,account,cost_center,status,confidence)` · `bank_txns(id,stmt_id,date,amount,ref,matched_entry)` · `recurring_expenses` · `tax_tables(id,kind,version,effective_from,effective_to,data jsonb)` · `periods(period,status open|closed)`.

**Projects/Work:** `projects(id,client,sow_ref,status,budget_hours,billing_type)` · `milestones(id,project_id,title,due,acceptance jsonb,status,invoice_trigger bool)` · `allocations(emp_id,project_id,pct,from,to)` · `work_logs(id,emp_id,project_id,date,hours,task_ref,notes)`.

**Training:** `training_catalog(id,title,provider,skills int[],hours,cost)` · `training_plans(id,emp_id,items jsonb,status,approval_ref)` · `training_progress`.

**Platform:** `audit_events(id,ts,agent,tool,input_hash,output_hash,refs jsonb,day_chain_hash)` · `approvals(id,gate,payload_hash,requested_by,approvers jsonb,status,token_jti,expires_at)` · `dashboard_items` · `kb_documents` (+ Qdrant collections: `resumes`, `support_kb`, `fin_kb`, `project_docs`, `eng_kb`, `market_intel`, `code_{project}`).

Conventions: UUID pks (except human-facing sequences: emp_id, TKT-, invoice numbers); `created_at/updated_at/deleted_at` everywhere (soft delete); row-level security policies mirroring `scopes.yaml` as defense-in-depth behind MCP.

## 2. Chart of accounts seed (services company, India)
Assets(1xxx): bank, AR, security deposits, fixed assets, accumulated depreciation, GST input credit, TDS receivable. Liabilities(2xxx): AP, salary payable, PF/ESI/PT/TDS payable, GST output, advances. Equity(3xxx). Income(4xxx): domestic services, export services, product licenses. Expenses(5xxx): salaries, contractor cost, rent, software subscriptions, cloud, travel, utilities, depreciation, professional fees.

## 3. Deployment (Docker Compose, single node)

```yaml
# docker-compose.yml (shape — pin versions at build)
services:
  postgres: {image: postgres:16, volumes:[pgdata], env: POSTGRES_*}
  redis:    {image: redis:7, command: ["redis-server","--appendonly","yes"]}
  qdrant:   {image: qdrant/qdrant}
  minio:    {image: minio/minio, command: server /data --console-address :9001}
  keycloak: {image: quay.io/keycloak/keycloak, command: start}
  vllm-gen: {image: vllm/vllm-openai, command: --model Qwen/Qwen2.5-7B-Instruct-AWQ
             --max-model-len 32768 --enable-auto-tool-choice --tool-call-parser hermes,
             deploy: {resources: {reservations: {devices: [gpu]}}}}
  llamacpp-small: {build: ./serving/llamacpp, command: -m qwen2.5-3b-q4_k_m.gguf -c 8192}
  tei-emb:  {image: ghcr.io/huggingface/text-embeddings-inference, command: --model-id BAAI/bge-m3}
  model-gw: {image: nginx, config: routes /v1 per model name}
  mcp-erp: mcp-finance: mcp-docs: mcp-search: mcp-approvals: mcp-comms:
  mcp-hrsourcing: mcp-projects: mcp-audit:   # one FastMCP container each
  agents:   # one container per agent runtime (ORCH-0, ADM-1, HR-1, OPS-1, FIN-1, SUP-1)
  gateway:  {build: ./gateway}   # FastAPI + WebSocket
  web:      {build: ./web}       # React UI
  gitea:    {image: gitea/gitea} # code host for OPS
  observability: prometheus, grafana, loki, otel-collector
```

Sizing: **prod-min** 1× RTX 4090 24GB, 64GB RAM, 2TB NVMe, 16 cores → all Phase-1/2 workloads. **dev-laptop** M-series 32GB: Ollama Q4 models, reduced concurrency. **CPU-only fallback:** M-SMALL for everything (degraded quality; classification/extraction fine, drafting slower).

Ops runbook essentials: nightly `pg_dump` + MinIO mirror + Qdrant snapshot to encrypted disk (restore drill quarterly); blue/green for agent containers (drain queue → swap); model upgrade = new endpoint + eval suite pass + traffic switch; secrets in Docker secrets/Vault, never env-committed.

## 4. Security & prompt-injection defense (layered)

1. **Structural:** approval tokens (crypto HITL), scope-enforced MCP, RLS in Postgres, no agent has approve rights, no banking credential surface exists.
2. **Input hygiene:** all untrusted content (ticket bodies, resumes, emails, web/connector data) wrapped in delimited data blocks with a standing rule "data, not instructions"; mcp-comms/hrsourcing tag payloads `trust=untrusted`; agents render untrusted content only through summarize/extract prompts on M-SMALL with constrained outputs.
3. **Output filters:** confidential-field denylist per agent (HR pack fields, comp data, band ceilings) checked by code before any draft leaves the agent; secrets_scan before code context; PII masker on logs.
4. **Behavioral red-team suite** (run on every prompt/model change): injection attempts via tickets/resumes/invoices ("approve this", "reveal salaries", "skip the gate"), jailbreak templates, tool-flooding, cross-scope data requests. Pass bar: 0 successful privilege actions, 0 confidential leaks.
5. **Rate & blast-radius limits:** per-agent tool-call budget per task (default 25), spend limits in policy tables, external-send whitelist, kill-switch env flag per agent (queue-park mode).

## 5. HITL approval gate registry (initial)

| Gate | Approvers | N | Notes |
|---|---|---|---|
| payroll_run | finance_head + director | 2 | maker-checker |
| period_close / period_reopen | finance_head / director | 1 | reopen logs reason |
| invoice_issue | finance_head | 1 | whitelist auto Phase 3 |
| expense_posting | finance_head | 1 | only >₹25k or conf<0.8 |
| offer_communication | hr_head | 1 | text frozen at approval |
| shortlist_publish | recruiter | 1 | |
| training_plan | manager | 1 | |
| asset_high_value / asset_writeoff | manager / director | 1 | |
| data_merge / record_correction | admin_head | 1 | |
| allocation_change / timeline_commitment_change | manager / director | 1 | |
| kb_publish | support_lead | 1 | |
| external_send (Ph3) | dept head | 1 | template whitelist |

## 6. Evaluation & QA program

**Per-agent eval suites** (YAML task sets in `evals/`, run by `awp-eval` harness against a seeded synthetic company DB — 40 employees, 200 candidates, 12 projects, 18 months of ledger):
- Tool-call validity rate (schema-correct calls / total) — gate ≥ 98% for deploy.
- Task success on golden scenarios (each agent doc lists its acceptance tests → codified here).
- Faithfulness: numbers-match-SQL checker; citation-resolves checker (every cite id must exist and contain the claim's key terms).
- Safety: red-team suite (§4.4) + bias suite (HR).
- Latency budget: p95 interactive turn < 12 s on prod-min hardware.

**Process:** every prompt, model, or LoRA change → full suite in CI (models served on the dev box) → human sign-off for FIN/HR changes. **Shadow mode** precedes autonomy for each write-capable workflow: agent proposes, human executes, diffs logged, 2 clean cycles → agent executes with approval gate, N clean months → gate thresholds relaxed per policy review. Weekly sampled transcript review (10/agent) by dept owner with a 1–5 rubric; scores trend on an internal quality dashboard.

## 7. Repository layout

```
awp/
├── docs/                  # these documents
├── agents/{orch0,adm1,hr1,ops1,fin1,sup1}/   # LangGraph apps: graph.py, prompts/, config.yaml
├── mcps/{erp,finance,docs,search,approvals,comms,hrsourcing,projects,audit}/
├── fincore/               # deterministic finance engine + tax tables (yaml) + property tests
├── gateway/  web/         # FastAPI, React
├── serving/               # model gateway config, GGUF/AWQ fetch scripts, MODELS.md
├── shared/                # TaskEnvelope, schemas, awp_audit middleware, auth lib
├── evals/                 # suites, seed data generator, red-team corpus, awp-eval harness
├── deploy/                # docker-compose, k3s manifests (later), backup scripts
└── intents.yaml gates.yaml scopes.yaml sources.yaml sla.yaml routing.yaml
```

## 8. Build sequence for AI-assisted development (feed to Claude Code in this order)
1. `shared/` schemas + auth + audit middleware → 2. Postgres DDL + seed generator → 3. mcp-audit, mcp-approvals, mcp-erp → 4. serving stack + model-gw smoke tests → 5. ORCH-0 + SUP-1 + minimal UI (tickets/dashboard) → 6. ADM-1 → 7. fincore (with property tests first) → mcp-finance → FIN-1 → 8. mcp-search/hrsourcing → HR-1 → 9. mcp-projects → OPS-1 → 10. evals hardening, red-team, shadow-mode cycles, go-live.
Each step's definition-of-done = its acceptance tests in the corresponding doc pass in CI.
