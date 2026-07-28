import pytest
from awp_mcp_base.server import AwpMcpServer
from awp_shared.auth import mint_service_jwt
from awp_shared.errors import NotFoundError, ValidationError


def _headers(scopes: list[str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {mint_service_jwt('OPS-1', scopes)}"}


def _write() -> dict[str, str]:
    return _headers(["projects.write"])


def _read() -> dict[str, str]:
    return _headers(["projects.read"])


@pytest.mark.asyncio
async def test_create_issue_round_trips(projects_server: AwpMcpServer) -> None:
    created = await projects_server.dispatch_raw(
        "create_issue",
        {
            "project_id": "P1",
            "description": "milestone slipping",
            "impact": "schedule",
            "severity": "S1",
        },
        _write(),
    )
    assert created["severity"] == "S1"
    assert created["status"] == "open"

    fetched = await projects_server.dispatch_raw(
        "get_issue", {"issue_id": created["id"]}, _read()
    )
    assert fetched["description"] == "milestone slipping"


@pytest.mark.asyncio
async def test_create_issue_requires_fields(projects_server: AwpMcpServer) -> None:
    with pytest.raises(ValidationError):
        await projects_server.dispatch_raw(
            "create_issue", {"project_id": "P1"}, _write()
        )


@pytest.mark.asyncio
async def test_create_issue_rejects_bad_impact(projects_server: AwpMcpServer) -> None:
    with pytest.raises(ValidationError):
        await projects_server.dispatch_raw(
            "create_issue",
            {"project_id": "P1", "description": "x", "impact": "vibes"},
            _write(),
        )


@pytest.mark.asyncio
async def test_get_issue_not_found(projects_server: AwpMcpServer) -> None:
    with pytest.raises(NotFoundError):
        await projects_server.dispatch_raw("get_issue", {"issue_id": "nope"}, _read())


@pytest.mark.asyncio
async def test_query_issues_filters_by_severity(projects_server: AwpMcpServer) -> None:
    await projects_server.dispatch_raw(
        "create_issue",
        {"project_id": "P1", "description": "a", "impact": "cost", "severity": "S1"},
        _write(),
    )
    await projects_server.dispatch_raw(
        "create_issue",
        {"project_id": "P1", "description": "b", "impact": "scope", "severity": "S3"},
        _write(),
    )
    result = await projects_server.dispatch_raw(
        "query_issues", {"project_id": "P1", "severity": "S1"}, _read()
    )
    assert len(result["issues"]) == 1
    assert result["issues"][0]["description"] == "a"


@pytest.mark.asyncio
async def test_update_issue_patches_status(projects_server: AwpMcpServer) -> None:
    created = await projects_server.dispatch_raw(
        "create_issue",
        {"project_id": "P1", "description": "x", "impact": "quality"},
        _write(),
    )
    updated = await projects_server.dispatch_raw(
        "update_issue",
        {"issue_id": created["id"], "patch": {"status": "resolved"}},
        _write(),
    )
    assert updated["status"] == "resolved"


@pytest.mark.asyncio
async def test_update_issue_not_found(projects_server: AwpMcpServer) -> None:
    with pytest.raises(NotFoundError):
        await projects_server.dispatch_raw(
            "update_issue", {"issue_id": "nope", "patch": {"status": "resolved"}}, _write()
        )
