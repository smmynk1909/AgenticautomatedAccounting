import uuid

import pytest
from awp_mcp_base.server import AwpMcpServer
from awp_shared.auth import mint_approval_token, mint_service_jwt
from awp_shared.errors import ApprovalRequiredError, NotFoundError, ValidationError


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _write_token() -> str:
    return mint_service_jwt(
        "FIN-1",
        [
            "finance.write",
            "finance.read",
            "finance.gated",
        ],
    )


def _approval(gate: str, payload: dict) -> str:
    return mint_approval_token(
        gate=gate, payload=payload, approvers=["dev-finance-head"], ttl_h=24, jti=str(uuid.uuid4())
    )


def _balanced_entry(period: str = "2026-06") -> dict:
    return {
        "date": "2026-06-15",
        "period": period,
        "lines": [
            {"account": "5001", "dr": "1000.00"},
            {"account": "1001", "cr": "1000.00"},
        ],
        "ref": "test-entry",
        "posted_by": "tester",
    }


async def test_post_journal_happy_path(finance_server: AwpMcpServer) -> None:
    result = await finance_server.dispatch_raw(
        "post_journal", {"entry": _balanced_entry()}, _headers(_write_token())
    )
    assert len(result["lines"]) == 2
    assert result["period"] == "2026-06"


async def test_post_journal_unbalanced_rejected(finance_server: AwpMcpServer) -> None:
    entry = _balanced_entry()
    entry["lines"][1]["cr"] = "999.00"
    with pytest.raises(ValidationError):
        await finance_server.dispatch_raw(
            "post_journal", {"entry": entry}, _headers(_write_token())
        )


async def test_post_journal_closed_period_rejected(finance_server: AwpMcpServer) -> None:
    entry = _balanced_entry(period="2099-01")
    with pytest.raises(ValidationError):
        await finance_server.dispatch_raw(
            "post_journal", {"entry": entry}, _headers(_write_token())
        )


async def test_post_journal_unknown_account_rejected(finance_server: AwpMcpServer) -> None:
    entry = _balanced_entry()
    entry["lines"][0]["account"] = "9999"
    with pytest.raises(ValidationError):
        await finance_server.dispatch_raw(
            "post_journal", {"entry": entry}, _headers(_write_token())
        )


async def test_post_journal_expense_above_threshold_requires_approval(
    finance_server: AwpMcpServer,
) -> None:
    entry = _balanced_entry()
    with pytest.raises(ApprovalRequiredError):
        await finance_server.dispatch_raw(
            "post_journal",
            {"entry": entry, "expense_context": {"amount": "30000", "confidence": "0.99"}},
            _headers(_write_token()),
        )


async def test_post_journal_expense_above_threshold_succeeds_with_token(
    finance_server: AwpMcpServer,
) -> None:
    entry = _balanced_entry()
    token = _approval("expense_posting", entry)
    result = await finance_server.dispatch_raw(
        "post_journal",
        {
            "entry": entry,
            "expense_context": {"amount": "30000", "confidence": "0.99"},
            "approval_token": token,
        },
        _headers(_write_token()),
    )
    assert len(result["lines"]) == 2


async def test_post_journal_expense_below_threshold_auto_posts(
    finance_server: AwpMcpServer,
) -> None:
    entry = _balanced_entry()
    result = await finance_server.dispatch_raw(
        "post_journal",
        {"entry": entry, "expense_context": {"amount": "500", "confidence": "0.99"}},
        _headers(_write_token()),
    )
    assert len(result["lines"]) == 2


