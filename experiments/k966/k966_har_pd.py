"""
K966: HAR-PD Path-Dependent RV Forecasting (5-min RV version)
==============================================================
Data source: yfinance 5-min intraday data for SPY
Period: 2026-01-14 to 2026-04-06 (56 trading days)
Method: HAR-PD (path-dependent features on top of HAR-RV)
Reference:
  - Guyon, J. & Lekeufack, J. (2023). "Volatility is (Mostly) Path-Dependent."
    arXiv:2503.00851 (extended version)
  - Corsi, F. (2009). "A Simple Approximate Long-Memory Model of Realized Volatility."
    Journal of Financial Econometrics, 7(2), 174-196.
  - Patton, A. (2011). "Volatility Forecast Comparison Using Imperfect Volatility Proxies."
    Journal of Econometrics, 160(1), 246-256.

Related: K624 (HAR-PD on daily r² → NULL), K960 (HAR-RV 5-min pilot, R²=0.243)

PILOT STUDY: Only 56 days total, 19 OOS days. Results are preliminary.
"""

import numpy as np
import pandas as pd
import os
import json
import glob
import warnings
from datetime import datetime
from scipy import stats
import statsmodels.api as sm
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from itertools import product

np.random.seed(42)
warnings.filterwarnings('ignore')

# ============================================================
# Part A: Load 5-min data and compute daily RV + daily returns
# ============================================================

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'intraday')
if not os.path.exists(DATA_DIR) or len(glob.glob(os.path.join(DATA_DIR, 'SPY_5min_*.csv'))) == 0:
    DATA_DIR = '/Users/yhlai0911/Desktop/volpred-research/data/intraday'
OUT_DIR = os.path.dirname(__file__)


def load_5min_data(data_dir):
    """Load all SPY 5-min CSV files and compute daily RV + daily returns."""
    files = sorted(glob.glob(os.path.join(data_dir, 'SPY_5min_*.csv')))
    print(f"Found {len(files)} 5-min data files")

    daily_rv = {}
    daily_close = {}
    daily_log_ret = {}

    for f in files:
        date_str = os.path.basename(f).replace('SPY_5min_', '').replace('.csv', '')

        # yfinance multi-header format: skip first 3 rows
        df = pd.read_csv(f, skiprows=3, header=None,
                         names=['Datetime', 'Close', 'High', 'Low', 'Open', 'Volume'])
        df['Close'] = pd.to_numeric(df['Close'], errors='coerce')
        df = df.dropna(subset=['Close'])

        if len(df) < 5:
            print(f"  Skipping {date_str}: only {len(df)} rows")
            continue

        # 5-min log returns → RV
        log_ret = np.log(df['Close'].values[1:] / df['Close'].values[:-1])
        rv = np.sum(log_ret ** 2)
        daily_rv[date_str] = rv
        daily_close[date_str] = df['Close'].values[-1]

    # Build DataFrame
    rv_df = pd.DataFrame({
        'date': list(daily_rv.keys()),
        'rv': list(daily_rv.values()),
        'close': [daily_close[d] for d in daily_rv.keys()],
    })
    rv_df['date'] = pd.to_datetime(rv_df['date'])
    rv_df = rv_df.sort_values('date').reset_index(drop=True)

    # Compute daily log returns from close prices
    rv_df['log_ret'] = np.log(rv_df['close'] / rv_df['close'].shift(1))
    rv_df = rv_df.dropna().reset_index(drop=True)

    return rv_df


def compute_har_features(rv_series):
    """Compute standard HAR features: daily, weekly (5d), monthly (22d) RV."""
    n = len(rv_series)
    rv_d = rv_series.values  # daily RV (lag 1)

    # Weekly RV: average of past 5 days
    rv_w = rv_series.rolling(5).mean().values

    # Monthly RV: average of past 22 days
    rv_m = rv_series.rolling(22).mean().values

    return rv_d, rv_w, rv_m


