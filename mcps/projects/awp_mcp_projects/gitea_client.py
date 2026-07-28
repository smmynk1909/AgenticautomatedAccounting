"""Thin Gitea REST API client — doc 08 §8's "read-only Gitea API" (doc 10
C12's `Gitea` dependency). Every endpoint used here was verified live
against a real Gitea 1.22 instance during Sprint 10 development, not
assumed from the docs — two real API quirks worth recording:

1. `GET /repos/{owner}/{repo}/compare/{base}...{head}` (the documented
   diff-between-two-refs endpoint) returns commit *metadata* only
   (`{"total_commits": N, "commits": [...]}`), never the actual unified
   diff text — confirmed against Gitea 1.22's own swagger spec
   (`produces: [application/json]`, `$ref: #/responses/Compare"`, no diff
   field). `get_diff` here instead resolves `head` to its commit SHA and
   uses the web route `/{owner}/{repo}/commit/{sha}.diff` (undocumented in
   the API swagger, but a real, stable Gitea route — same one the "Get
   the diff" link on Gitea's own commit page targets), which returns that
   *one* commit's diff against its immediate parent. Multi-commit range
   diffs (`base` genuinely far behind `head`) are not supported —
   documented as a Sprint 10 simplification in DEVIATIONS.md, since no
   Sprint 10 acceptance test (doc 12 §5 cites only 05§5.3,5) exercises
   `get_diff` at all.
2. That `.diff` route only accepts a commit SHA, not a branch/tag name —
   `head` is resolved via `GET .../commits?sha={ref}&limit=1` first
   (confirmed: this endpoint accepts branch names, tags, and SHAs alike).
"""

from __future__ import annotations

import base64
from typing import Any, Protocol

import httpx


class GiteaClientLike(Protocol):
    async def list_repos(self) -> list[dict[str, Any]]: ...
    async def get_file(self, repo: str, path: str, ref: str | None) -> dict[str, Any]: ...
    async def get_tree(self, repo: str, ref: str) -> list[dict[str, Any]]: ...
    async def get_diff(self, repo: str, base: str, head: str) -> str: ...


class GiteaClient:
    def __init__(
        self, base_url: str, token: str, *, client: httpx.AsyncClient | None = None
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(
            headers={"Authorization": f"token {token}"}, timeout=30.0
        )
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def list_repos(self) -> list[dict[str, Any]]:
        r = await self._client.get(f"{self._base_url}/api/v1/repos/search", params={"limit": 50})
        r.raise_for_status()
        data: dict[str, Any] = r.json()
        repos: list[dict[str, Any]] = data.get("data", [])
        return repos

    async def get_file(self, repo: str, path: str, ref: str | None) -> dict[str, Any]:
        params = {"ref": ref} if ref else {}
        r = await self._client.get(
            f"{self._base_url}/api/v1/repos/{repo}/contents/{path}", params=params
        )
        r.raise_for_status()
        data: dict[str, Any] = r.json()
        content = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
        return {"path": data["path"], "sha": data["sha"], "content": content}

    async def get_tree(self, repo: str, ref: str) -> list[dict[str, Any]]:
        r = await self._client.get(
            f"{self._base_url}/api/v1/repos/{repo}/git/trees/{ref}", params={"recursive": "true"}
        )
        r.raise_for_status()
        data: dict[str, Any] = r.json()
        tree: list[dict[str, Any]] = data.get("tree", [])
        return [entry for entry in tree if entry.get("type") == "blob"]

    async def _resolve_commit_sha(self, repo: str, ref: str) -> str:
        r = await self._client.get(
            f"{self._base_url}/api/v1/repos/{repo}/commits", params={"sha": ref, "limit": 1}
        )
        r.raise_for_status()
        commits: list[dict[str, Any]] = r.json()
        if not commits:
            raise ValueError(f"no commits found resolving ref {ref!r} in {repo!r}")
        sha: str = commits[0]["sha"]
        return sha

    async def get_diff(self, repo: str, base: str, head: str) -> str:
        sha = await self._resolve_commit_sha(repo, head)
        r = await self._client.get(f"{self._base_url}/{repo}/commit/{sha}.diff")
        r.raise_for_status()
        return r.text
