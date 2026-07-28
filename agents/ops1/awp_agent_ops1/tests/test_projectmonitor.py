from __future__ import annotations

from datetime import date

from awp_agent_ops1.projectmonitor import (
    MILESTONE_AT_RISK_HORIZON_DAYS,
    HealthReport,
    MilestoneRisk,
    assemble_health_report,
    burn_variance_pct,
    milestones_at_risk,
    overdue_milestones,
    rank_worst_projects,
    schedule_variance_pct,
)

_TODAY = date(2026, 7, 27)


def test_milestones_at_risk_within_horizon() -> None:
    milestones = [
        {"id": "M1", "title": "UAT", "due": _TODAY, "status": "in_progress"},
        {
            "id": "M2",
            "title": "GA",
            "due": date(2026, 8, 20),  # > 14d out
            "status": "planned",
        },
        {"id": "M3", "title": "Done already", "due": _TODAY, "status": "done"},
    ]
    at_risk = milestones_at_risk(milestones, _TODAY)
    assert [r.milestone_id for r in at_risk] == ["M1"]


def test_milestones_at_risk_excludes_overdue() -> None:
    milestones = [{"id": "M1", "title": "x", "due": date(2026, 7, 20), "status": "in_progress"}]
    assert milestones_at_risk(milestones, _TODAY) == []


def test_overdue_milestones_excludes_done() -> None:
    milestones = [
        {"id": "M1", "title": "x", "due": date(2026, 7, 20), "status": "in_progress"},
        {"id": "M2", "title": "y", "due": date(2026, 7, 20), "status": "done"},
    ]
    overdue = overdue_milestones(milestones, _TODAY)
    assert [m["id"] for m in overdue] == ["M1"]


def test_burn_variance_pct_over_budget() -> None:
    assert burn_variance_pct(120, 100) == 20.0


def test_burn_variance_pct_no_budget_is_none() -> None:
    assert burn_variance_pct(120, None) is None
    assert burn_variance_pct(120, 0) is None


def test_schedule_variance_pct_half_overdue() -> None:
    milestones = [
        {"id": "M1", "due": date(2026, 7, 20), "status": "in_progress"},
        {"id": "M2", "due": date(2026, 8, 10), "status": "in_progress"},
    ]
    assert schedule_variance_pct(milestones, _TODAY) == 50.0


def test_schedule_variance_pct_no_open_milestones_is_none() -> None:
    milestones = [{"id": "M1", "due": date(2026, 7, 20), "status": "done"}]
    assert schedule_variance_pct(milestones, _TODAY) is None


def test_assemble_health_report_sums_hours_from_work_logs() -> None:
    project = {"id": "P1", "client": "Acme", "budget_hours": 100}
    work_logs = [{"hours": 30}, {"hours": 20}]
    report = assemble_health_report(project, [], work_logs, _TODAY)
    assert report.hours_burned == 50
    assert report.burn_variance_pct == -50.0


def test_worst_risk_severity_high_when_overdue() -> None:
    report = HealthReport(
        project_id="P1",
        client="Acme",
        hours_burned=0,
        budget_hours=None,
        burn_variance_pct=None,
        schedule_variance_pct=None,
        at_risk=[],
        overdue=[{"id": "M1"}],
    )
    assert report.worst_risk_severity == "critical"


def test_worst_risk_severity_low_when_clean() -> None:
    report = HealthReport(
        project_id="P1",
        client="Acme",
        hours_burned=0,
        budget_hours=None,
        burn_variance_pct=None,
        schedule_variance_pct=None,
        at_risk=[],
        overdue=[],
    )
    assert report.worst_risk_severity == "info"


def test_rank_worst_projects_returns_top_n_by_severity() -> None:
    high = HealthReport("P1", "A", 0, None, None, None, [], [{"id": "M1"}])
    low = HealthReport("P2", "B", 0, None, None, None, [], [])
    medium = HealthReport(
        "P3",
        "C",
        0,
        None,
        None,
        None,
        [MilestoneRisk("M2", "x", _TODAY, 1, "due soon")],
        [],
    )
    ranked = rank_worst_projects([low, high, medium], n=2)
    assert [r.project_id for r in ranked] == ["P1", "P3"]


def test_milestone_at_risk_horizon_constant_is_14_days() -> None:
    assert MILESTONE_AT_RISK_HORIZON_DAYS == 14
