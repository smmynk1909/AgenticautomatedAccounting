"""Ledger tools — doc 08 §2, doc 06 §2.2.

`post_journal`'s `expense_posting` gate is conditional on the entry's own
`expense_context` (doc 06 §2.2: "confidence < 0.8 or amount > Rs 25,000 ->
human confirm gate expense_posting; else auto-post") — payroll/invoice
postings don't set `expense_context` at all, since those flows are gated
by `payroll_run`/`invoice_issue` tokens earlier in their own workflow
(doc 06 §2.1 step 6-7, §2.3 step 4); `post_journal` itself only re-checks
a gate for the one condition doc 08 §2 actually ties to it.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from awp_mcp_base.ctx import Ctx
from awp_mcp_base.server import AwpMcpServer
from awp_mcp_base.uow import UnitOfWork
from awp_shared.auth import verify_approval_token
from awp_shared.errors import NotFoundError, ValidationError
from fincore.ledger import LedgerError
from fincore.ledger import validate_entry as fincore_validate_entry
from fincore.models import JournalEntry, JournalLine
from redis.asyncio import Redis

from awp_mcp_finance.repos.ledger import AccountRepo, JournalRepo, PeriodRepo
from awp_mcp_finance.wire import parse_date

EXPENSE_POSTING_CONFIDENCE_THRESHOLD = Decimal("0.8")
EXPENSE_POSTING_AMOUNT_THRESHOLD = Decimal("25000")


def _to_fincore_entry(payload: dict[str, Any]) -> JournalEntry:
    lines = payload.get("lines") or []
    if not lines:
        raise ValidationError("post_journal requires at least one line")
    return JournalEntry(
        date=parse_date(payload["date"]) or date.today(),
        period=payload["period"],
        lines=tuple(
            JournalLine(
                account=line_dict["account"],
                dr=Decimal(str(line_dict.get("dr", "0"))),
                cr=Decimal(str(line_dict.get("cr", "0"))),
                cost_center=line_dict.get("cost_center"),
                meta=line_dict.get("meta", {}),
            )
            for line_dict in lines
        ),
        ref=payload.get("ref"),
        posted_by=payload.get("posted_by", ""),
    )


def register_ledger_tools(server: AwpMcpServer, uow: UnitOfWork, redis: Redis) -> None:
    @server.tool()
    async def post_journal(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        entry_payload = payload.get("entry")
        if not entry_payload:
            raise ValidationError("post_journal requires 'entry'")
        entry = _to_fincore_entry(entry_payload)

        expense_context = payload.get("expense_context")
        if expense_context:
            amount = Decimal(str(expense_context.get("amount", "0")))
            confidence = Decimal(str(expense_context.get("confidence", "1")))
            if (
                amount > EXPENSE_POSTING_AMOUNT_THRESHOLD
                or confidence < EXPENSE_POSTING_CONFIDENCE_THRESHOLD
            ):
                await verify_approval_token(
                    ctx.approval_token or "",
                    "expense_posting",
                    entry_payload,
                    redis=redis,
                )

        async with uow() as session:
            valid_accounts = await AccountRepo(session).all_codes()
            open_periods = await PeriodRepo(session).open_periods()
            try:
                fincore_validate_entry(
                    entry, open_periods=open_periods, valid_accounts=valid_accounts
                )
            except LedgerError as exc:
                raise ValidationError(str(exc)) from exc

            entry_id = await JournalRepo(session).post(
                entry_date=entry.date,
                period=entry.period,
                lines=[
                    {
                        "account": line_obj.account,
                        "dr": line_obj.dr,
                        "cr": line_obj.cr,
                        "cost_center": line_obj.cost_center,
                        "meta": line_obj.meta,
                    }
                    for line_obj in entry.lines
                ],
                ref=entry.ref,
                posted_by=entry.posted_by or ctx.principal.sub,
                approval_ref=ctx.approval_token,
            )
            posted = await JournalRepo(session).get_entry(entry_id)
        assert posted is not None
        return posted

    @server.tool()
    async def get_trial_balance(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        period = payload.get("period")
        if not period:
            raise ValidationError("get_trial_balance requires 'period'")
        async with uow() as session:
            balances = await JournalRepo(session).trial_balance(period)
        total = sum(balances.values(), Decimal("0"))
        return {
            "period": period,
            "balances": {k: str(v) for k, v in balances.items()},
            "in_balance": total == Decimal("0"),
        }

    @server.tool()
    async def get_ledger(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        account = payload.get("account")
        if not account:
            raise ValidationError("get_ledger requires 'account'")
        date_range = payload.get("range", {})
        async with uow() as session:
            entries = await JournalRepo(session).ledger_for_account(
                account,
                date_from=parse_date(date_range.get("from")),
                date_to=parse_date(date_range.get("to")),
            )
        return {"account": account, "entries": entries}

    @server.tool()
    async def get_pnl(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        period = payload.get("period")
        if not period:
            raise ValidationError("get_pnl requires 'period'")
        async with uow() as session:
            balances = await JournalRepo(session).trial_balance(period)
            account_repo = AccountRepo(session)
            income = Decimal("0")
            expense = Decimal("0")
            for code, net in balances.items():
                acct_type = await account_repo.get_type(code)
                if acct_type == "income":
                    income += -net  # income accounts carry a credit-normal balance
                elif acct_type == "expense":
                    expense += net
        return {
            "period": period,
            "income": str(income),
            "expense": str(expense),
            "net_income": str(income - expense),
        }

    @server.tool()
    async def get_balance_sheet(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        as_of = parse_date(payload.get("date"))
        if as_of is None:
            raise ValidationError("get_balance_sheet requires 'date'")
        async with uow() as session:
            account_repo = AccountRepo(session)
            all_codes = await account_repo.all_codes()
            type_by_code = {code: await account_repo.get_type(code) for code in all_codes}
            balances = await JournalRepo(session).balances_as_of(as_of, None, type_by_code)
            totals: dict[str, Decimal] = {
                "asset": Decimal("0"),
                "liability": Decimal("0"),
                "equity": Decimal("0"),
            }
            for code, net in balances.items():
                acct_type = type_by_code.get(code)
                if acct_type in totals:
                    signed = net if acct_type == "asset" else -net
                    totals[acct_type] += signed
        return {"date": as_of.isoformat(), **{k: str(v) for k, v in totals.items()}}

    @server.tool()
    async def close_period(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        period = payload.get("period")
        if not period:
            raise ValidationError("close_period requires 'period'")
        await verify_approval_token(
            ctx.approval_token or "", "period_close", {"period": period}, redis=redis
        )
        async with uow() as session:
            repo = PeriodRepo(session)
            existing = await repo.get(period)
            if existing is None:
                raise NotFoundError(f"no such period: {period}")
            await repo.update(period, {"status": "closed"})
            updated = await repo.get(period)
        assert updated is not None
        return updated

    @server.tool()
    async def reopen_period(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        period = payload.get("period")
        reason = payload.get("reason")
        if not period or not reason:
            raise ValidationError("reopen_period requires 'period' and 'reason'")
        await verify_approval_token(
            ctx.approval_token or "",
            "period_reopen",
            {"period": period, "reason": reason},
            redis=redis,
        )
        async with uow() as session:
            repo = PeriodRepo(session)
            existing = await repo.get(period)
            if existing is None:
                raise NotFoundError(f"no such period: {period}")
            await repo.update(period, {"status": "open"})
            updated = await repo.get(period)
        assert updated is not None
        return updated
