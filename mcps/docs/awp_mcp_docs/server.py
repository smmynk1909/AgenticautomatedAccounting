"""mcp-docs's tool surface — doc 08 §3."""

from __future__ import annotations

from awp_mcp_base.server import AwpMcpServer, make_server
from awp_shared.audit_mw import AuditSink
from redis.asyncio import Redis

from awp_mcp_docs.storage import DocStorage
from awp_mcp_docs.tools_extract import register_extract_tools
from awp_mcp_docs.tools_render import register_render_tools
from awp_mcp_docs.tools_store import register_store_tools


def make_docs_server(storage: DocStorage, redis: Redis, audit_sink: AuditSink) -> AwpMcpServer:
    server = make_server("docs", audit_sink=audit_sink, redis=redis)
    register_render_tools(server, storage)
    register_store_tools(server, storage)
    register_extract_tools(server, storage)
    return server
