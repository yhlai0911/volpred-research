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

# 2026-04-20: test runs must never send real emails. Previously
# tests/test_content_release_pool.py fixtures mile_first_run / mile_sched_1
# triggered real SMTP via release_pool_by_settings → admin notifications
# reached user inbox describing non-existent articles. This gate is checked
# in email_notifier.py _send_email; must be set BEFORE any test imports
# that might transitively load the notifier.
os.environ["VOLPRED_NO_EMAIL"] = "1"
