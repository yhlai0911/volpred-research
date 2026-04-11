"""
K1048: Threshold GARCH-X with Variable Selection
=================================================
Combines K1031's SSVS insight (VIX9D^2 PIP=1.000) with K813's threshold
structure concept. Tests whether GARCH parameters and optimal exogenous
variables differ between high/low VIX regimes.

Model (Threshold GJR-GARCH-X):
  Regime 1 (Z_{t-1} <= c):
    h_t = w1 + a1*e^2_{t-1} + g1*e^2_{t-1}*I(e<0) + b1*h_{t-1} + d1*X_{t-1}
  Regime 2 (Z_{t-1} > c):
    h_t = w2 + a2*e^2_{t-1} + g2*e^2_{t-1}*I(e<0) + b2*h_{t-1} + d2*X_{t-1}

  Z = VIX level (threshold variable)
  c in {15, 20, 25, 30, 35} (threshold candidates)
  X selected per-regime via BIC from candidate set

References:
  - Gonzalez-Rivera (1998, JBES) - Threshold GARCH
  - So, Chen, Liu (2006, JRSS-C) - SSVS for GARCH (K1031 used this)
  - Patton (2011) - QLIKE loss function
  - Chen & So (2006) - Threshold heteroscedastic models
  - K813: STGARCH 11-param failed OOS (DM=-0.11 NS)
  - K1031: SSVS selects VIX9D^2 PIP=1.000, VIX^2 PIP=0.995
  - K1019: MS(2)-GJR regime dynamics real (DM=-3.20) but lost to A4f

Data: SPY 2005-2026, yfinance (^VIX, ^VIX9D)
Seed: 42
Target: r^2 (squared daily return) per preamble rule
Evaluation: QLIKE (Patton 2011), DM test, BIC, VaR Trinity
"""

import numpy as np
import pandas as pd
import json
import os
import sys
import warnings
from datetime import datetime
from scipy.optimize import minimize
from scipy.stats import norm, chi2
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

warnings.filterwarnings('ignore')
np.random.seed(42)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(os.path.dirname(BASE_DIR))

print("=" * 70)
print("K1048: Threshold GARCH-X with Variable Selection")
print("=" * 70)

# ============================================================
# 1. DATA LOADING
# ============================================================
import yfinance as yf

print("\n[1] Loading data from yfinance...")
spy = yf.download('SPY', start='2004-01-01', end='2026-12-31', progress=False)
if isinstance(spy.columns, pd.MultiIndex):
    spy.columns = spy.columns.get_level_values(0)
spy.index = pd.DatetimeIndex(spy.index).tz_localize(None)
spy['ret'] = np.log(spy['Close'] / spy['Close'].shift(1))
spy = spy.dropna(subset=['ret'])
print(f"  SPY: {spy.index[0].date()} to {spy.index[-1].date()}, N={len(spy)}")

# Load VIX and VIX9D
vix_tickers = yf.download(['^VIX', '^VIX9D'], start='2004-01-01', end='2026-12-31', progress=False)
if isinstance(vix_tickers.columns, pd.MultiIndex):
    vix_close = vix_tickers['Close']
else:
    vix_close = vix_tickers[['Close']]

vix_df = pd.DataFrame(index=vix_close.index)
for col in vix_close.columns:
    col_str = str(col)
    if 'VIX9D' in col_str:
        vix_df['VIX9D'] = vix_close[col]
    elif 'VIX' in col_str:
        vix_df['VIX'] = vix_close[col]

vix_df.index = pd.DatetimeIndex(vix_df.index).tz_localize(None)

# Merge
df = spy[['ret']].copy()
df['r_sq'] = df['ret'] ** 2  # target for GARCH evaluation
df = df.join(vix_df, how='left')
df['VIX'] = df['VIX'].ffill()
df['VIX9D'] = df['VIX9D'].ffill()
df = df.dropna(subset=['VIX'])

# Build exogenous candidates (all lagged by 1 day for no lookahead)
df['VIX_sq'] = df['VIX'] ** 2
df['VIX_level'] = df['VIX']
df['log_VIX'] = np.log(df['VIX'].clip(lower=1))
df['VIX_change'] = df['VIX'].diff()
df['VIX_percentile'] = df['VIX'].rolling(252, min_periods=63).rank(pct=True)

# VIX9D only available from ~2011
vix9d_start = df['VIX9D'].first_valid_index()
df['VIX9D_sq'] = df['VIX9D'] ** 2

# Drop initial NaN rows
df = df.dropna(subset=['VIX_change', 'VIX_percentile'])

print(f"  Final dataset: {df.index[0].date()} to {df.index[-1].date()}, N={len(df)}")
print(f"  VIX9D available from: {vix9d_start.date() if vix9d_start is not None else 'N/A'}")

# ============================================================
# 2. DESCRIPTIVE STATISTICS
# ============================================================
print("\n[2] Descriptive Statistics")
print(f"  ret:   mean={df['ret'].mean()*252:.4f} (ann), std={df['ret'].std()*np.sqrt(252):.4f}")
print(f"  VIX:   mean={df['VIX'].mean():.2f}, median={df['VIX'].median():.2f}")
print(f"         min={df['VIX'].min():.2f}, max={df['VIX'].max():.2f}")
print(f"  VIX9D: mean={df['VIX9D'].dropna().mean():.2f}, median={df['VIX9D'].dropna().median():.2f}")

