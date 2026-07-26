from __future__ import annotations

from awp_shared.llm import LLMResponse

from awp_agent_sup1 import statuskeeper
from awp_agent_sup1.tests.conftest import FakeLLM, FakeMCP


async def test_refresh_summary_mentions_latest_event_and_calls_set_summary() -> None:
    ticket = {
        "status": "in_progress",
        "assignee_id": "ADM-1",
        "events": [
            {"type": "comment", "body": {"text": "old"}},
            {"type": "status_change", "body": {"to": "in_progress"}},
        ],
    }
    llm = FakeLLM(
        [
            LLMResponse(
                content=(
                    "Ticket moved to in_progress (latest event: status_change). "
                    "Next step: ADM-1 to action the request. ADM-1 currently holds the ball."
                )
            )
        ]
    )
    mcp = FakeMCP(handlers={("erp", "get_ticket"): ticket})

    summary = await statuskeeper.refresh_summary(llm, mcp, "TKT-1")

    assert "status_change" in summary
    assert "ADM-1" in summary
    set_summary_calls = [c for c in mcp.calls if c[1] == "set_summary"]
    assert set_summary_calls == [("erp", "set_summary", {"ticket_id": "TKT-1", "text": summary})]


async def test_refresh_summary_handles_no_events() -> None:
    ticket: dict[str, object] = {"status": "new", "assignee_id": None, "events": []}
    llm = FakeLLM([LLMResponse(content="New ticket, unassigned. Next step: triage.")])
    mcp = FakeMCP(handlers={("erp", "get_ticket"): ticket})

    summary = await statuskeeper.refresh_summary(llm, mcp, "TKT-2")
    assert summary
