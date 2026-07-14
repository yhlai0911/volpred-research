"""K1711 regression tests — the invariants that would fail *silently* if broken.

Run:  uv run --extra dev python -m pytest experiments/k1711/test_k1711.py -q

Every test here exists because the corresponding mistake has actually shipped in
this repo before (see docs/error_log.md §G): a forecast that peeks one day into
the future still produces a beautiful, plausible, entirely wrong results table.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import k1711  # noqa: E402
import k1711_tsfm  # noqa: E402


# ── targets ───────────────────────────────────────────────────────────────────

def test_target_is_strictly_forward_looking():
    """y_h[t] must average days t+1..t+h — never day t itself."""
    rv = np.arange(1.0, 11.0)
    y1 = k1711.build_targets(rv, rv, h=1, floor=0.0)
    assert y1[0] == 2.0 and y1[3] == 5.0          # y[t] == rv[t+1]
    assert np.isnan(y1[-1])                        # last day has no future

    y3 = k1711.build_targets(rv, rv, h=3, floor=0.0)
    assert y3[0] == pytest.approx((2 + 3 + 4) / 3)
    assert np.all(np.isnan(y3[-3:]))               # last h days unavailable


def test_target_floor_applied_to_proxy_only():
    rv = np.array([1.0, 2.0, 3.0, 4.0])
    proxy = np.array([0.0, 0.0, 3.0, 4.0])
    y = k1711.build_targets(rv, proxy, h=1, floor=0.5)
    assert y[0] == 0.5                             # zero proxy raised to the floor
    assert y[1] == 3.0


# ── HAR features ──────────────────────────────────────────────────────────────

def test_har_features_use_only_past_and_present():
    """Perturbing rv[t+1] must not move any feature at origin t."""
    rng = np.random.default_rng(0)
    rv = np.exp(rng.normal(-9, 0.5, 200))
    ret = rng.normal(0, 0.01, 200)
    X = k1711.har_features(rv, ret)

    t = 100
    rv2, ret2 = rv.copy(), ret.copy()
    rv2[t + 1:] *= 7.0                             # blow up the entire future
    ret2[t + 1:] = -0.2
    X2 = k1711.har_features(rv2, ret2)

    assert np.allclose(X[t], X2[t], equal_nan=True)
    assert np.all(np.isnan(X[:21, 1]))             # monthly lag needs 22 days


def test_leverage_term_is_negative_part_of_same_day_return():
    rv = np.exp(np.full(30, -9.0))
    ret = np.array([-0.02, 0.03] * 15)
    X = k1711.har_features(rv, ret)
    assert X[22, 4] == pytest.approx(-0.02)        # down day keeps its magnitude
    assert X[23, 4] == 0.0                         # up day contributes nothing


# ── the load-bearing one: HAR forecasts cannot see the future ─────────────────

@pytest.mark.parametrize("h", [1, 5])
def test_expanding_ols_forecast_is_immune_to_future_data(h):
    """A forecast made at origin t must be identical if every day after t changes.

    This is the whole ballgame. If the expanding OLS trains on rows whose label window
    reaches past t, this fails — and no amount of plausible-looking QLIKE would reveal it.
    Covers HAR, HAR-A, AR1, MZ and COMB-GR, which all route through this one function.
    """
    rng = np.random.default_rng(1)
    n, t = 900, 800
    rv = np.exp(rng.normal(-9, 0.5, n))
    ret = rng.normal(0, 0.01, n)

    origins = np.arange(21, n)
    X = k1711.har_features(rv, ret)
    logy = np.log(k1711.build_targets(rv, rv, h=h))
    g = k1711._expanding_ols_forecast(X, logy, h, origins, k1711.MIN_TRAIN_HAR)

    rv_alt, ret_alt = rv.copy(), ret.copy()
    rv_alt[t + 1:] = np.exp(rng.normal(-6, 1.0, n - t - 1))    # a totally different future
    ret_alt[t + 1:] = rng.normal(0, 0.05, n - t - 1)
    X_alt = k1711.har_features(rv_alt, ret_alt)
    logy_alt = np.log(k1711.build_targets(rv_alt, rv_alt, h=h))
    g_alt = k1711._expanding_ols_forecast(X_alt, logy_alt, h, origins, k1711.MIN_TRAIN_HAR)

    assert np.isfinite(g[t])
    assert g[t] == pytest.approx(g_alt[t], rel=1e-12)


@pytest.mark.parametrize("h", [1, 5])
def test_forward_label_rule_excludes_overlapping_training_rows(h):
    """Training row j is admissible only if j + h < t (label window closed before origin).

    The poison starts at row t-h — the *first* row whose label window touches day t. An
    off-by-one that admitted j = t-h would fail here; poisoning from t onwards (an easier
    test) would not, which is why the boundary is where the poison starts.
    """
    n, t = 800, 700
    rv = np.full(n, np.exp(-9.0))
    logy = np.log(k1711.build_targets(rv, rv, h=h))
    origins = np.arange(21, n)
    X = k1711.har_features(rv, np.zeros(n))

    logy_poison = logy.copy()
    logy_poison[t - h:] = 2.0                      # rows whose windows reach day t or later

    g_clean = k1711._expanding_ols_forecast(X, logy, h, origins, k1711.MIN_TRAIN_HAR)
    g_poison = k1711._expanding_ols_forecast(X, logy_poison, h, origins, k1711.MIN_TRAIN_HAR)

    assert np.isfinite(g_clean[t])
    assert g_clean[t] == pytest.approx(g_poison[t], rel=1e-12)


def test_combine_gr_is_immune_to_future_data():
    """COMB-GR estimates its weights, so it gets its own leakage test, not HAR's."""
    rng = np.random.default_rng(3)
    n, t, h = 900, 800, 1
    rv = np.exp(rng.normal(-9, 0.5, n))
    origins = np.arange(21, n)
    logy = np.log(k1711.build_targets(rv, rv, h=h))

    comps = {"HAR": np.log(rv) * 0.8, "A": np.log(rv) * 0.5 - 1, "B": np.log(rv) * 0.3}
    gr = k1711.combine_gr(comps, logy, h, origins)

    logy_alt = logy.copy()
    logy_alt[t - h:] = 3.0                         # corrupt every outcome from the boundary on
    gr_alt = k1711.combine_gr(comps, logy_alt, h, origins)

    assert np.isfinite(gr[t])
    assert gr[t] == pytest.approx(gr_alt[t], rel=1e-12)


