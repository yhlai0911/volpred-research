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


def org_policy(root: Path) -> str:
    """Org-wide standing rules, rendered into every role's brief.

    Single source on purpose: copying the decision chain into seven charters
    guarantees seven versions of it within a month.
    """
    path = root / "policy.md"
    if not path.exists():
        return "（組織通則檔 policy.md 不存在——這是缺陷，請回報經理）"
    return path.read_text(encoding="utf-8").strip()


def build_manager_brief(root: Path) -> str:
    """The coordinator's rehydration brief: charter, org state, inbox, tools."""
    mdir = root / "manager"
    registry = load_registry(root)

    def _read(path: Path, limit: int | None = None) -> str:
        if not path.exists():
            return "（無）"
        text = path.read_text(encoding="utf-8").strip()
        if limit:
            text = "\n".join(text.splitlines()[-limit:])
        return text or "（無）"

    lines = []
    for name, meta in sorted(registry.get("departments", {}).items()):
        if meta.get("status") == "retired":
            continue
        ddir = dept_dir(root, name)
        state = {}
        if (ddir / "state.json").exists():
            try:
                state = json.loads((ddir / "state.json").read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                state = {"health": f"unreadable ({type(exc).__name__})"}
        lease = read_lease(root, name)
        runner = f"{lease.get('runner')}·{lease.get('pane_id')}" if lease else "未附掛"
        lines.append(
            f"- **{meta.get('title') or name}** (`{name}`) — 收件匣 {len(inbox_items(root, name))} 件"
            f"；上次執行 {state.get('last_run') or '未執行'}；健康 {state.get('health', '?')}"
            f"；執行體 {runner}"
        )

    inbox = []
    for path in sorted((mdir / "inbox").glob("*.json")) if (mdir / "inbox").is_dir() else []:
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):  # silent-ok: not silent — surfaced to the manager as ⚠️ in its brief
            inbox.append(f"- ⚠️ 無法解析 `{path.name}`")
            continue
        inbox.append(f"- [{item.get('priority', 'P3')}] 來自 **{item.get('from')}**：{item.get('task')}")

    return f"""你現在是 VolPred 平台的**運營經理**（協調者）。

你是這個平台唯一的協調者。各部門是常駐角色，身分與記憶都在磁碟上
（`{root}`）；你這個 session 是經理這個角色的執行體。你不做部門的專業工作，
你決定「現在該做什麼、由誰做、什麼時候回報老闆」。

## 組織通則（全員共用，你是它的執行者與守護者）

{org_policy(root)}

## 你的章程（職責、決策權限邊界）

{_read(mdir / "charter.md")}

## 你的私有記憶

{_read(mdir / "memory" / "notes.md")}

## 組織現況

{chr(10).join(lines) or "（尚無 active 部門）"}

## 你的收件匣（{len(inbox)} 件；老闆指令與部門上報都在這裡）

{chr(10).join(inbox) or "（空）"}

## 你的工具（全部用 `uv run python` 執行）

- 派工到部門（**會直接送進該部門的視窗**，若對方 idle）：
  `scripts/org/dept_send.py <dept> --from manager --priority P1|P2|P3 --task "..."`
- 看組織狀態：`scripts/org/org_status.py`　｜　看誰在哪個 pane：`scripts/org/org_attach.py status`
- 看部門的 model/effort 路由：`scripts/org/dept_routing.py`
- 開/裁部門（裁撤與新開屬重大變更，需先寫提案 email 老闆）：`scripts/org/org_admin.py`
- 彙整給老闆的日報：`scripts/org/boss_digest.py --dry-run`
- 誰正在改哪些檔（避免撞車）：`scripts/path_claims.py list`

## 現在該做什麼

1. 先看收件匣：老闆指令永遠最優先，其次是部門上報的 P1。
2. 對照 CLAUDE.md 的 5 個 mission 與終極目標（商業盈利）判斷輕重，把工作派到對的部門。
3. **部門正在忙（老闆可能正在跟它協作）時不要打斷**——工作留在收件匣即可，
   `dept_send.py` 會自動判斷並告訴你。
4. 需要老闆決策的（開/裁部門、對外新通路、不可回復操作）寫提案到
   `manager/outbox/proposals/`，不要自己執行。
5. 結束前把這次的判斷與理由 append 到 `bulletin/`（組織佈告欄），
   下一個經理 session 靠它接續。
"""


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

## 組織通則（全員共用）

{org_policy(root)}

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
