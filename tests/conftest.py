from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

os.environ.setdefault("PYTHONHASHSEED", "0")

# The four production side-effect guards are deliberately owned by the tracked
# repo-root conftest.py so they apply to BOTH tests/ and scripts/tests/. Do not
# re-state them here: a nested duplicate previously hid the fact that worktree
# agents had no root conftest at all. scripts/tests/test_dispatch_state.py pins
# the root owner and the four values mechanically.

# Keep legacy publisher fixtures deterministic across the anti-AI gate's
# 2026-07-13 production escalation date. Strict/blocking behavior is covered by
# targeted tests that set VOLPRED_ANTI_AI_GATE_MODE explicitly.
os.environ.setdefault("VOLPRED_ANTI_AI_GATE_MODE", "warn")
