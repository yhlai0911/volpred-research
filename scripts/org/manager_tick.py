#!/usr/bin/env python3
"""Manager tick: zero-cost hard-fact gate deciding whether to wake the manager LLM.

Gate facts (no heuristics — lesson from pregate retirement):
  1. manager/inbox has unprocessed items
  2. any active department inbox has a due/overdue item
  3. a department declaring a min_cadence is overdue for its round
  4. manager state.json next_review_due is overdue
  5. (--check-github) open issues labeled dept:* not yet mirrored

All-negative → skip receipt, exit 0, no LLM spawned.
Any-positive → wake the coordinator: its live cockpit pane if there is one and it
               is idle, otherwise a headless round under a lease. `--shadow`
               records the decision without waking anyone.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _core import (  # noqa: E402
    DEFAULT_ORG_ROOT,
    runtime_dir,
    REPO_ROOT,
    dept_dir,
    load_registry,
    read_lease,
    write_receipt,
)

HERDR = "/opt/homebrew/bin/herdr"
MANAGER = "manager"
BUSY_STATES = {"working", "blocked"}

# How long a declared cadence may go unserved before the department is due.
CADENCE_SECONDS = {"hourly": 3600, "daily": 86400, "weekly": 604800}
# The coordinator patrols on its own clock even with an empty inbox.
PATROL_SECONDS = 4 * 3600

# Delivery and coordination want different clocks, and they used to share one.
#
# Waking an idle department that is already holding due work costs one herdr
# prompt; waking the coordinator starts an opus/high round. Running both at 30
# minutes meant publications sat 93 minutes on two items so the coordinator
# would not over-fire. The tick now runs every 10 minutes for delivery -- a
# department with an empty inbox is skipped, so the cadence is proportional to
# backlog by construction -- while the coordinator keeps its own floor here.
#
# The floor is deliberately not applied to an out-of-band wake: a boss message
# goes straight to `wake_manager` and must never be told to wait 30 minutes
# (feedback_urgent_bypasses_scheduler_by_design).
MANAGER_MIN_WAKE_INTERVAL_S = 30 * 60


def _inbox_items(inbox: Path) -> list[dict]:
    items = []
    if not inbox.is_dir():
        return items
    for path in sorted(inbox.glob("*.json")):
        try:
            items.append(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):  # silent-ok: malformed items are surfaced by the inbox reader
            items.append({"id": path.name, "corrupt": True})
    return items


def _is_due(item: dict, now: datetime) -> bool:
    due = item.get("due")
    if item.get("priority") == "P1":
        return True
    if not due:
        return True  # undated items are runnable immediately
    try:
        return datetime.fromisoformat(due.replace("Z", "+00:00")) <= now
    except ValueError:
        return True  # silent-ok: malformed due treated as due-now so bad data cannot hide work; item surfaces in the fire reasons


def evaluate_gate(root: Path, *, check_github: bool = False,
                  platform_facts=None) -> dict:
    """`platform_facts` is injectable so tests can isolate org semantics from
    the live platform without monkeypatching subprocess out from under the
    helpers that drive the CLI."""
    now = datetime.now(timezone.utc)
    reasons: list[str] = []

    manager_items = _inbox_items(root / "manager" / "inbox")
    if manager_items:
        reasons.append(f"manager inbox has {len(manager_items)} unprocessed item(s)")

    try:
        registry = load_registry(root)
    except FileNotFoundError:
        return {"fire": False, "reasons": ["org not initialized"], "error": "no_registry"}

    for dept, meta in registry.get("departments", {}).items():
        if meta.get("status") != "active":
            continue
        due = [i for i in _inbox_items(dept_dir(root, dept) / "inbox") if _is_due(i, now)]
        if due:
            reasons.append(f"dept {dept} has {len(due)} due item(s)")

        window = CADENCE_SECONDS.get(str(meta.get("min_cadence") or "").lower())
        if not window:
            continue  # on-demand departments are woken by work, not by the clock
        state_file = dept_dir(root, dept) / "state.json"
        last = None
        if state_file.exists():
            try:
                last = json.loads(state_file.read_text(encoding="utf-8")).get("last_run")
            except (json.JSONDecodeError, OSError) as exc:  # silent-ok: not silent — becomes a wake reason on the next line
                reasons.append(f"dept {dept} state unreadable ({type(exc).__name__})")
                continue
        if not last:
            reasons.append(f"dept {dept} declares {meta['min_cadence']} cadence but has never run")
            continue
        try:
            elapsed = (now - datetime.fromisoformat(str(last).replace("Z", "+00:00"))).total_seconds()
        except ValueError:  # silent-ok: not silent — becomes a wake reason on the next line
            reasons.append(f"dept {dept} last_run unparseable ({last})")
            continue
        if elapsed > window:
            reasons.append(
                f"dept {dept} is {int(elapsed // 3600)}h past its {meta['min_cadence']} cadence"
            )

    state_path = root / "manager" / "state.json"
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            nrd = state.get("next_review_due")
            if nrd and datetime.fromisoformat(nrd.replace("Z", "+00:00")) <= now:
                reasons.append(f"org review overdue (next_review_due={nrd})")
        except (json.JSONDecodeError, ValueError):
            reasons.append("manager state.json unreadable")

    if check_github:
        reasons.extend(_github_dept_labels(root))

    reasons.extend(_unanswered_requests(root, registry))
    reasons.extend((platform_facts or _platform_facts)())
    reasons.extend(_patrol_due(root, now))

    return {"fire": bool(reasons), "reasons": reasons}


def _unanswered_requests(root: Path, registry: dict) -> list[str]:
    """Requests and decisions handled without ever answering the asker.

    Covers both directions: a department that never answers a peer, and the
    coordinator that rules on a department's `decision` item without telling it.
    Either way someone is blocked while believing they are waiting on progress.

    Collaboration only works if help comes back on its own. Archiving a peer's
    request without replying leaves the asker waiting forever and makes the boss
    the transport layer, which is exactly what this org removes.
    """
    replied: set[str] = set()
    open_requests: dict[str, tuple[str, str]] = {}
    for dept in list(registry.get("departments", {})) + [MANAGER]:
        base = (dept_dir(root, dept) if dept != MANAGER else root / MANAGER) / "inbox"
        for folder in (base, base / "_archive"):
            if not folder.is_dir():
                continue
            for path in folder.glob("*.json"):
                try:
                    item = json.loads(path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):  # silent-ok: malformed items are surfaced by the inbox reader
                    continue
                if item.get("reply_to"):
                    replied.add(str(item["reply_to"]))
                elif item.get("kind") in {"request", "decision"} and folder.name == "_archive":
                    open_requests[str(item.get("id"))] = (dept, str(item.get("from")))

    out = []
    for rid, (handler, asker) in open_requests.items():
        if rid not in replied:
            role = "經理" if handler == MANAGER else handler
            out.append(f"{role} 處理完 {asker} 的請求/裁決請示但沒有回覆（{rid[:40]}）")
    return out[:5]


def _platform_facts() -> list[str]:
    """Hard facts from outside the org that are the coordinator's problem.

    An empty org inbox never meant an idle platform: 98 tasks sat pending while
    the gate reported nothing to do. These are counts, not judgements — the
    coordinator still decides what they mean.
    """
    import subprocess

    try:
        raw = subprocess.run(["uv", "run", "python", "scripts/ops_snapshot.py"],
                             cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=60)
        snap = json.loads(raw.stdout)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        return [f"platform snapshot unavailable ({type(exc).__name__}) — 需人工確認"]

    out: list[str] = []
    q = snap.get("queue") or {}
    by_p = q.get("pending_by_priority") or {}
    if by_p.get("p1"):
        out.append(f"canonical 池有 {by_p['p1']} 件 P1 pending")
    if q.get("urgent_pending"):
        out.append(f"{q['urgent_pending']} 件老闆急件 pending")
    if q.get("blocked"):
        out.append(f"{q['blocked']} 件 blocked 待裁決")
    pool = snap.get("content_pool") or {}
    if isinstance(pool.get("draft"), int) and pool["draft"] < 4:
        out.append(f"draft 池只剩 {pool['draft']} 篇（閾值 4）")
    alerts = snap.get("alerts") or {}
    if alerts.get("recent"):
        out.append(f"近期 alert {len(alerts['recent'])} 則未收斂")
    return out


def _patrol_due(root: Path, now: datetime) -> list[str]:
    """The coordinator owes a proactive round even when nothing is queued.

    "沒有待辦" is not a reason to stand down — it is a reason to go looking:
    read the platform, find what is degrading, propose the work nobody filed.
    Time elapsed is a hard fact, so this stays a fact-gate, not a heuristic.
    """
    state = root / "manager" / "state.json"
    last = None
    if state.exists():
        try:
            last = json.loads(state.read_text(encoding="utf-8")).get("last_patrol")
        except (json.JSONDecodeError, OSError) as exc:  # silent-ok: becomes a wake reason below
            return [f"manager state unreadable ({type(exc).__name__})"]
    if not last:
        return ["經理尚未做過主動巡檢"]
    try:
        elapsed = (now - datetime.fromisoformat(str(last).replace("Z", "+00:00"))).total_seconds()
    except ValueError:
        return [f"manager last_patrol unparseable ({last})"]
    if elapsed > PATROL_SECONDS:
        return [f"主動巡檢已逾期 {int(elapsed // 3600)}h（每 {PATROL_SECONDS // 3600}h 一次）"]
    return []


def _github_dept_labels(root: Path) -> list[str]:
    """Only the tracker work the org has not absorbed yet.

    The first version reported every open `dept:*` issue, which would have kept
    the gate firing forever: an issue stays open long after its runtime task is
    done (`issue_disposition=contained` is the default). Intake owns the
    issue→pool mapping, so it is also the only thing that can say what is still
    outstanding — asking it beats keeping a second copy of that judgement here.
    """
    try:
        from org_intake import unmirrored_github_issues  # noqa: PLC0415 — avoids an import cycle

        return unmirrored_github_issues(root)
    except Exception as exc:  # noqa: BLE001 — gh missing/offline must not break the gate
        return [f"github check unavailable ({type(exc).__name__}) — treated as no-signal"]


def wake_departments(root: Path) -> list[dict]:
    """Deliver: wake any department sitting idle on work it already owns.

    This does not bypass the chain of command — the decision was made when the
    item was placed in that inbox. A department idling with an assignment is
    pure waste, and making it depend on the coordinator remembering to nudge it
    turns one missed round into starvation.
    """
    import subprocess

    out: list[dict] = []
    try:
        registry = load_registry(root)
    except FileNotFoundError:
        return out
    now = datetime.now(timezone.utc)

    for dept, meta in sorted(registry.get("departments", {}).items()):
        if meta.get("status") != "active":
            continue
        due = [i for i in _inbox_items(dept_dir(root, dept) / "inbox") if _is_due(i, now)]
        if not due:
            continue
        lease = read_lease(root, dept)
        if not lease or lease.get("runner") != "herdr":
            out.append({"dept": dept, "woken": False, "reason": "無 cockpit pane（headless 部門執行尚未接線）"})
            continue
        try:
            got = subprocess.run([HERDR, "agent", "get", dept],
                                 capture_output=True, text=True, timeout=20)
            status = (json.loads(got.stdout)["result"]["agent"]["agent_status"]
                      if got.returncode == 0 else None)
        except (OSError, subprocess.SubprocessError, ValueError, KeyError) as exc:  # silent-ok: not silent — reported in the returned receipt
            out.append({"dept": dept, "woken": False, "reason": f"狀態讀不到（{type(exc).__name__}）"})
            continue
        if status in BUSY_STATES or status is None:
            out.append({"dept": dept, "woken": False, "reason": f"pane is {status} — 不打斷"})
            continue
        # The drain instruction rides on every wake, not just on attach: the
        # identity prompt is written when the pane is created, so a rule added
        # afterwards would not reach any department already running.
        text = (f"收件匣有 {len(due)} 件到期工作（最高 {due[0].get('priority', 'P3')}）。"
                f"依優先序處理，每張都走完 Session 收尾契約。"
                f"**做完一張直接接下一張**——收件匣清空、或 context／預算不夠完整收尾下一張，"
                f"才是收班條件；不要做完一張就回去等下一班喚醒。")
        sent = subprocess.run([HERDR, "agent", "prompt", dept, text],
                              capture_output=True, text=True, timeout=60)
        out.append({"dept": dept, "woken": sent.returncode == 0,
                    "reason": f"{len(due)} 件到期" if sent.returncode == 0
                              else f"prompt 失敗：{sent.stderr.strip()[:60]}"})
    return out


def _manager_wake_stamp(root: Path) -> Path:
    return runtime_dir(root) / "manager.last_wake.json"


def _too_soon_for_manager(root: Path, now: datetime) -> str | None:
    """Keep the coordinator on a 30-minute floor while delivery ticks faster."""
    path = _manager_wake_stamp(root)
    if not path.exists():
        return None
    try:
        last = json.loads(path.read_text(encoding="utf-8"))["at"]
        elapsed = (now - datetime.fromisoformat(last.replace("Z", "+00:00"))).total_seconds()
    except (json.JSONDecodeError, OSError, KeyError, ValueError) as exc:
        # Fail open, loudly. A throttle that silences the coordinator when its
        # own bookkeeping breaks is indistinguishable from a quiet platform,
        # and the whole org stops while every dashboard reads normal.
        print(f"[manager_tick] wake stamp unreadable ({type(exc).__name__}) — 不節流",
              file=sys.stderr)
        return None
    if elapsed < MANAGER_MIN_WAKE_INTERVAL_S:
        return (f"上次協調 {int(elapsed // 60)} 分鐘前，未達 "
                f"{MANAGER_MIN_WAKE_INTERVAL_S // 60} 分鐘下限（部門投遞不受此限）")
    return None


def _stamp_manager_wake(root: Path, now: datetime) -> None:
    """Record only a wake that actually landed — a refused one is not a round."""
    path = _manager_wake_stamp(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"at": now.strftime("%Y-%m-%dT%H:%M:%SZ")}), encoding="utf-8")


def wake_manager(root: Path, reasons: list[str], *, respect_min_interval: bool = True) -> dict:
    """Wake the coordinator: prefer its live cockpit pane, else run headless.

    Never stacks: a busy pane is left alone (the boss may be talking to it) and
    an existing lease means a round is already in flight.

    `respect_min_interval=False` is for out-of-band wakes (a boss message).
    Those are the one thing that must never queue behind a clock.
    """
    import subprocess

    now = datetime.now(timezone.utc)
    if respect_min_interval:
        too_soon = _too_soon_for_manager(root, now)
        if too_soon:
            return {"woken": False, "reason": too_soon}

    lease = read_lease(root, MANAGER)
    if lease and lease.get("runner") == "headless":
        return {"woken": False, "reason": "a headless round is already in flight"}

    if lease and lease.get("runner") == "herdr":
        try:
            got = subprocess.run([HERDR, "agent", "get", MANAGER],
                                 capture_output=True, text=True, timeout=20)
            status = (json.loads(got.stdout)["result"]["agent"]["agent_status"]
                      if got.returncode == 0 else None)
        except (OSError, subprocess.SubprocessError, ValueError, KeyError) as exc:
            status = None
            note = f"cockpit status unreadable ({type(exc).__name__})"
        else:
            note = None
        if status in BUSY_STATES:
            return {"woken": False, "reason": f"cockpit manager is {status} — 不打斷"}
        if status:
            text = ("開始本輪協調：" + "；".join(reasons[:4]) +
                    "。依優先序處理並派工，判斷記進 bulletin。")
            sent = subprocess.run([HERDR, "agent", "prompt", MANAGER, text],
                                  capture_output=True, text=True, timeout=60)
            if sent.returncode == 0:
                _stamp_manager_wake(root, now)
                return {"woken": True, "via": "cockpit", "pane": lease.get("pane_id")}
            return {"woken": False, "reason": f"cockpit prompt rejected: {sent.stderr.strip()[:80]}"}
        if note:
            return {"woken": False, "reason": note}

    runner = REPO_ROOT / "scripts" / "org" / "manager_run.py"
    try:
        subprocess.Popen(
            ["uv", "run", "python", str(runner), "--root", str(root),
             "--reason", "; ".join(reasons[:4])],
            cwd=str(REPO_ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"woken": False, "reason": f"headless spawn failed ({type(exc).__name__}: {exc})"}
    _stamp_manager_wake(root, now)
    return {"woken": True, "via": "headless"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=DEFAULT_ORG_ROOT)
    parser.add_argument("--shadow", action="store_true", help="P1 trial: receipt+log only, never spawn")
    parser.add_argument("--check-github", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    decision = evaluate_gate(args.root, check_github=args.check_github)
    kind = "manager_would_fire" if decision["fire"] else "manager_skip"
    if args.shadow:
        kind = "shadow_" + kind
    write_receipt(args.root, kind, decision)

    if args.as_json:
        print(json.dumps(decision, ensure_ascii=False))
    else:
        state = "FIRE" if decision["fire"] else "skip"
        print(f"[manager_tick] {state}: " + ("; ".join(decision["reasons"]) or "no runnable signal"))
    if decision["fire"] and not args.shadow:
        result = wake_manager(args.root, decision["reasons"])
        write_receipt(args.root, "manager_wake", result)
        print(f"[manager_tick] wake manager: {json.dumps(result, ensure_ascii=False)}")

    if not args.shadow:
        # Delivery runs regardless of the manager gate: a department holding due
        # work must not wait for the coordinator to have a reason of its own.
        dept_result = wake_departments(args.root)
        if dept_result:
            write_receipt(args.root, "dept_wake", {"departments": dept_result})
            woken = [d["dept"] for d in dept_result if d["woken"]]
            print(f"[manager_tick] wake depts: 喚醒 {len(woken)}/{len(dept_result)}"
                  + (f" → {', '.join(woken)}" if woken else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
