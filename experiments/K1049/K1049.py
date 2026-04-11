#!/usr/bin/env python3
"""
K1049: HAR-RV 60-Day SPY Pilot — Proxy Comparison r² vs RV (PRELIMINARY)

Compares HAR-RV vs GJR-GARCH vs A4f-VIX² using BOTH r² and RV as evaluation proxies.
Tests whether the evaluation proxy matters for model ranking.

Data:
- 5-min SPY data: data/intraday/SPY_5min_YYYY-MM-DD.csv (60 files, Jan 14 - Apr 10, 2026)
- Pre-computed daily RV: data/intraday/SPY_daily_rv.csv
- Daily SPY/VIX: yfinance

References:
- Patton (2011): Proxy-robust QLIKE loss — rankings preserved regardless of proxy
- Corsi (2009): HAR-RV model
- Hansen & Lunde (2005): Realized variance as vol proxy
- Engle & Rangel (2008): A4f (Spline-GARCH with VIX)

PRELIMINARY: Only ~30 OOS days — far below 252-day minimum for definitive conclusions.
"""

import json
import os
import sys
import warnings
from datetime import datetime, timezone

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import numpy as np
import pandas as pd
from arch import arch_model

warnings.filterwarnings('ignore')
np.random.seed(42)

# ── Paths ──
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.abspath(os.path.join(BASE_DIR, '..', '..'))
# Data lives in main repo (not worktree), use absolute path
MAIN_REPO = '/Users/yhlai0911/Desktop/volpred-research'
DATA_DIR = os.path.join(MAIN_REPO, 'data', 'intraday')
OUTPUT_DIR = BASE_DIR

print("=" * 70)
print("K1049: HAR-RV 60-Day SPY Pilot — Proxy Comparison r² vs RV")
print("=" * 70)


# ═══════════════════════════════════════════════════════════════════════
# 1. LOAD DATA
# ═══════════════════════════════════════════════════════════════════════

print("\n[1] Loading data...")

# 1a. Load pre-computed daily RV from 5-min data
rv_df = pd.read_csv(os.path.join(DATA_DIR, 'SPY_daily_rv.csv'), index_col=0, parse_dates=True)
rv_df.columns = ['rv_5min']
rv_df.index.name = 'Date'
print(f"  Daily RV from 5-min data: {len(rv_df)} days ({rv_df.index[0].date()} to {rv_df.index[-1].date()})")

# 1b. Verify RV by recalculating from raw 5-min files for a few sample days
def calc_rv_from_file(filepath):
    """Calculate realized variance from 5-min data file."""
    df = pd.read_csv(filepath, header=[0, 1], index_col=0, parse_dates=True)
    # Flatten multi-level columns
    close_col = None
    for col in df.columns:
        if 'Close' in str(col) or 'Price' in str(col):
            close_col = col
            break
    if close_col is None:
        close_col = df.columns[0]
    prices = df[close_col].dropna()
    log_returns = np.log(prices / prices.shift(1)).dropna()
    return (log_returns ** 2).sum()

# Verify first 3 days
print("  Verifying RV calculation against raw files...")
verify_dates = rv_df.index[:3]
for dt in verify_dates:
    date_str = dt.strftime('%Y-%m-%d')
    fpath = os.path.join(DATA_DIR, f'SPY_5min_{date_str}.csv')
    if os.path.exists(fpath):
        rv_calc = calc_rv_from_file(fpath)
        rv_stored = rv_df.loc[dt, 'rv_5min']
        pct_diff = abs(rv_calc - rv_stored) / rv_stored * 100
        print(f"    {date_str}: stored={rv_stored:.6e}, calc={rv_calc:.6e}, diff={pct_diff:.2f}%")

# 1c. Load daily SPY and VIX data via yfinance
import yfinance as yf

# Get data starting well before our RV period for GARCH estimation (2000+ days)
start_date = '2015-01-01'
end_date = '2026-04-15'

spy_daily = yf.download('SPY', start=start_date, end=end_date, progress=False)
vix_daily = yf.download('^VIX', start=start_date, end=end_date, progress=False)

# Handle multi-level columns from yfinance
if isinstance(spy_daily.columns, pd.MultiIndex):
    spy_daily.columns = spy_daily.columns.get_level_values(0)
if isinstance(vix_daily.columns, pd.MultiIndex):
    vix_daily.columns = vix_daily.columns.get_level_values(0)

spy_close = spy_daily['Close'].squeeze()
vix_close = vix_daily['Close'].squeeze()

# Daily log returns
spy_returns = np.log(spy_close / spy_close.shift(1)).dropna()
# Squared returns as proxy
r_squared = spy_returns ** 2

print(f"  SPY daily returns: {len(spy_returns)} days ({spy_returns.index[0].date()} to {spy_returns.index[-1].date()})")
print(f"  VIX daily close: {len(vix_close)} days")

