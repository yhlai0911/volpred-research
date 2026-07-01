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
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NEXT_TASKS = ROOT / "storage" / "next_tasks.json"
DASHBOARD = ROOT / "storage" / "ops" / "dashboard_latest.json"
WORK_LOG = ROOT / "storage" / "work_log.json"
LOG = ROOT / "storage" / "logs" / "hourly_pregate.jsonl"

# Substantive (research/content output) task types — used for backlog cadence.
# Ops/overhead types (email_reply, platform_ops, governance) don't count as
# "research got dispatched", so a run of only those still lets cadence fire.
SUBSTANTIVE_TYPES = {
    "daily_article", "experiment", "paper_body", "paper_review", "paper_decision",
    "event_article", "member_qa", "trending_repost", "strategy_lifecycle",
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
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception as exc:
        logging.debug("pregate: unparseable ISO timestamp %r: %s", s, exc)
        return None


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
    d = json.loads(DASHBOARD.read_text(encoding="utf-8"))
    bc = d.get("breach_count") or d.get("breaches") or 0
    crit = d.get("critical") or d.get("critical_count") or 0
    status = str(d.get("overall_status", "")).lower()
    try:
        if int(bc) > 0 or int(crit) > 0:
            return True
    except (TypeError, ValueError) as exc:
        logging.warning("pregate: unparseable dashboard breach counts, assuming critical: %s", exc)
        return True  # fail-open: unparseable -> assume critical
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
    """Most recent time an hourly fire dispatched a substantive task.

    Preferred source = next_tasks claimed_at (claimed_by startswith 'hourly').
    Fallback = work_log entries. Returns aware datetime or None (unknown)."""
    latest = None
    for t in tasks:
        if not isinstance(t, dict):
            continue
        if t.get("task_type") not in SUBSTANTIVE_TYPES:
            continue
        by = str(t.get("claimed_by", "") or "")
        if not by.startswith("hourly"):
            continue
        ts = _parse_iso(t.get("claimed_at") or t.get("started_at") or t.get("updated_at"))
        if ts and (latest is None or ts > latest):
            latest = ts
    if latest is not None:
        return latest
    # fallback: work_log
    try:
        d = json.loads(WORK_LOG.read_text(encoding="utf-8"))
        items = d if isinstance(d, list) else d.get("entries", d.get("log", []))
        for e in items[-50:]:
            if not isinstance(e, dict):
                continue
            if e.get("task_type") not in SUBSTANTIVE_TYPES:
                continue
            actor = str(e.get("actor", "") or e.get("claimed_by", "") or "")
            if "hourly" not in actor:
                continue
            ts = _parse_iso(e.get("ts") or e.get("timestamp"))
            if ts and (latest is None or ts > latest):
                latest = ts
    except Exception as e:
        _warn("pregate_worklog", "cannot read work_log for cadence", err=str(e))
    return latest


def _log_decision(entry: dict) -> None:
    try:
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

    last = _last_substantive_dispatch(tasks)
    if last is None:
        reasons["cadence_hours_since"] = None
        reasons["cadence_due"] = True  # unknown -> due (research must not starve)
    else:
        hrs = (_now() - last).total_seconds() / 3600.0
        reasons["cadence_hours_since"] = round(hrs, 2)
        reasons["cadence_due"] = hrs >= window_hours

    # None (unknown) counts as demand present -> proceed
    demand = any(reasons.get(k) in (True, None) for k in ("email", "critical", "high_prio"))
    proceed = bool(demand or reasons.get("cadence_due"))
    return {"proceed": proceed, "reasons": reasons}


def main(argv: list) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--window-hours", type=float, default=3.0)
    ap.add_argument("--shadow", action="store_true", help="never skip; only log the would-be decision")
    args = ap.parse_args(argv)

    try:
        d = decide(args.window_hours)
        proceed = d["proceed"]
        reasons = d["reasons"]
    except Exception as e:
        # top-level fail-open: never skip on an unexpected error
        _warn("pregate_fatal", "decide() crashed, fail-open PROCEED", err=str(e))
        _log_decision({"ts": _now().isoformat(), "mode": "shadow" if args.shadow else "real",
                       "decision": "proceed", "reason": "fail_open_exception", "err": str(e)})
        return 1

    would_skip = not proceed
    if args.shadow:
        _log_decision({"ts": _now().isoformat(), "mode": "shadow", "would_skip": would_skip,
                       "window_hours": args.window_hours, "reasons": reasons})
        return 1  # shadow: always proceed (zero behavior change)

    _log_decision({"ts": _now().isoformat(), "mode": "real",
                   "decision": "skip" if would_skip else "proceed",
                   "window_hours": args.window_hours, "reasons": reasons})
    return 0 if would_skip else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
