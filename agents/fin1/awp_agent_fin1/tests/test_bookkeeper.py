from __future__ import annotations

import json

from awp_shared.llm import LLMResponse

from awp_agent_fin1 import bookkeeper
from awp_agent_fin1.tests.conftest import FakeLLM


async def test_extract_expense_parses_llm_response() -> None:
    llm = FakeLLM(
        [
            LLMResponse(
                content=json.dumps(
                    {"vendor": "Acme Cloud", "gstin": None, "date": "2026-06-01", "total": "5000"}
                )
            )
        ]
    )
    result = await bookkeeper.extract_expense(
        llm, "Invoice from Acme Cloud dated 2026-06-01, total 5000"
    )
    assert result.vendor == "Acme Cloud"
    assert result.total == "5000"
    # frames text as data, not instructions (doc 06 §4 rule 5)
    system_msg = llm.calls[0]["messages"][0]["content"]
    assert "data" in system_msg.lower()


def test_propose_account_matches_keyword() -> None:
    extraction = bookkeeper.ExpenseExtraction(vendor="AWS Cloud Hosting", total="1000")
    proposal = bookkeeper.propose_account(extraction)
    assert proposal.account == "5005"
    assert proposal.confidence == 0.9


def test_propose_account_falls_back_to_default() -> None:
    extraction = bookkeeper.ExpenseExtraction(vendor="Mystery Vendor Inc", total="1000")
    proposal = bookkeeper.propose_account(extraction)
    assert proposal.account == bookkeeper.DEFAULT_EXPENSE_ACCOUNT
    assert proposal.confidence == 0.5


def test_duplicate_hash_is_stable_for_same_inputs() -> None:
    h1 = bookkeeper.duplicate_hash("Acme", "5000.00", "2026-06-01")
    h2 = bookkeeper.duplicate_hash("Acme", "5000.00", "2026-06-01")
    assert h1 == h2


def test_duplicate_hash_differs_for_different_amount() -> None:
    h1 = bookkeeper.duplicate_hash("Acme", "5000.00", "2026-06-01")
    h2 = bookkeeper.duplicate_hash("Acme", "5001.00", "2026-06-01")
    assert h1 != h2


def test_expense_journal_lines_balance() -> None:
    lines = bookkeeper.expense_journal_lines("5004", "1000.00")
    assert lines[0]["dr"] == "1000.00"
    assert lines[1]["cr"] == "1000.00"
    assert lines[1]["account"] == "2001"
