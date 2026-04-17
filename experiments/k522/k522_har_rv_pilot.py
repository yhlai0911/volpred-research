#!/usr/bin/env python3
"""
K522: HAR-RV Pilot with 50-Day 5-Min Data

Background:
  5-min SPY data accumulated for ~50 trading days (2026-01-14 to 2026-03-26).
  K188: HAR-RV with only 42 days → R² near zero, insufficient data.
  K465/K469: HAR log-range 8/10 cross-OOS but K468 revealed tautology issue
    (Parkinson proxy favors range-based models).
  Now we can compute TRUE Realized Variance from 5-min returns — the gold
  standard volatility proxy — and test HAR-RV properly.

Research Question:
  1. Does HAR-RV (with genuine 5-min RV) outperform GJR-GARCH and HAR log-range?
  2. How does using 5-min RV as evaluation proxy change model rankings
     compared to Parkinson or r² proxies?
  3. Is 50 days enough to see the HAR structure (daily/weekly/monthly components)?

Design:
  - Compute daily RV from 5-min log returns: RV_t = Σ r²_{t,i}
  - HAR-RV: RV_{t+1} = β₀ + β_d·RV_t + β_w·RV_t^(w) + β_m·RV_t^(m) + ε
    where RV_t^(w) = mean(RV_{t-4:t}), RV_t^(m) = mean(RV_{t-21:t})
  - Compare with: GJR-GARCH, HAR log-range (Parkinson), EWMA
  - OOS: leave-last-10-out (limited by 50-day sample)
  - Evaluation: QLIKE with 5-min RV as the TRUE proxy (most accurate available)

Caveats:
  - 50 days is PRELIMINARY — formal HAR-RV needs 60+ days (ETA ~04/05)
  - 22-day monthly component needs 22-day warmup → only ~28 usable days
  - Small OOS (10 days) limits statistical power of DM test
  - No overnight returns in 5-min data (RTH only)

Data: yfinance 5-min intraday CSVs (data/intraday/SPY_5min_*.csv)
Refs: Corsi (2009) "A Simple Approximate Long-Memory Model" J Financial Econometrics
      Andersen, Bollerslev, Diebold, Labys (2003) "Modeling and Forecasting Realized Volatility"
      K188 — HAR ceiling test (42 days, R²≈0)
      K465 — HAR log-range cross-OOS (Parkinson proxy)
      K468 — Yang-Zhang study revealing proxy tautology
      K469 — HAR log-range with r² proxy (correcting K465)
Author: [Proposed: User, Executed: Claude]
"""

import json
import warnings
import time
import glob
import os
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from scipy import stats

warnings.filterwarnings('ignore')

START_TIME = time.time()

print("=" * 70)
print("K522: HAR-RV Pilot with 50-Day 5-Min Data")
print("  TRUE Realized Variance from intraday data")
print("=" * 70)

# ============================================================
# 1. Load 5-min data and compute daily Realized Variance
# ============================================================
print("\n[1] Loading 5-min intraday data...")

# Use main repo data directory (worktree may not have data/)
MAIN_REPO = '/Users/yhlai0911/Desktop/volpred-research'
DATA_DIR = os.path.join(MAIN_REPO, 'data', 'intraday')
if not os.path.exists(DATA_DIR):
    DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            'data', 'intraday')
files = sorted(glob.glob(os.path.join(DATA_DIR, 'SPY_5min_*.csv')))
print(f"  Found {len(files)} daily 5-min files")

rv_daily = {}
parkinson_daily = {}
close_prices = {}
ohlc_daily = {}  # for Parkinson / daily returns

for f in files:
    # Read with multi-row header (rows 0,1 are Price/Ticker, row 2 is Datetime header)
    df = pd.read_csv(f, header=[0, 1], index_col=0)
    # Flatten multi-index columns
    df.columns = [col[0] for col in df.columns]
    df.index = pd.to_datetime(df.index)
    df = df.sort_index()

    date = df.index[0].date()

    # 5-min log returns
    log_ret = np.log(df['Close'].astype(float) / df['Close'].astype(float).shift(1)).dropna()

    # Realized Variance = sum of squared 5-min log returns
    rv = (log_ret ** 2).sum()
    rv_daily[date] = rv

    # Daily OHLC from intraday
    daily_high = df['High'].astype(float).max()
    daily_low = df['Low'].astype(float).min()
    daily_open = df['Open'].astype(float).iloc[0]
    daily_close = df['Close'].astype(float).iloc[-1]
    close_prices[date] = daily_close
    ohlc_daily[date] = {'open': daily_open, 'high': daily_high,
                         'low': daily_low, 'close': daily_close}

    # Parkinson variance
    if daily_high > 0 and daily_low > 0:
        log_hl = np.log(daily_high / daily_low)
        parkinson_daily[date] = log_hl ** 2 / (4 * np.log(2))

