"""Prometheus metrics — doc 00 §7 / doc 10 HLD C19's `Prometheus, Grafana`.
Sibling to `tracing.py`: both are wired into the same three choke points
(`ToolPipeline.dispatch`, `AgentApp.handle`, `LLM.chat`) so every MCP tool
call, agent task, and LLM call is counted/timed/traced identically
regardless of which server or agent it runs in.

`prometheus-client` is a required dependency (unlike the `otel` extra) —
it's pure in-process bookkeeping with no network calls of its own; a
scraper either polls `/metrics` or it doesn't. Nothing here talks to
Prometheus directly.
"""

from __future__ import annotations

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)

REGISTRY = CollectorRegistry(auto_describe=True)

mcp_tool_calls_total = Counter(
    "awp_mcp_tool_calls_total",
    "MCP tool calls, by server/tool/outcome",
    ["server", "tool", "status"],
    registry=REGISTRY,
)
mcp_tool_call_duration_seconds = Histogram(
    "awp_mcp_tool_call_duration_seconds",
    "MCP tool call latency, by server/tool",
    ["server", "tool"],
    registry=REGISTRY,
)

agent_tasks_total = Counter(
    "awp_agent_tasks_total",
    "Agent task graph runs, by agent/intent/outcome",
    ["agent", "intent", "status"],
    registry=REGISTRY,
)
agent_task_duration_seconds = Histogram(
    "awp_agent_task_duration_seconds",
    "Agent task graph run latency, by agent/intent",
    ["agent", "intent"],
    # Task graphs include LLM calls that can run minutes on CPU inference
    # (DEVIATIONS.md #18) — the histogram's default buckets top out at 10s.
    buckets=(0.5, 1, 2.5, 5, 10, 30, 60, 120, 300, 600, 1200, float("inf")),
    registry=REGISTRY,
)

llm_calls_total = Counter(
    "awp_llm_calls_total",
    "LLM gateway calls, by model/outcome",
    ["model", "status"],
    registry=REGISTRY,
)
llm_call_duration_seconds = Histogram(
    "awp_llm_call_duration_seconds",
    "LLM gateway call latency, by model",
    ["model"],
    buckets=(0.5, 1, 2.5, 5, 10, 30, 60, 120, 300, 600, 1200, float("inf")),
    registry=REGISTRY,
)


def render_latest() -> bytes:
    return generate_latest(REGISTRY)


__all__ = [
    "CONTENT_TYPE_LATEST",
    "REGISTRY",
    "agent_task_duration_seconds",
    "agent_tasks_total",
    "llm_call_duration_seconds",
    "llm_calls_total",
    "mcp_tool_call_duration_seconds",
    "mcp_tool_calls_total",
    "render_latest",
]
