from __future__ import annotations

import pytest
from awp_shared.auth import mint_user_jwt
from httpx import AsyncClient

from awp_gateway.routers import codeassist as codeassist_router
from awp_gateway.tests.conftest import FakeMCP


def _headers(user_id: str = "dev-employee") -> dict[str, str]:
    token = mint_user_jwt(user_id, ["employee"])
    return {"Authorization": f"Bearer {token}"}


def _request(**overrides: object) -> dict[str, object]:
    base = {
        "messages": [{"role": "user", "content": "what does add() do?"}],
        "project_id": "P1",
        "emp_id": "E1",
    }
    return {**base, **overrides}


@pytest.mark.asyncio
async def test_chat_completions_returns_openai_shape_when_done(
    client: AsyncClient, mcp: FakeMCP
) -> None:
    mcp._handlers[("erp", "get_task_status")] = {
        "task": {"status": "done", "result": {"summary": "add() sums two numbers."}}
    }
    r = await client.post("/v1/chat/completions", json=_request(), headers=_headers())
    assert r.status_code == 200
    body = r.json()
    assert body["object"] == "chat.completion"
    assert body["choices"][0]["message"]["content"] == "add() sums two numbers."


@pytest.mark.asyncio
async def test_chat_completions_dispatches_code_assist_session(
    client: AsyncClient, mcp: FakeMCP
) -> None:
    mcp._handlers[("erp", "get_task_status")] = {
        "task": {"status": "done", "result": {"summary": "ok"}}
    }
    await client.post("/v1/chat/completions", json=_request(mode="explain"), headers=_headers())
    dispatch_call = next(c for c in mcp.calls if c[1] == "dispatch_task")
    envelope = dispatch_call[2]["envelope"]
    assert envelope["intent"] == "code_assist_session"
    assert envelope["payload"]["mode"] == "explain"
    assert envelope["payload"]["emp_id"] == "E1"


@pytest.mark.asyncio
async def test_chat_completions_raises_on_task_failure(
    client: AsyncClient, mcp: FakeMCP
) -> None:
    mcp._handlers[("erp", "get_task_status")] = {
        "task": {"status": "failed", "result": None}
    }
    r = await client.post("/v1/chat/completions", json=_request(), headers=_headers())
    assert r.status_code == 502


@pytest.mark.asyncio
async def test_chat_completions_times_out(
    client: AsyncClient, mcp: FakeMCP, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(codeassist_router, "POLL_TIMEOUT_S", 0.01)
    monkeypatch.setattr(codeassist_router, "POLL_INTERVAL_S", 0.01)
    mcp._handlers[("erp", "get_task_status")] = {"task": {"status": "pending", "result": None}}
    r = await client.post("/v1/chat/completions", json=_request(), headers=_headers())
    assert r.status_code == 502


@pytest.mark.asyncio
async def test_chat_completions_requires_messages(client: AsyncClient) -> None:
    r = await client.post(
        "/v1/chat/completions", json=_request(messages=[]), headers=_headers()
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_chat_completions_requires_project_id_and_emp_id(client: AsyncClient) -> None:
    r = await client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "hi"}]},
        headers=_headers(),
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_chat_completions_requires_auth(client: AsyncClient) -> None:
    r = await client.post("/v1/chat/completions", json=_request())
    assert r.status_code == 403
