#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Mechanical gates for every defect Codex blocked K1694 on (rounds 1 and 2).

Each test names the defect it guards. They read the committed artifacts and, where
a claim is about the estimator rather than the output, rebuild the panel from the
cached CSVs -- so a future edit that reintroduces a defect fails here rather than
in the next round of a review.

Run: uv run --active python -m pytest experiments/K1694/test_K1694.py -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import K1694  # noqa: E402


@pytest.fixture(scope="module")
def results() -> dict:
    return json.loads((HERE / "K1694_results.json").read_text())


@pytest.fixture(scope="module")
def spec() -> dict:
    return json.loads((HERE / "reproduce_spec.json").read_text())


@pytest.fixture(scope="module")
def panel() -> pd.DataFrame:
    return K1694.build_panel(K1694.build_fcm(), K1694.build_dcot(), K1694.build_vol())


@pytest.fixture(scope="module")
def frame(panel: pd.DataFrame) -> pd.DataFrame:
    return K1694.build_spec_frame(panel)


@pytest.fixture(scope="module")
def coverage() -> pd.DataFrame:
    return K1694.monthly_coverage(K1694.build_dcot(), K1694.build_vol())


# --- defect 1: bootstrap must estimate spec1, not a neighbouring specification ---

def test_bootstrap_shares_spec1_design_matrix(results: dict) -> None:
    s1 = results["panel_regressions"]["spec1_fcm_highvol"]
    for key in ("stationary_block_by_month", "month_cluster_iid"):
        boot = results["bootstrap_spec1"][key]
        assert boot["rhs"] == s1["rhs"], f"{key} RHS differs from spec1"
        assert "t" in boot["rhs"], f"{key} dropped the time trend spec1 includes"
        assert boot["n_rows"] == s1["n_obs"], f"{key} sample differs from spec1"
        assert boot["n_months"] == s1["n_months"]
    assert results["primary_interaction"]["bootstrap_matches_spec1_sample_and_rhs"]


def test_bootstrap_point_is_the_reported_spec1_coefficient(results: dict) -> None:
    s1c = results["panel_regressions"]["spec1_fcm_highvol"]["driscoll_kraay"]["coef"]
    for key in ("stationary_block_by_month", "month_cluster_iid"):
        boot = results["bootstrap_spec1"][key]
        assert boot["point"] == pytest.approx(s1c["fcm_x_highvol"], rel=1e-12)
        chk = boot["point_estimator_identity_check"]
        assert chk["max_abs_diff"] < 1e-12, "within-OLS drifted from PanelOLS"


def test_within_ols_equals_panel_ols(frame: pd.DataFrame) -> None:
    """The bootstrap's fast estimator is the same estimator, not an approximation."""
    from linearmodels.panel import PanelOLS
    df = frame.dropna(subset=["d_nonrep"] + K1694.SPEC1_RHS)
    ref = PanelOLS(df.set_index(["commodity", "month_ts"])["d_nonrep"],
                   df.set_index(["commodity", "month_ts"])[K1694.SPEC1_RHS].astype(float),
                   entity_effects=True).fit(cov_type="unadjusted")
    beta = K1694._within_ols(df["d_nonrep"].to_numpy(float),
                            df[K1694.SPEC1_RHS].to_numpy(float),
                            pd.factorize(df["commodity"])[0])
    for j, name in enumerate(K1694.SPEC1_RHS):
        assert beta[j] == pytest.approx(float(ref.params[name]), rel=1e-9, abs=1e-18)


def test_single_estimation_sample_owner(frame: pd.DataFrame, results: dict) -> None:
    """spec1-3 come from build_spec_frame(); spec4 declares its own frame."""
    for label in ("spec1_fcm_highvol", "spec2_fcm_rvz_continuous"):
        blk = results["panel_regressions"][label]
        assert blk["n_obs"] == len(frame)
        assert blk["frame"] == "build_spec_frame()"
    assert results["panel_regressions"]["spec3_trader_conc4_highvol"]["n_obs"] <= len(frame)
    assert results["panel_regressions"][
        "spec4_lagged_timing_hardened"]["frame"] == "build_lagged_frame()"


