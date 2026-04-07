"""
K960: HAR-RV Formal Experiment — SPY 5-min Realized Variance
============================================================
Data source: yfinance 5-min intraday data for SPY
Period: 2026-01-14 to 2026-04-06 (56 trading days)
Method: HAR-RV (Corsi 2009) with OLS estimation
Reference: Corsi, F. (2009). "A Simple Approximate Long-Memory Model of Realized Volatility."
           Journal of Financial Econometrics, 7(2), 174-196.
           Patton, A. (2011). "Volatility Forecast Comparison Using Imperfect Volatility Proxies."
           Journal of Econometrics, 160(1), 246-256.

Related experiments: K188 (HAR on daily data), K744 (RV autocorrelation), K465/K469 (HAR log-range)
"""

import numpy as np
import pandas as pd
import os
import json
import glob
import warnings
from datetime import datetime
from scipy import stats
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

np.random.seed(42)
warnings.filterwarnings('ignore')

# ============================================================
# Part A: Load 5-min data and compute daily RV
# ============================================================

# Try worktree-local first, fall back to main repo (data is gitignored)
DATA_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'intraday')
if not os.path.exists(DATA_DIR) or len(glob.glob(os.path.join(DATA_DIR, 'SPY_5min_*.csv'))) == 0:
    DATA_DIR = '/Users/yhlai0911/Desktop/volpred-research/data/intraday'
OUT_DIR = os.path.dirname(__file__)

def load_5min_data(data_dir):
    """Load all SPY 5-min CSV files and compute daily RV."""
    files = sorted(glob.glob(os.path.join(data_dir, 'SPY_5min_*.csv')))
    print(f"Found {len(files)} 5-min data files")

    daily_rv = {}
    daily_close = {}
    daily_open = {}

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

        # Compute 5-min log returns
        log_ret = np.log(df['Close'].values[1:] / df['Close'].values[:-1])

        # RV = sum of squared log returns
        rv = np.sum(log_ret ** 2)
        daily_rv[date_str] = rv
        daily_close[date_str] = df['Close'].values[-1]
        daily_open[date_str] = df['Close'].values[0]  # first bar close ~ open

    # Convert to sorted DataFrame
    rv_df = pd.DataFrame({
        'date': list(daily_rv.keys()),
        'rv': list(daily_rv.values()),
        'close': [daily_close[d] for d in daily_rv.keys()],
    })
    rv_df['date'] = pd.to_datetime(rv_df['date'])
    rv_df = rv_df.sort_values('date').reset_index(drop=True)

    # Compute daily close-to-close returns for GARCH comparison
    rv_df['daily_ret'] = np.log(rv_df['close'] / rv_df['close'].shift(1))
    rv_df['r_squared'] = rv_df['daily_ret'] ** 2

    return rv_df


print("=" * 60)
print("Part A: RV Calculation and Descriptive Statistics")
print("=" * 60)

rv_df = load_5min_data(DATA_DIR)
print(f"\nLoaded {len(rv_df)} days of data: {rv_df['date'].min().date()} to {rv_df['date'].max().date()}")

# Descriptive statistics
rv_vals = rv_df['rv'].values
rv_ann = rv_vals * 252  # Annualized variance
rv_vol_ann = np.sqrt(rv_ann)  # Annualized vol

print(f"\n--- RV Descriptive Statistics ---")
print(f"  N days:         {len(rv_vals)}")
print(f"  Mean RV:        {np.mean(rv_vals):.8f}")
print(f"  Std RV:         {np.std(rv_vals):.8f}")
print(f"  Min RV:         {np.min(rv_vals):.8f}")
print(f"  Max RV:         {np.max(rv_vals):.8f}")
print(f"  Skewness:       {stats.skew(rv_vals):.4f}")
print(f"  Kurtosis:       {stats.kurtosis(rv_vals):.4f}")
print(f"  Mean Ann Vol:   {np.mean(rv_vol_ann)*100:.2f}%")
print(f"  Median Ann Vol: {np.median(rv_vol_ann)*100:.2f}%")

# Autocorrelation
print(f"\n--- Autocorrelation of RV ---")
ac_values = []
for lag in range(1, 11):
    ac = pd.Series(rv_vals).autocorr(lag=lag)
    ac_values.append(ac)
    print(f"  AC({lag:2d}): {ac:.4f}")

# Compare with daily r² autocorrelation
r2_vals = rv_df['r_squared'].dropna().values
print(f"\n--- Daily r² Autocorrelation (for comparison) ---")
r2_ac_values = []
for lag in range(1, 6):
    ac = pd.Series(r2_vals).autocorr(lag=lag)
    r2_ac_values.append(ac)
    print(f"  AC({lag:2d}): {ac:.4f}")

print(f"\n  RV AC(1) / r² AC(1) ratio: {ac_values[0] / r2_ac_values[0]:.2f}x")

# Ljung-Box test
from statsmodels.stats.diagnostic import acorr_ljungbox
lb_result = acorr_ljungbox(rv_vals, lags=[5, 10], return_df=True)
print(f"\n--- Ljung-Box Test for RV ---")
for idx, row in lb_result.iterrows():
    print(f"  Lag {idx}: Q={row['lb_stat']:.4f}, p-value={row['lb_pvalue']:.6f}")

