"""mcp-projects server assembly — doc 08. Wires every `tools_*.py`
module's tool handlers onto one `AwpMcpServer`.
"""

from __future__ import annotations

from awp_mcp_base.server import AwpMcpServer, make_server
from awp_mcp_base.uow import UnitOfWork
from awp_shared.audit_mw import AuditSink
from redis.asyncio import Redis

from awp_mcp_projects.gitea_client import GiteaClientLike
from awp_mcp_projects.tools_issues import register_issue_tools
from awp_mcp_projects.tools_patches import register_patch_tools
from awp_mcp_projects.tools_repo import register_repo_tools


def make_projects_server(
    uow: UnitOfWork, redis: Redis, audit_sink: AuditSink, gitea: GiteaClientLike
) -> AwpMcpServer:
    server = make_server("projects", audit_sink=audit_sink, redis=redis)
    register_issue_tools(server, uow)
    register_repo_tools(server, gitea)
    register_patch_tools(server, uow)
    return server
