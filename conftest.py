from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 2026-07-10: these four side-effect guards lived only in `tests/conftest.py`.
# A pytest conftest applies to its own directory tree, so the 58 tests under
# `scripts/tests/` ran with ALL of them unset — free to send real email, write
# production Supabase, read live Supabase, and rewrite canonical `storage/`
# state. Probed directly: a throwaway test dropped into `scripts/tests/` printed
# `None` for all four flags. The guards are stated here, at the
# repo root, so no test tree can be born outside them. This is the single Python
# enforcement owner; nested conftests must not re-state these assignments.
os.environ["VOLPRED_NO_EMAIL"] = "1"
os.environ["VOLPRED_NO_REMOTE_WRITE"] = "1"
os.environ["VOLPRED_NO_REMOTE_READ"] = "1"
os.environ["VOLPRED_NO_CANONICAL_WRITE"] = "1"
_termination_test_dir = Path(tempfile.mkdtemp(prefix="volpred-pytest-termination-"))
os.environ["VOLPRED_TERMINATION_LEDGER_PATH"] = str(
    _termination_test_dir / "termination_intents.jsonl"
)

# 2026-07-14: this file was .gitignore'd (`/conftest.py`, ignored as a "stray")
# for the whole four days the guards above existed, so no CI runner ever had it.
# The suite that was supposed to be un-escapable ran on the runner with
# VOLPRED_NO_REMOTE_READ unset. Nobody could see it locally, because locally the
# file is right there. That is the entire bug class the plugin below closes:
# a local run and a CI run reading different trees.


def pytest_configure(config) -> None:
    from scripts.ci_parity import install

    install(config)


# 2026-07-19: `task_pool_claim complete` asks `volpred.ops.dispatch_burst` whether a
# burst window is open, and when one is it calls `request_fire()` — a write to
# canonical `storage/ops/dispatch_state.json`. The default BURST_PATH is the LIVE
# repo file, so whether a unit test of `complete` took that branch depended on
# whether a burst window happened to be open on the machine running it. Green all
# week, then red the hour the owner opened a burst (CI run 29671078611's sibling
# failure). Reading live ops state is the leak; the write guard only made it loud.
#
# Same ownership rule as the four flags above: stated once, at the root, so no
# test tree can be born outside it. Tests that exercise the burst module itself
# pass `path=` explicitly and are unaffected.
@pytest.fixture(autouse=True)
def _isolate_burst_window(tmp_path_factory, monkeypatch):
    try:
        from volpred.ops import dispatch_burst
    except Exception:  # silent-ok: repos/checkouts without the module need no isolation
        return
    absent = tmp_path_factory.mktemp("burst") / "dispatch_burst.json"
    monkeypatch.setattr(dispatch_burst, "BURST_PATH", absent, raising=False)
    # `path: Path = BURST_PATH` binds at def time, so rebinding the module
    # attribute alone would leave every default still pointing at the live file.
    for name in ("read_window", "status", "active"):
        fn = getattr(dispatch_burst, name, None)
        if fn is not None and getattr(fn, "__kwdefaults__", None):
            monkeypatch.setitem(fn.__kwdefaults__, "path", absent)
