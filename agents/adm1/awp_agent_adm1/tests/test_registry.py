from __future__ import annotations

from awp_agent_adm1 import registry


def test_build_employee_record_merges_patch() -> None:
    record = registry.build_employee_record("EMP-1", {"grade": "E3", "status": "active"})
    assert record == {"emp_id": "EMP-1", "grade": "E3", "status": "active"}


def test_duplicate_candidate_dashboard_item_shape() -> None:
    candidate = {"name": "Ravi Kumar"}
    matches = [{"candidate_id": "CAND-1", "reason": "phone", "score": 1.0}]
    item = registry.duplicate_candidate_dashboard_item(candidate, matches, "task-123")

    assert item["audience_roles"] == ["admin_head"]
    assert item["panel"] == "registry"
    assert item["severity"] == "warning"
    assert "Ravi Kumar" in item["title"]
    assert "CAND-1" in item["body"]
    assert "phone" in item["body"]
    assert item["source_task_id"] == "task-123"
    assert len(item["body"]) <= 400