# ADF test on RV
from statsmodels.tsa.stattools import adfuller
adf_result = adfuller(rv_vals, maxlag=5)
print(f"\n--- ADF Test for RV Stationarity ---")
print(f"  ADF Statistic: {adf_result[0]:.4f}")
print(f"  p-value:       {adf_result[1]:.6f}")
print(f"  Stationary:    {'Yes' if adf_result[1] < 0.05 else 'No'}")


# ============================================================
# Part B: HAR-RV Model Estimation
# ============================================================
print("\n" + "=" * 60)
print("Part B: HAR-RV Model Estimation")
print("=" * 60)

def compute_har_features(rv_series):
    """Compute HAR-RV features: RV_d, RV_w (5-day avg), RV_m (22-day avg)."""
    n = len(rv_series)
    rv_d = rv_series.copy()

    # Weekly: 5-day rolling average
    rv_w = pd.Series(rv_series).rolling(window=5).mean().values

    # Monthly: 22-day rolling average
    rv_m = pd.Series(rv_series).rolling(window=22).mean().values

    return rv_d, rv_w, rv_m


rv_series = rv_df['rv'].values
rv_d, rv_w, rv_m = compute_har_features(rv_series)

# Find first valid index (need 22 days for monthly component)
first_valid = 22  # Index where rv_m first becomes non-NaN (0-indexed, day 22)

# Construct regression data: predict RV_{t+1} from (RV_t, RV_w_t, RV_m_t)
# X features at time t, Y target at time t+1
X_dates = rv_df['date'].values[first_valid:-1]  # t = first_valid ... N-2
Y_dates = rv_df['date'].values[first_valid+1:]  # t+1 = first_valid+1 ... N-1

X_rv_d = rv_d[first_valid:-1]
X_rv_w = rv_w[first_valid:-1]
X_rv_m = rv_m[first_valid:-1]
Y_rv = rv_series[first_valid+1:]

n_total = len(Y_rv)
print(f"\nTotal usable observations: {n_total} (after 22-day monthly lookback)")
print(f"  Prediction period: {pd.Timestamp(X_dates[0]).date()} to {pd.Timestamp(X_dates[-1]).date()}")

# Split: use expanding window with minimum IS = 14 observations
MIN_IS = 14
n_oos = n_total - MIN_IS
print(f"  In-sample (initial): {MIN_IS} days")
print(f"  Out-of-sample: {n_oos} days")

# Full-sample OLS for parameter analysis
from numpy.linalg import lstsq
X_full = np.column_stack([np.ones(n_total), X_rv_d, X_rv_w, X_rv_m])
betas_full, residuals, rank, sv = lstsq(X_full, Y_rv, rcond=None)

print(f"\n--- Full-sample HAR-RV OLS Estimates ---")
print(f"  Intercept (c):   {betas_full[0]:.8f}")
print(f"  beta_d (daily):  {betas_full[1]:.4f}")
print(f"  beta_w (weekly):  {betas_full[2]:.4f}")
print(f"  beta_m (monthly): {betas_full[3]:.4f}")

# R² full sample
Y_hat_full = X_full @ betas_full
ss_res = np.sum((Y_rv - Y_hat_full) ** 2)
ss_tot = np.sum((Y_rv - np.mean(Y_rv)) ** 2)
r2_full = 1 - ss_res / ss_tot
print(f"  In-sample R²:    {r2_full:.4f}")

# Standard errors (OLS)
n_obs, k = X_full.shape
sigma2_hat = ss_res / (n_obs - k)
cov_beta = sigma2_hat * np.linalg.inv(X_full.T @ X_full)
se_beta = np.sqrt(np.diag(cov_beta))
t_stats = betas_full / se_beta
p_values = 2 * (1 - stats.t.cdf(np.abs(t_stats), n_obs - k))

print(f"\n--- Coefficient Tests ---")
labels = ['Intercept', 'beta_d', 'beta_w', 'beta_m']
for i, lab in enumerate(labels):
    sig = '***' if p_values[i] < 0.01 else '**' if p_values[i] < 0.05 else '*' if p_values[i] < 0.1 else ''
    print(f"  {lab:12s}: {betas_full[i]:10.6f} (SE={se_beta[i]:.6f}, t={t_stats[i]:.3f}, p={p_values[i]:.4f}) {sig}")

# Residual diagnostics
resid_full = Y_rv - Y_hat_full
resid_std = resid_full / np.std(resid_full)
lb_resid = acorr_ljungbox(resid_std, lags=[5, 10], return_df=True)
print(f"\n--- Residual Diagnostics (Full Sample) ---")
print(f"  Mean residual: {np.mean(resid_full):.8f}")
print(f"  Ljung-Box on standardized residuals:")
for idx, row in lb_resid.iterrows():
    print(f"    Lag {idx}: Q={row['lb_stat']:.4f}, p-value={row['lb_pvalue']:.4f}")


# ============================================================
# Part C: OOS Prediction with Expanding Window
# ============================================================
print("\n" + "=" * 60)
print("Part C: Out-of-Sample Prediction (Expanding Window)")
print("=" * 60)

oos_forecasts = []
oos_actuals = []
oos_dates = []
oos_naive = []  # Naive forecast = yesterday's RV

