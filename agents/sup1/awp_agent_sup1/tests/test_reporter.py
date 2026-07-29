from __future__ import annotations

from typing import Any

from awp_agent_sup1 import reporter
from awp_agent_sup1.tests.conftest import FakeMCP


def _by_status(tickets_by_status: dict[str, list[dict[str, Any]]]) -> Any:
    def handler(args: dict[str, Any]) -> dict[str, Any]:
        return {"tickets": tickets_by_status.get(args["status"], [])}

    return handler


async def test_open_ticket_counts_sums_across_open_statuses() -> None:
    mcp = FakeMCP(
        handlers={
            ("erp", "query_tickets"): _by_status(
                {
                    "new": [{"category": "device", "priority": "P3"}],
                    "in_progress": [{"category": "device", "priority": "P3"}],
                }
            )
        }
    )
    counts = await reporter.open_ticket_counts_by_category_priority(mcp)
    assert counts == {"device:P3": 2}


async def test_push_daily_dashboard_calls_push_dashboard_item() -> None:
    mcp = FakeMCP(
        handlers={
            ("erp", "query_tickets"): _by_status({"new": [{"category": "hr", "priority": "P2"}]})
        }
    )
    counts = await reporter.push_daily_dashboard(mcp)
    assert counts == {"hr:P2": 1}
    push_calls = [c for c in mcp.calls if c[1] == "push_dashboard_item"]
    assert len(push_calls) == 1
    assert "hr:P2=1" in push_calls[0][2]["body"]
