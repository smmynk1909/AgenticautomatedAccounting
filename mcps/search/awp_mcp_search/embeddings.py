"""M-EMB (bge-m3) embedding client — doc 08 §4, served by Ollama per
DEVIATIONS.md #1. `awp_shared.llm.LLM` only wraps `/chat/completions`; this
is the same pattern applied to Ollama's OpenAI-compatible `/embeddings`
endpoint, kept local to mcp-search since it's the only server that needs it.
"""

from __future__ import annotations

from typing import Protocol

import httpx
import structlog
from awp_shared.errors import UpstreamError

logger = structlog.get_logger(__name__)


class Embedder(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class OllamaEmbedder:
    def __init__(
        self,
        gateway_url: str,
        model: str,
        *,
        client: httpx.AsyncClient | None = None,
        timeout_s: float = 180.0,
    ) -> None:
        # timeout_s=180 default (was 60) — CPU-inference reasoning, see
        # agents/hr1/awp_agent_hr1/main.py's LLM instantiation comment.
        # Live-verified (Sprint 10): embedding calls timed out at 60s when
        # Ollama was concurrently busy with an M-CODE completion on this
        # host — `embed()` isn't slow in isolation, but this host has no
        # request queue/priority between models sharing one CPU, so a
        # concurrent generative call can starve an embedding call past the
        # old default.
        self._base_url = gateway_url.rstrip("/")
        self._model = model
        self._client = client or httpx.AsyncClient(timeout=timeout_s)
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            r = await self._client.post(
                f"{self._base_url}/embeddings", json={"model": self._model, "input": texts}
            )
            r.raise_for_status()
            data = r.json()
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            raise UpstreamError(f"embedding gateway unreachable: {exc}") from exc
        try:
            rows = sorted(data["data"], key=lambda d: d["index"])
            return [row["embedding"] for row in rows]
        except (KeyError, IndexError) as exc:
            raise UpstreamError(f"malformed embedding gateway response: {data!r}") from exc