def test_lagged_frame_is_not_conditioned_on_a_regressor_it_does_not_use(
        panel: pd.DataFrame) -> None:
    """Codex round 2: selecting spec4's sample on contemporaneous rv_z would make a
    lagged design depend on a contemporaneous variable."""
    lagged = K1694.build_lagged_frame(panel)
    assert "rv_z" not in K1694.SPEC4_RHS
    assert lagged["rv_z"].isna().any(), (
        "every retained row happens to have rv_z, so this gate proved nothing; "
        "check build_lagged_frame still drops only on SPEC4_RHS")
    assert lagged[[c for c in K1694.SPEC4_RHS if c != "t"]].isna().sum().sum() == 0


# --- defect 2: a missing RV must not be silently labelled low-volatility ---

def test_highvol_is_nan_when_rv_is_missing(panel: pd.DataFrame) -> None:
    assert int((panel["rv"].isna() & panel["highvol"].notna()).sum()) == 0
    assert int(panel["rv"].isna().sum()) == int(panel["highvol"].isna().sum())


def test_highvol_pit_is_nan_when_rv_is_missing(panel: pd.DataFrame) -> None:
    assert int((panel["rv"].isna() & panel["highvol_pit"].notna()).sum()) == 0


# --- defect 3: the bootstrap's name must match what it resamples ---

def test_bootstrap_names_are_honest(results: dict) -> None:
    boots = results["bootstrap_spec1"]
    assert boots["stationary_block_by_month"]["preserves_serial_correlation"] is True
    assert boots["stationary_block_by_month"]["mean_block_months"] >= 2
    iid = boots["month_cluster_iid"]
    assert iid["preserves_serial_correlation"] is False
    assert "NOT a block bootstrap" in iid["label"]
    assert boots["headline"] == "stationary_block_by_month"


def test_stationary_blocks_are_consecutive_months() -> None:
    rng = np.random.default_rng(0)
    idx = K1694._month_blocks_stationary(120, 6, rng)
    runs = int((np.diff(idx) == 1).sum())
    assert runs > 0.5 * (len(idx) - 1), "blocks are not consecutive in time"


# --- defect 4: partial months excluded by a reproducible rule, not a date ---

def test_partial_months_are_excluded_by_rule(results: dict, panel: pd.DataFrame) -> None:
    cov = results["sample"]["completeness"]
    assert cov["rule"]["date_hardcoded"] is False
    dropped = {m["month"] for m in cov["dropped_partial_dcot_months"]}
    assert "2026-07" in dropped, "the partial DCOT month is still in the panel"
    assert str(panel["month"].max()) not in dropped
    assert results["sample"]["panel_span"][1] == "2026-06"
    # Codex round 4: the count-only RV cache cannot certify complete months, so the
    # claim is withdrawn. The disclosure that replaces it must say what IS certified.
    assert results["sample"]["panel_span_is_complete_months_only"] is False
    basis = results["sample"]["panel_span_completeness_basis"]
    assert "CERTIFIED" in basis and "SCREENED" in basis
    assert "rv_residual_blind_spot" in basis


def test_completeness_rule_holds_on_every_retained_row(panel: pd.DataFrame) -> None:
    assert (panel["nweeks"] >= K1694.MIN_DCOT_WEEKS).all()
    assert (panel["dcot_entry_gap_days"] <= K1694.MAX_DCOT_GAP_DAYS).all()
    assert (panel["dcot_interior_gap_days"].fillna(0) <= K1694.MAX_DCOT_GAP_DAYS).all()
    assert (panel["dcot_tail_gap_days"] <= K1694.MAX_DCOT_TAIL_GAP_DAYS).all()
    have_rv = panel["rv"].notna()
    assert (panel.loc[have_rv, "rv_ndays"] >= K1694.MIN_RV_DAYS).all()
    assert (panel.loc[have_rv, "rv_shortfall_vs_calendar"]
            <= K1694.MAX_RV_SHORTFALL_VS_CALENDAR).all()
    assert (panel.loc[have_rv, "rv_cross_shortfall"]
            <= K1694.MAX_RV_CROSS_SHORTFALL).all()
    assert (panel.loc[have_rv, "rv_month_shortfall"]
            <= K1694.MAX_RV_MONTH_SHORTFALL).all()


def _drop_one_report(dcot: pd.DataFrame, commodity: str, month: str, which: int):
    m = dcot["report_date"].dt.to_period("M")
    in_month = (dcot["commodity"] == commodity) & (m == pd.Period(month, "M"))
    idx = dcot.loc[in_month].sort_values("report_date").index[which]
    return dcot.drop(index=idx)


