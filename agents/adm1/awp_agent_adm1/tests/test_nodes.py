from __future__ import annotations

import pytest
from awp_agent_base.state import new_state
from awp_shared.errors import ApprovalRequiredError, ValidationError
from awp_shared.schemas import AgentId, TaskEnvelope, TaskStatus

from awp_agent_adm1 import nodes
from awp_agent_adm1.graph import build_graph
from awp_agent_adm1.tests.conftest import FakeLLM, FakeMCP


def _task(intent: str, payload: dict) -> TaskEnvelope:
    return TaskEnvelope(
        from_agent=AgentId.ORCH0, to_agent=AgentId.ADM1, intent=intent, payload=payload
    )


async def test_return_device_node_updates_scratch() -> None:
    mcp = FakeMCP(handlers={("erp", "return_asset"): {"id": "AST-1", "status": "in_stock"}})
    state = new_state(_task("return_device", {"asset_id": "AST-1", "emp_id": "EMP-1"}))
    node = nodes.make_return_device_node(mcp)
    result = await node(state)
    assert result["scratch"]["asset_id"] == "AST-1"
    assert mcp.calls[0] == ("erp", "return_asset", {"asset_id": "AST-1", "condition_report": {}})


async def test_device_repair_node_creates_repair_ticket() -> None:
    mcp = FakeMCP(handlers={("erp", "create_ticket"): {"ticket_id": "TKT-REPAIR-1"}})
    state = new_state(
        _task("device_repair", {"asset_id": "AST-1", "issue_description": "screen cracked"})
    )
    node = nodes.make_device_repair_node(mcp)
    result = await node(state)
    assert result["scratch"]["ticket_id"] == "TKT-REPAIR-1"
    create_call = mcp.calls[0]
    assert create_call[2]["category"] == "device"
    assert create_call[2]["subcategory"] == "repair"


async def test_update_employee_record_happy_path_no_gate() -> None:
    mcp = FakeMCP(handlers={("erp", "upsert_employee"): {"emp_id": "EMP-1", "grade": "E3"}})
    graph = build_graph(FakeLLM([]), mcp)
    task = _task("update_employee_record", {"emp_id": "EMP-1", "patch": {"grade": "E3"}})
    final = await graph.ainvoke(new_state(task))

    assert final["result"].status == TaskStatus.DONE
    assert final["scratch"]["emp_id"] == "EMP-1"
    upsert_call = next(c for c in mcp.calls if c[1] == "upsert_employee")
    assert upsert_call[2]["record"] == {"emp_id": "EMP-1", "grade": "E3"}


async def test_update_employee_record_identity_change_awaits_approval() -> None:
    def upsert_employee(args: dict) -> dict:
        raise ApprovalRequiredError("identity field changed")

    mcp = FakeMCP(
        handlers={
            ("erp", "upsert_employee"): upsert_employee,
            ("approvals", "request_approval"): {"approval_id": "APR-9", "status": "pending"},
        }
    )
    graph = build_graph(FakeLLM([]), mcp)
    task = _task("update_employee_record", {"emp_id": "EMP-1", "patch": {"name": "New Name"}})
    final = await graph.ainvoke(new_state(task))

    assert final["result"].status == TaskStatus.AWAITING_APPROVAL
    assert final["scratch"]["awaiting_approval_for"] == "update_employee_record"
    request_call = next(c for c in mcp.calls if c[1] == "request_approval")
    assert request_call[2]["gate"] == "record_correction"
    assert request_call[2]["payload"] == {"emp_id": "EMP-1", "name": "New Name"}


async def test_update_employee_record_resumes_after_approval() -> None:
    mcp = FakeMCP(
        handlers={
            ("approvals", "get_approval_status"): {"status": "approved", "token": "signed.jwt"},
            ("erp", "upsert_employee"): {"emp_id": "EMP-1", "name": "New Name"},
        }
    )
    graph = build_graph(FakeLLM([]), mcp)
    task = _task("update_employee_record", {"emp_id": "EMP-1", "patch": {"name": "New Name"}})
    state = new_state(task)
    state["scratch"] = {
        "awaiting_approval_for": "update_employee_record",
        "approval_id": "APR-9",
        "employee_record": {"emp_id": "EMP-1", "name": "New Name"},
    }
    final = await graph.ainvoke(state)

    assert final["result"].status == TaskStatus.DONE
    upsert_call = next(c for c in mcp.calls if c[1] == "upsert_employee")
    assert upsert_call[2]["record"]["approval_token"] == "signed.jwt"
    assert "awaiting_approval_for" not in final["scratch"]


async def test_update_employee_record_still_pending_reports_awaiting() -> None:
    mcp = FakeMCP(handlers={("approvals", "get_approval_status"): {"status": "pending"}})
    graph = build_graph(FakeLLM([]), mcp)
    task = _task("update_employee_record", {"emp_id": "EMP-1", "patch": {}})
    state = new_state(task)
    state["scratch"] = {"awaiting_approval_for": "update_employee_record", "approval_id": "APR-9"}
    final = await graph.ainvoke(state)
    assert final["result"].status == TaskStatus.AWAITING_APPROVAL
    assert not any(c[1] == "upsert_employee" for c in mcp.calls)


async def test_update_employee_record_rejected_approval_fails() -> None:
    mcp = FakeMCP(handlers={("approvals", "get_approval_status"): {"status": "rejected"}})
    graph = build_graph(FakeLLM([]), mcp)
    task = _task("update_employee_record", {"emp_id": "EMP-1", "patch": {}})
    state = new_state(task)
    state["scratch"] = {"awaiting_approval_for": "update_employee_record", "approval_id": "APR-9"}
    final = await graph.ainvoke(state)
    assert final["result"].status == TaskStatus.FAILED


async def test_unknown_intent_raises() -> None:
    graph = build_graph(FakeLLM([]), FakeMCP())
    task = _task("not_an_adm1_intent", {})
    with pytest.raises(ValidationError):
        await graph.ainvoke(new_state(task))


async def test_unknown_awaiting_approval_flow_raises() -> None:
    graph = build_graph(FakeLLM([]), FakeMCP())
    task = _task("issue_device", {"emp_id": "EMP-1", "asset_type": "laptop"})
    state = new_state(task)
    state["scratch"]["awaiting_approval_for"] = "not_a_real_flow"
    with pytest.raises(ValidationError):
        await graph.ainvoke(state)
