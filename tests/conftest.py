from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


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

# 2026-07-10: writes were blocked, reads were not. A test with an incomplete stub still
# queried LIVE production, so its verdict depended on today's prod data rather than its
# fixtures. tests/test_feed_sync.py stubbed `_fetch_supabase_articles` but not
# `_fetch_supabase_article_tags`; two of its tests were observed flipping between pass
# and fail across runs 40 minutes apart with no code change on that path.
# supabase_sync._urlopen raises on GET when this is set — loudly, because a silently
# empty read is indistinguishable from "nothing in the DB" and would let a missing stub
# produce a green test asserting the wrong thing.
os.environ["VOLPRED_NO_REMOTE_READ"] = "1"

# 2026-07-10: test runs must never rewrite canonical local state under storage/.
# test_refill_task_pool.py::test_research_reader_friendly_still_allows_general_companion
# monkeypatched refill_task_pool.CANDIDATES to a tmp_path file but left ROOT alone;
# the tmp file had no `generated_at`, so _ensure_candidates_fresh() read the age as
# unknown, judged the candidates stale, and shelled out to the real
# scripts/build_publication_candidates.py — which writes the live
# storage/publication_candidates.json. volpred.ops.canonical_write.guard_canonical_write
# honors this flag at the writer (env is inherited by subprocesses, so `uv run` children
# are covered too). Same failure class as VOLPRED_NO_REMOTE_WRITE above, one layer in:
# that gate protects prod, this one protects the repo's own source of truth.
os.environ["VOLPRED_NO_CANONICAL_WRITE"] = "1"

# Keep legacy publisher fixtures deterministic across the anti-AI gate's
# 2026-07-13 production escalation date. Strict/blocking behavior is covered by
# targeted tests that set VOLPRED_ANTI_AI_GATE_MODE explicitly.
os.environ.setdefault("VOLPRED_ANTI_AI_GATE_MODE", "warn")


# Canonical shared state. guard_canonical_write() stops the writers that opt in;
# this fingerprint backstops the ones that haven't, by naming the test that mutated it.
_CANONICAL_FILES = (
    "storage/publication_candidates.json",
    "storage/next_tasks.json",
    "storage/work_log.json",
    "storage/reports/feed.json",
    "storage/memory/knowledge.json",
    "storage/memory/thinking_journal.json",
    "storage/memory/experiment_experiences.json",
    # NOT storage/ops/dispatch_state.json — the live daemon stamps a heartbeat
    # into it every 30s, so this per-test fingerprint failed a random test on
    # every run whose span crossed a beat, and PHASE-Z (which runs the test gate
    # on this checkout after each fire) emailed the owner a CRITICAL "測試紅燈"
    # for it. Observed 2026-07-10: the error moved between tests across
    # back-to-back runs of the same suite. It is covered at the writer instead —
    # `dispatch_supervisor.state._atomic_write_json` raises on a canonical write
    # when VOLPRED_NO_CANONICAL_WRITE is set — which is precise where a
    # fingerprint cannot be: it knows WHO wrote, not merely that bytes moved.
)

# Dirs where the damage is a *new* file, not a modified one — a fixed file list
# cannot see those. event_jobs.materialize_* writes one ledger entry per event and
# defaults to storage_dir="storage", so a test that forgets to redirect it lands a
# real dedupe key in the live ledger. storage/ops/tasks/ is gitignored, so a stray
# TaskRecord there never shows up in `git status` — the dispatcher still reads it.
_CANONICAL_DIRS = ("storage/ops/event_ledger", "storage/ops/tasks")


def _stat_pair(path: Path) -> tuple[int, int] | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def _canonical_fingerprint() -> dict[str, object]:
    """stat() only — knowledge.json is ~50MB, never read it here."""
    prints: dict[str, object] = {rel: _stat_pair(ROOT / rel) for rel in _CANONICAL_FILES}
    for rel in _CANONICAL_DIRS:
        directory = ROOT / rel
        try:
            names = sorted(p.name for p in directory.iterdir())
        except OSError:
            prints[rel] = None
        else:
            prints[rel] = tuple((n, _stat_pair(directory / n)) for n in names)
    return prints


@pytest.fixture(autouse=True)
def _forbid_canonical_state_mutation():
    before = _canonical_fingerprint()
    yield
    after = _canonical_fingerprint()
    changed = [rel for rel in before if before[rel] != after[rel]]
    if changed:
        raise AssertionError(
            "This test mutated canonical shared state:\n  "
            + "\n  ".join(changed)
            + "\n\nTests must write to tmp_path only. Monkeypatch every path constant the "
            "writer reads (not just the obvious one), or stub the function that spawns it. "
            "Restore with `git checkout -- <path>`.\n"
            "False positive check: a scheduled job can rewrite these from the main checkout "
            "(publication_candidates_refresh runs daily 05:30 Taipei; publish_draft refreshes "
            "candidates after a feed change). Compare the file's mtime against "
            "storage/logs/cron/ before blaming the test."
        )
