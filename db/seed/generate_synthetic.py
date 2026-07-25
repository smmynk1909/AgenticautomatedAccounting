"""Synthetic company data generator — doc 09 §6 eval fixtures: "40 employees,
200 candidates, 12 projects, 18 months of ledger." Deterministic (fixed
random seed) so eval suites (Sprint 7+) get identical fixtures run to run.

Usage: `uv run python db/seed/generate_synthetic.py` (reads `DATABASE_URL`
from the environment; `make seed` wraps this). Requires `make migrate`
(alembic upgrade head) to have already created the schema — this script
reflects the existing tables rather than redeclaring them, so it can never
drift from the migrations.

Refuses to run against a non-empty `departments` table — reset the DB
(`docker compose down -v` + `make migrate`) before re-seeding.
"""

from __future__ import annotations

import asyncio
import os
import random
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml
from faker import Faker
from sqlalchemy import MetaData, Table, func, select
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

SEED = 42
random.seed(SEED)
fake = Faker("en_IN")
Faker.seed(SEED)

SEED_DIR = Path(__file__).parent

DEPARTMENTS = ["Admin", "HR", "Operations", "Finance", "Support", "Engineering"]
GRADES = ["E1", "E2", "E3", "E4", "E5"]
GRADE_BANDS = {
    "E1": (Decimal("400000"), Decimal("600000"), Decimal("800000")),
    "E2": (Decimal("700000"), Decimal("1000000"), Decimal("1300000")),
    "E3": (Decimal("1200000"), Decimal("1700000"), Decimal("2200000")),
    "E4": (Decimal("2000000"), Decimal("2800000"), Decimal("3600000")),
    "E5": (Decimal("3200000"), Decimal("4500000"), Decimal("6000000")),
}
JOB_TITLES = {
    "Admin": "Admin Executive",
    "HR": "HR Business Partner",
    "Operations": "Delivery Manager",
    "Finance": "Finance Analyst",
    "Support": "Support Engineer",
    "Engineering": "Software Engineer",
}
N_EMPLOYEES = 40
N_CANDIDATES = 200
N_PROJECTS = 12
LEDGER_MONTHS = 18


def _uuid() -> str:
    return str(uuid.uuid4())


async def _load_yaml(name: str) -> Any:
    with (SEED_DIR / name).open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


async def _refuse_if_already_seeded(conn: AsyncConnection, departments: Table) -> None:
    count = (await conn.execute(select(func.count()).select_from(departments))).scalar_one()
    if count:
        raise RuntimeError(
            "departments table is non-empty — refusing to double-seed. "
            "Reset the DB (docker compose down -v && make migrate) first."
        )


async def seed_config_tables(conn: AsyncConnection, tables: dict[str, Table]) -> dict[str, str]:
    coa = await _load_yaml("coa_seed.yaml")
    await conn.execute(tables["accounts"].insert(), coa)

    skills_raw = await _load_yaml("skills_master.yaml")
    skill_ids: dict[str, str] = {row["name"]: _uuid() for row in skills_raw}
    await conn.execute(
        tables["skills_master"].insert(),
        [
            {
                "id": skill_ids[row["name"]],
                "name": row["name"],
                "synonyms": row["synonyms"],
                "category": row["category"],
            }
            for row in skills_raw
        ],
    )

    entitlements = await _load_yaml("policies_seed.yaml")
    await conn.execute(tables["entitlement_matrix"].insert(), entitlements)

    tax_tables_rows = [
        dict(
            id=_uuid(),
            kind=kind,
            version="seed-1",
            effective_from=date(2025, 4, 1),
            effective_to=None,
            data=data,
        )
        for kind, data in {
            "it_slabs": {"regime": "new", "slabs": [{"upto": 300000, "rate": 0}, {"upto": 700000, "rate": 0.05}]},
            "pf": {"employee_rate": 0.12, "employer_rate": 0.12, "wage_ceiling": 15000},
            "esi": {"employee_rate": 0.0075, "employer_rate": 0.0325, "wage_ceiling": 21000},
            "pt_states": {"KA": {"monthly": 200}, "MH": {"monthly": 200}},
            "gst_rates": {"services_domestic": 0.18, "services_export": 0.0},
            "tds_sections": {"194C": 0.01, "194J": 0.10, "192": "slab"},
        }.items()
    ]
    await conn.execute(tables["tax_tables"].insert(), tax_tables_rows)

    return skill_ids


