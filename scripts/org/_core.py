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
import sys
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


def identity_path(root: Path, dept: str) -> Path:
    """Stable identity, passed as a file: a multi-KB argv is not a CLI argument."""
    return runtime_dir(root) / f"{dept}.identity.md"


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


def platform_overview() -> str:
    """Past / present / future of the whole platform, for the coordinator.

    A coordinator that only sees its own inbox will dispatch against a fiction:
    on 2026-08-05 the manager was assigning work while blind to 98 pending
    items (7 of them P1) in the canonical queue. Sourced from ops_snapshot.py —
    the canonical one-call readout — rather than a second inventory that could
    disagree with it.
    """
    import subprocess

    try:
        raw = subprocess.run(
            ["uv", "run", "python", "scripts/ops_snapshot.py"],
            cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=60,
        )
        snap = json.loads(raw.stdout)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        return (f"⚠️ **無法取得平台全局狀態**（{type(exc).__name__}）。"
                f"在修好之前，你只看得到組織內部，派工前請先自行跑 "
                f"`uv run python scripts/ops_snapshot.py` 確認，不要當作沒事。")

    q = snap.get("queue") or {}
    bb = snap.get("backbone") or {}
    pool = snap.get("content_pool") or {}
    alerts = snap.get("alerts") or {}
    git = snap.get("git") or {}

    top = q.get("top_pending") or []
    top_lines = "\n".join(
        f"  - [P{t.get('p', '?')}] `{t.get('id')}` ({t.get('type', '?')})"
        for t in top[:8]
    ) or "  （無）"

    by_p = q.get("pending_by_priority") or {}
    return f"""### 現在

- backbone：心跳 {bb.get('heartbeat_age_min', '?')} 分前；當前工作 {bb.get('current_job') or '無'}；
  上次 fire {bb.get('last_fire_age_min', '?')} 分前；auth_blocked={bb.get('auth_blocked')}
- 正在執行：{q.get('in_flight', '?')} 件；主線程收件匣 {q.get('main_thread_inbox', '?')} 件
- 未推 commit / git：{json.dumps(git, ensure_ascii=False)[:200]}

### 未來（canonical 任務池 `storage/next_tasks.json`）

- pending **{q.get('pending', '?')}** 件（P1={by_p.get('p1', 0)}／P2={by_p.get('p2', 0)}／
  P3={by_p.get('p3', 0)}／P4={by_p.get('p4', 0)}）；urgent {q.get('urgent_pending', 0)} 件；
  blocked {q.get('blocked', '?')} 件
- 隊首：
{top_lines}

### 過去 24 小時

- alerts 已送 {alerts.get('sent_last_24h', '?')} 則
- 內容池：{json.dumps(pool, ensure_ascii=False)[:200]}

**這個池是舊 dispatch 引擎在消化的，與部門收件匣目前並行。** 你要對它有判斷：
哪些該由部門接手、哪些該讓舊引擎跑完、哪些該退役。看到 P1 積壓或 blocked 堆高，
那是你的問題，不是別人的。
"""


def org_blockages(root: Path) -> str:
    """Who is blocked and who they are waiting on.

    Reuses the dashboard's aggregation rather than recomputing it: one
    calculation, two renderings (a page for the boss, this text for the
    coordinator). An agent should never be asked to read a web page to learn
    something that exists as data.
    """
    try:
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        import work_dashboard_org as view  # noqa: PLC0415
        snap = view.collect(root)
    except Exception as exc:  # noqa: BLE001 — a view problem must not blind the coordinator
        return (f"⚠️ 阻塞聚合讀不到（{type(exc).__name__}）。改用 org_status.py "
                f"與各部門 journal 自行判斷，不要當作沒有阻塞。")

    lines = []
    depts = snap.get("departments") or {}
    rows = depts.values() if isinstance(depts, dict) else depts
    for d in rows:
        blockers = d.get("blockers") or []
        waiting = d.get("pending_on_others") or []
        if not blockers and not waiting:
            continue
        lines.append(f"- **{d.get('title') or d.get('name')}**（health={d.get('health')}）")
        for b in blockers[:3]:
            what = b.get("what") if isinstance(b, dict) else str(b)
            fix = f" → 暫解：{b.get('workaround')}" if isinstance(b, dict) and b.get("workaround") else ""
            lines.append(f"  - 阻塞：{str(what)[:160]}{fix[:120]}")
        for w in waiting[:3]:
            lines.append(f"  - 等待：{str(w)[:160]}")
    if not lines:
        return "（目前沒有部門自報阻塞）"
    return "\n".join(lines) + (
        "\n\n**這些是你的工作**：等待別人的要確認對方知道且有排；被擋住的要裁決"
        "（放寬轄區、改派、或判定該項不做）。放著不動等於預設它會自己好。"
    )


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

## 平台全局（過去／現在／未來）

{platform_overview()}

## 誰卡住了（部門自報的阻塞與等待）

{org_blockages(root)}

## 你的收件匣（{len(inbox)} 件；老闆指令與部門上報都在這裡）

{chr(10).join(inbox) or "（空）"}

## 你的工具（全部用 `uv run python` 執行）

- **每輪必做：把 canonical 池的待辦依 task_type 派給對應部門**
  `scripts/org/queue_dispatch.py --dry-run`（先看分佈與無主型別）→ `--apply [--limit N]`
  部門收到的是**指標**不是副本：canonical 任務仍是唯一真相，部門用 task_pool_claim 結案。
