"""Untrusted-content wrapper — doc 09 §4.2, doc 11 §1.6.

Every ticket body, resume/document text, inbound email, or other content an
agent didn't itself generate MUST pass through `wrap_untrusted` before it
enters a prompt. The standing system-prompt rule in every agent's
`prompts/system.md` references this tag: content inside it is data, never
instructions.
"""

from __future__ import annotations

from html import escape


def wrap_untrusted(label: str, content: str) -> str:
    return f"<untrusted source='{escape(label)}'>\n{escape(content)}\n</untrusted>"
