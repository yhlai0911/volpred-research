"""Adversarial regression test for the k528 calendar completeness gate.

WHY THIS FILE EXISTS
--------------------
Codex review round 4 (``review_verdict_v6.json``, reviewed_commit ``3098ad5b5``)
returned FAIL with exactly one blocking defect, quoted verbatim:

    completeness could be bypassed by putting a tail month into
    KNOWN_MISSING_MONTHS (which made the raw->selected check skip it) while the
    counter-check that would expose the false claim only scanned the selected
    span; adding the month to REVIEWED_MULTI_ENTRY_MONTHS as well kept it
    accepted

In plain terms: the sample could be silently shortened by one tail month while
every gate stayed green. Two individually-reasonable allowlists combined into a
back door.

The fix landed in ``726a34fb0``. That commit was never covered by a test, so the
only evidence the door was shut was the diff itself. This file is that missing
evidence: it reproduces the attack against the real release feed and asserts the
gate now refuses it.

WHAT MAKES THIS A GATE AND NOT DECORATION
-----------------------------------------
A test that asserts "it raises" proves nothing if the code raises on everything,
and a mutation harness proves nothing if it silently fails to mutate. Both holes
are closed here:

* ``test_honest_calendar_is_accepted`` pins the negative side -- the real,
  un-tampered calendar passes. A gate that always raises fails this.
* ``_load_gate`` asserts every mutation applied exactly once, so if the gate's
  source drifts the harness fails loudly instead of quietly testing nothing.
* ``test_bypass_succeeds_when_all_three_defences_are_disabled`` proves the
  attack really does exercise the back door: with the three checks neutralised
  the tampered calendar sails through. Without this, a passing suite could not
  distinguish "the defences work" from "the attack was never valid".

NO NETWORK, NO RERUN
--------------------
``k528_nfp_event_study.py`` is a flat top-level script with no ``__main__``
guard -- importing it would run the whole event study and overwrite the results
JSON. The gate and the four constants it reads are therefore lifted out with
``ast`` and executed in isolation, against a pinned real feed
(``data/nfp_release_feed_fixture.json``).
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pandas as pd
import pytest

HERE = Path(__file__).parent
SCRIPT = HERE / "k528_nfp_event_study.py"
FIXTURE = HERE / "data" / "nfp_release_feed_fixture.json"

# The gate function plus every module-level name its body reads. Lifting these
# out by name (rather than importing) is what keeps the event study from running.
GATE_FUNC = "check_calendar_is_complete"
GATE_CONSTANTS = (
    "KNOWN_MISSING_MONTHS",
    "REVIEWED_MULTI_ENTRY_MONTHS",
    "AMBIGUOUS_SAME_MONTH_GAP_DAYS",
    "MAX_WINDOW_SHORTFALL_DAYS",
    "LATEST_OBSERVED_RELEASE_DAY_OF_MONTH",
)

# The three checks added in 726a34fb0 to close the back door, keyed by the
# variable each one guards. Mutating `if X:` -> `if False and X:` disables one
# check while leaving the rest of the function -- and its dead-code computation
# of X -- untouched.
DEFENCES = {
    "unconditional_raw_to_selected": "if dropped:",
    "allowlists_must_not_overlap": "if both:",
    "known_missing_claim_checked_against_whole_raw_feed": "if bogus:",
}

# The check added for Codex round-5 B2. Kept separate from DEFENCES above because
# it closes a different attack: those three catch a month that vanishes from the
# SELECTION while the raw feed still has it. This one catches a month that
# vanishes from BOTH at once, which leaves every feed-relative check consistent.
ENDPOINT_DEFENCE = "if absent_required:"


def _load_gate(disable: tuple[str, ...] = ()):
    """Return the gate function, optionally with named defences neutralised.

    Raises if a requested mutation does not apply exactly once -- a mutation
    harness that silently no-ops would turn every assertion below into a lie.
    """
    tree = ast.parse(SCRIPT.read_text(), filename=str(SCRIPT))
    wanted = {GATE_FUNC, *GATE_CONSTANTS}
    found, chunks = set(), []
    for node in tree.body:
        name = None
        if isinstance(node, ast.FunctionDef) and node.name == GATE_FUNC:
            name = node.name
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name = node.target.id
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
        if name in wanted:
            found.add(name)
            chunks.append(ast.get_source_segment(SCRIPT.read_text(), node))

    missing = wanted - found
    assert not missing, (
        f"could not lift {sorted(missing)} out of {SCRIPT.name}. The gate was renamed or "
        "restructured; this test is no longer testing what it claims to test."
    )

    source = "\n\n".join(chunks)
    all_defences = {**DEFENCES, "endpoint_expectation": ENDPOINT_DEFENCE}
    for key in disable:
        needle = all_defences[key]
        n = source.count(needle)
        assert n == 1, (
            f"expected exactly one occurrence of {needle!r} (defence {key!r}) in the gate "
            f"source, found {n}. The mutation would not have applied -- refusing to report a "
            "green run that proved nothing."
        )
        source = source.replace(needle, needle.replace("if ", "if False and ", 1))

    ns: dict = {"pd": pd}
    exec(compile(source, f"<{SCRIPT.name}:{GATE_FUNC}>", "exec"), ns)
    return ns


def _feed():
    d = json.loads(FIXTURE.read_text())
    return d["raw_dates"], d["selected_dates"], d["requested_window"]


# --------------------------------------------------------------------------
# The attack, exactly as review_verdict_v6.json describes it.
# --------------------------------------------------------------------------
def _tamper(ns, *, multi_entry: bool):
    """Hide the last month of the sample behind both allowlists.

    Returns (selected, raw, start, end) for a calendar in which the final month
    really was published, is really absent from the analysis, and is excused by
    a fabricated KNOWN_MISSING_MONTHS entry plus a matching
    REVIEWED_MULTI_ENTRY_MONTHS entry.

    ``multi_entry=True`` additionally gives that month a second raw entry. That
    is the stronger form of the attack: with two entries the month trips the
    "unreviewed multi-entry month" check unless the attacker also registers it
    in REVIEWED_MULTI_ENTRY_MONTHS -- which is precisely why the v6 finding
    named both lists.
    """
    raw, selected, window = _feed()
    raw, selected = list(raw), list(selected)

    victim = max(d[:7] for d in raw)  # the tail month: 2026-03
    victim_dates = sorted(d for d in raw if d.startswith(victim))
    assert victim_dates, "fixture has no tail month to attack"

    if multi_entry:
        extra = f"{victim}-20"
        assert extra not in raw
        raw.append(extra)
        raw.sort()
        victim_dates = sorted(victim_dates + [extra])

    # The silent truncation: the month is published, but not analysed.
    selected = [d for d in selected if not d.startswith(victim)]

    # The two lies that used to make that truncation look legitimate.
    ns["KNOWN_MISSING_MONTHS"][victim] = (
        "FABRICATED. This month was published; the claim exists only to test that the "
        "gate refuses it."
    )
    ns["REVIEWED_MULTI_ENTRY_MONTHS"][victim] = {
        "raw": victim_dates,
        "report": victim_dates[0],
    }
    return selected, raw, window["start"], window["end"]


def test_honest_calendar_is_accepted():
    """Control. The gate must pass the real calendar, or 'it raised' proves nothing."""
    ns = _load_gate()
    raw, selected, w = _feed()
    out = ns[GATE_FUNC](selected, raw, w["start"], w["end"])
    assert out["n_raw_entries"] == len(raw)
    assert out["months_with_multiple_raw_entries"] == sorted(ns["REVIEWED_MULTI_ENTRY_MONTHS"])


@pytest.mark.parametrize("multi_entry", [False, True], ids=["single_entry", "multi_entry"])
def test_tail_month_hidden_behind_both_allowlists_is_rejected(multi_entry):
    """The v6 bypass, verbatim. Must fail closed."""
    ns = _load_gate()
    with pytest.raises(RuntimeError) as exc:
        ns[GATE_FUNC](*_tamper(ns, multi_entry=multi_entry))
    # It must be rejected as a truncation/false claim, not incidentally by the
    # window-coverage tolerance (a 1-month tail gap is inside that tolerance).
    assert "does not cover the requested window" not in str(exc.value)


@pytest.mark.parametrize("keep", sorted(DEFENCES))
def test_each_defence_independently_closes_the_bypass(keep):
    """Defence in depth: any one of the three is sufficient on its own."""
    ns = _load_gate(disable=tuple(k for k in DEFENCES if k != keep))
    with pytest.raises(RuntimeError):
        ns[GATE_FUNC](*_tamper(ns, multi_entry=True))


# --------------------------------------------------------------------------
# Codex round-5 B2: the endpoint month deleted from raw AND selected together.
#
# The three defences above all reason about the feed using the feed -- they
# compare raw against selected, or look inside the observed span. Delete a month
# from both sides at once and every one of them is satisfied: raw and selected
# still agree, the span is still gap-free, and the 70-day window tolerance is
# wide enough to swallow a whole month at either end. Codex reproduced this
# independently (259 raw / 253 selected either way, head shortfall 34d / tail
# shortfall 44d, both accepted).
# --------------------------------------------------------------------------
def _truncate_endpoint(end: str):
    """Delete the first or last month from BOTH the raw feed and the selection."""
    raw, selected, window = _feed()
    months = sorted({d[:7] for d in raw})
    victim = months[0] if end == "head" else months[-1]
    raw = [d for d in raw if not d.startswith(victim)]
    selected = [d for d in selected if not d.startswith(victim)]
    assert victim not in {d[:7] for d in raw}, "the mutation did not remove the month"
    assert victim not in {d[:7] for d in selected}
    return selected, raw, window["start"], window["end"], victim


@pytest.mark.parametrize("end", ["head", "tail"])
def test_endpoint_month_deleted_from_raw_and_selected_is_rejected(end):
    """The B2 attack. Must fail closed on the required-month expectation."""
    ns = _load_gate()
    selected, raw, start, stop, victim = _truncate_endpoint(end)
    with pytest.raises(RuntimeError) as exc:
        ns[GATE_FUNC](selected, raw, start, stop)
    msg = str(exc.value)
    assert victim in msg, f"the rejection must name the month that vanished; got: {msg}"
    # It must be caught by the endpoint expectation, not incidentally by the
    # coarse window tolerance -- which is the check that was already there and
    # already demonstrated not to catch this.
    assert "does not cover the requested window" not in msg
    assert "fully contains the publication window" in msg


@pytest.mark.parametrize("end", ["head", "tail"])
def test_endpoint_truncation_is_invisible_without_the_new_check(end):
    """Anti-vacuity, and the evidence that this defect was real.

    With ONLY the required-month check neutralised -- every pre-existing defence
    left intact -- the truncated calendar is ACCEPTED. That is the pre-fix
    behaviour Codex round-5 B2 described, reproduced here so the test above
    cannot be mistaken for a test of something that was already working.
    """
    ns = _load_gate(disable=("endpoint_expectation",))
    selected, raw, start, stop, victim = _truncate_endpoint(end)
    out = ns[GATE_FUNC](selected, raw, start, stop)  # no raise: the hole
    assert victim not in {d[:7] for d in selected}, "the month is silently gone"
    shortfall = out["window_coverage"]
    assert (
        shortfall["head_shortfall_days"] <= ns["MAX_WINDOW_SHORTFALL_DAYS"]
        and shortfall["tail_shortfall_days"] <= ns["MAX_WINDOW_SHORTFALL_DAYS"]
    ), "the 70d tolerance is what let this through; if it no longer does, re-derive this test"


def test_endpoint_expectation_is_derived_from_the_window_not_the_feed():
    """The property that makes the check work at all.

    If the required-month set were computed from the observed feed, deleting a
    month would delete the expectation with it. Narrowing the REQUESTED window
    must change the requirement; truncating the feed must not.
    """
    ns = _load_gate()
    raw, selected, w = _feed()
    full = ns[GATE_FUNC](selected, raw, w["start"], w["end"])["endpoint_expectation"]
    assert full["required_first_month"] == "2005-01"
    assert full["required_last_month"] == "2026-03"

    # Same feed, window asking for less -> fewer required months.
    narrowed = ns[GATE_FUNC](selected, raw, "2005-01-01", "2025-06-30")["endpoint_expectation"]
    assert narrowed["required_last_month"] == "2025-06"
    assert narrowed["n_required_months"] < full["n_required_months"]


def test_release_later_than_the_constant_invalidates_the_expectation():
    """The constant is self-policing.

    LATEST_OBSERVED_RELEASE_DAY_OF_MONTH is the premise of the required-month
    rule. A release later in its month than the constant allows means the premise
    has expired, and the run must say so rather than quietly under-requiring.
    """
    ns = _load_gate()
    raw, selected, w = _feed()
    victim = max(d[:7] for d in raw)
    late = f"{victim}-28"
    # MOVE the tail release later, do not add a second one: a second entry would
    # trip the duplicate-month and unreviewed-multi-entry checks first, and the
    # test would pass while proving nothing about the constant.
    raw = sorted([d for d in raw if not d.startswith(victim)] + [late])
    selected = sorted([d for d in selected if not d.startswith(victim)] + [late])
    with pytest.raises(RuntimeError, match="LATEST_OBSERVED_RELEASE_DAY_OF_MONTH"):
        ns[GATE_FUNC](selected, raw, w["start"], w["end"])


@pytest.mark.parametrize("multi_entry", [False, True], ids=["single_entry", "multi_entry"])
def test_bypass_succeeds_when_all_three_defences_are_disabled(multi_entry):
    """Anti-vacuity.

    With the three checks neutralised the tampered calendar must be ACCEPTED --
    the pre-726a34fb0 behaviour. If this test ever fails, the attack above is no
    longer reaching the back door and the green runs mean nothing.
    """
    ns = _load_gate(disable=tuple(DEFENCES))
    selected, raw, start, end = _tamper(ns, multi_entry=multi_entry)
    out = ns[GATE_FUNC](selected, raw, start, end)
    victim = max(d[:7] for d in raw)
    assert victim not in {d[:7] for d in selected}, "the month should be silently gone"
    assert out["known_missing_months"].get(victim), "and excused by a claim nobody checked"
