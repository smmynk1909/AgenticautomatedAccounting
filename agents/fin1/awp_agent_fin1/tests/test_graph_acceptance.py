"""doc 06 §7 acceptance-adjacent graph-level tests (doc 11 §10's testing
pyramid, same convention as agents/adm1's test_graph_acceptance.py).
Payroll parity (test 1: shadow vs manual to the rupee) and extraction F1
(test 4) need real/labeled data this build doesn't have — covered instead
by asserting the flow's own numbers are exactly the fincore-computed ones
(never altered en route) and by `scripts/tests/test_shadow_diff.py` for
the comparator itself. Test 5 (post_journal without approval -> rejected)
is exercised directly here for both payroll and expense postings.
"""

from __future__ import annotations

import json

import pytest
from awp_agent_base.state import new_state
from awp_shared.errors import ApprovalRequiredError, ValidationError
from awp_shared.llm import LLMResponse
from awp_shared.schemas import AgentId, TaskEnvelope, TaskStatus

from awp_agent_fin1.graph import build_graph
from awp_agent_fin1.tests.conftest import FakeLLM, FakeMCP


def _task(intent: str, payload: dict) -> TaskEnvelope:
    return TaskEnvelope(
        from_agent=AgentId.ORCH0, to_agent=AgentId.FIN1, intent=intent, payload=payload
    )


# --- run_payroll ---


def _payroll_mcp() -> FakeMCP:
    return FakeMCP(
        handlers={
            ("erp", "query_employees"): {
                "employees": [
                    {"emp_id": "EMP-1", "grade": "E3", "name": "Asha Rao", "dept_id": "ENG"}
                ]
            },
            ("erp", "query_policies"): {"policies": [{"mid": "1200000"}]},
            ("finance", "freeze_payroll_inputs"): {"snapshot_id": "SNAP-1", "month": "2026-06"},
            ("finance", "compute_payroll"): {
                "register_id": "SNAP-1",
                "register": {
                    "lines": [
                        {
                            "emp_id": "EMP-1",
                            "earnings": {"basic": "50000.00"},
                            "deductions": {
                                "tds": "3000.00",
                                "pf": "1800.00",
                                "esi": "0",
                                "pt": "200.00",
                            },
                            "gross": "100000.00",
                            "net": "95000.00",
                        }
                    ],
                    "totals": {
                        "gross": "100000.00",
                        "lop": "0",
                        "net": "95000.00",
                        "pf": "1800.00",
                        "esi": "0",
                        "pt": "200.00",
                        "tds": "3000.00",
                    },
                },
            },
            ("docs", "render_pdf"): {"uri": "minio://bucket/salary_slip_v1.pdf"},
            ("approvals", "request_approval"): {"approval_id": "APR-1", "status": "pending"},
        }
    )


async def test_run_payroll_requests_approval() -> None:
    mcp = _payroll_mcp()
    graph = build_graph(FakeLLM([]), mcp)
    task = _task("run_payroll", {"month": "2026-06"})
    final = await graph.ainvoke(new_state(task))

    assert final["result"].status == TaskStatus.AWAITING_APPROVAL
    assert final["scratch"]["awaiting_approval_for"] == "run_payroll"
    request_call = next(c for c in mcp.calls if c[1] == "request_approval")
    assert request_call[2]["gate"] == "payroll_run"
    assert request_call[2]["payload"]["totals"]["net"] == "95000.00"
    # slips rendered before approval is requested
    assert any(c[1] == "render_pdf" for c in mcp.calls)
    assert not any(c[1] == "post_journal" for c in mcp.calls)


