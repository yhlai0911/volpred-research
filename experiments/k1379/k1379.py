#!/usr/bin/env python3
"""
K1379 — Paper 9 HAR-style daily-r² Benchmarks (C4 Partial Evidence)
===================================================================
Adds HAR-style regressions trained on daily squared returns, with and without
VIX, to the Paper 9 horse race.  These are not canonical intraday HAR-RV
models; the legacy internal keys are retained only for artifact continuity.

Addresses Review v3 C4 (HIGH): "horse race without HAR-RV is incomplete."

seed=42, no lookahead, VIX inputs lagged to t-1 where applicable
"""

import hashlib
import json
import os
import time
import warnings
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime, timezone
from scipy import optimize, stats
from numba import njit

from volpred.stats.model_evaluation import (
    dm_test as canonical_dm_test,
    qlike_pointwise,
)

warnings.filterwarnings('ignore')
np.random.seed(42)
START_TIME = time.time()

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))

OOS_START = '2019-01-01'
OOS_END = '2026-05-18'
WINDOW = 2000
REFIT_EVERY = 63
HORIZON = 1
HARVEY_THRESHOLD = 3.0
SNAPSHOT_CSV = os.path.join(
    PROJECT_ROOT,
    'experiments',
    'k1685',
    'data',
    'k1685_spy_vix_snapshot.csv',
)
EXPECTED_SNAPSHOT_SHA256 = (
    'eee7f9c62ce3ed3ee68d2bffeb3c9386fb8a6343e1a053379cfc89058518e3fb'
)

print("=" * 70)
print("K1379: HAR-style daily-r-squared Benchmarks vs A4f (Paper 9)")
print("=" * 70)

# ============================================================
# 1. DATA LOADING
# ============================================================
print("\n[1] Loading snapshot CSV...")
with open(SNAPSHOT_CSV, 'rb') as f:
    snapshot_sha256 = hashlib.sha256(f.read()).hexdigest()
if snapshot_sha256 != EXPECTED_SNAPSHOT_SHA256:
    raise RuntimeError(
        'Pinned snapshot hash mismatch: '
        f'expected {EXPECTED_SNAPSHOT_SHA256}, got {snapshot_sha256}'
    )

df_raw = pd.read_csv(SNAPSHOT_CSV, parse_dates=['date'], index_col='date')
df_raw.index = pd.to_datetime(df_raw.index)
df_raw = df_raw.sort_index(kind='stable')
if df_raw.index.has_duplicates:
    duplicate_dates = df_raw.index[df_raw.index.duplicated(keep=False)].unique()
    raise RuntimeError(
        'Pinned snapshot contains duplicate dates: '
        + ', '.join(str(x.date()) for x in duplicate_dates[:10])
    )

snapshot_start = df_raw.index.min()
snapshot_end = df_raw.index.max()
df_raw = df_raw.loc[:OOS_END].copy()
analysis_slice_csv = df_raw.to_csv(
    index=True,
    index_label='date',
    date_format='%Y-%m-%d',
    float_format='%.17g',
    na_rep='',
    lineterminator='\n',
)
analysis_slice_sha256 = hashlib.sha256(analysis_slice_csv.encode('utf-8')).hexdigest()

prices = df_raw['spy_close'].dropna()
log_ret = np.log(prices / prices.shift(1))
vix_close = df_raw['vix_close'].dropna()

df = pd.DataFrame({'log_ret': log_ret, 'VIX': vix_close}).dropna()
oos_mask = (df.index >= OOS_START) & (df.index <= OOS_END)

ret = df['log_ret'].values
vix = df['VIX'].values
log_vix = np.log(np.maximum(vix, 1.0))
r2 = ret ** 2

oos_indices = np.where(oos_mask)[0]
n_oos = len(oos_indices)

print(f"  Snapshot SHA256: {snapshot_sha256}")
print(f"  SPY: {df.index[0].date()} to {df.index[-1].date()}, n={len(df)}")
print(f"  OOS: {OOS_START} to {OOS_END}, n_oos={n_oos}")

# ============================================================
# 2. MODEL IMPLEMENTATIONS
# ============================================================

@njit(cache=True)
def gjr_loglik(params, returns):
    omega, alpha, gamma, beta = params
    n = len(returns)
    h = np.empty(n)
    h[0] = np.var(returns[:min(250, n)])
    ll = 0.0
    for t in range(1, n):
        asym = gamma * returns[t-1]**2 if returns[t-1] < 0 else 0.0
        h[t] = omega + alpha * returns[t-1]**2 + asym + beta * h[t-1]
        if h[t] < 1e-10:
            h[t] = 1e-10
    for t in range(n):
        if h[t] > 0:
            ll += -0.5 * (np.log(2 * np.pi) + np.log(h[t]) + returns[t]**2 / h[t])
    return -ll


def fit_gjr(returns):
    var0 = np.var(returns)
    best_ll, best_p = np.inf, None
    for s in [[var0 * 0.05, 0.05, 0.05, 0.90],
              [var0 * 0.02, 0.03, 0.08, 0.88],
              [var0 * 0.10, 0.08, 0.10, 0.80]]:
        try:
            res = optimize.minimize(gjr_loglik, s, args=(returns,),
                                    method='L-BFGS-B',
                                    bounds=[(1e-8, var0), (1e-4, 0.3),
                                            (1e-4, 0.3), (0.5, 0.999)])
            if (
                res.success
                and np.isfinite(res.fun)
                and np.all(np.isfinite(res.x))
                and res.fun < best_ll
            ):
                best_ll, best_p = res.fun, res.x
        except Exception:  # silent-ok: multistart GJR-MLE start diverged; None retained if all starts fail (caller checks is not None)
            pass
    return best_p


