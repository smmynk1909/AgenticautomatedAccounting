import pytest
from awp_shared.auth import mint_user_jwt
from httpx import AsyncClient

from awp_gateway.tests.conftest import FakeMCP


def _headers(user_id: str = "dev-employee", roles: list[str] | None = None) -> dict[str, str]:
    token = mint_user_jwt(user_id, roles or ["employee"])
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_chat_dispatches_and_returns_task_id(client: AsyncClient, mcp: FakeMCP) -> None:
    r = await client.post("/api/chat/ORCH-0", json={"message": "please help"}, headers=_headers())
    assert r.status_code == 200
    assert "task_id" in r.json()
    dispatch_calls = [c for c in mcp.calls if c[1] == "dispatch_task"]
    assert len(dispatch_calls) == 1


@pytest.mark.asyncio
async def test_chat_requires_message(client: AsyncClient) -> None:
    r = await client.post("/api/chat/ORCH-0", json={}, headers=_headers())
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_chat_unknown_agent_400s(client: AsyncClient) -> None:
    r = await client.post("/api/chat/NOT-AN-AGENT", json={"message": "hi"}, headers=_headers())
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_chat_requires_auth(client: AsyncClient) -> None:
    r = await client.post("/api/chat/ORCH-0", json={"message": "hi"})
    assert r.status_code == 403  # missing bearer token -> PermissionDeniedError


@pytest.mark.asyncio
async def test_chat_rejects_agent_token(client: AsyncClient) -> None:
    from awp_shared.auth import mint_service_jwt

    token = mint_service_jwt("SUP-1", [])
    r = await client.post(
        "/api/chat/ORCH-0",
        json={"message": "hi"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403
