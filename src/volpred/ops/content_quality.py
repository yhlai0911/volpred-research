"""Content-quality patrol — checks the system never had until 2026-06-24.

Background (2026-06-24 boss-triggered meta-fix): all four content problems
that day (release deadlock / digest duplicate / 標題前綴重複 / 前端 React #418)
were spotted by the user, not by the system. ops_dashboard and check_alerts
cover infrastructure (cron alive, pool empty, release gap) — they do **not**
inspect the actual content for correctness. This module fills that gap.

Initial MVP scope (3 of 7 designed checks; the rest land in follow-up fires):

1. `check_publish_rhythm` — gap histogram of recent published items inside the
   active window (TPE 09:00–23:00); flags <30 min bursts and >3 h droughts
   *before* the 5 h dead-man switch trips.
2. `check_daily_digest_uniqueness` — at most one published `每日精選導讀` per
   local day; >1 = breach. This is the patrol layer that would have caught
   `mile_f3e389cf` on the morning of 2026-06-24 instead of the user.
3. `check_title_format` — among the most recent published items, flag titles
   whose visible prefix duplicates the frontend section header (e.g. a
   `每日精選導讀｜...` title sitting inside a `每日精選導讀` block), plus
   format anomalies (overly long titles, stray control chars).

Aggregated by `content_quality_snapshot()` (mirrors `health.py::health_snapshot`)
which is consumed by the alert chain (`alerts._parse_content_quality_state`).

Design constraints:
- Read-only by default; never mutates feed.json (per project rule
  「永遠修流程不修資料」).
- Active window is asymmetric per `_TAIPEI_TZ` — gap rules suspend overnight to
  avoid 02:00 alerts (digest job legitimately fires then).
- No silent fallbacks: every `except` hits `warn(...)` first
  (`.claude/rules/no-silent-fallback.md`).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .common import load_json, project_path
from .diagnostics import warn

_TAIPEI_TZ = ZoneInfo("Asia/Taipei")

# Active publishing window (Taipei time) — outside this we skip rhythm checks.
ACTIVE_WINDOW_START_HOUR = 9
ACTIVE_WINDOW_END_HOUR = 23

# Rhythm thresholds (sliding window over last N published items).
RHYTHM_LOOKBACK = 10
RHYTHM_BURST_GAP_MIN = 30  # consecutive items < 30 min apart = burst
RHYTHM_DROUGHT_GAP_HOURS = 3.0  # > 3 h gap inside active window = drought

# Digest detection markers.
DIGEST_TITLE_PREFIX = "每日精選導讀"
DIGEST_CONTENT_TYPE = "daily_digest"

# Title format thresholds.
TITLE_MAX_LEN = 80  # frontend truncates beyond this; flag for tightening
TITLE_BAD_CHARS = ("\x00", "\r", "\t")


def _feed_path(storage_dir: str) -> Any:
    return project_path(storage_dir) / "reports" / "feed.json"


def _load_feed(storage_dir: str) -> list[dict[str, Any]]:
    feed = load_json(_feed_path(storage_dir), [])
    if not isinstance(feed, list):
        warn(
            "content_quality_feed",
            "feed.json not a list — treating as empty",
            type=type(feed).__name__,
        )
        return []
    return [x for x in feed if isinstance(x, dict)]


def _parse_iso(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        warn("content_quality_iso", "fromisoformat failed", raw=str(raw)[:60], err=str(exc))
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


def _published_items(feed: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [x for x in feed if x.get("status") == "published"]


def _item_publish_time(item: dict[str, Any]) -> datetime | None:
    return _parse_iso(item.get("published_at") or item.get("created_at"))


def _is_digest(item: dict[str, Any]) -> bool:
    if item.get("content_type") == DIGEST_CONTENT_TYPE:
        return True
    details = item.get("details")
    if isinstance(details, dict) and details.get("content_type") == DIGEST_CONTENT_TYPE:
        return True
    title = item.get("title") or ""
    return isinstance(title, str) and title.startswith(DIGEST_TITLE_PREFIX)


def check_publish_rhythm(
    storage_dir: str = "storage",
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Burst / drought detection over the last RHYTHM_LOOKBACK published items.

    Returns status one of: `ok`, `burst`, `drought`, `inactive_window`.

    `inactive_window` is a non-breach signal: we deliberately stay quiet
    overnight (digest job legitimately fires ~02:00 TPE).
    """
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    tpe_hour = current.astimezone(_TAIPEI_TZ).hour
    in_active = ACTIVE_WINDOW_START_HOUR <= tpe_hour < ACTIVE_WINDOW_END_HOUR

    feed = _load_feed(storage_dir)
    published = _published_items(feed)
    timed = [
        (item, ts)
        for item in published
        if (ts := _item_publish_time(item)) is not None
    ]
    timed.sort(key=lambda kv: kv[1], reverse=True)
    recent = timed[:RHYTHM_LOOKBACK]

    gaps_min: list[float] = []
    for i in range(len(recent) - 1):
        delta = (recent[i][1] - recent[i + 1][1]).total_seconds() / 60.0
        gaps_min.append(round(delta, 2))

    burst_pairs: list[dict[str, Any]] = []
    for i in range(len(recent) - 1):
        if gaps_min[i] < RHYTHM_BURST_GAP_MIN:
            burst_pairs.append(
                {
                    "newer_id": recent[i][0].get("id"),
                    "older_id": recent[i + 1][0].get("id"),
                    "gap_minutes": gaps_min[i],
                }
            )

    newest_ts = recent[0][1] if recent else None
    age_min = (
        round((current - newest_ts).total_seconds() / 60.0, 2)
        if newest_ts is not None
        else None
    )

    drought = (
        in_active
        and age_min is not None
        and age_min > RHYTHM_DROUGHT_GAP_HOURS * 60
    )

    if not in_active:
        status = "inactive_window"
    elif burst_pairs:
        status = "burst"
    elif drought:
        status = "drought"
    else:
        status = "ok"

    return {
        "status": status,
        "in_active_window": in_active,
        "tpe_hour": tpe_hour,
        "recent_count": len(recent),
        "newest_published_at": newest_ts.isoformat() if newest_ts else None,
        "age_since_newest_min": age_min,
        "gaps_min_newest_first": gaps_min,
        "burst_pairs": burst_pairs,
        "burst_gap_threshold_min": RHYTHM_BURST_GAP_MIN,
        "drought_gap_threshold_hours": RHYTHM_DROUGHT_GAP_HOURS,
    }


