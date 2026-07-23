"""CI trigger for scripts/audit_enforcement_map.py (WS-F1, ops master plan).

The audit itself is the single owner of the map-vs-disk consistency concern
(Enforcement Layer Map in loop-health-and-dreaming.md vs settings.json /
pretooluse deny list / CI workflows / git hooks). This test is only a trigger
point so pytest.yml makes a stale map a red build — same pattern as the
source-encoding audit riding pytest collection. Do not add a second wiring.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
AUDIT = REPO_ROOT / "scripts" / "audit_enforcement_map.py"


def test_enforcement_map_matches_disk() -> None:
    proc = subprocess.run(
        [sys.executable, str(AUDIT)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, (
        "Enforcement Layer Map is out of sync with disk — update "
        ".claude/skills/platform-ops-manager/references/loop-health-and-dreaming.md "
        "in the same commit as the hook/CI change.\n"
        f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
    )
