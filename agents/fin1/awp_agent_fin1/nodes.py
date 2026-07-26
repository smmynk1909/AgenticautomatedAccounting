"""FIN-1 graph nodes — doc 06. One handler node per registered FIN-1 intent
(`run_payroll`, `generate_salary_slips`, `record_expense`, `month_close`,
`create_invoice`, `compute_tax`, `financial_requirement_report`, doc 02 §5
/ `config/intents.yaml`) plus resume nodes for the five gated flows
(`run_payroll` -> `payroll_run`, `generate_salary_slips` -> `slip_reissue`,
`record_expense` -> `expense_posting` (conditional), `month_close` ->
`period_close`, `create_invoice` -> `invoice_issue`). Same factory
convention and same optimistic-call-then-catch-`ApprovalRequiredError`
gating pattern as `agents/adm1/awp_agent_adm1/nodes.py` — see that
module's docstring for the reasoning, including the still-open "who
re-dispatches after a human approves" gap.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from awp_agent_base.protocols import LLMLike, MCPLike
from awp_agent_base.state import AgentState
from awp_shared.errors import ApprovalRequiredError, ValidationError
from awp_shared.schemas import TaskResult, TaskStatus

from awp_agent_fin1 import anomaly, biller, bookkeeper, fpna, payroll_flow, taxdesk

Node = Any


def _fail_missing_token(state: AgentState, flow: str) -> None:
    state["result"] = TaskResult(
        task_id=state["task"].task_id,
        status=TaskStatus.FAILED,
        summary=f"{flow}: approval was granted but no token was returned",
    )


# --- run_payroll / generate_salary_slips (PayrollRunner) ---


async def _render_slips(
    mcp: MCPLike, month: str, employees: list[dict[str, Any]], lines: list[dict[str, Any]]
) -> list[str]:
    by_id = {e["emp_id"]: e for e in employees}
    uris = []
    for line in lines:
        emp = by_id.get(line["emp_id"], {"emp_id": line["emp_id"], "name": "", "dept_id": ""})
        pdf = await mcp.call(
            "docs",
            "render_pdf",
            {
                "template_id": "salary_slip_v1",
                "data": {
                    "month": month,
                    "employee": emp,
                    "earnings": line["earnings"],
                    "deductions": line["deductions"],
                    "gross": line["gross"],
                    "net": line["net"],
                },
                "output_scope": [line["emp_id"]],
            },
        )
        uris.append(pdf["uri"])
    return uris


def make_run_payroll_node(mcp: MCPLike) -> Node:
    async def node(state: AgentState) -> AgentState:
        month = state["task"].payload["month"]
        fy = payroll_flow.fy_for_month(month)

        employees = await payroll_flow.gather_employees_for_payroll(mcp, None)
        if not employees:
            raise ValidationError(f"no active employees found for payroll month {month}")
        comp_rows = [await payroll_flow.build_comp_snapshot_row(mcp, e) for e in employees]

        frozen = await mcp.call(
            "finance",
            "freeze_payroll_inputs",
            {"month": month, "employees": comp_rows, "attendance": []},
        )
        computed = await mcp.call(
            "finance", "compute_payroll", {"snapshot_id": frozen["snapshot_id"], "fy": fy}
        )
        register = computed["register"]

        flags = anomaly.flag_anomalies(register["lines"])
        if flags:
            state["scratch"]["review_flags"] = flags

        state["scratch"]["slip_uris"] = await _render_slips(
            mcp, month, employees, register["lines"]
        )

        approval = await mcp.call(
            "approvals",
            "request_approval",
            {
                "gate": "payroll_run",
                "payload": {"register_id": frozen["snapshot_id"], "totals": register["totals"]},
            },
        )
        state["scratch"]["awaiting_approval_for"] = "run_payroll"
        state["scratch"]["approval_id"] = approval["approval_id"]
        state["scratch"]["register_id"] = frozen["snapshot_id"]
        state["scratch"]["month"] = month
        state["scratch"]["totals"] = register["totals"]
        state["scratch"]["emp_ids"] = [line["emp_id"] for line in register["lines"]]
        state["result"] = TaskResult(
            task_id=state["task"].task_id,
            status=TaskStatus.AWAITING_APPROVAL,
            summary=f"payroll register for {month} awaiting finance_head+director approval"
            + (f" ({len(flags)} anomaly flag(s))" if flags else ""),
        )
        return state

    return node


def make_check_run_payroll_approval_node(mcp: MCPLike) -> Node:
    async def node(state: AgentState) -> AgentState:
        approval_id = state["scratch"].get("approval_id")
        if not approval_id:
            raise ValidationError("check_run_payroll_approval reached with no approval_id")

        result = await mcp.call("approvals", "get_approval_status", {"approval_id": approval_id})
        status = result.get("status", "pending")
        if status == "pending":
            state["result"] = TaskResult(
                task_id=state["task"].task_id,
                status=TaskStatus.AWAITING_APPROVAL,
                summary="still awaiting payroll_run approval",
            )
            return state
        if status != "approved":
            state["result"] = TaskResult(
                task_id=state["task"].task_id,
                status=TaskStatus.FAILED,
                summary=f"payroll approval was {status}",
            )
            return state

        token = result.get("token")
        if not token:
            _fail_missing_token(state, "run_payroll")
            return state

        register_id = state["scratch"]["register_id"]
        month = state["scratch"]["month"]
        await mcp.call(
            "finance",
            "generate_disbursement_file",
            {"register_id": register_id, "approval_token": token},
        )

        lines = payroll_flow.salary_journal_lines(state["scratch"]["totals"])
        await mcp.call(
            "finance",
            "post_journal",
            {
                "entry": {
                    "date": datetime.now(UTC).date().isoformat(),
                    "period": month,
                    "lines": lines,
                    "ref": f"payroll-{month}",
                    "posted_by": "FIN-1",
                }
            },
        )

        for emp_id in state["scratch"].get("emp_ids", []):
            await mcp.call(
                "comms",
                "notify_user",
                {
                    "user_id": emp_id,
                    "subject": f"Salary slip for {month} ready",
                    "body": "Your salary slip has been generated and is available for you to view.",
                },
            )

        state["scratch"].pop("awaiting_approval_for", None)
        state["result"] = TaskResult(
            task_id=state["task"].task_id,
            status=TaskStatus.DONE,
            summary=f"payroll for {month} disbursed and posted",
        )
        return state

    return node


def make_generate_salary_slips_node(mcp: MCPLike) -> Node:
    """Reissue/duplicate slips for an already-computed register (doc 06
    §2.1: "runs steps 1-4 for reissue/duplicates with slip_reissue
    approval"). Reads the register back via `mcp-finance.get_payroll_run`
    — added in Sprint 6 once this node (and the payroll UI) both turned
    out to need it and doc 08 §2's original tool list had no way to read
    back an already-computed month."""

    async def node(state: AgentState) -> AgentState:
        month = state["task"].payload["month"]
        employee_ids = state["task"].payload.get("employee_ids")

        run = await mcp.call("finance", "get_payroll_run", {"month": month})
        if run.get("register") is None:
            raise ValidationError(f"payroll for {month} has not been computed yet")

        lines = run["register"]["lines"]
        if employee_ids is not None:
            wanted = set(employee_ids)
            lines = [line for line in lines if line["emp_id"] in wanted]
            if not lines:
                raise ValidationError(f"none of {employee_ids} appear in the {month} register")

        approval = await mcp.call(
            "approvals",
            "request_approval",
            {
                "gate": "slip_reissue",
                "payload": {"month": month, "emp_ids": [line["emp_id"] for line in lines]},
            },
        )
        state["scratch"]["awaiting_approval_for"] = "generate_salary_slips"
        state["scratch"]["approval_id"] = approval["approval_id"]
        state["scratch"]["month"] = month
        state["scratch"]["reissue_lines"] = lines
        state["result"] = TaskResult(
            task_id=state["task"].task_id,
            status=TaskStatus.AWAITING_APPROVAL,
            summary=f"salary slip reissue for {month} awaiting finance_head approval",
        )
        return state

    return node


def make_check_generate_salary_slips_approval_node(mcp: MCPLike) -> Node:
    async def node(state: AgentState) -> AgentState:
        approval_id = state["scratch"].get("approval_id")
        if not approval_id:
            raise ValidationError(
                "check_generate_salary_slips_approval reached with no approval_id"
            )

        result = await mcp.call("approvals", "get_approval_status", {"approval_id": approval_id})
        status = result.get("status", "pending")
        if status == "pending":
            state["result"] = TaskResult(
                task_id=state["task"].task_id,
                status=TaskStatus.AWAITING_APPROVAL,
                summary="still awaiting slip_reissue approval",
            )
            return state
        if status != "approved":
            state["result"] = TaskResult(
                task_id=state["task"].task_id,
                status=TaskStatus.FAILED,
                summary=f"slip reissue approval was {status}",
            )
            return state
        if not result.get("token"):
            _fail_missing_token(state, "generate_salary_slips")
            return state

        month = state["scratch"]["month"]
        lines = state["scratch"]["reissue_lines"]
        employees = await payroll_flow.gather_employees_for_payroll(
            mcp, [line["emp_id"] for line in lines]
        )
        state["scratch"]["slip_uris"] = await _render_slips(mcp, month, employees, lines)
        state["scratch"].pop("awaiting_approval_for", None)
        state["result"] = TaskResult(
            task_id=state["task"].task_id,
            status=TaskStatus.DONE,
            summary=f"reissued {len(lines)} salary slip(s) for {month}",
        )
        return state

    return node


# --- record_expense / month_close (Bookkeeper) ---


def make_record_expense_node(llm: LLMLike, mcp: MCPLike) -> Node:
    async def node(state: AgentState) -> AgentState:
        payload = state["task"].payload
        doc_uri = payload["doc_uri"]

        extracted_text = await mcp.call("docs", "extract_text", {"file_uri": doc_uri})
        extraction = await bookkeeper.extract_expense(llm, extracted_text.get("text", ""))
        proposal = bookkeeper.propose_account(extraction)

        entry = {
            "date": (extraction.date or datetime.now(UTC).date().isoformat()),
            "period": (extraction.date or datetime.now(UTC).date().isoformat())[:7],
            "lines": bookkeeper.expense_journal_lines(proposal.account, extraction.total),
            "ref": f"expense-{extraction.vendor or 'unknown'}",
            "posted_by": "FIN-1",
        }

        try:
            posted = await mcp.call(
                "finance",
                "post_journal",
                {
                    "entry": entry,
                    "expense_context": {
                        "amount": extraction.total,
                        "confidence": proposal.confidence,
                    },
                },
            )
        except ApprovalRequiredError:
            approval = await mcp.call(
                "approvals",
                "request_approval",
                {"gate": "expense_posting", "payload": entry},
            )
            state["scratch"]["awaiting_approval_for"] = "record_expense"
            state["scratch"]["approval_id"] = approval["approval_id"]
            state["scratch"]["expense_entry"] = entry
            state["result"] = TaskResult(
                task_id=state["task"].task_id,
                status=TaskStatus.AWAITING_APPROVAL,
                summary=f"expense from {extraction.vendor or doc_uri} awaiting approval",
            )
            return state

        state["scratch"]["journal_entry_id"] = posted["id"]
        state["scratch"]["vendor"] = extraction.vendor
        return state

    return node


def make_check_record_expense_approval_node(mcp: MCPLike) -> Node:
    async def node(state: AgentState) -> AgentState:
        approval_id = state["scratch"].get("approval_id")
        if not approval_id:
            raise ValidationError("check_record_expense_approval reached with no approval_id")

        result = await mcp.call("approvals", "get_approval_status", {"approval_id": approval_id})
        status = result.get("status", "pending")
        if status == "pending":
            state["result"] = TaskResult(
                task_id=state["task"].task_id,
                status=TaskStatus.AWAITING_APPROVAL,
                summary="still awaiting expense_posting approval",
            )
            return state
        if status != "approved":
            state["result"] = TaskResult(
                task_id=state["task"].task_id,
                status=TaskStatus.FAILED,
                summary=f"expense approval was {status}",
            )
            return state

        token = result.get("token")
        if not token:
            _fail_missing_token(state, "record_expense")
            return state

        entry = state["scratch"]["expense_entry"]
        posted = await mcp.call(
            "finance", "post_journal", {"entry": entry, "approval_token": token}
        )
        state["scratch"]["journal_entry_id"] = posted["id"]
        state["scratch"].pop("awaiting_approval_for", None)
        return state

    return node


def make_month_close_node(mcp: MCPLike) -> Node:
    async def node(state: AgentState) -> AgentState:
        period = state["task"].payload["period"]
        try:
            closed = await mcp.call("finance", "close_period", {"period": period})
        except ApprovalRequiredError:
            approval = await mcp.call(
                "approvals",
                "request_approval",
                {"gate": "period_close", "payload": {"period": period}},
            )
            state["scratch"]["awaiting_approval_for"] = "month_close"
            state["scratch"]["approval_id"] = approval["approval_id"]
            state["scratch"]["period"] = period
            state["result"] = TaskResult(
                task_id=state["task"].task_id,
                status=TaskStatus.AWAITING_APPROVAL,
                summary=f"month-close for {period} awaiting finance_head approval",
            )
            return state

        state["scratch"]["period"] = closed["period"]
        return state

    return node


def make_check_month_close_approval_node(mcp: MCPLike) -> Node:
    async def node(state: AgentState) -> AgentState:
        approval_id = state["scratch"].get("approval_id")
        if not approval_id:
            raise ValidationError("check_month_close_approval reached with no approval_id")

        result = await mcp.call("approvals", "get_approval_status", {"approval_id": approval_id})
        status = result.get("status", "pending")
        if status == "pending":
            state["result"] = TaskResult(
                task_id=state["task"].task_id,
                status=TaskStatus.AWAITING_APPROVAL,
                summary="still awaiting period_close approval",
            )
            return state
        if status != "approved":
            state["result"] = TaskResult(
                task_id=state["task"].task_id,
                status=TaskStatus.FAILED,
                summary=f"month-close approval was {status}",
            )
            return state

        token = result.get("token")
        if not token:
            _fail_missing_token(state, "month_close")
            return state

        period = state["scratch"]["period"]
        await mcp.call("finance", "close_period", {"period": period, "approval_token": token})
        state["scratch"].pop("awaiting_approval_for", None)
        return state

    return node


# --- create_invoice (Biller) ---


def make_create_invoice_node(mcp: MCPLike) -> Node:
    async def node(state: AgentState) -> AgentState:
        payload = state["task"].payload
        lines = biller.build_invoice_lines(payload.get("items"))
        client = payload.get("client", "Unknown Client")
        gst_context = payload.get("gst_context", {"place_of_supply": "KA"})
        fy = payload.get("fy", payroll_flow.fy_for_month(datetime.now(UTC).strftime("%Y-%m")))

        draft = await mcp.call(
            "finance",
            "compute_invoice",
            {
                "lines": lines,
                "gst_context": gst_context,
                "fy": fy,
                "client": client,
                "contract_ref": payload.get("contract_ref"),
            },
        )

        approval = await mcp.call(
            "approvals",
            "request_approval",
            {"gate": "invoice_issue", "payload": {"invoice_id": draft["invoice_id"]}},
        )
        state["scratch"]["awaiting_approval_for"] = "create_invoice"
        state["scratch"]["approval_id"] = approval["approval_id"]
        state["scratch"]["invoice_id"] = draft["invoice_id"]
        state["result"] = TaskResult(
            task_id=state["task"].task_id,
            status=TaskStatus.AWAITING_APPROVAL,
            summary=f"invoice draft {draft['invoice_id']} awaiting finance_head approval",
        )
        return state

    return node


def make_check_create_invoice_approval_node(mcp: MCPLike) -> Node:
    async def node(state: AgentState) -> AgentState:
        approval_id = state["scratch"].get("approval_id")
        if not approval_id:
            raise ValidationError("check_create_invoice_approval reached with no approval_id")

        result = await mcp.call("approvals", "get_approval_status", {"approval_id": approval_id})
        status = result.get("status", "pending")
        if status == "pending":
            state["result"] = TaskResult(
                task_id=state["task"].task_id,
                status=TaskStatus.AWAITING_APPROVAL,
                summary="still awaiting invoice_issue approval",
            )
            return state
        if status != "approved":
            state["result"] = TaskResult(
                task_id=state["task"].task_id,
                status=TaskStatus.FAILED,
                summary=f"invoice approval was {status}",
            )
            return state

        token = result.get("token")
        if not token:
            _fail_missing_token(state, "create_invoice")
            return state

        invoice_id = state["scratch"]["invoice_id"]
        issued = await mcp.call(
            "finance", "issue_invoice", {"invoice_id": invoice_id, "approval_token": token}
        )
        pdf = await mcp.call(
            "docs",
            "render_pdf",
            {
                "template_id": "invoice_gst_v1",
                "data": {
                    "number": issued["number"],
                    "client": issued["client"],
                    "gst_treatment": issued["gst"]["treatment"],
                    "lines": issued["lines"],
                    "subtotal": issued["gst"]["subtotal"],
                    "cgst": issued["gst"]["cgst"],
                    "sgst": issued["gst"]["sgst"],
                    "igst": issued["gst"]["igst"],
                    "total": issued["gst"]["total"],
                },
            },
        )
        state["scratch"]["invoice_number"] = issued["number"]
        state["scratch"]["invoice_pdf_uri"] = pdf["uri"]
        state["scratch"].pop("awaiting_approval_for", None)
        return state

    return node


# --- compute_tax (TaxDesk) ---


def make_compute_tax_node(mcp: MCPLike) -> Node:
    async def node(state: AgentState) -> AgentState:
        payload = state["task"].payload
        kind = payload["kind"]
        fy = payload["fy"]

        if kind in ("tds_projection", "regime_comparison"):
            emp_id = payload.get("emp_id")
            if not emp_id:
                raise ValidationError(f"compute_tax kind={kind!r} requires 'emp_id'")
            gross_annual = await taxdesk.resolve_gross_annual(mcp, emp_id)
            if kind == "tds_projection":
                result = await mcp.call(
                    "finance",
                    "compute_tds_projection",
                    {"fy": fy, "regime": "new", "gross_annual": str(gross_annual)},
                )
            else:
                result = await mcp.call(
                    "finance", "compare_regimes", {"fy": fy, "gross_annual": str(gross_annual)}
                )
        elif kind == "gst_worksheet":
            result = await mcp.call(
                "finance", "gst_worksheet", {"period": payload.get("period", fy[:4] + "-04")}
            )
        elif kind == "advance_tax":
            result = await mcp.call(
                "finance",
                "advance_tax_estimate",
                {"fy": fy, "quarter": payload.get("quarter", "Q1")},
            )
        else:
            raise ValidationError(f"compute_tax: unknown kind {kind!r}")

        state["scratch"]["tax_result"] = result
        return state

    return node


# --- financial_requirement_report (FPnA) ---


def make_financial_requirement_report_node(mcp: MCPLike) -> Node:
    async def node(state: AgentState) -> AgentState:
        horizon_weeks = state["task"].payload.get("horizon_weeks", 13)
        today = datetime.now(UTC).date()
        period = today.strftime("%Y-%m")

        opening_balance, flows = await fpna.project_weekly_flows(mcp, period, horizon_weeks, today)
        model = await mcp.call(
            "finance",
            "cashflow_model",
            {
                "opening_balance": str(opening_balance),
                "weekly_flows": [
                    {
                        "week_start": week_start.isoformat(),
                        "inflow": str(inflow),
                        "outflow": str(outflow),
                        "assumptions": list(assumptions),
                    }
                    for week_start, inflow, outflow, assumptions in flows
                ],
            },
        )
        state["scratch"]["cashflow_rows"] = model["rows"]
        state["scratch"]["first_negative_week"] = model["first_negative_week"]
        return state

    return node


# --- shared respond ---


async def n_respond(state: AgentState) -> AgentState:
    if state.get("result") is not None:
        return state

    scratch = state["scratch"]
    summary = f"handled {state['task'].intent}"
    if scratch.get("invoice_number"):
        summary = f"invoice {scratch['invoice_number']} issued"
    elif scratch.get("journal_entry_id"):
        summary += f"; posted journal entry {scratch['journal_entry_id']}"
    elif scratch.get("period"):
        summary += f" for period {scratch['period']}"
    elif scratch.get("tax_result") is not None:
        summary += " (tax computation)"
    elif scratch.get("cashflow_rows") is not None:
        gap = scratch.get("first_negative_week")
        summary += f"; funding gap at {gap}" if gap else "; no funding gap in horizon"

    state["result"] = TaskResult(
        task_id=state["task"].task_id, status=TaskStatus.DONE, summary=summary
    )
    return state
