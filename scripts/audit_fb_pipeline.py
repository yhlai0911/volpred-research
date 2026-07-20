#!/usr/bin/env python3
"""FB pipeline audit: detect stale fb_post_status and expire old pending/handoff states.

Cron: every 6h. Alert if stale count >= 2.

2026-06-03 改寫（email-11939 用戶抱怨「FB 一直發不出去」根因追蹤）：
- awaiting_interactive_session 從 TERMINAL set 拿掉 — 它不是 terminal，是「無限期等」
  → 之前 4 篇 5/29-6/01 連續 4 天卡這狀態，audit 0 alert，dashboard 沒抓到
- pending/awaiting >48h 自動降為 expired_skip（時效已過，補發無 ROI）
- 仍 pending/awaiting >24h 計入 stale_pending，觸發 alert
- 12h..24h 進 early-warning 階段，提早 surface 但不回傳 findings exit
"""
from __future__ import annotations
import json, subprocess, sys, time
from pathlib import Path

REPO = Path(__file__).parent.parent
LOG = REPO / "storage" / "reports" / "trending_repost_log.json"
DRAFTS_DIR = REPO / "storage" / "drafts"
# 2026-06-10 process-audit CRITICAL #2: event_article FB statuses live as
# top-level fb_post_status on feed.json entries (publishing.md canonical),
# NOT in trending_repost_log.json — this audit was blind to them (6 awaiting,
# oldest 06-05, past the old auto-expire bar; structural repeat of the
# 2026-06-03 wrong-source incident this script's own docstring records).
FEED = REPO / "storage" / "reports" / "feed.json"
EARLY_WARN_HOURS = 12
STALE_HOURS = 24
AUTO_EXPIRE_HOURS = 48
AUTO_EXPIRE_STATUS_PREFIXES = ("awaiting_", "pending")
TERMINAL_STATUSES = {
    "success",
    "wont_fix",
    "fb_silent_reject",
    "expired_skip",
}
HANDOFF_STATUSES = {
    "awaiting_interactive_session",
}
TERMINAL_OR_HANDOFF_STATUSES = TERMINAL_STATUSES | HANDOFF_STATUSES


def _warn(message: str) -> None:
    print(f"[audit_fb_pipeline] WARN {message}", file=sys.stderr)


def _load_json_list(path: Path, *, source: str) -> list:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except Exception as exc:
        _warn(f"{source} JSON read failed; treating as empty path={path} error={type(exc).__name__}: {exc}")
        return []
    if not isinstance(data, list):
        _warn(f"{source} schema invalid; expected list, got {type(data).__name__} path={path}")
        return []
    return data


def _is_auto_expirable_status(status: str) -> bool:
    s = str(status or "").strip().lower()
    return s not in TERMINAL_STATUSES and s.startswith(AUTO_EXPIRE_STATUS_PREFIXES)


def _auto_expire_stale_pending(data: list, expire_cutoff_iso: str) -> list[dict]:
    """pending*/awaiting* > AUTO_EXPIRE_HOURS → auto-mark expired_skip."""
    expired = []
    for e in data:
        s = str(e.get("fb_post_status", "")).strip().lower()
        if not _is_auto_expirable_status(s):
            continue
        created = e.get("date") or e.get("created_at") or e.get("timestamp", "")
        if not created or created >= expire_cutoff_iso:
            continue
        mile_id = e.get("mile_id")
        if not mile_id:
            continue
        try:
            subprocess.run(
                [
                    "uv", "run", "python", "scripts/mark_fb_post_status.py",
                    "--mile-id", mile_id,
                    "--status", "expired_skip",
                    "--note", (
                        f"auto-expired by audit_fb_pipeline (>{AUTO_EXPIRE_HOURS}h "
                        f"{s}, time-value lost)"
                    ),
                ],
                cwd=REPO, check=True, capture_output=True,
            )
            expired.append({"mile_id": mile_id, "date": created})
        except Exception as exc:
            print(f"auto-expire failed for {mile_id}: {exc}", file=sys.stderr)
    return expired


def _collect_pending_by_age(
    data: list,
    *,
    older_than_iso: str,
    newer_or_equal_iso: str | None = None,
) -> list[dict]:
    """Collect non-terminal FB entries older than a cutoff.

    `newer_or_equal_iso` creates a bounded stage such as 12h..24h early
    warning without double-counting the same items in the stale bucket.
    """
    pending = []
    for e in data:
        s = str(e.get("fb_post_status", "")).strip().lower()
        if s in TERMINAL_STATUSES:
            continue
        created = e.get("date") or e.get("created_at") or e.get("timestamp", "")
        if not created or created >= older_than_iso:
            continue
        if newer_or_equal_iso is not None and created < newer_or_equal_iso:
            continue
        pending.append({
            "mile_id": e.get("mile_id"),
            "fb_post_status": s,
            "date": created,
            "has_draft": bool(e.get("fb_post_draft") or e.get("fb_draft")),
        })
    return pending


