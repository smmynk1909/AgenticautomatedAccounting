from __future__ import annotations

from awp_agent_adm1 import dashboard
from awp_agent_adm1.tests.conftest import FakeMCP


async def test_push_asset_register_panel_uses_real_numbers() -> None:
    mcp = FakeMCP(
        handlers={
            ("erp", "asset_audit_report"): {
                "count": 42,
                "by_status": {"in_stock": 10, "issued": 30, "written_off": 2},
                "total_value": "1234567.89",
                "assets": [],
            },
        }
    )
    report = await dashboard.push_asset_register_panel(mcp)
    assert report["count"] == 42

    push_call = next(c for c in mcp.calls if c[1] == "push_dashboard_item")
    item = push_call[2]
    # doc 03 §4 rule 1 / §2.4: numbers must come verbatim from the tool
    # result — assert the exact figures appear, not just "some number."
    assert "42" in item["body"]
    assert "1234567.89" in item["body"]
    assert item["audience_roles"] == ["director", "ceo"]
    assert item["panel"] == "asset_register"
