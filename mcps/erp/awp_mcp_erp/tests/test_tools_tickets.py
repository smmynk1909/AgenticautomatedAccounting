import pytest
from awp_mcp_base.server import AwpMcpServer
from awp_shared.auth import mint_service_jwt
from awp_shared.errors import PermissionDeniedError, ValidationError


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _write_token() -> str:
    return mint_service_jwt("SUP-1", ["erp.tickets.write"])


def _read_token() -> str:
    return mint_service_jwt("SUP-1", ["erp.tickets.read"])


def _summary_token() -> str:
    return mint_service_jwt("SUP-1", ["erp.tickets.write.summary"])


@pytest.mark.asyncio
async def test_create_ticket_then_get(erp_server: AwpMcpServer) -> None:
    created = await erp_server.dispatch_raw(
        "create_ticket",
        {
            "channel": "chat",
            "requester": {"type": "employee", "id": "EMP-00001"},
            "category": "device",
            "subject": "Laptop broken",
        },
        _headers(_write_token()),
    )
    assert created["ticket_id"].startswith("TKT-")
    assert created["status"] == "new"
    assert created["confidential"] is False

    fetched = await erp_server.dispatch_raw(
        "get_ticket", {"ticket_id": created["ticket_id"]}, _headers(_read_token())
    )
    assert fetched["events"] == []


@pytest.mark.asyncio
async def test_create_ticket_grievance_is_confidential(erp_server: AwpMcpServer) -> None:
    created = await erp_server.dispatch_raw(
        "create_ticket",
        {
            "channel": "chat",
            "requester": {"type": "employee", "id": "EMP-00001"},
            "category": "hr",
            "subcategory": "grievance",
            "subject": "confidential matter",
        },
        _headers(_write_token()),
    )
    assert created["confidential"] is True


@pytest.mark.asyncio
async def test_query_tickets_filters_by_category(erp_server: AwpMcpServer) -> None:
    await erp_server.dispatch_raw(
        "create_ticket",
        {"channel": "chat", "requester": {"id": "EMP-1"}, "category": "device", "subject": "a"},
        _headers(_write_token()),
    )
    await erp_server.dispatch_raw(
        "create_ticket",
        {"channel": "chat", "requester": {"id": "EMP-2"}, "category": "payroll", "subject": "b"},
        _headers(_write_token()),
    )
    result = await erp_server.dispatch_raw(
        "query_tickets", {"category": "device"}, _headers(_read_token())
    )
    assert len(result["tickets"]) == 1
    assert result["tickets"][0]["category"] == "device"


@pytest.mark.asyncio
async def test_append_ticket_event_shows_up_in_get_ticket(erp_server: AwpMcpServer) -> None:
    created = await erp_server.dispatch_raw(
        "create_ticket",
        {"channel": "chat", "requester": {"id": "EMP-1"}, "category": "device", "subject": "a"},
        _headers(_write_token()),
    )
    await erp_server.dispatch_raw(
        "append_ticket_event",
        {
            "ticket_id": created["ticket_id"],
            "event": {"type": "comment", "body": {"text": "looking into it"}},
        },
        _headers(_write_token()),
    )
    fetched = await erp_server.dispatch_raw(
        "get_ticket", {"ticket_id": created["ticket_id"]}, _headers(_read_token())
    )
    assert len(fetched["events"]) == 1
    assert fetched["events"][0]["type"] == "comment"


@pytest.mark.asyncio
async def test_update_ticket_legal_transition(erp_server: AwpMcpServer) -> None:
    created = await erp_server.dispatch_raw(
        "create_ticket",
        {"channel": "chat", "requester": {"id": "EMP-1"}, "category": "device", "subject": "a"},
        _headers(_write_token()),
    )
    updated = await erp_server.dispatch_raw(
        "update_ticket",
        {"ticket_id": created["ticket_id"], "patch": {"status": "triaged"}},
        _headers(_write_token()),
    )
    assert updated["status"] == "triaged"


@pytest.mark.asyncio
async def test_update_ticket_illegal_transition_raises(erp_server: AwpMcpServer) -> None:
    created = await erp_server.dispatch_raw(
        "create_ticket",
        {"channel": "chat", "requester": {"id": "EMP-1"}, "category": "device", "subject": "a"},
        _headers(_write_token()),
    )
    with pytest.raises(ValidationError, match="illegal ticket transition"):
        await erp_server.dispatch_raw(
            "update_ticket",
            {"ticket_id": created["ticket_id"], "patch": {"status": "closed"}},
            _headers(_write_token()),
        )


