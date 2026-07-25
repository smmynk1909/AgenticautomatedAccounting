import pytest
from fakeredis.aioredis import FakeRedis

from awp_shared.bus import DLQ_STREAM, MAX_ATTEMPTS, TaskBus, stream_name
from awp_shared.schemas import AgentId, TaskEnvelope, TaskResult, TaskStatus


def _redis() -> FakeRedis:
    return FakeRedis(decode_responses=True)


def _envelope(**overrides: object) -> TaskEnvelope:
    defaults: dict[str, object] = dict(
        from_agent=AgentId.ORCH0, to_agent=AgentId.FIN1, intent="run_payroll", payload={"month": "2026-07"}
    )
    defaults.update(overrides)
    return TaskEnvelope(**defaults)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_dispatch_adds_to_the_right_stream() -> None:
    redis = _redis()
    bus = TaskBus(redis)
    env = _envelope()
    await bus.dispatch(env)
    length = await redis.xlen(stream_name(AgentId.FIN1))
    assert length == 1


@pytest.mark.asyncio
async def test_consume_calls_handler_once_and_acks() -> None:
    redis = _redis()
    bus = TaskBus(redis)
    env = _envelope()
    await bus.dispatch(env)

    calls: list[TaskEnvelope] = []

    async def handler(e: TaskEnvelope) -> TaskResult:
        calls.append(e)
        return TaskResult(task_id=e.task_id, status=TaskStatus.DONE, summary="ok")

    # one non-blocking pass: read is available immediately, block=0 avoids test hangs
    stream = stream_name(AgentId.FIN1)
    await bus._ensure_group(stream)
    resp = await redis.xreadgroup("workers", "test-consumer", {stream: ">"}, count=10, block=None)
    for _s, messages in resp:
        for msg_id, fields in messages:
            await bus._handle_one(stream, msg_id, fields, handler)

    assert len(calls) == 1
    assert calls[0].task_id == env.task_id

    pending = await redis.xpending(stream, "workers")
    assert pending["pending"] == 0


@pytest.mark.asyncio
async def test_duplicate_delivery_is_deduped_and_handler_runs_once() -> None:
    redis = _redis()
    bus = TaskBus(redis)
    env = _envelope()
    stream = stream_name(AgentId.FIN1)
    await bus._ensure_group(stream)

    calls = 0

    async def handler(_e: TaskEnvelope) -> TaskResult:
        nonlocal calls
        calls += 1
        return TaskResult(task_id=_e.task_id, status=TaskStatus.DONE, summary="ok")

    fields = {"envelope": env.model_dump_json(), "attempt": "0"}
    await bus._handle_one(stream, "1-0", fields, handler)
    await bus._handle_one(stream, "2-0", fields, handler)  # simulated redelivery

    assert calls == 1


@pytest.mark.asyncio
async def test_failed_handler_at_max_attempts_goes_to_dlq() -> None:
    redis = _redis()
    bus = TaskBus(redis)
    env = _envelope()
    stream = stream_name(AgentId.FIN1)
    await bus._ensure_group(stream)

    async def failing_handler(_e: TaskEnvelope) -> TaskResult:
        raise RuntimeError("boom")

    fields = {"envelope": env.model_dump_json(), "attempt": str(MAX_ATTEMPTS - 1)}
    await bus._handle_one(stream, "1-0", fields, failing_handler)

    dlq_len = await redis.xlen(DLQ_STREAM)
    assert dlq_len == 1


@pytest.mark.asyncio
async def test_heartbeat_and_is_alive() -> None:
    redis = _redis()
    bus = TaskBus(redis)
    assert await bus.is_alive(AgentId.FIN1) is False
    await bus.heartbeat(AgentId.FIN1)
    assert await bus.is_alive(AgentId.FIN1) is True
