"""mcp-erp server assembly — doc 08 §1. Wires every `tools_*.py` module's
tool handlers onto one `AwpMcpServer`.
"""

from __future__ import annotations

from awp_mcp_base.server import AwpMcpServer, make_server
from awp_mcp_base.uow import UnitOfWork
from awp_shared.audit_mw import AuditSink
from redis.asyncio import Redis

from awp_mcp_erp.tools_assets import register_asset_tools
from awp_mcp_erp.tools_dashboard import register_dashboard_tools
from awp_mcp_erp.tools_people import register_people_tools
from awp_mcp_erp.tools_policies import register_policy_tools
from awp_mcp_erp.tools_tasks import register_task_tools
from awp_mcp_erp.tools_tickets import register_ticket_tools


def make_erp_server(uow: UnitOfWork, redis: Redis, audit_sink: AuditSink) -> AwpMcpServer:
    server = make_server("erp", audit_sink=audit_sink, redis=redis)
    register_people_tools(server, uow, redis)
    register_asset_tools(server, uow, redis)
    register_ticket_tools(server, uow)
    register_task_tools(server, uow)
    register_dashboard_tools(server, uow)
    register_policy_tools(server, uow)
    return server
