"""doc 04 §5 acceptance-adjacent graph-level tests (doc 11 §10's testing
pyramid, same convention as agents/fin1's test_graph_acceptance.py).
Extraction F1 (test 1) needs the labeled 50-resume set + a real LLM — that's
`scripts/resume_extraction_eval.py`'s live-verification job, not something
these graph tests (FakeMCP, no real Ollama) can assert a number for.
Shortlist determinism (test 2) IS asserted here at the graph level, on top
of shortlister.py's own pure-function tests.
"""

from __future__ import annotations

import pytest
from awp_agent_base.state import new_state
from awp_shared.errors import ValidationError
from awp_shared.llm import LLMResponse
from awp_shared.schemas import AgentId, TaskEnvelope, TaskStatus

from awp_agent_hr1.graph import build_graph
from awp_agent_hr1.tests.conftest import FakeLLM, FakeMCP


def _task(intent: str, payload: dict) -> TaskEnvelope:
    return TaskEnvelope(
        from_agent=AgentId.ORCH0, to_agent=AgentId.HR1, intent=intent, payload=payload
    )


# --- source_candidates ---


@pytest.mark.asyncio
async def test_source_candidates_uses_cached_role_profile() -> None:
    mcp = FakeMCP(
        handlers={
            ("erp", "get_role"): {"id": "R1", "role_profile": {"must_have": ["Python"]}},
            ("search", "search_candidates"): {
                "candidates": [{"candidate_id": "C1", "score": 0.9}]
            },
        }
    )
    graph = build_graph(FakeLLM([]), mcp)
    task = _task("source_candidates", {"role_id": "R1", "count": 5})
    final = await graph.ainvoke(new_state(task))

    assert final["result"].status == TaskStatus.DONE
    assert final["scratch"]["sourced_count"] == 1
    assert ("erp", "upsert_role") not in [c[:2] for c in mcp.calls]  # never re-parsed


# --- audit_resume ---


@pytest.mark.asyncio
async def test_audit_resume_canonicalizes_skills_and_persists() -> None:
    mcp = FakeMCP(
        handlers={
            ("docs", "get_file"): {"content_base64": "AAAA", "filename": "r.pdf"},
            ("hrsourcing", "extract_resume"): {"text": "Asha Rao resume text"},
            ("hrsourcing", "normalize_profile"): {
                "profile": {
                    "name": "Asha Rao",
                    "contact": {"email": "asha@x.com"},
                    "total_exp_months": 36,
                    "positions": [],
                    "education": [],
                    "certifications": [],
                    "skills_normalized": ["Python", "pythonn"],
                    "gaps": [],
                    "red_flags": [{"type": "overlap", "evidence": "x overlaps y"}],
                    "audit_score": {
                        "completeness": 0.8,
                        "consistency": 0.7,
                        "relevance_to_role": None,
                    },
                },
                "confidence": {"name": 1.0},
            },
            ("erp", "query_policies"): {
                "policies": [{"id": "sk-py", "name": "Python", "synonyms": []}]
            },
            ("hrsourcing", "skill_normalize"): {
                "matches": [
                    {"term": "Python", "skill_id": "sk-py", "name": "Python", "score": 1.0},
                    {"term": "pythonn", "skill_id": "sk-py", "name": "Python", "score": 0.9},
                ]
            },
            ("erp", "get_candidate"): {"id": "C1", "profile": {"name": "old"}},
            ("erp", "upsert_candidate"): {"id": "C1"},
        }
    )
    graph = build_graph(FakeLLM([]), mcp)
    task = _task("audit_resume", {"candidate_id": "C1", "resume_uri": "minio://bucket/r.pdf"})
    final = await graph.ainvoke(new_state(task))

    assert final["result"].status == TaskStatus.DONE
    assert "1 red flag" in final["result"].summary

    upsert_call = next(c for c in mcp.calls if c[:2] == ("erp", "upsert_candidate"))
    persisted_profile = upsert_call[2]["record"]["profile"]
    assert persisted_profile["skills_normalized"] == ["Python"]  # deduped canonical name


