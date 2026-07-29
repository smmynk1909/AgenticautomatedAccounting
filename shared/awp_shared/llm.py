"""LLM client — doc 11 §1.4 contract, served by Ollama per DEVIATIONS.md #1.

`LLM.chat` targets Ollama's OpenAI-compatible `/chat/completions` endpoint
directly (no nginx model-gw — Ollama already multiplexes models by name on
one port). Everything downstream of this module (agent graph nodes) is
written against `LLM`/`LLMResponse`/`ToolCall`, so pointing `gateway_url` at
a real vLLM `model-gw` later is a config change, not a code change.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from typing import Any

import httpx
import structlog
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from awp_shared.errors import UpstreamError, ValidationError
from awp_shared.metrics import llm_call_duration_seconds, llm_calls_total
from awp_shared.tracing import start_span

logger = structlog.get_logger(__name__)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# doc 01 §3 sampling defaults, keyed by task type. `models.yaml` carries the
# same table for ops/config visibility; this literal is the code-level
# fallback so `awp_shared` has zero required config-file dependency.
SAMPLING: dict[str, tuple[float, float, int]] = {
    "plan": (0.1, 0.9, 1024),
    "classify": (0.0, 1.0, 128),
    "draft": (0.6, 0.95, 2048),
    "extract": (0.0, 1.0, 1536),
    "code": (0.2, 0.95, 4096),
}

TRANSPORT_RETRIES = 2
_RETRY_BACKOFF_S = (0.5, 1.5)


class SamplingProfile(BaseModel):
    temperature: float = 0.1
    top_p: float = 0.9
    max_tokens: int = 1024

    @classmethod
    def for_task(cls, task: str) -> SamplingProfile:
        temp, top_p, max_tokens = SAMPLING.get(task, SAMPLING["plan"])
        return cls(temperature=temp, top_p=top_p, max_tokens=max_tokens)


class ModelBinding(BaseModel):
    planner: str = "M-GEN"
    extractor: str = "M-SMALL"
    coder: str | None = None
    classifier: str | None = None
    summarizer: str | None = None


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any]


class LLMResponse(BaseModel):
    content: str | None = None
    tool_calls: list[ToolCall] = []
    raw: dict[str, Any] = {}


class ToolSchema(BaseModel):
    """OpenAI-style function tool schema, e.g. {"type": "function", "function": {...}}."""

    type: str = "function"
    function: dict[str, Any]


class LLM:
    def __init__(
        self,
        gateway_url: str,
        model: str,
        defaults: SamplingProfile | None = None,
        *,
        client: httpx.AsyncClient | None = None,
        timeout_s: float = 60.0,
    ) -> None:
        self._base_url = gateway_url.rstrip("/")
        self._model = model
        self._defaults = defaults or SamplingProfile()
        self._client = client or httpx.AsyncClient(timeout=timeout_s)
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[ToolSchema | dict[str, Any]] | None = None,
        guided_json: type[BaseModel] | None = None,
        **overrides: Any,
    ) -> LLMResponse:
        profile = (
            SamplingProfile.for_task(overrides.pop("profile", None) or "plan")
            if overrides.get("profile")
            else self._defaults
        )
        body: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": overrides.get("temperature", profile.temperature),
            "top_p": overrides.get("top_p", profile.top_p),
            "max_tokens": overrides.get("max_tokens", profile.max_tokens),
            "stream": False,
        }
        if tools:
            body["tools"] = [t.model_dump() if isinstance(t, ToolSchema) else t for t in tools]
        if guided_json is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": guided_json.__name__,
                    "schema": guided_json.model_json_schema(),
                },
            }

        prompt_hash = _sha256(json.dumps(messages, sort_keys=True, default=str))
        start = time.monotonic()
        status = "ok"
        try:
            with start_span("llm.chat", model=self._model):
                raw = await self._post_with_retries(body)
                resp = self._parse(raw)

                if guided_json is not None and resp.content is not None:
                    resp = await self._repair_if_invalid_json(body, resp, guided_json)
        except Exception:
            status = "error"
            raise
        finally:
            duration = time.monotonic() - start
            llm_calls_total.labels(self._model, status).inc()
            llm_call_duration_seconds.labels(self._model).observe(duration)
            # doc 00 §7: "LLM calls logged with prompt/response hashes" — hashes,
            # never raw content, so this line is safe to ship to a log
            # aggregator without becoming a second copy of PII/candidate data.
            logger.info(
                "llm.call",
                model=self._model,
                status=status,
                duration_s=round(duration, 3),
                prompt_sha256=prompt_hash,
                response_sha256=_sha256(resp.content or "") if status == "ok" else None,
            )

        return resp

    async def _post_with_retries(self, body: dict[str, Any]) -> dict[str, Any]:
        last_exc: Exception | None = None
        for attempt in range(TRANSPORT_RETRIES + 1):
            try:
                r = await self._client.post(f"{self._base_url}/chat/completions", json=body)
                r.raise_for_status()
                data: dict[str, Any] = r.json()
                return data
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                last_exc = exc
                logger.warning("llm.transport_retry", attempt=attempt, error=str(exc))
                if attempt < TRANSPORT_RETRIES:
                    await asyncio.sleep(_RETRY_BACKOFF_S[min(attempt, len(_RETRY_BACKOFF_S) - 1)])
        raise UpstreamError(f"model gateway unreachable after retries: {last_exc}")

    def _parse(self, raw: dict[str, Any]) -> LLMResponse:
        try:
            choice = raw["choices"][0]["message"]
        except (KeyError, IndexError) as exc:
            raise UpstreamError(f"malformed model gateway response: {raw!r}") from exc

        tool_calls: list[ToolCall] = []
        for tc in choice.get("tool_calls") or []:
            fn = tc.get("function", {})
            try:
                args = json.loads(fn.get("arguments", "{}"))
            except json.JSONDecodeError:
                args = {"_raw": fn.get("arguments", "")}
            tool_calls.append(
                ToolCall(id=tc.get("id", ""), name=fn.get("name", ""), arguments=args)
            )

        return LLMResponse(content=choice.get("content"), tool_calls=tool_calls, raw=raw)

    async def _repair_if_invalid_json(
        self, body: dict[str, Any], resp: LLMResponse, model: type[BaseModel]
    ) -> LLMResponse:
        """doc 11 §5.4: one repair round on schema-invalid output, then fail."""
        try:
            model.model_validate_json(resp.content or "")
            return resp
        except PydanticValidationError as exc:
            logger.warning("llm.guided_json_repair", model=model.__name__, error=str(exc))
            repair_messages = [
                *body["messages"],
                {"role": "assistant", "content": resp.content or ""},
                {
                    "role": "user",
                    "content": (
                        f"Your previous output was invalid for schema {model.__name__}: {exc}. "
                        "Return ONLY corrected JSON matching the schema, nothing else."
                    ),
                },
            ]
            repaired_body = {**body, "messages": repair_messages}
            raw = await self._post_with_retries(repaired_body)
            repaired = self._parse(raw)
            try:
                model.model_validate_json(repaired.content or "")
            except PydanticValidationError as exc2:
                raise ValidationError(
                    f"model output still invalid for {model.__name__} after repair round: {exc2}"
                ) from exc2
            return repaired
