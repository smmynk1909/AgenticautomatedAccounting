"""mcp-search server assembly — doc 08 §4."""

from __future__ import annotations

from awp_mcp_base.server import AwpMcpServer, make_server
from awp_mcp_base.uow import UnitOfWork
from awp_shared.audit_mw import AuditSink
from redis.asyncio import Redis

from awp_mcp_search.embeddings import Embedder
from awp_mcp_search.qdrant_store import QdrantStore
from awp_mcp_search.tools_search import register_search_tools


def make_search_server(
    uow: UnitOfWork,
    redis: Redis,
    audit_sink: AuditSink,
    store: QdrantStore,
    embedder: Embedder,
) -> AwpMcpServer:
    server = make_server("search", audit_sink=audit_sink, redis=redis)
    register_search_tools(server, uow, redis, store, embedder)
    return server
