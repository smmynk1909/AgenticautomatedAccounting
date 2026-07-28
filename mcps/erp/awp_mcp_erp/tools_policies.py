"""Policy-table read tools — doc 08 §1 "Policy tables (read-only tools)":
entitlement matrix, spend thresholds, SLA table, routing matrix,
approval-gate policy.

Only `entitlement_matrix` has a per-row DB table (doc 09 §1) — the rest
(SLA, routing, gates, scopes, ...) are served straight from `config/*.yaml`
(see `awp_shared/config.py`'s module docstring / DEVIATIONS.md rationale:
these are static ops config, not per-tenant data, so a DB mirror would just
be a second source of truth to keep in sync for no benefit).
"""

from __future__ import annotations

from typing import Any

from awp_mcp_base.ctx import Ctx
from awp_mcp_base.server import AwpMcpServer
from awp_mcp_base.uow import UnitOfWork
from awp_shared.config import ConfigError, load_config
from awp_shared.errors import NotFoundError, ValidationError

from awp_mcp_erp.repos.asset import EntitlementRepo
from awp_mcp_erp.repos.employee import SalaryBandRepo, SkillsMasterRepo

WHOLE_TABLE_DOMAINS = frozenset({"sla", "routing", "gates", "scopes", "shortlist", "sources"})


def register_policy_tools(server: AwpMcpServer, uow: UnitOfWork) -> None:
    @server.tool()
    async def get_policy(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        policy_id = payload.get("policy_id")
        if not policy_id:
            raise ValidationError("get_policy requires 'policy_id'")

        async with uow() as session:
            entitlement = await EntitlementRepo(session).get_by_policy_id(policy_id)
        if entitlement is not None:
            return {"kind": "entitlement", "policy": entitlement}

        gates = load_config("gates")
        if policy_id in gates:
            return {"kind": "gate", "policy": {"gate": policy_id, **gates[policy_id]}}

        raise NotFoundError(f"no such policy: {policy_id}")

    @server.tool()
    async def query_policies(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        domain = payload.get("domain")
        if not domain:
            raise ValidationError("query_policies requires 'domain'")

        if domain == "entitlements":
            async with uow() as session:
                rows = await EntitlementRepo(session).query(grade=payload.get("grade"))
            return {"domain": domain, "policies": rows}

        if domain == "salary_bands":
            # doc 06 §7.1's payroll flow (DEVIATIONS.md #17): a grade's
            # salary_bands.mid stands in for real per-employee comp data
            # until comp_structures' encrypted components have a decrypt
            # path — a small infra piece no sprint has scoped yet.
            async with uow() as session:
                rows = await SalaryBandRepo(session).query(grade=payload.get("grade"))
            return {"domain": domain, "policies": rows}

        if domain == "skills_master":
            # doc 04 §2.2's controlled vocabulary table, needed by
            # mcp-hrsourcing.skill_normalize (Sprint 7) — same
            # "caller supplies data it can't reach cross-server" convention
            # as salary_bands above (DEVIATIONS.md #17), applied to the
            # "no MCP server calls another MCP server" rule.
            async with uow() as session:
                rows = await SkillsMasterRepo(session).query()
            return {"domain": domain, "policies": rows}

        if domain in WHOLE_TABLE_DOMAINS:
            try:
                return {"domain": domain, "policies": load_config(domain)}
            except ConfigError as exc:
                raise NotFoundError(f"policy domain {domain!r} config missing: {exc}") from exc

        known = sorted({"entitlements", "salary_bands", "skills_master", *WHOLE_TABLE_DOMAINS})
        raise ValidationError(f"unknown policy domain: {domain!r} (known: {known})")