# Regime statistics by VIX threshold
print("\n  Regime statistics by VIX threshold:")
for c in [15, 20, 25, 30, 35]:
    n_low = (df['VIX'] <= c).sum()
    n_high = (df['VIX'] > c).sum()
    pct_high = n_high / len(df) * 100
    vol_low = df.loc[df['VIX'] <= c, 'ret'].std() * np.sqrt(252)
    vol_high = df.loc[df['VIX'] > c, 'ret'].std() * np.sqrt(252) if n_high > 50 else np.nan
    print(f"    c={c}: Low={n_low} ({100-pct_high:.1f}%), High={n_high} ({pct_high:.1f}%), "
          f"Vol_low={vol_low:.4f}, Vol_high={vol_high:.4f}")

# ============================================================
# 3. GJR-GARCH-X ESTIMATION FUNCTIONS
# ============================================================
print("\n[3] Setting up GJR-GARCH-X estimation...")


def gjr_garch_x_negloglik(params, returns, exog=None):
    """
    Negative log-likelihood for GJR-GARCH(1,1)-X with optional exogenous.
    params: [mu, omega, alpha, gamma, beta, delta1, delta2, ...]
    """
    n = len(returns)
    mu = params[0]
    omega = params[1]
    alpha = params[2]
    gamma_p = params[3]
    beta = params[4]
    deltas = params[5:] if exog is not None else []

    eps = returns - mu
    h = np.zeros(n)
    h[0] = np.var(returns[:min(500, n)])

    for t in range(1, n):
        h[t] = omega + alpha * eps[t-1]**2 + gamma_p * eps[t-1]**2 * (eps[t-1] < 0) + beta * h[t-1]
        if exog is not None:
            for j, d in enumerate(deltas):
                h[t] += d * exog[t-1, j]
        if h[t] < 1e-10:
            h[t] = 1e-10

    # Normal log-likelihood
    ll = -0.5 * np.sum(np.log(2 * np.pi) + np.log(h) + eps**2 / h)
    return -ll


def estimate_gjr_x(returns, exog=None, max_attempts=3):
    """
    Estimate GJR-GARCH(1,1)-X model.
    Returns: params, loglik, convergence, h_series
    """
    n = len(returns)
    n_exog = exog.shape[1] if exog is not None else 0

    best_result = None
    best_ll = np.inf

    for attempt in range(max_attempts):
        # Initial params
        mu0 = returns.mean() if attempt == 0 else returns.mean() + np.random.normal(0, 0.0001)
        omega0 = np.var(returns) * 0.05 * (1 + 0.1 * attempt)
        alpha0 = 0.05 + 0.02 * attempt
        gamma0 = 0.05 + 0.02 * attempt
        beta0 = 0.85 - 0.05 * attempt
        delta0 = [1e-6] * n_exog

        x0 = [mu0, omega0, alpha0, gamma0, beta0] + delta0

        # Bounds
        # Scale-adaptive delta bounds based on exog magnitude
        if exog is not None:
            exog_max = np.abs(exog).max(axis=0)
            delta_bounds = [(-0.01 / max(em, 1e-6), 0.01 / max(em, 1e-6)) for em in exog_max]
        else:
            delta_bounds = []

        bounds = [
            (-0.01, 0.01),     # mu
            (1e-10, 0.001),    # omega
            (1e-6, 0.5),       # alpha
            (1e-6, 0.5),       # gamma
            (0.5, 0.999),      # beta
        ] + delta_bounds

        try:
            result = minimize(
                gjr_garch_x_negloglik, x0, args=(returns, exog),
                method='L-BFGS-B', bounds=bounds,
                options={'maxiter': 5000, 'ftol': 1e-12}
            )
            if result.fun < best_ll:
                best_ll = result.fun
                best_result = result
        except Exception:
            continue

    if best_result is None:
        return None, None, False, None

    # Extract conditional variance series
    params = best_result.x
    mu, omega, alpha, gamma_p, beta = params[:5]
    deltas = params[5:] if n_exog > 0 else []
    eps = returns - mu
    h = np.zeros(n)
    h[0] = np.var(returns[:min(500, n)])
    for t in range(1, n):
        h[t] = omega + alpha * eps[t-1]**2 + gamma_p * eps[t-1]**2 * (eps[t-1] < 0) + beta * h[t-1]
        for j, d in enumerate(deltas):
            h[t] += d * exog[t-1, j]
        if h[t] < 1e-10:
            h[t] = 1e-10

    persistence = alpha + gamma_p / 2 + beta
    converged = best_result.success and persistence < 1.0

    return params, -best_ll, converged, h


def compute_bic(loglik, n_params, n_obs):
    return -2 * loglik + n_params * np.log(n_obs)


def compute_qlike(actual_r_sq, predicted_h):
    """QLIKE loss: mean(r^2/h + log(h))"""
    mask = (predicted_h > 0) & np.isfinite(actual_r_sq) & np.isfinite(predicted_h)
    r2 = actual_r_sq[mask]
    h = predicted_h[mask]
    return np.mean(r2 / h + np.log(h))


def dm_test(loss1, loss2, h=1):
    """Diebold-Mariano test. Negative t = model 1 better."""
    d = loss1 - loss2
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 10:
        return 0.0, 1.0
    d_mean = np.mean(d)
    # Newey-West variance with h-1 lags
    gamma0 = np.var(d, ddof=1)
    gamma_sum = 0
    for k in range(1, h):
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        gamma_sum += 2 * (1 - k / h) * gamma_k
    var_d = (gamma0 + gamma_sum) / n
    if var_d <= 0:
        var_d = gamma0 / n
    t_stat = d_mean / np.sqrt(var_d)
    p_value = 2 * (1 - norm.cdf(abs(t_stat)))
    return t_stat, p_value


# ============================================================
# 4. THRESHOLD GARCH ANALYSIS (IN-SAMPLE)
# ============================================================
print("\n[4] In-Sample Threshold GARCH Analysis")

# Use data from 2005 onwards (after VIX_percentile fills)
# In-sample: 2005 - 2018
# OOS: 2019+
is_mask = df.index < '2019-01-01'
oos_mask = df.index >= '2019-01-01'