def compute_path_features(log_returns, rv_series, lambda1, lambda2):
    """
    Compute HAR-PD path-dependent features.

    R1 (trend/momentum): exponentially weighted past returns
        R1_t = sum_{k=0}^{t-1} lambda1^k * r_{t-k}

    R2 (volatility memory): exponentially weighted past |returns| residuals
        R2_t = sum_{k=0}^{t-1} lambda2^k * |r_{t-k}|

    Following Guyon & Lekeufack (2023), these capture path-dependent
    volatility dynamics beyond what standard HAR components capture.
    """
    n = len(log_returns)
    R1 = np.zeros(n)
    R2 = np.zeros(n)

    for t in range(n):
        r1_val = 0.0
        r2_val = 0.0
        for k in range(t + 1):
            weight1 = lambda1 ** k
            weight2 = lambda2 ** k
            r1_val += weight1 * log_returns.iloc[t - k]
            r2_val += weight2 * abs(log_returns.iloc[t - k])
            # Truncate when weight is negligible
            if weight1 < 1e-10 and weight2 < 1e-10:
                break
        R1[t] = r1_val
        R2[t] = r2_val

    return R1, R2


def qlike_loss(actual, forecast):
    """QLIKE loss: actual/forecast - log(actual/forecast) - 1"""
    ratio = actual / forecast
    # Avoid log(0) or negative
    ratio = np.maximum(ratio, 1e-20)
    return np.mean(ratio - np.log(ratio) - 1)


def mse_loss(actual, forecast):
    """Mean Squared Error"""
    return np.mean((actual - forecast) ** 2)


def dm_test(e1, e2, h=1):
    """
    Diebold-Mariano test for equal predictive accuracy.
    e1, e2: loss differentials (QLIKE losses for each model)
    Returns t-stat and p-value.
    """
    d = e1 - e2  # positive = model 2 better
    n = len(d)
    d_bar = np.mean(d)

    # HAC variance (Newey-West with h-1 lags)
    gamma_0 = np.var(d, ddof=1)
    if h > 1:
        for k in range(1, h):
            gamma_k = np.cov(d[k:], d[:-k])[0, 1]
            gamma_0 += 2 * (1 - k / h) * gamma_k

    se = np.sqrt(gamma_0 / n)
    if se < 1e-20:
        return 0.0, 1.0

    t_stat = d_bar / se
    p_value = 2 * (1 - stats.t.cdf(abs(t_stat), df=n - 1))
    return t_stat, p_value


# ============================================================
# Part B: Load data
# ============================================================

print("=" * 60)
print("K966: HAR-PD Path-Dependent RV Forecasting (5-min)")
print("=" * 60)

rv_df = load_5min_data(DATA_DIR)
print(f"\nTotal trading days with RV + returns: {len(rv_df)}")
print(f"Period: {rv_df['date'].iloc[0].strftime('%Y-%m-%d')} to {rv_df['date'].iloc[-1].strftime('%Y-%m-%d')}")

# Descriptive statistics
print(f"\n--- RV Descriptive Statistics ---")
print(f"Mean RV:   {rv_df['rv'].mean():.6f}")
print(f"Std RV:    {rv_df['rv'].std():.6f}")
print(f"Min RV:    {rv_df['rv'].min():.6f}")
print(f"Max RV:    {rv_df['rv'].max():.6f}")
print(f"Skewness:  {rv_df['rv'].skew():.3f}")
print(f"Kurtosis:  {rv_df['rv'].kurtosis():.3f}")
print(f"\nMean |log_ret|: {rv_df['log_ret'].abs().mean():.6f}")

# ============================================================
# Part C: IS/OOS split
# ============================================================

N = len(rv_df)
IS_END = 37  # first 37 days for IS
OOS_START = IS_END

print(f"\nIS: days 0-{IS_END-1} ({IS_END} days)")
print(f"OOS: days {OOS_START}-{N-1} ({N - OOS_START} days)")
print(f"⚠️  PILOT STUDY: N_OOS={N - OOS_START} is insufficient for DM significance")

