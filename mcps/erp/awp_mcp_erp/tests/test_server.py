import pytest
from awp_mcp_base.server import AwpMcpServer
from awp_shared.auth import mint_service_jwt
from awp_shared.errors import PermissionDeniedError, ValidationError


def _headers(token: str, idempotency_key: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if idempotency_key:
        headers["X-Idempotency-Key"] = idempotency_key
    return headers


@pytest.mark.asyncio
async def test_missing_auth_header_rejected(erp_server: AwpMcpServer) -> None:
    with pytest.raises(ValidationError):
        await erp_server.dispatch_raw("get_asset", {"asset_id": "x"}, {})


@pytest.mark.asyncio
async def test_missing_scope_rejected(erp_server: AwpMcpServer) -> None:
    token = mint_service_jwt("ADM-1", [])  # no scopes at all
    with pytest.raises(PermissionDeniedError):
        await erp_server.dispatch_raw("query_assets", {}, _headers(token))


@pytest.mark.asyncio
async def test_all_registered_tools_have_a_scopes_yaml_entry(erp_server: AwpMcpServer) -> None:
    """Regression guard: every tool this server exposes must be reachable
    under *some* scope grant — an un-entried tool would silently require
    zero scopes (== open to any authenticated caller)."""
    from awp_shared.config import get_required_scopes, load_config

    load_config.cache_clear()
    for tool_name in erp_server.tool_names:
        scopes = get_required_scopes("erp", tool_name)
        assert scopes, f"erp.{tool_name} has no scopes.yaml entry (would require zero scopes)"


@pytest.mark.asyncio
async def test_idempotent_replay_does_not_recreate_dashboard_item(erp_server: AwpMcpServer) -> None:
    token = mint_service_jwt("ADM-1", ["erp.dashboard.write"])
    item = {"audience_roles": ["ceo"], "panel": "x", "title": "t", "body": "b"}
    headers = _headers(token, idempotency_key="task-1:step-1")

    first = await erp_server.dispatch_raw("push_dashboard_item", {"item": item}, headers)
    second = await erp_server.dispatch_raw("push_dashboard_item", {"item": item}, headers)
    assert first["id"] == second["id"]
