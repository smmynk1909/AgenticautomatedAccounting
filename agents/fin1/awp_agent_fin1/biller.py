"""FIN-1c Biller — doc 06 §2.3.

Every rate should be "cited to contract clause" per doc 06 §2.3 step 1, but
no contracts corpus exists yet (`mcp-search`, Sprint 7+) — `items` and
`gst_context` come straight from the dispatching task's payload instead of
being pulled from a contract lookup. `contract_ref` is still recorded on
the invoice for traceability even though nothing resolves it yet.
"""

from __future__ import annotations

from typing import Any


def build_invoice_lines(items: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if not items:
        raise ValueError("create_invoice requires at least one item")
    return [
        {
            "description": item["description"],
            "quantity": str(item["quantity"]),
            "unit_price": str(item["unit_price"]),
            "hsn_sac": item.get("hsn_sac"),
        }
        for item in items
    ]
