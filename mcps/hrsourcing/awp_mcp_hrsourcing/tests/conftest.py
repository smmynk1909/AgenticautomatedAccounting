from __future__ import annotations

import base64
import io
from typing import Any

import pytest
from awp_mcp_base.server import AwpMcpServer
from awp_shared.audit_mw import AuditEvent
from awp_shared.llm import LLMResponse
from fakeredis.aioredis import FakeRedis
from xhtml2pdf import pisa

from awp_mcp_hrsourcing.server import make_hrsourcing_server


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


class NullAuditSink:
    async def log_event(self, event: AuditEvent) -> None:
        pass


@pytest.fixture(autouse=True)
def _dev_auth_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWP_DEV_JWT_SECRET", "test-service-secret-32-bytes-min-xxxx")
    monkeypatch.setenv("AWP_APPROVAL_JWT_SECRET", "test-approval-secret-32-bytes-min-xxxx")
    monkeypatch.setenv("AWP_JWT_ISSUER", "awp-test")


@pytest.fixture
def redis() -> FakeRedis:
    return FakeRedis(decode_responses=True)


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM([])


@pytest.fixture
def hrsourcing_server(redis: FakeRedis, fake_llm: FakeLLM) -> AwpMcpServer:
    return make_hrsourcing_server(redis, NullAuditSink(), fake_llm)  # type: ignore[arg-type]


def make_pdf_b64(text: str) -> str:
    html = f"<html><body><p>{text}</p></body></html>"
    buf = io.BytesIO()
    pisa.CreatePDF(html, dest=buf)
    return base64.b64encode(buf.getvalue()).decode()
