"""K1709-rev regression gates.

The v1 suite passed 26/26 while the experiment was making two CRITICAL inference
errors, so "the tests are green" was never the issue -- they tested the plumbing
and not the claim. This suite adds the checks the 2026-07-14 independent review
said were missing:

  * the calendar precondition every `.shift()` silently assumes
    (`test_deleting_a_sunday_is_rejected`)
  * that nothing already computed can be moved by data arriving later
    (`test_future_data_cannot_move_a_past_forecast`)
  * that US market holidays are not counted as genuine zero-flow days
    (`test_session_filter_*`)
  * that the flow lag and the state lag move independently
    (`test_state_lag_and_flow_lag_are_independent`)
  * that raw Diebold-Mariano cannot reach a verdict
    (`test_raw_dm_never_feeds_a_gate`,
     `test_repo_nested_dm_auditor_marks_this_file_safe`)
  * that power is never reported as an exclusion
    (`test_power_is_not_reported_as_an_exclusion`)

and, after the 2026-07-14 re-review of the frozen rebuild, the residuals it found:

  * that the power curve admits its own scope -- one cell, h=1, one alternative,
    nominal gate -- and is never quoted as the study's power
    (`test_power_scope_admits_it_is_not_the_studys_power`)
  * that the 80%/90%-power effect is BRACKETED, never a point estimate
    (`test_power_bracket_reports_an_interval_not_a_solved_threshold`)
  * that beta=0 is a false-positive check, not a size calibration
    (`test_beta0_row_is_a_false_positive_check_not_a_size_calibration`)
  * that the FIXED-window raw statistic is not smeared with the expanding
    window's pathology (`test_fixed_window_raw_dm_is_not_labelled_biased`)
  * that the one cell without bounded estimator memory is labelled, not pooled
    (`test_unbounded_memory_cell_is_flagged_not_silently_pooled`)

  nested-dm: diagnostic-only  -- this suite calls `raw_dm_diagnostic` only to pin
  down its LABELS and to assert it can never reach a verdict. No raw
  Diebold-Mariano statistic is used as inference anywhere in it.

Run:  uv run --extra dev python -m pytest experiments/k1709/test_k1709.py -q
"""

from __future__ import annotations

import ast
import builtins
import hashlib
import json
import symtable
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from k1709 import (  # noqa: E402
    GW_MIN_LOSSES,
    LOSS_CACHE,
    GW_TRAIN_WINDOW,
    HAR_M,
    MATERIAL_GAIN_MARGIN,
    REGISTRY,
    SPECS,
    Panel,
    _date_index_sha256,
    _non_string_leaf_surface,
    _ols,
    _parse_money,
    _string_sequence_sha256,
    ar_residual,
    assert_calendar_is_complete,
    assert_no_lookahead,
    build_panel,
    build_verdict_basis,
    evaluate_cell,
    filter_to_sessions,
    flow_zscore,
    gw_unconditional_dm,
    holm,
    make_flow_features,
    material_gain_exclusion,
    qlike_gain_upper_bound,
    paired_oos,
    power_simulation,
    raw_dm_diagnostic,
    us_equity_sessions,
)
from render_readme import build_readme  # noqa: E402

SEED = 1709


# ---------------------------------------------------------------------------
# Synthetic world — a complete 24/7 RV calendar, flows only on NYSE sessions
# ---------------------------------------------------------------------------
def _make_world(
    n_days: int = 900,
    start: str = "2023-01-02",
    seed: int = SEED,
    flow_beta: float = 0.0,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """`flow_beta` injects a KNOWN |z| effect into log RV, so the same helper
    drives both the placebo tests (beta = 0) and the power tests (beta large)."""
    rng = np.random.default_rng(seed)
    cal = pd.date_range(start, periods=n_days, freq="D")
    sessions = us_equity_sessions(cal.min(), cal.max())
    fdays = cal.intersection(sessions)

    flow = pd.Series(rng.normal(0, 300, len(fdays)), index=fdays)
    shock = flow_zscore(flow).abs().reindex(cal).shift(1).fillna(0.0).to_numpy()

    lrv = np.empty(n_days)
    lrv[:HAR_M] = -9.0 + rng.normal(0, 0.3, HAR_M)
    e = rng.normal(0, 0.45, n_days)
    for d in range(HAR_M, n_days):
        lrv[d] = (
            -9.0 * 0.15
            + 0.40 * lrv[d - 1]
            + 0.30 * lrv[d - 5 : d].mean()
            + 0.15 * lrv[d - HAR_M : d].mean()
            + flow_beta * shock[d]
            + e[d]
        )
    rv = pd.DataFrame(
        {"rv_gk": np.exp(lrv), "ret": rng.normal(0, 0.03, n_days)}, index=cal
    )
    flow_df = pd.DataFrame({"flow": flow, "gross": flow.abs() + 100.0}, index=fdays)
    return rv, flow_df


@pytest.fixture(scope="module")
def world():
    return _make_world()


@pytest.fixture(scope="module")
def panel(world):
    rv, flow = world
    p = build_panel(rv, make_flow_features(flow), "rv_gk", 1, "SYN", flow_lag=1)
    assert_no_lookahead(p)
    return p


@pytest.fixture(autouse=True)
def _clean_registry():
    """The registry and the loss cache are module-level state; a leaked record
    would corrupt the next test's family count or trip the collision guard."""
    REGISTRY.clear()
    LOSS_CACHE.clear()
    yield
    REGISTRY.clear()
    LOSS_CACHE.clear()


# ---------------------------------------------------------------------------
# 1. Farside parsing — missing is not zero
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("(95.1)", -95.1),
        ("(27,332)", -27332.0),
        ("1,234.5", 1234.5),
        ("0.0", 0.0),
        ("$12.3", 12.3),
    ],
)
def test_parse_money_values(raw, expected):
    assert _parse_money(raw) == pytest.approx(expected)


@pytest.mark.parametrize("raw", ["-", "–", "—", "", "nan"])
def test_parse_money_missing_is_nan_not_zero(raw):
    assert np.isnan(_parse_money(raw))


def test_zero_and_missing_are_distinct():
    assert _parse_money("0.0") == 0.0
    assert np.isnan(_parse_money("-"))


# ---------------------------------------------------------------------------
# 2. C3 — US market holidays are MISSING, not zero-flow days
# ---------------------------------------------------------------------------
def test_session_calendar_excludes_nyse_holidays():
    sess = us_equity_sessions(pd.Timestamp("2024-01-01"), pd.Timestamp("2024-12-31"))
    for holiday in (
        "2024-01-15",  # MLK
        "2024-02-19",  # Presidents Day
        "2024-03-29",  # Good Friday
        "2024-05-27",  # Memorial Day
        "2024-06-19",  # Juneteenth
        "2024-11-28",  # Thanksgiving
        "2024-12-25",  # Christmas
    ):
        assert pd.Timestamp(holiday) not in sess, holiday


