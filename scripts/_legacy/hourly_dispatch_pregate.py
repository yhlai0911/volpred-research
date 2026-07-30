"""Retired hourly-dispatch pre-gate evaluator.

This module is retained only so historical evidence and the crosscheck tooling
remain reproducible. H4-4 retired its scheduler authority on 2026-07-30 after
the final production crosscheck found 9 substantive-work false skips among 10
skip candidates (90%, versus the 10% ceiling). ``main()`` is therefore
fail-inert: direct invocation never evaluates, writes state/logs, or returns
the former SKIP/PROCEED exit codes.

The historical evaluator implementation below includes its former readers and
writers for reproducibility. None of them is a runtime dispatch interface.

Signals (all local reads, fail-open):
  A. email backlog      — pending email_reply tasks (PHASE 0, highest priority)
  B. dashboard critical — breach/critical needing triage
  C. high-prio pending  — P1/P2 pending, agentable (not blocked, not main-thread)
  D. backlog cadence     — hours since last hourly substantive dispatch >= N
                           (so the P3 research backlog never starves — Mission #2)
  E. capacity           — are there free dispatch slots (dispatch_slot_budget)?
  F. novelty            — has the actionable state CHANGED since the last fire
                          that proceeded?

Decision:
    proceed = hard_demand or cadence_due or (high_prio and capacity and novelty)

Why E/F exist (2026-07-20, owner directive telegram-1198). A/B/C/D are all
DEMAND signals: "is there work?". At a 60-minute cadence that is the right
question, because an hour reliably changes the answer. At 15 minutes it is the
wrong one — the pool always holds P1/P2, so `high_prio` is true on 100% of
fires (164/164 over the 7 days to 2026-07-20, would_skip=0) and the gate is
structurally incapable of skipping. Firing 4x/hour against an unchanged pool
with no free slot buys nothing and costs ~95K cold-load each time.

E and F ask the sub-hourly questions instead:
  E capacity — CAN another fire add throughput right now, or are all agent
    slots already held? Demand without capacity is not work, it is a queue.
  F novelty  — has anything actionable changed since the last fire proceeded?
    A signature over the agentable P1/P2 ids + compute-followup ids + drought
    flag. Identical signature = the previous fire already saw exactly this
    world; a second look at it is a duplicate cold-load.

Both are VETOES on the `high_prio` path only, never on hard demand:
  - email / critical / compute-followup / publish-drought are main-thread work
    that needs no agent slot, so they proceed regardless (responsiveness
    preserved — the original invariant).
  - `cadence_due` (substantive research starved >= window_hours) also bypasses
    both vetoes, so a static pool can never starve research indefinitely.
  - fail-open throughout: ANY read error -> treat as demand / capacity / novel.
  - historically, every decision was logged to
    storage/logs/hourly_pregate.jsonl (observable).

Direct CLI exit code: 2 = RETIRED. No decision or evidence is written.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from volpred.ops.dispatch_outcomes import SUBSTANTIVE_TASK_TYPES

NEXT_TASKS = ROOT / "storage" / "next_tasks.json"
DASHBOARD = ROOT / "storage" / "ops" / "dashboard_latest.json"
WORK_LOG = ROOT / "storage" / "work_log.json"
COMPUTE_QUEUE = ROOT / "storage" / "ops" / "compute_queue"
LOG = ROOT / "storage" / "logs" / "hourly_pregate.jsonl"
STATE = ROOT / "storage" / "ops" / "pregate_state.json"

# Host wall clock (Asia/Taipei) — the zone of naive timestamps in work_log.
_HOST_TZ = timezone(timedelta(hours=8))

# Substantive (research/content output) task types — used for backlog cadence.
# Ops/overhead types (email_reply, platform_ops, governance) don't count as
# "research got dispatched", so a run of only those still lets cadence fire.
# SINGLE SOURCE: scripts/crosscheck_pregate_outcomes.py imports this set —
# do not fork a second copy (2026-07-10: the two had already drifted on
# daily_digest).
SUBSTANTIVE_TYPES = SUBSTANTIVE_TASK_TYPES


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


def free_slots() -> int:
    """Free agent dispatch slots right now (cap - occupied).

    Delegates to scripts/dispatch_slot_budget.py, which is the SINGLE owner of
    both cap and occupancy — do not re-derive either here (re-deriving them in
    a second place is the exact bug its module docstring is about).
    """
    sys.path.insert(0, str(ROOT / "scripts"))
    from dispatch_slot_budget import budget  # type: ignore
    return int(budget().get("free", 0))


def _actionable_signature(tasks: list) -> str:
    """Stable digest of everything a fire could act on.

    Keyed on IDENTITY, not counts: a pool that swapped one P1 for another has
    genuinely changed even though `pending P1 = 39` did not move. Includes the
    drought flag because repairing a drought is itself dispatchable work whose
    arrival must break a novelty stall.

    Deliberately does NOT include P3+ backlog: those are picked up by the
    cadence signal, which bypasses novelty anyway, so folding them in here
    would just make every fire look novel and re-break the gate.
    """
    sys.path.insert(0, str(ROOT / "scripts"))
    from continue_task_dispatch import detect_block_reason, is_main_thread_only  # type: ignore

    ids = []
    for t in tasks:
        if not isinstance(t, dict) or str(t.get("status", "")).lower() != "pending":
            continue
        try:
            prio = int(t.get("priority", 9))
        except (TypeError, ValueError):
            prio = 9
        if prio > 2 or detect_block_reason(t) or is_main_thread_only(t):
            continue
        ids.append(str(t.get("id", "")))

    if COMPUTE_QUEUE.is_dir():
        for p in sorted(COMPUTE_QUEUE.glob("*.json")):
            try:
                j = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as e:
                _warn("pregate_sig_compute", "compute job unreadable, excluded from signature",
                      job=p.name, err=str(e))
                continue
            if (j.get("status") == "completed" and j.get("claude_followup")
                    and not j.get("followup_dispatched")):
                ids.append(f"compute:{p.stem}")

    # Critical dashboard sections by IDENTITY. `critical` is an incident STATE
    # that persists across fires (unlike email/compute/drought, which are
    # queues a fire actually drains), so "is there a critical?" pins the gate
    # open exactly the way `high_prio` does — on 2026-07-20 the two live
    # criticals were an escalated CI incident owned by the CI watcher and a
    # standing unhandled-alerts count, neither of which a re-fire changes.
    # Naming them here means a NEW critical still breaks novelty and fires
    # immediately, while the same one stops buying a cold-load every 15 min.
    try:
        d = json.loads(DASHBOARD.read_text(encoding="utf-8"))
        crit = sorted(str(s.get("section", "?")) for s in (d.get("sections") or [])
                      if isinstance(s, dict) and s.get("status") == "critical")
        ids.append("crit:" + ",".join(crit))
    except Exception as e:
        _warn("pregate_sig_critical", "dashboard read failed in signature", err=str(e))
        ids.append("crit:unknown")

    try:
        ids.append(f"drought:{int(has_publish_drought())}")
    except Exception as e:
        # unknown -> a value that differs from both 0 and 1, so an unreadable
        # drought state reads as novel (fail-open) rather than as "unchanged".
        _warn("pregate_sig_drought", "drought read failed in signature", err=str(e))
        ids.append("drought:unknown")

    return hashlib.sha256("\n".join(sorted(ids)).encode("utf-8")).hexdigest()[:16]


def _read_last_signature() -> str | None:
    if not STATE.exists():
        return None  # first run — nothing to compare against, and nothing to warn about
    try:
        return json.loads(STATE.read_text(encoding="utf-8")).get("last_proceed_signature")
    except (OSError, json.JSONDecodeError, AttributeError) as e:
        _warn("pregate_sig_state", "state unreadable, treating signature as novel (fail-open)",
              err=str(e))
        return None


def _write_signature(sig: str) -> None:
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(
            {"last_proceed_signature": sig, "ts": _now().isoformat()},
            ensure_ascii=False) + "\n", encoding="utf-8")
    except OSError as e:
        _warn("pregate_state", "cannot persist signature", err=str(e))


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

    # E/F — the sub-hourly signals. Only consulted on the high_prio path.
    _safe("free_slots", free_slots)
    _safe("signature", lambda: _actionable_signature(tasks))
    sig = reasons.get("signature")
    last_sig = _read_last_signature()
    reasons["last_signature"] = last_sig
    # unknown signature (read failed) or no prior state -> novel (fail-open)
    reasons["novel"] = True if (sig is None or last_sig is None) else sig != last_sig
    # unknown free_slots -> capacity available (fail-open)
    reasons["capacity"] = True if reasons.get("free_slots") is None else reasons["free_slots"] > 0

    # Three tiers, by what the signal actually IS:
    #   absolute — a queue this fire drains (email reply, compute followup,
    #     publish drought). Bounded, and if one is still there the fire must
    #     come back. Never vetoed by anything.
    #   critical — an incident STATE that persists whether or not we fire.
    #     Main-thread triage, so capacity is irrelevant, but a REPEAT of the
    #     identical incident set buys nothing -> novelty applies.
    #   high_prio — agent-dispatchable backlog. Needs a free slot AND a changed
    #     world -> both vetoes apply.
    # None (unknown) counts as demand present -> proceed (fail-open).
    _ABSOLUTE_DEMAND = ("email", "compute_followup", "publish_drought")
    absolute = any(reasons.get(k) in (True, None) for k in _ABSOLUTE_DEMAND)
    critical = reasons.get("critical") in (True, None)
    soft_demand = reasons.get("high_prio") in (True, None)

    proceed = bool(
        absolute
        or reasons.get("cadence_due")
        or (critical and reasons["novel"])
        or (soft_demand and reasons["capacity"] and reasons["novel"])
    )
    return {"proceed": proceed, "reasons": reasons, "signature": sig}


def main(argv: list) -> int:
    del argv
    sys.stderr.write(
        "hourly_dispatch_pregate is retired; Operations Core owns dispatch "
        "admission and no pregate decision was emitted.\n"
    )
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