async def seed_org(
    conn: AsyncConnection, tables: dict[str, Table], skill_ids: dict[str, str]
) -> list[dict[str, Any]]:
    dept_ids = {name: _uuid() for name in DEPARTMENTS}
    await conn.execute(
        tables["departments"].insert(),
        [{"id": dept_ids[name], "name": name, "head_emp_id": None} for name in DEPARTMENTS],
    )

    band_ids: dict[str, str] = {}
    band_rows = []
    for grade, (lo, mid, hi) in GRADE_BANDS.items():
        band_id = _uuid()
        band_ids[grade] = band_id
        band_rows.append(
            dict(id=band_id, grade=grade, min=lo, mid=mid, max=hi, currency="INR", effective_from=date(2025, 4, 1))
        )
    await conn.execute(tables["salary_bands"].insert(), band_rows)

    role_ids: dict[tuple[str, str], str] = {}
    role_rows = []
    for dept_name in DEPARTMENTS:
        for grade in GRADES:
            role_id = _uuid()
            role_ids[(dept_name, grade)] = role_id
            role_rows.append(
                dict(
                    id=role_id,
                    title=f"{JOB_TITLES[dept_name]} ({grade})",
                    grade=grade,
                    dept_id=dept_ids[dept_name],
                    salary_band_id=band_ids[grade],
                    role_profile={"skills": []},
                )
            )
    await conn.execute(tables["roles"].insert(), role_rows)

    employees: list[dict[str, Any]] = []
    managers_by_dept: dict[str, list[str]] = {name: [] for name in DEPARTMENTS}
    for i in range(1, N_EMPLOYEES + 1):
        emp_id = f"EMP-{i:05d}"
        dept_name = DEPARTMENTS[i % len(DEPARTMENTS)]
        grade = random.choices(GRADES, weights=[35, 30, 20, 10, 5])[0]
        manager_pool = managers_by_dept[dept_name]
        manager_id = random.choice(manager_pool) if manager_pool and grade in ("E1", "E2", "E3") else None
        join_date = fake.date_between(start_date="-3y", end_date="-30d")
        employees.append(
            dict(
                emp_id=emp_id,
                candidate_id=None,
                name=fake.name(),
                contact_encrypted=None,  # doc 09 §1 pii column; real encryption is repo-layer (Sprint 2+),
                                          # not meaningful for synthetic fixtures
                dept_id=dept_ids[dept_name],
                role_id=role_ids[(dept_name, grade)],
                manager_id=manager_id,
                grade=grade,
                status="active",
                join_date=join_date,
                exit_date=None,
                skills=random.sample(list(skill_ids.values()), k=min(4, len(skill_ids))),
                docs={},
                comp_structure_id=None,
            )
        )
        if grade in ("E4", "E5"):
            managers_by_dept[dept_name].append(emp_id)
    await conn.execute(tables["employees"].insert(), employees)

    comp_rows = [
        dict(
            id=_uuid(),
            emp_id=e["emp_id"],
            components_encrypted=None,  # doc 09 §1 pgcrypto column; see contact_encrypted note above
            effective_from=e["join_date"],
        )
        for e in employees
    ]
    await conn.execute(tables["comp_structures"].insert(), comp_rows)

    return employees


