from __future__ import annotations

from datetime import date

from awp_agent_ops1.deliveryrisk import is_s1, timeline_radar

_TODAY = date(2026, 7, 27)


def test_timeline_radar_ranks_invoice_trigger_higher_at_equal_proximity() -> None:
    milestones_by_project = {
        "P1": [
            {
                "id": "M1",
                "title": "Non-billing milestone",
                "due": date(2026, 8, 1),
                "status": "planned",
                "invoice_trigger": False,
            },
            {
                "id": "M2",
                "title": "Invoice milestone",
                "due": date(2026, 8, 1),
                "status": "planned",
                "invoice_trigger": True,
            },
        ]
    }
    items = timeline_radar(milestones_by_project, _TODAY)
    assert items[0].milestone_id == "M2"
    assert items[0].impact_score > items[1].impact_score


def test_timeline_radar_excludes_outside_horizon() -> None:
    milestones_by_project = {
        "P1": [{"id": "M1", "title": "x", "due": date(2026, 12, 1), "status": "planned"}]
    }
    assert timeline_radar(milestones_by_project, _TODAY, horizon_days=30) == []


def test_timeline_radar_excludes_done_milestones() -> None:
    milestones_by_project = {
        "P1": [{"id": "M1", "title": "x", "due": date(2026, 7, 28), "status": "done"}]
    }
    assert timeline_radar(milestones_by_project, _TODAY) == []


def test_timeline_radar_ranks_closer_due_dates_higher() -> None:
    milestones_by_project = {
        "P1": [
            {"id": "M1", "title": "far", "due": date(2026, 8, 20), "status": "planned"},
            {"id": "M2", "title": "near", "due": date(2026, 7, 28), "status": "planned"},
        ]
    }
    items = timeline_radar(milestones_by_project, _TODAY)
    assert items[0].milestone_id == "M2"


def test_is_s1() -> None:
    assert is_s1({"severity": "S1"})
    assert not is_s1({"severity": "S3"})
    assert not is_s1({})
