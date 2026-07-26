"""FIN-1d TaxDesk — doc 06 §2.4. `resolve_gross_annual` reuses the same
`salary_bands.mid` stand-in `payroll_flow.py` uses for real per-employee
comp data (see that module's docstring) — TDS projection and regime
comparison both need an annual income figure, which `compute_tax`'s
payload (`ComputeTaxIn`: emp_id/fy/kind) doesn't carry directly.
"""

from __future__ import annotations

from decimal import Decimal

from awp_agent_base.protocols import MCPLike

TAX_KINDS = frozenset({"tds_projection", "regime_comparison", "gst_worksheet", "advance_tax"})


async def resolve_gross_annual(mcp: MCPLike, emp_id: str) -> Decimal:
    employee = await mcp.call("erp", "get_employee", {"emp_id": emp_id})
    bands = await mcp.call(
        "erp", "query_policies", {"domain": "salary_bands", "grade": employee["grade"]}
    )
    policies = bands.get("policies", [])
    return Decimal(str(policies[0]["mid"])) if policies else Decimal("600000")
