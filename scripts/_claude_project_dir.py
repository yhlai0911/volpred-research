#!/usr/bin/env python3
"""共用 helper：偵測目前 repo 對應的 Claude Code session log 目錄（跨 Mac/Linux）。

背景（2026-07-02 repo 搬家 incident，2026-07-03 修復）：
repo 從 ``~/Desktop/volpred-research`` 搬到 ``~/volpred-research`` 後，Claude
Code 的 session log 目錄 slug 隨之從 ``-Users-<user>-Desktop-volpred-research``
換成 ``-Users-<user>-volpred-research``。舊 slug 目錄仍然存在（尚未刪除）但已
停止寫入（frozen）。任何 hardcode 舊 slug、或「舊 slug 存在就優先回傳」的偵測
邏輯，都會讓 token 用量報表 / session drill-down / dreaming review 讀到 stale
資料，漏算搬家之後的所有 session（詳見 ``docs/error_log.md`` 2026-07-03 entry）。

偵測策略（優先序）：
  (a) 動態從目前 repo root 絕對路徑推導 slug（``/`` -> ``-``），直接命中就用；
      這個方法不需要知道使用者名稱、不 hardcode "Desktop"，Mac / Linux 都適用。
  (b) 若推導出的目錄不存在（例如 repo 又搬家、或在還沒建 session 的新機器上跑），
      改選 ``~/.claude/projects/`` 下名稱含 "volpred"、且優先排除 worktree 分支
      目錄、mtime 最新的那個目錄 —— 最有可能是「目前真正在寫的」目錄。
  (c) 完全找不到任何候選目錄時，回傳依 (a) 推導出來的（可能不存在的）路徑，
      讓呼叫端自己處理 "目錄不存在" 的情況（沿用既有呼叫端行為）。

任何走到 (b)/(c) fallback 分支都會發出 warn（不 silent-fail）；優先用
``volpred.ops.diagnostics.warn``，import 不到時退回 stderr print。
"""
from __future__ import annotations

import sys
from pathlib import Path

__all__ = ["detect_claude_projects_dir", "detect_project_slug", "repo_root"]


def _warn(tag: str, msg: str, **ctx) -> None:
    try:
        from volpred.ops.diagnostics import warn as _diag_warn

        _diag_warn(tag, msg, **ctx)
        return
    except Exception:
        # diagnostics 模組 import 不到時退回 stderr —— warning 不 silent-drop
        extra = " | ".join(f"{k}={v}" for k, v in ctx.items())
        line = f"[{tag}] WARN {msg}"
        if extra:
            line += f" | {extra}"
        print(line, file=sys.stderr)


def repo_root() -> Path:
    """回傳目前 repo 的絕對根目錄（本檔案固定放在 ``scripts/`` 下，上一層即為 root）。"""
    return Path(__file__).resolve().parent.parent


def detect_project_slug(root: Path | None = None) -> str:
    """把 repo root 絕對路徑轉成 Claude Code project 目錄的 slug 格式（``/`` -> ``-``）。"""
    r = (root or repo_root()).resolve()
    return str(r).replace("/", "-")


def detect_claude_projects_dir(root: Path | None = None) -> Path:
    """偵測目前 repo 對應、且「目前活躍在寫」的 ``~/.claude/projects/<slug>`` 目錄。"""
    base = Path.home() / ".claude" / "projects"
    slug = detect_project_slug(root)
    candidate = base / slug
    if candidate.exists():
        return candidate

    if not base.exists():
        _warn(
            "claude_project_dir",
            "~/.claude/projects 不存在，回傳推導路徑（可能不存在）",
            base=str(base),
            derived_slug=slug,
        )
        return candidate

    # Fallback: 名稱含 "volpred"、優先排除 worktree 分支目錄、依「目錄內最新
    # session jsonl 的 mtime」排序（不可用目錄本身的 st_mtime — 目錄 entry 的
    # mtime 會被 symlink / 子目錄新增等 metadata 異動打亂，不反映真正的
    # session 寫入活動；2026-07-03 修 bug 時實測踩到：舊 Desktop slug 目錄因
    # migration 建立 symlink/backup 而 mtime 比新目錄還新，若照抄目錄 mtime
    # 排序會選回已凍結的舊目錄，完全違背本 helper 的目的）。
    dirs = [d for d in base.iterdir() if d.is_dir()]
    named = [d for d in dirs if "volpred" in d.name.lower()]
    if not named:
        # 沒有任何目錄名稱含 "volpred" —— 不可 fallback 到 `dirs`（任意其他
        # repo 的 session 目錄）；那是比 crash 更危險的 wrong-source fallback
        # （Codex review 2026-07-03 抓到：原本 `pool = non_worktree or named or
        # dirs` 在 named 為空時會選到完全無關的 project）。寧可回傳推導路徑
        # （可能不存在），讓呼叫端自然走「目錄不存在」的既有處理路徑。
        _warn(
            "claude_project_dir",
            "找不到任何名稱含 volpred 的候選目錄，回傳推導路徑（可能不存在）— 不 fallback 到無關 project",
            base=str(base),
            derived_slug=slug,
        )
        return candidate
    non_worktree = [d for d in named if "worktree" not in d.name.lower()]
    pool = non_worktree or named

    def _latest_activity(d: Path) -> float:
        jsonls = list(d.glob("*.jsonl"))
        if not jsonls:
            return 0.0
        return max(f.stat().st_mtime for f in jsonls)

    chosen = max(pool, key=_latest_activity)
    _warn(
        "claude_project_dir",
        "預期 slug 目錄不存在，改用名稱含 volpred 且 mtime 最新的目錄",
        expected_slug=slug,
        fallback_dir=chosen.name,
    )
    return chosen


if __name__ == "__main__":
    d = detect_claude_projects_dir()
    print(f"repo_root         = {repo_root()}")
    print(f"derived_slug      = {detect_project_slug()}")
    print(f"detected_dir      = {d}")
    print(f"exists            = {d.exists()}")
    if d.exists():
        n_top = len(list(d.glob("*.jsonl")))
        print(f"jsonl(top-level)  = {n_top}")
