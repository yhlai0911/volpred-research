#!/usr/bin/env python3
"""Hourly-dispatch pre-gate.

Cheaply decide (pure Python, NO LLM, zero token) whether this hourly fire has
work worth the ~95K `claude -p` cold-load. Most hourly fires are stubs (loaded
context, found no high-priority work, exited) yet still pay the ~95K boot cost
(~18/22 fires on 2026-07-01). This gate skips those.

Signals (all local reads, fail-open):
  A. email backlog      — pending email_reply tasks (PHASE 0, highest priority)
  B. dashboard critical — breach/critical needing triage
  C. high-prio pending  — P1/P2 pending, agentable (not blocked, not main-thread)
  D. backlog cadence     — hours since last hourly substantive dispatch >= N
                           (so the P3 research backlog never starves — Mission #2)

Decision: PROCEED if (A or B or C or cadence-due); else SKIP.
  - email / critical are NEVER skipped (responsiveness preserved).
  - fail-open: ANY read error -> PROCEED (never skip on uncertainty).
  - every decision logged to storage/logs/hourly_pregate.jsonl (observable).

Exit code: 0 = SKIP (real mode only), 1 = PROCEED (run claude -p).
  --shadow : never skip (always exit 1); just LOG the would-be decision.
             Run this way for ~1 week to validate that "would-skip" fires truly
             produced nothing, before enabling real skipping.

Usage:
  uv run python scripts/hourly_dispatch_pregate.py --window-hours 3 --shadow
  uv run python scripts/hourly_dispatch_pregate.py --window-hours 3   # real
"""
from __future__ import annotations
import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NEXT_TASKS = ROOT / "storage" / "next_tasks.json"
DASHBOARD = ROOT / "storage" / "ops" / "dashboard_latest.json"
WORK_LOG = ROOT / "storage" / "work_log.json"
COMPUTE_QUEUE = ROOT / "storage" / "ops" / "compute_queue"
LOG = ROOT / "storage" / "logs" / "hourly_pregate.jsonl"

# Host wall clock (Asia/Taipei) — the zone of naive timestamps in work_log.
_HOST_TZ = timezone(timedelta(hours=8))

# Substantive (research/content output) task types — used for backlog cadence.
# Ops/overhead types (email_reply, platform_ops, governance) don't count as
# "research got dispatched", so a run of only those still lets cadence fire.
# SINGLE SOURCE: scripts/crosscheck_pregate_outcomes.py imports this set —
# do not fork a second copy (2026-07-10: the two had already drifted on
# daily_digest).
SUBSTANTIVE_TYPES = {
    "daily_article", "daily_digest", "experiment", "paper_body", "paper_review",
    "paper_decision", "event_article", "member_qa", "trending_repost",
    "strategy_lifecycle",
}


def _warn(tag: str, msg: str, **ctx) -> None:
    try:
        sys.path.insert(0, str(ROOT / "src"))
        from volpred.ops.diagnostics import warn  # type: ignore
        warn(tag, msg, **ctx)
    except Exception:
        sys.stderr.write(f"[pregate] {tag}: {msg} {ctx}\n")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(s):
    """Parse an ISO timestamp to an AWARE datetime, or None.

    work_log carries three shapes in the wild (2026-07-10 survey of the last 60
    rows): `...+00:00` (aware), `...+0800` (aware, no colon), and bare
    `2026-07-08T03:16` (naive). The naive rows come from local
    `datetime.now().isoformat()` calls, so the host wall clock — Asia/Taipei —
    is their true zone. Guessing UTC instead would shift them 8h into the past,
    which only ever makes cadence look MORE stale (fail-open direction), but
    it's still wrong; stamp the real zone.
    """
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception as exc:
        logging.debug("pregate: unparseable ISO timestamp %r: %s", s, exc)
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=_HOST_TZ)


def _load_tasks() -> list:
    d = json.loads(NEXT_TASKS.read_text(encoding="utf-8"))
    return d if isinstance(d, list) else d.get("tasks", [])


def has_email_backlog(tasks: list) -> bool:
    for t in tasks:
        if not isinstance(t, dict):
            continue
        if t.get("task_type") == "email_reply" and str(t.get("status", "")).lower() in ("pending", "queued", ""):
            return True
    return False


