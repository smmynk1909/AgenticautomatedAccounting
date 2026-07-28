"""People tools — doc 08 §1 "People" section.

`upsert_employee` and `propose_merge`/`convert_candidate_to_employee` are
🔒-gated per doc 03 §2.2 / doc 08 §1: the handler itself decides *whether*
the gate applies (e.g. only when identity fields actually change) and calls
`verify_approval_token` inline — this is the same pattern doc 11 §3's
`assign_asset` example uses, not something the pipeline can do generically.
"""

from __future__ import annotations

import uuid
from typing import Any

from awp_mcp_base.ctx import Ctx
from awp_mcp_base.server import AwpMcpServer
from awp_mcp_base.uow import UnitOfWork
from awp_shared.auth import verify_approval_token
from awp_shared.errors import ConflictError, NotFoundError, ValidationError
from redis.asyncio import Redis

from awp_mcp_erp.dedupe import find_duplicates
from awp_mcp_erp.repos.employee import CandidateRepo, EmployeeRepo, RoleRepo
from awp_mcp_erp.wire import parse_date

# doc 03 §2.2: mutating these on an *existing* employee needs human sign-off
# (upsert_employee's `record_correction` gate); everything else (grade bump
# via HR process, status flip, manager reassignment) does not.
IDENTITY_FIELDS = frozenset({"name", "join_date", "dept_id"})


def _mask_employee(row: dict[str, Any], *, full: bool) -> dict[str, Any]:
    row = dict(row)
    if not full:
        row["contact_encrypted"] = None
    return row


def _coerce_employee_dates(record: dict[str, Any]) -> dict[str, Any]:
    """`join_date`/`exit_date` arrive as ISO strings over the wire — see
    wire.py's docstring for why these must be real `date` objects before
    they reach a `sa.Date()` column."""
    coerced = dict(record)
    if "join_date" in coerced:
        coerced["join_date"] = parse_date(coerced["join_date"])
    if "exit_date" in coerced:
        coerced["exit_date"] = parse_date(coerced["exit_date"])
    return coerced