def _canonical_fb_draft_path(mile_id: str) -> Path:
    """feed id `mile_08fefa59` → storage/drafts/fb_mile_08fefa59.md.

    Mirror of mark_fb_post_status.canonical_fb_draft_path — audit-side backstop
    for the 2026-07-07 invariant (awaiting handoff must carry a persisted draft).
    """
    mid = str(mile_id or "").strip()
    if not mid.startswith("mile_"):
        mid = f"mile_{mid}"
    return DRAFTS_DIR / f"fb_{mid}.md"


def _scan_missing_drafts(data: list) -> list[dict]:
    """Non-terminal entries whose canonical draft file is absent.

    This catches the failure mode where a writer marked the handoff status but
    never persisted the finished post to storage/drafts/fb_<mile_id>.md, so an
    interactive session has no reference copy to publish from.

    2026-07-20 widened from HANDOFF_STATUSES to all non-terminal statuses.
    The scan used to look only at `awaiting_interactive_session`, but the
    common failure shape is a `pending_*` entry that never got a draft written
    (the publish班 filed a fb_repost_* followup instead of persisting the post).
    Those stayed invisible here and simply aged out at the 48h TTL — a scan of
    feed.json on 2026-07-20 found 23 of 31 `expired_skip` entries had no draft
    that ever existed. A missing draft means the item can never succeed, so it
    should surface immediately regardless of status or age, not expire quietly.
    """
    missing = []
    seen: set[str] = set()
    for e in data:
        s = str(e.get("fb_post_status", "")).strip().lower()
        if not s or s in TERMINAL_STATUSES:
            continue
        mile_id = e.get("mile_id")
        if not mile_id or mile_id in seen:
            continue
        seen.add(mile_id)
        draft_path = _canonical_fb_draft_path(mile_id)
        if not draft_path.exists():
            try:
                expected = str(draft_path.relative_to(REPO))
            except ValueError:
                expected = str(draft_path)  # silent-ok: DRAFTS_DIR patched outside REPO in tests
            missing.append({
                "mile_id": mile_id,
                "fb_post_status": s,
                "date": e.get("date") or e.get("created_at") or e.get("timestamp", ""),
                "expected_draft": expected,
            })
    return missing


def _load_entries() -> list:
    """Merge trending log entries with feed.json top-level fb_post_status
    entries (event_article path). Feed entries are normalized to carry
    mile_id + date keys the rest of this script expects."""
    data: list = _load_json_list(LOG, source="trending_repost_log")
    seen = {e.get("mile_id") for e in data if isinstance(e, dict)}
    feed = _load_json_list(FEED, source="feed")
    for idx, a in enumerate(feed):
        if not isinstance(a, dict):
            _warn(f"feed entry schema invalid; skipping index={idx} type={type(a).__name__}")
            continue
        status = str(a.get("fb_post_status") or "").strip()
        if not status:
            continue
        mid = a.get("mile_id") or a.get("id")
        feed_date = (a.get("fb_post_status_at") or a.get("published_at")
                     or a.get("created_at") or "")
        if mid in seen:
            # 2026-06-28 dual-source-drift fix: feed.json top-level fb_post_status
            # is canonical (per .claude/rules/publishing.md — mark_fb_post_status
            # writes feed.json, often NOT the trending log). The old log-first dedup
            # let a stale log status (e.g. wont_fix) SHADOW a feed 'awaiting', so
            # the auto-expire never saw it and the backlog rotted invisibly. Make
            # feed canonical: override the log entry's status with feed's when they
            # drift, so the age-based auto-expire and stale scan operate on the truth.
            for e in data:
                if e.get("mile_id") != mid:
                    continue
                log_status = str(e.get("fb_post_status") or "").strip()
                if log_status != status:
                    _warn(
                        f"fb_post_status drift mile_id={mid} log={log_status!r} "
                        f"feed={status!r} — feed canonical, reconciling audit view"
                    )
                    e["fb_post_status"] = status
                    e["date"] = feed_date or e.get("date")
                    if a.get("fb_post_draft"):
                        e["fb_post_draft"] = a.get("fb_post_draft")
                break
            continue
        data.append({
            "mile_id": mid,
            "fb_post_status": status,
            "date": feed_date,
            "fb_post_draft": a.get("fb_post_draft"),
            "source": "feed.json",
        })
    return data


