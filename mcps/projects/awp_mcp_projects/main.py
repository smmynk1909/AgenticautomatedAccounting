"""mcp-projects process entrypoint:
`uvicorn awp_mcp_projects.main:app --host 0.0.0.0 --port 8000`."""

from __future__ import annotations

import os

from awp_mcp_base.asgi import build_asgi_app
from awp_mcp_base.uow import UnitOfWork, make_engine
from awp_shared.audit_mw import RemoteAuditSink
from awp_shared.auth import mint_service_jwt
from awp_shared.bus import make_redis
from awp_shared.config import validate_all
from awp_shared.mcpc import MCP
from fastapi import FastAPI

from awp_mcp_projects.gitea_client import GiteaClient
from awp_mcp_projects.server import make_projects_server

validate_all()

_engine = make_engine(os.environ["DATABASE_URL"])
_uow = UnitOfWork(_engine)
_redis = make_redis(os.environ["REDIS_URL"])

_audit_mcp = MCP(
    {"audit": os.environ["MCP_AUDIT_URL"]},
    principal_jwt_provider=lambda: mint_service_jwt("projects-service", ["audit.write"]),
)
_audit_sink = RemoteAuditSink(_audit_mcp)

_gitea = GiteaClient(os.environ["GITEA_URL"], os.environ["GITEA_ADMIN_TOKEN"])

app: FastAPI = build_asgi_app(make_projects_server(_uow, _redis, _audit_sink, _gitea))
