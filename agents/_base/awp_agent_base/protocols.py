"""Structural types for `nodes.py`'s dependency-injection params.

Nodes are typed against these instead of the concrete `awp_shared.llm.LLM` /
`awp_shared.mcpc.MCP` classes so unit tests can pass minimal fakes (no httpx
client, no real gateway) without subclassing — and so a future test double
for e.g. a streaming LLM client still type-checks without inheriting from
the production class.
"""

from __future__ import annotations

from typing import Any, Protocol

from awp_shared.llm import LLMResponse


class LLMLike(Protocol):
    async def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> LLMResponse: ...


class MCPLike(Protocol):
    async def call(self, server: str, tool: str, args: Any) -> dict[str, Any]: ...
