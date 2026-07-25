import uuid
from datetime import date

import pytest
from awp_mcp_base.server import AwpMcpServer
from awp_mcp_base.uow import UnitOfWork
from awp_shared.auth import mint_approval_token, mint_service_jwt
from awp_shared.errors import ApprovalRequiredError, ConflictError, NotFoundError

from awp_mcp_erp.repos.asset import AssetRepo


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _write_token() -> str:
    return mint_service_jwt("ADM-1", ["erp.assets.write"])


def _read_token() -> str:
    return mint_service_jwt("ADM-1", ["erp.assets.read"])


def _approval(gate: str, payload: dict) -> str:
    return mint_approval_token(
        gate=gate, payload=payload, approvers=["dev-manager"], ttl_h=24, jti=str(uuid.uuid4())
    )


async def _seed_asset(uow: UnitOfWork, *, value: int = 30000, status: str = "in_stock") -> str:
    asset_id = str(uuid.uuid4())
    async with uow() as session:
        await AssetRepo(session).insert(
            {
                "id": asset_id,
                "type": "laptop",
                "make_model": "Latitude 5420",
                "purchase_date": date(2025, 6, 1),
                "value": value,
                "status": status,
            }
        )
    return asset_id


@pytest.mark.asyncio
async def test_reserve_then_assign_below_threshold_needs_no_approval(
    erp_server: AwpMcpServer, uow: UnitOfWork
) -> None:
    asset_id = await _seed_asset(uow, value=30000)  # below default 50000 threshold
    reservation = await erp_server.dispatch_raw(
        "reserve_asset",
        {"asset_id": asset_id, "emp_id": "EMP-00001", "ttl_h": 24},
        _headers(_write_token()),
    )
    assigned = await erp_server.dispatch_raw(
        "assign_asset", {"reservation_id": reservation["reservation_id"]}, _headers(_write_token())
    )
    assert assigned["issued_at"] is not None

    asset = await erp_server.dispatch_raw(
        "get_asset", {"asset_id": asset_id}, _headers(_read_token())
    )
    assert asset["status"] == "issued"


@pytest.mark.asyncio
async def test_assign_above_threshold_requires_approval(
    erp_server: AwpMcpServer, uow: UnitOfWork
) -> None:
    asset_id = await _seed_asset(uow, value=110000)  # above default 50000 threshold
    reservation = await erp_server.dispatch_raw(
        "reserve_asset",
        {"asset_id": asset_id, "emp_id": "EMP-00002", "ttl_h": 24},
        _headers(_write_token()),
    )
    reservation_id = reservation["reservation_id"]

    with pytest.raises(ApprovalRequiredError):
        await erp_server.dispatch_raw(
            "assign_asset", {"reservation_id": reservation_id}, _headers(_write_token())
        )

    # match the exact string the handler hashes: str(Decimal from the NUMERIC(14,2)
    # column), not the plain input literal — fetch it rather than guess the format.
    asset = await erp_server.dispatch_raw(
        "get_asset", {"asset_id": asset_id}, _headers(_read_token())
    )
    payload = {"reservation_id": reservation_id, "asset_id": asset_id, "value": str(asset["value"])}
    token = _approval("asset_high_value", payload)
    assigned = await erp_server.dispatch_raw(
        "assign_asset",
        {"reservation_id": reservation_id, "approval_token": token},
        _headers(_write_token()),
    )
    assert assigned["issued_at"] is not None


@pytest.mark.asyncio
async def test_reserving_already_reserved_asset_conflicts(
    erp_server: AwpMcpServer, uow: UnitOfWork
) -> None:
    asset_id = await _seed_asset(uow)
    await erp_server.dispatch_raw(
        "reserve_asset", {"asset_id": asset_id, "emp_id": "EMP-00001"}, _headers(_write_token())
    )
    with pytest.raises(ConflictError):
        await erp_server.dispatch_raw(
            "reserve_asset", {"asset_id": asset_id, "emp_id": "EMP-00002"}, _headers(_write_token())
        )


@pytest.mark.asyncio
async def test_return_asset_round_trip(erp_server: AwpMcpServer, uow: UnitOfWork) -> None:
    asset_id = await _seed_asset(uow, value=20000)
    reservation = await erp_server.dispatch_raw(
        "reserve_asset", {"asset_id": asset_id, "emp_id": "EMP-00001"}, _headers(_write_token())
    )
    await erp_server.dispatch_raw(
        "assign_asset", {"reservation_id": reservation["reservation_id"]}, _headers(_write_token())
    )

    returned = await erp_server.dispatch_raw(
        "return_asset",
        {"asset_id": asset_id, "condition_report": {"condition": "good"}},
        _headers(_write_token()),
    )
    assert returned["status"] == "in_stock"


@pytest.mark.asyncio
async def test_return_asset_with_no_open_assignment_not_found(
    erp_server: AwpMcpServer, uow: UnitOfWork
) -> None:
    asset_id = await _seed_asset(uow)
    with pytest.raises(NotFoundError):
        await erp_server.dispatch_raw(
            "return_asset", {"asset_id": asset_id}, _headers(_write_token())
        )


@pytest.mark.asyncio
async def test_writeoff_requires_approval(erp_server: AwpMcpServer, uow: UnitOfWork) -> None:
    asset_id = await _seed_asset(uow)
    with pytest.raises(ApprovalRequiredError):
        await erp_server.dispatch_raw(
            "writeoff_asset",
            {"asset_id": asset_id, "reason": "damaged beyond repair"},
            _headers(_write_token()),
        )

    payload = {"asset_id": asset_id, "reason": "damaged beyond repair"}
    token = _approval("asset_writeoff", payload)
    result = await erp_server.dispatch_raw(
        "writeoff_asset", {**payload, "approval_token": token}, _headers(_write_token())
    )
    assert result["status"] == "written_off"


@pytest.mark.asyncio
async def test_asset_audit_report_counts_by_status(
    erp_server: AwpMcpServer, uow: UnitOfWork
) -> None:
    await _seed_asset(uow, status="in_stock")
    await _seed_asset(uow, status="in_stock")
    await _seed_asset(uow, status="issued")

    report = await erp_server.dispatch_raw(
        "asset_audit_report", {"scope": {}}, _headers(_read_token())
    )
    assert report["count"] == 3
    assert report["by_status"]["in_stock"] == 2
    assert report["by_status"]["issued"] == 1