def has_critical() -> bool:
    """True only when the dashboard has a genuine CRITICAL-level section.

    2026-07-01 bug fix: this previously read `breach_count`/`breaches`/`critical`/
    `critical_count` — none of which exist in scripts/ops_dashboard.py's real
    payload (it emits `section_breaches`/`section_critical`/`overall_status`
    only). Those reads always evaluated to 0, so the function silently fell
    through to `overall_status not in (ok, healthy, green, "")`. But
    `overall_status` is "warn" almost continuously (loop_health soft-tracking,
    reference-only host_cron_fail false-positive, routine content-quality
    warns) — see scripts/ops_dashboard.py's own comment that loop_health
    "degrading is surfaced as warn (not critical)". So this signal was
    effectively always True regardless of real urgency, defeating the gate:
    shadow-mode data from the first deploy (16:07/17:07 CST fires) showed
    critical=True on both, driven entirely by this dead-field fallback.
    Fix: use `section_critical` (count of sections whose status is literally
    "critical" — real triage-worthy breaches only; see ops_dashboard.py
    `critical = sum(1 for s in out if s["status"] == "critical")`). Routine
    warns are already covered by the email/high_prio/cadence signals, so they
    don't need to force PROCEED via this path too.
    """
    d = json.loads(DASHBOARD.read_text(encoding="utf-8"))
    section_critical = d.get("section_critical")
    if section_critical is not None:
        try:
            return int(section_critical) > 0
        except (TypeError, ValueError) as exc:
            logging.warning("pregate: unparseable section_critical=%r, assuming critical: %s", section_critical, exc)
            return True  # fail-open: unparseable -> assume critical
    # Fallback for an older/missing dashboard schema without section_critical.
    status = str(d.get("overall_status", "")).lower()
    if status and status not in ("ok", "healthy", "green", ""):
        return True
    return False


def has_high_prio(tasks: list) -> bool:
    """P1/P2 pending that is agentable (not blocked, not main-thread-only).

    Reuses the canonical dispatcher filters so this matches what
    continue_task_dispatch would actually consider dispatchable.
    """
    sys.path.insert(0, str(ROOT / "scripts"))
    from continue_task_dispatch import detect_block_reason, is_main_thread_only  # type: ignore
    for t in tasks:
        if not isinstance(t, dict) or str(t.get("status", "")).lower() != "pending":
            continue
        try:
            prio = int(t.get("priority", 9))
        except (TypeError, ValueError):
            prio = 9
        if prio > 2:
            continue
        if detect_block_reason(t):
            continue
        if is_main_thread_only(t):
            continue
        return True
    return False


def _last_substantive_dispatch(tasks: list):
    """Most recent time ANY actor completed substantive (research/content) work.

    2026-07-10 root-cause fix. The old version only counted tasks whose
    `claimed_by` startswith 'hourly' (primary) or work_log actors containing
    'hourly' (fallback). No claimer in this repo is ever named that way — the
    real owners are `codex-cli` (535 claims), `codex-vscode`, `interactive-
    claude`, `telegram-responder`, `main-session`… — so the primary source
    always returned None and the fallback almost always did too. Result:
    `cadence_due` was True on 20/20 supervisor fires and the gate could never
    skip anything. The gate was wired but structurally a no-op.

    The cadence signal's real question is "has research starved?" — NOT "did
    an hourly fire specifically do it". Work done by a parallel interactive or
    codex session feeds the same missions, so it must reset the clock. Hence:
    actor-agnostic, and keyed on COMPLETION (a claim that never finished is
    not output).

    Returns aware datetime or None (unknown → treated as due, research must
    never starve on a read failure).
    """
    latest = None
    for t in tasks:
        if not isinstance(t, dict):
            continue
        if t.get("task_type") not in SUBSTANTIVE_TYPES:
            continue
        if str(t.get("status", "")).lower() != "succeeded":
            continue
        ts = _parse_iso(t.get("completed_at"))
        if ts is None:
            # status_history is the canonical transition ledger (task_pool_claim)
            for h in reversed(t.get("status_history") or []):
                if isinstance(h, dict) and str(h.get("to", "")).lower() == "succeeded":
                    ts = _parse_iso(h.get("ts"))
                    break
        if ts and (latest is None or ts > latest):
            latest = ts

    # work_log is the second ledger (some substantive work is logged there
    # without a next_tasks row — e.g. main-thread event articles).
    try:
        d = json.loads(WORK_LOG.read_text(encoding="utf-8"))
        items = d if isinstance(d, list) else d.get("entries", d.get("log", []))
        for e in items[-100:]:
            if not isinstance(e, dict):
                continue
            if e.get("task_type") not in SUBSTANTIVE_TYPES:
                continue
            outcome = str(e.get("outcome", "") or "").lower()
            if outcome and outcome not in ("succeeded", "success", "done", "completed"):
                continue
            ts = _parse_iso(e.get("ts") or e.get("timestamp"))
            if ts and (latest is None or ts > latest):
                latest = ts
    except Exception as e:
        _warn("pregate_worklog", "cannot read work_log for cadence", err=str(e))
    return latest


def has_compute_followup() -> bool:
    """True when a finished compute job still awaits its LLM interpretation.

    2026-07-10: the hourly fire's PHASE 0.5 dispatches these followups. Without
    this signal an enforced skip would strand completed heavy-compute artifacts
    (the executor-advisor advisor call would simply never happen).
    """
    if not COMPUTE_QUEUE.is_dir():
        return False
    for p in COMPUTE_QUEUE.glob("*.json"):
        try:
            j = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logging.warning("pregate: unreadable compute job %s: %s", p.name, exc)
            continue  # a single bad file must not mask other pending followups
        if (j.get("status") == "completed" and j.get("claude_followup")
                and not j.get("followup_dispatched")):
            return True
    return False


