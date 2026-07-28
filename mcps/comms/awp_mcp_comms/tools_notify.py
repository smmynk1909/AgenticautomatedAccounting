"""Notification tools — doc 07 §4, doc 08 §1. See `tables.py`'s docstring
and DEVIATIONS.md #10: these record to `comms_outbox` durably; nothing
delivers them over a real channel yet (dev-mode stub, same pattern as the
LLM gateway and auth deviations).
"""

from __future__ import annotations

import uuid
from typing import Any

from awp_mcp_base.ctx import Ctx
from awp_mcp_base.server import AwpMcpServer
from awp_mcp_base.uow import UnitOfWork
from awp_shared.errors import ValidationError

from awp_mcp_comms.repos.outbox import OutboxRepo


async def _record(
    uow: UnitOfWork,
    ctx: Ctx,
    *,
    kind: str,
    recipient_type: str,
    recipient_id: str | None,
    subject: str,
    body: str,
    refs: dict[str, Any],
) -> dict[str, Any]:
    outbox_id = str(uuid.uuid4())
    async with uow() as session:
        await OutboxRepo(session).insert(
            {
                "id": outbox_id,
                "kind": kind,
                "recipient_type": recipient_type,
                "recipient_id": recipient_id,
                "subject": subject,
                "body": body,
                "refs": refs,
                "sent_by": ctx.principal.sub,
            }
        )
    return {"outbox_id": outbox_id}


def register_notify_tools(server: AwpMcpServer, uow: UnitOfWork) -> None:
    @server.tool()
    async def notify_user(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        user_id = payload.get("user_id")
        subject = payload.get("subject")
        body = payload.get("body")
        if not user_id or not subject or not body:
            raise ValidationError("notify_user requires 'user_id', 'subject', 'body'")
        return await _record(
            uow,
            ctx,
            kind="notify_user",
            recipient_type="user",
            recipient_id=user_id,
            subject=subject,
            body=body,
            refs=payload.get("refs", {}),
        )

    @server.tool()
    async def send_reminder(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        user_id = payload.get("user_id")
        subject = payload.get("subject")
        body = payload.get("body")
        if not user_id or not subject or not body:
            raise ValidationError("send_reminder requires 'user_id', 'subject', 'body'")
        return await _record(
            uow,
            ctx,
            kind="send_reminder",
            recipient_type="user",
            recipient_id=user_id,
            subject=subject,
            body=body,
            refs=payload.get("refs", {}),
        )

    @server.tool()
    async def draft_external_email(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        # doc 04 §2.4/§3: "draft-only object; sending is a human click" — no
        # real send path exists in this build (DEVIATIONS.md #10, same
        # dev-mode-stub delivery gap as notify_user/send_reminder). Callers
        # are expected to have already gated the exact frozen text through
        # an approval (e.g. HR-1's `offer_communication`) before calling
        # this — this tool only durably records it.
        candidate_id = payload.get("candidate_id")
        subject = payload.get("subject")
        body = payload.get("body")
        if not candidate_id or not subject or not body:
            raise ValidationError("draft_external_email requires 'candidate_id', 'subject', 'body'")
        return await _record(
            uow,
            ctx,
            kind="draft_external_email",
            recipient_type="candidate",
            recipient_id=candidate_id,
            subject=subject,
            body=body,
            refs=payload.get("refs", {}),
        )

    @server.tool()
    async def incident_broadcast(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        # doc 07 §3.4: P1 breach -> Director + CEO panel + incident channel.
        # No role targeting param here on purpose — a broadcast reaches
        # everyone subscribed to the incident channel, not a role list the
        # caller picks (that would make it just a bulk notify_user).
        subject = payload.get("subject")
        body = payload.get("body")
        if not subject or not body:
            raise ValidationError("incident_broadcast requires 'subject', 'body'")
        return await _record(
            uow,
            ctx,
            kind="incident_broadcast",
            recipient_type="broadcast",
            recipient_id=None,
            subject=subject,
            body=body,
            refs=payload.get("refs", {}),
        )
