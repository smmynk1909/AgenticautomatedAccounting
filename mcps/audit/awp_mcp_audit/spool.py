"""mcp-audit's own durability fallback — doc 09 §8 lists `spool.py` alongside
`chain.py`/`verifier.py`. Every *other* server already falls back to
`awp_shared.audit_mw.DiskSpool`/`SpoolingAuditSink` when a call *to*
mcp-audit fails; this module applies the same pattern to mcp-audit's own
write path, so a transient DB outage doesn't lose events mcp-audit accepted
about itself (its own tool calls are audited too, doc 08 §9's "Middleware
library ... auto-instruments all servers").
"""

from __future__ import annotations

import os
from pathlib import Path

from awp_mcp_base.uow import UnitOfWork
from awp_shared.audit_mw import AuditEvent, DiskSpool, SpoolingAuditSink

from awp_mcp_audit.store import EventStore


def default_spool_dir() -> Path:
    return Path(os.environ.get("AWP_AUDIT_SPOOL_DIR", "./.spool/audit"))


class DirectStoreSink:
    """Structurally satisfies `AuditSink` (log_event) by writing straight to
    the DB via `EventStore.append` — no network hop, since this *is* mcp-audit."""

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def log_event(self, event: AuditEvent) -> None:
        async with self._uow() as session:
            await EventStore(session).append(event)


def build_self_spooling_sink(
    uow: UnitOfWork, *, spool_dir: Path | None = None
) -> SpoolingAuditSink:
    return SpoolingAuditSink(DirectStoreSink(uow), DiskSpool(spool_dir or default_spool_dir()))
