"""`AgentApp` — common runtime: bus consumer + LangGraph executor +
checkpointing (doc 11 §2).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

import structlog
from awp_shared.schemas import AgentId, TaskEnvelope, TaskResult, TaskStatus

from awp_agent_base.checkpoint import CheckpointStore
from awp_agent_base.state import new_state

if TYPE_CHECKING:
    from awp_shared.bus import TaskBus

OnResult = Callable[[TaskEnvelope, TaskResult], Awaitable[None]]

logger = structlog.get_logger(__name__)

# `graph`'s real type is `langgraph.graph.state.CompiledStateGraph[AgentState,
# ...]`, whose `ainvoke` carries LangGraph's own generic `input`/config/
# stream_mode signature — not worth fighting via a structural Protocol (it
# doesn't cleanly unify with a plain test fake's `ainvoke(state) -> state`
# either). Left as `Any`; `AgentApp` is the one place that treats the return
# value as an `AgentState`.
CompiledGraph = Any


class AgentApp:
    """`agent_id`: which bus stream this app consumes (`AGENT_STREAM_SUFFIX` in
    `awp_shared.bus`). `graph_name`: the checkpoint row's `graph` column —
    lets one Postgres table safely hold checkpoints for every agent."""

    def __init__(
        self,
        agent_id: AgentId,
        graph: CompiledGraph,
        checkpoints: CheckpointStore,
        *,
        graph_name: str | None = None,
        on_result: OnResult | None = None,
    ) -> None:
        self.agent_id = agent_id
        self._graph = graph
        self._checkpoints = checkpoints
        self._graph_name = graph_name or agent_id.value
        # Called with every `TaskResult` `handle()` produces — success, a
        # graph-level crash, or a missing-result bug — so callers can mirror
        # the outcome onto their own durable state (e.g. ORCH-0/SUP-1 call
        # `erp.update_task`) uniformly, including the crash/missing-result
        # paths a graph's own nodes can never reach to update themselves
        # (Sprint 3: reproduced — an ORCH-0 task whose LLM call exhausted
        # all retries stayed "pending" in `orchestrator_tasks` forever, even
        # though the bus correctly ack'd it as handled). Best-effort: a
        # failing hook is logged, never re-raised — it must not turn a
        # successfully-handled task into a bus retry/DLQ entry.
        self._on_result = on_result

    async def handle(self, env: TaskEnvelope) -> TaskResult:
        """Entry per task (doc 11 §2). Resumes from a saved checkpoint if one
        exists for this `task_id` (crash-resume on bus redelivery), else
        starts a fresh `AgentState`."""
        state = await self._checkpoints.load(env.task_id, self._graph_name)
        if state is None:
            state = new_state(env)
        else:
            state["task"] = env  # refresh envelope (e.g. re-dispatch with updated payload)

        try:
            final_state = await self._graph.ainvoke(state)
        except Exception as exc:  # noqa: BLE001 - a node crash must still checkpoint + surface
            logger.error("agent.graph_crashed", agent=self.agent_id.value, error=str(exc))
            await self._checkpoints.save(env.task_id, self._graph_name, state)
            crash_result = TaskResult(
                task_id=env.task_id,
                status=TaskStatus.FAILED,
                summary=f"agent crashed: {exc}",
            )
            await self._call_on_result(env, crash_result)
            return crash_result

        await self._checkpoints.save(env.task_id, self._graph_name, final_state)

        result: TaskResult | None = final_state.get("result")
        if result is None:
            # Graph ended without reaching n_summarize/n_fail — a graph.py bug,
            # not a task outcome; surface it as FAILED rather than silently
            # reporting DONE.
            result = TaskResult(
                task_id=env.task_id,
                status=TaskStatus.FAILED,
                summary="agent graph ended without producing a result",
            )
        await self._call_on_result(env, result)
        return result

    async def _call_on_result(self, env: TaskEnvelope, result: TaskResult) -> None:
        if self._on_result is None:
            return
        try:
            await self._on_result(env, result)
        except Exception as exc:  # noqa: BLE001 - best-effort mirror, never fails the task
            logger.warning(
                "agent.on_result_hook_failed", agent=self.agent_id.value, error=str(exc)
            )

    async def run_forever(
        self, bus: TaskBus, *, consumer_name: str = "worker-1", stop: asyncio.Event | None = None
    ) -> None:
        await bus.consume(self.agent_id, self.handle, consumer_name=consumer_name, stop=stop)
