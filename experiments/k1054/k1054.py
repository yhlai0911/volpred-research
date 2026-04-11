#!/usr/bin/env python3
"""
K1054: HAR-RV Formal 60-Day SPY — Proxy Comparison r² vs 5-min RV

Extension of K1049 (28 OOS days, PRELIMINARY) with full 60-day 5-min dataset.
Compares HAR-RV vs GJR-GARCH vs A4f-VIX² using BOTH r² and RV proxies.

Data:
- 5-min SPY data: data/intraday/SPY_5min_YYYY-MM-DD.csv (60 files, Jan 14 - Apr 10, 2026)
- Pre-computed daily RV: data/intraday/SPY_daily_rv.csv (cross-checked)
- Daily SPY/VIX: yfinance

Research Questions:
1. With 60 days of 5-min data (~30 OOS), does HAR-RV improve over K1049?
2. Does A4f maintain its QLIKE advantage on BOTH proxies?
3. Are QLIKE rankings proxy-robust (Patton 2011)?

References:
- Patton (2011). Volatility forecast comparison using imperfect volatility proxies. JoE.
- Corsi (2009). A simple approximate long-memory model of realized volatility. JFEC.
- Hansen & Lunde (2005). A forecast comparison of volatility models. JFEC.
- Engle & Rangel (2008). The Spline-GARCH Model for Low-Frequency Volatility. RFS.
- Harvey, Leybourne & Newbold (1997). Testing the equality of prediction MSEs.

Status: PRELIMINARY (OOS << 252 days)
Random seed: 42
"""

import json
import os
import sys
import warnings
from datetime import datetime, timezone
from glob import glob

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import numpy as np
import pandas as pd
from arch import arch_model
from scipy import stats

warnings.filterwarnings('ignore')
np.random.seed(42)

# ── Paths ──
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.abspath(os.path.join(BASE_DIR, '..', '..'))
MAIN_REPO = '/Users/yhlai0911/Desktop/volpred-research'
DATA_DIR = os.path.join(MAIN_REPO, 'data', 'intraday')
OUTPUT_DIR = BASE_DIR

print("=" * 70)
print("K1054: HAR-RV Formal 60-Day SPY — Proxy Comparison r² vs 5-min RV")
print("=" * 70)


# ═══════════════════════════════════════════════════════════════════════
# 1. LOAD AND VALIDATE DATA
# ═══════════════════════════════════════════════════════════════════════

print("\n[1] Loading and validating data...")

# 1a. Load pre-computed daily RV (authoritative source)
# Note: SPY_daily_rv.csv was computed by collect_5min_data.py using
# pct_change() (simple returns) on full-session 5-min data from yfinance.
# Individual CSV files may have incomplete data (some days have only 9 bars
# if collection occurred mid-session), so we use the pre-computed RV.
precomputed_path = os.path.join(DATA_DIR, 'SPY_daily_rv.csv')
rv_df = pd.read_csv(precomputed_path, index_col=0, parse_dates=True)
rv_df.columns = ['rv']
rv_df.index.name = 'Date'
rv_df = rv_df.sort_index()
print(f"  Pre-computed daily RV: {len(rv_df)} days ({rv_df.index[0].date()} to {rv_df.index[-1].date()})")
print(f"  RV range: [{rv_df['rv'].min():.6e}, {rv_df['rv'].max():.6e}]")

# 1b. Verify a few complete CSV files to confirm consistency
fivemin_files = sorted(glob(os.path.join(DATA_DIR, 'SPY_5min_*.csv')))
print(f"  Found {len(fivemin_files)} 5-min CSV files for cross-check")
n_verified = 0
for fpath in fivemin_files[-3:]:  # verify last 3 files
    date_str = os.path.basename(fpath).replace('SPY_5min_', '').replace('.csv', '')
    df_raw = pd.read_csv(fpath, header=[0, 1], index_col=0, parse_dates=True)
    n_bars = len(df_raw)
    if n_bars >= 70:  # only verify files with full-session data
        close_col = [c for c in df_raw.columns if 'Close' in str(c)][0]
        prices = df_raw[close_col].dropna()
        simple_ret = prices.pct_change().dropna()
        rv_check = float((simple_ret ** 2).sum())
        dt = pd.Timestamp(date_str)
        if dt in rv_df.index:
            pct_diff = abs(rv_check - rv_df.loc[dt, 'rv']) / rv_df.loc[dt, 'rv'] * 100
            print(f"    {date_str}: {n_bars} bars, rv_csv={rv_check:.6e}, rv_pre={rv_df.loc[dt, 'rv']:.6e}, diff={pct_diff:.1f}%")
            n_verified += 1

# 1c. Load daily SPY and VIX data via yfinance
import yfinance as yf

start_date = '2015-01-01'
end_date = '2026-04-15'

print(f"  Downloading SPY daily data ({start_date} to {end_date})...")
spy_daily = yf.download('SPY', start=start_date, end=end_date, progress=False)
vix_daily = yf.download('^VIX', start=start_date, end=end_date, progress=False)

# Handle multi-level columns
if isinstance(spy_daily.columns, pd.MultiIndex):
    spy_daily.columns = spy_daily.columns.get_level_values(0)
if isinstance(vix_daily.columns, pd.MultiIndex):
    vix_daily.columns = vix_daily.columns.get_level_values(0)

spy_close = spy_daily['Close'].squeeze()
vix_close = vix_daily['Close'].squeeze()

# Daily log returns and squared returns
spy_returns = np.log(spy_close / spy_close.shift(1)).dropna()
r_squared = spy_returns ** 2

print(f"  SPY daily returns: {len(spy_returns)} days ({spy_returns.index[0].date()} to {spy_returns.index[-1].date()})")
print(f"  VIX daily close: {len(vix_close)} days")

# 1d. Align dates: find common RV + daily dates
rv_dates = rv_df.index
common_dates = rv_dates[rv_dates.isin(spy_returns.index) & rv_dates.isin(vix_close.index)]
print(f"  Common dates (RV + daily + VIX): {len(common_dates)} days")

