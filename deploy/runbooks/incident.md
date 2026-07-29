# Incident response runbook

Doc 12 §6 exit checklist: "on-call & escalation defined." This is that
definition, plus the concrete steps for this specific stack.

## Severity

Borrow ticket priority semantics (`config/sla.yaml`) rather than inventing
a parallel scale:

| Severity | Meaning | Example | First response |
|---|---|---|---|
| S1 | Platform down or data-integrity risk | Postgres unreachable, an agent writing incorrect financial data, a HITL gate bypassed | 15 min (matches `config/sla.yaml` P1) |
| S2 | A single agent/MCP server down, others unaffected | `mcp-finance` container crash-looping | 1h (matches P2) |
| S3 | Degraded but functioning | Slow LLM responses, one dashboard panel stale | 4h (matches P3) |

## First steps (any severity)

1. `docker compose -f deploy/docker-compose.dev.yml ps` — which containers
   are actually down vs. just slow. A container that's `Up` but
   unresponsive is a different problem than one that's `Restarting`.
2. Check Grafana (`http://localhost:3001`, `AWP / Agents` dashboard) for
   the failed-task and error-rate panels — narrows "what" before you
   start reading logs for "why."
3. `docker compose logs --tail 100 <service>` for the specific
   container, or the Loki datasource in Grafana for a cross-container
   search (`{container=~"deploy-.*-1"} |= "error"`).
4. Check `DEVIATIONS.md` for a matching known issue before assuming
   you've found a new bug — several real, still-open environmental
   issues are already documented there (Docker-internal DNS flakiness
   under host load, Docker Desktop API strain on memory-constrained
   hosts — see `degraded-cpu-mode.md`).

## Kill-switch (blast-radius control)

If a specific agent is doing something wrong and needs to stop consuming
new work *without* losing already-queued tasks or forcing a redeploy:

```bash
python scripts/kill_switch.py on HR-1     # HR-1 stops pulling new tasks;
                                           # already-queued ones wait
python scripts/kill_switch.py status      # see every agent's state
python scripts/kill_switch.py off HR-1    # resume
```

This flips a Redis flag `TaskBus.consume` polls every 2s (`shared/awp_shared/bus.py`)
— no container restart, no task loss, no partial processing. It stops
*new* consumption only; a task already mid-graph when the switch flips
finishes normally.

## Escalation

`config/sla.yaml`'s existing ladder (`notify_manager_and_dashboard` at
100% of SLA, `notify_director_ceo_incident_channel` for P1) is the
ticket-level escalation path SUP-1's SLAWarden already runs in code. For
a platform incident (not a single ticket), that same three-tier shape
applies to people: assignee/on-call engineer → engineering lead → CEO/
director, matching the P1 ladder's own escalation targets. This build has
no on-call *roster* or paging integration (PagerDuty/Opsgenie/etc.) —
doc 08 §6's `external_send` gate is Phase-3-only and nothing pages a
human today; who's on-call is a real-world staffing decision to make
before go-live, not something this repo can encode.

## Rollback

See `model-upgrade.md` for the blue/green model-swap rollback and
`restore-drill.md` for a full data restore. For a bad application
deploy (not data, not a model): `docker compose -f
deploy/docker-compose.dev.yml up -d --build <service>` against a
previous git commit is the rollback mechanism this build has — there is
no separate release/rollback tooling (no CD pipeline exists; `.github/workflows/ci.yml`
only runs lint/type/unit checks, doc 12 §4's full CD scope was never
built).
