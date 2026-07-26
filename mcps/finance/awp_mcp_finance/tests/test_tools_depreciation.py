import pytest
from awp_mcp_base.server import AwpMcpServer
from awp_shared.auth import mint_service_jwt
from awp_shared.errors import ValidationError


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _token() -> str:
    return mint_service_jwt("FIN-1", ["finance.write", "finance.read"])


async def test_run_depreciation_posts_journal_entry(finance_server: AwpMcpServer) -> None:
    result = await finance_server.dispatch_raw(
        "run_depreciation",
        {
            "period": "2026-06",
            "assets": [
                {
                    "asset_id": "AST-1",
                    "cost": "100000",
                    "method": "wdv",
                    "rate": "0.15",
                    "opening_wdv": "100000",
                }
            ],
        },
        _headers(_token()),
    )
    assert result["total_depreciation"] == "15000.00"
    assert result["journal_entry_id"] is not None

    tb = await finance_server.dispatch_raw(
        "get_trial_balance", {"period": "2026-06"}, _headers(_token())
    )
    assert tb["balances"]["5008"] == "15000.00"
    assert tb["balances"]["1005"] == "-15000.00"


async def test_run_depreciation_closed_period_rejected(finance_server: AwpMcpServer) -> None:
    with pytest.raises(ValidationError):
        await finance_server.dispatch_raw(
            "run_depreciation",
            {
                "period": "2099-01",
                "assets": [
                    {
                        "asset_id": "AST-1",
                        "cost": "1000",
                        "method": "wdv",
                        "rate": "0.1",
                        "opening_wdv": "1000",
                    }
                ],
            },
            _headers(_token()),
        )


async def test_run_depreciation_requires_fields(finance_server: AwpMcpServer) -> None:
    with pytest.raises(ValidationError):
        await finance_server.dispatch_raw("run_depreciation", {}, _headers(_token()))
