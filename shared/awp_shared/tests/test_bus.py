import asyncio
from typing import Any, cast

import pytest
from fakeredis.aioredis import FakeRedis
from redis.exceptions import TimeoutError as RedisTimeoutError

from awp_shared.bus import DLQ_STREAM, MAX_ATTEMPTS, TaskBus, make_redis, stream_name
from awp_shared.schemas import AgentId, TaskEnvelope, TaskResult, TaskStatus


def _redis() -> FakeRedis:
    return FakeRedis(decode_responses=True)


def _envelope(**overrides: object) -> TaskEnvelope:
    defaults: dict[str, object] = dict(
        from_agent=AgentId.ORCH0,
        to_agent=AgentId.FIN1,
        intent="run_payroll",
        payload={"month": "2026-07"},
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
    raw = await redis.xreadgroup("workers", "test-consumer", {stream: ">"}, count=10, block=None)
    # redis-py's stub return type is a broad union; see bus.py's `cast` for the same reason.
    resp = cast(list[tuple[str, list[tuple[str, dict[str, str]]]]], raw)
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


def test_make_redis_disables_client_side_socket_timeout() -> None:
    # Reproduced against real Redis (Sprint 3): redis-py's default
    # `socket_timeout` races `XREADGROUP ... BLOCK <ms>`'s server-side
    # timeout and raises a spurious `redis.exceptions.TimeoutError` on
    # every "no new messages" poll — crash-looping any long-running
    # `TaskBus.consume` worker. `fakeredis` doesn't model this, so this
    # only checks the client is constructed correctly, not the symptom.
    redis = make_redis("redis://localhost:6379/0")
    assert redis.connection_pool.connection_kwargs["socket_timeout"] is None


@pytest.mark.asyncio
async def test_consume_survives_transient_redis_timeout_and_keeps_polling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Isolates the resilience property itself (doesn't crash, keeps
    # retrying) from fakeredis's blocking-read timing semantics: every
    # `xreadgroup` call raises, deterministically, and the loop must
    # survive each one rather than propagating and killing the worker.
    monkeypatch.setattr("awp_shared.bus.RECONNECT_BACKOFF_S", 0.01)
    redis = _redis()
    bus = TaskBus(redis)

    call_count = 0
    stop = asyncio.Event()

    async def always_times_out(*args: Any, **kwargs: Any) -> Any:
        nonlocal call_count
        call_count += 1
        if call_count >= 3:
            stop.set()
        raise RedisTimeoutError("Timeout reading from redis:6379")

    redis.xreadgroup = always_times_out  # type: ignore[method-assign]

    async def handler(e: TaskEnvelope) -> TaskResult:
        return TaskResult(task_id=e.task_id, status=TaskStatus.DONE, summary="ok")

    await asyncio.wait_for(
        bus.consume(AgentId.FIN1, handler, consumer_name="c1", block_ms=100, stop=stop),
        timeout=5,
    )

    assert call_count >= 3


@pytest.mark.asyncio
async def test_heartbeat_and_is_alive() -> None:
    redis = _redis()
    bus = TaskBus(redis)
    assert await bus.is_alive(AgentId.FIN1) is False
    await bus.heartbeat(AgentId.FIN1)
    assert await bus.is_alive(AgentId.FIN1) is True


@pytest.mark.asyncio
async def test_kill_switch_round_trips() -> None:
    redis = _redis()
    bus = TaskBus(redis)
    assert await bus.is_killed(AgentId.HR1) is False

    await bus.set_kill_switch(AgentId.HR1, on=True)
    assert await bus.is_killed(AgentId.HR1) is True
    # Scoped per-agent — turning HR-1 on must not affect a different agent.
    assert await bus.is_killed(AgentId.FIN1) is False

    await bus.set_kill_switch(AgentId.HR1, on=False)
    assert await bus.is_killed(AgentId.HR1) is False


@pytest.mark.asyncio
async def test_consume_parks_while_killed_then_delivers_once_cleared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # doc 09 §4.5 "queue-park mode" — the defining property is that a
    # killed consumer never even issues XREADGROUP, so a dispatched task
    # sits untouched (not just unacked) until the switch clears, and is
    # then delivered normally with no special resume logic.
    monkeypatch.setattr("awp_shared.bus.KILL_SWITCH_POLL_S", 0.01)
    redis = _redis()
    bus = TaskBus(redis)
    env = _envelope(to_agent=AgentId.HR1, intent="prepare_negotiation")
    await bus.dispatch(env)
    await bus.set_kill_switch(AgentId.HR1, on=True)

    poll_count_while_killed = 0
    stop = asyncio.Event()

    async def handler(_e: TaskEnvelope) -> TaskResult:
        stop.set()  # let the loop exit right after the one real delivery
        return TaskResult(task_id=_e.task_id, status=TaskStatus.DONE, summary="ok")

    async def flip_off_after_a_few_polls() -> None:
        nonlocal poll_count_while_killed
        # Several real poll intervals elapse with the switch on before we
        # clear it — proves parking isn't a one-shot check at loop entry.
        for _ in range(5):
            assert await bus.is_killed(AgentId.HR1) is True
            poll_count_while_killed += 1
            await asyncio.sleep(0.015)
        await bus.set_kill_switch(AgentId.HR1, on=False)

    watcher = asyncio.create_task(flip_off_after_a_few_polls())
    await asyncio.wait_for(
        bus.consume(AgentId.HR1, handler, consumer_name="c1", block_ms=50, stop=stop),
        timeout=5,
    )
    await watcher

    assert poll_count_while_killed == 5
    assert stop.is_set()  # only true if the handler actually ran, post-unpark
