"""`extract_text` — doc 08 §3: "text + layout blocks (pdfplumber/pypdf +
Tesseract fallback)". OCR fallback for scanned/image-only PDFs is not
implemented (needs a Tesseract binary — no agent lands with a scanned-doc
workflow yet; `mcp-erp.record_expense`'s `doc_uri` field, the nearest
candidate, is FIN-1's, Sprint 5+) — a page with no extractable text layer
returns an empty block rather than failing the whole call.
"""

from __future__ import annotations

import io
from typing import Any

import pdfplumber
from awp_mcp_base.ctx import Ctx
from awp_mcp_base.server import AwpMcpServer
from awp_shared.errors import NotFoundError, ValidationError

from awp_mcp_docs.storage import DocStorage


def register_extract_tools(server: AwpMcpServer, storage: DocStorage) -> None:
    @server.tool()
    async def extract_text(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        file_uri = payload.get("file_uri")
        if not file_uri:
            raise ValidationError("extract_text requires 'file_uri'")
        try:
            stored = storage.get(file_uri)
        except FileNotFoundError as exc:
            raise NotFoundError(str(exc)) from exc

        blocks: list[dict[str, Any]] = []
        with pdfplumber.open(io.BytesIO(stored.data)) as pdf:
            for i, page in enumerate(pdf.pages):
                blocks.append({"page": i, "text": page.extract_text() or ""})

        return {"text": "\n".join(b["text"] for b in blocks), "blocks": blocks}