# --- shortlist_role ---


def _shortlist_mcp() -> FakeMCP:
    def get_candidate(args: dict) -> dict:
        profiles = {
            "C1": {"skills_normalized": ["Python"], "total_exp_months": 36},
            "C2": {"skills_normalized": ["Java"], "total_exp_months": 12},
        }
        return {"id": args["candidate_id"], "profile": profiles[args["candidate_id"]]}

    return FakeMCP(
        handlers={
            ("erp", "get_role"): {
                "id": "R1",
                "role_profile": {"must_have": ["Python"], "min_exp_months": 12},
            },
            ("search", "search_candidates"): {
                "candidates": [
                    {"candidate_id": "C1", "score": 0.8},
                    {"candidate_id": "C2", "score": 0.5},
                ]
            },
            ("erp", "get_candidate"): get_candidate,
            ("approvals", "request_approval"): {"approval_id": "AP1"},
        }
    )


@pytest.mark.asyncio
async def test_shortlist_role_requests_approval() -> None:
    mcp = _shortlist_mcp()
    llm = FakeLLM([LLMResponse(content="j1"), LLMResponse(content="j2")])
    graph = build_graph(llm, mcp)
    task = _task("shortlist_role", {"role_id": "R1", "top_n": 10})
    final = await graph.ainvoke(new_state(task))

    assert final["result"].status == TaskStatus.AWAITING_APPROVAL
    assert final["scratch"]["awaiting_approval_for"] == "shortlist_role"
    shortlist = final["scratch"]["shortlist"]
    assert shortlist[0]["candidate_id"] == "C1"  # Python match ranks above Java


@pytest.mark.asyncio
async def test_shortlist_role_ranking_is_deterministic() -> None:
    task = _task("shortlist_role", {"role_id": "R1", "top_n": 10})

    justifications = [LLMResponse(content="j1"), LLMResponse(content="j2")]
    graph_1 = build_graph(FakeLLM(list(justifications)), _shortlist_mcp())
    final_1 = await graph_1.ainvoke(new_state(task))

    graph_2 = build_graph(FakeLLM(list(justifications)), _shortlist_mcp())
    final_2 = await graph_2.ainvoke(new_state(task))

    ids_1 = [c["candidate_id"] for c in final_1["scratch"]["shortlist"]]
    ids_2 = [c["candidate_id"] for c in final_2["scratch"]["shortlist"]]
    assert ids_1 == ids_2
    scores_1 = [c["score"] for c in final_1["scratch"]["shortlist"]]
    scores_2 = [c["score"] for c in final_2["scratch"]["shortlist"]]
    assert scores_1 == scores_2


@pytest.mark.asyncio
async def test_shortlist_role_without_cached_profile_raises() -> None:
    mcp = FakeMCP(handlers={("erp", "get_role"): {"id": "R1", "role_profile": {}}})
    graph = build_graph(FakeLLM([]), mcp)
    task = _task("shortlist_role", {"role_id": "R1"})
    with pytest.raises(ValidationError):
        await graph.ainvoke(new_state(task))


@pytest.mark.asyncio
async def test_check_shortlist_role_approval_publishes_on_approve() -> None:
    mcp = FakeMCP(
        handlers={
            ("approvals", "get_approval_status"): {"status": "approved", "token": "signed.jwt"},
            ("erp", "push_dashboard_item"): {"id": "D1"},
        }
    )
    graph = build_graph(FakeLLM([]), mcp)
    task = _task("shortlist_role", {"role_id": "R1"})
    state = new_state(task)
    state["scratch"] = {
        "awaiting_approval_for": "shortlist_role",
        "approval_id": "AP1",
        "role_id": "R1",
        "shortlist": [{"candidate_id": "C1", "score": 0.8}],
    }
    final = await graph.ainvoke(state)

    assert final["result"].status == TaskStatus.DONE
    assert "awaiting_approval_for" not in final["scratch"]
    push_call = next(c for c in mcp.calls if c[:2] == ("erp", "push_dashboard_item"))
    assert push_call[2]["item"]["panel"] == "hr_shortlist"


