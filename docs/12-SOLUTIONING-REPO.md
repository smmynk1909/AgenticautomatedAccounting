# 12 — SOLUTIONING DOCUMENT & REPOSITORY STRUCTURE

**Purpose:** The build contract. Maps requirements → components → concrete files, defines the full monorepo tree (every file Cowork/Claude Code should generate), coding standards, CI, and the sprint-by-sprint execution plan with definitions of done.

---

## 1. Requirement → Solution Traceability

| Req (user statement) | Solution component | Docs | Key files |
|---|---|---|---|
| Open-source SLM from HF, runs locally | Qwen2.5 pool via vLLM/llama.cpp behind OpenAI-compatible gateway | 01,10-AD02/10 | `serving/*`, `config/models.yaml` |
| Admin: devices, internal DB, tickets, exec dashboard | ADM-1 (4 sub-agents) + mcp-erp + dashboard views | 03,08 | `agents/adm1/*`, `mcps/erp/*` |
| HR: negotiation, sourcing, CV audit, shortlist, training | HR-1 (6 sub-agents) + mcp-hrsourcing + mcp-search | 04,08 | `agents/hr1/*`, `mcps/hrsourcing/*` |
| Ops: work/project tracking, delivery, timelines, coding assistant | OPS-1 + mcp-projects + M-CODE | 05,08 | `agents/ops1/*`, `mcps/projects/*` |
| Finance: slips, disbursement, accounting, requirements, bills, tax, opex | FIN-1 + FinCore + mcp-finance | 06,11§4 | `fincore/*`, `mcps/finance/*`, `agents/fin1/*` |
| Support: tickets, cross-functional, status, top reports | SUP-1 ticket fabric | 07 | `agents/sup1/*` |
| Multi-agent network, agents communicate via API/tools | Task bus + MCP layer | 00§5,10-AD04/05 | `shared/awp_shared/bus.py`, `mcps/*` |
| Multiple MCPs + tools on MCPs + native connectors | 9 MCP servers, source registry connectors | 08 | `mcps/*`, `config/sources.yaml` |
| Production grade | HITL tokens, audit chain, RLS, evals, red-team, shadow mode, observability, backups | 09,10§6,11§9 | `evals/*`, `deploy/*`, `mcps/approvals/*`, `mcps/audit/*` |

## 2. Monorepo Tree (generate exactly this; ✱ = Phase 2, ✱✱ = Phase 3)

