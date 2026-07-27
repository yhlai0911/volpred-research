#!/usr/bin/env python3
"""K1396 legacy daily-r-squared / steady-state-A4f diagnostic.

This program is retained only to explain the historical 2026-05-22 artifact.
It does **not** implement canonical HAR-RV: the target and HAR-style regressors
use close-to-close daily squared returns rather than intraday realized
variance.  Its A4f forecast resets ``g`` to its unconditional steady state on
every OOS date instead of carrying the canonical recursion forward.  The
custom raw-loss DM calculations are also legacy diagnostics, not equivalence
or non-inferiority tests.  K1379 supersedes the public K1396 interpretation.

Running this file writes ``k1396_legacy_rerun_results.json`` and never
overwrites the frozen ``k1396_results.json`` audit artifact.

Models (accurate historical labels):
  HAR-style daily-r²:     daily/weekly/monthly lagged r² NNLS — no VIX
  HAR-style daily-r²-VIX: preceding regressors + VIX²/252 NNLS
  A4f approximation:      blockwise fit, steady-state g on every OOS date

Legacy protocol (does not match K988 exactly):
  DATA_FILE: paper/garch-x-vix/data/spy_vix_qqq_eem_fez_2000-2026.csv
  DATA_START: 2005-01-01
  OOS_START:  2019-01-01
  WINDOW:     2000 (rolling IS)
  REFIT_EVERY: 63 days
  LOSS:       QLIKE (Patton 2011)
  REPORTING SCREEN: Harvey, Liu & Zhu (2016) |t| > 3.0

References:
  Corsi (2009). J Fin Econometrics 7(2):174-196. Canonical HAR-RV definition.
  Diebold & Mariano (1995). JBES 13(3):253-263.
  Harvey, Liu & Zhu (2016). Review of Financial Studies 29(1):5-68.
  Patton (2011). J Econometrics 160:246-256.

Author: VolPred Research System
Date:   2026-05-22
Seed:   42
"""

import os
import sys
import json
import time
import warnings
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from scipy import stats, optimize
from volpred.ops.diagnostics import warn

warnings.filterwarnings('ignore')
np.random.seed(42)

START_TIME = time.time()
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
DATA_FILE = os.path.join(PROJECT_ROOT, 'paper', 'garch-x-vix', 'data', 'spy_vix_qqq_eem_fez_2000-2026.csv')
RESULT_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    'k1396_legacy_rerun_results.json',
)

DATA_START = '2005-01-01'
OOS_START = '2019-01-01'
WINDOW = 2000
REFIT_EVERY = 63

print("=" * 70)
print("K1396 LEGACY DIAGNOSTIC — daily-r² HAR-style vs steady-state A4f approximation")
print("WARNING: superseded by K1379; no canonical HAR-RV or non-inferiority claim")
print("=" * 70)

# ============================================================
# 1. DATA LOADING (snapshot CSV, no live fetch)
# ============================================================
print("\n[1] Loading data from snapshot CSV...")
df_raw = pd.read_csv(DATA_FILE, index_col=0, parse_dates=True)
# snapshot-dup guard (audit_snapshot_dup_20260721): dedup on the date index + sort so
# duplicate trading days are not carried into the rolling OOS design (count audits miss
# this — stored n_oos=1900 vs clean 1890).
df_raw = df_raw[~df_raw.index.duplicated(keep="last")].sort_index()
df_raw = df_raw[df_raw.index >= DATA_START]
df_raw = df_raw.dropna(subset=['spy_adj_close', 'vix_close'])

prices = df_raw['spy_adj_close']
vix = df_raw['vix_close']
log_ret = np.log(prices / prices.shift(1))

df = pd.DataFrame({'log_ret': log_ret, 'VIX': vix}).dropna()
df = df[df.index >= DATA_START]

ret = df['log_ret'].values
vix_vals = df['VIX'].values
r2 = ret ** 2

oos_mask = np.array(df.index >= OOS_START)
oos_indices = np.where(oos_mask)[0]
n_total = len(df)

print(f"  Total obs: {n_total} | OOS start: {OOS_START} | OOS n: {oos_mask.sum()}")
print(f"  Date range: {df.index[0].date()} to {df.index[-1].date()}")

