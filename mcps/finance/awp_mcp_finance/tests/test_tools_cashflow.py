import pytest
from awp_mcp_base.server import AwpMcpServer
from awp_shared.auth import mint_service_jwt
from awp_shared.errors import ValidationError


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _token() -> str:
    return mint_service_jwt("FIN-1", ["finance.read"])


async def test_cashflow_model_detects_funding_gap(finance_server: AwpMcpServer) -> None:
    result = await finance_server.dispatch_raw(
        "cashflow_model",
        {
            "opening_balance": "1000",
            "weekly_flows": [
                {"week_start": "2026-06-01", "inflow": "0", "outflow": "500"},
                {"week_start": "2026-06-08", "inflow": "0", "outflow": "600"},
            ],
        },
        _headers(_token()),
    )
    assert len(result["rows"]) == 2
    assert result["first_negative_week"] == "2026-06-08"


async def test_cashflow_model_requires_fields(finance_server: AwpMcpServer) -> None:
    with pytest.raises(ValidationError):
        await finance_server.dispatch_raw(
            "cashflow_model", {"opening_balance": "1000"}, _headers(_token())
        )
