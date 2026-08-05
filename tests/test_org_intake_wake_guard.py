"""Waking the coordinator is an outward effect; a throwaway root must never do it.

`org_intake.record_boss_message` wakes the manager so an owner message is acted on
in seconds rather than at the next 30-minute tick. The wake starts a *real*
coordinator session against the *real* repo, and it messages the owner.

On 2026-08-05 a test did exactly that. `tests/test_org_admin.py` runs the intake
CLI as a genuine subprocess with `tmp_path` as the org root, so the in-process
`monkeypatch` other tests use could not reach it: pytest woke a live coordinator,
which rehydrated from the pytest tmpdir and briefed itself on a fictional
organisation (one inbox item, no policy file, no active departments), then acted
on it. It also wrote `storage/logs/cron/org_manager_run.log`, which is what turned
the CI test-leak gate red.

The guard is on the root, not on the caller, because the caller cannot be trusted
to be in-process: direct import, subprocess, `uv run`, or an orphaned grandchild
all reach the same function. A root that is not the canonical one is never a
legitimate reason to wake anybody.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ORG_DIR = Path(__file__).resolve().parents[1] / "scripts" / "org"


@pytest.fixture(scope="module")
def intake():
    sys.path.insert(0, str(ORG_DIR))
    spec = importlib.util.spec_from_file_location(
        "org_intake_under_test", ORG_DIR / "org_intake.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_a_throwaway_root_is_refused_and_says_why(tmp_path, intake):
    outcome = intake._wake(tmp_path / "org", ["boss message"])

    assert outcome["woken"] is False
    assert "refused" in outcome["reason"]
    assert str(tmp_path) in outcome["reason"], (
        "the refusal must name the offending root, or the next person cannot tell "
        "a guarded refusal from a wake that simply failed"
    )


def test_the_refusal_never_imports_the_waker(tmp_path, intake, monkeypatch):
    """Refusing must happen before the import, not after a failed attempt."""
    def explode(*_args, **_kwargs):  # pragma: no cover - must never run
        raise AssertionError("wake_manager was reached from a non-canonical root")

    monkeypatch.setitem(
        sys.modules, "manager_tick", type(sys)("manager_tick")
    )
    sys.modules["manager_tick"].wake_manager = explode

    outcome = intake._wake(tmp_path / "org", ["boss message"])

    assert outcome["woken"] is False


def test_the_canonical_root_still_reaches_the_waker(intake, monkeypatch):
    """The guard must not turn the real path off — that would be a silent outage."""
    calls: list[tuple] = []
    stub = type(sys)("manager_tick")
    stub.wake_manager = lambda root, reasons, **kw: (
        calls.append((root, reasons, kw)) or {"woken": True, "reason": "stub"}
    )
    monkeypatch.setitem(sys.modules, "manager_tick", stub)

    outcome = intake._wake(intake.DEFAULT_ORG_ROOT, ["boss message"])

    assert outcome["woken"] is True
    assert calls, "the canonical root must still reach wake_manager"
    assert calls[0][2].get("respect_min_interval") is False, (
        "an owner message bypasses the tick interval on purpose"
    )
