"""FIN-1's LangGraph state machine — doc 06. Same code-switch-on-intent
routing as SUP-1/ADM-1 (no LLM classification node — inbound intents are
already registered by dispatch time), plus the same conditional-entry
resume pattern ADM-1 introduced for gated flows: a re-invoked task with
`scratch["awaiting_approval_for"]` set routes straight to the matching
`check_*_approval` node instead of re-running the intent node from
scratch (see `agents/adm1/awp_agent_adm1/graph.py`'s docstring for why).
"""

from __future__ import annotations

from collections.abc import Hashable
from typing import Any

from awp_agent_base.state import AgentState
from awp_shared.errors import ValidationError
from langgraph.graph import END, StateGraph

from awp_agent_fin1 import nodes as n

_INTENT_TO_NODE = {
    "run_payroll": "run_payroll",
    "generate_salary_slips": "generate_salary_slips",
    "record_expense": "record_expense",
    "month_close": "month_close",
    "create_invoice": "create_invoice",
    "compute_tax": "compute_tax",
    "financial_requirement_report": "financial_requirement_report",
}

_AWAITING_TO_CHECK_NODE = {
    "run_payroll": "check_run_payroll_approval",
    "generate_salary_slips": "check_generate_salary_slips_approval",
    "record_expense": "check_record_expense_approval",
    "month_close": "check_month_close_approval",
    "create_invoice": "check_create_invoice_approval",
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
        raise ValidationError(f"FIN-1 has no handler for intent: {intent!r}")
    return node_name


def build_graph(llm: Any, mcp: Any) -> Any:
    graph = StateGraph(AgentState)
    graph.add_node("run_payroll", n.make_run_payroll_node(mcp))
    graph.add_node("check_run_payroll_approval", n.make_check_run_payroll_approval_node(mcp))
    graph.add_node("generate_salary_slips", n.make_generate_salary_slips_node(mcp))
    graph.add_node(
        "check_generate_salary_slips_approval",
        n.make_check_generate_salary_slips_approval_node(mcp),
    )
    graph.add_node("record_expense", n.make_record_expense_node(llm, mcp))
    graph.add_node(
        "check_record_expense_approval", n.make_check_record_expense_approval_node(mcp)
    )
    graph.add_node("month_close", n.make_month_close_node(mcp))
    graph.add_node("check_month_close_approval", n.make_check_month_close_approval_node(mcp))
    graph.add_node("create_invoice", n.make_create_invoice_node(mcp))
    graph.add_node("check_create_invoice_approval", n.make_check_create_invoice_approval_node(mcp))
    graph.add_node("compute_tax", n.make_compute_tax_node(mcp))
    graph.add_node(
        "financial_requirement_report", n.make_financial_requirement_report_node(mcp)
    )
    graph.add_node("respond", n.n_respond)

    all_node_names = set(_INTENT_TO_NODE.values()) | set(_AWAITING_TO_CHECK_NODE.values())
    entry_path_map: dict[Hashable, str] = {name: name for name in all_node_names}
    graph.set_conditional_entry_point(_route_entry, entry_path_map)
    for node_name in entry_path_map.values():
        graph.add_edge(node_name, "respond")
    graph.add_edge("respond", END)
    return graph.compile()
