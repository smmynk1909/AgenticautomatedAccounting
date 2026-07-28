from __future__ import annotations

import json

import pytest
from awp_mcp_base.server import AwpMcpServer
from awp_shared.auth import mint_service_jwt
from awp_shared.errors import ValidationError
from awp_shared.llm import LLMResponse

from awp_mcp_hrsourcing.tests.conftest import FakeLLM, make_pdf_b64


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _token(scopes: list[str]) -> str:
    return mint_service_jwt("HR-1", scopes)


@pytest.mark.asyncio
async def test_extract_resume_returns_text_from_pdf(hrsourcing_server: AwpMcpServer) -> None:
    result = await hrsourcing_server.dispatch_raw(
        "extract_resume",
        {"file_bytes_b64": make_pdf_b64("Asha Rao, Senior Engineer")},
        _headers(_token(["hrsourcing.read"])),
    )
    assert "Asha Rao" in result["text"]
    assert result["blocks"][0]["page"] == 0


@pytest.mark.asyncio
async def test_extract_resume_requires_field(hrsourcing_server: AwpMcpServer) -> None:
    with pytest.raises(ValidationError):
        await hrsourcing_server.dispatch_raw(
            "extract_resume", {}, _headers(_token(["hrsourcing.read"]))
        )


@pytest.mark.asyncio
async def test_extract_resume_rejects_bad_base64(hrsourcing_server: AwpMcpServer) -> None:
    with pytest.raises(ValidationError):
        await hrsourcing_server.dispatch_raw(
            "extract_resume",
            {"file_bytes_b64": "not valid base64!!"},
            _headers(_token(["hrsourcing.read"])),
        )


@pytest.mark.asyncio
async def test_normalize_profile_merges_deterministic_overlap_flag(
    hrsourcing_server: AwpMcpServer, fake_llm: FakeLLM
) -> None:
    llm_profile = {
        "name": "Asha Rao",
        "contact": {"email": "asha@example.com"},
        "total_exp_months": 48,
        "positions": [
            {"org": "Acme", "title": "Engineer", "from": "2022-01", "to": "2023-06", "skills": []},
            {"org": "Globex", "title": "Lead", "from": "2023-01", "to": "2024-01", "skills": []},
        ],
        "education": [],
        "certifications": [],
        "skills_normalized": [],
        "gaps": [],
        "red_flags": [],
        "audit_score": {"completeness": 0.8, "consistency": 0.5, "relevance_to_role": None},
    }
    fake_llm._responses.append(LLMResponse(content=json.dumps(llm_profile)))

    result = await hrsourcing_server.dispatch_raw(
        "normalize_profile",
        {"raw": "Asha Rao resume text..."},
        _headers(_token(["hrsourcing.read"])),
    )
    flag_types = [f["type"] for f in result["profile"]["red_flags"]]
    assert "overlap" in flag_types
    assert result["confidence"]["name"] == 1.0
    assert result["confidence"]["education"] == 0.0


@pytest.mark.asyncio
async def test_normalize_profile_requires_raw(hrsourcing_server: AwpMcpServer) -> None:
    with pytest.raises(ValidationError):
        await hrsourcing_server.dispatch_raw(
            "normalize_profile", {}, _headers(_token(["hrsourcing.read"]))
        )


@pytest.mark.asyncio
async def test_connector_fetch_csv_import_parses_rows(hrsourcing_server: AwpMcpServer) -> None:
    csv_content = "name,email\nAsha Rao,asha@example.com\nBala Iyer,bala@example.com\n"
    result = await hrsourcing_server.dispatch_raw(
        "connector_fetch",
        {"source_id": "csv_import", "csv_content": csv_content, "limit": 10},
        _headers(_token(["hrsourcing.connectors"])),
    )
    assert len(result["profiles"]) == 2
    assert result["profiles"][0]["name"] == "Asha Rao"


@pytest.mark.asyncio
async def test_connector_fetch_internal_db_filters_by_query(
    hrsourcing_server: AwpMcpServer,
) -> None:
    candidates = [
        {"name": "Asha Rao", "skills_normalized": ["Python"]},
        {"name": "Bala Iyer", "skills_normalized": ["Figma"]},
    ]
    result = await hrsourcing_server.dispatch_raw(
        "connector_fetch",
        {"source_id": "internal_db", "query": "python", "candidates": candidates, "limit": 10},
        _headers(_token(["hrsourcing.connectors"])),
    )
    assert len(result["profiles"]) == 1
    assert result["profiles"][0]["name"] == "Asha Rao"


@pytest.mark.asyncio
async def test_connector_fetch_unknown_source_raises(hrsourcing_server: AwpMcpServer) -> None:
    with pytest.raises(ValidationError):
        await hrsourcing_server.dispatch_raw(
            "connector_fetch",
            {"source_id": "linkedin"},
            _headers(_token(["hrsourcing.connectors"])),
        )


@pytest.mark.asyncio
async def test_skill_normalize_matches_fuzzy_and_synonym(
    hrsourcing_server: AwpMcpServer,
) -> None:
    vocabulary = [
        {"id": "sk-py", "name": "Python", "synonyms": ["py"]},
        {"id": "sk-js", "name": "JavaScript", "synonyms": ["js"]},
    ]
    result = await hrsourcing_server.dispatch_raw(
        "skill_normalize",
        {"terms": ["Pythonn", "js", "COBOL"], "vocabulary": vocabulary},
        _headers(_token(["hrsourcing.read"])),
    )
    matches = {m["term"]: m for m in result["matches"]}
    assert matches["Pythonn"]["skill_id"] == "sk-py"
    assert matches["js"]["skill_id"] == "sk-js"
    assert matches["COBOL"]["skill_id"] is None


@pytest.mark.asyncio
async def test_normalize_profile_scope_required(hrsourcing_server: AwpMcpServer) -> None:
    from awp_shared.errors import PermissionDeniedError

    with pytest.raises(PermissionDeniedError):
        await hrsourcing_server.dispatch_raw(
            "normalize_profile", {"raw": "text"}, _headers(_token([]))
        )