if len(common_dates) < 30:
    print(f"  ERROR: Only {len(common_dates)} common dates. Need >= 30.")
    sys.exit(1)

# 1e. Descriptive statistics
rv_vals = rv_df.loc[common_dates, 'rv']
r2_vals = r_squared.loc[common_dates]
ret_vals = spy_returns.loc[common_dates]
vix_vals = vix_close.loc[common_dates]

desc_stats = {
    'daily_returns': {
        'mean': float(ret_vals.mean()),
        'std': float(ret_vals.std()),
        'skew': float(ret_vals.skew()),
        'kurtosis': float(ret_vals.kurtosis()),
    },
    'rv_5min': {
        'mean': float(rv_vals.mean()),
        'std': float(rv_vals.std()),
        'min': float(rv_vals.min()),
        'max': float(rv_vals.max()),
    },
    'r_squared': {
        'mean': float(r2_vals.mean()),
        'std': float(r2_vals.std()),
        'min': float(r2_vals.min()),
        'max': float(r2_vals.max()),
    },
    'vix': {
        'mean': float(vix_vals.mean()),
        'std': float(vix_vals.std()),
        'min': float(vix_vals.min()),
        'max': float(vix_vals.max()),
    },
    'correlation_rv_r2': float(np.corrcoef(rv_vals.values, r2_vals.values)[0, 1]),
}

print(f"\n  Descriptive Statistics (60-day RV period):")
print(f"    Daily returns: mean={desc_stats['daily_returns']['mean']:.6f}, "
      f"std={desc_stats['daily_returns']['std']:.6f}, "
      f"skew={desc_stats['daily_returns']['skew']:.2f}, "
      f"kurt={desc_stats['daily_returns']['kurtosis']:.2f}")
print(f"    RV (5-min):    mean={desc_stats['rv_5min']['mean']:.6e}, "
      f"std={desc_stats['rv_5min']['std']:.6e}")
print(f"    r² (squared):  mean={desc_stats['r_squared']['mean']:.6e}, "
      f"std={desc_stats['r_squared']['std']:.6e}")
print(f"    VIX:           mean={desc_stats['vix']['mean']:.2f}, "
      f"std={desc_stats['vix']['std']:.2f}, "
      f"range=[{desc_stats['vix']['min']:.2f}, {desc_stats['vix']['max']:.2f}]")
print(f"    Corr(RV, r²):  {desc_stats['correlation_rv_r2']:.4f}")


# ═══════════════════════════════════════════════════════════════════════
# 2. HAR-RV MODEL (Corsi 2009)
# ═══════════════════════════════════════════════════════════════════════

print("\n[2] HAR-RV Model (Corsi 2009)...")
print("  RV_t = beta0 + beta_d*RV_{t-1} + beta_w*mean(RV_{t-1:t-5}) + beta_m*mean(RV_{t-1:t-22}) + eps")

rv_series = rv_df.loc[common_dates, 'rv'].copy()
rv_series = rv_series.sort_index()
n_rv = len(rv_series)

HAR_INITIAL_WINDOW = 30  # First 30 days for initial training
oos_start_idx = HAR_INITIAL_WINDOW
oos_dates_har = rv_series.index[oos_start_idx:]

print(f"  Total RV days: {n_rv}")
print(f"  In-sample: first {HAR_INITIAL_WINDOW} days ({rv_series.index[0].date()} to {rv_series.index[HAR_INITIAL_WINDOW-1].date()})")
print(f"  Out-of-sample: {len(oos_dates_har)} days ({oos_dates_har[0].date()} to {oos_dates_har[-1].date()})")

# Expanding window HAR-RV estimation
har_forecasts = {}
har_betas_log = []

for t in range(oos_start_idx, n_rv):
    train_rv = rv_series.values[:t]
    n_train = len(train_rv)

    # Build regression data (need 22 lags)
    Y = []
    X = []
    for i in range(22, n_train):
        Y.append(train_rv[i])
        rv_d = train_rv[i - 1]  # lag 1
        rv_w = np.mean(train_rv[max(0, i - 5):i])  # avg of lag 1-5
        rv_m = np.mean(train_rv[max(0, i - 22):i])  # avg of lag 1-22
        X.append([1.0, rv_d, rv_w, rv_m])

    Y = np.array(Y)
    X = np.array(X)

    if len(Y) < 5:  # minimum observations for 4 parameters
        print(f"  Skipping t={t}: only {len(Y)} training obs for HAR")
        continue

    # OLS estimation with ridge regularization for small samples
    try:
        if len(Y) < 15:
            # Ridge regression (lambda=0.01) to stabilize betas with few observations
            lam = 0.01
            XtX = X.T @ X + lam * np.eye(X.shape[1])
            XtY = X.T @ Y
            beta = np.linalg.solve(XtX, XtY)
        else:
            beta = np.linalg.lstsq(X, Y, rcond=None)[0]
    except np.linalg.LinAlgError:
        continue

    # One-step-ahead forecast
    rv_d_fcast = train_rv[-1]  # most recent RV
    rv_w_fcast = np.mean(train_rv[-5:])  # last 5 days avg
    rv_m_fcast = np.mean(train_rv[-22:]) if n_train >= 22 else np.mean(train_rv)

    forecast = beta[0] + beta[1] * rv_d_fcast + beta[2] * rv_w_fcast + beta[3] * rv_m_fcast
    # Clamp to reasonable range: [10% of historical mean, 10x historical mean]
    rv_mean_train = np.mean(train_rv)
    forecast = np.clip(forecast, rv_mean_train * 0.1, rv_mean_train * 10.0)
    forecast = max(forecast, 1e-10)

    date = rv_series.index[t]
    har_forecasts[date] = forecast

    # Log betas at key points
    if t == oos_start_idx or t == n_rv - 1:
        har_betas_log.append({
            'date': str(date.date()),
            'n_train_obs': len(Y),
            'beta_0': float(beta[0]),
            'beta_d': float(beta[1]),
            'beta_w': float(beta[2]),
            'beta_m': float(beta[3])
        })

