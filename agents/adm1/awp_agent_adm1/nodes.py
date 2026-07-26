"""ADM-1 graph nodes — doc 03. One handler node per registered ADM-1 intent
(`issue_device`, `return_device`, `device_repair`, `add_candidate_record`,
`update_employee_record`, `dashboard_refresh`, `resolve_admin_ticket`, doc
02 §5 / `config/intents.yaml`) plus two resume nodes for the two
conditionally-gated intents. Same factory convention as
`awp_agent_base.nodes` — see that module's docstring.

Gated flows (`issue_device` -> `asset_high_value`, `update_employee_record`
-> `record_correction`) call the gated `mcp-erp` tool optimistically first
(no `approval_token`), and only start the request-approval detour on an
`ApprovalRequiredError` — the threshold/identity-field policy that decides
*whether* a gate applies lives entirely in `mcp-erp`'s own tool handlers
(`assign_asset`, `upsert_employee`), never duplicated here (doc 03 §4 rule
2: "policy comes from policy tables via tools"). `graph.py`'s entry routing
sends a re-invoked task straight to the matching `check_*_approval` node
when `scratch["awaiting_approval_for"]` is already set, instead of
re-running the intent node (which would re-reserve/re-request).

What re-triggers that re-invocation once a human approves — some caller
re-dispatching a `TaskEnvelope` with the same `task_id` so `AgentApp.handle`
reloads this checkpoint — isn't wired yet; `gateway/awp_gateway/routers/
approvals.py`'s `approve_endpoint` doesn't re-dispatch anything today. Doc
11 §2's design fully supports it (this graph's resume path is written and
tested against it directly); the actual trigger is a follow-up integration
task, not an ADM-1 gap.
"""

from __future__ import annotations

from typing import Any

from awp_agent_base.protocols import LLMLike, MCPLike
from awp_agent_base.state import AgentState
from awp_shared.errors import ApprovalRequiredError, ConflictError, ValidationError
from awp_shared.schemas import AgentId, TaskResult, TaskStatus

from awp_agent_adm1 import assetkeeper, dashboard, registry, tickets

Node = Any


def _fail_missing_token(state: AgentState, flow: str) -> None:
    state["result"] = TaskResult(
        task_id=state["task"].task_id,
        status=TaskStatus.FAILED,
        summary=f"{flow}: approval was granted but no token was returned",
    )


def make_issue_device_node(mcp: MCPLike) -> Node:
    async def node(state: AgentState) -> AgentState:
        payload = state["task"].payload
        emp_id = payload["emp_id"]
        asset_type = payload["asset_type"]
        ticket_ref = payload.get("ticket_ref")

        employee = await mcp.call("erp", "get_employee", {"emp_id": emp_id})
        if employee.get("status") != "active":
            raise ValidationError(f"employee {emp_id} is not active")

        stock = await mcp.call(
            "erp", "query_assets", {"type": asset_type, "status": "in_stock", "limit": 1}
        )
        available = stock.get("assets", [])
        if not available:
            # doc 03 §2.1 step 3 / doc 03 §6 test 3: no fabricated stock, no fake ETA.
            ticket = await mcp.call(
                "erp",
                "create_ticket",
                {
                    "channel": "agent",
                    "requester": {"type": "agent", "id": AgentId.ADM1.value},
                    "category": "procurement",
                    "subject": f"Procurement needed: {asset_type} for {emp_id}",
                    "body": f"No {asset_type} in stock to issue to {emp_id}.",
                },
            )
            await mcp.call(
                "comms",
                "notify_user",
                {
                    "user_id": emp_id,
                    "subject": "Device request delayed",
                    "body": (
                        f"No {asset_type} is currently in stock. Procurement ticket "
                        f"{ticket['ticket_id']} has been filed; we don't have a firm ETA "
                        "yet and will update you once procurement responds."
                    ),
                },
            )
            state["scratch"]["procurement_ticket_id"] = ticket["ticket_id"]
            return state

        asset = available[0]  # FIFO on purchase_date — AssetRepo.query's own order
        reservation = await mcp.call(
            "erp", "reserve_asset", {"asset_id": asset["id"], "emp_id": emp_id}
        )
        pdf_data = assetkeeper.build_issuance_pdf_data(employee, asset, ticket_ref)
        pdf = await mcp.call(
            "docs", "render_pdf", {"template_id": "issuance_form_v1", "data": pdf_data}
        )
        state["scratch"]["issuance_pdf_uri"] = pdf["uri"]

        try:
            assignment = await mcp.call(
                "erp", "assign_asset", {"reservation_id": reservation["reservation_id"]}
            )
        except ApprovalRequiredError:
            approval = await mcp.call(
                "approvals",
                "request_approval",
                {
                    "gate": "asset_high_value",
                    "payload": assetkeeper.approval_request_payload(reservation, asset),
                },
            )
            state["scratch"]["awaiting_approval_for"] = "issue_device"
            state["scratch"]["approval_gate"] = "asset_high_value"
            state["scratch"]["approval_id"] = approval["approval_id"]
            state["scratch"]["reservation_id"] = reservation["reservation_id"]
            state["scratch"]["emp_id"] = emp_id
            state["result"] = TaskResult(
                task_id=state["task"].task_id,
                status=TaskStatus.AWAITING_APPROVAL,
                summary=f"awaiting manager approval to issue high-value asset {asset['id']}",
            )
            return state

        await _notify_issuance(mcp, emp_id, assignment["asset_id"])
        state["scratch"]["asset_id"] = assignment["asset_id"]
        return state

    return node


