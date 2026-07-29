"""Burst window — completion-driven continuous dispatch, bounded by a clock.

## Why this exists

The supervisor's normal clock is `7 * * * *`: one fire per hour, plus ASAP
fires on `state.request_fire`. Between a fire finishing at :25 and the next
cron slot at :07 the pool sits idle even with 89 tasks pending. On 2026-07-19
the owner asked for that gap to close for one afternoon (Telegram msg
1012-1014, task `assign_cadde1b5`): "從現在開始到 16:00 持續執行任務不停止",
"16:00 後恢復正常班次".  The original per-completion Telegram side channel was
retired on 2026-07-30: progress delivery now has one structured owner,
``scripts/progress_report.py``.

## The shape of the fix

Two things the owner asked for — no idle gap, and auto-revert — are the same
thing if the window is a stored DEADLINE rather than a mode someone flips:

  * Continuation is **completion-driven, never a sleep loop.** Finishing a task
    is precisely the moment a slot may have freed, so `task_pool_claim complete`
    asks the supervisor for the next fire. No polling, no spin, no new daemon.
  * Auto-revert is **expiry, not cleanup.** Nothing has to run at 16:00 and
    nothing has to be remembered: one second past `until`, every read here
    returns inactive and the hourly cadence is simply what is left. A burst
    that needs a janitor to end is a burst that outlives its window when the
    janitor fails — which is how "temporary" settings become permanent.

Both consumers therefore gate on `active()` alone.

## Guards

* **Quota.** The capacity owner (`scheduler.quota_derate_active`) already knows
  when the weekly window is spent. Bursting into that would burn a ~95K
  cold-load per fire on runs that cannot work, so a quota streak suspends the
  burst — without ending it, because quota resolves on a clock too and the
  window should resume when it does.
* **No notification side effect.** Burst mode requests the next fire only.
  Task completion must not bypass the structured progress-report owner.
* Every read is **fail-open to inactive**: a missing or corrupt window file
  means "no burst", never "burst forever".
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from volpred.ops.diagnostics import warn
from volpred.ops.timestamps import parse_iso_warn

LOG = logging.getLogger(__name__)

REPO = Path(__file__).resolve().parents[3]
BURST_PATH = REPO / "storage" / "ops" / "dispatch_burst.json"
DISPATCH_STATE_PATH = REPO / "storage" / "ops" / "dispatch_state.json"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def read_window(*, path: Path = BURST_PATH) -> dict[str, Any] | None:
    """The stored window, or None when absent/unreadable/malformed."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None  # silent-ok: no burst window is the normal steady state, not an error
    except (OSError, json.JSONDecodeError) as exc:
        warn("dispatch_burst", "burst window unreadable",
             path=str(path), err=f"{type(exc).__name__}: {exc}")
        return None
    if not isinstance(data, dict) or not data.get("until"):
        return None
    return data


def status(*, path: Path = BURST_PATH, state_path: Path = DISPATCH_STATE_PATH,
           now: datetime | None = None) -> dict[str, Any]:
    """Full verdict: active / why not / how long left. Never raises."""
    now = now or _now()
    window = read_window(path=path)
    if window is None:
        return {"active": False, "reason": "no_window"}
    until = parse_iso_warn(str(window.get("until")), tag="burst",
                           field_name="until", fallback=None, site="dispatch_burst")
    if until is None:
        return {"active": False, "reason": "unparseable_until", "window": window}
    if until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)
    if now >= until:
        # Expiry IS the revert — deliberately no file cleanup here, so a failed
        # cleanup can never resurrect the window.
        return {"active": False, "reason": "expired", "until": window.get("until")}
    if _quota_suspended(state_path):
        return {"active": False, "reason": "quota_suspended", "until": window.get("until")}
    return {
        "active": True,
        "until": window.get("until"),
        "reason_opened": window.get("reason"),
        "seconds_left": int((until - now).total_seconds()),
    }


def active(*, path: Path = BURST_PATH, state_path: Path = DISPATCH_STATE_PATH,
           now: datetime | None = None) -> bool:
    return bool(status(path=path, state_path=state_path, now=now)["active"])


def _quota_suspended(state_path: Path) -> bool:
    """Ask the capacity owner whether a quota streak is running.

    Imported lazily: `scripts.dispatch_supervisor.scheduler` pulls in the whole
    supervisor package, which a CLI completing one task has no reason to pay
    for unless a window is actually open. Fail-open — an import problem must
    not silently stop the burst the owner asked for.
    """
    try:
        from scripts.dispatch_supervisor.scheduler import quota_derate_active
    except Exception as exc:  # pragma: no cover - import environment only
        LOG.warning("burst quota check unavailable (%s) — not suspending", exc)
        return False
    return quota_derate_active(state_path)


def open_window(*, until: str, reason: str, path: Path = BURST_PATH,
                opened_by: str | None = None) -> dict[str, Any]:
    """Write the window. `until` must parse, or the burst would never end."""
    parsed = parse_iso_warn(until, tag="burst", field_name="until",
                            fallback=None, site="dispatch_burst.open")
    if parsed is None:
        raise ValueError(f"until must be an ISO datetime, got {until!r}")
    payload = {
        "until": until,
        "reason": reason,
        "opened_at": _now().isoformat(),
        "opened_by": opened_by or "unknown",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    return payload


def close_window(*, path: Path = BURST_PATH) -> bool:
    """Manual early stop. Returns whether a window was there to remove."""
    if not path.exists():
        return False
    path.unlink()
    return True
