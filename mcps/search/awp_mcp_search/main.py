"""mcp-search process entrypoint: `uvicorn awp_mcp_search.main:app --host 0.0.0.0 --port 8000`."""

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
from qdrant_client import AsyncQdrantClient

from awp_mcp_search.embeddings import OllamaEmbedder
from awp_mcp_search.qdrant_store import QdrantStore
from awp_mcp_search.server import make_search_server

validate_all()

_engine = make_engine(os.environ["DATABASE_URL"])
_uow = UnitOfWork(_engine)
_redis = make_redis(os.environ["REDIS_URL"])

_audit_mcp = MCP(
    {"audit": os.environ["MCP_AUDIT_URL"]},
    principal_jwt_provider=lambda: mint_service_jwt("search-service", ["audit.write"]),
)
_audit_sink = RemoteAuditSink(_audit_mcp)

_qdrant_client = AsyncQdrantClient(url=os.environ["QDRANT_URL"])
_store = QdrantStore(_qdrant_client)
_embedder = OllamaEmbedder(os.environ["MODEL_GATEWAY_URL"], os.environ["MODEL_EMB"])

app: FastAPI = build_asgi_app(make_search_server(_uow, _redis, _audit_sink, _store, _embedder))