rv_series = pd.Series(rv_daily).sort_index()
parkinson_series = pd.Series(parkinson_daily).sort_index()
close_series = pd.Series(close_prices).sort_index()

print(f"  RV series: {len(rv_series)} days [{rv_series.index[0]} to {rv_series.index[-1]}]")
print(f"  Annualized vol (from RV): {np.sqrt(rv_series.mean() * 252) * 100:.1f}%")

# Daily close-to-close log returns
daily_log_ret = np.log(close_series / close_series.shift(1)).dropna()
r2_series = daily_log_ret ** 2  # squared return as another proxy

# ============================================================
# 2. Descriptive Statistics
# ============================================================
print("\n[2] Descriptive Statistics")
print(f"  {'Metric':<30} {'RV (5-min)':<15} {'Parkinson':<15} {'r²':<15}")
print(f"  {'-'*75}")
stats_data = {}
for name, s in [('RV_5min', rv_series), ('Parkinson', parkinson_series), ('r2', r2_series)]:
    # Align to common dates
    common = rv_series.index.intersection(s.index)
    s_aligned = s.loc[common]
    stats_data[name] = {
        'mean': float(s_aligned.mean()),
        'std': float(s_aligned.std()),
        'min': float(s_aligned.min()),
        'max': float(s_aligned.max()),
        'skew': float(s_aligned.skew()),
        'kurtosis': float(s_aligned.kurtosis()),
        'count': int(len(s_aligned)),
    }
    print(f"  {'Mean':<30} " if name == 'RV_5min' else '', end='')

for metric in ['mean', 'std', 'min', 'max', 'skew', 'kurtosis']:
    vals = [f"{stats_data[k][metric]:.6f}" if metric != 'kurtosis'
            else f"{stats_data[k][metric]:.2f}" for k in ['RV_5min', 'Parkinson', 'r2']]
    print(f"  {metric:<30} {vals[0]:<15} {vals[1]:<15} {vals[2]:<15}")

# Correlation between proxies
common_idx = rv_series.index.intersection(parkinson_series.index).intersection(r2_series.index)
corr_rv_park = np.corrcoef(rv_series.loc[common_idx], parkinson_series.loc[common_idx])[0, 1]
corr_rv_r2 = np.corrcoef(rv_series.loc[common_idx], r2_series.loc[common_idx])[0, 1]
corr_park_r2 = np.corrcoef(parkinson_series.loc[common_idx], r2_series.loc[common_idx])[0, 1]

print(f"\n  Proxy correlations:")
print(f"    RV vs Parkinson: {corr_rv_park:.4f}")
print(f"    RV vs r²:        {corr_rv_r2:.4f}")
print(f"    Parkinson vs r²: {corr_park_r2:.4f}")

# ============================================================
# 3. HAR-RV Model
# ============================================================
print("\n[3] Building HAR-RV Model (Corsi 2009)")

def build_har_features(rv_s, min_history=22):
    """Build HAR features: daily, weekly (5d), monthly (22d) RV components."""
    dates = rv_s.index
    features = []
    targets = []
    target_dates = []

    for i in range(min_history, len(rv_s) - 1):
        rv_d = rv_s.iloc[i]  # RV_t (daily)
        rv_w = rv_s.iloc[i-4:i+1].mean()  # RV_t^(w) = mean of last 5 days
        rv_m = rv_s.iloc[i-21:i+1].mean()  # RV_t^(m) = mean of last 22 days

        features.append([rv_d, rv_w, rv_m])
        targets.append(rv_s.iloc[i + 1])  # RV_{t+1}
        target_dates.append(dates[i + 1])

    X = np.array(features)
    y = np.array(targets)
    return X, y, target_dates


X_har, y_har, har_dates = build_har_features(rv_series)
n_total = len(y_har)
print(f"  Total usable observations: {n_total} (after 22-day warmup)")

# ============================================================
# 4. OOS Split: leave-last-10-out
# ============================================================
OOS_SIZE = 10
n_is = n_total - OOS_SIZE

if n_is < 10:
    print(f"  WARNING: Only {n_is} IS observations — results will be very noisy!")

