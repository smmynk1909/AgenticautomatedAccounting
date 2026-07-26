"""fincore/depreciation.py — doc 06 §2.2 month-close's "depreciation run",
doc 11 §4's "WDV/SLM per asset class". One period's worth of depreciation
per asset — `run_depreciation`'s caller (mcp-finance) is responsible for
turning the result into journal lines and advancing `opening_wdv` for the
next period.
"""

from __future__ import annotations

from decimal import Decimal

from fincore.models import DepreciableAsset, DepreciationLine, round2


def depreciate_one(asset: DepreciableAsset) -> DepreciationLine:
    if asset.method == "wdv":
        raw = asset.opening_wdv * asset.rate
    elif asset.method == "slm":
        raw = asset.cost * asset.rate
    else:
        raise ValueError(f"unknown depreciation method: {asset.method!r} (asset {asset.asset_id})")

    dep = round2(min(raw, asset.opening_wdv))
    closing = round2(asset.opening_wdv - dep)
    return DepreciationLine(
        asset_id=asset.asset_id,
        opening_wdv=asset.opening_wdv,
        depreciation=dep,
        closing_wdv=closing,
    )


def run_depreciation(assets: list[DepreciableAsset]) -> list[DepreciationLine]:
    return [depreciate_one(a) for a in assets]


def total_depreciation(lines: list[DepreciationLine]) -> Decimal:
    return round2(sum((line.depreciation for line in lines), Decimal("0")))
