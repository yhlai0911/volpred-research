#!/usr/bin/env python3
"""Mark FB posting state on feed + trending_repost_log in one place.

Use this instead of hand-editing feed.json / trending_repost_log.json when an
article enters a known FB pipeline state such as interactive-session handoff.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from volpred.ops.shared_lock import shared_state_lock

FEED_PATH = ROOT / "storage" / "reports" / "feed.json"
TRENDING_LOG_PATH = ROOT / "storage" / "reports" / "trending_repost_log.json"
VALID_STATUSES = {
    "pending",
    "success",
    "wont_fix",
    "fb_silent_reject",
    "awaiting_interactive_session",
    "expired_skip",
}
AUTO_EXPIRE_SOURCE_STATUSES = {"awaiting_interactive_session"}
AUTO_EXPIRE_TARGET_STATUS = "wont_fix"
AUTO_EXPIRE_DEFAULT_DAYS = 14


def _warn_mark_fb(message: str) -> None:
    print(f"[mark_fb_post_status] WARN {message}", file=sys.stderr)


def _load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        _warn_mark_fb(
            "JSON read failed; refusing to update "
            f"path={path} error={type(exc).__name__}: {exc}"
        )
        raise
    if not isinstance(data, list):
        _warn_mark_fb(
            "JSON schema invalid; refusing to update "
            f"path={path} expected=list got={type(data).__name__}"
        )
        raise ValueError(f"{path} must contain a JSON list")
    return data


def _write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def update_fb_status(mile_id: str, *, status: str, note: str | None = None) -> dict[str, int | str]:
    updated_feed = 0
    updated_log = 0
    now_iso = _now_iso()

    with shared_state_lock("publisher_feed", storage_dir="storage"):
        feed = _load_json(FEED_PATH, [])
        for item in feed:
            if isinstance(item, dict) and item.get("id") == mile_id:
                item["fb_post_status"] = status
                item["fb_post_status_updated_at"] = now_iso
                if note:
                    item["fb_post_note"] = note
                updated_feed += 1
        _write_json(FEED_PATH, feed)

    with shared_state_lock("fb_pipeline_log", storage_dir="storage"):
        log = _load_json(TRENDING_LOG_PATH, [])
        for item in log:
            if isinstance(item, dict) and item.get("mile_id") == mile_id:
                item["fb_post_status"] = status
                item["fb_post_status_updated_at"] = now_iso
                if note:
                    item["fb_post_note"] = note
                updated_log += 1
        _write_json(TRENDING_LOG_PATH, log)

    return {
        "mile_id": mile_id,
        "status": status,
        "updated_feed": updated_feed,
        "updated_log": updated_log,
    }


def _parse_iso_naive(value: str) -> datetime | None:
    """Parse ISO timestamp tolerating 'Z' suffix and microseconds; return UTC-aware."""
    s = (value or "").strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None  # silent-ok: malformed timestamp → None is the parse contract (caller handles None)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _entry_age_anchor(item: dict) -> datetime | None:
    """Pick the anchor timestamp for TTL: prefer fb_post_status_updated_at,
    fall back to published_at / created_at. This matches when the status
    last changed (or first surfaced) rather than article publish time."""
    for key in ("fb_post_status_updated_at", "fb_post_status_at",
                "published_at", "created_at", "date", "timestamp"):
        anchor = _parse_iso_naive(item.get(key) or "")
        if anchor is not None:
            return anchor
    return None


def auto_expire_stale(
    *, days: int, dry_run: bool = False
) -> dict:
    """Batch flip fb_post_status=awaiting_interactive_session entries older
    than `days` days to wont_fix. Used as a 14-day final TTL after the 48h
    expired_skip pass in audit_fb_pipeline. Rationale: Chrome MCP for the
    personal FB account is not available headlessly; entries older than two
    weeks have effectively been abandoned and should stop polluting the
    dashboard verification_fb_pipeline awaiting count."""
    if days <= 0:
        raise ValueError("--auto-expire days must be > 0")
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    note = (
        f"auto-expired by mark_fb_post_status TTL (>{days}d "
        "Chrome MCP 不可用 + 用戶人工 backlog 過期)"
    )

    expired = []
    skipped_recent = []
    skipped_no_anchor = []
    seen_mile_ids: set[str] = set()

    feed = _load_json(FEED_PATH, [])
    for item in feed:
        if not isinstance(item, dict):
            continue
        status = str(item.get("fb_post_status") or "").strip()
        if status not in AUTO_EXPIRE_SOURCE_STATUSES:
            continue
        mile_id = item.get("mile_id") or item.get("id")
        if not mile_id or mile_id in seen_mile_ids:
            continue
        seen_mile_ids.add(mile_id)
        anchor = _entry_age_anchor(item)
        if anchor is None:
            skipped_no_anchor.append({"mile_id": mile_id, "source": "feed"})
            continue
        age_days = (now - anchor).total_seconds() / 86400.0
        if anchor > cutoff:
            skipped_recent.append({
                "mile_id": mile_id,
                "age_days": round(age_days, 2),
                "source": "feed",
            })
            continue
        expired.append({
            "mile_id": mile_id,
            "age_days": round(age_days, 2),
            "anchor": anchor.isoformat(timespec="seconds"),
            "source": "feed",
        })

    # Also pick up trending_log-only entries (rare; trending posts usually
    # also appear in feed but be safe — same dedup rule applies).
    trending = _load_json(TRENDING_LOG_PATH, [])
    for item in trending:
        if not isinstance(item, dict):
            continue
        status = str(item.get("fb_post_status") or "").strip()
        if status not in AUTO_EXPIRE_SOURCE_STATUSES:
            continue
        mile_id = item.get("mile_id")
        if not mile_id or mile_id in seen_mile_ids:
            continue
        seen_mile_ids.add(mile_id)
        anchor = _entry_age_anchor(item)
        if anchor is None:
            skipped_no_anchor.append({"mile_id": mile_id, "source": "trending_log"})
            continue
        age_days = (now - anchor).total_seconds() / 86400.0
        if anchor > cutoff:
            skipped_recent.append({
                "mile_id": mile_id,
                "age_days": round(age_days, 2),
                "source": "trending_log",
            })
            continue
        expired.append({
            "mile_id": mile_id,
            "age_days": round(age_days, 2),
            "anchor": anchor.isoformat(timespec="seconds"),
            "source": "trending_log",
        })

    if not dry_run:
        for entry in expired:
            try:
                update_fb_status(
                    entry["mile_id"],
                    status=AUTO_EXPIRE_TARGET_STATUS,
                    note=note,
                )
            except Exception as exc:
                _warn_mark_fb(
                    f"auto-expire write failed mile_id={entry['mile_id']} "
                    f"error={type(exc).__name__}: {exc}"
                )
                entry["write_error"] = f"{type(exc).__name__}: {exc}"

    return {
        "mode": "auto_expire",
        "days": days,
        "dry_run": dry_run,
        "cutoff_iso": cutoff.isoformat(timespec="seconds"),
        "expired_count": len(expired),
        "expired": expired,
        "skipped_recent_count": len(skipped_recent),
        "skipped_recent": skipped_recent,
        "skipped_no_anchor_count": len(skipped_no_anchor),
        "skipped_no_anchor": skipped_no_anchor,
        "target_status": AUTO_EXPIRE_TARGET_STATUS,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mile-id")
    parser.add_argument("--status", choices=sorted(VALID_STATUSES))
    parser.add_argument("--note")
    parser.add_argument(
        "--auto-expire",
        type=int,
        nargs="?",
        const=AUTO_EXPIRE_DEFAULT_DAYS,
        default=None,
        metavar="DAYS",
        help=(
            "Batch mode: flip fb_post_status=awaiting_interactive_session "
            f"older than DAYS to wont_fix (default {AUTO_EXPIRE_DEFAULT_DAYS}). "
            "Mutually exclusive with --mile-id/--status."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Auto-expire only: report what would change without writing.",
    )
    args = parser.parse_args()

    if args.auto_expire is not None:
        if args.mile_id or args.status:
            parser.error("--auto-expire cannot be combined with --mile-id/--status")
        try:
            result = auto_expire_stale(days=args.auto_expire, dry_run=args.dry_run)
        except ValueError as exc:
            parser.error(str(exc))
        print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2))
        return 0

    if not args.mile_id or not args.status:
        parser.error("--mile-id and --status are required (or use --auto-expire)")

    result = update_fb_status(args.mile_id, status=args.status, note=args.note)
    if result["updated_feed"] == 0 and result["updated_log"] == 0:
        print(json.dumps({"ok": False, **result}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
