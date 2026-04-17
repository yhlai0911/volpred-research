#!/usr/bin/env python3
"""
K475: Simple Ensemble of Validated Methods
==========================================
Background:
  K434: BMA failed (BIC weights degenerate to 99.8% single model)
  K450/K466: Complex combinations failed (curse of dimensionality)
  But those tried to combine ALL methods or unvalidated methods.

New idea:
  Only combine methods that PASSED cross-OOS validation:
    1. GJR-GARCH(1,1) — best VaR (K454/K467), validated baseline
    2. HAR log-range — best vol forecasting 8/10 cross-OOS (K469 with r² proxy)
    3. Semivariance RS⁻ — equity-specific advantage 4/5 (K460)

  Use simplest possible combination: EQUAL WEIGHT average of σ² forecasts.
  σ²_ensemble = (σ²_GJR + σ²_HAR + σ²_semi) / N

Literature:
  Timmermann (2006) "Forecast Combinations" Handbook of Economic Forecasting
    — Equal weight often beats optimal weight (forecast combination puzzle)
  K434: BIC-based BMA weight degenerates to single model

Hypothesis:
  K467: HAR best forecasting but worst VaR. GJR best VaR but not best forecasting.
  Can ensemble "get the best of both worlds" — good at both tasks?

Design:
  Asset: SPY
  5 OOS periods (same as K460/K465/K469):
    1. 2015-2016 (low vol)
    2. 2017-2018 (Volmageddon)
    3. 2019-2020 (COVID)
    4. 2021-2022 (rate hikes)
    5. 2023-2025 (post-COVID)

  Ensembles:
    - 3-model: (GJR + HAR + Semi) / 3
    - 2-model: GJR+HAR, GJR+Semi, HAR+Semi (each /2)

  Evaluation:
    - QLIKE with r² proxy (K469 standard, avoids Parkinson tautology)
    - QLIKE with Parkinson proxy (for comparison)
    - DM test: ensemble vs best single model
    - VaR Trinity test at 1%/5% (last 2 periods: 2021-2024)

Data: yfinance (SPY), 2005-01-01 to present
Refs: Timmermann (2006), Corsi (2009), Patton & Sheppard (2015), K434/K460/K465/K467/K469
Author: [Proposed: User, Executed: Claude]
"""

import json
import warnings
import time
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timezone
from scipy import stats
from arch import arch_model
from statsmodels.tsa.stattools import adfuller
from statsmodels.stats.diagnostic import het_arch, acorr_ljungbox

warnings.filterwarnings('ignore')

print("=" * 70)
print("K475: Simple Ensemble of Validated Methods")
print("  Equal-weight combination of GJR + HAR + Semivariance")
print("  Hypothesis: ensemble gets best of both worlds (forecasting + VaR)")
print("=" * 70)

# ============================================================
# Configuration
# ============================================================
IS_WINDOW = 2000
OOS_PERIODS = [
    {"name": "2015-2016 (low vol)", "start": "2015-01-01", "end": "2016-12-31"},
    {"name": "2017-2018 (Volmageddon)", "start": "2017-01-01", "end": "2018-12-31"},
    {"name": "2019-2020 (COVID)", "start": "2019-01-01", "end": "2020-12-31"},
    {"name": "2021-2022 (rate hikes)", "start": "2021-01-01", "end": "2022-12-31"},
    {"name": "2023-2025 (post-COVID)", "start": "2023-01-01", "end": "2025-12-31"},
]

# Models: each produces a σ² forecast (in % squared)
SINGLE_MODELS = ['GJR', 'HAR', 'Semi']
ENSEMBLE_MODELS = {
    'Ens_3way': ['GJR', 'HAR', 'Semi'],
    'Ens_GJR_HAR': ['GJR', 'HAR'],
    'Ens_GJR_Semi': ['GJR', 'Semi'],
    'Ens_HAR_Semi': ['HAR', 'Semi'],
}
ALL_MODELS = SINGLE_MODELS + list(ENSEMBLE_MODELS.keys())

# ============================================================
# 1. DATA DOWNLOAD
# ============================================================
print("\n[1] Downloading OHLC data for SPY...")
raw = yf.download('SPY', start='2005-01-01', progress=False)
if isinstance(raw.columns, pd.MultiIndex):
    raw.columns = raw.columns.get_level_values(0)
print(f"  SPY: {raw.index[0].date()} to {raw.index[-1].date()} ({len(raw)} obs)")

# ============================================================
# 2. FEATURE COMPUTATION
# ============================================================
print("\n[2] Computing features...")

high = raw['High'].values.astype(float).ravel()
low = raw['Low'].values.astype(float).ravel()
close = raw['Close'].values.astype(float).ravel()

# Log returns in %
ret_pct = np.log(close[1:] / close[:-1]) * 100

# Log range (decimal)
ratio = high[1:] / low[1:]
ratio = np.maximum(ratio, 1.0001)
log_range = np.log(ratio)

# Build features DataFrame
idx = raw.index[1:]
feat = pd.DataFrame({
    'return_pct': ret_pct,
    'log_range': log_range,
}, index=idx)

# Parkinson variance (daily, in decimal²)
feat['parkinson_var'] = log_range**2 / (4 * np.log(2))

# r² proxy (daily, in decimal²) — K469 standard
feat['r2_proxy'] = (np.log(close[1:] / close[:-1]))**2