for i in range(MIN_IS, n_total):
    # Expanding window: use all data from 0 to i-1 for estimation
    X_is = np.column_stack([np.ones(i), X_rv_d[:i], X_rv_w[:i], X_rv_m[:i]])
    Y_is = Y_rv[:i]

    betas_is, _, _, _ = lstsq(X_is, Y_is, rcond=None)

    # Forecast for time i
    x_i = np.array([1, X_rv_d[i], X_rv_w[i], X_rv_m[i]])
    forecast = x_i @ betas_is
    forecast = max(forecast, 1e-10)  # Floor at small positive value

    oos_forecasts.append(forecast)
    oos_actuals.append(Y_rv[i])
    oos_dates.append(X_dates[i])
    oos_naive.append(X_rv_d[i])  # Naive = previous day RV

oos_forecasts = np.array(oos_forecasts)
oos_actuals = np.array(oos_actuals)
oos_naive = np.array(oos_naive)
oos_dates = np.array(oos_dates)

# Evaluation metrics on RV target
def compute_metrics(actual, forecast, naive=None):
    """Compute forecast evaluation metrics."""
    mse = np.mean((actual - forecast) ** 2)
    mae = np.mean(np.abs(actual - forecast))
    rmse = np.sqrt(mse)

    # QLIKE (Patton 2011) - proxy-robust loss for variance
    # QLIKE = mean(actual/forecast - log(actual/forecast) - 1)
    ratio = actual / forecast
    qlike = np.mean(ratio - np.log(ratio) - 1)

    # OOS R² vs naive
    if naive is not None:
        mse_naive = np.mean((actual - naive) ** 2)
        oos_r2 = 1 - mse / mse_naive
    else:
        oos_r2 = None

    # Mincer-Zarnowitz regression
    X_mz = np.column_stack([np.ones(len(actual)), forecast])
    betas_mz, _, _, _ = lstsq(X_mz, actual, rcond=None)
    Y_hat_mz = X_mz @ betas_mz
    ss_res_mz = np.sum((actual - Y_hat_mz) ** 2)
    ss_tot_mz = np.sum((actual - np.mean(actual)) ** 2)
    mz_r2 = 1 - ss_res_mz / ss_tot_mz

    return {
        'MSE': mse,
        'RMSE': rmse,
        'MAE': mae,
        'QLIKE': qlike,
        'OOS_R2': oos_r2,
        'MZ_alpha': betas_mz[0],
        'MZ_beta': betas_mz[1],
        'MZ_R2': mz_r2,
    }

har_metrics = compute_metrics(oos_actuals, oos_forecasts, oos_naive)
naive_metrics = compute_metrics(oos_actuals, oos_naive)

print(f"\nOOS period: {pd.Timestamp(oos_dates[0]).date()} to {pd.Timestamp(oos_dates[-1]).date()} ({len(oos_dates)} days)")

print(f"\n--- HAR-RV OOS Metrics ---")
print(f"  MSE:       {har_metrics['MSE']:.12f}")
print(f"  RMSE:      {har_metrics['RMSE']:.8f}")
print(f"  MAE:       {har_metrics['MAE']:.8f}")
print(f"  QLIKE:     {har_metrics['QLIKE']:.6f}")
print(f"  OOS R²:    {har_metrics['OOS_R2']:.4f} (vs naive=yesterday's RV)")
print(f"  MZ alpha:  {har_metrics['MZ_alpha']:.8f} (should be ~0)")
print(f"  MZ beta:   {har_metrics['MZ_beta']:.4f} (should be ~1)")
print(f"  MZ R²:     {har_metrics['MZ_R2']:.4f}")

print(f"\n--- Naive (RV_{{t-1}}) OOS Metrics ---")
print(f"  MSE:       {naive_metrics['MSE']:.12f}")
print(f"  RMSE:      {naive_metrics['RMSE']:.8f}")
print(f"  MAE:       {naive_metrics['MAE']:.8f}")
print(f"  QLIKE:     {naive_metrics['QLIKE']:.6f}")

# Spearman rank correlation
from scipy.stats import spearmanr
sp_corr, sp_pval = spearmanr(oos_actuals, oos_forecasts)
sp_naive, sp_naive_pval = spearmanr(oos_actuals, oos_naive)
print(f"\n--- Rank Correlation ---")
print(f"  HAR-RV Spearman rho:  {sp_corr:.4f} (p={sp_pval:.4f})")
print(f"  Naive  Spearman rho:  {sp_naive:.4f} (p={sp_naive_pval:.4f})")


# ============================================================
# Part D: GARCH Comparison (Fair Cross-Model)
# ============================================================
print("\n" + "=" * 60)
print("Part D: GARCH Comparison (Fair Cross-Model)")
print("=" * 60)

from arch import arch_model

# Use daily returns for GARCH
daily_ret_full = rv_df['daily_ret'].dropna().values * 100  # in percent
dates_for_garch = rv_df['date'].values[1:]  # skip first NaN

# Align with OOS period
# Find indices in daily_ret_full that correspond to OOS dates
oos_start_date = pd.Timestamp(oos_dates[0])
oos_end_date = pd.Timestamp(oos_dates[-1])

