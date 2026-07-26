"""fincore/tax.py — doc 06 §2.4, doc 11 §4.

Slab tax + a flat 4% health-and-education cess (a fixed, well-known
constant, not itself a versioned table — unlike the slabs, it hasn't
changed in years and doesn't need a CA-reviewed YAML entry to adjust).
"""

from __future__ import annotations

from decimal import Decimal

from fincore.models import (
    AnnualIncome,
    Declarations,
    ITSlab,
    RegimeComparison,
    TaxTables,
    TDSProjection,
    round2,
)

CESS_RATE = Decimal("0.04")
SECTION_80C_CAP = Decimal("150000")
SECTION_80D_CAP = Decimal("25000")


def _taxable_income(regime: str, income: AnnualIncome, decl: Declarations) -> Decimal:
    gross = income.gross_annual + income.other_income
    taxable = gross - decl.standard_deduction
    if regime == "old":
        taxable -= min(decl.section_80c, SECTION_80C_CAP)
        taxable -= min(decl.section_80d, SECTION_80D_CAP)
        taxable -= decl.hra_exemption
    return max(taxable, Decimal("0"))


def _slab_tax(taxable: Decimal, slabs: tuple[ITSlab, ...]) -> Decimal:
    tax = Decimal("0")
    for slab in slabs:
        upper = slab.income_to if slab.income_to is not None else taxable
        if taxable <= slab.income_from:
            break
        band = min(taxable, upper) - slab.income_from
        if band > 0:
            tax += band * slab.rate
    return tax


def project_tds(
    fy: str,
    regime: str,
    income: AnnualIncome,
    decl: Declarations,
    t: TaxTables,
    *,
    months_elapsed: int = 0,
    tds_deducted_so_far: Decimal = Decimal("0"),
) -> TDSProjection:
    if regime not in t.it_slabs:
        raise ValueError(f"tax tables {t.version!r} has no slabs for regime {regime!r}")

    taxable = _taxable_income(regime, income, decl)
    base_tax = _slab_tax(taxable, t.it_slabs[regime])
    annual_tax = round2(base_tax * (1 + CESS_RATE))

    months_remaining = max(12 - months_elapsed, 0)
    monthly_tds = Decimal("0")
    if months_remaining > 0:
        remaining = max(annual_tax - tds_deducted_so_far, Decimal("0"))
        monthly_tds = round2(remaining / months_remaining)

    return TDSProjection(
        fy=fy,
        regime=regime,
        annual_taxable_income=round2(taxable),
        annual_tax=annual_tax,
        months_elapsed=months_elapsed,
        months_remaining=months_remaining,
        tds_deducted_so_far=tds_deducted_so_far,
        monthly_tds=monthly_tds,
    )


def compare_regimes(
    fy: str, income: AnnualIncome, decl_old: Declarations, decl_new: Declarations, t: TaxTables
) -> RegimeComparison:
    """`decl_new`'s 80C/80D/HRA fields are ignored (see `_taxable_income` —
    the new regime doesn't allow those deductions) but accepted for symmetry
    (doc 11 §4's testing contract: "regime comparison symmetric" — calling
    this with either regime's declarations first should still compare the
    same two numbers)."""
    old = project_tds(fy, "old", income, decl_old, t)
    new = project_tds(fy, "new", income, decl_new, t)
    recommended = "old" if old.annual_tax < new.annual_tax else "new"
    return RegimeComparison(
        fy=fy, old_regime_tax=old.annual_tax, new_regime_tax=new.annual_tax, recommended=recommended
    )
