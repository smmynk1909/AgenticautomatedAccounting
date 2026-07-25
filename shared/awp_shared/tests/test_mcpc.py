import pytest
from pydantic import BaseModel

from awp_shared.errors import NotFoundError, PermissionDeniedError, UpstreamError
from awp_shared.mcpc import MCP, McpTransportError


class _Args(BaseModel):
    emp_id: str


def _mcp_with_raw(raw_result: dict, captured: dict | None = None) -> MCP:
    mcp = MCP({"erp": "http://mcp-erp:8000"}, principal_jwt_provider=lambda: "svc-token")

    async def fake_call_tool_raw(url: str, tool: str, payload: dict, headers: dict) -> dict:
        if captured is not None:
            captured.update(url=url, tool=tool, payload=payload, headers=headers)
        return raw_result

    mcp._call_tool_raw = fake_call_tool_raw  # type: ignore[method-assign]
    return mcp


@pytest.mark.asyncio
async def test_call_returns_result_dict_on_success() -> None:
    mcp = _mcp_with_raw({"emp_id": "E1", "name": "Asha"})
    result = await mcp.call("erp", "get_employee", _Args(emp_id="E1"))
    assert result == {"emp_id": "E1", "name": "Asha"}


@pytest.mark.asyncio
async def test_call_attaches_auth_trace_and_idempotency_headers() -> None:
    captured: dict = {}
    mcp = _mcp_with_raw({"ok": True}, captured)
    await mcp.call("erp", "get_employee", {"emp_id": "E1"}, idempotency_key="task-1:step-1")

    assert captured["headers"]["Authorization"] == "Bearer svc-token"
    assert "X-Trace-Id" in captured["headers"]
    assert captured["headers"]["X-Idempotency-Key"] == "task-1:step-1"
    assert captured["tool"] == "get_employee"


@pytest.mark.asyncio
async def test_call_merges_approval_token_into_payload() -> None:
    captured: dict = {}
    mcp = _mcp_with_raw({"ok": True}, captured)
    await mcp.call("erp", "assign_asset", {"asset_id": "A1"}, approval_token="tok-123")
    assert captured["payload"]["approval_token"] == "tok-123"


@pytest.mark.asyncio
async def test_call_raises_typed_error_on_server_error_envelope() -> None:
    mcp = _mcp_with_raw(
        {
            "error": {
                "code": "NOT_FOUND",
                "message": "no such employee",
                "retryable": False,
                "details": {},
            }
        }
    )
    with pytest.raises(NotFoundError):
        await mcp.call("erp", "get_employee", _Args(emp_id="does-not-exist"))


@pytest.mark.asyncio
async def test_call_permission_denied_error_envelope() -> None:
    mcp = _mcp_with_raw(
        {
            "error": {
                "code": "PERMISSION_DENIED",
                "message": "no scope",
                "retryable": False,
                "details": {},
            }
        }
    )
    with pytest.raises(PermissionDeniedError):
        await mcp.call("erp", "assign_asset", {"asset_id": "A1"})


@pytest.mark.asyncio
async def test_call_unknown_server_raises_value_error() -> None:
    mcp = MCP({"erp": "http://mcp-erp:8000"}, principal_jwt_provider=lambda: "svc-token")
    with pytest.raises(ValueError, match="unknown MCP server"):
        await mcp.call("finance", "compute_payroll", {})


@pytest.mark.asyncio
async def test_transport_failure_raises_upstream_error() -> None:
    mcp = MCP({"erp": "http://mcp-erp:8000"}, principal_jwt_provider=lambda: "svc-token")

    async def broken(url: str, tool: str, payload: dict, headers: dict) -> dict:
        raise McpTransportError("connection refused")

    mcp._call_tool_raw = broken  # type: ignore[method-assign]
    with pytest.raises(UpstreamError):
        await mcp.call("erp", "get_employee", {"emp_id": "E1"})
