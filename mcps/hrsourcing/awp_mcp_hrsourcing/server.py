"""mcp-hrsourcing server assembly — doc 08 §7."""

from __future__ import annotations

from awp_mcp_base.server import AwpMcpServer, make_server
from awp_shared.audit_mw import AuditSink
from awp_shared.llm import LLM
from redis.asyncio import Redis

from awp_mcp_hrsourcing.tools_hrsourcing import register_hrsourcing_tools


def make_hrsourcing_server(redis: Redis, audit_sink: AuditSink, llm: LLM) -> AwpMcpServer:
    server = make_server("hrsourcing", audit_sink=audit_sink, redis=redis)
    register_hrsourcing_tools(server, llm)
    return server
