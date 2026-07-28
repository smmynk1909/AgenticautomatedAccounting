from __future__ import annotations

import json

import pytest
from awp_shared.errors import ValidationError
from awp_shared.llm import LLMResponse

from awp_agent_hr1.sourcer import get_or_build_role_profile, search_internal_pool
from awp_agent_hr1.tests.conftest import FakeLLM, FakeMCP


@pytest.mark.asyncio
async def test_get_or_build_role_profile_returns_cached() -> None:
    mcp = FakeMCP(
        handlers={("erp", "get_role"): {"id": "R1", "role_profile": {"must_have": ["Python"]}}}
    )
    llm = FakeLLM([])
    profile = await get_or_build_role_profile(llm, mcp, "R1", jd_text=None)
    assert profile == {"must_have": ["Python"]}
    assert llm.calls == []  # never called the LLM — used the cache


@pytest.mark.asyncio
async def test_get_or_build_role_profile_parses_and_caches_when_missing() -> None:
    mcp = FakeMCP(
        handlers={
            ("erp", "get_role"): {"id": "R1", "role_profile": {}},
            ("erp", "upsert_role"): {"id": "R1"},
        }
    )
    llm = FakeLLM(
        [LLMResponse(content=json.dumps({"must_have": ["Django"], "min_exp_months": 24}))]
    )
    profile = await get_or_build_role_profile(llm, mcp, "R1", jd_text="Need a Django dev")
    assert profile["must_have"] == ["Django"]

    upsert_call = next(c for c in mcp.calls if c[:2] == ("erp", "upsert_role"))
    assert upsert_call[2]["record"]["role_profile"]["must_have"] == ["Django"]


@pytest.mark.asyncio
async def test_get_or_build_role_profile_raises_without_jd_or_cache() -> None:
    mcp = FakeMCP(handlers={("erp", "get_role"): {"id": "R1", "role_profile": {}}})
    llm = FakeLLM([])
    with pytest.raises(ValidationError):
        await get_or_build_role_profile(llm, mcp, "R1", jd_text=None)


@pytest.mark.asyncio
async def test_search_internal_pool_returns_candidates() -> None:
    mcp = FakeMCP(
        handlers={
            ("search", "search_candidates"): {
                "candidates": [{"candidate_id": "C1", "score": 0.9}]
            }
        }
    )
    result = await search_internal_pool(mcp, {"must_have": ["Python"]}, 10)
    assert result == [{"candidate_id": "C1", "score": 0.9}]
    assert mcp.calls[0] == (
        "search",
        "search_candidates",
        {"role_profile": {"must_have": ["Python"]}, "k": 10},
    )
