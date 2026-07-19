"""Regression test against the VERBATIM ALFRED raw response.

Why this file exists, separately from test_event_dates_release_selection.py:

The 42 tests that were green when Codex reviewed k528 all fed `release_dates`
a *hand-built* fixture in which the same-month duplicate entries had already
been removed. So they exercised the selection rule against input that could
not express the bug. The old per-month `max()` rule shipped 6 wrong NFP event
dates and flipped a significance result with a fully green suite.

The fix for a fixture that cannot express the bug is not a better assertion —
it is real input. This module pins `_fetch`'s actual bytes for release id 50
(Employment Situation, 2005-01-01..2026-07-19, 264 entries) and asserts the
six regular releases survive selection.

Fixture: tests/fixtures/fred_release_50_nfp_raw_20260719.json (never de-duplicate
it — the duplicate pairs ARE the regression surface).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from volpred.data import event_dates

_FIXTURE = Path(__file__).parent / "fixtures" / "fred_release_50_nfp_raw_20260719.json"

# The six months ALFRED returns twice for, with the regular Employment Situation
# release and the off-cycle entry (annual seasonal-factor / benchmark revisions,
# filed against the same release id LATER in the month). Verified against the
# live API on 2026-07-19; the right-hand column is exactly what the old max()
# rule picked and what k528's contaminated run treated as NFP event days.
OFF_CYCLE_PAIRS = {
    "2006-05": ("2006-05-05", "2006-05-08"),
    "2012-12": ("2012-12-07", "2012-12-12"),
    "2013-05": ("2013-05-03", "2013-05-06"),
    "2020-05": ("2020-05-08", "2020-05-11"),
    "2024-01": ("2024-01-05", "2024-01-10"),
    "2024-08": ("2024-08-02", "2024-08-21"),
}


@pytest.fixture(autouse=True)
def _sandbox_cache_dir(monkeypatch, tmp_path):
    # No test may touch the canonical storage/data cache dir (CI repo-state guard).
    monkeypatch.setattr(event_dates, "_CACHE_DIR", tmp_path)


@pytest.fixture
def raw_response() -> list[str]:
    return json.loads(_FIXTURE.read_text())["release_dates"]


@pytest.fixture
def selected(monkeypatch, raw_response) -> list[str]:
    monkeypatch.setattr(event_dates, "_fetch", lambda *_a, **_kw: list(raw_response))
    idx = event_dates.release_dates("NFP_US", "2005-01-01", "2026-07-19", use_cache=False)
    return [str(d.date()) for d in idx]


def test_fixture_still_carries_the_duplicate_months(raw_response):
    """Guard the guard: if someone 'cleans' the fixture, the suite goes quiet again."""
    by_month: dict[str, list[str]] = {}
    for d in raw_response:
        by_month.setdefault(d[:7], []).append(d)
    multi = {m: v for m, v in by_month.items() if len(v) > 1}
    assert set(multi) == set(OFF_CYCLE_PAIRS), (
        "fixture must keep exactly the six same-month duplicate pairs verbatim; "
        f"got {sorted(multi)}"
    )
    for month, (regular, off_cycle) in OFF_CYCLE_PAIRS.items():
        assert sorted(multi[month]) == [regular, off_cycle]


def test_regular_release_wins_in_every_duplicate_month(selected):
    for month, (regular, off_cycle) in OFF_CYCLE_PAIRS.items():
        in_month = [d for d in selected if d.startswith(month)]
        assert in_month == [regular], f"{month}: expected {regular}, got {in_month}"
        assert off_cycle not in selected, f"{off_cycle} is an off-cycle revision, not an NFP event"


def test_selection_is_one_per_month_and_complete(selected, raw_response):
    months_in = {d[:7] for d in raw_response}
    months_out = [d[:7] for d in selected]
    assert len(months_out) == len(set(months_out)), "more than one event date in some month"
    assert set(months_out) == months_in, "selection dropped or invented a month"
    assert len(selected) == 258


def test_max_rule_would_reproduce_the_k528_contamination(raw_response):
    """Mutation check: the OLD rule must fail this file, or it proves nothing.

    Without this, a future refactor could silently restore max() and the two
    assertions above would be the only thing standing in the way — this pins
    WHY they matter.
    """
    by_month: dict[str, list[str]] = {}
    for d in raw_response:
        by_month.setdefault(d[:7], []).append(d)
    old_rule = {m: max(v) for m, v in by_month.items()}
    wrong = {m: old_rule[m] for m, (regular, _) in OFF_CYCLE_PAIRS.items() if old_rule[m] != regular}
    assert wrong == {m: off for m, (_, off) in OFF_CYCLE_PAIRS.items()}, (
        "the old max() rule must pick exactly the six off-cycle dates on this input"
    )
