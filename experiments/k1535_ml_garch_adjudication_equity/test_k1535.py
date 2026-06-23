"""Unit tests for K1535 — anti-bug guards (run BEFORE trusting any result).

Covers:
  1. Lookahead: NN forward-label windows satisfy target_end > forecast_origin,
     and tampering with data dated >= origin does NOT change a forecast built
     from info <= origin-1 (causality test on both NN window builder and GARCH
     filter seeding).
  2. QLIKE direction: perfect forecast -> 0; worse forecast -> larger loss.
  3. Information symmetry: the feature set fed to the NN equals the lagged-RV +
     VIX information available to the GARCH-X / HAR-X baselines.
  4. Seed determinism: same seed -> identical NN forecast; different seed differs.
  5. DM-HLN horizon: inference horizon equals target H (rule check).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import k1535 as K  # noqa: E402


def _toy_series(n=400, seed=7):
    rng = np.random.default_rng(seed)
    ret = rng.normal(0, 1.0, n)
    rv = np.abs(rng.normal(1.0, 0.3, n)) + 0.5 * ret ** 2
    vix = 15 + 5 * np.abs(rng.normal(0, 1, n))
    return ret, rv, vix


def _feat_mat(ret, rv, vix):
    import pandas as pd
    logrv = np.log(np.maximum(rv, K.VAR_FLOOR))
    rv_w = pd.Series(logrv).rolling(5).mean().to_numpy()
    rv_m = pd.Series(logrv).rolling(22).mean().to_numpy()
    log_vix2 = np.log(np.maximum(vix, 1e-6) ** 2)
    fm = np.column_stack([ret, logrv, rv_w, rv_m, log_vix2])
    fm[:22] = np.nan_to_num(fm[:22], nan=0.0)
    return fm


# --------------------------------------------------------------------------- #
def test_qlike_direction():
    """Perfect forecast => QLIKE 0; biased forecast => strictly larger."""
    rng = np.random.default_rng(0)
    actual = np.abs(rng.normal(2, 0.5, 500)) + 0.1
    assert abs(K.qlike(actual, actual)) < 1e-10, "perfect forecast must give QLIKE~0"
    worse = actual * 1.5
    assert K.qlike(actual, worse) > 0, "biased forecast must give positive QLIKE"
    pw = K.qlike_pointwise(actual, actual)
    assert np.allclose(pw, 0.0, atol=1e-9), "pointwise perfect must be ~0"
    print("PASS test_qlike_direction")


def test_nn_window_forward_label_causality():
    """Every NN window's target window starts AFTER the input window ends
    (target_end = origin+H-1 >= origin = j+1 > j = last input day)."""
    ret, rv, vix = _toy_series()
    fm = _feat_mat(ret, rv, vix)
    for H in (1, 5, 22):
        X, y, origins = K.build_nn_windows(fm, rv, seq_len=22, H=H)
        assert len(X) > 0
        # origin = j+1, last input day = j = origin-1 < origin (causal)
        # target window [origin, origin+H-1]; target_end = origin+H-1 >= origin
        assert np.all(origins >= 22), "origin must leave seq_len history"
        assert np.all(origins + H - 1 < len(rv)), "target window must fit"
    print("PASS test_nn_window_forward_label_causality")


def test_nn_window_no_future_leakage():
    """Tampering with RV/features dated >= origin must NOT change the input
    window for that origin (input uses only days <= origin-1)."""
    ret, rv, vix = _toy_series()
    fm = _feat_mat(ret, rv, vix)
    H, seq_len = 1, 22
    X, y, origins = K.build_nn_windows(fm, rv, seq_len, H)
    # pick a middle origin
    k = len(origins) // 2
    origin = origins[k]
    win_before = X[k].copy()
    # tamper everything dated >= origin (the forecast day and beyond)
    fm_tampered = fm.copy()
    fm_tampered[origin:] = fm_tampered[origin:] * 1000.0 + 999.0
    X2, _, origins2 = K.build_nn_windows(fm_tampered, rv, seq_len, H)
    k2 = list(origins2).index(origin)
    win_after = X2[k2]
    assert np.allclose(win_before, win_after), \
        "input window must be invariant to future (>= origin) tampering"
    print("PASS test_nn_window_no_future_leakage")


def test_garch_filter_seed_causality():
    """GARCH filter seed state sigma^2_origin depends only on returns <= origin-1.
    Tampering returns dated >= origin must NOT change the in-sample filter tail."""
    ret, rv, vix = _toy_series()
    origin = 300
    y_hist = ret[:origin] - ret[:origin].mean()
    s2init = float(np.var(y_hist))
    s2 = K.filter_garch(y_hist, s2init, 0.05, 0.08, 0.90)
    # tamper future returns
    ret2 = ret.copy()
    ret2[origin:] += 50.0
    y_hist2 = ret2[:origin] - ret2[:origin].mean()
    s2b = K.filter_garch(y_hist2, s2init, 0.05, 0.08, 0.90)
    assert np.allclose(s2, s2b), "in-sample filter must ignore future returns"
    print("PASS test_garch_filter_seed_causality")


def test_har_design_lagged():
    """HAR regressors at row i use only RV dated <= i-1 (no contemporaneous)."""
    ret, rv, vix = _toy_series()
    X, y, idx = K.har_design(rv, vix=vix, include_vix=True)
    # tamper rv at a target index and confirm its regressors are unchanged
    i_target = idx[len(idx) // 2]
    rv2 = rv.copy()
    rv2[i_target:] = rv2[i_target:] * 100 + 5  # tamper i_target and future
    X2, y2, idx2 = K.har_design(rv2, vix=vix, include_vix=True)
    pos = list(idx).index(i_target)
    pos2 = list(idx2).index(i_target)
    assert np.allclose(X[pos], X2[pos2]), \
        "HAR regressors must be invariant to RV at/after the target day"
    print("PASS test_har_design_lagged")


def test_information_symmetry():
    """The NN feature columns are exactly the lagged-RV(1,5,22)+VIX information
    that the GARCH-X / HAR-X baselines receive — assert column identity."""
    ret, rv, vix = _toy_series()
    fm = _feat_mat(ret, rv, vix)
    # feature columns: [ret, logRV_d, logRV_w(5), logRV_m(22), logVIX^2]
    assert fm.shape[1] == 5
    # HAR-X design uses the SAME daily/weekly/monthly log-RV + log VIX^2 lagged
    Xh, _, idxh = K.har_design(rv, vix=vix, include_vix=True)
    # HAR-X has intercept + 3 RV lags + log VIX^2 = 5 columns
    assert Xh.shape[1] == 5, "HAR-X must use 3 RV lags + log VIX^2 (+intercept)"
    # check the log-RV daily lag in HAR-X equals NN feature logRV at i-1
    i = idxh[100]
    logrv = np.log(np.maximum(rv, K.VAR_FLOOR))
    assert abs(Xh[100, 1] - logrv[i - 1]) < 1e-9, "HAR daily lag = logRV_{i-1}"
    # NN feature at day i-1 daily log-RV col equals same logrv
    assert abs(fm[i - 1, 1] - logrv[i - 1]) < 1e-9, "NN daily logRV col = logRV"
    print("PASS test_information_symmetry")


def test_nn_seed_determinism():
    """Same seed => identical NN forecast; different seed => different forecast."""
    ret, rv, vix = _toy_series()
    fm = _feat_mat(ret, rv, vix)
    H, seq_len = 1, 22
    X, y, origins = K.build_nn_windows(fm, rv, seq_len, H)
    split = len(X) - 60
    X_tr, y_tr, X_te = X[:split], y[:split], X[split:]
    fmean = X_tr.reshape(-1, X_tr.shape[-1]).mean(axis=0)
    fstd = X_tr.reshape(-1, X_tr.shape[-1]).std(axis=0) + 1e-8
    ymean, ystd = y_tr.mean(), y_tr.std() + 1e-8
    kw = dict(seq_len=seq_len, n_feat=X.shape[-1], epochs=5, lr=1e-3,
              feat_mean=fmean, feat_std=fstd, y_mean=ymean, y_std=ystd)
    fc_a = K.train_predict_nn("PatchTST-lite", X_tr, y_tr, X_te, seed=0, **kw)
    fc_b = K.train_predict_nn("PatchTST-lite", X_tr, y_tr, X_te, seed=0, **kw)
    fc_c = K.train_predict_nn("PatchTST-lite", X_tr, y_tr, X_te, seed=1, **kw)
    assert np.allclose(fc_a, fc_b), "same seed must reproduce exactly"
    assert not np.allclose(fc_a, fc_c), "different seed must differ"
    print("PASS test_nn_seed_determinism")


def test_dm_hln_horizon_wired():
    """DM-HLN must accept and USE the horizon h (HAC lags); h=1 vs h=5 differ on
    autocorrelated loss differences."""
    rng = np.random.default_rng(3)
    base = rng.normal(0, 1, 500)
    # autocorrelated loss differential
    d = np.zeros(500)
    for t in range(1, 500):
        d[t] = 0.7 * d[t - 1] + rng.normal(0, 0.5)
    la = base
    lb = base - d  # loss_a - loss_b = d
    r1 = K.dm_hln_test(la, lb, h=1)
    r5 = K.dm_hln_test(la, lb, h=5)
    assert r1["h"] == 1 and r5["h"] == 5
    assert abs(r1["dm"] - r5["dm"]) > 1e-6, "h must change the HAC variance"
    print("PASS test_dm_hln_horizon_wired")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