def check_daily_digest_uniqueness(
    storage_dir: str = "storage",
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """At most one published `每日精選導讀` per Taipei-local day.

    >1 → breach. This would have caught `mile_f3e389cf` (02:16) +
    `mile_1597b341` (02:34) on 2026-06-24 instead of the user noticing.
    """
    current = (now or datetime.now(timezone.utc)).astimezone(_TAIPEI_TZ)
    today_tpe = current.date()
    feed = _load_feed(storage_dir)

    todays: list[dict[str, Any]] = []
    for item in _published_items(feed):
        if not _is_digest(item):
            continue
        ts = _item_publish_time(item)
        if ts is None:
            continue
        if ts.astimezone(_TAIPEI_TZ).date() != today_tpe:
            continue
        todays.append(
            {
                "id": item.get("id"),
                "title": item.get("title"),
                "published_at": ts.isoformat(),
            }
        )

    count = len(todays)
    status = "ok" if count <= 1 else "duplicate"
    return {
        "status": status,
        "date_tpe": today_tpe.isoformat(),
        "published_count": count,
        "items": todays,
    }


def check_title_format(
    storage_dir: str = "storage",
    *,
    lookback: int = 30,
) -> dict[str, Any]:
    """Recent published titles — flag prefix-redundancy + length / control chars.

    The prefix-redundancy case is concrete (2026-06-24): a digest title
    `每日精選導讀｜分散投資的幻覺：...` rendered inside a section labelled
    `每日精選導讀`, so readers saw the prefix twice. Whether the frontend
    section name is the source of truth or the title is, the system should
    surface the collision; the fix decision lives outside this check.
    """
    feed = _load_feed(storage_dir)
    timed = [
        (item, ts)
        for item in _published_items(feed)
        if (ts := _item_publish_time(item)) is not None
    ]
    timed.sort(key=lambda kv: kv[1], reverse=True)
    recent = timed[:lookback]

    findings: list[dict[str, Any]] = []
    for item, _ts in recent:
        title = item.get("title") or ""
        if not isinstance(title, str):
            findings.append(
                {
                    "id": item.get("id"),
                    "issue": "non_string_title",
                    "title_type": type(title).__name__,
                }
            )
            continue
        if any(ch in title for ch in TITLE_BAD_CHARS):
            findings.append(
                {"id": item.get("id"), "issue": "control_chars", "title": title[:80]}
            )
        if len(title) > TITLE_MAX_LEN:
            findings.append(
                {
                    "id": item.get("id"),
                    "issue": "too_long",
                    "length": len(title),
                    "threshold": TITLE_MAX_LEN,
                    "title": title[:80],
                }
            )
        # Digest prefix-redundancy: title `每日精選導讀｜<rest>` while the
        # frontend already labels the section `每日精選導讀`. We flag based
        # solely on digest content type (top-level legacy or details metadata)
        # so non-digest titles using a normal `｜` are not false-positives.
        if _is_digest(item) and title.startswith(DIGEST_TITLE_PREFIX + "｜"):
            findings.append(
                {
                    "id": item.get("id"),
                    "issue": "digest_prefix_duplicates_section_header",
                    "title": title,
                    "note": (
                        "Title 重複了前端 '每日精選導讀' 區塊標頭；"
                        "前端 header 或 title 擇一移除前綴"
                    ),
                }
            )

    return {
        "status": "ok" if not findings else "issues",
        "scanned": len(recent),
        "lookback": lookback,
        "findings": findings,
    }


def content_quality_snapshot(
    storage_dir: str = "storage",
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Aggregate the MVP checks into one report.

    Mirrors `health.py::health_snapshot` shape so callers (alerts.py, CLI)
    can treat the two reports uniformly.
    """
    current = now or datetime.now(timezone.utc)
    return {
        "generated_at": current.astimezone(timezone.utc).isoformat(),
        "publish_rhythm": check_publish_rhythm(storage_dir, now=current),
        "daily_digest_uniqueness": check_daily_digest_uniqueness(
            storage_dir, now=current
        ),
        "title_format": check_title_format(storage_dir),
    }
