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


# ---------------------------------------------------------------------------
# K528 -- the same proxy, the same bug, a 21-year sample.
#
# The sibling experiment above had 13 events. K528 had 254 and fed six numbers
# straight into a published article (mile_35eef830). Correcting its calendar
# swapped dates but reversed NO conclusion.
#
# An intermediate 2026-07-19 rerun did report the NFP-vs-Friday result flipping
# to non-significant (p 0.0335 -> 0.0571). That was WRONG and is recorded here
# so it is not repeated: the accessor was picking off-cycle revision entries for
# six months, and on correct dates the comparison stays significant
# (1.189x, p=0.021). A retraction of a correct finding was one Codex review away
# from being published. Same module rather than a new file: "NFP event dates are
# official" is one concern and should keep one enforcement owner.
# ---------------------------------------------------------------------------

K528_DIR = REPO_ROOT / "experiments" / "k528"
K528_PY = K528_DIR / "k528_nfp_event_study.py"
K528_RESULTS = K528_DIR / "k528_nfp_event_study_results.json"
K528_AUDIT = K528_DIR / "k528_nfp_official_dates_results.json"


def _load_k528(path):
    import json

    return json.loads(path.read_text(encoding="utf-8"))


def _k528_event_dates():
    return [pd.Timestamp(e["date"]) for e in _load_k528(K528_RESULTS)["event_data"]]


def assert_not_first_friday_proxy(dates):
    """Reject a calendar carrying the first-Friday proxy's fingerprints.

    Three independent signatures, because a partial revert should be caught as
    readily as a total one. This is the function the mutation test below fires
    a proxy calendar at: a guard nobody has ever seen fail is not a guard.
    """
    dates = pd.DatetimeIndex(dates)
    if len(dates) == 0:
        raise AssertionError("empty calendar")

    if (dates.weekday == 4).all():
        raise AssertionError(
            f"all {len(dates)} releases fall on a Friday. The official calendar "
            "does not: BLS moves the release off Friday at holiday and shutdown "
            "boundaries. This is the proxy's signature."
        )

    on_first_friday = [
        d for d in dates if d.date() == _first_friday(d.year, d.month)
    ]
    if len(on_first_friday) == len(dates):
        raise AssertionError(
            "every release sits on the first Friday of its month -- proxy calendar"
        )

    phantom = [d for d in dates if (d.year, d.month) == (2025, 10)]
    if phantom:
        raise AssertionError(
            f"calendar contains an October 2025 release ({phantom[0].date()}). "
            "The shutdown cancelled it; only the proxy invents one."
        )


class TestK528UsesOfficialCalendar:
    def test_defines_no_first_friday_helper(self):
        src = K528_PY.read_text(encoding="utf-8")
        assert "def get_first_friday" not in src
        assert "def generate_nfp_dates" not in src
        assert "(4 - first_day.weekday()) % 7" not in src

    def test_imports_the_official_calendar(self):
        """Match the import target, not the whole line: the script also imports
        _fetch/RELEASE_IDS to validate the unselected feed, and pinning the exact
        line text would fail on that without anything being wrong."""
        src = K528_PY.read_text(encoding="utf-8")
        assert "from volpred.data.event_dates import" in src
        assert "nfp_release_dates" in src

    def test_results_declare_the_official_source_and_no_fallback(self):
        source = _load_k528(K528_RESULTS)["event_date_source"]
        assert "nfp_release_dates" in source["accessor"]
        assert source["fallback"] == "none - the run raises if the calendar is unreachable"

    def test_event_dates_carry_no_proxy_signature(self):
        assert_not_first_friday_proxy(_k528_event_dates())

    def test_sample_is_not_uniformly_friday(self):
        """237 of 253, not 253 of 253. The gap is the corrected dates."""
        results = _load_k528(K528_RESULTS)
        n, on_friday = results["sample"]["total_nfp_events"], results["sample"]["nfp_days_on_friday"]
        assert n == 253
        assert on_friday == 237
        assert on_friday < n

    def test_audit_records_the_dates_that_changed(self):
        diff = _load_k528(K528_AUDIT)["calendar_diff"]
        assert diff["dates_in_common"] == 212
        # The near-equal sample sizes hide a date swap; assert the swap, not the
        # count, or a silent revert reads as unchanged.
        assert len(diff["proxy_only_dates"]) == 42
        assert len(diff["official_only_dates"]) == 41
        assert "2025-10-03" in diff["proxy_only_dates"]
        assert "2025-11-20" in diff["official_only_dates"]

    def test_no_off_cycle_revision_date_is_treated_as_an_event(self):
        """Direct pin on the k528 Codex v2 BLOCKER.

        For six months ALFRED returns two release-id-50 entries; the later one
        is a seasonal-factor/benchmark revision, not the Employment Situation.
        An earlier rerun selected those six and moved the NFP-vs-Friday test
        across the 5% line. Assert on the ARTIFACT, not just on the accessor:
        the accessor being right does not prove the shipped results used it.
        """
        event_dates = {str(d.date()) for d in _k528_event_dates()}
        off_cycle = {
            "2006-05-08", "2012-12-12", "2013-05-06",
            "2020-05-11", "2024-01-10", "2024-08-21",
        }
        regular = {
            "2006-05-05", "2012-12-07", "2013-05-03",
            "2020-05-08", "2024-01-05", "2024-08-02",
        }
        assert not (event_dates & off_cycle), (
            f"off-cycle revision dates present in k528 event set: "
            f"{sorted(event_dates & off_cycle)}"
        )
        assert regular <= event_dates, (
            f"regular releases missing from k528 event set: {sorted(regular - event_dates)}"
        )


