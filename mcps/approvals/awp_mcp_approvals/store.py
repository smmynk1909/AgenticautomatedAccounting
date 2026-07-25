"""Approval record store — doc 09 §1 `approvals` table.

The minted token (not only its `jti`) is persisted on the row once approved,
so `get_approval_status` can hand it back per doc 08 §5's contract
("+ token when approved"). This is safe: the token is already a short-TTL,
single-use, cryptographically signed artifact (`verify_approval_token`'s
Redis `SETNX` on `jti` still enforces single-use regardless of how many
times the row is read), and it's reachable only through the same
scope/auth-gated MCP surface as everything else in this store.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from awp_shared.auth import canonical_payload_hash
from awp_shared.timeutil import ensure_aware_utc
from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from awp_mcp_approvals.tables import approvals


class ApprovalStore:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        gate: str,
        payload: dict[str, Any],
        requested_by: str,
        approver_roles: list[str],
        n_required: int,
        ttl_h: int,
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        row: dict[str, Any] = dict(
            id=str(uuid.uuid4()),
            gate=gate,
            payload=payload,
            payload_hash=canonical_payload_hash(payload),
            requested_by=requested_by,
            approver_roles=approver_roles,
            n_required=n_required,
            approvals_received=[],
            status="pending",
            token=None,
            token_jti=None,
            rejected_by=None,
            rejection_reason=None,
            expires_at=now + timedelta(hours=ttl_h),
            created_at=now,
        )
        await self.session.execute(insert(approvals).values(**row))
        return row

    async def get(self, approval_id: str) -> dict[str, Any] | None:
        row = (
            (await self.session.execute(select(approvals).where(approvals.c.id == approval_id)))
            .mappings()
            .first()
        )
        return dict(row) if row else None

    async def record_vote(self, approval_id: str, user_id: str, comment: str) -> dict[str, Any]:
        record = await self.get(approval_id)
        if record is None:
            raise KeyError(approval_id)
        votes = [
            *record["approvals_received"],
            {"user_id": user_id, "ts": datetime.now(UTC).isoformat(), "comment": comment},
        ]
        await self.session.execute(
            update(approvals).where(approvals.c.id == approval_id).values(approvals_received=votes)
        )
        record["approvals_received"] = votes
        return record

    async def mark_approved(self, approval_id: str, *, token: str, token_jti: str) -> None:
        await self.session.execute(
            update(approvals)
            .where(approvals.c.id == approval_id)
            .values(status="approved", token=token, token_jti=token_jti)
        )

    async def mark_rejected(self, approval_id: str, user_id: str, reason: str) -> None:
        await self.session.execute(
            update(approvals)
            .where(approvals.c.id == approval_id)
            .values(status="rejected", rejected_by=user_id, rejection_reason=reason)
        )

    async def mark_expired_if_due(self, approval_id: str) -> dict[str, Any] | None:
        record = await self.get(approval_id)
        if (
            record
            and record["status"] == "pending"
            and ensure_aware_utc(record["expires_at"]) < datetime.now(UTC)
        ):
            await self.session.execute(
                update(approvals).where(approvals.c.id == approval_id).values(status="expired")
            )
            record["status"] = "expired"
        return record