def gjr_1step(p, h, r):
    o, a, g, b = p
    asym = g * r**2 if r < 0 else 0.0
    return max(o + a * r**2 + asym + b * h, 1e-10)


def fit_a4f(returns, log_vix_vals, vix_vals):
    """A4f: τ_t = θ₀ + θ₁VIX²_{t-1}, free ω_g."""
    infeasible_objective = 1e10
    n = len(returns)
    log_vix_lag = np.empty(n)
    log_vix_lag[0] = log_vix_vals[0]
    log_vix_lag[1:] = log_vix_vals[:-1]
    vix_lag = np.exp(log_vix_lag)

    def neg_loglik(params):
        th0, th1, omg, alp, gam, bet = params
        if omg <= 0 or alp < 0 or gam < 0 or bet < 0:
            return infeasible_objective
        persist = alp + gam / 2.0 + bet
        if persist >= 1.0:
            return infeasible_objective
        tau = np.maximum(th0 + th1 * vix_lag**2, 1e-16)
        eg = omg / (1.0 - persist)
        g = eg
        ll = 0.0
        for t in range(1, n):
            u = returns[t-1] / np.sqrt(max(tau[t], 1e-16))
            asym = gam * u**2 if u < 0 else 0.0
            g = omg + alp * u**2 + asym + bet * g
            g = max(g, 1e-10)
            sigma2 = tau[t] * g
            if sigma2 > 0:
                ll += -0.5 * (np.log(2*np.pi) + np.log(sigma2) + returns[t]**2 / sigma2)
        return -ll

    var0 = np.var(returns)
    vm = np.mean(vix_lag**2) + 1e-8
    best_ll, best_p = np.inf, None
    for s in [[var0 * 0.1, var0/vm, 0.05, 0.05, 0.05, 0.90],
              [var0 * 0.05, var0/vm*0.5, 0.10, 0.03, 0.08, 0.88],
              [var0 * 0.2, var0/vm*1.5, 0.02, 0.08, 0.10, 0.80]]:
        try:
            res = optimize.minimize(neg_loglik, s, method='L-BFGS-B',
                                    bounds=[(-1e-2, 1e-2), (1e-8, 1e-3), (1e-6, 1.0),
                                            (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)],
                                    options={'maxiter': 500})
            if (
                res.success
                and np.isfinite(res.fun)
                and np.all(np.isfinite(res.x))
                and res.fun < infeasible_objective
                and res.x[2] > 0
                and res.x[3] >= 0
                and res.x[4] >= 0
                and res.x[5] >= 0
                and res.x[3] + res.x[4] / 2.0 + res.x[5] < 1.0
                and res.fun < best_ll
            ):
                best_ll, best_p = res.fun, res.x
        except Exception:  # silent-ok: multistart GARCH-X-VIX MLE start diverged; None retained if all starts fail (caller checks is not None)
            pass
    return best_p


def fit_har_r2(r2_series, vix_series=None):
    """
    Fit a HAR-style daily-r² model (optionally augmented by lagged VIX) via OLS.
    r2_series: squared daily log returns, using past values only as regressors.
    vix_series: if not None, add VIX²_{t-1} as a regressor.

    Returns coefficient vector β (intercept last in sklearn convention,
    but here we build X explicitly).
    """
    n = len(r2_series)
    if n < 30:
        raise ValueError("HAR-style fit requires at least 30 observations")

    # Build features (all using lag ≥ 1, no lookahead)
    # RV_{t-1}
    rv_d = np.full(n, np.nan)
    rv_d[1:] = r2_series[:-1]
    # RV̄^(5): mean of RV_{t-1}, ..., RV_{t-5}
    rv_w = np.full(n, np.nan)
    for i in range(5, n):
        rv_w[i] = np.mean(r2_series[i-5:i])
    # RV̄^(22): mean of RV_{t-1}, ..., RV_{t-22}
    rv_m = np.full(n, np.nan)
    for i in range(22, n):
        rv_m[i] = np.mean(r2_series[i-22:i])

    if vix_series is not None:
        vix_sq_lag = np.full(n, np.nan)
        vix_sq_lag[1:] = vix_series[:-1] ** 2
        mask = ~(np.isnan(rv_d) | np.isnan(rv_w) | np.isnan(rv_m) |
                 np.isnan(vix_sq_lag) | np.isnan(r2_series))
        X = np.column_stack([np.ones(mask.sum()), rv_d[mask], rv_w[mask],
                             rv_m[mask], vix_sq_lag[mask]])
    else:
        mask = ~(np.isnan(rv_d) | np.isnan(rv_w) | np.isnan(rv_m) |
                 np.isnan(r2_series))
        X = np.column_stack([np.ones(mask.sum()), rv_d[mask], rv_w[mask], rv_m[mask]])

    y = r2_series[mask]
    beta, _, rank, _ = np.linalg.lstsq(X, y, rcond=None)
    if rank != X.shape[1] or not np.all(np.isfinite(beta)):
        raise RuntimeError(
            f"HAR-style OLS failed full-rank finite check: rank={rank}, columns={X.shape[1]}"
        )
    return beta