df_is = df[is_mask].copy()
df_oos = df[oos_mask].copy()

print(f"  In-sample: {df_is.index[0].date()} to {df_is.index[-1].date()}, N={len(df_is)}")
print(f"  OOS: {df_oos.index[0].date()} to {df_oos.index[-1].date()}, N={len(df_oos)}")

returns_is = df_is['ret'].values

# Candidate exogenous (use names that don't require VIX9D for now)
exog_candidates_basic = ['VIX_sq', 'VIX_level', 'log_VIX', 'VIX_change', 'VIX_percentile']

# First: Estimate pooled (no threshold) baseline models
print("\n  --- Pooled (no threshold) models ---")
pooled_results = {}

# Pooled GJR (no exog)
params_gjr, ll_gjr, conv_gjr, h_gjr = estimate_gjr_x(returns_is)
bic_gjr = compute_bic(ll_gjr, 5, len(returns_is)) if ll_gjr else np.inf
qlike_gjr = compute_qlike(df_is['r_sq'].values, h_gjr) if h_gjr is not None else np.inf
print(f"  GJR:     BIC={bic_gjr:.1f}, QLIKE={qlike_gjr:.4f}, conv={conv_gjr}")
if params_gjr is not None:
    print(f"           w={params_gjr[1]:.2e}, a={params_gjr[2]:.4f}, g={params_gjr[3]:.4f}, "
          f"b={params_gjr[4]:.4f}, persist={params_gjr[2]+params_gjr[3]/2+params_gjr[4]:.4f}")
pooled_results['GJR'] = {
    'params': params_gjr.tolist() if params_gjr is not None else None,
    'bic': bic_gjr, 'qlike': qlike_gjr, 'loglik': ll_gjr, 'h': h_gjr
}

# Pooled GJR-X with each exogenous variable
for exog_name in exog_candidates_basic:
    exog_vals = df_is[exog_name].values.reshape(-1, 1)
    params_x, ll_x, conv_x, h_x = estimate_gjr_x(returns_is, exog=exog_vals)
    bic_x = compute_bic(ll_x, 6, len(returns_is)) if ll_x else np.inf
    qlike_x = compute_qlike(df_is['r_sq'].values, h_x) if h_x is not None else np.inf
    delta_str = f"d={params_x[5]:.2e}" if params_x is not None else "d=NA"
    print(f"  GJR+{exog_name:15s}: BIC={bic_x:.1f}, QLIKE={qlike_x:.4f}, {delta_str}, conv={conv_x}")
    pooled_results[f'GJR+{exog_name}'] = {
        'params': params_x.tolist() if params_x is not None else None,
        'bic': bic_x, 'qlike': qlike_x, 'loglik': ll_x, 'h': h_x
    }

# Also test VIX9D_sq if data available
if df_is['VIX9D'].notna().sum() > 500:
    # Use subset where VIX9D is available
    vix9d_mask = df_is['VIX9D'].notna()
    ret_v9 = df_is.loc[vix9d_mask, 'ret'].values
    exog_v9 = df_is.loc[vix9d_mask, 'VIX9D_sq'].values.reshape(-1, 1)
    params_v9, ll_v9, conv_v9, h_v9 = estimate_gjr_x(ret_v9, exog=exog_v9)
    bic_v9 = compute_bic(ll_v9, 6, len(ret_v9)) if ll_v9 else np.inf
    qlike_v9 = compute_qlike(df_is.loc[vix9d_mask, 'r_sq'].values, h_v9) if h_v9 is not None else np.inf
    print(f"  GJR+VIX9D_sq (N={len(ret_v9)}): BIC={bic_v9:.1f}, QLIKE={qlike_v9:.4f}, conv={conv_v9}")
    pooled_results['GJR+VIX9D_sq'] = {
        'bic': bic_v9, 'qlike': qlike_v9, 'n_obs': len(ret_v9)
    }

# ============================================================
# 5. THRESHOLD MODEL ESTIMATION
# ============================================================
print("\n[5] Threshold Model Estimation")

threshold_results = {}
threshold_candidates = [15, 20, 25, 30, 35]

