"""mcp-docs process entrypoint: `uvicorn awp_mcp_docs.main:app --host 0.0.0.0 --port 8000`."""

from __future__ import annotations

import os

from awp_mcp_base.asgi import build_asgi_app
from awp_shared.audit_mw import RemoteAuditSink
from awp_shared.auth import mint_service_jwt
from awp_shared.bus import make_redis
from awp_shared.config import validate_all
from awp_shared.mcpc import MCP
from fastapi import FastAPI
from minio import Minio

from awp_mcp_docs.server import make_docs_server
from awp_mcp_docs.storage import DocStorage

validate_all()

_minio_client = Minio(
    os.environ["MINIO_ENDPOINT"],
    access_key=os.environ["MINIO_ROOT_USER"],
    secret_key=os.environ["MINIO_ROOT_PASSWORD"],
    secure=os.environ.get("MINIO_SECURE", "false").lower() == "true",
)
_storage = DocStorage(_minio_client, os.environ["MINIO_BUCKET"])
_storage.ensure_bucket()

_redis = make_redis(os.environ["REDIS_URL"])

_audit_mcp = MCP(
    {"audit": os.environ["MCP_AUDIT_URL"]},
    principal_jwt_provider=lambda: mint_service_jwt("docs-service", ["audit.write"]),
)
_audit_sink = RemoteAuditSink(_audit_mcp)

app: FastAPI = build_asgi_app(make_docs_server(_storage, _redis, _audit_sink))
