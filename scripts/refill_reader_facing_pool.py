#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo
import fcntl

ROOT = Path(__file__).resolve().parents[1]
STORAGE = ROOT / "storage"
OPS = STORAGE / "ops"
NEXT_TASKS = STORAGE / "next_tasks.json"
STATE_PATH = OPS / "daily_reader_facing_scan_state.json"
TRENDING_LOG = STORAGE / "reports" / "trending_repost_log.json"
FEED_PATH = STORAGE / "reports" / "feed.json"
RUNTIME_SCHEDULES = ROOT / "config" / "runtime_schedules.json"
LOCAL_TZ = ZoneInfo("Asia/Taipei")
TRENDING_SCAN_CMD_ENV = "VOLPRED_TRENDING_SCAN_CMD"
# 90d, not 30d: the 2026-07-13 incident was the 5th same-theme piece within 90
# days, and the theme-saturation threshold (6) was calibrated on the 90d live
# corpus. A 30d window would have scored the incident below threshold and let it
# through again. At generation time a wider window is the cheap direction — a
# false positive costs one swapped topic.
ARC_DEDUP_WINDOW_DAYS = 90

sys.path.insert(0, str(ROOT / "src"))

from volpred.ops.timestamps import parse_iso_warn  # noqa: E402
from volpred.ops.canonical_write import guard_canonical_write  # noqa: E402
from volpred.ops.diagnostics import warn  # noqa: E402
from volpred.ops.event_jobs import (  # noqa: E402
    build_pending_event_task,
    expand_due_event_jobs,
)
from volpred.ops.next_tasks import normalize_task_priorities, normalize_task_priority  # noqa: E402
from volpred.ops.topic_dedup import TopicScreen, log_decision, screen_topic  # noqa: E402

_diag_warn = warn  # legacy alias used by _warn_refill_reader (was undefined -> NameError)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _now_local() -> datetime:
    return _now_utc().astimezone(LOCAL_TZ)


def _today_local() -> str:
    return _now_local().date().isoformat()


def _warn_refill_reader(message: str, path: Path, exc: Exception) -> None:
    _diag_warn(
        "reader_facing_refill",
        message,
        path=str(path),
        err=f"{type(exc).__name__}: {exc}",
    )


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        _warn_refill_reader("JSON read failed; using default", path, exc)
        return default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load_next_tasks() -> list[dict[str, Any]]:
    return _load_json(NEXT_TASKS, [])


