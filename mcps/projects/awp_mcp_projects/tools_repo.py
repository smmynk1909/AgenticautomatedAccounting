"""Repo-read tools — doc 08 §8. `search_code` is deliberately not
implemented here (see DEVIATIONS.md): the actual vector index lives in
Qdrant via `mcp-search` (Sprint 7 infra), and "no MCP server calls another
MCP server" means `index_repo` here can only return chunks, never store
them — the calling agent (OPS-1) feeds `index_repo`'s output into
`mcp-search.upsert_documents` and searches it back via
`mcp-search.search_kb(corpus=f"code:{repo}", ...)`. A `search_code` tool
on this server would just be a second, redundant entry point to the same
Qdrant data mcp-search already owns.
"""

from __future__ import annotations

from typing import Any

from awp_mcp_base.ctx import Ctx
from awp_mcp_base.server import AwpMcpServer
from awp_shared.errors import ValidationError

from awp_mcp_projects.code_chunking import chunk_file
from awp_mcp_projects.gitea_client import GiteaClientLike

# doc 05 §2.4's secrets-scan-before-context guardrail applies to files fed
# to the model; index_repo additionally caps what it will even attempt to
# read, so one huge/binary-looking file can't stall or bloat a whole
# indexing pass.
MAX_INDEXED_FILES = 200
MAX_FILE_BYTES = 200_000
_SKIP_EXTENSIONS = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".tar", ".gz", ".ico", ".woff", ".woff2"}
)


def register_repo_tools(server: AwpMcpServer, gitea: GiteaClientLike) -> None:
    @server.tool()
    async def list_repos(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        repos = await gitea.list_repos()
        return {
            "repos": [
                {
                    "slug": r["full_name"],
                    "description": r.get("description", ""),
                    "default_branch": r.get("default_branch", "main"),
                }
                for r in repos
            ]
        }

    @server.tool()
    async def get_file(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        repo = payload.get("repo")
        path = payload.get("path")
        if not repo or not path:
            raise ValidationError("get_file requires 'repo' and 'path'")
        return await gitea.get_file(repo, path, payload.get("ref"))

    @server.tool()
    async def get_diff(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        repo = payload.get("repo")
        base = payload.get("base")
        head = payload.get("head")
        if not repo or not base or not head:
            raise ValidationError("get_diff requires 'repo', 'base', 'head'")
        diff = await gitea.get_diff(repo, base, head)
        return {"diff": diff}

    @server.tool()
    async def index_repo(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        repo = payload.get("repo")
        if not repo:
            raise ValidationError("index_repo requires 'repo'")
        ref = payload.get("ref", "main")

        entries = await gitea.get_tree(repo, ref)
        chunks: list[dict[str, Any]] = []
        indexed_files = 0
        for entry in entries:
            if indexed_files >= MAX_INDEXED_FILES:
                break
            path = entry["path"]
            if any(path.lower().endswith(ext) for ext in _SKIP_EXTENSIONS):
                continue
            if entry.get("size", 0) > MAX_FILE_BYTES:
                continue
            file_data = await gitea.get_file(repo, path, ref)
            for chunk in chunk_file(path, file_data["content"]):
                chunks.append(
                    {
                        "path": chunk.path,
                        "start_line": chunk.start_line,
                        "end_line": chunk.end_line,
                        "text": chunk.text,
                    }
                )
            indexed_files += 1
        return {"repo": repo, "ref": ref, "files_indexed": indexed_files, "chunks": chunks}

    @server.tool()
    async def ci_status(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        # doc 08 §8 lists `ci_status(repo, ref)` — no CI system exists in
        # this build (no sprint has ever built or scheduled one), so this
        # returns a real "not configured" status rather than fabricating a
        # green/red build result.
        repo = payload.get("repo")
        if not repo:
            raise ValidationError("ci_status requires 'repo'")
        return {"repo": repo, "status": "not_configured"}
