# Go-live checklist

Doc 12 §6's exit checklist, verbatim, checked honestly against this
build's actual state as of this writing — not aspirationally. An
unchecked item here is either a real gap or a live-verification step
this session deliberately deferred (server-hosted testing, per this
session's own scope decision); either way, don't flip it to checked
without actually doing the thing.

- [ ] **All 10§6 NFRs measured & met.** `loadtest/` (k6 smoke +
      ticket-volume scripts) and `deploy/observability/` (Grafana panels
      to read the results off of) exist and are ready to run — not yet
      run. The classifier-latency and payroll-500-employees rows have no
      direct load-test path at all (see `loadtest/README.md`'s table);
      those need a real timed run against real data.
- [ ] **0 red-team privilege escalations.** Only 1 of 5 starter corpus
      cases (`cross_scope`) has completed a clean live run
      (`DEVIATIONS.md` #23); the other 4 were blocked by host
      instability, not by a known failure. The 5-case corpus itself is
      also a starting point, not exhaustive coverage of doc 09 §4's
      threat categories — expect to grow it before this is a credible
      "0" claim.
- [ ] **Payroll parity 2 cycles.** `scripts/shadow_diff.py` (the
      comparator) is complete and unit-correct; running it for 2 real
      consecutive months against real manual-payroll reference data has
      not happened — there is no manual-payroll reference data in this
      dev environment. This is a business-process gate (needs a real
      payroll cycle and a real person's manual computation to diff
      against), not a code task.
- [x] **Restore drill < RTO.** Live-verified: 26s vs. a 4h RTO budget
      (`DEVIATIONS.md` #24). Postgres only — MinIO/Qdrant restore is
      unverified (`restore-drill.md` explains why that's a smaller gap
      than it sounds).
- [x] **Audit chain verifies daily.** Live-verified against real data:
      `compute_day_root` run for 2026-07-28 (6605 real audit events,
      root `594fb1d5...`), then the exact `verify_audit_chain_daily`
      function ran against the live `mcp-audit` server and confirmed
      `tampered=False` with the stored and recomputed roots matching
      exactly. The scheduled job itself (`scheduler/awp_scheduler/main.py`,
      redis-deduped once per UTC day) is running live in the rebuilt
      `scheduler` container and will fire on its own natural 24h
      cadence — this check proves the verification logic and escalation
      wiring are correct against real data, not that the cron trigger
      itself has fired unattended yet (it hasn't had a full day to).
      The tamper-detected/escalation branch is covered by
      `test_auditcheck.py`'s unit tests (deliberately not reproduced
      live — corrupting real audit_events rows to prove a negative
      would be reckless against a real database).
- [x] **RBAC matrix test 100%.** `gateway/awp_gateway/tests/test_rbac.py`
      exhaustively covers every role `config/roles.yaml` defines against
      every resource `rbac.py` gates: ticket category visibility (15
      roles × 12 categories, individually asserted, not just row-sum
      equality), dashboard visibility (15×15 role pairs), and payroll
      view (15 roles) — plus multi-role union semantics. The expected-
      access tables are authored independently of `rbac.py`'s own
      internals (never imports its private constants) and dynamically
      pull the role/category lists from config, so a role or category
      added later without an explicit decision here fails the test
      rather than defaulting silently. All pass against the real
      implementation, unit-level (pytest, no live stack needed).
- [ ] **Runbooks reviewed by ops owner.** The 6 runbooks this directory
      now contains (`incident.md`, `restore-drill.md`,
      `model-upgrade.md`, `degraded-cpu-mode.md`, `secrets-rotation.md`,
      this file) are freshly written — nobody but the person who wrote
      them has read them yet. This item can only ever be checked by a
      human, not by whoever wrote the runbook.
- [ ] **CA sign-off on tax tables.** `config/tax_tables.*`/`fincore/`'s
      tax logic has unit/property test coverage (`DEVIATIONS.md` #16)
      but no chartered-accountant sign-off — that's a compliance
      signature this repo cannot provide.
- [ ] **Dept-head sign-off per agent.** Same category as the above — a
      human approval step, not a code deliverable.
- [x] **Kill-switch drill executed.** Live-verified against the real
      running stack: `scripts/kill_switch.py on OPS-1`, dispatched a
      real `timeline_risk_scan` task over the real Redis bus, confirmed
      it stayed `pending` for a full 12s poll window while parked
      (`docker logs` showed `bus.kill_switch_parked` firing every 2s the
      whole time — the mechanism is genuinely not reading, not just not
      finishing), then `scripts/kill_switch.py off OPS-1` and confirmed
      the exact same task was picked up and completed with no special
      resume step. First attempt gave a false pass (task showed `done`
      while supposedly parked) — root cause: `ops1`'s running container
      image was built over 21 hours before the kill-switch code was even
      committed, so it was executing old code that never checked the
      switch at all. Rebuilding the image and re-running the drill
      produced the real result above. See `DEVIATIONS.md` #25's update
      for the full account, including an unrelated config-drift mistake
      made mid-drill and its fix.
- [ ] **On-call & escalation defined.** `incident.md` defines the
      *process* (severities, escalation ladder, kill-switch). It does
      **not** define a real roster or paging integration — that's a
      staffing/tooling decision for whoever runs this in production, not
      something a repo can pre-populate.
- [x] **30-day rollback plan documented.** `deploy/runbooks/stabilization-plan.md`
      (Sprint 12).

## Why so many are unchecked

This checklist was substantially built out in one working session whose
explicit scope was **implementation, not live verification** — Docker/
live-stack testing is deferred to a dedicated server, per direct
instruction, after weeks of exactly that kind of testing surfacing real
host-capacity limits on this dev machine (`DEVIATIONS.md` #19/#20,
`degraded-cpu-mode.md`). Every unchecked-but-code-complete item above
(NFR measurement, red-team corpus expansion, audit-chain job, kill-switch
drill) is a "run it and confirm" task on that future server, not a "build
it" task here. The business/compliance items (payroll cycles, CA
sign-off, dept-head sign-off, ops review, on-call roster) were never
going to be satisfiable by a coding session regardless of environment.
