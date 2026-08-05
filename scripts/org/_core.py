"""Shared primitives for the disk-persisted org layer (storage/org).

Design contract (docs/agents/ownership.md Zone D):
- The org's entire state (registry, charters, memories, inboxes, journals)
  lives in git-tracked files so that session restart / reboot / host
  migration recovers the whole organization from a checkout.
- Ephemeral receipts live in receipts/ (gitignored, rotated).
- Everything here is stdlib-only and side-effect free except explicit writes.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ORG_ROOT = REPO_ROOT / "storage" / "org"

DEPT_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")

# Paths no department may claim: Zone A (Codex-owned) and core Zone B
# (main-thread-owned) prefixes from docs/agents/ownership.md.
RESERVED_PATH_PREFIXES = (
    "src/volpred/ops/",
    "supabase/migrations/",
    "scripts/dispatch_supervisor/",
    "paper/",
    ".claude/skills/",
    "storage/org/registry.json",
    "storage/org/manager/",
)

REGISTRY_VERSION = 1


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def registry_path(root: Path) -> Path:
    return root / "registry.json"


def load_registry(root: Path) -> dict:
    path = registry_path(root)
    if not path.exists():
        raise FileNotFoundError(
            f"org registry not found at {path}; run `org_admin.py init` first"
        )
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def save_registry(root: Path, registry: dict) -> None:
    registry["updated_at"] = now_iso()
    atomic_write_json(registry_path(root), registry)


def bulletin_append(root: Path, actor: str, text: str) -> Path:
    """Append one decision record to the current month's bulletin (Zone C rules)."""
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    path = root / "bulletin" / f"{month}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    line = f"- {now_iso()} **{actor}**: {text}\n"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line)
    return path


def write_receipt(root: Path, kind: str, payload: dict) -> Path:
    """Ephemeral spawn/skip receipt (gitignored)."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = root / "receipts" / f"{stamp}_{kind}.json"
    payload = dict(payload)
    payload.setdefault("kind", kind)
    payload.setdefault("at", now_iso())
    atomic_write_json(path, payload)
    return path


def dept_dir(root: Path, name: str) -> Path:
    return root / "departments" / name


# --- runtime state (ephemeral, gitignored) --------------------------------
# The org's identity lives in git; who is *currently running* a department does
# not. A lease names the live runner so the headless dispatch path and a Herdr
# cockpit pane can never work the same inbox at the same time.

def runtime_dir(root: Path) -> Path:
    return root / "runtime"


def lease_path(root: Path, dept: str) -> Path:
    return runtime_dir(root) / f"{dept}.lease.json"


def brief_path(root: Path, dept: str) -> Path:
    return runtime_dir(root) / f"{dept}.brief.md"


def read_lease(root: Path, dept: str) -> dict | None:
    path = lease_path(root, dept)
    if not path.exists():
        return None
    try:
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        # A lease we cannot read must not silently read as "free" — that is
        # exactly the double-execution this file exists to prevent.
        return {"runner": "unreadable", "error": f"{type(exc).__name__}: {exc}"}


def write_lease(root: Path, dept: str, payload: dict) -> Path:
    payload = dict(payload)
    payload.setdefault("since", now_iso())
    path = lease_path(root, dept)
    atomic_write_json(path, payload)
    return path


def clear_lease(root: Path, dept: str) -> bool:
    path = lease_path(root, dept)
    if path.exists():
        path.unlink()
        return True
    return False


def inbox_items(root: Path, dept: str) -> list[dict]:
    inbox = dept_dir(root, dept) / "inbox"
    items: list[dict] = []
    if not inbox.is_dir():
        return items
    for path in sorted(inbox.glob("*.json")):
        try:
            with path.open(encoding="utf-8") as fh:
                items.append(json.load(fh))
        except (json.JSONDecodeError, OSError) as exc:
            items.append({"id": path.name, "task": f"⚠️ 無法解析（{type(exc).__name__}）", "priority": "P1"})
    items.sort(key=lambda i: (str(i.get("priority") or "P3"), str(i.get("created_at") or "")))
    return items


def build_brief(root: Path, dept: str) -> str:
    """The rehydration brief: how an ephemeral session becomes this department.

    Single source for both runners — a headless dispatch session and a Herdr
    cockpit pane must be given the identical identity, or the two surfaces drift.
    """
    ddir = dept_dir(root, dept)
    registry = load_registry(root)
    meta = registry.get("departments", {}).get(dept, {})
    title = meta.get("title") or dept

    def _read(path: Path, limit: int | None = None) -> str:
        if not path.exists():
            return "（無）"
        text = path.read_text(encoding="utf-8").strip()
        if limit:
            lines = text.splitlines()
            text = "\n".join(lines[-limit:])
        return text or "（無）"

    items = inbox_items(root, dept)
    if items:
        rendered = []
        for i in items:
            due = f" due={i['due']}" if i.get("due") else ""
            refs = f" refs={', '.join(i['refs'])}" if i.get("refs") else ""
            issue = f" issue=#{i['issue']}" if i.get("issue") else ""
            rendered.append(f"- [{i.get('priority', 'P3')}] `{i.get('id')}` {i.get('task')}{due}{refs}{issue}")
        inbox_block = "\n".join(rendered)
    else:
        inbox_block = "（收件匣是空的——沒有待辦就不要製造工作，回報 outcome=noop 後結束）"

    return f"""你現在是 VolPred 平台的**{title}**（部門代號 `{dept}`）。

這是一個常駐部門的身分；你這個 session 是它的執行體。你的身分、記憶與工作狀態
全部存在磁碟上（`{ddir}`），所以 session 結束不等於部門消失——下一個 session 會從
同一份檔案接續。

## 你的章程（職責、KPI、邊界、收尾契約）

{_read(ddir / "charter.md")}

## 你的私有記憶

{_read(ddir / "memory" / "notes.md")}

## 最近工作日誌（最後 20 行）

{_read(ddir / "journal.md", limit=20)}

## 你的收件匣（{len(items)} 件）

{inbox_block}

## 現在該做什麼

處理收件匣中優先序最高、已到期的工作項。**結束前必須執行章程末段的「Session 收尾契約」**
（寫 journal、更新 state.json、歸檔已處理項、回報給運營經理、經 git_writer_lock 提交、
清理自己的 worktree）。少做一步，下一個接手的 session 就會失去脈絡。
"""


def validate_dept_name(name: str) -> None:
    if not DEPT_NAME_RE.match(name):
        raise ValueError(
            f"invalid department name {name!r}: must match {DEPT_NAME_RE.pattern}"
        )


def check_path_conflicts(registry: dict, new_paths: list[str], *, exclude: str | None = None) -> list[str]:
    """Return human-readable conflict descriptions (empty = OK)."""
    conflicts: list[str] = []
    for p in new_paths:
        for prefix in RESERVED_PATH_PREFIXES:
            if p.startswith(prefix) or prefix.startswith(p):
                conflicts.append(f"{p!r} overlaps reserved zone {prefix!r}")
    for dept, meta in registry.get("departments", {}).items():
        if dept == exclude or meta.get("status") == "retired":
            continue
        for existing in meta.get("owned_paths", []):
            for p in new_paths:
                if p.startswith(existing) or existing.startswith(p):
                    conflicts.append(f"{p!r} overlaps {existing!r} owned by {dept}")
    return conflicts