async def test_run_payroll_resumes_and_posts_after_approval() -> None:
    mcp = FakeMCP(
        handlers={
            ("approvals", "get_approval_status"): {"status": "approved", "token": "signed.jwt"},
            ("finance", "generate_disbursement_file"): {"filename": "disbursement_2026-06.csv"},
            ("finance", "post_journal"): {"id": "JE-1"},
            ("comms", "notify_user"): {"ok": True},
        }
    )
    graph = build_graph(FakeLLM([]), mcp)
    task = _task("run_payroll", {"month": "2026-06"})
    state = new_state(task)
    state["scratch"] = {
        "awaiting_approval_for": "run_payroll",
        "approval_id": "APR-1",
        "register_id": "SNAP-1",
        "month": "2026-06",
        "totals": {
            "gross": "100000.00",
            "lop": "0",
            "net": "95000.00",
            "pf": "1800.00",
            "esi": "0",
            "pt": "200.00",
            "tds": "3000.00",
        },
        "emp_ids": ["EMP-1"],
    }
    final = await graph.ainvoke(state)

    assert final["result"].status == TaskStatus.DONE
    assert "awaiting_approval_for" not in final["scratch"]
    disbursement_call = next(c for c in mcp.calls if c[1] == "generate_disbursement_file")
    assert disbursement_call[2]["approval_token"] == "signed.jwt"
    post_call = next(c for c in mcp.calls if c[1] == "post_journal")
    dr_total = sum(float(line.get("dr", 0)) for line in post_call[2]["entry"]["lines"])
    cr_total = sum(float(line.get("cr", 0)) for line in post_call[2]["entry"]["lines"])
    assert dr_total == cr_total  # balanced posting (doc 06 §7 test 2)
    assert any(c[1] == "notify_user" for c in mcp.calls)


async def test_run_payroll_no_employees_raises() -> None:
    mcp = FakeMCP(handlers={("erp", "query_employees"): {"employees": []}})
    graph = build_graph(FakeLLM([]), mcp)
    task = _task("run_payroll", {"month": "2026-06"})
    with pytest.raises(ValidationError):
        await graph.ainvoke(new_state(task))


# --- generate_salary_slips ---


async def test_generate_salary_slips_requests_approval() -> None:
    mcp = FakeMCP(
        handlers={
            ("finance", "get_payroll_run"): {
                "status": "computed",
                "register": {
                    "lines": [
                        {
                            "emp_id": "EMP-1",
                            "earnings": {"basic": "50000.00"},
                            "deductions": {"tds": "3000.00"},
                            "gross": "70000.00",
                            "net": "64000.00",
                        }
                    ]
                },
            },
            ("approvals", "request_approval"): {"approval_id": "APR-5", "status": "pending"},
        }
    )
    graph = build_graph(FakeLLM([]), mcp)
    task = _task("generate_salary_slips", {"month": "2026-06"})
    final = await graph.ainvoke(new_state(task))
    assert final["result"].status == TaskStatus.AWAITING_APPROVAL
    request_call = next(c for c in mcp.calls if c[1] == "request_approval")
    assert request_call[2]["gate"] == "slip_reissue"


async def test_generate_salary_slips_uncomputed_month_raises() -> None:
    mcp = FakeMCP(handlers={("finance", "get_payroll_run"): {"status": "frozen", "register": None}})
    graph = build_graph(FakeLLM([]), mcp)
    task = _task("generate_salary_slips", {"month": "2026-06"})
    with pytest.raises(ValidationError, match="not been computed"):
        await graph.ainvoke(new_state(task))


async def test_generate_salary_slips_resumes_and_renders() -> None:
    mcp = FakeMCP(
        handlers={
            ("approvals", "get_approval_status"): {"status": "approved", "token": "signed.jwt"},
            ("erp", "query_employees"): {
                "employees": [{"emp_id": "EMP-1", "name": "Asha Rao", "dept_id": "ENG"}]
            },
            ("docs", "render_pdf"): {"uri": "minio://bucket/salary_slip_v1.pdf"},
        }
    )
    graph = build_graph(FakeLLM([]), mcp)
    task = _task("generate_salary_slips", {"month": "2026-06"})
    state = new_state(task)
    state["scratch"] = {
        "awaiting_approval_for": "generate_salary_slips",
        "approval_id": "APR-5",
        "month": "2026-06",
        "reissue_lines": [
            {
                "emp_id": "EMP-1",
                "earnings": {"basic": "50000.00"},
                "deductions": {"tds": "3000.00"},
                "gross": "70000.00",
                "net": "64000.00",
            }
        ],
    }
    final = await graph.ainvoke(state)
    assert final["result"].status == TaskStatus.DONE
    assert final["scratch"]["slip_uris"] == ["minio://bucket/salary_slip_v1.pdf"]
    assert "awaiting_approval_for" not in final["scratch"]


# --- record_expense ---


