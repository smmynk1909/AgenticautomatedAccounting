"""Approval-token minting — the ONLY module allowed to call
`awp_shared.auth.mint_approval_token` (doc 08 §5: token minted only on human
approve). `service.py`'s `approve()` calls `finalize_approval` once the
n_required-th vote lands; nothing else in the codebase reaches this.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from awp_shared.auth import mint_approval_token

from awp_mcp_approvals.gates import GateConfig
from awp_mcp_approvals.store import ApprovalStore


async def finalize_approval(store: ApprovalStore, record: dict[str, Any], gate: GateConfig) -> str:
    jti = str(uuid4())
    approvers = [vote["user_id"] for vote in record["approvals_received"]]
    token = mint_approval_token(
        gate=gate.name,
        payload=record["payload"],
        approvers=approvers,
        ttl_h=gate.ttl_h,
        jti=jti,
    )
    await store.mark_approved(record["id"], token=token, token_jti=jti)
    return token
