#!/usr/bin/env python3
"""Org intake: the two doors work enters this organization through.

**Door 1 — the boss.** A boss message does not wait for the 30-minute tick. It
is written into `manager/inbox` and the coordinator is woken immediately, via
the same `wake_manager` the tick uses — one wake path, not two. The wake is
best-effort by construction: the item is on disk before anyone is woken, so a
failed wake costs latency (the next tick collects it), never the message.

**Door 2 — the issue tracker.** GitHub issues labelled `dept:<name>` are
registered as *canonical* tasks in `storage/next_tasks.json`, never as a second
queue. The department receives them the way it receives everything else: as a
pointer, through `queue_dispatch.py`. Issues remain the planning and acceptance
layer (`docs/agents/issue-tracker.md`); this materializes only the runtime half,
and completing that task is not authority to close the issue.

An issue that carries `dept:*` but cannot be routed is not dropped and is not
left to re-fire the gate forever: it becomes one idempotent P3 item asking the
coordinator to rule, which disappears when ruled on.

  uv run python scripts/org/org_intake.py --boss-message "..." [--msg-id 1234]
  uv run python scripts/org/org_intake.py --github --dry-run
  uv run python scripts/org/org_intake.py --github --apply
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _core import (  # noqa: E402
    DEFAULT_ORG_ROOT,
    REPO_ROOT,
    atomic_write_json,
    load_registry,
    now_iso,
    write_receipt,
)

MANAGER = "manager"
NEXT_TASKS = REPO_ROOT / "storage" / "next_tasks.json"

# The canonical queue only admits producers listed in the reviewed provenance
# registry (`volpred.ops.work.legacy._NEXT_TASK_SOURCE`), and it checks that
# only on the canonical path — so a tmp-pool test passes while production fails
# closed. Naming it here lets the test assert the registration itself.
INTAKE_SOURCE = "github_issue"

DEPT_LABEL_RE = re.compile(r"^dept:([a-z][a-z0-9_]{1,31})$")
TITLE_TYPE_RE = re.compile(r"^\s*\[([a-z][a-z0-9_]*)\]")
PRIORITY_LABEL_RE = re.compile(r"^P([123])$", re.IGNORECASE)


# --- door 1: the boss ------------------------------------------------------

def _manager_inbox(root: Path) -> Path:
    return root / MANAGER / "inbox"


def _existing_item(root: Path, item_id: str) -> Path | None:
    """Look in the archive too: an item already handled must not come back.

    The daemon replays consumed Telegram updates after a restart, so intake has
    to be idempotent on the message id the same way `_append_task` is on the
    canonical task id — otherwise a restart storm re-wakes the coordinator once
    per replayed message.
    """
    inbox = _manager_inbox(root)
    for folder in (inbox, inbox / "_archive"):
        path = folder / f"{item_id}.json"
        if path.exists():
            return path
    return None


def _boss_task_text(text: str, channel: str, canonical_task_id: str | None) -> str:
    if canonical_task_id:
        contract = (
            f"—— 分工：**聊天回覆不歸你**，由既有 responder 透過 canonical 任務 "
            f"`{canonical_task_id}` 負責（reply-right guard 也會擋第二次回覆）。"
            f"你的職責是這則指令的**組織層後果**：要不要改優先序、派給哪個部門、"
            f"是否推翻既有裁決、要不要開新工作。若 responder 已完整答完且沒有組織層"
            f"後果，在 journal 記一行後歸檔即可 —— 但**不要**去 claim 那張任務。"
        )
    else:
        contract = (
            "—— 這則沒有其他 owner 在回覆，回覆責任在你（用 canonical 的 "
            "`volpred ops telegram-send` / email 通道）。"
        )
    return f"【老闆指令 · {channel}】{text}\n{contract}"


def _wake(root: Path, reasons: list[str]) -> dict:
    """Wake the coordinator now, reusing the tick's own wake path.

    Never raises. The inbox item is already durable at this point, so the worst
    case of a failed wake is the 30-minute tick picking it up — degraded, but
    the boss's message is not lost. The outcome is written into the receipt so
    "the manager was never woken" stays searchable instead of invisible.
    """
    try:
        from manager_tick import wake_manager  # noqa: PLC0415 — avoids an import cycle

        return wake_manager(root, reasons, respect_min_interval=False)
    except Exception as exc:  # noqa: BLE001 — see docstring; recorded in the receipt
        return {
            "woken": False,
            "reason": f"wake failed ({type(exc).__name__}: {exc}) — 下一班 tick 兜底",
        }


def record_boss_message(
    root: Path,
    text: str,
    *,
    channel: str = "telegram",
    msg_id: str | None = None,
    canonical_task_id: str | None = None,
    wake: bool = True,
) -> dict:
    """Write the boss's instruction into manager/inbox and wake the coordinator."""
    if msg_id:
        item_id = f"boss_{channel}_{msg_id}"
    else:
        item_id = f"boss_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}"

    existing = _existing_item(root, item_id)
    if existing:
        result = {
            "item_id": item_id,
            "created": False,
            "path": str(existing),
            "reason": "已存在（daemon replay 或重送）— 不重複建項、不重複喚醒",
        }
        write_receipt(root, "boss_intake", result)
        return result

    item = {
        "id": item_id,
        "from": "boss",
        "to": MANAGER,
        "priority": "P1",
        "kind": "assignment",
        "channel": channel,
        "task": _boss_task_text(text, channel, canonical_task_id),
        "refs": [],
        "canonical_task_id": canonical_task_id,
        "created_at": now_iso(),
    }
    path = _manager_inbox(root) / f"{item_id}.json"
    atomic_write_json(path, item)

    result: dict = {"item_id": item_id, "created": True, "path": str(path)}
    if wake:
        result["wake"] = _wake(root, [f"老闆經 {channel} 傳來指令（{item_id}）"])
    else:
        result["wake"] = {"woken": False, "reason": "--no-wake"}
    write_receipt(root, "boss_intake", result)
    return result