# 1d. Align all data: find common RV dates
rv_dates = rv_df.index
# Ensure all dates exist in daily data
common_dates = rv_dates[rv_dates.isin(spy_returns.index) & rv_dates.isin(vix_close.index)]
print(f"  Common dates (RV + daily): {len(common_dates)} days")

# Descriptive stats
print("\n  Descriptive Statistics:")
print(f"    Daily returns: mean={spy_returns.loc[common_dates].mean():.6f}, "
      f"std={spy_returns.loc[common_dates].std():.6f}")
print(f"    RV (5-min):    mean={rv_df.loc[common_dates, 'rv_5min'].mean():.6e}, "
      f"std={rv_df.loc[common_dates, 'rv_5min'].std():.6e}")
print(f"    r² (squared):  mean={r_squared.loc[common_dates].mean():.6e}, "
      f"std={r_squared.loc[common_dates].std():.6e}")
print(f"    VIX:           mean={vix_close.loc[common_dates].mean():.2f}, "
      f"std={vix_close.loc[common_dates].std():.2f}")


# ═══════════════════════════════════════════════════════════════════════
# 2. HAR-RV MODEL
# ═══════════════════════════════════════════════════════════════════════

print("\n[2] HAR-RV Model (Corsi 2009)...")
print("  RV_t = β₀ + β₁×RV_{t-1} + β₅×RV_{t-1:t-5} + β₂₂×RV_{t-1:t-22} + ε_t")

# Create HAR features for the RV series
rv_series = rv_df['rv_5min'].copy()
rv_series = rv_series.sort_index()

# HAR components: daily (lag 1), weekly (avg lag 1-5), monthly (avg lag 1-22)
def create_har_features(rv, date_idx):
    """Create HAR features for a given date index (position in rv_series)."""
    if date_idx < 22:
        return None, None, None
    rv_vals = rv.values
    rv_d = rv_vals[date_idx - 1]  # lag 1
    rv_w = np.mean(rv_vals[date_idx - 5:date_idx])  # avg of lag 1-5
    rv_m = np.mean(rv_vals[date_idx - 22:date_idx])  # avg of lag 1-22
    return rv_d, rv_w, rv_m


# For HAR, we need at least 22 past RV observations
# Split: first 30 days for initial estimation, rest for OOS
HAR_INITIAL_WINDOW = 30
n_rv = len(rv_series)

if n_rv < HAR_INITIAL_WINDOW + 5:
    print(f"  WARNING: Only {n_rv} RV days, need at least {HAR_INITIAL_WINDOW + 5} for meaningful OOS.")

# Determine OOS start
oos_start_idx = HAR_INITIAL_WINDOW
oos_dates_har = rv_series.index[oos_start_idx:]
print(f"  In-sample: first {HAR_INITIAL_WINDOW} days ({rv_series.index[0].date()} to {rv_series.index[HAR_INITIAL_WINDOW-1].date()})")
print(f"  Out-of-sample: {len(oos_dates_har)} days ({oos_dates_har[0].date()} to {oos_dates_har[-1].date()})")

# Expanding window HAR-RV estimation
har_forecasts = {}
har_betas_log = []

for t in range(oos_start_idx, n_rv):
    # Use all data up to t for estimation
    train_rv = rv_series.values[:t]
    n_train = len(train_rv)

    # Build regression data (need 22 lags)
    Y = []
    X = []
    for i in range(22, n_train):
        Y.append(train_rv[i])
        rv_d = train_rv[i - 1]
        rv_w = np.mean(train_rv[i - 5:i])
        rv_m = np.mean(train_rv[i - 22:i])
        X.append([1.0, rv_d, rv_w, rv_m])

    Y = np.array(Y)
    X = np.array(X)

    if len(Y) < 10:
        continue

    # OLS estimation
    try:
        beta = np.linalg.lstsq(X, Y, rcond=None)[0]
    except np.linalg.LinAlgError:
        continue

    # One-step-ahead forecast: use actual RV up to t
    rv_d_fcast = train_rv[t - 1]
    rv_w_fcast = np.mean(train_rv[t - 5:t])
    rv_m_fcast = np.mean(train_rv[t - 22:t])

    forecast = beta[0] + beta[1] * rv_d_fcast + beta[2] * rv_w_fcast + beta[3] * rv_m_fcast
    forecast = max(forecast, 1e-10)  # ensure positive

    date = rv_series.index[t]
    har_forecasts[date] = forecast

    if t == oos_start_idx:
        har_betas_log.append({
            'date': str(date.date()),
            'n_train': n_train,
            'beta_0': float(beta[0]),
            'beta_d': float(beta[1]),
            'beta_w': float(beta[2]),
            'beta_m': float(beta[3])
        })