# GARCH expanding window OOS
# Use all available daily data before OOS start for initial estimation
all_dates = rv_df['date'].values[1:]  # after differencing
all_rets = daily_ret_full

# Find index of OOS start in all_dates
oos_start_idx = None
for i, d in enumerate(all_dates):
    if pd.Timestamp(d) >= oos_start_date:
        oos_start_idx = i
        break

if oos_start_idx is None:
    print("ERROR: Could not find OOS start date in GARCH data")
else:
    print(f"GARCH estimation starts with {oos_start_idx} observations")
    print(f"GARCH OOS: {len(all_dates) - oos_start_idx} days")

    garch_forecasts = []
    garch_dates = []

    for i in range(oos_start_idx, len(all_rets)):
        # Expanding window
        rets_is = all_rets[:i]

        try:
            am = arch_model(rets_is, vol='GARCH', p=1, q=1, dist='normal', rescale=False)
            res = am.fit(disp='off', show_warning=False)

            # One-step ahead variance forecast (in %^2)
            fc = res.forecast(horizon=1)
            var_forecast = fc.variance.values[-1, 0] / 10000  # Convert back from %^2
            garch_forecasts.append(var_forecast)
            garch_dates.append(all_dates[i])
        except Exception as e:
            garch_forecasts.append(np.nan)
            garch_dates.append(all_dates[i])

    garch_forecasts = np.array(garch_forecasts)
    garch_dates = np.array(garch_dates)

    # Also try GJR-GARCH
    gjr_forecasts = []
    for i in range(oos_start_idx, len(all_rets)):
        rets_is = all_rets[:i]
        try:
            am = arch_model(rets_is, vol='GARCH', p=1, o=1, q=1, dist='normal', rescale=False)
            res = am.fit(disp='off', show_warning=False)
            fc = res.forecast(horizon=1)
            var_forecast = fc.variance.values[-1, 0] / 10000
            gjr_forecasts.append(var_forecast)
        except Exception:
            gjr_forecasts.append(np.nan)

    gjr_forecasts = np.array(gjr_forecasts)

    # Align HAR and GARCH OOS periods
    # Match dates
    har_oos_dates_set = set(pd.Timestamp(d).date() for d in oos_dates)
    garch_oos_dates_set = set(pd.Timestamp(d).date() for d in garch_dates)
    common_dates = sorted(har_oos_dates_set & garch_oos_dates_set)

    print(f"\nCommon OOS dates: {len(common_dates)}")

    if len(common_dates) > 5:
        # Get aligned arrays
        har_map = {pd.Timestamp(d).date(): (oos_actuals[i], oos_forecasts[i])
                   for i, d in enumerate(oos_dates)}
        garch_map = {pd.Timestamp(d).date(): garch_forecasts[i]
                     for i, d in enumerate(garch_dates)}
        gjr_map = {pd.Timestamp(d).date(): gjr_forecasts[i]
                   for i, d in enumerate(garch_dates)}

        # Also need daily r² for the common dates
        r2_map = {rv_df['date'].values[i+1]: rv_df['r_squared'].values[i+1]
                  for i in range(len(rv_df)-1) if not np.isnan(rv_df['r_squared'].values[i+1])}
        r2_date_map = {pd.Timestamp(d).date(): v for d, v in r2_map.items()}

        aligned_rv_actual = []
        aligned_r2_actual = []
        aligned_har = []
        aligned_garch = []
        aligned_gjr = []
        aligned_common_dates = []

        for d in common_dates:
            if d in har_map and d in garch_map and d in r2_date_map:
                rv_act, har_fc = har_map[d]
                aligned_rv_actual.append(rv_act)
                aligned_r2_actual.append(r2_date_map[d])
                aligned_har.append(har_fc)
                aligned_garch.append(garch_map[d])
                aligned_gjr.append(gjr_map[d])
                aligned_common_dates.append(d)

        aligned_rv_actual = np.array(aligned_rv_actual)
        aligned_r2_actual = np.array(aligned_r2_actual)
        aligned_har = np.array(aligned_har)
        aligned_garch = np.array(aligned_garch)
        aligned_gjr = np.array(aligned_gjr)

        n_common = len(aligned_rv_actual)
        print(f"Aligned observations: {n_common}")

        # === Native target evaluation ===
        print(f"\n--- Native Target Evaluation ---")
        print(f"  HAR-RV on RV target:")
        har_on_rv = compute_metrics(aligned_rv_actual, aligned_har)
        print(f"    QLIKE: {har_on_rv['QLIKE']:.6f}, MZ R²: {har_on_rv['MZ_R2']:.4f}")

        print(f"  GARCH on r² target:")
        garch_on_r2 = compute_metrics(aligned_r2_actual, aligned_garch)
        print(f"    QLIKE: {garch_on_r2['QLIKE']:.6f}, MZ R²: {garch_on_r2['MZ_R2']:.4f}")

        print(f"  GJR-GARCH on r² target:")
        gjr_on_r2 = compute_metrics(aligned_r2_actual, aligned_gjr)
        print(f"    QLIKE: {gjr_on_r2['QLIKE']:.6f}, MZ R²: {gjr_on_r2['MZ_R2']:.4f}")

        # === Cross-model comparison: Patton (2011) QLIKE on r² ===
        # This is proxy-robust: using r² as proxy for true variance
        print(f"\n--- Cross-Model: Patton (2011) QLIKE on r² ---")
        har_qlike_r2 = np.mean(aligned_r2_actual / aligned_har - np.log(aligned_r2_actual / aligned_har) - 1)
        garch_qlike_r2 = np.mean(aligned_r2_actual / aligned_garch - np.log(aligned_r2_actual / aligned_garch) - 1)
        gjr_qlike_r2 = np.mean(aligned_r2_actual / aligned_gjr - np.log(aligned_r2_actual / aligned_gjr) - 1)

        print(f"  HAR-RV  QLIKE(r²): {har_qlike_r2:.6f}")
        print(f"  GARCH   QLIKE(r²): {garch_qlike_r2:.6f}")
        print(f"  GJR     QLIKE(r²): {gjr_qlike_r2:.6f}")

        # Rank by QLIKE (lower = better)
        models_qlike = [('HAR-RV', har_qlike_r2), ('GARCH', garch_qlike_r2), ('GJR-GARCH', gjr_qlike_r2)]
        models_qlike.sort(key=lambda x: x[1])
        print(f"\n  Ranking (lower QLIKE = better):")
        for rank, (name, q) in enumerate(models_qlike, 1):
            print(f"    {rank}. {name}: {q:.6f}")

        # === Spearman rank correlation on r² ===
        print(f"\n--- Spearman Rank Correlation (forecast vs r²) ---")
        sp_har, sp_har_p = spearmanr(aligned_r2_actual, aligned_har)
        sp_garch, sp_garch_p = spearmanr(aligned_r2_actual, aligned_garch)
        sp_gjr, sp_gjr_p = spearmanr(aligned_r2_actual, aligned_gjr)
        print(f"  HAR-RV:     rho={sp_har:.4f} (p={sp_har_p:.4f})")
        print(f"  GARCH:      rho={sp_garch:.4f} (p={sp_garch_p:.4f})")
        print(f"  GJR-GARCH:  rho={sp_gjr:.4f} (p={sp_gjr_p:.4f})")

        # === DM test (if enough observations) ===
        print(f"\n--- Diebold-Mariano Test (QLIKE loss, HAR vs GARCH) ---")
        # DM test: H0: equal predictive ability
        loss_har = aligned_r2_actual / aligned_har - np.log(aligned_r2_actual / aligned_har) - 1
        loss_garch = aligned_r2_actual / aligned_garch - np.log(aligned_r2_actual / aligned_garch) - 1
        loss_gjr = aligned_r2_actual / aligned_gjr - np.log(aligned_r2_actual / aligned_gjr) - 1

        d_hg = loss_har - loss_garch  # HAR vs GARCH
        d_hgjr = loss_har - loss_gjr  # HAR vs GJR

        def dm_test(d):
            """Simple DM test statistic."""
            n = len(d)
            d_bar = np.mean(d)
            # HAC variance (Newey-West with 1 lag for short sample)
            gamma0 = np.var(d, ddof=1)
            if n > 2:
                gamma1 = np.cov(d[1:], d[:-1])[0, 1]
                var_d = (gamma0 + 2 * gamma1) / n
            else:
                var_d = gamma0 / n
            if var_d <= 0:
                return np.nan, np.nan
            dm_stat = d_bar / np.sqrt(var_d)
            dm_pval = 2 * (1 - stats.t.cdf(np.abs(dm_stat), n - 1))
            return dm_stat, dm_pval

        dm_hg, dm_hg_p = dm_test(d_hg)
        dm_hgjr, dm_hgjr_p = dm_test(d_hgjr)

        print(f"  HAR vs GARCH:     DM={dm_hg:.3f}, p={dm_hg_p:.4f}")
        print(f"  HAR vs GJR-GARCH: DM={dm_hgjr:.3f}, p={dm_hgjr_p:.4f}")
        print(f"  (negative DM = HAR has lower loss = HAR better)")
        print(f"  Note: {n_common} obs is FAR below Harvey (2016) threshold. DM results are indicative only.")


