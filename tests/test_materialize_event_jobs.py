from __future__ import annotations

from scripts import materialize_event_jobs


def test_pending_event_windows_are_a_successful_noop(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        materialize_event_jobs,
        "expand_due_event_jobs",
        lambda **_kwargs: {
            "created": [],
            "skipped": [{"id": "future", "reason": "pending"}],
            "expired_tasks": {},
            "removed_ledgers": [],
        },
    )

    result = materialize_event_jobs.run(storage_dir=tmp_path)

    assert result["ok"] is True
    assert result["created_count"] == 0
    assert result["structural_failures"] == []


def test_invalid_event_spec_fails_the_schedule_receipt(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        materialize_event_jobs,
        "expand_due_event_jobs",
        lambda **_kwargs: {
            "created": [],
            "skipped": [{"id": "bad", "reason": "invalid_event_window"}],
            "expired_tasks": {},
            "removed_ledgers": [],
        },
    )

    result = materialize_event_jobs.run(storage_dir=tmp_path)

    assert result["ok"] is False
    assert result["structural_failures"] == [
        {"id": "bad", "reason": "invalid_event_window"}
    ]