def register_people_tools(server: AwpMcpServer, uow: UnitOfWork, redis: Redis) -> None:
    @server.tool()
    async def get_employee(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        emp_id = payload.get("emp_id")
        if not emp_id:
            raise ValidationError("get_employee requires 'emp_id'")
        view = payload.get("view", "masked")
        async with uow() as session:
            row = await EmployeeRepo(session).get(emp_id)
        if row is None:
            raise NotFoundError(f"no such employee: {emp_id}")

        full = view == "full"
        if full and "pii.read.people" not in ctx.principal.scopes:
            # doc 08 §0: "full requires scope pii.read.<domain>" — silently
            # degrade to masked rather than error, since "give me whatever
            # you're allowed to see" is a reasonable default for callers
            # that don't specify a view at all.
            full = False
        return _mask_employee(row, full=full)

    @server.tool()
    async def query_employees(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        page = payload.get("page", 0)
        page_size = payload.get("page_size", 50)
        async with uow() as session:
            rows = await EmployeeRepo(session).query(
                dept_id=payload.get("dept_id"),
                status=payload.get("status"),
                manager_id=payload.get("manager_id"),
                limit=page_size,
                offset=page * page_size,
            )
        return {"employees": [_mask_employee(r, full=False) for r in rows]}

    @server.tool()
    async def upsert_employee(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        record = payload.get("record")
        if not record or not record.get("emp_id"):
            raise ValidationError("upsert_employee requires record.emp_id")
        record = _coerce_employee_dates(record)
        emp_id = record["emp_id"]

        async with uow() as session:
            repo = EmployeeRepo(session)
            existing = await repo.get(emp_id, include_deleted=True)
            if existing is not None:
                changed_identity = any(
                    field in record and record[field] != existing.get(field)
                    for field in IDENTITY_FIELDS
                )
                if changed_identity:
                    await verify_approval_token(
                        ctx.approval_token or "", "record_correction", record, redis=redis
                    )
                await repo.update(emp_id, {k: v for k, v in record.items() if k != "emp_id"})
            else:
                await repo.insert(record)
            updated = await repo.get(emp_id, include_deleted=True)
        assert updated is not None
        return _mask_employee(updated, full=False)

    @server.tool()
    async def get_candidate(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        candidate_id = payload.get("candidate_id")
        if not candidate_id:
            raise ValidationError("get_candidate requires 'candidate_id'")
        async with uow() as session:
            row = await CandidateRepo(session).get(candidate_id)
        if row is None:
            raise NotFoundError(f"no such candidate: {candidate_id}")
        return row

    @server.tool()
    async def query_candidates(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        async with uow() as session:
            rows = await CandidateRepo(session).query(
                status=payload.get("status"),
                limit=payload.get("page_size", 50),
                offset=payload.get("page", 0) * payload.get("page_size", 50),
            )
        return {"candidates": rows}

    @server.tool()
    async def upsert_candidate(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        record = payload.get("record")
        if not record:
            raise ValidationError("upsert_candidate requires 'record'")

        async with uow() as session:
            repo = CandidateRepo(session)
            candidate_id = record.get("id")
            if candidate_id:
                existing = await repo.get(candidate_id)
                if existing is None:
                    raise NotFoundError(f"no such candidate: {candidate_id}")
                await repo.update(candidate_id, {k: v for k, v in record.items() if k != "id"})
                updated = await repo.get(candidate_id)
                assert updated is not None
                return updated

            # New candidate: dedupe check first (doc 03 §2.2) — a positive
            # match returns CONFLICT with the proposal evidence, never a
            # silent overwrite or a silent duplicate insert.
            profile = record.get("profile", {})
            pool = await repo.all_active()
            matches = find_duplicates(profile, pool)
            if matches:
                raise ConflictError(
                    "possible duplicate candidate(s) found",
                    details={"matches": [m.model_dump() for m in matches]},
                )
            new_id = str(uuid.uuid4())
            await repo.insert({**record, "id": new_id})
            created = await repo.get(new_id)
        assert created is not None
        return created

    @server.tool()
    async def propose_merge(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        record_a_id = payload.get("record_a")
        record_b_id = payload.get("record_b")
        evidence = payload.get("evidence", {})
        if not record_a_id or not record_b_id:
            raise ValidationError(
                "propose_merge requires 'record_a' and 'record_b' (candidate ids)"
            )

        merge_payload = {"record_a": record_a_id, "record_b": record_b_id, "evidence": evidence}
        await verify_approval_token(
            ctx.approval_token or "", "data_merge", merge_payload, redis=redis
        )

        async with uow() as session:
            repo = CandidateRepo(session)
            a = await repo.get(record_a_id)
            b = await repo.get(record_b_id)
            if a is None or b is None:
                raise NotFoundError("one or both candidate records not found")
            # `a`'s fields win on conflict — it's the canonical survivor record.
            merged_profile = {**b["profile"], **a["profile"]}
            await repo.update(record_a_id, {"profile": merged_profile})
            await repo.soft_delete(record_b_id)
            merged = await repo.get(record_a_id)
        assert merged is not None
        return merged

    @server.tool()
    async def convert_candidate_to_employee(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        candidate_id = payload.get("candidate_id")
        emp_fields = payload.get("emp_fields")
        if not candidate_id or not emp_fields or not emp_fields.get("emp_id"):
            raise ValidationError(
                "convert_candidate_to_employee requires 'candidate_id' and 'emp_fields.emp_id'"
            )

        convert_payload = {"candidate_id": candidate_id, "emp_fields": emp_fields}
        await verify_approval_token(
            ctx.approval_token or "", "onboarding", convert_payload, redis=redis
        )

        async with uow() as session:
            cand_repo = CandidateRepo(session)
            emp_repo = EmployeeRepo(session)
            candidate = await cand_repo.get(candidate_id)
            if candidate is None:
                raise NotFoundError(f"no such candidate: {candidate_id}")

            record = {
                "emp_id": emp_fields["emp_id"],
                "candidate_id": candidate_id,  # lineage preserved, doc 08 §1
                "name": emp_fields.get("name") or candidate["profile"].get("name", ""),
                "contact_encrypted": None,
                "dept_id": emp_fields["dept_id"],
                "role_id": emp_fields["role_id"],
                "manager_id": emp_fields.get("manager_id"),
                "grade": emp_fields["grade"],
                "status": "active",
                # doc 08 §1: verified above against emp_fields as given on the
                # wire (string) — coerce to a real date only here, for the
                # DB insert, so the approval-token payload hash still matches
                # what the human approved (see wire.py's docstring).
                "join_date": parse_date(emp_fields["join_date"]),
                "skills": candidate["profile"].get("skills_normalized", []),
                "docs": {},
            }
            await emp_repo.insert(record)
            await cand_repo.update(candidate_id, {"status": "hired"})
            employee = await emp_repo.get(emp_fields["emp_id"])
        assert employee is not None
        return _mask_employee(employee, full=False)

    @server.tool()
    async def get_role(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        role_id = payload.get("role_id")
        if not role_id:
            raise ValidationError("get_role requires 'role_id'")
        async with uow() as session:
            row = await RoleRepo(session).get(role_id)
        if row is None:
            raise NotFoundError(f"no such role: {role_id}")
        return row

    @server.tool()
    async def upsert_role(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        # doc 04 §2.1: "recruiter confirms RoleProfile once per role —
        # cached" — not in doc 08 §1's original People tool list (which
        # only names employee/candidate tools), added once HR-1 (Sprint 7)
        # needed somewhere to persist the parsed RoleProfile JSON that
        # `roles.role_profile` already had a column for since Sprint 1.
        record = payload.get("record")
        if not record:
            raise ValidationError("upsert_role requires 'record'")
        async with uow() as session:
            repo = RoleRepo(session)
            role_id = record.get("id")
            if role_id:
                existing = await repo.get(role_id)
                if existing is None:
                    raise NotFoundError(f"no such role: {role_id}")
                await repo.update(role_id, {k: v for k, v in record.items() if k != "id"})
                updated = await repo.get(role_id)
                assert updated is not None
                return updated
            new_id = str(uuid.uuid4())
            await repo.insert({**record, "id": new_id})
            created = await repo.get(new_id)
        assert created is not None
        return created
