from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from volpred.ops.alerts import _parse_dispatch_duplicate_slot_state


CRON = "7 * * * *"
NOW = datetime(2026, 7, 11, 10, 0, tzinfo=timezone.utc)


def _write_state(storage: Path, completions: list[dict]) -> None:
    path = storage / "ops" / "dispatch_state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"completions": completions}), encoding="utf-8")


def _completion(
    fire_at: str,
    scheduled_for: str,
    *,
    fire_reason: str = "cron",
    attempts: int = 1,
) -> dict:
    return {
        "fire_at": fire_at,
        "scheduled_for": scheduled_for,
        "fire_reason": fire_reason,
        "attempts": attempts,
        "outcome": "success",
    }


def test_duplicate_slot_warns_from_structured_completions(tmp_path: Path) -> None:
    storage = tmp_path / "storage"
    _write_state(
        storage,
        [
            _completion("2026-07-11T00:07:12+00:00", "2026-07-11T08:07:00"),
            _completion("2026-07-11T00:48:00+00:00", "2026-07-11T08:07:00"),
        ],
    )

    result = _parse_dispatch_duplicate_slot_state(
        str(storage), NOW, cron_expr=CRON, supervisor_log=tmp_path / "missing.log"
    )

    assert result["breached"] is True
    assert result["level"] == "warn"
    assert result["details"]["duplicate_slot_count"] == 1
    assert result["details"]["extra_fire_count"] == 1
    assert "非排定時間多跑了 1 班，每班約 95K token" in result["body"]


def test_three_duplicate_slots_escalate_critical(tmp_path: Path) -> None:
    storage = tmp_path / "storage"
    completions: list[dict] = []
    for local_hour in (14, 15, 16):
        utc_hour = local_hour - 8
        slot = f"2026-07-11T{local_hour:02d}:07:00"
        completions.extend(
            [
                _completion(f"2026-07-11T{utc_hour:02d}:07:10+00:00", slot),
                _completion(f"2026-07-11T{utc_hour:02d}:40:00+00:00", slot),
            ]
        )
    _write_state(storage, completions)

    result = _parse_dispatch_duplicate_slot_state(
        str(storage), NOW, cron_expr=CRON, supervisor_log=tmp_path / "missing.log"
    )

    assert result["breached"] is True
    assert result["level"] == "critical"
    assert result["details"]["duplicate_slot_count"] == 3
    assert result["details"]["extra_fire_count"] == 3


def test_requested_fire_and_retry_do_not_create_false_duplicate(tmp_path: Path) -> None:
    storage = tmp_path / "storage"
    _write_state(
        storage,
        [
            _completion("2026-07-11T00:07:12+00:00", "2026-07-11T08:07:00"),
            _completion(
                "2026-07-11T00:30:00+00:00",
                "2026-07-11T08:07:00",
                fire_reason="requested:email_reply",
            ),
            _completion(
                "2026-07-11T00:35:00+00:00",
                "2026-07-11T08:07:00",
                attempts=2,
            ),
            # A delayed catch-up is legal when it is the only service of its slot.
            _completion("2026-07-11T01:27:00+00:00", "2026-07-11T09:07:00"),
        ],
    )

    result = _parse_dispatch_duplicate_slot_state(
        str(storage), NOW, cron_expr=CRON, supervisor_log=tmp_path / "missing.log"
    )

    assert result["breached"] is False
    assert result["details"]["duplicate_slot_count"] == 0


def test_log_supplements_reset_state_and_marks_requested_fire(tmp_path: Path) -> None:
    storage = tmp_path / "storage"
    # Simulate the production incident: the ring buffer was reset and retained
    # only the off-slot completion, while the supervisor log still has both fires.
    _write_state(
        storage,
        [_completion("2026-07-11T00:58:25+00:00", "2026-07-11T08:07:00")],
    )
    log_path = tmp_path / "dispatch_supervisor.log"
    log_path.write_text(
        "\n".join(
            [
                "2026-07-11 08:07:51,093 INFO [scripts.dispatch_supervisor.scheduler] firing worker prev_scheduled=2026-07-11T08:07:00 log=/tmp/worker.log",
                "2026-07-11 08:58:25,245 INFO firing worker prev_scheduled=2026-07-11T08:07:00 log=/tmp/worker.log",
                "2026-07-11 09:30:55,863 INFO [scripts.dispatch_supervisor.scheduler] fire request consumed (reason=email_reply:x) — firing off-cadence",
                "2026-07-11 09:30:59,152 INFO firing worker prev_scheduled=2026-07-11T09:07:00 log=/tmp/worker.log",
            ]
        ),
        encoding="utf-8",
    )

    result = _parse_dispatch_duplicate_slot_state(
        str(storage), NOW, cron_expr=CRON, supervisor_log=log_path
    )

    assert result["breached"] is True
    assert result["details"]["duplicate_slot_count"] == 1
    assert result["details"]["extra_fire_count"] == 1
    assert result["details"]["structured_events"] == 1
    assert result["details"]["log_events"] == 3