@pytest.mark.asyncio
async def test_check_shortlist_role_approval_still_pending() -> None:
    mcp = FakeMCP(handlers={("approvals", "get_approval_status"): {"status": "pending"}})
    graph = build_graph(FakeLLM([]), mcp)
    task = _task("shortlist_role", {"role_id": "R1"})
    state = new_state(task)
    state["scratch"] = {
        "awaiting_approval_for": "shortlist_role",
        "approval_id": "AP1",
        "role_id": "R1",
        "shortlist": [],
    }
    final = await graph.ainvoke(state)
    assert final["result"].status == TaskStatus.AWAITING_APPROVAL


@pytest.mark.asyncio
async def test_check_shortlist_role_approval_rejected() -> None:
    mcp = FakeMCP(handlers={("approvals", "get_approval_status"): {"status": "rejected"}})
    graph = build_graph(FakeLLM([]), mcp)
    task = _task("shortlist_role", {"role_id": "R1"})
    state = new_state(task)
    state["scratch"] = {
        "awaiting_approval_for": "shortlist_role",
        "approval_id": "AP1",
        "role_id": "R1",
        "shortlist": [],
    }
    final = await graph.ainvoke(state)
    assert final["result"].status == TaskStatus.FAILED


# --- prepare_negotiation ---

_TALK_TRACK_JSON = (
    '{"pairs": [{"objection": "wants more", "response": "we can move within band"}]}'
)


def _negotiation_mcp(extra: dict | None = None) -> FakeMCP:
    handlers = {
        ("erp", "get_role"): {"id": "R1", "grade": "G3", "title": "Backend Engineer"},
        ("erp", "query_policies"): {
            "policies": [{"grade": "G3", "min": 60000, "mid": 80000, "max": 100000}]
        },
        ("search", "search_kb"): {"results": []},
        ("erp", "get_candidate"): {"id": "C1", "profile": {"name": "Asha Rao"}},
    }
    handlers.update(extra or {})
    return FakeMCP(handlers=handlers)


@pytest.mark.asyncio
async def test_prepare_negotiation_without_draft_returns_pack() -> None:
    mcp = _negotiation_mcp()
    llm = FakeLLM([LLMResponse(content=_TALK_TRACK_JSON)])
    graph = build_graph(llm, mcp)
    task = _task("prepare_negotiation", {"candidate_id": "C1", "role_id": "R1"})
    final = await graph.ainvoke(new_state(task))

    assert final["result"].status == TaskStatus.DONE
    assert final["scratch"]["negotiation_pack"]["band"]["mid"] == 80000
    assert ("approvals", "request_approval") not in [c[:2] for c in mcp.calls]


@pytest.mark.asyncio
async def test_prepare_negotiation_with_draft_requests_approval() -> None:
    mcp = _negotiation_mcp({("approvals", "request_approval"): {"approval_id": "AP1"}})
    llm = FakeLLM(
        [
            LLMResponse(content=_TALK_TRACK_JSON),
            LLMResponse(content="We're pleased to offer a starting package of 80000."),
        ]
    )
    graph = build_graph(llm, mcp)
    task = _task(
        "prepare_negotiation", {"candidate_id": "C1", "role_id": "R1", "draft_email": True}
    )
    final = await graph.ainvoke(new_state(task))

    assert final["result"].status == TaskStatus.AWAITING_APPROVAL
    assert final["scratch"]["awaiting_approval_for"] == "prepare_negotiation"


