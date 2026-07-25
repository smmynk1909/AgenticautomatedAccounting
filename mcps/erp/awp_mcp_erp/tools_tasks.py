"""Task-bus state tools — doc 08 §1 "Tasks (bus state)".

`orchestrator_tasks` rows are the durable, queryable mirror of what's on the
Redis Streams task bus (`shared/awp_shared/bus.py`) — ORCH-0 (Sprint 3)
writes one here on every `TaskBus.dispatch`, and these tools are how status
gets read back / updated as agents work through it.
"""

from __future__ import annotations

from typing import Any

from awp_mcp_base.ctx import Ctx
from awp_mcp_base.server import AwpMcpServer
from awp_mcp_base.uow import UnitOfWork
from awp_shared.errors import NotFoundError, ValidationError
from awp_shared.schemas import TaskEnvelope
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select

from awp_mcp_erp.repos.task import OrchestratorTaskRepo


def register_task_tools(server: AwpMcpServer, uow: UnitOfWork) -> None:
    @server.tool()
    async def dispatch_task(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        # ORCH-0-only in practice (scope erp.tasks.dispatch granted to no
        # other agent's config.yaml, Sprint 3) — validated as a real
        # TaskEnvelope, not a bare dict, so a malformed plan can't get this far.
        try:
            envelope = TaskEnvelope.model_validate(payload.get("envelope", payload))
        except PydanticValidationError as exc:
            raise ValidationError(f"invalid task envelope: {exc}") from exc

        async with uow() as session:
            await OrchestratorTaskRepo(session).insert(
                {
                    "task_id": str(envelope.task_id),
                    "parent": str(envelope.parent_task_id) if envelope.parent_task_id else None,
                    "agent": envelope.to_agent.value,
                    "intent": envelope.intent,
                    "payload": envelope.payload,
                    "status": "pending",
                    "priority": envelope.priority.value,
                    "sla_deadline": envelope.sla_deadline,
                    "result": None,
                    "trace_id": str(envelope.trace_id),
                }
            )
        return {"task_id": str(envelope.task_id)}

    @server.tool()
    async def claim_task(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        agent_id = payload.get("agent_id")
        if not agent_id:
            raise ValidationError("claim_task requires 'agent_id'")

        async with uow() as session:
            repo = OrchestratorTaskRepo(session)
            # NOTE: plain SELECT + UPDATE, not `SELECT ... FOR UPDATE SKIP
            # LOCKED` — fine for one consumer per agent (today's topology);
            # revisit if an agent ever runs multiple concurrent replicas
            # claiming from this table directly (the Redis Streams consumer
            # group already handles that race for the bus itself).
            stmt = (
                select(repo.table)
                .where(repo.table.c.agent == agent_id, repo.table.c.status == "pending")
                .order_by(repo.table.c.created_at)
                .limit(1)
            )
            row = (await session.execute(stmt)).mappings().first()
            if row is None:
                return {"task": None}
            await repo.update(row["task_id"], {"status": "in_progress"})
            claimed = await repo.get(row["task_id"])
        return {"task": claimed}

    @server.tool()
    async def update_task(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        task_id = payload.get("task_id")
        status = payload.get("status")
        result = payload.get("result")
        if not task_id or not status:
            raise ValidationError("update_task requires 'task_id' and 'status'")

        async with uow() as session:
            repo = OrchestratorTaskRepo(session)
            task = await repo.get(task_id)
            if task is None:
                raise NotFoundError(f"no such task: {task_id}")
            patch: dict[str, Any] = {"status": status}
            if result is not None:
                patch["result"] = result
            await repo.update(task_id, patch)
            updated = await repo.get(task_id)
        assert updated is not None
        return updated

    @server.tool()
    async def get_task_status(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        task_id = payload.get("task_id")
        parent = payload.get("parent")
        if not task_id and not parent:
            raise ValidationError("get_task_status requires 'task_id' or 'parent'")

        async with uow() as session:
            repo = OrchestratorTaskRepo(session)
            if task_id:
                task = await repo.get(task_id)
                if task is None:
                    raise NotFoundError(f"no such task: {task_id}")
                children = await repo.children(task_id)
                return {"task": task, "children": children}
            assert parent is not None  # the not-task_id-and-not-parent case already raised above
            children = await repo.children(parent)
            return {"children": children}
