from datetime import date

import pytest
from awp_mcp_base.server import AwpMcpServer
from awp_mcp_base.uow import UnitOfWork
from awp_shared.auth import mint_service_jwt
from awp_shared.errors import NotFoundError, ValidationError

from awp_mcp_erp.tables import employees


def _headers(scopes: list[str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {mint_service_jwt('OPS-1', scopes)}"}


def _write() -> dict[str, str]:
    return _headers(["erp.projects.write"])


def _read() -> dict[str, str]:
    return _headers(["erp.projects.read"])


@pytest.fixture
async def emp1(uow: UnitOfWork, base_org: dict[str, str]) -> str:
    async with uow() as session:
        await session.execute(
            employees.insert().values(
                emp_id="E1",
                name="Asha Rao",
                dept_id=base_org["dept_id"],
                role_id=base_org["role_id"],
                grade="E2",
                status="active",
                join_date=date(2024, 1, 1),
            )
        )
    return "E1"


@pytest.mark.asyncio
async def test_upsert_project_creates_and_updates(erp_server: AwpMcpServer) -> None:
    created = await erp_server.dispatch_raw(
        "upsert_project", {"record": {"client": "Acme Corp", "budget_hours": 500}}, _write()
    )
    assert created["client"] == "Acme Corp"
    assert created["status"] == "active"

    updated = await erp_server.dispatch_raw(
        "upsert_project", {"record": {"id": created["id"], "status": "on_hold"}}, _write()
    )
    assert updated["status"] == "on_hold"
    assert updated["client"] == "Acme Corp"  # untouched fields survive a partial patch


@pytest.mark.asyncio
async def test_get_project_not_found(erp_server: AwpMcpServer) -> None:
    with pytest.raises(NotFoundError):
        await erp_server.dispatch_raw("get_project", {"project_id": "nope"}, _read())


@pytest.mark.asyncio
async def test_query_projects_filters_by_status(erp_server: AwpMcpServer) -> None:
    await erp_server.dispatch_raw("upsert_project", {"record": {"client": "A"}}, _write())
    p2 = await erp_server.dispatch_raw(
        "upsert_project", {"record": {"client": "B", "status": "closed"}}, _write()
    )
    result = await erp_server.dispatch_raw("query_projects", {"status": "closed"}, _read())
    assert [p["id"] for p in result["projects"]] == [p2["id"]]


@pytest.mark.asyncio
async def test_upsert_milestone_requires_project_id(erp_server: AwpMcpServer) -> None:
    with pytest.raises(ValidationError):
        await erp_server.dispatch_raw(
            "upsert_milestone", {"record": {"title": "Kickoff"}}, _write()
        )


@pytest.mark.asyncio
async def test_upsert_and_query_milestones_coerces_due_date(erp_server: AwpMcpServer) -> None:
    project = await erp_server.dispatch_raw(
        "upsert_project", {"record": {"client": "Acme"}}, _write()
    )
    milestone = await erp_server.dispatch_raw(
        "upsert_milestone",
        {"record": {"project_id": project["id"], "title": "UAT", "due": "2026-08-15"}},
        _write(),
    )
    assert milestone["due"] == date(2026, 8, 15)

    result = await erp_server.dispatch_raw(
        "query_milestones", {"project_id": project["id"], "due_before": "2026-09-01"}, _read()
    )
    assert len(result["milestones"]) == 1
    empty = await erp_server.dispatch_raw(
        "query_milestones", {"project_id": project["id"], "due_before": "2026-08-01"}, _read()
    )
    assert empty["milestones"] == []


@pytest.mark.asyncio
async def test_upsert_and_query_allocations(erp_server: AwpMcpServer, emp1: str) -> None:
    project = await erp_server.dispatch_raw(
        "upsert_project", {"record": {"client": "Acme"}}, _write()
    )
    allocation = await erp_server.dispatch_raw(
        "upsert_allocation",
        {
            "record": {
                "emp_id": emp1,
                "project_id": project["id"],
                "pct": 60,
                "from_date": "2026-01-01",
            }
        },
        _write(),
    )
    assert allocation["pct"] == 60

    result = await erp_server.dispatch_raw("query_allocations", {"emp_id": emp1}, _read())
    assert len(result["allocations"]) == 1


@pytest.mark.asyncio
async def test_upsert_and_query_work_logs(erp_server: AwpMcpServer, emp1: str) -> None:
    project = await erp_server.dispatch_raw(
        "upsert_project", {"record": {"client": "Acme"}}, _write()
    )
    log = await erp_server.dispatch_raw(
        "upsert_work_log",
        {
            "record": {
                "emp_id": emp1,
                "project_id": project["id"],
                "date": "2026-07-20",
                "hours": 8,
            }
        },
        _write(),
    )
    assert log["hours"] == 8

    result = await erp_server.dispatch_raw(
        "query_work_logs",
        {"emp_id": emp1, "date_from": "2026-07-01", "date_to": "2026-07-31"},
        _read(),
    )
    assert len(result["work_logs"]) == 1
