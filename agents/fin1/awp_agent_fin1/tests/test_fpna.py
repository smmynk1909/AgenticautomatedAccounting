from __future__ import annotations

from datetime import date
from decimal import Decimal

from awp_agent_fin1.fpna import project_weekly_flows
from awp_agent_fin1.tests.conftest import FakeMCP


async def test_project_weekly_flows_derives_outflow_from_pnl() -> None:
    mcp = FakeMCP(
        handlers={
            ("finance", "get_pnl"): {"income": "0", "expense": "433000", "net_income": "-433000"},
            ("finance", "get_balance_sheet"): {"asset": "1000000", "liability": "0", "equity": "0"},
        }
    )
    opening, flows = await project_weekly_flows(mcp, "2026-06", 3, date(2026, 7, 1))
    assert opening == Decimal("1000000")
    assert len(flows) == 3
    # 433000 / 4.33 = 100000.00 per week
    assert flows[0][2] == Decimal("100000.00")
    assert flows[0][1] == Decimal("0")
    assert flows[0][0] == date(2026, 7, 1)
    assert flows[1][0] == date(2026, 7, 8)
