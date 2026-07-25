"""Asset tools — doc 08 §1 "Assets" section, doc 03 §2.1 issuance workflow.

`reserve_asset` combines a Redis lock (prevents two concurrent reservations
of the same in-stock unit) with a DB row (a not-yet-issued
`asset_assignments` entry) — doc 08 §1's "reservation id (Redis lock + row)".
`assign_asset` finalizes it, gating on `asset_high_value` only when the
asset's value crosses `config/entitlements.yaml`'s threshold (doc 03 §2.1
rule: "approval only if asset value > ₹50,000").
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
from awp_shared.config import load_config
from awp_shared.errors import ConflictError, NotFoundError, ValidationError
from redis.asyncio import Redis

from awp_mcp_erp.repos.asset import AssetAssignmentRepo, AssetRepo


def register_asset_tools(server: AwpMcpServer, uow: UnitOfWork, redis: Redis) -> None:
    @server.tool()
    async def query_assets(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        async with uow() as session:
            rows = await AssetRepo(session).query(
                type_=payload.get("type"),
                status=payload.get("status"),
                limit=payload.get("limit", 50),
            )
        return {"assets": rows}

    @server.tool()
    async def get_asset(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        asset_id = payload.get("asset_id")
        if not asset_id:
            raise ValidationError("get_asset requires 'asset_id'")
        async with uow() as session:
            asset = await AssetRepo(session).get(asset_id)
            if asset is None:
                raise NotFoundError(f"no such asset: {asset_id}")
            history = await AssetAssignmentRepo(session).history_for_asset(asset_id)
        return {**asset, "history": history}

    @server.tool()
    async def reserve_asset(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        asset_id = payload.get("asset_id")
        emp_id = payload.get("emp_id")
        ttl_h = payload.get("ttl_h", 24)
        if not asset_id or not emp_id:
            raise ValidationError("reserve_asset requires 'asset_id' and 'emp_id'")

        lock_key = f"asset_lock:{asset_id}"
        got_lock = await redis.set(lock_key, emp_id, nx=True, ex=int(ttl_h * 3600))
        if not got_lock:
            raise ConflictError(f"asset {asset_id} is already reserved")

        try:
            async with uow() as session:
                asset_repo = AssetRepo(session)
                asset = await asset_repo.get(asset_id)
                if asset is None:
                    raise NotFoundError(f"no such asset: {asset_id}")
                if asset["status"] != "in_stock":
                    raise ConflictError(
                        f"asset {asset_id} is not in_stock (status={asset['status']})"
                    )

                reservation_id = str(uuid.uuid4())
                await AssetAssignmentRepo(session).insert(
                    {
                        "id": reservation_id,
                        "asset_id": asset_id,
                        "emp_id": emp_id,
                        "issued_at": None,
                        "ack_at": None,
                        "returned_at": None,
                        "condition": {},
                    }
                )
                await asset_repo.update(asset_id, {"status": "reserved"})
        except Exception:
            await redis.delete(lock_key)
            raise

        return {
            "reservation_id": reservation_id,
            "asset_id": asset_id,
            "emp_id": emp_id,
            "ttl_h": ttl_h,
        }

    @server.tool()
    async def assign_asset(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        reservation_id = payload.get("reservation_id")
        if not reservation_id:
            raise ValidationError("assign_asset requires 'reservation_id'")

        async with uow() as session:
            assignment_repo = AssetAssignmentRepo(session)
            asset_repo = AssetRepo(session)
            reservation = await assignment_repo.get(reservation_id)
            if reservation is None or reservation["issued_at"] is not None:
                raise NotFoundError(f"no pending reservation: {reservation_id}")
            asset = await asset_repo.get(reservation["asset_id"])
            if asset is None:
                raise NotFoundError(f"no such asset: {reservation['asset_id']}")

            threshold = Decimal(str(load_config("entitlements")["asset_high_value_threshold_inr"]))
            if Decimal(str(asset["value"])) > threshold:
                await verify_approval_token(
                    ctx.approval_token or "",
                    "asset_high_value",
                    {
                        "reservation_id": reservation_id,
                        "asset_id": asset["id"],
                        "value": str(asset["value"]),
                    },
                    redis=redis,
                )

            await assignment_repo.update(reservation_id, {"issued_at": datetime.now(UTC)})
            await asset_repo.update(asset["id"], {"status": "issued"})
            updated = await assignment_repo.get(reservation_id)

        await redis.delete(f"asset_lock:{asset['id']}")
        assert updated is not None
        return updated

    @server.tool()
    async def return_asset(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        asset_id = payload.get("asset_id")
        condition_report = payload.get("condition_report", {})
        if not asset_id:
            raise ValidationError("return_asset requires 'asset_id'")

        async with uow() as session:
            asset_repo = AssetRepo(session)
            assignment_repo = AssetAssignmentRepo(session)
            open_assignment = await assignment_repo.open_assignment(asset_id)
            if open_assignment is None:
                raise NotFoundError(f"no open assignment for asset: {asset_id}")
            await assignment_repo.update(
                open_assignment["id"],
                {"returned_at": datetime.now(UTC), "condition": condition_report},
            )
            await asset_repo.update(asset_id, {"status": "in_stock"})
            updated = await asset_repo.get(asset_id)
        assert updated is not None
        return updated

    @server.tool()
    async def writeoff_asset(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        asset_id = payload.get("asset_id")
        reason = payload.get("reason")
        if not asset_id or not reason:
            raise ValidationError("writeoff_asset requires 'asset_id' and 'reason'")

        await verify_approval_token(
            ctx.approval_token or "",
            "asset_writeoff",
            {"asset_id": asset_id, "reason": reason},
            redis=redis,
        )
        async with uow() as session:
            asset_repo = AssetRepo(session)
            asset = await asset_repo.get(asset_id)
            if asset is None:
                raise NotFoundError(f"no such asset: {asset_id}")
            await asset_repo.update(asset_id, {"status": "written_off"})
            updated = await asset_repo.get(asset_id)
        assert updated is not None
        return updated

    @server.tool()
    async def asset_audit_report(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        scope = payload.get("scope", {})
        async with uow() as session:
            rows = await AssetRepo(session).query(
                type_=scope.get("type"), status=scope.get("status"), limit=scope.get("limit", 1000)
            )
        by_status: dict[str, int] = {}
        total_value = Decimal("0")
        for row in rows:
            by_status[row["status"]] = by_status.get(row["status"], 0) + 1
            total_value += Decimal(str(row["value"]))
        return {
            "count": len(rows),
            "by_status": by_status,
            "total_value": str(total_value),
            "assets": rows,
        }
