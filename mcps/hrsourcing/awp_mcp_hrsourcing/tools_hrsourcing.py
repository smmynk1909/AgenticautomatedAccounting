"""mcp-hrsourcing tools — doc 08 §7."""

from __future__ import annotations

from typing import Any

from awp_mcp_base.ctx import Ctx
from awp_mcp_base.server import AwpMcpServer
from awp_shared.errors import ValidationError
from awp_shared.llm import LLM

from awp_mcp_hrsourcing.extraction import extract_resume_text
from awp_mcp_hrsourcing.normalize import normalize_profile as run_normalize_profile
from awp_mcp_hrsourcing.skills import normalize_skills
from awp_mcp_hrsourcing.sources import fetch_from_source


def register_hrsourcing_tools(server: AwpMcpServer, llm: LLM) -> None:
    @server.tool()
    async def extract_resume(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        file_bytes_b64 = payload.get("file_bytes_b64")
        if not file_bytes_b64:
            raise ValidationError("extract_resume requires 'file_bytes_b64'")
        return extract_resume_text(file_bytes_b64)

    @server.tool()
    async def normalize_profile(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        raw = payload.get("raw")
        if not raw:
            raise ValidationError("normalize_profile requires 'raw'")
        return await run_normalize_profile(llm, raw)

    @server.tool()
    async def connector_fetch(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        return fetch_from_source(payload)

    @server.tool()
    async def skill_normalize(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        terms = payload.get("terms")
        vocabulary = payload.get("vocabulary")
        if not terms or vocabulary is None:
            raise ValidationError("skill_normalize requires 'terms' and 'vocabulary'")
        return {"matches": normalize_skills(terms, vocabulary)}
