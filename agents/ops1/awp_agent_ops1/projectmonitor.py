"""OPS-1b ProjectMonitor — doc 05 §2.2. Pure functions: every number here
is code (doc 05 §2.2 step 2 "Compute (code)"), same deterministic-first
split as `worktracker.py`. "Milestone-at-risk" is "due within 14d & <70%
linked tasks done" per the doc; this schema has no task-per-milestone
linkage anywhere (no sprint has built one — `orchestrator_tasks` tracks
agent-execution tasks, not project deliverables), so the detector here is
due-date + status only. Documented in DEVIATIONS.md; the doc 04 §5.2-
equivalent acceptance bar for this ("precision >= 0.8 on historical
backtest set") has no historical dataset to backtest against either (same
"no data source built yet" pattern as every other backtest-needing
acceptance test in this build) — proven against synthetic fixtures instead
(`tests/test_projectmonitor.py`), not a real precision number.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

MILESTONE_AT_RISK_HORIZON_DAYS = 14
_DONE_STATUSES = frozenset({"done", "completed", "cancelled"})


@dataclass(frozen=True)
class MilestoneRisk:
    milestone_id: str
    title: str
    due: date
    days_until_due: int
    reason: str


def milestones_at_risk(
    milestones: list[dict[str, Any]],
    today: date,
    horizon_days: int = MILESTONE_AT_RISK_HORIZON_DAYS,
) -> list[MilestoneRisk]:
    at_risk = []
    for m in milestones:
        due = m.get("due")
        if due is None or m.get("status") in _DONE_STATUSES:
            continue
        days_until = (due - today).days
        if 0 <= days_until <= horizon_days:
            at_risk.append(
                MilestoneRisk(
                    milestone_id=m["id"],
                    title=m["title"],
                    due=due,
                    days_until_due=days_until,
                    reason=f"due in {days_until}d, status={m.get('status', 'unknown')}",
                )
            )
    at_risk.sort(key=lambda r: r.days_until_due)
    return at_risk


def overdue_milestones(milestones: list[dict[str, Any]], today: date) -> list[dict[str, Any]]:
    return [
        m
        for m in milestones
        if m.get("due") is not None and m["due"] < today and m.get("status") not in _DONE_STATUSES
    ]


def burn_variance_pct(hours_burned: float, budget_hours: float | None) -> float | None:
    """`None` when there's no budget to compare against (`budget_hours` is
    nullable in the schema) — never a fabricated 0%."""
    if not budget_hours:
        return None
    return round((hours_burned / float(budget_hours) - 1.0) * 100.0, 1)


def schedule_variance_pct(milestones: list[dict[str, Any]], today: date) -> float | None:
    """Fraction of not-yet-done milestones that are overdue, as a percentage.
    `None` if there are no open milestones to measure (nothing to be
    behind on)."""
    open_milestones = [m for m in milestones if m.get("status") not in _DONE_STATUSES]
    if not open_milestones:
        return None
    overdue = overdue_milestones(milestones, today)
    return round(len(overdue) / len(open_milestones) * 100.0, 1)


@dataclass(frozen=True)
class HealthReport:
    project_id: str
    client: str
    hours_burned: float
    budget_hours: float | None
    burn_variance_pct: float | None
    schedule_variance_pct: float | None
    at_risk: list[MilestoneRisk]
    overdue: list[dict[str, Any]]

    @property
    def worst_risk_severity(self) -> str:
        """ "Worst-3 to ADM-1 exec dashboard" (doc 05 §2.2 step 5) needs a
        rankable severity per report — code, not an LLM judgment call.
        Values match `dashboard_items.severity`'s established vocabulary
        (`"info"`/`"warning"`/`"critical"` — see every other agent's
        `push_dashboard_item` calls), not an ad hoc high/medium/low scale."""
        if self.overdue or (self.burn_variance_pct or 0) > 20:
            return "critical"
        if self.at_risk or (self.burn_variance_pct or 0) > 0:
            return "warning"
        return "info"


def assemble_health_report(
    project: dict[str, Any],
    milestones: list[dict[str, Any]],
    work_logs: list[dict[str, Any]],
    today: date,
) -> HealthReport:
    hours_burned = sum(float(w["hours"]) for w in work_logs)
    budget_hours = project.get("budget_hours")
    return HealthReport(
        project_id=project["id"],
        client=project["client"],
        hours_burned=hours_burned,
        budget_hours=float(budget_hours) if budget_hours is not None else None,
        burn_variance_pct=burn_variance_pct(hours_burned, budget_hours),
        schedule_variance_pct=schedule_variance_pct(milestones, today),
        at_risk=milestones_at_risk(milestones, today),
        overdue=overdue_milestones(milestones, today),
    )


def _rank_key(report: HealthReport) -> tuple[int, float]:
    order = {"critical": 0, "warning": 1, "info": 2}
    return order[report.worst_risk_severity], -(report.burn_variance_pct or 0)


def rank_worst_projects(reports: list[HealthReport], n: int = 3) -> list[HealthReport]:
    return sorted(reports, key=_rank_key)[:n]
