"""Projects/work tools — doc 08 §1's tool list extended for doc 05 (OPS-1)
Sprint 9. Deliberately dumb CRUD/query only, same split as every other
mcp-erp aggregate: business logic (utilization math, milestone-at-risk
detection, allocation conflict checks) lives in `agents/ops1/*.py`'s pure
functions, not here — this module never decides anything, it just persists
and returns what it's asked to.
"""

from __future__ import annotations

import uuid
from typing import Any

from awp_mcp_base.ctx import Ctx
from awp_mcp_base.server import AwpMcpServer
from awp_mcp_base.uow import UnitOfWork
from awp_shared.errors import NotFoundError, ValidationError

from awp_mcp_erp.repos.project import AllocationRepo, MilestoneRepo, ProjectRepo, WorkLogRepo
from awp_mcp_erp.wire import parse_date


def _coerce_dates(record: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    coerced = dict(record)
    for field in fields:
        if field in coerced:
            coerced[field] = parse_date(coerced[field])
    return coerced


def register_project_tools(server: AwpMcpServer, uow: UnitOfWork) -> None:
    @server.tool()
    async def get_project(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        project_id = payload.get("project_id")
        if not project_id:
            raise ValidationError("get_project requires 'project_id'")
        async with uow() as session:
            row = await ProjectRepo(session).get(project_id)
        if row is None:
            raise NotFoundError(f"no such project: {project_id}")
        return row

    @server.tool()
    async def query_projects(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        async with uow() as session:
            rows = await ProjectRepo(session).query(
                status=payload.get("status"),
                limit=payload.get("page_size", 50),
                offset=payload.get("page", 0) * payload.get("page_size", 50),
            )
        return {"projects": rows}

    @server.tool()
    async def upsert_project(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        record = payload.get("record")
        if not record:
            raise ValidationError("upsert_project requires 'record'")
        async with uow() as session:
            repo = ProjectRepo(session)
            project_id = record.get("id")
            if project_id:
                existing = await repo.get(project_id)
                if existing is None:
                    raise NotFoundError(f"no such project: {project_id}")
                await repo.update(project_id, {k: v for k, v in record.items() if k != "id"})
                updated = await repo.get(project_id)
                assert updated is not None
                return updated
            new_id = str(uuid.uuid4())
            await repo.insert({**record, "id": new_id})
            created = await repo.get(new_id)
        assert created is not None
        return created

    @server.tool()
    async def query_milestones(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        async with uow() as session:
            rows = await MilestoneRepo(session).query(
                project_id=payload.get("project_id"),
                due_before=parse_date(payload.get("due_before")),
                status=payload.get("status"),
            )
        return {"milestones": rows}

    @server.tool()
    async def upsert_milestone(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        record = payload.get("record")
        if not record or not record.get("project_id"):
            raise ValidationError("upsert_milestone requires 'record.project_id'")
        record = _coerce_dates(record, ("due",))
        async with uow() as session:
            repo = MilestoneRepo(session)
            milestone_id = record.get("id")
            if milestone_id:
                existing = await repo.get(milestone_id)
                if existing is None:
                    raise NotFoundError(f"no such milestone: {milestone_id}")
                await repo.update(milestone_id, {k: v for k, v in record.items() if k != "id"})
                updated = await repo.get(milestone_id)
                assert updated is not None
                return updated
            new_id = str(uuid.uuid4())
            await repo.insert({**record, "id": new_id})
            created = await repo.get(new_id)
        assert created is not None
        return created

    @server.tool()
    async def query_allocations(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        async with uow() as session:
            rows = await AllocationRepo(session).query(
                emp_id=payload.get("emp_id"),
                project_id=payload.get("project_id"),
                active_on=parse_date(payload.get("active_on")),
            )
        return {"allocations": rows}

    @server.tool()
    async def upsert_allocation(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        # doc 05 §2.1: the availability/skill-match check, conflict
        # detection, and `allocation_change` approval gate are all
        # OPS-1a's own workflow, resolved *before* this tool is ever
        # called (same "agent decides when to gate, tool just persists"
        # pattern as HR-1's shortlist_role/prepare_negotiation) — this
        # tool never checks an approval token itself.
        record = payload.get("record")
        if not record or not record.get("emp_id") or not record.get("project_id"):
            raise ValidationError(
                "upsert_allocation requires 'record.emp_id' and 'record.project_id'"
            )
        record = _coerce_dates(record, ("from_date", "to_date"))
        async with uow() as session:
            repo = AllocationRepo(session)
            allocation_id = record.get("id")
            if allocation_id:
                existing = await repo.get(allocation_id)
                if existing is None:
                    raise NotFoundError(f"no such allocation: {allocation_id}")
                await repo.update(allocation_id, {k: v for k, v in record.items() if k != "id"})
                updated = await repo.get(allocation_id)
                assert updated is not None
                return updated
            new_id = str(uuid.uuid4())
            await repo.insert({**record, "id": new_id})
            created = await repo.get(new_id)
        assert created is not None
        return created

    @server.tool()
    async def query_work_logs(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        async with uow() as session:
            rows = await WorkLogRepo(session).query(
                emp_id=payload.get("emp_id"),
                project_id=payload.get("project_id"),
                date_from=parse_date(payload.get("date_from")),
                date_to=parse_date(payload.get("date_to")),
            )
        return {"work_logs": rows}

    @server.tool()
    async def upsert_work_log(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        record = payload.get("record")
        if not record or not record.get("emp_id") or not record.get("project_id"):
            raise ValidationError(
                "upsert_work_log requires 'record.emp_id' and 'record.project_id'"
            )
        record = _coerce_dates(record, ("date",))
        async with uow() as session:
            repo = WorkLogRepo(session)
            log_id = record.get("id")
            if log_id:
                existing = await repo.get(log_id)
                if existing is None:
                    raise NotFoundError(f"no such work_log: {log_id}")
                await repo.update(log_id, {k: v for k, v in record.items() if k != "id"})
                updated = await repo.get(log_id)
                assert updated is not None
                return updated
            new_id = str(uuid.uuid4())
            await repo.insert({**record, "id": new_id})
            created = await repo.get(new_id)
        assert created is not None
        return created