# ============================================================
# Part E: HAR-RV VT Strategy Pilot
# ============================================================
print("\n" + "=" * 60)
print("Part E: HAR-RV VT Strategy Pilot (Very Short Sample Caveat)")
print("=" * 60)

# Align with daily returns for the OOS period
oos_ret_map = {}
for i in range(len(rv_df)):
    d = rv_df['date'].values[i]
    if not np.isnan(rv_df['daily_ret'].values[i]):
        oos_ret_map[pd.Timestamp(d).date()] = rv_df['daily_ret'].values[i]

# VT: w_t = sigma_target / sigma_HAR_forecast
# sigma_target = 15% annualized (reasonable for SPY)
sigma_target = 0.15

vt_dates = []
vt_weights = []
vt_returns = []
bh_returns = []

for i, d in enumerate(oos_dates):
    d_date = pd.Timestamp(d).date()
    # Next day's date for return
    if i + 1 < len(oos_dates):
        next_d = pd.Timestamp(oos_dates[i + 1]).date()
    else:
        # Last day - skip
        continue

    if next_d not in oos_ret_map:
        continue

    # signal.shift(1): forecast from day t, applied to day t+1 return
    rv_forecast = oos_forecasts[i]
    sigma_forecast_ann = np.sqrt(rv_forecast * 252)

    if sigma_forecast_ann > 0:
        w = sigma_target / sigma_forecast_ann
        w = np.clip(w, 0.1, 2.0)  # Cap leverage
    else:
        w = 1.0

    ret_next = oos_ret_map[next_d]

    vt_dates.append(next_d)
    vt_weights.append(w)
    vt_returns.append(w * ret_next)
    bh_returns.append(ret_next)

