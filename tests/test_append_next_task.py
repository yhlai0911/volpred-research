"""Hermetic tests for the single-gateway append path (append_next_task)."""

from __future__ import annotations

import json

import pytest

from volpred.ops.next_tasks import _legacy_priority_to_p, append_next_task


def test_append_creates_pending_record_with_mapped_fields(tmp_path):
    queue = tmp_path / "next_tasks.json"
    rec = append_next_task(
        title="t",
        description="d",
        source="user",
        task_family="research",
        legacy_priority=30,
        path=queue,
    )
    assert rec["status"] == "pending"
    assert rec["task_type"] == "experiment"
    assert rec["priority"] == 2  # 30 → P2
    assert rec["id"].startswith("assign_")

    on_disk = json.loads(queue.read_text(encoding="utf-8"))
    assert [t["id"] for t in on_disk] == [rec["id"]]


def test_append_preserves_existing_rows(tmp_path):
    queue = tmp_path / "next_tasks.json"
    queue.write_text(json.dumps([{"id": "existing", "status": "pending", "priority": 3}]), encoding="utf-8")
    append_next_task(title="t", description="d", path=queue)
    on_disk = json.loads(queue.read_text(encoding="utf-8"))
    assert {t["id"] for t in on_disk} >= {"existing"}
    assert len(on_disk) == 2


def test_append_rejects_non_list_root(tmp_path):
    queue = tmp_path / "next_tasks.json"
    queue.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError):
        append_next_task(title="t", description="d", path=queue)


@pytest.mark.parametrize(
    "legacy,expected",
    [(1, 1), (10, 1), (30, 2), (50, 2), (80, 3), (100, 3), (101, 4), (500, 4)],
)
def test_legacy_priority_mapping(legacy, expected):
    assert _legacy_priority_to_p(legacy) == expected


def test_unknown_family_falls_back_to_platform_ops(tmp_path):
    rec = append_next_task(
        title="t",
        description="d",
        task_family="something_new",
        path=tmp_path / "q.json",
    )
    assert rec["task_type"] == "platform_ops"