# --- door 2: the issue tracker ---------------------------------------------

def _gh() -> str | None:
    """One resolver for `gh`, shared with the runtime issue bridge.

    Non-interactive shells drop Homebrew from PATH, so "command not found" is
    not evidence that gh is missing (CLAUDE.md). Reusing the bridge's resolver
    keeps that knowledge in one place.
    """
    try:
        from volpred.ops.issue_tracker_sync import _resolve_gh_binary  # noqa: PLC0415

        return _resolve_gh_binary()
    except Exception:  # noqa: BLE001 — reported by the caller as "gh unavailable"
        import shutil

        return shutil.which("gh") or (
            "/opt/homebrew/bin/gh" if Path("/opt/homebrew/bin/gh").exists() else None
        )


def _open_issues(gh: str) -> list[dict]:
    out = subprocess.run(
        [gh, "issue", "list", "--state", "open",
         "--json", "number,title,labels,url", "--limit", "200"],
        capture_output=True, text=True, timeout=60, check=True,
    ).stdout
    return json.loads(out)


def resolve_issue(issue: dict, registry: dict) -> tuple[str | None, str | None, str | None]:
    """(department, task_type, why_not) for one issue.

    All three None means "not opted in" — an unlabelled issue is planning work,
    not a routing failure. Ownership is resolved from the registry, never
    guessed: a department owning several task_types needs the `[task_type]`
    title prefix, because picking one for it would silently mis-route the work.
    """
    labels = [str(lbl.get("name") or "") for lbl in (issue.get("labels") or [])]
    depts = [m.group(1) for m in (DEPT_LABEL_RE.match(lbl) for lbl in labels) if m]
    if not depts:
        return None, None, None
    if len(depts) > 1:
        return None, None, f"帶了多個 dept:* 標籤（{', '.join(sorted(depts))}）— 歸屬必須唯一"

    dept = depts[0]
    meta = (registry.get("departments") or {}).get(dept)
    if not meta or meta.get("status") != "active":
        return None, None, f"dept:{dept} 不是 active 部門"
    owned = list(meta.get("owned_task_types") or [])
    if not owned:
        return None, None, f"{dept} 沒有宣告 owned_task_types，無法決定 task_type"

    prefix = TITLE_TYPE_RE.match(str(issue.get("title") or ""))
    if prefix:
        declared = prefix.group(1)
        if declared in owned:
            return dept, declared, None
        return None, None, (
            f"標題宣告 [{declared}]，但 {dept} 不擁有這個 task_type（它擁有：{', '.join(owned)}）"
        )
    if len(owned) == 1:
        return dept, owned[0], None
    return None, None, (
        f"{dept} 擁有 {len(owned)} 個 task_type，標題缺 [task_type] 前綴 — 可選：{', '.join(owned)}"
    )


def _issue_priority(issue: dict) -> int:
    for lbl in (issue.get("labels") or []):
        m = PRIORITY_LABEL_RE.match(str(lbl.get("name") or ""))
        if m:
            return int(m.group(1))
    return 2