# HAR components: 5d and 21d rolling averages of log_range
feat['log_range_5d'] = feat['log_range'].rolling(5).mean()
feat['log_range_21d'] = feat['log_range'].rolling(21).mean()

# Semivariance components
# Negative returns only
neg_ret = np.where(ret_pct < 0, ret_pct, 0)
pos_ret = np.where(ret_pct > 0, ret_pct, 0)
feat['neg_ret_sq'] = neg_ret**2
feat['pos_ret_sq'] = pos_ret**2

# Rolling semivariance (21-day and 5-day)
feat['rs_neg_21'] = feat['neg_ret_sq'].rolling(21).mean()
feat['rs_neg_5'] = feat['neg_ret_sq'].rolling(5).mean()
feat['rs_pos_21'] = feat['pos_ret_sq'].rolling(21).mean()
feat['rs_pos_5'] = feat['pos_ret_sq'].rolling(5).mean()

# Rolling realized variance (21-day)
feat['rv_21'] = (feat['return_pct']**2).rolling(21).mean()

feat = feat.dropna()
print(f"  Features: {len(feat)} obs ({feat.index[0].date()} to {feat.index[-1].date()})")

# ============================================================
# 3. DIAGNOSTICS (CLAUDE.md rule 5)
# ============================================================
print("\n[3] Data diagnostics...")
ret = feat['return_pct'].values
lr = feat['log_range'].values
r2 = feat['r2_proxy'].values
pk = feat['parkinson_var'].values

adf_stat, adf_p, _, _, _, _ = adfuller(ret, maxlag=21)
arch_stat, arch_p, _, _ = het_arch(ret, nlags=10)
lb = acorr_ljungbox(ret**2, lags=[10], return_df=True)

diagnostics = {
    'n_obs': len(feat),
    'date_range': f"{feat.index[0].date()} to {feat.index[-1].date()}",
    'return_mean_pct': float(np.mean(ret)),
    'return_std_pct': float(np.std(ret)),
    'return_skew': float(stats.skew(ret)),
    'return_kurt': float(stats.kurtosis(ret)),
    'log_range_mean': float(np.mean(lr)),
    'log_range_std': float(np.std(lr)),
    'r2_proxy_mean': float(np.mean(r2)),
    'parkinson_var_mean': float(np.mean(pk)),
    'r2_over_parkinson_ratio': float(np.mean(r2) / np.mean(pk)),
    'adf_stat': float(adf_stat),
    'adf_p': float(adf_p),
    'is_stationary': bool(adf_p < 0.05),
    'arch_lm_stat': float(arch_stat),
    'arch_lm_p': float(arch_p),
    'has_arch_effects': bool(arch_p < 0.05),
    'ljung_box_sq_p10': float(lb['lb_pvalue'].values[0]),
    'neg_return_fraction': float(np.mean(ret < 0)),
}

print(f"  n={diagnostics['n_obs']}, ADF p={adf_p:.2e} ({'stationary' if adf_p < 0.05 else 'NON-STATIONARY'})")
print(f"  ARCH-LM p={arch_p:.2e} ({'YES' if arch_p < 0.05 else 'NO'})")
print(f"  r²/Parkinson ratio: {diagnostics['r2_over_parkinson_ratio']:.3f}")
print(f"  Neg return fraction: {diagnostics['neg_return_fraction']:.3f}")


# ============================================================
# 4. MODEL FORECAST FUNCTIONS
# ============================================================

def gjr_garch_forecast(returns_pct):
    """
    GJR-GARCH(1,1) with Student-t, 1-step forecast.
    Returns σ² in %² units.
    """
    try:
        am = arch_model(returns_pct, vol='GARCH', p=1, o=1, q=1, dist='t', mean='Constant')
        res = am.fit(disp='off', show_warning=False)
        fc = res.forecast(horizon=1)
        sigma2 = float(fc.variance.values[-1, 0])
        return sigma2, res
    except Exception:
        return np.nan, None


def har_log_range_forecast(feat_window):
    """
    HAR log-range model: y_{t+1} = b0 + b1*y_t + b2*y_{5d,t} + b3*y_{21d,t}
    Returns σ² forecast in %² units (via Parkinson → scale to r²).
    Also returns Parkinson-scale σ² for separate evaluation.
    """
    cols = ['log_range', 'log_range_5d', 'log_range_21d']
    data = feat_window[cols].dropna()
    if len(data) < 50:
        return np.nan, np.nan

    Y = data['log_range'].values[1:]
    X_mat = data[cols].values[:-1]
    X_mat = np.column_stack([np.ones(len(Y)), X_mat])

    try:
        beta = np.linalg.lstsq(X_mat, Y, rcond=None)[0]
    except Exception:
        return np.nan, np.nan

    x_last = data[cols].values[-1]
    fc_log_range = beta[0] + beta[1:] @ x_last
    fc_log_range = max(fc_log_range, 1e-6)

    # Parkinson variance in decimal²
    parkinson_var_decimal = fc_log_range**2 / (4 * np.log(2))

    # Convert to %²: multiply by (100)² = 10000
    parkinson_var_pct2 = parkinson_var_decimal * 10000

    return parkinson_var_pct2, parkinson_var_decimal