X_is, y_is = X_har[:n_is], y_har[:n_is]
X_oos, y_oos = X_har[n_is:], y_har[n_is:]
oos_dates = har_dates[n_is:]

print(f"  IS: {n_is} days, OOS: {OOS_SIZE} days")
print(f"  OOS period: {oos_dates[0]} to {oos_dates[-1]}")

# --- HAR-RV OLS estimation ---
from numpy.linalg import lstsq

X_is_with_const = np.column_stack([np.ones(n_is), X_is])
beta_har, residuals, rank, sv = lstsq(X_is_with_const, y_is, rcond=None)

print(f"\n  HAR-RV coefficients (IS):")
print(f"    β₀ (intercept): {beta_har[0]:.8f}")
print(f"    β_d (daily):    {beta_har[1]:.4f}")
print(f"    β_w (weekly):   {beta_har[2]:.4f}")
print(f"    β_m (monthly):  {beta_har[3]:.4f}")

# IS R²
y_is_hat = X_is_with_const @ beta_har
ss_res = np.sum((y_is - y_is_hat) ** 2)
ss_tot = np.sum((y_is - y_is.mean()) ** 2)
r2_is = 1 - ss_res / ss_tot
print(f"    R² (IS):        {r2_is:.4f}")

# IS standard errors
n_params = 4
mse = ss_res / (n_is - n_params)
cov_matrix = mse * np.linalg.inv(X_is_with_const.T @ X_is_with_const)
se = np.sqrt(np.diag(cov_matrix))
t_stats = beta_har / se
print(f"\n    t-statistics:")
for i, name in enumerate(['intercept', 'β_d', 'β_w', 'β_m']):
    sig = '***' if abs(t_stats[i]) > 2.576 else '**' if abs(t_stats[i]) > 1.96 else '*' if abs(t_stats[i]) > 1.645 else ''
    print(f"      {name:<12}: t={t_stats[i]:>7.3f} {sig}")

# OOS HAR-RV forecasts
X_oos_with_const = np.column_stack([np.ones(OOS_SIZE), X_oos])
har_rv_forecast = X_oos_with_const @ beta_har
# Floor at small positive to avoid division by zero
har_rv_forecast = np.maximum(har_rv_forecast, 1e-10)

# ============================================================
# 5. HAR Log-Range Model (for comparison)
# ============================================================
print("\n[4] HAR Log-Range Model (Parkinson-based, for comparison)")

# Build log-range features from Parkinson
log_range_series = pd.Series(
    {d: np.log(ohlc_daily[d]['high'] / ohlc_daily[d]['low'])
     for d in ohlc_daily if ohlc_daily[d]['high'] > 0 and ohlc_daily[d]['low'] > 0}
).sort_index()

X_lr, y_lr, lr_dates = [], [], []
for i in range(22, len(log_range_series) - 1):
    lr_d = log_range_series.iloc[i]
    lr_w = log_range_series.iloc[i-4:i+1].mean()
    lr_m = log_range_series.iloc[i-21:i+1].mean()
    X_lr.append([lr_d, lr_w, lr_m])
    y_lr.append(log_range_series.iloc[i + 1])
    lr_dates.append(log_range_series.index[i + 1])

X_lr = np.array(X_lr)
y_lr = np.array(y_lr)

# Same split
n_lr_is = len(y_lr) - OOS_SIZE
X_lr_is = np.column_stack([np.ones(n_lr_is), X_lr[:n_lr_is]])
y_lr_is = y_lr[:n_lr_is]
X_lr_oos = np.column_stack([np.ones(OOS_SIZE), X_lr[n_lr_is:]])

beta_lr, _, _, _ = lstsq(X_lr_is, y_lr_is, rcond=None)
lr_forecast_raw = X_lr_oos @ beta_lr

# Convert log-range forecast to variance scale: σ² = lr² / (4·ln2)
lr_forecast_var = lr_forecast_raw ** 2 / (4 * np.log(2))
lr_forecast_var = np.maximum(lr_forecast_var, 1e-10)

# Scale calibration: match IS mean to RV mean
# Use common IS period
park_is_mean = parkinson_series.iloc[:n_is + 22].mean() if len(parkinson_series) > n_is + 22 else parkinson_series.iloc[:-OOS_SIZE].mean()
rv_is_mean = rv_series.iloc[:n_is + 22].mean() if len(rv_series) > n_is + 22 else rv_series.iloc[:-OOS_SIZE].mean()
scale_ratio = rv_is_mean / park_is_mean if park_is_mean > 0 else 1.0
lr_forecast_scaled = lr_forecast_var * scale_ratio