# Need at least 22 days for monthly RV feature
MIN_START = 22  # first usable observation for HAR

# ============================================================
# Part D: Lambda grid search (IS period)
# ============================================================

LAMBDA_GRID = [0.01, 0.05, 0.1, 0.2, 0.5, 0.8, 0.9, 0.95]

print(f"\n{'='*60}")
print("Lambda Grid Search (IS period, minimizing QLIKE)")
print(f"{'='*60}")

# Prepare HAR features for full sample
rv_d, rv_w, rv_m = compute_har_features(rv_df['rv'])

best_qlike = np.inf
best_lambdas = (0.5, 0.5)
grid_results = {}

for lam1, lam2 in product(LAMBDA_GRID, LAMBDA_GRID):
    # Compute path features
    R1, R2 = compute_path_features(rv_df['log_ret'], rv_df['rv'], lam1, lam2)

    # Build IS dataset (need lag-1 features to predict next-day RV)
    # Target: RV_{t+1}, Features: RV_t, RV_w_t, RV_m_t, R1_t, R2_t
    # Usable range: MIN_START to IS_END-1 (predicting MIN_START+1 to IS_END)
    y_is = rv_df['rv'].values[MIN_START + 1:IS_END]
    X_is = np.column_stack([
        rv_d[MIN_START:IS_END - 1],
        rv_w[MIN_START:IS_END - 1],
        rv_m[MIN_START:IS_END - 1],
        R1[MIN_START:IS_END - 1],
        R2[MIN_START:IS_END - 1],
    ])

    # Check for NaN
    valid = ~np.isnan(X_is).any(axis=1) & ~np.isnan(y_is)
    if valid.sum() < 5:
        continue

    X_is_v = sm.add_constant(X_is[valid])
    y_is_v = y_is[valid]

    try:
        model = sm.OLS(y_is_v, X_is_v).fit()
        fitted = model.predict(X_is_v)
        fitted = np.maximum(fitted, 1e-10)  # floor at 0
        ql = qlike_loss(y_is_v, fitted)
        grid_results[(lam1, lam2)] = ql

        if ql < best_qlike:
            best_qlike = ql
            best_lambdas = (lam1, lam2)
    except Exception as e:
        continue

print(f"\nBest lambdas: λ₁={best_lambdas[0]}, λ₂={best_lambdas[1]}")
print(f"Best IS QLIKE: {best_qlike:.6f}")

# Show top 10
sorted_grid = sorted(grid_results.items(), key=lambda x: x[1])
print(f"\nTop 10 lambda combinations:")
for (l1, l2), ql in sorted_grid[:10]:
    print(f"  λ₁={l1:.2f}, λ₂={l2:.2f} → QLIKE={ql:.6f}")

# ============================================================
# Part E: Fit HAR and HAR-PD on IS, evaluate on OOS
# ============================================================

print(f"\n{'='*60}")
print("OOS Evaluation: HAR vs HAR-PD")
print(f"{'='*60}")

# --- Standard HAR-RV ---
y_is_har = rv_df['rv'].values[MIN_START + 1:IS_END]
X_is_har = np.column_stack([
    rv_d[MIN_START:IS_END - 1],
    rv_w[MIN_START:IS_END - 1],
    rv_m[MIN_START:IS_END - 1],
])
valid_har = ~np.isnan(X_is_har).any(axis=1) & ~np.isnan(y_is_har)
X_is_har_v = sm.add_constant(X_is_har[valid_har])
y_is_har_v = y_is_har[valid_har]

har_model = sm.OLS(y_is_har_v, X_is_har_v).fit()
print(f"\n--- HAR-RV IS Estimation ---")
print(f"Coefficients: const={har_model.params[0]:.6f}, β_d={har_model.params[1]:.4f}, "
      f"β_w={har_model.params[2]:.4f}, β_m={har_model.params[3]:.4f}")
