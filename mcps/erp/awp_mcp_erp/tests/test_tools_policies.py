import pytest
from awp_mcp_base.server import AwpMcpServer
from awp_mcp_base.uow import UnitOfWork
from awp_shared.auth import mint_service_jwt
from awp_shared.config import load_config
from awp_shared.errors import NotFoundError, ValidationError

from awp_mcp_erp.tables import entitlement_matrix


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _read_token() -> str:
    return mint_service_jwt("ADM-1", ["erp.policies.read"])


async def _seed_entitlement(uow: UnitOfWork) -> None:
    async with uow() as session:
        await session.execute(
            entitlement_matrix.insert().values(
                grade="E4", asset_type="laptop", spec="32GB RAM", policy_id="entitlement_e4_laptop"
            )
        )


@pytest.mark.asyncio
async def test_query_policies_entitlements(erp_server: AwpMcpServer, uow: UnitOfWork) -> None:
    await _seed_entitlement(uow)
    result = await erp_server.dispatch_raw(
        "query_policies", {"domain": "entitlements", "grade": "E4"}, _headers(_read_token())
    )
    assert len(result["policies"]) == 1
    assert result["policies"][0]["policy_id"] == "entitlement_e4_laptop"


@pytest.mark.asyncio
async def test_get_policy_entitlement_by_policy_id(
    erp_server: AwpMcpServer, uow: UnitOfWork
) -> None:
    await _seed_entitlement(uow)
    result = await erp_server.dispatch_raw(
        "get_policy", {"policy_id": "entitlement_e4_laptop"}, _headers(_read_token())
    )
    assert result["kind"] == "entitlement"
    assert result["policy"]["spec"] == "32GB RAM"


@pytest.mark.asyncio
async def test_get_policy_gate_by_name(erp_server: AwpMcpServer) -> None:
    load_config.cache_clear()
    result = await erp_server.dispatch_raw(
        "get_policy", {"policy_id": "payroll_run"}, _headers(_read_token())
    )
    assert result["kind"] == "gate"
    assert result["policy"]["n_required"] == 2


@pytest.mark.asyncio
async def test_get_policy_unknown_id_not_found(erp_server: AwpMcpServer) -> None:
    with pytest.raises(NotFoundError):
        await erp_server.dispatch_raw(
            "get_policy", {"policy_id": "no-such-policy"}, _headers(_read_token())
        )


@pytest.mark.asyncio
async def test_query_policies_whole_table_domain(erp_server: AwpMcpServer) -> None:
    load_config.cache_clear()
    result = await erp_server.dispatch_raw(
        "query_policies", {"domain": "sla"}, _headers(_read_token())
    )
    assert result["policies"]["priorities"]["P1"]["first_response_minutes"] == 15


@pytest.mark.asyncio
async def test_query_policies_unknown_domain_raises(erp_server: AwpMcpServer) -> None:
    with pytest.raises(ValidationError):
        await erp_server.dispatch_raw(
            "query_policies", {"domain": "not_a_real_domain"}, _headers(_read_token())
        )
