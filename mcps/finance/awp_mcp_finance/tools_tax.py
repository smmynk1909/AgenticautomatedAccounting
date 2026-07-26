"""Tax tools — doc 06 §2.4, doc 08 §2.

`compute_tds_projection`/`compare_regimes` take `gross_annual` directly as
input rather than looking an employee up — same reasoning as
`tools_payroll.py`'s docstring: mcp-finance has no direct access to
mcp-erp's employee/comp tables, so the caller (FIN-1, Sprint 6) supplies
the figure it already has.

`gst_worksheet`/`advance_tax_estimate` are simplified: GSTR-1/3B prep
normally needs invoice-level HSN/SAC breakdowns and a full return-filing
pipeline doc 06 §2.4 explicitly scopes to "the system prepares computations
and worksheets ... filings ... reviewed by the company's human accountant" —
this build produces the account-level liability/credit summary a human
accountant would start from, not a filing-ready return. `advance_tax_estimate`
applies a flat corporate tax rate to trailing P&L as its "projected annual
tax liability" input — a documented placeholder for the real driver (doc 06
§2.5's FPnA cashflow/budget forecast, not built in this sprint) rather than
FinCore reaching into data it doesn't have.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from awp_mcp_base.ctx import Ctx
from awp_mcp_base.server import AwpMcpServer
from awp_mcp_base.uow import UnitOfWork
from awp_shared.errors import ValidationError
from fincore.models import AnnualIncome, Declarations
from fincore.tables import load_tax_tables
from fincore.tax import compare_regimes as fincore_compare_regimes
from fincore.tax import project_tds

from awp_mcp_finance.repos.ledger import AccountRepo, JournalRepo

# doc 06 §2.4: "advance-tax quarterly estimate from FPnA forecast" — the
# real FPnA-driven input doesn't exist yet (deferred, see module docstring);
# this flat rate is a stand-in for whatever `financial_requirement_report`
# eventually supplies.
PLACEHOLDER_CORPORATE_TAX_RATE = Decimal("0.25")

ADVANCE_TAX_CUMULATIVE_PCT = {
    "Q1": Decimal("0.15"),
    "Q2": Decimal("0.45"),
    "Q3": Decimal("0.75"),
    "Q4": Decimal("1.00"),
}
QUARTER_ORDER = ["Q1", "Q2", "Q3", "Q4"]


def _declarations_from_dict(d: dict[str, Any] | None) -> Declarations:
    d = d or {}
    return Declarations(
        section_80c=Decimal(str(d.get("section_80c", "0"))),
        section_80d=Decimal(str(d.get("section_80d", "0"))),
        hra_exemption=Decimal(str(d.get("hra_exemption", "0"))),
        standard_deduction=Decimal(str(d.get("standard_deduction", "50000"))),
    )


def register_tax_tools(server: AwpMcpServer, uow: UnitOfWork) -> None:
    @server.tool()
    async def compute_tds_projection(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        fy = payload.get("fy")
        regime = payload.get("regime")
        gross_annual = payload.get("gross_annual")
        if not fy or not regime or gross_annual is None:
            raise ValidationError(
                "compute_tds_projection requires 'fy', 'regime', 'gross_annual'"
            )
        tables = load_tax_tables(datetime.now(UTC).date())
        income = AnnualIncome(
            gross_annual=Decimal(str(gross_annual)),
            other_income=Decimal(str(payload.get("other_income", "0"))),
        )
        decl = _declarations_from_dict(payload.get("declarations"))
        projection = project_tds(
            fy,
            regime,
            income,
            decl,
            tables,
            months_elapsed=payload.get("months_elapsed", 0),
            tds_deducted_so_far=Decimal(str(payload.get("tds_deducted_so_far", "0"))),
        )
        return {
            "fy": projection.fy,
            "regime": projection.regime,
            "annual_taxable_income": str(projection.annual_taxable_income),
            "annual_tax": str(projection.annual_tax),
            "months_remaining": projection.months_remaining,
            "monthly_tds": str(projection.monthly_tds),
        }

    @server.tool()
    async def compare_regimes(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        fy = payload.get("fy")
        gross_annual = payload.get("gross_annual")
        if not fy or gross_annual is None:
            raise ValidationError("compare_regimes requires 'fy', 'gross_annual'")
        tables = load_tax_tables(datetime.now(UTC).date())
        income = AnnualIncome(gross_annual=Decimal(str(gross_annual)))
        decl_old = _declarations_from_dict(payload.get("declarations_old"))
        decl_new = _declarations_from_dict(payload.get("declarations_new"))
        cmp = fincore_compare_regimes(fy, income, decl_old, decl_new, tables)
        return {
            "fy": cmp.fy,
            "old_regime_tax": str(cmp.old_regime_tax),
            "new_regime_tax": str(cmp.new_regime_tax),
            "recommended": cmp.recommended,
        }

    @server.tool()
    async def gst_worksheet(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        period = payload.get("period")
        return_type = payload.get("return_type", "GSTR-3B")
        if not period:
            raise ValidationError("gst_worksheet requires 'period'")
        async with uow() as session:
            balances = await JournalRepo(session).trial_balance(period)
        output_liability = -balances.get("2007", Decimal("0"))  # liability account: credit-normal
        input_credit = balances.get("1006", Decimal("0"))  # asset account: debit-normal
        return {
            "period": period,
            "return_type": return_type,
            "output_liability": str(output_liability),
            "input_credit": str(input_credit),
            "net_payable": str(max(output_liability - input_credit, Decimal("0"))),
        }

    @server.tool()
    async def advance_tax_estimate(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        fy = payload.get("fy")
        quarter = payload.get("quarter")
        if not fy or quarter not in ADVANCE_TAX_CUMULATIVE_PCT:
            raise ValidationError("advance_tax_estimate requires 'fy' and quarter in Q1..Q4")

        fy_start_month = f"{fy[:4]}-04"
        async with uow() as session:
            journal_repo = JournalRepo(session)
            account_repo = AccountRepo(session)
            all_codes = await account_repo.all_codes()
            type_by_code = {code: await account_repo.get_type(code) for code in all_codes}
            income = Decimal("0")
            expense = Decimal("0")
            for month_offset in range(12):
                month = _shift_month(fy_start_month, month_offset)
                balances = await journal_repo.trial_balance(month)
                for code, net in balances.items():
                    if type_by_code.get(code) == "income":
                        income += -net
                    elif type_by_code.get(code) == "expense":
                        expense += net

        projected_annual_tax = max(income - expense, Decimal("0")) * PLACEHOLDER_CORPORATE_TAX_RATE
        cumulative_due = projected_annual_tax * ADVANCE_TAX_CUMULATIVE_PCT[quarter]
        prior_cumulative_pct = ADVANCE_TAX_CUMULATIVE_PCT[
            QUARTER_ORDER[max(QUARTER_ORDER.index(quarter) - 1, 0)]
        ]
        prior_cumulative_due = (
            projected_annual_tax * prior_cumulative_pct if quarter != "Q1" else Decimal("0")
        )
        this_installment = cumulative_due - prior_cumulative_due
        return {
            "fy": fy,
            "quarter": quarter,
            "projected_annual_tax": str(projected_annual_tax.quantize(Decimal("0.01"))),
            "cumulative_due": str(cumulative_due.quantize(Decimal("0.01"))),
            "this_installment": str(this_installment.quantize(Decimal("0.01"))),
        }


def _shift_month(month: str, offset: int) -> str:
    year, mon = (int(p) for p in month.split("-"))
    total = (year * 12 + (mon - 1)) + offset
    return f"{total // 12:04d}-{total % 12 + 1:02d}"
