"""Redis Streams task bus — doc 00 §5A, doc 10 AD-05, doc 11 §1.3.

At-least-once delivery; consumers must be idempotent. `TaskBus` enforces that
by deduping on `idempotency_key` before calling the handler. Delivery
failures retry with backoff (1m/5m/25m per doc 00 §5); after `MAX_ATTEMPTS`
the envelope moves to `tasks.dlq` and an audit event fires — SUP-1 (Sprint 3)
subscribes to the DLQ to auto-file a ticket, per doc 00 §5.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any, cast

import structlog
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import ResponseError
from redis.exceptions import TimeoutError as RedisTimeoutError

from awp_shared.schemas import AgentId, TaskEnvelope, TaskResult

logger = structlog.get_logger(__name__)

DEDUPE_TTL_S = 7 * 24 * 3600
RETRY_DELAYS_S = (60, 300, 1500)  # 1m, 5m, 25m
MAX_ATTEMPTS = 3
DLQ_STREAM = "tasks.dlq"
CONSUMER_GROUP = "workers"
RECONNECT_BACKOFF_S = 2.0
KILL_SWITCH_PREFIX = "killswitch:"
KILL_SWITCH_POLL_S = 2.0

# doc 00 §5 examples use short department names, not the AgentId enum values.
AGENT_STREAM_SUFFIX: dict[AgentId, str] = {
    AgentId.ORCH0: "orchestrator",
    AgentId.ADM1: "admin",
    AgentId.HR1: "hr",
    AgentId.OPS1: "operations",
    AgentId.FIN1: "finance",
    AgentId.SUP1: "support",
}


def make_redis(url: str) -> Redis:
    """Every TaskBus/dedupe/idempotency helper assumes str, not bytes, back.

    `socket_timeout=None`: `TaskBus.consume`'s `XREADGROUP ... BLOCK
    <block_ms>` relies on the *server* timing out the blocking read after
    `block_ms`, not the client socket. redis-py's own default client-side
    `socket_timeout` is short enough to race that server-side timeout —
    confirmed by reproduction, not just docs — so a blocking read with no
    new messages spuriously raises `redis.exceptions.TimeoutError` instead
    of returning an empty response, which `TaskBus.consume`'s loop doesn't
    catch and crashes the whole worker process (doc 00 §5 assumes at-least-
    once delivery from a *running* consumer, not a crash-looping one).
    `fakeredis` (every unit test) doesn't model real socket timeouts, so
    this was never caught until a real bus consumer — ORCH-0, SUP-1 — ran
    against real Redis for the first time (Sprint 3).
    """
    return Redis.from_url(url, decode_responses=True, socket_timeout=None)


def stream_name(agent: AgentId) -> str:
    suffix = AGENT_STREAM_SUFFIX.get(agent)
    if suffix is None:
        raise ValueError(f"agent {agent} has no task stream (HUMAN/SCHEDULER never consume)")
    return f"tasks.{suffix}"


class TaskBus:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def _ensure_group(self, stream: str) -> None:
        try:
            await self._redis.xgroup_create(stream, CONSUMER_GROUP, id="0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def dispatch(self, env: TaskEnvelope) -> None:
        stream = stream_name(env.to_agent)
        await self._ensure_group(stream)
        await self._redis.xadd(stream, {"envelope": env.model_dump_json(), "attempt": "0"})
        logger.info(
            "bus.dispatch", task_id=str(env.task_id), intent=env.intent, to_agent=env.to_agent.value
        )

    async def consume(
        self,
        agent: AgentId,
        handler: Callable[[TaskEnvelope], Awaitable[TaskResult]],
        *,
        consumer_name: str = "worker-1",
        block_ms: int = 5000,
        stop: asyncio.Event | None = None,
    ) -> None:
        """Runs until `stop` is set. One iteration = one XREADGROUP batch."""
        stream = stream_name(agent)
        await self._ensure_group(stream)
        while stop is None or not stop.is_set():
            if await self.is_killed(agent):
                # doc 09 §4.5 "kill-switch env flag per agent (queue-park
                # mode)" — never actually implemented before Sprint 11/12's
                # go-live hardening (doc 12 §6 exit checklist: "kill-switch
                # drill executed"). Deliberately does NOT ack/read/drop
                # anything: this consumer just stops pulling from the
                # stream, so every new task piles up unread ("parks") for
                # whichever consumer picks the switch back up — no task is
                # lost, silently dropped, or partially processed.
                logger.warning("bus.kill_switch_parked", agent=agent.value)
                await asyncio.sleep(KILL_SWITCH_POLL_S)
                continue
            try:
                # redis-py's XREADGROUP return type is a broad union in its
                # stubs (shape varies with flags we don't use here); `cast`
                # documents the shape this call actually produces rather
                # than widening the variable's type and losing precision
                # everywhere it's used below.
                raw = await self._redis.xreadgroup(
                    CONSUMER_GROUP, consumer_name, {stream: ">"}, count=10, block=block_ms
                )
            except (RedisTimeoutError, RedisConnectionError) as exc:
                # A blocking read timing out is an expected "no messages"
                # outcome, not a failure (doc 00 §5's "at-least-once
                # delivery" promise assumes a *running* consumer) — a
                # transient connection drop is recoverable the same way.
                # `make_redis`'s `socket_timeout=None` should make the
                # first case impossible, but this loop must survive either
                # way: an unhandled crash here kills the whole worker
                # process (Sprint 3: reproduced against real Redis, the
                # exact scenario `fakeredis`-based unit tests never
                # exercise).
                logger.warning("bus.consume_transient_error", agent=agent.value, error=str(exc))
                await asyncio.sleep(RECONNECT_BACKOFF_S)
                continue
            resp = cast(list[tuple[str, list[tuple[str, dict[str, str]]]]], raw)
            if not resp:
                continue
            for _stream, messages in resp:
                for msg_id, fields in messages:
                    await self._handle_one(stream, msg_id, fields, handler)

    async def _handle_one(
        self,
        stream: str,
        msg_id: str,
        fields: dict[str, str],
        handler: Callable[[TaskEnvelope], Awaitable[TaskResult]],
    ) -> None:
        env = TaskEnvelope.model_validate_json(fields["envelope"])
        attempt = int(fields.get("attempt", "0"))
        dedupe_key = f"processed:{env.idempotency_key}"

        first = await self._redis.set(dedupe_key, "1", nx=True, ex=DEDUPE_TTL_S)
        if not first:
            logger.info("bus.duplicate_delivery_skipped", task_id=str(env.task_id))
            await self._redis.xack(stream, CONSUMER_GROUP, msg_id)
            return

        try:
            await handler(env)
            await self._redis.xack(stream, CONSUMER_GROUP, msg_id)
        except Exception as exc:  # noqa: BLE001 - handler failure must not kill the loop
            logger.warning(
                "bus.handler_failed", task_id=str(env.task_id), attempt=attempt, error=str(exc)
            )
            await self._redis.delete(dedupe_key)  # allow the retry to actually re-run
            await self._redis.xack(stream, CONSUMER_GROUP, msg_id)
            if attempt + 1 >= MAX_ATTEMPTS:
                await self._to_dlq(env, str(exc))
            else:
                delay = RETRY_DELAYS_S[min(attempt, len(RETRY_DELAYS_S) - 1)]
                asyncio.create_task(self._delayed_readd(stream, env, attempt + 1, delay))

    async def _delayed_readd(
        self, stream: str, env: TaskEnvelope, attempt: int, delay_s: int
    ) -> None:
        await asyncio.sleep(delay_s)
        await self._redis.xadd(stream, {"envelope": env.model_dump_json(), "attempt": str(attempt)})

    async def _to_dlq(self, env: TaskEnvelope, error: str) -> None:
        await self._redis.xadd(DLQ_STREAM, {"envelope": env.model_dump_json(), "error": error})
        logger.error("bus.dead_letter", task_id=str(env.task_id), error=error)

    async def ack(self, agent: AgentId, msg_id: str) -> None:
        await self._redis.xack(stream_name(agent), CONSUMER_GROUP, msg_id)

    async def heartbeat(self, agent: AgentId, *, ttl_s: int = 120) -> None:
        await self._redis.set(f"hb:{agent.value}", str(time.time()), ex=ttl_s)

    async def is_alive(self, agent: AgentId) -> bool:
        result: Any = await self._redis.get(f"hb:{agent.value}")
        return result is not None

    async def set_kill_switch(self, agent: AgentId, on: bool) -> None:
        """Ops-triggered (`scripts/kill_switch.py`), not agent-triggered — no
        MCP tool exposes this (doc 08 never lists one), matching the "an
        agent scope can never approve its own gate" discipline elsewhere in
        this codebase applied to blast-radius control instead of HITL."""
        key = f"{KILL_SWITCH_PREFIX}{agent.value}"
        if on:
            await self._redis.set(key, "1")
        else:
            await self._redis.delete(key)

    async def is_killed(self, agent: AgentId) -> bool:
        return bool(await self._redis.exists(f"{KILL_SWITCH_PREFIX}{agent.value}"))
