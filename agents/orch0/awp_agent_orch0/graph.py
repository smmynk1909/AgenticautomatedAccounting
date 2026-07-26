"""ORCH-0's LangGraph state machine — doc 02 §3:

    [ingress] -> [classify_intent] -> known? -> [load_playbook] -> [plan_dag]
                                            -> [validate_plan] -> [dispatch] -> [respond]
                              \\-> no -> [freeform_triage] -> mapped? -> [load_playbook]
                                                          \\-> no -> [create_ticket_fallback]
                                                                      -> [respond]

`validate_plan` re-routes to `plan_dag` once on failure (doc 02 §8: "one
re-plan attempt with error feedback appended"), then to
`create_ticket_fallback` on a second failure ("second failure -> human
ticket"). The "monitor loop" and "aggregate" steps from the doc's pseudocode
are NOT graph nodes here — see `reconcile.py`'s docstring for why.
"""

from __future__ import annotations

from typing import Any

from awp_agent_base.state import AgentState
from awp_shared.bus import TaskBus
from langgraph.graph import END, StateGraph

from awp_agent_orch0 import nodes as n
from awp_agent_orch0.intent_registry import IntentRegistry


def _route_after_classify(state: AgentState) -> str:
    return "known" if n.is_known_intent(state) else "freeform"


def _route_after_validate(state: AgentState) -> str:
    if n.plan_is_valid(state):
        return "dispatch"
    if n.can_replan(state):
        return "replan"
    return "ticket"


def _route_after_freeform(state: AgentState) -> str:
    return "mapped" if n.freeform_mapped_to_intent(state) else "ticket"


def build_graph(llm: Any, mcp: Any, bus: TaskBus, registry: IntentRegistry) -> Any:
    graph = StateGraph(AgentState)
    graph.add_node("classify_intent", n.make_classify_intent_node(llm, registry))
    graph.add_node("load_playbook", n.make_load_playbook_node(registry))
    graph.add_node("plan_dag", n.make_plan_dag_node(llm))
    graph.add_node("validate_plan", n.make_validate_plan_node(registry))
    graph.add_node("dispatch", n.make_dispatch_node(mcp, bus))
    graph.add_node("freeform_triage", n.make_freeform_triage_node(llm, registry))
    graph.add_node("create_ticket_fallback", n.make_create_ticket_fallback_node(mcp))
    graph.add_node("respond", n.make_respond_node(mcp))

    graph.set_entry_point("classify_intent")
    graph.add_conditional_edges(
        "classify_intent",
        _route_after_classify,
        {"known": "load_playbook", "freeform": "freeform_triage"},
    )
    graph.add_edge("load_playbook", "plan_dag")
    graph.add_edge("plan_dag", "validate_plan")
    graph.add_conditional_edges(
        "validate_plan",
        _route_after_validate,
        {"dispatch": "dispatch", "replan": "plan_dag", "ticket": "create_ticket_fallback"},
    )
    graph.add_edge("dispatch", "respond")
    graph.add_conditional_edges(
        "freeform_triage",
        _route_after_freeform,
        {"mapped": "load_playbook", "ticket": "create_ticket_fallback"},
    )
    graph.add_edge("create_ticket_fallback", "respond")
    graph.add_edge("respond", END)
    return graph.compile()
