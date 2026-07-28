import uuid

import pytest
from awp_mcp_base.server import AwpMcpServer
from awp_shared.auth import mint_approval_token, mint_service_jwt
from awp_shared.errors import ApprovalRequiredError, ConflictError, NotFoundError


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _approval(gate: str, payload: dict) -> str:
    return mint_approval_token(
        gate=gate, payload=payload, approvers=["dev-admin-head"], ttl_h=24, jti=str(uuid.uuid4())
    )


# Plain functions, called inside each test body (not module-level constants):
# mint_service_jwt reads AWP_DEV_JWT_SECRET from the environment, which the
# autouse `_dev_auth_secrets` fixture only sets once a test actually runs.
def _write_token() -> str:
    return mint_service_jwt("ADM-1", ["erp.people.write"])


def _read_token() -> str:
    return mint_service_jwt("ADM-1", ["erp.people.read"])


def _full_read_token() -> str:
    return mint_service_jwt("ADM-1", ["erp.people.read"])  # scope alone isn't enough for view=full


def _pii_read_token() -> str:
    return mint_service_jwt("ADM-1", ["erp.people.read", "pii.read.people"])


@pytest.mark.asyncio
async def test_upsert_employee_insert_then_get(erp_server: AwpMcpServer, base_org: dict) -> None:
    record = {
        "emp_id": "EMP-00001",
        "name": "Asha Rao",
        "dept_id": base_org["dept_id"],
        "role_id": base_org["role_id"],
        "grade": "E2",
        "join_date": "2026-01-15",
    }
    created = await erp_server.dispatch_raw(
        "upsert_employee", {"record": record}, _headers(_write_token())
    )
    assert created["emp_id"] == "EMP-00001"
    assert created["contact_encrypted"] is None

    fetched = await erp_server.dispatch_raw(
        "get_employee", {"emp_id": "EMP-00001"}, _headers(_read_token())
    )
    assert fetched["name"] == "Asha Rao"


@pytest.mark.asyncio
async def test_get_employee_masks_contact_by_default(
    erp_server: AwpMcpServer, base_org: dict
) -> None:
    record = {
        "emp_id": "EMP-00002",
        "name": "Ravi Kumar",
        "dept_id": base_org["dept_id"],
        "role_id": base_org["role_id"],
        "grade": "E2",
        "join_date": "2026-01-15",
    }
    await erp_server.dispatch_raw("upsert_employee", {"record": record}, _headers(_write_token()))

    masked = await erp_server.dispatch_raw(
        "get_employee", {"emp_id": "EMP-00002"}, _headers(_read_token())
    )
    assert masked["contact_encrypted"] is None

    without_pii_scope = await erp_server.dispatch_raw(
        "get_employee", {"emp_id": "EMP-00002", "view": "full"}, _headers(_full_read_token())
    )
    assert without_pii_scope["contact_encrypted"] is None  # degrades silently, doesn't error

    with_pii_scope = await erp_server.dispatch_raw(
        "get_employee", {"emp_id": "EMP-00002", "view": "full"}, _headers(_pii_read_token())
    )
    assert "contact_encrypted" in with_pii_scope  # present (still None here, no real data seeded)


@pytest.mark.asyncio
async def test_get_employee_not_found(erp_server: AwpMcpServer) -> None:
    with pytest.raises(NotFoundError):
        await erp_server.dispatch_raw(
            "get_employee", {"emp_id": "EMP-99999"}, _headers(_read_token())
        )


@pytest.mark.asyncio
async def test_query_employees_filters_by_dept(erp_server: AwpMcpServer, base_org: dict) -> None:
    for i in range(3):
        record = {
            "emp_id": f"EMP-1000{i}",
            "name": f"Person {i}",
            "dept_id": base_org["dept_id"],
            "role_id": base_org["role_id"],
            "grade": "E2",
            "join_date": "2026-01-15",
        }
        await erp_server.dispatch_raw(
            "upsert_employee", {"record": record}, _headers(_write_token())
        )

    result = await erp_server.dispatch_raw(
        "query_employees", {"dept_id": base_org["dept_id"]}, _headers(_read_token())
    )
    assert len(result["employees"]) == 3


