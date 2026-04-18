from __future__ import annotations

import subprocess
from pathlib import Path

from .common import project_path
from .experiments import build_experiments_report

ROOT_CLUTTER = [
    ".DS_Store",
    ".codex-backups",
    ".next",
    ".pytest_cache",
    "__pycache__",
    "backups",
    "舊前端",
    ".worktree_tmp_k797.py",
    "CLAUDE.md.backup.2026-04-11",
    "texput.log",
]


def _safe_count(path: Path, *, pattern: str = "*", maxdepth: int | None = None) -> int:
    if not path.exists():
        return 0
    if maxdepth is None:
        return sum(1 for _ in path.glob(pattern))
    return sum(1 for item in path.iterdir() if item.match(pattern))


def build_hygiene_report() -> dict[str, object]:
    root = project_path()
    experiments_root = root / "experiments"
    clutter = [name for name in ROOT_CLUTTER if (root / name).exists()]
    experiments_report = build_experiments_report(root_path=root, limit=10)

    worktree_output = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    registered_worktrees = [
        line.split(" ", 1)[1]
        for line in worktree_output.splitlines()
        if line.startswith("worktree ")
    ]

    managed_worktrees_dir = root / ".claude" / "worktrees"
    managed_worktrees = sorted(
        path.name for path in managed_worktrees_dir.iterdir() if path.is_dir()
    ) if managed_worktrees_dir.exists() else []

    return {
        "root_clutter": clutter,
        "experiments_loose_files": sum(1 for path in experiments_root.iterdir() if path.is_file()) if experiments_root.exists() else 0,
        "experiments_top_level_dirs": sum(1 for path in experiments_root.iterdir() if path.is_dir()) if experiments_root.exists() else 0,
        "experiments_loose_by_extension": experiments_report["loose_files_by_extension"],
        "experiments_grouped_candidates": experiments_report["grouped_candidates"],
        "experiments_ungrouped_loose_files": experiments_report["ungrouped_loose_files"],
        "registered_worktrees": registered_worktrees,
        "managed_worktrees": managed_worktrees,
        "orphan_worktree_dirs": [
            name
            for name in managed_worktrees
            if str(managed_worktrees_dir / name) not in registered_worktrees
        ],
    }