# ============================================================
# 2. QLIKE LOSS FUNCTION
# ============================================================

def qlike(forecast, actual):
    """QLIKE = actual/forecast - log(actual/forecast) - 1 (Patton 2011)"""
    ratio = actual / np.maximum(forecast, 1e-16)
    return ratio - np.log(np.maximum(ratio, 1e-16)) - 1.0


# ============================================================
# 3. HAR-STYLE DAILY-r² MODEL (NOT CANONICAL CORSI HAR-RV)
# ============================================================

def make_har_features(r2_vals, vix_sq=None):
    """
    Build daily/weekly/monthly features from lagged squared daily returns.
    Daily r² is a noisy volatility proxy, not intraday realized variance.
    Features are all lagged to avoid lookahead.
    """
    n = len(r2_vals)
    rv_d = r2_vals  # daily r² volatility proxy; not intraday RV
    rv_w = np.full(n, np.nan)
    rv_m = np.full(n, np.nan)
    for t in range(4, n):
        rv_w[t] = np.mean(r2_vals[t-4:t+1])  # 5-day window ending at t
    for t in range(21, n):
        rv_m[t] = np.mean(r2_vals[t-21:t+1])  # 22-day window ending at t

    if vix_sq is not None:
        data = {'const': np.ones(n), 'rv_d': rv_d, 'rv_w': rv_w, 'rv_m': rv_m, 'vix_sq': vix_sq}
    else:
        data = {'const': np.ones(n), 'rv_d': rv_d, 'rv_w': rv_w, 'rv_m': rv_m}
    return data


def fit_har(X, y):
    """Fit coefficients by non-negative least squares (NNLS)."""
    from scipy.optimize import nnls
    coef, _ = nnls(X, y)
    return coef


def har_forecast_1step(coef, rv_d_t, rv_w_t, rv_m_t, vix_sq_t=None):
    """1-step-ahead HAR forecast."""
    x = [1.0, rv_d_t, rv_w_t, rv_m_t]
    if vix_sq_t is not None:
        x.append(vix_sq_t)
    return max(np.dot(coef, x), 1e-10)


# ============================================================
# 4. A4f FIT + UNUSED CANONICAL-LIKE RECURSION HELPER
# ============================================================

def fit_mfgjr_a4f(returns, vix_vals_is):
    """Fit A4f: VIX^2, tau_t denominator, free omega."""
    n = len(returns)
    vix_lag = np.empty(n)
    vix_lag[0] = vix_vals_is[0]
    vix_lag[1:] = vix_vals_is[:-1]

    var0 = np.var(returns)
    vm = np.mean(vix_lag**2) + 1e-8

    def neg_loglik(params):
        th0, th1, omg, alp, gam, bet = params
        if omg <= 0: return 1e10
        if alp < 0 or gam < 0 or bet < 0: return 1e10
        persist = alp + gam/2.0 + bet
        if persist >= 1.0: return 1e10

        tau = np.maximum(th0 + th1 * vix_lag**2, 1e-16)
        eg = omg / (1.0 - persist)
        g = np.empty(n)
        g[0] = eg

        ll = 0.0
        for t in range(1, n):
            u_prev = returns[t-1] / np.sqrt(tau[t])
            asym = gam * u_prev**2 if u_prev < 0 else 0.0
            g[t] = omg + alp * u_prev**2 + asym + bet * g[t-1]
            if g[t] < 1e-10: g[t] = 1e-10

        for t in range(n):
            sigma2 = tau[t] * g[t]
            if sigma2 > 0:
                ll += -0.5 * (np.log(2 * np.pi) + np.log(sigma2) + returns[t]**2 / sigma2)
        return -ll

    starts = [
        [var0 * 0.1, var0 / vm, 0.05, 0.05, 0.05, 0.90],
        [var0 * 0.05, var0 / vm * 0.5, 0.10, 0.03, 0.08, 0.88],
        [var0 * 0.2, var0 / vm * 1.5, 0.02, 0.08, 0.10, 0.80],
    ]
    bounds = [
        (1e-8, var0), (1e-6, 1.0),
        (1e-8, 0.5), (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)
    ]

    best_ll, best_p = np.inf, None
    for s in starts:
        try:
            res = optimize.minimize(neg_loglik, s, method='L-BFGS-B', bounds=bounds,
                                    options={'maxiter': 1000})
            if res.fun < best_ll:
                best_ll, best_p = res.fun, res.x
        except Exception as exc:
            warn(
                "k1396",
                "legacy A4f optimization start failed",
                start=s,
                err=str(exc),
            )
    return best_p