for c in threshold_candidates:
    print(f"\n  --- Threshold c={c} (VIX) ---")

    # Split by lagged VIX (no lookahead: use VIX_{t-1} to determine regime at t)
    vix_lagged = df_is['VIX'].shift(1)
    regime_low = vix_lagged <= c
    regime_high = vix_lagged > c

    # Remove first row (NaN from shift)
    regime_low = regime_low.iloc[1:]
    regime_high = regime_high.iloc[1:]

    n_low = regime_low.sum()
    n_high = regime_high.sum()

    if n_low < 252 or n_high < 100:
        print(f"    Skipped: insufficient data (low={n_low}, high={n_high})")
        continue

    print(f"    Regime sizes: Low={n_low}, High={n_high}")

    # Estimate GJR in each regime
    ret_low = df_is['ret'].iloc[1:][regime_low].values
    ret_high = df_is['ret'].iloc[1:][regime_high].values

    # --- Low regime ---
    params_low, ll_low, conv_low, h_low = estimate_gjr_x(ret_low)
    bic_low_base = compute_bic(ll_low, 5, len(ret_low)) if ll_low else np.inf

    # --- High regime ---
    params_high, ll_high, conv_high, h_high = estimate_gjr_x(ret_high)
    bic_high_base = compute_bic(ll_high, 5, len(ret_high)) if ll_high else np.inf

    if params_low is not None and params_high is not None:
        persist_low = params_low[2] + params_low[3]/2 + params_low[4]
        persist_high = params_high[2] + params_high[3]/2 + params_high[4]
        print(f"    Low:  w={params_low[1]:.2e}, a={params_low[2]:.4f}, g={params_low[3]:.4f}, "
              f"b={params_low[4]:.4f}, persist={persist_low:.4f}")
        print(f"    High: w={params_high[1]:.2e}, a={params_high[2]:.4f}, g={params_high[3]:.4f}, "
              f"b={params_high[4]:.4f}, persist={persist_high:.4f}")

    # BIC for combined threshold model (10 params: 5 per regime + threshold)
    combined_ll = (ll_low or 0) + (ll_high or 0)
    combined_bic = compute_bic(combined_ll, 11, len(returns_is) - 1)  # 5+5+1(threshold)
    print(f"    Combined BIC={combined_bic:.1f} (vs pooled GJR BIC={bic_gjr:.1f})")

    # --- Variable selection per regime ---
    best_low_exog = None
    best_low_bic = bic_low_base
    best_high_exog = None
    best_high_bic = bic_high_base

    for exog_name in exog_candidates_basic:
        # Low regime with exog
        exog_low = df_is[exog_name].iloc[1:][regime_low].values.reshape(-1, 1)
        p_lx, ll_lx, c_lx, h_lx = estimate_gjr_x(ret_low, exog=exog_low)
        bic_lx = compute_bic(ll_lx, 6, len(ret_low)) if ll_lx else np.inf
        if bic_lx < best_low_bic:
            best_low_bic = bic_lx
            best_low_exog = exog_name

        # High regime with exog
        exog_high = df_is[exog_name].iloc[1:][regime_high].values.reshape(-1, 1)
        p_hx, ll_hx, c_hx, h_hx = estimate_gjr_x(ret_high, exog=exog_high)
        bic_hx = compute_bic(ll_hx, 6, len(ret_high)) if ll_hx else np.inf
        if bic_hx < best_high_bic:
            best_high_bic = bic_hx
            best_high_exog = exog_name

    print(f"    Best low exog:  {best_low_exog or 'NONE'} (BIC: {bic_low_base:.1f} -> {best_low_bic:.1f})")
    print(f"    Best high exog: {best_high_exog or 'NONE'} (BIC: {bic_high_base:.1f} -> {best_high_bic:.1f})")

    threshold_results[c] = {
        'n_low': int(n_low), 'n_high': int(n_high),
        'params_low': params_low.tolist() if params_low is not None else None,
        'params_high': params_high.tolist() if params_high is not None else None,
        'conv_low': conv_low, 'conv_high': conv_high,
        'bic_low_base': bic_low_base, 'bic_high_base': bic_high_base,
        'bic_combined': combined_bic,
        'bic_pooled_gjr': bic_gjr,
        'best_low_exog': best_low_exog,
        'best_high_exog': best_high_exog,
        'best_low_bic': best_low_bic,
        'best_high_bic': best_high_bic,
        'loglik_low': ll_low, 'loglik_high': ll_high,
        'loglik_combined': combined_ll,
    }

# Find optimal threshold by combined BIC
optimal_c = min(threshold_results.keys(),
                key=lambda c: threshold_results[c]['bic_combined'])
print(f"\n  Optimal threshold (by BIC): c={optimal_c}")
print(f"    Combined BIC: {threshold_results[optimal_c]['bic_combined']:.1f}")
print(f"    Pooled GJR BIC: {bic_gjr:.1f}")
print(f"    BIC improvement: {bic_gjr - threshold_results[optimal_c]['bic_combined']:.1f}")

# ============================================================
# 6. LR TEST FOR THRESHOLD SIGNIFICANCE
# ============================================================
print("\n[6] Likelihood Ratio Test for Threshold Effect")

# H0: No threshold (pooled model) vs H1: Threshold model
for c in threshold_results:
    if threshold_results[c]['loglik_combined'] is not None and ll_gjr is not None:
        lr_stat = 2 * (threshold_results[c]['loglik_combined'] - ll_gjr)
        # Under H0, LR ~ chi2 with 5 df (5 extra params in high regime)
        # But threshold parameter is not identified under H0 (Davies 1977/1987)
        # Conservative: use chi2 with 6 df
        p_val = 1 - chi2.cdf(lr_stat, df=6) if lr_stat > 0 else 1.0
        print(f"  c={c}: LR={lr_stat:.2f}, p(chi2_6)={p_val:.4f} {'***' if p_val < 0.01 else '**' if p_val < 0.05 else 'NS'}")
        threshold_results[c]['lr_stat'] = lr_stat
        threshold_results[c]['lr_pvalue'] = p_val

# ============================================================
# 7. OUT-OF-SAMPLE EVALUATION
# ============================================================
print("\n[7] Out-of-Sample Evaluation (rolling window)")
print(f"    OOS period: {df_oos.index[0].date()} to {df_oos.index[-1].date()}")
print(f"    Window: 2000, Refit every: 63 days")

WINDOW = 2000
REFIT_EVERY = 63

# Prepare full data arrays
full_ret = df['ret'].values
full_r_sq = df['r_sq'].values
full_vix = df['VIX'].values

# Candidate exog arrays for full data
exog_arrays = {
    'VIX_sq': df['VIX_sq'].values,
    'VIX_level': df['VIX_level'].values,
    'log_VIX': df['log_VIX'].values,
    'VIX_change': df['VIX_change'].values,
    'VIX_percentile': df['VIX_percentile'].values,
}

oos_start_idx = df.index.get_loc(df_oos.index[0])
n_total = len(df)
n_oos = n_total - oos_start_idx

# Storage for OOS predictions
h_oos_gjr = np.full(n_oos, np.nan)           # Plain GJR
h_oos_gjr_vix_sq = np.full(n_oos, np.nan)    # GJR + VIX^2 (A4f equivalent)
h_oos_threshold = np.full(n_oos, np.nan)      # Threshold GJR
h_oos_threshold_x = np.full(n_oos, np.nan)    # Threshold GJR-X (best exog per regime)

