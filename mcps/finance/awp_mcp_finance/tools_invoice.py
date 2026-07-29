"""Invoice tools — doc 06 §2.3, doc 08 §2, doc 11 §7 (gapless numbering).

Account codes (1002 Accounts Receivable, 4001 Domestic Services Income,
2007 GST Output Liability) match `db/seed/coa_seed.yaml`'s chart of
accounts — `issue_invoice`'s AR posting isn't configurable per-invoice
(doc 08 §2 doesn't ask for that); export invoices (zero-rated) skip the
GST-liability line entirely since there's no tax to post.
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
from fincore.invoice import compute_invoice as fincore_compute_invoice
from fincore.invoice import format_invoice_number
from fincore.models import GstContext, InvoiceLineItem
from fincore.tables import load_tax_tables
from redis.asyncio import Redis

from awp_mcp_finance.repos.invoice import FyCounterRepo, InvoiceRepo
from awp_mcp_finance.repos.ledger import JournalRepo, PeriodRepo
from awp_mcp_finance.wire import parse_date

ACCOUNT_AR = "1002"
ACCOUNT_DOMESTIC_INCOME = "4001"
ACCOUNT_GST_OUTPUT = "2007"


def register_invoice_tools(server: AwpMcpServer, uow: UnitOfWork, redis: Redis) -> None:
    @server.tool()
    async def compute_invoice(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        raw_lines = payload.get("lines")
        gst_ctx = payload.get("gst_context")
        fy = payload.get("fy")
        client = payload.get("client")
        if not raw_lines or not gst_ctx or not fy or not client:
            raise ValidationError("compute_invoice requires 'lines', 'gst_context', 'fy', 'client'")

        lines = [
            InvoiceLineItem(
                description=line_dict["description"],
                quantity=Decimal(str(line_dict["quantity"])),
                unit_price=Decimal(str(line_dict["unit_price"])),
                hsn_sac=line_dict.get("hsn_sac"),
            )
            for line_dict in raw_lines
        ]
        gst_context = GstContext(
            place_of_supply=gst_ctx["place_of_supply"],
            is_export=gst_ctx.get("is_export", False),
            gstin=gst_ctx.get("gstin"),
        )
        tables = load_tax_tables(datetime.now(UTC).date())
        computed = fincore_compute_invoice(lines, gst_context, tables)

        invoice_id = str(uuid.uuid4())
        async with uow() as session:
            await InvoiceRepo(session).insert(
                {
                    "id": invoice_id,
                    "number": None,
                    "fy": fy,
                    "client": client,
                    "contract_ref": payload.get("contract_ref"),
                    "lines": [
                        {
                            "description": li.description,
                            "quantity": str(li.quantity),
                            "unit_price": str(li.unit_price),
                            "hsn_sac": li.hsn_sac,
                        }
                        for li in computed.lines
                    ],
                    "gst": {
                        "subtotal": str(computed.subtotal),
                        "cgst": str(computed.cgst),
                        "sgst": str(computed.sgst),
                        "igst": str(computed.igst),
                        "total": str(computed.total),
                        "treatment": computed.gst_treatment,
                    },
                    "status": "draft",
                    "due_date": parse_date(payload.get("due_date")),
                }
            )
        return {
            "invoice_id": invoice_id,
            "subtotal": str(computed.subtotal),
            "cgst": str(computed.cgst),
            "sgst": str(computed.sgst),
            "igst": str(computed.igst),
            "total": str(computed.total),
            "gst_treatment": computed.gst_treatment,
        }

    @server.tool()
    async def issue_invoice(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        invoice_id = payload.get("invoice_id")
        if not invoice_id:
            raise ValidationError("issue_invoice requires 'invoice_id'")

        async with uow() as session:
            invoice_repo = InvoiceRepo(session)
            invoice = await invoice_repo.get(invoice_id)
            if invoice is None:
                raise NotFoundError(f"no such invoice: {invoice_id}")
            if invoice["status"] != "draft":
                raise ValidationError(f"invoice {invoice_id} is {invoice['status']}, not draft")

            await verify_approval_token(
                ctx.approval_token or "",
                "invoice_issue",
                {"invoice_id": invoice_id},
                redis=redis,
            )

            seq = await FyCounterRepo(session).next_seq(invoice["fy"])
            number = format_invoice_number(invoice["fy"], seq)
            await invoice_repo.update(invoice_id, {"number": number, "status": "issued"})

            now = datetime.now(UTC)
            post_period = payload.get("period") or now.strftime("%Y-%m")
            if post_period not in await PeriodRepo(session).open_periods():
                raise ValidationError(f"period {post_period!r} is not open")

            gst = invoice["gst"]
            subtotal = Decimal(gst["subtotal"])
            lines = [{"account": ACCOUNT_AR, "dr": Decimal(gst["total"])}]
            lines.append({"account": ACCOUNT_DOMESTIC_INCOME, "cr": subtotal})
            tax_total = Decimal(gst["total"]) - subtotal
            if tax_total > 0:
                lines.append({"account": ACCOUNT_GST_OUTPUT, "cr": tax_total})

            entry_id = await JournalRepo(session).post(
                entry_date=now.date(),
                period=post_period,
                lines=lines,
                ref=number,
                posted_by=ctx.principal.sub,
                approval_ref=ctx.approval_token,
            )
            updated = await invoice_repo.get(invoice_id)
        assert updated is not None
        return {**updated, "journal_entry_id": entry_id}