@pytest.mark.asyncio
async def test_parent_cannot_resolve_with_open_child(erp_server: AwpMcpServer) -> None:
    parent = await erp_server.dispatch_raw(
        "create_ticket",
        {
            "channel": "agent",
            "requester": {"id": "ORCH-0"},
            "category": "cross_functional",
            "subject": "kickoff",
        },
        _headers(_write_token()),
    )
    child = await erp_server.dispatch_raw(
        "create_ticket",
        {
            "channel": "agent",
            "requester": {"id": "ORCH-0"},
            "category": "device",
            "subject": "provision laptop",
        },
        _headers(_write_token()),
    )
    await erp_server.dispatch_raw(
        "link_tickets",
        {"parent": parent["ticket_id"], "children": [child["ticket_id"]]},
        _headers(_write_token()),
    )

    # walk the parent through the legal transition path (state_machine.py) so
    # the *next* attempt is blocked by the open-child invariant, not by an
    # illegal-transition error unrelated to what this test is checking.
    for status in ("triaged", "assigned", "in_progress"):
        await erp_server.dispatch_raw(
            "update_ticket",
            {"ticket_id": parent["ticket_id"], "patch": {"status": status}},
            _headers(_write_token()),
        )

    with pytest.raises(ValidationError, match="child ticket"):
        await erp_server.dispatch_raw(
            "update_ticket",
            {"ticket_id": parent["ticket_id"], "patch": {"status": "resolved"}},
            _headers(_write_token()),
        )

    # close the child, then parent resolution is allowed
    await erp_server.dispatch_raw(
        "update_ticket",
        {"ticket_id": child["ticket_id"], "patch": {"status": "triaged"}},
        _headers(_write_token()),
    )
    await erp_server.dispatch_raw(
        "update_ticket",
        {"ticket_id": child["ticket_id"], "patch": {"status": "assigned"}},
        _headers(_write_token()),
    )
    await erp_server.dispatch_raw(
        "update_ticket",
        {"ticket_id": child["ticket_id"], "patch": {"status": "in_progress"}},
        _headers(_write_token()),
    )
    await erp_server.dispatch_raw(
        "update_ticket",
        {"ticket_id": child["ticket_id"], "patch": {"status": "resolved"}},
        _headers(_write_token()),
    )

    resolved_parent = await erp_server.dispatch_raw(
        "update_ticket",
        {"ticket_id": parent["ticket_id"], "patch": {"status": "resolved"}},
        _headers(_write_token()),
    )
    assert resolved_parent["status"] == "resolved"


@pytest.mark.asyncio
async def test_link_tickets_sets_parent_and_linked_ids(erp_server: AwpMcpServer) -> None:
    parent = await erp_server.dispatch_raw(
        "create_ticket",
        {
            "channel": "agent",
            "requester": {"id": "ORCH-0"},
            "category": "cross_functional",
            "subject": "kickoff",
        },
        _headers(_write_token()),
    )
    child = await erp_server.dispatch_raw(
        "create_ticket",
        {
            "channel": "agent",
            "requester": {"id": "ORCH-0"},
            "category": "device",
            "subject": "provision",
        },
        _headers(_write_token()),
    )
    updated_parent = await erp_server.dispatch_raw(
        "link_tickets",
        {"parent": parent["ticket_id"], "children": [child["ticket_id"]]},
        _headers(_write_token()),
    )
    assert child["ticket_id"] in updated_parent["linked_ticket_ids"]

    fetched_child = await erp_server.dispatch_raw(
        "get_ticket", {"ticket_id": child["ticket_id"]}, _headers(_read_token())
    )
    assert fetched_child["parent_ticket_id"] == parent["ticket_id"]


@pytest.mark.asyncio
async def test_set_summary_requires_dedicated_scope(erp_server: AwpMcpServer) -> None:
    created = await erp_server.dispatch_raw(
        "create_ticket",
        {"channel": "chat", "requester": {"id": "EMP-1"}, "category": "device", "subject": "a"},
        _headers(_write_token()),
    )
    with pytest.raises(PermissionDeniedError):
        await erp_server.dispatch_raw(
            "set_summary",
            {"ticket_id": created["ticket_id"], "text": "current status: pending parts"},
            _headers(_write_token()),  # has erp.tickets.write, NOT .write.summary
        )

    updated = await erp_server.dispatch_raw(
        "set_summary",
        {"ticket_id": created["ticket_id"], "text": "current status: pending parts"},
        _headers(_summary_token()),
    )
    assert updated["summary_current"] == "current status: pending parts"
