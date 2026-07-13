from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 2026-07-10: these four side-effect guards lived only in `tests/conftest.py`.
# A pytest conftest applies to its own directory tree, so the 58 tests under
# `scripts/tests/` ran with ALL of them unset — free to send real email, write
# production Supabase, read live Supabase, and rewrite canonical `storage/`
# state. Probed directly: a throwaway test dropped into `scripts/tests/` printed
# `None` for all three of the first flags. The guards are stated here, at the
# repo root, so no test tree can be born outside them; `tests/conftest.py` keeps
# the incident history behind each one and re-asserts the same values.
os.environ["VOLPRED_NO_EMAIL"] = "1"
os.environ["VOLPRED_NO_REMOTE_WRITE"] = "1"
os.environ["VOLPRED_NO_REMOTE_READ"] = "1"
os.environ["VOLPRED_NO_CANONICAL_WRITE"] = "1"

# 2026-07-14: this file was .gitignore'd (`/conftest.py`, ignored as a "stray")
# for the whole four days the guards above existed, so no CI runner ever had it.
# The suite that was supposed to be un-escapable ran on the runner with
# VOLPRED_NO_REMOTE_READ unset. Nobody could see it locally, because locally the
# file is right there. That is the entire bug class the plugin below closes:
# a local run and a CI run reading different trees.


def pytest_configure(config) -> None:
    from scripts.ci_parity import install

    install(config)
