"""Structural backstop: forbid writes to canonical `storage/` state under test.

Sibling of the `VOLPRED_NO_EMAIL` / `VOLPRED_NO_REMOTE_WRITE` gates set in
`tests/conftest.py`. Those two stop a test from reaching the outside world
(SMTP, Supabase); this one stops a test from rewriting the repo's own
single-source-of-truth JSON.

2026-07-10 incident: a full `pytest` run rewrote `storage/publication_candidates.json`.
`tests/test_refill_task_pool.py::test_research_reader_friendly_still_allows_general_companion`
monkeypatched `CANDIDATES` to a `tmp_path` file but not `ROOT`, and that tmp file
carried no `generated_at`. `refill_task_pool._ensure_candidates_fresh()` reads
`generated_at` to decide staleness, saw `None`, treated the candidates as stale,
and spawned the real `scripts/build_publication_candidates.py` — which resolves its
own output path from its own location, i.e. the live checkout. Same failure class as
the 2026-06-23 test that synced stub `daily_digest` rows to the live feed.

The env var is honored at the *writer*, not at each caller, so it holds no matter
how the writer is reached — direct import, `subprocess`, or `uv run` (env is
inherited by child processes).
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = ["CanonicalWriteBlocked", "canonical_writes_disabled", "guard_canonical_write"]

ENV_FLAG = "VOLPRED_NO_CANONICAL_WRITE"

# Directories under the repo root that hold single-source-of-truth state.
GUARDED_DIRS = ("storage",)


class CanonicalWriteBlocked(RuntimeError):
    """Raised when guarded code tries to write canonical state with the gate on."""


def _repo_root() -> Path:
    # src/volpred/ops/canonical_write.py -> ops -> volpred -> src -> <repo root>
    return Path(__file__).resolve().parents[3]


def canonical_writes_disabled() -> bool:
    return os.environ.get(ENV_FLAG) == "1"


def guard_canonical_write(path: str | os.PathLike[str]) -> None:
    """Raise if `path` is canonical state and the gate is on. Otherwise no-op.

    Paths outside the repo (`tmp_path` fixtures, scratch dirs) always pass, so a
    test that redirects its writer's output stays green.
    """
    if not canonical_writes_disabled():
        return

    target = Path(path).resolve()
    root = _repo_root()
    for name in GUARDED_DIRS:
        guarded = (root / name).resolve()
        if target == guarded or guarded in target.parents:
            raise CanonicalWriteBlocked(
                f"{ENV_FLAG}=1 blocks write to canonical state: {target}\n"
                f"A test tried to rewrite shared repo state. Redirect the writer's "
                f"output to a tmp_path (monkeypatch every path constant it reads, "
                f"not just the one you noticed), or stub the function that spawns it."
            )
