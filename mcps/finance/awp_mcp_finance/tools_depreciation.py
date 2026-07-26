"""Depreciation tool — doc 06 §2.2 month-close's "depreciation run", doc 08
§2. `assets` is caller-supplied (mcp-finance has no direct access to
mcp-erp's asset register) — same reasoning as `tools_payroll.py`'s
docstring. Posts one aggregate journal entry (Depreciation Expense /
Accumulated Depreciation) for the period's total, matching
`db/seed/coa_seed.yaml`'s account codes (5008, 1005).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from awp_mcp_base.ctx import Ctx
from awp_mcp_base.server import AwpMcpServer
from awp_mcp_base.uow import UnitOfWork
from awp_shared.errors import ValidationError
from fincore.depreciation import run_depreciation as fincore_run_depreciation
from fincore.depreciation import total_depreciation
from fincore.models import DepreciableAsset

from awp_mcp_finance.repos.ledger import JournalRepo, PeriodRepo

ACCOUNT_DEPRECIATION_EXPENSE = "5008"
ACCOUNT_ACCUMULATED_DEPRECIATION = "1005"


def register_depreciation_tools(server: AwpMcpServer, uow: UnitOfWork) -> None:
    @server.tool()
    async def run_depreciation(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        period = payload.get("period")
        raw_assets = payload.get("assets")
        if not period or not raw_assets:
            raise ValidationError("run_depreciation requires 'period' and 'assets'")

        assets = [
            DepreciableAsset(
                asset_id=a["asset_id"],
                cost=Decimal(str(a["cost"])),
                method=a["method"],
                rate=Decimal(str(a["rate"])),
                opening_wdv=Decimal(str(a["opening_wdv"])),
            )
            for a in raw_assets
        ]
        lines = fincore_run_depreciation(assets)
        total = total_depreciation(lines)

        entry_id = None
        if total > 0:
            async with uow() as session:
                if period not in await PeriodRepo(session).open_periods():
                    raise ValidationError(f"period {period!r} is not open")
                entry_id = await JournalRepo(session).post(
                    entry_date=datetime.now(UTC).date(),
                    period=period,
                    lines=[
                        {"account": ACCOUNT_DEPRECIATION_EXPENSE, "dr": total},
                        {"account": ACCOUNT_ACCUMULATED_DEPRECIATION, "cr": total},
                    ],
                    ref=f"depreciation-{period}",
                    posted_by=ctx.principal.sub,
                    approval_ref=None,
                )

        return {
            "period": period,
            "lines": [
                {
                    "asset_id": line_obj.asset_id,
                    "opening_wdv": str(line_obj.opening_wdv),
                    "depreciation": str(line_obj.depreciation),
                    "closing_wdv": str(line_obj.closing_wdv),
                }
                for line_obj in lines
            ],
            "total_depreciation": str(total),
            "journal_entry_id": entry_id,
        }
