"""`extract_resume` — doc 08 §7: "raw text + layout". Takes the file's
bytes directly (base64) rather than a `file_uri` mcp-hrsourcing would fetch
itself — MinIO storage/scope-checking is `mcp-docs`'s aggregate (doc 08 §3
"output_scope controls who can fetch the artifact"); reaching into MinIO
from a second server would bypass that check, same "no MCP server calls
another MCP server" convention as everywhere else in this build. The
calling agent fetches via `docs.get_file` first and hands the bytes here —
see DEVIATIONS.md.
"""

from __future__ import annotations

import base64
import io
from typing import Any

import pdfplumber
from awp_shared.errors import ValidationError


def extract_resume_text(file_bytes_b64: str) -> dict[str, Any]:
    try:
        raw = base64.b64decode(file_bytes_b64, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValidationError(f"file_bytes_b64 is not valid base64: {exc}") from exc

    blocks: list[dict[str, Any]] = []
    try:
        with pdfplumber.open(io.BytesIO(raw)) as pdf:
            for i, page in enumerate(pdf.pages):
                blocks.append({"page": i, "text": page.extract_text() or ""})
    except Exception as exc:  # pdfplumber raises varied low-level parse errors
        raise ValidationError(f"could not parse resume as PDF: {exc}") from exc

    return {"text": "\n".join(b["text"] for b in blocks), "blocks": blocks}