async def seed_candidates(conn: AsyncConnection, tables: dict[str, Table]) -> None:
    statuses = ["sourced", "screening", "shortlisted", "rejected", "hired", "archived"]
    weights = [30, 25, 15, 15, 10, 5]
    rows = []
    for _ in range(N_CANDIDATES):
        rows.append(
            dict(
                id=_uuid(),
                source=random.choice(["internal_db", "csv_import"]),
                profile={
                    "name": fake.name(),
                    "contact": {"email": fake.email(), "phone": fake.phone_number()},
                    "total_exp_months": random.randint(6, 180),
                    "skills_normalized": random.sample(
                        ["Python", "TypeScript", "React", "SQL", "AWS", "Project Management"], k=3
                    ),
                },
                resume_uri=None,
                status=random.choices(statuses, weights=weights)[0],
                consent={"source_tos_ack": True},
                archived_at=None,
            )
        )
    await conn.execute(tables["candidates"].insert(), rows)


async def seed_projects_and_work(
    conn: AsyncConnection, tables: dict[str, Table], employees: list[dict[str, Any]]
) -> None:
    candidate_pool = [e["emp_id"] for e in employees]

    project_rows = []
    project_ids = []
    for i in range(N_PROJECTS):
        pid = _uuid()
        project_ids.append(pid)
        project_rows.append(
            dict(
                id=pid,
                client=fake.company(),
                sow_ref=f"SOW-{2024 + i % 3}-{i:03d}",
                status=random.choice(["active", "active", "active", "completed"]),
                budget_hours=Decimal(random.choice([500, 1000, 1500, 2000])),
                billing_type=random.choice(["t_and_m", "fixed"]),
            )
        )
    await conn.execute(tables["projects"].insert(), project_rows)

    milestone_rows = []
    for pid in project_ids:
        for m in range(random.randint(2, 4)):
            milestone_rows.append(
                dict(
                    id=_uuid(),
                    project_id=pid,
                    title=f"Milestone {m + 1}",
                    due=fake.date_between(start_date="-6m", end_date="+6m"),
                    acceptance={"criteria": "client sign-off"},
                    status=random.choice(["planned", "in_progress", "done"]),
                    invoice_trigger=(m % 2 == 0),
                )
            )
    await conn.execute(tables["milestones"].insert(), milestone_rows)

    allocation_rows = []
    work_log_rows = []
    today = date.today()
    for pid in project_ids:
        team = random.sample(candidate_pool, k=min(4, len(candidate_pool)))
        for emp_id in team:
            start = fake.date_between(start_date="-18m", end_date="-1m")
            allocation_rows.append(
                dict(
                    id=_uuid(),
                    emp_id=emp_id,
                    project_id=pid,
                    pct=Decimal(random.choice([25, 50, 75, 100])),
                    from_date=start,
                    to_date=None,
                )
            )
            # one work_log per week from `start` to today, capped to keep volume sane
            cursor = start
            weeks = 0
            while cursor < today and weeks < 78:  # ~18 months of weekly entries
                work_log_rows.append(
                    dict(
                        id=_uuid(),
                        emp_id=emp_id,
                        project_id=pid,
                        date=cursor,
                        hours=Decimal(random.choice([20, 32, 40])),
                        task_ref=f"TASK-{random.randint(100, 999)}",
                        notes=None,
                    )
                )
                cursor += timedelta(weeks=1)
                weeks += 1
    await conn.execute(tables["allocations"].insert(), allocation_rows)
    for chunk_start in range(0, len(work_log_rows), 500):
        await conn.execute(tables["work_logs"].insert(), work_log_rows[chunk_start : chunk_start + 500])


