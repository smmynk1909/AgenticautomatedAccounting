"""doc 06 §7 acceptance test 2: "Ledger invariant: trial balance always
balances; fuzz 10k random postings via API — zero unbalanced entries
persisted." This is the "via API" half — `post_journal` dispatched through
the real pipeline (auth, scope check, DB) against a real (sqlite) database,
not fincore's own in-process property test (`fincore/fincore/tests/
test_properties.py`, which already fuzzes 1000 examples at the pure-function
level). Scaled to a few hundred postings rather than a literal 10k: doc 11
§10's testing pyramid puts genuinely large-N fuzzing in the e2e/k6 tier, not
here — this tier's job is proving the same invariant holds through the real
auth+DB pipeline, not exhaustive volume.
"""

from __future__ import annotations

import random
from decimal import Decimal

from awp_mcp_base.server import AwpMcpServer
from awp_shared.auth import mint_service_jwt
from awp_shared.errors import ValidationError

ACCOUNTS = ["5001", "1001", "1002", "4001", "2001", "5008"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _token() -> str:
    return mint_service_jwt("FIN-1", ["finance.write", "finance.read"])


async def test_fuzz_random_postings_never_unbalance(finance_server: AwpMcpServer) -> None:
    rng = random.Random(1234)
    posted = 0
    rejected = 0

    for _ in range(300):
        n_dr_lines = rng.randint(1, 3)
        amounts = [Decimal(rng.randint(1, 500000)) / 100 for _ in range(n_dr_lines)]
        total = sum(amounts, Decimal("0"))

        balanced = rng.random() > 0.3
        if not balanced:
            total += Decimal(rng.randint(1, 1000)) / 100  # deliberately mismatch

        accounts = rng.sample(ACCOUNTS, n_dr_lines)
        entry = {
            "date": "2026-06-10",
            "period": "2026-06",
            "lines": [
                {"account": accounts[i % len(accounts)], "dr": str(amounts[i])}
                for i in range(n_dr_lines)
            ]
            + [{"account": "1001", "cr": str(total)}],
            "posted_by": "fuzz",
        }

        try:
            await finance_server.dispatch_raw(
                "post_journal", {"entry": entry}, _headers(_token())
            )
            posted += 1
        except ValidationError:
            rejected += 1
            assert not balanced, "a balanced entry was rejected"

    assert posted > 0
    assert rejected > 0  # both code paths actually got exercised

    tb = await finance_server.dispatch_raw(
        "get_trial_balance", {"period": "2026-06"}, _headers(_token())
    )
    assert tb["in_balance"] is True  # every persisted entry balanced individually,
    # so the period as a whole must too — this is the real assertion doc 06 §7
    # test 2 cares about: zero unbalanced entries ever made it into the ledger.
