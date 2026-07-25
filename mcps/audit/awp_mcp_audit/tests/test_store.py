from datetime import datetime, timezone

import pytest

from awp_shared.audit_mw import AuditEvent

from awp_mcp_audit.store import EventStore
from awp_mcp_base.uow import UnitOfWork


def _event(**overrides: object) -> AuditEvent:
    defaults: dict[str, object] = dict(
        ts=datetime(2026, 7, 25, 10, 0, 0, tzinfo=timezone.utc),
        agent_id="FIN-1",
        server="finance",
        tool="post_journal",
        input_hash="a" * 64,
        output_hash="b" * 64,
        latency_ms=12.5,
        ok=True,
    )
    defaults.update(overrides)
    return AuditEvent(**defaults)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_append_assigns_seq_and_fills_record_hash(uow: UnitOfWork) -> None:
    async with uow() as session:
        store = EventStore(session)
        seq = await store.append(_event())
        rows = await store.query()
    assert seq >= 1
    assert rows[0]["record_hash"] != ""
    assert len(rows[0]["record_hash"]) == 64


@pytest.mark.asyncio
async def test_query_filters_by_day_and_agent(uow: UnitOfWork) -> None:
    async with uow() as session:
        store = EventStore(session)
        await store.append(_event(agent_id="FIN-1"))
        await store.append(_event(agent_id="HR-1"))
        await store.append(_event(agent_id="FIN-1", ts=datetime(2026, 7, 26, tzinfo=timezone.utc)))

    async with uow() as session:
        store = EventStore(session)
        fin_events = await store.query(agent_id="FIN-1")
        day1_events = await store.query(day="2026-07-25")

    assert len(fin_events) == 2
    assert len(day1_events) == 2


@pytest.mark.asyncio
async def test_compute_and_store_day_root_is_idempotent(uow: UnitOfWork) -> None:
    async with uow() as session:
        store = EventStore(session)
        await store.append(_event())
        first = await store.compute_and_store_day_root("2026-07-25")
        second = await store.compute_and_store_day_root("2026-07-25")

    assert first["root_hash"] == second["root_hash"]
    assert first["event_count"] == 1


@pytest.mark.asyncio
async def test_get_day_root_returns_none_when_uncomputed(uow: UnitOfWork) -> None:
    async with uow() as session:
        row = await EventStore(session).get_day_root("2026-01-01")
    assert row is None