har_forecast_series = pd.Series(har_forecasts)
print(f"  HAR-RV forecasts: {len(har_forecast_series)} days")
if len(har_betas_log) > 0:
    b = har_betas_log[0]
    print(f"  Initial betas: β₀={b['beta_0']:.6e}, β_d={b['beta_d']:.4f}, β_w={b['beta_w']:.4f}, β_m={b['beta_m']:.4f}")


# ═══════════════════════════════════════════════════════════════════════
# 3. GJR-GARCH MODEL
# ═══════════════════════════════════════════════════════════════════════

print("\n[3] GJR-GARCH(1,1) Model...")

# Scale returns to percentage for arch package
ret_pct = spy_returns * 100

# Determine OOS dates: same as HAR OOS dates for fair comparison
oos_dates_common = har_forecast_series.index
print(f"  OOS dates to forecast: {len(oos_dates_common)} ({oos_dates_common[0].date()} to {oos_dates_common[-1].date()})")

# For each OOS date, estimate GJR on all available daily data up to that date
# Use a 2000-day rolling window (or all available if < 2000)
GARCH_WINDOW = 2000

gjr_forecasts = {}
gjr_params_log = []

for date in oos_dates_common:
    # Get all returns up to (not including) this date
    train_returns = ret_pct[ret_pct.index < date]
    if len(train_returns) < 500:
        print(f"  WARNING: Only {len(train_returns)} returns for GJR at {date.date()}")
        continue

    # Use last GARCH_WINDOW observations
    if len(train_returns) > GARCH_WINDOW:
        train_returns = train_returns.iloc[-GARCH_WINDOW:]

    try:
        model = arch_model(train_returns, vol='GARCH', p=1, o=1, q=1, dist='normal')
        result = model.fit(disp='off', show_warning=False)

        # One-step-ahead forecast (returns variance in percentage-squared units)
        fcast = result.forecast(horizon=1, reindex=False)
        var_pct = fcast.variance.values[-1, 0]
        # Convert from percentage to decimal: (pct^2) / 10000
        var_decimal = var_pct / 10000.0

        gjr_forecasts[date] = max(var_decimal, 1e-10)

        if len(gjr_params_log) == 0:
            params = result.params
            gjr_params_log.append({
                'date': str(date.date()),
                'omega': float(params.get('omega', 0)),
                'alpha': float(params.get('alpha[1]', 0)),
                'gamma': float(params.get('gamma[1]', 0)),
                'beta': float(params.get('beta[1]', 0)),
                'persistence': float(params.get('alpha[1]', 0) + params.get('gamma[1]', 0)/2 + params.get('beta[1]', 0))
            })
    except Exception as e:
        print(f"  GJR failed at {date.date()}: {e}")
        continue

gjr_forecast_series = pd.Series(gjr_forecasts)
print(f"  GJR-GARCH forecasts: {len(gjr_forecast_series)} days")
if len(gjr_params_log) > 0:
    p = gjr_params_log[0]
    print(f"  Initial params: ω={p['omega']:.6f}, α={p['alpha']:.4f}, γ={p['gamma']:.4f}, β={p['beta']:.4f}, persistence={p['persistence']:.4f}")


# ═══════════════════════════════════════════════════════════════════════
# 4. A4f-VIX² MODEL (Engle & Rangel 2008 style)
# ═══════════════════════════════════════════════════════════════════════

print("\n[4] A4f-VIX² Model (Multiplicative GARCH with VIX component)...")
print("  τ_t = θ₀ + θ₁×VIX²_{t-1}")
print("  u_t = r_t / √τ_t")
print("  g_t = GJR(1,1) on u_t")
print("  σ²_t = τ_t × g_t")

a4f_forecasts = {}
a4f_params_log = []