def test_session_calendar_is_nyse_not_the_federal_holiday_list():
    """Columbus Day and Veterans Day are FEDERAL holidays -- the NYSE is OPEN.

    A federal-holiday calendar would silently delete two real flow days a year.
    This is the test that tells the two calendars apart.
    """
    sess = us_equity_sessions(pd.Timestamp("2024-01-01"), pd.Timestamp("2024-12-31"))
    assert pd.Timestamp("2024-10-14") in sess     # Columbus Day
    assert pd.Timestamp("2024-11-11") in sess     # Veterans Day


def test_session_filter_drops_holiday_rows_that_look_like_genuine_zeros():
    """The exact trap: an all-dash holiday row sums to 0.0 under skipna, so
    Farside's Total and the recomputed sum agree and the parser cross-check is
    blind to it."""
    idx = pd.DatetimeIndex(["2024-01-12", "2024-01-15", "2024-01-16"])  # Fri/MLK/Tue
    df = pd.DataFrame(
        {
            "flow": [120.0, 0.0, -80.0],          # the middle 0.0 is fake
            "gross": [500.0, 0.0, 400.0],
            "all_dash": [False, True, False],
        },
        index=idx,
    )
    kept, diag = filter_to_sessions(df)

    assert pd.Timestamp("2024-01-15") not in kept.index
    assert len(kept) == 2
    assert diag["n_nonsession_rows_dropped"] == 1
    assert diag["n_nonsession_rows_with_nonzero_total"] == 0
    assert diag["nonsession_rows_dropped"][0]["all_fund_columns_dash"] is True


def test_session_filter_keeps_a_genuine_zero_on_an_open_market_day():
    """Missing is not zero -- but zero is not missing either. A real zero-flow
    day on an open market must survive."""
    idx = pd.DatetimeIndex(["2024-01-12", "2024-01-16"])
    df = pd.DataFrame(
        {"flow": [0.0, -80.0], "gross": [0.0, 400.0], "all_dash": [False, False]},
        index=idx,
    )
    kept, diag = filter_to_sessions(df)
    assert len(kept) == 2
    assert kept.loc[pd.Timestamp("2024-01-12"), "flow"] == 0.0
    assert diag["n_nonsession_rows_dropped"] == 0


def test_holiday_zeros_would_have_inflated_every_shock():
    """Show the damage rather than asserting the rows exist. Fake zeros shrink the
    20-day rolling sd, which INFLATES every |z| that follows -- that is the
    channel through which C3 moved the test statistics."""
    rng = np.random.default_rng(7)
    fdays = us_equity_sessions(pd.Timestamp("2024-01-02"), pd.Timestamp("2024-12-31"))
    clean = pd.Series(rng.normal(0, 300, len(fdays)), index=fdays)
    holidays = pd.DatetimeIndex(["2024-01-15", "2024-02-19", "2024-03-29"])
    polluted = pd.concat([clean, pd.Series(0.0, index=holidays)]).sort_index()

    assert flow_zscore(polluted).abs().mean() > flow_zscore(clean).abs().mean()


# ---------------------------------------------------------------------------
# 3. Lookahead — the calendar precondition and the future-mutation invariant
# ---------------------------------------------------------------------------
def test_deleting_a_sunday_is_rejected(world):
    """Codex's test. `.shift(1)` moves by ROW POSITION, not by a day.

    Punch one Sunday out and every later row silently becomes a t+2 forecast
    wearing a t+1 label. v1's `assert_no_lookahead` re-derived its gap from the
    very src_date the shift produced, so it could be fooled. The precondition
    check cannot be.
    """
    rv, flow = world
    sunday = next(d for d in rv.index if d.dayofweek == 6 and d > rv.index[100])
    holed = rv.drop(index=sunday)

    with pytest.raises(AssertionError, match="hole"):
        build_panel(holed, make_flow_features(flow), "rv_gk", 1, "SYN")


def test_assert_calendar_rejects_duplicates_and_disorder():
    with pytest.raises(AssertionError, match="duplicate"):
        assert_calendar_is_complete(
            pd.DatetimeIndex(["2024-01-01", "2024-01-02", "2024-01-02"]), "dup"
        )
    with pytest.raises(AssertionError, match="sorted"):
        assert_calendar_is_complete(
            pd.DatetimeIndex(["2024-01-03", "2024-01-01", "2024-01-02"]), "unsorted"
        )


