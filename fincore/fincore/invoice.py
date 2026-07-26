"""fincore/invoice.py — doc 06 §2.3.

Gapless sequential numbering is a DB-transactional concern (doc 11 §7:
"SELECT ... FOR UPDATE this row inside issue_invoice's transaction") that
lives in `mcp-finance`'s repo layer against the `fy_counters` table, not
here — `format_invoice_number` is the pure formatting half of that (given
an already-reserved sequence number, render it), same split as
`ledger.post`/the DB write.
"""

from __future__ import annotations

from decimal import Decimal

from fincore.models import ComputedInvoice, GstContext, InvoiceLineItem, TaxTables, round2

HOME_STATE = "KA"


def format_invoice_number(fy: str, seq: int) -> str:
    return f"INV/{fy}/{seq:06d}"


def compute_invoice(
    lines: list[InvoiceLineItem], gst_context: GstContext, tables: TaxTables
) -> ComputedInvoice:
    if not lines:
        raise ValueError("compute_invoice requires at least one line item")

    subtotal = round2(sum((li.quantity * li.unit_price for li in lines), Decimal("0")))

    if gst_context.is_export:
        return ComputedInvoice(
            lines=tuple(lines),
            subtotal=subtotal,
            cgst=Decimal("0"),
            sgst=Decimal("0"),
            igst=Decimal("0"),
            total=subtotal,
            gst_treatment="export",
        )

    rate = tables.gst_rates["standard"]
    if gst_context.place_of_supply == HOME_STATE:
        half = round2(subtotal * rate / 2)
        return ComputedInvoice(
            lines=tuple(lines),
            subtotal=subtotal,
            cgst=half,
            sgst=half,
            igst=Decimal("0"),
            total=round2(subtotal + half + half),
            gst_treatment="intra_state",
        )

    igst = round2(subtotal * rate)
    return ComputedInvoice(
        lines=tuple(lines),
        subtotal=subtotal,
        cgst=Decimal("0"),
        sgst=Decimal("0"),
        igst=igst,
        total=round2(subtotal + igst),
        gst_treatment="inter_state",
    )
