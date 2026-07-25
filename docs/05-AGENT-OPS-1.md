# 05 — Agent Spec: OPS-1 (Operations Agent)

**Purpose:** Track employee work and utilization, monitor project execution, surface delivery issues and key timelines, and provide a local coding assistant to engineering.

**Model binding:** planner=M-GEN · coder=M-CODE · classifier=M-SMALL
**RAG scopes:** `project_docs` (SOWs, specs, meeting notes), `eng_kb` (internal code conventions, runbooks), repo code index (per-project, ACL'd).

---

## 1. Sub-agents
| Sub-agent | Function |
|---|---|
| OPS-1a WorkTracker | Employee work status, timesheet sanity, utilization & allocation views |
| OPS-1b ProjectMonitor | Project health: scope/milestones/burn vs plan; weekly health reports |
| OPS-1c DeliveryRisk | Delivery-issue detection, key-timeline radar, escalation |
| OPS-1d CodeAssist | Coding assistant (chat + repo-aware) on M-CODE |

## 2. Workflows

### 2.1 Employee Work Tracking (OPS-1a)
Data in: timesheets (`work_logs` table), task systems (Gitea/issue tracker via mcp-projects), leave calendar (HR data, read-scoped aggregate only).
```
Daily job:
- Missing/anomalous timesheets (0h on workday, >14h day, project mismatch vs allocation) → gentle nudge (mcp-comms) → 3 misses → manager dashboard flag
- Utilization view per employee/team: billable vs internal vs bench (SQL views; LLM writes the weekly narrative only)
- Allocation intent `assign_employee_project {emp_id, project_id, %, from, to}`:
  check availability & skill match (skills_master vs project needs) → conflict? → propose alternatives → manager approval gate 'allocation_change' → commit
```
**Privacy stance:** no keystroke/screen surveillance; tracking is deliverable- and timesheet-based only. Individual-level reports visible to the employee's manager chain + the employee themself.

### 2.2 Project Monitoring (OPS-1b)
Project record: `{project_id, client, sow_ref, milestones[{id,title,due,acceptance_criteria,status}], budget_hours, team[], risks[]}`.
```
Weekly health report per active project (scheduled Mon):
1. Pull: milestone status, hours burned vs budget (work_logs), open issues by severity,
   scope-change log, last client-communication date
2. Compute (code): schedule variance, burn variance, milestone-at-risk list
   (due within 14d & <70% linked tasks done)
3. M-GEN drafts report: status summary, top risks with evidence links, asks for
   decisions needed. RAG cites project_docs for commitments.
4. RAG-verified: every claimed commitment/date must resolve to a doc/DB reference.
5. Publish to manager + roll worst-3 to ADM-1 exec dashboard.
```

### 2.3 Delivery Issues & Key Timeline Radar (OPS-1c)
```
Timeline radar (daily): union of {milestone due dates, contract renewal dates,
invoice-trigger dates (→ FIN-1), compliance/report deadlines} within 30 days →
ranked by (impact × proximity) → dashboard 'Key Timelines' panel.
Issue intake: from tickets (category=delivery), from ProjectMonitor variance
thresholds, from client-email summaries (Phase 3 mcp-comms ingestion).
Issue object: {project, description, impact(schedule|quality|scope|cost),
severity, owner, mitigation_options[], decision_needed_by}
Severity S1 (client-facing slip on committed date): immediate escalation to
Director + CEO dashboard, and creates a SUP-1 cross-functional ticket if another
department is needed (e.g., FIN-1 for invoice hold, HR-1 for emergency staffing).
```

### 2.4 Coding Assistant (OPS-1d)
Served to engineers via chat UI + optional editor endpoint (OpenAI-compatible so IDE plugins like Continue work against it).
```
Modes:
- chat: Q&A grounded in eng_kb + selected repo context (embeddings over code via
  mcp-projects.index_repo; retrieval by file path/symbol/semantic)
- review: diff in → structured review out {bugs[], security[], style[], tests_missing[]}
  referencing line numbers; never auto-commits
- generate: function/test/boilerplate generation; output framed as patch suggestion
- explain/refactor: selected code + instruction
Guardrails: read-only repo access by default; write = suggested-patch artifact the
engineer applies; secrets scanner runs on all context before it reaches the model
(no .env/credentials in prompts); per-project ACL — an engineer only reaches repos
they're allocated to.
```

## 3. Tools (MCP)
`mcp-erp`: employees (scoped read), work_logs CRUD, allocations, projects/milestones CRUD (scoped), tickets, push_dashboard_item.
`mcp-projects`: list_repos, index_repo, search_code, get_file, get_diff, issue-tracker CRUD, ci_status.
`mcp-search`: search_kb (project_docs, eng_kb).
`mcp-docs`: render_pdf/docx (health reports), render_xlsx (utilization).
`mcp-approvals`: gates `allocation_change`, `timeline_commitment_change`.
`mcp-comms`: notify_user, meeting-notes ingestion (Phase 3).
`mcp-audit`: log_event.

## 4. System prompt skeletons
`prompts/ops1.md` (planner): facts from tools only; every risk claim carries an evidence link; no client-facing communication without approval; timeline commitments can be *reported*, never *changed*, without the `timeline_commitment_change` gate.
`prompts/ops1-code.md` (M-CODE): follow eng_kb conventions; produce runnable, tested code; flag security issues (OWASP top-10 awareness); never include secrets; when uncertain about APIs, say so rather than inventing.

## 5. Acceptance tests
1. Health report numbers = SQL ground truth; all commitments cite a doc/DB ref (0 uncited commitments in 20-report audit).
2. Milestone-at-risk detector: precision ≥ 0.8 on historical backtest set.
3. CodeAssist: HumanEval-style internal suite pass@1 ≥ baseline of raw M-CODE (RAG must not degrade); secrets scanner blocks 100% of seeded credentials.
4. S1 issue → Director notification + dashboard flag < 2 min.
5. Engineer without ACL to repo X gets zero code context from X (leakage test).
