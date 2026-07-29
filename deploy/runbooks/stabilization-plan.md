# 30-day stabilization plan

Doc 12 §5 Sprint 12: "Go-live (HITL-max settings) + 30-day stabilization
plan." Doc 12 §6 exit checklist: "30-day rollback plan documented" — this
covers both: the monitoring/relaxation cadence *and* the rollback plan,
since in this build they're the same document (relaxing a gate and
rolling one back are opposite directions of the same lever:
`config/gates.yaml` + `AWP_HITL_MAX`).

## Starting posture (day 0)

- `AWP_HITL_MAX=true` — every `expense_posting` fires its approval gate,
  no amount/confidence auto-post (see `tools_ledger.py`'s module
  docstring). Every other gate in `config/gates.yaml` already fires
  unconditionally, so this is the *only* lever this plan needs for
  "maximum HITL."
- All 6 agents running normally (no kill-switches engaged).
- Grafana (`deploy/observability/`) and the daily audit-chain check
  (`scheduler/awp_scheduler/auditcheck.py`) are the two automated
  watchers; everything else in this plan is a human reviewing their
  output on a cadence.

## Weekly cadence

| Week | What to review | What "healthy" looks like | Action if not |
|---|---|---|---|
| 1 | `AWP / Agents` + `AWP / LLM` Grafana dashboards daily. Every `expense_posting` approval queue (`GET /api/approvals/inbox`) — confirm none are timing out unactioned. | Error rate <1% per agent (`awp_mcp_tool_calls_total{status!="ok"}`), no approval backlog, no kill-switch engaged. | Engage the kill-switch (`incident.md`) for the specific agent, not the whole platform, while investigating. |
| 2 | Same dashboards, daily → every-other-day. First red-team corpus re-run (`make redteam-live`) against live traffic patterns, not just the 5-case starter set. | Same as week 1, plus: 0 privilege escalations in the red-team re-run. | Do not relax anything; extend week 1's cadence until resolved. |
| 3 | Dashboards 2-3x/week. Reconcile one full week of `expense_posting` approvals against what a human would have decided without the gate (spot-check, not every case) — this is the actual evidence for whether the threshold-based auto-post (pre-`AWP_HITL_MAX`) logic was trustworthy. | Spot-check agreement rate high enough that the department head sanctions relaxing the threshold (a business judgment call, not a numeric formula this repo defines). | Keep `AWP_HITL_MAX=true` at least one more week. |
| 4 | Dashboards weekly. Decision point: relax `AWP_HITL_MAX` to `false` (falls back to the original amount<25000/confidence>0.8 auto-post thresholds) or keep it. | Dept-head (finance_head) sign-off obtained. | Keep `AWP_HITL_MAX=true` indefinitely until sign-off happens — there's no time-based auto-relaxation; a human decides. |

## Rollback triggers (any time in the 30 days, not just week boundaries)

Roll back — don't wait for the weekly review — if:

- **Audit chain tamper detected** (`auditcheck.py`'s daily job pages
  `director`/`admin_head` automatically): treat as a security incident
  per `incident.md`'s S1 path, not a stabilization hiccup.
- **A HITL gate is bypassed** (an action posted without a valid approval
  token where `config/gates.yaml` requires one) — this should be
  structurally impossible (`verify_approval_token` is called inline by
  every gated tool, not a middleware that could be missed), so seeing it
  happen at all means investigate the code path immediately, don't just
  re-gate and move on.
- **Error rate on any single agent exceeds 5%** sustained over 15 min
  (Grafana `AWP / Agents` panel) — kill-switch that agent
  (`scripts/kill_switch.py on <AGENT>`), investigate, resume once fixed.
- **A red-team case that previously passed starts failing** — treat the
  regression as a live incident, not a flaky test.

## Rollback mechanics

1. **Single agent misbehaving**: `scripts/kill_switch.py on <AGENT>` —
   tasks queue, nothing lost, other agents unaffected. This is the
   *first* response for almost everything, since it's reversible and
   scoped.
2. **A bad code deploy**: `docker compose -f deploy/docker-compose.dev.yml
   up -d --build <service>` against the previous git commit (see
   `incident.md` — this build has no separate CD/release tooling to
   automate this).
3. **A bad model upgrade**: `model-upgrade.md`'s rollback section (point
   config back at the previous model tag).
4. **Data corruption**: `restore-drill.md` — restore from the most recent
   clean backup. This is the last resort, not the first response, given
   its RTO (minutes, per the live-verified drill) is still slower than a
   kill-switch flip (seconds).

## End of the 30 days

The plan's exit is doc 12 §6's checklist being fully checked — not just
this document's own items but the whole list in `go-live-checklist.md`.
If items still can't be checked after 30 days (e.g. payroll's 2 shadow
cycles need 2 real months regardless of how confident anyone is), extend
the plan rather than declaring stabilization complete on a deadline
alone; doc 12 §6's list is a set of conditions, not a countdown timer.
