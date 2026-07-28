"""doc 05 §5 acceptance-adjacent graph-level tests (doc 11 §10's testing
pyramid, same convention as agents/hr1/fin1's test_graph_acceptance.py).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from awp_agent_base.state import new_state
from awp_shared.errors import ValidationError
from awp_shared.llm import LLMResponse
from awp_shared.schemas import AgentId, TaskEnvelope, TaskStatus

from awp_agent_ops1.graph import build_graph
from awp_agent_ops1.tests.conftest import FakeLLM, FakeMCP


def _task(intent: str, payload: dict) -> TaskEnvelope:
    return TaskEnvelope(
        from_agent=AgentId.ORCH0, to_agent=AgentId.OPS1, intent=intent, payload=payload
    )


# --- assign_employee_project ---


@pytest.mark.asyncio
async def test_assign_employee_project_requests_approval() -> None:
    mcp = FakeMCP(
        handlers={
            ("erp", "query_allocations"): {"allocations": [{"pct": 40}]},
            ("approvals", "request_approval"): {"approval_id": "AP1"},
        }
    )
    graph = build_graph(FakeLLM([]), mcp)
    task = _task(
        "assign_employee_project",
        {"emp_id": "E1", "project_id": "P1", "pct": 50, "from_date": "2026-08-01"},
    )
    final = await graph.ainvoke(new_state(task))

    assert final["result"].status == TaskStatus.AWAITING_APPROVAL
    assert final["scratch"]["awaiting_approval_for"] == "assign_employee_project"
    assert "over capacity" not in final["result"].summary  # 40 + 50 = 90%, under 100


@pytest.mark.asyncio
async def test_assign_employee_project_flags_over_capacity_in_summary() -> None:
    mcp = FakeMCP(
        handlers={
            ("erp", "query_allocations"): {"allocations": [{"pct": 80}]},
            ("approvals", "request_approval"): {"approval_id": "AP1"},
        }
    )
    graph = build_graph(FakeLLM([]), mcp)
    task = _task(
        "assign_employee_project",
        {"emp_id": "E1", "project_id": "P1", "pct": 50, "from_date": "2026-08-01"},
    )
    final = await graph.ainvoke(new_state(task))
    assert "over capacity" in final["result"].summary
    assert "130" in final["result"].summary


@pytest.mark.asyncio
async def test_check_assign_employee_project_approval_commits_on_approve() -> None:
    mcp = FakeMCP(
        handlers={
            ("approvals", "get_approval_status"): {"status": "approved", "token": "signed.jwt"},
            ("erp", "upsert_allocation"): {"id": "A1"},
        }
    )
    graph = build_graph(FakeLLM([]), mcp)
    task = _task("assign_employee_project", {})
    state = new_state(task)
    state["scratch"] = {
        "awaiting_approval_for": "assign_employee_project",
        "approval_id": "AP1",
        "allocation_record": {
            "emp_id": "E1",
            "project_id": "P1",
            "pct": 50,
            "from_date": "2026-08-01",
            "to_date": None,
        },
    }
    final = await graph.ainvoke(state)

    assert final["result"].status == TaskStatus.DONE
    upsert_call = next(c for c in mcp.calls if c[:2] == ("erp", "upsert_allocation"))
    assert upsert_call[2]["record"]["emp_id"] == "E1"


@pytest.mark.asyncio
async def test_check_assign_employee_project_approval_rejected() -> None:
    mcp = FakeMCP(handlers={("approvals", "get_approval_status"): {"status": "rejected"}})
    graph = build_graph(FakeLLM([]), mcp)
    task = _task("assign_employee_project", {})
    state = new_state(task)
    state["scratch"] = {
        "awaiting_approval_for": "assign_employee_project",
        "approval_id": "AP1",
        "allocation_record": {},
    }
    final = await graph.ainvoke(state)
    assert final["result"].status == TaskStatus.FAILED


# --- project_health_report ---


def _health_report_mcp(*, overdue_invoice_milestone: bool) -> FakeMCP:
    # ISO string, not a `date` object: a real `query_milestones` response
    # crosses the wire as JSON, so `due` arrives as a string — using a real
    # `date` here would test a shape the node never actually sees (this
    # exact mismatch was live-verified to crash the node before nodes.py's
    # `_coerce_milestone_dates` existed: "'<' not supported between
    # instances of 'str' and 'datetime.date'").
    due = (datetime.now(UTC).date() - timedelta(days=7)).isoformat()  # always overdue
    milestones = [
        {
            "id": "M1",
            "title": "GA",
            "due": due,
            "status": "in_progress",
            "invoice_trigger": overdue_invoice_milestone,
        }
    ]
    handlers = {
        ("erp", "get_project"): {"id": "P1", "client": "Acme", "budget_hours": 100},
        ("erp", "query_milestones"): {"milestones": milestones},
        ("erp", "query_work_logs"): {"work_logs": [{"hours": 40}]},
        ("erp", "push_dashboard_item"): {"id": "D1"},
        ("projects", "create_issue"): {"id": "I1", "severity": "S1", "description": "slip"},
        ("comms", "notify_user"): {"outbox_id": "O1"},
    }
    return FakeMCP(handlers=handlers)


@pytest.mark.asyncio
async def test_project_health_report_publishes_dashboard_item() -> None:
    mcp = _health_report_mcp(overdue_invoice_milestone=False)
    llm = FakeLLM([LLMResponse(content="Project is progressing with one overdue milestone.")])
    graph = build_graph(llm, mcp)
    task = _task("project_health_report", {"project_id": "P1"})
    final = await graph.ainvoke(new_state(task))

    assert final["result"].status == TaskStatus.DONE
    push_call = next(c for c in mcp.calls if c[:2] == ("erp", "push_dashboard_item"))
    assert push_call[2]["item"]["panel"] == "project_health"
    assert ("projects", "create_issue") not in [c[:2] for c in mcp.calls]


@pytest.mark.asyncio
async def test_project_health_report_escalates_s1_on_overdue_invoice_milestone() -> None:
    mcp = _health_report_mcp(overdue_invoice_milestone=True)
    llm = FakeLLM([LLMResponse(content="Milestone slipped past its committed date.")])
    graph = build_graph(llm, mcp)
    task = _task("project_health_report", {"project_id": "P1"})
    final = await graph.ainvoke(new_state(task))

    assert final["result"].status == TaskStatus.DONE
    assert "S1 escalated" in final["result"].summary
    create_call = next(c for c in mcp.calls if c[:2] == ("projects", "create_issue"))
    assert create_call[2]["severity"] == "S1"
    notify_call = next(c for c in mcp.calls if c[:2] == ("comms", "notify_user"))
    assert notify_call[2]["user_id"] == "director"
    ceo_dashboard_call = [
        c
        for c in mcp.calls
        if c[:2] == ("erp", "push_dashboard_item") and c[2]["item"]["panel"] == "ceo_dashboard"
    ]
    assert len(ceo_dashboard_call) == 1


# --- timeline_risk_scan ---


@pytest.mark.asyncio
async def test_timeline_risk_scan_publishes_key_timelines_panel() -> None:
    mcp = FakeMCP(
        handlers={
            ("erp", "query_projects"): {"projects": [{"id": "P1", "client": "Acme"}]},
            ("erp", "query_milestones"): {
                "milestones": [
                    {
                        "id": "M1",
                        "title": "GA",
                        "due": (datetime.now(UTC).date() + timedelta(days=5)).isoformat(),
                        "status": "planned",
                        "invoice_trigger": True,
                    }
                ]
            },
            ("erp", "push_dashboard_item"): {"id": "D1"},
        }
    )
    graph = build_graph(FakeLLM([]), mcp)
    task = _task("timeline_risk_scan", {"horizon_days": 30})
    final = await graph.ainvoke(new_state(task))

    assert final["result"].status == TaskStatus.DONE
    push_call = next(c for c in mcp.calls if c[:2] == ("erp", "push_dashboard_item"))
    assert push_call[2]["item"]["panel"] == "key_timelines"


@pytest.mark.asyncio
async def test_timeline_risk_scan_no_items_still_publishes_info_panel() -> None:
    mcp = FakeMCP(
        handlers={
            ("erp", "query_projects"): {"projects": []},
            ("erp", "push_dashboard_item"): {"id": "D1"},
        }
    )
    graph = build_graph(FakeLLM([]), mcp)
    task = _task("timeline_risk_scan", {})
    final = await graph.ainvoke(new_state(task))

    assert final["result"].status == TaskStatus.DONE
    push_call = next(c for c in mcp.calls if c[:2] == ("erp", "push_dashboard_item"))
    assert push_call[2]["item"]["severity"] == "info"


# --- code_assist_session ---


@pytest.mark.asyncio
async def test_code_assist_session_denies_engineer_without_allocation() -> None:
    """doc 05 §5.5 acceptance test: "Engineer without ACL to repo X gets
    zero code context from X" — no allocation means the node never even
    calls get_project/search_kb for that repo."""
    mcp = FakeMCP(handlers={("erp", "query_allocations"): {"allocations": []}})
    graph = build_graph(FakeLLM([]), mcp)
    task = _task(
        "code_assist_session",
        {"project_id": "P1", "mode": "chat", "input": "what does this repo do?", "emp_id": "E1"},
    )
    final = await graph.ainvoke(new_state(task))

    assert final["result"].status == TaskStatus.FAILED
    assert "no allocation" in final["result"].summary
    called_tools = [c[:2] for c in mcp.calls]
    assert ("erp", "get_project") not in called_tools
    assert ("search", "search_kb") not in called_tools


@pytest.mark.asyncio
async def test_code_assist_session_chat_uses_repo_context() -> None:
    mcp = FakeMCP(
        handlers={
            ("erp", "query_allocations"): {"allocations": [{"pct": 100}]},
            ("erp", "get_project"): {"id": "P1", "repo_slug": "awp-admin/svc-a"},
            ("search", "search_kb"): {"results": [{"text": "def add(a, b): return a + b"}]},
            ("projects", "secrets_scan"): {
                "clean": True,
                "findings": [],
                "redacted_text": "def add(a, b): return a + b",
            },
        }
    )
    llm = FakeLLM([LLMResponse(content="add() sums two numbers.")])
    graph = build_graph(llm, mcp)
    task = _task(
        "code_assist_session",
        {"project_id": "P1", "mode": "chat", "input": "what does add do?", "emp_id": "E1"},
    )
    final = await graph.ainvoke(new_state(task))

    assert final["result"].status == TaskStatus.DONE
    assert final["scratch"]["code_assist_result"] == "add() sums two numbers."
    # TaskResult.summary carries the actual answer, not a generic status
    # blurb — it's the only thing the gateway's IDE endpoint can return.
    assert final["result"].summary == "add() sums two numbers."
    search_call = next(c for c in mcp.calls if c[:2] == ("search", "search_kb"))
    assert search_call[2]["corpus"] == "code_awp-admin_svc-a"


@pytest.mark.asyncio
async def test_code_assist_session_redacts_secrets_before_model_call() -> None:
    mcp = FakeMCP(
        handlers={
            ("erp", "query_allocations"): {"allocations": [{"pct": 100}]},
            ("erp", "get_project"): {"id": "P1", "repo_slug": "awp-admin/svc-a"},
            ("search", "search_kb"): {
                "results": [{"text": 'AWS_ACCESS_KEY_ID = "AKIAIOSFODNN7EXAMPLE"'}]
            },
            ("projects", "secrets_scan"): {
                "clean": False,
                "findings": [
                    {"kind": "aws_access_key_id", "line": 1, "match_preview": "AKIA...MPLE"}
                ],
                "redacted_text": "AWS_ACCESS_KEY_ID = [REDACTED:aws_access_key_id]",
            },
        }
    )
    llm = FakeLLM([LLMResponse(content="I don't see credential values in this context.")])
    graph = build_graph(llm, mcp)
    task = _task(
        "code_assist_session",
        {"project_id": "P1", "mode": "chat", "input": "what's the access key?", "emp_id": "E1"},
    )
    final = await graph.ainvoke(new_state(task))

    assert final["result"].status == TaskStatus.DONE
    assert "secrets were redacted" in final["result"].summary
    sent_context = llm.calls[0]["messages"][-1]["content"]
    assert "AKIAIOSFODNN7EXAMPLE" not in sent_context
    assert "[REDACTED:aws_access_key_id]" in sent_context


@pytest.mark.asyncio
async def test_code_assist_session_review_mode_uses_input_as_diff() -> None:
    import json

    mcp = FakeMCP(handlers={("erp", "query_allocations"): {"allocations": [{"pct": 100}]}})
    review_json = json.dumps(
        {"bugs": [], "security": [], "style": ["missing docstring"], "tests_missing": []}
    )
    llm = FakeLLM([LLMResponse(content=review_json)])
    graph = build_graph(llm, mcp)
    task = _task(
        "code_assist_session",
        {
            "project_id": "P1",
            "mode": "review",
            "input": "diff --git a/x b/x\n+def f(): pass\n",
            "emp_id": "E1",
        },
    )
    final = await graph.ainvoke(new_state(task))

    assert final["result"].status == TaskStatus.DONE
    assert final["scratch"]["code_assist_result"]["style"] == ["missing docstring"]
    assert "missing docstring" in final["result"].summary  # JSON-encoded into summary too
    # review mode never calls get_project/search_kb — the diff itself is the context
    called_tools = [c[:2] for c in mcp.calls]
    assert ("erp", "get_project") not in called_tools


@pytest.mark.asyncio
async def test_unknown_intent_raises() -> None:
    mcp = FakeMCP()
    graph = build_graph(FakeLLM([]), mcp)
    task = _task("not_a_real_intent", {})
    with pytest.raises(ValidationError):
        await graph.ainvoke(new_state(task))
