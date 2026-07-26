"""Common graph nodes — doc 11 §2. Every node here is a *factory*: it closes
over its dependencies (payload model, `LLM`, `MCP`, tool schemas) at
graph-build time and returns a plain `async def node(state) -> state`
callable, which is what `langgraph.graph.StateGraph.add_node` expects. The
doc's pseudocode signatures (`n_plan(state, llm, tools)`) describe the
dependency, not the literal callable shape.

Every node does at most one LLM call or one MCP call (doc 11 §2: "every node
≤ 1 LLM call"); looping across nodes is bounded by `tool_budget` and the
graph's own edge conditions (see each agent's `graph.py`), never by a node
looping internally.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any

from awp_shared.errors import AwpError
from awp_shared.llm import ToolSchema
from awp_shared.schemas import ErrorInfo, StepRecord, TaskResult, TaskStatus
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from awp_agent_base.protocols import LLMLike, MCPLike
from awp_agent_base.state import AgentState, append_step

Node = Callable[[AgentState], "Any"]


def _args_hash(args: dict[str, Any]) -> str:
    canonical = json.dumps(args, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def set_error(state: AgentState, err: AwpError) -> None:
    state["scratch"]["error"] = err.to_error_info().model_dump(mode="json")


def has_error(state: AgentState) -> bool:
    return state["scratch"].get("error") is not None


def make_validate_payload_node(payload_model: type[BaseModel] | None) -> Node:
    """doc 11 §2: payload vs intent model. `payload_model=None` (freeform /
    no registered schema for this intent) is a no-op pass-through."""

    async def node(state: AgentState) -> AgentState:
        if payload_model is not None:
            try:
                payload_model.model_validate(state["task"].payload)
            except PydanticValidationError as exc:
                set_error(
                    state,
                    AwpError(f"payload invalid for {payload_model.__name__}: {exc}"),
                )
        return state

    return node


def make_plan_node(
    llm: LLMLike,
    tools: list[ToolSchema | dict[str, Any]],
    *,
    system_prompt: str,
    guided_json: type[BaseModel] | None = None,
) -> Node:
    """guided_json ToolPlan | direct tool_call (doc 11 §2)."""

    async def node(state: AgentState) -> AgentState:
        if state["tool_budget"] <= 0:
            set_error(state, AwpError("tool budget exhausted before planning"))
            return state

        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "intent": state["task"].intent,
                        "payload": state["task"].payload,
                        "prior_steps": [s.model_dump(mode="json") for s in state["steps"]],
                    },
                    default=str,
                ),
            },
        ]
        resp = await llm.chat(messages, tools=tools or None, guided_json=guided_json)
        state["scratch"]["plan"] = {
            "content": resp.content,
            "tool_calls": [tc.model_dump() for tc in resp.tool_calls],
        }
        return state

    return node


def make_execute_tool_node(mcp: MCPLike, *, tool_servers: dict[str, str]) -> Node:
    """Pops the next planned tool call, validates it names a known
    `tool -> server` mapping (`tool_servers`), calls it, and records a
    `StepRecord`. Never trusts the plan's server/tool pair blindly — an
    unknown tool name fails the step instead of calling an arbitrary server.
    """

    async def node(state: AgentState) -> AgentState:
        plan = state["scratch"].get("plan") or {}
        calls: list[dict[str, Any]] = plan.get("tool_calls") or []
        if not calls:
            return state

        call = calls.pop(0)
        state["scratch"]["plan"] = {**plan, "tool_calls": calls}

        name = call.get("name", "")
        args = call.get("arguments", {})
        server = tool_servers.get(name)

        if state["tool_budget"] <= 0:
            set_error(state, AwpError("tool budget exhausted"))
            return state
        state["tool_budget"] -= 1

        if server is None:
            append_step(
                state,
                StepRecord(
                    tool=name,
                    server="unknown",
                    args_hash=_args_hash(args),
                    ok=False,
                    error=ErrorInfo(
                        code="VALIDATION", message=f"unplanned tool: {name}", retryable=False
                    ),
                ),
            )
            return state

        try:
            result = await mcp.call(server, name, args)
            append_step(
                state,
                StepRecord(
                    tool=name,
                    server=server,
                    args_hash=_args_hash(args),
                    ok=True,
                    result_summary=json.dumps(result, default=str)[:500],
                ),
            )
        except AwpError as exc:
            append_step(
                state,
                StepRecord(
                    tool=name,
                    server=server,
                    args_hash=_args_hash(args),
                    ok=False,
                    error=exc.to_error_info(),
                ),
            )
        return state

    return node


def has_pending_tool_calls(state: AgentState) -> bool:
    plan = state["scratch"].get("plan") or {}
    calls: list[Any] = plan.get("tool_calls") or []
    return bool(calls)


def make_check_approval_node(mcp: MCPLike) -> Node:
    """Polls `mcp-approvals.get_approval_status` once per node call. Doesn't
    block inside the node (every node is ≤ 1 call, doc 11 §2) — if still
    pending, the graph edge (built by each agent's `graph.py`) routes to END
    with `TaskStatus.AWAITING_APPROVAL`, and the task-bus's redelivery /
    ORCH-0's monitor-loop re-triggers this node on the next pass."""

    async def node(state: AgentState) -> AgentState:
        gate = state["scratch"].get("approval_gate")
        approval_id = state["scratch"].get("approval_id")
        if not gate or not approval_id:
            set_error(state, AwpError("n_check_approval reached with no pending approval"))
            return state

        result = await mcp.call("approvals", "get_approval_status", {"approval_id": approval_id})
        state["scratch"]["approval_status"] = result.get("status", "pending")
        # Only present once `status == "approved"` (doc 08 §5) — the caller
        # needs this to retry the gated tool call with `approval_token` set;
        # dropping it here (as an earlier version of this node did) silently
        # strands every gated flow at "approved" with no way to finish.
        if "token" in result:
            state["scratch"]["approval_token"] = result["token"]
        return state

    return node


def approval_is_granted(state: AgentState) -> bool:
    return state["scratch"].get("approval_status") == "approved"


def make_summarize_node(llm: LLMLike) -> Node:
    async def node(state: AgentState) -> AgentState:
        messages = [
            {
                "role": "system",
                "content": "Summarize the outcome of this task in 1-2 sentences for the requester.",
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "intent": state["task"].intent,
                        "steps": [s.model_dump(mode="json") for s in state["steps"]],
                    },
                    default=str,
                ),
            },
        ]
        resp = await llm.chat(messages, profile="draft")
        state["result"] = TaskResult(
            task_id=state["task"].task_id,
            status=TaskStatus.DONE,
            summary=resp.content or "done",
        )
        return state

    return node


async def n_fail(state: AgentState) -> AgentState:
    err = state["scratch"].get("error") or {
        "code": "INTERNAL",
        "message": "unknown failure",
        "retryable": False,
        "details": {},
    }
    state["result"] = TaskResult(
        task_id=state["task"].task_id,
        status=TaskStatus.FAILED,
        summary=err.get("message", "failed"),
        error=ErrorInfo.model_validate(err),
    )
    return state