def a4f_oos_forecast(params, ret_is, vix_is, ret_oos, vix_oos):
    """
    Generate A4f 1-step OOS forecasts using fitted params.
    Appends OOS one step at a time; g recursion continues from IS end.
    """
    th0, th1, omg, alp, gam, bet = params
    n_is = len(ret_is)

    # Run IS recursion to get terminal g_T
    vix_lag_is = np.empty(n_is)
    vix_lag_is[0] = vix_is[0]
    vix_lag_is[1:] = vix_is[:-1]

    tau_is = np.maximum(th0 + th1 * vix_lag_is**2, 1e-16)
    persist = alp + gam / 2.0 + bet
    eg = omg / (1.0 - persist)
    g_prev = eg
    for t in range(1, n_is):
        u = ret_is[t-1] / np.sqrt(tau_is[t])
        asym = gam * u**2 if u < 0 else 0.0
        g_prev = max(omg + alp * u**2 + asym + bet * g_prev, 1e-10)

    # OOS 1-step-ahead forecasts
    n_oos = len(ret_oos)
    forecasts = np.empty(n_oos)
    ret_full = np.concatenate([ret_is, ret_oos])
    vix_full = np.concatenate([vix_is, vix_oos])

    g_t = g_prev
    for t in range(n_oos):
        t_abs = n_is + t
        vix_lag = vix_full[t_abs - 1]
        tau_next = max(th0 + th1 * vix_lag**2, 1e-16)
        forecasts[t] = tau_next * g_t

        # Update g using current return (for next step)
        if t < n_oos - 1:
            vix_tau_curr = max(th0 + th1 * vix_lag**2, 1e-16)
            u = ret_full[t_abs - 1] / np.sqrt(vix_tau_curr)
            asym = gam * u**2 if u < 0 else 0.0
            g_t = max(omg + alp * u**2 + asym + bet * g_t, 1e-10)

    return forecasts


# ============================================================
# 5. ROLLING OOS — HAR, HAR-VIX, A4f
# ============================================================
print("\n[2] Rolling OOS evaluation...")

n_oos = oos_mask.sum()
har_forecasts = np.empty(n_oos)
harvix_forecasts = np.empty(n_oos)
a4f_forecasts = np.empty(n_oos)
actual_r2 = r2[oos_indices]

# VIX squared (variance units, /252 to get daily)
vix_sq = (vix_vals / 100.0)**2 / 252.0  # VIX in percent, convert to decimal and daily

refit_times = []
last_refit = -REFIT_EVERY

