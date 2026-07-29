"""Mechanical gate: a retired wrapper's BEHAVIOUR must survive, not just its callees.

2026-07-10, after the FIFTH cutover orphan — and the first that
`test_cutover_orphans.py` structurally could not catch.

That gate asks "every `scripts/*.py` the legacy wrapper executes — did it survive?"
It found orphans #3 and #4. It could never have found #5, because #5 was not a
script the wrapper *called*. It was a shell function the wrapper *implemented*:

  `run_codex_failover()` — hand the hourly slot to `codex exec` when Claude's
  quota or auth is dead (2026-06-28 owner directive). The 2026-07-04 supervisor
  cutover reimplemented the wrapper's classification logic but not this. From
  then on, every Claude quota outage silently dropped every hourly slot until
  the quota reset, and the only signal was an email that said "quota exhausted"
  — indistinguishable from a healthy quota-blocked fire.

Nothing pointed at that function. No file imported it, no grep for a filename
surfaced it, and it was fail-open by construction (an absent failover looks
exactly like a failover that had nothing to do). Per control-plane.md — 同一 bug
class 第二次出現起，交付物必須是機械 gate — this is that gate for behaviour.

Contract: every shell function the legacy wrapper defines must either name the
supervisor symbol that carries its behaviour across the cutover (and that symbol
must actually exist), or be declared dead here with a reason.

The archived wrapper remains immutable rollback evidence.  This gate reads that
archive while separately proving the executable `scripts/` entrypoint is gone.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LEGACY_WRAPPER = ROOT / "scripts" / "_legacy" / "cron_hourly_dispatch.sh"
LIVE_WRAPPER = ROOT / "scripts" / "cron_hourly_dispatch.sh"
SUPERVISOR_PKG = ROOT / "scripts" / "dispatch_supervisor"

# `name() {` at the start of a line — how every function in the wrapper is defined.
_FUNC_DEF = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\(\)")

# Each wrapper function → a symbol in scripts/dispatch_supervisor/ that carries
# its behaviour. The value is grepped for in the supervisor sources, so a
# renamed/deleted successor fails this gate rather than rotting quietly.
_CARRIED_ACROSS: dict[str, str] = {
    # The orphan this gate was born from. Restored 2026-07-10.
    "run_codex_failover": "run_codex_failover",
    # Quota classification: the shell tagged the string, worker.py regex-classifies it.
    "_note_quota": "QUOTA_RE",
    # Auth probe before spending a fire on a dead credential.
    "run_auth_preflight": "AUTH_RE",
    "send_auth_preflight_alert": "send_auth_alert",
    # Alert plumbing: `volpred ops send-alert --body-md <tmp>`.
    "run_send_alert": "send-alert",
    # One `claude -p` attempt with its timeout + kill ladder.
    "run_one_attempt": "_run_one_attempt",
}

# Behaviour deliberately NOT carried across. A reason that survives review;
# "unused" is not one.
_BEHAVIOUR_RETIRED_BY_DESIGN: dict[str, str] = {
    # The shell trap that reaped perl-alarm/watchdog children on wrapper exit.
    # The supervisor spawns each worker into its own PGID (start_new_session=True)
    # and kills the group directly — see worker._kill_pgid + procutil. There is no
    # trap-driven cleanup left to carry.
    "cleanup": "PGID-isolated kill replaces the shell exit trap (worker._kill_pgid)",
}


def _wrapper_text() -> str:
    return LEGACY_WRAPPER.read_text(encoding="utf-8")


def _defined_functions() -> set[str]:
    return {
        m.group(1)
        for line in _wrapper_text().splitlines()
        if (m := _FUNC_DEF.match(line))
    }


def _supervisor_sources() -> str:
    return "\n".join(
        p.read_text(encoding="utf-8") for p in sorted(SUPERVISOR_PKG.glob("*.py"))
    )


def test_legacy_wrapper_is_archived_and_not_live() -> None:
    assert LEGACY_WRAPPER.exists(), (
        f"{LEGACY_WRAPPER} is gone — the behaviour transfer cannot be audited."
    )
    assert not LIVE_WRAPPER.exists(), (
        f"{LIVE_WRAPPER} resurrected the physically retired dispatcher."
    )


def test_parser_finds_the_wrapper_functions() -> None:
    found = _defined_functions()
    assert found, "parser found no shell functions — regex or wrapper changed"
    # The orphan that motivated this gate must be visible to the parser, or the
    # gate is inspecting nothing.
    assert "run_codex_failover" in found


def test_every_wrapper_behaviour_survived_the_cutover() -> None:
    defined = _defined_functions()
    accounted = set(_CARRIED_ACROSS) | set(_BEHAVIOUR_RETIRED_BY_DESIGN)
    unaccounted = sorted(defined - accounted)

    assert not unaccounted, (
        "Wrapper function(s) with no declared fate: "
        + ", ".join(unaccounted)
        + ".\nEach shell function the legacy wrapper defines is BEHAVIOUR that either "
        "survived the supervisor cutover or was dropped on purpose. Add it to "
        "_CARRIED_ACROSS (naming the supervisor symbol) or to "
        "_BEHAVIOUR_RETIRED_BY_DESIGN (with a reason). Orphan #5 (run_codex_failover) "
        "went unnoticed for 6 days precisely because nothing forced this choice."
    )


@pytest.mark.parametrize("func,symbol", sorted(_CARRIED_ACROSS.items()))
def test_carried_behaviour_actually_exists_in_supervisor(func: str, symbol: str) -> None:
    sources = _supervisor_sources()
    assert symbol in sources, (
        f"{func}() is declared as carried across via `{symbol}`, but that symbol "
        f"appears nowhere in scripts/dispatch_supervisor/. Either the successor was "
        f"renamed (update the mapping) or the behaviour was lost (restore it) — this "
        f"is the exact shape of the 2026-07-10 codex-failover orphan."
    )


@pytest.mark.parametrize("func", sorted(_CARRIED_ACROSS) + sorted(_BEHAVIOUR_RETIRED_BY_DESIGN))
def test_mappings_do_not_rot(func: str) -> None:
    # An entry only earns its place while the wrapper still defines the function.
    assert func in _defined_functions(), (
        f"{func} is mapped here but the wrapper no longer defines it — drop the entry."
    )
