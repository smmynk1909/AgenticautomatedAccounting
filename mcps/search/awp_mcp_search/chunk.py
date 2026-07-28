"""Doc chunking — doc 08 §4 "chunking (600-token, 80 overlap)". Uses a
whitespace-word count as the token proxy (no tokenizer dependency pulled in
just for chunk boundaries) — close enough for chunk-sizing purposes, not a
precision requirement anywhere downstream.
"""

from __future__ import annotations

CHUNK_WORDS = 600
OVERLAP_WORDS = 80


def chunk_text(
    text: str, *, chunk_words: int = CHUNK_WORDS, overlap: int = OVERLAP_WORDS
) -> list[str]:
    words = text.split()
    if not words:
        return []
    if len(words) <= chunk_words:
        return [text]
    chunks = []
    step = chunk_words - overlap
    for start in range(0, len(words), step):
        piece = words[start : start + chunk_words]
        if not piece:
            break
        chunks.append(" ".join(piece))
        if start + chunk_words >= len(words):
            break
    return chunks
