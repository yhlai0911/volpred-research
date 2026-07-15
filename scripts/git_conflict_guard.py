#!/usr/bin/env python3
"""Read-first AUTO_MERGE / conflict-marker watchdog.

The preserved 2026-06-28 AUTO_MERGE tree contains Git's ``Updated upstream`` /
``Stashed changes`` markers: the direct producer was an unresolved
``stash pop/apply`` conflict.  Multiple writers sharing one checkout were the
structural condition that made the surrounding stash transaction unsafe.

This guard is deliberately *not* a repair writer.  It never resets the shared
index and never checks out HEAD over an author's working bytes.  It may remove
only a provably empty orphan AUTO_MERGE pseudo-ref: no MERGE_HEAD/rebase, no
unmerged index entries, and no tracked conflict markers.  That tiny mutation is
performed under the repository-wide Git-writer lease.  Anything ambiguous is
left byte-for-byte intact and reported for investigation.

Wire-in: run at the START of cron_hourly_dispatch.sh (every hour, before the
Claude/Codex dispatch) and standalone via cron. Safe to run anytime.

Usage:
    uv run python scripts/git_conflict_guard.py            # clean + report
    uv run python scripts/git_conflict_guard.py --dry-run  # report only
    uv run python scripts/git_conflict_guard.py --quiet    # only act, terse
"""
from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
from pathlib import Path

# This script is copied into hermetic incident probes whose Git status is itself
# evidence. Dynamic-loading the owner must not create an untracked __pycache__
# and make a second read-only guard fire look dirty.
sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
_OWNER_PATH = ROOT / "src/volpred/ops/git_writer_lock.py"
_SPEC = importlib.util.spec_from_file_location("_volpred_guard_git_lock", _OWNER_PATH)
if _SPEC is None or _SPEC.loader is None:  # pragma: no cover - corrupt deploy
    raise SystemExit(f"cannot load Git writer lock owner: {_OWNER_PATH}")
_OWNER = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _OWNER
_SPEC.loader.exec_module(_OWNER)
GitWriterLockError = _OWNER.GitWriterLockError
git_writer_lock = _OWNER.git_writer_lock
git_writer_subprocess_kwargs = _OWNER.git_writer_subprocess_kwargs

CONFLICT_MARKERS = ("<<<<<<< ", "=======", ">>>>>>> ")


def _run(args: list[str], check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(ROOT), *args],
        capture_output=True,
        text=True,
        check=check,
        **git_writer_subprocess_kwargs(),
    )


def _log(msg: str) -> None:
    print(f"[git-conflict-guard] {msg}", flush=True)


def _git_dir() -> Path | None:
    probe = _run(["rev-parse", "--path-format=absolute", "--git-dir"])
    value = (probe.stdout or "").strip()
    if probe.returncode != 0 or not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def _orphaned_automerge() -> bool:
    git_dir = _git_dir()
    if git_dir is None:
        return False
    automerge = git_dir / "AUTO_MERGE"
    merge_head = git_dir / "MERGE_HEAD"
    rebase = (git_dir / "rebase-merge").exists() or (git_dir / "rebase-apply").exists()
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


def _send_alert(marker_files: list[str], orphan: bool, *, cleared: bool) -> None:
    if cleared and not marker_files:
        _log("empty orphan-only cleanup — no owner alert")
        return
    try:
        body = "\n".join(
            [
                "## 觸發條件",
                f"- git_conflict_guard 偵測到 {'orphaned AUTO_MERGE + ' if orphan else ''}"
                f"{len(marker_files)} 個 conflict-marker 檔",
                "- 受影響檔案：" + (", ".join(marker_files) or "(無 marker；index 狀態不明)"),
                "",
                "## 影響",
                "- 這些是 live 站 + dispatcher 讀的 canonical 狀態檔；未清理會被下一次 commit "
                "永久污染。",
                "",
                "## 保全處理",
                "- guard 沒有 reset index，也沒有 checkout/覆寫任何檔案；現場 bytes 完整保留。",
                "- single-writer transaction lock 防止新的 writer 與現場交錯；請由作者檢視後收斂。",
            ]
        )
        tmp = ROOT / "storage" / "logs" / "_git_guard_alert.md"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(body, encoding="utf-8")
        subprocess.run(
            [
                "uv", "run", "volpred", "ops", "send-alert",
                "--level", "warn",
                "--title", f"git_conflict_guard 保留 {len(marker_files)} 個衝突檔待查",
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

    if _git_dir() is None:
        _log("no git dir — skip")
        return 0

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

    cleared = False
    has_unmerged = False
    try:
        with git_writer_lock(ROOT, actor="git-conflict-guard", timeout_s=5):
            # Recheck after acquiring: the producer may have resolved the state
            # while this watchdog waited.
            orphan = _orphaned_automerge()
            marker_files = _files_with_markers()
            unmerged = _run(["ls-files", "-u"])
            has_unmerged = unmerged.returncode != 0 or bool(unmerged.stdout.strip())
            if orphan and not marker_files and not has_unmerged:
                git_dir = _git_dir()
                if git_dir is not None:
                    (git_dir / "AUTO_MERGE").unlink(missing_ok=True)
                    cleared = True
                    _log("removed provably empty orphan AUTO_MERGE")
            elif orphan or marker_files or has_unmerged:
                _log(
                    "PRESERVED ambiguous conflict state — no reset/checkout; "
                    f"markers={len(marker_files)} unmerged={has_unmerged}"
                )
    except (GitWriterLockError, OSError) as exc:
        _log(f"WARN could not obtain safe cleanup lease; preserved state: {exc}")

    if not orphan and not marker_files and not has_unmerged:
        _log("state resolved before cleanup lease; nothing to report")
        return 0
    _send_alert(marker_files, orphan, cleared=cleared)
    _log(f"DONE — preserved {len(marker_files)} marker file(s), orphan_cleared={cleared}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