for date in oos_dates_common:
    # Get all returns and VIX up to (not including) this date
    train_mask = spy_returns.index < date
    train_ret = spy_returns[train_mask]
    train_vix = vix_close.reindex(train_ret.index).ffill().dropna()

    # Align
    common_idx = train_ret.index.intersection(train_vix.index)
    if len(common_idx) < 500:
        continue

    train_ret = train_ret.loc[common_idx]
    train_vix = train_vix.loc[common_idx]

    # Use last GARCH_WINDOW
    if len(train_ret) > GARCH_WINDOW:
        train_ret = train_ret.iloc[-GARCH_WINDOW:]
        train_vix = train_vix.iloc[-GARCH_WINDOW:]

    # Step 1: Estimate τ_t = θ₀ + θ₁ × VIX²_{t-1}
    # VIX is annualized vol in %, so VIX²/252/10000 ≈ daily variance
    vix_sq = (train_vix / 100) ** 2 / 252  # daily variance scale
    vix_sq_lag = vix_sq.shift(1).dropna()
    r_sq_train = (train_ret ** 2).reindex(vix_sq_lag.index).dropna()
    vix_sq_lag = vix_sq_lag.reindex(r_sq_train.index)

    # OLS: r²_t = θ₀ + θ₁ × VIX²_{t-1}/252
    X_tau = np.column_stack([np.ones(len(vix_sq_lag)), vix_sq_lag.values])
    Y_tau = r_sq_train.values

    try:
        theta = np.linalg.lstsq(X_tau, Y_tau, rcond=None)[0]
    except np.linalg.LinAlgError:
        continue

    theta[0] = max(theta[0], 1e-10)
    if theta[1] < 0:
        theta[1] = 0  # VIX component should be non-negative

    # Compute τ for training data
    tau_train = theta[0] + theta[1] * vix_sq_lag.values
    tau_train = np.maximum(tau_train, 1e-10)

    # Step 2: Standardized returns u_t = r_t / sqrt(τ_t)
    aligned_ret = train_ret.reindex(vix_sq_lag.index).values
    u_train = aligned_ret / np.sqrt(tau_train)
    u_series = pd.Series(u_train * 100, index=vix_sq_lag.index)  # percentage scale for arch

    # Step 3: GJR-GARCH on u_t
    try:
        model_u = arch_model(u_series, vol='GARCH', p=1, o=1, q=1, dist='normal')
        result_u = model_u.fit(disp='off', show_warning=False)

        # One-step forecast of g_t+1
        fcast_u = result_u.forecast(horizon=1, reindex=False)
        g_var_pct = fcast_u.variance.values[-1, 0]
        g_var = g_var_pct / 10000.0  # decimal scale

        # Forecast τ_{t+1} using VIX at date-1
        # Get VIX on the last available day before forecast date
        vix_for_fcast = vix_close[vix_close.index < date]
        if len(vix_for_fcast) == 0:
            continue
        last_vix = vix_for_fcast.iloc[-1]
        vix_sq_fcast = (last_vix / 100) ** 2 / 252
        tau_fcast = theta[0] + theta[1] * vix_sq_fcast
        tau_fcast = max(tau_fcast, 1e-10)

        # Total variance forecast: σ² = τ × g
        sigma2_fcast = tau_fcast * g_var

        a4f_forecasts[date] = max(sigma2_fcast, 1e-10)

        if len(a4f_params_log) == 0:
            params_u = result_u.params
            a4f_params_log.append({
                'date': str(date.date()),
                'theta_0': float(theta[0]),
                'theta_1': float(theta[1]),
                'gjr_omega': float(params_u.get('omega', 0)),
                'gjr_alpha': float(params_u.get('alpha[1]', 0)),
                'gjr_gamma': float(params_u.get('gamma[1]', 0)),
                'gjr_beta': float(params_u.get('beta[1]', 0)),
                'tau_fcast': float(tau_fcast),
                'g_fcast': float(g_var)
            })
    except Exception as e:
        print(f"  A4f failed at {date.date()}: {e}")
        continue

a4f_forecast_series = pd.Series(a4f_forecasts)
print(f"  A4f-VIX² forecasts: {len(a4f_forecast_series)} days")
if len(a4f_params_log) > 0:
    p = a4f_params_log[0]
    print(f"  Initial params: θ₀={p['theta_0']:.6e}, θ₁={p['theta_1']:.4f}")
    print(f"  GJR on u: ω={p['gjr_omega']:.6f}, α={p['gjr_alpha']:.4f}, γ={p['gjr_gamma']:.4f}, β={p['gjr_beta']:.4f}")


# ═══════════════════════════════════════════════════════════════════════
# 5. EVALUATION: DUAL-PROXY COMPARISON
# ═══════════════════════════════════════════════════════════════════════

print("\n[5] Evaluation: Dual-Proxy Comparison...")

# Find common forecast dates across all three models
common_fcast_dates = har_forecast_series.index.intersection(
    gjr_forecast_series.index
).intersection(
    a4f_forecast_series.index
).intersection(
    r_squared.index
).intersection(
    rv_df.index
)

print(f"  Common forecast dates: {len(common_fcast_dates)}")
if len(common_fcast_dates) == 0:
    print("  ERROR: No common dates. Exiting.")
    sys.exit(1)

print(f"  Period: {common_fcast_dates[0].date()} to {common_fcast_dates[-1].date()}")

# Extract aligned forecasts and targets
har_f = har_forecast_series.loc[common_fcast_dates].values
gjr_f = gjr_forecast_series.loc[common_fcast_dates].values
a4f_f = a4f_forecast_series.loc[common_fcast_dates].values

# Two proxies
rv_target = rv_df.loc[common_fcast_dates, 'rv_5min'].values  # 5-min realized variance
r2_target = r_squared.loc[common_fcast_dates].values          # squared daily return

print(f"\n  Proxy Statistics (OOS period):")
print(f"    RV (5-min): mean={rv_target.mean():.6e}, std={rv_target.std():.6e}")
print(f"    r² (daily): mean={r2_target.mean():.6e}, std={r2_target.std():.6e}")
print(f"    Correlation(RV, r²): {np.corrcoef(rv_target, r2_target)[0,1]:.4f}")