har_forecast_series = pd.Series(har_forecasts)
print(f"  HAR-RV forecasts: {len(har_forecast_series)} days")
for b in har_betas_log:
    print(f"  Betas at {b['date']} (n={b['n_train_obs']}): "
          f"beta0={b['beta_0']:.6e}, beta_d={b['beta_d']:.4f}, "
          f"beta_w={b['beta_w']:.4f}, beta_m={b['beta_m']:.4f}")


# ═══════════════════════════════════════════════════════════════════════
# 3. GJR-GARCH(1,1) MODEL
# ═══════════════════════════════════════════════════════════════════════

print("\n[3] GJR-GARCH(1,1) Model...")

ret_pct = spy_returns * 100  # percentage scale for arch package
GARCH_WINDOW = 2000

# OOS dates: same as HAR OOS dates for fair comparison
oos_dates_common = har_forecast_series.index
print(f"  OOS dates: {len(oos_dates_common)} ({oos_dates_common[0].date()} to {oos_dates_common[-1].date()})")

gjr_forecasts = {}
gjr_params_log = []

for date in oos_dates_common:
    train_returns = ret_pct[ret_pct.index < date]
    if len(train_returns) < 500:
        print(f"  WARNING: Only {len(train_returns)} returns for GJR at {date.date()}")
        continue

    if len(train_returns) > GARCH_WINDOW:
        train_returns = train_returns.iloc[-GARCH_WINDOW:]

    try:
        model = arch_model(train_returns, vol='GARCH', p=1, o=1, q=1, dist='normal')
        result = model.fit(disp='off', show_warning=False)

        fcast = result.forecast(horizon=1, reindex=False)
        var_pct = fcast.variance.values[-1, 0]
        var_decimal = var_pct / 10000.0  # percentage^2 -> decimal

        gjr_forecasts[date] = max(var_decimal, 1e-10)

        # Log params at first and last date
        if len(gjr_params_log) == 0 or date == oos_dates_common[-1]:
            params = result.params
            persistence = float(params.get('alpha[1]', 0) + params.get('gamma[1]', 0) / 2 + params.get('beta[1]', 0))
            gjr_params_log.append({
                'date': str(date.date()),
                'n_train': len(train_returns),
                'omega': float(params.get('omega', 0)),
                'alpha': float(params.get('alpha[1]', 0)),
                'gamma': float(params.get('gamma[1]', 0)),
                'beta': float(params.get('beta[1]', 0)),
                'persistence': persistence,
                'converged': bool(result.convergence_flag == 0)
            })
    except Exception as e:
        print(f"  GJR failed at {date.date()}: {e}")
        continue

gjr_forecast_series = pd.Series(gjr_forecasts)
print(f"  GJR-GARCH forecasts: {len(gjr_forecast_series)} days")
for p in gjr_params_log:
    print(f"  Params at {p['date']}: omega={p['omega']:.6f}, alpha={p['alpha']:.4f}, "
          f"gamma={p['gamma']:.4f}, beta={p['beta']:.4f}, pers={p['persistence']:.4f}, "
          f"converged={p['converged']}")
    if p['persistence'] >= 1.0:
        print(f"  WARNING: persistence >= 1.0 at {p['date']}!")


# ═══════════════════════════════════════════════════════════════════════
# 4. A4f-VIX² MODEL (Engle & Rangel 2008 style)
# ═══════════════════════════════════════════════════════════════════════

print("\n[4] A4f-VIX² Model (Multiplicative GARCH with VIX component)...")
print("  tau_t = theta0 + theta1 * VIX^2_{t-1}")
print("  u_t = r_t / sqrt(tau_t)")
print("  g_t = GJR(1,1) on u_t")
print("  sigma^2_t = tau_t * g_t")

a4f_forecasts = {}
a4f_params_log = []

for date in oos_dates_common:
    train_mask = spy_returns.index < date
    train_ret = spy_returns[train_mask]
    train_vix = vix_close.reindex(train_ret.index).ffill().dropna()

    common_idx = train_ret.index.intersection(train_vix.index)
    if len(common_idx) < 500:
        continue

    train_ret_aligned = train_ret.loc[common_idx]
    train_vix_aligned = train_vix.loc[common_idx]

    if len(train_ret_aligned) > GARCH_WINDOW:
        train_ret_aligned = train_ret_aligned.iloc[-GARCH_WINDOW:]
        train_vix_aligned = train_vix_aligned.iloc[-GARCH_WINDOW:]

    # Step 1: tau_t = theta0 + theta1 * (VIX_{t-1}/100)^2 / 252
    vix_sq = (train_vix_aligned / 100) ** 2 / 252  # annualized -> daily variance scale
    vix_sq_lag = vix_sq.shift(1).dropna()
    r_sq_train = (train_ret_aligned ** 2).reindex(vix_sq_lag.index).dropna()
    vix_sq_lag = vix_sq_lag.reindex(r_sq_train.index)

    X_tau = np.column_stack([np.ones(len(vix_sq_lag)), vix_sq_lag.values])
    Y_tau = r_sq_train.values

    try:
        theta = np.linalg.lstsq(X_tau, Y_tau, rcond=None)[0]
    except np.linalg.LinAlgError:
        continue

    theta[0] = max(theta[0], 1e-10)
    if theta[1] < 0:
        theta[1] = 0

    # Compute tau for training
    tau_train = theta[0] + theta[1] * vix_sq_lag.values
    tau_train = np.maximum(tau_train, 1e-10)

    # Step 2: u_t = r_t / sqrt(tau_t)
    aligned_ret = train_ret_aligned.reindex(vix_sq_lag.index).values
    u_train = aligned_ret / np.sqrt(tau_train)
    u_series = pd.Series(u_train * 100, index=vix_sq_lag.index)  # pct scale

    # Step 3: GJR on u_t
    try:
        model_u = arch_model(u_series, vol='GARCH', p=1, o=1, q=1, dist='normal')
        result_u = model_u.fit(disp='off', show_warning=False)

        fcast_u = result_u.forecast(horizon=1, reindex=False)
        g_var_pct = fcast_u.variance.values[-1, 0]
        g_var = g_var_pct / 10000.0

        # tau forecast using yesterday's VIX
        vix_for_fcast = vix_close[vix_close.index < date]
        if len(vix_for_fcast) == 0:
            continue
        last_vix = vix_for_fcast.iloc[-1]
        vix_sq_fcast = (last_vix / 100) ** 2 / 252
        tau_fcast = theta[0] + theta[1] * vix_sq_fcast
        tau_fcast = max(tau_fcast, 1e-10)

        sigma2_fcast = tau_fcast * g_var
        a4f_forecasts[date] = max(sigma2_fcast, 1e-10)

        if len(a4f_params_log) == 0 or date == oos_dates_common[-1]:
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
                'g_fcast': float(g_var),
                'converged': bool(result_u.convergence_flag == 0)
            })
    except Exception as e:
        print(f"  A4f failed at {date.date()}: {e}")
        continue

