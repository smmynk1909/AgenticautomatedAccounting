import httpx
import pytest
from awp_shared.audit_mw import AuditEvent
from awp_shared.auth import mint_service_jwt
from awp_shared.errors import NotFoundError
from fakeredis.aioredis import FakeRedis
from fastapi import FastAPI

from awp_mcp_base.asgi import build_asgi_app
from awp_mcp_base.ctx import Ctx
from awp_mcp_base.server import AwpMcpServer


class _NullSink:
    async def log_event(self, event: AuditEvent) -> None:
        pass


def _server() -> AwpMcpServer:
    server = AwpMcpServer("audit", audit_sink=_NullSink(), redis=FakeRedis(decode_responses=True))

    @server.tool()
    async def log_event(payload: dict, ctx: Ctx) -> dict:
        return {"logged": True, "by": ctx.principal.sub}

    @server.tool()
    async def broken(payload: dict, ctx: Ctx) -> dict:
        raise NotFoundError("nope")

    return server


async def _client(app: FastAPI) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


@pytest.mark.asyncio
async def test_healthz_lists_registered_tools() -> None:
    app = build_asgi_app(_server())
    async with await _client(app) as client:
        r = await client.get("/healthz")
    assert r.status_code == 200
    assert set(r.json()["tools"]) == {"log_event", "broken"}


@pytest.mark.asyncio
async def test_tool_call_success_round_trip() -> None:
    app = build_asgi_app(_server())
    # "audit.log_event" requires the audit.write scope per config/scopes.yaml.
    token = mint_service_jwt("FIN-1", ["audit.write"])
    async with await _client(app) as client:
        r = await client.post(
            "/tools/log_event",
            json={"tool": "post_journal"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 200
    assert r.json() == {"logged": True, "by": "FIN-1"}


@pytest.mark.asyncio
async def test_unknown_tool_returns_structured_404() -> None:
    app = build_asgi_app(_server())
    token = mint_service_jwt("FIN-1", ["audit.write"])
    async with await _client(app) as client:
        r = await client.post(
            "/tools/does_not_exist", json={}, headers={"Authorization": f"Bearer {token}"}
        )
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_missing_auth_header_returns_structured_400() -> None:
    app = build_asgi_app(_server())
    async with await _client(app) as client:
        r = await client.post("/tools/log_event", json={})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "VALIDATION"


@pytest.mark.asyncio
async def test_tool_raises_not_found_error_maps_to_404() -> None:
    app = build_asgi_app(_server())
    token = mint_service_jwt("FIN-1", [])  # "broken" has no scopes.yaml entry, so [] is sufficient
    async with await _client(app) as client:
        r = await client.post(
            "/tools/broken", json={}, headers={"Authorization": f"Bearer {token}"}
        )
    assert r.status_code == 404
    assert r.json()["error"]["message"] == "nope"