def qlike(target, forecast):
    """QLIKE loss: L = target/forecast + log(forecast)
    Lower is better. Patton (2011) proxy-robust loss function."""
    # Ensure positive values
    f = np.maximum(forecast, 1e-20)
    t = np.maximum(target, 1e-20)
    return np.mean(t / f + np.log(f))


def mse(target, forecast):
    """Mean Squared Error."""
    return np.mean((target - forecast) ** 2)


def mae(target, forecast):
    """Mean Absolute Error."""
    return np.mean(np.abs(target - forecast))


# Compute losses for all model × proxy combinations
models = {
    'HAR-RV': har_f,
    'GJR-GARCH': gjr_f,
    'A4f-VIX²': a4f_f
}

proxies = {
    'RV (5-min)': rv_target,
    'r² (daily)': r2_target
}

results = {}
for proxy_name, proxy_vals in proxies.items():
    results[proxy_name] = {}
    for model_name, model_fcast in models.items():
        q = qlike(proxy_vals, model_fcast)
        m = mse(proxy_vals, model_fcast)
        ma = mae(proxy_vals, model_fcast)
        results[proxy_name][model_name] = {
            'QLIKE': float(q),
            'MSE': float(m),
            'MAE': float(ma)
        }

# Print results table
print("\n" + "=" * 70)
print("  RESULTS: QLIKE Loss (Lower = Better)")
print("=" * 70)
print(f"  {'Model':<15} {'RV Proxy':>15} {'r² Proxy':>15} {'Rank (RV)':>12} {'Rank (r²)':>12}")
print(f"  {'-'*15} {'-'*15} {'-'*15} {'-'*12} {'-'*12}")

# Get rankings
rv_qlikes = {m: results['RV (5-min)'][m]['QLIKE'] for m in models}
r2_qlikes = {m: results['r² (daily)'][m]['QLIKE'] for m in models}

rv_ranking = sorted(rv_qlikes, key=rv_qlikes.get)
r2_ranking = sorted(r2_qlikes, key=r2_qlikes.get)

for model_name in models:
    rv_q = results['RV (5-min)'][model_name]['QLIKE']
    r2_q = results['r² (daily)'][model_name]['QLIKE']
    rv_rank = rv_ranking.index(model_name) + 1
    r2_rank = r2_ranking.index(model_name) + 1
    print(f"  {model_name:<15} {rv_q:>15.6f} {r2_q:>15.6f} {rv_rank:>12} {r2_rank:>12}")

print(f"\n  QLIKE Ranking with RV proxy:  {' > '.join(rv_ranking)}")
print(f"  QLIKE Ranking with r² proxy: {' > '.join(r2_ranking)}")

ranking_consistent = (rv_ranking == r2_ranking)
print(f"\n  Rankings consistent across proxies: {ranking_consistent}")
if not ranking_consistent:
    print("  ⚠️ Rankings DIFFER — but with only ~30 OOS days, this is likely noise.")
    print("     Patton (2011): QLIKE should preserve rankings regardless of proxy")
    print("     in large samples. Discrepancy here suggests sample too small.")

# MSE results
print(f"\n  {'Model':<15} {'MSE (RV)':>15} {'MSE (r²)':>15}")
print(f"  {'-'*15} {'-'*15} {'-'*15}")
for model_name in models:
    rv_m = results['RV (5-min)'][model_name]['MSE']
    r2_m = results['r² (daily)'][model_name]['MSE']
    print(f"  {model_name:<15} {rv_m:>15.6e} {r2_m:>15.6e}")

# MAE results
print(f"\n  {'Model':<15} {'MAE (RV)':>15} {'MAE (r²)':>15}")
print(f"  {'-'*15} {'-'*15} {'-'*15}")
for model_name in models:
    rv_m = results['RV (5-min)'][model_name]['MAE']
    r2_m = results['r² (daily)'][model_name]['MAE']
    print(f"  {model_name:<15} {rv_m:>15.6e} {r2_m:>15.6e}")


# ═══════════════════════════════════════════════════════════════════════
# 6. DM TEST (Diebold-Mariano) — Pairwise
# ═══════════════════════════════════════════════════════════════════════

print("\n[6] Diebold-Mariano Tests (QLIKE loss differentials)...")
print("  Harvey (2016) threshold: |t| > 3.0 for significance")

from scipy import stats