def _append_task(task: dict[str, Any]) -> bool:
    normalize_task_priority(task)
    NEXT_TASKS.parent.mkdir(parents=True, exist_ok=True)
    if not NEXT_TASKS.exists():
        NEXT_TASKS.write_text("[]\n", encoding="utf-8")
    with NEXT_TASKS.open("r+", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            data = json.load(fh)
            if not isinstance(data, list):
                raise ValueError("next_tasks.json is not a list")
            if any(isinstance(item, dict) and item.get("id") == task["id"] for item in data):
                return False
            data.append(task)
            normalize_task_priorities(data)
            fh.seek(0)
            fh.truncate()
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
            return True
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _load_runtime_event_items() -> list[dict[str, Any]]:
    payload = _load_json(RUNTIME_SCHEDULES, {})
    event_jobs = payload.get("event_jobs") if isinstance(payload, dict) else None
    items = event_jobs.get("items") if isinstance(event_jobs, dict) else None
    return items if isinstance(items, list) else []


def _task_exists(task_id: str) -> bool:
    tasks = _load_next_tasks()
    return any(isinstance(item, dict) and item.get("id") == task_id for item in tasks)


def _event_task_id(event_type: str, event_date: str, slot: str) -> str:
    slot_norm = slot.lower().replace("+", "plus").replace("-", "minus")
    return f"event_article_{event_type.lower()}_{event_date}_{slot_norm}"


# --- Slot-aware event coverage (2026-07-03 NFP T+0 stale-duplicate fix) -------
# Root cause: refill deduped only by task_id, so a reaction (result-known) task
# (T+0/T-0/T+1) was regenerated even when a feed article already covered the
# event. The scheduled event_date is an ESTIMATE; when the data releases early
# and a reaction article publishes early, the estimated-date task becomes a
# stale duplicate (mile_35eef830 vs event_article_nfp_us_2026-07-03_tplus0,
# intercepted manually). Feed articles carry no event_key metadata yet (part-b
# follow-up), so coverage falls back to event-type alias + reaction-window title
# match. Only reaction slots are gated — forward slots (T-7/T-2) are distinct
# pre-event pieces and keep the existing task_id idempotency untouched so a real
# forward article is never suppressed. Risk asymmetry: a false-positive here
# would MISS a real event article (unrecoverable), whereas a false-negative only
# lets a duplicate through to the publish-time arc-dedup backstop (recoverable);
# so the check is conservative + fail-open + audit-logged (dedup-gate-audit rule).
DEDUP_LOG = STORAGE / "logs" / "dedup_decisions.jsonl"
REACTION_EARLY_RELEASE_DAYS = 3   # data can print up to N days before scheduled date
REACTION_POST_DAYS = 7            # reaction article publishes within N days after event
FORWARD_TITLE_SIGNALS = (
    "前瞻", "預告", "倒數", "前夕", "來臨", "即將", "展望",
    "前7天", "前 7 天", "前七天", "前2天", "前 2 天", "前兩天",
    "t-7", "t-2", "t-3", "t-5",
)
EVENT_TYPE_ALIASES = {
    "nfp": ("非農", "非農就業", "nonfarm", "payroll", "就業報告", "nfp"),
    "cpi": ("cpi", "消費者物價", "通膨", "通脹", "物價指數"),
    "pce": ("pce", "個人消費支出", "個人消費"),
    "ppi": ("ppi", "生產者物價"),
    "fomc": ("fomc", "聯準會", "利率決策", "點陣圖", "議息", "降息", "升息", "fed"),
    "gdp": ("gdp", "國內生產毛額", "經濟成長"),
    "tsmc_revenue": ("台積電", "tsmc", "營收"),
    "earnings": ("財報", "earnings"),
}


def _slot_is_reaction(slot: str) -> bool:
    """T+0 / T-0 / T+N are result-known reaction slots; T-N (N>=1) is forward.

    Unknown/unparseable slots are treated as forward (not gated) so we never
    suppress a real article on an unexpected slot label.
    """
    m = re.match(r"^t([+-])(\d+)", str(slot or "").strip().lower().replace(" ", ""))
    if not m:
        return False
    sign, num = m.group(1), int(m.group(2))
    return not (sign == "-" and num >= 1)


def _event_type_aliases(event_type: str) -> list[str]:
    et = str(event_type or "").strip().lower()
    aliases: set[str] = set()
    if et:
        aliases.add(et)
        aliases.add(et.split("_")[0])  # e.g. nfp_us -> nfp
    for key, vals in EVENT_TYPE_ALIASES.items():
        if et.startswith(key) or key in et:
            aliases.update(vals)
    return [a for a in aliases if a]


def _looks_forward(title: str) -> bool:
    t = str(title or "").lower()
    return any(sig in t for sig in FORWARD_TITLE_SIGNALS)


def _log_coverage_decision(target_id: str, decision: str, reason: str, dup_of: str = "") -> None:
    """Audit trail for the coverage gate (dedup-gate-audit rule). Never raises."""
    guard_canonical_write(DEDUP_LOG)
    try:
        DEDUP_LOG.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": _now_utc().isoformat(timespec="seconds"),
            "gate": "event_reaction_coverage",
            "target_id": target_id,
            "decision": decision,   # "skip" | "pass"
            "reason": reason,
            "dup_of": dup_of,
        }
        with DEDUP_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as exc:  # pragma: no cover - audit log must never block refill
        warn("reader_facing_refill", "coverage audit log failed",
             err=f"{type(exc).__name__}: {exc}")


def _reaction_already_covered(
    event_type: str, event_date: date | None, feed: list[dict[str, Any]]
) -> dict[str, str] | None:
    """Return the covering reaction article for this event, or None (fail-open).

    Matching (published articles only):
      1. EXACT metadata — article.event_type + event_date + a reaction slot
         (activates once the part-b publisher metadata write lands).
      2. FUZZY fallback (current reality: feed has no event metadata) — an
         event-type alias appears in title/tags, the article published within
         [event_date - EARLY, event_date + POST], and the title is NOT a
         forward-looking preview (excludes T-7/T-2 pieces).
    Any exception returns None so a real event task is still generated.
    """
    try:
        aliases = _event_type_aliases(event_type)
        if not aliases:
            return None
        et = str(event_type or "").strip().lower()
        ev_iso = event_date.isoformat() if event_date else None
        lo = event_date - timedelta(days=REACTION_EARLY_RELEASE_DAYS) if event_date else None
        hi = event_date + timedelta(days=REACTION_POST_DAYS) if event_date else None
        for art in feed:
            if not isinstance(art, dict):
                continue
            if art.get("status") not in (None, "published"):
                continue
            # 1. exact metadata match (future articles once part-b lands)
            a_type = str(art.get("event_type") or "").strip().lower()
            if a_type and et and a_type == et and ev_iso and art.get("event_date") == ev_iso:
                if _slot_is_reaction(art.get("event_series_slot") or ""):
                    return {"id": str(art.get("id") or ""), "match": "metadata"}
            # 2. fuzzy fallback on title/tags + reaction publish-window
            title = str(art.get("title") or "")
            tags = " ".join(str(t) for t in (art.get("tags") or []))
            hay = (title + " " + tags).lower()
            if not any(a in hay for a in aliases):
                continue
            if _looks_forward(title):
                continue  # forward preview, not a reaction — do not gate
            if lo is None or hi is None:
                continue
            pub_raw = art.get("published_at") or art.get("created_at")
            pub_dt = parse_iso_warn(
                pub_raw, tag="reader_facing_refill", field_name="published_at",
                fallback=None, item_id=str(art.get("id") or ""), path=str(FEED_PATH),
            ) if pub_raw else None
            if pub_dt is None:
                continue
            pub_date = pub_dt.astimezone(LOCAL_TZ).date()
            if lo <= pub_date <= hi:
                return {"id": str(art.get("id") or ""), "match": "fuzzy"}
        return None
    except Exception as exc:  # fail-open: never block generating a real article
        warn("reader_facing_refill", "reaction coverage check failed (fail-open)",
             err=f"{type(exc).__name__}: {exc}")
        return None