def har_r2_forecast(beta, rv_last, rv_history, vix_last=None):
    """One-step forecast from a HAR-style daily-r² model."""
    if beta is None:
        return np.nan
    n_hist = len(rv_history)
    rv_d = rv_last
    rv_w = np.mean(rv_history[-5:]) if n_hist >= 5 else rv_last
    rv_m = np.mean(rv_history[-22:]) if n_hist >= 22 else rv_last
    if vix_last is not None and len(beta) == 5:
        pred = beta[0] + beta[1]*rv_d + beta[2]*rv_w + beta[3]*rv_m + beta[4]*vix_last**2
    else:
        pred = beta[0] + beta[1]*rv_d + beta[2]*rv_w + beta[3]*rv_m
    return float(pred)


# ============================================================
# 3. ROLLING WINDOW OOS FORECASTING
# ============================================================
print("\n[2] Rolling window OOS forecasting (4 models)...")

fcst_gjr = np.full(n_oos, np.nan)
fcst_a4f = np.full(n_oos, np.nan)
fcst_har = np.full(n_oos, np.nan)
fcst_har_vix = np.full(n_oos, np.nan)
raw_fcst_har = np.full(n_oos, np.nan)
raw_fcst_har_vix = np.full(n_oos, np.nan)

gjr_state = {'params': None, 'h': None}
a4f_state = {'params': None, 'g': None}
har_beta = None
har_vix_beta = None

for t_idx, abs_idx in enumerate(oos_indices):
    if t_idx % 500 == 0:
        elapsed = time.time() - START_TIME
        print(f"  OOS step {t_idx}/{n_oos} ({elapsed:.1f}s)")

    need_refit = (t_idx % REFIT_EVERY == 0) or (t_idx == 0)

    if need_refit:
        ts = max(0, abs_idx - WINDOW)
        tr_ret = ret[ts:abs_idx]
        tr_log_vix = log_vix[ts:abs_idx]
        tr_vix = vix[ts:abs_idx]
        tr_r2 = r2[ts:abs_idx]

        # GJR-GARCH
        gjr_p = fit_gjr(tr_ret)
        if gjr_p is None:
            raise RuntimeError(f"All GJR optimization starts failed at OOS step {t_idx}")
        gjr_state['params'] = gjr_p
        h = np.var(tr_ret)
        for i in range(1, len(tr_ret)):
            h = gjr_1step(gjr_p, h, tr_ret[i-1])
        gjr_state['h'] = h

        # A4f
        a4f_p = fit_a4f(tr_ret, tr_log_vix, tr_vix)
        if a4f_p is None:
            raise RuntimeError(f"All A4f optimization starts failed at OOS step {t_idx}")
        a4f_state['params'] = a4f_p
        th0, th1, omg, alp, gam, bet = a4f_p
        persist = alp + gam / 2.0 + bet
        nt = len(tr_ret)
        lv_lag = np.empty(nt)
        lv_lag[0] = tr_log_vix[0]
        lv_lag[1:] = tr_log_vix[:-1]
        v_lag = np.exp(lv_lag)
        tau_tr = np.maximum(th0 + th1 * v_lag**2, 1e-16)
        eg = omg / (1.0 - persist) if persist < 1.0 else 1.0
        g = eg
        for i in range(1, nt):
            u = tr_ret[i-1] / np.sqrt(max(tau_tr[i], 1e-16))
            asym = gam * u**2 if u < 0 else 0.0
            g = omg + alp * u**2 + asym + bet * g
            g = max(g, 1e-10)
        a4f_state['g'] = g

        # HAR-style daily r²
        har_beta = fit_har_r2(tr_r2)

        # HAR-style daily r² augmented with lagged VIX
        har_vix_beta = fit_har_r2(tr_r2, tr_vix)

    # GJR forecast
    if gjr_state['params'] is not None:
        h = gjr_1step(gjr_state['params'], gjr_state['h'], ret[abs_idx-1])
        fcst_gjr[t_idx] = h
        gjr_state['h'] = h

    # A4f forecast
    if a4f_state['params'] is not None:
        th0, th1, omg, alp, gam, bet = a4f_state['params']
        vix_t1 = vix[abs_idx - 1]  # VIX at t-1 (signal.shift(1))
        tau_t = max(th0 + th1 * vix_t1**2, 1e-16)
        g = a4f_state['g']
        # Match fit_a4f and Paper 9's Engle-style baseline exactly: tau_t is
        # predetermined by VIX_{t-1}, so estimation and OOS use the same scale.
        u = ret[abs_idx-1] / np.sqrt(max(tau_t, 1e-16))
        asym = gam * u**2 if u < 0 else 0.0
        g = omg + alp * u**2 + asym + bet * g
        g = max(g, 1e-10)
        fcst_a4f[t_idx] = tau_t * g
        a4f_state['g'] = g

    # HAR-style daily-r² forecast (all regressors at t-1, no lookahead)
    if har_beta is not None and abs_idx > 22:
        ts_start = max(0, abs_idx - WINDOW)
        rv_hist = r2[ts_start:abs_idx]
        rv_last = r2[abs_idx - 1]
        raw_fcst_har[t_idx] = har_r2_forecast(har_beta, rv_last, rv_hist)
        fcst_har[t_idx] = max(raw_fcst_har[t_idx], 1e-16)

    # HAR-style daily-r²-VIX forecast (VIX²_{t-1} as extra regressor)
    if har_vix_beta is not None and abs_idx > 22:
        ts_start = max(0, abs_idx - WINDOW)
        rv_hist = r2[ts_start:abs_idx]
        rv_last = r2[abs_idx - 1]
        vix_last = vix[abs_idx - 1]  # VIX at t-1
        raw_fcst_har_vix[t_idx] = har_r2_forecast(
            har_vix_beta, rv_last, rv_hist, vix_last
        )
        fcst_har_vix[t_idx] = max(raw_fcst_har_vix[t_idx], 1e-16)

