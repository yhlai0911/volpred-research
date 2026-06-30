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

import re
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

# Phases / categories whose publish timing is NOT controlled by the 6h
# release_pool rhythm — fixtures (digest/daily_update fire at fixed times) and
# event-driven types (trending/event publish when news breaks). Excluded from
# burst detection: two of them coinciding is not a rhythm violation.
_NON_RHYTHM_PHASES = {
    "digest",
    "daily_update",
    "daily_recommendation",
    "trending_repost",
    "event",
    "event_article",
}
_NON_RHYTHM_CATEGORIES = {"event_article", "trending_repost"}

# 2026-06-30 (boss email-12281 / boss 設 release=6h)：drought 門檻須跟 release 節奏
# 對齊。固定 3h 門檻 < 6h release interval → 正常 6h gap 就誤報 drought（同 burst 的
# 測量-政策錯配）。drought 真正要抓的是「pipeline stall」，門檻 = release interval +
# grace（涵蓋 piggy-back latency + 偶爾 skip cycle），floor 仍是 RHYTHM_DROUGHT_GAP_HOURS。
RHYTHM_DROUGHT_GRACE_HOURS = 2.0
_DEFAULT_RELEASE_INTERVAL_HOURS = 6.0  # fallback 若 .release_settings.json 不可讀

# Digest detection markers.
DIGEST_TITLE_PREFIX = "每日精選導讀"
DIGEST_CONTENT_TYPE = "daily_digest"

# Title format thresholds.
TITLE_MAX_LEN = 80  # frontend truncates beyond this; flag for tightening
TITLE_BAD_CHARS = ("\x00", "\r", "\t")

# --- 2026-06-29 patrol completion (the 4 checks designed but not yet built) ---
# arc diversity: over-concentration of one narrative arc among recent published.
ARC_DIVERSITY_LOOKBACK = 20
ARC_DIVERSITY_MIN_SAMPLE = 8
ARC_DOMINANCE_THRESHOLD = 0.50  # top arc share > 50% over the sample → warn
# content completeness: chart + source markers expected in every article.
COMPLETENESS_LOOKBACK = 12
_CHART_MARKERS = ("![", ".png", ".svg", ".jpg", "chart", "figure", "圖", "<img")
_SOURCE_MARKERS = ("來源", "資料來源", "data source", "experiment", "實驗", "回測", "樣本")
_KID_RE = re.compile(r"\bK\d{2,}\b")  # K-id citation (K123, K1557, ...)
# release deadlock: the candidate source feeding the draft/release pool.
RELEASE_CANDIDATE_FIELDS = ("candidates", "top_10_uncovered")
# frontend render probe.
FRONTEND_PROBE_TIMEOUT_S = 6.0
_FRONTEND_ERROR_MARKERS = ("Minified React error", "Application error", "500 Internal")


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


