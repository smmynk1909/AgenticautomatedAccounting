"""OPS-1's LangGraph state machine — doc 05. Same code-switch-on-intent
routing and conditional-entry resume pattern as FIN-1/HR-1 — see
`agents/fin1/awp_agent_fin1/graph.py`'s docstring.
"""

from __future__ import annotations

from collections.abc import Hashable
from typing import Any

from awp_agent_base.state import AgentState
from awp_shared.errors import ValidationError
from langgraph.graph import END, StateGraph

from awp_agent_ops1 import nodes as n

_INTENT_TO_NODE = {
    "assign_employee_project": "assign_employee_project",
    "project_health_report": "project_health_report",
    "timeline_risk_scan": "timeline_risk_scan",
    "code_assist_session": "code_assist_session",
}

_AWAITING_TO_CHECK_NODE = {
    "assign_employee_project": "check_assign_employee_project_approval",
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
        raise ValidationError(f"OPS-1 has no handler for intent: {intent!r}")
    return node_name


def build_graph(llm: Any, mcp: Any, llm_code: Any = None) -> Any:
    # `llm_code` defaults to `llm` so callers/tests that only need one
    # model binding (everything except code_assist_session) don't have to
    # pass two — main.py always passes the real M-CODE-bound instance.
    graph = StateGraph(AgentState)
    graph.add_node("assign_employee_project", n.make_assign_employee_project_node(mcp))
    graph.add_node(
        "check_assign_employee_project_approval",
        n.make_check_assign_employee_project_approval_node(mcp),
    )
    graph.add_node("project_health_report", n.make_project_health_report_node(llm, mcp))
    graph.add_node("timeline_risk_scan", n.make_timeline_risk_scan_node(mcp))
    graph.add_node("code_assist_session", n.make_code_assist_session_node(llm_code or llm, mcp))
    graph.add_node("respond", n.n_respond)

    all_node_names = set(_INTENT_TO_NODE.values()) | set(_AWAITING_TO_CHECK_NODE.values())
    entry_path_map: dict[Hashable, str] = {name: name for name in all_node_names}
    graph.set_conditional_entry_point(_route_entry, entry_path_map)
    for node_name in entry_path_map.values():
        graph.add_edge(node_name, "respond")
    graph.add_edge("respond", END)
    return graph.compile()
