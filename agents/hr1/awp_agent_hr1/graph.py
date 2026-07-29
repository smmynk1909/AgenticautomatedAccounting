"""HR-1's LangGraph state machine — doc 04. Same code-switch-on-intent
routing and conditional-entry resume pattern as FIN-1/ADM-1 — see
`agents/fin1/awp_agent_fin1/graph.py`'s docstring.
"""

from __future__ import annotations

from collections.abc import Hashable
from typing import Any

from awp_agent_base.state import AgentState
from awp_shared.errors import ValidationError
from langgraph.graph import END, StateGraph

from awp_agent_hr1 import nodes as n

_INTENT_TO_NODE = {
    "source_candidates": "source_candidates",
    "audit_resume": "audit_resume",
    "shortlist_role": "shortlist_role",
    "prepare_negotiation": "prepare_negotiation",
    "plan_training": "plan_training",
}

_AWAITING_TO_CHECK_NODE = {
    "shortlist_role": "check_shortlist_role_approval",
    "prepare_negotiation": "check_prepare_negotiation_approval",
    "plan_training": "check_plan_training_approval",
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
        raise ValidationError(f"HR-1 has no handler for intent: {intent!r}")
    return node_name


def build_graph(llm: Any, mcp: Any) -> Any:
    graph = StateGraph(AgentState)
    graph.add_node("source_candidates", n.make_source_candidates_node(llm, mcp))
    graph.add_node("audit_resume", n.make_audit_resume_node(mcp))
    graph.add_node("shortlist_role", n.make_shortlist_role_node(llm, mcp))
    graph.add_node("check_shortlist_role_approval", n.make_check_shortlist_role_approval_node(mcp))
    graph.add_node("prepare_negotiation", n.make_prepare_negotiation_node(llm, mcp))
    graph.add_node(
        "check_prepare_negotiation_approval", n.make_check_prepare_negotiation_approval_node(mcp)
    )
    graph.add_node("plan_training", n.make_plan_training_node(mcp))
    graph.add_node("check_plan_training_approval", n.make_check_plan_training_approval_node(mcp))
    graph.add_node("respond", n.n_respond)

    all_node_names = set(_INTENT_TO_NODE.values()) | set(_AWAITING_TO_CHECK_NODE.values())
    entry_path_map: dict[Hashable, str] = {name: name for name in all_node_names}
    graph.set_conditional_entry_point(_route_entry, entry_path_map)
    for node_name in entry_path_map.values():
        graph.add_edge(node_name, "respond")
    graph.add_edge("respond", END)
    return graph.compile()
