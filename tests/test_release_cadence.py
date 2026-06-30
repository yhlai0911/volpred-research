from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from volpred.ops import content_quality as cq
from volpred.ops.alerts import (
    _parse_publishing_freshness_state,
    _parse_release_pool_state,
)
from volpred.ops.release_cadence import (
    DEFAULT_RELEASE_INTERVAL_MINUTES,
    get_release_interval_hours,
    get_release_interval_minutes,
)

TPE = timezone(timedelta(hours=8))


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_settings(storage: Path, *, interval_minutes: int) -> None:
    _write_json(
        storage / ".release_settings.json",
        {
            "mode": "auto",
            "interval_minutes": interval_minutes,
            "last_released_at": "2026-06-30T03:00:00+00:00",
            "updated_at": "2026-06-30T03:00:00+00:00",
        },
    )


def _write_feed(storage: Path, newest: datetime) -> None:
    _write_json(
        storage / "reports" / "feed.json",
        [
            {
                "id": "mile_newest",
                "status": "published",
                "audience": "general",
                "category": "general",
                "published_at": newest.astimezone(timezone.utc).isoformat(),
            },
            {
                "id": "mile_older",
                "status": "published",
                "audience": "general",
                "category": "general",
                "published_at": (newest - timedelta(hours=2)).astimezone(timezone.utc).isoformat(),
            },
        ],
    )


def test_release_interval_helper_reads_settings_and_defaults(tmp_path: Path) -> None:
    storage = tmp_path / "storage"
    assert get_release_interval_minutes(str(storage)) == DEFAULT_RELEASE_INTERVAL_MINUTES

    _write_settings(storage, interval_minutes=180)
    assert get_release_interval_minutes(str(storage)) == 180
    assert get_release_interval_hours(str(storage)) == 3.0


def test_release_cadence_thresholds_move_with_interval(tmp_path: Path) -> None:
    storage = tmp_path / "storage"
    _write_settings(storage, interval_minutes=240)
    now = datetime(2026, 6, 30, 14, 0, tzinfo=TPE)
    _write_feed(storage, newest=now - timedelta(hours=1))
    _write_text(
        storage / "logs" / "cron" / "release_pool.log",
        "=== [release_pool] fire at 2026-06-30T05:30:00+00:00 ===\n",
    )

    rhythm = cq.check_publish_rhythm(str(storage), now=now.astimezone(timezone.utc))
    freshness = _parse_publishing_freshness_state(str(storage), now.astimezone(timezone.utc))
    release_pool = _parse_release_pool_state(str(storage), now.astimezone(timezone.utc))

    # One configured interval (4h) feeds all cadence-derived thresholds.
    assert rhythm["drought_gap_threshold_hours"] == 6.0  # interval + 2h grace
    assert freshness["details"]["threshold_hours"] == 6.0  # interval + 2h grace, 5h floor
    assert release_pool["details"]["warn_threshold_hours"] == 5.0  # interval + 1h grace
    assert release_pool["details"]["interval_minutes"] == 240
