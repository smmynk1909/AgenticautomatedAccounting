from __future__ import annotations

import json

import pytest
from awp_shared.errors import ValidationError
from awp_shared.llm import LLMResponse

from awp_agent_ops1.codeassist import CodeReview, code_corpus_name, has_repo_access, run_mode
from awp_agent_ops1.tests.conftest import FakeLLM, FakeMCP


def test_code_corpus_name_strips_slash_from_repo_slug() -> None:
    # Qdrant collection names are raw URL path segments — an embedded "/"
    # (every real Gitea repo_slug is "owner/name") 404s every call against
    # a real Qdrant server (live-verified; no unit test hits real Qdrant).
    assert code_corpus_name("awp-admin/awp-sample-svc") == "code_awp-admin_awp-sample-svc"


@pytest.mark.asyncio
async def test_has_repo_access_true_when_allocated() -> None:
    mcp = FakeMCP(handlers={("erp", "query_allocations"): {"allocations": [{"pct": 50}]}})
    assert await has_repo_access(mcp, "E1", "P1") is True


@pytest.mark.asyncio
async def test_has_repo_access_false_when_not_allocated() -> None:
    mcp = FakeMCP(handlers={("erp", "query_allocations"): {"allocations": []}})
    assert await has_repo_access(mcp, "E1", "P1") is False


@pytest.mark.asyncio
async def test_run_mode_chat_returns_stripped_text() -> None:
    llm = FakeLLM([LLMResponse(content="  the answer is 42  ")])
    result = await run_mode(llm, "chat", "context", "what is the answer?")
    assert result == "the answer is 42"


@pytest.mark.asyncio
async def test_run_mode_generate_uses_context_and_instruction() -> None:
    llm = FakeLLM([LLMResponse(content="def f(): ...")])
    await run_mode(llm, "generate", "def existing(): ...", "add a helper")
    sent = llm.calls[0]["messages"][-1]["content"]
    assert "def existing" in sent
    assert "add a helper" in sent


@pytest.mark.asyncio
async def test_run_mode_review_returns_code_review_model() -> None:
    review_json = json.dumps(
        {"bugs": ["off-by-one on line 3"], "security": [], "style": [], "tests_missing": []}
    )
    llm = FakeLLM([LLMResponse(content=review_json)])
    result = await run_mode(llm, "review", "diff --git a/x b/x\n", "review this")
    assert isinstance(result, CodeReview)
    assert result.bugs == ["off-by-one on line 3"]


@pytest.mark.asyncio
async def test_run_mode_rejects_unknown_mode() -> None:
    llm = FakeLLM([])
    with pytest.raises(ValidationError):
        await run_mode(llm, "delete_everything", "context", "instruction")