- 派工到部門（**會直接送進該部門的視窗**，若對方 idle）：
  `scripts/org/dept_send.py <dept> --from manager --priority P1|P2|P3 --task "..."`
- 組織全景（含各部門自報阻塞，agent 讀 JSON 不讀網頁）：`curl -s localhost:8787/api/org`
  （老闆看的是同一份資料的網頁版 http://127.0.0.1:8787/org）
- 看組織狀態：`scripts/org/org_status.py`　｜　看誰在哪個 pane：`scripts/org/org_attach.py status`
- 看部門的 model/effort 路由：`scripts/org/dept_routing.py`
- 開/裁部門（裁撤與新開屬重大變更，需先寫提案 email 老闆）：`scripts/org/org_admin.py`
- 彙整給老闆的日報：`scripts/org/boss_digest.py --dry-run`
- 誰正在改哪些檔（避免撞車）：`scripts/path_claims.py list`

## 你的節奏（你不排班，機械排你）

`org_manager_tick` **每 30 分鐘**由 launchd 跑一次零成本判斷，有事才叫醒你——
所以你沒有自己的排程，也不該自己排。你只需要知道兩件事：

- 這一輪要做完，不要留半件（下一輪可能是 30 分鐘後，也可能因為沒有硬事實而不來）
- **每輪結尾在視窗裡寫一行**：本輪做了什麼、下一次閘門評估時間（每 :00 與 :30），
  以及你在等什麼。老闆會看這個視窗，他需要知道你還活著、下次什麼時候動。

另外你每 4 小時欠一次**主動巡檢**（見下），那是即使收件匣全空也會叫醒你的理由。

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


def identity_prompt(root: Path, dept: str) -> str:
    """The STABLE half of a department's identity: role, policy, charter.

    Belongs in the system prompt (`claude --append-system-prompt`), not in a
    user message. A first message competes for attention as the conversation
    grows and can be summarised away; a system prompt cannot, and it stays in
    the prompt cache instead of being re-sent as fresh input every turn.
    """
    ddir = dept_dir(root, dept)
    registry = load_registry(root)
    meta = registry.get("departments", {}).get(dept, {})
    title = meta.get("title") or dept
    charter = ddir / "charter.md"
    memory = ddir / "memory" / "notes.md"

    def _read(path: Path) -> str:
        if not path.exists():
            return "（無）"
        return path.read_text(encoding="utf-8").strip() or "（無）"

    return f"""你是 VolPred 平台的**{title}**（部門代號 `{dept}`）。

這是一個常駐部門的身分；你這個 session 是它的執行體。身分、記憶與工作狀態都在磁碟上
（`{ddir}`），session 結束不等於部門消失——下一個 session 會從同一份檔案接續。

## 組織通則（全員共用）

{org_policy(root)}

## 你的章程（職責、KPI、邊界、收尾契約）

{_read(charter)}

## 你的私有記憶

{_read(memory)}
"""


def build_brief(root: Path, dept: str) -> str:
    """Identity + current work, for callers that deliver both in one message.

    The headless path has no system-prompt hook, so it still needs the whole
    thing; the cockpit splits it (identity → system prompt, work → message).
    Composed from the same halves so the two surfaces cannot drift.
    """
    return identity_prompt(root, dept) + "\n" + work_prompt(root, dept)


def work_prompt(root: Path, dept: str) -> str:
    """The VOLATILE half: what this department should do right now."""
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
            sender = i.get("from") or "?"
            kind = i.get("kind") or "assignment"
            rendered.append(
                f"- [{i.get('priority', 'P3')}] **來自 {sender}**（{kind}）"
                f" `{i.get('id')}`\n  {i.get('task')}{due}{refs}{issue}"
            )
            # The reply command, spelled out: a department that has to work out
            # who asked and how to answer will skip answering.
            if kind == "request":
                rendered.append(
                    f"  ↩︎ 做完必回：`uv run python scripts/org/dept_send.py {sender}"
                    f" --from {dept} --reply-to {i.get('id')} --task \"結果：…\"`"
                )
            elif i.get("canonical_task_id"):
                rendered.append(
                    f"  ⓘ 這是 canonical 任務 `{i['canonical_task_id']}` 的指標——"
                    f"結案走 task_pool_claim，不要只歸檔本張工單"
                )
        inbox_block = "\n".join(rendered)
    else:
        inbox_block = "（收件匣是空的——沒有待辦就不要製造工作，回報 outcome=noop 後結束）"

    return f"""## 最近工作日誌（最後 20 行）

{_read(ddir / "journal.md", limit=20)}

## 你的收件匣（{len(items)} 件）

{inbox_block}

## 現在該做什麼

處理收件匣中優先序最高、已到期的工作項。**結束前必須執行章程末段的「Session 收尾契約」**
（寫 journal、更新 state.json、歸檔已處理項、回報給運營經理、經 git_writer_lock 提交、
清理自己的 worktree）。少做一步，下一個接手的 session 就會失去脈絡。

**收完一張就接下一張**（組織通則的 batch-drain：收班條件只有「沒有到期工作」與
「剩餘 context／預算不夠完整做完並收尾下一張」兩個），不要收工回去等下一班喚醒。
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