print(f"IS R²: {har_model.rsquared:.4f}")
print(f"IS Adj R²: {har_model.rsquared_adj:.4f}")

# --- HAR-PD with best lambdas ---
lam1_best, lam2_best = best_lambdas
R1_best, R2_best = compute_path_features(rv_df['log_ret'], rv_df['rv'], lam1_best, lam2_best)

y_is_pd = rv_df['rv'].values[MIN_START + 1:IS_END]
X_is_pd = np.column_stack([
    rv_d[MIN_START:IS_END - 1],
    rv_w[MIN_START:IS_END - 1],
    rv_m[MIN_START:IS_END - 1],
    R1_best[MIN_START:IS_END - 1],
    R2_best[MIN_START:IS_END - 1],
])
valid_pd = ~np.isnan(X_is_pd).any(axis=1) & ~np.isnan(y_is_pd)
X_is_pd_v = sm.add_constant(X_is_pd[valid_pd])
y_is_pd_v = y_is_pd[valid_pd]

pd_model = sm.OLS(y_is_pd_v, X_is_pd_v).fit()
print(f"\n--- HAR-PD IS Estimation (λ₁={lam1_best}, λ₂={lam2_best}) ---")
coef_names = ['const', 'β_d', 'β_w', 'β_m', 'β_R1', 'β_R2']
for name, coef, se, pval in zip(coef_names, pd_model.params, pd_model.bse, pd_model.pvalues):
    sig = '***' if pval < 0.01 else ('**' if pval < 0.05 else ('*' if pval < 0.1 else ''))
    print(f"  {name:>6s} = {coef:>10.6f}  (SE={se:.6f}, p={pval:.4f}) {sig}")
print(f"IS R²: {pd_model.rsquared:.4f}")
print(f"IS Adj R²: {pd_model.rsquared_adj:.4f}")

# --- OOS predictions ---
y_oos = rv_df['rv'].values[OOS_START + 1:]  # target: RV from OOS_START+1 to end
n_oos = len(y_oos)

# HAR OOS
X_oos_har = np.column_stack([
    rv_d[OOS_START:-1],
    rv_w[OOS_START:-1],
    rv_m[OOS_START:-1],
])
# Ensure same length
X_oos_har = X_oos_har[:n_oos]
X_oos_har_c = sm.add_constant(X_oos_har)
har_oos_pred = har_model.predict(X_oos_har_c)
har_oos_pred = np.maximum(har_oos_pred, 1e-10)

# HAR-PD OOS
X_oos_pd = np.column_stack([
    rv_d[OOS_START:-1],
    rv_w[OOS_START:-1],
    rv_m[OOS_START:-1],
    R1_best[OOS_START:-1],
    R2_best[OOS_START:-1],
])
X_oos_pd = X_oos_pd[:n_oos]
X_oos_pd_c = sm.add_constant(X_oos_pd)
pd_oos_pred = pd_model.predict(X_oos_pd_c)
pd_oos_pred = np.maximum(pd_oos_pred, 1e-10)

# Naive mean forecast
naive_mean = rv_df['rv'].values[:OOS_START].mean()

# --- Metrics ---
har_qlike = qlike_loss(y_oos, har_oos_pred)
pd_qlike = qlike_loss(y_oos, pd_oos_pred)
har_mse = mse_loss(y_oos, har_oos_pred)
pd_mse = mse_loss(y_oos, pd_oos_pred)
naive_mse = mse_loss(y_oos, np.full(n_oos, naive_mean))

har_r2_oos = 1 - har_mse / naive_mse
pd_r2_oos = 1 - pd_mse / naive_mse

# Individual QLIKE losses for DM test
har_ql_individual = y_oos / har_oos_pred - np.log(y_oos / har_oos_pred) - 1
pd_ql_individual = y_oos / pd_oos_pred - np.log(y_oos / pd_oos_pred) - 1

