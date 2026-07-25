"""Event store — append + query over `audit_events`/`audit_day_roots`."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from awp_shared.audit_mw import AuditEvent

from awp_mcp_audit.chain import event_day, merkle_root, record_hash, record_hash_from_row
from awp_mcp_audit.tables import audit_day_roots, audit_events


class EventStore:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def append(self, event: AuditEvent) -> int:
        day = event_day(event)
        stmt = (
            insert(audit_events)
            .values(
                ts=event.ts,
                day=day,
                agent_id=event.agent_id,
                server=event.server,
                tool=event.tool,
                input_hash=event.input_hash,
                output_hash=event.output_hash,
                refs=event.refs,
                latency_ms=event.latency_ms,
                ok=event.ok,
                error_code=event.error_code,
                record_hash="",  # seq isn't known until insert; filled in below
            )
            .returning(audit_events.c.seq)
        )
        seq: int = (await self.session.execute(stmt)).scalar_one()
        rhash = record_hash(event, seq)
        await self.session.execute(
            audit_events.update().where(audit_events.c.seq == seq).values(record_hash=rhash)
        )
        return seq

    async def query(
        self,
        *,
        day: str | None = None,
        agent_id: str | None = None,
        tool: str | None = None,
        server: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        stmt = select(audit_events).order_by(audit_events.c.seq)
        if day:
            stmt = stmt.where(audit_events.c.day == day)
        if agent_id:
            stmt = stmt.where(audit_events.c.agent_id == agent_id)
        if tool:
            stmt = stmt.where(audit_events.c.tool == tool)
        if server:
            stmt = stmt.where(audit_events.c.server == server)
        stmt = stmt.limit(limit)
        rows = (await self.session.execute(stmt)).mappings().all()
        return [dict(r) for r in rows]

    async def events_for_day(self, day: str) -> list[dict[str, Any]]:
        return await self.query(day=day, limit=1_000_000)

    async def compute_and_store_day_root(self, day: str) -> dict[str, Any]:
        events = await self.events_for_day(day)
        # recomputed from current row values, not the stored `record_hash`
        # column — see chain.record_hash_from_row's docstring for why.
        root = merkle_root([record_hash_from_row(e) for e in events])
        now = datetime.now(timezone.utc)

        existing = (
            await self.session.execute(select(audit_day_roots).where(audit_day_roots.c.day == day))
        ).first()
        if existing is not None:
            await self.session.execute(
                audit_day_roots.update()
                .where(audit_day_roots.c.day == day)
                .values(root_hash=root, event_count=len(events), computed_at=now)
            )
        else:
            await self.session.execute(
                insert(audit_day_roots).values(
                    day=day, root_hash=root, event_count=len(events), computed_at=now
                )
            )
        return {"day": day, "root_hash": root, "event_count": len(events), "computed_at": now}

    async def get_day_root(self, day: str) -> dict[str, Any] | None:
        row = (
            await self.session.execute(select(audit_day_roots).where(audit_day_roots.c.day == day))
        ).mappings().first()
        return dict(row) if row else None
