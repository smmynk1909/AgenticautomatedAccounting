from __future__ import annotations

import os
import time
import uuid

import jwt
import pytest
from awp_mcp_base.server import AwpMcpServer
from awp_shared.auth import mint_approval_token, mint_service_jwt
from awp_shared.errors import ApprovalRequiredError, NotFoundError, ValidationError


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _agent_token(scopes: list[str] | None = None) -> str:
    return mint_service_jwt(
        "HR-1", scopes or ["search.write", "search.read", "search.candidates.read"]
    )


def _user_token_with_role_and_read_scope(role: str) -> str:
    # `mint_user_jwt` hard-codes scopes=[] (real scope-from-role mapping is
    # gateway RBAC, doc 08 §0, not built for search yet) — this test needs
    # both a role (for the ACL check) and the search.read scope (for the
    # tool-level scope check) on one principal, so it mints directly rather
    # than extending the shared helper for one test's sake.
    now = int(time.time())
    claims = {
        "sub": "dev-user",
        "kind": "user",
        "roles": [role],
        "scopes": ["search.read"],
        "iss": os.environ["AWP_JWT_ISSUER"],
        "iat": now,
        "exp": now + 3600,
    }
    return jwt.encode(claims, os.environ["AWP_DEV_JWT_SECRET"], algorithm="HS256")


def _approval(gate: str, payload: dict) -> str:
    return mint_approval_token(
        gate=gate, payload=payload, approvers=["dev-support-lead"], ttl_h=24, jti=str(uuid.uuid4())
    )


@pytest.mark.asyncio
async def test_upsert_then_search_kb_returns_matching_chunk(search_server: AwpMcpServer) -> None:
    await search_server.dispatch_raw(
        "upsert_documents",
        {
            "corpus": "market_intel",
            "docs": [
                {"text": "Python backend engineers command a salary premium in Bangalore."},
                {"text": "Frontend React developer demand is flat quarter over quarter."},
            ],
        },
        _headers(_agent_token()),
    )
    result = await search_server.dispatch_raw(
        "search_kb",
        {"corpus": "market_intel", "query": "Python backend salary", "k": 1},
        _headers(_agent_token()),
    )
    assert len(result["results"]) == 1
    assert "Python" in result["results"][0]["text"]
    assert result["results"][0]["citation"]["chunk_id"]


@pytest.mark.asyncio
async def test_search_kb_acl_filters_non_matching_role(search_server: AwpMcpServer) -> None:
    await search_server.dispatch_raw(
        "upsert_documents",
        {
            "corpus": "fin_kb",
            "docs": [
                {
                    "text": "Board-level compensation strategy notes.",
                    "metadata": {"acl_tags": ["director"]},
                }
            ],
        },
        _headers(_agent_token()),
    )
    visible_to_director = await search_server.dispatch_raw(
        "search_kb",
        {"corpus": "fin_kb", "query": "compensation strategy"},
        _headers(_user_token_with_role_and_read_scope("director")),
    )
    visible_to_employee = await search_server.dispatch_raw(
        "search_kb",
        {"corpus": "fin_kb", "query": "compensation strategy"},
        _headers(_user_token_with_role_and_read_scope("employee")),
    )
    assert len(visible_to_director["results"]) == 1
    assert len(visible_to_employee["results"]) == 0


@pytest.mark.asyncio
async def test_upsert_documents_support_kb_requires_approval(
    search_server: AwpMcpServer,
) -> None:
    with pytest.raises(ApprovalRequiredError):
        await search_server.dispatch_raw(
            "upsert_documents",
            {"corpus": "support_kb", "docs": [{"text": "VPN reset steps."}]},
            _headers(_agent_token()),
        )


@pytest.mark.asyncio
async def test_upsert_documents_support_kb_succeeds_with_valid_token(
    search_server: AwpMcpServer,
) -> None:
    token = _approval("kb_publish", {"corpus": "support_kb"})
    result = await search_server.dispatch_raw(
        "upsert_documents",
        {"corpus": "support_kb", "docs": [{"text": "VPN reset steps."}], "approval_token": token},
        _headers(_agent_token()),
    )
    assert result["chunks_written"] == 1


@pytest.mark.asyncio
async def test_search_candidates_ranks_and_dedupes_by_candidate(
    search_server: AwpMcpServer,
) -> None:
    await search_server.dispatch_raw(
        "upsert_documents",
        {
            "corpus": "resumes",
            "docs": [
                {"id": "cand-1", "text": "Senior Python developer, 6 years, Django and AWS."},
                {"id": "cand-1", "text": "Led a team of 4 backend engineers on a Django project."},
                {"id": "cand-2", "text": "Frontend designer specializing in Figma and CSS."},
            ],
        },
        _headers(_agent_token()),
    )
    result = await search_server.dispatch_raw(
        "search_candidates",
        {"role_profile": {"must_have": ["Python", "Django"], "keywords": ["backend"]}, "k": 5},
        _headers(_agent_token()),
    )
    candidate_ids = [c["candidate_id"] for c in result["candidates"]]
    assert candidate_ids[0] == "cand-1"
    assert candidate_ids.count("cand-1") == 1  # deduped, not one row per chunk


@pytest.mark.asyncio
async def test_embed_returns_one_vector_per_text(search_server: AwpMcpServer) -> None:
    result = await search_server.dispatch_raw(
        "embed", {"texts": ["hello", "world"]}, _headers(_agent_token())
    )
    assert len(result["vectors"]) == 2


@pytest.mark.asyncio
async def test_cluster_groups_identical_vectors_together(search_server: AwpMcpServer) -> None:
    result = await search_server.dispatch_raw(
        "cluster",
        {"vectors": [[1, 0], [1, 0], [0, 1], [0, 1]], "k": 2},
        _headers(_agent_token()),
    )
    assignments = result["assignments"]
    assert assignments[0] == assignments[1]
    assert assignments[2] == assignments[3]
    assert assignments[0] != assignments[2]


@pytest.mark.asyncio
async def test_search_code_not_implemented(search_server: AwpMcpServer) -> None:
    with pytest.raises(NotFoundError):
        await search_server.dispatch_raw(
            "search_code",
            {"project_id": "p1", "query": "x"},
            _headers(_agent_token(["search.code.read"])),
        )


@pytest.mark.asyncio
async def test_upsert_documents_requires_corpus_and_docs(search_server: AwpMcpServer) -> None:
    with pytest.raises(ValidationError):
        await search_server.dispatch_raw(
            "upsert_documents", {"corpus": "market_intel"}, _headers(_agent_token())
        )