def dm_test_qlike(target, forecast1, forecast2):
    """DM test for QLIKE loss: H0: equal predictive accuracy."""
    f1 = np.maximum(forecast1, 1e-20)
    f2 = np.maximum(forecast2, 1e-20)
    t = np.maximum(target, 1e-20)

    loss1 = t / f1 + np.log(f1)
    loss2 = t / f2 + np.log(f2)
    d = loss1 - loss2  # positive = model 2 better

    n = len(d)
    d_mean = np.mean(d)
    # HAC variance (Newey-West with auto bandwidth)
    from scipy.signal import correlate
    gamma_0 = np.var(d, ddof=1)

    # Simple bandwidth = int(n^(1/3))
    bandwidth = max(1, int(n ** (1/3)))
    hac_var = gamma_0
    for j in range(1, bandwidth + 1):
        weight = 1 - j / (bandwidth + 1)
        gamma_j = np.cov(d[j:], d[:-j], ddof=1)[0, 1]
        hac_var += 2 * weight * gamma_j

    se = np.sqrt(hac_var / n)
    if se < 1e-20:
        return 0.0, 1.0

    t_stat = d_mean / se
    p_val = 2 * (1 - stats.t.cdf(abs(t_stat), df=n - 1))
    return t_stat, p_val


model_names = list(models.keys())
model_fcasts = [har_f, gjr_f, a4f_f]

for proxy_name, proxy_vals in proxies.items():
    print(f"\n  Target: {proxy_name}")
    for i in range(len(model_names)):
        for j in range(i + 1, len(model_names)):
            t_stat, p_val = dm_test_qlike(proxy_vals, model_fcasts[i], model_fcasts[j])
            sig = "***" if abs(t_stat) > 3.0 else ("**" if abs(t_stat) > 2.0 else ("*" if abs(t_stat) > 1.65 else ""))
            better = model_names[j] if t_stat > 0 else model_names[i]
            print(f"    {model_names[i]} vs {model_names[j]}: t={t_stat:+.3f}, p={p_val:.4f} {sig}  ({better} better)")


# ═══════════════════════════════════════════════════════════════════════
# 7. ADDITIONAL: Spearman Rank Correlation (distribution-free)
# ═══════════════════════════════════════════════════════════════════════

print("\n[7] Spearman Rank Correlation with targets...")

for proxy_name, proxy_vals in proxies.items():
    print(f"\n  Target: {proxy_name}")
    for model_name, model_fcast in models.items():
        rho, p_val = stats.spearmanr(proxy_vals, model_fcast)
        print(f"    {model_name}: ρ={rho:.4f}, p={p_val:.4f}")


# ═══════════════════════════════════════════════════════════════════════
# 8. FORECAST COMPARISON PLOT
# ═══════════════════════════════════════════════════════════════════════

print("\n[8] Generating comparison plot...")

fig = plt.figure(figsize=(16, 14))
gs = gridspec.GridSpec(3, 2, hspace=0.35, wspace=0.3)

dates_plot = common_fcast_dates.to_numpy()  # convert to numpy for matplotlib

# Panel 1: Forecasts vs RV target
ax1 = fig.add_subplot(gs[0, :])
ax1.plot(dates_plot, rv_target * 1e4, 'ko-', label='RV (5-min)', alpha=0.7, markersize=3, linewidth=1)
ax1.plot(dates_plot, har_f * 1e4, 'b--', label='HAR-RV', alpha=0.8, linewidth=1.5)
ax1.plot(dates_plot, gjr_f * 1e4, 'r--', label='GJR-GARCH', alpha=0.8, linewidth=1.5)
ax1.plot(dates_plot, a4f_f * 1e4, 'g--', label='A4f-VIX²', alpha=0.8, linewidth=1.5)
ax1.set_title('Variance Forecasts vs Realized Variance (5-min)', fontsize=12, fontweight='bold')
ax1.set_ylabel('Variance (×10⁴)')
ax1.legend(fontsize=9)
ax1.grid(True, alpha=0.3)

# Panel 2: Forecasts vs r² target
ax2 = fig.add_subplot(gs[1, :])
ax2.plot(dates_plot, r2_target * 1e4, 'ko-', label='r² (squared return)', alpha=0.7, markersize=3, linewidth=1)
ax2.plot(dates_plot, har_f * 1e4, 'b--', label='HAR-RV', alpha=0.8, linewidth=1.5)
ax2.plot(dates_plot, gjr_f * 1e4, 'r--', label='GJR-GARCH', alpha=0.8, linewidth=1.5)
ax2.plot(dates_plot, a4f_f * 1e4, 'g--', label='A4f-VIX²', alpha=0.8, linewidth=1.5)
ax2.set_title('Variance Forecasts vs Squared Returns', fontsize=12, fontweight='bold')
ax2.set_ylabel('Variance (×10⁴)')
ax2.legend(fontsize=9)
ax2.grid(True, alpha=0.3)

# Panel 3: QLIKE comparison bar chart
ax3 = fig.add_subplot(gs[2, 0])
x = np.arange(len(models))
width = 0.35
qlike_rv = [results['RV (5-min)'][m]['QLIKE'] for m in models]
qlike_r2 = [results['r² (daily)'][m]['QLIKE'] for m in models]