print(f"  HAR log-range β: const={beta_lr[0]:.4f}, d={beta_lr[1]:.4f}, w={beta_lr[2]:.4f}, m={beta_lr[3]:.4f}")
print(f"  Scale ratio (RV/Parkinson): {scale_ratio:.4f}")

# ============================================================
# 6. GJR-GARCH(1,1) Model
# ============================================================
print("\n[5] GJR-GARCH(1,1) Model")

try:
    from arch import arch_model

    # Need daily returns — use close prices from intraday data
    returns_pct = daily_log_ret * 100  # arch uses percentage returns

    # Fit on IS period (all data before OOS)
    # Align dates: we need returns that map to the same OOS dates as HAR
    all_ret_dates = returns_pct.index
    n_ret = len(returns_pct)

    # Use all returns except last OOS_SIZE for fitting
    ret_is = returns_pct.iloc[:-OOS_SIZE]
    ret_oos = returns_pct.iloc[-OOS_SIZE:]

    model = arch_model(ret_is, vol='GARCH', p=1, o=1, q=1, dist='StudentsT', mean='Constant')
    res = model.fit(disp='off', show_warning=False)

    print(f"  GJR-GARCH parameters:")
    print(f"    omega: {res.params['omega']:.6f}")
    print(f"    alpha: {res.params.get('alpha[1]', 0):.4f}")
    print(f"    gamma: {res.params.get('gamma[1]', 0):.4f}")
    print(f"    beta:  {res.params.get('beta[1]', 0):.4f}")
    persistence = res.params.get('alpha[1]', 0) + res.params.get('gamma[1]', 0) / 2 + res.params.get('beta[1]', 0)
    print(f"    persistence: {persistence:.4f}")

    # 1-step ahead rolling forecasts for OOS
    gjr_forecasts_pct2 = []
    for i in range(OOS_SIZE):
        ret_window = returns_pct.iloc[:-(OOS_SIZE - i)]
        m = arch_model(ret_window, vol='GARCH', p=1, o=1, q=1, dist='StudentsT', mean='Constant')
        r = m.fit(disp='off', show_warning=False, starting_values=res.params.values)
        fc = r.forecast(horizon=1)
        gjr_forecasts_pct2.append(fc.variance.values[-1, 0])

    # Convert from %² to decimal variance
    gjr_forecast = np.array(gjr_forecasts_pct2) / 10000.0
    gjr_forecast = np.maximum(gjr_forecast, 1e-10)
    gjr_available = True

except Exception as e:
    print(f"  GJR-GARCH failed: {e}")
    gjr_available = False
    gjr_forecast = None

# ============================================================
# 7. EWMA Model
# ============================================================
print("\n[6] EWMA Model (lambda=0.94)")

LAMBDA = 0.94
ewma_var = np.zeros(len(rv_series))
ewma_var[0] = rv_series.iloc[0]

for i in range(1, len(rv_series)):
    ewma_var[i] = LAMBDA * ewma_var[i - 1] + (1 - LAMBDA) * rv_series.iloc[i]

# EWMA forecast for OOS: use variance at t to forecast t+1
ewma_forecast = ewma_var[-(OOS_SIZE + 1):-1]
ewma_forecast = np.maximum(ewma_forecast, 1e-10)

# ============================================================
# 8. Evaluation with 5-min RV as TRUE proxy
# ============================================================
print("\n[7] OOS Evaluation (proxy = 5-min Realized Variance)")

# Align OOS actual RV
rv_oos = rv_series.iloc[-OOS_SIZE:].values


def qlike(forecast, actual):
    """QLIKE loss: actual/forecast - log(actual/forecast) - 1"""
    ratio = actual / forecast
    return np.mean(ratio - np.log(ratio) - 1)


def mse_loss(forecast, actual):
    return np.mean((forecast - actual) ** 2)


def mae_loss(forecast, actual):
    return np.mean(np.abs(forecast - actual))


# Compute R² for OOS
def oos_r2(forecast, actual):
    ss_res = np.sum((actual - forecast) ** 2)
    ss_tot = np.sum((actual - actual.mean()) ** 2)
    return 1 - ss_res / ss_tot


results = {}

