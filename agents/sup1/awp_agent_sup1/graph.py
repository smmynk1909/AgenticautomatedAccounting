"""SUP-1's LangGraph state machine — doc 07. No LLM-based intent
classification node: unlike ORCH-0, SUP-1's inbound `TaskEnvelope.intent` is
already one of its own registered intents (`config/intents.yaml`'s
`agent: SUP-1` entries) by the time it's dispatched — routing here is a
plain code switch on that field.
"""

from __future__ import annotations

from collections.abc import Hashable
from typing import Any

from awp_agent_base.state import AgentState
from awp_shared.errors import ValidationError
from langgraph.graph import END, StateGraph

from awp_agent_sup1 import nodes as n

_INTENT_TO_NODE = {
    "create_ticket": "create_ticket",
    "escalate_ticket": "escalate_ticket",
    "cross_dept_request": "cross_dept_request",
    "sla_report": "sla_report",
}


def _route_by_intent(state: AgentState) -> str:
    intent = state["task"].intent
    node_name = _INTENT_TO_NODE.get(intent)
    if node_name is None:
        raise ValidationError(f"SUP-1 has no handler for intent: {intent!r}")
    return node_name


def build_graph(llm: Any, mcp: Any) -> Any:
    graph = StateGraph(AgentState)
    graph.add_node("create_ticket", n.make_create_ticket_node(llm, mcp))
    graph.add_node("escalate_ticket", n.make_escalate_ticket_node(mcp))
    graph.add_node("cross_dept_request", n.make_cross_dept_request_node(mcp))
    graph.add_node("sla_report", n.make_sla_report_node(mcp))
    graph.add_node("respond", n.n_respond)

    entry_path_map: dict[Hashable, str] = {name: name for name in _INTENT_TO_NODE.values()}
    graph.set_conditional_entry_point(_route_by_intent, entry_path_map)
    for node_name in _INTENT_TO_NODE.values():
        graph.add_edge(node_name, "respond")
    graph.add_edge("respond", END)
    return graph.compile()
