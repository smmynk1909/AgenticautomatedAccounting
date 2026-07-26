from __future__ import annotations

from decimal import Decimal

import pytest

from fincore.depreciation import depreciate_one, run_depreciation, total_depreciation
from fincore.models import DepreciableAsset


def test_wdv_depreciates_off_opening_balance() -> None:
    asset = DepreciableAsset(
        asset_id="AST-1",
        cost=Decimal("100000"),
        method="wdv",
        rate=Decimal("0.15"),
        opening_wdv=Decimal("100000"),
    )
    line = depreciate_one(asset)
    assert line.depreciation == Decimal("15000.00")
    assert line.closing_wdv == Decimal("85000.00")


def test_slm_depreciates_off_original_cost() -> None:
    asset = DepreciableAsset(
        asset_id="AST-2",
        cost=Decimal("100000"),
        method="slm",
        rate=Decimal("0.10"),
        opening_wdv=Decimal("60000"),
    )
    line = depreciate_one(asset)
    assert line.depreciation == Decimal("10000.00")
    assert line.closing_wdv == Decimal("50000.00")


def test_depreciation_never_exceeds_opening_balance() -> None:
    asset = DepreciableAsset(
        asset_id="AST-3",
        cost=Decimal("100000"),
        method="slm",
        rate=Decimal("0.50"),
        opening_wdv=Decimal("1000"),
    )
    line = depreciate_one(asset)
    assert line.depreciation <= line.opening_wdv
    assert line.closing_wdv >= Decimal("0")


def test_unknown_method_raises() -> None:
    asset = DepreciableAsset(
        asset_id="AST-4",
        cost=Decimal("100000"),
        method="units_of_production",
        rate=Decimal("0.1"),
        opening_wdv=Decimal("100000"),
    )
    with pytest.raises(ValueError, match="AST-4"):
        depreciate_one(asset)


def test_run_depreciation_totals() -> None:
    assets = [
        DepreciableAsset(
            asset_id="A",
            cost=Decimal("10000"),
            method="wdv",
            rate=Decimal("0.1"),
            opening_wdv=Decimal("10000"),
        ),
        DepreciableAsset(
            asset_id="B",
            cost=Decimal("20000"),
            method="wdv",
            rate=Decimal("0.1"),
            opening_wdv=Decimal("20000"),
        ),
    ]
    lines = run_depreciation(assets)
    assert total_depreciation(lines) == Decimal("3000.00")