# ── TSFM alignment ────────────────────────────────────────────────────────────

def test_tsfm_contexts_end_at_the_origin_and_are_keyed_by_target():
    idx = pd.bdate_range("2010-01-01", periods=600)
    log_rv = pd.Series(np.arange(600.0), index=idx)

    k1711_tsfm.CONTEXT = 512
    k1711_tsfm.TSFM_START = "2010-01-01"
    contexts, targets, origins = k1711_tsfm._build_contexts(log_rv)

    # first origin is index 511; it predicts index 512
    assert contexts[0][-1] == 511.0
    assert targets[0] == idx[512]
    assert origins[0] == idx[511]
    # the context must never contain the value it is predicting
    for c, tgt, org in zip(contexts[:20], targets[:20], origins[:20]):
        pos = idx.get_loc(tgt)
        assert c[-1] == float(pos - 1)
        assert org == idx[pos - 1]
        assert float(pos) not in set(c)


def _steps_frame(idx, positions, values):
    df = pd.DataFrame(values, columns=[f"step{k}" for k in range(1, values.shape[1] + 1)],
                      index=idx[positions])
    df.insert(0, "origin_date", idx[[p - 1 for p in positions]].astype(str))
    return df


def test_tsfm_log_forecast_maps_target_dates_back_to_origins():
    idx = pd.bdate_range("2020-01-01", periods=10)
    steps = _steps_frame(idx, [5, 6, 7], np.log(np.full((3, 5), 1e-4)))
    g = k1711.tsfm_log_forecast(steps, idx, h=1, n=10)

    # a forecast for target date idx[5] belongs to origin 4
    assert np.isfinite(g[4]) and np.isfinite(g[5]) and np.isfinite(g[6])
    assert np.isnan(g[7])
    assert g[4] == pytest.approx(np.log(1e-4))


def test_tsfm_log_forecast_rejects_a_stale_csv():
    """A panel rebuild that shifts a trading day must raise, not silently re-pair."""
    idx = pd.bdate_range("2020-01-01", periods=10)
    steps = _steps_frame(idx, [5, 6], np.log(np.full((2, 5), 1e-4)))
    steps["origin_date"] = str(idx[0].date())      # corrupt the recorded origin

    with pytest.raises(ValueError, match="stale forecast CSV"):
        k1711.tsfm_log_forecast(steps, idx, h=1, n=10)


def test_tsfm_log_forecast_h5_is_log_of_mean_variance():
    """h=5 must aggregate in *variance* space, not log space (Jensen)."""
    idx = pd.bdate_range("2020-01-01", periods=10)
    logs = np.log(np.array([[1e-4, 2e-4, 3e-4, 4e-4, 5e-4]]))
    steps = _steps_frame(idx, [5], logs)

    g = k1711.tsfm_log_forecast(steps, idx, h=5, n=10)
    assert g[4] == pytest.approx(np.log(np.mean([1e-4, 2e-4, 3e-4, 4e-4, 5e-4])))
    assert g[4] > np.mean(logs)                    # log-of-mean > mean-of-log


# ── DM / HLN ──────────────────────────────────────────────────────────────────

def test_hln_factor_shrinks_t_and_is_near_identity_at_h1():
    n = 2500
    t_dm = 4.0
    t1, _ = k1711.hln_correct(t_dm, n, h=1)
    assert abs(t1) < abs(t_dm)                     # correction is a shrinkage
    assert t1 == pytest.approx(t_dm, rel=1e-3)     # negligible at h=1, as theory says

    t5, _ = k1711.hln_correct(t_dm, n, h=5)
    assert abs(t5) < abs(t1)                       # bites harder at longer horizons


