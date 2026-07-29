"""Synthetic labeled resume corpus for doc 04 §5.1's acceptance test:
"Resume extraction F1 ≥ 0.92 on a 50-resume labeled set (fields: dates,
orgs, skills); date-overlap red-flag detection recall ≥ 0.9."

No real resumes exist in this build (synthetic-company-only, doc 09's
privacy stance) — this generates resume *text* and its exact ground-truth
`CandidateProfile` from the same structured data in lockstep (Faker +
fixed seed, same pattern as `db/seed/generate_synthetic.py`), so the
ground truth is correct by construction rather than hand-labeled. ~30% of
resumes get two deliberately overlapping positions, giving the overlap
red-flag recall metric something real to measure.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from awp_shared.candidate_profile import CandidateProfile, Contact, Gap, Position
from faker import Faker

SEED = 42
SKILL_POOL = [
    "Python", "TypeScript", "React", "SQL", "AWS", "Docker", "Kubernetes",
    "Django", "FastAPI", "PostgreSQL", "Project Management", "Figma",
]  # fmt: skip


@dataclass(frozen=True)
class LabeledResume:
    id: str
    text: str
    ground_truth: CandidateProfile
    has_real_overlap: bool


def _month_str(year: int, month: int) -> str:
    total = year * 12 + (month - 1)
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def _shift(ym: str, months: int) -> str:
    year, mon = (int(p) for p in ym.split("-"))
    return _month_str(year, mon + months)


def generate_labeled_resumes(n: int = 50, seed: int = SEED) -> list[LabeledResume]:
    fake = Faker("en_IN")
    Faker.seed(seed)
    rng = random.Random(seed)

    resumes = []
    for i in range(n):
        name = fake.name()
        email = fake.email()
        phone = fake.phone_number()
        overlap = i % 3 == 0  # deterministic ~33% overlap rate, not RNG-order-sensitive

        start = _month_str(rng.randint(2015, 2020), rng.randint(1, 12))
        pos1_end = _shift(start, rng.randint(18, 36))
        if overlap:
            pos2_start = _shift(pos1_end, -rng.randint(3, 8))  # starts before pos1 ends
            gaps: list[Gap] = []
        else:
            gap_months = rng.choice([0, 0, 4, 8])
            pos2_start = _shift(pos1_end, gap_months)
            gaps = [Gap.new(from_=pos1_end, to=pos2_start, months=gap_months)] if gap_months else []
        pos2_end = _shift(pos2_start, rng.randint(12, 30))

        org1, org2 = fake.company(), fake.company()
        title1, title2 = (
            rng.choice(["Software Engineer", "Analyst"]),
            rng.choice(["Senior Engineer", "Team Lead"]),
        )
        skills = rng.sample(SKILL_POOL, k=4)
        degree = rng.choice(["B.Tech Computer Science", "B.Sc Mathematics", "MBA"])
        institution = fake.city() + " University"

        positions = [
            Position.new(org=org1, title=title1, from_=start, to=pos1_end, skills=skills[:2]),
            Position.new(org=org2, title=title2, from_=pos2_start, to=pos2_end, skills=skills[2:]),
        ]
        total_exp_months = sum(_month_index(p.to) - _month_index(p.from_) for p in positions)

        truth = CandidateProfile(
            name=name,
            contact=Contact(email=email, phone=phone),
            total_exp_months=total_exp_months,
            positions=positions,
            education=[f"{degree}, {institution}"],
            skills_normalized=sorted(set(skills)),
            gaps=gaps,
        )

        text = (
            f"{name}\n"
            f"Email: {email} | Phone: {phone}\n\n"
            f"EXPERIENCE\n"
            f"{org1} — {title1} ({start} to {pos1_end})\n"
            f"{org2} — {title2} ({pos2_start} to {pos2_end})\n\n"
            f"EDUCATION\n{degree}, {institution}\n\n"
            f"SKILLS\n{', '.join(skills)}\n"
        )

        resumes.append(
            LabeledResume(
                id=f"res-{i:03d}", text=text, ground_truth=truth, has_real_overlap=overlap
            )
        )
    return resumes


def _month_index(ym: str) -> int:
    year, month = ym.split("-")
    return int(year) * 12 + int(month)