def semi_forecast(feat_window):
    """
    Semivariance RS⁻ model: HAR-style with RS⁻ components.
    next-day σ² ~ const + RS⁻_5 + RS⁻_21 + RS⁺_5 + RS⁺_21
    Returns σ² forecast in %² units.
    """
    cols = ['rs_neg_5', 'rs_neg_21', 'rs_pos_5', 'rs_pos_21']
    data = feat_window[cols + ['return_pct']].dropna()
    if len(data) < 50:
        return np.nan

    # Target: next-day r²
    Y = data['return_pct'].values[1:]**2
    X_mat = data[cols].values[:-1]
    X_mat = np.column_stack([np.ones(len(Y)), X_mat])

    try:
        beta = np.linalg.lstsq(X_mat, Y, rcond=None)[0]
    except Exception:
        return np.nan

    x_last = data[cols].values[-1]
    fc = beta[0] + beta[1:] @ x_last
    fc = max(fc, 1e-6)

    return fc  # Already in %² units


# ============================================================
# 5. DM TEST
# ============================================================

def dm_test(losses1, losses2, h=1):
    """
    Diebold-Mariano test with HAC variance.
    H0: equal predictive accuracy.
    Returns t-stat and p-value. Negative t → model 1 better.
    """
    d = losses1 - losses2
    n = len(d)
    d_bar = np.mean(d)

    # HAC variance (Bartlett kernel)
    max_lag = max(1, int(np.ceil(n ** (1/3))))
    gamma = np.zeros(max_lag + 1)
    for k in range(max_lag + 1):
        gamma[k] = np.mean((d[:n-k] - d_bar) * (d[k:] - d_bar))

    var_d = gamma[0]
    for k in range(1, max_lag + 1):
        w = 1 - k / (max_lag + 1)
        var_d += 2 * w * gamma[k]

    if var_d <= 0:
        return 0.0, 1.0

    dm_stat = d_bar / np.sqrt(var_d / n)
    pval = 2 * (1 - stats.norm.cdf(abs(dm_stat)))

    return float(dm_stat), float(pval)


# ============================================================
# 6. QLIKE LOSS
# ============================================================

def qlike_loss(sigma2_forecast, realized_var):
    """QLIKE = realized/forecast + log(forecast). Lower is better."""
    # Filter out invalid entries
    valid = (sigma2_forecast > 0) & (realized_var > 0) & np.isfinite(sigma2_forecast) & np.isfinite(realized_var)
    s2f = sigma2_forecast[valid]
    rv = realized_var[valid]
    ql = rv / s2f + np.log(s2f)
    return ql  # Return individual losses for DM test


# ============================================================
# 7. TRINITY TEST FUNCTIONS
# ============================================================

def kupiec_test(violations, n_total, alpha):
    n_viol = int(np.sum(violations))
    p_hat = n_viol / n_total if n_total > 0 else 0
    if p_hat == 0 or p_hat == 1:
        return 0.0, 1.0
    lr = -2 * (n_viol * np.log(alpha / p_hat) +
               (n_total - n_viol) * np.log((1 - alpha) / (1 - p_hat)))
    pval = 1 - stats.chi2.cdf(lr, df=1)
    return float(lr), float(pval)


def christoffersen_test(violations):
    n = len(violations)
    n00 = n01 = n10 = n11 = 0
    for i in range(1, n):
        if violations[i - 1] == 0 and violations[i] == 0:
            n00 += 1
        elif violations[i - 1] == 0 and violations[i] == 1:
            n01 += 1
        elif violations[i - 1] == 1 and violations[i] == 0:
            n10 += 1
        else:
            n11 += 1
    if (n00 + n01) == 0 or (n10 + n11) == 0:
        return 0.0, 1.0
    p01 = n01 / (n00 + n01)
    p11 = n11 / (n10 + n11) if (n10 + n11) > 0 else 0
    p = (n01 + n11) / n
    if p == 0 or p == 1 or p01 == 0 or p01 == 1 or p11 == 0 or p11 == 1:
        return 0.0, 1.0
    lr_ind = -2 * (
        (n00 + n10) * np.log(1 - p) + (n01 + n11) * np.log(p)
        - n00 * np.log(1 - p01) - n01 * np.log(p01)
        - n10 * np.log(1 - p11) - n11 * np.log(p11)
    )
    pval = 1 - stats.chi2.cdf(lr_ind, df=1)
    return float(lr_ind), float(pval)


def dq_test(violations, var_forecasts, actual_returns, n_lags=4):
    T = len(violations)
    if T <= n_lags + 2:
        return 0.0, 1.0
    hits = violations.astype(float) - np.mean(violations)
    X = np.ones((T - n_lags, 1))
    for lag in range(1, n_lags + 1):
        X = np.column_stack([X, hits[n_lags - lag:T - lag]])
    X = np.column_stack([X, var_forecasts[n_lags:]])
    y = hits[n_lags:]
    try:
        XtX = X.T @ X
        XtX_inv = np.linalg.inv(XtX + 1e-10 * np.eye(XtX.shape[0]))
        beta = XtX_inv @ X.T @ y
        dq_stat = float(beta.T @ X.T @ X @ beta)
        pval = 1 - stats.chi2.cdf(dq_stat, df=X.shape[1])
        return float(dq_stat), float(pval)
    except np.linalg.LinAlgError:
        return 0.0, 1.0


