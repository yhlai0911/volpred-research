from __future__ import annotations

import subprocess
import sys

from .common import PROJECT_ROOT, project_path
from scripts.supabase_sync import sync_full


def sync_all(storage_dir: str = "storage") -> dict:
    return sync_full(storage_dir)


def run_daily_update() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(project_path("scripts", "daily_update.py"))],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def run_recalc_metrics() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(project_path("scripts", "recalc_metrics.py"))],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
