from datetime import date

import pytest
from awp_mcp_base.server import AwpMcpServer
from awp_mcp_base.uow import UnitOfWork
from awp_shared.auth import mint_service_jwt
from awp_shared.config import load_config
from awp_shared.errors import NotFoundError, ValidationError

from awp_mcp_erp.tables import entitlement_matrix, salary_bands, skills_master


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


async def _seed_salary_band(uow: UnitOfWork) -> None:
    async with uow() as session:
        await session.execute(
            salary_bands.insert().values(
                id="sb-e3",
                grade="E3",
                min="600000",
                mid="900000",
                max="1200000",
                effective_from=date(2026, 4, 1),
            )
        )


@pytest.mark.asyncio
async def test_query_policies_salary_bands(erp_server: AwpMcpServer, uow: UnitOfWork) -> None:
    await _seed_salary_band(uow)
    result = await erp_server.dispatch_raw(
        "query_policies", {"domain": "salary_bands", "grade": "E3"}, _headers(_read_token())
    )
    assert len(result["policies"]) == 1
    assert float(result["policies"][0]["mid"]) == 900000.0


async def _seed_skill(uow: UnitOfWork) -> None:
    async with uow() as session:
        await session.execute(
            skills_master.insert().values(
                id="sk-py",
                name="Python",
                synonyms=["py", "python3"],
                category="language",
            )
        )


@pytest.mark.asyncio
async def test_query_policies_skills_master(erp_server: AwpMcpServer, uow: UnitOfWork) -> None:
    await _seed_skill(uow)
    result = await erp_server.dispatch_raw(
        "query_policies", {"domain": "skills_master"}, _headers(_read_token())
    )
    assert len(result["policies"]) == 1
    assert result["policies"][0]["name"] == "Python"
    assert result["policies"][0]["synonyms"] == ["py", "python3"]


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
