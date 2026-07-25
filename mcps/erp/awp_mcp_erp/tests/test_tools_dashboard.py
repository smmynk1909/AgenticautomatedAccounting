from datetime import UTC, datetime, timedelta

import pytest
from awp_mcp_base.server import AwpMcpServer
from awp_shared.auth import mint_service_jwt
from awp_shared.errors import ValidationError


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _write_token() -> str:
    return mint_service_jwt("ADM-1", ["erp.dashboard.write"])


def _read_token() -> str:
    return mint_service_jwt("ADM-1", ["erp.dashboard.read"])


@pytest.mark.asyncio
async def test_push_and_get_dashboard_item_for_matching_role(erp_server: AwpMcpServer) -> None:
    await erp_server.dispatch_raw(
        "push_dashboard_item",
        {
            "item": {
                "audience_roles": ["ceo", "director"],
                "panel": "approvals",
                "title": "3 pending",
                "body": "3 approvals pending review",
            }
        },
        _headers(_write_token()),
    )
    ceo_view = await erp_server.dispatch_raw(
        "get_dashboard", {"role": "ceo"}, _headers(_read_token())
    )
    manager_view = await erp_server.dispatch_raw(
        "get_dashboard", {"role": "manager"}, _headers(_read_token())
    )

    assert len(ceo_view["items"]) == 1
    assert manager_view["items"] == []


@pytest.mark.asyncio
async def test_push_dashboard_item_missing_fields_raises(erp_server: AwpMcpServer) -> None:
    with pytest.raises(ValidationError):
        await erp_server.dispatch_raw(
            "push_dashboard_item", {"item": {"panel": "approvals"}}, _headers(_write_token())
        )


@pytest.mark.asyncio
async def test_push_dashboard_item_body_too_long_raises(erp_server: AwpMcpServer) -> None:
    with pytest.raises(ValidationError, match="400 characters"):
        await erp_server.dispatch_raw(
            "push_dashboard_item",
            {"item": {"audience_roles": ["ceo"], "panel": "x", "title": "t", "body": "x" * 401}},
            _headers(_write_token()),
        )


@pytest.mark.asyncio
async def test_expired_dashboard_item_excluded(erp_server: AwpMcpServer) -> None:
    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    await erp_server.dispatch_raw(
        "push_dashboard_item",
        {
            "item": {
                "audience_roles": ["ceo"],
                "panel": "x",
                "title": "expired",
                "body": "b",
                "expires_at": past,
            }
        },
        _headers(_write_token()),
    )
    view = await erp_server.dispatch_raw("get_dashboard", {"role": "ceo"}, _headers(_read_token()))
    assert view["items"] == []