def _is_complete(cov: pd.DataFrame, commodity: str, month: str) -> bool:
    row = cov.loc[(cov.commodity == commodity) & (cov.month == pd.Period(month, "M"))]
    assert len(row) == 1
    return bool(row["dcot_complete"].iloc[0])


@pytest.mark.parametrize(
    "commodity,month,which,label",
    [("GOLD", "2024-10", 0, "first week -- Codex round-3 counterexample"),
     ("GOLD", "2020-06", 2, "an interior week"),
     ("GOLD", "2020-06", -1, "the last week"),
     ("CORN", "2019-05", 0, "first week, different commodity"),
     ("CORN", "2019-05", 1, "second week")])
def test_completeness_rule_catches_a_skipped_week(commodity, month, which, label) -> None:
    """Deleting ANY single weekly report must make the month incomplete.

    ``GOLD 2024-10`` is Codex's round-3 counterexample verbatim: its reports fall on
    the 1st, 8th, 15th, 22nd and 29th, so deleting the 1st left a month-start-anchored
    head gap of only 7 days and the month passed. Continuity is now measured against
    the previous report, across the month boundary, where the same deletion reads 14.
    """
    dcot, rv = K1694.build_dcot(), K1694.build_vol()
    assert _is_complete(K1694.monthly_coverage(dcot, rv), commodity, month)
    holed = K1694.monthly_coverage(_drop_one_report(dcot, commodity, month, which), rv)
    assert not _is_complete(holed, commodity, month), (
        f"a missing weekly report ({label}) was accepted as a complete month")


def test_completeness_rule_catches_an_independently_truncated_rv_month() -> None:
    """A commodity short of days relative to both the calendar and its peers had its
    own download truncated, even if it clears the absolute MIN_RV_DAYS floor."""
    dcot = K1694.build_dcot()
    rv = K1694.build_vol().copy()
    key = ("GOLD", pd.Period("2020-06", "M"))
    victim = (rv["commodity"] == "GOLD") & (rv["month_end"].dt.to_period("M") == key[1])
    assert victim.sum() == 1
    assert bool(K1694.monthly_coverage(dcot, rv)
                .set_index(["commodity", "month"]).loc[key, "rv_complete"])
    rv.loc[victim, "ndays"] = 16  # still above MIN_RV_DAYS, but short of its peers
    cov = K1694.monthly_coverage(dcot, rv).set_index(["commodity", "month"])
    assert not bool(cov.loc[key, "rv_complete"])


def test_completeness_rule_catches_a_truncation_common_to_every_commodity() -> None:
    """Codex round 3: a cross-sectional check is blind when EVERY commodity loses the
    same days, because the cross-sectional maximum is truncated too. The month-level
    calendar anchor is what catches it."""
    dcot = K1694.build_dcot()
    rv = K1694.build_vol().copy()
    month = pd.Period("2020-06", "M")
    rows = rv["month_end"].dt.to_period("M") == month
    assert rows.sum() > 1
    base = K1694.monthly_coverage(dcot, rv)
    assert base.loc[base.month == month, "rv_complete"].all()
    rv.loc[rows, "ndays"] = rv.loc[rows, "ndays"] - 2  # everyone loses two days
    cov = K1694.monthly_coverage(dcot, rv)
    hit = cov.loc[cov.month == month]
    assert hit["rv_cross_shortfall"].max() == 0, "cross-sectional check is blind here"
    assert not hit["rv_complete"].any(), (
        "a truncation common to every commodity was accepted as a complete month")