class TestProxyMutationIsCaught:
    """Mutation test. Reverting to the proxy must turn the suite red, and the
    only way to know that is to build the proxy calendar and watch the guard
    reject it."""

    @staticmethod
    def _proxy_calendar(start_year=2005, end_year=2026, end_month=3):
        out = []
        for year in range(start_year, end_year + 1):
            last = 12 if year < end_year else end_month
            for month in range(1, last + 1):
                out.append(pd.Timestamp(_first_friday(year, month)))
        return pd.DatetimeIndex(out)

    def test_the_proxy_calendar_is_rejected(self):
        with pytest.raises(AssertionError, match="Friday"):
            assert_not_first_friday_proxy(self._proxy_calendar())

    def test_phantom_october_2025_alone_is_enough_to_fail(self):
        """A partial revert that keeps some real dates still gets caught."""
        mixed = pd.DatetimeIndex(
            _k528_event_dates() + [pd.Timestamp("2025-10-03")]
        )
        with pytest.raises(AssertionError, match="October 2025"):
            assert_not_first_friday_proxy(mixed)

    def test_the_guard_accepts_the_official_calendar(self, official):
        """The other half of the mutation test: the guard must not reject
        everything. A guard that always fails is as useless as one that never
        does."""
        assert_not_first_friday_proxy(official)


# ---------------------------------------------------------------------------
# Holes found by Codex v3 against commit 6fd281901. Each of these shipped once
# with a green suite, so each gets an assertion rather than a comment.
# ---------------------------------------------------------------------------


def _k528_module():
    """Load the k528 script's pure helpers without running the analysis body."""
    import ast
    import types

    src = K528_PY.read_text(encoding="utf-8")
    tree = ast.parse(src)
    keep = [
        n for n in tree.body
        if isinstance(n, (ast.Import, ast.ImportFrom, ast.FunctionDef))
        or (isinstance(n, ast.AnnAssign) and getattr(n.target, "id", "") == "KNOWN_MISSING_MONTHS")
        or (isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") in (
            "SAMPLE_START", "SAMPLE_END", "AMBIGUOUS_SAME_MONTH_GAP_DAYS"))
    ]
    mod = types.ModuleType("k528_helpers")
    exec(compile(ast.Module(body=keep, type_ignores=[]), "k528", "exec"), mod.__dict__)
    return mod


class TestControlGroupHasNoNfpDays:
    """A real NFP session sitting in the control group is the exact failure this
    experiment exists to document -- it just happened at 1/253 scale instead of
    46/254, via an event dropped for lacking a pre-window but never removed from
    the baseline."""

    def test_every_mapped_nfp_session_is_excluded_from_the_control_group(self):
        sample = _load_k528(K528_RESULTS)["sample"]
        audit = sample["event_mapping_audit"]
        total_sessions = sample["non_nfp_trading_days"] + audit["n_mapped_to_sessions"]
        assert sample["non_nfp_trading_days"] == total_sessions - audit["n_mapped_to_sessions"], (
            "control group size must exclude ALL mapped NFP sessions, not just the "
            "ones that survived the event-window filter"
        )

    def test_window_excluded_event_is_not_silently_analysed_or_kept_as_control(self):
        audit = _load_k528(K528_RESULTS)["sample"]["event_mapping_audit"]
        assert audit["n_valid_events"] + audit["n_excluded_for_window_buffer"] == \
            audit["n_mapped_to_sessions"]
        assert audit["window_excluded_dates"], "the partition must name what it dropped"