a4f_forecast_series = pd.Series(a4f_forecasts)
print(f"  A4f-VIX² forecasts: {len(a4f_forecast_series)} days")
for p in a4f_params_log:
    print(f"  Params at {p['date']}: theta0={p['theta_0']:.6e}, theta1={p['theta_1']:.4f}")
    print(f"    GJR on u: omega={p['gjr_omega']:.6f}, alpha={p['gjr_alpha']:.4f}, "
          f"gamma={p['gjr_gamma']:.4f}, beta={p['gjr_beta']:.4f}")


# ═══════════════════════════════════════════════════════════════════════
# 5. EVALUATION: DUAL-PROXY COMPARISON
# ═══════════════════════════════════════════════════════════════════════

print("\n[5] Evaluation: Dual-Proxy Comparison...")

# Find common forecast dates
common_fcast_dates = har_forecast_series.index.intersection(
    gjr_forecast_series.index
).intersection(
    a4f_forecast_series.index
).intersection(
    r_squared.index
).intersection(
    rv_df.index
)

print(f"  Common OOS forecast dates: {len(common_fcast_dates)}")
if len(common_fcast_dates) == 0:
    print("  ERROR: No common dates. Exiting.")
    sys.exit(1)

print(f"  OOS Period: {common_fcast_dates[0].date()} to {common_fcast_dates[-1].date()}")

# Extract aligned forecasts and targets
har_f = har_forecast_series.loc[common_fcast_dates].values
gjr_f = gjr_forecast_series.loc[common_fcast_dates].values
a4f_f = a4f_forecast_series.loc[common_fcast_dates].values

rv_target = rv_df.loc[common_fcast_dates, 'rv'].values    # 5-min RV
r2_target = r_squared.loc[common_fcast_dates].values       # squared daily return

n_oos = len(common_fcast_dates)
print(f"  N_OOS = {n_oos}")

# Proxy statistics in OOS
print(f"\n  OOS Proxy Statistics:")
print(f"    RV (5-min): mean={rv_target.mean():.6e}, std={rv_target.std():.6e}")
print(f"    r² (daily): mean={r2_target.mean():.6e}, std={r2_target.std():.6e}")
print(f"    Corr(RV, r²): {np.corrcoef(rv_target, r2_target)[0,1]:.4f}")

# Forecast statistics
print(f"\n  Forecast Statistics (OOS mean):")
print(f"    HAR-RV:     {har_f.mean():.6e}")
print(f"    GJR-GARCH:  {gjr_f.mean():.6e}")
print(f"    A4f-VIX²:   {a4f_f.mean():.6e}")


# ── Loss Functions ──

def qlike_loss(target, forecast):
    """QLIKE loss (element-wise): L_t = target/forecast + log(forecast).
    Patton (2011): proxy-robust, ranking consistent regardless of proxy."""
    f = np.maximum(forecast, 1e-20)
    return target / f + np.log(f)

def mse_loss(target, forecast):
    """MSE loss (element-wise)."""
    return (target - forecast) ** 2

def mae_loss(target, forecast):
    """MAE loss (element-wise)."""
    return np.abs(target - forecast)


# Compute QLIKE, MSE, MAE for each model x each proxy
models = {'HAR-RV': har_f, 'GJR-GARCH': gjr_f, 'A4f-VIX²': a4f_f}
proxies = {'RV (5-min)': rv_target, 'r² (daily)': r2_target}

evaluation = {'QLIKE': {}, 'MSE': {}, 'MAE': {}}
qlike_losses_detail = {}  # for DM test and bootstrap

for proxy_name, target in proxies.items():
    evaluation['QLIKE'][proxy_name] = {}
    evaluation['MSE'][proxy_name] = {}
    evaluation['MAE'][proxy_name] = {}
    qlike_losses_detail[proxy_name] = {}

    for model_name, fcast in models.items():
        ql = qlike_loss(target, fcast)
        ms = mse_loss(target, fcast)
        ma = mae_loss(target, fcast)

        evaluation['QLIKE'][proxy_name][model_name] = float(ql.mean())
        evaluation['MSE'][proxy_name][model_name] = float(ms.mean())
        evaluation['MAE'][proxy_name][model_name] = float(ma.mean())
        qlike_losses_detail[proxy_name][model_name] = ql

print(f"\n  {'':12s} | {'QLIKE':>10s} | {'MSE':>12s} | {'MAE':>10s}")
print(f"  {'-'*12}-+-{'-'*10}-+-{'-'*12}-+-{'-'*10}")
for proxy_name in proxies:
    print(f"\n  Proxy: {proxy_name}")
    for model_name in models:
        q = evaluation['QLIKE'][proxy_name][model_name]
        m = evaluation['MSE'][proxy_name][model_name]
        a = evaluation['MAE'][proxy_name][model_name]
        print(f"    {model_name:12s} | {q:10.4f} | {m:12.4e} | {a:10.4e}")


