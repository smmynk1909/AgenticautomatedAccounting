from __future__ import annotations

from typing import Any

import pytest
from awp_shared.errors import PermissionDeniedError
from awp_shared.llm import LLMResponse, ToolCall
from awp_shared.schemas import AgentId, TaskEnvelope
from pydantic import BaseModel

from awp_agent_base import nodes
from awp_agent_base.state import new_state


class _FakeLLM:
    def __init__(self, response: LLMResponse) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    async def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> LLMResponse:
        self.calls.append({"messages": messages, **kwargs})
        return self.response


class _FakeMCP:
    def __init__(
        self, result: dict[str, Any] | None = None, error: Exception | None = None
    ) -> None:
        self.result = result or {}
        self.error = error
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def call(self, server: str, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((server, tool, args))
        if self.error:
            raise self.error
        return self.result


class _Payload(BaseModel):
    amount: int


def _task(intent: str = "create_ticket", payload: dict[str, Any] | None = None) -> TaskEnvelope:
    return TaskEnvelope(
        from_agent=AgentId.ORCH0, to_agent=AgentId.SUP1, intent=intent, payload=payload or {}
    )


async def test_validate_payload_none_model_is_noop() -> None:
    state = new_state(_task())
    node = nodes.make_validate_payload_node(None)
    result = await node(state)
    assert not nodes.has_error(result)


async def test_validate_payload_valid() -> None:
    state = new_state(_task(payload={"amount": 5}))
    node = nodes.make_validate_payload_node(_Payload)
    result = await node(state)
    assert not nodes.has_error(result)


async def test_validate_payload_invalid_sets_error() -> None:
    state = new_state(_task(payload={"amount": "not-an-int-or-str"}))
    node = nodes.make_validate_payload_node(_Payload)
    result = await node(state)
    assert nodes.has_error(result)
    assert result["scratch"]["error"]["code"] == "INTERNAL"


async def test_plan_node_stores_tool_calls() -> None:
    llm = _FakeLLM(
        LLMResponse(content=None, tool_calls=[ToolCall(id="1", name="get_ticket", arguments={})])
    )
    state = new_state(_task())
    node = nodes.make_plan_node(llm, tools=[], system_prompt="sys")
    result = await node(state)
    assert result["scratch"]["plan"]["tool_calls"] == [
        {"id": "1", "name": "get_ticket", "arguments": {}}
    ]
    assert llm.calls[0]["messages"][0]["content"] == "sys"


async def test_plan_node_exhausted_budget_sets_error() -> None:
    llm = _FakeLLM(LLMResponse(content="{}"))
    state = new_state(_task(), tool_budget=0)
    node = nodes.make_plan_node(llm, tools=[], system_prompt="sys")
    result = await node(state)
    assert nodes.has_error(result)
    assert llm.calls == []


async def test_execute_tool_node_happy_path() -> None:
    mcp = _FakeMCP(result={"ticket_id": "TKT-1"})
    state = new_state(_task())
    state["scratch"]["plan"] = {
        "tool_calls": [{"name": "create_ticket", "arguments": {"channel": "chat"}}]
    }
    node = nodes.make_execute_tool_node(mcp, tool_servers={"create_ticket": "erp"})
    result = await node(state)

    assert result["steps"][-1].ok is True
    assert result["steps"][-1].server == "erp"
    assert mcp.calls == [("erp", "create_ticket", {"channel": "chat"})]
    assert result["tool_budget"] == 24


async def test_execute_tool_node_unknown_tool_records_failed_step() -> None:
    mcp = _FakeMCP()
    state = new_state(_task())
    state["scratch"]["plan"] = {"tool_calls": [{"name": "delete_everything", "arguments": {}}]}
    node = nodes.make_execute_tool_node(mcp, tool_servers={"create_ticket": "erp"})
    result = await node(state)

    assert result["steps"][-1].ok is False
    assert result["steps"][-1].error is not None
    assert result["steps"][-1].error.code == "VALIDATION"
    assert mcp.calls == []


async def test_execute_tool_node_mcp_error_records_failed_step() -> None:
    mcp = _FakeMCP(error=PermissionDeniedError("nope"))
    state = new_state(_task())
    state["scratch"]["plan"] = {"tool_calls": [{"name": "create_ticket", "arguments": {}}]}
    node = nodes.make_execute_tool_node(mcp, tool_servers={"create_ticket": "erp"})
    result = await node(state)

    assert result["steps"][-1].ok is False
    assert result["steps"][-1].error is not None
    assert result["steps"][-1].error.code == "PERMISSION_DENIED"


async def test_execute_tool_node_exhausted_budget_sets_error() -> None:
    mcp = _FakeMCP()
    state = new_state(_task())
    state["tool_budget"] = 0
    state["scratch"]["plan"] = {"tool_calls": [{"name": "create_ticket", "arguments": {}}]}
    node = nodes.make_execute_tool_node(mcp, tool_servers={"create_ticket": "erp"})
    result = await node(state)
    assert nodes.has_error(result)
    assert mcp.calls == []


async def test_has_pending_tool_calls() -> None:
    state = new_state(_task())
    assert nodes.has_pending_tool_calls(state) is False
    state["scratch"]["plan"] = {"tool_calls": [{"name": "x", "arguments": {}}]}
    assert nodes.has_pending_tool_calls(state) is True


async def test_check_approval_node_missing_context_sets_error() -> None:
    mcp = _FakeMCP()
    state = new_state(_task())
    node = nodes.make_check_approval_node(mcp)
    result = await node(state)
    assert nodes.has_error(result)


async def test_check_approval_node_records_status() -> None:
    mcp = _FakeMCP(result={"status": "approved", "token": "signed.jwt.here"})
    state = new_state(_task())
    state["scratch"]["approval_gate"] = "payroll_run"
    state["scratch"]["approval_id"] = "abc"
    node = nodes.make_check_approval_node(mcp)
    result = await node(state)
    assert nodes.approval_is_granted(result) is True
    assert result["scratch"]["approval_token"] == "signed.jwt.here"
    assert mcp.calls == [("approvals", "get_approval_status", {"approval_id": "abc"})]


async def test_check_approval_node_pending_has_no_token() -> None:
    mcp = _FakeMCP(result={"status": "pending"})
    state = new_state(_task())
    state["scratch"]["approval_gate"] = "payroll_run"
    state["scratch"]["approval_id"] = "abc"
    node = nodes.make_check_approval_node(mcp)
    result = await node(state)
    assert nodes.approval_is_granted(result) is False
    assert "approval_token" not in result["scratch"]


async def test_summarize_node_sets_done_result() -> None:
    llm = _FakeLLM(LLMResponse(content="All done."))
    state = new_state(_task())
    node = nodes.make_summarize_node(llm)
    result = await node(state)
    assert result["result"] is not None
    assert result["result"].status.value == "done"
    assert result["result"].summary == "All done."


async def test_n_fail_builds_failed_result() -> None:
    state = new_state(_task())
    nodes.set_error(state, PermissionDeniedError("nope"))
    result = await nodes.n_fail(state)
    assert result["result"] is not None
    assert result["result"].status.value == "failed"
    assert result["result"].error is not None
    assert result["result"].error.code == "PERMISSION_DENIED"


@pytest.mark.parametrize("has_error", [True, False])
async def test_n_fail_handles_missing_error(has_error: bool) -> None:
    state = new_state(_task())
    if has_error:
        nodes.set_error(state, PermissionDeniedError("nope"))
    result = await nodes.n_fail(state)
    assert result["result"] is not None