def run_trinity(violations, var_fcasts, actuals, alpha):
    n = len(violations)
    n_viol = int(np.sum(violations))
    viol_rate = n_viol / n if n > 0 else 0
    kup_stat, kup_p = kupiec_test(violations, n, alpha)
    chr_stat, chr_p = christoffersen_test(violations)
    dq_stat, dq_p = dq_test(violations, var_fcasts, actuals)
    trinity_pass = bool(kup_p > 0.05 and chr_p > 0.05 and dq_p > 0.05)
    tests_passed = sum([kup_p > 0.05, chr_p > 0.05, dq_p > 0.05])
    return {
        'n_obs': n,
        'n_violations': n_viol,
        'violation_rate': round(viol_rate, 4),
        'expected_rate': alpha,
        'kupiec': {'stat': round(kup_stat, 4), 'p_value': round(float(kup_p), 4)},
        'christoffersen': {'stat': round(chr_stat, 4), 'p_value': round(float(chr_p), 4)},
        'dq': {'stat': round(dq_stat, 4), 'p_value': round(float(dq_p), 4)},
        'trinity_pass': trinity_pass,
        'tests_passed': tests_passed,
    }


# ============================================================
# 8. MAIN CROSS-OOS LOOP
# ============================================================
print("\n" + "=" * 70)
print("[4] Cross-OOS Evaluation (5 periods × 7 models)")
print("=" * 70)

t_start = time.time()
period_results = []

