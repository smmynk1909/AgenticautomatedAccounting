from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from awp_agent_sup1 import slawarden


def test_compute_sla_deadlines_p1(sla_table: dict[str, Any]) -> None:
    created = datetime(2026, 7, 26, 9, 0, tzinfo=UTC)
    timers = slawarden.compute_sla_deadlines("P1", created, sla_table)
    assert timers.first_response_due == created + timedelta(minutes=15)
    assert timers.resolution_due == created + timedelta(hours=4)


def test_pct_consumed_halfway() -> None:
    created = datetime(2026, 7, 26, 9, 0, tzinfo=UTC)
    due = created + timedelta(hours=4)
    now = created + timedelta(hours=2)
    assert slawarden.pct_consumed(due, created, now) == 50.0


def test_pct_consumed_clamped_to_100() -> None:
    created = datetime(2026, 7, 26, 9, 0, tzinfo=UTC)
    due = created + timedelta(hours=4)
    now = created + timedelta(hours=10)
    assert slawarden.pct_consumed(due, created, now) == 100.0


def test_escalation_action_below_threshold_is_none(sla_table: dict[str, Any]) -> None:
    assert slawarden.escalation_action(50.0, "P2", sla_table) is None


def test_escalation_action_75_pct_warns_assignee(sla_table: dict[str, Any]) -> None:
    assert slawarden.escalation_action(80.0, "P2", sla_table) == "warn_assignee"


def test_escalation_action_100_pct_p2_notifies_manager(sla_table: dict[str, Any]) -> None:
    assert slawarden.escalation_action(100.0, "P2", sla_table) == "notify_manager_and_dashboard"


def test_escalation_action_100_pct_p1_notifies_director_ceo(sla_table: dict[str, Any]) -> None:
    # doc 07 §3.4: "P1 breach -> Director + CEO panel + incident channel."
    assert (
        slawarden.escalation_action(100.0, "P1", sla_table)
        == "notify_director_ceo_incident_channel"
    )