def test_dm_uses_canonical_implementation():
    """Guard against someone re-writing a local DM with lag = h-1 (K1655)."""
    from volpred.stats import model_evaluation
    assert k1711.dm_test is model_evaluation.dm_test
    assert k1711.clark_west_test is model_evaluation.clark_west_test


def test_holm_is_monotone_and_conservative():
    raw = {"a": 0.001, "b": 0.02, "c": 0.30}
    adj = k1711.holm(raw)
    assert adj["a"] == pytest.approx(0.003)        # 3 * 0.001
    assert adj["b"] == pytest.approx(0.04)         # 2 * 0.02
    assert adj["c"] == pytest.approx(0.30)         # 1 * 0.30
    assert adj["a"] <= adj["b"] <= adj["c"]        # step-down monotonicity
    assert all(adj[k] >= raw[k] for k in raw)      # never anti-conservative


def test_models_that_nest_har_are_routed_away_from_dm():
    """The K1701 trap: a model whose weights collapse onto HAR under the null cannot be
    judged by a raw DM t-stat. Those models must be declared, not discovered later."""
    assert set(k1711.NESTED_WITH_HAR) == {"AR1", "HAR-A", "COMB-GR"}
    for m, (small, large) in k1711.NESTED_WITH_HAR.items():
        assert small in k1711.FULL_POOL and large in k1711.FULL_POOL
        assert m in (small, large)
    # fixed-weight combinations are NOT degenerate under the null, so DM stays valid
    assert "COMB-EW" not in k1711.NESTED_WITH_HAR
    assert {"COMB-EW", "COMB-MZ"} <= k1711.CONTAINS_HAR


# ── evaluate(): the end-to-end path that actually crashed ─────────────────────

def _synthetic_cell(n=1700):
    """A small but complete (panel, forecasts) pair, enough to drive evaluate()."""
    rng = np.random.default_rng(7)
    idx = pd.bdate_range("2012-01-02", periods=n)
    log_rv = np.full(n, -9.0)
    for t in range(1, n):
        log_rv[t] = -9.0 + 0.95 * (log_rv[t - 1] + 9.0) + rng.normal(0, 0.35)
    rv = np.exp(log_rv)
    ret = rng.normal(0, np.sqrt(rv))
    panel = pd.DataFrame({"rv": rv, "ret": ret, "r2": ret ** 2}, index=idx)
    panel.index.name = "date"

    steps = {}
    for m in k1711.TSFMS:
        pos = np.arange(520, n - 1)
        vals = np.column_stack([log_rv[pos] + rng.normal(0, 0.1, len(pos))
                                for _ in range(5)])
        df = pd.DataFrame(vals, columns=[f"step{k}" for k in range(1, 6)], index=idx[pos + 1])
        df.index.name = "target_date"
        df.insert(0, "origin_date", idx[pos].astype(str))
        steps[m] = df
    return panel, steps


def test_evaluate_runs_end_to_end_and_scores_every_model_on_the_same_days(monkeypatch):
    panel, steps = _synthetic_cell()
    monkeypatch.setitem(k1711.WINDOWS, "pseudo_oos", pd.Timestamp("2016-03-01"))
    monkeypatch.setattr(k1711, "N_BOOT", 200)           # keep the test fast

    F = k1711.build_forecasts(panel, h=1, tsfm_steps=steps)
    assert set(F) == set(k1711.FULL_POOL)

    out = k1711.evaluate("SYN", 1, "rv", "pseudo_oos", panel, F)

    assert out["n_scored"] >= 252
    assert set(out["mean_loss"]["qlike"]) == set(k1711.FULL_POOL)
    assert set(out["mcs"]["qlike"]["superior_set_by_alpha"]["0.1"]) <= set(k1711.FULL_POOL)
    assert set(out["mcs_base_pool"]["qlike"]["superior_set_by_alpha"]["0.1"]) <= set(k1711.BASE_POOL)
    # nested models must carry a Clark-West result on MSE and no Holm-corrected DM verdict
    assert out["vs_har"]["mse"]["COMB-GR"]["dm_inference"] == "diagnostic_only"
    assert out["vs_har"]["mse"]["COMB-GR"]["clark_west"] is not None
    assert "p_hln_holm" not in out["vs_har"]["mse"]["COMB-GR"]
    assert out["vs_har"]["qlike"]["TimesFM-MZ"]["dm_inference"] == "valid"
    assert "p_hln_holm" in out["vs_har"]["qlike"]["TimesFM-MZ"]


def test_evaluate_refuses_to_silently_drop_a_model_with_gaps(monkeypatch):
    """A hole inside the evaluation window must raise, not shrink the sample."""
    panel, steps = _synthetic_cell()
    monkeypatch.setitem(k1711.WINDOWS, "pseudo_oos", pd.Timestamp("2016-03-01"))

    F = k1711.build_forecasts(panel, h=1, tsfm_steps=steps)
    F["HAR"] = F["HAR"].copy()
    F["HAR"][-100] = np.nan                        # punch one hole mid-window

    with pytest.raises(RuntimeError, match="missing/non-positive forecasts"):
        k1711.evaluate("SYN", 1, "rv", "pseudo_oos", panel, F)
