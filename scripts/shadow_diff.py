"""Payroll shadow-run comparator — doc 06 §7.1 / doc 12 §2's tree.

Compares a FIN-1-computed payroll register (mcp-finance.compute_payroll's
`register.lines`) against a "manual payroll" reference of the same shape,
to the rupee, per doc 06 §7 acceptance test 1: "shadow run matches the
existing manual payroll to the rupee for 2 consecutive months before
go-live (100% employees)."

This is the comparator itself — "the harness runs" (doc 12 §5's Sprint 6
DoD) means this script functions correctly against real inputs, not that
2 real shadow cycles have already been verified (that's Sprint 11's gate:
"2 clean payroll shadow cycles" before go-live). There is no real manual-
payroll reference data in this dev environment to run it against yet.

Usage:
    python scripts/shadow_diff.py --computed computed.json --manual manual.json

Both files: a JSON object with a "lines" array of
`{emp_id, net, gross?, deductions?}` objects (the same shape
`compute_payroll`'s register lines already have — either file can be a
raw register export).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class LineDiff:
    emp_id: str
    computed_net: str
    manual_net: str
    delta: str


@dataclass(frozen=True)
class ShadowDiffReport:
    matched: int
    mismatched: list[LineDiff]
    missing_in_manual: list[str]
    missing_in_computed: list[str]

    @property
    def clean(self) -> bool:
        return not self.mismatched and not self.missing_in_manual and not self.missing_in_computed


def _net_by_emp(lines: list[dict[str, Any]]) -> dict[str, Decimal]:
    result: dict[str, Decimal] = {}
    for line in lines:
        try:
            result[line["emp_id"]] = Decimal(str(line["net"]))
        except (InvalidOperation, KeyError) as exc:
            raise ValueError(f"malformed payroll line (needs emp_id + net): {line!r}") from exc
    return result


def compare(
    computed_lines: list[dict[str, Any]], manual_lines: list[dict[str, Any]]
) -> ShadowDiffReport:
    computed = _net_by_emp(computed_lines)
    manual = _net_by_emp(manual_lines)

    common = set(computed) & set(manual)
    mismatched = [
        LineDiff(
            emp_id=emp_id,
            computed_net=str(computed[emp_id]),
            manual_net=str(manual[emp_id]),
            delta=str(computed[emp_id] - manual[emp_id]),
        )
        for emp_id in sorted(common)
        if computed[emp_id] != manual[emp_id]
    ]
    matched = len(common) - len(mismatched)

    return ShadowDiffReport(
        matched=matched,
        mismatched=mismatched,
        missing_in_manual=sorted(set(computed) - set(manual)),
        missing_in_computed=sorted(set(manual) - set(computed)),
    )


def _load_lines(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    lines: list[dict[str, Any]] = data.get("lines", data) if isinstance(data, dict) else data
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--computed", required=True, type=Path)
    parser.add_argument("--manual", required=True, type=Path)
    args = parser.parse_args(argv)

    report = compare(_load_lines(args.computed), _load_lines(args.manual))

    print(f"matched: {report.matched}")
    print(f"mismatched: {len(report.mismatched)}")
    for diff in report.mismatched:
        print(
            f"  {diff.emp_id}: computed={diff.computed_net} "
            f"manual={diff.manual_net} delta={diff.delta}"
        )
    if report.missing_in_manual:
        print(f"missing in manual reference: {report.missing_in_manual}")
    if report.missing_in_computed:
        print(f"missing in FIN-1 register: {report.missing_in_computed}")

    if report.clean:
        print("CLEAN — shadow run matches manual payroll to the rupee, 100% employees.")
        return 0
    print("NOT CLEAN — see above.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
