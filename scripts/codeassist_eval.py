"""CodeAssist pass@1 — doc 04 §5.3 acceptance test (doc numbering note: the
CodeAssist acceptance tests live in doc 05 §5.3/§5.5, referenced here by
their doc 12 §5 S10 DoD citation "05§5.3,5"): "HumanEval-style internal
suite pass@1 >= baseline of raw M-CODE (RAG must not degrade)."

This is a LIVE verification script, not part of `pytest -q` — it calls a
real Ollama M-CODE completion per problem per condition
(`codeassist.run_mode`'s "generate" mode, unit-tested with a FakeLLM in
`agents/ops1/awp_agent_ops1/tests/test_codeassist.py`). Not a real
HumanEval clone: HumanEval is 164 problems with a real execution
sandbox/dataset license; this is 5 small synthetic function-completion
problems, graded by direct `exec()` in this same process (fine for
generated code from a fixed, non-adversarial small problem set — this is
a dev-mode eval harness, not a security boundary). Documented as a scoped-
down substitute in DEVIATIONS.md, same "no full dataset exists" pattern as
Sprint 7's F1 eval and Sprint 9's milestone-at-risk precision.

Usage (from repo root, `ollama` running with M-CODE pulled):
    uv run python scripts/codeassist_eval.py
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from dataclasses import dataclass
from typing import Any

from awp_agent_ops1.codeassist import run_mode
from awp_shared.llm import LLM

PASS_AT_1_THRESHOLD = 0.6  # small model, small sample — see DEVIATIONS.md


@dataclass(frozen=True)
class Problem:
    name: str
    instruction: str
    rag_context: str
    cases: list[tuple[tuple[Any, ...], Any]]


PROBLEMS = [
    Problem(
        name="add_two",
        instruction=(
            "Write a Python function `add_two(a: int, b: int) -> int` that returns "
            "a + b. Return only the function definition, no explanation."
        ),
        rag_context="Style guide: functions in this repo use plain +/-/* arithmetic, no numpy.",
        cases=[((2, 3), 5), ((-1, 1), 0)],
    ),
    Problem(
        name="is_palindrome",
        instruction=(
            "Write a Python function `is_palindrome(s: str) -> bool` that returns True "
            "if s reads the same forwards and backwards. Return only the function "
            "definition, no explanation."
        ),
        rag_context=(
            "Style guide: string helpers in this repo are case-sensitive and do not "
            "strip whitespace unless asked."
        ),
        cases=[(("racecar",), True), (("hello",), False)],
    ),
    Problem(
        name="factorial",
        instruction=(
            "Write a Python function `factorial(n: int) -> int` that returns n! "
            "(factorial(0) == 1). Return only the function definition, no explanation."
        ),
        rag_context="Style guide: use iteration, not recursion, for numeric helpers in this repo.",
        cases=[((0,), 1), ((5,), 120)],
    ),
    Problem(
        name="reverse_words",
        instruction=(
            "Write a Python function `reverse_words(s: str) -> str` that reverses the "
            "order of words in s (words separated by single spaces). Return only the "
            "function definition, no explanation."
        ),
        rag_context="Style guide: split on whitespace with str.split(), join with a single space.",
        cases=[(("hello world",), "world hello"), (("a b c",), "c b a")],
    ),
    Problem(
        name="max_of_three",
        instruction=(
            "Write a Python function `max_of_three(a: int, b: int, c: int) -> int` "
            "that returns the largest of the three. Return only the function "
            "definition, no explanation."
        ),
        rag_context="Style guide: use the builtin max() for numeric comparisons in this repo.",
        cases=[((1, 2, 3), 3), ((5, 2, 1), 5)],
    ),
]

_CODE_FENCE_RE = re.compile(r"```(?:python)?\n(.*?)```", re.DOTALL)


def _extract_code(text: str) -> str:
    m = _CODE_FENCE_RE.search(text)
    return m.group(1) if m else text


def _grade(name: str, code: str, cases: list[tuple[tuple[Any, ...], Any]]) -> bool:
    namespace: dict[str, Any] = {}
    try:
        exec(_extract_code(code), namespace)  # fixed, small, non-adversarial problem set
        fn = namespace.get(name)
        if fn is None:
            return False
        return all(fn(*args) == expected for args, expected in cases)
    except Exception:
        return False


async def _run_condition(llm: LLM, use_rag: bool) -> tuple[int, list[str]]:
    passed = 0
    failures = []
    for problem in PROBLEMS:
        context = problem.rag_context if use_rag else ""
        result = await run_mode(llm, "generate", context, problem.instruction)
        assert isinstance(result, str)
        if _grade(problem.name, result, problem.cases):
            passed += 1
        else:
            failures.append(problem.name)
    return passed, failures


async def main() -> int:
    llm = LLM(
        os.environ.get("MODEL_GATEWAY_URL", "http://localhost:11434/v1"),
        os.environ.get("MODEL_CODE", "qwen2.5-coder:7b-instruct"),
        # 600s, not 180s: live-verified (Sprint 10) that llama.cpp's Ollama
        # backend runs a single inference slot — concurrent callers (this
        # eval's own 10 sequential calls plus anything else hitting Ollama,
        # e.g. mcp-search's embedder) queue serially rather than in
        # parallel, so wall-clock wait for a given call includes however
        # long everything ahead of it in the queue takes, not just this
        # call's own generation time.
        timeout_s=600.0,
    )

    base_passed, base_failures = await _run_condition(llm, use_rag=False)
    rag_passed, rag_failures = await _run_condition(llm, use_rag=True)

    n = len(PROBLEMS)
    base_rate = base_passed / n
    rag_rate = rag_passed / n
    print(f"baseline pass@1: {base_passed}/{n} ({base_rate:.2f}) — failed: {base_failures}")
    print(f"RAG pass@1:      {rag_passed}/{n} ({rag_rate:.2f}) — failed: {rag_failures}")

    rag_not_degraded = rag_rate >= base_rate
    meets_threshold = base_rate >= PASS_AT_1_THRESHOLD
    print(f"RAG does not degrade baseline: {rag_not_degraded}")
    print(f"baseline meets pass@1 >= {PASS_AT_1_THRESHOLD}: {meets_threshold}")

    passed = rag_not_degraded and meets_threshold
    print("PASS" if passed else "FAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
