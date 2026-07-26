"""FinCore's value objects — doc 11 §4: "PayrollSnapshot frozen (employees,
comp, attendance, declarations)". Frozen dataclasses, not pydantic — fincore
has no wire boundary of its own (mcp-finance's tool handlers own dict<->model
conversion at the actual MCP boundary); keeping this module dependency-free
and hashable makes it a clean target for `hypothesis` property tests (doc 11
§4's testing contract) and keeps the "LLM never computes money" boundary
unambiguous — nothing here is JSON, nothing here is a bare dict.

Money: `Decimal` only (doc 12 §3: "Money: Decimal only inside fincore,
NUMERIC in DB, never float").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

TWO_PLACES = Decimal("0.01")


def round2(x: Decimal) -> Decimal:
    """doc 11 §4's testing contract: "rounding = round-half-up 2dp" — Python
    Decimal's default context rounding is ROUND_HALF_EVEN (banker's
    rounding), which would silently violate that contract, so every money
    figure fincore produces must go through this instead of a bare
    `.quantize(TWO_PLACES)`."""
    return x.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


# --- Payroll (fincore/payroll.py) ---


@dataclass(frozen=True)
class EmpComp:
    emp_id: str
    grade: str
    basic: Decimal
    hra: Decimal
    special: Decimal
    variable: Decimal = Decimal("0")
    pf_opt_in: bool = True
    state: str = "KA"  # PT slab lookup


@dataclass(frozen=True)
class Attendance:
    emp_id: str
    days_in_month: int
    lop_days: Decimal = Decimal("0")


@dataclass(frozen=True)
class PayrollSnapshot:
    """`freeze_payroll_inputs`'s output (doc 06 §2.1 step 1) — a locked,
    immutable view of everything a payroll run needs."""

    month: str  # "YYYY-MM"
    snapshot_id: str
    employees: tuple[EmpComp, ...]
    attendance: tuple[Attendance, ...]


@dataclass(frozen=True)
class PayrollLine:
    emp_id: str
    earnings: dict[str, Decimal]
    deductions: dict[str, Decimal]
    gross: Decimal
    net: Decimal


@dataclass(frozen=True)
class PayrollRegister:
    month: str
    snapshot_id: str
    lines: tuple[PayrollLine, ...]
    totals: dict[str, Decimal]
    tax_table_version: str


# --- Tax (fincore/tax.py) ---


@dataclass(frozen=True)
class ITSlab:
    income_from: Decimal
    income_to: Decimal | None  # None = no upper bound
    rate: Decimal  # e.g. Decimal("0.05") for 5%


@dataclass(frozen=True)
class PTSlab:
    income_from: Decimal
    income_to: Decimal | None
    amount_per_month: Decimal


@dataclass(frozen=True)
class AnnualIncome:
    gross_annual: Decimal
    other_income: Decimal = Decimal("0")


@dataclass(frozen=True)
class Declarations:
    section_80c: Decimal = Decimal("0")
    section_80d: Decimal = Decimal("0")
    hra_exemption: Decimal = Decimal("0")
    standard_deduction: Decimal = Decimal("50000")


@dataclass(frozen=True)
class TDSProjection:
    fy: str
    regime: str
    annual_taxable_income: Decimal
    annual_tax: Decimal
    months_elapsed: int
    months_remaining: int
    tds_deducted_so_far: Decimal
    monthly_tds: Decimal


@dataclass(frozen=True)
class RegimeComparison:
    fy: str
    old_regime_tax: Decimal
    new_regime_tax: Decimal
    recommended: str  # "old" | "new"


# --- Tax tables (fincore/tables.py) ---


@dataclass(frozen=True)
class TaxTables:
    version: str
    effective_from: date
    effective_to: date | None
    it_slabs: dict[str, tuple[ITSlab, ...]]  # regime -> slabs
    pf_employee_rate: Decimal
    pf_wage_ceiling: Decimal
    esi_gross_threshold: Decimal
    esi_employee_rate: Decimal
    pt_states: dict[str, tuple[PTSlab, ...]]
    gst_rates: dict[str, Decimal]  # e.g. {"standard": 0.18}
    tds_sections: dict[str, Decimal]

    def covers(self, on: date) -> bool:
        if on < self.effective_from:
            return False
        return self.effective_to is None or on <= self.effective_to


# --- Ledger (fincore/ledger.py) ---


@dataclass(frozen=True)
class JournalLine:
    account: str
    dr: Decimal = Decimal("0")
    cr: Decimal = Decimal("0")
    cost_center: str | None = None
    meta: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class JournalEntry:
    date: date
    period: str  # "YYYY-MM"
    lines: tuple[JournalLine, ...]
    ref: str | None = None
    posted_by: str = ""
    approval_ref: str | None = None


@dataclass(frozen=True)
class PostedEntry:
    entry: JournalEntry
    total_dr: Decimal
    total_cr: Decimal


# --- Invoicing (fincore/invoice.py) ---


@dataclass(frozen=True)
class InvoiceLineItem:
    description: str
    quantity: Decimal
    unit_price: Decimal
    hsn_sac: str | None = None


@dataclass(frozen=True)
class GstContext:
    place_of_supply: str
    is_export: bool = False
    gstin: str | None = None


@dataclass(frozen=True)
class ComputedInvoice:
    lines: tuple[InvoiceLineItem, ...]
    subtotal: Decimal
    cgst: Decimal
    sgst: Decimal
    igst: Decimal
    total: Decimal
    gst_treatment: str  # "intra_state" | "inter_state" | "export"


# --- Depreciation (fincore/depreciation.py) ---


@dataclass(frozen=True)
class DepreciableAsset:
    asset_id: str
    cost: Decimal
    method: str  # "wdv" | "slm"
    rate: Decimal  # annual rate, e.g. Decimal("0.15")
    opening_wdv: Decimal


@dataclass(frozen=True)
class DepreciationLine:
    asset_id: str
    opening_wdv: Decimal
    depreciation: Decimal
    closing_wdv: Decimal


# --- Bank reconciliation (fincore/reconcile.py) ---


@dataclass(frozen=True)
class BankTxnInput:
    id: str
    date: date
    amount: Decimal
    ref: str | None = None


@dataclass(frozen=True)
class LedgerCandidate:
    entry_id: str
    date: date
    amount: Decimal
    ref: str | None = None


@dataclass(frozen=True)
class MatchResult:
    bank_txn_id: str
    entry_id: str
    confidence: Decimal  # 0..1
    reason: str


# --- Cashflow (fincore/cashflow.py) ---


@dataclass(frozen=True)
class CashflowRow:
    week_start: date
    inflow: Decimal
    outflow: Decimal
    net: Decimal
    running_balance: Decimal
    assumptions: tuple[str, ...] = ()
