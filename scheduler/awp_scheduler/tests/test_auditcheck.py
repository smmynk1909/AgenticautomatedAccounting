from __future__ import annotations

from datetime import date

from awp_scheduler.auditcheck import verify_audit_chain_daily
from awp_scheduler.tests.conftest import FakeMCP

_TODAY = date(2026, 7, 29)
_YESTERDAY = "2026-07-28"


def _clean_report(day: str = _YESTERDAY) -> dict:
    # Shape matches the real `VerificationResult.model_dump()` from
    # mcps/audit/awp_mcp_audit/verifier.py — `tampered` is always present,
    # never omitted, even when false.
    return {
        "day": day,
        "stored_root": "abc123",
        "recomputed_root": "abc123",
        "event_count": 4,
        "tampered": False,
    }


def _tampered_report(day: str = _YESTERDAY) -> dict:
    return {
        "day": day,
        "stored_root": "abc123",
        "recomputed_root": "def456",
        "event_count": 4,
        "tampered": True,
    }


async def test_checks_yesterday_not_today() -> None:
    mcp = FakeMCP({("audit", "export_audit"): {"days": [_clean_report()]}})

    await verify_audit_chain_daily(mcp, _TODAY)

    server, tool, args = mcp.calls[0]
    assert (server, tool) == ("audit", "export_audit")
    assert args == {"start_day": _YESTERDAY, "end_day": _YESTERDAY}


async def test_no_tamper_does_not_escalate() -> None:
    mcp = FakeMCP({("audit", "export_audit"): {"days": [_clean_report()]}})

    result = await verify_audit_chain_daily(mcp, _TODAY)

    assert result["tampered"] is False
    called_tools = [(s, t) for s, t, _ in mcp.calls]
    assert ("comms", "notify_user") not in called_tools
    assert ("erp", "push_dashboard_item") not in called_tools


async def test_tampered_day_escalates_via_notify_and_dashboard() -> None:
    mcp = FakeMCP({("audit", "export_audit"): {"days": [_tampered_report()]}})

    result = await verify_audit_chain_daily(mcp, _TODAY)

    assert result["tampered"] is True
    called_tools = [(s, t) for s, t, _ in mcp.calls]
    assert ("comms", "notify_user") in called_tools
    assert ("erp", "push_dashboard_item") in called_tools

    notify_args = next(args for s, t, args in mcp.calls if (s, t) == ("comms", "notify_user"))
    assert notify_args["user_id"] == "director"
    assert _YESTERDAY in notify_args["body"]

    dashboard_args = next(
        args for s, t, args in mcp.calls if (s, t) == ("erp", "push_dashboard_item")
    )
    assert dashboard_args["item"]["severity"] == "critical"


async def test_only_tampered_days_trigger_notify_in_a_multi_day_range() -> None:
    mcp = FakeMCP(
        {
            ("audit", "export_audit"): {
                "days": [_clean_report("2026-07-27"), _tampered_report("2026-07-28")]
            }
        }
    )

    await verify_audit_chain_daily(mcp, _TODAY)

    notify_calls = [args for s, t, args in mcp.calls if (s, t) == ("comms", "notify_user")]
    assert len(notify_calls) == 1
    assert notify_calls[0]["refs"]["day"] == "2026-07-28"
