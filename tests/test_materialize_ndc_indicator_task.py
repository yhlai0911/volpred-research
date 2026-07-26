from __future__ import annotations

from scripts import materialize_ndc_indicator_task


def test_fresh_ndc_state_is_noop(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        materialize_ndc_indicator_task,
        "build_ndc_indicator_maintenance",
        lambda **_kwargs: {
            "skip": True,
            "reason": "fresh",
            "expected_period": "2026M05",
        },
    )

    result = materialize_ndc_indicator_task.run(
        next_tasks_path=tmp_path / "next_tasks.json"
    )

    assert result == {
        "ok": True,
        "action": "skip",
        "reason": "fresh",
        "expected_period": "2026M05",
        "task_created": False,
    }


def test_stale_ndc_state_materializes_deterministic_task(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        materialize_ndc_indicator_task,
        "build_ndc_indicator_maintenance",
        lambda **_kwargs: {
            "skip": False,
            "reason": "stale_series",
            "expected_period": "2026M05",
            "stale_series": ["leading_indicator"],
            "followup_commands": ["check", "collect"],
        },
    )
    captured = {}

    def append(record, **_kwargs):
        captured.update(record)
        return record, True

    monkeypatch.setattr(materialize_ndc_indicator_task, "append_task_record", append)

    result = materialize_ndc_indicator_task.run(
        next_tasks_path=tmp_path / "next_tasks.json"
    )

    assert result["task_created"] is True
    assert captured["id"] == "ndc_indicator_refresh_2026m05"
    assert captured["task_type"] == "platform_ops"
    assert captured["status"] == "pending"
    assert captured["dispatch_lane"] == "agent"