# Use optimal threshold from in-sample
c_opt = optimal_c
print(f"    Using threshold c={c_opt}")

# Determine best exog for threshold model
best_low_exog_name = threshold_results[c_opt].get('best_low_exog')
best_high_exog_name = threshold_results[c_opt].get('best_high_exog')
print(f"    Low regime exog: {best_low_exog_name or 'NONE'}")
print(f"    High regime exog: {best_high_exog_name or 'NONE'}")

last_refit = -REFIT_EVERY  # force refit on first iteration

# Cached parameters
cached_gjr_params = None
cached_gjr_vix_params = None
cached_low_params = None
cached_high_params = None
cached_low_x_params = None
cached_high_x_params = None

for i in range(n_oos):
    t = oos_start_idx + i

    # Refit?
    if i - last_refit >= REFIT_EVERY or i == 0:
        last_refit = i
        train_start = max(0, t - WINDOW)
        train_ret = full_ret[train_start:t]
        train_vix = full_vix[train_start:t]

        if len(train_ret) < 500:
            continue

        # 1. Plain GJR
        p, ll, conv, h = estimate_gjr_x(train_ret)
        if conv and p is not None:
            cached_gjr_params = p

        # 2. GJR + VIX^2
        train_exog_vix = exog_arrays['VIX_sq'][train_start:t].reshape(-1, 1)
        p, ll, conv, h = estimate_gjr_x(train_ret, exog=train_exog_vix)
        if conv and p is not None:
            cached_gjr_vix_params = p

        # 3. Threshold GJR (split by lagged VIX)
        vix_lag_train = np.roll(train_vix, 1)
        vix_lag_train[0] = train_vix[0]
        mask_low = vix_lag_train <= c_opt
        mask_high = vix_lag_train > c_opt

        if mask_low.sum() >= 100 and mask_high.sum() >= 50:
            # Low regime
            p, ll, conv, h = estimate_gjr_x(train_ret[mask_low])
            if conv and p is not None:
                cached_low_params = p

            # High regime
            p, ll, conv, h = estimate_gjr_x(train_ret[mask_high])
            if conv and p is not None:
                cached_high_params = p

            # 4. Threshold GJR-X
            if best_low_exog_name:
                exog_low_train = exog_arrays[best_low_exog_name][train_start:t][mask_low].reshape(-1, 1)
                p, ll, conv, h = estimate_gjr_x(train_ret[mask_low], exog=exog_low_train)
                if conv and p is not None:
                    cached_low_x_params = p
            else:
                cached_low_x_params = cached_low_params

            if best_high_exog_name:
                exog_high_train = exog_arrays[best_high_exog_name][train_start:t][mask_high].reshape(-1, 1)
                p, ll, conv, h = estimate_gjr_x(train_ret[mask_high], exog=exog_high_train)
                if conv and p is not None:
                    cached_high_x_params = p
            else:
                cached_high_x_params = cached_high_params

        if i % (REFIT_EVERY * 3) == 0:
            print(f"    Refit at OOS day {i}/{n_oos} (t={t})")

    # One-step-ahead forecast using h[t] = f(h[t-1], e^2[t-1])
    # For proper OOS: use previous day's information only
    if t < 2:
        continue

    eps_prev = full_ret[t-1] - (cached_gjr_params[0] if cached_gjr_params is not None else 0)
    ind_neg = 1.0 if eps_prev < 0 else 0.0

    # 1. Plain GJR
    if cached_gjr_params is not None:
        mu, omega, alpha, gamma_p, beta = cached_gjr_params[:5]
        if i == 0:
            h_prev = np.var(full_ret[max(0,t-500):t])
        else:
            h_prev = h_oos_gjr[i-1] if not np.isnan(h_oos_gjr[i-1]) else np.var(full_ret[max(0,t-500):t])
        h_oos_gjr[i] = omega + alpha * eps_prev**2 + gamma_p * eps_prev**2 * ind_neg + beta * h_prev
        h_oos_gjr[i] = max(h_oos_gjr[i], 1e-10)

    # 2. GJR + VIX^2
    if cached_gjr_vix_params is not None:
        mu, omega, alpha, gamma_p, beta, delta = cached_gjr_vix_params[:6]
        eps_prev2 = full_ret[t-1] - mu
        if i == 0:
            h_prev = np.var(full_ret[max(0,t-500):t])
        else:
            h_prev = h_oos_gjr_vix_sq[i-1] if not np.isnan(h_oos_gjr_vix_sq[i-1]) else np.var(full_ret[max(0,t-500):t])
        h_oos_gjr_vix_sq[i] = (omega + alpha * eps_prev2**2 + gamma_p * eps_prev2**2 * ind_neg
                                + beta * h_prev + delta * exog_arrays['VIX_sq'][t-1])
        h_oos_gjr_vix_sq[i] = max(h_oos_gjr_vix_sq[i], 1e-10)

    # 3. Threshold GJR (determine regime from lagged VIX)
    vix_prev = full_vix[t-1]  # VIX from previous day (no lookahead)

    if vix_prev <= c_opt:
        params_use = cached_low_params
        params_use_x = cached_low_x_params
        exog_name_use = best_low_exog_name
    else:
        params_use = cached_high_params
        params_use_x = cached_high_x_params
        exog_name_use = best_high_exog_name

    if params_use is not None:
        mu, omega, alpha, gamma_p, beta = params_use[:5]
        eps_prev3 = full_ret[t-1] - mu
        if i == 0:
            h_prev = np.var(full_ret[max(0,t-500):t])
        else:
            h_prev = h_oos_threshold[i-1] if not np.isnan(h_oos_threshold[i-1]) else np.var(full_ret[max(0,t-500):t])
        h_oos_threshold[i] = omega + alpha * eps_prev3**2 + gamma_p * eps_prev3**2 * ind_neg + beta * h_prev
        h_oos_threshold[i] = max(h_oos_threshold[i], 1e-10)

    # 4. Threshold GJR-X
    if params_use_x is not None:
        mu, omega, alpha, gamma_p, beta = params_use_x[:5]
        eps_prev4 = full_ret[t-1] - mu
        if i == 0:
            h_prev = np.var(full_ret[max(0,t-500):t])
        else:
            h_prev = h_oos_threshold_x[i-1] if not np.isnan(h_oos_threshold_x[i-1]) else np.var(full_ret[max(0,t-500):t])
        h_val = omega + alpha * eps_prev4**2 + gamma_p * eps_prev4**2 * ind_neg + beta * h_prev
        if exog_name_use and len(params_use_x) > 5:
            h_val += params_use_x[5] * exog_arrays[exog_name_use][t-1]
        h_oos_threshold_x[i] = max(h_val, 1e-10)