@pytest.mark.asyncio
async def test_upsert_employee_non_identity_field_needs_no_gate(
    erp_server: AwpMcpServer, base_org: dict
) -> None:
    record = {
        "emp_id": "EMP-00003",
        "name": "Meera Iyer",
        "dept_id": base_org["dept_id"],
        "role_id": base_org["role_id"],
        "grade": "E2",
        "join_date": "2026-01-15",
    }
    await erp_server.dispatch_raw("upsert_employee", {"record": record}, _headers(_write_token()))

    updated = await erp_server.dispatch_raw(
        "upsert_employee",
        {"record": {"emp_id": "EMP-00003", "status": "on_leave"}},
        _headers(_write_token()),
    )
    assert updated["status"] == "on_leave"


@pytest.mark.asyncio
async def test_upsert_employee_identity_field_requires_approval(
    erp_server: AwpMcpServer, base_org: dict
) -> None:
    record = {
        "emp_id": "EMP-00004",
        "name": "Kabir Singh",
        "dept_id": base_org["dept_id"],
        "role_id": base_org["role_id"],
        "grade": "E2",
        "join_date": "2026-01-15",
    }
    await erp_server.dispatch_raw("upsert_employee", {"record": record}, _headers(_write_token()))

    with pytest.raises(ApprovalRequiredError):
        await erp_server.dispatch_raw(
            "upsert_employee",
            {"record": {"emp_id": "EMP-00004", "name": "Kabir S. Singh"}},
            _headers(_write_token()),
        )

    patch = {"emp_id": "EMP-00004", "name": "Kabir S. Singh"}
    token = _approval("record_correction", patch)
    # approval_token is a sibling of "record" (the pipeline pops it from the
    # top-level tool payload, not from inside a nested field — doc 11 §3).
    fixed = await erp_server.dispatch_raw(
        "upsert_employee", {"record": patch, "approval_token": token}, _headers(_write_token())
    )
    assert fixed["name"] == "Kabir S. Singh"


@pytest.mark.asyncio
async def test_upsert_candidate_insert_and_dedupe_conflict(erp_server: AwpMcpServer) -> None:
    first = await erp_server.dispatch_raw(
        "upsert_candidate",
        {
            "record": {
                "source": "internal_db",
                "profile": {"name": "Nisha Patel", "contact": {"email": "nisha@x.com"}},
            }
        },
        _headers(_write_token()),
    )
    assert first["profile"]["name"] == "Nisha Patel"

    with pytest.raises(ConflictError):
        await erp_server.dispatch_raw(
            "upsert_candidate",
            {
                "record": {
                    "source": "csv_import",
                    "profile": {"name": "N. Patel", "contact": {"email": "Nisha@X.com"}},
                }
            },
            _headers(_write_token()),
        )


@pytest.mark.asyncio
async def test_upsert_candidate_update_by_id_bypasses_dedupe(erp_server: AwpMcpServer) -> None:
    created = await erp_server.dispatch_raw(
        "upsert_candidate",
        {"record": {"source": "internal_db", "profile": {"name": "Dev Kapoor", "contact": {}}}},
        _headers(_write_token()),
    )
    updated = await erp_server.dispatch_raw(
        "upsert_candidate",
        {"record": {"id": created["id"], "status": "shortlisted"}},
        _headers(_write_token()),
    )
    assert updated["status"] == "shortlisted"


