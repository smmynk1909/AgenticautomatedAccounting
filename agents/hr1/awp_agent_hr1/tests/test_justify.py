from __future__ import annotations

import pytest
from awp_shared.candidate_profile import CandidateProfile
from awp_shared.llm import LLMResponse

from awp_agent_hr1.justify import write_justification
from awp_agent_hr1.tests.conftest import FakeLLM


@pytest.mark.asyncio
async def test_write_justification_returns_llm_content() -> None:
    llm = FakeLLM([LLMResponse(content="Line 1\nLine 2\nLine 3")])
    profile = CandidateProfile(skills_normalized=["Python"], total_exp_months=36)
    result = await write_justification(llm, {"must_have": ["Python"]}, profile, 0.85)
    assert result == "Line 1\nLine 2\nLine 3"
    assert "Python" in llm.calls[0]["messages"][1]["content"]