async def test_record_expense_auto_posts_below_threshold() -> None:
    llm = FakeLLM(
        [
            LLMResponse(
                content=json.dumps({"vendor": "Cloud Co", "total": "500", "date": "2026-06-10"})
            )
        ]
    )
    mcp = FakeMCP(
        handlers={
            ("docs", "extract_text"): {"text": "Cloud Co invoice, total 500"},
            ("finance", "post_journal"): {"id": "JE-EXP-1"},
        }
    )
    graph = build_graph(llm, mcp)
    task = _task("record_expense", {"doc_uri": "minio://bucket/receipt.pdf"})
    final = await graph.ainvoke(new_state(task))

    assert final["result"].status == TaskStatus.DONE
    assert final["scratch"]["journal_entry_id"] == "JE-EXP-1"
    post_call = next(c for c in mcp.calls if c[1] == "post_journal")
    assert "approval_token" not in post_call[2]


async def test_record_expense_above_threshold_awaits_approval() -> None:
    def post_journal(args: dict) -> dict:
        raise ApprovalRequiredError("amount exceeds threshold")

    llm = FakeLLM(
        [
            LLMResponse(
                content=json.dumps({"vendor": "Big Vendor", "total": "50000", "date": "2026-06-10"})
            )
        ]
    )
    mcp = FakeMCP(
        handlers={
            ("docs", "extract_text"): {"text": "Big Vendor invoice, total 50000"},
            ("finance", "post_journal"): post_journal,
            ("approvals", "request_approval"): {"approval_id": "APR-2", "status": "pending"},
        }
    )
    graph = build_graph(llm, mcp)
    task = _task("record_expense", {"doc_uri": "minio://bucket/big_receipt.pdf"})
    final = await graph.ainvoke(new_state(task))

    assert final["result"].status == TaskStatus.AWAITING_APPROVAL
    request_call = next(c for c in mcp.calls if c[1] == "request_approval")
    assert request_call[2]["gate"] == "expense_posting"


async def test_record_expense_resumes_after_approval() -> None:
    mcp = FakeMCP(
        handlers={
            ("approvals", "get_approval_status"): {"status": "approved", "token": "signed.jwt"},
            ("finance", "post_journal"): {"id": "JE-EXP-2"},
        }
    )
    graph = build_graph(FakeLLM([]), mcp)
    task = _task("record_expense", {"doc_uri": "minio://bucket/receipt.pdf"})
    state = new_state(task)
    state["scratch"] = {
        "awaiting_approval_for": "record_expense",
        "approval_id": "APR-2",
        "expense_entry": {
            "date": "2026-06-10",
            "period": "2026-06",
            "lines": [{"account": "5009", "dr": "50000"}, {"account": "2001", "cr": "50000"}],
            "ref": "expense-Big Vendor",
            "posted_by": "FIN-1",
        },
    }
    final = await graph.ainvoke(state)
    assert final["scratch"]["journal_entry_id"] == "JE-EXP-2"
    assert "awaiting_approval_for" not in final["scratch"]


# --- month_close ---


async def test_month_close_awaits_approval() -> None:
    def close_period(args: dict) -> dict:
        raise ApprovalRequiredError("needs approval")

    mcp = FakeMCP(
        handlers={
            ("finance", "close_period"): close_period,
            ("approvals", "request_approval"): {"approval_id": "APR-3", "status": "pending"},
        }
    )
    graph = build_graph(FakeLLM([]), mcp)
    task = _task("month_close", {"period": "2026-06"})
    final = await graph.ainvoke(new_state(task))
    assert final["result"].status == TaskStatus.AWAITING_APPROVAL


async def test_month_close_resumes_after_approval() -> None:
    mcp = FakeMCP(
        handlers={
            ("approvals", "get_approval_status"): {"status": "approved", "token": "signed.jwt"},
            ("finance", "close_period"): {"period": "2026-06", "status": "closed"},
        }
    )
    graph = build_graph(FakeLLM([]), mcp)
    task = _task("month_close", {"period": "2026-06"})
    state = new_state(task)
    state["scratch"] = {
        "awaiting_approval_for": "month_close",
        "approval_id": "APR-3",
        "period": "2026-06",
    }
    final = await graph.ainvoke(state)
    assert final["result"].status == TaskStatus.DONE
    close_call = next(c for c in mcp.calls if c[1] == "close_period")
    assert close_call[2]["approval_token"] == "signed.jwt"


# --- create_invoice ---


