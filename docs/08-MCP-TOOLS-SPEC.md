# 08 — MCP Servers & Tool Specification

**Scope:** Every MCP server, its tools, schemas, scoping model, and implementation notes. Implementation: Python `mcp` SDK (FastMCP), HTTP-SSE transport, one container per server, Pydantic v2 validation on every input/output.

---

## 0. Cross-cutting conventions

- **Auth:** every MCP request carries a service-account JWT (`agent_id`, `scopes[]`). Servers enforce scopes per tool (declared in `scopes.yaml`); a call outside scope returns `PERMISSION_DENIED` and an audit event. Humans acting via UI get user JWTs with role scopes.
- **Idempotency:** all write tools accept `idempotency_key` (usually `task_id:step`); replays return the original result.
- **Errors:** structured `{code, message, retryable, details}`; codes: `VALIDATION`, `NOT_FOUND`, `PERMISSION_DENIED`, `CONFLICT`, `APPROVAL_REQUIRED`, `UPSTREAM`, `INTERNAL`.
- **Approval tokens:** tools marked 🔒 require `approval_token` (JWT minted by mcp-approvals binding: gate, payload_hash, approver(s), expiry 24h, single-use). Server verifies signature + payload hash match — approval is cryptographic, not conversational.
- **Audit:** every tool call auto-emits to mcp-audit (middleware): `{ts, agent_id, tool, input_hash, output_hash, ticket/task refs, latency}`.
- **PII:** responses support `?view=masked|full`; `full` requires scope `pii.read.<domain>`.

---

## 1. mcp-erp — People, Assets, Tickets, Tasks, Dashboard

### People
- `get_employee(emp_id, view)` / `query_employees(filters, page)` — filters: dept, status, grade, skills, manager.
- `upsert_employee(record, idempotency_key)` 🔒gate `record_correction` when mutating historical/identity fields; scope: ADM-1b, HR-1 (subset).
- `get_candidate` / `query_candidates(filters)` / `upsert_candidate(record)` — upsert runs dedupe pipeline; merge conflicts return `CONFLICT` with proposal id.
- `propose_merge(record_a, record_b, evidence)` 🔒`data_merge` → merged record.
- `convert_candidate_to_employee(candidate_id, emp_fields)` 🔒`onbodin g` gate; preserves lineage.

### Assets
- `query_assets(filters)` · `get_asset(asset_id)` (history included)
- `reserve_asset(asset_id, emp_id, ttl_h)` → reservation id (Redis lock + row)
- `assign_asset(reservation_id, ack_required)` 🔒`asset_high_value` if value>threshold
- `return_asset(asset_id, condition_report)` · `writeoff_asset(asset_id, reason)` 🔒`asset_writeoff`
- `asset_audit_report(scope)` → structured report object

### Tickets (fabric)
- `create_ticket(ticket)` → id; `get_ticket` · `query_tickets(filters)` (scope-filtered: dept agents see their categories, SUP-1 sees all, confidential only to authorized humans)
- `append_ticket_event(ticket_id, event)` · `update_ticket(ticket_id, patch)` — status transitions validated by state machine; illegal transition → `VALIDATION`
- `link_tickets(parent, children[])` · `set_summary(ticket_id, text)` (SUP-1c only)

### Tasks (bus state)
- `dispatch_task(envelope)` (ORCH-0 only) · `claim_task(agent_id)` · `update_task(task_id, status, result)` · `get_task_status(task_id|parent)`

### Dashboard
- `push_dashboard_item(item)` — validated `{audience_roles[], panel, severity, title, body≤400ch, action_link, expires_at, source}`
- `get_dashboard(role)` (UI backend)

### Policy tables (read-only tools)
- `get_policy(policy_id)` · `query_policies(domain)` — entitlement matrix, spend thresholds, SLA table, routing matrix, approval-gate policy.

## 2. mcp-finance — FinCore wrapper (all math deterministic)

- `compute_payroll(month, employee_scope)` → register `{lines[{emp_id, earnings{}, deductions{}, net}], totals, tax_table_version}`; pure function over frozen inputs snapshot id.
- `freeze_payroll_inputs(month)` → snapshot_id (locks attendance/comp data for the run)
- `generate_disbursement_file(register_id)` 🔒`payroll_run`(2-approver) → MinIO vault URI (AES-encrypted)
- `post_journal(entry{date, lines[{account, dr, cr, cost_center, ref}]}, idempotency_key)` — must balance; 🔒`expense_posting` above threshold or below confidence; period must be open.
- `get_trial_balance(period)` · `get_ledger(account, range)` · `get_pnl(period)` · `get_balance_sheet(date)`
- `reconcile_bank(statement_file_uri)` → `{auto_matched[], suggestions[], unmatched[]}`; `confirm_matches(ids[])` 🔒`recon_confirm` (human)
- `compute_invoice(contract_ref, items[], gst_context)` → invoice object; `issue_invoice(invoice_id)` 🔒`invoice_issue` → gapless number + AR posting
- `compute_tds_projection(emp_id, fy, regime, declarations)` · `compare_regimes(emp_id, fy)`
- `gst_worksheet(period, return_type)` · `advance_tax_estimate(fy, quarter)`
- `run_depreciation(period)` · `close_period(period)` 🔒`period_close` · `reopen_period` 🔒`period_reopen`
- `cashflow_model(horizon_weeks, scenario)` → rows + assumptions (each row sourced)

