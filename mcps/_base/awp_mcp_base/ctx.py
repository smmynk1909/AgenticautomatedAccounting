"""Per-call request context handed to every tool handler — doc 11 §3."""

from __future__ import annotations

from dataclasses import dataclass

from awp_shared.auth import Principal


@dataclass
class Ctx:
    principal: Principal
    trace_id: str
    idempotency_key: str | None = None
    approval_token: str | None = None