def _build_event_task(item: dict[str, Any]) -> dict[str, Any]:
    """Compatibility wrapper; event_jobs owns the canonical task schema.

    The feed MUST be passed: `build_pending_event_task` only runs the
    generation-time topic screen when it has a corpus, so omitting it here would
    silently leave this second event-task path unscreened — the exact "generator
    never looks at the feed" hole this change closes. Event lane screens in WARN
    mode, so this can annotate a task but never block one.
    """

    # Pass STORAGE explicitly: the callee's default is the relative "storage",
    # which resolves against the caller's cwd rather than the repo root.
    return build_pending_event_task(
        item, now=_now_utc(), feed=_load_feed_for_dedup(), storage_dir=str(STORAGE)
    )


def refill_event_candidates(*, horizon_days: int = 14) -> dict[str, Any]:
    """Delegate event eligibility and materialization to the hourly owner.

    ``horizon_days`` remains for API compatibility.  Eligibility now comes
    only from canonical ``not_before`` / ``deadline`` values, eliminating the
    second writer and its once-per-day scan gate.
    """

    _ = horizon_days
    result = expand_due_event_jobs(storage_dir=str(STORAGE), now=_now_utc())
    added = [
        str(entry["task"]["id"])
        for entry in result.get("created", [])
        if entry.get("queue_created") and isinstance(entry.get("task"), dict)
    ]
    return {
        "added": added,
        "skipped": result.get("skipped", []),
        "expired": result.get("expired_tasks", {}),
    }


def refill_member_qa() -> dict[str, Any]:
    try:
        import sys

        sys.path.insert(0, str(ROOT / "src"))
        from volpred.ops.questions import ensure_member_qa_task

        result = ensure_member_qa_task(source="user")
        return {"ok": True, "result": result}
    except Exception as exc:
        return {"ok": False, "error": repr(exc)}