# HAR-RV
results['HAR-RV'] = {
    'QLIKE': float(qlike(har_rv_forecast, rv_oos)),
    'MSE': float(mse_loss(har_rv_forecast, rv_oos)),
    'MAE': float(mae_loss(har_rv_forecast, rv_oos)),
    'R2_oos': float(oos_r2(har_rv_forecast, rv_oos)),
    'mean_forecast': float(har_rv_forecast.mean()),
    'mean_actual': float(rv_oos.mean()),
}

# HAR log-range (scaled)
results['HAR-LogRange'] = {
    'QLIKE': float(qlike(lr_forecast_scaled, rv_oos)),
    'MSE': float(mse_loss(lr_forecast_scaled, rv_oos)),
    'MAE': float(mae_loss(lr_forecast_scaled, rv_oos)),
    'R2_oos': float(oos_r2(lr_forecast_scaled, rv_oos)),
    'mean_forecast': float(lr_forecast_scaled.mean()),
    'mean_actual': float(rv_oos.mean()),
}

# GJR-GARCH
if gjr_available:
    results['GJR-GARCH'] = {
        'QLIKE': float(qlike(gjr_forecast, rv_oos)),
        'MSE': float(mse_loss(gjr_forecast, rv_oos)),
        'MAE': float(mae_loss(gjr_forecast, rv_oos)),
        'R2_oos': float(oos_r2(gjr_forecast, rv_oos)),
        'mean_forecast': float(gjr_forecast.mean()),
        'mean_actual': float(rv_oos.mean()),
    }

# EWMA
results['EWMA'] = {
    'QLIKE': float(qlike(ewma_forecast, rv_oos)),
    'MSE': float(mse_loss(ewma_forecast, rv_oos)),
    'MAE': float(mae_loss(ewma_forecast, rv_oos)),
    'R2_oos': float(oos_r2(ewma_forecast, rv_oos)),
    'mean_forecast': float(ewma_forecast.mean()),
    'mean_actual': float(rv_oos.mean()),
}

# Print comparison table
print(f"\n  {'Model':<15} {'QLIKE':<12} {'MSE(×10⁸)':<12} {'MAE(×10⁴)':<12} {'R²_OOS':<10}")
print(f"  {'-'*60}")

# Rank by QLIKE
ranked = sorted(results.items(), key=lambda x: x[1]['QLIKE'])
best_model = ranked[0][0]

for name, r in ranked:
    marker = ' ★' if name == best_model else ''
    print(f"  {name:<15} {r['QLIKE']:<12.4f} {r['MSE']*1e8:<12.4f} {r['MAE']*1e4:<12.4f} {r['R2_oos']:<10.4f}{marker}")

# ============================================================
# 9. Diebold-Mariano Tests
# ============================================================
print("\n[8] Diebold-Mariano Tests (QLIKE loss differential)")

def dm_test(loss1, loss2, h=1):
    """Diebold-Mariano test. H0: equal predictive accuracy."""
    d = loss1 - loss2
    d_mean = np.mean(d)
    # HAC variance (Newey-West with h-1 lags)
    n = len(d)
    gamma0 = np.var(d, ddof=1)
    hac_var = gamma0
    for k in range(1, h):
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        hac_var += 2 * (1 - k / h) * gamma_k
    se = np.sqrt(hac_var / n)
    if se < 1e-15:
        return 0.0, 1.0
    dm_stat = d_mean / se
    p_val = 2 * (1 - stats.norm.cdf(abs(dm_stat)))
    return float(dm_stat), float(p_val)


# Individual QLIKE losses per observation
def qlike_individual(forecast, actual):
    ratio = actual / forecast
    return ratio - np.log(ratio) - 1


dm_results = {}

# HAR-RV losses
har_rv_losses = qlike_individual(har_rv_forecast, rv_oos)

models_to_compare = ['HAR-LogRange', 'EWMA']
forecasts_map = {
    'HAR-LogRange': lr_forecast_scaled,
    'EWMA': ewma_forecast,
}
if gjr_available:
    models_to_compare.append('GJR-GARCH')
    forecasts_map['GJR-GARCH'] = gjr_forecast

for m_name in models_to_compare:
    other_losses = qlike_individual(forecasts_map[m_name], rv_oos)
    dm_stat, dm_pval = dm_test(har_rv_losses, other_losses)
    dm_results[f'HAR-RV vs {m_name}'] = {
        'DM_stat': dm_stat,
        'p_value': dm_pval,
        'HAR_RV_better': bool(dm_stat < 0),
    }
    sig = '***' if dm_pval < 0.01 else '**' if dm_pval < 0.05 else '*' if dm_pval < 0.10 else 'n.s.'
    direction = '<' if dm_stat < 0 else '>'
    print(f"  HAR-RV vs {m_name:<15}: DM={dm_stat:>7.3f}, p={dm_pval:.4f} ({sig}) [HAR-RV {direction} {m_name}]")

