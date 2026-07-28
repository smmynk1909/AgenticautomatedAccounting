"""Code chunking — doc 08 §8: "code chunks to vector index (tree-sitter
aware chunking)". Real tree-sitter-based syntactic chunking (per-function/
per-class boundaries) is not implemented — no tree-sitter dependency exists
anywhere in this build, and adding one (plus per-language grammar files)
for chunk boundaries only is a large dependency for a boundary-quality
improvement, not a capability gap. This is a line-window chunker (same
overlap-window shape as `mcps/search/awp_mcp_search/chunk.py`'s doc
chunker, sized in lines instead of words since code has meaningful line
structure text doesn't) — a follow-up doc PR could scope real AST-aware
chunking as its own deliverable.
"""

from __future__ import annotations

from dataclasses import dataclass

CHUNK_LINES = 80
OVERLAP_LINES = 10


@dataclass(frozen=True)
class CodeChunk:
    path: str
    start_line: int
    end_line: int
    text: str


def chunk_file(
    path: str, text: str, *, chunk_lines: int = CHUNK_LINES, overlap: int = OVERLAP_LINES
) -> list[CodeChunk]:
    lines = text.splitlines()
    if not lines:
        return []
    if len(lines) <= chunk_lines:
        return [CodeChunk(path=path, start_line=1, end_line=len(lines), text=text)]

    chunks = []
    step = chunk_lines - overlap
    for start in range(0, len(lines), step):
        piece = lines[start : start + chunk_lines]
        if not piece:
            break
        chunks.append(
            CodeChunk(
                path=path,
                start_line=start + 1,
                end_line=start + len(piece),
                text="\n".join(piece),
            )
        )
        if start + chunk_lines >= len(lines):
            break
    return chunks