# ============================================================
# 8. OOS QLIKE AND DM TESTS
# ============================================================
print("\n[8] OOS Evaluation Results")

actual_oos_r_sq = full_r_sq[oos_start_idx:]

# Compute QLIKE for each model
models_oos = {
    'GJR': h_oos_gjr,
    'GJR+VIX_sq': h_oos_gjr_vix_sq,
    'Threshold_GJR': h_oos_threshold,
    'Threshold_GJR-X': h_oos_threshold_x,
}

qlike_results = {}
for name, h_pred in models_oos.items():
    valid = ~np.isnan(h_pred)
    if valid.sum() < 100:
        print(f"  {name}: insufficient valid predictions ({valid.sum()})")
        qlike_results[name] = np.inf
        continue
    qlike_val = compute_qlike(actual_oos_r_sq[valid], h_pred[valid])
    qlike_results[name] = qlike_val
    print(f"  {name:20s}: QLIKE={qlike_val:.6f} (N_valid={valid.sum()})")

# DM tests (vs GJR baseline)
print("\n  DM Tests (vs GJR baseline):")
dm_results = {}
loss_gjr = actual_oos_r_sq / h_oos_gjr + np.log(h_oos_gjr)
for name, h_pred in models_oos.items():
    if name == 'GJR':
        continue
    valid = ~np.isnan(h_pred) & ~np.isnan(h_oos_gjr)
    if valid.sum() < 100:
        continue
    loss_other = actual_oos_r_sq / h_pred + np.log(h_pred)
    t_stat, p_val = dm_test(loss_other[valid], loss_gjr[valid])
    sig = '***' if abs(t_stat) > 3.0 else '**' if abs(t_stat) > 2.0 else '*' if abs(t_stat) > 1.65 else 'NS'
    print(f"  {name:20s} vs GJR: DM t={t_stat:.3f}, p={p_val:.4f} {sig}")
    dm_results[f'{name}_vs_GJR'] = {'t_stat': t_stat, 'p_value': p_val}

# DM: Threshold models vs GJR+VIX_sq (A4f equivalent)
print("\n  DM Tests (vs GJR+VIX_sq):")
loss_a4f = actual_oos_r_sq / h_oos_gjr_vix_sq + np.log(h_oos_gjr_vix_sq)
for name in ['Threshold_GJR', 'Threshold_GJR-X']:
    h_pred = models_oos[name]
    valid = ~np.isnan(h_pred) & ~np.isnan(h_oos_gjr_vix_sq)
    if valid.sum() < 100:
        continue
    loss_other = actual_oos_r_sq / h_pred + np.log(h_pred)
    t_stat, p_val = dm_test(loss_other[valid], loss_a4f[valid])
    sig = '***' if abs(t_stat) > 3.0 else '**' if abs(t_stat) > 2.0 else '*' if abs(t_stat) > 1.65 else 'NS'
    print(f"  {name:20s} vs A4f: DM t={t_stat:.3f}, p={p_val:.4f} {sig}")
    dm_results[f'{name}_vs_A4f'] = {'t_stat': t_stat, 'p_value': p_val}

# ============================================================
# 9. VaR BACKTEST (5% and 1%)
# ============================================================
print("\n[9] VaR Backtest")

def var_backtest(returns_oos, h_oos, alpha_level=0.05):
    """Simple VaR backtest. VaR = mu + z_alpha * sqrt(h)"""
    valid = ~np.isnan(h_oos)
    r = returns_oos[valid]
    h = h_oos[valid]
    n = len(r)

    z_alpha = norm.ppf(alpha_level)
    var_series = z_alpha * np.sqrt(h)  # assuming mean ~ 0

    violations = (r < var_series).sum()
    viol_rate = violations / n

    # Kupiec LR test (POF test)
    if violations == 0 or violations == n:
        lr_kupiec = np.inf
        p_kupiec = 0
    else:
        p_hat = violations / n
        lr_kupiec = 2 * (violations * np.log(p_hat / alpha_level)
                         + (n - violations) * np.log((1 - p_hat) / (1 - alpha_level)))
        lr_kupiec = max(lr_kupiec, 0)
        p_kupiec = 1 - chi2.cdf(lr_kupiec, 1)

    # Basel traffic light (250 day window approximation)
    # Green: <= 4 violations in 250 days
    # Yellow: 5-9
    # Red: >= 10
    expected = alpha_level * n

    return {
        'violations': int(violations),
        'violation_rate': viol_rate,
        'expected': expected,
        'kupiec_lr': lr_kupiec,
        'kupiec_p': p_kupiec,
        'kupiec_pass': p_kupiec > 0.05,
        'n': n
    }

