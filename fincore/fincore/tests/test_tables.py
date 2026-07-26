from __future__ import annotations

from datetime import date

import pytest

from fincore.tables import TaxTableCoverageError, load_tax_tables


def test_loads_default_tables_for_covered_date() -> None:
    t = load_tax_tables(date(2026, 6, 15))
    assert t.version == "2026-27"
    assert "old" in t.it_slabs and "new" in t.it_slabs
    assert t.pf_employee_rate is not None
    assert "KA" in t.pt_states


def test_date_after_any_it_slab_file_raises() -> None:
    with pytest.raises(TaxTableCoverageError):
        load_tax_tables(date(2030, 1, 1))


def test_date_before_any_it_slab_file_raises() -> None:
    with pytest.raises(TaxTableCoverageError):
        load_tax_tables(date(2020, 1, 1))


def test_effective_range_boundaries_are_inclusive() -> None:
    start = load_tax_tables(date(2026, 4, 1))
    end = load_tax_tables(date(2027, 3, 31))
    assert start.version == "2026-27"
    assert end.version == "2026-27"


def test_tax_tables_covers_checks_the_same_effective_range() -> None:
    t = load_tax_tables(date(2026, 6, 15))
    assert t.covers(date(2026, 4, 1)) is True
    assert t.covers(date(2027, 3, 31)) is True
    assert t.covers(date(2026, 3, 31)) is False
    assert t.covers(date(2027, 4, 1)) is False