vt_returns = np.array(vt_returns)
bh_returns = np.array(bh_returns)
vt_weights = np.array(vt_weights)

if len(vt_returns) > 5:
    vt_cum = np.cumprod(1 + vt_returns) - 1
    bh_cum = np.cumprod(1 + bh_returns) - 1

    vt_sharpe = np.mean(vt_returns) / np.std(vt_returns) * np.sqrt(252) if np.std(vt_returns) > 0 else 0
    bh_sharpe = np.mean(bh_returns) / np.std(bh_returns) * np.sqrt(252) if np.std(bh_returns) > 0 else 0

    print(f"\nVT Strategy (sigma_target=15%, HAR-RV forecast, lag=1)")
    print(f"  Period: {vt_dates[0]} to {vt_dates[-1]} ({len(vt_returns)} days)")
    print(f"  Mean weight: {np.mean(vt_weights):.3f}")
    print(f"  Weight range: [{np.min(vt_weights):.3f}, {np.max(vt_weights):.3f}]")
    print(f"  VT cumulative return:  {vt_cum[-1]*100:.2f}%")
    print(f"  BH cumulative return:  {bh_cum[-1]*100:.2f}%")
    print(f"  VT annualized Sharpe:  {vt_sharpe:.3f}")
    print(f"  BH annualized Sharpe:  {bh_sharpe:.3f}")
    print(f"  VT daily vol (ann):    {np.std(vt_returns)*np.sqrt(252)*100:.2f}%")
    print(f"  BH daily vol (ann):    {np.std(bh_returns)*np.sqrt(252)*100:.2f}%")
    print(f"\n  *** CAVEAT: {len(vt_returns)} days is FAR too short for reliable strategy evaluation ***")
    print(f"  *** This is a directional pilot only, not a valid backtest ***")
else:
    vt_sharpe = None
    bh_sharpe = None
    print("Not enough data for VT strategy pilot")


# ============================================================
# Plots
# ============================================================
print("\n" + "=" * 60)
print("Generating plots...")
print("=" * 60)

fig, axes = plt.subplots(3, 2, figsize=(14, 12))

# Plot 1: RV time series
ax = axes[0, 0]
ax.plot(rv_df['date'], rv_df['rv'] * 10000, 'b-', linewidth=1, label='5-min RV')
ax.set_title('SPY Daily Realized Variance (5-min)', fontsize=11)
ax.set_ylabel('RV (bps²)')
ax.legend()
ax.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
ax.tick_params(axis='x', rotation=45)

# Plot 2: RV autocorrelation vs r² autocorrelation
ax = axes[0, 1]
lags = range(1, 11)
ax.bar([l - 0.15 for l in lags], ac_values, width=0.3, label='RV AC', color='steelblue')
ax.bar([l + 0.15 for l in lags[:5]], r2_ac_values, width=0.3, label='r² AC', color='coral')
ax.set_title('Autocorrelation: RV vs r²', fontsize=11)
ax.set_xlabel('Lag')
ax.set_ylabel('Autocorrelation')
ax.legend()
ax.axhline(y=0, color='gray', linestyle='-', linewidth=0.5)

# Plot 3: HAR-RV OOS forecast vs actual
ax = axes[1, 0]
oos_plot_dates = pd.to_datetime(oos_dates)
ax.plot(oos_plot_dates, oos_actuals * 10000, 'b-', linewidth=1.5, label='Actual RV', marker='o', markersize=3)
ax.plot(oos_plot_dates, oos_forecasts * 10000, 'r--', linewidth=1.5, label='HAR-RV forecast', marker='s', markersize=3)
ax.plot(oos_plot_dates, oos_naive * 10000, 'g:', linewidth=1, label='Naive (RV_{t-1})', alpha=0.6)
ax.set_title(f'HAR-RV OOS Forecast vs Actual (R²={har_metrics["OOS_R2"]:.3f})', fontsize=11)
ax.set_ylabel('RV (bps²)')
ax.legend(fontsize=9)
ax.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
ax.tick_params(axis='x', rotation=45)

# Plot 4: Mincer-Zarnowitz scatter
ax = axes[1, 1]
ax.scatter(oos_forecasts * 10000, oos_actuals * 10000, c='steelblue', alpha=0.7, s=30)
# 45-degree line
min_val = min(oos_forecasts.min(), oos_actuals.min()) * 10000
max_val = max(oos_forecasts.max(), oos_actuals.max()) * 10000
ax.plot([min_val, max_val], [min_val, max_val], 'r--', linewidth=1, label='45° line')
# MZ regression line
x_mz = np.linspace(min_val, max_val, 100)
ax.plot(x_mz, har_metrics['MZ_alpha'] * 10000 + har_metrics['MZ_beta'] * x_mz, 'g-',
        linewidth=1.5, label=f'MZ: α={har_metrics["MZ_alpha"]*10000:.2f}, β={har_metrics["MZ_beta"]:.2f}')
