from pathlib import Path
from typing import Any

import pytest

from awp_shared.audit_mw import (
    AuditEvent,
    AuditMiddleware,
    DiskSpool,
    RemoteAuditSink,
    SpoolingAuditSink,
    hash_payload,
)


def _event(tool: str = "log_event") -> AuditEvent:
    return AuditEvent(
        agent_id="FIN-1",
        server="finance",
        tool=tool,
        input_hash="a",
        output_hash="b",
        latency_ms=1.0,
        ok=True,
    )


def test_hash_payload_is_order_independent() -> None:
    assert hash_payload({"a": 1, "b": 2}) == hash_payload({"b": 2, "a": 1})


def test_disk_spool_write_and_drain_round_trip(tmp_path: Path) -> None:
    spool = DiskSpool(tmp_path)
    spool.write(_event("t1"))
    spool.write(_event("t2"))
    assert spool.pending_count() == 2

    drained = spool.drain()
    assert [e.tool for e in drained] == ["t1", "t2"]
    assert spool.pending_count() == 0


class _FailingSink:
    async def log_event(self, event: AuditEvent) -> None:
        raise ConnectionError("mcp-audit unreachable")


class _RecordingSink:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    async def log_event(self, event: AuditEvent) -> None:
        self.events.append(event)


@pytest.mark.asyncio
async def test_spooling_sink_falls_back_to_disk_on_primary_failure(tmp_path: Path) -> None:
    spool = DiskSpool(tmp_path)
    sink = SpoolingAuditSink(_FailingSink(), spool)
    await sink.log_event(_event())
    assert spool.pending_count() == 1


@pytest.mark.asyncio
async def test_spooling_sink_replay_flushes_to_recovered_primary(tmp_path: Path) -> None:
    spool = DiskSpool(tmp_path)
    failing_sink = SpoolingAuditSink(_FailingSink(), spool)
    await failing_sink.log_event(_event("t1"))
    assert spool.pending_count() == 1

    recording = _RecordingSink()
    recovered_sink = SpoolingAuditSink(recording, spool)
    sent = await recovered_sink.replay()

    assert sent == 1
    assert spool.pending_count() == 0
    assert [e.tool for e in recording.events] == ["t1"]


@pytest.mark.asyncio
async def test_audit_middleware_emits_event_on_success(tmp_path: Path) -> None:
    recording = _RecordingSink()
    mw = AuditMiddleware(recording, agent_id="FIN-1", server_name="finance")

    async def call_fn() -> dict[str, int]:
        return {"ok": 1}

    result = await mw.wrap("compute_payroll", {"month": "2026-07"}, call_fn)

    assert result == {"ok": 1}
    assert len(recording.events) == 1
    assert recording.events[0].ok is True
    assert recording.events[0].tool == "compute_payroll"


@pytest.mark.asyncio
async def test_audit_middleware_emits_event_on_failure_and_reraises() -> None:
    recording = _RecordingSink()
    mw = AuditMiddleware(recording, agent_id="FIN-1", server_name="finance")

    async def call_fn() -> dict[str, int]:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await mw.wrap("post_journal", {"x": 1}, call_fn)

    assert len(recording.events) == 1
    assert recording.events[0].ok is False


class _FakeMcpClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []

    async def call(self, server: str, tool: str, args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append((server, tool, args))
        return {"seq": 1}


@pytest.mark.asyncio
async def test_remote_audit_sink_calls_mcp_audit_log_event() -> None:
    fake_mcp = _FakeMcpClient()
    sink = RemoteAuditSink(fake_mcp)
    await sink.log_event(_event("post_journal"))

    assert len(fake_mcp.calls) == 1
    server, tool, args = fake_mcp.calls[0]
    assert server == "audit"
    assert tool == "log_event"
    assert args["tool"] == "post_journal"
