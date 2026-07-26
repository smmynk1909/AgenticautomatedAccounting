"""mcp-comms's tool surface — doc 08 §1, doc 07 §4."""

from __future__ import annotations

from awp_mcp_base.server import AwpMcpServer, make_server
from awp_mcp_base.uow import UnitOfWork
from awp_shared.audit_mw import AuditSink
from redis.asyncio import Redis

from awp_mcp_comms.tools_notify import register_notify_tools


def make_comms_server(uow: UnitOfWork, redis: Redis, audit_sink: AuditSink) -> AwpMcpServer:
    server = make_server("comms", audit_sink=audit_sink, redis=redis)
    register_notify_tools(server, uow)
    return server