async def seed_ledger(conn: AsyncConnection, tables: dict[str, Table]) -> None:
    today = date.today()
    months = []
    cursor = date(today.year, today.month, 1)
    for i in range(LEDGER_MONTHS):
        y, m = cursor.year, cursor.month - i
        while m <= 0:
            m += 12
            y -= 1
        months.append(date(y, m, 1))
    months.reverse()  # oldest first

    period_rows = [
        dict(period=f"{d.year:04d}-{d.month:02d}", status="closed" if i < len(months) - 1 else "open")
        for i, d in enumerate(months)
    ]
    await conn.execute(tables["periods"].insert(), period_rows)

    entry_rows = []
    line_rows = []
    for d in months:
        period = f"{d.year:04d}-{d.month:02d}"

        # Monthly rent: dr Rent Expense (5003) / cr Bank (1001)
        rent_entry_id = _uuid()
        entry_rows.append(
            dict(id=rent_entry_id, date=d, period=period, ref=f"RENT-{period}", posted_by="seed", approval_ref=None)
        )
        rent_amount = Decimal("150000.00")
        line_rows += [
            dict(id=_uuid(), entry_id=rent_entry_id, account="5003", dr=rent_amount, cr=Decimal("0"), cost_center="ops", meta={}),
            dict(id=_uuid(), entry_id=rent_entry_id, account="1001", dr=Decimal("0"), cr=rent_amount, cost_center="ops", meta={}),
        ]

        # Monthly salary accrual: dr Salaries Expense (5001) / cr Salary Payable (2002)
        salary_entry_id = _uuid()
        entry_rows.append(
            dict(id=salary_entry_id, date=d, period=period, ref=f"PAYROLL-{period}", posted_by="seed", approval_ref=None)
        )
        salary_amount = Decimal(random.randint(2_800_000, 3_200_000))
        line_rows += [
            dict(id=_uuid(), entry_id=salary_entry_id, account="5001", dr=salary_amount, cr=Decimal("0"), cost_center="payroll", meta={}),
            dict(id=_uuid(), entry_id=salary_entry_id, account="2002", dr=Decimal("0"), cr=salary_amount, cost_center="payroll", meta={}),
        ]

        # Monthly software subscription: dr Software Subscriptions (5004) / cr Bank (1001)
        sw_entry_id = _uuid()
        entry_rows.append(
            dict(id=sw_entry_id, date=d, period=period, ref=f"SUBS-{period}", posted_by="seed", approval_ref=None)
        )
        sw_amount = Decimal("85000.00")
        line_rows += [
            dict(id=_uuid(), entry_id=sw_entry_id, account="5004", dr=sw_amount, cr=Decimal("0"), cost_center="it", meta={}),
            dict(id=_uuid(), entry_id=sw_entry_id, account="1001", dr=Decimal("0"), cr=sw_amount, cost_center="it", meta={}),
        ]

    await conn.execute(tables["journal_entries"].insert(), entry_rows)
    await conn.execute(tables["journal_lines"].insert(), line_rows)

    def _fy_for(d: date) -> str:
        # Indian FY: Apr-Mar, e.g. Jan 2026 -> "2025-26", Apr 2026 -> "2026-27"
        return f"{d.year}-{str(d.year + 1)[2:]}" if d.month >= 4 else f"{d.year - 1}-{str(d.year)[2:]}"

    fy_rows = [
        dict(fy=fy, invoice_seq=0, updated_at=datetime.now(timezone.utc))
        for fy in sorted({_fy_for(d) for d in months})
    ]
    if fy_rows:
        await conn.execute(tables["fy_counters"].insert(), fy_rows)


async def main() -> None:
    database_url = os.environ["DATABASE_URL"]
    engine = create_async_engine(database_url)
    metadata = MetaData()

    async with engine.connect() as conn:
        await conn.run_sync(metadata.reflect)
    tables = {t.name: t for t in metadata.sorted_tables}

    async with engine.begin() as conn:
        await _refuse_if_already_seeded(conn, tables["departments"])
        skill_ids = await seed_config_tables(conn, tables)
        employees = await seed_org(conn, tables, skill_ids)
        await seed_candidates(conn, tables)
        await seed_projects_and_work(conn, tables, employees)
        await seed_ledger(conn, tables)

    await engine.dispose()
    print(
        f"Seeded {N_EMPLOYEES} employees, {N_CANDIDATES} candidates, "
        f"{N_PROJECTS} projects, {LEDGER_MONTHS} months of ledger (seed={SEED})."
    )


if __name__ == "__main__":
    asyncio.run(main())