```
awp/
├── README.md                          # quickstart, arch summary, doc links
├── Makefile                           # make dev|test|eval|up|seed|migrate|redteam
├── pyproject.toml                     # uv workspace root (members: shared,fincore,mcps/*,agents/*,gateway,scheduler)
├── .env.example                       # all env vars documented
├── .pre-commit-config.yaml            # ruff, ruff-format, mypy, detect-secrets
├── .github/workflows/
│   ├── ci.yml                         # lint→unit→contract→graph tests, coverage gates
│   ├── e2e.yml                        # compose-up matrix, DF-1..5 scenarios
│   └── evals.yml                      # nightly + on prompts/models change: awp-eval + red-team
│
├── docs/                              # ← this documentation set (00–12)
│
├── config/
│   ├── intents.yaml  gates.yaml  scopes.yaml  routing.yaml  sla.yaml
│   ├── models.yaml   entitlements.yaml  shortlist.yaml  sources.yaml  roles.yaml
│   └── schema/                        # JSON-schemas for each yaml (boot validation)
│
├── shared/
│   ├── pyproject.toml
│   └── awp_shared/
│       ├── __init__.py  schemas.py  auth.py  bus.py  llm.py  mcpc.py
│       ├── trust.py  audit_mw.py  config.py  intent_models.py   # payload models per intent
│       ├── errors.py  tracing.py   # OTel helpers
│       └── tests/ (unit per module)
│
├── db/
│   ├── alembic.ini
│   ├── migrations/versions/           # 0001_people … 0009_platform (per 09§1/11§7)
│   ├── ddl/                           # reference SQL: triggers, RLS policies, views
│   │   ├── trg_balance.sql  rls_policies.sql  dashboard_views.sql  reporting_views.sql
│   └── seed/
│       ├── generate_synthetic.py      # 40 emp/200 cand/12 proj/18mo ledger (evals dep)
│       ├── coa_seed.yaml  skills_master.yaml  policies_seed.yaml
│
├── fincore/
│   ├── pyproject.toml
│   └── fincore/
│       ├── payroll.py  tax.py  ledger.py  invoice.py  depreciation.py  cashflow.py
│       ├── tables.py  models.py       # frozen dataclasses/pydantic for snapshots
│       ├── tax_tables/                # YAML per FY: it_slabs_2026_27.yaml, pf.yaml, esi.yaml,
│       │                              #   pt_states.yaml, gst_rates.yaml, tds_sections.yaml
│       └── tests/
│           ├── test_properties.py     # hypothesis invariants (11§4)
│           └── golden/                # per-FY golden registers, regime comparisons
│
├── mcps/
│   ├── _base/                         # make_server, middlewares, uow, repo base (11§3)
│   ├── erp/
│   │   ├── server.py  tools_people.py  tools_assets.py  tools_tickets.py
│   │   ├── tools_tasks.py  tools_dashboard.py  tools_policies.py
│   │   ├── repos/ (employee.py asset.py ticket.py task.py)
│   │   ├── dedupe.py  state_machine.py   # ticket transitions
│   │   └── tests/ (contract per tool: schema, scope-denial, idempotency, gates)
│   ├── finance/
│   │   ├── server.py  tools_payroll.py  tools_ledger.py  tools_billing.py
│   │   ├── tools_tax.py  tools_recon.py  tools_close.py  repos/ledger.py
│   │   └── tests/ (incl. gate-bypass red tests)
│   ├── docs/    ├── server.py tools_extract.py tools_render.py tools_store.py
│   │            ├── templates/ (salary_slip_v1.html invoice_gst_v1.html issuance_form_v1.html
│   │            │              offer_letter_v1.docx.j2 project_health_v1.html negotiation_pack_v1.html)
│   │            └── tests/ (golden PDFs hash-compare)
│   ├── search/  ├── server.py tools_kb.py tools_candidates.py tools_vectors.py
│   │            ├── chunking.py acl.py hybrid.py rerank.py ✱  └── tests/ (ACL leak tests)
│   ├── approvals/ ├── server.py gates.py tokens.py  # mint on human approve only
│   │              └── tests/ (token forgery/replay/expiry/payload-mismatch)
│   ├── comms/   ├── server.py tools_notify.py tools_outbox.py tools_slips.py
│   │            ├── inbox_poll.py ✱✱  templates/  └── tests/
│   ├── audit/   ├── server.py chain.py verifier.py spool.py  └── tests/ (tamper detection)
│   ├── hrsourcing/ ✱ ├── server.py tools_resume.py tools_connectors.py normalize.py
│   │                 ├── connectors/ (internal_db.py csv_import.py <board_x>.py ✱✱)
│   │                 └── tests/ (extraction F1 harness vs labeled set)
│   └── projects/ ✱✱ ├── server.py tools_repo.py tools_index.py tools_issues.py
│                    ├── code_chunking.py secrets_scan.py patch_artifacts.py └── tests/
│
├── agents/
│   ├── _base/                         # AgentApp, AgentState, nodes.py, checkpointer (11§2)
│   ├── orch0/
│   │   ├── main.py  graph.py  planner.py  intent_registry.py  validators.py
│   │   ├── prompts/ (system.md plan.md triage.md)  config.yaml
│   │   └── tests/ (acceptance 02§9 as graph tests w/ mocked MCP+LLM fixtures)
│   ├── sup1/    graph.py intake.py router.py statuskeeper.py slawarden.py reporter.py
│   │            prompts/ config.yaml tests/ (07§6)
│   ├── adm1/    graph.py assetkeeper.py registry.py tickets.py dashboard.py
│   │            prompts/ config.yaml tests/ (03§6)
│   ├── fin1/ ✱  graph.py payroll_flow.py bookkeeper.py biller.py taxdesk.py fpna.py
│   │            anomaly.py prompts/ config.yaml tests/ (06§7)
│   ├── hr1/ ✱   graph.py sourcer.py auditor.py shortlister.py negotiation.py
│   │            training.py tickets.py output_filter.py  # confidential denylist
│   │            prompts/ config.yaml tests/ (04§5 incl. bias suite hooks)
│   └── ops1/ ✱✱ graph.py worktracker.py projectmonitor.py deliveryrisk.py codeassist.py
│                prompts/ (system.md code.md) config.yaml tests/ (05§5)
│
├── scheduler/
│   ├── main.py  jobs.yaml             # crons → TaskEnvelope dispatch (02§7)
│   └── tests/
│
├── gateway/
│   ├── main.py  deps.py  routers/ (chat.py tasks.py tickets.py dashboard.py
│   │            approvals.py files.py uploads.py payroll.py reports.py)
│   ├── ws.py  sse.py  rbac.py  ratelimit.py
│   └── tests/ (API contract via schemathesis, RBAC matrix)
│
├── web/
│   ├── package.json  vite.config.ts  tailwind.config.ts
│   └── src/
│       ├── app/ (routes: /chat /tickets /dashboard /approvals /payroll /projects /people /assets)
│       ├── components/ (TicketBoard ApprovalCard DashboardPanel ChatStream FileDrop …)
│       ├── api/ (generated client from OpenAPI)  auth/ (oidc)  ws/
│       └── e2e/ (Playwright: approve-payroll, ticket-lifecycle, dashboard-roles)
│
├── serving/
│   ├── modelgw/nginx.conf             # /v1 routing by model name (config/models.yaml)
│   ├── fetch_models.sh                # HF download + sha pin → MODELS.md update
│   ├── llamacpp/Dockerfile  vllm/args.md  MODELS.md
│   └── smoke/test_toolcall.py         # gateway tool-call round-trip per model
│
├── evals/
│   ├── awp_eval/ (harness: runner.py checkers.py fixtures.py report.py)
│   ├── suites/ (orch0.yaml adm1.yaml hr1.yaml ops1.yaml fin1.yaml sup1.yaml)
│   ├── checkers: numbers_match_sql.py citations_resolve.py toolcall_validity.py
│   ├── redteam/ (corpus/ injections tickets|resumes|invoices, runner.py)  bias/ (hr_suite.py)
│   └── labeled/ (resumes_50/ gst_invoices_100/ tickets_300/  — synthetic, generated+reviewed)
│
├── deploy/
│   ├── docker-compose.yml  docker-compose.dev.yml  docker-compose.cpu.yml
│   ├── keycloak/realm-export.json  postgres/init.sql  minio/policies.json
│   ├── observability/ (prometheus.yml grafana-dashboards/ loki.yml otel-collector.yml
│   │                   grafana: agents.json llm.json tickets.json finance.json)
│   ├── backup/ (backup.sh restore.sh verify_chain.sh)   # nightly cron on host
│   └── runbooks/ (model-upgrade.md restore-drill.md incident.md go-live-checklist.md
│                  degraded-cpu-mode.md secrets-rotation.md)
│
└── scripts/
    ├── dev_bootstrap.sh               # compose dev up → migrate → seed → smoke
    ├── shadow_diff.py                 # payroll shadow vs manual comparator (06§7.1)
    └── gen_openapi_client.sh
```

