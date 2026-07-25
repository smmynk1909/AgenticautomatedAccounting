"""mcp-audit's tool surface — doc 08 §9.

`log_event` is called by every other server's `AuditMiddleware`; `query_events`
serves auditor/human read access; `export_audit` and `compute_day_root` are
admin-scoped (`compute_day_root` is meant to run from a daily cron once the
scheduler exists — Sprint 3 — but is exposed as a tool now so it's callable
and testable ahead of that).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from awp_mcp_base.ctx import Ctx
from awp_mcp_base.server import AwpMcpServer, make_server
from awp_mcp_base.uow import UnitOfWork
from awp_shared.audit_mw import AuditEvent
from awp_shared.errors import ValidationError
from redis.asyncio import Redis

from awp_mcp_audit.spool import build_self_spooling_sink
from awp_mcp_audit.store import EventStore
from awp_mcp_audit.verifier import verify_day


def _day_range(start: str, end: str) -> list[str]:
    d0 = date.fromisoformat(start)
    d1 = date.fromisoformat(end)
    if d1 < d0:
        raise ValidationError("end_day must be >= start_day")
    n = (d1 - d0).days
    return [(d0 + timedelta(days=i)).isoformat() for i in range(n + 1)]


def make_audit_server(uow: UnitOfWork, redis: Redis) -> AwpMcpServer:
    sink = build_self_spooling_sink(uow)
    server = make_server("audit", audit_sink=sink, redis=redis)

    @server.tool()
    async def log_event(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        event = AuditEvent.model_validate(payload)
        async with uow() as session:
            seq = await EventStore(session).append(event)
        return {"seq": seq}

    @server.tool()
    async def query_events(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        async with uow() as session:
            events = await EventStore(session).query(
                day=payload.get("day"),
                agent_id=payload.get("agent_id"),
                tool=payload.get("tool"),
                server=payload.get("server"),
                limit=payload.get("limit", 100),
            )
        return {"events": events}

    @server.tool()
    async def compute_day_root(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        day = payload.get("day")
        if not day:
            raise ValidationError("compute_day_root requires 'day' (YYYY-MM-DD)")
        async with uow() as session:
            result = await EventStore(session).compute_and_store_day_root(day)
        return result

    @server.tool()
    async def export_audit(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        start, end = payload.get("start_day"), payload.get("end_day")
        if not start or not end:
            raise ValidationError("export_audit requires start_day and end_day (YYYY-MM-DD)")
        async with uow() as session:
            store = EventStore(session)
            report = [
                (await verify_day(store, day)).model_dump(mode="json")
                for day in _day_range(start, end)
            ]
        return {"days": report}

    return server
