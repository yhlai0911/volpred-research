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
ARC_DEDUP_WINDOW_DAYS = 30

sys.path.insert(0, str(ROOT / "src"))

from volpred.ops.timestamps import parse_iso_warn  # noqa: E402
from volpred.ops.diagnostics import warn  # noqa: E402

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
    payload_patch = ((item.get("task_template") or {}).get("payload_patch") or {})
    event_type = str(payload_patch.get("event_type") or item.get("event_key") or "event").lower()
    event_date = str(payload_patch.get("event_date") or "unknown-date")
    slot = str(payload_patch.get("event_series_slot") or "T-0")
    title = str((item.get("task_template") or {}).get("title") or item.get("id") or "event article")
    description = str((item.get("task_template") or {}).get("description") or "")
    return {
        "id": _event_task_id(event_type, event_date, slot),
        "title": f"[event_article] {title}",
        "description": (
            f"Auto-generated by refill_reader_facing_pool.py from event_jobs.\n"
            f"ref_event_job_id: {item.get('id')}\n"
            f"event_key: {item.get('event_key')}\n"
            f"event_type: {event_type}\n"
            f"event_date: {event_date}\n"
            f"event_series_slot: {slot}\n\n"
            f"{description}"
        ),
        "task_type": "event_article",
        "priority": 1,
        "status": "pending",
        "created_at": _now_utc().isoformat(timespec="seconds"),
        "source": "reader_facing_refill",
        "ref_event_job_id": item.get("id"),
        "event_key": item.get("event_key"),
        "event_type": event_type,
        "event_date": event_date,
        "event_series_slot": slot,
        "tags": ["event_article", "reader_facing", event_type, slot],
    }


def refill_event_candidates(*, horizon_days: int = 14) -> dict[str, Any]:
    now = _now_utc()
    added: list[str] = []
    skipped: list[dict[str, str]] = []
    feed_cache: list[dict[str, Any]] | None = None  # loaded lazily on first reaction slot
    for item in _load_runtime_event_items():
        payload_patch = ((item.get("task_template") or {}).get("payload_patch") or {})
        event_date_raw = payload_patch.get("event_date")
        if not event_date_raw:
            skipped.append({"id": str(item.get("id")), "reason": "missing_event_date"})
            continue
        event_date_dt = parse_iso_warn(
            event_date_raw,
            tag="reader_facing_refill",
            field_name="event_date",
            fallback=None,
            item_id=str(item.get("id") or ""),
            path=str(RUNTIME_SCHEDULES),
        )
        if event_date_dt is None:
            skipped.append({"id": str(item.get("id")), "reason": "bad_event_date"})
            continue
        event_date = event_date_dt.date()
        delta_days = (event_date - now.astimezone(LOCAL_TZ).date()).days
        if delta_days < 0 or delta_days > horizon_days:
            skipped.append({"id": str(item.get("id")), "reason": "out_of_horizon"})
            continue
        not_before_raw = item.get("not_before")
        if not_before_raw:
            not_before_dt = parse_iso_warn(
                not_before_raw,
                tag="reader_facing_refill",
                field_name="not_before",
                fallback=None,
                assume_tz=None,
                item_id=str(item.get("id") or ""),
                path=str(RUNTIME_SCHEDULES),
            )
            if not_before_dt is None:
                skipped.append({"id": str(item.get("id")), "reason": "bad_not_before"})
                continue
            if not_before_dt.tzinfo is None:
                not_before_dt = not_before_dt.replace(tzinfo=LOCAL_TZ)
            if now < not_before_dt.astimezone(timezone.utc):
                skipped.append({"id": str(item.get("id")), "reason": "not_yet_in_window"})
                continue
        task = _build_event_task(item)
        # Slot-aware coverage: only gate result-known reaction slots (T+0/T-0/T+N);
        # forward slots keep plain task_id idempotency so a real preview is never lost.
        if _slot_is_reaction(task.get("event_series_slot") or ""):
            if feed_cache is None:
                feed_cache = _load_feed_for_dedup()
            covered = _reaction_already_covered(
                str(task.get("event_type") or ""), event_date, feed_cache
            )
            if covered:
                skipped.append({
                    "id": task["id"],
                    "reason": "reaction_already_covered",
                    "dup_of": covered.get("id", ""),
                })
                _log_coverage_decision(
                    task["id"], "skip", "reaction_already_covered", covered.get("id", "")
                )
                continue
        if _append_task(task):
            added.append(task["id"])
        else:
            skipped.append({"id": task["id"], "reason": "already_exists"})
    return {"added": added, "skipped": skipped}


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


def _is_arc_duplicate(title: str, description: str, feed: list[dict] | None) -> dict | None:
    """Return first arc-duplicate match or None.

    Pre-write gate (release-layer recycling root cause, 2026-06-23): trending
    scan kept producing pending tasks for arcs already covered (Fed-pivot 22
    dups, AI capex 2 dups) because no upstream check existed. Publisher arc
    block fires only at publish time — the task still wastes a dispatch slot.
    """
    if not feed:
        return None
    try:
        from volpred.publisher.arc_dedup import find_arc_duplicates
    except Exception:
        return None
    dups = find_arc_duplicates(title, description, feed, days=ARC_DEDUP_WINDOW_DAYS)
    return dups[0] if dups else None


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
        dup = _is_arc_duplicate(task["title"], task.get("description", ""), feed)
        if dup:
            skipped.append({
                "id": task["id"],
                "reason": "arc_duplicate",
                "dup_of": dup.get("id", ""),
            })
            continue
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