## 3. mcp-docs — Documents

- `extract_text(file_uri, ocr=auto)` → text + layout blocks (pdfplumber/pypdf + Tesseract fallback)
- `render_pdf(template_id, data, output_scope)` — templates: `salary_slip_v1`, `issuance_form_v1`, `invoice_gst_v1`, `offer_letter_v1`, `project_health_v1`, `negotiation_pack_v1` (Jinja2+WeasyPrint); `output_scope` controls who can fetch the artifact.
- `render_docx(template_id, data)` · `render_xlsx(spec)` (openpyxl; spec = sheets/tables/formats)
- `store_file(bytes|uri, scope, retention)` → MinIO URI · `get_file(uri)` (scope-checked)

## 4. mcp-search — RAG & Vector Ops (Qdrant + Postgres FTS)

- `upsert_documents(corpus, docs[{id, text, metadata{acl_tags, department_scope, as_of}}])` — chunking (600-token, 80 overlap), M-EMB embeddings, hybrid index. 🔒`kb_publish` when corpus=support_kb.
- `search_kb(corpus, query, filters, k)` → chunks with scores + citations `{doc_id, span}`; **server-side ACL filter on caller scope — non-bypassable.**
- `search_candidates(role_profile, filters, k)` — hybrid BM25+dense (+rerank if enabled); returns candidate ids + evidence spans, protected attributes stripped.
- `search_code(project_id, query, k)` (delegates to mcp-projects index) — repo ACL enforced.
- `embed(texts[])` · `cluster(vectors|ids, method)` (Reporter trend mining)

## 5. mcp-approvals — Human-in-the-Loop Gates

- `request_approval(gate, payload, approver_roles[], n_required, expiry_h)` → approval_id; renders card in approver UI (payload rendered read-only; free-text comment allowed).
- `get_approval_status(approval_id)` → `pending|approved|rejected|expired` (+ token when approved)
- Human-only UI endpoints (NOT MCP tools): approve/reject. **No agent scope can ever approve** — enforced structurally.
- Gate registry (`gates.yaml`): gate → required roles, n_required, payload schema, token TTL. Changing gates itself requires `sla_table_change`-style admin approval + git PR.

## 6. mcp-comms — Notifications & Messaging

- `notify_user(user_id, channel(app|email), message, ref)` — internal only, template-based
- `send_reminder(user_id, ticket/task_ref, schedule)` · `incident_broadcast(severity, message, roles[])`
- `draft_external_email(to, subject, body, ref)` → draft object in outbox UI; **sending is a human click** (Phase 3: `send_external` 🔒`external_send` for whitelisted templates like invoice delivery)
- `distribute_slip(emp_id, file_uri)` — employee-scoped secure link
- Phase 3 ingestion: `poll_inbox(mailbox)` → normalized messages (content flagged untrusted for prompt-injection handling)

## 7. mcp-hrsourcing — Resume & External Sourcing

- `extract_resume(file_uri)` → raw text + layout; `normalize_profile(raw, schema=CandidateProfile)` (calls M-SMALL internally with guided JSON; returns confidence per field)
- `connector_fetch(source_id, query, limit)` — source registry (`sources.yaml`): API endpoint, auth ref (secrets vault), ToS notes, rate limits, consent handling. Ships with `internal_db` and `csv_import`; external boards added per license.
- `skill_normalize(terms[])` → skills_master ids (fuzzy + synonym table)

## 8. mcp-projects — Code & Delivery

- `list_repos(scope)` · `get_file(repo, path, ref)` · `get_diff(repo, base, head)` (read-only Gitea API)
- `index_repo(repo)` → code chunks to vector index (tree-sitter aware chunking); `search_code(repo|project, query)`
- `issues_crud` (tracker), `ci_status(repo, ref)`
- `suggest_patch(repo, base_ref, patch, rationale)` → patch artifact for human application (no direct commits)
- `secrets_scan(text|diff)` → findings; called by OPS-1d pipeline before any code reaches a model context.

## 9. mcp-audit — Immutable Event Log

- `log_event(event)` → append-only table + daily hash-chain (each day's Merkle root stored; tamper-evident)
- `query_events(filters)` (auditor/human scope) · `export_audit(range)` 🔒admin
- Middleware library `awp_audit` auto-instruments all servers; direct log_event for agent-level decisions (plan chosen, escalation fired).

---

## 10. Scope matrix (excerpt — full `scopes.yaml` in repo)

| Tool group | ORCH-0 | ADM-1 | HR-1 | OPS-1 | FIN-1 | SUP-1 |
|---|---|---|---|---|---|---|
| erp.people write | – | ✔ | partial | – | – | – |
| erp.assets write | – | ✔ | – | – | – | – |
| erp.tickets | route | own cats | own cats | own cats | own cats | all |
| finance.* | – | – | – | read invoices trig. | ✔ | – |
| docs.render | – | ✔ | ✔ | ✔ | ✔ | ✔ |
| search.candidates | – | – | ✔ | – | – | – |
| projects.* | – | – | – | ✔ | read | – |
| comms.external draft | – | – | ✔ | ✔ | ✔ | – |
| approvals.request | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ |
| approvals.approve | **none — humans only** ||||||