returns_oos = full_ret[oos_start_idx:]
var_results = {}
for name, h_pred in models_oos.items():
    for alpha in [0.05, 0.01]:
        result = var_backtest(returns_oos, h_pred, alpha)
        key = f"{name}_VaR{int(alpha*100)}%"
        var_results[key] = result
        pass_str = "PASS" if result['kupiec_pass'] else "FAIL"
        print(f"  {name:20s} VaR {alpha:.0%}: violations={result['violations']}/{result['n']} "
              f"({result['violation_rate']:.3f} vs {alpha}), Kupiec p={result['kupiec_p']:.4f} [{pass_str}]")

# ============================================================
# 10. PARAMETER COMPARISON TABLE
# ============================================================
print("\n[10] Parameter Comparison: Regime-Specific vs Pooled")

opt_res = threshold_results.get(c_opt, {})
param_table = {
    'pooled': {
        'omega': params_gjr[1] if params_gjr is not None else None,
        'alpha': params_gjr[2] if params_gjr is not None else None,
        'gamma': params_gjr[3] if params_gjr is not None else None,
        'beta': params_gjr[4] if params_gjr is not None else None,
        'persistence': (params_gjr[2] + params_gjr[3]/2 + params_gjr[4]) if params_gjr is not None else None,
    }
}

if opt_res.get('params_low'):
    pl = opt_res['params_low']
    param_table['low_regime'] = {
        'omega': pl[1], 'alpha': pl[2], 'gamma': pl[3], 'beta': pl[4],
        'persistence': pl[2] + pl[3]/2 + pl[4],
        'n_obs': opt_res['n_low']
    }

if opt_res.get('params_high'):
    ph = opt_res['params_high']
    param_table['high_regime'] = {
        'omega': ph[1], 'alpha': ph[2], 'gamma': ph[3], 'beta': ph[4],
        'persistence': ph[2] + ph[3]/2 + ph[4],
        'n_obs': opt_res['n_high']
    }

print(f"  {'Param':<12} {'Pooled':>12} {'Low (VIX<={c_opt})':>18} {'High (VIX>{c_opt})':>18}")
print(f"  {'-'*60}")
for param_name in ['omega', 'alpha', 'gamma', 'beta', 'persistence']:
    pooled_val = param_table['pooled'].get(param_name)
    low_val = param_table.get('low_regime', {}).get(param_name)
    high_val = param_table.get('high_regime', {}).get(param_name)

    fmt = '.6f' if param_name == 'omega' else '.4f'
    pooled_str = f"{pooled_val:{fmt}}" if pooled_val is not None else "N/A"
    low_str = f"{low_val:{fmt}}" if low_val is not None else "N/A"
    high_str = f"{high_val:{fmt}}" if high_val is not None else "N/A"
    print(f"  {param_name:<12} {pooled_str:>12} {low_str:>18} {high_str:>18}")

# ============================================================
# 11. PLOTS
# ============================================================
print("\n[11] Generating plots...")

# Plot 1: Regime-specific parameters by threshold
fig, axes = plt.subplots(2, 2, figsize=(14, 10))
fig.suptitle('K1048: Threshold GARCH Parameters by VIX Threshold', fontsize=14)