def main():
    if not LOG.exists() and not FEED.exists():
        print(json.dumps({"audit": "fb_pipeline", "skip": "no log"}))
        return 0
    data = _load_entries()
    now = time.time()
    early_cutoff_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now - EARLY_WARN_HOURS * 3600))
    stale_cutoff_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now - STALE_HOURS * 3600))
    expire_cutoff_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now - AUTO_EXPIRE_HOURS * 3600))

    # 1) Auto-expire pending/awaiting >48h（不再無限期等）
    auto_expired = _auto_expire_stale_pending(data, expire_cutoff_iso)
    if auto_expired:
        # 重 load（mark_fb_post_status 已寫盤；feed 端 status 也可能已被改）
        data = _load_entries()

    # 2) 掃 24h stale pending（findings exit），以及 12h..24h early warning。
    pending = _collect_pending_by_age(data, older_than_iso=stale_cutoff_iso)
    early_warning = _collect_pending_by_age(
        data,
        older_than_iso=early_cutoff_iso,
        newer_or_equal_iso=stale_cutoff_iso,
    )

    # 3) Invariant: awaiting_interactive_session 但 canonical 完稿檔缺 → 稿遺失風險
    #    （docs/error_log.md 2026-07-07 FB 完稿未持久化）。與年齡無關，只要缺就 warn。
    missing_drafts = _scan_missing_drafts(data)

    report = {
        "audit": "fb_pipeline",
        "early_warn_hours": EARLY_WARN_HOURS,
        "stale_hours": STALE_HOURS,
        "auto_expire_hours": AUTO_EXPIRE_HOURS,
        "early_warning_count": len(early_warning),
        "early_warning": early_warning,
        "stale_pending_count": len(pending),
        "stale_pending": pending,
        "auto_expired_count": len(auto_expired),
        "auto_expired": auto_expired,
        "missing_draft_count": len(missing_drafts),
        "missing_draft": missing_drafts,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))

    if len(early_warning) >= 2 or len(pending) >= 2 or len(auto_expired) >= 1 or missing_drafts:
        sections = []
        if len(early_warning) >= 2:
            sections.append(
                f"## Early warning（>={EARLY_WARN_HOURS}h, <{STALE_HOURS}h）{len(early_warning)} 篇\n"
                + "\n".join(
                    f"- {p['mile_id']} status={p['fb_post_status']} date={p['date']} has_draft={p['has_draft']}"
                    for p in early_warning
                )
            )
        if len(pending) >= 2:
            sections.append(
                f"## Stale pending（>={STALE_HOURS}h）{len(pending)} 篇\n"
                + "\n".join(
                    f"- {p['mile_id']} status={p['fb_post_status']} date={p['date']} has_draft={p['has_draft']}"
                    for p in pending
                )
            )
        if auto_expired:
            sections.append(
                f"## Auto-expired（pending/awaiting >{AUTO_EXPIRE_HOURS}h → expired_skip）{len(auto_expired)} 篇\n"
                + "\n".join(f"- {p['mile_id']} ({p['date']})" for p in auto_expired)
            )
        if missing_drafts:
            sections.append(
                f"## ⚠️ Handoff 缺 canonical 完稿檔 {len(missing_drafts)} 篇\n"
                "awaiting_interactive_session 但 storage/drafts/fb_<mile_id>.md 不存在 —— "
                "互動 session 找不到稿。稿寫手應在 mark_fb_post_status 傳 --draft-file 持久化。\n"
                + "\n".join(
                    f"- {p['mile_id']} status={p['fb_post_status']} 缺檔={p['expected_draft']}"
                    for p in missing_drafts
                )
            )
        sections.append(
            "## 根因\n個人 FB 帳號無 headless API。stale 累積 = 等不到 interactive session。\n"
            "## 永久規則\n見 `docs/fb_pipeline_permanent_fix.md`（個人帳號 + Claude-in-Chrome；Page/Graph API 已撤回）。"
        )
        body = "\n\n".join(sections)
        try:
            from volpred.ops.alerts import send_alert
            level = "warn" if pending or auto_expired or missing_drafts else "info"
            send_alert(
                level=level,
                title=(
                    f"FB pipeline: {len(pending)} stale + {len(early_warning)} early "
                    f"+ {len(auto_expired)} auto-expired"
                ),
                body=body,
            )
        except Exception as e:
            print(f"alert send failed: {e}", file=sys.stderr)
    return 0 if not pending else 1


if __name__ == "__main__":
    sys.exit(main())