for p_idx, period in enumerate(OOS_PERIODS):
    p_name = period['name']
    print(f"\n{'─'*60}")
    print(f"  Period {p_idx+1}/5: {p_name}")
    print(f"{'─'*60}")

    oos_mask = (feat.index >= period['start']) & (feat.index <= period['end'])
    oos_dates = feat.index[oos_mask]

    if len(oos_dates) == 0:
        print(f"  SKIP: no OOS data")
        continue

    # Need IS_WINDOW before first OOS date
    first_oos_loc = feat.index.get_loc(oos_dates[0])
    if first_oos_loc < IS_WINDOW:
        print(f"  SKIP: insufficient IS data ({first_oos_loc} < {IS_WINDOW})")
        continue

    n_oos = len(oos_dates)
    is_start_date = feat.index[first_oos_loc - IS_WINDOW]

    print(f"  IS: {is_start_date.date()} ({IS_WINDOW} obs)")
    print(f"  OOS: {oos_dates[0].date()} to {oos_dates[-1].date()} ({n_oos} obs)")

    # Storage for forecasts (σ² in %²)
    forecasts = {m: np.full(n_oos, np.nan) for m in ALL_MODELS}
    # Realized values for evaluation
    realized_r2 = np.full(n_oos, np.nan)        # r² proxy (in %²)
    realized_parkinson = np.full(n_oos, np.nan)  # Parkinson proxy (in %²)
    actual_returns = np.full(n_oos, np.nan)      # returns in %

    # Scale calibration: compute IS mean ratio for HAR scaling (K469 approach)
    is_data = feat.iloc[first_oos_loc - IS_WINDOW:first_oos_loc]
    is_r2_mean = is_data['r2_proxy'].mean() * 10000     # to %²
    is_pk_mean = is_data['parkinson_var'].mean() * 10000  # to %²
    scale_ratio = is_r2_mean / is_pk_mean if is_pk_mean > 0 else 1.0
    print(f"  IS scale ratio (r²/Parkinson): {scale_ratio:.3f}")

    # Rolling forecasts
    for i, oos_date in enumerate(oos_dates):
        oos_loc = feat.index.get_loc(oos_date)

        # Window for estimation
        window_start = oos_loc - IS_WINDOW
        window_data = feat.iloc[window_start:oos_loc]

        # Realized values at oos_date
        realized_r2[i] = feat.iloc[oos_loc]['r2_proxy'] * 10000       # decimal² → %²
        realized_parkinson[i] = feat.iloc[oos_loc]['parkinson_var'] * 10000  # decimal² → %²
        actual_returns[i] = feat.iloc[oos_loc]['return_pct']

        # --- GJR-GARCH ---
        ret_window = window_data['return_pct'].values
        gjr_sigma2, _ = gjr_garch_forecast(ret_window)
        forecasts['GJR'][i] = gjr_sigma2  # Already in %²

        # --- HAR log-range ---
        har_sigma2_pk, _ = har_log_range_forecast(window_data)
        forecasts['HAR'][i] = har_sigma2_pk  # Parkinson scale in %²

        # --- Semivariance ---
        semi_sigma2 = semi_forecast(window_data)
        forecasts['Semi'][i] = semi_sigma2  # Already in %²

        if (i + 1) % 100 == 0:
            elapsed = time.time() - t_start
            print(f"    {i+1}/{n_oos} forecasts done ({elapsed:.1f}s)")

    # Compute ensemble forecasts
    for ens_name, components in ENSEMBLE_MODELS.items():
        comp_forecasts = np.array([forecasts[c] for c in components])
        forecasts[ens_name] = np.nanmean(comp_forecasts, axis=0)

    # --- Scale HAR forecasts to r² level for r²-proxy evaluation ---
    # HAR forecasts are in Parkinson %² scale; multiply by scale_ratio for r² comparison
    har_scaled_r2 = forecasts['HAR'] * scale_ratio

    # Ensemble with scaled HAR for r² evaluation
    ens_scaled = {
        'Ens_3way': (forecasts['GJR'] + har_scaled_r2 + forecasts['Semi']) / 3,
        'Ens_GJR_HAR': (forecasts['GJR'] + har_scaled_r2) / 2,
        'Ens_GJR_Semi': (forecasts['GJR'] + forecasts['Semi']) / 2,
        'Ens_HAR_Semi': (har_scaled_r2 + forecasts['Semi']) / 2,
    }

    # ---- QLIKE evaluation ----
    # r² proxy evaluation (K469 standard)
    qlike_r2 = {}
    qlike_r2_losses = {}

    # Single models (for r² proxy, scale HAR)
    for m in SINGLE_MODELS:
        if m == 'HAR':
            fc = har_scaled_r2
        else:
            fc = forecasts[m]
        losses = qlike_loss(fc, realized_r2)
        qlike_r2[m] = float(np.mean(losses))
        qlike_r2_losses[m] = losses

    # Ensembles (already scaled)
    for ens_name in ENSEMBLE_MODELS:
        fc = ens_scaled[ens_name]
        losses = qlike_loss(fc, realized_r2)
        qlike_r2[ens_name] = float(np.mean(losses))
        qlike_r2_losses[ens_name] = losses

    # Parkinson proxy evaluation
    qlike_pk = {}
    qlike_pk_losses = {}
    for m in ALL_MODELS:
        fc = forecasts[m]  # Parkinson scale (no scaling needed)
        losses = qlike_loss(fc, realized_parkinson)
        qlike_pk[m] = float(np.mean(losses))
        qlike_pk_losses[m] = losses

    # ---- DM tests: each ensemble vs best single ----
    # Find best single model (r² proxy)
    best_single_r2 = min(SINGLE_MODELS, key=lambda m: qlike_r2[m])
    # Find best single model (Parkinson)
    best_single_pk = min(SINGLE_MODELS, key=lambda m: qlike_pk[m])

    dm_results = {}
    for ens_name in ENSEMBLE_MODELS:
        # r² proxy: ensemble vs best single
        dm_stat_r2, dm_p_r2 = dm_test(qlike_r2_losses[ens_name], qlike_r2_losses[best_single_r2])
        # Parkinson: ensemble vs best single
        dm_stat_pk, dm_p_pk = dm_test(qlike_pk_losses[ens_name], qlike_pk_losses[best_single_pk])

        dm_results[ens_name] = {
            'vs_best_single_r2': {
                'best_single': best_single_r2,
                'dm_stat': round(dm_stat_r2, 4),
                'p_value': round(dm_p_r2, 4),
                'ensemble_better': dm_stat_r2 < 0,
                'significant_005': dm_p_r2 < 0.05,
            },
            'vs_best_single_pk': {
                'best_single': best_single_pk,
                'dm_stat': round(dm_stat_pk, 4),
                'p_value': round(dm_p_pk, 4),
                'ensemble_better': dm_stat_pk < 0,
                'significant_005': dm_p_pk < 0.05,
            },
        }

    # Also DM: 3-way ensemble vs each single
    dm_3way_vs_each = {}
    for single in SINGLE_MODELS:
        dm_stat_r2, dm_p_r2 = dm_test(qlike_r2_losses['Ens_3way'], qlike_r2_losses[single])
        dm_stat_pk, dm_p_pk = dm_test(qlike_pk_losses['Ens_3way'], qlike_pk_losses[single])
        dm_3way_vs_each[single] = {
            'r2': {'dm_stat': round(dm_stat_r2, 4), 'p_value': round(dm_p_r2, 4), 'ens_better': dm_stat_r2 < 0},
            'pk': {'dm_stat': round(dm_stat_pk, 4), 'p_value': round(dm_p_pk, 4), 'ens_better': dm_stat_pk < 0},
        }

    # Rank models
    rank_r2 = sorted(ALL_MODELS, key=lambda m: qlike_r2[m])
    rank_pk = sorted(ALL_MODELS, key=lambda m: qlike_pk[m])

    # Print summary
    print(f"\n  QLIKE (r² proxy) ranking:")
    for j, m in enumerate(rank_r2):
        marker = " ★" if m.startswith('Ens') else ""
        print(f"    {j+1}. {m}: {qlike_r2[m]:.4f}{marker}")

    print(f"\n  QLIKE (Parkinson proxy) ranking:")
    for j, m in enumerate(rank_pk):
        marker = " ★" if m.startswith('Ens') else ""
        print(f"    {j+1}. {m}: {qlike_pk[m]:.4f}{marker}")

    print(f"\n  DM: 3-way ensemble vs each single (r² proxy):")
    for single in SINGLE_MODELS:
        d = dm_3way_vs_each[single]['r2']
        direction = "Ens better" if d['ens_better'] else "Single better"
        sig = "***" if d['p_value'] < 0.01 else "**" if d['p_value'] < 0.05 else "*" if d['p_value'] < 0.10 else ""
        print(f"    vs {single}: DM={d['dm_stat']:+.3f}, p={d['p_value']:.4f} ({direction}) {sig}")

    result = {
        'period': p_name,
        'oos_start': str(oos_dates[0].date()),
        'oos_end': str(oos_dates[-1].date()),
        'n_is': IS_WINDOW,
        'n_oos': n_oos,
        'is_scale_ratio': round(scale_ratio, 4),
        'qlike_r2': {m: round(v, 6) for m, v in qlike_r2.items()},
        'qlike_parkinson': {m: round(v, 6) for m, v in qlike_pk.items()},
        'rank_r2': rank_r2,
        'rank_parkinson': rank_pk,
        'dm_ensemble_vs_best_single': dm_results,
        'dm_3way_vs_each_single': dm_3way_vs_each,
    }
    period_results.append(result)