param_names = ['alpha', 'gamma', 'beta', 'persistence']
for idx, pname in enumerate(param_names):
    ax = axes[idx // 2][idx % 2]
    lows = []
    highs = []
    pooled_val = param_table['pooled'].get(pname)

    for c in sorted(threshold_results.keys()):
        res = threshold_results[c]
        if res.get('params_low') and res.get('params_high'):
            pl = res['params_low']
            ph = res['params_high']
            if pname == 'alpha':
                lows.append(pl[2]); highs.append(ph[2])
            elif pname == 'gamma':
                lows.append(pl[3]); highs.append(ph[3])
            elif pname == 'beta':
                lows.append(pl[4]); highs.append(ph[4])
            elif pname == 'persistence':
                lows.append(pl[2] + pl[3]/2 + pl[4])
                highs.append(ph[2] + ph[3]/2 + ph[4])
        else:
            lows.append(np.nan); highs.append(np.nan)

    thresholds = sorted(threshold_results.keys())
    ax.plot(thresholds, lows, 'b-o', label='Low VIX regime', linewidth=2)
    ax.plot(thresholds, highs, 'r-s', label='High VIX regime', linewidth=2)
    if pooled_val is not None:
        ax.axhline(pooled_val, color='gray', linestyle='--', label='Pooled')
    ax.set_xlabel('VIX Threshold')
    ax.set_ylabel(pname)
    ax.set_title(pname.capitalize())
    ax.legend()
    ax.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig(os.path.join(BASE_DIR, 'k1048_regime_parameters.png'), dpi=150, bbox_inches='tight')
plt.close()
print("  Saved: k1048_regime_parameters.png")

# Plot 2: QLIKE by model
fig, ax = plt.subplots(figsize=(10, 6))
model_names = list(qlike_results.keys())
qlike_vals = [qlike_results[m] for m in model_names]
colors = ['#2196F3', '#4CAF50', '#FF9800', '#F44336']
bars = ax.bar(model_names, qlike_vals, color=colors[:len(model_names)])
ax.set_ylabel('QLIKE (lower is better)')
ax.set_title(f'K1048: OOS QLIKE Comparison (2019-2026, threshold c={c_opt})')
ax.grid(True, alpha=0.3, axis='y')

# Add value labels
for bar, val in zip(bars, qlike_vals):
    if val < 100:
        ax.text(bar.get_x() + bar.get_width()/2., bar.get_height() + 0.001,
                f'{val:.4f}', ha='center', va='bottom', fontsize=10)

plt.tight_layout()
plt.savefig(os.path.join(BASE_DIR, 'k1048_qlike_comparison.png'), dpi=150, bbox_inches='tight')
plt.close()
print("  Saved: k1048_qlike_comparison.png")

# ============================================================
# 12. SAVE RESULTS
# ============================================================
print("\n[12] Saving results...")

results = {
    'experiment_id': 'K1048',
    'title': 'Threshold GARCH-X with Variable Selection',
    'timestamp': datetime.now().isoformat(),
    'data_source': 'yfinance (SPY, ^VIX, ^VIX9D)',
    'data_period': f"{df.index[0].date()} to {df.index[-1].date()}",
    'n_total': len(df),
    'n_is': len(df_is),
    'n_oos': len(df_oos),
    'oos_start': '2019-01-01',
    'window': WINDOW,
    'refit_every': REFIT_EVERY,
    'seed': 42,

    'threshold_candidates': threshold_candidates,
    'optimal_threshold': optimal_c,
    'threshold_results': {str(k): {kk: vv for kk, vv in v.items()
                                    if kk not in ['h']}
                          for k, v in threshold_results.items()},

    'pooled_results': {
        'GJR': {
            'bic': pooled_results['GJR']['bic'],
            'qlike_is': pooled_results['GJR']['qlike'],
            'loglik': pooled_results['GJR']['loglik'],
            'params': pooled_results['GJR']['params'],
        },
    },

    'oos_qlike': qlike_results,
    'oos_dm_tests': dm_results,
    'oos_var_backtest': var_results,

    'parameter_comparison': param_table,

    'key_findings': [],
    'references': [
        'Gonzalez-Rivera (1998, JBES) - Threshold GARCH',
        'Chen & So (2006) - Threshold heteroscedastic models',
        'So, Chen, Liu (2006, JRSS-C) - SSVS for GARCH',
        'Patton (2011) - QLIKE loss',
        'K1031: SSVS VIX9D^2 PIP=1.000',
        'K813: STGARCH 11-param OOS DM=-0.11 NS',
        'K1019: MS(2)-GJR DM=-3.20 sig but lost to A4f',
    ],
}

# Generate key findings
findings = []

# Finding 1: threshold significance
if optimal_c in threshold_results:
    lr = threshold_results[optimal_c].get('lr_stat', 0)
    lrp = threshold_results[optimal_c].get('lr_pvalue', 1)
    findings.append(
        f"LR test for threshold at VIX={optimal_c}: LR={lr:.2f}, p={lrp:.4f}. "
        f"{'Threshold effect significant.' if lrp < 0.05 else 'Threshold effect NOT significant.'}"
    )

# Finding 2: parameter differences
if 'low_regime' in param_table and 'high_regime' in param_table:
    g_low = param_table['low_regime'].get('gamma', 0)
    g_high = param_table['high_regime'].get('gamma', 0)
    findings.append(
        f"Gamma (leverage): Low VIX={g_low:.4f}, High VIX={g_high:.4f}. "
        f"{'Higher leverage effect in high VIX regime.' if g_high > g_low else 'Higher leverage in low VIX regime.'}"
    )

# Finding 3: variable selection differs by regime
if optimal_c in threshold_results:
    low_exog = threshold_results[optimal_c].get('best_low_exog', 'NONE')
    high_exog = threshold_results[optimal_c].get('best_high_exog', 'NONE')
    findings.append(
        f"Best exog variable differs by regime: Low={low_exog}, High={high_exog}. "
        f"{'Same variable selected.' if low_exog == high_exog else 'Different variables optimal in different regimes.'}"
    )

# Finding 4: OOS performance
best_oos = min(qlike_results, key=qlike_results.get) if qlike_results else 'N/A'
findings.append(f"Best OOS model by QLIKE: {best_oos} ({qlike_results.get(best_oos, 'N/A'):.6f})")

# Finding 5: vs A4f
a4f_dm = dm_results.get('Threshold_GJR-X_vs_A4f', {})
if a4f_dm:
    findings.append(
        f"Threshold GJR-X vs A4f (GJR+VIX^2): DM t={a4f_dm.get('t_stat', 0):.3f}. "
        f"{'Threshold model significantly better.' if a4f_dm.get('t_stat', 0) < -3.0 else 'No significant improvement over A4f.'}"
    )

results['key_findings'] = findings

# Save
results_path = os.path.join(BASE_DIR, 'k1048_results.json')
with open(results_path, 'w') as f:
    json.dump(results, f, indent=2, default=str, ensure_ascii=False)
print(f"  Saved: {results_path}")

# ============================================================
# 13. SUMMARY
# ============================================================
print("\n" + "=" * 70)
print("K1048 SUMMARY")
print("=" * 70)
for i, finding in enumerate(findings, 1):
    print(f"  {i}. {finding}")

print("\n  Conclusion:")
print(f"  - Optimal threshold: VIX = {optimal_c}")
print(f"  - Threshold model BIC vs pooled: {threshold_results[optimal_c]['bic_combined']:.1f} vs {bic_gjr:.1f}")
bic_diff = bic_gjr - threshold_results[optimal_c]['bic_combined']
print(f"  - BIC improvement: {bic_diff:.1f} {'(threshold preferred)' if bic_diff > 0 else '(pooled preferred)'}")
print(f"  - Best OOS QLIKE: {best_oos}")

if 'Threshold_GJR-X_vs_A4f' in dm_results:
    t = dm_results['Threshold_GJR-X_vs_A4f']['t_stat']
    print(f"  - Threshold GJR-X vs A4f: DM t={t:.3f} {'(sig)' if abs(t) > 3.0 else '(NS)'}")

print(f"\n  K813 lesson check: Threshold model has 10-12 params vs 5 (GJR).")
print(f"  Parsimony trade-off matters for OOS performance.")
print("\nDone!")
