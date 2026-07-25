# 04 — Agent Spec: HR-1 (Human Resources Agent)

**Purpose:** Candidate sourcing (internal DB + external platforms), CV/resume auditing, keyword+semantic shortlisting, salary-negotiation preparation and in-band negotiation support, HR ticket handling, and training-needs management per manager/candidate against market requirements.

**Model binding:** planner=M-GEN · extraction=M-SMALL (JSON-constrained) · shortlist rerank=M-RERANK (Phase 2+)
**RAG scopes:** `hr_policies`, `resumes` (candidate corpus), `market_intel` (salary benchmarks, skill-trend notes), `training_catalog`.

---

## 1. Sub-agents
| Sub-agent | Function |
|---|---|
| HR-1a Sourcer | Search internal candidate DB + external connectors; ingest new profiles |
| HR-1b ResumeAuditor | Parse, structure, verify-consistency, and score CVs |
| HR-1c Shortlister | Rank candidates for a role (keyword + semantic + policy filters) |
| HR-1d NegotiationDesk | Prepare negotiation packs; draft offer communications (HITL) |
| HR-1e TrainingPlanner | Skill-gap analysis per employee/manager vs market; training plans & tracking |
| HR-1f TicketHandler | HR-category tickets (leave, policy queries, grievances → human fast-path) |

## 2. Workflows

### 2.1 Sourcing (HR-1a)
Trigger: `source_candidates {role_id, jd_text|jd_ref, count, sources[]}`.
```
1. Parse JD → RoleProfile JSON: {must_have[], nice_to_have[], min_exp, max_ctc_band, location, keywords[]}
   (M-GEN, guided_json; recruiter confirms RoleProfile once per role — cached)
2. Internal: mcp-search.search_candidates(hybrid: BM25 keywords + M-EMB vectors, filters: status≠blacklisted, notice≤X)
3. External (Phase 3, via mcp-hrsourcing connectors — e.g., job-board APIs/exports the company is licensed to use):
   fetch profiles → normalize → RegistryKeeper ingest pipeline (ADM-1b dedupe applies)
   ⚠ Compliance: only sources with valid API terms; no scraping that violates platform ToS; consent flag stored per profile.
4. Output: sourcing report (count by source, top-N preview) → recruiter + dashboard.
```

### 2.2 Resume Audit (HR-1b)
Input: resume file (pdf/docx) → `mcp-docs.extract_text` → M-SMALL extraction to **CandidateProfile schema**:
```json
{"name":"","contact":{},"total_exp_months":0,"positions":[{"org":"","title":"","from":"","to":"","skills":[]}],
 "education":[],"certifications":[],"skills_normalized":[],"gaps":[{"from":"","to":"","months":0}],
 "red_flags":[{"type":"overlap|inconsistent_dates|title_inflation_signal|unverifiable_claim","evidence":""}],
 "audit_score":{"completeness":0,"consistency":0,"relevance_to_role":null}}
```
Rules: every red flag must cite verbatim evidence spans; the agent flags, humans judge — **no auto-rejection on red flags**; skill normalization against a controlled vocabulary table (`skills_master`) to make shortlisting deterministic downstream.

### 2.3 Shortlisting (HR-1c)
Deterministic-first, LLM-last:
```
score = 0.35*keyword_coverage(must_have)      [code]
      + 0.25*semantic_similarity(JD, resume)  [M-EMB + M-RERANK]
      + 0.20*experience_fit                   [code, band function]
      + 0.10*recency_of_relevant_skills       [code]
      + 0.10*audit_score.consistency          [from 2.2]
Hard filters first (location/notice/ctc band/work-auth). LLM writes a 3-line
justification per shortlisted candidate citing profile fields (no new facts).
```
Output: ranked shortlist + justifications + diversity/compliance note → recruiter approval gate `shortlist_publish` before any candidate is contacted. **Fairness rule:** protected attributes (age, gender, religion, marital status) are excluded from features and masked in LLM context; quarterly bias audit compares shortlist rates across masked cohorts (doc 09 §6).

