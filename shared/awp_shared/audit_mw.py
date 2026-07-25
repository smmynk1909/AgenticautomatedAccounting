"""Audit middleware library — doc 11 §1.7, doc 08 §9.

Every MCP server auto-instruments its tool calls through `AuditMiddleware`,
which logs to an `AuditSink` (normally an MCP call to `mcp-audit.log_event`)
and falls back to an on-disk spool if the sink is unreachable — the doc's
guarantee is "no lost events on audit downtime; replayed on recovery."

`mcps/_base/make_server` (Sprint 1) wires this into FastMCP's actual
middleware hook; this module stays framework-agnostic so it's testable
without a running FastMCP app.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def hash_payload(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class AuditEvent(BaseModel):
    ts: datetime = Field(default_factory=_utcnow)
    agent_id: str
    server: str
    tool: str
    input_hash: str
    output_hash: str
    refs: dict[str, Any] = Field(default_factory=dict)
    latency_ms: float
    ok: bool
    error_code: str | None = None


class AuditSink(Protocol):
    async def log_event(self, event: AuditEvent) -> None: ...


class DiskSpool:
    """Append-only JSONL fallback store — doc 09 §8 step 1 spool.py detail."""

    def __init__(self, directory: Path) -> None:
        self._dir = directory
        self._dir.mkdir(parents=True, exist_ok=True)
        self._file = self._dir / "audit_spool.jsonl"

    def write(self, event: AuditEvent) -> None:
        with self._file.open("a", encoding="utf-8") as f:
            f.write(event.model_dump_json() + "\n")

    def drain(self) -> list[AuditEvent]:
        if not self._file.exists():
            return []
        with self._file.open("r", encoding="utf-8") as f:
            lines = [line for line in f.read().splitlines() if line.strip()]
        self._file.write_text("", encoding="utf-8")
        return [AuditEvent.model_validate_json(line) for line in lines]

    def pending_count(self) -> int:
        if not self._file.exists():
            return 0
        return sum(1 for line in self._file.read_text(encoding="utf-8").splitlines() if line.strip())


class SpoolingAuditSink:
    """Wraps a primary sink; spools to disk on failure, replays on demand."""

    def __init__(self, primary: AuditSink, spool: DiskSpool) -> None:
        self._primary = primary
        self._spool = spool

    async def log_event(self, event: AuditEvent) -> None:
        try:
            await self._primary.log_event(event)
        except Exception as exc:  # noqa: BLE001 - audit must never crash the caller
            logger.warning("audit.spooled", tool=event.tool, error=str(exc))
            self._spool.write(event)

    async def replay(self) -> int:
        """Call on startup / periodically to flush spooled events. Stops at the
        first failure (preserves order) and re-spools the remainder."""
        events = self._spool.drain()
        sent = 0
        for i, event in enumerate(events):
            try:
                await self._primary.log_event(event)
                sent += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("audit.replay_failed", error=str(exc), remaining=len(events) - i)
                for remaining in events[i:]:
                    self._spool.write(remaining)
                break
        return sent


class RemoteAuditSink:
    """Sends events to mcp-audit over the network — the sink every server
    *other than* mcp-audit itself uses. (mcp-audit audits its own tool calls
    via `mcps/audit/awp_mcp_audit/spool.py`'s `DirectStoreSink` instead,
    writing straight to its own DB with no self-network-hop.)

    Constructed with an already-configured `awp_shared.mcpc.MCP` client so
    this module doesn't have to import it unconditionally (kept as a
    `TYPE_CHECKING`-only import to avoid a hard dependency on `mcpc`'s httpx
    requirement for callers — like fincore, eventually — that never send
    audit events themselves).
    """

    def __init__(self, mcp: Any) -> None:
        self._mcp = mcp

    async def log_event(self, event: AuditEvent) -> None:
        await self._mcp.call("audit", "log_event", event.model_dump(mode="json"))


class AuditMiddleware:
    """Wraps a tool call: hash inputs/outputs, time it, emit one AuditEvent."""

    def __init__(self, sink: AuditSink, *, agent_id: str, server_name: str) -> None:
        self._sink = sink
        self._agent_id = agent_id
        self._server_name = server_name

    async def wrap(
        self, tool_name: str, args: Any, call_fn: Callable[[], Awaitable[Any]]
    ) -> Any:
        start = time.monotonic()
        ok = True
        error_code: str | None = None
        result: Any = None
        try:
            result = await call_fn()
            return result
        except Exception as exc:
            ok = False
            error_code = getattr(exc, "code", "INTERNAL")
            raise
        finally:
            latency_ms = (time.monotonic() - start) * 1000
            event = AuditEvent(
                agent_id=self._agent_id,
                server=self._server_name,
                tool=tool_name,
                input_hash=hash_payload(args),
                output_hash=hash_payload(result) if ok else "",
                latency_ms=latency_ms,
                ok=ok,
                error_code=error_code,
            )
            await self._sink.log_event(event)
