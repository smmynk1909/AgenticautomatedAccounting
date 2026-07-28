"""HR-1's output filter — doc 04 §2.4/§4, doc 09 §4.3: "confidential-field
denylist per agent (HR pack fields, comp data, band ceilings) checked by
code before any draft leaves the agent". Deliberately code, not another LLM
call — a second model call can be fooled by the same prompt-injection class
of attack the first one might have been; a denylist substring check cannot.
This is defense-in-depth on top of `negotiation.py`'s system prompt, which
is the first (weaker) line of defense.
"""

from __future__ import annotations

from awp_agent_hr1.negotiation import NegotiationPack

# doc 04 §2.4: "must never disclose band ceilings ... or internal walk-away
# numbers in any candidate-facing draft." `band.min`/`band.mid` are
# deliberately NOT denylisted: `negotiation.compute_recommendation` sets
# `recommendation.open` equal to `band.mid` by design (the open offer *is*
# the band midpoint) — denylisting `band.mid` would make it impossible to
# ever legitimately state the open offer. Only the ceiling (`band.max`) and
# the walk-away number (numerically the same value today, kept as two
# entries in case a future `compute_recommendation` change makes them
# diverge) are genuinely confidential per the doc.
_DENYLISTED_FIELDS = ("band.max", "recommendation.walk_away")


def confidential_values(pack: NegotiationPack) -> dict[str, str]:
    """Field path -> its formatted value, for every pack field a
    candidate-facing draft must never contain."""
    values: dict[str, str] = {
        "band.max": _fmt(pack.band.max),
        "recommendation.walk_away": _fmt(pack.recommendation.walk_away),
    }
    return {k: v for k, v in values.items() if k in _DENYLISTED_FIELDS}


def _fmt(value: float) -> str:
    # Matches both "85000" and "85000.0"-style renderings a model might
    # produce for a whole-number float — strip a trailing ".0" so the
    # denylist check isn't defeated by that formatting difference.
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text


def check_draft(draft_text: str, pack: NegotiationPack) -> list[str]:
    """Returns a list of violation descriptions; empty means the draft is
    clean. Every confidential numeric value is checked as a substring
    (formatted with and without thousands separators / decimal noise) —
    exact-value leakage is what doc 04 §5's acceptance test targets, not
    paraphrase detection."""
    violations: list[str] = []
    for field, value in confidential_values(pack).items():
        if _value_present(draft_text, value):
            violations.append(f"draft contains confidential field {field} (value {value})")
    return violations


def _value_present(text: str, value: str) -> bool:
    if value in text:
        return True
    # A comma-grouped rendering (e.g. "85,000") of the same number.
    try:
        grouped = f"{float(value):,.0f}"
    except ValueError:
        return False
    return grouped in text
