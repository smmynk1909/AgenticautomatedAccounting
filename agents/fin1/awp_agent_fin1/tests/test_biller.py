from __future__ import annotations

import pytest

from awp_agent_fin1.biller import build_invoice_lines


def test_build_invoice_lines_maps_items() -> None:
    items = [{"description": "Consulting", "quantity": 10, "unit_price": 5000, "hsn_sac": "9983"}]
    lines = build_invoice_lines(items)
    assert lines[0]["description"] == "Consulting"
    assert lines[0]["quantity"] == "10"
    assert lines[0]["hsn_sac"] == "9983"


def test_build_invoice_lines_requires_items() -> None:
    with pytest.raises(ValueError, match="item"):
        build_invoice_lines(None)
    with pytest.raises(ValueError, match="item"):
        build_invoice_lines([])
