"""Delivery-issue tools — doc 05 §2.3, doc 08's "issue-tracker CRUD".
Repo/CodeAssist tools (`list_repos`, `index_repo`, `search_code`,
`get_file`, `get_diff`) land Sprint 10 — see DEVIATIONS.md, same
"the acceptance tests actually named for this sprint don't need it" split
as every other partial-sprint build in this codebase.
"""

from __future__ import annotations

import uuid
from typing import Any

from awp_mcp_base.ctx import Ctx
from awp_mcp_base.server import AwpMcpServer
from awp_mcp_base.uow import UnitOfWork
from awp_shared.errors import NotFoundError, ValidationError

from awp_mcp_projects.repos.issue import DeliveryIssueRepo
from awp_mcp_projects.wire import parse_date

_VALID_IMPACT = frozenset({"schedule", "quality", "scope", "cost"})
_VALID_SEVERITY = frozenset({"S1", "S2", "S3", "S4"})


def register_issue_tools(server: AwpMcpServer, uow: UnitOfWork) -> None:
    @server.tool()
    async def create_issue(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        project_id = payload.get("project_id")
        description = payload.get("description")
        impact = payload.get("impact")
        if not project_id or not description or not impact:
            raise ValidationError("create_issue requires 'project_id', 'description', 'impact'")
        if impact not in _VALID_IMPACT:
            raise ValidationError(f"impact must be one of {sorted(_VALID_IMPACT)}")
        severity = payload.get("severity", "S3")
        if severity not in _VALID_SEVERITY:
            raise ValidationError(f"severity must be one of {sorted(_VALID_SEVERITY)}")

        issue_id = str(uuid.uuid4())
        async with uow() as session:
            repo = DeliveryIssueRepo(session)
            await repo.insert(
                {
                    "id": issue_id,
                    "project_id": project_id,
                    "description": description,
                    "impact": impact,
                    "severity": severity,
                    "status": payload.get("status", "open"),
                    "owner": payload.get("owner"),
                    "mitigation_options": payload.get("mitigation_options", []),
                    "decision_needed_by": parse_date(payload.get("decision_needed_by")),
                }
            )
            created = await repo.get(issue_id)
        assert created is not None
        return created

    @server.tool()
    async def get_issue(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        issue_id = payload.get("issue_id")
        if not issue_id:
            raise ValidationError("get_issue requires 'issue_id'")
        async with uow() as session:
            row = await DeliveryIssueRepo(session).get(issue_id)
        if row is None:
            raise NotFoundError(f"no such issue: {issue_id}")
        return row

    @server.tool()
    async def query_issues(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        async with uow() as session:
            rows = await DeliveryIssueRepo(session).query(
                project_id=payload.get("project_id"),
                severity=payload.get("severity"),
                status=payload.get("status"),
            )
        return {"issues": rows}

    @server.tool()
    async def update_issue(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        issue_id = payload.get("issue_id")
        patch = payload.get("patch")
        if not issue_id or not patch:
            raise ValidationError("update_issue requires 'issue_id' and 'patch'")
        if "decision_needed_by" in patch:
            patch = {**patch, "decision_needed_by": parse_date(patch["decision_needed_by"])}

        async with uow() as session:
            repo = DeliveryIssueRepo(session)
            existing = await repo.get(issue_id)
            if existing is None:
                raise NotFoundError(f"no such issue: {issue_id}")
            await repo.update(issue_id, patch)
            updated = await repo.get(issue_id)
        assert updated is not None
        return updated