dm_t, dm_p = dm_test(har_ql_individual, pd_ql_individual)

print(f"\n{'='*60}")
print("OOS Results (PILOT: N_OOS={})".format(n_oos))
print(f"{'='*60}")
print(f"\n{'Metric':<15} {'HAR-RV':>12} {'HAR-PD':>12} {'Improvement':>12}")
print(f"{'-'*51}")
print(f"{'QLIKE':<15} {har_qlike:>12.6f} {pd_qlike:>12.6f} {(1-pd_qlike/har_qlike)*100:>11.1f}%")
print(f"{'MSE':<15} {har_mse:>12.2e} {pd_mse:>12.2e} {(1-pd_mse/har_mse)*100:>11.1f}%")
print(f"{'R² OOS':<15} {har_r2_oos:>12.4f} {pd_r2_oos:>12.4f} {pd_r2_oos-har_r2_oos:>+12.4f}")
print(f"\nDM test (HAR vs HAR-PD, QLIKE):")
print(f"  t-stat = {dm_t:.4f}, p-value = {dm_p:.4f}")
print(f"  (positive t → HAR-PD better; Harvey 2016 threshold |t|>3.0)")
if abs(dm_t) < 3.0:
    print(f"  ⚠️  |t|={abs(dm_t):.2f} < 3.0 → NOT significant (expected with N={n_oos})")

# ============================================================
# Part F: Robustness — HAR-PD variants
# ============================================================

print(f"\n{'='*60}")
print("Robustness: HAR-PD Variants")
print(f"{'='*60}")

# Variant 1: R1 only (trend)
X_is_r1 = np.column_stack([
    rv_d[MIN_START:IS_END - 1],
    rv_w[MIN_START:IS_END - 1],
    rv_m[MIN_START:IS_END - 1],
    R1_best[MIN_START:IS_END - 1],
])
X_is_r1_v = sm.add_constant(X_is_r1[valid_pd])
r1_model = sm.OLS(y_is_pd_v, X_is_r1_v).fit()

X_oos_r1 = np.column_stack([
    rv_d[OOS_START:-1],
    rv_w[OOS_START:-1],
    rv_m[OOS_START:-1],
    R1_best[OOS_START:-1],
])[:n_oos]
r1_pred = np.maximum(r1_model.predict(sm.add_constant(X_oos_r1)), 1e-10)
r1_qlike = qlike_loss(y_oos, r1_pred)
r1_mse = mse_loss(y_oos, r1_pred)
r1_r2 = 1 - r1_mse / naive_mse

# Variant 2: R2 only (volatility memory)
X_is_r2 = np.column_stack([
    rv_d[MIN_START:IS_END - 1],
    rv_w[MIN_START:IS_END - 1],
    rv_m[MIN_START:IS_END - 1],
    R2_best[MIN_START:IS_END - 1],
])
X_is_r2_v = sm.add_constant(X_is_r2[valid_pd])
r2_model = sm.OLS(y_is_pd_v, X_is_r2_v).fit()

X_oos_r2 = np.column_stack([
    rv_d[OOS_START:-1],
    rv_w[OOS_START:-1],
    rv_m[OOS_START:-1],
    R2_best[OOS_START:-1],
])[:n_oos]
r2_pred = np.maximum(r2_model.predict(sm.add_constant(X_oos_r2)), 1e-10)
r2_qlike = qlike_loss(y_oos, r2_pred)
r2_mse = mse_loss(y_oos, r2_pred)
r2_r2 = 1 - r2_mse / naive_mse

print(f"\n{'Model':<20} {'QLIKE':>10} {'MSE':>12} {'R² OOS':>10}")
print(f"{'-'*52}")
print(f"{'HAR-RV':<20} {har_qlike:>10.6f} {har_mse:>12.2e} {har_r2_oos:>10.4f}")
print(f"{'HAR-PD (R1+R2)':<20} {pd_qlike:>10.6f} {pd_mse:>12.2e} {pd_r2_oos:>10.4f}")
print(f"{'HAR-PD (R1 only)':<20} {r1_qlike:>10.6f} {r1_mse:>12.2e} {r1_r2:>10.4f}")
print(f"{'HAR-PD (R2 only)':<20} {r2_qlike:>10.6f} {r2_mse:>12.2e} {r2_r2:>10.4f}")