elapsed_oos = time.time() - t_start
print(f"\n  Cross-OOS complete in {elapsed_oos:.1f}s")


# ============================================================
# 9. VaR TRINITY TEST (last 2 periods combined: 2021-2024)
# ============================================================
print("\n" + "=" * 70)
print("[5] VaR Trinity Test (2021-2024)")
print("=" * 70)

VAR_OOS_START = '2021-01-01'
VAR_OOS_END = '2024-12-31'
ROLLING_VAR_WINDOW = 504
ALPHA_LEVELS = [0.01, 0.05]

oos_mask_var = (feat.index >= VAR_OOS_START) & (feat.index <= VAR_OOS_END)
oos_dates_var = feat.index[oos_mask_var]
n_var_oos = len(oos_dates_var)
first_var_loc = feat.index.get_loc(oos_dates_var[0])

print(f"  VaR OOS: {oos_dates_var[0].date()} to {oos_dates_var[-1].date()} ({n_var_oos} obs)")

# Collect rolling forecasts for VaR
var_models = ['GJR', 'HAR', 'Semi', 'Ens_3way', 'Ens_GJR_HAR', 'Ens_GJR_Semi', 'Ens_HAR_Semi']
var_sigma = {m: np.full(n_var_oos, np.nan) for m in var_models}
var_returns = np.full(n_var_oos, np.nan)

# IS calibration for scaling
is_var_data = feat.iloc[first_var_loc - ROLLING_VAR_WINDOW:first_var_loc]
is_r2_var = is_var_data['r2_proxy'].mean() * 10000
is_pk_var = is_var_data['parkinson_var'].mean() * 10000
var_scale = is_r2_var / is_pk_var if is_pk_var > 0 else 1.0

print(f"  Rolling window: {ROLLING_VAR_WINDOW}")
print(f"  VaR scale (r²/Parkinson): {var_scale:.3f}")

t_var_start = time.time()

for i, oos_date in enumerate(oos_dates_var):
    oos_loc = feat.index.get_loc(oos_date)
    w_start = oos_loc - ROLLING_VAR_WINDOW
    if w_start < 0:
        continue

    window = feat.iloc[w_start:oos_loc]
    var_returns[i] = feat.iloc[oos_loc]['return_pct']

    # GJR
    gjr_s2, _ = gjr_garch_forecast(window['return_pct'].values)
    var_sigma['GJR'][i] = np.sqrt(gjr_s2) if gjr_s2 > 0 and np.isfinite(gjr_s2) else np.nan

    # HAR — convert to σ in % (same scale as returns)
    har_s2_pk, _ = har_log_range_forecast(window)
    if har_s2_pk > 0 and np.isfinite(har_s2_pk):
        # Scale from Parkinson to r² level, then sqrt
        har_s2_r2 = har_s2_pk * var_scale
        var_sigma['HAR'][i] = np.sqrt(har_s2_r2)
    else:
        var_sigma['HAR'][i] = np.nan

    # Semi — EWMA of RS⁻
    semi_s2 = semi_forecast(window)
    var_sigma['Semi'][i] = np.sqrt(semi_s2) if semi_s2 > 0 and np.isfinite(semi_s2) else np.nan

    if (i + 1) % 200 == 0:
        elapsed = time.time() - t_var_start
        print(f"    {i+1}/{n_var_oos} VaR forecasts ({elapsed:.1f}s)")

# Ensemble σ for VaR
for ens_name, components in ENSEMBLE_MODELS.items():
    # Average σ (not σ²) for VaR — more conservative
    comp_sigmas = np.array([var_sigma[c] for c in components])
    var_sigma[ens_name] = np.nanmean(comp_sigmas, axis=0)

# Compute VaR and run Trinity
var_results = {}
for alpha in ALPHA_LEVELS:
    z = stats.norm.ppf(alpha)
    var_results[f"{int(alpha*100)}%"] = {}

    for m in var_models:
        sigma = var_sigma[m]
        # VaR (left tail) = μ_rolling - z_α * σ
        # Use simple rolling mean for μ
        valid = np.isfinite(sigma) & np.isfinite(var_returns)
        if np.sum(valid) < 50:
            var_results[f"{int(alpha*100)}%"][m] = {'error': 'insufficient data'}
            continue

        sigma_v = sigma[valid]
        ret_v = var_returns[valid]

        # Rolling mean of returns (use same window concept, but simplified)
        mu = np.mean(ret_v)  # Use overall mean for simplicity
        var_threshold = mu + z * sigma_v  # z is negative for left tail

        violations = (ret_v < var_threshold).astype(int)
        trinity = run_trinity(violations, var_threshold, ret_v, alpha)
        var_results[f"{int(alpha*100)}%"][m] = trinity

        marker = "✓" if trinity['trinity_pass'] else "✗"
        print(f"  {m} @ {int(alpha*100)}%: violations={trinity['n_violations']}/{trinity['n_obs']} "
              f"({trinity['violation_rate']:.4f}), Trinity {trinity['tests_passed']}/3 {marker}")

var_elapsed = time.time() - t_var_start
print(f"\n  VaR backtesting complete in {var_elapsed:.1f}s")


# ============================================================
# 10. CROSS-OOS SUMMARY
# ============================================================
print("\n" + "=" * 70)
print("[6] Cross-OOS Summary")
print("=" * 70)

