"""Reconciliation tools — doc 06 §2.2, doc 08 §2.

`reconcile_bank` takes structured `bank_txns` as input rather than a
`statement_file_uri` — mcp-finance has no `mcp-docs` client of its own (no
MCP server calls another MCP server in this architecture); a bank CSV's
text extraction is the calling agent's job, same reasoning as
`tools_payroll.py`'s docstring.

Candidates for matching are drawn from unreconciled Bank-account (1001)
journal lines — an existing posted entry with no `bank_txns` row pointing
at it yet is exactly "money that moved through the ledger but hasn't been
tied to a statement line."
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from awp_mcp_base.ctx import Ctx
from awp_mcp_base.server import AwpMcpServer
from awp_mcp_base.uow import UnitOfWork
from awp_shared.auth import verify_approval_token
from awp_shared.errors import NotFoundError, ValidationError
from fincore.models import BankTxnInput, LedgerCandidate
from fincore.reconcile import match_bank_txns
from redis.asyncio import Redis
from sqlalchemy import select

from awp_mcp_finance.repos.bank import BankTxnRepo
from awp_mcp_finance.tables import journal_entries, journal_lines
from awp_mcp_finance.wire import parse_date

BANK_ACCOUNT = "1001"


def register_reconcile_tools(server: AwpMcpServer, uow: UnitOfWork, redis: Redis) -> None:
    @server.tool()
    async def reconcile_bank(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        stmt_id = payload.get("stmt_id")
        raw_txns = payload.get("bank_txns")
        if not stmt_id or not raw_txns:
            raise ValidationError("reconcile_bank requires 'stmt_id' and 'bank_txns'")

        async with uow() as session:
            bank_repo = BankTxnRepo(session)
            txn_id_by_bank_id: dict[str, str] = {}
            for t in raw_txns:
                row_id = str(uuid.uuid4())
                txn_id_by_bank_id[t["id"]] = row_id
                await bank_repo.insert(
                    {
                        "id": row_id,
                        "stmt_id": stmt_id,
                        "date": parse_date(t["date"]),
                        "amount": Decimal(str(t["amount"])),
                        "ref": t.get("ref"),
                    }
                )

            candidate_stmt = (
                select(
                    journal_lines.c.entry_id,
                    journal_entries.c.date,
                    journal_lines.c.dr,
                    journal_lines.c.cr,
                    journal_entries.c.ref,
                )
                .join(journal_entries, journal_lines.c.entry_id == journal_entries.c.id)
                .where(journal_lines.c.account == BANK_ACCOUNT)
            )
            rows = (await session.execute(candidate_stmt)).all()

        candidates = [
            LedgerCandidate(
                entry_id=entry_id,
                date=entry_date,
                amount=Decimal(dr) if Decimal(dr) > 0 else Decimal(cr),
                ref=ref,
            )
            for entry_id, entry_date, dr, cr, ref in rows
        ]
        bank_inputs = [
            BankTxnInput(
                id=t["id"],
                date=parse_date(t["date"]) or datetime.now(UTC).date(),
                amount=Decimal(str(t["amount"])),
                ref=t.get("ref"),
            )
            for t in raw_txns
        ]

        auto, suggestions, unmatched = match_bank_txns(bank_inputs, candidates)

        async with uow() as session:
            bank_repo = BankTxnRepo(session)
            for m in auto:
                await bank_repo.update(
                    txn_id_by_bank_id[m.bank_txn_id], {"matched_entry": m.entry_id}
                )

        return {
            "auto_matched": [
                {"bank_txn_id": m.bank_txn_id, "entry_id": m.entry_id, "reason": m.reason}
                for m in auto
            ],
            "suggestions": [
                {
                    "bank_txn_id": m.bank_txn_id,
                    "entry_id": m.entry_id,
                    "confidence": str(m.confidence),
                    "reason": m.reason,
                }
                for m in suggestions
            ],
            "unmatched": [t.id for t in unmatched],
        }

    @server.tool()
    async def confirm_matches(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        matches = payload.get("matches")
        if not matches:
            raise ValidationError("confirm_matches requires 'matches'")

        await verify_approval_token(
            ctx.approval_token or "", "recon_confirm", {"matches": matches}, redis=redis
        )

        async with uow() as session:
            bank_repo = BankTxnRepo(session)
            confirmed = []
            for m in matches:
                existing = await bank_repo.get(m["bank_txn_id"])
                if existing is None:
                    raise NotFoundError(f"no such bank txn: {m['bank_txn_id']}")
                await bank_repo.update(m["bank_txn_id"], {"matched_entry": m["entry_id"]})
                confirmed.append(m["bank_txn_id"])
        return {"confirmed": confirmed}
