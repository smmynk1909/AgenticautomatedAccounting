from awp_shared.metrics import (
    CONTENT_TYPE_LATEST,
    agent_task_duration_seconds,
    agent_tasks_total,
    llm_call_duration_seconds,
    llm_calls_total,
    mcp_tool_call_duration_seconds,
    mcp_tool_calls_total,
    render_latest,
)


def test_render_latest_produces_valid_prometheus_text_exposition() -> None:
    mcp_tool_calls_total.labels("erp", "get_project", "ok").inc()
    agent_tasks_total.labels("HR-1", "prepare_negotiation", "done").inc()
    llm_calls_total.labels("qwen2.5:7b-instruct", "ok").inc()

    body = render_latest()

    assert isinstance(body, bytes)
    text = body.decode("utf-8")
    # Every metric this module defines should appear in the exposition
    # format at least once (as a HELP/TYPE line, even before any sample).
    for metric_name in (
        "awp_mcp_tool_calls_total",
        "awp_agent_tasks_total",
        "awp_llm_calls_total",
        "awp_mcp_tool_call_duration_seconds",
        "awp_agent_task_duration_seconds",
        "awp_llm_call_duration_seconds",
    ):
        assert metric_name in text


def test_content_type_is_the_prometheus_text_format() -> None:
    assert "text/plain" in CONTENT_TYPE_LATEST


def test_histograms_accept_observations_without_raising() -> None:
    # Regression guard for the custom bucket tuples (agent/llm duration
    # histograms use non-default buckets reaching up to 20 minutes, per
    # DEVIATIONS.md #18's CPU-inference latency) — a malformed buckets=
    # tuple would raise at observe()-time, not at import-time.
    mcp_tool_call_duration_seconds.labels("erp", "get_project").observe(0.05)
    agent_task_duration_seconds.labels("HR-1", "prepare_negotiation").observe(650.0)
    llm_call_duration_seconds.labels("qwen2.5:7b-instruct").observe(300.0)