print(f"  Done in {time.time()-START_TIME:.1f}s")

# ============================================================
# 4. QLIKE LOSSES
# ============================================================
print("\n[3] Computing QLIKE losses...")

r2_oos = r2[oos_indices]
valid_all = (
    np.isfinite(fcst_gjr)
    & np.isfinite(fcst_a4f)
    & np.isfinite(fcst_har)
    & np.isfinite(fcst_har_vix)
    & np.isfinite(r2_oos)
    & (r2_oos > 1e-16)
)
n_zero_return_excluded = int(np.sum(np.isfinite(r2_oos) & (r2_oos <= 1e-16)))
oos_dates = df.index[oos_indices]
har_nonpositive_mask = np.isfinite(raw_fcst_har) & (raw_fcst_har <= 0)
har_vix_nonpositive_mask = np.isfinite(raw_fcst_har_vix) & (raw_fcst_har_vix <= 0)
positive_forecast_mask = (
    valid_all
    & np.isfinite(raw_fcst_har)
    & (raw_fcst_har > 0)
    & np.isfinite(raw_fcst_har_vix)
    & (raw_fcst_har_vix > 0)
)

# Canonical Patton QLIKE orientation: actual / forecast.  The pre-repair
# artifact inverted this ratio, so every loss and downstream DM test must be
# regenerated rather than reusing the saved arrays.
loss_gjr = qlike_pointwise(r2_oos, fcst_gjr)
loss_a4f = qlike_pointwise(r2_oos, fcst_a4f)
loss_har = qlike_pointwise(r2_oos, fcst_har)
loss_har_vix = qlike_pointwise(r2_oos, fcst_har_vix)

# QLIKE means (lower = better)
v = valid_all
print(f"  Valid OOS obs: {v.sum()}")
print(f"  GJR    QLIKE: {np.mean(loss_gjr[v]):.6f}")
print(f"  A4f    QLIKE: {np.mean(loss_a4f[v]):.6f}")
print(f"  HAR-r2 QLIKE: {np.mean(loss_har[v]):.6f}")
print(f"  HAR-r2-VIX QLIKE: {np.mean(loss_har_vix[v]):.6f}")

# ============================================================
# 5. DM TESTS
# ============================================================
print("\n[4] Canonical DM tests with Bartlett HAC (Harvey threshold |t| > 3.0)...")


def acf_diagnostics(values, max_lag=5):
    """Sample ACF diagnostics for the exact loss differential sent to DM."""
    values = np.asarray(values, dtype=np.float64)
    centered = values - np.mean(values)
    denominator = float(np.dot(centered, centered))
    output = {}
    for lag in range(1, max_lag + 1):
        key = f'lag_{lag}'
        output[key] = (
            float(np.dot(centered[lag:], centered[:-lag]) / denominator)
            if len(values) > lag and denominator > 0
            else None
        )
    return output


