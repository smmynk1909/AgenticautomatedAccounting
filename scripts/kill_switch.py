"""Ops kill-switch CLI — doc 09 §4.5, doc 12 §6 exit checklist ("kill-switch
drill executed"). Flips `TaskBus`'s per-agent queue-park flag in Redis; the
agent process itself needs no restart — `TaskBus.consume`'s loop polls the
flag every `KILL_SWITCH_POLL_S` (2s).

Usage:
    python scripts/kill_switch.py status
    python scripts/kill_switch.py on HR-1
    python scripts/kill_switch.py off HR-1
"""

from __future__ import annotations

import asyncio
import os
import sys

from awp_shared.bus import TaskBus, make_redis
from awp_shared.schemas import AgentId

CONSUMING_AGENTS = [a for a in AgentId if a not in (AgentId.HUMAN, AgentId.SCHEDULER)]


async def _status(bus: TaskBus) -> None:
    for agent in CONSUMING_AGENTS:
        killed = await bus.is_killed(agent)
        print(f"{agent.value}: {'PARKED (killed)' if killed else 'running'}")


async def main(argv: list[str]) -> int:
    if not argv or argv[0] not in ("status", "on", "off"):
        print(__doc__)
        return 2

    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    bus = TaskBus(make_redis(redis_url))

    if argv[0] == "status":
        await _status(bus)
        return 0

    if len(argv) != 2:
        print(f"usage: kill_switch.py {argv[0]} <AGENT_ID e.g. HR-1>")
        return 2

    try:
        agent = AgentId(argv[1])
    except ValueError:
        print(f"unknown agent id {argv[1]!r}; valid: {[a.value for a in CONSUMING_AGENTS]}")
        return 2
    if agent not in CONSUMING_AGENTS:
        print(f"{agent.value} doesn't consume a task stream (HUMAN/SCHEDULER never do)")
        return 2

    await bus.set_kill_switch(agent, on=argv[0] == "on")
    print(f"{agent.value}: {'PARKED (killed)' if argv[0] == 'on' else 'running'}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