@pytest.mark.asyncio
async def test_propose_merge_requires_approval_and_merges(erp_server: AwpMcpServer) -> None:
    a = await erp_server.dispatch_raw(
        "upsert_candidate",
        {
            "record": {
                "source": "internal_db",
                "profile": {"name": "Arjun Mehta", "skills": ["Python"]},
            }
        },
        _headers(_write_token()),
    )
    # bypass dedupe on purpose (different-enough name) to create a second row to merge
    b = await erp_server.dispatch_raw(
        "upsert_candidate",
        {
            "record": {
                "source": "csv_import",
                "profile": {"name": "Arjun M. (dup)", "extra_field": "x"},
            }
        },
        _headers(_write_token()),
    )

    merge_payload = {"record_a": a["id"], "record_b": b["id"], "evidence": {}}
    with pytest.raises(ApprovalRequiredError):
        await erp_server.dispatch_raw("propose_merge", merge_payload, _headers(_write_token()))

    token = _approval("data_merge", merge_payload)
    merged = await erp_server.dispatch_raw(
        "propose_merge", {**merge_payload, "approval_token": token}, _headers(_write_token())
    )
    assert merged["id"] == a["id"]
    assert merged["profile"]["extra_field"] == "x"  # merged in from b

    with pytest.raises(NotFoundError):
        await erp_server.dispatch_raw(
            "get_candidate", {"candidate_id": b["id"]}, _headers(_read_token())
        )


@pytest.mark.asyncio
async def test_convert_candidate_to_employee_requires_approval(
    erp_server: AwpMcpServer, base_org: dict
) -> None:
    candidate = await erp_server.dispatch_raw(
        "upsert_candidate",
        {
            "record": {
                "source": "internal_db",
                "profile": {"name": "Farah Sheikh", "skills_normalized": ["SQL"]},
            }
        },
        _headers(_write_token()),
    )
    emp_fields = {
        "emp_id": "EMP-00099",
        "dept_id": base_org["dept_id"],
        "role_id": base_org["role_id"],
        "grade": "E2",
        "join_date": "2026-02-01",
    }
    convert_payload = {"candidate_id": candidate["id"], "emp_fields": emp_fields}

    with pytest.raises(ApprovalRequiredError):
        await erp_server.dispatch_raw(
            "convert_candidate_to_employee", convert_payload, _headers(_write_token())
        )

    token = _approval("onboarding", convert_payload)
    employee = await erp_server.dispatch_raw(
        "convert_candidate_to_employee",
        {**convert_payload, "approval_token": token},
        _headers(_write_token()),
    )
    assert employee["emp_id"] == "EMP-00099"
    assert employee["candidate_id"] == candidate["id"]
    assert employee["skills"] == ["SQL"]

    updated_candidate = await erp_server.dispatch_raw(
        "get_candidate", {"candidate_id": candidate["id"]}, _headers(_read_token())
    )
    assert updated_candidate["status"] == "hired"


@pytest.mark.asyncio
async def test_get_role_returns_seeded_role(erp_server: AwpMcpServer, base_org: dict) -> None:
    role = await erp_server.dispatch_raw(
        "get_role", {"role_id": base_org["role_id"]}, _headers(_read_token())
    )
    assert role["title"] == "Software Engineer (E2)"


@pytest.mark.asyncio
async def test_get_role_unknown_id_404s(erp_server: AwpMcpServer) -> None:
    with pytest.raises(NotFoundError):
        await erp_server.dispatch_raw(
            "get_role", {"role_id": "not-a-role"}, _headers(_read_token())
        )


@pytest.mark.asyncio
async def test_upsert_role_caches_role_profile(
    erp_server: AwpMcpServer, base_org: dict
) -> None:
    updated = await erp_server.dispatch_raw(
        "upsert_role",
        {
            "record": {
                "id": base_org["role_id"],
                "role_profile": {"must_have": ["Python"], "min_exp_months": 24},
            }
        },
        _headers(_write_token()),
    )
    assert updated["role_profile"]["must_have"] == ["Python"]


@pytest.mark.asyncio
async def test_upsert_role_creates_new_role(erp_server: AwpMcpServer, base_org: dict) -> None:
    created = await erp_server.dispatch_raw(
        "upsert_role",
        {
            "record": {
                "title": "Data Analyst (E2)",
                "grade": "E2",
                "dept_id": base_org["dept_id"],
                "role_profile": {},
            }
        },
        _headers(_write_token()),
    )
    assert created["title"] == "Data Analyst (E2)"
    assert created["id"] != base_org["role_id"]
