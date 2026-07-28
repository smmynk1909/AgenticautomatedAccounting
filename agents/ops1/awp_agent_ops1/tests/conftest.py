from __future__ import annotations

from typing import Any

from awp_shared.llm import LLMResponse


class FakeLLM:
    """Mirrors agents/fin1/awp_agent_fin1/tests/conftest.py's FakeLLM."""

    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> LLMResponse:
        self.calls.append({"messages": messages, **kwargs})
        if not self._responses:
            raise AssertionError("FakeLLM.chat called with no scripted response left")
        if len(self._responses) > 1:
            return self._responses.pop(0)
        return self._responses[0]


class FakeMCP:
    """`handlers`: `(server, tool) -> dict | Callable[[dict], dict] | Exception`."""

    def __init__(self, handlers: dict[tuple[str, str], Any] | None = None) -> None:
        self._handlers = handlers or {}
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def call(self, server: str, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((server, tool, args))
        handler = self._handlers.get((server, tool))
        if handler is None:
            return {}
        if isinstance(handler, Exception):
            raise handler
        result: dict[str, Any] = handler(args) if callable(handler) else handler
        return result
