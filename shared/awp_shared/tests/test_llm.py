import json
from collections.abc import Callable

import httpx
import pytest
from pydantic import BaseModel

from awp_shared.errors import UpstreamError, ValidationError
from awp_shared.llm import LLM, SamplingProfile
from awp_shared.metrics import REGISTRY


def _chat_response(content: str | None = None, tool_calls: list[dict] | None = None) -> dict:
    message: dict = {"role": "assistant"}
    if content is not None:
        message["content"] = content
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    return {"choices": [{"message": message}]}


def _llm_with_transport(handler: Callable[[httpx.Request], httpx.Response]) -> LLM:
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
                        "function": {
                            "name": "get_employee",
                            "arguments": json.dumps({"emp_id": "E1"}),
                        },
                    }
                ]
            ),
        )

    llm = _llm_with_transport(handler)
    resp = await llm.chat(
        [{"role": "user", "content": "hi"}], tools=[{"type": "function", "function": {}}]
    )
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
        return httpx.Response(
            200, json=_chat_response(content=_Plan(goal="g", tasks=["t1"]).model_dump_json())
        )

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
        return httpx.Response(
            200, json=_chat_response(content=_Plan(goal="g", tasks=[]).model_dump_json())
        )

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


def _counter(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


@pytest.mark.asyncio
async def test_chat_records_metrics_on_success() -> None:
    # A model name unique to this test avoids colliding with any other
    # test file's counter values for a shared label combination — the
    # Prometheus registry is process-global, so before/after deltas on a
    # dedicated label are the only reliable way to assert on it.
    model = "test-model-metrics-ok"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_chat_response(content="hi"))

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    llm = LLM("http://model-gw:11434/v1", model, SamplingProfile(), client=client)
    before_ok = _counter("awp_llm_calls_total", model=model, status="ok")
    before_count = _counter("awp_llm_call_duration_seconds_count", model=model)

    await llm.chat([{"role": "user", "content": "hi"}])

    assert _counter("awp_llm_calls_total", model=model, status="ok") == before_ok + 1
    assert _counter("awp_llm_call_duration_seconds_count", model=model) == before_count + 1


@pytest.mark.asyncio
async def test_chat_records_metrics_on_transport_error() -> None:
    model = "test-model-metrics-error"

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    llm = LLM("http://model-gw:11434/v1", model, SamplingProfile(), client=client)
    before_error = _counter("awp_llm_calls_total", model=model, status="error")

    with pytest.raises(UpstreamError):
        await llm.chat([{"role": "user", "content": "hi"}])

    assert _counter("awp_llm_calls_total", model=model, status="error") == before_error + 1