ax.set_xlabel('Forecast RV (bps²)')
ax.set_ylabel('Actual RV (bps²)')
ax.set_title(f'Mincer-Zarnowitz (MZ R²={har_metrics["MZ_R2"]:.3f})', fontsize=11)
ax.legend(fontsize=9)

# Plot 5: Cross-model QLIKE comparison
ax = axes[2, 0]
if 'har_qlike_r2' in dir():
    models = ['HAR-RV', 'GARCH', 'GJR-GARCH']
    qlikes = [har_qlike_r2, garch_qlike_r2, gjr_qlike_r2]
    colors = ['steelblue', 'coral', 'gold']
    bars = ax.bar(models, qlikes, color=colors, edgecolor='black', linewidth=0.5)
    ax.set_title('Cross-Model QLIKE on r² (lower = better)', fontsize=11)
    ax.set_ylabel('QLIKE')
    for bar, val in zip(bars, qlikes):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.01,
                f'{val:.4f}', ha='center', va='bottom', fontsize=9)

# Plot 6: VT strategy cumulative returns
ax = axes[2, 1]
if len(vt_returns) > 5:
    vt_plot_dates = pd.to_datetime(vt_dates)
    ax.plot(vt_plot_dates, (np.cumprod(1 + vt_returns) - 1) * 100, 'b-', linewidth=1.5, label='HAR-RV VT')
    ax.plot(vt_plot_dates, (np.cumprod(1 + bh_returns) - 1) * 100, 'r--', linewidth=1.5, label='Buy & Hold')
    ax.set_title(f'VT Pilot ({len(vt_returns)} days, NOT a valid backtest)', fontsize=11)
    ax.set_ylabel('Cumulative Return (%)')
    ax.legend()
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
    ax.tick_params(axis='x', rotation=45)
    ax.axhline(y=0, color='gray', linestyle='-', linewidth=0.5)

plt.tight_layout()
plt.savefig(os.path.join(OUT_DIR, 'k960_har_rv_results.png'), dpi=150, bbox_inches='tight')
print(f"Saved: k960_har_rv_results.png")
plt.close()

# Additional plot: RV distribution
fig, axes = plt.subplots(1, 2, figsize=(12, 5))

ax = axes[0]
ax.hist(rv_vals * 10000, bins=20, color='steelblue', edgecolor='black', alpha=0.7)
ax.set_title('Distribution of Daily RV (bps²)', fontsize=11)
ax.set_xlabel('RV (bps²)')
ax.set_ylabel('Frequency')
ax.axvline(np.mean(rv_vals) * 10000, color='red', linestyle='--', label=f'Mean={np.mean(rv_vals)*10000:.2f}')
ax.legend()

ax = axes[1]
ax.hist(np.log(rv_vals), bins=20, color='coral', edgecolor='black', alpha=0.7)
ax.set_title('Distribution of log(RV)', fontsize=11)
ax.set_xlabel('log(RV)')
ax.set_ylabel('Frequency')

plt.tight_layout()
plt.savefig(os.path.join(OUT_DIR, 'k960_rv_distribution.png'), dpi=150, bbox_inches='tight')
print(f"Saved: k960_rv_distribution.png")
plt.close()


# ============================================================
# Save Results JSON
# ============================================================
print("\n" + "=" * 60)
print("Saving results...")
print("=" * 60)

