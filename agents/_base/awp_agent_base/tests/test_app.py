from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from awp_shared.metrics import REGISTRY
from awp_shared.schemas import AgentId, TaskEnvelope, TaskResult, TaskStatus
from langgraph.graph import END, StateGraph

from awp_agent_base import nodes
from awp_agent_base.app import AgentApp
from awp_agent_base.checkpoint import CheckpointStore
from awp_agent_base.state import AgentState


def _task(**overrides: Any) -> TaskEnvelope:
    defaults: dict[str, Any] = dict(
        from_agent=AgentId.ORCH0, to_agent=AgentId.SUP1, intent="create_ticket"
    )
    defaults.update(overrides)
    return TaskEnvelope(**defaults)


def _counter(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


class _FakeGraph:
    def __init__(self, fn: Callable[[AgentState], Awaitable[AgentState]]) -> None:
        self._fn = fn

    async def ainvoke(self, state: AgentState, **kwargs: Any) -> AgentState:
        return await self._fn(state)


async def test_handle_fresh_task_returns_result_and_checkpoints(
    checkpoints: CheckpointStore,
) -> None:
    async def fn(state: AgentState) -> AgentState:
        state["result"] = TaskResult(
            task_id=state["task"].task_id, status=TaskStatus.DONE, summary="ok"
        )
        return state

    app = AgentApp(AgentId.SUP1, _FakeGraph(fn), checkpoints, graph_name="sup1")
    env = _task()

    result = await app.handle(env)

    assert result.status == TaskStatus.DONE
    saved = await checkpoints.load(env.task_id, "sup1")
    assert saved is not None
    saved_result = saved["result"]
    assert saved_result is not None
    assert saved_result.summary == "ok"


async def test_handle_resumes_from_checkpoint(checkpoints: CheckpointStore) -> None:
    env = _task()
    seen_scratch: dict[str, Any] = {}

    async def fn(state: AgentState) -> AgentState:
        seen_scratch.update(state["scratch"])
        state["result"] = TaskResult(task_id=env.task_id, status=TaskStatus.DONE, summary="ok")
        return state

    app = AgentApp(AgentId.SUP1, _FakeGraph(fn), checkpoints, graph_name="sup1")
    await checkpoints.save(
        env.task_id,
        "sup1",
        {"task": env, "steps": [], "scratch": {"resumed": True}, "result": None, "tool_budget": 5},
    )

    await app.handle(env)

    assert seen_scratch == {"resumed": True}


async def test_handle_graph_crash_saves_partial_state_and_returns_failed(
    checkpoints: CheckpointStore,
) -> None:
    async def fn(state: AgentState) -> AgentState:
        state["scratch"]["got_here"] = True
        raise RuntimeError("boom")

    app = AgentApp(AgentId.SUP1, _FakeGraph(fn), checkpoints, graph_name="sup1")
    env = _task()

    result = await app.handle(env)

    assert result.status == TaskStatus.FAILED
    assert "boom" in result.summary
    saved = await checkpoints.load(env.task_id, "sup1")
    assert saved is not None
    assert saved["scratch"]["got_here"] is True


async def test_handle_graph_without_result_returns_failed(checkpoints: CheckpointStore) -> None:
    async def fn(state: AgentState) -> AgentState:
        return state  # never sets state["result"]

    app = AgentApp(AgentId.SUP1, _FakeGraph(fn), checkpoints, graph_name="sup1")
    result = await app.handle(_task())

    assert result.status == TaskStatus.FAILED
    assert "without producing a result" in result.summary


async def test_on_result_hook_called_on_success(checkpoints: CheckpointStore) -> None:
    async def fn(state: AgentState) -> AgentState:
        state["result"] = TaskResult(
            task_id=state["task"].task_id, status=TaskStatus.DONE, summary="ok"
        )
        return state

    seen: list[tuple[TaskEnvelope, TaskResult]] = []

    async def on_result(env: TaskEnvelope, result: TaskResult) -> None:
        seen.append((env, result))

    app = AgentApp(
        AgentId.SUP1, _FakeGraph(fn), checkpoints, graph_name="sup1", on_result=on_result
    )
    env = _task()
    result = await app.handle(env)

    assert len(seen) == 1
    assert seen[0][0].task_id == env.task_id
    assert seen[0][1].status == TaskStatus.DONE
    assert result.status == TaskStatus.DONE


async def test_on_result_hook_called_on_graph_crash(checkpoints: CheckpointStore) -> None:
    """The exact gap this hook closes: a graph-level crash (e.g. all LLM
    retries exhausted) still returns a FAILED TaskResult from `handle`, but
    no graph node ever runs to mirror that onto the caller's own durable
    state — `on_result` is the only thing that can (Sprint 3: reproduced
    against a real ORCH-0 task that stayed "pending" forever)."""

    async def fn(state: AgentState) -> AgentState:
        raise RuntimeError("llm unreachable after retries")

    seen: list[TaskResult] = []

    async def on_result(env: TaskEnvelope, result: TaskResult) -> None:
        seen.append(result)

    app = AgentApp(
        AgentId.SUP1, _FakeGraph(fn), checkpoints, graph_name="sup1", on_result=on_result
    )
    result = await app.handle(_task())

    assert result.status == TaskStatus.FAILED
    assert len(seen) == 1
    assert seen[0].status == TaskStatus.FAILED


async def test_on_result_hook_failure_does_not_propagate(checkpoints: CheckpointStore) -> None:
    async def fn(state: AgentState) -> AgentState:
        state["result"] = TaskResult(
            task_id=state["task"].task_id, status=TaskStatus.DONE, summary="ok"
        )
        return state

    async def broken_on_result(env: TaskEnvelope, result: TaskResult) -> None:
        raise RuntimeError("erp unreachable")

    app = AgentApp(
        AgentId.SUP1, _FakeGraph(fn), checkpoints, graph_name="sup1", on_result=broken_on_result
    )
    result = await app.handle(_task())

    assert result.status == TaskStatus.DONE  # hook failure doesn't turn success into failure


async def test_real_langgraph_wiring_validate_then_summarize(checkpoints: CheckpointStore) -> None:
    """Integration check that this module's nodes actually compose into a
    real `langgraph.graph.StateGraph`, not just satisfy the `CompiledGraph`
    Protocol shape."""

    class _FakeLLM:
        async def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> Any:
            from awp_shared.llm import LLMResponse

            return LLMResponse(content="Ticket created.")

    graph = StateGraph(AgentState)
    graph.add_node("validate", nodes.make_validate_payload_node(None))
    graph.add_node("summarize", nodes.make_summarize_node(_FakeLLM()))
    graph.set_entry_point("validate")
    graph.add_edge("validate", "summarize")
    graph.add_edge("summarize", END)
    compiled = graph.compile()

    app = AgentApp(AgentId.SUP1, compiled, checkpoints, graph_name="sup1")
    result = await app.handle(_task())

    assert result.status == TaskStatus.DONE
    assert result.summary == "Ticket created."


async def test_handle_records_task_metrics_on_success(checkpoints: CheckpointStore) -> None:
    intent = "test_metrics_success"

    async def fn(state: AgentState) -> AgentState:
        state["result"] = TaskResult(
            task_id=state["task"].task_id, status=TaskStatus.DONE, summary="ok"
        )
        return state

    app = AgentApp(AgentId.SUP1, _FakeGraph(fn), checkpoints, graph_name="sup1")
    labels = {"agent": AgentId.SUP1.value, "intent": intent, "status": "done"}
    before_calls = _counter("awp_agent_tasks_total", **labels)
    before_duration = _counter(
        "awp_agent_task_duration_seconds_count", agent=AgentId.SUP1.value, intent=intent
    )

    await app.handle(_task(intent=intent))

    assert _counter("awp_agent_tasks_total", **labels) == before_calls + 1
    assert (
        _counter("awp_agent_task_duration_seconds_count", agent=AgentId.SUP1.value, intent=intent)
        == before_duration + 1
    )


async def test_handle_records_task_metrics_on_crash(checkpoints: CheckpointStore) -> None:
    intent = "test_metrics_crash"

    async def fn(state: AgentState) -> AgentState:
        raise RuntimeError("boom")

    app = AgentApp(AgentId.SUP1, _FakeGraph(fn), checkpoints, graph_name="sup1")
    labels = {"agent": AgentId.SUP1.value, "intent": intent, "status": "failed"}
    before = _counter("awp_agent_tasks_total", **labels)

    await app.handle(_task(intent=intent))

    assert _counter("awp_agent_tasks_total", **labels) == before + 1
