import pytest
from awp_mcp_base.server import AwpMcpServer
from awp_shared.auth import mint_service_jwt
from awp_shared.errors import ValidationError


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _notify_token() -> str:
    return mint_service_jwt("SUP-1", ["comms.notify"])


def _broadcast_token() -> str:
    return mint_service_jwt("SUP-1", ["comms.notify.broadcast"])


def _draft_token() -> str:
    return mint_service_jwt("HR-1", ["comms.draft"])


@pytest.mark.asyncio
async def test_notify_user_records_outbox_entry(comms_server: AwpMcpServer) -> None:
    result = await comms_server.dispatch_raw(
        "notify_user",
        {"user_id": "emp1", "subject": "Ticket update", "body": "your ticket moved"},
        _headers(_notify_token()),
    )
    assert "outbox_id" in result


@pytest.mark.asyncio
async def test_notify_user_requires_fields(comms_server: AwpMcpServer) -> None:
    with pytest.raises(ValidationError):
        await comms_server.dispatch_raw(
            "notify_user", {"user_id": "emp1"}, _headers(_notify_token())
        )


@pytest.mark.asyncio
async def test_send_reminder_records_outbox_entry(comms_server: AwpMcpServer) -> None:
    result = await comms_server.dispatch_raw(
        "send_reminder",
        {"user_id": "emp1", "subject": "SLA reminder", "body": "75% of SLA consumed"},
        _headers(_notify_token()),
    )
    assert "outbox_id" in result


@pytest.mark.asyncio
async def test_draft_external_email_records_outbox_entry(comms_server: AwpMcpServer) -> None:
    result = await comms_server.dispatch_raw(
        "draft_external_email",
        {"candidate_id": "C1", "subject": "Offer discussion", "body": "We're pleased to..."},
        _headers(_draft_token()),
    )
    assert "outbox_id" in result


@pytest.mark.asyncio
async def test_draft_external_email_requires_fields(comms_server: AwpMcpServer) -> None:
    with pytest.raises(ValidationError):
        await comms_server.dispatch_raw(
            "draft_external_email", {"candidate_id": "C1"}, _headers(_draft_token())
        )


@pytest.mark.asyncio
async def test_draft_external_email_requires_scope(comms_server: AwpMcpServer) -> None:
    from awp_shared.errors import PermissionDeniedError

    with pytest.raises(PermissionDeniedError):
        await comms_server.dispatch_raw(
            "draft_external_email",
            {"candidate_id": "C1", "subject": "x", "body": "y"},
            _headers(_notify_token()),  # comms.notify, not comms.draft
        )


@pytest.mark.asyncio
async def test_incident_broadcast_records_broadcast_entry(comms_server: AwpMcpServer) -> None:
    result = await comms_server.dispatch_raw(
        "incident_broadcast",
        {"subject": "VPN outage", "body": "Investigating VPN drops since 09:00"},
        _headers(_broadcast_token()),
    )
    assert "outbox_id" in result


@pytest.mark.asyncio
async def test_incident_broadcast_requires_scope(comms_server: AwpMcpServer) -> None:
    from awp_shared.errors import PermissionDeniedError

    with pytest.raises(PermissionDeniedError):
        await comms_server.dispatch_raw(
            "incident_broadcast",
            {"subject": "x", "body": "y"},
            _headers(_notify_token()),  # comms.notify, not comms.notify.broadcast
        )


@pytest.mark.asyncio
async def test_incident_broadcast_requires_fields(comms_server: AwpMcpServer) -> None:
    with pytest.raises(ValidationError):
        await comms_server.dispatch_raw(
            "incident_broadcast", {"subject": "x"}, _headers(_broadcast_token())
        )
