"""SUP-1d SLAWarden — doc 07 §3.4: pure code + notifications, no LLM in the
timer path (reliability).

Deadlines here are calendar-time, not the doc's full "business-hours
calendar aware (IST, company holidays)" refinement — `config/sla.yaml`'s
`holidays_ref` file exists (`config/holidays_in.yaml`) but nothing consumes
it yet; true business-hours arithmetic (partial-day accounting around the
09:00-18:00 window) is deferred. This makes computed deadlines slightly
conservative across a holiday/weekend (the real deadline would be later),
never the reverse — never a false "not yet breached." Revisit once that
arithmetic is worth the complexity (Sprint 4+, once SUP-1 is under real
ticket volume).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from awp_shared.config import load_config


@dataclass(frozen=True)
class SlaTimers:
    first_response_due: datetime
    resolution_due: datetime


def compute_sla_deadlines(
    priority: str, created_at: datetime, sla_table: dict[str, Any] | None = None
) -> SlaTimers:
    table = sla_table or load_config("sla")
    row = table["priorities"][priority]
    return SlaTimers(
        first_response_due=created_at + timedelta(minutes=row["first_response_minutes"]),
        resolution_due=created_at + timedelta(hours=row["resolution_hours"]),
    )


def pct_consumed(due: datetime, created_at: datetime, now: datetime) -> float:
    total = (due - created_at).total_seconds()
    if total <= 0:
        return 100.0
    elapsed = (now - created_at).total_seconds()
    return max(0.0, min(100.0, elapsed / total * 100))


def escalation_action(
    pct: float, priority: str, sla_table: dict[str, Any] | None = None
) -> str | None:
    """Returns the most severe action whose `at_pct` (and, if set,
    `priority`) threshold `pct` has crossed — `config/sla.yaml`'s
    `escalation_ladder` is ordered least -> most severe, and later rungs
    override earlier ones once their own threshold is also met."""
    table = sla_table or load_config("sla")
    triggered: str | None = None
    for rung in table["escalation_ladder"]:
        rung_priority = rung.get("priority")
        if rung_priority is not None and rung_priority != priority:
            continue
        if pct >= rung["at_pct"]:
            triggered = rung["action"]
    return triggered
