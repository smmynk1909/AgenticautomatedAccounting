"""awp-eval harness (doc 09 §6-7) — dispatches every `RedTeamCase` in
`redteam/*.yaml` as a real `TaskEnvelope` over the actual Redis bus, waits
for it to finish, and checks its `required`/`forbidden` outcomes against
the real task result and audit trail. This is a live-verification tool
(needs a running stack — Postgres, Redis, `mcp-erp`, `mcp-audit`, and
whichever agent each case targets), not a `pytest -q` unit suite — same
split as `scripts/resume_extraction_eval.py` and `scripts/shadow_diff.py`.

Usage (from repo root, stack up via `make up`):
    uv run python -m awp_evals.harness
    uv run python -m awp_evals.harness --erp-url http://localhost:8003 --audit-url http://localhost:8001
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import yaml
from awp_shared.auth import mint_service_jwt
from awp_shared.bus import TaskBus, make_redis
from awp_shared.mcpc import MCP
from awp_shared.schemas import AgentId, TaskEnvelope

from awp_evals.schema import Outcome, RedTeamCase

DEFAULT_CORPUS_DIR = Path(__file__).parent / "redteam"
POLL_INTERVAL_S = 2.0


class MCPLike(Protocol):
    """Same shape as `awp_agent_base.protocols.MCPLike` — duck-typed so
    tests can pass a fake without a concrete `MCP` instance (evals has no
    other reason to depend on `agents/_base`)."""

    async def call(self, server: str, tool: str, args: dict[str, Any]) -> dict[str, Any]: ...


class BusLike(Protocol):
    async def dispatch(self, env: TaskEnvelope) -> None: ...


def load_corpus(directory: Path = DEFAULT_CORPUS_DIR) -> list[RedTeamCase]:
    cases: list[RedTeamCase] = []
    for path in sorted(directory.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        for item in raw["cases"]:
            cases.append(RedTeamCase.model_validate(item))
    return cases


class CaseReport:
    def __init__(self, case: RedTeamCase, passed: bool, detail: str, tool_calls: int) -> None:
        self.case = case
        self.passed = passed
        self.detail = detail
        self.tool_calls = tool_calls


async def _poll_task(mcp: MCPLike, task_id: str, timeout_s: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        status = await mcp.call("erp", "get_task_status", {"task_id": task_id})
        task: dict[str, Any] = status["task"]
        if task["status"] in ("done", "failed"):
            return task
        await asyncio.sleep(POLL_INTERVAL_S)
    raise TimeoutError(f"task {task_id} did not finish within {timeout_s}s")


async def _tool_call_count_since(mcp: MCPLike, agent_id: str, since: datetime) -> int:
    """Approximate, not exact: counts every `mcp-audit` event logged for
    `agent_id` on `since`'s calendar day at or after `since`. Fine for a
    harness that runs one case at a time (no concurrent dispatches to the
    same agent to conflate); would need a real per-task correlation id in
    `AuditEvent` (it has none today) to be exact under concurrency."""
    result = await mcp.call(
        "audit",
        "query_events",
        {"agent_id": agent_id, "day": since.date().isoformat(), "limit": 500},
    )
    return sum(1 for e in result["events"] if datetime.fromisoformat(e["ts"]) >= since)


def _check_outcome(outcome: Outcome, task: dict[str, Any], tool_calls: int) -> bool:
    if outcome.kind == "status_is":
        status: str = task["status"]
        return status == outcome.value
    if outcome.kind == "result_contains":
        summary = str((task.get("result") or {}).get("summary", ""))
        return str(outcome.value) in summary
    if outcome.kind == "tool_call_count_over":
        return tool_calls > int(outcome.value)
    raise ValueError(f"unknown outcome kind: {outcome.kind!r}")  # pragma: no cover


async def run_case(mcp: MCPLike, bus: BusLike, case: RedTeamCase) -> CaseReport:
    env = TaskEnvelope(
        from_agent=AgentId.HUMAN,
        to_agent=AgentId(case.to_agent),
        intent=case.intent,
        payload=case.payload,
    )
    dispatch_time = datetime.now(UTC)
    # Both calls are required, same as every other real dispatcher in this
    # codebase (gateway/awp_gateway/routers/*.py) — `erp.dispatch_task`
    # only creates the `orchestrator_tasks` row; nothing consumes a task
    # until it's actually published onto the Redis Streams bus. Omitting
    # `bus.dispatch` was a real bug here: the task sat at status=pending
    # forever and every case timed out looking like an agent-side failure
    # (DEVIATIONS.md #23).
    await mcp.call("erp", "dispatch_task", {"envelope": env.model_dump(mode="json")})
    await bus.dispatch(env)
    task = await _poll_task(mcp, str(env.task_id), case.timeout_s)
    tool_calls = await _tool_call_count_since(mcp, case.to_agent, dispatch_time)

    failures: list[str] = []
    for outcome in case.required:
        if not _check_outcome(outcome, task, tool_calls):
            failures.append(f"required {outcome.kind}={outcome.value!r} did not hold")
    for outcome in case.forbidden:
        if _check_outcome(outcome, task, tool_calls):
            failures.append(f"forbidden {outcome.kind}={outcome.value!r} occurred")

    if failures:
        return CaseReport(case, passed=False, detail="; ".join(failures), tool_calls=tool_calls)
    return CaseReport(case, passed=True, detail="ok", tool_calls=tool_calls)


async def run_corpus(mcp: MCPLike, bus: BusLike, cases: list[RedTeamCase]) -> list[CaseReport]:
    reports = []
    for case in cases:
        print(f"[{case.category}] {case.id} ... ", end="", file=sys.stderr, flush=True)
        try:
            report = await run_case(mcp, bus, case)
        except Exception as exc:  # noqa: BLE001 — a case erroring out is a FAIL, not a crash
            report = CaseReport(case, passed=False, detail=f"error: {exc}", tool_calls=0)
        print("PASS" if report.passed else f"FAIL ({report.detail})", file=sys.stderr)
        reports.append(report)
    return reports


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--erp-url", default="http://localhost:8003")
    parser.add_argument("--audit-url", default="http://localhost:8001")
    parser.add_argument("--redis-url", default="redis://localhost:6379/0")
    parser.add_argument("--corpus-dir", type=Path, default=DEFAULT_CORPUS_DIR)
    args = parser.parse_args(argv)

    mcp = MCP(
        {"erp": args.erp_url, "audit": args.audit_url},
        principal_jwt_provider=lambda: mint_service_jwt(
            "redteam-harness", ["erp.tasks.dispatch", "erp.tasks.read", "audit.read"]
        ),
        timeout_s=1500.0,
    )
    bus = TaskBus(make_redis(args.redis_url))

    cases = load_corpus(args.corpus_dir)
    reports = await run_corpus(mcp, bus, cases)

    passed = sum(1 for r in reports if r.passed)
    failed = len(reports) - passed
    print(f"\n{passed}/{len(reports)} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
