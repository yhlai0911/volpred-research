#!/usr/bin/env python3
"""Liveness reconciler — queue declaration vs disk vs process reality.

`refactor_plan_ops_master_2026_07.md` §WS-A4. The k1709 lesson: a task can
declare itself `claimed` / `in_progress` while the fire behind it died hours
ago. On 2026-07-20 10:49 the pool declared in_flight=7 with 18/18 worktrees
holding no process at all — seven slots haunted by nobody. Nothing in the
control plane compared the declaration against the two facts that can falsify
it, so the declaration simply stood.

This module is that comparison, run hourly:

  declaration  next_tasks.json rows in {claimed, in_progress}
  disk fact    does the fire's worktree still exist?
  process fact does the fire's pid still exist, and is it still *that* pid?

Detachment requires **both** facts to say dead. That asymmetry is deliberate
and is the whole safety argument:

  - Most supervisor fires never create a worktree (the hourly worker runs in
    the main checkout), so "worktree absent" alone is the normal state of a
    perfectly healthy job. On its own it would re-pend the entire live queue.
  - A worktree that still exists is treated as a veto even when the pid is
    gone: something on disk is still owed a merge decision, and re-pending the
    task would invite a second agent to redo work that may already be
    committed (`feedback_no_research_artifact_loss`).
  - A pid probe that could not be *completed* (`ps` hiccup) is `unknown`, never
    `dead` — the same distinction `procutil.PROBE_FAILED` exists to preserve.

Plus a grace period (default 20 min): a fire that just started has neither
built its worktree nor necessarily attached its pid to dispatch_state yet, and
killing a job at minute two is a worse failure than noticing a zombie at minute
thirty.

Process liveness is NOT re-implemented here. `dispatch_supervisor.procutil` is
the single owner of "is this pid still our pid" (pid-reuse safe via the
`ps -o lstart=` fingerprint captured at spawn) and this module calls it.

Re-pending goes through `task_pool_claim.release_owner_claims()` — the
canonical next_tasks writer (WS-A1 is collapsing direct writers; this must not
add one back). That helper is owner-scoped, which suits us: the owner token is
`<role>-slot-<n>-<job_id>`, i.e. exactly one supervisor fire, so a dead fire
hands back every task it was holding in one locked pass.

Usage:
    uv run python scripts/liveness_reconcile.py              # dry-run (default)
    uv run python scripts/liveness_reconcile.py --apply
    uv run python scripts/liveness_reconcile.py --grace-minutes 30 --apply
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from scripts.dispatch_supervisor import procutil  # noqa: E402

NEXT_TASKS = ROOT / "storage" / "next_tasks.json"
DISPATCH_STATE = ROOT / "storage" / "ops" / "dispatch_state.json"
WORKTREES_DIR = ROOT / ".claude" / "worktrees"
RECEIPTS_DIR = ROOT / "storage" / "ops" / "liveness_receipts"

#: A fire younger than this is never judged. It may not have created its
#: worktree or attached its pid yet, and a false re-pend races a live agent.
DEFAULT_GRACE_MINUTES = 20

IN_FLIGHT_STATUSES = frozenset({"claimed", "in_progress"})

#: Owner tokens minted by `dispatch_supervisor.identity.task_claim_owner()`:
#: `<role>-slot-<n>-<job_id>`. Anything else (interactive sessions, ad-hoc
#: agents, codex-cli) carries no slot/job we could resolve to a pid, so it is
#: reported as unmappable and never re-pended by this reconciler.
OWNER_TOKEN_RE = re.compile(r"^(?P<role>[a-z][a-z-]*?)-(?P<slot>slot-\d+)-(?P<job>[0-9a-f]{8,})$")

#: Same shape daily_checkup's worktree_reconcile dimension looks for.
WORKTREE_REF_RE = re.compile(r"\.claude/worktrees/([A-Za-z0-9._-]+)")

ALIVE = "alive"
DEAD = "dead"
UNKNOWN = "unknown"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _warn(message: str) -> None:
    print(f"[liveness_reconcile] WARN {message}", file=sys.stderr)


def _load_json(path: Path, default: Any) -> Any:
    """Read-only, fail-open. This module never writes canonical state itself."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except (OSError, ValueError) as exc:
        _warn(f"read failed path={path} error={type(exc).__name__}: {exc}")
        return default


