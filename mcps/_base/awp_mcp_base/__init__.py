"""Shared MCP server scaffolding — see docs/11-LLD.md §3 and DEVIATIONS.md #6."""

from awp_mcp_base.ctx import Ctx
from awp_mcp_base.server import AwpMcpServer, make_server

__all__ = ["AwpMcpServer", "Ctx", "make_server"]
