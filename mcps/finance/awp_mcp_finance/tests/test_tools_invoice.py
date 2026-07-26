import uuid

import pytest
from awp_mcp_base.server import AwpMcpServer
from awp_shared.auth import mint_approval_token, mint_service_jwt
from awp_shared.errors import ApprovalRequiredError, ValidationError


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _token() -> str:
    return mint_service_jwt("FIN-1", ["finance.write", "finance.read", "finance.gated"])


def _approval(gate: str, payload: dict) -> str:
    return mint_approval_token(
        gate=gate, payload=payload, approvers=["dev-finance-head"], ttl_h=24, jti=str(uuid.uuid4())
    )


def _draft_payload() -> dict:
    return {
        "lines": [{"description": "Consulting", "quantity": "10", "unit_price": "5000"}],
        "gst_context": {"place_of_supply": "KA"},
        "fy": "2026-27",
        "client": "Acme Corp",
    }


async def test_compute_invoice_creates_draft(finance_server: AwpMcpServer) -> None:
    result = await finance_server.dispatch_raw(
        "compute_invoice", _draft_payload(), _headers(_token())
    )
    assert result["subtotal"] == "50000.00"
    assert result["gst_treatment"] == "intra_state"
    assert result["invoice_id"]


async def test_compute_invoice_requires_fields(finance_server: AwpMcpServer) -> None:
    with pytest.raises(ValidationError):
        await finance_server.dispatch_raw("compute_invoice", {}, _headers(_token()))


async def test_issue_invoice_requires_approval(finance_server: AwpMcpServer) -> None:
    draft = await finance_server.dispatch_raw(
        "compute_invoice", _draft_payload(), _headers(_token())
    )
    with pytest.raises(ApprovalRequiredError):
        await finance_server.dispatch_raw(
            "issue_invoice", {"invoice_id": draft["invoice_id"]}, _headers(_token())
        )


async def test_issue_invoice_assigns_gapless_numbers(finance_server: AwpMcpServer) -> None:
    numbers = []
    for _ in range(3):
        draft = await finance_server.dispatch_raw(
            "compute_invoice", _draft_payload(), _headers(_token())
        )
        token = _approval("invoice_issue", {"invoice_id": draft["invoice_id"]})
        issued = await finance_server.dispatch_raw(
            "issue_invoice",
            {"invoice_id": draft["invoice_id"], "approval_token": token, "period": "2026-06"},
            _headers(_token()),
        )
        numbers.append(issued["number"])

    assert numbers == [
        "INV/2026-27/000001",
        "INV/2026-27/000002",
        "INV/2026-27/000003",
    ]
    assert len(set(numbers)) == 3


async def test_issue_invoice_posts_to_ledger(finance_server: AwpMcpServer) -> None:
    draft = await finance_server.dispatch_raw(
        "compute_invoice", _draft_payload(), _headers(_token())
    )
    token = _approval("invoice_issue", {"invoice_id": draft["invoice_id"]})
    issued = await finance_server.dispatch_raw(
        "issue_invoice",
        {"invoice_id": draft["invoice_id"], "approval_token": token, "period": "2026-06"},
        _headers(_token()),
    )
    assert issued["journal_entry_id"]

    tb = await finance_server.dispatch_raw(
        "get_trial_balance", {"period": "2026-06"}, _headers(_token())
    )
    assert tb["balances"]["1002"] == "59000.00"


async def test_cannot_issue_already_issued_invoice(finance_server: AwpMcpServer) -> None:
    draft = await finance_server.dispatch_raw(
        "compute_invoice", _draft_payload(), _headers(_token())
    )
    token = _approval("invoice_issue", {"invoice_id": draft["invoice_id"]})
    await finance_server.dispatch_raw(
        "issue_invoice",
        {"invoice_id": draft["invoice_id"], "approval_token": token, "period": "2026-06"},
        _headers(_token()),
    )
    token2 = _approval("invoice_issue", {"invoice_id": draft["invoice_id"]})
    with pytest.raises(ValidationError):
        await finance_server.dispatch_raw(
            "issue_invoice",
            {"invoice_id": draft["invoice_id"], "approval_token": token2},
            _headers(_token()),
        )