def has_publish_drought() -> bool:
    """True when reader-facing publishing has fallen behind its cadence.

    Reuses the canonical detector owned by volpred.ops.alerts (single source —
    do not reimplement the gap/active-window rules here). The hourly fire is
    what repairs a drought, so a drought must never be skipped.
    """
    sys.path.insert(0, str(ROOT / "src"))
    from volpred.ops.alerts import _parse_publishing_freshness_state  # type: ignore

    state = _parse_publishing_freshness_state(str(ROOT / "storage"), _now())
    return bool(state.get("breached"))


def _log_decision(entry: dict) -> None:
    try:
        # forensic attribution（2026-07-10）：invoker 是自報值可被誤標（13:44/13:50 兩筆
        # 手動跑卻標 supervisor 的實例）；pid/ppid 是 OS 事實 — daemon 生的 pregate 其
        # ppid == supervisor pid，crosscheck 可機械驗證 entry 真偽。
        entry.setdefault("pid", os.getpid())
        entry.setdefault("ppid", os.getppid())
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        _warn("pregate_log", "cannot write decision log", err=str(e))


def decide(window_hours: float) -> dict:
    """Return {proceed: bool, reasons: {...}}. Fail-open: any error -> proceed."""
    reasons: dict = {}
    tasks = _load_tasks()

    def _safe(name, fn):
        try:
            reasons[name] = fn()
        except Exception as e:
            _warn(f"pregate_{name}", "signal read failed, fail-open", err=str(e))
            reasons[name] = None  # None = unknown -> treated as demand (proceed)

    _safe("email", lambda: has_email_backlog(tasks))
    _safe("critical", has_critical)
    _safe("high_prio", lambda: has_high_prio(tasks))
    # 2026-07-10: the hourly fire also repairs droughts and dispatches compute
    # followups. Skipping a fire that owed either of those was a silent stall.
    _safe("compute_followup", has_compute_followup)
    _safe("publish_drought", has_publish_drought)

    last = _last_substantive_dispatch(tasks)
    if last is None:
        reasons["cadence_hours_since"] = None
        reasons["cadence_due"] = True  # unknown -> due (research must not starve)
    else:
        hrs = (_now() - last).total_seconds() / 3600.0
        reasons["cadence_hours_since"] = round(hrs, 2)
        if hrs < 0:
            # Future timestamp = clock skew or a mis-zoned row. It would fake a
            # "just did work" reading and manufacture a skip. Refuse it.
            _warn("pregate_cadence", "future last-completion timestamp, fail-open",
                  last=last.isoformat(), hours=round(hrs, 2))
            reasons["cadence_due"] = True
        else:
            reasons["cadence_due"] = hrs >= window_hours

    # None (unknown) counts as demand present -> proceed
    _DEMAND_SIGNALS = ("email", "critical", "high_prio", "compute_followup", "publish_drought")
    demand = any(reasons.get(k) in (True, None) for k in _DEMAND_SIGNALS)
    proceed = bool(demand or reasons.get("cadence_due"))
    return {"proceed": proceed, "reasons": reasons}


def main(argv: list) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--window-hours", type=float, default=3.0)
    ap.add_argument("--shadow", action="store_true", help="never skip; only log the would-be decision")
    # 2026-07-10 歸因欄位：不帶 --invoker 的呼叫（手動 / 測試 / 不明來源）記 "manual"，
    # supervisor 呼叫記 "supervisor" — skip-vs-產出交叉核對只採 supervisor entries，
    # 解決 13:34:58 三筆一秒內不明來源 entries 污染觀察資料的問題。
    ap.add_argument("--invoker", default="manual",
                    help="who invoked this run (supervisor|shell|manual|test); logged for attribution")
    args = ap.parse_args(argv)

    try:
        d = decide(args.window_hours)
        proceed = d["proceed"]
        reasons = d["reasons"]
    except Exception as e:
        # top-level fail-open: never skip on an unexpected error
        _warn("pregate_fatal", "decide() crashed, fail-open PROCEED", err=str(e))
        _log_decision({"ts": _now().isoformat(), "mode": "shadow" if args.shadow else "real",
                       "invoker": args.invoker,
                       "decision": "proceed", "reason": "fail_open_exception", "err": str(e)})
        return 1

    would_skip = not proceed
    if args.shadow:
        _log_decision({"ts": _now().isoformat(), "mode": "shadow", "invoker": args.invoker,
                       "would_skip": would_skip,
                       "window_hours": args.window_hours, "reasons": reasons})
        return 1  # shadow: always proceed (zero behavior change)

    _log_decision({"ts": _now().isoformat(), "mode": "real", "invoker": args.invoker,
                   "decision": "skip" if would_skip else "proceed",
                   "window_hours": args.window_hours, "reasons": reasons})
    return 0 if would_skip else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
