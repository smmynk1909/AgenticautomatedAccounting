from __future__ import annotations

import json

import pytest
from awp_shared.llm import LLMResponse

from awp_agent_hr1.negotiation import (
    CandidateAsk,
    MarketBenchmark,
    SalaryBand,
    build_negotiation_pack,
    compute_recommendation,
    draft_candidate_email,
)
from awp_agent_hr1.tests.conftest import FakeLLM, FakeMCP

_TALK_TRACK_JSON = json.dumps(
    {
        "pairs": [
            {"objection": "wants more base", "response": "we can move within band"},
            {"objection": "has a competing offer", "response": "highlight non-cash levers"},
        ]
    }
)


def test_compute_recommendation_is_deterministic_and_within_band() -> None:
    band = SalaryBand(grade="G3", min=60000, mid=80000, max=100000)
    rec = compute_recommendation(band)

    assert rec.open == band.mid
    assert band.mid < rec.target < band.max
    assert rec.walk_away == band.max

    rec2 = compute_recommendation(band)
    assert rec == rec2


@pytest.mark.asyncio
async def test_build_negotiation_pack_cites_market_or_marks_unknown() -> None:
    mcp = FakeMCP(
        handlers={
            ("erp", "get_role"): {"id": "R1", "grade": "G3", "title": "Backend Engineer"},
            ("erp", "query_policies"): {
                "policies": [{"grade": "G3", "min": 60000, "mid": 80000, "max": 100000}]
            },
            ("search", "search_kb"): {"results": []},  # no market_intel hit
        }
    )
    llm = FakeLLM([LLMResponse(content=_TALK_TRACK_JSON)])
    pack = await build_negotiation_pack(
        llm, mcp, "C1", "R1", {"current_ctc": 70000, "expected_ctc": 95000}
    )

    assert pack.market.known is False
    assert pack.band.mid == 80000
    assert len(pack.talk_track) == 2
    assert pack.candidate.expected_ctc == 95000


@pytest.mark.asyncio
async def test_build_negotiation_pack_missing_grade_raises() -> None:
    from awp_shared.errors import ValidationError

    mcp = FakeMCP(handlers={("erp", "get_role"): {"id": "R1"}})
    llm = FakeLLM([])
    with pytest.raises(ValidationError):
        await build_negotiation_pack(llm, mcp, "C1", "R1", None)


@pytest.mark.asyncio
async def test_draft_candidate_email_uses_open_and_target_only() -> None:
    band = SalaryBand(grade="G3", min=60000, mid=80000, max=100000)
    rec = compute_recommendation(band)
    from awp_agent_hr1.negotiation import NegotiationPack

    pack = NegotiationPack(
        candidate_id="C1",
        role_id="R1",
        band=band,
        market=MarketBenchmark(),
        candidate=CandidateAsk(),
        recommendation=rec,
        talk_track=[],
    )
    llm = FakeLLM([LLMResponse(content="We're delighted to offer you a competitive package.")])
    draft = await draft_candidate_email(llm, pack, "Asha Rao", None)

    assert draft
    sent_messages = llm.calls[0]["messages"]
    user_content = sent_messages[-1]["content"]
    assert str(rec.open) in user_content
    assert str(rec.walk_away) not in user_content
