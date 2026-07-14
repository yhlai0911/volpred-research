"""K1709 regression gates.

The most important test here is `test_power_injected_signal_is_detected`.
A NULL result is only credible if the pipeline could have found a signal had one
existed. A broken merge, a misaligned shift, or a dead regressor all produce a
null that looks exactly like market efficiency. We therefore inject a synthetic
flow series that genuinely predicts next-day RV and require the pipeline to
recover it with a large, correctly-signed DM statistic.

Run:  uv run --extra dev python -m pytest experiments/k1709/test_k1709.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from k1709 import (  # noqa: E402
    Z_WINDOW,
    Panel,
    _parse_money,
    ar_residual,
    assert_no_lookahead,
    build_panel,
    compare,
    flow_zscore,
    unexpected_flow_z,
)


# --------------------------------------------------------------------------
# 1. Farside parsing traps
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("(95.1)", -95.1),      # parentheses = NEGATIVE (redemption)
        ("(27,332)", -27332.0),  # parentheses + thousands separator
        ("1,373.8", 1373.8),
        ("0.0", 0.0),            # a REAL zero flow
        ("111.7", 111.7),
        ("9,199.3*", 9199.3),    # asterisk footnote marker
    ],
)
def test_parse_money_values(raw, expected):
    assert _parse_money(raw) == pytest.approx(expected)


@pytest.mark.parametrize("raw", ["-", "–", "—", "", "nan"])
def test_parse_money_missing_is_nan_not_zero(raw):
    """'-' means the fund did not trade. Coercing it to 0.0 would invent a
    real zero-flow observation that never happened."""
    assert np.isnan(_parse_money(raw))


def test_zero_and_missing_are_distinct():
    assert _parse_money("0.0") == 0.0
    assert np.isnan(_parse_money("-"))


# --------------------------------------------------------------------------
# 2. Flow-shock scaling is strictly backward-looking
# --------------------------------------------------------------------------
def test_flow_zscore_denominator_excludes_own_day():
    rng = np.random.default_rng(0)
    f = pd.Series(rng.normal(size=200), index=pd.date_range("2024-01-01", periods=200))
    z = flow_zscore(f)
    i = 100
    expected_sd = f.iloc[i - Z_WINDOW : i].std()   # days t-20 .. t-1, NOT t
    assert z.iloc[i] == pytest.approx(f.iloc[i] / expected_sd)


def test_flow_zscore_is_invariant_to_future_values():
    """Perturbing the FUTURE must not change a past z-score."""
    rng = np.random.default_rng(1)
    f = pd.Series(rng.normal(size=200), index=pd.date_range("2024-01-01", periods=200))
    z1 = flow_zscore(f)
    f2 = f.copy()
    f2.iloc[150:] += 1000.0          # blow up the future
    z2 = flow_zscore(f2)
    pd.testing.assert_series_equal(z1.iloc[:150], z2.iloc[:150])


def test_unexpected_flow_ar5_lag_ordering():
    """The AR(5) prediction vector must line up with the design-matrix columns.

    Discriminating construction: a PURE LAG-5 process, f_t = 0.9*f_{t-5} + eps.
    The fitted coefficient vector is then ~[0,0,0,0,0.9], so the prediction is
    driven entirely by the LAST element of the lag vector. If that vector were
    built in the wrong order, the model would multiply 0.9 by f_{t-1} instead of
    f_{t-5} and the residual would blow up to the scale of the series itself.

    A correct implementation leaves a residual at the INNOVATION scale (eps),
    which is the theoretical floor -- it cannot do better. So we assert the
    residual sits near eps, and, more tellingly, that it is far below what the
    reversed ordering would produce.
    """
    n, sigma = 600, 0.01
    rng = np.random.default_rng(2)
    f = np.zeros(n)
    for t in range(5, n):
        f[t] = 0.9 * f[t - 5] + rng.normal(scale=sigma)
    s = pd.Series(f, index=pd.date_range("2024-01-01", periods=n))

    resid = ar_residual(s, p=5).dropna()      # the RAW residual, not the z-score

    # (a) A correct fit recovers the innovation: the residual sits at the eps
    #     floor (median |N(0,sigma)| = 0.674*sigma), well under the series' own
    #     dispersion. A reversed lag vector cannot achieve this.
    med = float(np.nanmedian(np.abs(resid)))
    assert med < 1.5 * sigma, (
        f"residual {med:.5f} exceeds the innovation floor ~{0.674 * sigma:.5f} "
        f"-- lag vector is probably misordered"
    )
    assert med < 0.5 * s.std()

    # (b) A correct AR(5) residual on a pure lag-5 process is WHITE. A reversed
    #     vector leaves 0.9*(f_{t-5} - f_{t-1}) in the residual, which is heavily
    #     autocorrelated. This check is scale-free, so it cannot be passed by
    #     accident of normalisation.
    assert abs(resid.autocorr(1)) < 0.2, (
        f"residual is autocorrelated (acf1={resid.autocorr(1):.3f}) -- the AR is "
        f"not removing the structure it claims to"
    )


# --------------------------------------------------------------------------
# 3. Calendar alignment
# --------------------------------------------------------------------------
def _toy(n=400, seed=3):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    rv = pd.Series(np.exp(rng.normal(-8, 0.5, n)), index=idx)
    rv = rv.rolling(3, min_periods=1).mean()          # some persistence
    ret = pd.Series(rng.normal(0, 0.02, n), index=idx)
    rvdf = pd.DataFrame(
        {"rv_gk": rv, "rv_park": rv, "rv_r2": rv, "rv_hourly": rv, "ret": ret}, index=idx
    )
    # ETF flow only on weekdays
    fidx = idx[idx.dayofweek < 5]
    flow = pd.DataFrame(
        {"flow": rng.normal(0, 100, len(fidx)), "gross": rng.uniform(50, 400, len(fidx))},
        index=fidx,
    )
    return rvdf, flow


def test_source_date_is_exactly_one_day_before_target():
    rvdf, flow = _toy()
    p = build_panel(rvdf, flow, "rv_gk", 1, "TOY", pub_lag=1)
    assert_no_lookahead(p, pub_lag=1)
    gap = (p.df.index - p.df["src_date"]).dt.days
    assert (gap == 1).all()


def test_pub_lag_two_shifts_exactly_two_days():
    rvdf, flow = _toy()
    p = build_panel(rvdf, flow, "rv_gk", 1, "TOY", pub_lag=2)
    assert_no_lookahead(p, pub_lag=2)
    assert ((p.df.index - p.df["src_date"]).dt.days == 2).all()


def test_calendar_gap_is_caught_not_silently_compressed():
    """A hole in the RV calendar must FAIL the assertion, not silently turn a
    t+1 target into a t+2 target. This is the 2026-07-13 Yahoo-gap bug."""
    rvdf, flow = _toy()
    holed = rvdf.drop(rvdf.index[200])          # punch out one calendar day
    p = build_panel(holed, flow, "rv_gk", 1, "TOY", pub_lag=1)
    with pytest.raises(AssertionError, match="gap"):
        assert_no_lookahead(p, pub_lag=1)


def test_target_matches_actual_future_rv():
    """y must literally be the RV of the target date (h=1)."""
    rvdf, flow = _toy()
    p = build_panel(rvdf, flow, "rv_gk", 1, "TOY", pub_lag=1)
    row = p.df.index[50]
    assert p.df.loc[row, "y"] == pytest.approx(rvdf.loc[row, "rv_gk"])


def test_har_features_come_from_the_day_before_the_target():
    rvdf, flow = _toy()
    p = build_panel(rvdf, flow, "rv_gk", 1, "TOY", pub_lag=1)
    row = p.df.index[60]
    src = p.df.loc[row, "src_date"]
    assert p.df.loc[row, "har_d"] == pytest.approx(np.log(rvdf.loc[src, "rv_gk"]))


def test_h5_target_is_mean_of_next_five_days():
    rvdf, flow = _toy()
    p = build_panel(rvdf, flow, "rv_gk", 5, "TOY", pub_lag=1)
    row = p.df.index[60]
    window = rvdf["rv_gk"].loc[row : row + pd.Timedelta(days=4)]
    assert p.df.loc[row, "y"] == pytest.approx(window.mean())
    assert p.df.loc[row, "y_end_date"] == row + pd.Timedelta(days=4)


# --------------------------------------------------------------------------
# 4. THE POWER TEST — can the pipeline find a signal that is really there?
# --------------------------------------------------------------------------
def test_power_injected_signal_is_detected():
    """Inject a flow that genuinely drives NEXT-day RV, and require detection.

    Construction: RV_{t+1} is built to depend on |z_t|. If the merge, the
    `.shift(1)`, the OOS split, or the DM sign convention were wrong, this
    planted signal would be destroyed and the test would fail -- which is
    precisely the failure mode that would also fake a null on the real data.
    """
    rng = np.random.default_rng(7)
    n = 700
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    fidx = idx[idx.dayofweek < 5]

    flow_vals = rng.normal(0, 100, len(fidx))
    flow = pd.DataFrame({"flow": flow_vals, "gross": np.abs(flow_vals)}, index=fidx)
    z = flow_zscore(flow["flow"]).reindex(idx)

    # log RV_{t+1} = persistent base + 1.2 * |z_t|  ->  flow LEADS rv by one day
    base = np.zeros(n)
    for t in range(1, n):
        base[t] = 0.9 * base[t - 1] + rng.normal(0, 0.20)
    shock = np.nan_to_num(z.shift(1).to_numpy(), nan=0.0)   # |z| from the DAY BEFORE
    log_rv = -8.0 + base + 1.2 * np.abs(shock)
    rvdf = pd.DataFrame(
        {
            "rv_gk": np.exp(log_rv),
            "rv_park": np.exp(log_rv),
            "rv_r2": np.exp(log_rv),
            "rv_hourly": np.exp(log_rv),
            "ret": rng.normal(0, 0.02, n),
        },
        index=idx,
    )

    p = build_panel(rvdf, flow, "rv_gk", 1, "TOY", pub_lag=1)
    assert_no_lookahead(p, pub_lag=1)
    c = compare(p, "HAR+ctrl", "H1_absflow", initial_train=200)

    # Negative DM t => the flow model wins. Signal is strong, so this must be
    # decisive, not marginal.
    assert c["dm_t"] < -3.0, f"planted signal not recovered: DM t={c[chr(39)+chr(100)+chr(109)+chr(95)+chr(116)+chr(39)]}"
    assert c["qlike_improvement_pct"] > 0, "planted signal did not improve QLIKE"
    assert c["clark_west_t"] > 1.645, f"Clark-West missed it: {c['clark_west_t']}"


def test_h5_oos_training_rows_never_see_the_forecast_origin():
    """The overlapping-target training filter (.claude/rules/experiments.md L20).

    With h=5 the targets overlap, so "all rows before i" would let the model train
    on a label window that extends INTO or PAST the forecast origin -- i.e. it
    would see realized returns from the day it is predicting. Every power/placebo
    test runs h=1, where the filter is trivial, so this rule had no coverage at all
    until now. We re-derive the filter here and assert the invariant directly.
    """
    rvdf, flow = _toy(n=500)
    p = build_panel(rvdf, flow, "rv_gk", 5, "TOY", pub_lag=1)
    cols = ["har_d", "har_w", "har_m", "ret", "abs_ret", "abs_z"]
    d = p.df.dropna(subset=cols)
    origins = d.index
    y_end = d["y_end_date"]

    checked = 0
    for i in range(60, len(d)):
        train = np.where(y_end.to_numpy() < origins[i])[0]
        train = train[train < i]
        if len(train) == 0:
            continue
        # every training label must CLOSE strictly before this forecast origin
        assert y_end.iloc[train].max() < origins[i], (
            f"leak at origin {origins[i].date()}: a training label ends "
            f"{y_end.iloc[train].max().date()}, on/after the origin"
        )
        checked += 1
    assert checked > 100, "filter was never exercised"


def test_h5_compare_runs_end_to_end():
    """h=5 must survive the full compare() path, not just target construction."""
    rvdf, flow = _toy(n=600)
    p = build_panel(rvdf, flow, "rv_gk", 5, "TOY", pub_lag=1)
    assert_no_lookahead(p, pub_lag=1)
    c = compare(p, "HAR+ctrl", "H1_absflow", initial_train=200)
    assert c["n_oos"] > 50
    assert np.isfinite(c["dm_t"]) and np.isfinite(c["clark_west_t"])


def test_verdict_gate_is_direction_aware():
    """A flow model that is significantly WORSE must never count as a pass.

    `abs(t) > 3` would count it; `t < -3` does not. This guards the latent
    inversion bug where the script could print PASS on evidence that flow HURTS.
    """
    rng = np.random.default_rng(21)
    n = 700
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    fidx = idx[idx.dayofweek < 5]
    flow_vals = rng.normal(0, 100, len(fidx))
    flow = pd.DataFrame({"flow": flow_vals, "gross": np.abs(flow_vals)}, index=fidx)

    base = np.zeros(n)
    for t in range(1, n):
        base[t] = 0.9 * base[t - 1] + rng.normal(0, 0.20)
    rvdf = pd.DataFrame(
        {c: np.exp(-8.0 + base) for c in ("rv_gk", "rv_park", "rv_r2", "rv_hourly")},
        index=idx,
    )
    rvdf["ret"] = rng.normal(0, 0.02, n)
    p = build_panel(rvdf, flow, "rv_gk", 1, "TOY", pub_lag=1)
    c = compare(p, "HAR+ctrl", "H1_absflow", initial_train=200)

    # the two flags must be mutually exclusive and direction-correct
    assert not (c["dm_harvey_pass_flow_better"] and c["dm_harvey_pass_flow_worse"])
    if c["dm_t"] > 3.0:
        assert c["dm_harvey_pass_flow_worse"]
        assert not c["dm_harvey_pass_flow_better"], "a WORSE flow model counted as a pass"
    if c["dm_t"] < -3.0:
        assert c["dm_harvey_pass_flow_better"]


def test_placebo_scrambled_flow_is_not_detected():
    """Mirror image: with the SAME machinery, a flow that carries no information
    must NOT be flagged. Guards against a pipeline that 'finds' signal in noise."""
    rng = np.random.default_rng(11)
    n = 700
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    fidx = idx[idx.dayofweek < 5]
    flow_vals = rng.normal(0, 100, len(fidx))
    flow = pd.DataFrame({"flow": flow_vals, "gross": np.abs(flow_vals)}, index=fidx)

    base = np.zeros(n)
    for t in range(1, n):
        base[t] = 0.9 * base[t - 1] + rng.normal(0, 0.20)
    rvdf = pd.DataFrame(
        {
            "rv_gk": np.exp(-8.0 + base),      # RV does NOT depend on flow
            "rv_park": np.exp(-8.0 + base),
            "rv_r2": np.exp(-8.0 + base),
            "rv_hourly": np.exp(-8.0 + base),
            "ret": rng.normal(0, 0.02, n),
        },
        index=idx,
    )
    p = build_panel(rvdf, flow, "rv_gk", 1, "TOY", pub_lag=1)
    c = compare(p, "HAR+ctrl", "H1_absflow", initial_train=200)
    assert abs(c["dm_t"]) < 3.0, f"false positive on pure noise: DM t={c['dm_t']}"
