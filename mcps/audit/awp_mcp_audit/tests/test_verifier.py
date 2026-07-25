from datetime import UTC, datetime

import pytest
from awp_mcp_base.uow import UnitOfWork
from awp_shared.audit_mw import AuditEvent
from sqlalchemy import delete, update

from awp_mcp_audit.store import EventStore
from awp_mcp_audit.tables import audit_events
from awp_mcp_audit.verifier import verify_day


def _event(**overrides: object) -> AuditEvent:
    defaults: dict[str, object] = dict(
        ts=datetime(2026, 7, 25, 10, 0, 0, tzinfo=UTC),
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
async def test_verify_day_ok_when_untampered(uow: UnitOfWork) -> None:
    async with uow() as session:
        store = EventStore(session)
        await store.append(_event())
        await store.compute_and_store_day_root("2026-07-25")

    async with uow() as session:
        result = await verify_day(EventStore(session), "2026-07-25")

    assert result.tampered is False
    assert result.stored_root == result.recomputed_root


@pytest.mark.asyncio
async def test_verify_day_detects_a_single_column_edit(uow: UnitOfWork) -> None:
    """This is the case a naive "trust the stored record_hash column" design
    would miss: only `ok` is edited, the (unused-for-verification) record_hash
    column is left alone. Verification must still catch it."""
    async with uow() as session:
        store = EventStore(session)
        await store.append(_event(ok=True))
        await store.compute_and_store_day_root("2026-07-25")

    async with uow() as session:
        await session.execute(update(audit_events).where(audit_events.c.seq == 1).values(ok=False))

    async with uow() as session:
        result = await verify_day(EventStore(session), "2026-07-25")

    assert result.tampered is True
    assert result.stored_root != result.recomputed_root


@pytest.mark.asyncio
async def test_verify_day_detects_row_deletion(uow: UnitOfWork) -> None:
    async with uow() as session:
        store = EventStore(session)
        await store.append(_event(tool="t1"))
        await store.append(_event(tool="t2"))
        await store.compute_and_store_day_root("2026-07-25")

    async with uow() as session:
        await session.execute(delete(audit_events).where(audit_events.c.seq == 2))

    async with uow() as session:
        result = await verify_day(EventStore(session), "2026-07-25")

    assert result.tampered is True
    assert result.event_count == 1


@pytest.mark.asyncio
async def test_verify_day_with_no_stored_root_is_not_flagged_tampered(uow: UnitOfWork) -> None:
    async with uow() as session:
        await EventStore(session).append(_event())

    async with uow() as session:
        result = await verify_day(EventStore(session), "2026-07-25")

    assert result.stored_root is None
    assert result.tampered is False  # nothing to compare against yet, not a failure
    assert result.event_count == 1
