"""F1/recall scoring for doc 04 §5.1's extraction acceptance test — pure,
deterministic comparison code, unit-tested independently of any real LLM
(see `tests/test_extraction_scoring.py`). Actually *running* extraction
against the 50-resume set needs a real M-SMALL call, so the ≥0.92/≥0.9
acceptance numbers themselves are asserted during live Docker verification
(`scripts/resume_extraction_eval.py`), same "unit tests never require a
live service" split as every other sprint's live-vs-unit boundary.
"""

from __future__ import annotations

from dataclasses import dataclass

from awp_shared.candidate_profile import CandidateProfile


def _prf1(predicted: set[str], truth: set[str]) -> tuple[float, float, float]:
    if not predicted and not truth:
        return 1.0, 1.0, 1.0
    if not predicted or not truth:
        return 0.0, 0.0, 0.0
    tp = len(predicted & truth)
    precision = tp / len(predicted)
    recall = tp / len(truth)
    f1 = 0.0 if (precision + recall) == 0 else 2 * precision * recall / (precision + recall)
    return precision, recall, f1


@dataclass(frozen=True)
class ExtractionScore:
    dates_f1: float
    orgs_f1: float
    skills_f1: float

    @property
    def overall_f1(self) -> float:
        # doc 04 §5.1 names "fields: dates, orgs, skills" as one combined
        # bar, no aggregation method specified — macro-average across the
        # three field categories (equal weight per category, not per item).
        return (self.dates_f1 + self.orgs_f1 + self.skills_f1) / 3


def score_extraction(predicted: CandidateProfile, truth: CandidateProfile) -> ExtractionScore:
    pred_dates = {(p.from_, p.to) for p in predicted.positions}
    truth_dates = {(p.from_, p.to) for p in truth.positions}
    pred_orgs = {p.org for p in predicted.positions}
    truth_orgs = {p.org for p in truth.positions}
    pred_skills = set(predicted.skills_normalized)
    truth_skills = set(truth.skills_normalized)

    _, _, dates_f1 = _prf1({str(d) for d in pred_dates}, {str(d) for d in truth_dates})
    _, _, orgs_f1 = _prf1(pred_orgs, truth_orgs)
    _, _, skills_f1 = _prf1(pred_skills, truth_skills)
    return ExtractionScore(dates_f1=dates_f1, orgs_f1=orgs_f1, skills_f1=skills_f1)


def overlap_recall(results: list[tuple[bool, CandidateProfile]]) -> float:
    """`results`: `(has_real_overlap, predicted_profile)` per resume.
    Recall over resumes that truly have an overlapping pair of positions —
    doc 04 §5.1's "date-overlap red-flag detection recall".
    """
    positives = [r for r in results if r[0]]
    if not positives:
        return 1.0
    caught = sum(
        1 for _, profile in positives if any(f.type == "overlap" for f in profile.red_flags)
    )
    return caught / len(positives)