### 2.4 Salary Negotiation (HR-1d)
The agent **prepares and drafts; humans negotiate final numbers.** External sending of any offer/counter is HITL-gated.
```
prepare_negotiation {candidate_id, role_id} →
  NegotiationPack:
   - band: role salary band (policy table) + internal parity check (peers ±1 grade, anonymized aggregates)
   - market: benchmark range from market_intel corpus (with source + as-of date)
   - candidate: current/expected CTC, competing offers (if disclosed), leverage notes
   - recommendation: open / target / walk-away numbers + non-cash levers (joining bonus, LTA, learning budget, remote days)
   - talk track: 5 objection-response pairs
Gate: pack visible only to roles {hr, director}. Any drafted email to candidate →
request_approval('offer_communication') with the exact final text frozen at approval.
```
Chat-assist mode: recruiter pastes candidate's counter → agent returns options within approved band; if counter exceeds band → auto-escalate to Director with parity impact analysis. The agent must never disclose band ceilings, other employees' salaries, or internal walk-away numbers in any candidate-facing draft (output filter checks drafts against a denylist of pack fields).

### 2.5 Training & Market-Requirement Management (HR-1e)
```
Quarterly (scheduled) + on-demand per manager:
1. Build SkillMatrix per team: employees' skills_normalized vs RoleProfile of their
   current+next-grade role vs market_intel trend tags.
2. Gap report per employee: {skill, current_level, target_level, market_demand_score, evidence}
3. Match gaps → training_catalog (internal courses, licensed platforms) → draft plan
   {courses, hours, cost, quarter} → manager approval gate 'training_plan'
4. Track: enrollment, completion, post-assessment; nudges via mcp-comms;
   compliance % feeds manager dashboard (ADM-1d).
market_intel corpus upkeep: monthly ingestion job (curated reports/JD samples the
company licenses or collects) → tagged, dated; every market claim in outputs cites
corpus doc id + as-of date. No claims from model memory.
```

### 2.6 HR Tickets (HR-1f)
Leave balance queries, policy Q&A (RAG with citation to policy section), letter requests (employment/offer/relieving letters via mcp-docs templates, approval-gated). **Grievance/harassment category:** agent does zero triage content-processing beyond routing — immediate private escalation to designated human HR + confidentiality lock on the ticket.

## 3. Tools (MCP)
`mcp-erp`: candidates/employees read-write (scoped), roles, salary_bands (read), tickets.
`mcp-search`: search_candidates (hybrid), search_kb (policies, market_intel), upsert_documents (resume chunks).
`mcp-hrsourcing`: extract_resume, connector_fetch(source, query), normalize_profile.
`mcp-docs`: extract_text, render_pdf/docx (letters, packs, reports).
`mcp-approvals`: gates `shortlist_publish`, `offer_communication`, `training_plan`, `letter_issue`.
`mcp-comms`: notify_user, draft_external_email (draft-only object; sending is a human click).
`mcp-audit`: log_event.

## 4. System prompt skeleton (`prompts/hr1.md`)
```
You are HR-1, the HR agent. You prepare, analyze, and draft; humans decide on
people. Rules:
1. Facts about candidates come only from their profile/tool results; cite fields.
2. Never auto-reject; red flags are surfaced with evidence for human judgment.
3. Never reveal salary bands, peer salaries, or walk-away numbers in candidate-
   facing text. Check every draft against the confidential-fields list.
4. Exclude protected attributes from all evaluations and hide them from context.
5. Market claims require a market_intel citation with date; otherwise say unknown.
6. Grievance-class tickets: route to human immediately, process no content.
7. External platform use only through approved connectors; respect source ToS.
```

## 5. Acceptance tests
1. Resume extraction F1 ≥ 0.92 on a 50-resume labeled set (fields: dates, orgs, skills); date-overlap red-flag detection recall ≥ 0.9.
2. Shortlist determinism: same inputs → same ranking (LLM only writes justifications).
3. Negotiation draft containing a band ceiling number → blocked by output filter test.
4. Masked-cohort shortlist parity within tolerance on synthetic bias suite.
5. Grievance keyword ticket → routed to human < 60 s, no LLM summary stored.
