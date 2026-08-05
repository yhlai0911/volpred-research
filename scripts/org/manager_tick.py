#!/usr/bin/env python3
"""Manager tick: zero-cost hard-fact gate deciding whether to wake the manager LLM.

Gate facts (no heuristics — lesson from pregate retirement):
  1. manager/inbox has unprocessed items
  2. any active department inbox has a due/overdue item
  3. manager state.json next_review_due is overdue
  4. (--check-github) open issues labeled dept:* not yet mirrored

All-negative → skip receipt, exit 0, no LLM spawned.
Any-positive → in --shadow mode: would-fire receipt + log only (P1 trial);
               live spawn wiring arrives in a later phase behind --live.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _core import DEFAULT_ORG_ROOT, dept_dir, load_registry, write_receipt  # noqa: E402


def _inbox_items(inbox: Path) -> list[dict]:
    items = []
    if not inbox.is_dir():
        return items
    for path in sorted(inbox.glob("*.json")):
        try:
            items.append(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
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


def evaluate_gate(root: Path, *, check_github: bool = False) -> dict:
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
        reasons.extend(_github_dept_labels())

    return {"fire": bool(reasons), "reasons": reasons}


def _github_dept_labels() -> list[str]:
    import subprocess

    gh = "/opt/homebrew/bin/gh"
    try:
        out = subprocess.run(
            [gh, "issue", "list", "--state", "open", "--json", "number,labels", "--limit", "100"],
            capture_output=True, text=True, timeout=30, check=True,
        ).stdout
        hits = [
            str(i["number"]) for i in json.loads(out)
            if any(lbl["name"].startswith("dept:") for lbl in i.get("labels", []))
        ]
        return [f"github issues with dept:* labels: {', '.join(hits)}"] if hits else []
    except Exception as exc:  # gh missing/offline must not break the gate
        return [f"github check unavailable ({type(exc).__name__}) — treated as no-signal"]


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
        print("[manager_tick] live spawn not wired yet (P1 shadow phase) — receipt recorded only")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
