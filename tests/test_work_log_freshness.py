from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from volpred.ops.alerts import _parse_work_log_freshness_state, build_alert_condition_report


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_work_log_freshness_ok_when_latest_entry_is_recent(tmp_path: Path):
    storage = tmp_path / "storage"
    now = datetime(2026, 6, 28, 12, 0, tzinfo=timezone.utc)
    _write_json(
        storage / "work_log.json",
        [{"timestamp": (now - timedelta(hours=2)).isoformat(), "task_type": "platform_ops"}],
    )

    condition = _parse_work_log_freshness_state(str(storage), now)

    assert condition["breached"] is False
    assert condition["level"] == "info"
    assert condition["details"]["age_hours"] == 2.0


def test_work_log_freshness_warns_when_latest_entry_is_stale(tmp_path: Path):
    storage = tmp_path / "storage"
    now = datetime(2026, 6, 28, 12, 0, tzinfo=timezone.utc)
    _write_json(
        storage / "work_log.json",
        [{"timestamp": (now - timedelta(hours=30)).isoformat(), "task_type": "platform_ops"}],
    )

    condition = _parse_work_log_freshness_state(str(storage), now)

    assert condition["breached"] is True
    assert condition["level"] == "warn"
    assert "## 觸發條件" in condition["body"]
    assert condition["details"]["age_hours"] == 30.0


def test_work_log_freshness_warns_on_bad_json(tmp_path: Path):
    storage = tmp_path / "storage"
    now = datetime(2026, 6, 28, 12, 0, tzinfo=timezone.utc)
    path = storage / "work_log.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{bad-json", encoding="utf-8")

    condition = _parse_work_log_freshness_state(str(storage), now)

    assert condition["breached"] is True
    assert condition["details"]["read_error"].startswith("JSONDecodeError")


def test_alert_report_includes_work_log_freshness_condition(tmp_path: Path):
    storage = tmp_path / "storage"
    now = datetime(2026, 6, 28, 12, 0, tzinfo=timezone.utc)
    _write_json(
        storage / "work_log.json",
        [{"timestamp": (now - timedelta(hours=30)).isoformat(), "task_type": "platform_ops"}],
    )

    report = build_alert_condition_report(storage_dir=str(storage), now=now)
    by_id = {condition["id"]: condition for condition in report["conditions"]}

    assert by_id["work_log_freshness"]["breached"] is True