# ── Rankings ──
rankings = {}
for proxy_name in proxies:
    ql = evaluation['QLIKE'][proxy_name]
    sorted_models = sorted(ql.keys(), key=lambda m: ql[m])
    rankings[f"QLIKE_{proxy_name}"] = sorted_models

print(f"\n  QLIKE Rankings:")
for rk, models_list in rankings.items():
    print(f"    {rk}: {' > '.join(models_list)}")

rankings_consistent = rankings.get('QLIKE_RV (5-min)', []) == rankings.get('QLIKE_r² (daily)', [])
print(f"  Rankings consistent across proxies: {rankings_consistent}")


# ═══════════════════════════════════════════════════════════════════════
# 6. SPEARMAN RANK CORRELATION
# ═══════════════════════════════════════════════════════════════════════

print("\n[6] Spearman Rank Correlation (forecast vs target)...")

spearman_results = {}
for proxy_name, target in proxies.items():
    spearman_results[proxy_name] = {}
    for model_name, fcast in models.items():
        rho, pval = stats.spearmanr(fcast, target)
        spearman_results[proxy_name][model_name] = {
            'rho': float(rho),
            'p_value': float(pval)
        }
        sig = '*' if pval < 0.05 else ''
        print(f"  {proxy_name:12s} | {model_name:12s}: rho={rho:.4f} (p={pval:.4f}){sig}")


# ═══════════════════════════════════════════════════════════════════════
# 7. DIEBOLD-MARIANO TESTS
# ═══════════════════════════════════════════════════════════════════════

print("\n[7] Diebold-Mariano Tests (QLIKE loss, Harvey threshold |t|>3.0)...")

def dm_test(loss1, loss2):
    """Diebold-Mariano test for equal predictive ability.
    H0: E[d_t] = 0 where d_t = L1_t - L2_t.
    Positive t-stat means model 2 is better (lower loss)."""
    d = loss1 - loss2
    n = len(d)
    d_bar = d.mean()
    # Newey-West HAC variance with 1 lag (for small samples)
    gamma_0 = np.var(d, ddof=1)
    if n > 1:
        gamma_1 = np.cov(d[:-1], d[1:])[0, 1]
        var_d = gamma_0 + 2 * gamma_1
    else:
        var_d = gamma_0
    var_d = max(var_d, 1e-20)
    se = np.sqrt(var_d / n)
    t_stat = d_bar / se if se > 0 else 0.0
    p_value = 2 * (1 - stats.t.cdf(abs(t_stat), df=n - 1))
    return float(t_stat), float(p_value)


dm_results = {}
model_pairs = [
    ('HAR-RV', 'GJR-GARCH'),
    ('HAR-RV', 'A4f-VIX²'),
    ('GJR-GARCH', 'A4f-VIX²'),
]

for proxy_name in proxies:
    dm_results[proxy_name] = {}
    for m1, m2 in model_pairs:
        t_stat, p_val = dm_test(
            qlike_losses_detail[proxy_name][m1],
            qlike_losses_detail[proxy_name][m2]
        )
        sig_harvey = abs(t_stat) > 3.0
        dm_results[proxy_name][f"{m1}_vs_{m2}"] = {
            't_stat': t_stat,
            'p_value': p_val,
            'significant_harvey': str(sig_harvey),
            'direction': f"{m2} better" if t_stat > 0 else f"{m1} better"
        }
        sig_str = "***" if sig_harvey else ("*" if p_val < 0.05 else "")
        print(f"  {proxy_name:12s} | {m1} vs {m2}: t={t_stat:.3f} (p={p_val:.4f}) "
              f"{'=> ' + dm_results[proxy_name][f'{m1}_vs_{m2}']['direction']}{sig_str}")


# ═══════════════════════════════════════════════════════════════════════
# 8. BOOTSTRAP CONFIDENCE INTERVALS FOR QLIKE DIFFERENCES
# ═══════════════════════════════════════════════════════════════════════

print("\n[8] Bootstrap CIs for QLIKE differences (B=5000)...")

B = 5000
rng = np.random.default_rng(42)

bootstrap_results = {}
for proxy_name in proxies:
    bootstrap_results[proxy_name] = {}
    for m1, m2 in model_pairs:
        d = qlike_losses_detail[proxy_name][m1] - qlike_losses_detail[proxy_name][m2]
        boot_means = np.zeros(B)
        for b in range(B):
            idx = rng.integers(0, n_oos, size=n_oos)
            boot_means[b] = d[idx].mean()
        ci_lo = float(np.percentile(boot_means, 2.5))
        ci_hi = float(np.percentile(boot_means, 97.5))
        mean_d = float(d.mean())
        bootstrap_results[proxy_name][f"{m1}_vs_{m2}"] = {
            'mean_diff': mean_d,
            'ci_95_lo': ci_lo,
            'ci_95_hi': ci_hi,
            'ci_excludes_zero': bool(ci_lo > 0 or ci_hi < 0)
        }
        excl = "YES" if ci_lo > 0 or ci_hi < 0 else "no"
        print(f"  {proxy_name:12s} | {m1} vs {m2}: diff={mean_d:.4f} CI=[{ci_lo:.4f}, {ci_hi:.4f}] excl_0={excl}")


# ═══════════════════════════════════════════════════════════════════════
# 9. COMPARISON WITH K1049
# ═══════════════════════════════════════════════════════════════════════

print("\n[9] Comparison with K1049 (28 OOS days)...")

