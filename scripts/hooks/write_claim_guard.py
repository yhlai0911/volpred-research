#!/usr/bin/env python3
"""PreToolUse(Edit|Write): stop two sessions from editing the same thing at once.

THE BUG CLASS
-------------
2026-08-05: while the main thread was building ``scripts/org/``, a second live
session edited ``scripts/org/org_status.py`` and added ``dept_routing.py``. Both
edits were competent; neither session knew the other existed. That is the same
shape as the boss's standing complaint -- "所有東西擠在一起 結果就是相互干擾" --
and it is not what the existing mechanisms cover:

  * ``git_writer_lock.py`` serializes COMMITS. Two sessions can still edit the
    same file for an hour and then commit sequentially, landing two designs.
  * ``docs/agents/ownership.md`` declares zones in PROSE. Prose does not fire.
  * the org's runner lease covers DEPARTMENTS, not arbitrary file edits.

So the gap is precisely: nothing knows, at write time, that someone else is
already working here. This hook is the enforcement owner for that concern, and
only that one -- ``gate_edit_guard.py`` (evidence preservation) is a different
concern and stays separate.

HOW IT WORKS
------------
Writing auto-claims a scope; you never run a command to take a claim. A claim
held by a DIFFERENT session blocks the write until it expires or is released.

  scope = the department/zone prefix containing the file, when one is declared
          (org registry ``owned_paths`` + the Zone A/B prefixes)
        = otherwise the file itself

File granularity for shared directories is deliberate: claiming all of
``scripts/`` because someone touched one script would block every other worker
and teach people to set the override, and a gate people route around is worse
than no gate.

EXITS -- a block must never be a dead end
-----------------------------------------
The denial names the holder, when the claim expires, and three ways out: wait
for expiry, coordinate with the holder, or override with
``VOLPRED_ALLOW_CONCURRENT_WRITE=1`` (appended to
``storage/ops/write_claim_overrides.jsonl`` -- an untraceable override is
indistinguishable from the gate not existing).

FAIL-OPEN BY CONSTRUCTION
-------------------------
Any unreadable state, odd payload, or unexpected error emits ``{}`` (no-op). A
hook that breaks Edit costs more than a hook that occasionally misses a clash.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

NOOP = "{}"
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
REPO_ROOT = Path(__file__).resolve().parents[2]
# Overridable so tests never write to the live claim state.
CLAIM_DIR = Path(os.environ.get("VOLPRED_WRITE_CLAIM_DIR")
                 or REPO_ROOT / "storage" / "ops" / "path_claims")
OVERRIDE_ENV = "VOLPRED_ALLOW_CONCURRENT_WRITE"
OVERRIDE_LOG = Path(os.environ.get("VOLPRED_WRITE_CLAIM_OVERRIDE_LOG")
                    or REPO_ROOT / "storage" / "ops" / "write_claim_overrides.jsonl")
TTL_SECONDS = int(os.environ.get("VOLPRED_WRITE_CLAIM_TTL", "2700"))  # 45 min

# Declared ownership areas. A clash anywhere inside one of these is a clash with
# the whole area, because that is the unit people actually work on.
ZONE_PREFIXES = (
    "src/volpred/ops/",
    "supabase/migrations/",
    "scripts/dispatch_supervisor/",
    "scripts/org/",
    "scripts/hooks/",
    "paper/",
    ".claude/skills/",
    ".claude/rules/",
    "frontend-v2-fix/src/",
)


def _noop() -> None:
    print(NOOP)
    raise SystemExit(0)


def _now() -> float:
    return time.time()


def _declared_prefixes() -> tuple[str, ...]:
    """Zone prefixes plus every department's declared owned_paths."""
    prefixes = list(ZONE_PREFIXES)
    registry = REPO_ROOT / "storage" / "org" / "registry.json"
    try:
        data = json.loads(registry.read_text(encoding="utf-8"))
        for meta in (data.get("departments") or {}).values():
            if meta.get("status") == "retired":
                continue
            prefixes.extend(p for p in (meta.get("owned_paths") or []) if isinstance(p, str))
    except (OSError, ValueError):  # silent-ok: no org yet is a valid state; zones still apply
        pass
    return tuple(sorted(set(prefixes), key=len, reverse=True))


