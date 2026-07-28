"""`skill_normalize` — doc 08 §7: "terms[] → skills_master ids (fuzzy +
synonym table)". `mcp-hrsourcing` owns no DB of its own (skills_master is
`mcp-erp`'s aggregate) — the caller fetches the vocabulary via
`erp.query_policies(domain="skills_master")` and supplies it here, same
"no MCP server calls another MCP server" convention as everywhere else.
Fuzzy matching uses `difflib.SequenceMatcher` (stdlib, no new dependency),
matching `mcps/erp/awp_mcp_erp/dedupe.py`'s precedent for this exact
trade-off (trigram-ish fuzzy match without pulling in rapidfuzz).
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

MATCH_THRESHOLD = 0.85


@dataclass(frozen=True)
class SkillVocabEntry:
    id: str
    name: str
    synonyms: list[str]


def _entry_from_dict(d: dict[str, Any]) -> SkillVocabEntry:
    return SkillVocabEntry(id=d["id"], name=d["name"], synonyms=list(d.get("synonyms") or []))


def _best_match(
    term: str, vocabulary: list[SkillVocabEntry]
) -> tuple[SkillVocabEntry, float] | None:
    term_l = term.strip().lower()
    if not term_l:
        return None
    best: tuple[SkillVocabEntry, float] | None = None
    for entry in vocabulary:
        candidates = [entry.name, *entry.synonyms]
        score = max(SequenceMatcher(None, term_l, c.lower()).ratio() for c in candidates)
        if best is None or score > best[1]:
            best = (entry, score)
    return best


def normalize_skills(terms: list[str], vocabulary: list[dict[str, Any]]) -> list[dict[str, Any]]:
    vocab_entries = [_entry_from_dict(v) for v in vocabulary]
    results = []
    for term in terms:
        match = _best_match(term, vocab_entries)
        if match is not None and match[1] >= MATCH_THRESHOLD:
            entry, score = match
            results.append({"term": term, "skill_id": entry.id, "name": entry.name, "score": score})
        else:
            results.append({"term": term, "skill_id": None, "name": None, "score": 0.0})
    return results
