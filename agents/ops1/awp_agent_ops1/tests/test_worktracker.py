from __future__ import annotations

from datetime import date

from awp_agent_ops1.worktracker import (
    ANOMALY_MAX_HOURS_PER_DAY,
    MISSES_BEFORE_MANAGER_FLAG,
    check_allocation_conflict,
    compute_utilization,
    detect_timesheet_anomalies,
    needs_manager_flag,
    workdays_between,
)


def test_workdays_between_excludes_weekends() -> None:
    # Mon 2026-07-27 .. Sun 2026-08-02 == 5 workdays
    days = workdays_between(date(2026, 7, 27), date(2026, 8, 2))
    assert len(days) == 5
    assert all(d.weekday() < 5 for d in days)


def test_compute_utilization_splits_billable_and_internal() -> None:
    projects = {
        "P1": {"billing_type": "t_and_m"},
        "P2": {"billing_type": "internal"},
    }
    logs = [
        {"project_id": "P1", "hours": 6},
        {"project_id": "P2", "hours": 2},
    ]
    view = compute_utilization(logs, projects, date(2026, 7, 27), date(2026, 7, 27))  # 1 workday
    assert view.billable_hours == 6
    assert view.internal_hours == 2
    assert view.expected_hours == 8
    assert view.bench_hours == 0


def test_compute_utilization_bench_never_negative() -> None:
    projects = {"P1": {"billing_type": "t_and_m"}}
    logs = [{"project_id": "P1", "hours": 20}]  # way over expected for 1 day
    view = compute_utilization(logs, projects, date(2026, 7, 27), date(2026, 7, 27))
    assert view.bench_hours == 0


def test_detect_timesheet_anomalies_flags_zero_hours_day() -> None:
    workdays = [date(2026, 7, 27)]
    anomalies = detect_timesheet_anomalies("E1", workdays, [], {"P1"})
    assert len(anomalies) == 1
    assert anomalies[0].kind == "zero_hours"


def test_detect_timesheet_anomalies_flags_excess_hours() -> None:
    workdays = [date(2026, 7, 27)]
    logs = [{"date": date(2026, 7, 27), "hours": ANOMALY_MAX_HOURS_PER_DAY + 1, "project_id": "P1"}]
    anomalies = detect_timesheet_anomalies("E1", workdays, logs, {"P1"})
    assert any(a.kind == "excess_hours" for a in anomalies)


def test_detect_timesheet_anomalies_flags_project_mismatch() -> None:
    workdays = [date(2026, 7, 27)]
    logs = [{"date": date(2026, 7, 27), "hours": 8, "project_id": "P2"}]
    anomalies = detect_timesheet_anomalies("E1", workdays, logs, {"P1"})  # allocated to P1 only
    assert any(a.kind == "project_mismatch" for a in anomalies)


def test_detect_timesheet_anomalies_clean_day_no_anomaly() -> None:
    workdays = [date(2026, 7, 27)]
    logs = [{"date": date(2026, 7, 27), "hours": 8, "project_id": "P1"}]
    anomalies = detect_timesheet_anomalies("E1", workdays, logs, {"P1"})
    assert anomalies == []


def test_needs_manager_flag_threshold() -> None:
    workdays = [date(2026, 7, d) for d in (27, 28, 29)]  # Mon-Wed, all zero-hours
    anomalies = detect_timesheet_anomalies("E1", workdays, [], set())
    assert len(anomalies) == MISSES_BEFORE_MANAGER_FLAG
    assert needs_manager_flag(anomalies)
    assert not needs_manager_flag(anomalies[:-1])


def test_check_allocation_conflict_under_capacity() -> None:
    conflict = check_allocation_conflict([{"pct": 40}], requested_pct=30)
    assert conflict.conflicting_pct == 70
    assert not conflict.over_capacity


def test_check_allocation_conflict_over_capacity() -> None:
    conflict = check_allocation_conflict([{"pct": 80}], requested_pct=50)
    assert conflict.conflicting_pct == 130
    assert conflict.over_capacity
