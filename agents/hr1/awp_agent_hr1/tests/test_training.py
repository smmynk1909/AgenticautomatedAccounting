from __future__ import annotations

import pytest
from awp_shared.errors import ValidationError

from awp_agent_hr1.tests.conftest import FakeMCP
from awp_agent_hr1.training import build_gap_report, match_training_plan, summarize_plan


def _mcp(*, skills: list[str], search_results: dict | None = None) -> FakeMCP:
    return FakeMCP(
        handlers={
            ("erp", "get_employee"): {"emp_id": "E1", "role_id": "R1", "skills": skills},
            ("erp", "get_role"): {
                "id": "R1",
                "role_profile": {"must_have": ["Python", "SQL"], "nice_to_have": ["AWS"]},
            },
            ("search", "search_kb"): search_results or {"results": []},
        }
    )


@pytest.mark.asyncio
async def test_gap_report_only_lists_missing_skills() -> None:
    mcp = _mcp(skills=["Python"])
    gaps = await build_gap_report(mcp, "E1")

    skills = {g.skill for g in gaps}
    assert skills == {"SQL", "AWS"}
    assert all(g.current_level == "absent" for g in gaps)


@pytest.mark.asyncio
async def test_gap_report_empty_when_all_skills_present() -> None:
    mcp = _mcp(skills=["Python", "SQL", "AWS"])
    gaps = await build_gap_report(mcp, "E1")
    assert gaps == []


@pytest.mark.asyncio
async def test_gap_report_missing_role_id_raises() -> None:
    mcp = FakeMCP(handlers={("erp", "get_employee"): {"emp_id": "E1"}})
    with pytest.raises(ValidationError):
        await build_gap_report(mcp, "E1")


@pytest.mark.asyncio
async def test_match_training_plan_only_includes_catalog_hits() -> None:
    mcp = _mcp(
        skills=["Python"],
        search_results={"results": [{"text": "SQL fundamentals course", "citation": {}}]},
    )
    gaps = await build_gap_report(mcp, "E1")
    items = await match_training_plan(mcp, gaps, "2026-Q3")

    # every gap got a catalog hit in this fixture (same canned search_kb
    # response for every query) — plan has one item per gap.
    assert len(items) == len(gaps)
    assert all(i.quarter == "2026-Q3" for i in items)


@pytest.mark.asyncio
async def test_match_training_plan_drops_gaps_with_no_catalog_hit() -> None:
    mcp = _mcp(skills=["Python"], search_results={"results": []})
    gaps = await build_gap_report(mcp, "E1")
    items = await match_training_plan(mcp, gaps, "2026-Q3")
    assert items == []


def test_summarize_plan_totals() -> None:
    from awp_agent_hr1.training import TrainingItem

    items = [
        TrainingItem(skill="SQL", course="SQL 101", hours=8, cost=1000, quarter="2026-Q3"),
        TrainingItem(skill="AWS", course="AWS Basics", hours=16, cost=3000, quarter="2026-Q3"),
    ]
    summary = summarize_plan(items)
    assert summary["total_hours"] == 24
    assert summary["total_cost"] == 4000
