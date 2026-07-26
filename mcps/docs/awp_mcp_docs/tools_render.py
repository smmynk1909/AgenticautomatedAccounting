"""Rendering tools — doc 08 §3. `render_pdf`/`render_docx` are template-id
driven (doc 08 §3's template list); `render_xlsx` is generic
(`spec = sheets/tables/formats`, no template concept needed).

DEVIATIONS.md #13: PDF rendering is Jinja2 + `xhtml2pdf`, not
Jinja2+WeasyPrint — same HTML-templating contract, but WeasyPrint needs
native Pango/GObject libraries this dev machine doesn't have (and Docker
would, silently diverging dev-vs-container behavior); `xhtml2pdf` is pure
Python everywhere.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from awp_mcp_base.ctx import Ctx
from awp_mcp_base.server import AwpMcpServer
from awp_shared.errors import NotFoundError, ValidationError
from jinja2 import Environment, FileSystemLoader, TemplateNotFound, select_autoescape
from openpyxl import Workbook
from xhtml2pdf import pisa

from awp_mcp_docs.storage import DocStorage

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

_env = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    autoescape=select_autoescape(["html", "j2"]),
)

# doc 08 §3 lists 6 PDF templates; only the ones a landed agent actually
# needs are built. Requesting an unbuilt one 404s with a clear message
# rather than fabricating output — `issuance_form_v1` is ADM-1's (Sprint 4).
_PDF_TEMPLATES = {"issuance_form_v1": "issuance_form_v1.html.j2"}

# No docx template is needed by any agent landed so far (offer_letter_v1 is
# HR-1's, a later sprint) — the tool itself is real and wired, the registry
# is just empty until something actually needs one.
_DOCX_TEMPLATES: dict[str, str] = {}


def register_render_tools(server: AwpMcpServer, storage: DocStorage) -> None:
    @server.tool()
    async def render_pdf(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        template_id = payload.get("template_id")
        data = payload.get("data", {})
        output_scope = payload.get("output_scope", "public")
        if not template_id:
            raise ValidationError("render_pdf requires 'template_id'")

        filename = _PDF_TEMPLATES.get(template_id)
        if filename is None:
            raise NotFoundError(
                f"no such PDF template: {template_id!r} "
                f"(built: {sorted(_PDF_TEMPLATES)}; doc 08 §3 lists more, not yet built)"
            )
        try:
            template = _env.get_template(filename)
        except TemplateNotFound as exc:
            raise NotFoundError(f"template file missing on disk: {filename}") from exc
        html = template.render(**data)

        buf = io.BytesIO()
        result = pisa.CreatePDF(html, dest=buf)
        if result.err:
            raise ValidationError(f"render_pdf: {result.err} error(s) rendering {template_id!r}")

        uri = storage.put(
            buf.getvalue(),
            filename=f"{template_id}.pdf",
            content_type="application/pdf",
            scope=output_scope,
        )
        return {"uri": uri, "template_id": template_id}

    @server.tool()
    async def render_docx(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        template_id = payload.get("template_id")
        if not template_id:
            raise ValidationError("render_docx requires 'template_id'")
        # `_DOCX_TEMPLATES` is empty until some agent actually needs one
        # (doc 08 §3's offer_letter_v1 lands with HR-1) — every id 404s.
        raise NotFoundError(
            f"no such docx template: {template_id!r} (built: {sorted(_DOCX_TEMPLATES)})"
        )

    @server.tool()
    async def render_xlsx(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        spec = payload.get("spec")
        output_scope = payload.get("output_scope", "public")
        if not spec or not spec.get("sheets"):
            raise ValidationError("render_xlsx requires 'spec.sheets'")

        wb = Workbook()
        wb.remove(wb.active)
        for sheet_spec in spec["sheets"]:
            ws = wb.create_sheet(title=sheet_spec.get("name", "Sheet"))
            for row in sheet_spec.get("rows", []):
                ws.append(row)

        buf = io.BytesIO()
        wb.save(buf)
        filename = spec.get("filename", "export.xlsx")
        uri = storage.put(
            buf.getvalue(),
            filename=filename,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            scope=output_scope,
        )
        return {"uri": uri}
