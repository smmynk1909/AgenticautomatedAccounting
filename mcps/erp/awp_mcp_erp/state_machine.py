"""Ticket status transition validation — doc 07 §2 status enum, doc 08 §1
"status transitions validated by state machine; illegal transition ->
VALIDATION".
"""

from __future__ import annotations

from awp_shared.errors import ValidationError

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "new": {"triaged"},
    "triaged": {"assigned", "closed"},
    "assigned": {"in_progress", "triaged"},
    "in_progress": {"waiting_requester", "waiting_approval", "resolved", "assigned"},
    "waiting_requester": {"in_progress", "resolved", "closed"},
    "waiting_approval": {"in_progress", "resolved"},
    "resolved": {"closed", "reopened"},
    "closed": {"reopened"},
    "reopened": {"triaged", "assigned", "in_progress"},
}


def validate_transition(current: str, target: str) -> None:
    if current == target:
        return  # idempotent no-op updates are fine
    allowed = ALLOWED_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise ValidationError(
            f"illegal ticket transition: {current!r} -> {target!r} (allowed: {sorted(allowed)})"
        )
