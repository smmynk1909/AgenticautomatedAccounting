"""SUP-1 graph nodes — doc 07. One handler node per registered SUP-1 intent
(`create_ticket`, `escalate_ticket`, `cross_dept_request`, `sla_report`,
doc 02 §5). Same factory convention as `awp_agent_base.nodes` and
`awp_agent_orch0.nodes` — see the former's docstring.
"""

from __future__ import annotations

from typing import Any

from awp_agent_base.protocols import LLMLike, MCPLike
from awp_agent_base.state import AgentState
from awp_shared.errors import ValidationError
from awp_shared.schemas import TaskResult, TaskStatus

from awp_agent_sup1 import intake, reporter, router, statuskeeper

Node = Any


def _requester(state: AgentState) -> dict[str, str]:
    payload_requester = state["task"].payload.get("requester")
    if payload_requester:
        result: dict[str, str] = payload_requester
        return result
    return {"type": "agent", "id": state["task"].from_agent.value}


def make_create_ticket_node(llm: LLMLike, mcp: MCPLike) -> Node:
    async def node(state: AgentState) -> AgentState:
        payload = state["task"].payload
        category = payload["category"]
        body = payload.get("body", "")
        subcategory = payload.get("subcategory")

        classification = None
        if not intake.is_confidential(subcategory):
            classification = await intake.classify_freeform(llm, category, body)
            subcategory = classification.subcategory or subcategory

        priority = intake.apply_priority_policy(
            category,
            subcategory,
            body,
            classification.priority_suggestion if classification else "P3",
        )

        result = await mcp.call(
            "erp",
            "create_ticket",
            {
                "channel": payload["channel"],
                "requester": _requester(state),
                "category": category,
                "subcategory": subcategory,
                "subject": payload["subject"],
                "body": body,
                "priority": priority.value,
            },
        )
        state["scratch"]["ticket_id"] = result["ticket_id"]
        return state

    return node


def make_escalate_ticket_node(mcp: MCPLike) -> Node:
    async def node(state: AgentState) -> AgentState:
        payload = state["task"].payload
        ticket_id = payload.get("ticket_id")
        reason = payload.get("reason", "")
        if not ticket_id:
            raise ValidationError("escalate_ticket requires 'ticket_id'")

        await mcp.call(
            "erp",
            "append_ticket_event",
            {"ticket_id": ticket_id, "event": {"type": "escalation", "body": {"reason": reason}}},
        )
        await mcp.call(
            "erp",
            "push_dashboard_item",
            {
                "audience_roles": ["support_lead", "manager"],
                "panel": "ticket_fabric",
                "severity": "warning",
                "title": f"Ticket {ticket_id} escalated",
                "body": reason[:400],
                "source_task_id": str(state["task"].task_id),
            },
        )
        state["scratch"]["ticket_id"] = ticket_id
        return state

    return node


def make_cross_dept_request_node(mcp: MCPLike) -> Node:
    async def node(state: AgentState) -> AgentState:
        payload = state["task"].payload
        parent_ticket_id = payload.get("parent_ticket_id")
        departments = payload.get("departments") or []
        if not parent_ticket_id or not departments:
            raise ValidationError("cross_dept_request requires 'parent_ticket_id', 'departments'")

        child_ids = await router.fan_out_cross_functional(
            mcp, parent_ticket_id, departments, _requester(state)
        )
        state["scratch"]["ticket_id"] = parent_ticket_id
        state["scratch"]["child_ticket_ids"] = child_ids
        return state

    return node


def make_sla_report_node(mcp: MCPLike) -> Node:
    async def node(state: AgentState) -> AgentState:
        counts = await reporter.push_daily_dashboard(mcp)
        state["scratch"]["report_counts"] = counts
        return state

    return node


def make_refresh_summary_node(llm: LLMLike, mcp: MCPLike) -> Node:
    """Not wired to a public intent — called directly by
    `awp_agent_sup1.reconcile.refresh_stale_summaries` (a scheduler-driven
    sweep, mirroring ORCH-0's `reconcile.py`), not dispatched as a
    `TaskEnvelope`."""

    async def node(state: AgentState) -> AgentState:
        ticket_id = state["scratch"]["ticket_id"]
        await statuskeeper.refresh_summary(llm, mcp, ticket_id)
        return state

    return node


async def n_respond(state: AgentState) -> AgentState:
    ticket_id = state["scratch"].get("ticket_id")
    summary = f"handled {state['task'].intent}"
    if ticket_id:
        summary += f" for ticket {ticket_id}"
    state["result"] = TaskResult(
        task_id=state["task"].task_id, status=TaskStatus.DONE, summary=summary
    )
    return state
