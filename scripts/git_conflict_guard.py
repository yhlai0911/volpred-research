#!/usr/bin/env python3
"""AUTO_MERGE / conflict-marker watchdog (2026-06-28).

Root cause (docs/error_log.md 2026-06-28): two dispatchers write the same git
branch concurrently — the Claude hourly LaunchAgent and the always-on
codex_loop.sh — so a 3-way merge (or codex's internal git) can leave an orphaned
`.git/AUTO_MERGE` (no `.git/MERGE_HEAD`) and inject `<<<<<<<` conflict markers
into constantly-rewritten state files (feed.json / next_tasks.json /
work_log.json). Those files are then read by the live site + dispatcher =
corruption.

This guard is the deterministic backstop. It is fail-OPEN (never aborts the
caller) and idempotent (no-op on a clean tree):

  1. Re-assert `merge.ours.driver=true` so the `.gitattributes merge=ours`
     protection on canonical state files is always active.
  2. If `.git/AUTO_MERGE` exists but `.git/MERGE_HEAD` does not → orphaned
     half-merge: `git reset -q` (unstage) then remove `.git/AUTO_MERGE`.
  3. Scan tracked files for conflict markers (`git diff --check` +
     marker grep). Any tracked file carrying markers → restore the canonical
     HEAD blob (`git checkout HEAD -- <file>`).
  4. If anything was cleaned, emit a warn alert (visibility) and print a
     summary. Exit 0 always (a guard must not break the dispatch it guards).

Wire-in: run at the START of cron_hourly_dispatch.sh (every hour, before the
Claude/Codex dispatch) and standalone via cron. Safe to run anytime.

Usage:
    uv run python scripts/git_conflict_guard.py            # clean + report
    uv run python scripts/git_conflict_guard.py --dry-run  # report only
    uv run python scripts/git_conflict_guard.py --quiet    # only act, terse
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GIT_DIR = ROOT / ".git"
CONFLICT_MARKERS = ("<<<<<<< ", "=======", ">>>>>>> ")


def _run(args: list[str], check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(ROOT), *args],
        capture_output=True,
        text=True,
        check=check,
    )


def _log(msg: str) -> None:
    print(f"[git-conflict-guard] {msg}", flush=True)


def _ensure_ours_driver() -> None:
    """Idempotently assert the local `ours` merge driver the .gitattributes
    `merge=ours` rules depend on. Without it those rules silently no-op."""
    try:
        cur = _run(["config", "--get", "merge.ours.driver"]).stdout.strip()
        if cur != "true":
            _run(["config", "merge.ours.driver", "true"])
            _log("set merge.ours.driver=true")
    except Exception as exc:  # noqa: BLE001 - guard must not raise
        _log(f"WARN could not assert merge.ours.driver: {exc}")


def _orphaned_automerge() -> bool:
    automerge = GIT_DIR / "AUTO_MERGE"
    merge_head = GIT_DIR / "MERGE_HEAD"
    rebase = (GIT_DIR / "rebase-merge").exists() or (GIT_DIR / "rebase-apply").exists()
    # AUTO_MERGE without MERGE_HEAD and not mid-rebase = an interrupted/aborted
    # 3-way merge that git never finished — the corruption source.
    return automerge.exists() and not merge_head.exists() and not rebase


def _files_with_markers() -> list[str]:
    """Tracked working-tree files that contain conflict markers."""
    flagged: set[str] = set()
    # `git diff --check` reports conflict markers (and whitespace) with file:line.
    check = _run(["diff", "--check"])
    for line in (check.stdout or "").splitlines():
        if "conflict marker" in line.lower():
            path = line.split(":", 1)[0].strip()
            if path:
                flagged.add(path)
    # Belt-and-suspenders: grep tracked files for the marker tokens directly
    # (diff --check only sees unstaged; staged-but-marked needs this).
    grep = _run(["grep", "-l", "-E", r"^(<<<<<<< |>>>>>>> )", "--", "."])
    if grep.returncode in (0, 1):  # 0=matches, 1=no matches (both fine)
        for path in (grep.stdout or "").splitlines():
            p = path.strip()
            if p:
                flagged.add(p)
    return sorted(flagged)


def _send_alert(cleaned: list[str], orphan: bool) -> None:
    try:
        body = "\n".join(
            [
                "## 觸發條件",
                f"- git_conflict_guard 偵測到 {'orphaned AUTO_MERGE + ' if orphan else ''}"
                f"{len(cleaned)} 個 conflict-marker 檔，已自動清理",
                "- 受影響檔案：" + (", ".join(cleaned) if cleaned else "(僅 AUTO_MERGE，無 marker 檔)"),
                "",
                "## 影響",
                "- 這些是 live 站 + dispatcher 讀的 canonical 狀態檔；未清理會被下一次 commit "
                "永久污染。已還原 HEAD canonical 版本，運作不中斷。",
                "",
                "## 建議行動",
                "- 結構根因 = 雙 dispatcher（Claude hourly + codex_loop）並發寫同分支。"
                "已用 .gitattributes merge=ours + 本 guard 止血；長期解見 docs/error_log.md "
                "2026-06-28 entry（single-writer / commit-lock 決策）。",
            ]
        )
        tmp = ROOT / "storage" / "logs" / "_git_guard_alert.md"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(body, encoding="utf-8")
        subprocess.run(
            [
                "uv", "run", "volpred", "ops", "send-alert",
                "--level", "warn",
                "--title", f"git_conflict_guard 自動清理 {len(cleaned)} 衝突檔",
                "--body-md", str(tmp), "--force",
            ],
            cwd=str(ROOT), capture_output=True, text=True,
        )
        tmp.unlink(missing_ok=True)
    except Exception as exc:  # noqa: BLE001 - alert failure must not break guard
        _log(f"WARN alert send failed: {exc}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="report only, no mutation")
    ap.add_argument("--quiet", action="store_true", help="terse output")
    args = ap.parse_args()

    if not GIT_DIR.exists():
        _log("no .git dir — skip")
        return 0

    _ensure_ours_driver()

    orphan = _orphaned_automerge()
    marker_files = _files_with_markers()

    if not orphan and not marker_files:
        if not args.quiet:
            _log("clean — no orphaned AUTO_MERGE, no conflict markers")
        return 0

    _log(
        f"DETECTED orphaned_automerge={orphan} marker_files={len(marker_files)}: "
        f"{marker_files}"
    )
    if args.dry_run:
        _log("--dry-run: not mutating")
        return 0

    # 1) Clear orphaned half-merge state.
    if orphan:
        _run(["reset", "-q"])  # unstage any conflict-staged entries
        try:
            (GIT_DIR / "AUTO_MERGE").unlink(missing_ok=True)
            _log("removed orphaned .git/AUTO_MERGE")
        except Exception as exc:  # noqa: BLE001
            _log(f"WARN could not remove AUTO_MERGE: {exc}")

    # 2) Restore canonical HEAD blob for every marker-laden tracked file.
    cleaned: list[str] = []
    for path in marker_files:
        res = _run(["checkout", "HEAD", "--", path])
        if res.returncode == 0:
            cleaned.append(path)
            _log(f"restored canonical: {path}")
        else:
            _log(f"WARN could not restore {path}: {res.stderr.strip()[:120]}")

    _send_alert(cleaned, orphan)
    _log(f"DONE — cleaned {len(cleaned)} file(s), orphan_cleared={orphan}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