# ============================================================
# Part G: Bootstrap confidence intervals
# ============================================================

print(f"\n{'='*60}")
print("Bootstrap (1000 reps) — QLIKE difference")
print(f"{'='*60}")

B = 1000
delta_qlike_boot = np.zeros(B)
for b in range(B):
    idx = np.random.choice(n_oos, size=n_oos, replace=True)
    boot_har_ql = np.mean(har_ql_individual[idx])
    boot_pd_ql = np.mean(pd_ql_individual[idx])
    delta_qlike_boot[b] = boot_har_ql - boot_pd_ql  # positive = PD better

ci_lo = np.percentile(delta_qlike_boot, 2.5)
ci_hi = np.percentile(delta_qlike_boot, 97.5)
pct_pd_better = np.mean(delta_qlike_boot > 0) * 100

print(f"ΔQLIKE (HAR - HAR-PD): mean={np.mean(delta_qlike_boot):.6f}")
print(f"95% CI: [{ci_lo:.6f}, {ci_hi:.6f}]")
print(f"HAR-PD better in {pct_pd_better:.1f}% of bootstrap samples")
if ci_lo > 0:
    print("→ HAR-PD significantly better (CI excludes 0)")
elif ci_hi < 0:
    print("→ HAR significantly better (CI excludes 0)")
else:
    print("→ No significant difference (CI includes 0)")

# ============================================================
# Part H: Comparison with K624 (daily r² version)
# ============================================================

print(f"\n{'='*60}")
print("Comparison with K624 (daily r² proxy)")
print(f"{'='*60}")
print(f"K624 (daily r²):  HAR QLIKE=1.531, HAR-PD QLIKE=2.877 → PD 88% WORSE")
print(f"K966 (5-min RV):  HAR QLIKE={har_qlike:.4f}, HAR-PD QLIKE={pd_qlike:.4f}", end="")
if pd_qlike < har_qlike:
    print(f" → PD {(1-pd_qlike/har_qlike)*100:.1f}% better")
elif pd_qlike > har_qlike:
    print(f" → PD {(pd_qlike/har_qlike-1)*100:.1f}% worse")
else:
    print(f" → identical")

# ============================================================
# Part I: Plots
# ============================================================

# Plot 1: Lambda grid search heatmap
fig, ax = plt.subplots(figsize=(8, 6))
lam1_vals = sorted(set(l1 for l1, _ in grid_results.keys()))
lam2_vals = sorted(set(l2 for _, l2 in grid_results.keys()))
grid_matrix = np.full((len(lam1_vals), len(lam2_vals)), np.nan)
for i, l1 in enumerate(lam1_vals):
    for j, l2 in enumerate(lam2_vals):
        if (l1, l2) in grid_results:
            grid_matrix[i, j] = grid_results[(l1, l2)]

im = ax.imshow(grid_matrix, cmap='RdYlGn_r', aspect='auto')
ax.set_xticks(range(len(lam2_vals)))
ax.set_xticklabels([f'{l:.2f}' for l in lam2_vals], rotation=45)
ax.set_yticks(range(len(lam1_vals)))
ax.set_yticklabels([f'{l:.2f}' for l in lam1_vals])
ax.set_xlabel('λ₂ (volatility memory decay)')
ax.set_ylabel('λ₁ (trend decay)')
ax.set_title('HAR-PD: λ Grid Search (IS QLIKE, lower=better)')
plt.colorbar(im, label='QLIKE')

