from datetime import UTC, datetime

import pytest
from awp_mcp_base.uow import UnitOfWork
from awp_shared.auth import mint_service_jwt
from awp_shared.errors import PermissionDeniedError, ValidationError
from fakeredis.aioredis import FakeRedis

from awp_mcp_audit.server import make_audit_server


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _payload(**overrides: object) -> dict[str, object]:
    defaults: dict[str, object] = dict(
        agent_id="FIN-1",
        server="finance",
        tool="post_journal",
        input_hash="a" * 64,
        output_hash="b" * 64,
        latency_ms=5.0,
        ok=True,
    )
    defaults.update(overrides)
    return defaults


@pytest.mark.asyncio
async def test_log_event_tool_persists_the_payload_event(uow: UnitOfWork) -> None:
    server = make_audit_server(uow, FakeRedis(decode_responses=True))
    write_token = mint_service_jwt("FIN-1", ["audit.write"])

    result = await server.dispatch_raw("log_event", _payload(), _headers(write_token))
    assert "seq" in result

    read_token = mint_service_jwt("FIN-1", ["audit.write", "audit.read"])
    queried = await server.dispatch_raw(
        "query_events", {"tool": "post_journal"}, _headers(read_token)
    )
    # exactly the payload event — the pipeline's own audit-of-itself is logged
    # under tool="log_event", not "post_journal", so it doesn't show up here.
    assert len(queried["events"]) == 1
    assert queried["events"][0]["agent_id"] == "FIN-1"


@pytest.mark.asyncio
async def test_the_pipeline_audits_its_own_log_event_call(uow: UnitOfWork) -> None:
    """Every server (mcp-audit included) auto-instruments its own tool calls
    (doc 08 §9) — calling log_event once should also produce a self-audit row
    for the log_event call itself."""
    server = make_audit_server(uow, FakeRedis(decode_responses=True))
    token = mint_service_jwt("FIN-1", ["audit.write", "audit.read"])

    await server.dispatch_raw("log_event", _payload(), _headers(token))
    queried = await server.dispatch_raw("query_events", {"tool": "log_event"}, _headers(token))
    assert len(queried["events"]) == 1


@pytest.mark.asyncio
async def test_log_event_requires_audit_write_scope(uow: UnitOfWork) -> None:
    server = make_audit_server(uow, FakeRedis(decode_responses=True))
    token = mint_service_jwt("FIN-1", [])
    with pytest.raises(PermissionDeniedError):
        await server.dispatch_raw("log_event", _payload(), _headers(token))


@pytest.mark.asyncio
async def test_query_events_requires_audit_read_scope(uow: UnitOfWork) -> None:
    server = make_audit_server(uow, FakeRedis(decode_responses=True))
    token = mint_service_jwt("FIN-1", [])
    with pytest.raises(PermissionDeniedError):
        await server.dispatch_raw("query_events", {}, _headers(token))


@pytest.mark.asyncio
async def test_export_audit_requires_admin_scope(uow: UnitOfWork) -> None:
    server = make_audit_server(uow, FakeRedis(decode_responses=True))
    token = mint_service_jwt("FIN-1", [])
    with pytest.raises(PermissionDeniedError):
        await server.dispatch_raw(
            "export_audit", {"start_day": "2026-07-25", "end_day": "2026-07-25"}, _headers(token)
        )


@pytest.mark.asyncio
async def test_export_audit_requires_start_and_end_day(uow: UnitOfWork) -> None:
    server = make_audit_server(uow, FakeRedis(decode_responses=True))
    token = mint_service_jwt("FIN-1", ["audit.admin"])
    with pytest.raises(ValidationError):
        await server.dispatch_raw("export_audit", {}, _headers(token))


@pytest.mark.asyncio
async def test_export_audit_reports_verification_per_day(uow: UnitOfWork) -> None:
    server = make_audit_server(uow, FakeRedis(decode_responses=True))
    write_token = mint_service_jwt("FIN-1", ["audit.write"])
    admin_token = mint_service_jwt("FIN-1", ["audit.admin"])

    await server.dispatch_raw("log_event", _payload(), _headers(write_token))

    today = datetime.now(UTC).date().isoformat()
    result = await server.dispatch_raw(
        "export_audit", {"start_day": today, "end_day": today}, _headers(admin_token)
    )
    assert len(result["days"]) == 1
    assert result["days"][0]["day"] == today
    assert result["days"][0]["tampered"] is False


@pytest.mark.asyncio
async def test_compute_day_root_requires_admin_scope(uow: UnitOfWork) -> None:
    server = make_audit_server(uow, FakeRedis(decode_responses=True))
    token = mint_service_jwt("FIN-1", [])
    with pytest.raises(PermissionDeniedError):
        await server.dispatch_raw("compute_day_root", {"day": "2026-07-25"}, _headers(token))
