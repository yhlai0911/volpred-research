#!/usr/bin/env python3
"""
K482: MCS-Weighted Ensemble Forecast
=====================================
Background:
  K481 MCS identified 5 superior models (p-values: Ensemble 1.000, Semi 0.785,
  EGARCH 0.461, HAR 0.141, GJR 0.186). K475 equal-weight ensemble ranked top
  for forecasting in 5/5 cross-OOS periods.

Question:
  Can MCS p-value weighting beat equal weight (the forecast combination puzzle)?
  Timmermann (2006) famously showed equal weight often wins. Does MCS info help?

Design:
  4 component models from MCS superior set (excluding Ensemble itself):
    - GJR-GARCH(1,1) Student-t (p=0.186)
    - EGARCH(1,1) Normal (p=0.461)
    - HAR log-range (p=0.141)
    - Semivariance RS⁻ (p=0.785)

  4 weighting schemes:
    1. Equal weight (1/N) — K475 baseline
    2. MCS p-value weighted — proportional to MCS p-value
    3. Inverse QLIKE weighted — lower QLIKE = higher weight (adaptive per period)
    4. Best single model (GJR) — benchmark

  5 cross-OOS periods (same as K475/K481):
    2015-2016, 2017-2018, 2019-2020, 2021-2022, 2023-2025

  Evaluation: QLIKE with r² proxy, DM tests between weighting schemes

References:
  Hansen, Lunde, Nason (2011) "The Model Confidence Set" Econometrica 79(2):453-497
  Timmermann (2006) "Forecast Combinations" Handbook of Economic Forecasting
  Corsi (2009) J Financial Econometrics — HAR-RV
  Patton (2011) J Econometrics — QLIKE loss
  K475 — Equal-weight ensemble (top 5/5 cross-OOS)
  K481 — MCS superior set identification

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
print("K482: MCS-Weighted Ensemble Forecast")
print("  Compare: Equal weight vs MCS p-value vs Inverse QLIKE vs Best single")
print("  4 component models from MCS superior set")
print("=" * 70)

t0 = time.time()

# ============================================================
# Configuration
# ============================================================
IS_WINDOW = 2000
REFIT_INTERVAL = 63  # quarterly refit for GARCH models

OOS_PERIODS = [
    {"name": "2015-2016 (low vol)", "start": "2015-01-01", "end": "2016-12-31"},
    {"name": "2017-2018 (Volmageddon)", "start": "2017-01-01", "end": "2018-12-31"},
    {"name": "2019-2020 (COVID)", "start": "2019-01-01", "end": "2020-12-31"},
    {"name": "2021-2022 (rate hikes)", "start": "2021-01-01", "end": "2022-12-31"},
    {"name": "2023-2025 (post-COVID)", "start": "2023-01-01", "end": "2025-12-31"},
]

# MCS p-values from K481 (r² proxy, 2023-2025 period)
MCS_PVALUES = {
    'GJR': 0.186,
    'EGARCH': 0.461,
    'HAR': 0.141,
    'Semi': 0.785,
}

# Subperiod MCS p-values from K481 (for robustness check)
SUBPERIOD_MCS = {
    "2015-2016 (low vol)": {'GJR': 0.863, 'EGARCH': 0.863, 'HAR': 0.555, 'Semi': 0.536},
    "2017-2018 (Volmageddon)": {'GJR': 1.000, 'EGARCH': 0.707, 'HAR': 0.077, 'Semi': 0.096},
    "2019-2020 (COVID)": {'GJR': 0.300, 'EGARCH': 0.208, 'HAR': 0.703, 'Semi': 0.347},
    "2021-2022 (rate hikes)": {'GJR': 0.033, 'EGARCH': 0.099, 'HAR': 0.177, 'Semi': 0.006},
    "2023-2025 (post-COVID)": {'GJR': 0.179, 'EGARCH': 0.439, 'HAR': 0.142, 'Semi': 0.779},
}

COMPONENT_MODELS = ['GJR', 'EGARCH', 'HAR', 'Semi']

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
neg_ret = np.where(ret_pct < 0, ret_pct, 0)
pos_ret = np.where(ret_pct > 0, ret_pct, 0)
feat['neg_ret_sq'] = neg_ret**2
feat['pos_ret_sq'] = pos_ret**2

# Rolling semivariance (21-day and 5-day)
feat['rs_neg_21'] = feat['neg_ret_sq'].rolling(21).mean()
feat['rs_neg_5'] = feat['neg_ret_sq'].rolling(5).mean()
feat['rs_pos_21'] = feat['pos_ret_sq'].rolling(21).mean()
feat['rs_pos_5'] = feat['pos_ret_sq'].rolling(5).mean()

feat = feat.dropna()
print(f"  Features: {len(feat)} obs ({feat.index[0].date()} to {feat.index[-1].date()})")

# ============================================================
# 3. DIAGNOSTICS (CLAUDE.md rule 5)
# ============================================================
print("\n[3] Data diagnostics...")
ret = feat['return_pct'].values
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
    'r2_proxy_mean': float(np.mean(r2)),
    'parkinson_var_mean': float(np.mean(pk)),
    'r2_over_parkinson_ratio': float(np.mean(r2) / np.mean(pk)),
    'adf_p': float(adf_p),
    'is_stationary': bool(adf_p < 0.05),
    'arch_lm_p': float(arch_p),
    'has_arch_effects': bool(arch_p < 0.05),
}

print(f"  n={diagnostics['n_obs']}, ADF p={adf_p:.2e}, ARCH-LM p={arch_p:.2e}")


# ============================================================
# 4. MODEL FORECAST FUNCTIONS
# ============================================================

def gjr_garch_forecast(returns_pct):
    """GJR-GARCH(1,1) Student-t, 1-step forecast. Returns σ² in %²."""
    try:
        am = arch_model(returns_pct, vol='GARCH', p=1, o=1, q=1, dist='t', mean='Constant')
        res = am.fit(disp='off', show_warning=False)
        fc = res.forecast(horizon=1)
        sigma2 = float(fc.variance.values[-1, 0])
        return sigma2, res
    except Exception:
        return np.nan, None


def egarch_forecast(returns_pct):
    """EGARCH(1,1) Normal, 1-step forecast. Returns σ² in %²."""
    try:
        am = arch_model(returns_pct, vol='EGARCH', p=1, o=1, q=1, dist='normal', mean='Constant')
        res = am.fit(disp='off', show_warning=False)
        fc = res.forecast(horizon=1)
        sigma2 = float(fc.variance.values[-1, 0])
        return sigma2, res
    except Exception:
        return np.nan, None


def har_log_range_forecast(feat_window):
    """HAR log-range, returns σ² in %² (via Parkinson scaling to r²)."""
    cols = ['log_range', 'log_range_5d', 'log_range_21d']
    data = feat_window[cols].dropna()
    if len(data) < 50:
        return np.nan

    Y = data['log_range'].values[1:]
    X_mat = data[cols].values[:-1]
    X_mat = np.column_stack([np.ones(len(Y)), X_mat])

    try:
        beta = np.linalg.lstsq(X_mat, Y, rcond=None)[0]
    except Exception:
        return np.nan

    x_last = data[cols].values[-1]
    fc_log_range = beta[0] + beta[1:] @ x_last
    fc_log_range = max(fc_log_range, 1e-6)

    # Parkinson variance in decimal² → %²
    parkinson_var_decimal = fc_log_range**2 / (4 * np.log(2))
    parkinson_var_pct2 = parkinson_var_decimal * 10000

    return parkinson_var_pct2


def semi_forecast(feat_window):
    """Semivariance RS⁻ model. Returns σ² in %²."""
    cols = ['rs_neg_5', 'rs_neg_21', 'rs_pos_5', 'rs_pos_21']
    data = feat_window[cols + ['return_pct']].dropna()
    if len(data) < 50:
        return np.nan

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
    return fc


# ============================================================
# 5. QLIKE LOSS & DM TEST
# ============================================================

def qlike_loss(sigma2_forecast, realized_var):
    """QLIKE = realized/forecast + log(forecast). Lower is better."""
    valid = (sigma2_forecast > 0) & (realized_var > 0) & np.isfinite(sigma2_forecast) & np.isfinite(realized_var)
    s2f = sigma2_forecast[valid]
    rv = realized_var[valid]
    ql = rv / s2f + np.log(s2f)
    return ql, valid


def qlike_mean(sigma2_forecast, realized_var):
    """Mean QLIKE."""
    ql, valid = qlike_loss(sigma2_forecast, realized_var)
    return float(np.mean(ql)) if len(ql) > 0 else np.nan


def dm_test(losses1, losses2, h=1):
    """Diebold-Mariano test with HAC variance."""
    d = losses1 - losses2
    n = len(d)
    d_bar = np.mean(d)

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
# 6. WEIGHTING SCHEMES
# ============================================================

def compute_weights(scheme, mcs_pvals=None, qlike_vals=None):
    """
    Compute weights for component models.

    Args:
        scheme: 'equal', 'mcs_pvalue', 'inv_qlike'
        mcs_pvals: dict {model: p-value} for MCS weighting
        qlike_vals: dict {model: QLIKE} for inverse QLIKE weighting

    Returns: dict {model: weight}
    """
    models = COMPONENT_MODELS

    if scheme == 'equal':
        w = {m: 1.0 / len(models) for m in models}
    elif scheme == 'mcs_pvalue':
        total = sum(mcs_pvals[m] for m in models)
        w = {m: mcs_pvals[m] / total for m in models}
    elif scheme == 'inv_qlike':
        # Lower QLIKE = better → inverse as weight
        inv = {m: 1.0 / max(qlike_vals[m], 1e-6) for m in models}
        total = sum(inv.values())
        w = {m: inv[m] / total for m in models}
    else:
        raise ValueError(f"Unknown scheme: {scheme}")

    return w


# ============================================================
# 7. MAIN CROSS-OOS LOOP
# ============================================================
print("\n[4] Running cross-OOS evaluation...")

all_period_results = []

for pidx, period in enumerate(OOS_PERIODS):
    pname = period['name']
    print(f"\n  --- Period {pidx+1}/{len(OOS_PERIODS)}: {pname} ---")

    oos_mask = (feat.index >= period['start']) & (feat.index <= period['end'])
    oos_idx = feat.index[oos_mask]
    n_oos = len(oos_idx)

    if n_oos == 0:
        print(f"    No OOS data for {pname}, skipping")
        continue

    # Find IS start
    all_idx = feat.index.tolist()
    oos_start_pos = all_idx.index(oos_idx[0])

    if oos_start_pos < IS_WINDOW:
        print(f"    Not enough IS data for {pname}, skipping")
        continue

    print(f"    OOS: {oos_idx[0].date()} to {oos_idx[-1].date()} ({n_oos} obs)")

    # Storage for per-day forecasts
    forecasts = {m: np.full(n_oos, np.nan) for m in COMPONENT_MODELS}
    realized_r2 = np.full(n_oos, np.nan)

    # GARCH model caches (refit quarterly)
    gjr_res = None
    egarch_res = None
    last_gjr_fit = -REFIT_INTERVAL
    last_egarch_fit = -REFIT_INTERVAL

    for t in range(n_oos):
        pos = oos_start_pos + t
        date_t = all_idx[pos]

        # r² proxy for today (to be forecasted from yesterday)
        realized_r2[t] = feat['r2_proxy'].iloc[pos] * 10000  # Convert to %² for comparison with GARCH

        # IS window
        is_start = max(0, pos - IS_WINDOW)

        # === GJR-GARCH ===
        if t - last_gjr_fit >= REFIT_INTERVAL or gjr_res is None:
            ret_is = feat['return_pct'].values[is_start:pos]
            sigma2_gjr, gjr_res = gjr_garch_forecast(ret_is)
            last_gjr_fit = t
        else:
            # Update with new observation
            try:
                ret_is = feat['return_pct'].values[is_start:pos]
                am = arch_model(ret_is, vol='GARCH', p=1, o=1, q=1, dist='t', mean='Constant')
                res = am.fit(disp='off', show_warning=False, starting_values=gjr_res.params.values)
                fc = res.forecast(horizon=1)
                sigma2_gjr = float(fc.variance.values[-1, 0])
                gjr_res = res
            except Exception:
                sigma2_gjr = np.nan
        forecasts['GJR'][t] = sigma2_gjr

        # === EGARCH ===
        if t - last_egarch_fit >= REFIT_INTERVAL or egarch_res is None:
            ret_is = feat['return_pct'].values[is_start:pos]
            sigma2_eg, egarch_res = egarch_forecast(ret_is)
            last_egarch_fit = t
        else:
            try:
                ret_is = feat['return_pct'].values[is_start:pos]
                am = arch_model(ret_is, vol='EGARCH', p=1, o=1, q=1, dist='normal', mean='Constant')
                res = am.fit(disp='off', show_warning=False, starting_values=egarch_res.params.values)
                fc = res.forecast(horizon=1)
                sigma2_eg = float(fc.variance.values[-1, 0])
                egarch_res = res
            except Exception:
                sigma2_eg = np.nan
        forecasts['EGARCH'][t] = sigma2_eg

        # === HAR log-range (refit every day, OLS is fast) ===
        feat_window = feat.iloc[is_start:pos]
        forecasts['HAR'][t] = har_log_range_forecast(feat_window)

        # === Semivariance ===
        forecasts['Semi'][t] = semi_forecast(feat_window)

    # ============================================================
    # Compute per-model QLIKE
    # ============================================================
    model_qlike = {}
    model_losses = {}  # per-day losses for DM test

    for m in COMPONENT_MODELS:
        fc = forecasts[m]
        ql, valid = qlike_loss(fc, realized_r2)
        model_qlike[m] = float(np.mean(ql)) if len(ql) > 0 else np.nan
        # Store full loss vector (using valid mask)
        full_losses = np.full(n_oos, np.nan)
        full_losses[valid] = ql
        model_losses[m] = full_losses

    print(f"    Component QLIKE: {' | '.join(f'{m}={model_qlike[m]:.4f}' for m in COMPONENT_MODELS)}")

    # ============================================================
    # Compute ensemble forecasts with different weighting schemes
    # ============================================================
    ensemble_schemes = {}

    # 1. Equal weight
    w_equal = compute_weights('equal')
    ensemble_schemes['Equal_Weight'] = {'weights': w_equal}

    # 2. MCS p-value weighted (from full-sample K481)
    w_mcs = compute_weights('mcs_pvalue', mcs_pvals=MCS_PVALUES)
    ensemble_schemes['MCS_PValue'] = {'weights': w_mcs}

    # 3. MCS p-value weighted (subperiod-specific from K481)
    if pname in SUBPERIOD_MCS:
        w_mcs_sub = compute_weights('mcs_pvalue', mcs_pvals=SUBPERIOD_MCS[pname])
        ensemble_schemes['MCS_Subperiod'] = {'weights': w_mcs_sub}

    # 4. Inverse QLIKE weighted (adaptive — uses THIS period's QLIKE)
    # This has look-ahead bias for current period but shows potential
    w_inv = compute_weights('inv_qlike', qlike_vals=model_qlike)
    ensemble_schemes['Inv_QLIKE'] = {'weights': w_inv}

    # 5. Inverse QLIKE from PREVIOUS period (no look-ahead)
    if pidx > 0:
        prev_results = all_period_results[pidx - 1]
        prev_qlike = prev_results['component_qlike']
        w_inv_prev = compute_weights('inv_qlike', qlike_vals=prev_qlike)
        ensemble_schemes['Inv_QLIKE_Prev'] = {'weights': w_inv_prev}

    # Compute ensemble σ² and QLIKE for each scheme
    ensemble_results = {}
    ensemble_losses = {}

    for scheme_name, scheme_info in ensemble_schemes.items():
        w = scheme_info['weights']
        ens_fc = np.zeros(n_oos)
        for m in COMPONENT_MODELS:
            ens_fc += w[m] * forecasts[m]

        ql, valid = qlike_loss(ens_fc, realized_r2)
        ens_qlike = float(np.mean(ql)) if len(ql) > 0 else np.nan

        full_losses = np.full(n_oos, np.nan)
        full_losses[valid] = ql
        ensemble_losses[scheme_name] = full_losses

        ensemble_results[scheme_name] = {
            'weights': {m: round(w[m], 4) for m in COMPONENT_MODELS},
            'qlike': round(ens_qlike, 6),
        }

    # Best single model
    best_single = min(model_qlike, key=model_qlike.get)
    ensemble_results['Best_Single'] = {
        'model': best_single,
        'qlike': round(model_qlike[best_single], 6),
    }
    ensemble_losses['Best_Single'] = model_losses[best_single]

    # Print results
    print(f"    --- QLIKE Results ---")
    for sname, sres in ensemble_results.items():
        ql = sres['qlike']
        if 'weights' in sres:
            w_str = ', '.join(f"{m}={sres['weights'][m]:.3f}" for m in COMPONENT_MODELS)
            print(f"    {sname:20s}: QLIKE={ql:.6f}  [{w_str}]")
        else:
            print(f"    {sname:20s}: QLIKE={ql:.6f}  [{sres['model']}]")

    # ============================================================
    # DM tests: Equal Weight vs alternatives
    # ============================================================
    dm_results = {}
    ref_scheme = 'Equal_Weight'
    ref_losses = ensemble_losses[ref_scheme]

    for sname in ensemble_results:
        if sname == ref_scheme:
            continue
        alt_losses = ensemble_losses[sname]
        # Use only jointly valid observations
        both_valid = np.isfinite(ref_losses) & np.isfinite(alt_losses)
        if np.sum(both_valid) < 30:
            continue
        dm_stat, dm_p = dm_test(ref_losses[both_valid], alt_losses[both_valid])
        dm_results[f"{ref_scheme}_vs_{sname}"] = {
            'dm_stat': round(dm_stat, 4),
            'p_value': round(dm_p, 4),
            'equal_better': dm_stat < 0,
            'significant_005': dm_p < 0.05,
        }

    # Also test: MCS_PValue vs Best_Single
    both_valid = np.isfinite(ensemble_losses['MCS_PValue']) & np.isfinite(ensemble_losses['Best_Single'])
    if np.sum(both_valid) >= 30:
        dm_stat, dm_p = dm_test(ensemble_losses['MCS_PValue'][both_valid], ensemble_losses['Best_Single'][both_valid])
        dm_results['MCS_PValue_vs_Best_Single'] = {
            'dm_stat': round(dm_stat, 4),
            'p_value': round(dm_p, 4),
            'mcs_better': dm_stat < 0,
            'significant_005': dm_p < 0.05,
        }

    # Print DM results
    print(f"    --- DM Tests (vs Equal Weight) ---")
    for dname, dres in dm_results.items():
        sign = "*" if dres['significant_005'] else ""
        print(f"    {dname:35s}: DM={dres['dm_stat']:+.4f}, p={dres['p_value']:.4f} {sign}")

    # Store period results
    period_result = {
        'period': pname,
        'n_oos': n_oos,
        'oos_range': f"{oos_idx[0].date()} to {oos_idx[-1].date()}",
        'component_qlike': {m: round(model_qlike[m], 6) for m in COMPONENT_MODELS},
        'ensemble_results': ensemble_results,
        'dm_tests': dm_results,
        'ranking': sorted(
            [(sname, sres['qlike']) for sname, sres in ensemble_results.items()],
            key=lambda x: x[1]
        ),
    }
    all_period_results.append(period_result)


# ============================================================
# 8. CROSS-PERIOD SUMMARY
# ============================================================
print("\n" + "=" * 70)
print("[5] Cross-Period Summary")
print("=" * 70)

# Track which scheme wins in each period
scheme_wins = {}
scheme_qlike_all = {}

for pr in all_period_results:
    best_scheme = pr['ranking'][0][0]
    scheme_wins[best_scheme] = scheme_wins.get(best_scheme, 0) + 1

    for sname, ql in pr['ranking']:
        if sname not in scheme_qlike_all:
            scheme_qlike_all[sname] = []
        scheme_qlike_all[sname].append(ql)

print("\n  Wins by scheme:")
for scheme, wins in sorted(scheme_wins.items(), key=lambda x: -x[1]):
    print(f"    {scheme}: {wins}/{len(all_period_results)}")

print("\n  Average QLIKE across periods:")
for scheme in sorted(scheme_qlike_all, key=lambda x: np.mean(scheme_qlike_all[x])):
    vals = scheme_qlike_all[scheme]
    avg = np.mean(vals)
    n = len(vals)
    print(f"    {scheme:20s}: {avg:.6f} ({n} periods)")

# Compute average rank per scheme
scheme_ranks = {}
for pr in all_period_results:
    for rank_idx, (sname, _) in enumerate(pr['ranking']):
        if sname not in scheme_ranks:
            scheme_ranks[sname] = []
        scheme_ranks[sname].append(rank_idx + 1)

print("\n  Average Rank across periods:")
for scheme in sorted(scheme_ranks, key=lambda x: np.mean(scheme_ranks[x])):
    vals = scheme_ranks[scheme]
    avg = np.mean(vals)
    print(f"    {scheme:20s}: {avg:.2f}")

# ============================================================
# 9. KEY COMPARISON: Equal vs MCS-weighted
# ============================================================
print("\n  --- Equal Weight vs MCS P-Value (per period) ---")
equal_better_count = 0
mcs_better_count = 0

for pr in all_period_results:
    eq_ql = pr['ensemble_results']['Equal_Weight']['qlike']
    mcs_ql = pr['ensemble_results']['MCS_PValue']['qlike']
    diff = eq_ql - mcs_ql
    winner = "Equal" if diff < 0 else "MCS"
    if diff < 0:
        equal_better_count += 1
    else:
        mcs_better_count += 1
    print(f"    {pr['period']:30s}: EQ={eq_ql:.6f} MCS={mcs_ql:.6f} diff={diff:+.6f} → {winner}")

print(f"\n  Equal wins: {equal_better_count}/{len(all_period_results)}")
print(f"  MCS wins:   {mcs_better_count}/{len(all_period_results)}")

# ============================================================
# 10. WEIGHT CONCENTRATION ANALYSIS
# ============================================================
print("\n  --- Weight Analysis ---")
for scheme in ['Equal_Weight', 'MCS_PValue']:
    w = all_period_results[0]['ensemble_results'][scheme]['weights']
    hhi = sum(v**2 for v in w.values())
    max_w = max(w.values())
    min_w = min(w.values())
    print(f"    {scheme}: HHI={hhi:.4f}, max_w={max_w:.4f}, min_w={min_w:.4f}")
    print(f"      Weights: {w}")

elapsed = time.time() - t0
print(f"\n  Total time: {elapsed:.1f} seconds")

# ============================================================
# 11. CONCLUSION
# ============================================================

# Determine overall verdict
all_eq = [pr['ensemble_results']['Equal_Weight']['qlike'] for pr in all_period_results]
all_mcs = [pr['ensemble_results']['MCS_PValue']['qlike'] for pr in all_period_results]

# Paired test across periods (if enough)
if len(all_eq) >= 3:
    from scipy.stats import wilcoxon
    try:
        w_stat, w_p = wilcoxon(all_eq, all_mcs)
        wilcoxon_result = {'W_stat': float(w_stat), 'p_value': float(w_p)}
    except Exception:
        wilcoxon_result = {'W_stat': None, 'p_value': None}
else:
    wilcoxon_result = {'W_stat': None, 'p_value': None}

# Build conclusion
avg_eq = np.mean(all_eq)
avg_mcs = np.mean(all_mcs)
pct_diff = (avg_mcs - avg_eq) / avg_eq * 100

if avg_eq < avg_mcs:
    verdict = f"Equal weight BEATS MCS-weighted by {abs(pct_diff):.2f}% avg QLIKE. Timmermann (2006) forecast combination puzzle CONFIRMED."
elif avg_mcs < avg_eq and pct_diff < -1:
    verdict = f"MCS-weighted BEATS equal weight by {abs(pct_diff):.2f}% avg QLIKE. MCS information adds value."
else:
    verdict = f"Difference is negligible ({pct_diff:+.2f}%). Both approaches are equivalent in practice."

print(f"\n  VERDICT: {verdict}")

# ============================================================
# 12. SAVE RESULTS
# ============================================================
results = {
    'experiment_id': 'K482',
    'title': 'MCS-Weighted Ensemble Forecast',
    'date': datetime.now(timezone.utc).isoformat(),
    'references': [
        'Hansen, Lunde, Nason (2011) "The Model Confidence Set" Econometrica 79(2):453-497',
        'Timmermann (2006) "Forecast Combinations" Handbook of Economic Forecasting',
        'Corsi (2009) J Financial Econometrics — HAR-RV',
        'Patton (2011) J Econometrics — QLIKE loss',
        'K475 — Equal-weight ensemble (top 5/5 cross-OOS)',
        'K481 — MCS superior set identification',
    ],
    'method': {
        'component_models': {
            'GJR': 'GJR-GARCH(1,1) Student-t, quarterly refit',
            'EGARCH': 'EGARCH(1,1) Normal, quarterly refit',
            'HAR': 'HAR log-range (1d+5d+21d), daily OLS refit',
            'Semi': 'HAR-style semivariance (RS⁻_5 + RS⁻_21 + RS⁺_5 + RS⁺_21), daily OLS refit',
        },
        'weighting_schemes': {
            'Equal_Weight': '1/N equal weight',
            'MCS_PValue': 'Proportional to MCS p-values from K481 (full-sample)',
            'MCS_Subperiod': 'Proportional to subperiod-specific MCS p-values from K481',
            'Inv_QLIKE': 'Inverse QLIKE weighting (oracle — uses current period QLIKE)',
            'Inv_QLIKE_Prev': 'Inverse QLIKE from previous period (no look-ahead)',
            'Best_Single': 'Best individual model (benchmark)',
        },
        'evaluation': 'QLIKE with r² proxy, DM test with HAC variance',
        'is_window': IS_WINDOW,
        'refit_interval': REFIT_INTERVAL,
    },
    'asset': 'SPY',
    'data_source': 'yfinance',
    'diagnostics': diagnostics,
    'mcs_pvalues_used': MCS_PVALUES,
    'mcs_weights': {m: round(v, 4) for m, v in compute_weights('mcs_pvalue', mcs_pvals=MCS_PVALUES).items()},
    'cross_oos_results': [],
    'summary': {
        'scheme_wins': scheme_wins,
        'avg_qlike_by_scheme': {s: round(np.mean(v), 6) for s, v in scheme_qlike_all.items()},
        'avg_rank_by_scheme': {s: round(np.mean(v), 2) for s, v in scheme_ranks.items()},
        'equal_weight_wins': equal_better_count,
        'mcs_pvalue_wins': mcs_better_count,
        'n_periods': len(all_period_results),
        'wilcoxon_test': wilcoxon_result,
        'avg_qlike_equal': round(avg_eq, 6),
        'avg_qlike_mcs': round(avg_mcs, 6),
        'pct_diff_mcs_vs_equal': round(pct_diff, 4),
    },
    'conclusion': verdict,
    'timmermann_puzzle': {
        'description': 'Timmermann (2006): equal weight ensemble often beats optimized weight',
        'confirmed': avg_eq <= avg_mcs,
        'evidence': f'Equal Weight avg QLIKE={avg_eq:.6f} vs MCS-weighted {avg_mcs:.6f} ({pct_diff:+.2f}%)',
    },
    'limitations': [
        'MCS p-values from K481 are estimated once — time-varying MCS might differ',
        'Subperiod MCS p-values from K481 use specific sub-periods, not rolling',
        'Inv_QLIKE is oracle (uses current-period QLIKE) — not implementable in real-time',
        'Inv_QLIKE_Prev uses previous period, which may not predict next period well',
        'QLIKE is the only loss function — other losses (MSE, MAE) may give different rankings',
        'Single asset (SPY) — generalization to other assets needs verification',
        'r² proxy is noisy — results may change with realized variance from intraday data',
    ],
}

# Add per-period results (simplified for JSON)
for pr in all_period_results:
    period_out = {
        'period': pr['period'],
        'n_oos': pr['n_oos'],
        'oos_range': pr['oos_range'],
        'component_qlike': pr['component_qlike'],
        'ensemble_qlike': {sname: sres['qlike'] for sname, sres in pr['ensemble_results'].items()},
        'ensemble_weights': {sname: sres.get('weights', {}) for sname, sres in pr['ensemble_results'].items()},
        'best_single_model': pr['ensemble_results'].get('Best_Single', {}).get('model', ''),
        'ranking': pr['ranking'],
        'dm_tests': pr['dm_tests'],
    }
    results['cross_oos_results'].append(period_out)

# Save
import os
out_path = os.path.join(os.path.dirname(__file__), 'k482_mcs_weighted_ensemble_results.json')
with open(out_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"\n  Results saved to: {out_path}")
print("\n" + "=" * 70)
print("K482 COMPLETE")
print("=" * 70)