k1049_ref = {
    'oos_days': 28,
    'QLIKE_RV': {'HAR-RV': -7.646, 'GJR-GARCH': -7.646, 'A4f-VIX²': -7.794},
    'QLIKE_r2': {'HAR-RV': -7.848, 'GJR-GARCH': -7.977, 'A4f-VIX²': -8.040},
    'Spearman_RV': {'HAR-RV': -0.383, 'GJR-GARCH': 0.137, 'A4f-VIX²': 0.424},
    'ranking_RV': ['A4f-VIX²', 'HAR-RV', 'GJR-GARCH'],
    'ranking_r2': ['A4f-VIX²', 'GJR-GARCH', 'HAR-RV'],
}

k1054_summary = {
    'oos_days': n_oos,
    'QLIKE_RV': {m: evaluation['QLIKE']['RV (5-min)'][m] for m in models},
    'QLIKE_r2': {m: evaluation['QLIKE']['r² (daily)'][m] for m in models},
    'Spearman_RV': {m: spearman_results['RV (5-min)'][m]['rho'] for m in models},
    'ranking_RV': rankings.get('QLIKE_RV (5-min)', []),
    'ranking_r2': rankings.get('QLIKE_r² (daily)', []),
}

print(f"  K1049 OOS: {k1049_ref['oos_days']} days | K1054 OOS: {k1054_summary['oos_days']} days")
print(f"\n  QLIKE Changes (RV proxy):")
for m in models:
    old = k1049_ref['QLIKE_RV'][m]
    new = k1054_summary['QLIKE_RV'][m]
    print(f"    {m:12s}: K1049={old:.3f}, K1054={new:.3f}, diff={new-old:+.3f}")

print(f"\n  QLIKE Changes (r² proxy):")
for m in models:
    old = k1049_ref['QLIKE_r2'][m]
    new = k1054_summary['QLIKE_r2'][m]
    print(f"    {m:12s}: K1049={old:.3f}, K1054={new:.3f}, diff={new-old:+.3f}")

print(f"\n  Spearman Changes (RV proxy):")
for m in models:
    old = k1049_ref['Spearman_RV'][m]
    new = k1054_summary['Spearman_RV'][m]
    print(f"    {m:12s}: K1049={old:.3f}, K1054={new:.3f}, diff={new-old:+.3f}")

print(f"\n  Ranking Changes:")
print(f"    RV proxy: K1049={' > '.join(k1049_ref['ranking_RV'])} -> K1054={' > '.join(k1054_summary['ranking_RV'])}")
print(f"    r² proxy: K1049={' > '.join(k1049_ref['ranking_r2'])} -> K1054={' > '.join(k1054_summary['ranking_r2'])}")


# ═══════════════════════════════════════════════════════════════════════
# 10. FIGURES
# ═══════════════════════════════════════════════════════════════════════

print("\n[10] Generating figures...")

dates_plot = common_fcast_dates

# ── Figure 1: Proxy Comparison (QLIKE + Spearman + DM) ──
fig, axes = plt.subplots(2, 2, figsize=(14, 10))
fig.suptitle('K1054: HAR-RV vs GJR vs A4f — Dual-Proxy Evaluation (60-day SPY 5-min)', fontsize=13, fontweight='bold')

# Panel A: QLIKE by proxy
ax = axes[0, 0]
model_names = list(models.keys())
x = np.arange(len(model_names))
width = 0.35
rv_qlike = [evaluation['QLIKE']['RV (5-min)'][m] for m in model_names]
r2_qlike = [evaluation['QLIKE']['r² (daily)'][m] for m in model_names]
bars1 = ax.bar(x - width/2, rv_qlike, width, label='RV proxy', color='steelblue', alpha=0.8)
bars2 = ax.bar(x + width/2, r2_qlike, width, label='r² proxy', color='coral', alpha=0.8)
ax.set_xticks(x)
ax.set_xticklabels(model_names, fontsize=9)
ax.set_ylabel('QLIKE (lower is better)')
ax.set_title('(A) QLIKE Loss by Proxy')
ax.legend(fontsize=8)
ax.grid(axis='y', alpha=0.3)
# Add value labels
for bar in bars1:
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.01,
            f'{bar.get_height():.3f}', ha='center', va='bottom', fontsize=7)
for bar in bars2:
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.01,
            f'{bar.get_height():.3f}', ha='center', va='bottom', fontsize=7)

# Panel B: Spearman by proxy
ax = axes[0, 1]
rv_spear = [spearman_results['RV (5-min)'][m]['rho'] for m in model_names]
r2_spear = [spearman_results['r² (daily)'][m]['rho'] for m in model_names]
bars1 = ax.bar(x - width/2, rv_spear, width, label='RV proxy', color='steelblue', alpha=0.8)
bars2 = ax.bar(x + width/2, r2_spear, width, label='r² proxy', color='coral', alpha=0.8)
ax.set_xticks(x)
ax.set_xticklabels(model_names, fontsize=9)
ax.set_ylabel('Spearman rho')
ax.set_title('(B) Spearman Rank Correlation')
ax.axhline(0, color='black', linestyle='-', linewidth=0.5)
ax.legend(fontsize=8)
ax.grid(axis='y', alpha=0.3)
for bar in bars1:
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.01 * np.sign(bar.get_height()),
            f'{bar.get_height():.3f}', ha='center', va='bottom' if bar.get_height() >= 0 else 'top', fontsize=7)
for bar in bars2:
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.01 * np.sign(bar.get_height()),
            f'{bar.get_height():.3f}', ha='center', va='bottom' if bar.get_height() >= 0 else 'top', fontsize=7)

# Panel C: DM test t-statistics
ax = axes[1, 0]
pair_labels = [f"{m1}\nvs\n{m2}" for m1, m2 in model_pairs]
rv_dm = [dm_results['RV (5-min)'][f"{m1}_vs_{m2}"]['t_stat'] for m1, m2 in model_pairs]
r2_dm = [dm_results['r² (daily)'][f"{m1}_vs_{m2}"]['t_stat'] for m1, m2 in model_pairs]
xp = np.arange(len(model_pairs))
bars1 = ax.bar(xp - width/2, rv_dm, width, label='RV proxy', color='steelblue', alpha=0.8)
bars2 = ax.bar(xp + width/2, r2_dm, width, label='r² proxy', color='coral', alpha=0.8)
ax.axhline(3.0, color='red', linestyle='--', linewidth=0.8, label='Harvey |t|>3.0')
ax.axhline(-3.0, color='red', linestyle='--', linewidth=0.8)
ax.set_xticks(xp)
ax.set_xticklabels(pair_labels, fontsize=8)
ax.set_ylabel('DM t-statistic')
ax.set_title('(C) DM Test (positive = model 2 better)')
ax.legend(fontsize=7)
ax.grid(axis='y', alpha=0.3)

