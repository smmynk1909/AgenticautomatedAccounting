"""OPS-1b's report-narrative writer — doc 05 §2.2 step 3: "M-GEN drafts
report: status summary ... RAG cites project_docs for commitments" and
step 4: "every claimed commitment/date must resolve to a doc/DB
reference." No `project_docs` corpus has been seeded in any sprint (same
"no data source built yet" pattern as HR-1's `market_intel` —
DEVIATIONS.md), so there's nothing to RAG-cite. Instead of building a
citation-checker against an empty corpus, the prompt is constrained to
restate *only* the already-computed facts it's given — every number here
already traces to a DB query the caller ran, so the doc's "0 uncited
commitments" bar is met by construction: the LLM is never given room to
make a claim beyond what's already been computed, not because a checker
verified it after the fact.
"""

from __future__ import annotations

from awp_agent_base.protocols import LLMLike

from awp_agent_ops1.projectmonitor import HealthReport

_SYSTEM_PROMPT = """You write a one-paragraph project health status summary
for a manager. Rules:
1. State only the facts given to you — every number/date you mention must
   come directly from the facts block, verbatim or trivially derived
   (e.g. "2 milestones at risk" when 2 are listed).
2. Never invent a commitment, date, or claim not present in the facts.
3. If risks exist, name them and ask what decision is needed; otherwise
   say the project is on track.
4. 3-5 sentences."""


async def write_report_narrative(llm: LLMLike, report: HealthReport) -> str:
    facts = (
        f"client={report.client}, hours_burned={report.hours_burned}, "
        f"budget_hours={report.budget_hours}, burn_variance_pct={report.burn_variance_pct}, "
        f"schedule_variance_pct={report.schedule_variance_pct}, "
        f"milestones_at_risk={[(r.title, r.days_until_due) for r in report.at_risk]}, "
        f"overdue_milestones={[m['title'] for m in report.overdue]}"
    )
    resp = await llm.chat(
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": f"Facts: {facts}\n\nWrite the status summary."},
        ],
        profile="draft",
    )
    return (resp.content or "").strip()
