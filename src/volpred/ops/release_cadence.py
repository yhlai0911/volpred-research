"""Shared release-cadence policy for publisher, patrol, and alerts.

The release interval lives in ``storage/.release_settings.json``. Checks that
derive gap thresholds from that cadence should read it through this module so a
cadence change does not require hand-editing multiple watchdogs.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Mapping

from .common import load_json, project_path
from .diagnostics import warn

DEFAULT_RELEASE_INTERVAL_MINUTES = 360
MIN_RELEASE_INTERVAL_MINUTES = 5

RHYTHM_BURST_GAP_MIN = 30
NON_RHYTHM_PHASES = frozenset(
    {
        "digest",
        "daily_update",
        "daily_recommendation",
        "trending_repost",
        "event",
        "event_article",
    }
)
NON_RHYTHM_CATEGORIES = frozenset({"event_article", "trending_repost"})


def get_release_interval_minutes(
    storage_dir: str = "storage",
    *,
    settings: Mapping[str, Any] | None = None,
    default_minutes: int = DEFAULT_RELEASE_INTERVAL_MINUTES,
    warn_key: str = "release_cadence",
) -> int:
    """Return configured release interval in minutes, clamped to the safe floor."""
    raw_settings: Mapping[str, Any] | None = settings
    if raw_settings is None:
        path = project_path(storage_dir) / ".release_settings.json"
        try:
            loaded = load_json(path, default={})
        except (OSError, ValueError, TypeError) as exc:
            warn(warn_key, "release interval read failed; using default", err=str(exc))
            loaded = {}
        raw_settings = loaded if isinstance(loaded, Mapping) else {}

    try:
        minutes = int(raw_settings.get("interval_minutes") or default_minutes)
    except (TypeError, ValueError) as exc:
        warn(warn_key, "bad interval_minutes; using default", err=str(exc))
        minutes = int(default_minutes)
    return max(MIN_RELEASE_INTERVAL_MINUTES, minutes)


def get_release_interval_hours(
    storage_dir: str = "storage",
    *,
    settings: Mapping[str, Any] | None = None,
    default_minutes: int = DEFAULT_RELEASE_INTERVAL_MINUTES,
    warn_key: str = "release_cadence",
) -> float:
    return get_release_interval_minutes(
        storage_dir,
        settings=settings,
        default_minutes=default_minutes,
        warn_key=warn_key,
    ) / 60.0


def release_interval_timedelta(
    storage_dir: str = "storage",
    *,
    settings: Mapping[str, Any] | None = None,
    default_minutes: int = DEFAULT_RELEASE_INTERVAL_MINUTES,
    warn_key: str = "release_cadence",
) -> timedelta:
    return timedelta(
        minutes=get_release_interval_minutes(
            storage_dir,
            settings=settings,
            default_minutes=default_minutes,
            warn_key=warn_key,
        )
    )


def release_cadence_threshold_hours(
    storage_dir: str = "storage",
    *,
    grace_hours: float,
    floor_hours: float = 0.0,
    precision: int = 1,
    settings: Mapping[str, Any] | None = None,
    default_minutes: int = DEFAULT_RELEASE_INTERVAL_MINUTES,
    warn_key: str = "release_cadence",
) -> float:
    """Return ``max(floor, configured interval + grace)`` in hours."""
    threshold = max(
        floor_hours,
        get_release_interval_hours(
            storage_dir,
            settings=settings,
            default_minutes=default_minutes,
            warn_key=warn_key,
        )
        + grace_hours,
    )
    return round(threshold, precision)


def is_rhythm_controlled(item: dict[str, Any]) -> bool:
    """True for discretionary reader-facing articles governed by release_pool cadence."""
    if (item.get("audience") or "").lower() == "daily":
        return False
    phase = (item.get("phase") or "").lower()
    if phase in NON_RHYTHM_PHASES:
        return False
    cat = (item.get("category") or "").lower()
    if cat in NON_RHYTHM_CATEGORIES:
        return False
    return True


def sibling_group(item: dict[str, Any]) -> str | None:
    det = item.get("details")
    if isinstance(det, dict):
        grp = det.get("paired_sibling_group")
        if isinstance(grp, str) and grp:
            return grp
    return None