async def _notify_issuance(mcp: MCPLike, emp_id: str, asset_id: str) -> None:
    await mcp.call(
        "comms",
        "notify_user",
        {
            "user_id": emp_id,
            "subject": "Device issued to you",
            "body": f"Asset {asset_id} has been issued to you. Please confirm receipt.",
        },
    )


def make_check_issue_device_approval_node(mcp: MCPLike) -> Node:
    """Resume path for `issue_device`. Doesn't reuse
    `awp_agent_base.nodes.make_check_approval_node` as-is: on approval it
    also needs to finalize (`assign_asset` with the token) and notify, not
    just record the status, so the extra call lives here rather than forking
    the shared node's contract for one caller."""

    async def node(state: AgentState) -> AgentState:
        approval_id = state["scratch"].get("approval_id")
        if not approval_id:
            raise ValidationError("check_issue_device_approval reached with no approval_id")

        result = await mcp.call("approvals", "get_approval_status", {"approval_id": approval_id})
        status = result.get("status", "pending")
        if status == "pending":
            state["result"] = TaskResult(
                task_id=state["task"].task_id,
                status=TaskStatus.AWAITING_APPROVAL,
                summary="still awaiting manager approval",
            )
            return state
        if status != "approved":
            state["result"] = TaskResult(
                task_id=state["task"].task_id,
                status=TaskStatus.FAILED,
                summary=f"asset issuance approval was {status}",
            )
            return state

        token = result.get("token")
        if not token:
            _fail_missing_token(state, "issue_device")
            return state

        assignment = await mcp.call(
            "erp",
            "assign_asset",
            {
                "reservation_id": state["scratch"]["reservation_id"],
                "approval_token": token,
            },
        )
        await _notify_issuance(mcp, state["scratch"]["emp_id"], assignment["asset_id"])
        state["scratch"]["asset_id"] = assignment["asset_id"]
        state["scratch"].pop("awaiting_approval_for", None)
        return state

    return node


def make_return_device_node(mcp: MCPLike) -> Node:
    async def node(state: AgentState) -> AgentState:
        payload = state["task"].payload
        asset = await mcp.call(
            "erp",
            "return_asset",
            {
                "asset_id": payload["asset_id"],
                "condition_report": payload.get("condition_report", {}),
            },
        )
        state["scratch"]["asset_id"] = asset["id"]
        return state

    return node


def make_device_repair_node(mcp: MCPLike) -> Node:
    async def node(state: AgentState) -> AgentState:
        payload = state["task"].payload
        asset_id = payload["asset_id"]
        ticket = await mcp.call(
            "erp",
            "create_ticket",
            {
                "channel": "agent",
                "requester": {"type": "agent", "id": AgentId.ADM1.value},
                "category": "device",
                "subcategory": "repair",
                "subject": f"Repair vendor ticket for asset {asset_id}",
                "body": payload["issue_description"],
            },
        )
        state["scratch"]["ticket_id"] = ticket["ticket_id"]
        return state

    return node


def make_add_candidate_record_node(mcp: MCPLike) -> Node:
    async def node(state: AgentState) -> AgentState:
        candidate = state["task"].payload["candidate"]
        try:
            created = await mcp.call("erp", "upsert_candidate", {"record": {"profile": candidate}})
            state["scratch"]["candidate_id"] = created["id"]
        except ConflictError as exc:
            matches = exc.details.get("matches", [])
            item = registry.duplicate_candidate_dashboard_item(
                candidate, matches, str(state["task"].task_id)
            )
            await mcp.call("erp", "push_dashboard_item", {"item": item})
            state["scratch"]["duplicate_flagged"] = True
        return state

    return node