# Mark best
best_i = lam1_vals.index(best_lambdas[0])
best_j = lam2_vals.index(best_lambdas[1])
ax.plot(best_j, best_i, 'k*', markersize=15, label=f'Best: λ₁={best_lambdas[0]}, λ₂={best_lambdas[1]}')
ax.legend(loc='upper right')

plt.tight_layout()
plt.savefig(os.path.join(OUT_DIR, 'k966_lambda_grid.png'), dpi=150)
plt.close()
print(f"\nSaved: k966_lambda_grid.png")

# Plot 2: Forecast comparison
fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)

oos_dates = rv_df['date'].values[OOS_START + 1:OOS_START + 1 + n_oos]

# Panel A: Actual vs forecasts
ax = axes[0]
ax.plot(oos_dates, y_oos * 1e4, 'ko-', markersize=4, label='Actual RV', linewidth=1.5)
ax.plot(oos_dates, har_oos_pred * 1e4, 'b^--', markersize=4, label=f'HAR (QLIKE={har_qlike:.4f})', alpha=0.8)
ax.plot(oos_dates, pd_oos_pred * 1e4, 'rs--', markersize=4, label=f'HAR-PD (QLIKE={pd_qlike:.4f})', alpha=0.8)
ax.set_ylabel('RV (×10⁴)')
ax.set_title('K966: HAR vs HAR-PD Forecast Comparison (OOS)')
ax.legend(fontsize=9)
ax.grid(True, alpha=0.3)

# Panel B: Forecast errors
ax = axes[1]
har_err = (y_oos - har_oos_pred) * 1e4
pd_err = (y_oos - pd_oos_pred) * 1e4
ax.bar(oos_dates, har_err, width=0.8, alpha=0.5, label='HAR error', color='blue')
ax.bar(oos_dates, pd_err, width=0.4, alpha=0.7, label='HAR-PD error', color='red')
ax.axhline(0, color='black', linewidth=0.5)
ax.set_ylabel('Forecast Error (×10⁴)')
ax.set_xlabel('Date')
ax.legend(fontsize=9)
ax.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig(os.path.join(OUT_DIR, 'k966_forecast_comparison.png'), dpi=150)
plt.close()
print(f"Saved: k966_forecast_comparison.png")

# ============================================================
# Part J: Save results
# ============================================================

