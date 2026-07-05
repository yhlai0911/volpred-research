from __future__ import annotations

import pytest

from volpred.ops.next_tasks import (
    InvalidTaskPriority,
    normalize_priority,
    normalize_task_priorities,
    priority_sort_key,
)


def test_normalize_priority_accepts_legacy_label_forms() -> None:
    assert normalize_priority(1) == 1
    assert normalize_priority("2") == 2
    assert normalize_priority("P3") == 3
    assert normalize_priority("p4") == 4
    assert normalize_priority("PP1") == 1


def test_normalize_task_priorities_mutates_legacy_strings() -> None:
    tasks = [
        {"id": "a", "priority": "P3"},
        {"id": "b", "priority": "PP1"},
        {"id": "c", "priority": "4"},
        {"id": "d", "priority": 2},
    ]

    changed = normalize_task_priorities(tasks)

    assert changed == 3
    assert [task["priority"] for task in tasks] == [3, 1, 4, 2]


def test_normalize_priority_rejects_invalid_write_values() -> None:
    with pytest.raises(InvalidTaskPriority):
        normalize_priority("urgent")

    with pytest.raises(InvalidTaskPriority):
        normalize_priority(0)


def test_priority_sort_key_sends_invalid_values_to_tail() -> None:
    assert priority_sort_key("P2") == 2
    assert priority_sort_key("urgent", default=999) == 999
