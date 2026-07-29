import pytest
from awp_mcp_base.server import AwpMcpServer
from awp_shared.auth import mint_service_jwt
from awp_shared.errors import ValidationError


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _token() -> str:
    return mint_service_jwt("FIN-1", ["finance.read"])


async def test_compute_tds_projection(finance_server: AwpMcpServer) -> None:
    result = await finance_server.dispatch_raw(
        "compute_tds_projection",
        {"fy": "2026-27", "regime": "new", "gross_annual": "960000"},
        _headers(_token()),
    )
    assert result["annual_tax"] == "48360.00"
    assert result["months_remaining"] == 12


async def test_compute_tds_projection_requires_fields(finance_server: AwpMcpServer) -> None:
    with pytest.raises(ValidationError):
        await finance_server.dispatch_raw(
            "compute_tds_projection", {"fy": "2026-27"}, _headers(_token())
        )


async def test_compare_regimes(finance_server: AwpMcpServer) -> None:
    result = await finance_server.dispatch_raw(
        "compare_regimes",
        {"fy": "2026-27", "gross_annual": "900000"},
        _headers(_token()),
    )
    assert result["recommended"] in ("old", "new")
    assert "old_regime_tax" in result and "new_regime_tax" in result


async def test_gst_worksheet_no_activity_is_zero(finance_server: AwpMcpServer) -> None:
    result = await finance_server.dispatch_raw(
        "gst_worksheet", {"period": "2026-06"}, _headers(_token())
    )
    assert result["output_liability"] == "0"
    assert result["net_payable"] == "0"


async def test_advance_tax_estimate_requires_valid_quarter(finance_server: AwpMcpServer) -> None:
    with pytest.raises(ValidationError):
        await finance_server.dispatch_raw(
            "advance_tax_estimate", {"fy": "2026-27", "quarter": "Q9"}, _headers(_token())
        )


async def test_advance_tax_estimate_with_no_activity_is_zero(
    finance_server: AwpMcpServer,
) -> None:
    result = await finance_server.dispatch_raw(
        "advance_tax_estimate", {"fy": "2026-27", "quarter": "Q1"}, _headers(_token())
    )
    assert result["projected_annual_tax"] == "0.00"
    assert result["this_installment"] == "0.00"
