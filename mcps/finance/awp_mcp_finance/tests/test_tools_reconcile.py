import uuid

import pytest
from awp_mcp_base.server import AwpMcpServer
from awp_shared.auth import mint_approval_token, mint_service_jwt
from awp_shared.errors import ApprovalRequiredError, NotFoundError, ValidationError


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _token() -> str:
    return mint_service_jwt("FIN-1", ["finance.write", "finance.gated"])


def _approval(gate: str, payload: dict) -> str:
    return mint_approval_token(
        gate=gate, payload=payload, approvers=["dev-finance-head"], ttl_h=24, jti=str(uuid.uuid4())
    )


async def test_reconcile_bank_requires_fields(finance_server: AwpMcpServer) -> None:
    with pytest.raises(ValidationError):
        await finance_server.dispatch_raw("reconcile_bank", {}, _headers(_token()))


async def test_reconcile_bank_no_ledger_candidates_all_unmatched(
    finance_server: AwpMcpServer,
) -> None:
    result = await finance_server.dispatch_raw(
        "reconcile_bank",
        {
            "stmt_id": "STMT-1",
            "bank_txns": [{"id": "B1", "date": "2026-06-05", "amount": "1000.00", "ref": "X"}],
        },
        _headers(_token()),
    )
    assert result["auto_matched"] == []
    assert result["unmatched"] == ["B1"]


async def test_reconcile_bank_auto_matches_against_posted_entry(
    finance_server: AwpMcpServer,
) -> None:
    entry = {
        "date": "2026-06-05",
        "period": "2026-06",
        "lines": [
            {"account": "1001", "dr": "5000.00", "ref": "INV-9"},
            {"account": "1002", "cr": "5000.00"},
        ],
        "ref": "INV-9",
        "posted_by": "tester",
    }
    await finance_server.dispatch_raw("post_journal", {"entry": entry}, _headers(_token()))

    result = await finance_server.dispatch_raw(
        "reconcile_bank",
        {
            "stmt_id": "STMT-2",
            "bank_txns": [{"id": "B1", "date": "2026-06-05", "amount": "5000.00", "ref": "INV-9"}],
        },
        _headers(_token()),
    )
    assert len(result["auto_matched"]) == 1
    assert result["auto_matched"][0]["bank_txn_id"] == "B1"


async def test_confirm_matches_requires_approval(finance_server: AwpMcpServer) -> None:
    result = await finance_server.dispatch_raw(
        "reconcile_bank",
        {
            "stmt_id": "STMT-3",
            "bank_txns": [{"id": "B1", "date": "2026-06-05", "amount": "1000.00"}],
        },
        _headers(_token()),
    )
    bank_txn_id = result["unmatched"][0]
    with pytest.raises(ApprovalRequiredError):
        await finance_server.dispatch_raw(
            "confirm_matches",
            {"matches": [{"bank_txn_id": bank_txn_id, "entry_id": "does-not-matter"}]},
            _headers(_token()),
        )


async def test_confirm_matches_unknown_txn_404s(finance_server: AwpMcpServer) -> None:
    matches = [{"bank_txn_id": "not-a-real-id", "entry_id": "also-not-real"}]
    token = _approval("recon_confirm", {"matches": matches})
    with pytest.raises(NotFoundError):
        await finance_server.dispatch_raw(
            "confirm_matches", {"matches": matches, "approval_token": token}, _headers(_token())
        )
