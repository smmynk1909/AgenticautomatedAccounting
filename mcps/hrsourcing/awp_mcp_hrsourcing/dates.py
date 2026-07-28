"""Deterministic date-overlap detection over extracted `Position`s — doc
04 §5.1's acceptance test wants overlap red-flag *recall* ≥ 0.9, which an
LLM alone on a 3B model can't reliably hit. Doc 04 §2.3's "deterministic-
first, LLM-last" principle applied to auditing too: the LLM extracts
structured `from`/`to` fields, code detects the overlap.

Dates are `"YYYY-MM"` strings (this build's month-string convention
throughout — payroll periods, journal periods, etc.); `to=""` or
`to="present"` means ongoing, treated as open-ended.
"""

from __future__ import annotations

from awp_shared.candidate_profile import Position, RedFlag, RedFlagType

_OPEN_ENDED = {"", "present", "current", "now"}
_OVERLAP_TOLERANCE_MONTHS = 1  # a 1-month handover between roles isn't a red flag


def _month_index(ym: str) -> int | None:
    try:
        year, month = ym.split("-")
        return int(year) * 12 + int(month)
    except (ValueError, AttributeError):
        return None


def detect_overlaps(positions: list[Position]) -> list[RedFlag]:
    flags: list[RedFlag] = []
    intervals = []
    for pos in positions:
        start = _month_index(pos.from_)
        end = None if pos.to.lower() in _OPEN_ENDED else _month_index(pos.to)
        if start is None:
            continue
        intervals.append((start, end, pos))

    for i in range(len(intervals)):
        start_a, end_a, pos_a = intervals[i]
        for j in range(i + 1, len(intervals)):
            start_b, end_b, pos_b = intervals[j]
            overlap_start = max(start_a, start_b)
            overlap_end = min(
                end_a if end_a is not None else float("inf"),
                end_b if end_b is not None else float("inf"),
            )
            overlap_months = overlap_end - overlap_start
            if overlap_months > _OVERLAP_TOLERANCE_MONTHS:
                flags.append(
                    RedFlag(
                        type=RedFlagType.OVERLAP,
                        evidence=(
                            f"{pos_a.org} ({pos_a.title}, {pos_a.from_}-{pos_a.to or 'present'}) "
                            f"overlaps {pos_b.org} ({pos_b.title}, "
                            f"{pos_b.from_}-{pos_b.to or 'present'})"
                        ),
                    )
                )
    return flags
