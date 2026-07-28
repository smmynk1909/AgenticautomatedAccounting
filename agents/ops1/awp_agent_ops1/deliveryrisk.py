"""OPS-1c DeliveryRisk — doc 05 §2.3. Timeline radar's doc-named sources
are "{milestone due dates, contract renewal dates, invoice-trigger dates,
compliance/report deadlines}" — only milestone due dates (and
`milestones.invoice_trigger`, already a real column) exist in this schema;
`projects` has no contract-renewal-date field and no compliance-deadline
source has been built in any sprint. Radar here is milestone-due-dates
only, `invoice_trigger=True` milestones weighted higher impact.
Cross-functional ticket creation on S1 escalation (doc: "creates a SUP-1
cross-functional ticket if another department is needed") is not
implemented — the department-needed heuristic doc 05 §2.3 implies isn't
specified precisely enough to build without guessing, and isn't required
by doc 12 §5's S9 acceptance tests (04§5.1-2,4 don't name it); the
Director-notification + dashboard-flag half (test 4) is implemented.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

TIMELINE_RADAR_DEFAULT_HORIZON_DAYS = 30
_INVOICE_TRIGGER_IMPACT = 1.0
_DEFAULT_IMPACT = 0.5
_DONE_STATUSES = frozenset({"done", "completed", "cancelled"})


@dataclass(frozen=True)
class TimelineItem:
    project_id: str
    milestone_id: str
    title: str
    due: date
    days_until_due: int
    impact_score: float
    rank_score: float


def timeline_radar(
    milestones_by_project: dict[str, list[dict[str, Any]]],
    today: date,
    horizon_days: int = TIMELINE_RADAR_DEFAULT_HORIZON_DAYS,
) -> list[TimelineItem]:
    items: list[TimelineItem] = []
    for project_id, milestones in milestones_by_project.items():
        for m in milestones:
            due = m.get("due")
            if due is None or m.get("status") in _DONE_STATUSES:
                continue
            days_until = (due - today).days
            if not (0 <= days_until <= horizon_days):
                continue
            impact = _INVOICE_TRIGGER_IMPACT if m.get("invoice_trigger") else _DEFAULT_IMPACT
            proximity = 1.0 - (days_until / horizon_days)
            items.append(
                TimelineItem(
                    project_id=project_id,
                    milestone_id=m["id"],
                    title=m["title"],
                    due=due,
                    days_until_due=days_until,
                    impact_score=impact,
                    rank_score=round(impact * proximity, 4),
                )
            )
    items.sort(key=lambda i: -i.rank_score)
    return items


def is_s1(issue: dict[str, Any]) -> bool:
    """doc 05 §2.3: "Severity S1 (client-facing slip on committed date):
    immediate escalation to Director + CEO dashboard."""
    return issue.get("severity") == "S1"
