"""Pin the NFP event dates that a first-Friday proxy gets wrong.

`experiments/event_article_nfp_2026_07_03_t1` used to derive its NFP release
dates from a "first Friday of the month" rule. Against the official BLS
Employment Situation calendar, 7 of its 13 historical events were on the wrong
day, and correcting them flipped the headline direction: the SPY up-day rate
went from 53.8% to 46.2% and both medians changed sign.

The proxy never raised and never produced a NaN. It produced a complete,
plausible, wrong table. These tests exist so that failure mode cannot come
back silently. See experiments/k1442/related_event_date_audit.md.

Network is mocked throughout: the point is to pin the calendar semantics, not
to re-verify FRED's uptime. The fixture dates below are the real values
returned by FRED release id 50 (Employment Situation), fetched 2026-07-19.
"""

from __future__ import annotations

import importlib.util
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

from volpred.data import event_dates

REPO_ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT_DIR = REPO_ROOT / "experiments" / "event_article_nfp_2026_07_03_t1"
EXPERIMENT_PY = EXPERIMENT_DIR / "event_article_nfp_2026_07_03_t1.py"

# Official Employment Situation release dates, FRED release id 50.
OFFICIAL_2024_2026 = [
    "2024-01-05", "2024-02-02", "2024-03-08", "2024-04-05", "2024-05-03",
    "2024-06-07", "2024-07-05", "2024-08-02", "2024-09-06", "2024-10-04",
    "2024-11-01", "2024-12-06",
    "2025-01-10", "2025-02-07", "2025-03-07", "2025-04-04", "2025-05-02",
    "2025-06-06", "2025-07-03", "2025-08-01", "2025-09-05",
    # No October 2025 release: the shutdown cancelled it and pushed the
    # September report to 2025-11-20.
    "2025-11-20", "2025-12-16",
    "2026-01-09", "2026-02-11", "2026-03-06", "2026-04-03", "2026-05-08",
    "2026-06-05", "2026-07-02",
]

# The 7 dates the first-Friday proxy got wrong, as (proxy, official).
# `None` means the proxy invented an event that does not exist.
PROXY_MISMATCHES = [
    ("2025-07-04", "2025-07-03"),  # proxy landed on the closed July 4 holiday
    ("2025-10-03", None),          # phantom: no Employment Situation in Oct 2025
    ("2025-11-07", "2025-11-20"),  # shutdown backlog
    ("2025-12-05", "2025-12-16"),
    ("2026-01-02", "2026-01-09"),
    ("2026-02-06", "2026-02-11"),
    ("2026-05-01", "2026-05-08"),
]

# The 6 the proxy happened to get right. Pinned so a "fix" that shifts every
# date is caught too -- the proxy is not wrong everywhere, it is wrong at the
# holiday and shutdown boundaries.
PROXY_CORRECT = [
    "2025-06-06", "2025-08-01", "2025-09-05",
    "2026-03-06", "2026-04-03", "2026-06-05",
]

# What the experiment must use: trailing 13 official releases before 2026-07-02.
EXPECTED_TRAILING_13 = [
    "2025-05-02", "2025-06-06", "2025-07-03", "2025-08-01", "2025-09-05",
    "2025-11-20", "2025-12-16", "2026-01-09", "2026-02-11", "2026-03-06",
    "2026-04-03", "2026-05-08", "2026-06-05",
]


def _first_friday(year: int, month: int) -> date:
    """The proxy this module exists to keep out of the codebase."""
    d = date(year, month, 1)
    return d + timedelta(days=(4 - d.weekday()) % 7)


@pytest.fixture(autouse=True)
def isolate_event_date_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(event_dates, "_CACHE_DIR", tmp_path)


@pytest.fixture
def official(monkeypatch):
    monkeypatch.setattr(
        event_dates, "_fetch", lambda *_a, **_kw: list(OFFICIAL_2024_2026)
    )
    return event_dates.nfp_release_dates("2024-01-01", "2026-07-02", use_cache=False)