for j, t in enumerate(oos_indices):
    is_start = t - WINDOW
    is_end = t  # predict t using IS=[is_start, t-1]
    ret_is = ret[is_start:is_end]
    vix_is = vix_vals[is_start:is_end]
    r2_is = r2[is_start:is_end]
    vix_sq_is = vix_sq[is_start:is_end]

    need_refit = (j - last_refit >= REFIT_EVERY) or (j == 0)

    if need_refit:
        # ---- HAR features (lagged, no lookahead) ----
        feat_data = make_har_features(r2_is, vix_sq=vix_sq_is)
        valid = ~(np.isnan(feat_data['rv_d']) | np.isnan(feat_data['rv_w']) | np.isnan(feat_data['rv_m']))
        X_har = np.column_stack([feat_data['const'][valid], feat_data['rv_d'][valid],
                                  feat_data['rv_w'][valid], feat_data['rv_m'][valid]])
        X_harvix = np.column_stack([feat_data['const'][valid], feat_data['rv_d'][valid],
                                     feat_data['rv_w'][valid], feat_data['rv_m'][valid],
                                     feat_data['vix_sq'][valid]])
        # HAR target = next-day r² (t+1 = r²_{is+1}), but we train to predict contemporaneous
        # Correct HAR: predict r²_t using lagged RVs from day t-1
        # In IS, y[t] = r²[t], X[t] uses rv_{t-1}, rv_w_{t-1}, rv_m_{t-1}
        # So shift features by 1 to predict next
        y_is = r2_is[valid]
        X_har_fit = X_har[:-1] if len(X_har) > 1 else X_har
        y_har_fit = y_is[1:] if len(y_is) > 1 else y_is
        X_harvix_fit = X_harvix[:-1] if len(X_harvix) > 1 else X_harvix

        coef_har = fit_har(X_har_fit, y_har_fit)
        coef_harvix = fit_har(X_harvix_fit, y_har_fit)

        # ---- A4f ----
        t0 = time.time()
        a4f_params = fit_mfgjr_a4f(ret_is, vix_is)
        refit_times.append(time.time() - t0)

        last_refit = j
        if j % 63 == 0:
            print(f"  Refit at OOS[{j}/{n_oos}] t={t}, "
                  f"A4f fit time={refit_times[-1]:.1f}s, "
                  f"elapsed={time.time()-START_TIME:.0f}s")

    # ---- HAR 1-step forecast ----
    rv_d_t = r2[t - 1]  # lagged daily
    rv_w_t = np.mean(r2[t-5:t]) if t >= 5 else rv_d_t
    rv_m_t = np.mean(r2[t-22:t]) if t >= 22 else rv_w_t
    vix_sq_t = vix_sq[t - 1]

    har_forecasts[j] = har_forecast_1step(coef_har, rv_d_t, rv_w_t, rv_m_t)
    harvix_forecasts[j] = har_forecast_1step(coef_harvix, rv_d_t, rv_w_t, rv_m_t, vix_sq_t)

    # ---- A4f 1-step forecast ----
    if a4f_params is not None:
        th0, th1, omg, alp, gam, bet = a4f_params
        vix_lag_t = vix_vals[t - 1]
        tau_t = max(th0 + th1 * vix_lag_t**2, 1e-16)
        a4f_forecasts[j] = tau_t * max(omg / (1.0 - alp - gam/2.0 - bet), 1e-10)
        # Legacy approximation: every OOS date resets g to its unconditional
        # steady state. This is not limited to refit boundaries and is not the
        # canonical K988 recursion, which carries the short-run state forward.
    else:
        raise RuntimeError(
            "all legacy A4f optimization starts failed; refusing a proxy fallback"
        )

print(f"  OOS complete. Mean refit time: {np.mean(refit_times):.1f}s ({len(refit_times)} refits)")

# ============================================================
# 6. LEGACY RAW-LOSS DM DIAGNOSTICS + |t|>3 REPORTING SCREEN
# ============================================================
print("\n[3] Computing DM tests...")


def legacy_dm_hac_screen(loss1, loss2, n):
    """Historical custom HAC-DM diagnostic; no HLN small-sample correction."""
    d = loss1 - loss2  # positive = loss1 > loss2 (loss2 is better)
    mean_d = np.mean(d)
    # HAC variance (Newey-West with lags=min(n^(1/3), 12))
    lags = min(int(n ** (1/3)), 12)
    gamma0 = np.var(d)
    acov = sum(
        (1 - l / (lags + 1)) * np.cov(d[l:], d[:-l])[0, 1]
        for l in range(1, lags + 1)
    )
    var_d = (gamma0 + 2 * acov) / n
    if var_d <= 0:
        var_d = gamma0 / n
    t_stat = mean_d / np.sqrt(var_d)
    p_val = 2 * stats.t.sf(abs(t_stat), df=n - 1)
    screen_pass = abs(t_stat) > 3.0
    return float(t_stat), float(p_val), bool(screen_pass)


har_loss = qlike(har_forecasts, actual_r2)
harvix_loss = qlike(harvix_forecasts, actual_r2)
a4f_loss = qlike(a4f_forecasts, actual_r2)
n = len(actual_r2)

