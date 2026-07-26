from __future__ import annotations

from uuid import uuid4

from awp_shared.schemas import AgentId, TaskEnvelope

from awp_agent_base.checkpoint import CheckpointStore
from awp_agent_base.state import new_state


async def test_load_missing_returns_none(checkpoints: CheckpointStore) -> None:
    assert await checkpoints.load(uuid4(), "orch0") is None


async def test_save_then_load_roundtrips(checkpoints: CheckpointStore) -> None:
    env = TaskEnvelope(from_agent=AgentId.ORCH0, to_agent=AgentId.SUP1, intent="create_ticket")
    state = new_state(env)
    state["scratch"]["foo"] = "bar"

    await checkpoints.save(env.task_id, "sup1", state)
    loaded = await checkpoints.load(env.task_id, "sup1")

    assert loaded is not None
    assert loaded["scratch"]["foo"] == "bar"
    assert loaded["task"].task_id == env.task_id


async def test_save_upserts_same_task_id(checkpoints: CheckpointStore) -> None:
    env = TaskEnvelope(from_agent=AgentId.ORCH0, to_agent=AgentId.SUP1, intent="create_ticket")
    state = new_state(env)

    await checkpoints.save(env.task_id, "sup1", state)
    state["scratch"]["step"] = 1
    await checkpoints.save(env.task_id, "sup1", state)

    loaded = await checkpoints.load(env.task_id, "sup1")
    assert loaded is not None
    assert loaded["scratch"]["step"] == 1


async def test_load_with_mismatched_graph_name_returns_none(checkpoints: CheckpointStore) -> None:
    env = TaskEnvelope(from_agent=AgentId.ORCH0, to_agent=AgentId.SUP1, intent="create_ticket")
    state = new_state(env)

    await checkpoints.save(env.task_id, "sup1", state)

    assert await checkpoints.load(env.task_id, "orch0") is None


async def test_clear_removes_checkpoint(checkpoints: CheckpointStore) -> None:
    env = TaskEnvelope(from_agent=AgentId.ORCH0, to_agent=AgentId.SUP1, intent="create_ticket")
    state = new_state(env)
    await checkpoints.save(env.task_id, "sup1", state)

    await checkpoints.clear(env.task_id)

    assert await checkpoints.load(env.task_id, "sup1") is None
