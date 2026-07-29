"""OPS-1d CodeAssist — doc 05 §2.4. `chat`/`generate`/`explain`/`refactor`
are free-text M-CODE completions; `review` is the one mode with a
structured contract (`{bugs[], security[], style[], tests_missing[]}` per
the doc) via `guided_json`. Every mode's context (repo file content, diff
text) is expected to have already passed `output_filter`-style vetting
before reaching here — specifically `secrets_scan` (doc: "secrets scanner
runs on all context before it reaches the model") — `nodes.py`'s node
enforces that ordering, not this module (same "agent decides when to gate"
split as every other guardrail in this codebase).
"""

from __future__ import annotations

from datetime import date

from awp_agent_base.protocols import LLMLike, MCPLike
from awp_shared.errors import ValidationError
from awp_shared.llm import LLMResponse
from pydantic import BaseModel, Field

_VALID_MODES = frozenset({"chat", "review", "generate", "explain", "refactor"})


class CodeReview(BaseModel):
    bugs: list[str] = Field(default_factory=list)
    security: list[str] = Field(default_factory=list)
    style: list[str] = Field(default_factory=list)
    tests_missing: list[str] = Field(default_factory=list)


def code_corpus_name(repo_slug: str) -> str:
    """doc 09 §1's Qdrant collection convention is `code_{project}` — a
    literal `owner/name` Gitea slug (e.g. `awp-admin/awp-sample-svc`) can't
    be used as-is: Qdrant's REST API takes the collection name as a raw URL
    path segment, so an embedded `/` splits the path and every call 404s
    (live-verified — `qdrant_client.http.exceptions.UnexpectedResponse: 404`
    on `collection_exists`, no unit test catches this since tests never hit
    a real Qdrant server, see `qdrant_store.py`'s own docstring on that).
    `/` -> `_` keeps the name human-legible and collapses to the doc's
    convention for a single-segment repo slug."""
    return f"code_{repo_slug.replace('/', '_')}"


async def has_repo_access(mcp: MCPLike, emp_id: str, project_id: str) -> bool:
    """doc 05 §2.4: "per-project ACL — an engineer only reaches repos
    they're allocated to." Allocation, not role or department — the same
    `allocations` table OPS-1a's `assign_employee_project` writes to
    (Sprint 9), reused rather than a new ACL concept invented for
    CodeAssist specifically."""
    result = await mcp.call(
        "erp",
        "query_allocations",
        {"emp_id": emp_id, "project_id": project_id, "active_on": date.today().isoformat()},
    )
    return bool(result.get("allocations"))


_SYSTEM_PROMPTS = {
    "chat": (
        "You are a coding assistant answering questions about a codebase. "
        "Ground every answer in the repo context given to you — if the "
        "context doesn't contain the answer, say so rather than guessing. "
        "Never include secrets, credentials, or .env contents in your answer."
    ),
    "generate": (
        "You generate code (functions, tests, or boilerplate) following the "
        "conventions shown in the repo context. Output your suggestion as a "
        "patch/diff-style code block — never claim to have committed or "
        "applied anything; the engineer applies it themselves."
    ),
    "explain": (
        "You explain the given code clearly and concisely, grounded only in "
        "what the code actually does — never invent behavior it doesn't have."
    ),
    "refactor": (
        "You refactor the given code per the engineer's instruction. Output "
        "the refactored code as a patch/diff-style suggestion, and briefly "
        "note what changed and why. Never claim to have committed anything."
    ),
}

_REVIEW_SYSTEM_PROMPT = """You review a code diff. Rules:
1. Every finding must cite a real line from the diff — never invent an issue.
2. Categorize each finding as exactly one of: bugs, security, style,
   tests_missing.
3. An empty category means you found nothing there — do not pad with
   filler findings.
4. Output must match the CodeReview JSON schema exactly."""


async def run_mode(llm: LLMLike, mode: str, context: str, instruction: str) -> CodeReview | str:
    if mode not in _VALID_MODES:
        raise ValidationError(f"unknown CodeAssist mode: {mode!r} (known: {sorted(_VALID_MODES)})")

    if mode == "review":
        resp: LLMResponse = await llm.chat(
            messages=[
                {"role": "system", "content": _REVIEW_SYSTEM_PROMPT},
                {"role": "user", "content": f"Diff:\n\n{context}\n\nInstruction: {instruction}"},
            ],
            guided_json=CodeReview,
            profile="code",
        )
        return CodeReview.model_validate_json(resp.content or "{}")

    user_content = f"Repo context:\n\n{context}\n\nInstruction: {instruction}"
    resp = await llm.chat(
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPTS[mode]},
            {"role": "user", "content": user_content},
        ],
        profile="code",
    )
    return (resp.content or "").strip()
