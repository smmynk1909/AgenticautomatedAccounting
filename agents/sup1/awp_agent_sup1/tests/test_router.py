from __future__ import annotations

from awp_agent_sup1 import router
from awp_agent_sup1.tests.conftest import FakeMCP


def test_resolve_owner_known_category() -> None:
    assert router.resolve_owner("payroll") == "FIN-1"


def test_resolve_owner_human_queue() -> None:
    assert router.resolve_owner("it_support") == "human:it_support"


def test_resolve_owner_unknown_falls_back() -> None:
    assert router.resolve_owner("not-a-real-category") == "human:support_lead"


async def test_fan_out_cross_functional_creates_and_links_children() -> None:
    counter = {"n": 0}

    def create_ticket(args: dict) -> dict:
        counter["n"] += 1
        return {"ticket_id": f"TKT-CHILD-{counter['n']}"}

    mcp = FakeMCP(handlers={("erp", "create_ticket"): create_ticket})
    child_ids = await router.fan_out_cross_functional(
        mcp, "TKT-PARENT", ["delivery", "device"], {"type": "agent", "id": "ORCH-0"}
    )

    assert child_ids == ["TKT-CHILD-1", "TKT-CHILD-2"]
    link_calls = [c for c in mcp.calls if c[1] == "link_tickets"]
    assert link_calls[0][2] == {"parent": "TKT-PARENT", "children": child_ids}