# Also compare GJR vs HAR-LogRange if available
if gjr_available:
    gjr_losses = qlike_individual(gjr_forecast, rv_oos)
    lr_losses = qlike_individual(lr_forecast_scaled, rv_oos)
    dm_stat, dm_pval = dm_test(gjr_losses, lr_losses)
    dm_results['GJR-GARCH vs HAR-LogRange'] = {
        'DM_stat': float(dm_stat),
        'p_value': float(dm_pval),
    }
    print(f"  GJR-GARCH vs HAR-LogRange: DM={dm_stat:>7.3f}, p={dm_pval:.4f}")

# ============================================================
# 10. Day-by-day OOS comparison
# ============================================================
print("\n[9] Day-by-day OOS forecasts vs actual RV")
print(f"  {'Date':<15} {'Actual_RV':<12} {'HAR-RV':<12} {'HAR-LR':<12}", end='')
if gjr_available:
    print(f" {'GJR':<12}", end='')
print(f" {'EWMA':<12}")

oos_date_list = rv_series.index[-OOS_SIZE:]
for i in range(OOS_SIZE):
    d = oos_date_list[i]
    line = f"  {str(d):<15} {rv_oos[i]*1e4:>10.4f}  {har_rv_forecast[i]*1e4:>10.4f}  {lr_forecast_scaled[i]*1e4:>10.4f}"
    if gjr_available:
        line += f"  {gjr_forecast[i]*1e4:>10.4f}"
    line += f"  {ewma_forecast[i]*1e4:>10.4f}"
    print(line)

print(f"  (all values ×10⁴ for readability)")

# ============================================================
# 11. HAR Component Analysis
# ============================================================
print("\n[10] HAR Component Analysis")

# Relative contribution of each component
total_beta = abs(beta_har[1]) + abs(beta_har[2]) + abs(beta_har[3])
if total_beta > 0:
    pct_d = abs(beta_har[1]) / total_beta * 100
    pct_w = abs(beta_har[2]) / total_beta * 100
    pct_m = abs(beta_har[3]) / total_beta * 100
    print(f"  Relative contribution (|β|):")
    print(f"    Daily:   {pct_d:.1f}%")
    print(f"    Weekly:  {pct_w:.1f}%")
    print(f"    Monthly: {pct_m:.1f}%")

# Corsi (2009) typical values: β_d ≈ 0.36, β_w ≈ 0.28, β_m ≈ 0.28
print(f"\n  Comparison with Corsi (2009) typical values:")
print(f"    {'Component':<12} {'This study':<15} {'Corsi (2009)':<15}")
print(f"    {'β_d':<12} {beta_har[1]:<15.4f} {'~0.36':<15}")
print(f"    {'β_w':<12} {beta_har[2]:<15.4f} {'~0.28':<15}")
print(f"    {'β_m':<12} {beta_har[3]:<15.4f} {'~0.28':<15}")

# ============================================================
# 12. HAR-RV vs HAR-RV with only daily/weekly (nested test)
# ============================================================
print("\n[11] Nested Model Comparison")

# HAR(1): only daily
X_d_is = np.column_stack([np.ones(n_is), X_is[:, 0:1]])
beta_d, _, _, _ = lstsq(X_d_is, y_is, rcond=None)
X_d_oos = np.column_stack([np.ones(OOS_SIZE), X_oos[:, 0:1]])
fc_d = np.maximum(X_d_oos @ beta_d, 1e-10)
qlike_d = qlike(fc_d, rv_oos)

# HAR(1,5): daily + weekly
X_dw_is = np.column_stack([np.ones(n_is), X_is[:, 0:2]])
beta_dw, _, _, _ = lstsq(X_dw_is, y_is, rcond=None)
X_dw_oos = np.column_stack([np.ones(OOS_SIZE), X_oos[:, 0:2]])
fc_dw = np.maximum(X_dw_oos @ beta_dw, 1e-10)
qlike_dw = qlike(fc_dw, rv_oos)

# HAR(1,5,22): full
qlike_full = results['HAR-RV']['QLIKE']