def test_common_two_day_truncation_2020_10() -> None:
    """Codex round-4 counterexample 1, verbatim.

    2020-10 has 22 weekdays and one federal holiday CME futures trade through,
    Columbus Day. The retired calendar subtracted it, so ``expected`` read 21 while
    every commodity in the cache actually has 22 days. Truncating all 22 commodities
    by two days then left ``expected - max(ndays) = 1``, inside the month-level
    threshold, and 22/22 rows were still certified -- refuting the claim that a
    common truncation of two days is detected. The calendar no longer subtracts
    Columbus Day, so the same truncation now reads 2 and every row is flagged.
    """
    dcot = K1694.build_dcot()
    rv = K1694.build_vol().copy()
    month = pd.Period("2020-10", "M")
    rows = rv["month_end"].dt.to_period("M") == month
    assert rows.sum() == 22, "the counterexample needs the full 22-commodity month"
    base = K1694.monthly_coverage(dcot, rv)
    in_month = base["month"] == month
    assert base.loc[in_month, "rv_complete"].all(), "untouched month must start complete"
    assert (base.loc[in_month, "rv_ndays"] == 22).all()
    assert base.loc[in_month, "rv_expected_trading_days"].eq(22).all(), (
        "Columbus Day is a trading day for CME futures; expected must count it")

    rv.loc[rows, "ndays"] = rv.loc[rows, "ndays"] - 2  # everyone loses two days
    cov = K1694.monthly_coverage(dcot, rv)
    hit = cov.loc[cov["month"] == month]
    assert hit["rv_cross_shortfall"].max() == 0, "cross-sectional check is blind here"
    assert (hit["rv_month_shortfall"] == 2).all()
    assert not hit["rv_complete"].any(), (
        "a two-day truncation common to every commodity was accepted as complete")


def test_endpoint_truncation_2020_06() -> None:
    """Codex round-4 counterexample 2, verbatim.

    The date-bearing path allowed up to three weekday gaps at each end of the month,
    so dropping 2020-06-30 from every commodity left ``rv_tail_gap_days = 1`` and
    22/22 rows complete -- the same one-day endpoint blind spot the disclosure said
    existed only in the count-only cache. The gate now requires the observed first /
    last day to reach the calendar's first / last trading day exactly.
    """
    dcot = K1694.build_dcot()
    rv = K1694.build_vol().copy()
    assert {"first_day", "last_day"} - set(rv.columns) == {"first_day", "last_day"}, (
        "the frozen cache is count-only; this test injects the dates itself")
    # Injected from the plain weekday boundaries, not from the module's calendar, so
    # this test reproduces Codex's counterexample on the pre-fix code as well.
    per = rv["month_end"].dt.to_period("M")
    rv["first_day"] = [pd.bdate_range(p.start_time, p.end_time)[0] for p in per]
    rv["last_day"] = [pd.bdate_range(p.start_time, p.end_time)[-1] for p in per]

    month = pd.Period("2020-06", "M")
    rows = rv["month_end"].dt.to_period("M") == month
    assert rows.sum() == 22
    base = K1694.monthly_coverage(dcot, rv)
    in_month = base["month"] == month
    assert base.loc[in_month, "rv_complete"].all(), "untouched month must start complete"
    assert (base.loc[in_month, "last_day"] == pd.Timestamp("2020-06-30")).all()

    # every commodity loses the last trading day, and only that day
    rv.loc[rows, "last_day"] = pd.Timestamp("2020-06-29")
    rv.loc[rows, "ndays"] = rv.loc[rows, "ndays"] - 1
    cov = K1694.monthly_coverage(dcot, rv)
    hit = cov.loc[cov["month"] == month]
    assert (hit["rv_tail_gap_days"] == 1).all(), "the retired rule allowed <= 3 here"
    assert (hit["rv_month_shortfall"] == 1).all(), (
        "the count test alone cannot see this: it is inside the one-day tolerance")
    assert not hit["rv_complete"].any(), (
        "a one-day endpoint truncation was accepted as a complete month")


def test_endpoint_gate_accepts_an_untruncated_dated_cache() -> None:
    """The endpoint gate must not simply reject everything: with the calendar's own
    endpoints injected, the dated path certifies the same months the count path does."""
    dcot = K1694.build_dcot()
    rv = K1694.build_vol().copy()
    first, last = K1694.expected_month_endpoints()
    per = rv["month_end"].dt.to_period("M")
    rv["first_day"] = per.map(first)
    rv["last_day"] = per.map(last)
    rv = rv.loc[rv["first_day"].notna() & rv["last_day"].notna()].copy()
    cov = K1694.monthly_coverage(dcot, rv)
    dated = cov.loc[cov["rv"].notna(), "rv_complete"]
    count_only = K1694.monthly_coverage(dcot, K1694.build_vol())
    count_only = count_only.loc[count_only["rv"].notna(), "rv_complete"]
    assert dated.sum() == count_only.sum(), (
        "injecting the calendar's own endpoints must not change which months pass")


