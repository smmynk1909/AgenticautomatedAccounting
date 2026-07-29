# Load testing — doc 10 §6 NFR table, doc 12 §4 CI (`k6 smoke (50 VU, 5 min)`)

Requires [k6](https://k6.io/) (not a repo dependency — a separate binary,
same as this repo treats `docker`/`psql` as host tools it shells out to,
not something `uv sync` installs).

```bash
BASE_URL=http://localhost:8000 k6 run loadtest/smoke.js
BASE_URL=http://localhost:8000 k6 run loadtest/ticket_volume.js
```

## What each NFR row is covered by

| doc 10 §6 NFR | Covered by | Notes |
|---|---|---|
| p95 interactive turn < 12s | `smoke.js` | Read endpoints only (tickets list, dashboard) — see `smoke.js`'s header for why chat/codeassist (LLM calls) are deliberately excluded from a *load* test. |
| classifier < 1.5s | *Not covered here* | SUP-1's ticket classifier is an internal agent-graph step, not a gateway HTTP endpoint — nothing to point k6 at directly. Best measured via `awp_agent_task_duration_seconds{agent="SUP-1",intent="triage_ticket"}` in Grafana (`deploy/observability/`) during real traffic, not a synthetic k6 run. |
| 50 concurrent users | `smoke.js` | `stages` ramp to and hold 50 VUs. |
| 1,000 tickets/day | `ticket_volume.js` | Scaled-rate burst/soak proxy, not a literal 24h run — see the script's header comment for the exact scaling. |
| payroll 500 employees < 10 min | *Not covered here* | `payroll_run` is an async, approval-gated, multi-step FIN-1 workflow (compute → maker-checker approval → disbursement) — not a synchronous request a k6 VU can usefully drive. Its own timing is what `scripts/shadow_diff.py`'s shadow-run cycles measure directly (elapsed wall-clock for a real `compute_payroll` call against a real 500-employee dataset); that number belongs in the Sprint 11 payroll-shadow-cycle write-up (`DEVIATIONS.md`), not a k6 script. |

## Why no CI wiring yet

Doc 12 §4 names an `e2e.yml` workflow running "k6 smoke (50 VU, 5 min)"
against a compose-up CPU profile. `.github/workflows/ci.yml` exists, but
only runs ruff/mypy/pytest against the workspace directly — it never
`docker compose up`s the 24-service stack (Ollama alone needs a model
pull), so there's nothing for a k6 job to point at yet. Standing up a
full-stack `e2e.yml` (compose up, wait for health, `k6 run smoke.js`,
compose down) is real, separate infrastructure work — deliberately not
added here rather than guessed at. `make loadtest-smoke` (see `Makefile`)
is the manual entry point until that CI job exists.