def _parse_iso(raw: Any) -> datetime | None:
    if not raw or not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        _warn(f"unparseable timestamp {raw!r}")
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _task_pool_claim() -> ModuleType:
    """Import `scripts/task_pool_claim.py` — the canonical next_tasks writer.

    Loaded by path and cached in sys.modules, the same way `health.py` does it:
    it is a top-level script rather than a package member, and a second module
    object would mean a second (non-shared) view of the file lock.
    """
    cached = sys.modules.get("task_pool_claim")
    if isinstance(cached, ModuleType):
        return cached
    module_path = ROOT / "scripts" / "task_pool_claim.py"
    spec = importlib.util.spec_from_file_location("task_pool_claim", module_path)
    if spec is None or spec.loader is None:  # pragma: no cover - packaging bug
        raise ImportError(f"cannot load task_pool_claim from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["task_pool_claim"] = module
    spec.loader.exec_module(module)
    return module


def parse_owner_token(owner: Any) -> dict[str, str] | None:
    """Split a supervisor claim owner into role / slot / job, or None."""
    match = OWNER_TOKEN_RE.match(str(owner or "").strip())
    if not match:
        return None
    return {
        "role": match.group("role"),
        "slot": match.group("slot"),
        "job_id": match.group("job"),
    }


def process_verdict(job_id: str, state: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """ALIVE / DEAD / UNKNOWN for the fire that minted a claim owner token.

    dispatch_state is the supervisor's own register of fires, so a job_id that
    appears in neither `current_jobs` nor the `completions` ring has no running
    process by construction — that is the aged-out zombie, and it reads DEAD.
    A live row is then checked against the OS through `procutil`, whose
    fingerprint comparison is what makes a recycled pid read DEAD (`mismatch`)
    rather than falsely alive.
    """
    jobs = state.get("current_jobs")
    if not isinstance(jobs, list):
        jobs = []
    current = state.get("current_job")
    rows = [j for j in [*jobs, current] if isinstance(j, dict)]

    for job in rows:
        if str(job.get("job_id") or "") != job_id:
            continue
        pid = int(job.get("pid") or 0)
        identity = procutil.check_identity(pid, job.get("started_wall"))
        evidence = {
            "source": "dispatch_state.current_jobs",
            "pid": pid,
            "pgid": job.get("pgid"),
            "phase": job.get("phase"),
            "started_wall": job.get("started_wall"),
            "identity": identity,
        }
        if identity == procutil.IDENTITY_MATCH:
            return ALIVE, evidence
        if identity in (procutil.IDENTITY_DEAD, procutil.IDENTITY_MISMATCH):
            # mismatch = the pid exists but belongs to somebody else now, i.e.
            # our process is gone. Same verdict, different story.
            return DEAD, evidence
        return UNKNOWN, evidence  # probe failed / no fingerprint: prove nothing

    completions = state.get("completions")
    if isinstance(completions, list):
        for entry in completions:
            if isinstance(entry, dict) and str(entry.get("job_id") or "") == job_id:
                return DEAD, {
                    "source": "dispatch_state.completions",
                    "completed_at": entry.get("completed_at"),
                    "outcome": entry.get("outcome"),
                    "exit_code": entry.get("exit_code"),
                }

    return DEAD, {
        "source": "dispatch_state",
        "detail": "job_id absent from current_jobs and completions ring",
    }


def disk_verdict(
    owner: dict[str, str],
    tasks: list[dict[str, Any]],
    *,
    worktrees_dir: Path | None = None,
) -> tuple[bool, dict[str, Any]]:
    """Does anything on disk still belong to this fire?

    Two ways a fire shows up on disk: the dispatch worktree named after its
    slot + job_id prefix, and any `.claude/worktrees/<name>` path the task text
    itself references (an agent that built its own worktree and wrote the path
    into the task). Either one present means "do not re-pend": there may be
    uncommitted work behind it.
    """
    wt_dir = WORKTREES_DIR if worktrees_dir is None else worktrees_dir
    pattern = f"dispatch-{owner['slot']}-{owner['job_id'][:8]}*"
    matches = sorted(p.name for p in wt_dir.glob(pattern)) if wt_dir.exists() else []

    referenced: set[str] = set()
    for task in tasks:
        referenced.update(WORKTREE_REF_RE.findall(json.dumps(task, ensure_ascii=False)))
    referenced_present = sorted(n for n in referenced if (wt_dir / n).exists())

    evidence = {
        "pattern": pattern,
        "pattern_matches": matches,
        "referenced": sorted(referenced),
        "referenced_present": referenced_present,
    }
    return bool(matches or referenced_present), evidence


def _claim_age_minutes(task: dict[str, Any], now: datetime) -> tuple[float, str | None]:
    """Age of a claim, and which field proved it.

    No usable timestamp at all means nothing can vouch for this claim's youth,
    so it is infinitely old — matching `task_pool_claim.cmd_cleanup`'s
    claimed_at-blindspot fallback (WS-A2a) rather than inventing a second rule.
    """
    for field in ("claimed_at", "started_at", "updated_at", "created_at"):
        parsed = _parse_iso(task.get(field))
        if parsed is not None:
            return (now - parsed).total_seconds() / 60.0, field
    return float("inf"), None


def reconcile(
    *,
    grace_minutes: float = DEFAULT_GRACE_MINUTES,
    apply: bool = False,
    now: datetime | None = None,
    next_tasks_path: Path | None = None,
    dispatch_state_path: Path | None = None,
    worktrees_dir: Path | None = None,
) -> dict[str, Any]:
    """Compare declaration against disk + process; optionally re-pend."""
    now = now or _now()
    tasks_path = NEXT_TASKS if next_tasks_path is None else next_tasks_path
    state_path = DISPATCH_STATE if dispatch_state_path is None else dispatch_state_path

    tasks = _load_json(tasks_path, [])
    if not isinstance(tasks, list):
        _warn(f"next_tasks.json is not a list (path={tasks_path}); nothing to reconcile")
        tasks = []
    state = _load_json(state_path, {})
    if not isinstance(state, dict):
        _warn(f"dispatch_state.json is not an object (path={state_path}); treating as empty")
        state = {}

    in_flight = [
        t for t in tasks
        if isinstance(t, dict) and (t.get("status") or "").lower() in IN_FLIGHT_STATUSES
    ]

    groups: dict[str, list[dict[str, Any]]] = {}
    unmappable: list[dict[str, Any]] = []
    for task in in_flight:
        owner_raw = str(task.get("claimed_by") or "")
        if parse_owner_token(owner_raw) is None:
            unmappable.append({
                "id": task.get("id"),
                "status": task.get("status"),
                "claimed_by": owner_raw or None,
                "reason": "owner_not_supervisor_scoped",
            })
            continue
        groups.setdefault(owner_raw, []).append(task)

    detached: list[dict[str, Any]] = []
    retained: list[dict[str, Any]] = []

    for owner_raw, owner_tasks in sorted(groups.items()):
        owner = parse_owner_token(owner_raw)
        assert owner is not None  # grouping already filtered

        ages = [_claim_age_minutes(t, now) for t in owner_tasks]
        youngest_minutes, age_field = min(ages, key=lambda pair: pair[0])
        proc, proc_evidence = process_verdict(owner["job_id"], state)
        worktree_present, disk_evidence = disk_verdict(
            owner, owner_tasks, worktrees_dir=worktrees_dir
        )

        common = {
            "owner": owner_raw,
            "slot": owner["slot"],
            "job_id": owner["job_id"],
            "task_ids": [t.get("id") for t in owner_tasks],
            "youngest_claim_age_min": (
                None if youngest_minutes == float("inf") else round(youngest_minutes, 1)
            ),
            "age_source": age_field,
            "process": proc,
            "process_evidence": proc_evidence,
            "worktree_present": worktree_present,
            "disk_evidence": disk_evidence,
        }

        # Youngest claim, not oldest: the whole owner is judged as one fire, so
        # a freshly claimed task inside the group protects its siblings too.
        if youngest_minutes < grace_minutes:
            retained.append({**common, "verdict": "in_grace"})
            continue
        if proc != DEAD:
            retained.append({**common, "verdict": f"process_{proc}"})
            continue
        if worktree_present:
            retained.append({**common, "verdict": "worktree_on_disk"})
            continue

        detached.append({
            **common,
            "verdict": "detached",
            "rationale": (
                f"process {proc} ({proc_evidence.get('source')}"
                f"{'/' + str(proc_evidence.get('identity')) if proc_evidence.get('identity') else ''})"
                f" AND no worktree on disk AND claim age "
                f"{common['youngest_claim_age_min']}min >= grace {grace_minutes}min"
            ),
        })

    released: list[dict[str, Any]] = []
    if apply and detached:
        tpc = _task_pool_claim()
        for entry in detached:
            job_short = entry["job_id"][:8]
            try:
                result = tpc.release_owner_claims(
                    [entry["owner"]],
                    reason=f"liveness_reconcile_detached_{job_short}",
                    note=(
                        "liveness_reconcile: 進程與磁碟兩項均證明脫鉤 — "
                        + entry["rationale"]
                    ),
                )
            except Exception as exc:  # noqa: BLE001 — one bad owner must not stop the sweep
                _warn(f"release failed owner={entry['owner']}: {type(exc).__name__}: {exc}")
                entry["released"] = False
                entry["release_error"] = f"{type(exc).__name__}: {exc}"
                continue
            ids = [str(r.get("id") or "") for r in (result.get("released") or [])]
            entry["released"] = True
            entry["released_ids"] = ids
            entry["released_at"] = _now().isoformat(timespec="seconds")
            released.extend(result.get("released") or [])

    report = {
        "ok": True,
        "generated_at": now.isoformat(timespec="seconds"),
        "mode": "apply" if apply else "dry_run",
        "grace_minutes": grace_minutes,
        "in_flight_declared": len(in_flight),
        "owners_examined": len(groups),
        "detached_count": len(detached),
        "detached_task_ids": [tid for e in detached for tid in e["task_ids"]],
        "released_count": len(released),
        "detached": detached,
        "retained": retained,
        "unmappable": unmappable,
    }
    return report


def write_receipt(report: dict[str, Any], *, receipts_dir: Path | None = None) -> Path | None:
    """Persist why a re-pend happened. Apply-mode only, and only if it re-pended.

    A re-pend that leaves no trace is indistinguishable from a task that
    mysteriously reset itself, which is how k1709 stayed unexplained for five
    days. The receipt names the task, the two facts that convicted it, and the
    moment it went back to the pool.

    A dry-run deliberately writes nothing: an inspection command that leaves
    files behind is one an operator stops running.
    """
    if report.get("mode") != "apply" or not report.get("detached"):
        return None
    out_dir = RECEIPTS_DIR if receipts_dir is None else receipts_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = report["generated_at"].replace(":", "").replace("-", "")
    path = out_dir / f"liveness_reconcile_{stamp}.json"
    path.write_text(
        json.dumps(
            {
                "generated_at": report["generated_at"],
                "mode": report["mode"],
                "grace_minutes": report["grace_minutes"],
                "detached": report["detached"],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--apply", action="store_true",
        help="re-pend detached claims (default: dry-run, report only)",
    )
    ap.add_argument(
        "--grace-minutes", type=float, default=DEFAULT_GRACE_MINUTES,
        help=f"claims younger than this are never judged (default {DEFAULT_GRACE_MINUTES})",
    )
    ap.add_argument("--json", action="store_true", help="emit the full report as JSON")
    args = ap.parse_args(argv)

    report = reconcile(grace_minutes=args.grace_minutes, apply=args.apply)
    receipt = write_receipt(report)
    if receipt is not None:
        report["receipt_path"] = str(receipt)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(
            f"[liveness_reconcile] {report['mode']} "
            f"in_flight={report['in_flight_declared']} "
            f"owners={report['owners_examined']} "
            f"detached={report['detached_count']} "
            f"released={report['released_count']} "
            f"unmappable={len(report['unmappable'])}"
        )
        for entry in report["detached"]:
            print(
                f"  DETACHED {','.join(str(t) for t in entry['task_ids'])} "
                f"owner={entry['owner']} — {entry['rationale']}"
            )
        if receipt is not None:
            print(f"  receipt: {receipt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
