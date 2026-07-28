"""Resume extraction F1 / overlap-recall — doc 04 §5.1 acceptance test:
"Resume extraction F1 ≥ 0.92 on a 50-resume labeled set (fields: dates,
orgs, skills); date-overlap red-flag detection recall ≥ 0.9."

This is a LIVE verification script, not part of `pytest -q` — it needs a
real Ollama serving M-SMALL through a running `mcp-hrsourcing` container
(same "unit tests never require a live service" split as every other
sprint's live-vs-unit boundary; `extraction_scoring.py`'s own scoring math
is unit-tested with scripted inputs in `agents/hr1/awp_agent_hr1/tests/`).
Renders each synthetic resume's text to a real one-page PDF (xhtml2pdf, the
same library mcp-docs/mcp-hrsourcing use) so `extract_resume` exercises the
real pdfplumber parse path, not just `normalize_profile` on already-clean
text.

Usage (from repo root, stack up via `make up`):
    uv run python scripts/resume_extraction_eval.py --n 50 --hrsourcing-url http://localhost:8007
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import io
import sys

from awp_agent_hr1.eval_fixtures import generate_labeled_resumes
from awp_agent_hr1.extraction_scoring import overlap_recall, score_extraction
from awp_shared.auth import mint_service_jwt
from awp_shared.candidate_profile import CandidateProfile
from awp_shared.mcpc import MCP
from xhtml2pdf import pisa

F1_THRESHOLD = 0.92
RECALL_THRESHOLD = 0.9


def _resume_pdf_b64(text: str) -> str:
    paragraphs = "".join(f"<p>{line}</p>" for line in text.splitlines())
    html = f"<html><body>{paragraphs}</body></html>"
    buf = io.BytesIO()
    pisa.CreatePDF(html, dest=buf)
    return base64.b64encode(buf.getvalue()).decode()


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=50)
    parser.add_argument("--hrsourcing-url", default="http://localhost:8007")
    args = parser.parse_args(argv)

    mcp = MCP(
        {"hrsourcing": args.hrsourcing_url},
        principal_jwt_provider=lambda: mint_service_jwt("eval-script", ["hrsourcing.read"]),
        # Must exceed mcp-hrsourcing's own internal LLM timeout_s=600 (see
        # main.py) with headroom for a schema-repair round (up to two
        # sequential completions server-side) — this host's measured Ollama
        # throughput (~1.45 tok/s) makes a single extraction genuinely slow,
        # not stuck.
        timeout_s=1500.0,
    )

    resumes = generate_labeled_resumes(args.n)
    scores = []
    overlap_results = []
    for resume in resumes:
        pdf_b64 = _resume_pdf_b64(resume.text)
        extracted = await mcp.call("hrsourcing", "extract_resume", {"file_bytes_b64": pdf_b64})
        normalized = await mcp.call(
            "hrsourcing", "normalize_profile", {"raw": extracted["text"]}
        )
        predicted = CandidateProfile.model_validate(normalized["profile"])
        scores.append(score_extraction(predicted, resume.ground_truth))
        overlap_results.append((resume.has_real_overlap, predicted))
        print(f"{resume.id}: f1={scores[-1].overall_f1:.3f}", file=sys.stderr)

    mean_f1 = sum(s.overall_f1 for s in scores) / len(scores)
    recall = overlap_recall(overlap_results)

    print(
        f"\nmean extraction F1 over {len(resumes)} resumes: "
        f"{mean_f1:.4f} (threshold {F1_THRESHOLD})"
    )
    print(f"overlap red-flag recall: {recall:.4f} (threshold {RECALL_THRESHOLD})")

    passed = mean_f1 >= F1_THRESHOLD and recall >= RECALL_THRESHOLD
    print("PASS" if passed else "FAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