def make_update_employee_record_node(mcp: MCPLike) -> Node:
    async def node(state: AgentState) -> AgentState:
        payload = state["task"].payload
        record = registry.build_employee_record(payload["emp_id"], payload["patch"])

        try:
            updated = await mcp.call("erp", "upsert_employee", {"record": record})
        except ApprovalRequiredError:
            approval = await mcp.call(
                "approvals", "request_approval", {"gate": "record_correction", "payload": record}
            )
            state["scratch"]["awaiting_approval_for"] = "update_employee_record"
            state["scratch"]["approval_gate"] = "record_correction"
            state["scratch"]["approval_id"] = approval["approval_id"]
            state["scratch"]["employee_record"] = record
            state["result"] = TaskResult(
                task_id=state["task"].task_id,
                status=TaskStatus.AWAITING_APPROVAL,
                summary=f"awaiting admin_head approval to correct employee {record['emp_id']}",
            )
            return state

        state["scratch"]["emp_id"] = updated["emp_id"]
        return state

    return node


def make_check_update_employee_approval_node(mcp: MCPLike) -> Node:
    async def node(state: AgentState) -> AgentState:
        approval_id = state["scratch"].get("approval_id")
        if not approval_id:
            raise ValidationError("check_update_employee_approval reached with no approval_id")

        result = await mcp.call("approvals", "get_approval_status", {"approval_id": approval_id})
        status = result.get("status", "pending")
        if status == "pending":
            state["result"] = TaskResult(
                task_id=state["task"].task_id,
                status=TaskStatus.AWAITING_APPROVAL,
                summary="still awaiting admin_head approval",
            )
            return state
        if status != "approved":
            state["result"] = TaskResult(
                task_id=state["task"].task_id,
                status=TaskStatus.FAILED,
                summary=f"employee record correction approval was {status}",
            )
            return state

        token = result.get("token")
        if not token:
            _fail_missing_token(state, "update_employee_record")
            return state

        record = {**state["scratch"]["employee_record"], "approval_token": token}
        updated = await mcp.call("erp", "upsert_employee", {"record": record})
        state["scratch"]["emp_id"] = updated["emp_id"]
        state["scratch"].pop("awaiting_approval_for", None)
        return state

    return node


def make_dashboard_refresh_node(mcp: MCPLike) -> Node:
    async def node(state: AgentState) -> AgentState:
        report = await dashboard.push_asset_register_panel(mcp)
        state["scratch"]["dashboard_asset_count"] = report["count"]
        return state

    return node


def make_resolve_admin_ticket_node(llm: LLMLike, mcp: MCPLike) -> Node:
    async def node(state: AgentState) -> AgentState:
        ticket_id = state["task"].payload["ticket_id"]
        ticket = await mcp.call("erp", "get_ticket", {"ticket_id": ticket_id})

        classification = await tickets.classify_ticket(
            llm, ticket["category"], ticket.get("subcategory"), ticket.get("summary_current", "")
        )
        matched = tickets.auto_resolve_match(classification)
        note = tickets.draft_resolution_note(classification, matched)

        await mcp.call(
            "erp",
            "append_ticket_event",
            {"ticket_id": ticket_id, "event": {"type": "resolution_note", "body": note}},
        )

        if matched is not None:
            await mcp.call(
                "erp", "update_ticket", {"ticket_id": ticket_id, "patch": {"status": "resolved"}}
            )
            state["scratch"]["ticket_resolution"] = "auto_resolved"
        else:
            await mcp.call(
                "erp",
                "push_dashboard_item",
                {
                    "item": {
                        "audience_roles": ["admin_head"],
                        "panel": "admin_tickets",
                        "severity": "warning",
                        "title": f"Ticket {ticket_id} needs admin review",
                        "body": note["diagnosis"][:400],
                        "source_task_id": str(state["task"].task_id),
                    }
                },
            )
            state["scratch"]["ticket_resolution"] = "escalated"

        state["scratch"]["ticket_id"] = ticket_id
        return state

    return node


async def n_respond(state: AgentState) -> AgentState:
    if state.get("result") is not None:
        # issue_device / update_employee_record already set a
        # DONE/AWAITING_APPROVAL/FAILED result on the approval-detour paths.
        return state

    scratch = state["scratch"]
    summary = f"handled {state['task'].intent}"
    if scratch.get("procurement_ticket_id"):
        summary = f"no stock available; filed procurement ticket {scratch['procurement_ticket_id']}"
    elif scratch.get("duplicate_flagged"):
        summary = "possible duplicate candidate flagged for admin review"
    elif scratch.get("ticket_resolution"):
        summary = f"ticket {scratch['ticket_id']}: {scratch['ticket_resolution']}"
    elif scratch.get("asset_id"):
        summary += f" for asset {scratch['asset_id']}"
    elif scratch.get("emp_id"):
        summary += f" for employee {scratch['emp_id']}"

    state["result"] = TaskResult(
        task_id=state["task"].task_id, status=TaskStatus.DONE, summary=summary
    )
    return state