def _release_interval_hours(storage_dir: str) -> float:
    """Canonical release cadence (hours) from .release_settings.json.

    Used to make the drought threshold track the boss-configured release rhythm
    (6h since 2026-06-30) instead of a static 3h that false-fires on normal gaps.
    """
    path = project_path(storage_dir) / ".release_settings.json"
    try:
        raw = load_json(path, default={})
        minutes = float((raw or {}).get("interval_minutes") or 0)
        if minutes > 0:
            return minutes / 60.0
    except (OSError, ValueError, TypeError) as exc:
        warn("content_quality", "release interval read failed; using default", err=str(exc))
    return _DEFAULT_RELEASE_INTERVAL_HOURS


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

    # 2026-06-30 (boss email-12253): pairs sharing the same
    # `details.paired_sibling_group` (e.g. daily_update.py's strategy +
    # 持倉 sibling articles that fire together in one script run) are
    # semantically one publish event and must NOT count as a burst.
    def _sibling_group(item: dict[str, Any]) -> str | None:
        det = item.get("details")
        if isinstance(det, dict):
            grp = det.get("paired_sibling_group")
            if isinstance(grp, str) and grp:
                return grp
        return None

    # 2026-06-30 (boss email-12281「兩個 Warn 已經存在很久」): burst 只衡量
    # *discretionary* 文章（受 6h release_pool 節奏控制者）clumping。獨立排程的
    # fixture / 事件驅動文章——daily_digest（晨間固定）、daily_update（每日固定）、
    # trending_repost / event_article（事件驅動，新聞一來就發）——各依自己邏輯擇時，
    # 兩個不同 type 偶然相近不是 6h 節奏違規。把它們算進 burst → 每天晨間 digest+
    # trending 撞在一起就永久誤報（root cause of「存在很久」的 warn）。
    def _is_rhythm_controlled(item: dict[str, Any]) -> bool:
        if (item.get("audience") or "").lower() == "daily":
            return False
        phase = (item.get("phase") or "").lower()
        if phase in _NON_RHYTHM_PHASES:
            return False
        cat = (item.get("category") or "").lower()
        if cat in _NON_RHYTHM_CATEGORIES:
            return False
        return True

    disc = [kv for kv in recent if _is_rhythm_controlled(kv[0])]
    burst_pairs: list[dict[str, Any]] = []
    for i in range(len(disc) - 1):
        gap = round((disc[i][1] - disc[i + 1][1]).total_seconds() / 60.0, 2)
        if gap < RHYTHM_BURST_GAP_MIN:
            g_new = _sibling_group(disc[i][0])
            g_old = _sibling_group(disc[i + 1][0])
            if g_new and g_new == g_old:
                continue
            burst_pairs.append(
                {
                    "newer_id": disc[i][0].get("id"),
                    "older_id": disc[i + 1][0].get("id"),
                    "gap_minutes": gap,
                }
            )

    newest_ts = recent[0][1] if recent else None
    age_min = (
        round((current - newest_ts).total_seconds() / 60.0, 2)
        if newest_ts is not None
        else None
    )

    drought_threshold_h = max(
        RHYTHM_DROUGHT_GAP_HOURS,
        _release_interval_hours(storage_dir) + RHYTHM_DROUGHT_GRACE_HOURS,
    )
    drought = (
        in_active
        and age_min is not None
        and age_min > drought_threshold_h * 60
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
        "drought_gap_threshold_hours": round(drought_threshold_h, 1),
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


def _arc_axis(item: dict[str, Any]) -> str:
    """Best-available narrative-arc key for an item (real fields only).

    Handles both legacy string arc_signature and current dict shape
    (`arc_dedup_v2`/`v3` schema). For dicts, the key is the sorted entity tuple
    + conclusion_class — different entity sets / different conclusion classes
    become distinct axes (fixes 2026-06-30 false-positive where dict
    arc_signature fell through to coarse category=general/milestone).
    """
    details = item.get("details")
    if isinstance(details, dict):
        for key in ("arc_signature", "arc_signature_backfill"):
            val = details.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
            if isinstance(val, dict) and val:
                entities = val.get("entities") or []
                concl = val.get("conclusion_class") or ""
                if isinstance(entities, list) and entities:
                    ent_key = "|".join(sorted(str(e) for e in entities))
                    return f"{ent_key}::{concl}" if concl else ent_key
                if isinstance(concl, str) and concl.strip():
                    return f"::{concl.strip()}"
    cat = item.get("category")
    return cat.strip() if isinstance(cat, str) and cat.strip() else "(unaxised)"


def check_arc_diversity(
    storage_dir: str = "storage",
    *,
    lookback: int = ARC_DIVERSITY_LOOKBACK,
) -> dict[str, Any]:
    """Over-concentration of one narrative arc among recent published items.

    Reader retention dies when every recent article is the same arc in a new
    shell. Flags when the top arc exceeds ARC_DOMINANCE_THRESHOLD of a
    sufficiently large recent sample (uses `details.arc_signature`, falling back
    to `category`). Remediation: dispatch a fresh-arc / journal-discovery topic.
    """
    feed = _load_feed(storage_dir)
    timed = [
        (item, ts)
        for item in _published_items(feed)
        if (ts := _item_publish_time(item)) is not None
    ]
    timed.sort(key=lambda kv: kv[1], reverse=True)
    recent = [item for item, _ in timed[:lookback]]
    if len(recent) < ARC_DIVERSITY_MIN_SAMPLE:
        return {
            "status": "ok",
            "sample": len(recent),
            "note": "too few recent published items to judge diversity",
        }
    counts: dict[str, int] = {}
    for item in recent:
        axis = _arc_axis(item)
        counts[axis] = counts.get(axis, 0) + 1
    top_axis, top_count = max(counts.items(), key=lambda kv: kv[1])
    share = round(top_count / len(recent), 3)
    status = "concentrated" if share > ARC_DOMINANCE_THRESHOLD else "ok"
    return {
        "status": status,
        "sample": len(recent),
        "distinct_axes": len(counts),
        "top_axis": top_axis,
        "top_share": share,
        "threshold": ARC_DOMINANCE_THRESHOLD,
        "distribution": dict(sorted(counts.items(), key=lambda kv: kv[1], reverse=True)),
    }


def check_content_completeness(
    storage_dir: str = "storage",
    *,
    lookback: int = COMPLETENESS_LOOKBACK,
) -> dict[str, Any]:
    """Recent published articles must carry a real chart AND a source citation.

    Per the project rule (每篇文章都要有真圖表 + 標明數據來源). Scans the
    rendered `content` for chart/image markers and source/experiment markers;
    flags items missing either. Conservative: only flags when BOTH the content
    body and structured fields lack the marker (avoids false positives on items
    whose chart lives in a `charts`/`images` field).
    """
    feed = _load_feed(storage_dir)
    timed = [
        (item, ts)
        for item in _published_items(feed)
        if (ts := _item_publish_time(item)) is not None
    ]
    timed.sort(key=lambda kv: kv[1], reverse=True)
    recent = [item for item, _ in timed[:lookback]]

    findings: list[dict[str, Any]] = []
    for item in recent:
        content = item.get("content")
        text = content if isinstance(content, str) else ""
        text_low = text.lower()
        details = item.get("details") if isinstance(item.get("details"), dict) else {}
        # A chart is present if the body has an inline marker, a structured
        # charts/images field, OR `details` carries numeric metric data the
        # frontend renders into a chart component (avoids flagging articles whose
        # chart is frontend-rendered from details — e.g. dm_stat/pvalue fields).
        has_chartable_details = any(isinstance(v, (int, float)) for v in details.values())
        has_chart = (
            any(m.lower() in text_low for m in _CHART_MARKERS)
            or bool(item.get("charts") or item.get("images"))
            or bool(details.get("charts") or details.get("chart_path"))
            or has_chartable_details
        )
        has_source = (
            any(m.lower() in text_low for m in _SOURCE_MARKERS)
            or bool(_KID_RE.search(text))
            or bool(details.get("experiment_refs") or details.get("experiment_id"))
        )
        if not has_chart or not has_source:
            findings.append(
                {
                    "id": item.get("id"),
                    "missing_chart": not has_chart,
                    "missing_source": not has_source,
                    "title": (item.get("title") or "")[:60],
                }
            )
    return {
        "status": "ok" if not findings else "incomplete",
        "scanned": len(recent),
        "findings": findings,
    }


def check_release_deadlock(storage_dir: str = "storage") -> dict[str, Any]:
    """Early warning: the candidate source feeding the release pool is empty.

    `draft_pool_low` (alerts.py) fires once the draft pool drains; this fires
    UPSTREAM — when `publication_candidates.json` itself has no candidates, the
    refill source is exhausted and the pool will inevitably empty next. Critical
    because a dry source = the release pipeline deadlocks (2026-06-23 8-day gap).
    """
    path = project_path(storage_dir) / "publication_candidates.json"
    if not path.exists():
        # Missing file is a setup/provisioning problem, not a release deadlock —
        # don't fire a false critical (e.g. in test/sandbox storage dirs).
        return {"status": "unknown", "exists": False}
    data = load_json(path, {})
    if not isinstance(data, dict):
        warn("content_quality_release", "publication_candidates not a dict", type=type(data).__name__)
        return {"status": "unknown", "exists": True}
    counts = {}
    total = 0
    for field in RELEASE_CANDIDATE_FIELDS:
        val = data.get(field)
        n = len(val) if isinstance(val, list) else 0
        counts[field] = n
        total += n
    status = "deadlock" if total == 0 else "ok"
    return {
        "status": status,
        "exists": path.exists(),
        "candidate_counts": counts,
        "total": total,
    }


def _default_fetcher(url: str, timeout: float) -> tuple[int, str]:
    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": "volpred-content-patrol"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (fixed https target)
        body = resp.read(4096).decode("utf-8", errors="replace")
        return resp.status, body


def check_frontend_render(
    storage_dir: str = "storage",
    *,
    fetcher=None,
    probe: bool = True,
) -> dict[str, Any]:
    """Best-effort probe that the live homepage returns 200 with no React error.

    Network-dependent → fail-open: any error / disabled probe → `unknown` (never
    a breach). `fetcher` is injectable for tests (default urllib). Reads the live
    URL from config/project_targets.json (single source of truth).
    """
    if not probe:
        return {"status": "unknown", "probed": False, "note": "probe disabled"}
    try:
        from volpred.config import load_project_targets

        targets = load_project_targets()
        url = (targets.get("site") or {}).get("default_remote_url") if isinstance(targets, dict) else None
    except Exception as exc:
        warn("content_quality_frontend", "target URL resolve failed; skipping probe", err=str(exc))
        return {"status": "unknown", "probed": False, "error": str(exc)}
    if not url:
        return {"status": "unknown", "probed": False, "note": "no site URL in project_targets"}

    fetch = fetcher or _default_fetcher
    try:
        status_code, body = fetch(url, FRONTEND_PROBE_TIMEOUT_S)
    except Exception as exc:
        warn("content_quality_frontend", "frontend probe failed; treating as unknown", url=url, err=str(exc))
        return {"status": "unknown", "probed": True, "url": url, "error": str(exc)}
    react_error = any(marker in body for marker in _FRONTEND_ERROR_MARKERS)
    if status_code != 200:
        status = "error"
    elif react_error:
        status = "error"
    else:
        status = "ok"
    return {
        "status": status,
        "probed": True,
        "url": url,
        "http_status": status_code,
        "react_error": react_error,
    }


def content_quality_snapshot(
    storage_dir: str = "storage",
    *,
    now: datetime | None = None,
    probe_frontend: bool = False,
    fetcher=None,
) -> dict[str, Any]:
    """Aggregate all content-quality checks into one report.

    Mirrors `health.py::health_snapshot` shape so callers (alerts.py, CLI)
    can treat the two reports uniformly. `probe_frontend` defaults OFF so the
    snapshot is pure/offline (safe for tests + the dashboard); the hourly alert
    path opts in via env (see alerts._parse_content_quality_state). `fetcher` is
    injectable for tests.
    """
    current = now or datetime.now(timezone.utc)
    return {
        "generated_at": current.astimezone(timezone.utc).isoformat(),
        "publish_rhythm": check_publish_rhythm(storage_dir, now=current),
        "daily_digest_uniqueness": check_daily_digest_uniqueness(
            storage_dir, now=current
        ),
        "title_format": check_title_format(storage_dir),
        # 2026-06-29 patrol completion (4 designed checks now built).
        "arc_diversity": check_arc_diversity(storage_dir),
        "content_completeness": check_content_completeness(storage_dir),
        "release_deadlock": check_release_deadlock(storage_dir),
        "frontend_render": check_frontend_render(
            storage_dir, fetcher=fetcher, probe=probe_frontend
        ),
    }
