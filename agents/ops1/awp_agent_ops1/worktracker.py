"""OPS-1a WorkTracker — doc 05 §2.1. Pure functions; "SQL views" per the
doc are Python aggregation over already-fetched rows here (same split as
`shortlister.py`/`fincore`: deterministic-first, LLM-last, and in this
sprint there's no narrative-generation step at all — the numbers *are* the
output). Holiday-calendar awareness (`config/holidays_in.yaml`) is not
factored into expected working hours — that file is "not consumed by any
code yet" per its own header comment (SLAWarden doesn't either); workdays
here means plain Mon-Fri, same simplification.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

EXPECTED_HOURS_PER_DAY = 8.0
# doc 05 §2.1: "0h on workday, >14h day" — code thresholds, not LLM judgment.
ANOMALY_MAX_HOURS_PER_DAY = 14.0
MISSES_BEFORE_MANAGER_FLAG = 3


def workdays_between(date_from: date, date_to: date) -> list[date]:
    days = []
    d = date_from
    while d <= date_to:
        if d.weekday() < 5:  # Mon-Fri
            days.append(d)
        d += timedelta(days=1)
    return days


@dataclass(frozen=True)
class UtilizationView:
    billable_hours: float
    internal_hours: float
    bench_hours: float
    expected_hours: float


def compute_utilization(
    work_logs: list[dict[str, Any]],
    projects_by_id: dict[str, dict[str, Any]],
    date_from: date,
    date_to: date,
) -> UtilizationView:
    billable = 0.0
    internal = 0.0
    for log in work_logs:
        project = projects_by_id.get(log["project_id"], {})
        hours = float(log["hours"])
        if project.get("billing_type") == "internal":
            internal += hours
        else:
            billable += hours
    expected = len(workdays_between(date_from, date_to)) * EXPECTED_HOURS_PER_DAY
    bench = max(0.0, expected - billable - internal)
    return UtilizationView(
        billable_hours=billable, internal_hours=internal, bench_hours=bench, expected_hours=expected
    )


@dataclass(frozen=True)
class TimesheetAnomaly:
    emp_id: str
    date: date
    kind: str  # "zero_hours" | "excess_hours" | "project_mismatch"
    detail: str


def detect_timesheet_anomalies(
    emp_id: str,
    workdays: list[date],
    work_logs: list[dict[str, Any]],
    allocated_project_ids: set[str],
) -> list[TimesheetAnomaly]:
    """doc 05 §2.1's three anomaly kinds. `work_logs` is one employee's
    logs for the period being checked; `workdays` is that same period's
    Mon-Fri dates (missing entirely = a `zero_hours` day, not silently
    skipped)."""
    hours_by_day: dict[date, float] = {}
    projects_by_day: dict[date, set[str]] = {}
    for log in work_logs:
        d = log["date"]
        hours_by_day[d] = hours_by_day.get(d, 0.0) + float(log["hours"])
        projects_by_day.setdefault(d, set()).add(log["project_id"])

    anomalies: list[TimesheetAnomaly] = []
    for day in workdays:
        total = hours_by_day.get(day, 0.0)
        if total == 0.0:
            anomalies.append(
                TimesheetAnomaly(emp_id, day, "zero_hours", "no hours logged on a workday")
            )
            continue
        if total > ANOMALY_MAX_HOURS_PER_DAY:
            detail = f"{total:.1f}h logged (max {ANOMALY_MAX_HOURS_PER_DAY:.0f}h)"
            anomalies.append(TimesheetAnomaly(emp_id, day, "excess_hours", detail))
        unallocated = projects_by_day.get(day, set()) - allocated_project_ids
        if unallocated:
            detail = f"logged against project(s) not allocated: {sorted(unallocated)}"
            anomalies.append(TimesheetAnomaly(emp_id, day, "project_mismatch", detail))
    return anomalies


def needs_manager_flag(anomalies: list[TimesheetAnomaly]) -> bool:
    """doc 05 §2.1: "3 misses -> manager dashboard flag". A "miss" is any
    zero/excess/mismatch day, not just zero-hours ones."""
    return len(anomalies) >= MISSES_BEFORE_MANAGER_FLAG


@dataclass(frozen=True)
class AllocationConflict:
    conflicting_pct: float
    overlapping: list[dict[str, Any]]

    @property
    def over_capacity(self) -> bool:
        return self.conflicting_pct > 100.0


def check_allocation_conflict(
    existing_allocations: list[dict[str, Any]], requested_pct: float
) -> AllocationConflict:
    """doc 05 §2.1: "check availability ... conflict? -> propose
    alternatives". `existing_allocations` is assumed pre-filtered to those
    overlapping the requested date window (the repo's `active_on` query
    does that) — this function just sums percentages. Skill-match against
    `skills_master`/project needs is not implemented: `projects` has no
    skill-requirements field in this schema (doc 09 §1's DDL sketch doesn't
    give projects one either) — documented in DEVIATIONS.md."""
    existing_pct = sum(float(a["pct"]) for a in existing_allocations)
    return AllocationConflict(
        conflicting_pct=existing_pct + requested_pct, overlapping=existing_allocations
    )