@pytest.fixture(scope="module")
def experiment():
    spec = importlib.util.spec_from_file_location(
        "nfp_t1_experiment", EXPERIMENT_PY
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestProxyMismatches:
    @pytest.mark.parametrize("proxy_date,official_date", PROXY_MISMATCHES)
    def test_proxy_date_is_not_an_official_release(
        self, official, proxy_date, official_date
    ):
        assert pd.Timestamp(proxy_date) not in official, (
            f"{proxy_date} came from the first-Friday proxy and is not an "
            "Employment Situation release date"
        )
        if official_date is not None:
            assert pd.Timestamp(official_date) in official

    @pytest.mark.parametrize("proxy_date,official_date", PROXY_MISMATCHES)
    def test_mismatch_really_is_what_the_proxy_would_have_produced(
        self, proxy_date, official_date
    ):
        """Guard the fixture itself: each 'proxy' date must be a first Friday.

        Without this, a typo in PROXY_MISMATCHES would make the suite pass by
        testing a date the proxy never generated.
        """
        d = pd.Timestamp(proxy_date)
        assert _first_friday(d.year, d.month) == d.date()

    def test_october_2025_release_does_not_exist(self, official):
        """The proxy's worst failure: a full event window scored on a non-event.

        No Employment Situation was published in October 2025. A monthly
        heuristic cannot represent this, which is why the calendar has to be
        data rather than a rule.
        """
        assert not [d for d in official if (d.year, d.month) == (2025, 10)]

    @pytest.mark.parametrize("proxy_date", PROXY_CORRECT)
    def test_proxy_dates_that_were_already_correct_stay_correct(
        self, official, proxy_date
    ):
        assert pd.Timestamp(proxy_date) in official

    def test_seven_of_thirteen_were_wrong(self, official):
        """The headline number from the K1442 audit, recomputed not restated."""
        proxy_dates = []
        y, m = 2026, 6
        while len(proxy_dates) < 13:
            ff = _first_friday(y, m)
            if ff < date(2026, 7, 3):
                proxy_dates.append(ff)
            m -= 1
            if m == 0:
                m, y = 12, y - 1

        wrong = [d for d in proxy_dates if pd.Timestamp(d) not in official]
        assert len(wrong) == 7
        assert {str(d) for d in wrong} == {p for p, _ in PROXY_MISMATCHES}


class TestExperimentUsesOfficialCalendar:
    def test_release_date_is_july_2_not_july_3(self, experiment):
        """July 4 fell on a Saturday, observed Friday July 3, so BLS moved up."""
        assert experiment.RELEASE_DATE == "2026-07-02"
        assert experiment.AS_OF == "2026-07-01"

    def test_build_nfp_dates_returns_the_official_trailing_thirteen(
        self, experiment, monkeypatch
    ):
        monkeypatch.setattr(
            event_dates, "_fetch", lambda *_a, **_kw: list(OFFICIAL_2024_2026)
        )
        monkeypatch.setattr(
            experiment,
            "nfp_release_dates",
            lambda start, end, **kw: event_dates.nfp_release_dates(
                start, end, use_cache=False
            ),
        )

        actual = [str(d.date()) for d in experiment.build_nfp_dates(13)]
        assert actual == EXPECTED_TRAILING_13

    def test_release_date_itself_is_excluded(self, experiment, monkeypatch):
        """2026-07-02 is the event under study; it must not enter its own history."""
        monkeypatch.setattr(
            event_dates, "_fetch", lambda *_a, **_kw: list(OFFICIAL_2024_2026)
        )
        monkeypatch.setattr(
            experiment,
            "nfp_release_dates",
            lambda start, end, **kw: event_dates.nfp_release_dates(
                start, end, use_cache=False
            ),
        )

        assert pd.Timestamp("2026-07-02") not in experiment.build_nfp_dates(13)

    def test_fails_closed_when_calendar_is_short(self, experiment, monkeypatch):
        """No proxy fallback: too few official dates must raise, not improvise."""
        monkeypatch.setattr(
            experiment,
            "nfp_release_dates",
            lambda *_a, **_kw: pd.DatetimeIndex(pd.to_datetime(["2026-06-05"])),
        )

        with pytest.raises(RuntimeError, match="only 1 releases"):
            experiment.build_nfp_dates(13)

    def test_fails_closed_when_calendar_is_unreachable(
        self, experiment, monkeypatch
    ):
        def boom(*_a, **_kw):
            raise RuntimeError("FRED_API_KEY not found")

        monkeypatch.setattr(experiment, "nfp_release_dates", boom)

        with pytest.raises(RuntimeError, match="FRED_API_KEY"):
            experiment.build_nfp_dates(13)


class TestNoLookahead:
    """The download window itself must exclude the release day.

    Asserting on constants is not enough: the constant can be right while the
    call still passes a later `end`. These observe the actual yfinance calls.
    """

    # SPY, ^VIX, ^VIX9D -- every series must respect the cutoff, so the
    # recorder has to survive past the first call. Stopping on call 1 would
    # leave a mutated ^VIX or ^VIX9D `end` completely untested.
    EXPECTED_TICKERS = ["SPY", "^VIX", "^VIX9D"]

    def _capture_downloads(self, experiment, monkeypatch):
        calls = []

        def recorder(ticker, **kw):
            calls.append({"ticker": ticker, **kw})
            # Never abort inside the recorder itself. Stopping on call N would
            # make a download added AFTER the ones we know about unreachable,
            # so a 4th series could ship with an unchecked `end`. The tripwire
            # defers the abort until main() first touches a frame, which is
            # past the whole download block.
            return _Tripwire()

        monkeypatch.setattr(
            event_dates, "_fetch", lambda *_a, **_kw: list(OFFICIAL_2024_2026)
        )
        monkeypatch.setattr(
            experiment,
            "nfp_release_dates",
            lambda start, end, **kw: event_dates.nfp_release_dates(
                start, end, use_cache=False
            ),
        )
        monkeypatch.setattr(experiment.yf, "download", recorder)
        try:
            experiment.main()
        except _StopEarly:
            pass  # silent-ok: sentinel to stop main() once args are captured
        return calls

    def test_every_series_is_downloaded(self, experiment, monkeypatch):
        """Pin the call count so the assertions below cannot pass vacuously."""
        calls = self._capture_downloads(experiment, monkeypatch)
        assert [c["ticker"] for c in calls] == self.EXPECTED_TICKERS

    def test_download_window_ends_before_the_release(self, experiment, monkeypatch):
        calls = self._capture_downloads(experiment, monkeypatch)
        assert len(calls) == len(self.EXPECTED_TICKERS)
        for call in calls:
            # yfinance `end` is exclusive, so end == release date means the
            # last obtainable session is 2026-07-01.
            assert call["end"] == "2026-07-02", (
                f"{call['ticker']} download window ends at {call['end']!r}; "
                "the 2026-07-02 release day must not be downloadable"
            )

    def test_download_window_starts_before_the_earliest_event(
        self, experiment, monkeypatch
    ):
        calls = self._capture_downloads(experiment, monkeypatch)
        # Guard against all([]) passing vacuously if nothing was captured.
        assert len(calls) == len(self.EXPECTED_TICKERS)
        # Needs a prior close to difference against 2025-05-02.
        assert all(call["start"] < "2025-05-02" for call in calls)


class _StopEarly(Exception):
    """Abort main() once the download arguments have been observed."""


class _Tripwire:
    """Stand-in for a downloaded frame that raises when first consumed.

    Lets every `yf.download` call run and be recorded before main() is
    aborted, so the ticker-sequence assertion can see a download that does
    not exist yet. main() touches `.columns` first when it flattens the
    MultiIndex.
    """

    @property
    def columns(self):
        raise _StopEarly()


class TestNoProxyResidue:
    """Source-level guard. The behavioural tests above can all pass while a
    dormant proxy helper sits in the file waiting to be called again."""

    def test_experiment_defines_no_first_friday_helper(self):
        src = EXPERIMENT_PY.read_text(encoding="utf-8")
        assert "def first_friday" not in src
        assert "(4 - d.weekday()) % 7" not in src

    def test_experiment_imports_the_official_calendar(self):
        src = EXPERIMENT_PY.read_text(encoding="utf-8")
        assert "from volpred.data.event_dates import nfp_release_dates" in src

    def test_results_json_declares_its_event_date_source(self):
        import json

        results = json.loads(
            (EXPERIMENT_DIR / "event_article_nfp_2026_07_03_t1_results.json")
            .read_text(encoding="utf-8")
        )
        assert results["nfp_release_date"] == "2026-07-02"
        assert "nfp_release_dates" in results["event_date_source"]
        assert [r["nfp_release_date"] for r in results["historical_nfp_table"]] == (
            EXPECTED_TRAILING_13
        )
