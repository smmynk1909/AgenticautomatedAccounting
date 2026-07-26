"""doc 07 §6 acceptance tests, run at the graph level with scripted LLM/MCP
fixtures (doc 11 §10's testing pyramid, same convention as
agents/orch0/tests/test_graph_acceptance.py).

Test 1 (classification accuracy >= 0.9 on a 300-ticket labeled set) and
test 5 (4 consecutive weeks of human rating) need a labeled dataset /
production usage history this build doesn't have; the P1-override property
they both partly depend on is verified directly instead (also covered at
the unit level in test_intake.py and test_nodes.py). Test 4's "simulated
1,000-ticket day, zero timers lost on restart" is a k6/load scenario per
doc 11 §10, not a graph-level test — deferred to the (not yet built) e2e
suite, same scoping as agents/orch0/tests/test_graph_acceptance.py.
"""

from __future__ import annotations

import json

from awp_agent_base.state import new_state
from awp_shared.llm import LLMResponse
from awp_shared.schemas import AgentId, TaskEnvelope, TaskStatus

from awp_agent_sup1.graph import build_graph
from awp_agent_sup1.tests.conftest import FakeLLM, FakeMCP


def _task(intent: str, payload: dict) -> TaskEnvelope:
    return TaskEnvelope(
        from_agent=AgentId.ORCH0, to_agent=AgentId.SUP1, intent=intent, payload=payload
    )


async def test_create_ticket_end_to_end_p1_override() -> None:
    llm = FakeLLM(
        [
            LLMResponse(
                content=json.dumps(
                    {
                        "subcategory": "payroll_run",
                        "priority_suggestion": "P4",
                        "extracted_entities": {},
                        "missing_info": [],
                    }
                )
            )
        ]
    )
    mcp = FakeMCP(handlers={("erp", "create_ticket"): {"ticket_id": "TKT-1"}})
    graph = build_graph(llm, mcp)

    task = _task(
        "create_ticket",
        {
            "channel": "agent",
            "category": "payroll",
            "subject": "Payroll blocked",
            "body": "salary not processed, payroll is blocked for this cycle",
        },
    )
    final = await graph.ainvoke(new_state(task))

    create_call = next(c for c in mcp.calls if c[1] == "create_ticket")
    assert create_call[2]["priority"] == "P1"
    assert final["result"].status == TaskStatus.DONE


async def test_cross_functional_children_created_and_linked() -> None:
    """doc 07 §6 test 2's "parent never resolves with an open child" is a
    property of `mcp-erp.update_ticket` (tested there); this checks SUP-1's
    own fan-out produces the parent/child linkage that property depends on.
    """
    counter = {"n": 0}

    def create_ticket(args: dict) -> dict:
        counter["n"] += 1
        return {"ticket_id": f"TKT-CHILD-{counter['n']}"}

    mcp = FakeMCP(
        handlers={
            ("erp", "create_ticket"): create_ticket,
            ("erp", "link_tickets"): {"linked_ticket_ids": []},
        }
    )
    graph = build_graph(FakeLLM([]), mcp)

    task = _task(
        "cross_dept_request",
        {"parent_ticket_id": "TKT-PARENT", "departments": ["delivery", "device", "hr", "payroll"]},
    )
    final = await graph.ainvoke(new_state(task))

    assert final["scratch"]["child_ticket_ids"] == [
        "TKT-CHILD-1",
        "TKT-CHILD-2",
        "TKT-CHILD-3",
        "TKT-CHILD-4",
    ]
    link_calls = [c for c in mcp.calls if c[1] == "link_tickets"]
    assert link_calls[0][2]["parent"] == "TKT-PARENT"
    assert final["result"].status == TaskStatus.DONE


async def test_unknown_intent_raises() -> None:
    import pytest
    from awp_shared.errors import ValidationError

    graph = build_graph(FakeLLM([]), FakeMCP())
    task = _task("not_a_sup1_intent", {})
    with pytest.raises(ValidationError):
        await graph.ainvoke(new_state(task))
