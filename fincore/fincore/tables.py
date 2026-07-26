"""Tax-table loader — doc 06 §6 / doc 11 §4: "load YAML -> TaxTables(version,
effective range); refuse if period uncovered."

Only `it_slabs_*.yaml` is FY-versioned (income tax slabs are what genuinely
changes every budget and is what payroll/TDS correctness actually hinges
on); `pf.yaml`/`esi.yaml`/`pt_states.yaml`/`gst_rates.yaml`/`tds_sections.yaml`
are loaded as single current tables, not date-ranged — a deliberate scope
reduction from doc 09's `tax_tables(kind,version,effective_from,
effective_to,...)` schema (which models every kind as independently
versioned), tracked in DEVIATIONS.md. The "refuse to compute a period
without a covering table version" contract is enforced for the part that
matters most: an `as_of` date with no covering `it_slabs_*.yaml` raises
`TaxTableCoverageError` rather than silently falling back to whatever's
on disk.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from fincore.models import ITSlab, PTSlab, TaxTables

DEFAULT_TAX_TABLES_DIR = Path(__file__).resolve().parent / "tax_tables"


class TaxTableCoverageError(Exception):
    pass


@dataclass(frozen=True)
class _ItSlabFile:
    version: str
    effective_from: date
    effective_to: date | None
    regimes: dict[str, tuple[ITSlab, ...]]


def _dec(x: Any) -> Decimal:
    return Decimal(str(x))


def _load_yaml(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _parse_it_slab_file(path: Path) -> _ItSlabFile:
    raw = _load_yaml(path)
    regimes = {
        regime: tuple(
            ITSlab(
                income_from=_dec(row["income_from"]),
                income_to=_dec(row["income_to"]) if row["income_to"] is not None else None,
                rate=_dec(row["rate"]),
            )
            for row in rows
        )
        for regime, rows in raw["regimes"].items()
    }
    return _ItSlabFile(
        version=raw["version"],
        effective_from=date.fromisoformat(raw["effective_from"]),
        effective_to=date.fromisoformat(raw["effective_to"]) if raw.get("effective_to") else None,
        regimes=regimes,
    )


def _covers(f: _ItSlabFile, on: date) -> bool:
    if on < f.effective_from:
        return False
    return f.effective_to is None or on <= f.effective_to


def load_tax_tables(as_of: date, tax_tables_dir: Path | None = None) -> TaxTables:
    tdir = tax_tables_dir or DEFAULT_TAX_TABLES_DIR

    candidates = [_parse_it_slab_file(p) for p in sorted(tdir.glob("it_slabs_*.yaml"))]
    covering = [f for f in candidates if _covers(f, as_of)]
    if not covering:
        known = ", ".join(f.version for f in candidates) or "none"
        raise TaxTableCoverageError(
            f"no it_slabs table covers {as_of.isoformat()} (known versions: {known})"
        )
    it_slab_file = covering[0]

    pf_raw = _load_yaml(tdir / "pf.yaml")
    esi_raw = _load_yaml(tdir / "esi.yaml")
    pt_raw = _load_yaml(tdir / "pt_states.yaml")
    gst_raw = _load_yaml(tdir / "gst_rates.yaml")
    tds_raw = _load_yaml(tdir / "tds_sections.yaml")

    pt_states = {
        state: tuple(
            PTSlab(
                income_from=_dec(row["income_from"]),
                income_to=_dec(row["income_to"]) if row["income_to"] is not None else None,
                amount_per_month=_dec(row["amount_per_month"]),
            )
            for row in rows
        )
        for state, rows in pt_raw.items()
    }

    return TaxTables(
        version=it_slab_file.version,
        effective_from=it_slab_file.effective_from,
        effective_to=it_slab_file.effective_to,
        it_slabs=it_slab_file.regimes,
        pf_employee_rate=_dec(pf_raw["employee_rate"]),
        pf_wage_ceiling=_dec(pf_raw["wage_ceiling"]),
        esi_gross_threshold=_dec(esi_raw["gross_threshold"]),
        esi_employee_rate=_dec(esi_raw["employee_rate"]),
        pt_states=pt_states,
        gst_rates={k: _dec(v) for k, v in gst_raw.items()},
        tds_sections={k: _dec(v) for k, v in tds_raw.items()},
    )
