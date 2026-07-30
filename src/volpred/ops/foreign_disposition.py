"""已裁決 foreign 路徑的**寫入出口** —— incident 解除端的 actuator（決策文件 §4 D4 前的最小止血）。

## 為什麼需要這個模組

`volpred.ops.foreign_incident` 把「檔案卡在工作區、沒有人會回來收」變成一張會壓
scheduler slot cap 的 incident。那半邊是對的：懲罰端接上了控制流程。但**解除端沒接**
—— 能讓那些路徑不再髒在 main checkout 的三條路全部封閉：

* PHASE-Z 只 commit ``dirty_now - baseline``，foreign 檔依定義不在其中；
* dispatch 規則硬禁 agent 在 shared checkout 裸跑 git mutation（且併行 slot 會撞）；
* cleanup layer 的猜測式自動收編已被 D1 明令停止。

結果是每班半速派工，而且**沒有一班能靠自己走出來** —— 違反這個 class 自己的驗收
標準「有限班數內必達 terminal state」。本模組就是那條缺掉的出口。

## 這個出口刻意不做的事

**零推斷**。它不判斷「這些 bytes 是誰的」「該不該進 main」—— 那正是 D1 停掉的東西。
輸入是一份**逐路徑的明文裁決**（disposition），由知道該檔案的人或任務產生；本模組
只負責把已經做成的決定**安全地、序列化地**落地。沒有 disposition 就沒有動作。

這是刻意的 operator gate，不是漏接自動 caller：CLI shim
``scripts/foreign_disposition.py`` 就是 actuator。自動呼叫必須猜 ownership/disposition，
會直接違反上面的 zero-inference contract。

## 三個不變式（少一個就是這個 class 的第 7 次補丁）

1. **只動清單內的路徑。** 全程使用明確 pathspec，永不 ``git add -A``；並在事後比對
   dirty 集合的差異，任何清單外的附帶變化都是錯誤（``collateral``），不是可接受的
   副作用。2026-07-10 那次 ``git add -A`` 收走被截斷的 ``next_tasks.json``，就是這條
   不變式缺席的代價。
2. **處置前 bytes 必須可取回。** quarantine ref 或 HEAD 至少一處拿得到，否則拒做。
   ``delete`` 丟掉的是工作區副本，不是唯一副本 —— 這是它和 ``rm`` 的全部差別。
3. **處置後必須機械可驗。** 每個被處置的路徑事後不得再 dirty；沒達成就回報失敗，
   不自我宣告成功。

``leave`` 是刻意保留的第三種裁決：明文記錄「這個路徑現在不處置，理由是 X」。它不會
讓 incident 變可關，但它把沉默變成有署名的決定 —— 沉默正是這 78 班的失敗模式。
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .diagnostics import warn
from .foreign_incident import dirty_paths, quarantine_covered_paths
from .git_writer_lock import (
    git_writer_lock,
    git_writer_subprocess_kwargs,
    require_canonical_main_checkout,
)

#: 合法裁決。``commit`` = 這些 bytes 屬於 main；``delete`` = 丟掉工作區副本
#: （quarantine/HEAD 仍可取回）；``leave`` = 明文不處置，附理由。
ACTIONS = ("commit", "delete", "leave")

_GIT_TIMEOUT_S = 60.0


class DispositionError(RuntimeError):
    """裁決檔不合法，或落地過程違反不變式。一律 fail-closed。"""


# ── disposition 檔 ───────────────────────────────────────────────────────────

def load_disposition(path: str | Path) -> dict[str, Any]:
    """讀並驗證裁決檔。格式錯 = 不動任何檔案。

    ``{"adjudicated_by": str, "incident": str|null,
       "paths": {"<rel>": {"action": "commit|delete|leave", "reason": str}}}``

    ``reason`` 是必填而不是選填：一個沒有理由的裁決，下一班沒辦法判斷它還成不成立，
    於是又變成一筆無主狀態。
    """
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DispositionError(f"讀不到或解析不了裁決檔 {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise DispositionError("裁決檔頂層必須是 object")

    adjudicated_by = str(raw.get("adjudicated_by") or "").strip()
    if not adjudicated_by:
        raise DispositionError("adjudicated_by 必填 —— 裁決要有署名，否則無法追責")

    paths = raw.get("paths")
    if not isinstance(paths, dict) or not paths:
        raise DispositionError("paths 必須是非空 object")

    cleaned: dict[str, dict[str, str]] = {}
    for rel, spec in paths.items():
        rel = str(rel).strip()
        if not rel or rel.startswith("/") or ".." in Path(rel).parts:
            raise DispositionError(f"路徑必須是 repo 相對且不含 ..：{rel!r}")
        if not isinstance(spec, dict):
            raise DispositionError(f"{rel}: 裁決必須是 object")
        action = str(spec.get("action") or "").strip()
        if action not in ACTIONS:
            raise DispositionError(f"{rel}: action 必須是 {ACTIONS} 之一，得到 {action!r}")
        reason = str(spec.get("reason") or "").strip()
        if not reason:
            raise DispositionError(f"{rel}: reason 必填")
        cleaned[rel] = {"action": action, "reason": reason}

    return {
        "adjudicated_by": adjudicated_by,
        "incident": (str(raw["incident"]) if raw.get("incident") else None),
        "paths": cleaned,
    }


# ── preflight ────────────────────────────────────────────────────────────────

def _git(repo_root: Path, *args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(Path(repo_root).resolve()), *args],
        capture_output=True, text=True, timeout=_GIT_TIMEOUT_S, check=check,
        **git_writer_subprocess_kwargs(),
    )


def _head_has(repo_root: Path, rel: str) -> bool:
    """該路徑在 HEAD 拿得回來嗎（tracked 且未新增）。"""
    return _git(repo_root, "cat-file", "-e", f"HEAD:{rel}").returncode == 0


def preflight(repo_root: Path, disposition: dict[str, Any]) -> dict[str, Any]:
    """逐路徑判定「可不可以照這份裁決動手」，不寫任何東西。

    ``ready`` 為 False 時呼叫端必須整份放棄 —— 部分落地會讓下一班面對一個既非原狀
    也非裁決結果的工作區，那比不動更難處理。
    """
    repo_root = Path(repo_root)
    specs: dict[str, dict[str, str]] = disposition["paths"]
    quarantined = quarantine_covered_paths(repo_root)
    dirty = dirty_paths(repo_root)

    per_path: dict[str, dict[str, Any]] = {}
    refusals: list[str] = []
    for rel, spec in sorted(specs.items()):
        action = spec["action"]
        in_head = _head_has(repo_root, rel)
        retrievable = (rel in quarantined) or in_head
        is_dirty = rel in dirty
        entry: dict[str, Any] = {
            "action": action,
            "reason": spec["reason"],
            "dirty_in_main": is_dirty,
            "in_quarantine": rel in quarantined,
            "in_head": in_head,
            "retrievable": retrievable,
        }
        if action in ("commit", "delete") and not retrievable:
            entry["verdict"] = "refused"
            entry["detail"] = "處置前 bytes 不可取回（quarantine ref 與 HEAD 都沒有）"
            refusals.append(f"{rel}: {entry['detail']}")
        elif action == "leave":
            entry["verdict"] = "leave"
        elif not is_dirty:
            entry["verdict"] = "noop"
            entry["detail"] = "已不髒在 main checkout —— 無事可做"
        else:
            entry["verdict"] = "ready"
        per_path[rel] = entry

    return {
        "ready": not refusals,
        "paths": per_path,
        "refusals": refusals,
        "actionable": sorted(r for r, e in per_path.items() if e["verdict"] == "ready"),
    }


# ── apply ────────────────────────────────────────────────────────────────────

def _restore_or_remove(repo_root: Path, rel: str) -> str:
    """``delete`` 的實作：tracked 就還原成 HEAD，untracked 就移除工作區副本。

    兩種情況都不碰 quarantine ref —— bytes 的保存與工作區的收拾是兩件事，
    這裡只做後者。
    """
    if _head_has(repo_root, rel):
        proc = _git(repo_root, "checkout", "HEAD", "--", rel)
        if proc.returncode != 0:
            raise DispositionError(f"{rel}: git checkout 失敗 — {(proc.stderr or '').strip()[-200:]}")
        return "restored_from_head"
    target = Path(repo_root) / rel
    try:
        target.unlink()
    except FileNotFoundError:  # silent-ok: 目標已不存在即為所求的終態。
        return "already_absent"
    except OSError as exc:
        raise DispositionError(f"{rel}: 移除失敗 — {exc}") from exc
    return "removed_untracked"


def apply_disposition(
    repo_root: Path,
    disposition: dict[str, Any],
    *,
    actor: str,
    dry_run: bool = False,
    lock_timeout_s: float = 300.0,
) -> dict[str, Any]:
    """在 canonical writer lock 下把裁決落地，並機械驗證前後狀態。

    整份 all-or-nothing：preflight 一旦有拒絕就完全不動手。lock 內會**重跑**
    preflight —— 等鎖那段時間裡別的 writer 可能已經改變了工作區，用鎖外的舊判斷
    動手正是併發事故的標準形狀。
    """
    repo_root = Path(repo_root).resolve()
    specs: dict[str, dict[str, str]] = disposition["paths"]
    declared = set(specs)

    outside = preflight(repo_root, disposition)
    if not outside["ready"]:
        return {"applied": False, "stage": "preflight", **outside}
    if dry_run:
        return {"applied": False, "stage": "dry_run", **outside}

    require_canonical_main_checkout(repo_root)

    with git_writer_lock(repo_root, actor=actor, timeout_s=lock_timeout_s):
        inside = preflight(repo_root, disposition)
        if not inside["ready"]:
            return {"applied": False, "stage": "preflight_under_lock", **inside}

        dirty_before = dirty_paths(repo_root)
        results: dict[str, str] = {}

        # delete 先做：它只會讓路徑變乾淨，不影響後續 commit 的 pathspec。
        for rel in inside["actionable"]:
            if specs[rel]["action"] == "delete":
                results[rel] = _restore_or_remove(repo_root, rel)

        to_commit = [r for r in inside["actionable"] if specs[r]["action"] == "commit"]
        commit_sha: str | None = None
        if to_commit:
            add = _git(repo_root, "add", "--", *to_commit)
            if add.returncode != 0:
                raise DispositionError(f"git add 失敗 — {(add.stderr or '').strip()[-300:]}")
            message = _commit_message(disposition, to_commit)
            # `git commit -- <paths>` 只提交指定路徑，index 裡別人的東西一概不動。
            commit = _git(repo_root, "commit", "-m", message, "--", *to_commit)
            if commit.returncode != 0:
                raise DispositionError(
                    f"git commit 失敗 — {(commit.stderr or commit.stdout or '').strip()[-300:]}"
                )
            head = _git(repo_root, "rev-parse", "HEAD")
            commit_sha = (head.stdout or "").strip() or None
            for rel in to_commit:
                results[rel] = "committed"

        # ── 事後機械驗證 ──
        dirty_after = dirty_paths(repo_root)
        still_dirty = sorted(r for r in inside["actionable"] if r in dirty_after)
        collateral = sorted((dirty_before ^ dirty_after) - declared)
        if collateral:
            warn("foreign_disposition",
                 "偵測到清單外的 dirty 變化 —— 不變式 1 被破壞",
                 paths=collateral[:20])

        return {
            "applied": True,
            "stage": "applied",
            "actor": actor,
            "adjudicated_by": disposition["adjudicated_by"],
            "incident": disposition.get("incident"),
            "results": results,
            "commit": commit_sha,
            "still_dirty": still_dirty,
            "collateral": collateral,
            "verified": not still_dirty and not collateral,
            "paths": inside["paths"],
        }


def _commit_message(disposition: dict[str, Any], paths: list[str]) -> str:
    incident = disposition.get("incident") or "n/a"
    adjudicated_by = str(disposition.get("adjudicated_by") or "")
    prefix = "[codex] " if adjudicated_by.startswith("codex") else ""
    head = (
        f"{prefix}chore(foreign): 落地 {len(paths)} 個已裁決路徑 "
        f"(incident {incident})"
    )
    body = "\n".join(
        f"- {rel}: {disposition['paths'][rel]['reason']}" for rel in paths
    )
    return (
        f"{head}\n\n{body}\n\n"
        f"adjudicated_by: {disposition['adjudicated_by']}\n"
        f"actuator: volpred.ops.foreign_disposition\n"
    )


# ── CLI ──────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--disposition", required=True, help="逐路徑裁決 JSON")
    ap.add_argument("--actor", default=os.environ.get("VOLPRED_TASK_CLAIM_OWNER", ""),
                    help="writer lock actor（預設取 $VOLPRED_TASK_CLAIM_OWNER）")
    ap.add_argument("--apply", action="store_true", help="真的落地；預設只做 preflight")
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parents[3]))
    args = ap.parse_args(argv)

    try:
        disposition = load_disposition(args.disposition)
    except DispositionError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2

    repo_root = Path(args.repo)
    if not args.apply:
        report = preflight(repo_root, disposition)
        print(json.dumps({"ok": report["ready"], "dry_run": True, **report},
                         ensure_ascii=False, indent=2))
        return 0 if report["ready"] else 1

    actor = str(args.actor).strip()
    if not actor:
        print(json.dumps(
            {"ok": False, "error": "--actor 或 $VOLPRED_TASK_CLAIM_OWNER 必須非空"},
            ensure_ascii=False, indent=2))
        return 2

    try:
        report = apply_disposition(repo_root, disposition, actor=actor)
    except DispositionError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    report["ok"] = bool(report.get("verified"))
    report["ts"] = datetime.now(timezone.utc).isoformat()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