## 3. Coding standards (enforced by CI)
Python: ruff (line 100), full type hints, mypy strict on `shared/ fincore/ mcps/_base`; async-first; Pydantic models for every boundary; no bare dict crossing module boundaries; no `print` (structlog). Prompts are versioned files (`prompts/*.md`) with front-matter `{version, model, sampling_profile, changelog}` — prompt change = PR = eval run. Money: `Decimal` only inside fincore, `NUMERIC` in DB, never float. Web: TS strict, generated API client only (no hand-written fetch). Commits: conventional; every PR links a doc section it implements.

## 4. CI/CD pipeline (maps 11§10)
```
ci.yml:    ruff → mypy → unit (shared,fincore) → contract (mcps, testcontainers-postgres/redis)
           → graph tests (agents, mocked LLM fixtures) → coverage gates (95/85/edges-100)
e2e.yml:   compose up (cpu profile, M-SMALL only) → migrate+seed → DF-1..5 pytest scenarios
           → Playwright core flows → k6 smoke (50 VU, 5 min)
evals.yml: serve models on GPU runner (self-hosted) → awp-eval suites → red-team → bias(HR)
           → gates: toolcall≥98%, safety 0-fail, per-agent acceptance green → publish report artifact
Deploy:    tag → build/push images (local registry) → staging compose → shadow checks → manual prod promote
```