def test_rv_endpoint_test_is_declared_unavailable_when_the_cache_lacks_dates(
        results: dict) -> None:
    """The frozen cache stores counts only. Say so; do not claim an endpoint test."""
    rule = results["sample"]["completeness"]["rule"]
    rv_cache_has_dates = {"first_day", "last_day"} <= set(K1694.build_vol().columns)
    if rv_cache_has_dates:
        assert rule["rv_endpoint_test"].startswith("applied")
    else:
        assert rule["rv_endpoint_test"].startswith("UNAVAILABLE")
        assert "does NOT prove" in rule["rv_residual_blind_spot"]
        assert "2012-10" in rule["rv_residual_blind_spot"]
        # Codex round 4: months that pass a count-only screen are not certified.
        assert "NOT certified complete" in rule["rv_residual_blind_spot"]
    # The claim must not appear in the rule's POSITIVE descriptions; the blind-spot
    # field exists precisely to deny it, so it is excluded from the scan.
    positive = json.dumps({k: v for k, v in rule.items()
                           if k != "rv_residual_blind_spot"})
    assert "reached both ends" not in positive


def test_log_oi_has_a_positivity_guard(panel: pd.DataFrame) -> None:
    """Codex round 2: np.log(oi).diff() had no oi>0/finite guard, so an inf would
    survive dropna() into the design matrix."""
    assert int(panel["oi_invalid"].sum()) == 0, "cached OI is expected to be valid"
    assert np.isfinite(panel["dlog_oi"].dropna().to_numpy(dtype=float)).all()
    poisoned = panel.copy()
    poisoned.loc[poisoned.index[:5], "oi"] = 0.0
    poisoned.loc[poisoned.index[5:8], "oi"] = -1.0
    oi_ok = poisoned["oi"].where(np.isfinite(poisoned["oi"]) & (poisoned["oi"] > 0))
    assert oi_ok.iloc[:8].isna().all()
    assert np.isfinite(np.log(oi_ok.dropna().to_numpy(dtype=float))).all()


def test_differences_never_span_a_dropped_month(panel: pd.DataFrame) -> None:
    """Excluding a month must not silently turn the next month into a 2-month diff."""
    non_adjacent = panel.loc[~panel["adjacent_prev_month"]]
    assert non_adjacent["d_nonrep"].notna().sum() == 0
    assert non_adjacent["nonrep_lag"].notna().sum() == 0
    assert non_adjacent["dlog_oi"].notna().sum() == 0


# --- defect 5: the methodology description must match the code ---

def test_bandwidth_rule_is_named_for_what_it_computes(results: dict) -> None:
    assert K1694._hac_bandwidth_rule(149) == 6
    assert not hasattr(K1694, "_acf_bandwidth"), "the misleading name is back"
    rule = results["panel_regressions"]["_hac_bandwidth_rule"]
    assert "not ACF-derived" in rule
    assert "acf" not in results["timeseries_regression"]["hac_lag_rule"].lower() or \
           "not ACF-derived" in results["timeseries_regression"]["hac_lag_rule"]


def test_bandwidth_choice_is_backed_by_a_sensitivity_grid(results: dict) -> None:
    sens = results["dk_bandwidth_sensitivity_spec1"]
    assert [r["bandwidth"] for r in sens["grid"]] == list(range(1, 25))
    assert sens["term"] == "fcm_x_highvol"


def test_promised_lagged_spec_exists_and_is_timed_correctly(results: dict) -> None:
    spec4 = results["panel_regressions"]["spec4_lagged_timing_hardened"]
    assert "fcm_pre_x_highvol_lag" in spec4["rhs"]
    assert "highvol" not in spec4["rhs"], "spec4 must not use the full-sample regime label"
    # Codex round 2: a t-1 DCOT aggregate is not fully published before month t begins
    for banned in ("dlog_oi", "dlog_oi_lag", "nonrep_lag", "d_nonrep_lag"):
        assert banned not in spec4["rhs"], f"spec4 uses {banned}, published too late"
    for needed in ("nonrep_lag2", "d_nonrep_lag2", "dlog_oi_lag2"):
        assert needed in spec4["rhs"]
    assert spec4["n_obs"] > 0