@pytest.mark.asyncio
async def test_prepare_negotiation_draft_leaking_ceiling_is_blocked() -> None:
    mcp = _negotiation_mcp({("approvals", "request_approval"): {"approval_id": "AP1"}})
    llm = FakeLLM(
        [
            LLMResponse(content=_TALK_TRACK_JSON),
            LLMResponse(content="Our absolute ceiling for this role is 100000."),
        ]
    )
    graph = build_graph(llm, mcp)
    task = _task(
        "prepare_negotiation", {"candidate_id": "C1", "role_id": "R1", "draft_email": True}
    )
    final = await graph.ainvoke(new_state(task))

    assert final["result"].status == TaskStatus.FAILED
    assert "output filter" in final["result"].summary
    assert ("approvals", "request_approval") not in [c[:2] for c in mcp.calls]


@pytest.mark.asyncio
async def test_check_prepare_negotiation_approval_records_draft_on_approve() -> None:
    mcp = FakeMCP(
        handlers={
            ("approvals", "get_approval_status"): {"status": "approved", "token": "signed.jwt"},
            ("comms", "draft_external_email"): {"outbox_id": "O1"},
        }
    )
    graph = build_graph(FakeLLM([]), mcp)
    task = _task("prepare_negotiation", {"candidate_id": "C1", "role_id": "R1"})
    state = new_state(task)
    state["scratch"] = {
        "awaiting_approval_for": "prepare_negotiation",
        "approval_id": "AP1",
        "candidate_id": "C1",
        "draft_text": "frozen offer text",
    }
    final = await graph.ainvoke(state)

    assert final["result"].status == TaskStatus.DONE
    draft_call = next(c for c in mcp.calls if c[:2] == ("comms", "draft_external_email"))
    assert draft_call[2]["body"] == "frozen offer text"


# --- plan_training ---


def _training_mcp(extra: dict | None = None) -> FakeMCP:
    handlers = {
        ("erp", "get_employee"): {"emp_id": "E1", "role_id": "R1", "skills": ["Python"]},
        ("erp", "get_role"): {
            "id": "R1",
            "role_profile": {"must_have": ["Python", "SQL"], "nice_to_have": []},
        },
        ("search", "search_kb"): {"results": [{"text": "SQL fundamentals", "citation": {}}]},
    }
    handlers.update(extra or {})
    return FakeMCP(handlers=handlers)


@pytest.mark.asyncio
async def test_plan_training_requests_approval() -> None:
    mcp = _training_mcp({("approvals", "request_approval"): {"approval_id": "AP2"}})
    graph = build_graph(FakeLLM([]), mcp)
    task = _task("plan_training", {"emp_id": "E1", "quarter": "2026-Q3"})
    final = await graph.ainvoke(new_state(task))

    assert final["result"].status == TaskStatus.AWAITING_APPROVAL
    assert final["scratch"]["awaiting_approval_for"] == "plan_training"
    assert final["scratch"]["training_plan"]["items"]


@pytest.mark.asyncio
async def test_check_plan_training_approval_notifies_on_approve() -> None:
    mcp = FakeMCP(
        handlers={
            ("approvals", "get_approval_status"): {"status": "approved", "token": "signed.jwt"},
            ("comms", "notify_user"): {"outbox_id": "O2"},
        }
    )
    graph = build_graph(FakeLLM([]), mcp)
    task = _task("plan_training", {"emp_id": "E1"})
    state = new_state(task)
    state["scratch"] = {
        "awaiting_approval_for": "plan_training",
        "approval_id": "AP2",
        "emp_id": "E1",
        "training_plan": {"items": [], "total_hours": 0, "total_cost": 0},
    }
    final = await graph.ainvoke(state)

    assert final["result"].status == TaskStatus.DONE
    notify_call = next(c for c in mcp.calls if c[:2] == ("comms", "notify_user"))
    assert notify_call[2]["user_id"] == "E1"


@pytest.mark.asyncio
async def test_unknown_intent_raises() -> None:
    mcp = FakeMCP()
    graph = build_graph(FakeLLM([]), mcp)
    task = _task("not_a_real_intent", {})
    with pytest.raises(ValidationError):
        await graph.ainvoke(new_state(task))
