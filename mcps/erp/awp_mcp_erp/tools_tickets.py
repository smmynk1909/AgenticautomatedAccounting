"""Ticket-fabric tools — doc 08 §1 "Tickets (fabric)", doc 07 §2.

`update_ticket` is where the "parent never resolves with an open child"
invariant (doc 07 §3.2, acceptance test 2 in doc 07 §6) is enforced — code,
not an LLM decision.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from awp_mcp_base.ctx import Ctx
from awp_mcp_base.server import AwpMcpServer
from awp_mcp_base.uow import UnitOfWork
from awp_shared.config import load_config
from awp_shared.errors import NotFoundError, ValidationError

from awp_mcp_erp.repos.ticket import TicketEventRepo, TicketRepo
from awp_mcp_erp.state_machine import validate_transition


def register_ticket_tools(server: AwpMcpServer, uow: UnitOfWork) -> None:
    @server.tool()
    async def create_ticket(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        channel = payload.get("channel")
        requester = payload.get("requester", {})
        category = payload.get("category")
        if not channel or not requester.get("id") or not category:
            raise ValidationError("create_ticket requires 'channel', 'requester.id', 'category'")

        subcategory = payload.get("subcategory")
        confidential_subcats = load_config("routing").get("confidential_subcategories", [])
        confidential = bool(subcategory) and subcategory in confidential_subcats

        ticket_id = f"TKT-{datetime.now(UTC).year}-{uuid.uuid4().hex[:8].upper()}"
        async with uow() as session:
            await TicketRepo(session).insert(
                {
                    "ticket_id": ticket_id,
                    "channel": channel,
                    "requester_type": requester.get("type", "employee"),
                    "requester_id": requester["id"],
                    "category": category,
                    "subcategory": subcategory,
                    "priority": payload.get("priority", "P3"),
                    "status": "new",
                    "assignee_type": None,
                    "assignee_id": None,
                    "parent_ticket_id": payload.get("parent_ticket_id"),
                    "linked_ticket_ids": [],
                    "sla_first_response_due": None,
                    "sla_resolution_due": None,
                    "summary_current": payload.get("subject") or (payload.get("body", "")[:120]),
                    "resolution": {},
                    "confidential": confidential,
                }
            )
            created = await TicketRepo(session).get(ticket_id)
        assert created is not None
        return created

    @server.tool()
    async def get_ticket(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        ticket_id = payload.get("ticket_id")
        if not ticket_id:
            raise ValidationError("get_ticket requires 'ticket_id'")
        async with uow() as session:
            ticket = await TicketRepo(session).get(ticket_id)
            if ticket is None:
                raise NotFoundError(f"no such ticket: {ticket_id}")
            events = await TicketEventRepo(session).for_ticket(ticket_id)
        return {**ticket, "events": events}

    @server.tool()
    async def query_tickets(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        # doc 08 §1 "scope-filtered: dept agents see their own categories,
        # SUP-1 sees all" — category ACL enforcement is gateway/awp_gateway
        # (Sprint 3); this tool just applies whatever filters it's given
        # (including `requester_id`, for the gateway's employee self-service
        # "own tickets" view, roles.yaml).
        async with uow() as session:
            rows = await TicketRepo(session).query(
                status=payload.get("status"),
                category=payload.get("category"),
                priority=payload.get("priority"),
                assignee_id=payload.get("assignee_id"),
                requester_id=payload.get("requester_id"),
                limit=payload.get("limit", 50),
            )
        return {"tickets": rows}

    @server.tool()
    async def append_ticket_event(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        ticket_id = payload.get("ticket_id")
        event = payload.get("event")
        if not ticket_id or not event:
            raise ValidationError("append_ticket_event requires 'ticket_id' and 'event'")

        async with uow() as session:
            ticket = await TicketRepo(session).get(ticket_id)
            if ticket is None:
                raise NotFoundError(f"no such ticket: {ticket_id}")
            event_id = str(uuid.uuid4())
            await TicketEventRepo(session).insert(
                {
                    "id": event_id,
                    "ticket_id": ticket_id,
                    "actor": ctx.principal.sub,
                    "type": event.get("type", "comment"),
                    "body": event.get("body", {}),
                }
            )
        return {"event_id": event_id}

    @server.tool()
    async def update_ticket(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        ticket_id = payload.get("ticket_id")
        patch = payload.get("patch")
        if not ticket_id or not patch:
            raise ValidationError("update_ticket requires 'ticket_id' and 'patch'")

        async with uow() as session:
            repo = TicketRepo(session)
            ticket = await repo.get(ticket_id)
            if ticket is None:
                raise NotFoundError(f"no such ticket: {ticket_id}")

            if "status" in patch:
                validate_transition(ticket["status"], patch["status"])
                if patch["status"] in ("resolved", "closed"):
                    children = await repo.children(ticket_id)
                    open_children = [
                        c for c in children if c["status"] not in ("resolved", "closed")
                    ]
                    if open_children:
                        raise ValidationError(
                            f"cannot {patch['status']} ticket {ticket_id}: "
                            f"{len(open_children)} child ticket(s) still open"
                        )

            await repo.update(ticket_id, patch)
            updated = await repo.get(ticket_id)
        assert updated is not None
        return updated

    @server.tool()
    async def link_tickets(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        parent = payload.get("parent")
        children = payload.get("children", [])
        if not parent or not children:
            raise ValidationError("link_tickets requires 'parent' and 'children'")

        async with uow() as session:
            repo = TicketRepo(session)
            parent_ticket = await repo.get(parent)
            if parent_ticket is None:
                raise NotFoundError(f"no such parent ticket: {parent}")
            for child_id in children:
                child = await repo.get(child_id)
                if child is None:
                    raise NotFoundError(f"no such child ticket: {child_id}")
                await repo.update(child_id, {"parent_ticket_id": parent})
            linked = sorted(set(parent_ticket["linked_ticket_ids"]) | set(children))
            await repo.update(parent, {"linked_ticket_ids": linked})
            updated = await repo.get(parent)
        assert updated is not None
        return updated

    @server.tool()
    async def set_summary(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        # scope erp.tickets.write.summary — SUP-1c StatusKeeper only (doc 07 §3.3)
        ticket_id = payload.get("ticket_id")
        text = payload.get("text")
        if not ticket_id or text is None:
            raise ValidationError("set_summary requires 'ticket_id' and 'text'")
        async with uow() as session:
            repo = TicketRepo(session)
            ticket = await repo.get(ticket_id)
            if ticket is None:
                raise NotFoundError(f"no such ticket: {ticket_id}")
            await repo.update(ticket_id, {"summary_current": text})
            updated = await repo.get(ticket_id)
        assert updated is not None
        return updated
