import json

import httpx
import pytest
from pydantic import BaseModel

from awp_shared.errors import UpstreamError, ValidationError
from awp_shared.llm import LLM, SamplingProfile


def _chat_response(content: str | None = None, tool_calls: list[dict] | None = None) -> dict:
    message: dict = {"role": "assistant"}
    if content is not None:
        message["content"] = content
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    return {"choices": [{"message": message}]}


def _llm_with_transport(handler) -> LLM:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    return LLM("http://model-gw:11434/v1", "qwen2.5:7b-instruct", SamplingProfile(), client=client)


@pytest.mark.asyncio
async def test_chat_returns_plain_content() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_chat_response(content="hello"))

    llm = _llm_with_transport(handler)
    resp = await llm.chat([{"role": "user", "content": "hi"}])
    assert resp.content == "hello"
    assert resp.tool_calls == []


@pytest.mark.asyncio
async def test_chat_parses_tool_calls() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_chat_response(
                tool_calls=[
                    {
                        "id": "call_1",
                        "function": {"name": "get_employee", "arguments": json.dumps({"emp_id": "E1"})},
                    }
                ]
            ),
        )

    llm = _llm_with_transport(handler)
    resp = await llm.chat([{"role": "user", "content": "hi"}], tools=[{"type": "function", "function": {}}])
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].name == "get_employee"
    assert resp.tool_calls[0].arguments == {"emp_id": "E1"}


@pytest.mark.asyncio
async def test_transport_error_raises_upstream_after_retries() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("connection refused")

    llm = _llm_with_transport(handler)
    with pytest.raises(UpstreamError):
        await llm.chat([{"role": "user", "content": "hi"}])
    assert calls == 3  # 1 initial + 2 retries


class _Plan(BaseModel):
    goal: str
    tasks: list[str]


@pytest.mark.asyncio
async def test_guided_json_valid_on_first_try_skips_repair() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_chat_response(content=_Plan(goal="g", tasks=["t1"]).model_dump_json()))

    llm = _llm_with_transport(handler)
    resp = await llm.chat([{"role": "user", "content": "plan"}], guided_json=_Plan)
    assert calls == 1
    parsed = _Plan.model_validate_json(resp.content or "")
    assert parsed.goal == "g"


@pytest.mark.asyncio
async def test_guided_json_repairs_once_then_succeeds() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(200, json=_chat_response(content="not json at all"))
        return httpx.Response(200, json=_chat_response(content=_Plan(goal="g", tasks=[]).model_dump_json()))

    llm = _llm_with_transport(handler)
    resp = await llm.chat([{"role": "user", "content": "plan"}], guided_json=_Plan)
    assert calls == 2
    assert _Plan.model_validate_json(resp.content or "").goal == "g"


@pytest.mark.asyncio
async def test_guided_json_fails_after_repair_round() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_chat_response(content="still not json"))

    llm = _llm_with_transport(handler)
    with pytest.raises(ValidationError):
        await llm.chat([{"role": "user", "content": "plan"}], guided_json=_Plan)
