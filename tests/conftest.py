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

# The four production side-effect guards are deliberately owned by the tracked
# repo-root conftest.py so they apply to BOTH tests/ and scripts/tests/. Do not
# re-state them here: a nested duplicate previously hid the fact that worktree
# agents had no root conftest at all. scripts/tests/test_dispatch_state.py pins
# the root owner and the four values mechanically.

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
        return None  # silent-ok: test fingerprint records a missing path as state
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