def canonical_hac_lag(n, h=HORIZON):
    """Mirror the documented bandwidth used by canonical_dm_test for audit output."""
    return max(1, min(int(np.ceil(h ** (1 / 3) * n ** (1 / 3))), n // 4))


def nw_t_sensitivity(values, max_lag):
    """Reproduce the canonical Bartlett LRV at a chosen diagnostic lag."""
    values = np.asarray(values, dtype=np.float64)
    n = len(values)
    mean = float(np.mean(values))
    long_run_var = float(np.mean((values - mean) ** 2))
    for lag in range(1, max_lag + 1):
        weight = 1.0 - lag / (max_lag + 1.0)
        autocov = float(
            np.mean((values[lag:] - mean) * (values[:-lag] - mean))
        )
        long_run_var += 2.0 * weight * autocov
    if not np.isfinite(long_run_var) or long_run_var <= 0:
        return None
    return float(mean / np.sqrt(long_run_var / n))


# canonical_dm_test defines d = loss(model 1) - loss(model 2), hence a
# negative statistic favours model 1.  Keeping the two series explicit avoids
# the sign ambiguity in the former pre-differenced interface.
pairs = [
    ('A4f vs GJR', 'A4f', loss_a4f[v], 'GJR', loss_gjr[v]),
    (
        'A4f vs HAR-RV',
        'A4f',
        loss_a4f[v],
        'HAR-style daily-r²',
        loss_har[v],
    ),
    (
        'A4f vs HAR-RV-VIX',
        'A4f',
        loss_a4f[v],
        'HAR-style daily-r²-VIX',
        loss_har_vix[v],
    ),
    (
        'HAR-RV vs GJR',
        'HAR-style daily-r²',
        loss_har[v],
        'GJR',
        loss_gjr[v],
    ),
    (
        'HAR-RV-VIX vs GJR',
        'HAR-style daily-r²-VIX',
        loss_har_vix[v],
        'GJR',
        loss_gjr[v],
    ),
    (
        'HAR-RV-VIX vs HAR-RV',
        'HAR-style daily-r²-VIX',
        loss_har_vix[v],
        'HAR-style daily-r²',
        loss_har[v],
    ),
]

dm_results = {}
for label, model1, model1_loss, model2, model2_loss in pairs:
    d = model1_loss - model2_loss
    t, p = canonical_dm_test(model1_loss, model2_loss, h=HORIZON)
    hac_lag = canonical_hac_lag(len(d))
    acf = acf_diagnostics(d)
    sensitivity_lags = sorted({0, 1, 5, 10, hac_lag, 20})
    lag_sensitivity = {
        f'lag_{lag}': {
            'dm_t': nw_t_sensitivity(d, lag),
            'hac_applied': bool(lag > 0),
        }
        for lag in sensitivity_lags
    }
    primary_sensitivity_t = lag_sensitivity[f'lag_{hac_lag}']['dm_t']
    if primary_sensitivity_t is None or not np.isclose(
        t, primary_sensitivity_t, rtol=1e-12, atol=1e-12
    ):
        raise RuntimeError(
            f'{label}: canonical DM and reported HAC-lag diagnostic disagree'
        )
    hln_factor = float(
        np.sqrt(
            (
                len(d)
                + 1
                - 2 * HORIZON
                + HORIZON * (HORIZON - 1) / len(d)
            )
            / len(d)
        )
    )
    t_hln = float(t * hln_factor)
    p_hln = float(2.0 * stats.t.sf(abs(t_hln), df=len(d) - 1))
    harvey = bool(abs(t) > HARVEY_THRESHOLD)
    if t < 0:
        direction = 'model1_lower_loss'
    elif t > 0:
        direction = 'model2_lower_loss'
    else:
        direction = 'tie_or_undefined'
    winner = model1 if (harvey and t < 0) else model2 if (harvey and t > 0) else None
    advantage_pct = 100.0 * (np.mean(model2_loss) - np.mean(model1_loss)) / np.mean(model2_loss)
    print(
        f"  {label:25s}: t={t:+.3f}, p={p:.4f}, "
        f"acf(1)={acf['lag_1']:+.3f}, HAC lag={hac_lag}, "
        f"Harvey={'PASS' if harvey else 'FAIL'}"
    )
    dm_results[label] = {
        'model1': model1,
        'model2': model2,
        'loss_differential': 'model1_minus_model2',
        'mean_loss_differential': float(np.mean(d)),
        'model1_qlike_advantage_pct': float(advantage_pct),
        'loss_differential_acf': acf,
        'loss_differential_acf_1': acf['lag_1'],
        'hac_max_lag': hac_lag,
        'hac_lag_sensitivity': lag_sensitivity,
        'inference_status': 'ok',
        'dm_t': t,
        'dm_p': p,
        'hln_diagnostic': {
            'factor': hln_factor,
            'dm_t': t_hln,
            'dm_p': p_hln,
            'primary': False,
            'note': 'Correct HLN factor shown diagnostically; canonical unscaled HAC-DM is primary.',
        },
        'harvey_pass': harvey,
        'direction': direction,
        'harvey_winner': winner,
        'forecast_stability': (
            'bounded_nonpositive_raw_forecasts_present'
            if 'HAR-RV-VIX' in label and np.any(har_vix_nonpositive_mask)
            else 'all_raw_forecasts_positive'
        ),
    }

# Positivity robustness excludes every date on which either HAR-style OLS
# specification produced a nonpositive raw variance forecast.  It is
# diagnostic only because conditioning on forecast validity changes the
# evaluation sample, but it reveals whether the 1e-16 numerical floor alone
# drives the qualitative Harvey screen.
positive_only_pairs = [
    ('A4f vs GJR', loss_a4f[positive_forecast_mask], loss_gjr[positive_forecast_mask]),
    (
        'A4f vs HAR-RV',
        loss_a4f[positive_forecast_mask],
        loss_har[positive_forecast_mask],
    ),
    (
        'A4f vs HAR-RV-VIX',
        loss_a4f[positive_forecast_mask],
        loss_har_vix[positive_forecast_mask],
    ),
    (
        'HAR-RV vs GJR',
        loss_har[positive_forecast_mask],
        loss_gjr[positive_forecast_mask],
    ),
    (
        'HAR-RV-VIX vs GJR',
        loss_har_vix[positive_forecast_mask],
        loss_gjr[positive_forecast_mask],
    ),
    (
        'HAR-RV-VIX vs HAR-RV',
        loss_har_vix[positive_forecast_mask],
        loss_har[positive_forecast_mask],
    ),
]
positive_only_dm = {}
for label, loss1, loss2 in positive_only_pairs:
    t_positive, p_positive = canonical_dm_test(loss1, loss2, h=HORIZON)
    positive_only_dm[label] = {
        'dm_t': t_positive,
        'dm_p': p_positive,
        'harvey_pass': bool(abs(t_positive) > HARVEY_THRESHOLD),
    }

# ============================================================
# 6. SAVE LOSSES FOR K_NEW_C (White RC / SPA)
# ============================================================
np.save(os.path.join(SCRIPT_DIR, 'k1379_loss_gjr.npy'), loss_gjr)
np.save(os.path.join(SCRIPT_DIR, 'k1379_loss_a4f.npy'), loss_a4f)
np.save(os.path.join(SCRIPT_DIR, 'k1379_loss_har.npy'), loss_har)
np.save(os.path.join(SCRIPT_DIR, 'k1379_loss_har_vix.npy'), loss_har_vix)
np.save(os.path.join(SCRIPT_DIR, 'k1379_valid_mask.npy'), v)
print("\n  Saved loss arrays for K_NEW_C")

# Regenerate the article chart from the corrected loss orientation and HAC
# statistics so the published visual cannot silently retain invalid numbers.
chart_path = os.path.join(SCRIPT_DIR, 'k1379_general_article_chart.png')
chart_tmp_path = chart_path + '.tmp.png'
model_names = ['GJR', 'A4f', 'HAR-style r²', 'HAR-style r²-VIX']
model_means = [
    np.mean(loss_gjr[v]),
    np.mean(loss_a4f[v]),
    np.mean(loss_har[v]),
    np.mean(loss_har_vix[v]),
]
key_dm_labels = ['A4f vs GJR', 'A4f vs HAR-RV', 'A4f vs HAR-RV-VIX']
key_dm_display_labels = [
    'A4f vs GJR',
    'A4f vs HAR-style r²',
    'A4f vs HAR-style r²-VIX',
]
key_dm_values = [dm_results[x]['dm_t'] for x in key_dm_labels]

fig, axes = plt.subplots(1, 2, figsize=(15, 7), constrained_layout=True)
bars = axes[0].bar(model_names, model_means, color=['#607d8b', '#1976d2', '#43a047', '#fb8c00'])
axes[0].set_title('Out-of-sample Patton QLIKE by model')
axes[0].set_ylabel('Mean QLIKE (lower is better)')
axes[0].grid(axis='y', alpha=0.25)
for bar, value in zip(bars, model_means):
    axes[0].text(
        bar.get_x() + bar.get_width() / 2,
        bar.get_height(),
        f'{value:.3f}' if value < 1_000 else f'{value:.2e}',
        ha='center',
        va='bottom',
    )
if max(model_means) / min(model_means) > 100:
    axes[0].set_yscale('log')
    axes[0].set_title(
        'Out-of-sample Patton QLIKE by model (log scale)\n'
        'Nonpositive OLS variance forecasts are floored at 1e-16'
    )

y_pos = np.arange(len(key_dm_labels))
colors = ['#1976d2' if value < 0 else '#ef5350' for value in key_dm_values]
axes[1].barh(y_pos, key_dm_values, color=colors)
axes[1].set_yticks(y_pos, labels=key_dm_display_labels)
axes[1].axvline(0, color='black', linewidth=1)
axes[1].axvline(HARVEY_THRESHOLD, color='#2e7d32', linestyle='--', linewidth=1.5)
axes[1].axvline(-HARVEY_THRESHOLD, color='#2e7d32', linestyle='--', linewidth=1.5)
axes[1].set_title('Canonical HAC DM statistics')
axes[1].set_xlabel('DM t (negative favours model named first; dashed = ±3)')
axes[1].grid(axis='x', alpha=0.25)
for y, value in zip(y_pos, key_dm_values):
    axes[1].text(
        value + (0.12 if value < 0 else -0.12),
        y,
        f'{value:+.2f}',
        ha='left' if value < 0 else 'right',
        va='center',
        color='white',
    )

valid_dates = oos_dates[v]
fig.suptitle(
    'Daily volatility forecast comparison\n'
    f'{valid_dates[0].date()} to {valid_dates[-1].date()}, n={v.sum():,}',
    fontsize=15,
)
fig.savefig(chart_tmp_path, dpi=160, bbox_inches='tight')
plt.close(fig)
os.replace(chart_tmp_path, chart_path)
print(f"  Regenerated chart: {chart_path}")

# A second public-facing chart makes the HAC bandwidth robustness directly
# auditable.  It intentionally covers only the three stable comparators; the
# HAR-style r²-VIX series has three nonpositive raw variance forecasts and is
# reported separately as an instability diagnostic rather than as a clean
# bandwidth comparison.
sensitivity_chart_path = os.path.join(
    SCRIPT_DIR, 'k1379_hac_lag_sensitivity.png'
)
sensitivity_chart_tmp_path = sensitivity_chart_path + '.tmp.png'
sensitivity_lags = [0, 1, 5, 10, 13, 20]
sensitivity_series = [
    ('A4f vs GJR', 'A4f vs GJR', '#1976d2'),
    ('A4f vs HAR-RV', 'A4f vs HAR-style r²', '#7b1fa2'),
    ('HAR-RV vs GJR', 'HAR-style r² vs GJR', '#00897b'),
]

fig_sensitivity, ax_sensitivity = plt.subplots(
    figsize=(10.5, 6.5), constrained_layout=True
)
for result_key, display_label, color in sensitivity_series:
    t_values = [
        dm_results[result_key]['hac_lag_sensitivity'][f'lag_{lag}']['dm_t']
        for lag in sensitivity_lags
    ]
    ax_sensitivity.plot(
        sensitivity_lags,
        t_values,
        marker='o',
        linewidth=2.2,
        label=display_label,
        color=color,
    )
ax_sensitivity.axhline(0, color='black', linewidth=1)
ax_sensitivity.axhline(
    HARVEY_THRESHOLD, color='#c62828', linestyle='--', linewidth=1.5
)
ax_sensitivity.axhline(
    -HARVEY_THRESHOLD, color='#c62828', linestyle='--', linewidth=1.5
)
ax_sensitivity.axvline(
    canonical_hac_lag(int(v.sum())),
    color='#616161',
    linestyle=':',
    linewidth=1.8,
    label=f'Primary HAC lag = {canonical_hac_lag(int(v.sum()))}',
)
ax_sensitivity.set_xticks(sensitivity_lags)
ax_sensitivity.set_xlabel('Bartlett HAC maximum lag')
ax_sensitivity.set_ylabel('DM t (negative favours model named first)')
ax_sensitivity.set_title(
    'DM inference across pre-specified HAC lags\n'
    f'{valid_dates[0].date()} to {valid_dates[-1].date()}, n={v.sum():,}'
)
ax_sensitivity.grid(alpha=0.25)
ax_sensitivity.legend(frameon=False, loc='best')
fig_sensitivity.savefig(
    sensitivity_chart_tmp_path, dpi=160, bbox_inches='tight'
)
plt.close(fig_sensitivity)
os.replace(sensitivity_chart_tmp_path, sensitivity_chart_path)
print(f"  Regenerated chart: {sensitivity_chart_path}")

# ============================================================
# 7. RESULTS JSON
# ============================================================
elapsed = time.time() - START_TIME
results = {
    "experiment_id": "k1379",
    "title": "Paper 9 HAR-style daily-r-squared Benchmarks vs A4f",
    "metadata": {
        "data_source": "experiments/k1685/data/k1685_spy_vix_snapshot.csv",
        "data_source_provenance": "Independent yfinance 1.2.0 SPY/^VIX fetch pinned by K1685 on 2026-07-11; unique dates and cross-checked there against the Paper 9 CSV.",
        "input_columns": {
            "price": "spy_close (unadjusted close, retained to match the original K1379 specification)",
            "volatility_index": "vix_close",
        },
        "snapshot_sha256": snapshot_sha256,
        "snapshot_expected_sha256": EXPECTED_SNAPSHOT_SHA256,
        "snapshot_start": str(snapshot_start.date()),
        "snapshot_end": str(snapshot_end.date()),
        "analysis_slice_sha256": analysis_slice_sha256,
        "data_start": str(df.index[0].date()),
        "data_end": str(df.index[-1].date()),
        "oos_start": OOS_START,
        "oos_end": OOS_END,
        "first_valid_oos_date": str(valid_dates[0].date()),
        "last_valid_oos_date": str(valid_dates[-1].date()),
        "window": WINDOW,
        "refit_every": REFIT_EVERY,
        "forecast_horizon_days": HORIZON,
        "n_data": int(len(df)),
        "n_oos": int(n_oos),
        "n_valid_oos": int(v.sum()),
        "n_zero_return_excluded": n_zero_return_excluded,
        "zero_return_policy": "Exclude r_squared <= 1e-16 from the shared QLIKE/DM mask for all models.",
        "variance_forecast_floor": 1e-16,
        "forecast_diagnostics": {
            "HAR_RV": {
                "raw_nonpositive_count": int(np.sum(har_nonpositive_mask)),
                "raw_nonpositive_dates": [
                    str(date.date()) for date in oos_dates[har_nonpositive_mask]
                ],
            },
            "HAR_RV_VIX": {
                "raw_nonpositive_count": int(np.sum(har_vix_nonpositive_mask)),
                "raw_nonpositive_dates": [
                    str(date.date()) for date in oos_dates[har_vix_nonpositive_mask]
                ],
            },
        },
        "seed": 42,
        "harvey_threshold": HARVEY_THRESHOLD,
        "qlike_proxy": "r_squared (daily squared log return)",
        "qlike_formula": "actual/predicted - log(actual/predicted) - 1",
        "har_benchmark_scope": "HAR-style regression on lagged daily squared returns; not a canonical intraday realized-variance HAR-RV benchmark",
        "model_display_names": {
            "HAR_RV": "HAR-style daily-r-squared",
            "HAR_RV_VIX": "HAR-style daily-r-squared-VIX",
        },
        "a4f_normalization": "Engle-style contemporaneous scale: u_{t-1}=r_{t-1}/sqrt(tau_t), with tau_t predetermined by VIX_{t-1}; identical in fit and OOS recursion.",
        "dm_method": "canonical volpred.stats.model_evaluation.dm_test with Bartlett Newey-West HAC",
        "dm_hac_bandwidth_rule": "max(1, min(ceil(h^(1/3) * n^(1/3)), n//4))",
        "dm_small_sample_correction": "none",
        "dm_sign_convention": "loss(model1)-loss(model2); negative t favors model1",
        "elapsed_seconds": round(elapsed, 1),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "note": "HAR-style daily-r-squared models use rolling OLS; A4f and GJR use MLE. All models are evaluated on the same daily r-squared QLIKE proxy.",
    },
    "qlike_means": {
        "GJR": float(np.mean(loss_gjr[v])),
        "A4f": float(np.mean(loss_a4f[v])),
        "HAR_RV": float(np.mean(loss_har[v])),
        "HAR_RV_VIX": float(np.mean(loss_har_vix[v])),
    },
    "dm_tests": dm_results,
    "positive_raw_forecast_robustness": {
        "status": "diagnostic_only_sample_selection",
        "n_valid": int(np.sum(positive_forecast_mask)),
        "qlike_means": {
            "GJR": float(np.mean(loss_gjr[positive_forecast_mask])),
            "A4f": float(np.mean(loss_a4f[positive_forecast_mask])),
            "HAR_RV": float(np.mean(loss_har[positive_forecast_mask])),
            "HAR_RV_VIX": float(np.mean(loss_har_vix[positive_forecast_mask])),
        },
        "dm_tests": positive_only_dm,
        "interpretation": "Excludes dates with nonpositive raw HAR-style OLS variance forecasts; not the primary common-date evaluation.",
    },
    "methodology_repair": {
        "supersedes_pre_repair_artifact": True,
        "pre_repair_issues": [
            "QLIKE ratio was inverted as predicted/actual",
            "DM long-run variance omitted all autocovariances",
            "ad-hoc h=1 HLN factor was incorrect",
            "A4f fit used tau_t normalization while its OOS recursion used tau_{t-1}",
            "mutable Paper 9 CSV contained duplicate dates",
        ],
        "pre_repair_harvey_significant_comparisons": [],
        "current_harvey_significant_comparisons": [
            label for label, test in dm_results.items() if test['harvey_pass']
        ],
        "harvey_significance_flips": [
            {
                "comparison": label,
                "from": "not_significant",
                "to": "significant",
            }
            for label, test in dm_results.items()
            if test['harvey_pass']
        ],
        "comparison_caveat": "The rerun jointly corrects the loss orientation, HAC inference, A4f fit/OOS normalization alignment, and duplicated-date input, so old/new t-stat differences are not attributable to HAC alone.",
    },
    "paper9_c4_assessment": {
        "scope": "partial_evidence_only",
        "benchmark_limitation": "K1379 uses daily squared returns rather than intraday realized variance, so it does not fully close the canonical HAR-RV benchmark request.",
        "a4f_vs_har_rv_harvey_pass": dm_results.get('A4f vs HAR-RV', {}).get('harvey_pass', None),
        "verdict": (
            "C4 PARTIAL — A4f has significantly lower QLIKE than the daily-r-squared HAR-style comparator"
            if dm_results.get('A4f vs HAR-RV', {}).get('harvey_winner') == 'A4f'
            else "C4 PARTIAL — A4f has significantly higher QLIKE than the daily-r-squared HAR-style comparator"
            if dm_results.get('A4f vs HAR-RV', {}).get('harvey_winner') == 'HAR-style daily-r²'
            else "C4 PARTIAL — no statistically significant A4f–daily-r-squared-HAR difference under this protocol"
        ),
    },
    "references": [
        {
            "authors": "Diebold, F.X.; Mariano, R.S.",
            "year": 1995,
            "title": "Comparing Predictive Accuracy",
            "journal": "Journal of Business & Economic Statistics 13(3), 253–263",
            "doi": "10.1080/07350015.1995.10524599",
        },
        {
            "authors": "Harvey, D.; Leybourne, S.; Newbold, P.",
            "year": 1997,
            "title": "Testing the equality of prediction mean squared errors",
            "journal": "International Journal of Forecasting 13(2), 281–291",
            "doi": "10.1016/S0169-2070(96)00719-4",
        },
        {
            "authors": "Newey, W.K.; West, K.D.",
            "year": 1987,
            "title": "A Simple, Positive Semi-definite, Heteroskedasticity and Autocorrelation Consistent Covariance Matrix",
            "journal": "Econometrica 55(3), 703–708",
            "doi": "10.2307/1913610",
        },
        {
            "authors": "Patton, A.J.",
            "year": 2011,
            "title": "Volatility forecast comparison using imperfect volatility proxies",
            "journal": "Journal of Econometrics 160(1), 246–256",
            "doi": "10.1016/j.jeconom.2010.03.034",
        },
        {
            "authors": "Corsi, F.",
            "year": 2009,
            "title": "A Simple Approximate Long-Memory Model of Realized Volatility",
            "journal": "Journal of Financial Econometrics 7(2), 174–196",
            "doi": "10.1093/jjfinec/nbp001",
        },
        {
            "authors": "Harvey, C.R.; Liu, Y.; Zhu, H.",
            "year": 2016,
            "title": "… and the Cross-Section of Expected Returns",
            "journal": "Review of Financial Studies 29(1), 5–68",
            "doi": "10.1093/rfs/hhv059",
        },
    ],
}

out_path = os.path.join(SCRIPT_DIR, 'k1379_results.json')
tmp_out_path = out_path + '.tmp'
with open(tmp_out_path, 'w') as f:
    json.dump(results, f, indent=2, ensure_ascii=False)
with open(tmp_out_path) as f:
    json.load(f)
os.replace(tmp_out_path, out_path)

print(f"\n[5] Results saved to {out_path}")
print(f"\nTotal elapsed: {elapsed:.1f}s")
print(f"\n{'='*50}")
print(f"C4 VERDICT: {results['paper9_c4_assessment']['verdict']}")
print('='*50)