print(f"  {'Model':<25} {'QLIKE':<12}")
print(f"  {'-'*37}")
print(f"  {'HAR(d) — daily only':<25} {qlike_d:<12.4f}")
print(f"  {'HAR(d,w) — daily+weekly':<25} {qlike_dw:<12.4f}")
print(f"  {'HAR(d,w,m) — full':<25} {qlike_full:<12.4f}")

# Does adding weekly/monthly improve?
improvement_w = (qlike_d - qlike_dw) / qlike_d * 100
improvement_m = (qlike_dw - qlike_full) / qlike_dw * 100
print(f"  Adding weekly:  {improvement_w:+.1f}% QLIKE change")
print(f"  Adding monthly: {improvement_m:+.1f}% QLIKE change")

# ============================================================
# 13. Cross-proxy evaluation (robustness)
# ============================================================
print("\n[12] Cross-proxy Evaluation (same forecasts, different evaluation proxies)")

# Evaluate all models with Parkinson proxy too
park_oos = parkinson_series.iloc[-OOS_SIZE:].values
r2_oos_vals = r2_series.iloc[-OOS_SIZE:].values

cross_proxy = {}
for proxy_name, proxy_vals in [('5min_RV', rv_oos), ('Parkinson', park_oos), ('r²', r2_oos_vals)]:
    cross_proxy[proxy_name] = {}
    for m_name, fc in [('HAR-RV', har_rv_forecast), ('HAR-LogRange', lr_forecast_scaled),
                        ('EWMA', ewma_forecast)]:
        cross_proxy[proxy_name][m_name] = float(qlike(fc, proxy_vals))
    if gjr_available:
        cross_proxy[proxy_name]['GJR-GARCH'] = float(qlike(gjr_forecast, proxy_vals))

print(f"\n  QLIKE by proxy:")
print(f"  {'Model':<15} {'5min_RV':<12} {'Parkinson':<12} {'r²':<12}")
print(f"  {'-'*50}")
model_names_all = ['HAR-RV', 'HAR-LogRange']
if gjr_available:
    model_names_all.append('GJR-GARCH')
model_names_all.append('EWMA')

for m in model_names_all:
    line = f"  {m:<15}"
    for p in ['5min_RV', 'Parkinson', 'r²']:
        line += f" {cross_proxy[p][m]:<12.4f}"
    print(line)

# Rank analysis
print(f"\n  Rankings by proxy:")
for p in ['5min_RV', 'Parkinson', 'r²']:
    ranking = sorted(cross_proxy[p].items(), key=lambda x: x[1])
    rank_str = ' > '.join([f"{r[0]}({r[1]:.3f})" for r in ranking])
    print(f"    {p:<12}: {rank_str}")

# ============================================================
# 14. Summary
# ============================================================
elapsed = time.time() - START_TIME
print(f"\n{'='*70}")
print(f"SUMMARY — K522 HAR-RV Pilot (50-day, PRELIMINARY)")
print(f"{'='*70}")

print(f"\n  Best model (QLIKE, 5-min RV proxy): {best_model}")
print(f"  HAR-RV R² (IS): {r2_is:.4f}")
print(f"  HAR-RV R² (OOS): {results['HAR-RV']['R2_oos']:.4f}")
print(f"  Sample: {len(rv_series)} days ({rv_series.index[0]} to {rv_series.index[-1]})")
print(f"  OOS: last {OOS_SIZE} days")
print(f"  Elapsed: {elapsed:.1f}s")

# Key finding
print(f"\n  KEY FINDINGS (PRELIMINARY — 50 days only):")

# Check if HAR-RV beats GJR
if gjr_available:
    har_vs_gjr = results['HAR-RV']['QLIKE'] < results['GJR-GARCH']['QLIKE']
    print(f"    1. HAR-RV {'<' if har_vs_gjr else '>'} GJR-GARCH (QLIKE: {results['HAR-RV']['QLIKE']:.4f} vs {results['GJR-GARCH']['QLIKE']:.4f})")

har_vs_lr = results['HAR-RV']['QLIKE'] < results['HAR-LogRange']['QLIKE']
print(f"    2. HAR-RV {'<' if har_vs_lr else '>'} HAR-LogRange (QLIKE: {results['HAR-RV']['QLIKE']:.4f} vs {results['HAR-LogRange']['QLIKE']:.4f})")

print(f"\n  CAVEATS:")
print(f"    - 50 days is too short for reliable HAR estimation (need 60+)")
print(f"    - Monthly component has minimal effective sample (28 obs after warmup)")
print(f"    - OOS of 10 days → DM test has very low power")
print(f"    - No overnight return component in 5-min RV")
print(f"    - Results should be re-evaluated with 60+ days (ETA ~04/05)")

