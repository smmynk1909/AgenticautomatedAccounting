from __future__ import annotations

from decimal import Decimal

import pytest

from fincore.invoice import compute_invoice, format_invoice_number
from fincore.models import GstContext, InvoiceLineItem, TaxTables


def _lines() -> list[InvoiceLineItem]:
    return [
        InvoiceLineItem(
            description="Consulting", quantity=Decimal("10"), unit_price=Decimal("5000")
        )
    ]


def test_intra_state_splits_cgst_sgst_evenly(tax_tables: TaxTables) -> None:
    inv = compute_invoice(_lines(), GstContext(place_of_supply="KA"), tax_tables)
    assert inv.subtotal == Decimal("50000.00")
    assert inv.cgst == Decimal("4500.00")
    assert inv.sgst == Decimal("4500.00")
    assert inv.igst == Decimal("0")
    assert inv.total == Decimal("59000.00")
    assert inv.gst_treatment == "intra_state"


def test_inter_state_charges_igst_only(tax_tables: TaxTables) -> None:
    inv = compute_invoice(_lines(), GstContext(place_of_supply="MH"), tax_tables)
    assert inv.cgst == Decimal("0")
    assert inv.sgst == Decimal("0")
    assert inv.igst == Decimal("9000.00")
    assert inv.total == Decimal("59000.00")
    assert inv.gst_treatment == "inter_state"


def test_export_is_zero_rated(tax_tables: TaxTables) -> None:
    inv = compute_invoice(_lines(), GstContext(place_of_supply="US", is_export=True), tax_tables)
    assert inv.cgst == inv.sgst == inv.igst == Decimal("0")
    assert inv.total == inv.subtotal
    assert inv.gst_treatment == "export"


def test_empty_lines_rejected(tax_tables: TaxTables) -> None:
    with pytest.raises(ValueError, match="line item"):
        compute_invoice([], GstContext(place_of_supply="KA"), tax_tables)


def test_intra_and_inter_state_totals_match_for_same_subtotal(tax_tables: TaxTables) -> None:
    """Same subtotal, different place of supply -> same total either way
    (only the CGST+SGST vs IGST split differs) — a useful sanity property
    given intra/inter-state math is computed via two separate code paths."""
    intra = compute_invoice(_lines(), GstContext(place_of_supply="KA"), tax_tables)
    inter = compute_invoice(_lines(), GstContext(place_of_supply="MH"), tax_tables)
    assert intra.total == inter.total


def test_format_invoice_number_is_gapless_for_sequential_input() -> None:
    numbers = [format_invoice_number("2026-27", seq) for seq in range(1, 5)]
    assert numbers == [
        "INV/2026-27/000001",
        "INV/2026-27/000002",
        "INV/2026-27/000003",
        "INV/2026-27/000004",
    ]
    assert len(set(numbers)) == len(numbers)