results = {
    "experiment_id": "K960",
    "title": "HAR-RV Formal Experiment with SPY 5-min Realized Variance",
    "date": datetime.now().strftime("%Y-%m-%d"),
    "data_source": "yfinance 5-min intraday (SPY)",
    "data_period": f"{rv_df['date'].min().date()} to {rv_df['date'].max().date()}",
    "n_days": int(len(rv_df)),
    "n_oos": int(len(oos_forecasts)),
    "references": [
        "Corsi (2009) J.Fin.Econometrics 7(2):174-196",
        "Patton (2011) J.Econometrics 160(1):246-256",
        "K188: HAR on daily data loses to GARCH",
        "K744: RV AC(1)=0.423 vs daily r² AC(1)=0.076"
    ],
    "part_a_descriptive": {
        "rv_mean": float(np.mean(rv_vals)),
        "rv_std": float(np.std(rv_vals)),
        "rv_min": float(np.min(rv_vals)),
        "rv_max": float(np.max(rv_vals)),
        "rv_skew": float(stats.skew(rv_vals)),
        "rv_kurtosis": float(stats.kurtosis(rv_vals)),
        "mean_annualized_vol_pct": float(np.mean(rv_vol_ann) * 100),
        "rv_ac1": float(ac_values[0]),
        "rv_ac5": float(ac_values[4]),
        "r2_ac1": float(r2_ac_values[0]),
        "rv_to_r2_ac_ratio": float(ac_values[0] / r2_ac_values[0]),
        "ljung_box_lag5_pvalue": float(lb_result.iloc[0]['lb_pvalue']),
        "adf_statistic": float(adf_result[0]),
        "adf_pvalue": float(adf_result[1]),
        "rv_stationary": bool(adf_result[1] < 0.05),
    },
    "part_b_har_estimation": {
        "method": "OLS (HAR-RV is linear regression)",
        "intercept": float(betas_full[0]),
        "beta_d": float(betas_full[1]),
        "beta_w": float(betas_full[2]),
        "beta_m": float(betas_full[3]),
        "insample_r2": float(r2_full),
        "t_stats": {labels[i]: float(t_stats[i]) for i in range(4)},
        "p_values": {labels[i]: float(p_values[i]) for i in range(4)},
    },
    "part_c_oos_evaluation": {
        "oos_period": f"{pd.Timestamp(oos_dates[0]).date()} to {pd.Timestamp(oos_dates[-1]).date()}",
        "n_oos": int(len(oos_forecasts)),
        "har_rv": {
            "MSE": float(har_metrics['MSE']),
            "RMSE": float(har_metrics['RMSE']),
            "MAE": float(har_metrics['MAE']),
            "QLIKE": float(har_metrics['QLIKE']),
            "OOS_R2_vs_naive": float(har_metrics['OOS_R2']),
            "MZ_alpha": float(har_metrics['MZ_alpha']),
            "MZ_beta": float(har_metrics['MZ_beta']),
            "MZ_R2": float(har_metrics['MZ_R2']),
            "spearman_rho": float(sp_corr),
            "spearman_pvalue": float(sp_pval),
        },
        "naive": {
            "MSE": float(naive_metrics['MSE']),
            "RMSE": float(naive_metrics['RMSE']),
            "MAE": float(naive_metrics['MAE']),
            "QLIKE": float(naive_metrics['QLIKE']),
        },
    },
    "part_d_cross_model": {},
    "part_e_vt_pilot": {},
    "limitations": [
        "56 days of 5-min data is extremely small for robust inference",
        f"OOS period is only {len(oos_forecasts)} days (ideal: >= 252)",
        "HAR monthly component estimated from only 22 days of history",
        "IS for OLS initially only 14 observations — parameter estimates unstable",
        "DM test with this sample size has very low power — cannot meet Harvey (2016) |t|>3.0 threshold",
        "VT strategy pilot is directional only, not a valid backtest",
        "No microstructure noise correction (e.g., Hansen-Lunde subsampling) applied to RV",
        "Single asset (SPY) — generalizability unknown",
    ],
    "conclusions": [],
}

# Add cross-model results
if 'har_qlike_r2' in dir():
    results["part_d_cross_model"] = {
        "n_common_obs": int(n_common),
        "patton_qlike_on_r2": {
            "HAR_RV": float(har_qlike_r2),
            "GARCH": float(garch_qlike_r2),
            "GJR_GARCH": float(gjr_qlike_r2),
            "ranking": [m[0] for m in models_qlike],
        },
        "spearman_on_r2": {
            "HAR_RV": float(sp_har),
            "GARCH": float(sp_garch),
            "GJR_GARCH": float(sp_gjr),
        },
        "dm_test": {
            "HAR_vs_GARCH": {"DM_stat": float(dm_hg), "p_value": float(dm_hg_p)},
            "HAR_vs_GJR": {"DM_stat": float(dm_hgjr), "p_value": float(dm_hgjr_p)},
            "caveat": f"Only {n_common} observations — DM test has very low power",
        },
    }

# Add VT pilot results
if len(vt_returns) > 5:
    results["part_e_vt_pilot"] = {
        "n_days": int(len(vt_returns)),
        "sigma_target": sigma_target,
        "mean_weight": float(np.mean(vt_weights)),
        "vt_cum_return_pct": float(vt_cum[-1] * 100),
        "bh_cum_return_pct": float(bh_cum[-1] * 100),
        "vt_sharpe": float(vt_sharpe) if vt_sharpe else None,
        "bh_sharpe": float(bh_sharpe) if bh_sharpe else None,
        "vt_ann_vol_pct": float(np.std(vt_returns) * np.sqrt(252) * 100),
        "bh_ann_vol_pct": float(np.std(bh_returns) * np.sqrt(252) * 100),
        "caveat": "NOT a valid backtest — only a directional pilot with very short sample",
    }

# Generate conclusions
conclusions = []
conclusions.append(f"RV AC(1)={ac_values[0]:.3f} confirms strong persistence in intraday volatility (vs r² AC(1)={r2_ac_values[0]:.3f})")
conclusions.append(f"HAR-RV full-sample R²={r2_full:.3f}, OOS R² vs naive={har_metrics['OOS_R2']:.3f}")
conclusions.append(f"HAR-RV QLIKE={har_metrics['QLIKE']:.4f} vs Naive QLIKE={naive_metrics['QLIKE']:.4f}")
if 'har_qlike_r2' in dir():
    conclusions.append(f"Cross-model Patton QLIKE on r²: {models_qlike[0][0]} best ({models_qlike[0][1]:.4f})")
conclusions.append("All results carry severe small-sample caveat (56 days, ~19 OOS obs)")
conclusions.append("Need 1+ year of 5-min data for publishable HAR-RV results")

results["conclusions"] = conclusions

with open(os.path.join(OUT_DIR, 'k960_har_rv_results.json'), 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"Saved: k960_har_rv_results.json")

print("\n" + "=" * 60)
print("K960 COMPLETE")
print("=" * 60)
for c in conclusions:
    print(f"  - {c}")
