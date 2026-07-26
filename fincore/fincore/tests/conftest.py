from __future__ import annotations

from datetime import date

import pytest

from fincore.models import TaxTables
from fincore.tables import load_tax_tables


@pytest.fixture
def tax_tables() -> TaxTables:
    return load_tax_tables(date(2026, 6, 15))