# Count how many periods each model is best (r² proxy)
model_wins_r2 = {m: 0 for m in ALL_MODELS}
# Count how many periods ensemble beats best single
ens_beats_best = {m: 0 for m in ENSEMBLE_MODELS}
ens_sig_beats = {m: 0 for m in ENSEMBLE_MODELS}

for pr in period_results:
    # Best model per period
    best = pr['rank_r2'][0]
    model_wins_r2[best] += 1

    # Does ensemble beat best single?
    for ens_name in ENSEMBLE_MODELS:
        dm_info = pr['dm_ensemble_vs_best_single'][ens_name]['vs_best_single_r2']
        if dm_info['ensemble_better']:
            ens_beats_best[ens_name] += 1
        if dm_info['ensemble_better'] and dm_info['significant_005']:
            ens_sig_beats[ens_name] += 1

print("\n  Model wins (best QLIKE, r² proxy) across 5 periods:")
for m in ALL_MODELS:
    print(f"    {m}: {model_wins_r2[m]}/5")

print("\n  Ensemble vs best single model (r² proxy):")
for ens_name in ENSEMBLE_MODELS:
    print(f"    {ens_name}: better {ens_beats_best[ens_name]}/5, significantly better {ens_sig_beats[ens_name]}/5")

# Average QLIKE across periods
avg_qlike_r2 = {m: np.mean([pr['qlike_r2'][m] for pr in period_results]) for m in ALL_MODELS}
avg_qlike_pk = {m: np.mean([pr['qlike_parkinson'][m] for pr in period_results]) for m in ALL_MODELS}

rank_avg_r2 = sorted(ALL_MODELS, key=lambda m: avg_qlike_r2[m])
rank_avg_pk = sorted(ALL_MODELS, key=lambda m: avg_qlike_pk[m])

print("\n  Average QLIKE across 5 periods (r² proxy):")
for j, m in enumerate(rank_avg_r2):
    marker = " ★" if m.startswith('Ens') else ""
    print(f"    {j+1}. {m}: {avg_qlike_r2[m]:.4f}{marker}")

print("\n  Average QLIKE across 5 periods (Parkinson proxy):")
for j, m in enumerate(rank_avg_pk):
    marker = " ★" if m.startswith('Ens') else ""
    print(f"    {j+1}. {m}: {avg_qlike_pk[m]:.4f}{marker}")


# ============================================================
# 11. VaR SUMMARY
# ============================================================
print("\n  VaR Trinity Results Summary:")
for alpha_str in var_results:
    print(f"\n  --- {alpha_str} VaR ---")
    for m in var_models:
        if 'error' in var_results[alpha_str].get(m, {}):
            print(f"    {m}: ERROR ({var_results[alpha_str][m]['error']})")
        else:
            r = var_results[alpha_str][m]
            marker = "✓ PASS" if r['trinity_pass'] else f"✗ FAIL ({r['tests_passed']}/3)"
            print(f"    {m}: viol_rate={r['violation_rate']:.4f} (expect {r['expected_rate']}), {marker}")


# ============================================================
# 12. KEY FINDING: DOES ENSEMBLE GET "BEST OF BOTH WORLDS"?
# ============================================================
print("\n" + "=" * 70)
print("[7] Key Question: Does Ensemble Get Best of Both Worlds?")
print("=" * 70)

# Forecasting: is ensemble in top 3 across all periods?
ens3_rank_r2 = []
for pr in period_results:
    rank = pr['rank_r2'].index('Ens_3way') + 1
    ens3_rank_r2.append(rank)
avg_ens3_rank = np.mean(ens3_rank_r2)

print(f"\n  3-way Ensemble forecasting rank (r² proxy): {ens3_rank_r2}")
print(f"  Average rank: {avg_ens3_rank:.1f} / 7")

# VaR: how does ensemble compare?
ens3_var_1 = var_results.get('1%', {}).get('Ens_3way', {})
ens3_var_5 = var_results.get('5%', {}).get('Ens_3way', {})
gjr_var_1 = var_results.get('1%', {}).get('GJR', {})
gjr_var_5 = var_results.get('5%', {}).get('GJR', {})

print(f"\n  VaR comparison (3-way Ensemble vs GJR):")
if 'trinity_pass' in ens3_var_1 and 'trinity_pass' in gjr_var_1:
    print(f"    1%: Ens={ens3_var_1['tests_passed']}/3, GJR={gjr_var_1['tests_passed']}/3")
if 'trinity_pass' in ens3_var_5 and 'trinity_pass' in gjr_var_5:
    print(f"    5%: Ens={ens3_var_5['tests_passed']}/3, GJR={gjr_var_5['tests_passed']}/3")

# Judgment
forecasting_good = avg_ens3_rank <= 3
var_good = (ens3_var_1.get('trinity_pass', False) or ens3_var_1.get('tests_passed', 0) >= 2) and \
           (ens3_var_5.get('trinity_pass', False) or ens3_var_5.get('tests_passed', 0) >= 2)
both_good = forecasting_good and var_good

print(f"\n  Forecasting good (avg rank ≤ 3)? {forecasting_good} (rank={avg_ens3_rank:.1f})")
print(f"  VaR good (Trinity ≥ 2/3 at both levels)? {var_good}")
print(f"  ★ Best of both worlds? {both_good}")

