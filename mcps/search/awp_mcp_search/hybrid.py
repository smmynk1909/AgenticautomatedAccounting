"""Hybrid ranking — doc 08 §4 "hybrid BM25+dense (+rerank if enabled)".

M-RERANK is Phase 2+ (`config/models.yaml`) so reranking is out of scope.
Real BM25 needs an inverted index (Postgres FTS per the doc's title) — that
integration is real scope this sprint doesn't need to take on to make
hybrid search *work*, so the keyword half is a plain token-overlap score
computed over the same chunk text Qdrant already returned, not a tsvector
query. Documented as a scope reduction (DEVIATIONS.md), swappable for real
Postgres FTS later without changing `search_kb`/`search_candidates`'s
contract (the merge step is the same either way).
"""

from __future__ import annotations

import re

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


def keyword_score(query: str, text: str) -> float:
    q_tokens = _tokens(query)
    if not q_tokens:
        return 0.0
    hits = len(q_tokens & _tokens(text))
    return hits / len(q_tokens)


def blend(dense_score: float, kw_score: float, *, dense_weight: float = 0.6) -> float:
    return dense_weight * dense_score + (1 - dense_weight) * kw_score