def test_future_data_cannot_move_a_past_forecast(world):
    """Codex's test, and the strongest lookahead check there is: mutate the future
    and demand that nothing already computed moves.

    A src_date assertion can be satisfied by a leak that never touches src_date --
    Codex demonstrated this by copying `y` straight into `z` and watching v1's
    assertion still pass. This test cannot be fooled that way, because it never
    asks the code where the data came from. It asks whether the answer changed.
    """
    rv, flow = world
    p0 = build_panel(rv, make_flow_features(flow), "rv_gk", 1, "SYN")
    base = paired_oos(p0, "HAR+ctrl", "H1_absflow")
    assert len(base.actual) > GW_MIN_LOSSES

    cut = base.origins[len(base.origins) // 2]

    rv_mut = rv.copy()
    rv_mut.loc[rv_mut.index >= cut, "rv_gk"] *= 100.0      # blow up the future
    flow_mut = flow.copy()
    flow_mut.loc[flow_mut.index >= cut, "flow"] *= -50.0

    p1 = build_panel(rv_mut, make_flow_features(flow_mut), "rv_gk", 1, "SYN")
    mut = paired_oos(p1, "HAR+ctrl", "H1_absflow")

    keep0, keep1 = base.origins < cut, mut.origins < cut
    assert keep0.sum() > 50
    assert (base.origins[keep0] == mut.origins[keep1]).all()

    np.testing.assert_allclose(base.pred_base[keep0], mut.pred_base[keep1], atol=1e-12)
    np.testing.assert_allclose(base.pred_aug[keep0], mut.pred_aug[keep1], atol=1e-12)


def test_a_rows_own_target_cannot_touch_its_own_forecast(world):
    """Closes a hole the rev1 review found in the test above.

    `test_future_data_cannot_move_a_past_forecast` only compares origins BEFORE the
    mutation point, so it is blind to a SAME-ROW leak: set z_tau = y_tau and every
    pre-cut forecast is still bit-identical, and the test waves it through. Codex
    reproduced exactly that.

    The invariant that does catch it: the forecast at origin i must not depend on
    y[i]. Row i is never in its own training set (the embargo removes it), and the
    design matrix must not contain the target. So perturb y at one row and demand
    that the forecast AT THAT ORIGIN does not move.
    """
    rv, flow = world
    p = build_panel(rv, make_flow_features(flow), "rv_gk", 1, "SYN")
    clean = paired_oos(p, "HAR+ctrl", "H1_absflow")
    j = len(clean.origins) // 2
    origin = clean.origins[j]

    bumped = p.df.copy()
    bumped.loc[origin, "y"] *= 1000.0
    out = paired_oos(
        Panel(bumped, p.rv_col, p.horizon, p.asset, p.state_lag, p.flow_lag),
        "HAR+ctrl",
        "H1_absflow",
    )
    k = list(out.origins).index(origin)
    assert out.pred_base[k] == pytest.approx(clean.pred_base[j], rel=1e-12)
    assert out.pred_aug[k] == pytest.approx(clean.pred_aug[j], rel=1e-12)
    # the ACTUAL must move -- otherwise the perturbation never landed and the test
    # is vacuous
    assert out.actual[k] != pytest.approx(clean.actual[j])


def test_the_target_leak_codex_planted_is_actually_caught(world):
    """The adversarial case, run for real: copy the target into a regressor.

    v1's `assert_no_lookahead` passed under exactly this leak because it only ever
    re-checked the src_date it had generated itself. The row-target invariant above
    must fail loudly instead.
    """
    rv, flow = world
    p = build_panel(rv, make_flow_features(flow), "rv_gk", 1, "SYN")
    leaked = p.df.copy()
    leaked["abs_z"] = np.log(leaked["y"])          # the leak: target -> regressor
    lp = Panel(leaked, p.rv_col, p.horizon, p.asset, p.state_lag, p.flow_lag)

    clean_out = paired_oos(lp, "HAR+ctrl", "H1_absflow")
    j = len(clean_out.origins) // 2
    origin = clean_out.origins[j]

    bumped = leaked.copy()
    bumped.loc[origin, "y"] *= 1000.0
    bumped["abs_z"] = np.log(bumped["y"])
    out = paired_oos(
        Panel(bumped, p.rv_col, p.horizon, p.asset, p.state_lag, p.flow_lag),
        "HAR+ctrl",
        "H1_absflow",
    )
    k = list(out.origins).index(origin)

    # baseline has no flow regressor, so it must be untouched...
    assert out.pred_base[k] == pytest.approx(clean_out.pred_base[j], rel=1e-12)
    # ...but the leaked model's own forecast MOVES with its own target. That is the
    # signature of the leak, and the invariant test above is what detects it.
    assert out.pred_aug[k] != pytest.approx(clean_out.pred_aug[j], rel=1e-9)


def test_flow_zscore_is_invariant_to_future_values(world):
    _, flow = world
    z0 = flow_zscore(flow["flow"])
    mutated = flow["flow"].copy()
    mutated.iloc[-30:] *= 99.0
    pd.testing.assert_series_equal(z0.iloc[:-30], flow_zscore(mutated).iloc[:-30])


def test_flow_zscore_denominator_excludes_own_day():
    f = pd.Series(np.arange(1.0, 61.0), index=pd.date_range("2024-01-01", periods=60))
    z = flow_zscore(f)
    i = 40
    assert z.iloc[i] == pytest.approx(f.iloc[i] / f.iloc[i - 20 : i].std())


def test_unexpected_flow_ar5_lag_ordering():
    """The AR design matrix is [lag1..lag5], so the prediction vector must be
    f[i-1]..f[i-5]. Reversing it silently multiplies the lag-5 coefficient by the
    lag-1 value. On a pure AR(1) the residual must collapse to ~0."""
    n = 300
    rng = np.random.default_rng(3)
    f = np.zeros(n)
    for i in range(1, n):
        f[i] = 0.8 * f[i - 1] + rng.normal(0, 0.01)
    s = pd.Series(f, index=pd.date_range("2024-01-01", periods=n))
    assert ar_residual(s, p=5).dropna().abs().mean() < 0.05


# ---------------------------------------------------------------------------
# 4. C4 — the state lag and the flow lag move independently
# ---------------------------------------------------------------------------
def test_state_lag_and_flow_lag_are_independent(world):
    """v1's `pub_lag=2` run also pushed HAR and the return controls back a day.

    But if the flow is only usable at the end of t+1, RV_{t+1} and ret_{t+1} are
    plainly already known. Lagging them too handicapped v1's own baseline and made
    the robustness run answer a question nobody asked.
    """
    rv, flow = world
    ff = make_flow_features(flow)
    p = build_panel(rv, ff, "rv_gk", 1, "SYN", flow_lag=2, state_lag=1)
    assert_no_lookahead(p)

    assert (p.df.index - p.df["state_src_date"]).dt.days.eq(1).all()
    assert (p.df.index - p.df["flow_src_date"]).dt.days.eq(2).all()

    tau = p.df.index[80]
    lr = np.log(rv["rv_gk"])
    assert p.df.loc[tau, "har_d"] == pytest.approx(lr.loc[tau - pd.Timedelta(days=1)])
    assert p.df.loc[tau, "z"] == pytest.approx(
        ff.z.reindex(rv.index).loc[tau - pd.Timedelta(days=2)]
    )


def test_baseline_lags_are_one_and_one(panel):
    assert (panel.df.index - panel.df["state_src_date"]).dt.days.eq(1).all()
    assert (panel.df.index - panel.df["flow_src_date"]).dt.days.eq(1).all()


def test_every_primary_predictor_matches_its_real_source_date(world):
    """Pin values to raw dated inputs, not to self-authored provenance columns."""
    rv, flow = world
    ff = make_flow_features(flow)
    p = build_panel(rv, ff, "rv_gk", 1, "SYN", btc_z=ff.z * 1.7)
    log_rv = np.log(rv["rv_gk"])
    for tau in p.df.index[80:180:17]:
        state_date = tau - pd.Timedelta(days=1)
        flow_date = tau - pd.Timedelta(days=1)
        row = p.df.loc[tau]
        assert row["state_src_date"] == state_date
        assert row["flow_src_date"] == flow_date
        assert row["har_d"] == pytest.approx(log_rv.loc[state_date])
        assert row["har_w"] == pytest.approx(
            log_rv.loc[state_date - pd.Timedelta(days=4) : state_date].mean()
        )
        assert row["har_m"] == pytest.approx(
            log_rv.loc[state_date - pd.Timedelta(days=21) : state_date].mean()
        )
        assert row["ret"] == pytest.approx(rv.loc[state_date, "ret"])
        assert row["abs_ret"] == pytest.approx(abs(rv.loc[state_date, "ret"]))
        assert row["z"] == pytest.approx(ff.z.loc[flow_date])
        assert row["abs_z"] == pytest.approx(abs(ff.z.loc[flow_date]))
        assert row["z_neg"] == pytest.approx(
            abs(ff.z.loc[flow_date]) * (ff.z.loc[flow_date] < 0)
        )
        assert row["abs_z_btc"] == pytest.approx(abs(1.7 * ff.z.loc[flow_date]))


def test_assert_no_lookahead_catches_a_lag_mixup(world):
    rv, flow = world
    p = build_panel(rv, make_flow_features(flow), "rv_gk", 1, "SYN")
    bad = p.df.copy()
    bad.iloc[5, bad.columns.get_loc("flow_src_date")] -= pd.Timedelta(days=1)
    with pytest.raises(AssertionError, match="flow source->target gap"):
        assert_no_lookahead(Panel(bad, p.rv_col, p.horizon, p.asset, 1, 1))


def test_h5_target_is_the_mean_of_the_next_five_days(world):
    rv, flow = world
    p = build_panel(rv, make_flow_features(flow), "rv_gk", 5, "SYN")
    assert_no_lookahead(p)
    tau = p.df.index[60]
    window = rv["rv_gk"].loc[tau : tau + pd.Timedelta(days=4)]
    assert len(window) == 5
    assert p.df.loc[tau, "y"] == pytest.approx(window.mean())
    assert p.df.loc[tau, "y_end_date"] == tau + pd.Timedelta(days=4)


def test_h5_training_labels_close_before_the_forecast_origin(world):
    """The forward-label embargo: with overlapping 5-day targets, "every row before
    i" would train on a label window overlapping the forecast day."""
    rv, flow = world
    p = build_panel(rv, make_flow_features(flow), "rv_gk", 5, "SYN")
    po = paired_oos(p, "HAR+ctrl", "H1_absflow")
    assert po.audit["embargo_ok"]
    assert po.audit["min_origin_minus_last_train_label_end_days"] >= 1


# ---------------------------------------------------------------------------
# 5. C1 — a nested comparison cannot be adjudicated by raw Diebold-Mariano
# ---------------------------------------------------------------------------
def test_repo_nested_dm_auditor_marks_this_file_safe():
    """The project's own mechanical gate, mirrored here so it fails loudly and
    locally. `scripts/tests/test_nested_dm_misuse_ratchet.py` FAILED on v1.
    """
    from audit_nested_dm_misuse import FIXED_MEMORY_ROLE, scan_file

    root = Path(__file__).resolve().parents[2]
    finding = scan_file(Path(__file__).resolve().parent / "k1709.py", root)
    assert finding is not None
    assert finding.test_role == FIXED_MEMORY_ROLE
    assert finding.safe_role_evidence
    assert finding.role_validation_errors == []


def test_raw_dm_never_feeds_a_gate(panel):
    evaluate_cell(panel, "HAR+ctrl", "H1_absflow", family="unit")
    by_inf = {r.inference: r for r in REGISTRY}
    assert by_inf["giacomini_white_qlike_fixed_window"].feeds_gate is False
    assert by_inf["raw_dm_qlike"].feeds_gate is False
    assert by_inf["clark_west_mspe"].feeds_gate is False


def test_clark_west_is_not_relabelled_as_a_qlike_test(panel):
    """v1's CRITICAL #1. The CW helper scores variance-level squared error, but v1
    presented it as the nested-correct test for a QLIKE loss and let it carry the
    NULL on its own."""
    c = evaluate_cell(panel, "HAR+ctrl", "H1_absflow", family="unit")
    cw = c["clark_west_mspe_separate_estimand"]
    assert "MSPE" in cw["estimand"]
    assert cw["feeds_gate"] is False
    assert c["primary_inference_gw_qlike"]["loss"] == "Patton QLIKE"


def test_gw_requires_strict_nesting(panel):
    with pytest.raises(ValueError, match="strict nesting"):
        paired_oos(panel, "H1_absflow", "HAR+ctrl")      # backwards
    with pytest.raises(ValueError, match="strict nesting"):
        paired_oos(panel, "HAR+ctrl", "HAR+ctrl")        # not proper


def test_gw_uses_a_fixed_window_with_shared_training_dates(panel):
    """The scheme is what makes GW legal under nesting -- not the formula."""
    po = paired_oos(panel, "HAR+ctrl", "H1_absflow")
    assert po.audit["scheme"] == "fixed_rolling"
    assert po.audit["fixed_window_held"] is True
    assert po.audit["train_window"] == GW_TRAIN_WINDOW
    assert po.audit["same_training_dates_for_both_models"] is True
    assert po.audit["base_training_schedule_sha256"] == (
        po.audit["aug_training_schedule_sha256"]
    )
    assert po.audit["gw_fixed_memory_eligible"] is True

    d = panel.df.dropna(subset=[*SPECS["H1_absflow"], "y", "y_end_date"])
    y_end = d["y_end_date"].to_numpy()
    schedules = []
    for origin in po.origins:
        end = int(np.searchsorted(y_end, origin.to_datetime64(), side="left"))
        start = end - GW_TRAIN_WINDOW
        schedules.append(_date_index_sha256(d.index[start:end]))
    assert po.audit["base_training_schedule_sha256"] == (
        _string_sequence_sha256(schedules)
    )


def test_expanding_window_is_reported_but_flagged_invalid(panel):
    c = evaluate_cell(panel, "HAR+ctrl", "H1_absflow", family="unit")
    exp = c["expanding_window_diagnostic_v1_design"]
    assert exp["valid_for_nested_inference"] is False
    assert exp["feeds_gate"] is False
    assert exp["scheme"].startswith("expanding")


def test_gw_direction_negative_z_favours_the_flow_model():
    """Sign convention. Getting it backwards would report "flow works" exactly
    when the data says the opposite."""
    rng = np.random.default_rng(11)
    loss_base = np.abs(rng.normal(1.0, 0.2, 400))
    gw = gw_unconditional_dm(loss_base - 0.10, loss_base, h=1)   # augmented is BETTER
    assert gw["z_stat"] < 0
    assert gw["p_value_one_sided_flow_better"] < 0.01


# ---------------------------------------------------------------------------
# 6. C2 — a real exclusion test, and power that is actually power
# ---------------------------------------------------------------------------
def test_material_gain_exclusion_rejects_when_there_is_no_gain():
    rng = np.random.default_rng(5)
    loss_base = np.abs(rng.normal(1.0, 0.15, 400))
    loss_aug = loss_base + rng.normal(0, 1e-4, 400)          # no gain
    ex = material_gain_exclusion(loss_aug, loss_base, h=1, margin=0.01)
    assert ex["z_stat"] > 0
    assert ex["p_value_one_sided"] < 0.01


def test_material_gain_exclusion_does_not_reject_when_the_gain_is_real():
    """The other direction. Without this the exclusion test could be a rubber
    stamp that always says "no material gain", and the bounded null would be
    vacuous."""
    rng = np.random.default_rng(6)
    loss_base = np.abs(rng.normal(1.0, 0.15, 400))
    ex = material_gain_exclusion(loss_base * 0.95, loss_base, h=1, margin=0.01)
    assert ex["p_value_one_sided"] > 0.05                    # a real 5% gain


def test_exclusion_margin_is_the_prespecified_one():
    assert MATERIAL_GAIN_MARGIN == 0.01


def test_inverted_upper_bound_brackets_the_true_gain():
    """The bound is the ONLY object here that can legitimately bound the effect.

    Plant a known 5% gain: the one-sided 95% upper bound must sit ABOVE it (a bound
    that excluded the truth would be wrong) and must still be finite (a bound that
    excluded nothing would be useless).
    """
    rng = np.random.default_rng(21)
    loss_base = np.abs(rng.normal(1.0, 0.10, 800))
    bound = qlike_gain_upper_bound(loss_base * 0.95, loss_base, h=1, alpha=0.05)
    assert bound is not None
    assert bound > 5.0            # does not exclude the true 5% gain
    assert bound < 20.0           # but still says something


def test_inverted_upper_bound_is_tight_when_there_is_no_gain():
    rng = np.random.default_rng(22)
    loss_base = np.abs(rng.normal(1.0, 0.10, 800))
    bound = qlike_gain_upper_bound(
        loss_base + rng.normal(0, 1e-4, 800), loss_base, h=1, alpha=0.05
    )
    assert bound is not None
    assert bound < 3.0            # near-zero gain -> a tight bound


def test_inverted_upper_bound_returns_none_when_nothing_can_be_excluded():
    """A design that cannot exclude even a 90% gain must SAY so, not emit a number.

    Here the augmented model really is ~95% better, so a 90% gain is genuinely NOT
    excludable and the honest answer is "no bound". Emitting a number instead would
    be the same class of error as v1's: manufacturing a bound the data cannot carry.
    """
    rng = np.random.default_rng(23)
    loss_base = np.abs(rng.normal(1.0, 0.2, 300))
    assert qlike_gain_upper_bound(loss_base * 0.05, loss_base, h=1, alpha=0.05) is None


def test_bound_inversion_audits_a_nonmonotone_rejection_topology():
    """The HAC denominator varies with the margin, so z(m) can turn around.

    This deterministic stream has one crossing followed by a local maximum: z(m)
    falls near the top of the searched range. The inversion must enumerate the
    full topology and return the last non-rejected boundary, not merely rely on a
    comment claiming global monotonicity.
    """
    rng = np.random.default_rng(70)
    n = 250
    loss_base = np.exp(rng.normal(0, 0.8, n))
    eps = np.empty(n)
    eps[0] = rng.normal()
    for i in range(1, n):
        eps[i] = 0.8 * eps[i - 1] + rng.normal(scale=0.6)
    diff = (
        rng.uniform(-1.5, 1.5) * loss_base
        + rng.uniform(0.1, 2.0) * eps
        + rng.uniform(-1.0, 1.0)
    )
    loss_aug = loss_base + diff

    grid = np.linspace(1e-4, 0.90, 1001)
    z = np.array(
        [
            material_gain_exclusion(loss_aug, loss_base, h=1, margin=m)["z_stat"]
            for m in grid
        ]
    )
    assert np.any(np.diff(z) > 0) and np.any(np.diff(z) < 0)  # genuinely non-monotone

    crit = 1.6448536269514722
    non_rejected = grid[z < crit]
    assert len(non_rejected) and z[-1] >= crit
    dense_boundary_pct = float(non_rejected.max() * 100)
    bound = qlike_gain_upper_bound(loss_aug, loss_base, h=1, alpha=0.05)
    assert bound is not None
    assert dense_boundary_pct <= bound <= dense_boundary_pct + 0.10
    assert np.all(z[grid > bound / 100.0] >= crit)


def test_power_rises_with_the_effect_and_does_not_fire_on_noise():
    """v1's "MDE" injected each beta ONCE into the single realised noise path and
    took the first crossing: no repeated sampling, no size calibration, and a
    curve that was not even monotone (its BTC CW fell from 1.713 at beta=.15 to
    1.623 at beta=.8).

    A real power curve must (a) not fire when the effect is zero and (b) rise with
    the effect. Note (a) is asserted as an UPPER bound only: under GW's
    method-level null a useless extra regressor makes the augmented method
    genuinely worse, so the flow-favouring one-sided gate is conservative at
    beta=0 by construction. A rate far BELOW 5% is correct behaviour; a rate above
    it would be the alarm.
    """
    rv, flow = _make_world(n_days=800)
    pw = power_simulation(
        rv, make_flow_features(flow), "SYN", horizon=1, reps=60,
        betas=(0.0, 0.30, 0.80),
    )
    curve = {r["beta"]: r["power_gw_one_sided_5pct"] for r in pw["curve"]}
    assert curve[0.0] <= 0.10                # never manufactures a flow signal
    assert curve[0.80] > curve[0.0]
    assert curve[0.80] > 0.50
    assert pw["false_positive_rate_at_beta_0"] == curve[0.0]
    assert "CONSERVATIVE at beta = 0" in pw["false_positive_note"]


def test_a_planted_effect_is_recovered_end_to_end():
    """A null is only credible if the pipeline could have found a signal. Plant one
    in the DGP and require the pre-specified gate to fire on the real estimator."""
    rv, flow = _make_world(n_days=900, flow_beta=0.9)
    p = build_panel(rv, make_flow_features(flow), "rv_gk", 1, "SYN")
    assert_no_lookahead(p)
    c = evaluate_cell(p, "HAR+ctrl", "H1_absflow", family="unit")
    assert c["qlike_improvement_pct"] > 0
    assert c["primary_inference_gw_qlike"]["z_stat"] < -1.645


def test_placebo_scrambled_flow_is_not_detected(world):
    """Destroy the flow/RV correspondence and the gate must go quiet."""
    rv, flow = world
    rng = np.random.default_rng(99)
    scrambled = flow.copy()
    scrambled["flow"] = rng.permutation(scrambled["flow"].to_numpy())
    p = build_panel(rv, make_flow_features(scrambled), "rv_gk", 1, "SYN")
    c = evaluate_cell(p, "HAR+ctrl", "H1_absflow", family="unit")
    assert c["primary_inference_gw_qlike"]["z_stat"] > -1.645


def test_power_is_not_reported_as_an_exclusion():
    """v1's logic error, pinned so it cannot come back: power says how often the
    gate fires against an effect of a given size. It does NOT bound the effect."""
    rv, flow = _make_world(n_days=700)
    pw = power_simulation(
        rv, make_flow_features(flow), "SYN", horizon=1, reps=20, betas=(0.0, 0.5)
    )
    assert "POWER IS NOT AN EXCLUSION" in pw["scope_warning"]


# ---------------------------------------------------------------------------
# 7. C6 — Holm on raw p; the family is derived, not hand-listed
# ---------------------------------------------------------------------------
def test_holm_step_down_is_correct():
    adj = holm([0.01, 0.02, 0.03])
    assert adj[0] == pytest.approx(0.03)      # 3 * 0.01
    assert adj == sorted(adj)                 # step-down enforces monotonicity
    assert all(0.0 <= a <= 1.0 for a in adj)


def test_holm_on_raw_p_can_differ_from_holm_on_rounded_p():
    """v1 fed 4-decimal rounded p into Holm. At the 5% boundary that flips a
    verdict, so the raw values must survive all the way to serialization."""
    raw = [0.0166667, 0.4, 0.9]
    rounded = [round(p, 4) for p in raw]
    assert holm(raw)[0] != holm(rounded)[0]


def test_colliding_cell_keys_fail_loudly(panel):
    """A real bug, pinned. The cell key joins the registry, the loss cache and the
    verdict. When it was just `{asset}_h{h}_{alt}`, the primary BTC h=1 cell shared
    a key with its rv-proxy, flow-lag, threshold and window variants -- so the dict
    carrying exclusion statistics into the verdict kept whichever was written LAST,
    and the primary family was silently adjudicated with a robustness cell's
    numbers. A collision must now crash, not pick a winner.
    """
    evaluate_cell(panel, "HAR+ctrl", "H1_absflow", family="primary")
    with pytest.raises(AssertionError, match="duplicate cell key"):
        evaluate_cell(panel, "HAR+ctrl", "H1_absflow", family="primary")


def test_cell_keys_separate_families_and_variants(panel):
    """The same comparison run under different families/variants must get distinct
    keys -- otherwise the collision guard above would just make the study crash."""
    evaluate_cell(panel, "HAR+ctrl", "H1_absflow", family="primary")
    evaluate_cell(panel, "HAR+ctrl", "H1_absflow", family="threshold",
                  variant="thr1.0")
    evaluate_cell(panel, "HAR+ctrl", "H1_absflow", family="threshold",
                  variant="thr2.0")
    evaluate_cell(panel, "HAR+ctrl", "H1_absflow", family="eth_window",
                  train_window=200)

    gw = [r for r in REGISTRY if r.inference == "giacomini_white_qlike_fixed_window"]
    assert len({r.cell for r in gw}) == len(gw) == 4


def test_union_and_intersection_claims_get_opposite_multiplicity_treatment():
    """The two families need OPPOSITE corrections, and the reason is logical, not
    stylistic. Pinned because "be consistent, Holm everything" is the tempting
    wrong move.

    - "flow helps SOMEWHERE" is a UNION of alternatives: ten shots at finding an
      effect, so the family-wise error rate must be controlled -> Holm.
    - "flow helps NOWHERE by >= m" is an INTERSECTION: it may be asserted only if
      EVERY cell rejects, which is an intersection-union test (Berger 1982) and
      holds at level alpha with each cell UNADJUSTED. Holm there would inflate
      type-II error and buy no type-I protection.

    Concretely: a set of p-values that a conjunction claim should accept must be
    accepted unadjusted, while the same p-values under a union claim must not all
    survive Holm.
    """
    p = [0.01, 0.02, 0.03, 0.04]

    # conjunction (exclusion): every cell rejects at an unadjusted 5%
    assert all(x < 0.05 for x in p)

    # union (GW): Holm must NOT wave all four through
    assert not all(x < 0.05 for x in holm(p))


def test_registry_captures_every_test_including_the_smearing_runs(panel):
    """v1 hand-listed "EVERY DM test" and missed the 8 smearing ones. The family
    must be DERIVED, so a new robustness run cannot be forgotten."""
    evaluate_cell(panel, "HAR+ctrl", "H1_absflow", family="primary")
    evaluate_cell(panel, "HAR+ctrl", "H1_absflow", family="smearing_none",
                  smearing="none")
    evaluate_cell(panel, "HAR+ctrl", "H1_absflow", family="smearing_shared",
                  smearing="shared")

    gw = [r for r in REGISTRY if r.inference == "giacomini_white_qlike_fixed_window"]
    assert len(gw) == 3
    assert {r.family for r in gw} == {"primary", "smearing_none", "smearing_shared"}
    assert [r.feeds_gate for r in gw] == [True, False, False]


# ---------------------------------------------------------------------------
# 8. Estimator integrity
# ---------------------------------------------------------------------------
def test_normal_equations_match_lstsq(panel):
    """The OOS loop solves the normal equations for speed (the power simulation
    runs it ~16k times). It must be numerically identical to the SVD solution, or
    the simulation and the headline would be using different estimators."""
    d = panel.df.dropna(subset=SPECS["H1_absflow"])
    X = np.column_stack([np.ones(len(d)), d[SPECS["H1_absflow"]].to_numpy(float)])
    y = np.log(d["y"].to_numpy(float))
    for start in (0, 100, 200):
        xtr = X[start : start + GW_TRAIN_WINDOW]
        ytr = y[start : start + GW_TRAIN_WINDOW]
        np.testing.assert_allclose(
            np.linalg.solve(xtr.T @ xtr, xtr.T @ ytr),
            np.linalg.lstsq(xtr, ytr, rcond=None)[0],
            rtol=1e-7,
            atol=1e-9,
        )


def test_ols_helper_agrees_with_the_oos_loop(panel):
    d = panel.df.dropna(subset=SPECS["HAR+ctrl"])
    X = d[SPECS["HAR+ctrl"]].to_numpy(float)
    y = np.log(d["y"].to_numpy(float))
    Xc = np.column_stack([np.ones(len(X)), X])
    np.testing.assert_allclose(
        _ols(X, y), np.linalg.solve(Xc.T @ Xc, Xc.T @ y), rtol=1e-7, atol=1e-9
    )


def test_smearing_modes_produce_different_forecasts(panel):
    """If none/own/shared all returned the same numbers, the smearing robustness
    family would be theatre."""
    own = paired_oos(panel, "HAR+ctrl", "H1_absflow", smearing="own")
    none = paired_oos(panel, "HAR+ctrl", "H1_absflow", smearing="none")
    shared = paired_oos(panel, "HAR+ctrl", "H1_absflow", smearing="shared")

    assert not np.allclose(own.pred_aug, none.pred_aug)
    assert not np.allclose(own.pred_aug, shared.pred_aug)
    # 'shared' only overrides the AUGMENTED spec's multiplier
    np.testing.assert_allclose(own.pred_base, shared.pred_base, rtol=1e-12)


def test_forecasts_are_positive_variances(panel):
    po = paired_oos(panel, "HAR+ctrl", "H1_absflow")
    assert (po.pred_base > 0).all()
    assert (po.pred_aug > 0).all()
    assert (po.actual > 0).all()


# ---------------------------------------------------------------------------
# 9. End-to-end: the results file and the README must be reachable
# ---------------------------------------------------------------------------
def test_every_results_key_the_renderer_reads_is_produced(panel):
    """The rev1 review caught the experiment shipping in a state where the figure
    code still read `size_at_beta_0` after the field had been renamed -- so `main()`
    would have crashed before writing anything, and the renderer would have
    KeyError'd on the stale file. Unit-testing the pieces never sees that.

    This walks the renderer's key list against a freshly-built cell + power block,
    so a rename cannot pass CI again while leaving a reader-facing consumer broken.
    """
    c = evaluate_cell(panel, "HAR+ctrl", "H1_absflow", family="primary")

    for key in (
        "cell", "asset", "horizon", "alt", "n_oos", "qlike_base", "qlike_alt",
        "qlike_improvement_pct", "primary_inference_gw_qlike",
        "material_gain_exclusion", "raw_dm_diagnostic",
        "expanding_window_diagnostic_v1_design",
        "clark_west_mspe_separate_estimand", "family", "oos_audit",
    ):
        assert key in c, key

    for key in ("z_stat", "p_value_one_sided_flow_better", "loss", "hac_lag_used"):
        assert key in c["primary_inference_gw_qlike"], key

    for key in (
        "z_stat", "p_value_one_sided", "margin_relative_qlike",
        "qlike_gain_upper_bound_95pct",
    ):
        assert key in c["material_gain_exclusion"], key

    rv, flow = _make_world(n_days=700)
    pw = power_simulation(
        rv, make_flow_features(flow), "SYN", horizon=1, reps=20, betas=(0.0, 0.5)
    )
    for key in (
        "false_positive_rate_at_beta_0", "false_positive_note", "curve",
        "power_80pct_bracket", "power_90pct_bracket", "max_uplift_tested_pct",
        "scope_warning", "reps_per_beta", "scope",
    ):
        assert key in pw, key
    for key in ("rv_uplift_per_1sd_shock_pct", "power_gw_one_sided_5pct", "power_gw_se"):
        assert key in pw["curve"][0], key


def test_power_bracket_reports_an_interval_not_a_solved_threshold():
    """The grid is coarse, so the 80%-power effect can only be BRACKETED.

    The rev1 re-review's R2: the previous revision published both a bracket and a
    point (`rv_uplift_at_80pct_power_pct`), and the README then quoted the point.
    A number that exists in the JSON will be quoted, so the point fields are gone,
    and this test is the ratchet that keeps them gone.
    """
    rv, flow = _make_world(n_days=800, flow_beta=0.0)
    pw = power_simulation(
        rv, make_flow_features(flow), "SYN", horizon=1, reps=40,
        betas=(0.0, 0.30, 0.90),
    )
    assert "COARSE" in pw["grid_note"] or "coarse" in pw["grid_note"]

    for banned in (
        "beta_at_80pct_power", "rv_uplift_at_80pct_power_pct",
        "beta_at_90pct_power", "rv_uplift_at_90pct_power_pct",
    ):
        assert banned not in pw, (
            f"{banned!r} is a POINT estimate of a crossing that only a bracket can "
            "locate. It was removed after the rev1 re-review; it must not come back."
        )

    br = pw["power_80pct_bracket"]
    assert br is not None                       # always an object, never None
    assert "reached_on_grid" in br
    if br["reached_on_grid"]:
        assert br["upper_grid_power"] >= 0.80
        assert "bracket" in br["note"]
        if br["lower_rv_uplift_pct"] is not None:
            assert br["lower_grid_power"] < 0.80          # the target IS bracketed
            assert br["lower_rv_uplift_pct"] < br["upper_rv_uplift_pct"]
    else:
        assert br["upper_rv_uplift_pct"] is None
        assert "not reached" in br["note"]


def test_power_scope_admits_it_is_not_the_studys_power():
    """R1: the curve is ONE cell, at h=1, against ONE alternative, at the nominal
    gate. The verdict runs a 10-cell Holm family, which is strictly weaker. The
    previous revision reported the curve without saying so, which invites a reader
    to treat it as the design's family-wise power."""
    rv, flow = _make_world(n_days=700)
    pw = power_simulation(
        rv, make_flow_features(flow), "SYN", horizon=1, reps=20, betas=(0.0, 0.5)
    )
    sc = pw["scope"]
    assert sc["horizon_simulated"] == 1
    assert 5 in sc["primary_family_horizons"]
    assert 5 in sc["horizons_not_simulated"]
    assert sc["alternatives_not_simulated"]                    # H2/H4 are not covered
    assert "Holm" in sc["multiplicity_in_the_actual_verdict"]
    assert "none" in sc["multiplicity_in_the_simulated_gate"]
    assert "NOT the ten-cell" in pw["gate"] or "not the ten-cell" in pw["gate"].lower()


def test_beta0_row_is_a_false_positive_check_not_a_size_calibration():
    """R3: 'size-calibrated' is the wrong word and it was in the module docstring.

    Under GW's method-level null with a fixed window, an irrelevant regressor makes
    the augmented METHOD genuinely worse, so the one-sided flow-favouring test is
    conservative at beta=0 BY CONSTRUCTION. A rate below 5% is correct behaviour,
    not a calibrated size — so the file must not advertise size calibration.
    """
    src = (Path(__file__).parent / "k1709.py").read_text(encoding="utf-8")
    doc = ast.get_docstring(ast.parse(src)) or ""
    assert "size-calibrated" not in doc.lower()
    assert "FALSE-POSITIVE DIAGNOSTIC" in doc

    rv, flow = _make_world(n_days=700)
    pw = power_simulation(
        rv, make_flow_features(flow), "SYN", horizon=1, reps=20, betas=(0.0, 0.5)
    )
    assert "NOT 'size' in" in pw["false_positive_note"]


def test_fixed_window_raw_dm_is_not_labelled_biased():
    """R4: the two raw-DM records are diagnostic for DIFFERENT reasons.

    The expanding-window statistic is diagnostic because it is INVALID. The
    fixed-window one is diagnostic because the verdict was pre-registered on the GW
    object — it runs on the same GW-legal loss stream and agrees with the gate
    statistic to ~3 decimals. Tagging the fixed-window statistic 'biased toward the
    smaller model' imports the expanding-window pathology into the very design that
    was changed to avoid it, and directly contradicts the file's own coincidence
    note.
    """
    rng = np.random.default_rng(7)
    la = np.abs(rng.normal(1.0, 0.2, 300))
    lb = np.abs(rng.normal(1.0, 0.2, 300))

    fixed = raw_dm_diagnostic(la, lb, h=1, scheme="fixed")
    expanding = raw_dm_diagnostic(la, lb, h=1, scheme="expanding")

    assert fixed["t_stat"] == pytest.approx(expanding["t_stat"])   # same arithmetic
    assert fixed["feeds_gate"] is False and expanding["feeds_gate"] is False

    # the discriminating substring: the fixed-window role may only ever say it is
    # NOT biased; only the expanding one may assert the bias.
    assert "is NOT biased toward the smaller model" in fixed["role"]
    assert "is biased toward the smaller model" not in fixed["role"]
    assert fixed["valid_for_this_nested_comparison"] is True
    assert "not by invalidity" in fixed["role"].lower()

    assert "is biased toward the smaller model" in expanding["role"]
    assert expanding["valid_for_this_nested_comparison"] is False

    with pytest.raises(ValueError):
        raw_dm_diagnostic(la, lb, h=1, scheme="whatever")


def test_unbounded_memory_cell_is_flagged_not_silently_pooled(panel):
    """R6: the AR(5)-unexpected regressor is built on an EXPANDING window, so that
    cell's forecasting METHOD is not bounded-memory — which is a condition GW puts
    on the whole method, not on the final regression. It must be labelled, not
    quietly counted among the bounded-memory tests (and not dropped either: removing
    a test once its result is known is selection)."""
    ok = evaluate_cell(panel, "HAR+ctrl", "H1_absflow", family="primary")
    bad = evaluate_cell(
        panel, "HAR+ctrl", "H1_absflow", family="flow_transform",
        variant="unexp", bounded_memory=False,
    )
    assert ok["bounded_memory"] is True
    assert bad["bounded_memory"] is False

    gw = [r for r in REGISTRY if r.inference == "giacomini_white_qlike_fixed_window"]
    assert {r.bounded_memory for r in gw} == {True, False}
    # every test of the offending cell inherits the flag, not just the GW one
    assert all(
        not r.bounded_memory for r in REGISTRY if r.cell == bad["cell"]
    )
    assert all(not r.feeds_gate for r in REGISTRY if r.cell == bad["cell"])


def test_primary_gate_fails_closed_when_upstream_memory_is_unbounded(panel):
    with pytest.raises(AssertionError, match="without fixed-memory provenance"):
        evaluate_cell(
            panel,
            "HAR+ctrl",
            "H1_absflow",
            family="primary",
            bounded_memory=False,
        )


# ---------------------------------------------------------------------------
# 10. rev4 frozen-claim-surface ratchets
# ---------------------------------------------------------------------------
def _frozen_results() -> dict:
    return json.loads((Path(__file__).parent / "k1709_results.json").read_text())


def test_frozen_non_string_surface_has_not_moved():
    """Freeze every typed leaf after the audited gate-scope correction."""
    surface = _non_string_leaf_surface(_frozen_results())
    rows = [
        [list(path), kind, encoded]
        for path, (kind, encoded) in sorted(surface.items(), key=lambda item: repr(item[0]))
    ]
    payload = json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode()
    assert len(rows) == 4383
    assert hashlib.sha256(payload).hexdigest() == (
        "476f2fcfc72f06cc6aca4be2210f30972979356a5fcb88ae22e4cb5aecebc61d"
    )


def test_frozen_gate_metadata_correction_is_exactly_scoped():
    r = _frozen_results()
    rows = r["multiple_testing"]["full_family_holm"]
    primary = [row for row in rows if row["family"] == "primary"]
    diagnostic = [row for row in rows if row["family"] != "primary"]
    assert len(primary) == 10
    assert all(row["feeds_gate"] is True for row in primary)
    assert all(
        row["claim_role"] == "primary_unconditional_detection_gate"
        for row in primary
    )
    assert len(diagnostic) == 44
    assert all(row["feeds_gate"] is False for row in diagnostic)
    invalid = [
        row
        for row in rows
        if row["bounded_memory"] is False
    ]
    assert len(invalid) == 2
    assert all(row["feeds_gate"] is False for row in invalid)
    assert all(
        row["claim_role"] == "invalid_for_nested_inference_diagnostic_only"
        for row in invalid
    )
    assert all(
        row["claim_role"] == "non_primary_diagnostic_only"
        for row in diagnostic
        if row["bounded_memory"] is True
    )
    assert r["multiple_testing"]["n_gate_eligible_gw_tests"] == 10
    assert r["multiple_testing"]["n_diagnostic_only_tests"] == 152
    assert (
        r["multiple_testing"]["bounded_memory_sensitivity"][
            "n_gw_tests_bounded_memory"
        ]
        == 10
    )


def test_frozen_verdict_words_are_exactly_rederived_from_frozen_counts():
    r = _frozen_results()
    old = r["verdict_basis"]
    rebuilt = build_verdict_basis(
        r["verdict"],
        n_cells=old["cells_in_primary_family"],
        n_pass=old["cells_passing_flow_gate"],
        n_excl=old["cells_excluding_material_gain"],
        n_excl_holm=old["cells_excluding_material_gain_holm_conservative"],
        margin_pct=old["material_gain_margin_pct"],
        family_bound=old["qlike_gain_upper_bound_family_simultaneous_pct"],
        per_cell_upper_bounds=old["qlike_gain_upper_bound_95pct_per_cell"],
    )
    assert rebuilt == old


def test_readme_is_an_exact_pure_render_of_the_frozen_json():
    r = _frozen_results()
    expected = build_readme(r)
    assert expected == (Path(__file__).parent / "README.md").read_text()


def test_final_claim_bullets_have_one_author_and_include_conditional_caveat():
    r = _frozen_results()
    vb = r["verdict_basis"]
    text = build_readme(r)
    summary = text.split("## What this study does and does not say", 1)[1]
    does_say, does_not = summary.split("**Does not say:**", 1)

    actual_say = [line for line in does_say.splitlines() if line.startswith("- ")]
    actual_not = [line for line in does_not.splitlines() if line.startswith("- ")]
    expected_say = [
        f"- {vb[key]}"
        for key in sorted(k for k in vb if k.startswith("does_say_"))
        if vb[key]
    ]
    expected_not = [
        f"- {vb[key]}"
        for key in sorted(k for k in vb if k.startswith("does_not_say_"))
        if vb[key]
    ]
    assert actual_say == expected_say
    assert actual_not == expected_not

    conditional = vb["does_not_say_3_conditional_effect"].lower()
    assert "conditional" in conditional
    assert "regime" in conditional
    assert "not excluded" in conditional

    renderer = (Path(__file__).parent / "render_readme.py").read_text()
    assert "No robust incremental predictive evidence was found" not in renderer
    assert "That the true effect is exactly zero" not in renderer


def test_every_inferential_figure_label_is_explicitly_unconditional():
    vb = _frozen_results()["verdict_basis"]
    labels = {
        key: value for key, value in vb.items() if key.startswith("figure_")
    }
    assert labels
    for key, value in labels.items():
        if "GW" in value or "Giacomini-White" in value:
            assert "uncond" in value.lower() or "sec. 3.4" in value.lower(), key

    src = (Path(__file__).parent / "k1709.py").read_text()
    for stale in (
        'f"GW z=',
        "Giacomini-White on QLIKE",
        "Giacomini-White z by shock threshold",
        "power of the GW gate",
    ):
        assert stale not in src


def test_main_has_no_unresolved_global_references():
    """Compile succeeds with unresolved globals; stdlib symtable catches them."""
    source = (Path(__file__).parent / "k1709.py").read_text()
    table = symtable.symtable(source, "k1709.py", "exec")
    module_defined = {
        symbol.get_name()
        for symbol in table.get_symbols()
        if symbol.is_assigned() or symbol.is_imported() or symbol.is_namespace()
    }
    main_scope = next(child for child in table.get_children() if child.get_name() == "main")
    unresolved = {
        symbol.get_name()
        for symbol in main_scope.get_symbols()
        if symbol.is_referenced()
        and symbol.is_global()
        and symbol.get_name() not in module_defined
        and not hasattr(builtins, symbol.get_name())
    }
    assert unresolved == set()
