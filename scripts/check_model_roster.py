#!/usr/bin/env python3
"""Model-roster staleness + baseline reporter.

Why: we cannot auto-detect Anthropic model additions/removals from a cron
(no ANTHROPIC_API_KEY; a script also can't read the in-session Agent tool
`model` enum). So detection is a MAIN-THREAD session-start discipline. This
script is the *reminder* half: it prints the current baseline and warns when
the roster hasn't been reconciled against the live tool enum recently, so the
reconcile doesn't silently rely on memory.

Reconcile (main-thread, when this warns or at session start):
  1. Look at the Agent/Workflow tool `model` enum in the current tool schema.
  2. Compare its alias set to available_aliases in config/models.json.
  3. If an alias was added/removed (or the main-loop model id changed), update
     config/models.json + the agent-delegation.md table. WebSearch a NEW alias's
     positioning before assigning a tier — do not guess.
  4. Bump _meta.last_reconciled to today.

Exit code: 0 = fresh; 1 = reconcile due (age > threshold) — lets a cron alert.

Usage: uv run python scripts/check_model_roster.py [--max-age-days 30] [--json]
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

CONFIG = Path(__file__).resolve().parent.parent / "config" / "models.json"

# Model-CHOICE patterns (not pricing-table keys, which look like `"claude-x": {`).
# Catches: `--model claude-...`, `SOME_MODEL = "claude-..."`, router `"opus": "claude-..."`.
_PIN_PATTERNS = [
    re.compile(r'--model\s+["\']?(claude-[\w.\-]+)'),
    re.compile(r'\b[A-Z_]*MODEL[A-Z_]*\s*=\s*["\'](claude-[\w.\-]+)["\']'),
    re.compile(r'["\'](?:opus|sonnet|haiku|fable)["\']\s*:\s*["\'](claude-[\w.\-]+)["\']'),
]
_SCAN_DIRS = ("scripts", "config", "src", ".claude")
_SCAN_SKIP = ("_legacy", "__pycache__", ".git", "node_modules", "check_model_roster.py", "models.json")
_SCAN_EXT = (".py", ".sh", ".json", ".md", ".ts", ".js", ".tsx")


def scan_code_pins(current_ids: set[str]) -> list[dict]:
    """Grep the codebase for hardcoded model-CHOICE IDs that are no longer current.

    Closes the gap the 2026-07-01 token report exposed: config/models.json's
    drift-check compared the tool enum but never scanned cron wrappers /
    model_router for stale pins (hourly-dispatch was hardcoded to opus-4-7)."""
    root = CONFIG.resolve().parent.parent
    findings = []
    for d in _SCAN_DIRS:
        base = root / d
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if not p.is_file() or p.suffix not in _SCAN_EXT:
                continue
            if any(skip in str(p) for skip in _SCAN_SKIP):
                continue
            try:
                lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
            except Exception:
                continue
            for i, line in enumerate(lines, 1):
                for pat in _PIN_PATTERNS:
                    for mid in pat.findall(line):
                        if mid not in current_ids:
                            findings.append({"file": str(p.relative_to(root)), "line": i,
                                             "stale_id": mid, "text": line.strip()[:90]})
    return findings


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-age-days", type=int, default=30)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--today", default=None, help="ISO date override (tests); default = date.today()")
    args = ap.parse_args(argv)

    try:
        cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"model-roster: cannot read {CONFIG}: {e}", file=sys.stderr)
        return 1

    meta = cfg.get("_meta", {})
    last = meta.get("last_reconciled")
    aliases = cfg.get("dispatchable_now", [])
    unavailable = cfg.get("known_but_unavailable", [])
    versions = {k: v.get("display", v.get("id")) if isinstance(v, dict) else v
                for k, v in cfg.get("models", {}).items()}

    today = date.fromisoformat(args.today) if args.today else date.today()
    age_days = None
    stale = False
    if last:
        try:
            age_days = (today - date.fromisoformat(last)).days
            stale = age_days > args.max_age_days
        except ValueError:
            stale = True  # unparseable date -> treat as stale

    report = {
        "dispatchable_now": aliases,
        "known_but_unavailable": unavailable,
        "versions": versions,
        "last_reconciled": last,
        "age_days": age_days,
        "max_age_days": args.max_age_days,
        "reconcile_due": stale,
        "how": "Authoritative availability = Claude Desktop model selector (owner screenshot). Compare vs config/models.json; update config + agent-delegation.md on drift; WebSearch a new model before assigning a tier; route around available=false.",
    }

    current_ids = {v.get("id") for v in cfg.get("models", {}).values()
                   if isinstance(v, dict) and v.get("id")}
    pins = scan_code_pins(current_ids)
    report["stale_code_pins"] = pins

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"model roster: dispatchable={aliases} unavailable={unavailable} versions={versions}")
        print(f"  last_reconciled={last} (age {age_days}d, threshold {args.max_age_days}d)")
        if stale:
            print("  ⚠ RECONCILE DUE — compare live tool `model` enum vs config/models.json; "
                  "update config + agent-delegation.md on drift (WebSearch new aliases first).")
        else:
            print("  ✓ fresh")
        if pins:
            print(f"  ⚠ {len(pins)} STALE MODEL PIN(S) in code (not current per config/models.json):")
            for f in pins:
                print(f"      {f['file']}:{f['line']}  {f['stale_id']}  | {f['text']}")
        else:
            print("  ✓ no stale model pins in code")
    return 1 if (stale or pins) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
