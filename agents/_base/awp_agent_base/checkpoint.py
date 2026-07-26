"""Minimal crash-resume checkpoint store — doc 11 §2's "PostgresSaver (table
agent_checkpoints) keyed by task_id" requirement, but NOT LangGraph's native
`BaseCheckpointSaver` protocol: that protocol owns its own migration-managed
tables (`checkpoints`, `checkpoint_writes`, `checkpoint_blobs`, ...), which
don't match `agent_checkpoints`' simpler one-row-per-task-id shape (doc 09
§1 / migration `0008_platform_dashboard`). See DEVIATIONS.md #9.

Instead, `AgentApp` explicitly saves the whole `AgentState` (pickled) after
every graph run and loads it back — instead of starting `graph.ainvoke` from
scratch — when a bus message for a `task_id` that already has a row shows up
(the at-least-once bus redelivery-on-crash case doc 00 §5 / doc 02 §8
assume). This is coarser than LangGraph's per-superstep checkpointing (no
mid-run resume between individual node executions), but every node here is
"≤ 1 LLM call" (doc 11 §2) and idempotent-safe via the bus's own dedupe, so
re-running a whole task from its last-saved state on crash-resume is
sufficient for the doc's guarantee, not a functional gap.
"""

from __future__ import annotations

import pickle
from typing import TYPE_CHECKING
from uuid import UUID

from awp_mcp_base.uow import UnitOfWork
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from awp_agent_base.tables import agent_checkpoints

if TYPE_CHECKING:
    from awp_agent_base.state import AgentState


class CheckpointStore:
    def __init__(self, uow: UnitOfWork, *, dialect: str = "postgresql") -> None:
        # `dialect` picks the upsert dialect ("postgresql" prod, "sqlite"
        # tests) — passed explicitly by the caller (who built the engine)
        # rather than introspected from the session, since `AsyncSession`
        # doesn't reliably expose a sync `.bind` before a connection is
        # checked out.
        self._sessions = uow
        self._insert_fn = pg_insert if dialect == "postgresql" else sqlite_insert

    async def save(self, task_id: UUID, graph_name: str, state: AgentState) -> None:
        blob = pickle.dumps(state)
        async with self._sessions() as session:
            await self._upsert(session, task_id, graph_name, blob)

    async def _upsert(
        self, session: AsyncSession, task_id: UUID, graph_name: str, blob: bytes
    ) -> None:
        stmt = self._insert_fn(agent_checkpoints).values(
            task_id=str(task_id), graph=graph_name, state=blob
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[agent_checkpoints.c.task_id],
            set_={"graph": graph_name, "state": blob},
        )
        await session.execute(stmt)

    async def load(self, task_id: UUID, graph_name: str) -> AgentState | None:
        async with self._sessions() as session:
            row = (
                await session.execute(
                    select(agent_checkpoints.c.state, agent_checkpoints.c.graph).where(
                        agent_checkpoints.c.task_id == str(task_id)
                    )
                )
            ).first()
            if row is None:
                return None
            blob, saved_graph = row
            if saved_graph != graph_name:
                # A task_id should never be replayed against a different graph;
                # treat as "no checkpoint" rather than deserializing a
                # foreign-shaped state and crashing the node.
                return None
            result: AgentState = pickle.loads(blob)  # noqa: S301 - our own trusted writes
            return result

    async def clear(self, task_id: UUID) -> None:
        async with self._sessions() as session:
            await session.execute(
                delete(agent_checkpoints).where(agent_checkpoints.c.task_id == str(task_id))
            )
