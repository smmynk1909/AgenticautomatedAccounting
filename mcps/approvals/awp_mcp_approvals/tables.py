"""`approvals` — doc 09 §1: `approvals(id,gate,payload_hash,requested_by,
approvers jsonb,status,token_jti,expires_at)`, extended with the fields the
actual workflow needs (payload itself for the approver-UI card per doc 08 §5,
the granted role list, per-vote records, and the minted token — see
`store.py` for why the token, not just its jti, is persisted).
"""

from __future__ import annotations

from sqlalchemy import JSON, Column, DateTime, Integer, MetaData, String, Table

metadata = MetaData()

approvals = Table(
    "approvals",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("gate", String(64), nullable=False, index=True),
    Column("payload", JSON, nullable=False),
    Column("payload_hash", String(64), nullable=False),
    Column("requested_by", String(64), nullable=False),
    Column("approver_roles", JSON, nullable=False),
    Column("n_required", Integer, nullable=False),
    Column("approvals_received", JSON, nullable=False, default=list),  # [{user_id, ts, comment}]
    Column(
        "status", String(16), nullable=False, default="pending"
    ),  # pending|approved|rejected|expired
    Column("token", String, nullable=True),
    Column("token_jti", String(64), nullable=True),
    Column("rejected_by", String(64), nullable=True),
    Column("rejection_reason", String, nullable=True),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