# Panel D: Bootstrap CI for QLIKE differences
ax = axes[1, 1]
boot_data = []
boot_labels = []
colors = []
for proxy_name, proxy_color in [('RV (5-min)', 'steelblue'), ('r² (daily)', 'coral')]:
    for m1, m2 in model_pairs:
        key = f"{m1}_vs_{m2}"
        br = bootstrap_results[proxy_name][key]
        boot_data.append((br['mean_diff'], br['ci_95_lo'], br['ci_95_hi']))
        boot_labels.append(f"{m1[:3]}v{m2[:3]}\n({proxy_name[:2]})")
        colors.append(proxy_color)

ypos = np.arange(len(boot_data))
for i, (mean, lo, hi) in enumerate(boot_data):
    ax.barh(i, mean, color=colors[i], alpha=0.6, height=0.6)
    ax.errorbar(mean, i, xerr=[[mean - lo], [hi - mean]], fmt='o', color='black', markersize=3, capsize=3)
ax.axvline(0, color='black', linestyle='-', linewidth=0.5)
ax.set_yticks(ypos)
ax.set_yticklabels(boot_labels, fontsize=7)
ax.set_xlabel('QLIKE difference (>0 = model 2 better)')
ax.set_title('(D) Bootstrap 95% CI for QLIKE Differences')
ax.grid(axis='x', alpha=0.3)

plt.tight_layout()
fig.savefig(os.path.join(OUTPUT_DIR, 'k1054_proxy_comparison.png'), dpi=150, bbox_inches='tight')
print(f"  Saved: k1054_proxy_comparison.png")
plt.close()


# ── Figure 2: Forecast Time Series ──
fig, axes = plt.subplots(3, 1, figsize=(14, 10), sharex=True)
fig.suptitle('K1054: Forecast vs Actual — 3 Models, 2 Proxies', fontsize=13, fontweight='bold')

# Panel A: RV proxy
ax = axes[0]
ax.plot(dates_plot, rv_target * 1e4, 'k-', linewidth=1.5, label='RV (5-min)', alpha=0.8)
ax.plot(dates_plot, har_f * 1e4, 'b--', linewidth=1, label='HAR-RV', alpha=0.7)
ax.plot(dates_plot, gjr_f * 1e4, 'g--', linewidth=1, label='GJR-GARCH', alpha=0.7)
ax.plot(dates_plot, a4f_f * 1e4, 'r--', linewidth=1, label='A4f-VIX²', alpha=0.7)
ax.set_ylabel('Variance (×10⁴)')
ax.set_title('(A) Forecasts vs 5-min Realized Variance')
ax.legend(fontsize=8, ncol=4)
ax.grid(alpha=0.3)

# Panel B: r² proxy
ax = axes[1]
ax.plot(dates_plot, r2_target * 1e4, 'k-', linewidth=1.5, label='r² (daily)', alpha=0.8)
ax.plot(dates_plot, har_f * 1e4, 'b--', linewidth=1, label='HAR-RV', alpha=0.7)
ax.plot(dates_plot, gjr_f * 1e4, 'g--', linewidth=1, label='GJR-GARCH', alpha=0.7)
ax.plot(dates_plot, a4f_f * 1e4, 'r--', linewidth=1, label='A4f-VIX²', alpha=0.7)
ax.set_ylabel('Variance (×10⁴)')
ax.set_title('(B) Forecasts vs Squared Daily Return')
ax.legend(fontsize=8, ncol=4)
ax.grid(alpha=0.3)

# Panel C: VIX context
ax = axes[2]
vix_oos = vix_close.reindex(dates_plot)
ax.fill_between(dates_plot, vix_oos, alpha=0.3, color='orange')
ax.plot(dates_plot, vix_oos, 'orange', linewidth=1, label='VIX')
ax.set_ylabel('VIX Level')
ax.set_xlabel('Date')
ax.set_title('(C) VIX Context')
ax.legend(fontsize=8)
ax.grid(alpha=0.3)

plt.tight_layout()
fig.savefig(os.path.join(OUTPUT_DIR, 'k1054_forecast_timeseries.png'), dpi=150, bbox_inches='tight')
print(f"  Saved: k1054_forecast_timeseries.png")
plt.close()


# ═══════════════════════════════════════════════════════════════════════
# 11. RESULTS JSON
# ═══════════════════════════════════════════════════════════════════════

print("\n[11] Saving results...")