async def test_post_journal_below_threshold_still_gated_under_hitl_max(
    finance_server: AwpMcpServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    # doc 12 §5 Sprint 12 "HITL-max settings" — with the flag on, even an
    # entry that would normally auto-post (small amount, high confidence,
    # same fixture as test_post_journal_expense_below_threshold_auto_posts
    # above) must still gate. Read fresh from os.environ on every call
    # (`_hitl_max()`), so setenv alone is enough — no reload needed.
    monkeypatch.setenv("AWP_HITL_MAX", "true")
    entry = _balanced_entry()
    with pytest.raises(ApprovalRequiredError):
        await finance_server.dispatch_raw(
            "post_journal",
            {"entry": entry, "expense_context": {"amount": "500", "confidence": "0.99"}},
            _headers(_write_token()),
        )


async def test_post_journal_hitl_max_off_leaves_thresholds_unchanged(
    finance_server: AwpMcpServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AWP_HITL_MAX", "false")
    entry = _balanced_entry()
    result = await finance_server.dispatch_raw(
        "post_journal",
        {"entry": entry, "expense_context": {"amount": "500", "confidence": "0.99"}},
        _headers(_write_token()),
    )
    assert len(result["lines"]) == 2


async def test_get_trial_balance_reflects_posted_entries(finance_server: AwpMcpServer) -> None:
    await finance_server.dispatch_raw(
        "post_journal", {"entry": _balanced_entry()}, _headers(_write_token())
    )
    result = await finance_server.dispatch_raw(
        "get_trial_balance", {"period": "2026-06"}, _headers(_write_token())
    )
    assert result["in_balance"] is True
    assert result["balances"]["5001"] == "1000.00"
    assert result["balances"]["1001"] == "-1000.00"


async def test_get_ledger_returns_entries_for_account(finance_server: AwpMcpServer) -> None:
    await finance_server.dispatch_raw(
        "post_journal", {"entry": _balanced_entry()}, _headers(_write_token())
    )
    result = await finance_server.dispatch_raw(
        "get_ledger", {"account": "5001"}, _headers(_write_token())
    )
    assert len(result["entries"]) == 1


async def test_get_pnl_computes_net_income(finance_server: AwpMcpServer) -> None:
    entry = {
        "date": "2026-06-15",
        "period": "2026-06",
        "lines": [
            {"account": "1002", "dr": "10000.00"},
            {"account": "4001", "cr": "10000.00"},
        ],
        "posted_by": "tester",
    }
    await finance_server.dispatch_raw("post_journal", {"entry": entry}, _headers(_write_token()))
    result = await finance_server.dispatch_raw(
        "get_pnl", {"period": "2026-06"}, _headers(_write_token())
    )
    assert result["income"] == "10000.00"
    assert result["net_income"] == "10000.00"


async def test_get_balance_sheet_balances(finance_server: AwpMcpServer) -> None:
    entry = {
        "date": "2026-06-15",
        "period": "2026-06",
        "lines": [
            {"account": "1001", "dr": "50000.00"},
            {"account": "3001", "cr": "50000.00"},
        ],
        "posted_by": "tester",
    }
    await finance_server.dispatch_raw("post_journal", {"entry": entry}, _headers(_write_token()))
    result = await finance_server.dispatch_raw(
        "get_balance_sheet", {"date": "2026-06-30"}, _headers(_write_token())
    )
    assert result["asset"] == "50000.00"
    assert result["equity"] == "50000.00"


async def test_close_period_requires_approval(finance_server: AwpMcpServer) -> None:
    with pytest.raises(ApprovalRequiredError):
        await finance_server.dispatch_raw(
            "close_period", {"period": "2026-06"}, _headers(_write_token())
        )


async def test_close_period_succeeds_with_token(finance_server: AwpMcpServer) -> None:
    token = _approval("period_close", {"period": "2026-06"})
    result = await finance_server.dispatch_raw(
        "close_period", {"period": "2026-06", "approval_token": token}, _headers(_write_token())
    )
    assert result["status"] == "closed"


async def test_close_unknown_period_404s(finance_server: AwpMcpServer) -> None:
    token = _approval("period_close", {"period": "2030-01"})
    with pytest.raises(NotFoundError):
        await finance_server.dispatch_raw(
            "close_period", {"period": "2030-01", "approval_token": token}, _headers(_write_token())
        )


async def test_reopen_period_requires_reason(finance_server: AwpMcpServer) -> None:
    with pytest.raises(ValidationError):
        await finance_server.dispatch_raw(
            "reopen_period", {"period": "2026-06"}, _headers(_write_token())
        )


async def test_reopen_period_succeeds_with_token(finance_server: AwpMcpServer) -> None:
    close_token = _approval("period_close", {"period": "2026-06"})
    await finance_server.dispatch_raw(
        "close_period",
        {"period": "2026-06", "approval_token": close_token},
        _headers(_write_token()),
    )
    reopen_token = _approval("period_reopen", {"period": "2026-06", "reason": "back-dated fix"})
    result = await finance_server.dispatch_raw(
        "reopen_period",
        {"period": "2026-06", "reason": "back-dated fix", "approval_token": reopen_token},
        _headers(_write_token()),
    )
    assert result["status"] == "open"
