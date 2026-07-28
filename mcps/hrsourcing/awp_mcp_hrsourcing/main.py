"""mcp-hrsourcing process entrypoint:
`uvicorn awp_mcp_hrsourcing.main:app --host 0.0.0.0 --port 8000`.
"""

from __future__ import annotations

import os

from awp_mcp_base.asgi import build_asgi_app
from awp_shared.audit_mw import RemoteAuditSink
from awp_shared.auth import mint_service_jwt
from awp_shared.bus import make_redis
from awp_shared.config import validate_all
from awp_shared.llm import LLM
from awp_shared.mcpc import MCP
from fastapi import FastAPI

from awp_mcp_hrsourcing.server import make_hrsourcing_server

validate_all()

_redis = make_redis(os.environ["REDIS_URL"])

_audit_mcp = MCP(
    {"audit": os.environ["MCP_AUDIT_URL"]},
    principal_jwt_provider=lambda: mint_service_jwt("hrsourcing-service", ["audit.write"]),
)
_audit_sink = RemoteAuditSink(_audit_mcp)

_llm = LLM(
    os.environ["MODEL_GATEWAY_URL"],
    os.environ["MODEL_SMALL"],
    # timeout_s=600 — CPU-inference reasoning, see
    # agents/hr1/awp_agent_hr1/main.py's LLM instantiation comment, bumped
    # further than that 180s: this host's Ollama measured ~1.45 tok/s during
    # bring-up (no AVX2 fast path under this WSL2/Docker Desktop setup), so a
    # guided-JSON "extract" completion (1536 max_tokens) can take several
    # minutes even for a well-formed response, before any repair round.
    timeout_s=600.0,
)

app: FastAPI = build_asgi_app(make_hrsourcing_server(_redis, _audit_sink, _llm))