results = {
    "experiment_id": "K966",
    "title": "HAR-PD Path-Dependent RV Forecasting (5-min, Pilot)",
    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "data_source": "yfinance 5-min intraday SPY",
    "period": f"{rv_df['date'].iloc[0].strftime('%Y-%m-%d')} to {rv_df['date'].iloc[-1].strftime('%Y-%m-%d')}",
    "n_total": int(N),
    "n_is": int(IS_END),
    "n_oos": int(n_oos),
    "is_pilot_study": True,
    "pilot_caveat": "N_OOS=19 insufficient for DM significance; results are preliminary",
    "references": [
        "Guyon & Lekeufack (2023), 'Volatility is (Mostly) Path-Dependent', arXiv:2503.00851",
        "Corsi (2009), JFE 7(2):174-196",
        "Patton (2011), JoE 160(1):246-256"
    ],
    "related_experiments": {
        "K624": "HAR-PD on daily r² → NULL (PD 88% worse)",
        "K960": "HAR-RV on 5-min RV → R²=0.243, QLIKE=0.118"
    },
    "lambda_grid_search": {
        "grid": LAMBDA_GRID,
        "best_lambda1": best_lambdas[0],
        "best_lambda2": best_lambdas[1],
        "best_is_qlike": round(best_qlike, 6),
        "top_5": [
            {"lambda1": l1, "lambda2": l2, "qlike": round(ql, 6)}
            for (l1, l2), ql in sorted_grid[:5]
        ]
    },
    "har_rv": {
        "is_r2": round(har_model.rsquared, 4),
        "is_adj_r2": round(har_model.rsquared_adj, 4),
        "coefficients": {
            "const": round(float(har_model.params[0]), 6),
            "beta_d": round(float(har_model.params[1]), 4),
            "beta_w": round(float(har_model.params[2]), 4),
            "beta_m": round(float(har_model.params[3]), 4),
        },
        "oos_qlike": round(har_qlike, 6),
        "oos_mse": float(f"{har_mse:.4e}"),
        "oos_r2": round(har_r2_oos, 4),
    },
    "har_pd": {
        "lambda1": best_lambdas[0],
        "lambda2": best_lambdas[1],
        "is_r2": round(pd_model.rsquared, 4),
        "is_adj_r2": round(pd_model.rsquared_adj, 4),
        "coefficients": {
            name: {
                "value": round(float(coef), 6),
                "se": round(float(se), 6),
                "pvalue": round(float(pval), 4),
            }
            for name, coef, se, pval in zip(coef_names, pd_model.params, pd_model.bse, pd_model.pvalues)
        },
        "oos_qlike": round(pd_qlike, 6),
        "oos_mse": float(f"{pd_mse:.4e}"),
        "oos_r2": round(pd_r2_oos, 4),
    },
    "variants": {
        "har_pd_r1_only": {"oos_qlike": round(r1_qlike, 6), "oos_r2": round(r1_r2, 4)},
        "har_pd_r2_only": {"oos_qlike": round(r2_qlike, 6), "oos_r2": round(r2_r2, 4)},
    },
    "dm_test": {
        "t_stat": round(dm_t, 4),
        "p_value": round(dm_p, 4),
        "significant_at_harvey_threshold": bool(abs(dm_t) > 3.0),
        "note": "positive t → HAR-PD better"
    },
    "bootstrap": {
        "n_reps": B,
        "seed": 42,
        "delta_qlike_mean": round(float(np.mean(delta_qlike_boot)), 6),
        "ci_95_lower": round(float(ci_lo), 6),
        "ci_95_upper": round(float(ci_hi), 6),
        "pct_pd_better": round(float(pct_pd_better), 1),
        "significant": bool(float(ci_lo) > 0 or float(ci_hi) < 0),
    },
    "conclusion": "",  # will be filled below
}

# Generate conclusion
if pd_qlike < har_qlike:
    improvement = (1 - pd_qlike / har_qlike) * 100
    if results["bootstrap"]["significant"]:
        conclusion = (f"HAR-PD improves over HAR-RV by {improvement:.1f}% in QLIKE (significant via bootstrap). "
                      f"Path-dependent features capture additional volatility dynamics with 5-min RV data. "
                      f"This contrasts with K624 where daily r² proxy showed PD 88% worse.")
    else:
        conclusion = (f"HAR-PD shows {improvement:.1f}% QLIKE improvement over HAR-RV but NOT statistically "
                      f"significant (bootstrap CI includes 0, DM |t|={abs(dm_t):.2f}<3.0). "
                      f"Pilot study with N_OOS={n_oos}: need 100+ days for reliable inference. "
                      f"Direction is promising vs K624 daily NULL result.")
elif pd_qlike > har_qlike:
    deterioration = (pd_qlike / har_qlike - 1) * 100
    conclusion = (f"HAR-PD is {deterioration:.1f}% worse than HAR-RV in QLIKE, confirming K624 NULL result. "
                  f"Path-dependent features do NOT improve RV forecasting even with 5-min data. "
                  f"N_OOS={n_oos} (pilot), but direction is consistently negative.")
else:
    conclusion = f"HAR-PD and HAR-RV are identical. N_OOS={n_oos} (pilot)."

results["conclusion"] = conclusion
print(f"\n{'='*60}")
print(f"CONCLUSION: {conclusion}")
print(f"{'='*60}")

with open(os.path.join(OUT_DIR, 'k966_har_pd_results.json'), 'w') as f:
    json.dump(results, f, indent=2, ensure_ascii=False)
print(f"\nSaved: k966_har_pd_results.json")

print("\n✅ K966 complete.")
