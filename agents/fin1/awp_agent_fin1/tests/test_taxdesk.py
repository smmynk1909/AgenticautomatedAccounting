from __future__ import annotations

from decimal import Decimal

from awp_agent_fin1.taxdesk import resolve_gross_annual
from awp_agent_fin1.tests.conftest import FakeMCP


async def test_resolve_gross_annual_uses_band_mid() -> None:
    mcp = FakeMCP(
        handlers={
            ("erp", "get_employee"): {"emp_id": "EMP-1", "grade": "E3"},
            ("erp", "query_policies"): {"policies": [{"mid": "900000"}]},
        }
    )
    result = await resolve_gross_annual(mcp, "EMP-1")
    assert result == Decimal("900000")


async def test_resolve_gross_annual_defaults_when_no_band() -> None:
    mcp = FakeMCP(
        handlers={
            ("erp", "get_employee"): {"emp_id": "EMP-1", "grade": "E9"},
            ("erp", "query_policies"): {"policies": []},
        }
    )
    result = await resolve_gross_annual(mcp, "EMP-1")
    assert result == Decimal("600000")