results = {
    'experiment_id': 'K1054',
    'title': 'HAR-RV Formal 60-Day SPY — Proxy Comparison r² vs 5-min RV',
    'status': 'PRELIMINARY',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'extends': 'K1049',
    'data': {
        'asset': 'SPY',
        'source': 'yfinance (daily) + data/intraday/ (5-min)',
        'rv_days': int(n_rv),
        'rv_period': f"{rv_series.index[0].date()} to {rv_series.index[-1].date()}",
        'daily_returns_count': int(len(spy_returns)),
        'oos_days': int(n_oos),
        'oos_period': f"{common_fcast_dates[0].date()} to {common_fcast_dates[-1].date()}",
        '5min_rv_files': len(fivemin_files),
    },
    'descriptive_stats': desc_stats,
    'models': {
        'HAR-RV': {
            'specification': 'RV_t = beta0 + beta_d*RV_{t-1} + beta_w*mean(RV_{t-1:t-5}) + beta_m*mean(RV_{t-1:t-22})',
            'estimation': f'Expanding window OLS, initial window = {HAR_INITIAL_WINDOW} days',
            'betas': har_betas_log,
        },
        'GJR-GARCH': {
            'specification': 'GJR(1,1) with normal innovations',
            'estimation': f'Rolling window = {GARCH_WINDOW} daily returns',
            'params': gjr_params_log,
        },
        'A4f-VIX²': {
            'specification': 'tau_t = theta0 + theta1*VIX²_{t-1}, g_t = GJR(1,1) on r_t/sqrt(tau_t)',
            'estimation': f'Rolling window = {GARCH_WINDOW} daily returns',
            'params': a4f_params_log,
        },
    },
    'proxy_stats_oos': {
        'rv_5min': {
            'mean': float(rv_target.mean()),
            'std': float(rv_target.std()),
            'min': float(rv_target.min()),
            'max': float(rv_target.max()),
        },
        'r_squared': {
            'mean': float(r2_target.mean()),
            'std': float(r2_target.std()),
            'min': float(r2_target.min()),
            'max': float(r2_target.max()),
        },
        'correlation_rv_r2': float(np.corrcoef(rv_target, r2_target)[0, 1]),
    },
    'evaluation': {
        'QLIKE': evaluation['QLIKE'],
        'MSE': evaluation['MSE'],
        'MAE': evaluation['MAE'],
        'rankings': rankings,
        'rankings_consistent': rankings_consistent,
    },
    'spearman': spearman_results,
    'dm_tests': dm_results,
    'bootstrap_ci': bootstrap_results,
    'comparison_with_k1049': {
        'k1049_oos': k1049_ref['oos_days'],
        'k1054_oos': n_oos,
        'har_spearman_RV_improved': float(k1054_summary['Spearman_RV']['HAR-RV']) > float(k1049_ref['Spearman_RV']['HAR-RV']),
        'ranking_RV_changed': k1049_ref['ranking_RV'] != list(k1054_summary['ranking_RV']),
        'ranking_r2_changed': k1049_ref['ranking_r2'] != list(k1054_summary['ranking_r2']),
    },
    'key_findings': [],  # filled below
    'limitations': [
        f'Only {n_oos} OOS days — still below 252-day minimum for definitive conclusions',
        f'HAR-RV trained on only {n_rv} expanding-window observations (vs 2000 for GARCH)',
        'r² is noisy proxy (single squared return vs sum of ~78 squared 5-min returns)',
        'VIX regime during sample may not represent typical conditions (includes tariff crisis)',
        'No multiple testing correction beyond Harvey (2016) threshold',
    ],
    'references': [
        'Patton (2011). Volatility forecast comparison using imperfect volatility proxies. JoE.',
        'Corsi (2009). A simple approximate long-memory model of realized volatility. JFEC.',
        'Hansen & Lunde (2005). A forecast comparison of volatility models. JFEC.',
        'Engle & Rangel (2008). The Spline-GARCH Model for Low-Frequency Volatility. RFS.',
        'Harvey, Leybourne & Newbold (1997). Testing the equality of prediction MSEs.',
    ],
}

# Generate key findings based on actual results
findings = []
findings.append(f"OOS period: {n_oos} days ({common_fcast_dates[0].date()} to {common_fcast_dates[-1].date()}) — PRELIMINARY, need >= 252")

# Best model
best_rv = rankings.get('QLIKE_RV (5-min)', ['?'])[0]
best_r2 = rankings.get('QLIKE_r² (daily)', ['?'])[0]
findings.append(f"Best QLIKE (RV proxy): {best_rv}")
findings.append(f"Best QLIKE (r² proxy): {best_r2}")
findings.append(f"Rankings consistent: {rankings_consistent}")

# Spearman improvements
for m in models:
    old_rho = k1049_ref['Spearman_RV'][m]
    new_rho = k1054_summary['Spearman_RV'][m]
    if abs(new_rho - old_rho) > 0.1:
        findings.append(f"Spearman RV {m}: K1049={old_rho:.3f} -> K1054={new_rho:.3f} (delta={new_rho-old_rho:+.3f})")

# DM significance
any_sig = False
for proxy_name in proxies:
    for pair_key, result in dm_results[proxy_name].items():
        if result['significant_harvey'] == 'True':
            findings.append(f"DM significant (Harvey): {pair_key} on {proxy_name}: t={result['t_stat']:.3f}")
            any_sig = True
if not any_sig:
    findings.append("No DM test reaches Harvey (2016) |t|>3.0 threshold — expected with small sample")

# Mechanical vs empirical note
findings.append("GARCH winning on r² proxy is EXPECTED (native target) — mechanical, not empirical")
findings.append("HAR-RV winning on RV proxy would be EXPECTED (native target) — mechanical, not empirical")
findings.append("A4f winning on BOTH proxies (if confirmed) would be genuine empirical finding")

results['key_findings'] = findings

# Save results JSON
results_path = os.path.join(OUTPUT_DIR, 'k1054_results.json')
with open(results_path, 'w', encoding='utf-8') as f:
    json.dump(results, f, indent=2, ensure_ascii=False, default=str)
print(f"  Saved: k1054_results.json")


# ═══════════════════════════════════════════════════════════════════════
# 12. SUMMARY
# ═══════════════════════════════════════════════════════════════════════

print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)
print(f"Data: {n_rv} days of 5-min RV ({rv_series.index[0].date()} to {rv_series.index[-1].date()})")
print(f"OOS:  {n_oos} days ({common_fcast_dates[0].date()} to {common_fcast_dates[-1].date()})")
print(f"\nQLIKE Rankings:")
for rk, ml in rankings.items():
    print(f"  {rk}: {' > '.join(ml)}")
print(f"Rankings consistent: {rankings_consistent}")
print(f"\nStatus: PRELIMINARY (need >= 252 OOS days, have {n_oos})")
for f in findings:
    print(f"  - {f}")
print("=" * 70)
print("K1054 complete.")