def test_lagged_controls_really_are_two_months_back(panel: pd.DataFrame) -> None:
    p = panel.sort_values(["commodity", "month"]).reset_index(drop=True)
    g = p.groupby("commodity", group_keys=False)
    expect = g["nonrep_share"].shift(2).where(p["adjacent_prev2_months"])
    got = p["nonrep_lag2"]
    assert got.notna().sum() > 0
    assert ((got - expect).abs().fillna(0) < 1e-15).all()
    assert (p.loc[~p["adjacent_prev2_months"], "nonrep_lag2"].notna().sum()) == 0


def test_predictive_spec_signal_precedes_the_outcome_window(panel: pd.DataFrame) -> None:
    have = panel.dropna(subset=["avail_date_pre"])
    assert int((have["avail_date_pre"] >= have["month_start"]).sum()) == 0


def test_primary_merge_is_backward_only(panel: pd.DataFrame) -> None:
    have = panel.dropna(subset=["avail_date"])
    assert int((have["avail_date"] > have["month_end"]).sum()) == 0


# --- defect 6 / 7: the JSON must not overstate, and NULL must be scoped ---

def test_no_spec_claims_prediction(results: dict) -> None:
    """Codex round 2: no spec here can carry a predictive claim -- spec1-3 because of
    the within-month timing overlap, spec4 because its ex-ante status rests on a
    synthetic availability constant. Prose that *denies* prediction is the point, so
    only the claim-bearing surface is searched."""
    assert results["claim_type"] == "ex_post_association"
    assert results["primary_interaction"]["claim_type"] == "ex_post_association"
    banned = ("predictive", "causal", "known-before-outcome", "forecast")
    headline = json.dumps([results["title"], results["primary_interaction"]]).lower()
    for word in banned:
        assert word not in headline, f"headline surface claims '{word}'"
    specs = results["panel_regressions"]
    for label in ("spec1_fcm_highvol", "spec2_fcm_rvz_continuous",
                  "spec3_trader_conc4_highvol"):
        note = specs[label]["note"].lower()
        assert note.startswith("ex-post association"), label
        assert "predictive" not in note, label
    note4 = specs["spec4_lagged_timing_hardened"]["note"].lower()
    assert "conditional" in note4 and "not a verified predictive test" in note4
    assert not note4.startswith("predictive")


def test_nothing_claims_absence_of_predictability(results: dict) -> None:
    reading = results["secondary_findings"][
        "spec4_lagged_timing_hardened"]["reading"].lower()
    assert "not" in reading and "no predictability" in reading
    assert "no predictability" in results["claim_language_rule"].lower()


def test_nothing_claims_absence_of_association(results: dict) -> None:
    """Codex round 3: 'no association survives this timing' is still an absence
    claim, and it contradicts the artifact's own 'cannot establish absence'."""
    searchable = json.dumps({k: v for k, v in results.items()
                             if k != "claim_language_rule"}).lower()
    assert "no association survives" not in searchable
    # "there is no association" may appear only where the text forbids it
    start = 0
    while (hit := searchable.find("there is no association", start)) != -1:
        context = searchable[max(0, hit - 30):hit]
        assert "never" in context or "not " in context, (
            f"absence claim asserted at offset {hit}: "
            f"...{searchable[max(0, hit - 60):hit + 30]}...")
        start = hit + 1
    reading = results["secondary_findings"][
        "spec4_lagged_timing_hardened"]["reading"]
    assert "NOT SUPPORTED under this timing" in reading
    # In the README's claim section the phrase may appear ONLY inside a denial
    # ("it is not 'no association'"). A blacklist cannot tell an assertion from its
    # retraction, so require every occurrence to sit next to a negation marker.
    claims = (HERE / "README.md").read_text().split("## Codex round")[0]
    for phrase in ("沒有關聯", "不存在關聯"):
        start = 0
        while (hit := claims.find(phrase, start)) != -1:
            context = claims[max(0, hit - 24):hit]
            assert any(neg in context for neg in ("不是", "不能", "非")), (
                f"README claim section asserts {phrase!r} at offset {hit}: "
                f"...{claims[max(0, hit - 40):hit + 20]}...")
            start = hit + len(phrase)


def test_within_month_overlap_count_is_scoped_to_the_estimation_sample(
        results: dict, frame: pd.DataFrame) -> None:
    """Codex round 3: the README quoted N/N estimation rows while the JSON field was
    computed over the whole panel."""
    prov = results["data_provenance"]
    assert "fcm_avail_inside_outcome_month_rows" not in prov, "ambiguous key is back"
    n = prov["fcm_avail_inside_outcome_month_rows_in_estimation_sample"]
    assert prov["estimation_sample_rows"] == len(frame)
    assert n <= len(frame)
    assert f"{n}/{len(frame)}" in (HERE / "README.md").read_text()