def scope_for(rel_path: str) -> str:
    """Deepest declared prefix containing the path, else the file itself."""
    for prefix in _declared_prefixes():
        if rel_path.startswith(prefix):
            return prefix
    return rel_path


def _claim_path(scope: str) -> Path:
    return CLAIM_DIR / f"{hashlib.sha256(scope.encode()).hexdigest()[:16]}.json"


def read_claim(scope: str) -> dict | None:
    path = _claim_path(scope)
    try:
        claim = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):  # silent-ok: documented fail-open hook; path_claims.py lists it as unreadable
        return None
    if not isinstance(claim, dict):
        return None
    if float(claim.get("expires_at", 0)) <= _now():
        return None  # expired claims hold nothing
    return claim


def write_claim(scope: str, session: str, rel_path: str) -> None:
    path = _claim_path(scope)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "scope": scope,
        "session_id": session,
        "actor": os.environ.get("VOLPRED_TASK_CLAIM_OWNER") or os.environ.get("USER") or "unknown",
        "last_path": rel_path,
        "taken_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "expires_at": _now() + TTL_SECONDS,
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _record_override(scope: str, holder: dict) -> None:
    try:
        OVERRIDE_LOG.parent.mkdir(parents=True, exist_ok=True)
        with OVERRIDE_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "scope": scope,
                "overridden_holder": holder.get("session_id"),
            }, ensure_ascii=False) + "\n")
    except OSError:
        pass  # silent-ok: failing to log must never turn an allowed edit into a block


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:  # noqa: BLE001
        _noop()

    if payload.get("tool_name") not in EDIT_TOOLS:
        _noop()
    tool_input = payload.get("tool_input") or {}
    raw = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not isinstance(raw, str) or not raw:
        _noop()

    path = Path(raw)
    if not path.is_absolute():
        path = REPO_ROOT / path
    try:
        rel = str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        _noop()  # outside the repo: not our concern

    session = str(payload.get("session_id") or "").strip()
    if not session:
        _noop()  # without an identity every write looks like the same writer

    scope = scope_for(rel)
    holder = read_claim(scope)

    if holder and holder.get("session_id") != session:
        if os.environ.get(OVERRIDE_ENV) == "1":
            _record_override(scope, holder)
            write_claim(scope, session, rel)
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "permissionDecisionReason": (
                    f"{OVERRIDE_ENV}=1 — took {scope} from session "
                    f"{str(holder.get('session_id'))[:8]}; recorded in {OVERRIDE_LOG.name}"
                ),
            }}))
            raise SystemExit(0)

        remaining = int(float(holder.get("expires_at", 0)) - _now())
        reason = (
            f"另一個 session 正在改 `{scope}`（本次目標 {rel}）。\n"
            f"持有者 session {str(holder.get('session_id'))[:8]}（actor={holder.get('actor')}），"
            f"最後動到 {holder.get('last_path')}，於 {holder.get('taken_at')} 取得，"
            f"還有 {max(remaining, 0) // 60} 分鐘到期。\n\n"
            f"兩個 session 同時改同一處，會各自 lock、各自 commit、設計往兩個方向走——"
            f"這正是要防的干擾。三條出路：\n"
            f"  1. 等它到期（{max(remaining, 0) // 60} 分鐘）或請對方先收尾\n"
            f"  2. 改動別的區域，或先 git log 看對方剛做了什麼再接續\n"
            f"  3. 確定對方已停工："
            f"uv run python scripts/path_claims.py release --scope '{scope}'\n"
            f"     真的要硬搶（會留紀錄）：{OVERRIDE_ENV}=1"
        )
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }}))
        raise SystemExit(0)

    write_claim(scope, session, rel)
    _noop()


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        # Never let conflict detection take Edit down with it.
        print(NOOP)
