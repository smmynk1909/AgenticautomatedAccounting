"""Tamper-evidence check — doc 08 §9. Recomputes a day's Merkle root from
whatever rows are currently in `audit_events` and compares it to the
persisted `audit_day_roots` value. Any edit, deletion, or reordering of a
day's events after its root was stored changes the recomputed root.
"""

from __future__ import annotations

from pydantic import BaseModel

from awp_mcp_audit.chain import merkle_root, record_hash_from_row
from awp_mcp_audit.store import EventStore


class VerificationResult(BaseModel):
    day: str
    stored_root: str | None
    recomputed_root: str
    event_count: int
    tampered: bool


async def verify_day(store: EventStore, day: str) -> VerificationResult:
    events = await store.events_for_day(day)
    recomputed = merkle_root([record_hash_from_row(e) for e in events])
    stored = await store.get_day_root(day)
    stored_root = stored["root_hash"] if stored else None
    tampered = stored_root is not None and stored_root != recomputed
    return VerificationResult(
        day=day,
        stored_root=stored_root,
        recomputed_root=recomputed,
        event_count=len(events),
        tampered=tampered,
    )