if both_good:
    print("\n  → HYPOTHESIS CONFIRMED: Equal-weight ensemble achieves good")
    print("    forecasting AND VaR, overcoming the single-model tradeoff.")
else:
    print("\n  → HYPOTHESIS STATUS: Partial or failed.")
    if forecasting_good and not var_good:
        print("    Good forecasting but VaR not improved.")
    elif var_good and not forecasting_good:
        print("    Good VaR but forecasting not competitive.")
    else:
        print("    Neither forecasting nor VaR improved.")


# ============================================================
# 13. SAVE RESULTS
# ============================================================
total_time = time.time() - t_start
print(f"\n  Total runtime: {total_time:.1f}s")

results = {
    "experiment_id": "K475",
    "title": "Simple Ensemble of Validated Methods (Equal Weight)",
    "date": datetime.now(timezone.utc).isoformat(),
    "background": "K434 BMA failed (BIC weight degeneration). K450/K466 complex combos failed. "
                  "This test uses the simplest possible combination — equal weight average — "
                  "of only validated methods (GJR, HAR log-range, Semivariance RS⁻).",
    "hypothesis": "Can equal-weight ensemble achieve good forecasting AND VaR, "
                  "overcoming the single-model tradeoff (HAR best forecasting, GJR best VaR)?",
    "references": [
        "Timmermann (2006) 'Forecast Combinations' Handbook of Economic Forecasting — equal weight puzzle",
        "Corsi (2009) J Financial Econometrics — HAR-RV model",
        "Patton & Sheppard (2015) — Semivariance decomposition",
        "K434 — BMA weight degeneration (99.8% single model)",
        "K460 — Semivariance cross-OOS (4/5 equity)",
        "K465/K469 — HAR log-range cross-OOS (8/10 with r² proxy)",
        "K467 — HAR best forecasting but worst VaR",
    ],
    "method": {
        "ensemble_rule": "Equal weight average of σ² forecasts (σ²_ens = mean of component σ²)",
        "single_models": {
            "GJR": "GJR-GARCH(1,1) Student-t, 1-step rolling",
            "HAR": "HAR log-range (1d+5d+21d), Parkinson σ², scaled to r² for evaluation",
            "Semi": "HAR-style semivariance (RS⁻_5 + RS⁻_21 + RS⁺_5 + RS⁺_21)",
        },
        "ensemble_models": {
            "Ens_3way": "(GJR + HAR + Semi) / 3",
            "Ens_GJR_HAR": "(GJR + HAR) / 2",
            "Ens_GJR_Semi": "(GJR + Semi) / 2",
            "Ens_HAR_Semi": "(HAR + Semi) / 2",
        },
        "evaluation_proxies": ["r² (squared return)", "Parkinson range-based"],
        "significance": "Diebold-Mariano with HAC variance",
        "var_method": "Normal VaR with equal-weight σ averaging",
        "var_test": "Trinity (Kupiec + Christoffersen + DQ)",
    },
    "asset": "SPY",
    "data_source": "yfinance",
    "is_window": IS_WINDOW,
    "diagnostics": diagnostics,
    "cross_oos_results": period_results,
    "cross_oos_summary": {
        "model_wins_r2": model_wins_r2,
        "ens_beats_best_single": ens_beats_best,
        "ens_significantly_beats_best": ens_sig_beats,
        "avg_qlike_r2": {m: round(v, 6) for m, v in avg_qlike_r2.items()},
        "avg_qlike_parkinson": {m: round(v, 6) for m, v in avg_qlike_pk.items()},
        "rank_avg_r2": rank_avg_r2,
        "rank_avg_parkinson": rank_avg_pk,
        "ens_3way_rank_per_period_r2": ens3_rank_r2,
        "ens_3way_avg_rank_r2": round(avg_ens3_rank, 2),
    },
    "var_results": var_results,
    "key_question": {
        "question": "Does equal-weight ensemble get best of both worlds (forecasting + VaR)?",
        "forecasting_good": forecasting_good,
        "forecasting_avg_rank": round(avg_ens3_rank, 2),
        "var_good": var_good,
        "both_good": both_good,
    },
    "runtime_seconds": round(total_time, 1),
    "conclusion": "",  # Will be filled after seeing results
}

# Fill conclusion based on results
if both_good:
    results["conclusion"] = (
        f"CONFIRMED: Equal-weight ensemble of 3 validated methods achieves good forecasting "
        f"(avg rank {avg_ens3_rank:.1f}/7) AND good VaR. Timmermann (2006) forecast combination "
        f"puzzle applies — simple 1/N beats complex BMA (K434). This is the first method to "
        f"perform well on BOTH tasks simultaneously."
    )
else:
    reasons = []
    if not forecasting_good:
        reasons.append(f"forecasting avg rank {avg_ens3_rank:.1f}/7 (>3)")
    if not var_good:
        reasons.append("VaR Trinity insufficient")
    results["conclusion"] = (
        f"PARTIAL/FAILED: Equal-weight ensemble does not achieve best-of-both-worlds. "
        f"Issues: {'; '.join(reasons)}. "
        f"But equal weight may still be useful if it reduces variance of forecast errors "
        f"(check: lower MSE even if QLIKE not best?)."
    )

# Save
out_path = 'experiments/k475_validated_ensemble_results.json'
with open(out_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"\n  Results saved to {out_path}")
print("\n" + "=" * 70)
print("K475 COMPLETE")
print("=" * 70)
