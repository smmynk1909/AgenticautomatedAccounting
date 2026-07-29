"""Patch-artifact and secrets-scan tools — doc 08 §8."""

from __future__ import annotations

import uuid
from typing import Any

from awp_mcp_base.ctx import Ctx
from awp_mcp_base.server import AwpMcpServer
from awp_mcp_base.uow import UnitOfWork
from awp_shared.errors import ValidationError

from awp_mcp_projects.repos.patch import PatchArtifactRepo
from awp_mcp_projects.secrets_scan import redact_text, scan_text


def register_patch_tools(server: AwpMcpServer, uow: UnitOfWork) -> None:
    @server.tool()
    async def suggest_patch(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        # doc 08 §8: "patch artifact for human application (no direct
        # commits)" — this tool only persists the artifact; nothing in
        # this codebase ever pushes it to Gitea.
        repo = payload.get("repo")
        base_ref = payload.get("base_ref")
        patch_text = payload.get("patch")
        rationale = payload.get("rationale")
        if not repo or not base_ref or not patch_text or not rationale:
            raise ValidationError("suggest_patch requires 'repo', 'base_ref', 'patch', 'rationale'")
        patch_id = str(uuid.uuid4())
        async with uow() as session:
            await PatchArtifactRepo(session).insert(
                {
                    "id": patch_id,
                    "repo_slug": repo,
                    "base_ref": base_ref,
                    "patch_text": patch_text,
                    "rationale": rationale,
                    "proposed_by": ctx.principal.sub,
                }
            )
        return {"patch_id": patch_id, "status": "proposed"}

    @server.tool()
    async def secrets_scan(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        text = payload.get("text")
        if text is None:
            raise ValidationError("secrets_scan requires 'text'")
        findings = scan_text(text)
        return {
            "findings": [
                {"kind": f.kind, "line": f.line, "match_preview": f.match_preview} for f in findings
            ],
            "clean": not findings,
            "redacted_text": redact_text(text),
        }
