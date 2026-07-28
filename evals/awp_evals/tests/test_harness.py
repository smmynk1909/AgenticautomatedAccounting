from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from awp_evals import harness
from awp_evals.schema import Outcome, RedTeamCase


class FakeMCP:
    def __init__(
        self,
        *,
        task_status_sequence: list[dict[str, Any]] | None = None,
        events: list[dict[str, Any]] | None = None,
    ) -> None:
        self._task_status_sequence = list(task_status_sequence or [])
        self._events = events or []
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def call(self, server: str, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((server, tool, args))
        if server == "erp" and tool == "dispatch_task":
            return {}
        if server == "erp" and tool == "get_task_status":
            if len(self._task_status_sequence) > 1:
                return {"task": self._task_status_sequence.pop(0)}
            return {"task": self._task_status_sequence[0]}
        if server == "audit" and tool == "query_events":
            return {"events": self._events}
        raise AssertionError(f"unexpected call: {server}.{tool}")


class FakeBus:
    def __init__(self) -> None:
        self.dispatched: list[Any] = []

    async def dispatch(self, env: Any) -> None:
        self.dispatched.append(env)


def _case(**overrides: Any) -> RedTeamCase:
    base = {
        "id": "t1",
        "category": "prompt_injection",
        "to_agent": "SUP-1",
        "intent": "create_ticket",
        "description": "d",
        "payload": {"channel": "chat", "category": "general", "subject": "s", "body": "b"},
        "timeout_s": 5.0,
    }
    base.update(overrides)
    return RedTeamCase.model_validate(base)


def test_load_corpus_reads_yaml_files(tmp_path: Path) -> None:
    (tmp_path / "one.yaml").write_text(
        """
cases:
  - id: c1
    category: prompt_injection
    description: d
    to_agent: SUP-1
    intent: create_ticket
    payload: {channel: chat, category: general, subject: s, body: b}
""",
        encoding="utf-8",
    )
    cases = harness.load_corpus(tmp_path)
    assert len(cases) == 1
    assert cases[0].id == "c1"


@pytest.mark.asyncio
async def test_run_case_passes_when_required_outcomes_hold() -> None:
    case = _case(
        required=[
            Outcome(kind="status_is", value="done"),
            Outcome(kind="result_contains", value="ok"),
        ]
    )
    mcp = FakeMCP(task_status_sequence=[{"status": "done", "result": {"summary": "all ok here"}}])
    report = await harness.run_case(mcp, FakeBus(), case)
    assert report.passed, report.detail


@pytest.mark.asyncio
async def test_run_case_actually_publishes_to_the_bus() -> None:
    # Regression guard: an earlier version of this harness only called
    # erp.dispatch_task (creates the Postgres row) and never bus.dispatch
    # (publishes to Redis Streams) — every case timed out with the task
    # stuck at status=pending forever, since no agent consumer ever saw
    # it. Live-verified and fixed, DEVIATIONS.md #23.
    case = _case(required=[Outcome(kind="status_is", value="done")])
    mcp = FakeMCP(task_status_sequence=[{"status": "done", "result": {}}])
    bus = FakeBus()
    await harness.run_case(mcp, bus, case)
    assert len(bus.dispatched) == 1
    assert bus.dispatched[0].intent == case.intent


@pytest.mark.asyncio
async def test_run_case_fails_when_forbidden_outcome_occurs() -> None:
    case = _case(forbidden=[Outcome(kind="result_contains", value="secret-leak")])
    mcp = FakeMCP(
        task_status_sequence=[
            {"status": "done", "result": {"summary": "here is the secret-leak value"}}
        ]
    )
    report = await harness.run_case(mcp, FakeBus(), case)
    assert not report.passed
    assert "forbidden" in report.detail


@pytest.mark.asyncio
async def test_run_case_fails_when_required_outcome_missing() -> None:
    case = _case(required=[Outcome(kind="status_is", value="done")])
    mcp = FakeMCP(task_status_sequence=[{"status": "failed", "result": {"summary": "nope"}}])
    report = await harness.run_case(mcp, FakeBus(), case)
    assert not report.passed
    assert "required" in report.detail


@pytest.mark.asyncio
async def test_run_case_counts_tool_calls_since_dispatch() -> None:
    case = _case(required=[Outcome(kind="tool_call_count_over", value=1)])
    events = [
        {"ts": "2020-01-01T00:00:00+00:00"},  # before dispatch — excluded
        {"ts": "2999-01-01T00:00:00+00:00"},
        {"ts": "2999-01-01T00:00:01+00:00"},
        {"ts": "2999-01-01T00:00:02+00:00"},
    ]
    mcp = FakeMCP(task_status_sequence=[{"status": "done", "result": {}}], events=events)
    report = await harness.run_case(mcp, FakeBus(), case)
    assert report.passed, report.detail
    assert report.tool_calls == 3


@pytest.mark.asyncio
async def test_poll_task_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(harness, "POLL_INTERVAL_S", 0.01)
    mcp = FakeMCP(task_status_sequence=[{"status": "in_progress"}])
    with pytest.raises(TimeoutError):
        await harness._poll_task(mcp, "task-1", timeout_s=0.03)


@pytest.mark.asyncio
async def test_run_corpus_reports_error_as_failure() -> None:
    class ExplodingMCP(FakeMCP):
        async def call(self, server: str, tool: str, args: dict[str, Any]) -> dict[str, Any]:
            raise RuntimeError("boom")

    case = _case()
    reports = await harness.run_corpus(ExplodingMCP(), FakeBus(), [case])
    assert len(reports) == 1
    assert not reports[0].passed
    assert "boom" in reports[0].detail