async def test_create_invoice_requests_approval() -> None:
    mcp = FakeMCP(
        handlers={
            ("finance", "compute_invoice"): {
                "invoice_id": "INV-1",
                "subtotal": "50000.00",
                "total": "59000.00",
            },
            ("approvals", "request_approval"): {"approval_id": "APR-4", "status": "pending"},
        }
    )
    graph = build_graph(FakeLLM([]), mcp)
    task = _task(
        "create_invoice",
        {
            "contract_ref": "CTR-1",
            "items": [{"description": "Consulting", "quantity": 10, "unit_price": 5000}],
            "client": "Acme Corp",
        },
    )
    final = await graph.ainvoke(new_state(task))
    assert final["result"].status == TaskStatus.AWAITING_APPROVAL
    request_call = next(c for c in mcp.calls if c[1] == "request_approval")
    assert request_call[2]["gate"] == "invoice_issue"


async def test_create_invoice_resumes_issues_and_renders() -> None:
    mcp = FakeMCP(
        handlers={
            ("approvals", "get_approval_status"): {"status": "approved", "token": "signed.jwt"},
            ("finance", "issue_invoice"): {
                "number": "INV/2026-27/000001",
                "client": "Acme Corp",
                "gst": {
                    "subtotal": "50000.00",
                    "cgst": "4500.00",
                    "sgst": "4500.00",
                    "igst": "0",
                    "total": "59000.00",
                    "treatment": "intra_state",
                },
                "lines": [{"description": "Consulting", "quantity": "10", "unit_price": "5000"}],
            },
            ("docs", "render_pdf"): {"uri": "minio://bucket/invoice.pdf"},
        }
    )
    graph = build_graph(FakeLLM([]), mcp)
    task = _task(
        "create_invoice",
        {"contract_ref": "CTR-1", "items": [{"description": "x", "quantity": 1, "unit_price": 1}]},
    )
    state = new_state(task)
    state["scratch"] = {
        "awaiting_approval_for": "create_invoice",
        "approval_id": "APR-4",
        "invoice_id": "INV-1",
    }
    final = await graph.ainvoke(state)
    assert final["scratch"]["invoice_number"] == "INV/2026-27/000001"
    assert final["scratch"]["invoice_pdf_uri"] == "minio://bucket/invoice.pdf"


# --- compute_tax ---


async def test_compute_tax_tds_projection() -> None:
    mcp = FakeMCP(
        handlers={
            ("erp", "get_employee"): {"emp_id": "EMP-1", "grade": "E3"},
            ("erp", "query_policies"): {"policies": [{"mid": "1200000"}]},
            ("finance", "compute_tds_projection"): {"annual_tax": "48360.00"},
        }
    )
    graph = build_graph(FakeLLM([]), mcp)
    task = _task("compute_tax", {"emp_id": "EMP-1", "fy": "2026-27", "kind": "tds_projection"})
    final = await graph.ainvoke(new_state(task))
    assert final["scratch"]["tax_result"]["annual_tax"] == "48360.00"


async def test_compute_tax_gst_worksheet() -> None:
    mcp = FakeMCP(handlers={("finance", "gst_worksheet"): {"net_payable": "1000.00"}})
    graph = build_graph(FakeLLM([]), mcp)
    task = _task("compute_tax", {"fy": "2026-27", "kind": "gst_worksheet", "period": "2026-06"})
    final = await graph.ainvoke(new_state(task))
    assert final["scratch"]["tax_result"]["net_payable"] == "1000.00"


async def test_compute_tax_requires_emp_id_for_projection() -> None:
    graph = build_graph(FakeLLM([]), FakeMCP())
    task = _task("compute_tax", {"fy": "2026-27", "kind": "tds_projection"})
    with pytest.raises(ValidationError):
        await graph.ainvoke(new_state(task))


# --- financial_requirement_report ---


async def test_financial_requirement_report() -> None:
    mcp = FakeMCP(
        handlers={
            ("finance", "get_pnl"): {"expense": "433000"},
            ("finance", "get_balance_sheet"): {"asset": "1000000"},
            ("finance", "cashflow_model"): {
                "rows": [{"week_start": "2026-07-01", "running_balance": "900000.00"}],
                "first_negative_week": None,
            },
        }
    )
    graph = build_graph(FakeLLM([]), mcp)
    task = _task("financial_requirement_report", {"horizon_weeks": 13})
    final = await graph.ainvoke(new_state(task))
    assert final["result"].status == TaskStatus.DONE
    assert final["scratch"]["first_negative_week"] is None


# --- routing ---


async def test_unknown_intent_raises() -> None:
    graph = build_graph(FakeLLM([]), FakeMCP())
    task = _task("not_a_fin1_intent", {})
    with pytest.raises(ValidationError):
        await graph.ainvoke(new_state(task))