def _pool_index() -> dict[str, str]:
    """issue_ref → task id, for every task in the pool regardless of status.

    Terminal tasks count. `issue_disposition=contained` is the *default* for a
    successful linked task — the issue deliberately stays open — so keying only
    on pending tasks would re-queue every completed slice on the next round.
    """
    try:
        tasks = json.loads(NEXT_TASKS.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise SystemExit(f"無法讀取 canonical 任務池 {NEXT_TASKS}：{type(exc).__name__}: {exc}")
    if isinstance(tasks, dict):
        tasks = tasks.get("tasks", [])
    out: dict[str, str] = {}
    for t in tasks:
        if not isinstance(t, dict):
            continue
        ref = str(t.get("issue_ref") or "")
        if ref:
            out.setdefault(ref, str(t.get("id")))
        tid = str(t.get("id") or "")
        if tid.startswith("gh-"):
            out.setdefault(f"#{tid[3:]}", tid)
    return out


def plan_github(root: Path) -> dict:
    """Read-only: what intake would do with the tracker right now."""
    gh = _gh()
    if not gh:
        return {"error": "gh 不可用（PATH 與 /opt/homebrew/bin 都找不到）", "routable": [],
                "unroutable": [], "mirrored": [], "unlabelled": 0}
    try:
        issues = _open_issues(gh)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        return {"error": f"gh issue list 失敗（{type(exc).__name__}: {exc}）", "routable": [],
                "unroutable": [], "mirrored": [], "unlabelled": 0}

    registry = load_registry(root)
    in_pool = _pool_index()
    routable, unroutable, mirrored = [], [], []
    unlabelled = 0

    for issue in issues:
        number = int(issue.get("number"))
        dept, task_type, why_not = resolve_issue(issue, registry)
        if dept is None and why_not is None:
            unlabelled += 1
            continue
        existing = in_pool.get(f"#{number}")
        if existing:
            mirrored.append({"number": number, "task_id": existing})
            continue
        row = {"number": number, "title": str(issue.get("title") or ""),
               "url": str(issue.get("url") or "")}
        if dept:
            routable.append({**row, "dept": dept, "task_type": task_type,
                             "priority": _issue_priority(issue)})
        else:
            unroutable.append({**row, "why_not": why_not})
    return {"routable": routable, "unroutable": unroutable, "mirrored": mirrored,
            "unlabelled": unlabelled, "gh": gh}


def unmirrored_github_issues(root: Path) -> list[str]:
    """Gate-facing summary: only issues the tracker still owes the org.

    Reporting every open `dept:*` issue would fire the gate forever — an issue
    stays open long after its runtime task is done. What is actually a signal is
    work the org has not absorbed yet.
    """
    result = plan_github(root)
    if result.get("error"):
        return [f"github check unavailable（{result['error']}）— treated as no-signal"]
    out = []
    if result["routable"]:
        nums = ", ".join(f"#{r['number']}" for r in result["routable"][:8])
        out.append(f"github 有 {len(result['routable'])} 件 dept:* issue 尚未入池（{nums}）")
    if result["unroutable"]:
        nums = ", ".join(f"#{r['number']}" for r in result["unroutable"][:8])
        out.append(f"github 有 {len(result['unroutable'])} 件 dept:* issue 路由不了，待你裁（{nums}）")
    return out


def _mirror_one(issue_row: dict, gh: str) -> dict:
    from volpred.ops.next_tasks import append_task_record  # noqa: PLC0415

    number = issue_row["number"]
    task_id = f"gh-{number}"
    record = {
        "id": task_id,
        "task_type": issue_row["task_type"],
        "priority": issue_row["priority"],
        "status": "pending",
        "source": INTAKE_SOURCE,
        "issue_ref": f"#{number}",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "title": f"[#{number}] {issue_row['title'][:180]}",
        "description": (
            f"GitHub issue #{number} 經 dept:{issue_row['dept']} 標籤登記為 runtime 工作。\n"
            f"{issue_row['url']}\n\n"
            "驗收條件、討論與歷史都在 issue 上（`gh issue view "
            f"{number} --comments`）—— 那裡是規劃與驗收層，這裡只是 runtime 那一半。\n"
            "**完成這張任務不等於可以關 issue**：預設 `--issue-disposition contained`，"
            "只有整張 issue 的驗收條件與結案五步 Gate 全過才可傳 `close`"
            "（見 docs/agents/issue-tracker.md）。"
        ),
    }
    _created_record, created = append_task_record(record, path=NEXT_TASKS, if_exists="skip")
    out = {"number": number, "task_id": task_id, "created": bool(created),
           "dept": issue_row["dept"], "task_type": issue_row["task_type"]}
    if not created:
        out["comment"] = "skipped（任務已存在，不重複留言）"
        return out

    body = (
        f"🏢 已入運營池：canonical 任務 `{task_id}`（`storage/next_tasks.json`，"
        f"task_type=`{issue_row['task_type']}`，歸屬 `{issue_row['dept']}`）。\n\n"
        "GitHub 仍是規劃與驗收層；runtime 任務完成預設 `contained`，issue 保持開啟，"
        "直到整張 issue 的驗收條件與結案五步 Gate 全過。"
    )
    try:
        proc = subprocess.run([gh, "issue", "comment", str(number), "--body", body],
                              capture_output=True, text=True, timeout=60)
        out["comment"] = "ok" if proc.returncode == 0 else f"failed: {(proc.stderr or '').strip()[:120]}"
    except (OSError, subprocess.SubprocessError) as exc:
        # Declared contract of the issue bridge: a GitHub failure is reported,
        # never rolled back. The task is real work now; losing it because a
        # comment did not post would be the worse failure.
        out["comment"] = f"failed: {type(exc).__name__}: {exc}"
    return out


def _report_unroutable(root: Path, rows: list[dict]) -> list[str]:
    """One idempotent P3 ruling request per unroutable issue.

    A gate that keeps firing on the same unfixable fact trains everyone to
    ignore it. An inbox item is self-terminating instead: it fires the gate once
    and stops when the coordinator rules.
    """
    written = []
    for row in rows:
        item_id = f"gh_unroutable_{row['number']}"
        if _existing_item(root, item_id):
            continue
        item = {
            "id": item_id,
            "from": "github",
            "to": MANAGER,
            "priority": "P3",
            "kind": "decision",
            "task": (
                f"GitHub issue #{row['number']}「{row['title'][:100]}」帶了 dept:* 標籤但路由不了："
                f"{row['why_not']}。請裁：補標籤／改標題前綴／調整 registry 的 owned_task_types／"
                f"判定它不是 runtime 工作。裁完把這件歸檔。\n{row['url']}"
            ),
            "refs": [row["url"]],
            "issue": row["number"],
            "created_at": now_iso(),
        }
        atomic_write_json(_manager_inbox(root) / f"{item_id}.json", item)
        written.append(item_id)
    return written


def mirror_github(root: Path, *, apply: bool, limit: int = 20) -> dict:
    result = plan_github(root)
    if result.get("error"):
        return result
    result["applied"] = []
    result["ruling_requests"] = []
    if not apply:
        return result
    for row in result["routable"][:limit]:
        result["applied"].append(_mirror_one(row, result["gh"]))
    result["ruling_requests"] = _report_unroutable(root, result["unroutable"])
    write_receipt(root, "github_intake", {
        "applied": result["applied"],
        "ruling_requests": result["ruling_requests"],
        "routable_total": len(result["routable"]),
        "unroutable_total": len(result["unroutable"]),
    })
    return result


# --- CLI -------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=DEFAULT_ORG_ROOT)
    parser.add_argument("--boss-message", default=None)
    parser.add_argument("--channel", choices=("telegram", "email"), default="telegram")
    parser.add_argument("--msg-id", default=None,
                        help="transport message id; makes intake idempotent on daemon replay")
    parser.add_argument("--canonical-task-id", default=None,
                        help="id of the task that already owns the reply obligation")
    parser.add_argument("--no-wake", action="store_true",
                        help="record only; leave the coordinator to the next tick")
    parser.add_argument("--github", action="store_true",
                        help="mirror dept:*-labelled open issues into the canonical queue")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--limit", type=int, default=20,
                        help="max issues mirrored per round (default 20)")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    if not args.github and not args.boss_message:
        parser.error("nothing to do: pass --boss-message or --github")

    if args.boss_message:
        result = record_boss_message(
            args.root, args.boss_message, channel=args.channel, msg_id=args.msg_id,
            canonical_task_id=args.canonical_task_id, wake=not args.no_wake,
        )
        if args.as_json:
            print(json.dumps(result, ensure_ascii=False))
        else:
            print(result["path"])
            if not result["created"]:
                print(f"note: {result['reason']}", file=sys.stderr)
            else:
                print(f"wake: {json.dumps(result['wake'], ensure_ascii=False)}", file=sys.stderr)

    if args.github:
        if not args.dry_run and not args.apply:
            parser.error("--github 需要 --dry-run 或 --apply")
        result = mirror_github(args.root, apply=args.apply, limit=args.limit)
        if args.as_json:
            print(json.dumps(result, ensure_ascii=False))
            return 1 if result.get("error") else 0
        if result.get("error"):
            print(f"⚠️ {result['error']}", file=sys.stderr)
            return 1
        print(f"開啟中 issue：{result['unlabelled']} 件未帶 dept:* 標籤（不入池）；"
              f"{len(result['mirrored'])} 件已在池中")
        for row in result["routable"]:
            mark = "已入池" if args.apply else "可入池"
            print(f"  {mark} #{row['number']} → {row['dept']}/{row['task_type']} "
                  f"P{row['priority']}：{row['title'][:60]}")
        for row in result["unroutable"]:
            print(f"  ⚠️ #{row['number']} 路由不了：{row['why_not']}")
        if args.apply:
            failed = [a for a in result["applied"] if str(a.get("comment", "")).startswith("failed")]
            print(f"\n入池 {sum(1 for a in result['applied'] if a['created'])} 件"
                  f"（issue 留言失敗 {len(failed)} 件，不影響入池）；"
                  f"送出 {len(result['ruling_requests'])} 件請經理裁決")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