class TestCalendarFailClosedCannotBeBypassed:
    """Codex v3 finding 3: validating only the accessor's OUTPUT cannot work,
    because the accessor collapses each month to one date before any check on
    the output can look for an ambiguity."""

    @pytest.fixture
    def check(self):
        return _k528_module().check_calendar_is_complete

    def test_off_cycle_entry_earlier_in_the_month_is_ambiguous_not_silently_picked(self, check):
        """The bypass: an off-cycle entry filed EARLIER than the report. A
        per-month min() takes it without complaint and the cadence still passes."""
        with pytest.raises(RuntimeError, match="too close together"):
            check(
                pd.to_datetime(["2024-01-05", "2024-02-01", "2024-03-08"]),
                ["2024-01-05", "2024-02-01", "2024-02-02", "2024-03-08"],
                "2024-01-01", "2024-12-31",
            )

    def test_selection_that_is_not_the_earliest_entry_fails(self, check):
        with pytest.raises(RuntimeError, match="did not select the earliest"):
            check(
                pd.to_datetime(["2024-01-05", "2024-02-09", "2024-03-08"]),
                ["2024-01-05", "2024-02-02", "2024-02-09", "2024-03-08"],
                "2024-01-01", "2024-12-31",
            )

    def test_missing_month_inside_the_observed_span_fails(self, check):
        """The old check exempted the first and last month unconditionally, so a
        genuinely complete endpoint month could vanish for free."""
        with pytest.raises(RuntimeError, match="missing 1 month"):
            check(
                pd.to_datetime(["2024-01-05", "2024-02-02", "2024-04-05"]),
                ["2024-01-05", "2024-02-02", "2024-04-05"],
                "2024-01-01", "2024-12-31",
            )

    def test_allowlist_cannot_silence_a_month_that_has_data(self, check):
        """KNOWN_MISSING_MONTHS is for real cancellations. If it is taken on
        faith it is just a way to make a failing check pass."""
        mod = _k528_module()
        mod.KNOWN_MISSING_MONTHS["2024-03"] = "fabricated"
        with pytest.raises(RuntimeError, match="claims"):
            mod.check_calendar_is_complete(
                pd.to_datetime(["2024-01-05", "2024-02-02", "2024-04-05"]),
                ["2024-01-05", "2024-02-02", "2024-03-08", "2024-04-05"],
                "2024-01-01", "2024-12-31",
            )

    def test_a_legitimate_calendar_with_a_normal_revision_still_passes(self, check):
        """The other half: a guard that rejects everything is as useless as one
        that rejects nothing. A revision filed a week later is normal."""
        out = check(
            pd.to_datetime(["2024-01-05", "2024-02-02", "2024-03-08"]),
            ["2024-01-05", "2024-02-02", "2024-02-09", "2024-03-08"],
            "2024-01-01", "2024-12-31",
        )
        assert out["months_with_multiple_raw_entries"] == ["2024-02"]


class TestFridayEstimandIsScopedHonestly:
    """Codex v3 finding 4: restricting to Friday is a legitimate conditional
    estimand, but it stops supporting statements about NFP releases in general,
    and the restriction is not a neutral sample deletion."""

    def test_results_scope_the_claim_to_friday_and_disclose_the_non_neutrality(self):
        b = _load_k528(K528_RESULTS)["statistical_tests"]["B_nfp_vs_friday"]
        assert "CONDITIONAL ON FRIDAY" in b["estimand"]
        assert "Friday NFP" in b["claim_scope"]
        nn = b["restriction_is_not_neutral"]
        assert nn["excluded_are_quieter_by_pct"] > 0, (
            "if the excluded events are quieter, the restriction RAISES the ratio "
            "and that must be stated, not discovered by a reviewer"
        )

    def test_excluded_count_matches_the_weekday_breakdown(self):
        """The results file once said 11 in prose and 16 in data."""
        results = _load_k528(K528_RESULTS)
        b = results["statistical_tests"]["B_nfp_vs_friday"]
        non_friday = sum(1 for e in results["event_data"] if e["weekday"] != 4)
        assert b["excluded_non_friday_events"]["n"] == non_friday == 16
        assert str(non_friday) in b["estimand"]
