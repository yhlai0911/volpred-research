"""Loop-health metrics — "is the autonomous loop actually getting better?"

Background (2026-06-29, boss read a "Loop Engineering" tutorial): VolPred's
existing ops monitors answer "is the loop alive?" (freshness / dead-man
switches in `alerts.py`) and "is the infrastructure healthy?" (`health.py`).
Neither answers the loop-engineering question — *is the loop improving?* — i.e.
are the same errors recurring, are tasks succeeding first-try, are corrections
trending down. This module fills that gap.

It is the **fast loop**: a cheap pure-Python aggregation that piggy-backs on the
existing hourly `ops_dashboard` / `check_alerts` fire (no new schedule). The
**slow loop** that mines cross-session failure *patterns* and proposes fixes is
`scripts/dreaming_review.py`, which embeds this snapshot.

Four metrics, all **derived** from existing audit trails (no new stored
counters), each annotated with its signal strength because the underlying data
is heterogeneous:

1. `first_pass_success` — share of recently-succeeded tasks that never went
   through a failed/blocked attempt. `next_tasks.status_history` coverage is low
   (~9/1794), so this is cross-referenced against `work_log` execution traces and
   reports an explicit `coverage`; below the coverage floor it self-labels
   `low_coverage` and does not breach.
2. `task_outcome` — terminal success / fail / blocked mix of recent tasks. Well
   supported (succeeded≫blocked≫failed in the pool), the primary "are we
   shipping" signal.
3. `error_recurrence` — repeated non-zero cron exits + repeated diagnostics tags.
   A signature seen ≥2× in the window is "recurring"; the worst is the seed for a
   dreaming three-strike escalation.
4. `correction_trend` — 4-week slope of correction-driven events (boss/self
   catching content errors). Rising = the loop is regressing on quality.

Design constraints (per `.claude/rules/no-silent-fallback.md`):
- Read-only; never mutates state.
- Every `except` calls `diagnostics.warn(...)` before falling back.
- A sub-metric that can't be computed returns `{"status": "unknown", ...}` and
  never raises — `loop_health_snapshot()` always returns a full dict.
- `NULL` / `MIXED` / `CONDITIONAL_PASS` are research *verdicts*, NOT task
  execution failures, and are deliberately excluded from failure detection.

Shape mirrors `health.py::health_snapshot` / `content_quality.py::
content_quality_snapshot` so `alerts.py` and the dashboard consume it uniformly.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .common import load_json, project_path
from .diagnostics import warn

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------
LOOP_HEALTH_WINDOW_DAYS = 14
CORRECTION_TREND_WEEKS = 4

# Coverage floor for first_pass_success: below this we cannot honestly judge the
# rate (too few succeeded tasks are traceable to an execution history), so the
# metric reports `low_coverage` (info, never a breach) instead of a misleading %.
FIRST_PASS_COVERAGE_FLOOR = 0.30

# first_pass_success thresholds (applied only when coverage >= floor).
FIRST_PASS_OK = 0.80
FIRST_PASS_WARN = 0.60

# task_outcome thresholds (terminal success share of success+fail+blocked).
TASK_SUCCESS_OK = 0.80
TASK_SUCCESS_WARN = 0.60

# error_recurrence thresholds.
RECURRENCE_WARN_COUNT = 5          # any single signature seen >= 5× in window → warn
RECURRENCE_DEGRADING_COUNT = 8     # >= 8× AND spanning >= 3 days → degrading
RECURRENCE_DEGRADING_SPAN_DAYS = 3

# Known self-healing signatures whose recurrence is already structurally tracked
# elsewhere and which must NOT drive a loop-health status escalation (would just
# re-raise noise the existing calibration already handles):
#   - exit142 = hourly_dispatch SIGALRM perl-alarm hang; the NEXT hourly fire
#     self-recovers by design (host_cron_fail treats a lone 142 as WARN, and the
#     pattern is tracked in docs/refactor_plan_hourly_dispatch.md). It is still
#     COUNTED and surfaced (honest recurrence data) but annotated `known`.
_KNOWN_SELF_HEALING_SUFFIXES = (":exit142",)

# A cron-exit failure whose latest fire is exit 0 and whose last failure is older
# than this many hours is RECOVERED (root fixed) — its finding clears immediately
# rather than lingering as a false-critical until the 14d window rolls. 6h ≈ a few
# hourly cycles of success, enough to trust the recovery.
RECOVERY_GRACE_HOURS = 6

# Execution-failure tokens. Substring match, case-insensitive. Deliberately does
# NOT include null/mixed/conditional/partial — those are research/review verdicts,
# not task-execution failures (would otherwise mark honest null results as "fails").
_FAILURE_TOKENS = ("fail", "error", "aborted", "abandon", "terminated")
_BLOCKED_TOKEN = "blocked"
# Success tokens (a terminal status that means the task shipped).
_SUCCESS_TOKENS = ("succeed", "completed", "published", "done")

# Correction-driven event markers in work_log (the loop catching its own errors).
_CORRECTION_OUTCOME_TOKENS = ("correction", "errata", "self_correction", "drift_fix")
_CORRECTION_KEY_FIELDS = ("fixed_in_article", "errors_found", "errata_count", "issues_fixed")

# 2026-07-06 (boss demand "Dreaming再不修好"): cron exit codes that are a BENIGN
# self-reported FINDINGS signal, not an execution failure — mirrors alerts.py
# `_BENIGN_FINDINGS_EXIT_CODES`. exit120 = cron_git_push_backup.sh protectively HELD
# a push because HEAD carries a NEW silent fallback (CI-red protection); the guard
# ran fine and self-sent its own targeted WARN. Counting it as a recurring error
# double-flags noise the push-held alert already tracks, and (worse) makes the job's
# latest fire read non-zero so genuinely-recovered exit1 failures never clear. So we
# neither count exit120 as a failure signature NOR let it block recovery detection.
_BENIGN_CRON_EXIT_CODES = frozenset({"120"})

_CRON_EXIT_RE = re.compile(r"===.*?\bexit\s+(\d+)\b", re.IGNORECASE)
_DISPATCH_OUTCOME_RE = re.compile(r"\bworker returned outcome=(?P<outcome>[a-z_]+)\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _now_utc(now: datetime | None) -> datetime:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc)


def _parse_iso(raw: Any) -> datetime | None:
    if not raw or not isinstance(raw, str):
        return None
    try:
        ts = datetime.fromisoformat(raw.replace("Z", "+00:00").replace("z", "+00:00"))
    except ValueError as exc:
        warn("loop_health_iso", "fromisoformat failed", raw=str(raw)[:60], err=str(exc))
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _has_token(value: Any, tokens: tuple[str, ...]) -> bool:
    s = str(value or "").strip().lower()
    return bool(s) and any(tok in s for tok in tokens)


def _is_execution_failure(value: Any) -> bool:
    return _has_token(value, _FAILURE_TOKENS)


def _is_blocked(value: Any) -> bool:
    return _BLOCKED_TOKEN in str(value or "").strip().lower()


def _is_success(value: Any) -> bool:
    s = str(value or "").strip().lower()
    if not s:
        return False
    return any(tok in s for tok in _SUCCESS_TOKENS) and not _is_execution_failure(s)


def _load_next_tasks(storage_dir: str) -> list[dict[str, Any]]:
    raw = load_json(project_path(storage_dir) / "next_tasks.json", [])
    tasks = raw if isinstance(raw, list) else raw.get("tasks", []) if isinstance(raw, dict) else []
    if not isinstance(tasks, list):
        warn("loop_health_tasks", "next_tasks payload not a list", type=type(tasks).__name__)
        return []
    return [t for t in tasks if isinstance(t, dict)]


def _load_work_log(storage_dir: str) -> list[dict[str, Any]]:
    raw = load_json(project_path(storage_dir) / "work_log.json", [])
    if not isinstance(raw, list):
        warn("loop_health_worklog", "work_log payload not a list", type=type(raw).__name__)
        return []
    return [r for r in raw if isinstance(r, dict)]


def _task_terminal_time(task: dict[str, Any]) -> datetime | None:
    return _parse_iso(task.get("completed_at")) or _parse_iso(task.get("created_at"))


# ---------------------------------------------------------------------------
# 1. first_pass_success
# ---------------------------------------------------------------------------
def compute_first_pass_success(
    storage_dir: str = "storage",
    *,
    now: datetime | None = None,
    window_days: int = LOOP_HEALTH_WINDOW_DAYS,
) -> dict[str, Any]:
    """Share of recently-succeeded tasks that succeeded on the first attempt.

    A succeeded task is *first-pass* if no failure trace exists for it: neither a
    `status_history` transition out of failed/blocked, nor a `work_log` row for
    the same task_id/k_id whose status/outcome/verdict reads as an execution
    failure. Because most tasks lack `status_history`, the rate is reported only
    over the *traceable* subset and carries an explicit `coverage`.
    """
    try:
        cutoff = _now_utc(now) - timedelta(days=window_days)
        tasks = _load_next_tasks(storage_dir)
        work_log = _load_work_log(storage_dir)

        # Index work_log failure traces by task_id and k_id (only rows with a
        # failure marker matter — keeps the index small).
        failed_ids: set[str] = set()
        seen_ids: set[str] = set()
        for row in work_log:
            tid = str(row.get("task_id") or "").strip()
            kid = str(row.get("k_id") or "").strip()
            for ident in (tid, kid):
                if ident:
                    seen_ids.add(ident)
            if any(
                _is_execution_failure(row.get(field))
                for field in ("status", "outcome", "verdict")
            ):
                for ident in (tid, kid):
                    if ident:
                        failed_ids.add(ident)

        succeeded = [
            t for t in tasks
            if _is_success(t.get("status"))
            and (tt := _task_terminal_time(t)) is not None
            and tt >= cutoff
        ]
        total = len(succeeded)
        if total == 0:
            return {
                "status": "unknown",
                "signal": "no_recent_successes",
                "window_days": window_days,
                "total_succeeded": 0,
            }

        traced = 0
        first_pass = 0
        retried = 0
        for t in succeeded:
            tid = str(t.get("id") or "").strip()
            kid = str(t.get("k_id") or "").strip()
            history = t.get("status_history") if isinstance(t.get("status_history"), list) else []
            history_failure = any(
                _is_execution_failure(h.get("from")) or _is_blocked(h.get("from"))
                for h in history
                if isinstance(h, dict)
            )
            traceable = bool(history) or tid in seen_ids or kid in seen_ids
            if not traceable:
                continue
            traced += 1
            had_failure = history_failure or tid in failed_ids or kid in failed_ids
            if had_failure:
                retried += 1
            else:
                first_pass += 1

        coverage = round(traced / total, 3)
        if traced == 0 or coverage < FIRST_PASS_COVERAGE_FLOOR:
            return {
                "status": "low_coverage",
                "signal": "derived_low_coverage",
                "window_days": window_days,
                "total_succeeded": total,
                "traced": traced,
                "coverage": coverage,
                "coverage_floor": FIRST_PASS_COVERAGE_FLOOR,
                "note": (
                    "status_history coverage too low to judge first-pass rate "
                    "honestly; surfacing counts only (info, not a breach)."
                ),
            }

        rate = round(first_pass / traced, 3)
        retry_rate = round(retried / traced, 3)
        if rate >= FIRST_PASS_OK:
            status = "ok"
        elif rate >= FIRST_PASS_WARN:
            status = "warn"
        else:
            status = "degrading"
        return {
            "status": status,
            "signal": "derived",
            "window_days": window_days,
            "total_succeeded": total,
            "traced": traced,
            "coverage": coverage,
            "first_pass": first_pass,
            "retried": retried,
            "first_pass_rate": rate,
            "retry_rate": retry_rate,
        }
    except Exception as exc:  # never let one metric crash the snapshot
        warn("loop_health_first_pass", "compute failed; returning unknown", err=str(exc))
        return {"status": "unknown", "signal": "compute_error", "error": str(exc)}


# ---------------------------------------------------------------------------
# 2. task_outcome
# ---------------------------------------------------------------------------
def compute_task_outcome(
    storage_dir: str = "storage",
    *,
    now: datetime | None = None,
    window_days: int = LOOP_HEALTH_WINDOW_DAYS,
) -> dict[str, Any]:
    """Terminal success / fail / blocked mix of recent tasks (well-supported)."""
    try:
        cutoff = _now_utc(now) - timedelta(days=window_days)
        tasks = _load_next_tasks(storage_dir)
        recent = [t for t in tasks if (tt := _task_terminal_time(t)) is not None and tt >= cutoff]

        success = fail = blocked = other = 0
        for t in recent:
            status = t.get("status")
            if _is_execution_failure(status):
                fail += 1
            elif _is_blocked(status):
                blocked += 1
            elif _is_success(status):
                success += 1
            else:
                other += 1

        denom = success + fail + blocked
        if denom == 0:
            return {
                "status": "unknown",
                "signal": "no_recent_terminal_tasks",
                "window_days": window_days,
                "recent_total": len(recent),
            }
        rate = round(success / denom, 3)
        if rate >= TASK_SUCCESS_OK:
            status = "ok"
        elif rate >= TASK_SUCCESS_WARN:
            status = "warn"
        else:
            status = "degrading"
        return {
            "status": status,
            "signal": "supported",
            "window_days": window_days,
            "success": success,
            "fail": fail,
            "blocked": blocked,
            "other": other,
            "success_rate": rate,
        }
    except Exception as exc:
        warn("loop_health_task_outcome", "compute failed; returning unknown", err=str(exc))
        return {"status": "unknown", "signal": "compute_error", "error": str(exc)}


# ---------------------------------------------------------------------------
# 3. error_recurrence
# ---------------------------------------------------------------------------
def _merge_signature(
    sigs: dict[str, dict[str, Any]],
    sig: str,
    *,
    seen_at: datetime | None,
    source: str,
) -> dict[str, Any]:
    entry = sigs.setdefault(
        sig,
        {"count": 0, "first_seen": None, "last_seen": None, "source": source},
    )
    entry["count"] += 1
    if seen_at is not None:
        if entry["first_seen"] is None or seen_at < _parse_iso(entry["first_seen"]):
            entry["first_seen"] = seen_at.isoformat()
        if entry["last_seen"] is None or seen_at > _parse_iso(entry["last_seen"]):
            entry["last_seen"] = seen_at.isoformat()
    return entry


def _scan_cron_exit_signatures(
    storage_dir: str, cutoff: datetime, now: datetime
) -> dict[str, dict[str, Any]]:
    """signature -> {count, first_seen, last_seen, recovered} for non-zero cron exits.

    A cron log appends a banner per fire; we count non-zero `=== ... exit N ===`
    lines, attributing each to the nearest preceding parseable timestamp so the
    window bound is honoured. Lines without a resolvable timestamp are counted
    (fail-open toward inclusion) but do not move first/last_seen.

    2026-06-29 (boss demand: handle resolved criticals at the architecture level,
    not on a fixed timer): a signature is marked `recovered` when the job's MOST
    RECENT fire is exit 0 AND its last failure is older than RECOVERY_GRACE_HOURS.
    This is RECOVERY-AWARE — a finding clears as soon as the cron actually recovers
    (evidence: recent clean fires), instead of lingering as a false-critical until
    the historical spike ages out of the 14d window (which made the 06-28-fixed
    hourly_dispatch keychain incident still read CRITICAL 35h later).
    """
    sigs: dict[str, dict[str, Any]] = {}
    logs_dir = project_path(storage_dir) / "logs" / "cron"
    if not logs_dir.exists():
        return sigs
    for log_path in sorted(logs_dir.glob("*.log")):
        # audit_* logs use non-zero exit as a FINDINGS signal, not an error.
        if log_path.name.startswith("audit_"):
            continue
        try:
            lines = log_path.read_text(errors="ignore").splitlines()
        except OSError as exc:
            warn("loop_health_cron", "cron log read failed; skipping", path=str(log_path), err=str(exc))
            continue
        last_ts: datetime | None = None
        last_exit_code: str | None = None  # most recent exit banner, ANY code
        log_sigs: list[str] = []
        for ln in lines:
            ts = _parse_banner_ts(ln)
            if ts is not None:
                last_ts = ts
            m = _CRON_EXIT_RE.search(ln)
            if not m:
                continue
            code = m.group(1)
            last_exit_code = code  # track recovery: latest fire's exit code
            if code == "0" or code in _BENIGN_CRON_EXIT_CODES:
                continue
            if last_ts is not None and last_ts < cutoff:
                continue
            sig = f"{log_path.name}:exit{code}"
            _merge_signature(sigs, sig, seen_at=last_ts, source="cron_log")
            if sig not in log_sigs:
                log_sigs.append(sig)
        # Recovery: the job's latest fire succeeded AND its failures are old →
        # the underlying problem is fixed; clear the false-critical immediately.
        if last_exit_code == "0" or last_exit_code in _BENIGN_CRON_EXIT_CODES:
            for sig in log_sigs:
                ls = _parse_iso(sigs[sig].get("last_seen"))
                if ls is not None and (now - ls) >= timedelta(hours=RECOVERY_GRACE_HOURS):
                    sigs[sig]["recovered"] = True
    return sigs


def _normalise_dispatch_outcome(value: Any) -> str:
    s = re.sub(r"[^a-z0-9_]+", "_", str(value or "").strip().lower()).strip("_")
    return s or "non_success"


def _dispatch_signature(outcome: Any, exit_code: Any = None) -> str:
    norm = _normalise_dispatch_outcome(outcome)
    try:
        code = int(exit_code)
    except (TypeError, ValueError):
        code = None
    if code is None:
        return f"dispatch_supervisor:{norm}"
    return f"dispatch_supervisor:{norm}:exit{code}"


def _is_dispatch_success(entry: dict[str, Any]) -> bool:
    outcome = _normalise_dispatch_outcome(entry.get("outcome"))
    try:
        exit_code = int(entry.get("exit_code", 0))
    except (TypeError, ValueError):
        exit_code = 1
    return outcome == "success" and exit_code == 0


def _scan_dispatch_supervisor_completion_signatures(
    storage_dir: str, cutoff: datetime, now: datetime
) -> dict[str, dict[str, Any]]:
    """Count non-success dispatch supervisor completions from structured state.

    `dispatch_state.json` is the canonical structured source for the launchd-era
    hourly dispatcher. It records attempt-level completion outcomes even though
    they no longer appear in `storage/logs/cron/*.log`.
    """
    sigs: dict[str, dict[str, Any]] = {}
    state_path = project_path(storage_dir) / "ops" / "dispatch_state.json"
    if not state_path.exists():
        return sigs
    try:
        raw = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        warn("loop_health_dispatch_state", "dispatch state read failed; skipping", path=str(state_path), err=str(exc))
        return sigs
    completions = raw.get("completions") if isinstance(raw, dict) else None
    if not isinstance(completions, list):
        return sigs

    latest_success_ts: datetime | None = None
    failure_sigs: list[str] = []
    for rec in completions:
        if not isinstance(rec, dict):
            continue
        ts = _parse_iso(rec.get("completed_at")) or _parse_iso(rec.get("fire_at"))
        if _is_dispatch_success(rec):
            if ts is not None and (latest_success_ts is None or ts > latest_success_ts):
                latest_success_ts = ts
            continue
        if ts is not None and ts < cutoff:
            continue
        sig = _dispatch_signature(rec.get("outcome"), rec.get("exit_code"))
        _merge_signature(sigs, sig, seen_at=ts, source="dispatch_state.completions")
        if sig not in failure_sigs:
            failure_sigs.append(sig)

    if latest_success_ts is not None:
        for sig in failure_sigs:
            ls = _parse_iso(sigs[sig].get("last_seen"))
            if ls is not None and latest_success_ts > ls and (now - ls) >= timedelta(hours=RECOVERY_GRACE_HOURS):
                sigs[sig]["recovered"] = True
    return sigs


def _scan_dispatch_supervisor_log_signatures(
    storage_dir: str, cutoff: datetime, now: datetime
) -> dict[str, dict[str, Any]]:
    """Fallback source when dispatch_state has no usable completion failures."""
    sigs: dict[str, dict[str, Any]] = {}
    if "VOLPRED_HOME_DIR" not in os.environ:
        try:
            if project_path(storage_dir).resolve() != project_path("storage").resolve():
                return sigs
        except OSError:
            return sigs
    home_dir = Path(os.environ.get("VOLPRED_HOME_DIR", str(Path.home() / ".volpred")))
    logs_dir = home_dir / "logs"
    if not logs_dir.exists():
        return sigs

    latest_success_ts: datetime | None = None
    failure_sigs: list[str] = []
    for log_path in sorted(logs_dir.glob("dispatch_supervisor*.log")):
        try:
            lines = log_path.read_text(errors="ignore").splitlines()
        except OSError as exc:
            warn(
                "loop_health_dispatch_log",
                "dispatch supervisor log read failed; skipping",
                path=str(log_path),
                err=str(exc),
            )
            continue
        for ln in lines:
            m = _DISPATCH_OUTCOME_RE.search(ln)
            if not m:
                continue
            ts = _parse_banner_ts(ln)
            outcome = _normalise_dispatch_outcome(m.group("outcome"))
            if outcome == "success":
                if ts is not None and (latest_success_ts is None or ts > latest_success_ts):
                    latest_success_ts = ts
                continue
            if ts is not None and ts < cutoff:
                continue
            sig = _dispatch_signature(outcome)
            _merge_signature(sigs, sig, seen_at=ts, source="dispatch_supervisor.log")
            if sig not in failure_sigs:
                failure_sigs.append(sig)

    if latest_success_ts is not None:
        for sig in failure_sigs:
            ls = _parse_iso(sigs[sig].get("last_seen"))
            if ls is not None and latest_success_ts > ls and (now - ls) >= timedelta(hours=RECOVERY_GRACE_HOURS):
                sigs[sig]["recovered"] = True
    return sigs


def _parse_banner_ts(line: str) -> datetime | None:
    """Parse a cron banner timestamp (UTC ISO or local naive) → UTC datetime."""
    m = re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?\+00:00", line)
    if m:
        try:
            return datetime.fromisoformat(m.group(0)).astimezone(timezone.utc)
        except ValueError:
            return None  # silent-ok: best-effort line parser, "no timestamp" is normal flow
    m = re.search(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}", line)
    if m:
        try:
            # Local banners are Asia/Taipei (+08:00); normalise to UTC.
            naive = datetime.strptime(m.group(0).replace("T", " "), "%Y-%m-%d %H:%M:%S")
            return naive.replace(tzinfo=timezone(timedelta(hours=8))).astimezone(timezone.utc)
        except ValueError:
            return None  # silent-ok: best-effort line parser, "no timestamp" is normal flow
    return None


def _scan_diagnostics_signatures(
    storage_dir: str, cutoff: datetime
) -> dict[str, dict[str, Any]]:
    """signature -> {count, first_seen, last_seen} for persisted diagnostics tags.

    Only present when VOLPRED_DIAGNOSTICS_PERSIST=1 has been writing
    storage/logs/diagnostics/<tag>.jsonl; absent dir → empty (fail-open).
    """
    sigs: dict[str, dict[str, Any]] = {}
    diag_dir = project_path(storage_dir) / "logs" / "diagnostics"
    if not diag_dir.exists():
        return sigs
    for jl in sorted(diag_dir.glob("*.jsonl")):
        try:
            lines = jl.read_text(errors="ignore").splitlines()
        except OSError as exc:
            warn("loop_health_diag", "diagnostics read failed; skipping", path=str(jl), err=str(exc))
            continue
        for ln in lines:
            if not ln.strip():
                continue
            try:
                rec = json.loads(ln)
            except ValueError:
                continue  # silent-ok: one malformed jsonl line, dir is best-effort
            if not isinstance(rec, dict):
                continue
            ts = _parse_iso(rec.get("ts"))
            if ts is not None and ts < cutoff:
                continue
            sig = f"diag:{rec.get('tag') or jl.stem}"
            _merge_signature(sigs, sig, seen_at=ts, source="diagnostics")
    return sigs


def compute_error_recurrence(
    storage_dir: str = "storage",
    *,
    now: datetime | None = None,
    window_days: int = LOOP_HEALTH_WINDOW_DAYS,
) -> dict[str, Any]:
    """Repeated failure signatures (cron exits + diagnostics tags) in the window."""
    try:
        current = _now_utc(now)
        cutoff = current - timedelta(days=window_days)
        sigs: dict[str, dict[str, Any]] = {}
        sigs.update(_scan_cron_exit_signatures(storage_dir, cutoff, current))
        dispatch_sigs = _scan_dispatch_supervisor_completion_signatures(storage_dir, cutoff, current)
        if not dispatch_sigs:
            dispatch_sigs = _scan_dispatch_supervisor_log_signatures(storage_dir, cutoff, current)
        sigs.update(dispatch_sigs)
        for sig, entry in _scan_diagnostics_signatures(storage_dir, cutoff).items():
            sigs[sig] = entry

        if not sigs:
            return {
                "status": "ok",
                "signal": "supported",
                "window_days": window_days,
                "distinct_signatures": 0,
                "recurring": 0,
                "recurrence_rate": 0.0,
                "top_recurring": [],
            }

        recurring = [s for s, e in sigs.items() if e["count"] >= 2]
        rate = round(len(recurring) / len(sigs), 3)
        ranked = sorted(sigs.items(), key=lambda kv: kv[1]["count"], reverse=True)

        def _is_known(sig: str) -> bool:
            return any(sig.endswith(sfx) for sfx in _KNOWN_SELF_HEALING_SUFFIXES)

        top = [
            {
                "signature": s,
                **e,
                "span_days": _span_days(e),
                "known": _is_known(s),
                "recovered": bool(e.get("recovered")),
            }
            for s, e in ranked[:5]
        ]

        # Status is driven only by signatures NOT already structurally tracked
        # (self-healing exit142 etc.) and NOT already recovered (root fixed, recent
        # fires clean) — they stay visible but don't re-raise noise / false-critical.
        escalating = [t for t in top if not t["known"] and not t["recovered"]]
        worst = escalating[0] if escalating else None
        status = "ok"
        if worst:
            if worst["count"] >= RECURRENCE_DEGRADING_COUNT and (worst["span_days"] or 0) >= RECURRENCE_DEGRADING_SPAN_DAYS:
                status = "degrading"
            elif worst["count"] >= RECURRENCE_WARN_COUNT:
                status = "warn"
        return {
            "status": status,
            "signal": "supported",
            "window_days": window_days,
            "distinct_signatures": len(sigs),
            "recurring": len(recurring),
            "recurrence_rate": rate,
            "top_recurring": top,
        }
    except Exception as exc:
        warn("loop_health_error_recurrence", "compute failed; returning unknown", err=str(exc))
        return {"status": "unknown", "signal": "compute_error", "error": str(exc)}


def _span_days(entry: dict[str, Any]) -> float | None:
    first = _parse_iso(entry.get("first_seen"))
    last = _parse_iso(entry.get("last_seen"))
    if first is None or last is None:
        return None
    return round((last - first).total_seconds() / 86400.0, 2)


# ---------------------------------------------------------------------------
# 4. correction_trend
# ---------------------------------------------------------------------------
def compute_correction_trend(
    storage_dir: str = "storage",
    *,
    now: datetime | None = None,
    weeks: int = CORRECTION_TREND_WEEKS,
) -> dict[str, Any]:
    """Weekly count of correction-driven events → slope over the last N weeks.

    Sources (all timestamped, so the trend is real, not a single snapshot):
    - work_log rows whose outcome reads as a correction, or that carry a
      correction key field (`fixed_in_article`, `errors_found`, ...).
    The current `content_correction_report.json` HIGH/MEDIUM level is attached as
    a supplementary point-in-time indicator, not part of the slope.
    """
    try:
        now_utc = _now_utc(now)
        work_log = _load_work_log(storage_dir)

        buckets = [0] * weeks  # buckets[0] = most recent week
        for row in work_log:
            ts = _parse_iso(row.get("timestamp")) or _parse_iso(row.get("ts"))
            if ts is None:
                continue
            age_days = (now_utc - ts).total_seconds() / 86400.0
            if age_days < 0 or age_days >= weeks * 7:
                continue
            is_correction = _has_token(row.get("outcome"), _CORRECTION_OUTCOME_TOKENS) or any(
                row.get(field) for field in _CORRECTION_KEY_FIELDS
            )
            if is_correction:
                buckets[int(age_days // 7)] += 1

        # Slope via least-squares over week index (0=oldest .. weeks-1=newest) so
        # a positive slope means corrections are rising (loop regressing).
        ordered = list(reversed(buckets))  # oldest first
        slope = _least_squares_slope(ordered)
        if slope > 0.5:
            trend = "worsening"
        elif slope < -0.5:
            trend = "improving"
        else:
            trend = "flat"

        recent, prev = buckets[0], buckets[1] if weeks > 1 else 0
        status = "warn" if (trend == "worsening" and recent > prev and recent >= 2) else "ok"

        report = load_json(project_path(storage_dir) / "content_correction_report.json", {})
        high = med = None
        if isinstance(report, dict):
            summary = report.get("summary") if isinstance(report.get("summary"), dict) else report
            counts = summary.get("flagged_by_severity") if isinstance(summary, dict) else None
            if isinstance(counts, dict):
                high, med = counts.get("HIGH"), counts.get("MEDIUM")

        return {
            "status": status,
            "signal": "supported",
            "weeks": weeks,
            "weekly_counts_recent_first": buckets,
            "slope_per_week": round(slope, 3),
            "trend": trend,
            "current_correction_report_high": high,
            "current_correction_report_medium": med,
        }
    except Exception as exc:
        warn("loop_health_correction_trend", "compute failed; returning unknown", err=str(exc))
        return {"status": "unknown", "signal": "compute_error", "error": str(exc)}


def _least_squares_slope(ys: list[int]) -> float:
    n = len(ys)
    if n < 2:
        return 0.0
    xs = list(range(n))
    mx = sum(xs) / n
    my = sum(ys) / n
    denom = sum((x - mx) ** 2 for x in xs)
    if denom == 0:
        return 0.0
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denom


# ---------------------------------------------------------------------------
# Aggregate
# ---------------------------------------------------------------------------
_STATUS_RANK = {"degrading": 3, "warn": 2, "ok": 1, "low_coverage": 0, "unknown": 0}


def loop_health_snapshot(
    storage_dir: str = "storage",
    *,
    now: datetime | None = None,
    window_days: int = LOOP_HEALTH_WINDOW_DAYS,
) -> dict[str, Any]:
    """Aggregate the four loop-health metrics into one report.

    Mirrors `health.py::health_snapshot` shape. `overall` is the worst sub-status
    (`unknown`/`low_coverage` never escalate — they're info, not breaches).
    """
    current = _now_utc(now)
    metrics = {
        "first_pass_success": compute_first_pass_success(storage_dir, now=current, window_days=window_days),
        "task_outcome": compute_task_outcome(storage_dir, now=current, window_days=window_days),
        "error_recurrence": compute_error_recurrence(storage_dir, now=current, window_days=window_days),
        "correction_trend": compute_correction_trend(storage_dir, now=current),
    }
    worst = max(
        (_STATUS_RANK.get(m.get("status"), 0) for m in metrics.values()),
        default=0,
    )
    overall = next(
        (name for name, rank in (("degrading", 3), ("warn", 2), ("ok", 1)) if rank == worst),
        "ok",
    )
    return {
        "generated_at": current.isoformat(),
        "window_days": window_days,
        "overall": overall,
        **metrics,
    }
