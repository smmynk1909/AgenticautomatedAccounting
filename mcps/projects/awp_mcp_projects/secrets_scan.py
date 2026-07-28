"""Secrets scanner — doc 08 §8: "secrets_scan(text|diff) -> findings;
called by OPS-1d pipeline before any code reaches a model context." Pure
regex pattern matching against known credential *shapes* (AWS keys, GitHub
tokens, Slack tokens, private key headers, generic high-entropy
`*_KEY`/`*_SECRET`/`*_TOKEN` assignments) — not a secrets-vault lookup or
an entropy-analysis model. This is the same class of tool as every real
open-source secrets scanner (gitleaks, trufflehog): known-shape regex
first, since that's what actually catches real leaked-credential formats.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("aws_access_key_id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("aws_secret_access_key", re.compile(r"\b[A-Za-z0-9/+=]{40}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    (
        "private_key_header",
        re.compile(r"-----BEGIN (RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    ),
    (
        "generic_secret_assignment",
        re.compile(
            r"(?i)\b\w*(secret|api_key|apikey|token|password)\w*\s*[:=]\s*"
            r"['\"][A-Za-z0-9_\-/+=]{16,}['\"]"
        ),
    ),
]


@dataclass(frozen=True)
class SecretFinding:
    kind: str
    line: int
    match_preview: str  # first/last 4 chars only — never the full secret


def _preview(matched: str) -> str:
    if len(matched) <= 10:
        return "*" * len(matched)
    return f"{matched[:4]}...{matched[-4:]}"


def scan_text(text: str) -> list[SecretFinding]:
    findings: list[SecretFinding] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        for kind, pattern in _PATTERNS:
            for m in pattern.finditer(line):
                findings.append(
                    SecretFinding(kind=kind, line=line_no, match_preview=_preview(m.group(0)))
                )
    return findings


def redact_text(text: str) -> str:
    """doc 05 §2.4: "secrets scanner runs on all context *before* it
    reaches the model" — prevention, not just detection. Returns `text`
    with every matched span replaced by `[REDACTED:<kind>]`, so a caller
    (OPS-1's CodeAssist node) never needs the raw matched value — which
    `SecretFinding.match_preview` deliberately never exposes — to act on
    a finding."""
    redacted = text
    for kind, pattern in _PATTERNS:
        redacted = pattern.sub(f"[REDACTED:{kind}]", redacted)
    return redacted