def test_null_is_worded_as_not_supported_not_as_disproved(results: dict) -> None:
    """Codex round 2: the estimators establish 未獲支持, never 不成立."""
    scope = results["verdict_scope"]
    assert "NOT SUPPORTED" in scope
    assert "cannot establish that the effect is absent" in scope
    # Scope the scan to the README's CLAIM sections. Everything from the first
    # "## Codex round" heading down is a repair log that necessarily quotes the
    # banned wording in order to record that it was removed; a flat word blacklist
    # cannot tell a claim from its own retraction.
    readme = (HERE / "README.md").read_text()
    claims = readme.split("## Codex round")[0]
    assert "## Codex round" in readme, "repair-log boundary moved; re-scope this gate"
    assert "不成立" not in claims, "README still says the hypothesis is disproved"
    assert "未獲支持" in claims
    # Same exclusion as above: claim_language_rule is the rule that forbids the word,
    # so it necessarily contains it.
    searchable = json.dumps({k: v for k, v in results.items()
                             if k != "claim_language_rule"}).lower()
    for word in ("disproved", "ruled out", "no effect exists"):
        assert word not in searchable
    assert "never as disproved" in results["claim_language_rule"].lower()


def test_effective_temporal_dof_is_disclosed_not_asserted_independent(
        results: dict) -> None:
    dof = results["sample"]["effective_temporal_dof"]
    acf = dof["hhi_seg_z_autocorrelation"]
    assert acf["acf1"] > 0.9 and acf["acf6"] > 0.5
    assert "below" in dof["reading"].lower()
    blob = json.dumps(results).lower()
    assert "independent fcm variation" not in blob
    assert "months of independent" not in blob


def test_limitations_cover_every_disclosure_codex_named(results: dict) -> None:
    blob = " ".join(results["limitations"]).lower()
    for token in ("synthetic", "timing overlap", "full-sample", "serial correlation"):
        assert token in blob, f"limitations omit '{token}'"


def test_null_is_scoped_and_names_the_positive_continuous_result(results: dict) -> None:
    assert results["verdict"] == "NULL"
    scope = results["verdict_scope"].lower()
    assert "negative" in scope and "binary" in scope
    assert "no association" in scope
    sec = results["secondary_findings"][
        "spec2_continuous_interaction_is_positive_and_significant"]
    assert sec["coef"] > 0
    assert abs(sec["t_driscoll_kraay"]) >= 1.96


def test_no_stale_bootstrap_key_impersonating_a_spec1_ci(results: dict) -> None:
    assert "bootstrap_interaction_spec1" not in results
    assert "bootstrap_ci95" not in results["primary_interaction"]


# --- defect 8: reproduce_spec.json must be a side effect of the run ---

def test_reproduce_spec_pins_the_bytes_that_ran(results: dict, spec: dict) -> None:
    assert spec["schema_version"] == "volpred.reproduce_spec.v1"
    assert spec["entrypoint"]["sha256"] == results["code_trace"]["sha256"]
    assert spec["entrypoint"]["size_bytes"] == results["code_trace"]["size_bytes"]
    on_disk = (HERE / "K1694.py").read_bytes()
    import hashlib
    assert hashlib.sha256(on_disk).hexdigest() == spec["entrypoint"]["sha256"], (
        "K1694.py changed after the run that produced these results -- rerun, do not "
        "refresh the checksum")


def test_reproduce_spec_pins_the_result_bytes(spec: dict) -> None:
    import hashlib
    ident = spec["canonical_result_identity"]
    raw = (HERE / ident["path"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == ident["sha256"]
    assert len(raw) == ident["size_bytes"]


def test_reproduce_spec_declares_seed_and_inputs(spec: dict) -> None:
    assert spec["randomness"]["status"] == "declared"
    assert {"library": "numpy", "value": K1694.SEED} in spec["randomness"]["seeds"]
    inputs = {Path(i["path"]).name for i in spec["inputs"]}
    assert {"fcm_monthly.csv", "dcot_weekly.csv", "rv_monthly.csv"} <= inputs