def _extract_trending_candidates(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        items = payload.get("candidates")
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    return []


def _build_trending_task(candidate: dict[str, Any]) -> dict[str, Any]:
    task_id = str(candidate.get("id") or "").strip()
    if not task_id:
        topic = str(candidate.get("topic") or "trending")
        task_id = f"trending_repost_{_today_local().replace('-', '_')}_{topic.lower().replace(' ', '_')[:40]}"
    title = str(candidate.get("title") or candidate.get("topic") or "trending repost candidate")
    description = str(candidate.get("description") or candidate.get("brief") or "")
    return {
        "id": task_id,
        "title": f"[trending_repost] {title}",
        "description": description,
        "task_type": "trending_repost",
        "priority": 1,
        "status": "pending",
        "created_at": _now_utc().isoformat(timespec="seconds"),
        "source": "reader_facing_refill",
        "tags": ["trending_repost", "reader_facing", "auto_refill"],
    }


def _screen_trending_topic(title: str, description: str, feed: list[dict] | None) -> TopicScreen:
    """Generation-time dedup screen for a trending candidate (BLOCK mode).

    Pre-write gate (release-layer recycling root cause, 2026-06-23): trending
    scan kept producing pending tasks for arcs already covered (Fed-pivot 22
    dups, AI capex 2 dups) because no upstream check existed. Publisher arc
    block fires only at publish time — the task still wastes a dispatch slot.

    2026-07-14: the previous version called `find_arc_duplicates` alone and
    swallowed every exception into `return None` (a silent fallback). It could
    not have caught the 2026-07-13 incident anyway — the arc gate is
    entity-anchored and the incident's five siblings do not arc-match each other
    (0 of 10 pairs; see volpred.publisher.arc_dedup.theme_saturation). The screen
    now also runs theme saturation, which does catch it (saturation 11 >= 6), and
    every decision — including a gate error — is logged, never swallowed.
    """
    return screen_topic(
        title,
        description,
        feed=feed,
        days=ARC_DEDUP_WINDOW_DAYS,
        mode="block",
    )


def _load_feed_for_dedup() -> list[dict]:
    if not FEED_PATH.exists():
        return []
    try:
        data = json.loads(FEED_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    return data if isinstance(data, list) else []


def refill_trending_candidates() -> dict[str, Any]:
    cmd = os.environ.get(TRENDING_SCAN_CMD_ENV, "").strip()
    if not cmd:
        # Trending scan is best-effort: main pipeline relies on the trending_repost
        # agent doing WebSearch itself. Missing scan command is a skip, not an error.
        return {
            "ok": True,
            "skipped": True,
            "reason": "no_scan_cmd_configured",
            "hint": f"set {TRENDING_SCAN_CMD_ENV} to enable batch refill",
            "added": [],
        }
    proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=ROOT)
    if proc.returncode != 0:
        return {"ok": False, "reason": "scan_failed", "stderr": proc.stderr[-500:]}
    try:
        payload = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError as exc:
        return {"ok": False, "reason": "bad_json", "error": str(exc)}

    feed = _load_feed_for_dedup()
    added: list[str] = []
    skipped: list[dict[str, str]] = []
    for candidate in _extract_trending_candidates(payload):
        task = _build_trending_task(candidate)
        screen = _screen_trending_topic(task["title"], task.get("description", ""), feed)
        # Audit trail is written for EVERY verdict (pass / block / gate error),
        # so "why was this task never created?" is always answerable. Silent skip
        # is what let the 2026-07-13 dup sit in the pool for 20 hours.
        log_decision(str(STORAGE), "trending_repost", task["id"], screen)
        if screen.blocked:
            skipped.append({
                "id": task["id"],
                "reason": screen.verdict,
                "detail": screen.reason,
                "dup_of": ",".join(str(m.get("id")) for m in screen.matches[:3]),
            })
            continue
        # Not blocked, but the screen still has something to say -> hand the near
        # misses to the writer agent instead of dropping them on the floor.
        task["dedup_screen"] = screen.as_task_field()
        if _append_task(task):
            added.append(task["id"])
            if len(added) >= 1:
                break
        else:
            skipped.append({"id": task["id"], "reason": "already_exists"})
    return {"ok": True, "added": added, "skipped": skipped}


def _default_state() -> dict[str, Any]:
    return {
        "date": _today_local(),
        "scanned": False,
        "scanned_at": None,
        "trending_added": 0,
        "event_added": 0,
        "member_qa_added": 0,
        "errors": [],
    }


def run_refill(*, force: bool = False) -> dict[str, Any]:
    state = _load_json(STATE_PATH, _default_state())
    today = _today_local()
    if not force and state.get("date") == today and state.get("scanned") is True:
        return {
            "skip": True,
            "reason": "already_scanned_today",
            "state": state,
        }

    result = _default_state()
    result["scanned_at"] = _now_utc().isoformat(timespec="seconds")

    trending = refill_trending_candidates()
    if trending.get("ok"):
        result["trending_added"] = len(trending.get("added") or [])
        if trending.get("skipped"):
            result["trending_skipped"] = {
                "reason": trending.get("reason"),
                "hint": trending.get("hint"),
            }
    else:
        result["errors"].append({"source": "trending_scan", **trending})

    events = refill_event_candidates()
    result["event_added"] = len(events.get("added") or [])
    if events.get("skipped"):
        result["event_skipped"] = events["skipped"][:20]

    member = refill_member_qa()
    if member.get("ok") and isinstance(member.get("result"), dict) and member["result"].get("created"):
        result["member_qa_added"] = 1
    elif not member.get("ok"):
        result["errors"].append({"source": "member_qa_eval", **member})
    else:
        result["member_qa_result"] = member.get("result")

    result["scanned"] = True
    _write_json(STATE_PATH, result)
    return {"skip": False, "state": result}


def main() -> int:
    parser = argparse.ArgumentParser(description="Refill reader-facing task pool (event/trending/member_qa)")
    parser.add_argument("--force", action="store_true", help="Ignore daily state and scan again")
    args = parser.parse_args()

    outcome = run_refill(force=args.force)
    print(json.dumps(outcome, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
