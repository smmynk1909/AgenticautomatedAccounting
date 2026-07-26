import uuid

import pytest
from awp_mcp_base.server import AwpMcpServer
from awp_shared.auth import mint_approval_token, mint_service_jwt
from awp_shared.errors import ApprovalRequiredError, ConflictError


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _token() -> str:
    return mint_service_jwt("FIN-1", ["finance.write", "finance.read", "finance.gated"])


def _approval(gate: str, payload: dict) -> str:
    return mint_approval_token(
        gate=gate, payload=payload, approvers=["dev-finance-head"], ttl_h=24, jti=str(uuid.uuid4())
    )


def _employees() -> list[dict]:
    return [
        {
            "emp_id": "EMP-1",
            "grade": "E3",
            "basic": "50000",
            "hra": "20000",
            "special": "10000",
            "state": "KA",
        }
    ]


def _attendance() -> list[dict]:
    return [{"emp_id": "EMP-1", "days_in_month": 30, "lop_days": "0"}]


async def test_freeze_payroll_inputs_returns_snapshot_id(finance_server: AwpMcpServer) -> None:
    result = await finance_server.dispatch_raw(
        "freeze_payroll_inputs",
        {"month": "2026-06", "employees": _employees(), "attendance": _attendance()},
        _headers(_token()),
    )
    assert result["month"] == "2026-06"
    assert result["snapshot_id"]


async def test_freeze_payroll_inputs_conflict_on_double_freeze(
    finance_server: AwpMcpServer,
) -> None:
    payload = {"month": "2026-06", "employees": _employees(), "attendance": _attendance()}
    await finance_server.dispatch_raw("freeze_payroll_inputs", payload, _headers(_token()))
    with pytest.raises(ConflictError):
        await finance_server.dispatch_raw("freeze_payroll_inputs", payload, _headers(_token()))


async def test_compute_payroll_produces_register(finance_server: AwpMcpServer) -> None:
    frozen = await finance_server.dispatch_raw(
        "freeze_payroll_inputs",
        {"month": "2026-06", "employees": _employees(), "attendance": _attendance()},
        _headers(_token()),
    )
    result = await finance_server.dispatch_raw(
        "compute_payroll",
        {"snapshot_id": frozen["snapshot_id"], "fy": "2026-27"},
        _headers(_token()),
    )
    assert result["register_id"] == frozen["snapshot_id"]
    assert len(result["register"]["lines"]) == 1
    assert result["register"]["lines"][0]["emp_id"] == "EMP-1"
    # Same employee/inputs as fincore/fincore/tests/test_payroll.py's golden
    # case, but for month="2026-06" (June, FY 2026-27's 3rd month) instead
    # of April — _months_elapsed("2026-27", "2026-06") = 2, so TDS spreads
    # over 10 remaining months, not 12: monthly_tds = round2(48360/10) =
    # 4836.00 (not fincore's own test's 4030.00), net = 80000 - 1800 - 200
    # - 4836 = 73164.00.
    assert result["register"]["lines"][0]["net"] == "73164.00"


async def test_compute_payroll_accumulates_tds_across_months(
    finance_server: AwpMcpServer,
) -> None:
    """`PayrollRunRepo.tds_deducted_so_far_by_emp` must find May's already-
    withheld TDS when computing June, so June's monthly figure spreads the
    *remaining* liability over the *remaining* months rather than
    recomputing from scratch every run (doc 06 §2.1 step 2)."""
    may = await finance_server.dispatch_raw(
        "freeze_payroll_inputs",
        {"month": "2026-05", "employees": _employees(), "attendance": _attendance()},
        _headers(_token()),
    )
    may_result = await finance_server.dispatch_raw(
        "compute_payroll", {"snapshot_id": may["snapshot_id"], "fy": "2026-27"}, _headers(_token())
    )
    may_tds = may_result["register"]["lines"][0]["deductions"]["tds"]
    assert may_tds == "4396.36"  # round2(48360.00 / 11 remaining months)

    june = await finance_server.dispatch_raw(
        "freeze_payroll_inputs",
        {"month": "2026-06", "employees": _employees(), "attendance": _attendance()},
        _headers(_token()),
    )
    june_result = await finance_server.dispatch_raw(
        "compute_payroll",
        {"snapshot_id": june["snapshot_id"], "fy": "2026-27"},
        _headers(_token()),
    )
    june_tds = june_result["register"]["lines"][0]["deductions"]["tds"]
    # (48360.00 - 4396.36) / 10 remaining months = 4396.364... -> 4396.36
    assert june_tds == "4396.36"


async def test_generate_disbursement_file_requires_approval(finance_server: AwpMcpServer) -> None:
    frozen = await finance_server.dispatch_raw(
        "freeze_payroll_inputs",
        {"month": "2026-06", "employees": _employees(), "attendance": _attendance()},
        _headers(_token()),
    )
    await finance_server.dispatch_raw(
        "compute_payroll",
        {"snapshot_id": frozen["snapshot_id"], "fy": "2026-27"},
        _headers(_token()),
    )
    with pytest.raises(ApprovalRequiredError):
        await finance_server.dispatch_raw(
            "generate_disbursement_file",
            {"register_id": frozen["snapshot_id"]},
            _headers(_token()),
        )


async def test_generate_disbursement_file_succeeds_with_token(
    finance_server: AwpMcpServer,
) -> None:
    frozen = await finance_server.dispatch_raw(
        "freeze_payroll_inputs",
        {"month": "2026-06", "employees": _employees(), "attendance": _attendance()},
        _headers(_token()),
    )
    computed = await finance_server.dispatch_raw(
        "compute_payroll",
        {"snapshot_id": frozen["snapshot_id"], "fy": "2026-27"},
        _headers(_token()),
    )
    totals = computed["register"]["totals"]
    token = _approval(
        "payroll_run", {"register_id": frozen["snapshot_id"], "totals": totals}
    )
    result = await finance_server.dispatch_raw(
        "generate_disbursement_file",
        {"register_id": frozen["snapshot_id"], "approval_token": token},
        _headers(_token()),
    )
    assert result["filename"] == "disbursement_2026-06.csv"
    assert result["content_base64"]
