"""ADM-1's LangGraph state machine — doc 03. Like SUP-1, routing is a plain
code switch on `TaskEnvelope.intent` (no LLM classification node) — ADM-1's
inbound intents are already registered (`config/intents.yaml`'s `agent:
ADM-1` entries) by the time ORCH-0/the scheduler dispatches them.

One addition SUP-1 doesn't need: `issue_device`/`update_employee_record`
are conditionally gated (doc 03 §2.1/§2.2). When a task carrying
`scratch["awaiting_approval_for"]` is re-invoked (see `nodes.py`'s module
docstring for what's expected to trigger that), entry routing sends it
straight to the matching `check_*_approval` node instead of re-running the
intent node from scratch, which would re-reserve/re-request.
"""

from __future__ import annotations

from collections.abc import Hashable
from typing import Any

from awp_agent_base.state import AgentState
from awp_shared.errors import ValidationError
from langgraph.graph import END, StateGraph

from awp_agent_adm1 import nodes as n

_INTENT_TO_NODE = {
    "issue_device": "issue_device",
    "return_device": "return_device",
    "device_repair": "device_repair",
    "add_candidate_record": "add_candidate_record",
    "update_employee_record": "update_employee_record",
    "dashboard_refresh": "dashboard_refresh",
    "resolve_admin_ticket": "resolve_admin_ticket",
}

_AWAITING_TO_CHECK_NODE = {
    "issue_device": "check_issue_device_approval",
    "update_employee_record": "check_update_employee_approval",
}


def _route_entry(state: AgentState) -> str:
    awaiting = state["scratch"].get("awaiting_approval_for")
    if awaiting is not None:
        check_node = _AWAITING_TO_CHECK_NODE.get(awaiting)
        if check_node is None:
            raise ValidationError(f"unknown awaiting_approval_for flow: {awaiting!r}")
        return check_node

    intent = state["task"].intent
    node_name = _INTENT_TO_NODE.get(intent)
    if node_name is None:
        raise ValidationError(f"ADM-1 has no handler for intent: {intent!r}")
    return node_name


def build_graph(llm: Any, mcp: Any) -> Any:
    graph = StateGraph(AgentState)
    graph.add_node("issue_device", n.make_issue_device_node(mcp))
    graph.add_node("check_issue_device_approval", n.make_check_issue_device_approval_node(mcp))
    graph.add_node("return_device", n.make_return_device_node(mcp))
    graph.add_node("device_repair", n.make_device_repair_node(mcp))
    graph.add_node("add_candidate_record", n.make_add_candidate_record_node(mcp))
    graph.add_node("update_employee_record", n.make_update_employee_record_node(mcp))
    graph.add_node(
        "check_update_employee_approval", n.make_check_update_employee_approval_node(mcp)
    )
    graph.add_node("dashboard_refresh", n.make_dashboard_refresh_node(mcp))
    graph.add_node("resolve_admin_ticket", n.make_resolve_admin_ticket_node(llm, mcp))
    graph.add_node("respond", n.n_respond)

    all_node_names = set(_INTENT_TO_NODE.values()) | set(_AWAITING_TO_CHECK_NODE.values())
    entry_path_map: dict[Hashable, str] = {name: name for name in all_node_names}
    graph.set_conditional_entry_point(_route_entry, entry_path_map)
    for node_name in entry_path_map.values():
        graph.add_edge(node_name, "respond")
    graph.add_edge("respond", END)
    return graph.compile()