## 5. Execution plan (sprints of 2 weeks; DoD = listed tests green in CI)

| Sprint | Deliverables | DoD |
|---|---|---|
| S1 | shared/, config schemas, db migrations 0001-0009, seed generator, mcp-audit, mcp-approvals | token forgery/replay tests green; chain verifier; seed produces eval fixtures |
| S2 | mcp-erp (people/assets/tickets/tasks/dashboard), serving stack + model-gw, smoke | all erp contract tests; tool-call smoke on M-GEN & M-SMALL |
| S3 | ORCH-0 + SUP-1 + scheduler + gateway core + web (tickets, chat, approvals inbox) | 02§9 & 07§6 acceptance; DF-1/DF-4 e2e |
| S4 | ADM-1 + mcp-docs + dashboard v1 | 03§6 acceptance; DF-2 partial (admin leg); Playwright ticket flow |
| S5 ✱ | fincore + mcp-finance | property/golden 95% cov; ledger fuzz invariant |
| S6 ✱ | FIN-1 flows (payroll shadow, expenses, month-close) + payroll UI | 06§7.1 shadow diff harness runs; DF-3 e2e in staging |
| S7 ✱ | mcp-search + mcp-hrsourcing + HR-1 (audit, shortlist) | 04§5.1-2; extraction F1 harness vs labeled set |
| S8 ✱ | HR-1 (negotiation, training) + output_filter + bias suite | 04§5.3-4; red-team HR pack leak = 0 |
| S9 ✱✱ | mcp-projects + OPS-1 (tracker, monitor, risk) | 05§5.1-2,4; DF-2 full onboarding fan-out e2e |
| S10 ✱✱ | CodeAssist + IDE endpoint + secrets scan | 05§5.3,5; eng pilot feedback loop |
| S11 | Hardening: full red-team, load, restore drill, runbooks, go-live checklist | NFR table (10§6) fully verified; 2 clean payroll shadow cycles |
| S12 | Go-live (HITL-max settings) + 30-day stabilization plan | production sign-off per runbooks/go-live-checklist.md |

## 6. Definition of "Production Grade" (exit checklist)
☐ All 10§6 NFRs measured & met ☐ 0 red-team privilege escalations ☐ Payroll parity 2 cycles ☐ Restore drill < RTO ☐ Audit chain verifies daily ☐ RBAC matrix test 100% ☐ Runbooks reviewed by ops owner ☐ CA sign-off on tax tables ☐ Dept-head sign-off per agent ☐ Kill-switch drill executed ☐ On-call & escalation defined ☐ 30-day rollback plan documented.

## 7. Cowork/Claude Code build instructions
Work sprint order (§5). Per task: load docs 10+11+12 + the relevant agent/MCP doc; generate files exactly at the tree paths in §2; implement signatures from LLD verbatim; write the doc-listed acceptance tests **first**, then code to green; never invent tools/scopes/gates not in docs 08/config — propose doc PRs instead; keep prompts in files with front-matter; run `make test` locally before proposing completion.
