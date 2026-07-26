"""mcp-finance server assembly — doc 08 §2. Wires every `tools_*.py`
module's tool handlers onto one `AwpMcpServer`.
"""

from __future__ import annotations

from awp_mcp_base.server import AwpMcpServer, make_server
from awp_mcp_base.uow import UnitOfWork
from awp_shared.audit_mw import AuditSink
from redis.asyncio import Redis

from awp_mcp_finance.tools_cashflow import register_cashflow_tools
from awp_mcp_finance.tools_depreciation import register_depreciation_tools
from awp_mcp_finance.tools_invoice import register_invoice_tools
from awp_mcp_finance.tools_ledger import register_ledger_tools
from awp_mcp_finance.tools_payroll import register_payroll_tools
from awp_mcp_finance.tools_reconcile import register_reconcile_tools
from awp_mcp_finance.tools_tax import register_tax_tools


def make_finance_server(uow: UnitOfWork, redis: Redis, audit_sink: AuditSink) -> AwpMcpServer:
    server = make_server("finance", audit_sink=audit_sink, redis=redis)
    register_ledger_tools(server, uow, redis)
    register_payroll_tools(server, uow, redis)
    register_invoice_tools(server, uow, redis)
    register_tax_tools(server, uow)
    register_reconcile_tools(server, uow, redis)
    register_depreciation_tools(server, uow)
    register_cashflow_tools(server)
    return server
