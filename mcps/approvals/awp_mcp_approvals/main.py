"""mcp-approvals process entrypoint: `uvicorn awp_mcp_approvals.main:app --host 0.0.0.0 --port 8000`.

Only the agent-facing surface (`request_approval`, `get_approval_status`) is
mounted here. `approve`/`reject` (`service.py`) are wired into the gateway's
human-authenticated routes at Sprint 3, never into this ASGI app — see
`service.py`'s docstring.
"""

from __future__ import annotations

import os

from fastapi import FastAPI

from awp_shared.audit_mw import RemoteAuditSink
from awp_shared.auth import mint_service_jwt
from awp_shared.bus import make_redis
from awp_shared.config import validate_all
from awp_shared.mcpc import MCP

from awp_mcp_base.asgi import build_asgi_app
from awp_mcp_base.uow import UnitOfWork, make_engine

from awp_mcp_approvals.server import make_approvals_server

validate_all()

_engine = make_engine(os.environ["DATABASE_URL"])
_uow = UnitOfWork(_engine)
_redis = make_redis(os.environ["REDIS_URL"])

_audit_mcp = MCP(
    {"audit": os.environ["MCP_AUDIT_URL"]},
    principal_jwt_provider=lambda: mint_service_jwt("approvals-service", ["audit.write"]),
)
_audit_sink = RemoteAuditSink(_audit_mcp)

app: FastAPI = build_asgi_app(make_approvals_server(_uow, _redis, _audit_sink))
