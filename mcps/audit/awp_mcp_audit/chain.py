"""Daily Merkle hash-chain — doc 08 §9 "append-only table + daily hash-chain
(each day's Merkle root stored; tamper-evident)".

Every stored event gets a `record_hash` (sha256 of its immutable fields,
including its append-order `seq`, so reordering is also detectable). At
day-close (or on demand — `verifier.py` can recompute at any time) the day's
`record_hash`es fold into a single Merkle root via `merkle_root`, persisted
in `audit_day_roots`. Editing, deleting, or reordering any event for a day
whose root has already been computed changes the recomputed root, which is
exactly what `verifier.py` checks for.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from awp_shared.audit_mw import AuditEvent, hash_payload


def event_day(event: AuditEvent) -> str:
    return event.ts.date().isoformat()


def _canonical_fields(
    *,
    seq: int,
    ts: str,
    agent_id: str,
    server: str,
    tool: str,
    input_hash: str,
    output_hash: str,
    ok: bool,
    error_code: str | None,
) -> dict[str, Any]:
    return {
        "seq": seq,
        "ts": ts,
        "agent_id": agent_id,
        "server": server,
        "tool": tool,
        "input_hash": input_hash,
        "output_hash": output_hash,
        "ok": ok,
        "error_code": error_code,
    }


def record_hash(event: AuditEvent, seq: int) -> str:
    """Hash computed fresh from an in-memory `AuditEvent` at append time."""
    return hash_payload(
        _canonical_fields(
            seq=seq,
            ts=event.ts.isoformat(),
            agent_id=event.agent_id,
            server=event.server,
            tool=event.tool,
            input_hash=event.input_hash,
            output_hash=event.output_hash,
            ok=event.ok,
            error_code=event.error_code,
        )
    )


def record_hash_from_row(row: dict[str, Any]) -> str:
    """Hash recomputed from a DB row's *current* column values — used by
    `verifier.py`. Deliberately does NOT read the row's stored `record_hash`
    column: trusting a value that could itself have been edited alongside the
    tampered column would make tamper detection a no-op. Recomputing from the
    other columns means editing *any* of them changes this hash, which
    changes the day's Merkle root, which is what verification compares."""
    ts = row["ts"]
    ts_str = ts.isoformat() if isinstance(ts, datetime) else str(ts)
    return hash_payload(
        _canonical_fields(
            seq=row["seq"],
            ts=ts_str,
            agent_id=row["agent_id"],
            server=row["server"],
            tool=row["tool"],
            input_hash=row["input_hash"],
            output_hash=row["output_hash"],
            ok=row["ok"],
            error_code=row["error_code"],
        )
    )


def merkle_root(record_hashes: list[str]) -> str:
    """Standard pairwise Merkle tree (odd node duplicated). Empty input has a
    well-defined root so a zero-event day is still verifiable."""
    if not record_hashes:
        return hashlib.sha256(b"").hexdigest()

    level = [bytes.fromhex(h) for h in record_hashes]
    while len(level) > 1:
        next_level: list[bytes] = []
        for i in range(0, len(level), 2):
            left = level[i]
            right = level[i + 1] if i + 1 < len(level) else left
            next_level.append(hashlib.sha256(left + right).digest())
        level = next_level
    return level[0].hex()
