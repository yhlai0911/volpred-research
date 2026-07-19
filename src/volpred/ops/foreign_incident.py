"""Persistent incident for foreign paths PHASE-Z can never clear (decision doc §4 D3).

外部第二意見的逐字結論：**「若 CRITICAL 不會改變 scheduler 行為，它只是紅色日誌。」**

PHASE-Z 對「某些檔案卡在工作區、沒有人會回來收」這件事，本來只做了一件事：發
CRITICAL 信（3/6/12/24… 班退避）。警報有正常送出，78 班零行動 —— 因為那是
*notification*，不是 *控制流程*：

* 沒有單一 owner（信寄給所有人＝寄給沒有人）；
* 沒有 deadline（永遠不會逾期，所以永遠不急）；
* 對 scheduler 零影響（工作區越髒，派工照樣全速）；
* 未解決不影響後續 fire（下一班照跑，把同一批檔案再數一次）。

這個模組把那封信換成一張**持久 incident**，並讓它變成 scheduler 讀得到的訊號：

1. **一組卡住路徑 = 一張任務**（``upsert_incident``）。dedup key 是路徑集合的穩定
   fingerprint，不是標題、不是時間。第 2..N 班是**更新**（班數 / quarantine ref /
   last_seen_at），不是新增，也不再重發同一封 CRITICAL —— 既有 alert 路徑是被
   *收編*，不是再疊一層通知（反 alert-stacking：多一個提醒管道只會讓兩個都被忽略）。
2. **未關 → 降載**（``open_incidents``）。唯一 enforcement owner 是
   ``scripts/dispatch_slot_budget.py``，形狀比照既有的 ``auth_blocked → DERATE_CAP``。
   這裡只**提供訊號**，不自己開第二個 gate。
3. **關閉條件是機械可驗的**（``incident_closeable``），不是「有人覺得處理完了」。
   每個 dirty path 必須有 live workspace **或** immutable quarantine ref 覆蓋，
   而且不能還髒在 main checkout 裡。少一個就關不掉。

刻意不做的事：這裡沒有任何「這些 bytes 是誰的」推測。D1 明令停止猜測式收編，
incident 只回答「還卡著嗎 / 收拾乾淨了嗎」，不回答「該不該進 main」。
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from volpred.canonical_write import guard_canonical_write

from .diagnostics import warn
from .next_tasks import (
    TERMINAL_COMPACTABLE_STATUSES,
    append_next_task,
    write_tasks_to_handle,
)

#: 這類 incident 在任務池裡的識別標記（存在 ``payload`` 裡，不靠標題比對）。
INCIDENT_KIND = "phase_z_foreign_stuck"

#: PHASE-Z quarantine checkpoint 的 ref namespace。單一 owner 在這裡，
#: ``phase_z._FOREIGN_QUARANTINE_REF_PREFIX`` 是它的別名 —— 兩份字面值會在
#: 其中一份被改時無聲分岔，而分岔的後果是「保存了但檢查不到」。
QUARANTINE_REF_PREFIX = "refs/volpred/quarantine"

#: incident 是 P1：它會壓 cap，壓 cap 的東西不能排在別人後面慢慢等。
_INCIDENT_LEGACY_PRIORITY = 10  # → P1（next_tasks._legacy_priority_to_p）

#: 終局狀態＝incident 已關。``blocked`` / ``blocked_on_user`` 刻意**不算關閉**：
#: 檔案還卡著，降載就該繼續生效，否則「先擋著」會變成靜音鍵。
_CLOSED_STATUSES = TERMINAL_COMPACTABLE_STATUSES

_GIT_TIMEOUT_S = 30


# ── fingerprint ──────────────────────────────────────────────────────────────

def fingerprint(paths: Iterable[str]) -> str:
    """Stable id for one *set* of stuck paths.

    去重複、排序後 hash：同一批檔案不論這班以什麼順序被列出、streak 數字怎麼變，
    fingerprint 都一樣，所以第 2..N 班找得到第 1 班那張單。反過來，卡住的檔案集合
    真的變了（多一個 / 少一個），那就是**另一個**狀況，理當是另一張單 —— 用內容
    而不是時間當 key，就是為了讓這兩件事自動分開。
    """
    unique = sorted({str(p) for p in paths if str(p)})
    digest = hashlib.sha256("\n".join(unique).encode("utf-8")).hexdigest()
    return digest[:16]


# ── task-pool access ─────────────────────────────────────────────────────────

def _load_tasks(handle) -> list[Any]:
    handle.seek(0)
    raw = handle.read().strip()
    tasks = json.loads(raw) if raw else []
    if not isinstance(tasks, list):
        raise ValueError("next_tasks.json root is not a list")
    return tasks


def _is_incident(task: Any) -> bool:
    if not isinstance(task, dict):
        return False
    payload = task.get("payload")
    return isinstance(payload, dict) and payload.get("incident_kind") == INCIDENT_KIND


def _is_open(task: dict) -> bool:
    return str(task.get("status") or "").strip().lower() not in _CLOSED_STATUSES


def open_incidents(tasks_path: str | Path) -> list[dict]:
    """Every unclosed PHASE-Z stuck-path incident in the queue.

    Read-only and never raises: this is on the scheduler's hot path, and a queue
    it cannot parse must not take dispatch down. An unreadable queue means "no
    incident signal" and says so out loud (no silent fallback).
    """
    path = Path(tasks_path)
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        warn("foreign_incident", f"讀不到任務池 {path} ({exc}) — 當作沒有未關 incident")
        return []
    try:
        tasks = json.loads(raw) if raw else []
    except json.JSONDecodeError as exc:
        warn("foreign_incident", f"任務池 {path} 無法解析 ({exc}) — 當作沒有未關 incident")
        return []
    if not isinstance(tasks, list):
        warn("foreign_incident", f"任務池 {path} 根節點不是 list — 當作沒有未關 incident")
        return []
    return [t for t in tasks if _is_incident(t) and _is_open(t)]


def _describe(paths: Sequence[str], streaks: dict[str, int], fires: int,
              quarantine_refs: Sequence[str]) -> str:
    worst = max((streaks.get(p, 0) for p in paths), default=0)
    lines = [
        "## 發生什麼",
        f"{len(paths)} 個未提交檔案不是任何一班 fire 產出的，最長已連續 {worst} 班還在工作區。"
        "連續多班沒清，代表沒有人會回來收；工作區越髒，每一班「誰擁有這個檔案」的判斷就越不可靠。",
        "",
        "## 為什麼是一張任務而不是一封信",
        "這張單未關就會**壓低 scheduler 的 slot cap**（`scripts/dispatch_slot_budget.py`）。"
        "也就是說，不處理它的代價是每班能派的工變少 —— 這是它和以前那封 CRITICAL 的唯一差別。",
        "",
        "## 關閉條件（機械可驗，不是自我宣告）",
        "`uv run python -m volpred.ops.foreign_incident --check` 全綠才可關：",
        "每個路徑都要有 live workspace 或 quarantine ref 覆蓋，且不得還髒在 main checkout。",
        "",
        f"## 卡住的檔案（連續班數；本班第 {fires} 次觀察到這組）",
        *[f"- {p} — {streaks.get(p, 0)} 班" for p in paths[:30]],
        *(["- …"] if len(paths) > 30 else []),
    ]
    if quarantine_refs:
        lines += [
            "",
            "## 已保存（可取回）",
            "bytes 已 checkpoint 進不可變 ref（保存，不是收養，也進不了 main）：",
            *[f"- `git show {ref}:<路徑>`" for ref in quarantine_refs[-5:]],
        ]
    return "\n".join(lines)


def upsert_incident(
    *,
    paths: Sequence[str],
    streaks: dict[str, int] | None = None,
    quarantine_ref: str | None = None,
    tasks_path: str | Path = "storage/next_tasks.json",
    now: datetime | None = None,
) -> dict[str, Any]:
    """建/更新**一張** incident。回傳 receipt，含 ``created``（是否為新單）。

    ``created`` 是 alert 收編的開關：只有新開的 incident 才配一封 CRITICAL。第
    2..N 班找到同 fingerprint 的未關單，就只更新班數 / ref / last_seen_at，不新增、
    不再發信 —— 78 班寄 6 封同樣的信，讀者學到的是把它歸檔，不是去處理它。

    建立走 ``next_tasks.append_next_task``（唯一 canonical append gateway），
    更新走 ``write_tasks_to_handle``（唯一 canonical serializer）。這裡沒有第二條
    寫入路徑，因為任務池被截斷過一次就夠了（incident 2026-07-05）。
    """
    now = now or datetime.now(timezone.utc)
    ordered = sorted({str(p) for p in paths if str(p)})
    receipt: dict[str, Any] = {
        "fingerprint": None, "task_id": None, "created": False,
        "updated": False, "reason": "", "fires": 0,
    }
    if not ordered:
        receipt["reason"] = "no_stuck_paths"
        return receipt

    fp = fingerprint(ordered)
    receipt["fingerprint"] = fp
    streaks = streaks or {}
    path = Path(tasks_path)
    guard_canonical_write(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("[]\n", encoding="utf-8")

    # Phase 1: 同 fingerprint 的未關單存在 → 就地更新，鎖內完成。
    with path.open("r+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            tasks = _load_tasks(handle)
            existing = next(
                (t for t in tasks
                 if _is_incident(t) and _is_open(t)
                 and (t.get("payload") or {}).get("fingerprint") == fp),
                None,
            )
            if existing is not None:
                payload = existing["payload"]
                payload["fires"] = int(payload.get("fires", 1)) + 1
                payload["streaks"] = {p: int(streaks.get(p, 0)) for p in ordered}
                payload["last_seen_at"] = now.isoformat()
                if quarantine_ref:
                    refs = payload.setdefault("quarantine_refs", [])
                    if quarantine_ref not in refs:
                        refs.append(quarantine_ref)
                existing["description"] = _describe(
                    ordered, payload["streaks"], payload["fires"],
                    payload.get("quarantine_refs", []),
                )
                existing["updated_at"] = now.isoformat()
                write_tasks_to_handle(handle, tasks)
                receipt.update({
                    "task_id": existing.get("id"), "updated": True,
                    "reason": "updated_existing", "fires": payload["fires"],
                })
                return receipt
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    # Phase 2: 沒有未關的同 fingerprint 單 → 走 canonical append gateway。
    # 鎖已釋放才呼叫（同一支 flock 在同 process 內重入會鎖死自己）。
    payload = {
        "incident_kind": INCIDENT_KIND,
        "fingerprint": fp,
        "paths": ordered,
        "streaks": {p: int(streaks.get(p, 0)) for p in ordered},
        "quarantine_refs": [quarantine_ref] if quarantine_ref else [],
        "fires": 1,
        "first_seen_at": now.isoformat(),
        "last_seen_at": now.isoformat(),
    }
    record = append_next_task(
        # 標題刻意不帶班數／檔案數：會浮動的數字進標題，等於每班一個新 dedup key，
        # 那正是舊 CRITICAL 變成連環通知的機制。浮動的東西全放 description。
        title=f"PHASE-Z 卡住檔案 incident（{fp}）— 未關則 scheduler 降載",
        description=_describe(ordered, payload["streaks"], 1, payload["quarantine_refs"]),
        source="phase_z",
        task_family="ops",
        legacy_priority=_INCIDENT_LEGACY_PRIORITY,
        payload=payload,
        path=path,
    )
    receipt.update({
        "task_id": record.get("id"), "created": True,
        "reason": "created", "fires": 1,
    })
    receipt["superseded"] = _supersede_subsumed(
        path, keep_id=str(record.get("id")), paths=set(ordered), now=now,
    )
    return receipt


def _supersede_subsumed(path: Path, *, keep_id: str, paths: set[str],
                        now: datetime) -> list[str]:
    """卡住的檔案集合長大時，把被完全涵蓋的舊 incident 標成 superseded。

    沒有這一步，「又多一個檔案卡住」就會是一張全新的單，而舊的那張永遠沒有關閉
    條件可滿足 —— 一年後任務池裡躺著幾十張同一件事的 incident，降載訊號變成常態
    背景，於是又回到「紅色日誌」。只在**子集**時 supersede：那是可以機械證明「新
    單完全涵蓋舊單」的唯一情況，不是猜的。
    """
    superseded: list[str] = []
    with path.open("r+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            tasks = _load_tasks(handle)
            for task in tasks:
                if not (_is_incident(task) and _is_open(task)):
                    continue
                if task.get("id") == keep_id:
                    continue
                old = set((task.get("payload") or {}).get("paths") or [])
                if not old or not old <= paths:
                    continue
                task["status"] = "superseded"
                task["superseded_at"] = now.isoformat()
                task["superseded_by"] = keep_id
                task["completed_at"] = now.isoformat()
                task["result"] = "subsumed_by_wider_stuck_path_set"
                superseded.append(str(task.get("id")))
            if superseded:
                write_tasks_to_handle(handle, tasks)
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    return superseded


# ── mechanical close condition ───────────────────────────────────────────────

def _git_lines(repo_root: Path, *args: str, runner=subprocess.run) -> list[str]:
    try:
        proc = runner(
            ["git", "-C", str(repo_root), *args],
            capture_output=True, text=True, timeout=_GIT_TIMEOUT_S, check=False,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        warn("foreign_incident", f"git {args[0]} 失敗 ({exc}) — 視為無覆蓋證據")
        return []
    if proc.returncode != 0:
        warn("foreign_incident",
             f"git {args[0]} rc={proc.returncode} — 視為無覆蓋證據",
             err=(proc.stderr or "")[-200:])
        return []
    return [line for line in (proc.stdout or "").splitlines() if line]


def quarantine_covered_paths(repo_root: Path, *, runner=subprocess.run) -> set[str]:
    """Every path retrievable from some immutable quarantine ref."""
    covered: set[str] = set()
    refs = _git_lines(repo_root, "for-each-ref", "--format=%(refname)",
                      QUARANTINE_REF_PREFIX, runner=runner)
    for ref in refs:
        covered.update(_git_lines(repo_root, "ls-tree", "-r", "--name-only", ref,
                                  runner=runner))
    return covered


def live_workspace_paths(repo_root: Path, paths: Iterable[str], *,
                         runner=subprocess.run) -> dict[str, str]:
    """``rel -> workspace`` for paths that exist in a registered git worktree.

    「Live workspace」= ``git worktree list`` 認得的工作區（不是 ``.claude/worktrees/``
    底下隨便一個目錄 —— 目錄是**產物**，registration 才是關係）。一個檔案還在某人的
    工作區裡，就不是「沒人收的遺留」，它有地方可去。
    """
    worktrees: list[Path] = []
    for line in _git_lines(repo_root, "worktree", "list", "--porcelain", runner=runner):
        if line.startswith("worktree "):
            wt = Path(line[len("worktree "):].strip())
            if wt.resolve() != repo_root.resolve():
                worktrees.append(wt)
    found: dict[str, str] = {}
    for rel in paths:
        for wt in worktrees:
            if (wt / rel).exists():
                found[rel] = str(wt)
                break
    return found


def dirty_paths(repo_root: Path, *, runner=subprocess.run) -> set[str]:
    """Paths still uncommitted in the main checkout."""
    out: set[str] = set()
    for line in _git_lines(repo_root, "status", "--porcelain",
                           "--untracked-files=all", runner=runner):
        rel = line[3:].strip().strip('"')
        if " -> " in rel:
            rel = rel.split(" -> ", 1)[1]
        out.add(rel)
    return out


def incident_closeable(
    repo_root: Path,
    paths: Sequence[str],
    *,
    runner=subprocess.run,
) -> dict[str, Any]:
    """一張 incident 可否關閉 —— 機械判定，逐路徑給證據。

    ``closeable`` 為 True 的充要條件：

    * **每一個** dirty path 都被覆蓋 —— 存在於某個 live workspace，或可從某個
      immutable quarantine ref 取回（``git show <ref>:<path>``）；**且**
    * 這些路徑都不再髒在 main checkout 裡。

    第二條是這張單真正的 forcing function。只有 quarantine 覆蓋、檔案卻還躺在工作
    區，是「保存了但沒收拾」—— 那正是 78 班期間的狀態，而它不該算解決。少一個路徑
    沒覆蓋就 False：關閉條件必須是全稱的，否則「大部分處理完了」會變成關單理由。
    """
    ordered = sorted({str(p) for p in paths if str(p)})
    quarantined = quarantine_covered_paths(repo_root, runner=runner)
    workspaces = live_workspace_paths(repo_root, ordered, runner=runner)
    still_dirty = dirty_paths(repo_root, runner=runner)

    evidence: dict[str, dict[str, Any]] = {}
    blockers: list[str] = []
    for rel in ordered:
        in_quarantine = rel in quarantined
        workspace = workspaces.get(rel)
        dirty = rel in still_dirty
        covered = bool(in_quarantine or workspace)
        evidence[rel] = {
            "quarantined": in_quarantine,
            "live_workspace": workspace,
            "still_dirty_in_main": dirty,
            "covered": covered,
        }
        if not covered:
            blockers.append(f"{rel}: 沒有 live workspace，也沒有 quarantine ref 可取回")
        elif dirty:
            blockers.append(f"{rel}: 已保存但仍髒在 main checkout — 尚未收拾")

    return {
        "closeable": bool(ordered) and not blockers,
        "paths": evidence,
        "blockers": blockers,
        "checked": ordered,
    }


def check_open_incidents(repo_root: Path, *, tasks_path: str | Path | None = None,
                         runner=subprocess.run) -> list[dict[str, Any]]:
    """跑每一張未關 incident 的關閉條件，回傳逐張結果。"""
    tasks_path = tasks_path or (repo_root / "storage" / "next_tasks.json")
    out: list[dict[str, Any]] = []
    for task in open_incidents(tasks_path):
        payload = task.get("payload") or {}
        result = incident_closeable(repo_root, payload.get("paths") or [], runner=runner)
        result["task_id"] = task.get("id")
        result["fingerprint"] = payload.get("fingerprint")
        out.append(result)
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="對每張未關 incident 跑關閉條件；有任一張關不掉則 exit 1")
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parents[3]))
    args = ap.parse_args(argv)

    repo_root = Path(args.repo)
    results = check_open_incidents(repo_root)
    print(json.dumps(results, ensure_ascii=False, indent=2))
    if not args.check:
        return 0
    return 0 if all(r["closeable"] for r in results) else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