bars1 = ax3.bar(x - width/2, qlike_rv, width, label='RV Proxy', color='steelblue', alpha=0.8)
bars2 = ax3.bar(x + width/2, qlike_r2, width, label='r² Proxy', color='coral', alpha=0.8)
ax3.set_xticks(x)
ax3.set_xticklabels(list(models.keys()), fontsize=9)
ax3.set_ylabel('QLIKE Loss')
ax3.set_title('QLIKE Loss: RV vs r² Proxy', fontsize=12, fontweight='bold')
ax3.legend()
ax3.grid(True, alpha=0.3, axis='y')

# Add value labels on bars
for bar in bars1:
    ax3.text(bar.get_x() + bar.get_width()/2., bar.get_height() + 0.02,
             f'{bar.get_height():.2f}', ha='center', va='bottom', fontsize=8)
for bar in bars2:
    ax3.text(bar.get_x() + bar.get_width()/2., bar.get_height() + 0.02,
             f'{bar.get_height():.2f}', ha='center', va='bottom', fontsize=8)

# Panel 4: Spearman correlation comparison
ax4 = fig.add_subplot(gs[2, 1])
spearman_rv = []
spearman_r2 = []
for model_name, model_fcast in models.items():
    rho_rv, _ = stats.spearmanr(rv_target, model_fcast)
    rho_r2, _ = stats.spearmanr(r2_target, model_fcast)
    spearman_rv.append(rho_rv)
    spearman_r2.append(rho_r2)

bars3 = ax4.bar(x - width/2, spearman_rv, width, label='RV Proxy', color='steelblue', alpha=0.8)
bars4 = ax4.bar(x + width/2, spearman_r2, width, label='r² Proxy', color='coral', alpha=0.8)
ax4.set_xticks(x)
ax4.set_xticklabels(list(models.keys()), fontsize=9)
ax4.set_ylabel('Spearman ρ')
ax4.set_title('Spearman Rank Correlation with Target', fontsize=12, fontweight='bold')
ax4.legend()
ax4.grid(True, alpha=0.3, axis='y')
ax4.set_ylim([-0.2, 1.0])

# Add value labels
for bar in bars3:
    ax4.text(bar.get_x() + bar.get_width()/2., max(bar.get_height(), 0) + 0.02,
             f'{bar.get_height():.3f}', ha='center', va='bottom', fontsize=8)
for bar in bars4:
    ax4.text(bar.get_x() + bar.get_width()/2., max(bar.get_height(), 0) + 0.02,
             f'{bar.get_height():.3f}', ha='center', va='bottom', fontsize=8)

fig.suptitle('K1049: HAR-RV 60-Day Pilot — Proxy Comparison (PRELIMINARY, ~30 OOS days)',
             fontsize=14, fontweight='bold', y=0.98)

plt.savefig(os.path.join(OUTPUT_DIR, 'K1049_proxy_comparison.png'), dpi=150, bbox_inches='tight')
plt.close()
print("  Saved: K1049_proxy_comparison.png")


# ═══════════════════════════════════════════════════════════════════════
# 9. SAVE RESULTS JSON
# ═══════════════════════════════════════════════════════════════════════

print("\n[9] Saving results...")

# Compute all summary stats
summary = {
    'experiment_id': 'K1049',
    'title': 'HAR-RV 60-Day SPY Pilot — Proxy Comparison r² vs RV',
    'status': 'PRELIMINARY',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'data': {
        'asset': 'SPY',
        'source': 'yfinance (daily) + data/intraday/ (5-min)',
        'rv_days': int(len(rv_df)),
        'rv_period': f"{rv_df.index[0].date()} to {rv_df.index[-1].date()}",
        'daily_returns_count': int(len(spy_returns)),
        'oos_days': int(len(common_fcast_dates)),
        'oos_period': f"{common_fcast_dates[0].date()} to {common_fcast_dates[-1].date()}"
    },
    'models': {
        'HAR-RV': {
            'specification': 'RV_t = β₀ + β₁×RV_{t-1} + β₅×RV_{t-1:t-5} + β₂₂×RV_{t-1:t-22}',
            'estimation': 'Expanding window OLS, initial window = 30 days',
            'initial_betas': har_betas_log[0] if har_betas_log else None
        },
        'GJR-GARCH': {
            'specification': 'GJR(1,1) with normal innovations',
            'estimation': f'Rolling window = {GARCH_WINDOW} daily returns',
            'initial_params': gjr_params_log[0] if gjr_params_log else None
        },
        'A4f-VIX²': {
            'specification': 'τ_t = θ₀ + θ₁×VIX²_{t-1}, g_t = GJR(1,1) on r_t/√τ_t',
            'estimation': f'Rolling window = {GARCH_WINDOW} daily returns',
            'initial_params': a4f_params_log[0] if a4f_params_log else None
        }
    },
    'proxy_stats': {
        'rv_5min': {
            'mean': float(rv_target.mean()),
            'std': float(rv_target.std()),
            'min': float(rv_target.min()),
            'max': float(rv_target.max())
        },
        'r_squared': {
            'mean': float(r2_target.mean()),
            'std': float(r2_target.std()),
            'min': float(r2_target.min()),
            'max': float(r2_target.max())
        },
        'correlation_rv_r2': float(np.corrcoef(rv_target, r2_target)[0, 1])
    },
    'evaluation': {
        'QLIKE': results,
        'rankings': {
            'QLIKE_RV_proxy': rv_ranking,
            'QLIKE_r2_proxy': r2_ranking,
            'rankings_consistent': ranking_consistent
        }
    },
    'spearman': {},
    'dm_tests': {},
    'key_findings': [],
    'limitations': [
        f'Only {len(common_fcast_dates)} OOS days — far below 252-day minimum for definitive conclusions',
        'HAR-RV trained on only 30 expanding-window observations (vs 2000 for GARCH)',
        'r² is very noisy proxy (single squared return vs sum of 78 squared 5-min returns)',
        'VIX regime during sample may not represent typical conditions',
        'No bootstrap CI due to small sample'
    ],
    'references': [
        'Patton (2011). Volatility forecast comparison using imperfect volatility proxies. JoE.',
        'Corsi (2009). A simple approximate long-memory model of realized volatility. JFEC.',
        'Hansen & Lunde (2005). A forecast comparison of volatility models. JFEC.',
        'Engle & Rangel (2008). The Spline-GARCH Model for Low-Frequency Volatility. RFS.'
    ]
}

