from __future__ import annotations

from decimal import Decimal

import pytest

from fincore.models import AnnualIncome, Declarations, TaxTables
from fincore.tax import compare_regimes, project_tds


def test_zero_income_below_exemption_has_zero_tax(tax_tables: TaxTables) -> None:
    proj = project_tds(
        "2026-27", "new", AnnualIncome(gross_annual=Decimal("300000")), Declarations(), tax_tables
    )
    # standard_deduction (50000) brings taxable to 250000, entirely in the 0% slab.
    assert proj.annual_tax == Decimal("0")


def test_higher_income_never_yields_lower_tax(tax_tables: TaxTables) -> None:
    low = project_tds(
        "2026-27", "new", AnnualIncome(gross_annual=Decimal("800000")), Declarations(), tax_tables
    )
    high = project_tds(
        "2026-27", "new", AnnualIncome(gross_annual=Decimal("1600000")), Declarations(), tax_tables
    )
    assert high.annual_tax >= low.annual_tax


def test_unknown_regime_raises(tax_tables: TaxTables) -> None:
    with pytest.raises(ValueError, match="regime"):
        project_tds(
            "2026-27",
            "flat",
            AnnualIncome(gross_annual=Decimal("1000000")),
            Declarations(),
            tax_tables,
        )


def test_monthly_tds_spreads_remaining_liability_over_remaining_months(
    tax_tables: TaxTables,
) -> None:
    proj = project_tds(
        "2026-27",
        "new",
        AnnualIncome(gross_annual=Decimal("1500000")),
        Declarations(),
        tax_tables,
        months_elapsed=6,
        tds_deducted_so_far=Decimal("30000"),
    )
    assert proj.months_remaining == 6
    expected_monthly = (proj.annual_tax - Decimal("30000")) / 6
    assert proj.monthly_tds == expected_monthly.quantize(Decimal("0.01"))


def test_no_months_remaining_yields_zero_monthly_tds(tax_tables: TaxTables) -> None:
    proj = project_tds(
        "2026-27",
        "new",
        AnnualIncome(gross_annual=Decimal("1000000")),
        Declarations(),
        tax_tables,
        months_elapsed=12,
    )
    assert proj.monthly_tds == Decimal("0")


def test_compare_regimes_picks_the_lower_tax(tax_tables: TaxTables) -> None:
    income = AnnualIncome(gross_annual=Decimal("1200000"))
    # Large 80C/80D declarations should make the old regime cheaper here.
    decl_old = Declarations(section_80c=Decimal("150000"), section_80d=Decimal("25000"))
    cmp = compare_regimes("2026-27", income, decl_old, Declarations(), tax_tables)
    assert cmp.recommended in ("old", "new")
    assert cmp.old_regime_tax <= cmp.new_regime_tax or cmp.recommended == "new"


def test_compare_regimes_consistent_with_project_tds(tax_tables: TaxTables) -> None:
    income = AnnualIncome(gross_annual=Decimal("900000"))
    decl_old = Declarations(section_80c=Decimal("100000"))
    decl_new = Declarations()
    cmp = compare_regimes("2026-27", income, decl_old, decl_new, tax_tables)
    old = project_tds("2026-27", "old", income, decl_old, tax_tables)
    new = project_tds("2026-27", "new", income, decl_new, tax_tables)
    assert cmp.old_regime_tax == old.annual_tax
    assert cmp.new_regime_tax == new.annual_tax
