"""OPS-1 graph nodes — doc 05. Sprint 9 covers OPS-1a WorkTracker's
`assign_employee_project` gated flow, OPS-1b ProjectMonitor's
`project_health_report` (incl. S1 escalation on an invoice-triggering
overdue milestone), and OPS-1c DeliveryRisk's `timeline_risk_scan` (doc 12
§5 DoD: "05§5.1-2,4"). Sprint 10 adds OPS-1d CodeAssist
(`code_assist_session`, doc 12 §5 DoD "05§5.3,5"). Same optimistic-call/
approval-gate/resume pattern as every other gated flow in this codebase
(`assign_employee_project` -> `allocation_change`).
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Any

from awp_agent_base.protocols import LLMLike, MCPLike
from awp_agent_base.state import AgentState
from awp_shared.errors import ValidationError
from awp_shared.schemas import TaskResult, TaskStatus

from awp_agent_ops1 import codeassist, deliveryrisk, projectmonitor, worktracker
from awp_agent_ops1.narrative import write_report_narrative

Node = Any


def _coerce_milestone_dates(milestones: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """MCP responses cross the wire as JSON — a `sa.Date()` column comes
    back as an ISO string, not a real `date` object (`mcpc.MCP.call`
    returns plain `dict[str, Any]` from `r.json()`, no type reconstruction;
    see `shared/awp_shared/mcpc.py`). Every other agent's tools happen to
    never do date *arithmetic* on an MCP response field, so this gap was
    never hit before `projectmonitor`/`deliveryrisk`'s `due - today`
    comparisons — live-verified failure: `'<' not supported between
    instances of 'str' and 'datetime.date'`. Coerce at the node boundary,
    once, rather than in every pure function that touches `due`."""
    coerced = []
    for m in milestones:
        due = m.get("due")
        if isinstance(due, str):
            m = {**m, "due": date.fromisoformat(due)}
        coerced.append(m)
    return coerced


def _fail_missing_token(state: AgentState, flow: str) -> None:
    state["result"] = TaskResult(
        task_id=state["task"].task_id,
        status=TaskStatus.FAILED,
        summary=f"{flow}: approval was granted but no token was returned",
    )


# --- assign_employee_project (WorkTracker) ---


def make_assign_employee_project_node(mcp: MCPLike) -> Node:
    async def node(state: AgentState) -> AgentState:
        payload = state["task"].payload
        emp_id = payload["emp_id"]
        project_id = payload["project_id"]
        pct = float(payload["pct"])
        from_date = payload["from_date"]

        existing = await mcp.call(
            "erp",
            "query_allocations",
            {"emp_id": emp_id, "active_on": from_date},
        )
        conflict = worktracker.check_allocation_conflict(
            existing.get("allocations", []), pct
        )

        approval = await mcp.call(
            "approvals",
            "request_approval",
            {
                "gate": "allocation_change",
                "payload": {
                    "emp_id": emp_id,
                    "project_id": project_id,
                    "pct": pct,
                    "conflicting_pct": conflict.conflicting_pct,
                    "over_capacity": conflict.over_capacity,
                },
            },
        )
        state["scratch"]["awaiting_approval_for"] = "assign_employee_project"
        state["scratch"]["approval_id"] = approval["approval_id"]
        state["scratch"]["allocation_record"] = {
            "emp_id": emp_id,
            "project_id": project_id,
            "pct": pct,
            "from_date": from_date,
            "to_date": payload.get("to_date"),
        }
        state["result"] = TaskResult(
            task_id=state["task"].task_id,
            status=TaskStatus.AWAITING_APPROVAL,
            summary=(
                f"allocation of {emp_id} to {project_id} at {pct}% "
                f"({'over capacity — ' if conflict.over_capacity else ''}"
                f"{conflict.conflicting_pct}% total) awaiting manager approval"
            ),
        )
        return state

    return node


def make_check_assign_employee_project_approval_node(mcp: MCPLike) -> Node:
    async def node(state: AgentState) -> AgentState:
        approval_id = state["scratch"].get("approval_id")
        if not approval_id:
            raise ValidationError(
                "check_assign_employee_project_approval reached with no approval_id"
            )

        result = await mcp.call("approvals", "get_approval_status", {"approval_id": approval_id})
        status = result.get("status", "pending")
        if status == "pending":
            state["result"] = TaskResult(
                task_id=state["task"].task_id,
                status=TaskStatus.AWAITING_APPROVAL,
                summary="still awaiting allocation_change approval",
            )
            return state
        if status != "approved":
            state["result"] = TaskResult(
                task_id=state["task"].task_id,
                status=TaskStatus.FAILED,
                summary=f"allocation_change approval was {status}",
            )
            return state
        if not result.get("token"):
            _fail_missing_token(state, "assign_employee_project")
            return state

        record = state["scratch"]["allocation_record"]
        created = await mcp.call("erp", "upsert_allocation", {"record": record})
        state["scratch"].pop("awaiting_approval_for", None)
        state["result"] = TaskResult(
            task_id=state["task"].task_id,
            status=TaskStatus.DONE,
            summary=f"allocation {created['id']} committed for {record['emp_id']}",
        )
        return state

    return node


# --- project_health_report (ProjectMonitor) ---


def make_project_health_report_node(llm: LLMLike, mcp: MCPLike) -> Node:
    async def node(state: AgentState) -> AgentState:
        payload = state["task"].payload
        project_id = payload["project_id"]
        today = datetime.now(UTC).date()

        project = await mcp.call("erp", "get_project", {"project_id": project_id})
        milestones_result = await mcp.call(
            "erp", "query_milestones", {"project_id": project_id}
        )
        work_logs_result = await mcp.call("erp", "query_work_logs", {"project_id": project_id})
        milestones = _coerce_milestone_dates(milestones_result.get("milestones", []))
        work_logs = work_logs_result.get("work_logs", [])

        report = projectmonitor.assemble_health_report(project, milestones, work_logs, today)
        narrative = await write_report_narrative(llm, report)

        await mcp.call(
            "erp",
            "push_dashboard_item",
            {
                "item": {
                    "audience_roles": ["manager", "director"],
                    "panel": "project_health",
                    "severity": report.worst_risk_severity,
                    "title": f"Health report: {report.client}",
                    "body": narrative,
                    "action_link": None,
                    "source_task_id": str(state["task"].task_id),
                }
            },
        )

        # doc 05 §2.3: an overdue *invoice-triggering* milestone is a
        # client-facing slip on a committed date — doc's own S1 definition
        # — auto-raised as an S1 delivery issue with immediate escalation,
        # rather than waiting for a human to notice the health report.
        s1_overdue = [m for m in report.overdue if m.get("invoice_trigger")]
        escalated = False
        if s1_overdue:
            issue = await mcp.call(
                "projects",
                "create_issue",
                {
                    "project_id": project_id,
                    "description": (
                        f"Invoice-triggering milestone(s) overdue: "
                        f"{', '.join(m['title'] for m in s1_overdue)}"
                    ),
                    "impact": "schedule",
                    "severity": "S1",
                },
            )
            if deliveryrisk.is_s1(issue):
                await mcp.call(
                    "comms",
                    "notify_user",
                    {
                        "user_id": "director",
                        "subject": f"S1 delivery issue: {report.client}",
                        "body": issue["description"],
                        "refs": {"issue_id": issue["id"], "project_id": project_id},
                    },
                )
                await mcp.call(
                    "erp",
                    "push_dashboard_item",
                    {
                        "item": {
                            "audience_roles": ["director"],
                            "panel": "ceo_dashboard",
                            "severity": "critical",
                            "title": f"S1: {report.client}",
                            "body": issue["description"],
                            "action_link": None,
                            "source_task_id": str(state["task"].task_id),
                        }
                    },
                )
                escalated = True

        state["scratch"]["health_report"] = {
            "hours_burned": report.hours_burned,
            "burn_variance_pct": report.burn_variance_pct,
            "schedule_variance_pct": report.schedule_variance_pct,
            "at_risk_count": len(report.at_risk),
            "overdue_count": len(report.overdue),
        }
        state["result"] = TaskResult(
            task_id=state["task"].task_id,
            status=TaskStatus.DONE,
            summary=(
                f"health report published for {report.client}"
                + (" — S1 escalated to Director" if escalated else "")
            ),
        )
        return state

    return node


# --- timeline_risk_scan (DeliveryRisk) ---


def make_timeline_risk_scan_node(mcp: MCPLike) -> Node:
    async def node(state: AgentState) -> AgentState:
        payload = state["task"].payload
        horizon_days = payload.get("horizon_days", deliveryrisk.TIMELINE_RADAR_DEFAULT_HORIZON_DAYS)
        today = datetime.now(UTC).date()

        projects_result = await mcp.call("erp", "query_projects", {"status": "active"})
        milestones_by_project: dict[str, list[dict[str, Any]]] = {}
        for project in projects_result.get("projects", []):
            m_result = await mcp.call(
                "erp", "query_milestones", {"project_id": project["id"]}
            )
            milestones_by_project[project["id"]] = _coerce_milestone_dates(
                m_result.get("milestones", [])
            )

        items = deliveryrisk.timeline_radar(milestones_by_project, today, horizon_days)

        body = (
            "; ".join(f"{i.title} (due in {i.days_until_due}d)" for i in items[:10])
            if items
            else "no timelines within the horizon"
        )
        await mcp.call(
            "erp",
            "push_dashboard_item",
            {
                "item": {
                    "audience_roles": ["manager", "director"],
                    "panel": "key_timelines",
                    "severity": "info" if not items else "warning",
                    "title": f"Key timelines (next {horizon_days}d)",
                    "body": body,
                    "action_link": None,
                    "source_task_id": str(state["task"].task_id),
                }
            },
        )
        state["scratch"]["timeline_item_count"] = len(items)
        state["result"] = TaskResult(
            task_id=state["task"].task_id,
            status=TaskStatus.DONE,
            summary=f"timeline radar published: {len(items)} item(s) within {horizon_days}d",
        )
        return state

    return node


# --- code_assist_session (CodeAssist) ---


def make_code_assist_session_node(llm_code: LLMLike, mcp: MCPLike) -> Node:
    async def node(state: AgentState) -> AgentState:
        payload = state["task"].payload
        project_id = payload["project_id"]
        mode = payload["mode"]
        input_text = payload["input"]
        emp_id = payload["emp_id"]

        # doc 05 §5.5's ACL-leakage test: no access -> zero code context,
        # checked *before* any repo call is made, not filtered after.
        if not await codeassist.has_repo_access(mcp, emp_id, project_id):
            state["result"] = TaskResult(
                task_id=state["task"].task_id,
                status=TaskStatus.FAILED,
                summary=(
                    f"employee {emp_id} has no allocation to project {project_id} — "
                    "zero code context returned"
                ),
            )
            return state

        context = input_text if mode == "review" else ""
        if mode != "review":
            project = await mcp.call("erp", "get_project", {"project_id": project_id})
            repo_slug = project.get("repo_slug")
            if repo_slug:
                search_result = await mcp.call(
                    "search",
                    "search_kb",
                    {
                        "corpus": codeassist.code_corpus_name(repo_slug),
                        "query": input_text,
                        "k": 3,
                    },
                )
                context = "\n\n".join(r["text"] for r in search_result.get("results", []))

        # doc 05 §2.4: "secrets scanner runs on all context before it
        # reaches the model" — redact, not just detect-and-log.
        scan_result = await mcp.call("projects", "secrets_scan", {"text": context})
        safe_context = scan_result.get("redacted_text", context)
        secrets_redacted = not scan_result.get("clean", True)

        result = await codeassist.run_mode(llm_code, mode, safe_context, input_text)
        summary = result.model_dump() if hasattr(result, "model_dump") else result

        # `TaskResult.summary` is the only free-text field this schema has,
        # and (unlike every other intent here, whose real output lands in a
        # dashboard item or notification) code_assist_session's whole
        # *point* is the text itself — the gateway's IDE endpoint has
        # nothing else to return to the caller. A structured `review`
        # result is JSON-encoded into the same field for the same reason.
        response_text = summary if isinstance(summary, str) else json.dumps(summary)
        if secrets_redacted:
            response_text += "\n\n(note: secrets were redacted from the repo context used here)"

        state["scratch"]["code_assist_result"] = summary
        state["result"] = TaskResult(
            task_id=state["task"].task_id,
            status=TaskStatus.DONE,
            summary=response_text,
        )
        return state

    return node


# --- shared respond ---


async def n_respond(state: AgentState) -> AgentState:
    if state.get("result") is not None:
        return state
    state["result"] = TaskResult(
        task_id=state["task"].task_id,
        status=TaskStatus.DONE,
        summary=f"handled {state['task'].intent}",
    )
    return state