# ============================================================
# 15. Save results
# ============================================================
output = {
    "experiment_id": "K522",
    "title": "HAR-RV Pilot with 50-Day 5-Min Data",
    "status": "PRELIMINARY",
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "data": {
        "source": "yfinance 5-min intraday CSVs (data/intraday/SPY_5min_*.csv)",
        "asset": "SPY",
        "n_days": int(len(rv_series)),
        "date_range": f"{rv_series.index[0]} to {rv_series.index[-1]}",
        "n_5min_files": len(files),
        "bars_per_day": "~78 (6.5h RTH / 5min)",
    },
    "descriptive_stats": stats_data,
    "proxy_correlations": {
        "RV_vs_Parkinson": float(corr_rv_park),
        "RV_vs_r2": float(corr_rv_r2),
        "Parkinson_vs_r2": float(corr_park_r2),
    },
    "har_rv_model": {
        "coefficients": {
            "intercept": float(beta_har[0]),
            "beta_daily": float(beta_har[1]),
            "beta_weekly": float(beta_har[2]),
            "beta_monthly": float(beta_har[3]),
        },
        "t_statistics": {
            "intercept": float(t_stats[0]),
            "beta_daily": float(t_stats[1]),
            "beta_weekly": float(t_stats[2]),
            "beta_monthly": float(t_stats[3]),
        },
        "R2_IS": float(r2_is),
        "R2_OOS": float(results['HAR-RV']['R2_oos']),
        "n_IS": int(n_is),
        "n_OOS": int(OOS_SIZE),
    },
    "har_logrange_model": {
        "coefficients": {
            "intercept": float(beta_lr[0]),
            "beta_daily": float(beta_lr[1]),
            "beta_weekly": float(beta_lr[2]),
            "beta_monthly": float(beta_lr[3]),
        },
        "scale_ratio_rv_parkinson": float(scale_ratio),
    },
    "oos_evaluation": {
        "proxy": "5-min Realized Variance (TRUE proxy)",
        "oos_period": f"{oos_dates[0]} to {oos_dates[-1]}",
        "n_oos": OOS_SIZE,
        "results": results,
        "ranking_by_QLIKE": [r[0] for r in ranked],
        "best_model": best_model,
    },
    "dm_tests": dm_results,
    "nested_comparison": {
        "HAR_d_QLIKE": float(qlike_d),
        "HAR_dw_QLIKE": float(qlike_dw),
        "HAR_dwm_QLIKE": float(qlike_full),
        "weekly_improvement_pct": float(improvement_w),
        "monthly_improvement_pct": float(improvement_m),
    },
    "cross_proxy_evaluation": cross_proxy,
    "caveats": [
        "50 days is PRELIMINARY — need 60+ for formal HAR-RV evaluation",
        "Monthly component has minimal effective sample (28 obs after 22-day warmup)",
        "OOS of 10 days limits DM test power",
        "5-min RV excludes overnight returns",
        "GJR-GARCH fitted on only ~40 daily returns (very short)",
        "Results should be re-evaluated with 60+ days data (ETA ~2026-04-05)",
    ],
    "references": [
        "Corsi (2009) 'A Simple Approximate Long-Memory Model' J Financial Econometrics",
        "Andersen, Bollerslev, Diebold, Labys (2003) 'Modeling and Forecasting Realized Volatility'",
        "K188: HAR ceiling test (42 days, R²≈0, insufficient data)",
        "K465: HAR log-range cross-OOS (Parkinson proxy, 10/10)",
        "K468: Yang-Zhang study revealing proxy tautology",
        "K469: HAR log-range with r² proxy (correcting K465)",
    ],
    "elapsed_seconds": round(elapsed, 1),
    "next_steps": [
        "Accumulate to 60+ days (~2026-04-05) for formal HAR-RV evaluation",
        "Add overnight return component (close-to-open + open-to-close decomposition)",
        "Test HAR-RV with jump-robust estimators (bipower variation)",
        "Compare with HEAVY model (Shephard & Sheppard 2010)",
        "Test on Taiwan market when 5-min data available",
    ],
}

results_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            'k522_har_rv_pilot_results.json')
with open(results_path, 'w') as f:
    json.dump(output, f, indent=2, default=str)

print(f"\n  Results saved to: {results_path}")
print(f"  Script: experiments/k522_har_rv_pilot.py")
print(f"  Elapsed: {elapsed:.1f}s")
