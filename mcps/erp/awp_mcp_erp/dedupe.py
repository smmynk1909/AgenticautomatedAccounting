"""Candidate dedupe pipeline — doc 03 §2.2: "normalized email/phone exact
match + name+DOB fuzzy (trigram > 0.85) -> merge proposal, human confirms
merges (approval gate `data_merge`)."

This module only *detects* duplicates — `upsert_candidate` surfaces a
`CONFLICT` with the match list when any are found (doc 08 §1); nothing here
ever merges automatically. Name matching uses `difflib.SequenceMatcher`
rather than Postgres `pg_trgm` so the detection logic is identical in unit
tests (sqlite) and production (Postgres) — the docs' trigram GIN index
(migration 0001) is a retrieval-speed concern for the *candidate pool*
lookup, not the fuzziness algorithm itself.
"""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any

from pydantic import BaseModel

FUZZY_THRESHOLD = 0.85


class DedupeMatch(BaseModel):
    candidate_id: str
    reason: str  # "email" | "phone" | "name_fuzzy"
    score: float


def _normalize_email(email: str | None) -> str | None:
    return email.strip().lower() if email else None


def _normalize_phone(phone: str | None) -> str | None:
    if not phone:
        return None
    digits = "".join(ch for ch in phone if ch.isdigit())
    return digits[-10:] if len(digits) >= 10 else None


def _name_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def find_duplicates(
    new_profile: dict[str, Any], existing: list[dict[str, Any]]
) -> list[DedupeMatch]:
    """`existing` rows: `{"id": ..., "profile": {...}}` (candidates table rows)."""
    new_contact = new_profile.get("contact", {}) or {}
    new_email = _normalize_email(new_contact.get("email"))
    new_phone = _normalize_phone(new_contact.get("phone"))
    new_name = new_profile.get("name", "")

    matches: list[DedupeMatch] = []
    for row in existing:
        profile = row["profile"] or {}
        contact = profile.get("contact", {}) or {}
        email = _normalize_email(contact.get("email"))
        phone = _normalize_phone(contact.get("phone"))
        name = profile.get("name", "")

        if new_email and email and new_email == email:
            matches.append(DedupeMatch(candidate_id=row["id"], reason="email", score=1.0))
            continue
        if new_phone and phone and new_phone == phone:
            matches.append(DedupeMatch(candidate_id=row["id"], reason="phone", score=1.0))
            continue
        if new_name and name:
            score = _name_similarity(new_name, name)
            if score > FUZZY_THRESHOLD:
                matches.append(
                    DedupeMatch(candidate_id=row["id"], reason="name_fuzzy", score=round(score, 3))
                )
    return matches