# Add Spearman correlations
for proxy_name, proxy_vals in proxies.items():
    summary['spearman'][proxy_name] = {}
    for model_name, model_fcast in models.items():
        rho, p_val = stats.spearmanr(proxy_vals, model_fcast)
        summary['spearman'][proxy_name][model_name] = {
            'rho': float(rho),
            'p_value': float(p_val)
        }

# Add DM tests
for proxy_name, proxy_vals in proxies.items():
    summary['dm_tests'][proxy_name] = {}
    for i in range(len(model_names)):
        for j in range(i + 1, len(model_names)):
            t_stat, p_val = dm_test_qlike(proxy_vals, model_fcasts[i], model_fcasts[j])
            pair = f"{model_names[i]}_vs_{model_names[j]}"
            summary['dm_tests'][proxy_name][pair] = {
                't_stat': float(t_stat),
                'p_value': float(p_val),
                'significant_harvey': abs(t_stat) > 3.0
            }

# Key findings
findings = []
findings.append(f"OOS period: {len(common_fcast_dates)} days (PRELIMINARY, need ≥252)")

if ranking_consistent:
    findings.append(f"QLIKE rankings CONSISTENT across proxies: {' > '.join(rv_ranking)}")
    findings.append("Supports Patton (2011): QLIKE is proxy-robust even in small samples")
else:
    findings.append(f"QLIKE rankings DIFFER: RV proxy → {' > '.join(rv_ranking)}, r² proxy → {' > '.join(r2_ranking)}")
    findings.append("Ranking discrepancy likely due to small sample (30 days) — not a refutation of Patton (2011)")

# Note about native-target advantage
rv_best_rv = rv_ranking[0]
r2_best_r2 = r2_ranking[0]
findings.append(f"Best model with RV proxy: {rv_best_rv}")
findings.append(f"Best model with r² proxy: {r2_best_r2}")

if rv_best_rv == 'HAR-RV':
    findings.append("HAR-RV winning on RV proxy is EXPECTED (native target) — mechanical, not empirical")
if r2_best_r2 in ['GJR-GARCH', 'A4f-VIX²']:
    findings.append(f"{r2_best_r2} winning on r² proxy is EXPECTED (native target) — mechanical, not empirical")

summary['key_findings'] = findings

# Save
results_path = os.path.join(OUTPUT_DIR, 'K1049_results.json')
with open(results_path, 'w') as f:
    json.dump(summary, f, indent=2, default=str)
print(f"  Saved: K1049_results.json")


# ═══════════════════════════════════════════════════════════════════════
# 10. SUMMARY
# ═══════════════════════════════════════════════════════════════════════

print("\n" + "=" * 70)
print("K1049 SUMMARY (PRELIMINARY — ~30 OOS days)")
print("=" * 70)
for f in findings:
    print(f"  • {f}")

print(f"\n  Proxy correlation (RV vs r²): {np.corrcoef(rv_target, r2_target)[0,1]:.4f}")
print(f"\n  Next steps:")
print(f"    - Accumulate more 5-min data (target: 252+ OOS days)")
print(f"    - Add HAR-RV-J (jump component) when enough data available")
print(f"    - Bootstrap CI once sample reaches 100+ days")
print(f"\n  All results saved to experiments/K1049/")
print("=" * 70)