# HAR vs A4f (positive t = A4f has lower loss = A4f better)
dm_har_vs_a4f = legacy_dm_hac_screen(har_loss, a4f_loss, n)
# HAR-VIX vs A4f
dm_harvix_vs_a4f = legacy_dm_hac_screen(harvix_loss, a4f_loss, n)
# HAR-VIX vs HAR
dm_harvix_vs_har = legacy_dm_hac_screen(harvix_loss, har_loss, n)

print(f"  Mean QLIKE — HAR: {np.mean(har_loss):.6f} | HAR-VIX: {np.mean(harvix_loss):.6f} | A4f: {np.mean(a4f_loss):.6f}")
print(f"  legacy DM(daily-r² HAR vs A4f approx): t={dm_har_vs_a4f[0]:.3f}  p={dm_har_vs_a4f[1]:.4f}  |t|>3={dm_har_vs_a4f[2]}")
print(f"  legacy DM(daily-r²-VIX HAR vs A4f approx): t={dm_harvix_vs_a4f[0]:.3f}  p={dm_harvix_vs_a4f[1]:.4f}  |t|>3={dm_harvix_vs_a4f[2]}")
print(f"  nested raw-loss diagnostic(daily-r²-VIX vs daily-r²): t={dm_harvix_vs_har[0]:.3f}  p={dm_harvix_vs_har[1]:.4f}  |t|>3={dm_harvix_vs_har[2]}")

# ============================================================
# 7. SAVE RESULTS
# ============================================================
elapsed = time.time() - START_TIME
results = {
    "experiment_id": "K1396",
    "run_at": datetime.now(timezone.utc).isoformat(),
    "elapsed_seconds": round(elapsed, 1),
    "configuration": {
        "data_file": "paper/garch-x-vix/data/spy_vix_qqq_eem_fez_2000-2026.csv",
        "data_start": DATA_START,
        "oos_start": OOS_START,
        "window": WINDOW,
        "refit_every": REFIT_EVERY,
        "loss": "QLIKE_Patton2011",
        "seed": 42
    },
    "sample_sizes": {
        "n_oos": int(n),
        "n_refits": len(refit_times)
    },
    "mean_qlike": {
        "HAR": float(np.mean(har_loss)),
        "HAR_VIX": float(np.mean(harvix_loss)),
        "A4f": float(np.mean(a4f_loss))
    },
    "dm_tests": {
        "HAR_vs_A4f": {
            "t_stat": dm_har_vs_a4f[0],
            "p_value": dm_har_vs_a4f[1],
            "legacy_abs_t_gt_3_screen": dm_har_vs_a4f[2],
            "interpretation": "historical diagnostic; positive t = approximation has lower QLIKE"
        },
        "HAR_VIX_vs_A4f": {
            "t_stat": dm_harvix_vs_a4f[0],
            "p_value": dm_harvix_vs_a4f[1],
            "legacy_abs_t_gt_3_screen": dm_harvix_vs_a4f[2],
            "interpretation": "historical diagnostic; positive t = approximation has lower QLIKE"
        },
        "HAR_VIX_vs_HAR": {
            "t_stat": dm_harvix_vs_har[0],
            "p_value": dm_harvix_vs_har[1],
            "legacy_abs_t_gt_3_screen": dm_harvix_vs_har[2],
            "interpretation": "nested raw-loss diagnostic only; positive t = daily-r² HAR has lower QLIKE"
        }
    },
    "notes": [
        "SUPERSEDED historical diagnostic; public interpretation withdrawn by K1379",
        "HAR-style regressions use daily r², not canonical intraday realized variance",
        "A4f approximation uses steady-state g on every OOS date, not only at refits",
        "Failure to reject equal predictive accuracy is not non-inferiority or equivalence",
        "HAR-style daily-r²-VIX vs HAR-style daily-r² is nested; raw QLIKE DM is diagnostic only",
        "Features are lagged and pass the lookahead audit"
    ]
}

tmp_result = RESULT_FILE + ".tmp"
with open(tmp_result, 'w') as f:
    json.dump(results, f, indent=2)
    f.write("\n")
os.replace(tmp_result, RESULT_FILE)

print(f"\n[4] Results saved: {RESULT_FILE}")
print(f"    Total elapsed: {elapsed:.0f}s")
print("\nDone.")
