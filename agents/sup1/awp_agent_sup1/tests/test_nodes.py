from __future__ import annotations

import json

from awp_agent_base.state import new_state
from awp_shared.llm import LLMResponse
from awp_shared.schemas import AgentId, TaskEnvelope

from awp_agent_sup1 import nodes
from awp_agent_sup1.tests.conftest import FakeLLM, FakeMCP


def _task(intent: str, payload: dict) -> TaskEnvelope:
    return TaskEnvelope(
        from_agent=AgentId.ORCH0, to_agent=AgentId.SUP1, intent=intent, payload=payload
    )


async def test_create_ticket_node_forces_p1_for_payroll_blocking() -> None:
    llm = FakeLLM(
        [
            LLMResponse(
                content=json.dumps(
                    {
                        "subcategory": "payroll_run",
                        "priority_suggestion": "P3",  # LLM under-classifies
                        "extracted_entities": {},
                        "missing_info": [],
                    }
                )
            )
        ]
    )
    mcp = FakeMCP(handlers={("erp", "create_ticket"): {"ticket_id": "TKT-1"}})
    state = new_state(
        _task(
            "create_ticket",
            {
                "channel": "agent",
                "category": "payroll",
                "subject": "Payroll blocked",
                "body": "We cannot run payroll for this month, it is blocked.",
            },
        )
    )

    node = nodes.make_create_ticket_node(llm, mcp)
    result = await node(state)

    assert result["scratch"]["ticket_id"] == "TKT-1"
    create_call = next(c for c in mcp.calls if c[1] == "create_ticket")
    assert create_call[2]["priority"] == "P1"


async def test_create_ticket_node_skips_llm_for_confidential_subcategory() -> None:
    llm = FakeLLM([])
    mcp = FakeMCP(handlers={("erp", "create_ticket"): {"ticket_id": "TKT-2"}})
    state = new_state(
        _task(
            "create_ticket",
            {
                "channel": "chat",
                "category": "hr",
                "subcategory": "grievance",
                "subject": "Confidential",
                "body": "sensitive content",
            },
        )
    )

    node = nodes.make_create_ticket_node(llm, mcp)
    await node(state)

    assert llm.calls == []


async def test_escalate_ticket_node_appends_event_and_pushes_dashboard() -> None:
    mcp = FakeMCP()
    state = new_state(_task("escalate_ticket", {"ticket_id": "TKT-3", "reason": "SLA at risk"}))

    node = nodes.make_escalate_ticket_node(mcp)
    result = await node(state)

    assert result["scratch"]["ticket_id"] == "TKT-3"
    assert [c for c in mcp.calls if c[1] == "append_ticket_event"]
    assert [c for c in mcp.calls if c[1] == "push_dashboard_item"]


async def test_cross_dept_request_node_creates_children() -> None:
    counter = {"n": 0}

    def create_ticket(args: dict) -> dict:
        counter["n"] += 1
        return {"ticket_id": f"TKT-CHILD-{counter['n']}"}

    mcp = FakeMCP(handlers={("erp", "create_ticket"): create_ticket})
    state = new_state(
        _task(
            "cross_dept_request",
            {"parent_ticket_id": "TKT-PARENT", "departments": ["delivery", "device"]},
        )
    )

    node = nodes.make_cross_dept_request_node(mcp)
    result = await node(state)

    assert result["scratch"]["child_ticket_ids"] == ["TKT-CHILD-1", "TKT-CHILD-2"]


async def test_sla_report_node_pushes_dashboard() -> None:
    mcp = FakeMCP(handlers={("erp", "query_tickets"): {"tickets": []}})
    state = new_state(_task("sla_report", {}))

    node = nodes.make_sla_report_node(mcp)
    result = await node(state)

    assert result["scratch"]["report_counts"] == {}
    assert [c for c in mcp.calls if c[1] == "push_dashboard_item"]


async def test_n_respond_sets_done_result() -> None:
    state = new_state(_task("sla_report", {}))
    state["scratch"]["ticket_id"] = "TKT-1"
    result = await nodes.n_respond(state)
    assert result["result"] is not None
    assert result["result"].status.value == "done"
    assert "TKT-1" in result["result"].summary
