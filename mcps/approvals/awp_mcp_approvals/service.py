"""Human approve/reject actions — doc 08 §5: "Human-only UI endpoints (NOT
MCP tools): approve/reject. No agent scope can ever approve — enforced
structurally."

These are plain async functions, never registered as tools on `AwpMcpServer`
(see `server.py` — there is no "approve" tool for any scope to be granted
against; the enforcement is structural absence, not a permission check that
could be misconfigured). The Sprint-3 gateway's
`POST /api/approvals/{id}/approve` route calls straight into this module,
authenticated with the requesting human's *user*-kind `Principal` — never an
agent JWT, which `require_human` rejects outright regardless of scopes.
"""

from __future__ import annotations

from typing import Any

from awp_shared.auth import Principal
from awp_shared.errors import ConflictError, NotFoundError, PermissionDeniedError

from awp_mcp_approvals.gates import resolve_gate
from awp_mcp_approvals.store import ApprovalStore
from awp_mcp_approvals.tokens import finalize_approval


def require_human(principal: Principal) -> None:
    if principal.kind != "user":
        raise PermissionDeniedError(
            "only human users can approve or reject — no agent scope exists for this action"
        )


async def _load_pending_and_authorize(
    store: ApprovalStore, approval_id: str, principal: Principal
) -> dict[str, Any]:
    require_human(principal)
    record = await store.mark_expired_if_due(approval_id)
    if record is None:
        raise NotFoundError(f"no such approval: {approval_id}")
    if record["status"] != "pending":
        raise ConflictError(f"approval {approval_id} is {record['status']}, not pending")

    gate = resolve_gate(record["gate"])
    if not set(principal.roles) & set(gate.approver_roles):
        raise PermissionDeniedError(
            f"role(s) {principal.roles} not authorized for gate {gate.name!r} "
            f"(needs one of {gate.approver_roles})"
        )
    already_voted = {vote["user_id"] for vote in record["approvals_received"]}
    if principal.sub in already_voted:
        raise ConflictError("this user has already voted on this approval (maker-checker)")
    return record


async def approve(
    store: ApprovalStore, approval_id: str, principal: Principal, comment: str = ""
) -> dict[str, Any]:
    record = await _load_pending_and_authorize(store, approval_id, principal)
    gate = resolve_gate(record["gate"])

    updated = await store.record_vote(approval_id, principal.sub, comment)
    votes_so_far = len(updated["approvals_received"])
    if votes_so_far >= gate.n_required:
        token = await finalize_approval(store, updated, gate)
        return {"approval_id": approval_id, "status": "approved", "token": token}
    return {
        "approval_id": approval_id,
        "status": "pending",
        "approvals_so_far": votes_so_far,
        "needed": gate.n_required,
    }


async def reject(
    store: ApprovalStore, approval_id: str, principal: Principal, reason: str
) -> dict[str, Any]:
    await _load_pending_and_authorize(store, approval_id, principal)
    await store.mark_rejected(approval_id, principal.sub, reason)
    return {"approval_id": approval_id, "status": "rejected"}
