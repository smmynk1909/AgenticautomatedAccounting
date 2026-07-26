"""Payroll tools — doc 06 §2.1, doc 08 §2, doc 11 §6.1.

Doc 11 §6.1's sequence returns two different ids — `freeze_payroll_inputs`
-> `snapshot_id`, `compute_payroll` -> `register_id` — implying a separate
snapshot store. Doc 09 §1's actual schema has only one finance table for
this (`payroll_runs`, no `payroll_snapshots`), and mcp-finance has no
direct access to mcp-erp's employee/attendance tables to reconstruct a
snapshot from a bare id anyway — `freeze_payroll_inputs` takes the raw
`employees`/`attendance` data as input instead (the caller, FIN-1 in
Sprint 6, gathers that from mcp-erp), locks it into one `payroll_runs` row,
and `snapshot_id`/`register_id` are the same identifier (that row's `id`)
at two different lifecycle stages, not two different rows.

`generate_disbursement_file` produces a simplified emp_id/net-amount CSV,
not a real per-bank NEFT/NACH file format (doc 06 §2.1 step 6) — no bank
account data reaches mcp-finance in this build either, same reasoning.
It returns the file content directly (base64) rather than a MinIO URI:
mcp-finance has no MinIO client of its own (no MCP server calls another
MCP server in this architecture — only agents/gateway call MCP servers);
vaulting it is the calling agent's job via `mcp-docs.store_file`.
"""

from __future__ import annotations

import base64
import csv
import io
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from awp_mcp_base.ctx import Ctx
from awp_mcp_base.server import AwpMcpServer
from awp_mcp_base.uow import UnitOfWork
from awp_shared.auth import verify_approval_token
from awp_shared.errors import ConflictError, NotFoundError, ValidationError
from fincore.models import Attendance, EmpComp, PayrollSnapshot
from fincore.payroll import compute_payroll as fincore_compute_payroll
from fincore.tables import load_tax_tables
from redis.asyncio import Redis

from awp_mcp_finance.repos.payroll import PayrollRunRepo
from awp_mcp_finance.wire import parse_date


def _emp_comp_from_dict(d: dict[str, Any]) -> EmpComp:
    return EmpComp(
        emp_id=d["emp_id"],
        grade=d.get("grade", ""),
        basic=Decimal(str(d["basic"])),
        hra=Decimal(str(d["hra"])),
        special=Decimal(str(d["special"])),
        variable=Decimal(str(d.get("variable", "0"))),
        pf_opt_in=d.get("pf_opt_in", True),
        state=d.get("state", "KA"),
    )


def _attendance_from_dict(d: dict[str, Any]) -> Attendance:
    return Attendance(
        emp_id=d["emp_id"],
        days_in_month=d["days_in_month"],
        lop_days=Decimal(str(d.get("lop_days", "0"))),
    )


def _months_elapsed(fy: str, month: str) -> int:
    """Complete months from FY `fy`'s start (April `fy[:4]`) up to `month`
    — e.g. fy="2026-27": "2026-04" -> 0, "2027-01" -> 9, "2027-03" -> 11."""
    fy_start_year = int(fy[:4])
    month_year, month_num = (int(p) for p in month.split("-"))
    return (month_year - fy_start_year) * 12 + (month_num - 4)


def register_payroll_tools(server: AwpMcpServer, uow: UnitOfWork, redis: Redis) -> None:
    @server.tool()
    async def freeze_payroll_inputs(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        month = payload.get("month")
        employees = payload.get("employees")
        if not month or not employees:
            raise ValidationError("freeze_payroll_inputs requires 'month' and 'employees'")

        async with uow() as session:
            repo = PayrollRunRepo(session)
            existing = await repo.get_by_month(month)
            if existing is not None:
                raise ConflictError(
                    f"payroll for {month} is already frozen",
                    details={"snapshot_id": existing["snapshot_id"]},
                )

            run_id = str(uuid.uuid4())
            snapshot = {"employees": employees, "attendance": payload.get("attendance", [])}
            await repo.insert(
                {
                    "id": run_id,
                    "month": month,
                    "snapshot_id": run_id,
                    "register": {"snapshot": snapshot},
                    "status": "frozen",
                    "approvals": {},
                }
            )
        return {"snapshot_id": run_id, "month": month}

    @server.tool()
    async def compute_payroll(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        snapshot_id = payload.get("snapshot_id")
        fy = payload.get("fy")
        if not snapshot_id or not fy:
            raise ValidationError("compute_payroll requires 'snapshot_id' and 'fy'")

        async with uow() as session:
            repo = PayrollRunRepo(session)
            run = await repo.get(snapshot_id)
            if run is None:
                raise NotFoundError(f"no such payroll snapshot: {snapshot_id}")

            raw_snapshot = run["register"].get("snapshot")
            if raw_snapshot is None:
                raise ValidationError(f"payroll run {snapshot_id} has no frozen snapshot")

            snapshot = PayrollSnapshot(
                month=run["month"],
                snapshot_id=snapshot_id,
                employees=tuple(_emp_comp_from_dict(e) for e in raw_snapshot["employees"]),
                attendance=tuple(_attendance_from_dict(a) for a in raw_snapshot["attendance"]),
            )

            tables = load_tax_tables(parse_date(f"{run['month']}-01") or datetime.now(UTC).date())
            months_elapsed = _months_elapsed(fy, run["month"])
            tds_so_far = await repo.tds_deducted_so_far_by_emp(fy, run["month"])

            register = fincore_compute_payroll(
                snapshot,
                tables,
                fy=fy,
                tds_deducted_so_far_by_emp=tds_so_far,
                months_elapsed=months_elapsed,
            )
            register_dict = {
                "month": register.month,
                "snapshot_id": register.snapshot_id,
                "lines": [
                    {
                        "emp_id": line_obj.emp_id,
                        "earnings": {k: str(v) for k, v in line_obj.earnings.items()},
                        "deductions": {k: str(v) for k, v in line_obj.deductions.items()},
                        "gross": str(line_obj.gross),
                        "net": str(line_obj.net),
                    }
                    for line_obj in register.lines
                ],
                "totals": {k: str(v) for k, v in register.totals.items()},
                "tax_table_version": register.tax_table_version,
            }
            await repo.update(
                snapshot_id,
                {
                    "register": {"snapshot": raw_snapshot, "computed": register_dict},
                    "status": "computed",
                },
            )
        return {"register_id": snapshot_id, "register": register_dict}

    @server.tool()
    async def generate_disbursement_file(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        register_id = payload.get("register_id")
        if not register_id:
            raise ValidationError("generate_disbursement_file requires 'register_id'")

        async with uow() as session:
            repo = PayrollRunRepo(session)
            run = await repo.get(register_id)
            if run is None:
                raise NotFoundError(f"no such payroll run: {register_id}")
            computed = run["register"].get("computed")
            if computed is None:
                raise ValidationError(f"payroll run {register_id} has not been computed yet")

            totals = {k: Decimal(v) for k, v in computed["totals"].items()}
            await verify_approval_token(
                ctx.approval_token or "",
                "payroll_run",
                {"register_id": register_id, "totals": computed["totals"]},
                redis=redis,
            )

            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(["emp_id", "net_amount"])
            for line_dict in computed["lines"]:
                writer.writerow([line_dict["emp_id"], line_dict["net"]])

            await repo.update(register_id, {"status": "disbursed"})

        content = buf.getvalue().encode("utf-8")
        return {
            "filename": f"disbursement_{run['month']}.csv",
            "content_base64": base64.b64encode(content).decode("ascii"),
            "total_net": str(totals.get("net", Decimal("0"))),
        }
