"""Mechanical gate: no component may be left behind when an execution path retires.

2026-07-10, after the FOURTH cutover orphan. The 2026-07-04 dispatch-supervisor
cutover unloaded `com.volpred.hourly-dispatch`, whose shell wrapper
(`scripts/cron_hourly_dispatch.sh`) was the sole caller of several components.
Each one silently stopped running; each was found by hand, days later:

  - `scripts/hourly_dispatch_pregate.py`  — 6 days, ~6 wasted opus cold-loads/day
  - `scripts/git_conflict_guard.py`       — 6 days, unguarded concurrent writers

`.claude/rules/control-plane.md` §控制面 audit 的完成門檻 already says, in prose,
that retiring an execution path requires grepping the full population of things
wired into it. Prose did not stop orphans #3 and #4. Per that same rule ("同一
bug class 第二次出現起，交付物必須是機械 gate"), this is the gate.

Contract: every `scripts/*.py` the legacy wrapper actually EXECUTES must either
be referenced from the supervisor package (i.e. carried across the cutover), or
be declared dead here with a reason. There is no third option, and "nobody
noticed" stops being reachable.

When the legacy wrapper is finally deleted, delete this file with it.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LEGACY_WRAPPER = ROOT / "scripts" / "cron_hourly_dispatch.sh"
SUPERVISOR_PKG = ROOT / "scripts" / "dispatch_supervisor"

# `scripts/<something>.py` appearing on a line the shell actually runs.
_PY_REF = re.compile(r"scripts/([A-Za-z0-9_]+\.py)")

# Components deliberately NOT carried into the supervisor's fire path. Each key
# needs a reason that survives review — "unused" is not one.
_RETIRED_BY_DESIGN: dict[str, str] = {
    # Per-task model/topology routing happens inside the DISPATCHED AGENT
    # (scripts/continue_task_dispatch.py), not in the fire path: the supervisor
    # always spawns opus. See dispatch_supervisor/worker.py OPUS_MODEL.
    "model_router.py": "per-task routing runs inside the dispatched agent, not the fire path",
    # The unloaded wrapper needs a CLI boundary to write a durable signal
    # receipt before shell-owned kills. Operations Core imports the canonical
    # termination module directly, so carrying this compatibility adapter into
    # the supervisor would recreate a second termination owner.
    "termination_signal.py": "legacy-only CLI bridge; supervisor calls volpred.ops.termination directly",
    # This tripwire exists specifically to catch an accidental resurrection of
    # the retired wrapper. The active supervisor must never emit a
    # legacy_business_fire event merely because normal Operations Core work ran.
    "record_legacy_business_fire.py": "legacy-entry tripwire; active supervisor must not self-report as legacy",
}


def _executed_py_components() -> set[str]:
    """Script basenames the wrapper executes, ignoring comment-only lines.

    Comment lines matter: cron_hourly_dispatch.sh:181 *mentions* model_router.py
    in prose. A naive grep reports it as wired and hides a real orphan behind a
    false positive — which is exactly how a full-population sweep goes wrong.
    """
    found: set[str] = set()
    for raw in LEGACY_WRAPPER.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        found.update(_PY_REF.findall(line))
    return found


def _supervisor_sources() -> str:
    return "\n".join(
        p.read_text(encoding="utf-8")
        for p in sorted(SUPERVISOR_PKG.glob("*.py"))
    )


def test_legacy_wrapper_still_exists_or_this_gate_is_dead() -> None:
    # If someone deletes the wrapper, this whole file must go too — a gate that
    # silently passes because its input vanished is worse than no gate.
    assert LEGACY_WRAPPER.exists(), (
        f"{LEGACY_WRAPPER} is gone — delete scripts/tests/test_cutover_orphans.py "
        "along with it (see module docstring)."
    )


def test_parser_ignores_comment_only_mentions() -> None:
    # Pins the false-positive guard above: model_router.py is mentioned only in a
    # comment, so it must NOT be reported as executed.
    assert "model_router.py" not in _executed_py_components()


def test_every_executed_legacy_component_survived_the_cutover() -> None:
    executed = _executed_py_components()
    assert executed, "parser found no executed scripts/*.py — regex or wrapper changed"

    sources = _supervisor_sources()
    orphans = [
        name for name in sorted(executed)
        if name not in _RETIRED_BY_DESIGN and name not in sources
    ]

    assert not orphans, (
        "Cutover orphan(s): "
        + ", ".join(f"scripts/{n}" for n in orphans)
        + ".\nThese are executed by the (unloaded) legacy wrapper but referenced "
        "nowhere in scripts/dispatch_supervisor/. Either wire them into the "
        "supervisor's fire path, or add them to _RETIRED_BY_DESIGN with a reason."
    )


@pytest.mark.parametrize("name", sorted(_RETIRED_BY_DESIGN))
def test_retired_components_are_still_referenced_by_the_wrapper(name: str) -> None:
    # Keeps the allowlist from rotting into a list of names nobody uses: an entry
    # only earns its place while the wrapper still mentions the script.
    assert name in LEGACY_WRAPPER.read_text(encoding="utf-8"), (
        f"{name} is in _RETIRED_BY_DESIGN but the wrapper no longer mentions it — "
        "drop the stale allowlist entry."
    )
