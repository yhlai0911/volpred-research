"""Pin the CPI event dates that a "around the 13th" proxy gets wrong.

`storage/event_articles/us_cpi_2026_06_11_t0` used to hard-code its CPI release
calendar. Against the official FRED/ALFRED calendar (release id 10), 7 of its 14
entries were not release dates, and one of those — 2025-11-13 — was a release
that never happened: BLS published no CPI in November 2025, because the
October-2025 reference month was cancelled during the shutdown.

The proxy never raised and never produced a NaN. It produced a complete,
plausible, wrong table, and the wrongness ran in one direction: all three moves
the article reported as larger than the 2026-06-10 release were on non-event
days. Correcting the calendar moves 2026-06-10's +11.827% VIX reaction from
"4th of 14" to "1st of 13" — the article's central comparative claim inverted.

These tests exist so that failure mode cannot come back silently. Reverting the
script to the hard-coded list fails `TestScriptUsesOfficialCalendar`, because
those tests feed the calendar through a mocked `_fetch` that a hard-coded list
would ignore.

Network is mocked throughout: the point is to pin the calendar semantics, not to
re-verify FRED's uptime. The fixture dates below are the real values returned by
FRED release id 10 (Consumer Price Index), fetched 2026-07-19.

See experiments/k1442/related_event_date_audit.md.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest

from volpred.data import event_dates

REPO_ROOT = Path(__file__).resolve().parents[1]
ARTICLE_DIR = REPO_ROOT / "storage" / "event_articles" / "us_cpi_2026_06_11_t0"
ANALYSIS_PY = ARTICLE_DIR / "analysis.py"
EVIDENCE_JSON = ARTICLE_DIR / "evidence.json"

# Official CPI release dates, FRED release id 10.
OFFICIAL_2025_2026 = [
    "2025-01-15", "2025-02-12", "2025-03-12", "2025-04-10", "2025-05-13",
    "2025-06-11", "2025-07-15", "2025-08-12", "2025-09-11",
    # No November 2025 release: the shutdown cancelled the October reference
    # month, and the September report slipped to 2025-10-24.
    "2025-10-24", "2025-12-18",
    "2026-01-13", "2026-02-13", "2026-03-11", "2026-04-10", "2026-05-12",
    "2026-06-10", "2026-07-14", "2026-08-12", "2026-09-11", "2026-10-14",
    "2026-11-10", "2026-12-10",
]

# The calendar the article's first draft hard-coded, verbatim.
LEGACY_HARDCODED = [
    "2025-05-13", "2025-06-11", "2025-07-15", "2025-08-12", "2025-09-11",
    "2025-10-15", "2025-11-13", "2025-12-10", "2026-01-14", "2026-02-12",
    "2026-03-12", "2026-04-10", "2026-05-13", "2026-06-10",
]

# The 7 it got wrong, as (hard-coded, official). `None` = invented event.
LEGACY_MISMATCHES = [
    ("2025-10-15", "2025-10-24"),  # shutdown delay
    ("2025-11-13", None),          # phantom: no CPI released in Nov 2025
    ("2025-12-10", "2025-12-18"),
    ("2026-01-14", "2026-01-13"),
    ("2026-02-12", "2026-02-13"),
    ("2026-03-12", "2026-03-11"),
    ("2026-05-13", "2026-05-12"),
]

# The 7 it happened to get right. Pinned so a "fix" that shifts every date is
# caught too -- the proxy is not wrong everywhere, it is wrong at the shutdown
# boundary and wherever BLS did not land near the 13th.
LEGACY_CORRECT = [
    "2025-05-13", "2025-06-11", "2025-07-15", "2025-08-12", "2025-09-11",
    "2026-04-10", "2026-06-10",
]

# What the study must use: official releases inside the 2025-05-01..2026-06-13 window.
EXPECTED_SAMPLE = [
    "2025-05-13", "2025-06-11", "2025-07-15", "2025-08-12", "2025-09-11",
    "2025-10-24", "2025-12-18", "2026-01-13", "2026-02-13", "2026-03-11",
    "2026-04-10", "2026-05-12", "2026-06-10",
]

RELEASE_DATE = "2026-06-10"


@pytest.fixture(autouse=True)
def isolate_event_date_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(event_dates, "_CACHE_DIR", tmp_path)


@pytest.fixture
def official(monkeypatch):
    monkeypatch.setattr(event_dates, "_fetch", lambda *_a, **_kw: list(OFFICIAL_2025_2026))
    return event_dates.cpi_release_dates("2025-01-01", "2026-12-31", use_cache=False)


@pytest.fixture(scope="module")
def analysis():
    spec = importlib.util.spec_from_file_location("cpi_t0_analysis", ANALYSIS_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def sessions():
    """XNYS sessions over the study window. Local calendar, no network."""
    import exchange_calendars as xcals

    raw = xcals.get_calendar("XNYS").sessions_in_range(
        pd.Timestamp("2025-05-01"), pd.Timestamp("2026-06-12")
    )
    return pd.DatetimeIndex([d.tz_localize(None) if d.tz else d for d in raw])


class TestLegacyCalendarWasWrong:
    @pytest.mark.parametrize("legacy_date,official_date", LEGACY_MISMATCHES)
    def test_legacy_date_is_not_an_official_release(self, official, legacy_date, official_date):
        assert pd.Timestamp(legacy_date) not in official, (
            f"{legacy_date} came from the hard-coded calendar and is not a CPI release date"
        )
        if official_date is not None:
            assert pd.Timestamp(official_date) in official

    @pytest.mark.parametrize("legacy_date", LEGACY_CORRECT)
    def test_legacy_dates_that_were_already_correct_stay_correct(self, official, legacy_date):
        assert pd.Timestamp(legacy_date) in official

    def test_november_2025_release_does_not_exist(self, official):
        """The worst failure: a full event window scored on a non-event.

        The hard-coded 2025-11-13 carried a +14.22% VIX move and was ranked 2nd,
        directly above the release this article is about. No CPI was published
        that month at all. A monthly heuristic cannot represent a cancelled
        release, which is why the calendar has to be data rather than a rule.
        """
        assert not [d for d in official if (d.year, d.month) == (2025, 11)]

    def test_seven_of_fourteen_were_wrong(self, official):
        """The headline number from the K1442 audit, recomputed not restated."""
        wrong = [d for d in LEGACY_HARDCODED if pd.Timestamp(d) not in official]
        assert len(wrong) == 7
        assert set(wrong) == {legacy for legacy, _ in LEGACY_MISMATCHES}

    def test_legacy_and_correct_partition_the_hard_coded_list(self):
        """Guard the fixtures themselves against a typo that would fake a pass."""
        assert set(LEGACY_HARDCODED) == {l for l, _ in LEGACY_MISMATCHES} | set(LEGACY_CORRECT)
        assert len(LEGACY_HARDCODED) == len(LEGACY_MISMATCHES) + len(LEGACY_CORRECT)


class TestScriptUsesOfficialCalendar:
    """Reverting analysis.py to a hard-coded list fails 8 of the 9 tests here.

    Each drives the script's own date resolution through a mocked `_fetch`, which
    a hard-coded list would ignore. The one that survives the revert is
    `test_target_release_is_resolved_from_the_calendar`: the legacy list happened
    to contain the correct 2026-06-10, so it resolves the right target for the
    wrong reason. Verified empirically, not assumed — see the results JSON.
    """

    def test_official_cpi_dates_returns_the_official_sample(self, analysis, monkeypatch, sessions):
        monkeypatch.setattr(event_dates, "_fetch", lambda *_a, **_kw: list(OFFICIAL_2025_2026))
        actual = [str(d.date()) for d in analysis.official_cpi_dates(sessions)]
        assert actual == EXPECTED_SAMPLE

    def test_no_legacy_date_survives_in_the_sample(self, analysis, monkeypatch, sessions):
        monkeypatch.setattr(event_dates, "_fetch", lambda *_a, **_kw: list(OFFICIAL_2025_2026))
        actual = {str(d.date()) for d in analysis.official_cpi_dates(sessions)}
        assert actual.isdisjoint({legacy for legacy, _ in LEGACY_MISMATCHES})

    def test_sample_is_thirteen_not_fourteen(self, analysis, monkeypatch, sessions):
        monkeypatch.setattr(event_dates, "_fetch", lambda *_a, **_kw: list(OFFICIAL_2025_2026))
        assert len(analysis.official_cpi_dates(sessions)) == 13

    def test_target_release_is_resolved_from_the_calendar(self, analysis, monkeypatch, sessions):
        monkeypatch.setattr(event_dates, "_fetch", lambda *_a, **_kw: list(OFFICIAL_2025_2026))
        dates = analysis.official_cpi_dates(sessions)
        assert str(analysis.resolve_target_release(dates).date()) == RELEASE_DATE

    def test_target_month_with_no_release_fails_closed(self, analysis, monkeypatch, sessions):
        """The phantom guard: an empty month must raise, not improvise a date."""
        monkeypatch.setattr(event_dates, "_fetch", lambda *_a, **_kw: list(OFFICIAL_2025_2026))
        dates = analysis.official_cpi_dates(sessions)
        monkeypatch.setattr(analysis, "TARGET_MONTH", (2025, 11))
        with pytest.raises(RuntimeError, match="expected exactly 1 official CPI release"):
            analysis.resolve_target_release(dates)

    def test_release_off_the_session_calendar_fails_closed(self, analysis, monkeypatch, sessions):
        """No snapping: a release on a non-session makes 't-1' ambiguous, so refuse."""
        monkeypatch.setattr(
            event_dates,
            "_fetch",
            lambda *_a, **_kw: [*OFFICIAL_2025_2026, "2026-05-30"],  # a Saturday
        )
        with pytest.raises(RuntimeError, match="not XNYS sessions"):
            analysis.official_cpi_dates(sessions)

    def test_empty_calendar_fails_closed(self, analysis, monkeypatch, sessions):
        monkeypatch.setattr(event_dates, "_fetch", lambda *_a, **_kw: ["2019-01-11"])
        with pytest.raises(RuntimeError, match="no dates inside the sample"):
            analysis.official_cpi_dates(sessions)

    def test_it_asks_fred_for_the_cpi_release_specifically(self, analysis, monkeypatch, sessions):
        """Pin release id 10.

        Every other test here mocks `_fetch` without inspecting its arguments, so a
        script that called `nfp_release_dates` would be handed the CPI fixture and
        sail through. This one records what was actually requested.
        """
        seen = []

        def spy(release_id, start, end):
            seen.append(release_id)
            return list(OFFICIAL_2025_2026)

        monkeypatch.setattr(event_dates, "_fetch", spy)
        analysis.official_cpi_dates(sessions)
        assert seen == [event_dates.RELEASE_IDS["CPI_US"]] == [10]

    def test_errata_table_is_recomputed_not_restated(self, analysis, monkeypatch, sessions):
        monkeypatch.setattr(event_dates, "_fetch", lambda *_a, **_kw: list(OFFICIAL_2025_2026))
        rows = analysis.build_errata(analysis.official_cpi_dates(sessions))
        assert [(r["old"], r["new"]) for r in rows] == LEGACY_MISMATCHES
        assert sum(1 for r in rows if r["kind"] == "phantom") == 1


class TestReactionArithmeticRejectsPoisonedQuotes:
    """The session guard validates the INDEX; these pin the VALUES.

    A structurally-perfect session list can still carry a NaN quote, which would
    sort silently into the ranking rather than raising.
    """

    @pytest.fixture
    def series(self):
        """The real ^VIX closes, full precision, so the normal case pins the
        headline number rather than a made-up one."""
        idx = pd.to_datetime(["2026-06-08", "2026-06-09", "2026-06-10"])
        return pd.Series([19.0, 19.8700008392334, 22.219999313354492], index=idx)

    def test_normal_case_reproduces_the_headline_reaction(self, analysis, series):
        prev, curr, pct = analysis.reaction_pct(series, pd.Timestamp("2026-06-10"))
        assert (round(prev, 2), round(curr, 2)) == (19.87, 22.22)
        assert pct == pytest.approx(11.827, abs=5e-4)

    def test_nan_close_raises(self, analysis, series):
        series.iloc[2] = float("nan")
        with pytest.raises(RuntimeError, match="non-finite close"):
            analysis.reaction_pct(series, pd.Timestamp("2026-06-10"))

    def test_nan_prior_close_raises(self, analysis, series):
        series.iloc[1] = float("nan")
        with pytest.raises(RuntimeError, match="non-finite close"):
            analysis.reaction_pct(series, pd.Timestamp("2026-06-10"))

    def test_zero_prior_close_raises(self, analysis, series):
        series.iloc[1] = 0.0
        with pytest.raises(RuntimeError, match="prior close is zero"):
            analysis.reaction_pct(series, pd.Timestamp("2026-06-10"))

    def test_first_session_has_no_t_minus_1(self, analysis, series):
        with pytest.raises(RuntimeError, match="no t-1 close exists"):
            analysis.reaction_pct(series, pd.Timestamp("2026-06-08"))


class TestOutputPathIsAnchoredToTheScript:
    """Note the scope: these pin OUT_DIR's value, they do not chdir and rerun.

    That is enough for the current implementation, where OUT_DIR is a module-level
    constant derived from __file__, but it would not catch a future version that
    resolved paths lazily against the cwd.
    """

    def test_out_dir_is_the_script_directory(self, analysis):
        assert analysis.OUT_DIR == ARTICLE_DIR

    def test_out_dir_is_not_the_stale_desktop_root(self, analysis):
        """The original hard-coded an absolute Desktop root the repo moved out of.

        Combined with mkdir(parents=True) that silently resurrects a stale tree and
        writes there, from any cwd -- so this pins the absolute path out, not cwd drift.
        """
        assert "Desktop" not in str(analysis.OUT_DIR)


class TestPublishedEvidenceMatchesTheOfficialCalendar:
    """Catch a stale artifact: correct code plus a never-rerun evidence.json."""

    @pytest.fixture(scope="class")
    def evidence(self):
        return json.loads(EVIDENCE_JSON.read_text(encoding="utf-8"))

    def test_evidence_pins_the_official_sample(self, evidence):
        assert evidence["official_cpi_release_dates"] == EXPECTED_SAMPLE

    def test_release_day_ranks_first_of_thirteen(self, evidence):
        rank = evidence["release_day_vix_rank"]
        assert rank["date"] == RELEASE_DATE
        assert rank["sample_n"] == 13
        assert rank["rank_among_official_cpi_days"] == 1, (
            "the corrected claim is that 2026-06-10 was the LARGEST CPI-day VIX "
            "move in the sample; the draft's '4th of 14' came from three "
            "non-event days ranked above it"
        )

    def test_rank_is_consistent_with_the_ranked_table(self, evidence):
        """Recompute the rank from the table rather than trusting the summary field."""
        table = evidence["official_cpi_vix_moves_ranked"]
        assert len(table) == 13
        pcts = [r["vix_pct"] for r in table]
        assert pcts == sorted(pcts, reverse=True)
        assert table[0]["date"] == RELEASE_DATE
        assert table[0]["vix_pct"] == evidence["release_day_vix_rank"]["vix_pct"]

    def test_no_legacy_date_appears_in_the_ranked_table(self, evidence):
        dates = {r["date"] for r in evidence["official_cpi_vix_moves_ranked"]}
        assert dates.isdisjoint({legacy for legacy, _ in LEGACY_MISMATCHES})

    def test_errata_block_records_the_inversion(self, evidence):
        errata = evidence["errata"]
        assert errata["legacy_sample_n"] == 14
        assert errata["official_sample_n"] == 13
        assert errata["legacy_rank_claim"] == 4
        assert errata["official_rank"] == 1
        assert [(r["old"], r["new"]) for r in errata["dates_fixed"]] == LEGACY_MISMATCHES

    def test_event_window_is_the_release_day_and_its_neighbours(self, evidence):
        """The one part of the draft that was already right must stay right."""
        assert list(evidence["event_window_closes"]) == [
            "2026-06-09", RELEASE_DATE, "2026-06-11"
        ]
