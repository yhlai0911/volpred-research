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

# 2026-06-23: test runs must never WRITE to production Supabase. A publish-style
# test (test_daily_digest_dup_exemption.py) whose per-test sync stub failed to
# apply synced two stub daily_digest rows (phase='test', identical MOVE-VIX
# content: mile_46918766 / mile_6d06f91c) to the LIVE feed — they surfaced on the
# 精選導讀 tab and had to be retracted. supabase_sync._post / _patch_where /
# _patch_where_returning honor this flag and no-op, so even with creds present
# (loaded from .env.local at import) and a missing per-test stub, no test can
# mutate prod. Structural backstop mirroring VOLPRED_NO_EMAIL above.
os.environ["VOLPRED_NO_REMOTE_WRITE"] = "1"
