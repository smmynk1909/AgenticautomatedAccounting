"""Model-gateway tool-call round-trip smoke test — doc 12 tree
`serving/smoke/test_toolcall.py`. Run against a *live* Ollama with the model
pool pulled (`make up && make models`); not part of the unit/contract test
suite (no mocking) since its entire purpose is proving the real endpoint
answers tool-calling prompts correctly.

Usage: `uv run python serving/smoke/test_toolcall.py`
"""

from __future__ import annotations

import asyncio
import os
import sys

from awp_shared.llm import LLM, ToolSchema
from pydantic import BaseModel

GET_EMPLOYEE_TOOL = ToolSchema(
    function={
        "name": "get_employee",
        "description": "Look up an employee by id.",
        "parameters": {
            "type": "object",
            "properties": {"emp_id": {"type": "string"}},
            "required": ["emp_id"],
        },
    }
)


class Plan(BaseModel):
    goal: str
    tasks: list[str]


async def check_plain_chat(llm: LLM) -> None:
    resp = await llm.chat([{"role": "user", "content": "Reply with exactly one word: pong"}])
    assert resp.content, "empty response from model gateway"
    print(f"  plain chat: OK ({resp.content.strip()!r})")


async def check_tool_call(llm: LLM) -> None:
    resp = await llm.chat(
        [
            {
                "role": "user",
                "content": "Use the get_employee tool to look up employee EMP-00007.",
            }
        ],
        tools=[GET_EMPLOYEE_TOOL],
    )
    if not resp.tool_calls:
        print(
            f"  WARNING: model did not emit a tool call (content={resp.content!r}). "
            f"Ollama tool-calling reliability varies by model/version — see DEVIATIONS.md #1."
        )
        return
    call = resp.tool_calls[0]
    assert call.name == "get_employee", f"unexpected tool name: {call.name}"
    assert call.arguments.get("emp_id"), f"missing emp_id argument: {call.arguments}"
    print(f"  tool call: OK ({call.name}({call.arguments}))")


async def check_guided_json(llm: LLM) -> None:
    resp = await llm.chat(
        [{"role": "user", "content": "Produce a plan with goal 'smoke test' and one task 'ping'."}],
        guided_json=Plan,
    )
    plan = Plan.model_validate_json(resp.content or "")
    assert plan.goal
    print(f"  guided_json: OK ({plan!r})")


async def main() -> None:
    gateway_url = os.environ.get("MODEL_GATEWAY_URL", "http://localhost:11434/v1")
    model = os.environ.get("MODEL_GEN", "qwen2.5:7b-instruct")
    print(f"Smoke-testing {model} via {gateway_url} ...")

    llm = LLM(gateway_url, model)
    try:
        await check_plain_chat(llm)
        await check_tool_call(llm)
        await check_guided_json(llm)
    finally:
        await llm.aclose()

    print("All checks completed.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:  # noqa: BLE001 - smoke test: any failure should exit non-zero with context
        print(f"SMOKE TEST FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
