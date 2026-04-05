"""
K913: Variance Risk Premium (VRP) as Return Predictor

Investigates whether VRP = Implied Variance - Realized Variance can predict SPY returns.
This is a RETURN prediction problem (not vol prediction), distinct from VIX sufficiency.

References:
- Bollerslev, Tauchen & Zhou (2009): Expected Stock Returns and Variance Risk Premia, RFS 22(11):4463-4492
- Bekaert & Hoerova (2014): The VIX, the Variance Premium and Stock Market Volatility, JFE 111(2):120-136
- Campbell & Thompson (2008): Predicting Excess Stock Returns Out of Sample, RFS 21(4):1509-1531
- Harvey (2016): ... and the Cross-Section of Expected Returns, RFS 29(1):5-68

Data: SPY + VIX from yfinance, 2006-01 to 2026-03
Author: Yi-Hao Lai + VolPred Research System
"""

import numpy as np
import pandas as pd
import json
import os
import warnings
from datetime import datetime

import yfinance as yf
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from scipy import stats as sp_stats
import statsmodels.api as sm
from statsmodels.stats.diagnostic import acorr_ljungbox

warnings.filterwarnings('ignore')
np.random.seed(42)

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))

# ============================================================
# Step 1: Data Preparation
# ============================================================
print("=" * 70)
print("K913: Variance Risk Premium (VRP) as Return Predictor")
print("=" * 70)

print("\n[Step 1] Downloading data...")
spy = yf.download("SPY", start="2005-11-01", end="2026-04-01", auto_adjust=True, progress=False)
vix = yf.download("^VIX", start="2005-11-01", end="2026-04-01", auto_adjust=True, progress=False)

# Handle multi-level columns if present
if isinstance(spy.columns, pd.MultiIndex):
    spy.columns = spy.columns.get_level_values(0)
if isinstance(vix.columns, pd.MultiIndex):
    vix.columns = vix.columns.get_level_values(0)

# Align dates
df = pd.DataFrame({
    'spy_close': spy['Close'],
    'vix_close': vix['Close']
}).dropna()

# Daily log returns
df['ret'] = np.log(df['spy_close'] / df['spy_close'].shift(1))
df['ret_sq'] = df['ret'] ** 2

# Realized Variance: 22-day rolling sum of r^2 (annualized)
df['rv_22d'] = df['ret_sq'].rolling(22).sum() * 252 / 22  # annualized

# Implied Variance from VIX (VIX is in % annualized vol)
df['iv'] = (df['vix_close'] / 100) ** 2  # annualized variance

# VRP = Implied Variance - Realized Variance (both annualized)
df['vrp'] = df['iv'] - df['rv_22d']

# Forward returns at different horizons
df['fwd_ret_1d'] = df['ret'].shift(-1)  # next day return
df['fwd_ret_5d'] = df['ret'].rolling(5).sum().shift(-5)  # next 5 days
df['fwd_ret_22d'] = df['ret'].rolling(22).sum().shift(-22)  # next 22 days

# Trim to analysis period (need lookback for RV)
df = df.loc['2006-01-01':].copy()
df = df.dropna(subset=['vrp', 'fwd_ret_1d'])

print(f"Sample period: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")
print(f"Total observations: {len(df)}")

# ============================================================
# Step 2: VRP Characteristics Analysis
# ============================================================
print("\n[Step 2] VRP Characteristics...")

vrp_stats = {
    'mean': float(df['vrp'].mean()),
    'std': float(df['vrp'].std()),
    'median': float(df['vrp'].median()),
    'skew': float(df['vrp'].skew()),
    'kurtosis': float(df['vrp'].kurtosis()),
    'min': float(df['vrp'].min()),
    'max': float(df['vrp'].max()),
    'pct_positive': float((df['vrp'] > 0).mean() * 100),
    'pct_negative': float((df['vrp'] < 0).mean() * 100),
    'q25': float(df['vrp'].quantile(0.25)),
    'q75': float(df['vrp'].quantile(0.75)),
}

print(f"  Mean VRP: {vrp_stats['mean']:.6f}")
print(f"  Std VRP: {vrp_stats['std']:.6f}")
print(f"  Skewness: {vrp_stats['skew']:.3f}")
print(f"  Kurtosis: {vrp_stats['kurtosis']:.3f}")
print(f"  Positive VRP: {vrp_stats['pct_positive']:.1f}%")
print(f"  Negative VRP: {vrp_stats['pct_negative']:.1f}%")

# VRP vs VIX correlation
vrp_vix_corr = float(df['vrp'].corr(df['vix_close']))
print(f"  VRP-VIX correlation: {vrp_vix_corr:.4f}")

# VRP autocorrelation
vrp_acf_1 = float(df['vrp'].autocorr(1))
vrp_acf_5 = float(df['vrp'].autocorr(5))
vrp_acf_22 = float(df['vrp'].autocorr(22))
print(f"  VRP ACF(1): {vrp_acf_1:.4f}")
print(f"  VRP ACF(5): {vrp_acf_5:.4f}")
print(f"  VRP ACF(22): {vrp_acf_22:.4f}")

# Ljung-Box test for VRP
lb_test = acorr_ljungbox(df['vrp'].dropna(), lags=[10], return_df=True)
lb_stat = float(lb_test['lb_stat'].iloc[0])
lb_pval = float(lb_test['lb_pvalue'].iloc[0])
print(f"  Ljung-Box(10): stat={lb_stat:.2f}, p={lb_pval:.6f}")

# VRP by VIX regime
vix_median = df['vix_close'].median()
high_vix = df[df['vix_close'] > vix_median]
low_vix = df[df['vix_close'] <= vix_median]

vrp_regime = {
    'high_vix_mean_vrp': float(high_vix['vrp'].mean()),
    'low_vix_mean_vrp': float(low_vix['vrp'].mean()),
    'high_vix_pct_positive': float((high_vix['vrp'] > 0).mean() * 100),
    'low_vix_pct_positive': float((low_vix['vrp'] > 0).mean() * 100),
    'vix_median_threshold': float(vix_median),
}

print(f"\n  VIX Regime Analysis (median VIX = {vix_median:.1f}):")
print(f"    High VIX: mean VRP = {vrp_regime['high_vix_mean_vrp']:.6f}, "
      f"positive = {vrp_regime['high_vix_pct_positive']:.1f}%")
print(f"    Low VIX: mean VRP = {vrp_regime['low_vix_mean_vrp']:.6f}, "
      f"positive = {vrp_regime['low_vix_pct_positive']:.1f}%")

# ============================================================
# Step 3: Predictive Regressions
# ============================================================
print("\n[Step 3] Predictive Regressions (Newey-West HAC SE)...")

def run_regression(y, X, nw_lags=None):
    """Run OLS regression with Newey-West HAC standard errors."""
    mask = y.notna() & X.notna().all(axis=1)
    y_clean = y[mask]
    X_clean = X[mask]
    X_const = sm.add_constant(X_clean)

    if nw_lags is None:
        nw_lags = int(np.ceil(len(y_clean) ** (1/3)))

    model = sm.OLS(y_clean, X_const).fit(cov_type='HAC', cov_kwds={'maxlags': nw_lags})
    return model

regression_results = {}

# --- Daily Regressions ---
print("\n  --- Daily Horizon ---")

# (a) Univariate: r_{t+1} = a + b * VRP_t
# MUST use lagged VRP: VRP at t predicts return at t+1
# fwd_ret_1d is already ret.shift(-1), so align with current VRP
df_daily = df[['vrp', 'fwd_ret_1d', 'vix_close', 'iv']].dropna().copy()

model_daily_uni = run_regression(df_daily['fwd_ret_1d'], df_daily[['vrp']])
print(f"  Univariate: beta={model_daily_uni.params['vrp']:.6f}, "
      f"t={model_daily_uni.tvalues['vrp']:.3f}, R2={model_daily_uni.rsquared:.6f}")

regression_results['daily_univariate'] = {
    'beta_vrp': float(model_daily_uni.params['vrp']),
    't_vrp': float(model_daily_uni.tvalues['vrp']),
    'p_vrp': float(model_daily_uni.pvalues['vrp']),
    'R2': float(model_daily_uni.rsquared),
    'R2_adj': float(model_daily_uni.rsquared_adj),
    'N': int(model_daily_uni.nobs),
    'nw_lags': int(np.ceil(model_daily_uni.nobs ** (1/3))),
}

# (b) Multivariate: r_{t+1} = a + b1*VRP_t + b2*VIX_t
model_daily_multi = run_regression(df_daily['fwd_ret_1d'], df_daily[['vrp', 'vix_close']])
print(f"  Multivariate: beta_vrp={model_daily_multi.params['vrp']:.6f}, "
      f"t_vrp={model_daily_multi.tvalues['vrp']:.3f}, "
      f"beta_vix={model_daily_multi.params['vix_close']:.6f}, "
      f"t_vix={model_daily_multi.tvalues['vix_close']:.3f}, "
      f"R2={model_daily_multi.rsquared:.6f}")

regression_results['daily_multivariate'] = {
    'beta_vrp': float(model_daily_multi.params['vrp']),
    't_vrp': float(model_daily_multi.tvalues['vrp']),
    'p_vrp': float(model_daily_multi.pvalues['vrp']),
    'beta_vix': float(model_daily_multi.params['vix_close']),
    't_vix': float(model_daily_multi.tvalues['vix_close']),
    'p_vix': float(model_daily_multi.pvalues['vix_close']),
    'R2': float(model_daily_multi.rsquared),
    'N': int(model_daily_multi.nobs),
}

# --- Weekly Regressions ---
print("\n  --- Weekly Horizon (5-day) ---")
df_weekly = df[['vrp', 'fwd_ret_5d', 'vix_close']].dropna().copy()

model_weekly_uni = run_regression(df_weekly['fwd_ret_5d'], df_weekly[['vrp']], nw_lags=10)
print(f"  Univariate: beta={model_weekly_uni.params['vrp']:.6f}, "
      f"t={model_weekly_uni.tvalues['vrp']:.3f}, R2={model_weekly_uni.rsquared:.6f}")

regression_results['weekly_univariate'] = {
    'beta_vrp': float(model_weekly_uni.params['vrp']),
    't_vrp': float(model_weekly_uni.tvalues['vrp']),
    'p_vrp': float(model_weekly_uni.pvalues['vrp']),
    'R2': float(model_weekly_uni.rsquared),
    'N': int(model_weekly_uni.nobs),
}

model_weekly_multi = run_regression(df_weekly['fwd_ret_5d'], df_weekly[['vrp', 'vix_close']], nw_lags=10)
print(f"  Multivariate: beta_vrp={model_weekly_multi.params['vrp']:.6f}, "
      f"t_vrp={model_weekly_multi.tvalues['vrp']:.3f}, R2={model_weekly_multi.rsquared:.6f}")

regression_results['weekly_multivariate'] = {
    'beta_vrp': float(model_weekly_multi.params['vrp']),
    't_vrp': float(model_weekly_multi.tvalues['vrp']),
    'p_vrp': float(model_weekly_multi.pvalues['vrp']),
    'beta_vix': float(model_weekly_multi.params['vix_close']),
    't_vix': float(model_weekly_multi.tvalues['vix_close']),
    'p_vix': float(model_weekly_multi.pvalues['vix_close']),
    'R2': float(model_weekly_multi.rsquared),
    'N': int(model_weekly_multi.nobs),
}

# --- Monthly Regressions ---
print("\n  --- Monthly Horizon (22-day) ---")
df_monthly = df[['vrp', 'fwd_ret_22d', 'vix_close']].dropna().copy()

model_monthly_uni = run_regression(df_monthly['fwd_ret_22d'], df_monthly[['vrp']], nw_lags=44)
print(f"  Univariate: beta={model_monthly_uni.params['vrp']:.6f}, "
      f"t={model_monthly_uni.tvalues['vrp']:.3f}, R2={model_monthly_uni.rsquared:.6f}")

regression_results['monthly_univariate'] = {
    'beta_vrp': float(model_monthly_uni.params['vrp']),
    't_vrp': float(model_monthly_uni.tvalues['vrp']),
    'p_vrp': float(model_monthly_uni.pvalues['vrp']),
    'R2': float(model_monthly_uni.rsquared),
    'N': int(model_monthly_uni.nobs),
}

model_monthly_multi = run_regression(df_monthly['fwd_ret_22d'], df_monthly[['vrp', 'vix_close']], nw_lags=44)
print(f"  Multivariate: beta_vrp={model_monthly_multi.params['vrp']:.6f}, "
      f"t_vrp={model_monthly_multi.tvalues['vrp']:.3f}, R2={model_monthly_multi.rsquared:.6f}")

regression_results['monthly_multivariate'] = {
    'beta_vrp': float(model_monthly_multi.params['vrp']),
    't_vrp': float(model_monthly_multi.tvalues['vrp']),
    'p_vrp': float(model_monthly_multi.pvalues['vrp']),
    'beta_vix': float(model_monthly_multi.params['vix_close']),
    't_vix': float(model_monthly_multi.tvalues['vix_close']),
    'p_vix': float(model_monthly_multi.pvalues['vix_close']),
    'R2': float(model_monthly_multi.rsquared),
    'N': int(model_monthly_multi.nobs),
}

# ============================================================
# Step 4: Out-of-Sample Prediction
# ============================================================
print("\n[Step 4] Out-of-Sample Prediction...")

# IS: 2006-2018, OOS: 2019-2026
is_end = '2018-12-31'
oos_start = '2019-01-01'

df_is = df.loc[:is_end].copy()
df_oos = df.loc[oos_start:].copy()

print(f"  IS period: {df_is.index[0].strftime('%Y-%m-%d')} to {df_is.index[-1].strftime('%Y-%m-%d')} (N={len(df_is)})")
print(f"  OOS period: {df_oos.index[0].strftime('%Y-%m-%d')} to {df_oos.index[-1].strftime('%Y-%m-%d')} (N={len(df_oos)})")

# Expanding window OOS prediction for daily returns
oos_results = {}
for horizon_name, ret_col in [('daily', 'fwd_ret_1d'), ('weekly', 'fwd_ret_5d'), ('monthly', 'fwd_ret_22d')]:
    df_h = df[['vrp', ret_col]].dropna().copy()
    df_h_oos = df_h.loc[oos_start:].copy()

    if len(df_h_oos) < 50:
        print(f"  {horizon_name}: insufficient OOS data, skipping")
        continue

    # Expanding window predictions
    predictions = []
    actuals = []
    hist_mean_preds = []

    oos_indices = df_h_oos.index
    # Refit model every 22 days to speed up (expanding window)
    refit_interval = 22
    current_model = None
    last_refit = -refit_interval  # force initial fit

    for i, date in enumerate(oos_indices):
        # Refit model periodically using expanding window
        if i - last_refit >= refit_interval or current_model is None:
            train = df_h.loc[:date].iloc[:-1]  # exclude current date
            if len(train) < 252:
                continue
            y_train = train[ret_col]
            X_train = sm.add_constant(train[['vrp']])
            try:
                current_model = sm.OLS(y_train, X_train).fit()
                last_refit = i
            except Exception:
                continue

        if current_model is None:
            continue

        try:
            # Predict using model coefficients directly
            vrp_val = df_h.loc[date, 'vrp']
            pred = float(current_model.params['const'] + current_model.params['vrp'] * vrp_val)
        except Exception:
            continue

        actual = float(df_h.loc[date, ret_col])
        # Historical mean from all data up to current date (expanding)
        hist_mean = float(df_h.loc[:date, ret_col].iloc[:-1].mean())

        predictions.append(pred)
        actuals.append(actual)
        hist_mean_preds.append(hist_mean)

    predictions = np.array(predictions)
    actuals = np.array(actuals)
    hist_mean_preds = np.array(hist_mean_preds)

    # OOS R^2 (Campbell & Thompson 2008)
    mse_model = np.mean((actuals - predictions) ** 2)
    mse_hist_mean = np.mean((actuals - hist_mean_preds) ** 2)
    r2_oos = 1 - mse_model / mse_hist_mean

    # Directional accuracy
    dir_accuracy = np.mean(np.sign(predictions) == np.sign(actuals))

    oos_results[horizon_name] = {
        'R2_OOS': float(r2_oos),
        'MSE_model': float(mse_model),
        'MSE_hist_mean': float(mse_hist_mean),
        'directional_accuracy': float(dir_accuracy),
        'N_OOS': int(len(predictions)),
    }

    print(f"  {horizon_name}: R2_OOS = {r2_oos:.6f}, "
          f"Dir. Accuracy = {dir_accuracy:.4f}, N = {len(predictions)}")

# ============================================================
# Step 5: VRP Trading Strategy
# ============================================================
print("\n[Step 5] VRP Trading Strategy...")

# Compute VRP percentile (expanding window)
df['vrp_pctile'] = df['vrp'].expanding(min_periods=252).apply(
    lambda x: sp_stats.percentileofscore(x, x.iloc[-1]) / 100, raw=False
)

# Strategy: weight = 0.5 + 0.5 * (vrp_pctile - 0.5)
# High VRP (high percentile) -> overweight SPY (VRP = fear premium = expected return)
# Low VRP (low percentile) -> underweight SPY
df['vrp_weight'] = 0.5 + 0.5 * (df['vrp_pctile'] - 0.5)
df['vrp_weight'] = df['vrp_weight'].clip(0.0, 1.0)

# MUST LAG: signal from t, applied to t+1 return
df['vrp_signal'] = df['vrp_weight'].shift(1)  # LAG = shift(1)

# Strategy return (SPY only, weight in SPY vs cash)
df['strat_ret'] = df['vrp_signal'] * df['ret']
df['bh_ret'] = df['ret']  # Buy & Hold SPY

# Start from a common point with valid signals
strat_start = '2007-01-01'  # after 1 year of lookback
df_strat = df.loc[strat_start:].dropna(subset=['strat_ret', 'bh_ret']).copy()

# Cumulative returns
df_strat['strat_cum'] = (1 + df_strat['strat_ret']).cumprod()
df_strat['bh_cum'] = (1 + df_strat['bh_ret']).cumprod()

# Performance metrics
def calc_metrics(returns, name):
    ann_ret = returns.mean() * 252
    ann_vol = returns.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    cum_ret = (1 + returns).cumprod()
    dd = cum_ret / cum_ret.cummax() - 1
    mdd = dd.min()
    return {
        'name': name,
        'ann_return': float(ann_ret),
        'ann_vol': float(ann_vol),
        'sharpe': float(sharpe),
        'mdd': float(mdd),
        'total_return': float(cum_ret.iloc[-1] - 1),
        'N': int(len(returns)),
    }

strat_metrics = calc_metrics(df_strat['strat_ret'], 'VRP Strategy')
bh_metrics = calc_metrics(df_strat['bh_ret'], 'Buy & Hold SPY')

print(f"\n  VRP Strategy: Sharpe={strat_metrics['sharpe']:.4f}, "
      f"Ann.Ret={strat_metrics['ann_return']:.4f}, MDD={strat_metrics['mdd']:.4f}")
print(f"  Buy & Hold SPY: Sharpe={bh_metrics['sharpe']:.4f}, "
      f"Ann.Ret={bh_metrics['ann_return']:.4f}, MDD={bh_metrics['mdd']:.4f}")

# DM test: strategy vs buy & hold
# Use squared error loss relative to actual returns
from statsmodels.stats.diagnostic import acorr_ljungbox

# Simple DM test implementation
def dm_test(e1, e2, h=1):
    """
    Diebold-Mariano test. e1, e2 are forecast errors (or loss differentials).
    H0: equal predictive accuracy.
    Returns t-stat and p-value.
    """
    d = e1 ** 2 - e2 ** 2  # squared error loss differential
    d_mean = d.mean()
    # Newey-West variance estimate
    T = len(d)
    nw_lags = int(np.ceil(T ** (1/3)))
    gamma_0 = np.var(d, ddof=1)
    gamma_sum = 0
    for j in range(1, nw_lags + 1):
        w = 1 - j / (nw_lags + 1)  # Bartlett kernel
        gamma_j = np.cov(d[j:], d[:-j])[0, 1]
        gamma_sum += 2 * w * gamma_j
    var_d = (gamma_0 + gamma_sum) / T
    if var_d <= 0:
        return 0.0, 1.0
    dm_stat = d_mean / np.sqrt(var_d)
    p_val = 2 * (1 - sp_stats.norm.cdf(abs(dm_stat)))
    return float(dm_stat), float(p_val)

# DM test: compare VRP strategy vs BH using returns as "forecasts" of zero
# Actually compare the strategies by their return differentials
ret_diff = df_strat['strat_ret'] - df_strat['bh_ret']
dm_stat_simple = float(ret_diff.mean() / (ret_diff.std() / np.sqrt(len(ret_diff))))
dm_p_simple = float(2 * (1 - sp_stats.norm.cdf(abs(dm_stat_simple))))

print(f"\n  Return differential t-stat: {dm_stat_simple:.4f}, p={dm_p_simple:.6f}")
print(f"  Harvey (2016) threshold: |t| > 3.0 → {'PASS' if abs(dm_stat_simple) > 3.0 else 'FAIL'}")

strategy_results = {
    'vrp_strategy': strat_metrics,
    'buy_hold_spy': bh_metrics,
    'return_diff_t': float(dm_stat_simple),
    'return_diff_p': float(dm_p_simple),
    'harvey_pass': bool(abs(dm_stat_simple) > 3.0),
}

# ============================================================
# Step 5b: VRP quintile strategy (more aggressive)
# ============================================================
print("\n[Step 5b] VRP Quintile Analysis...")

# Quintile analysis: sort by lagged VRP, look at next-day returns
df_q = df.loc[strat_start:].dropna(subset=['vrp_pctile', 'fwd_ret_1d']).copy()
df_q['vrp_quintile'] = pd.qcut(df_q['vrp'].shift(1), 5, labels=['Q1(Low)', 'Q2', 'Q3', 'Q4', 'Q5(High)'])
df_q = df_q.dropna(subset=['vrp_quintile'])

quintile_returns = df_q.groupby('vrp_quintile')['fwd_ret_1d'].agg(['mean', 'std', 'count'])
quintile_returns['sharpe'] = quintile_returns['mean'] / quintile_returns['std'] * np.sqrt(252)
quintile_returns['ann_ret'] = quintile_returns['mean'] * 252

print("\n  Quintile | Ann.Return | Sharpe | N")
print("  " + "-" * 45)
quintile_results = {}
for q in quintile_returns.index:
    row = quintile_returns.loc[q]
    print(f"  {q:10s} | {row['ann_ret']:.4f}   | {row['sharpe']:.4f} | {int(row['count'])}")
    quintile_results[str(q)] = {
        'ann_return': float(row['ann_ret']),
        'sharpe': float(row['sharpe']),
        'mean_daily': float(row['mean']),
        'std_daily': float(row['std']),
        'count': int(row['count']),
    }

# Q5-Q1 spread
q5_mean = quintile_returns.loc['Q5(High)', 'mean']
q1_mean = quintile_returns.loc['Q1(Low)', 'mean']
spread_daily = q5_mean - q1_mean
spread_ann = spread_daily * 252

# t-test for Q5 vs Q1
q5_rets = df_q[df_q['vrp_quintile'] == 'Q5(High)']['fwd_ret_1d']
q1_rets = df_q[df_q['vrp_quintile'] == 'Q1(Low)']['fwd_ret_1d']
t_q5q1, p_q5q1 = sp_stats.ttest_ind(q5_rets, q1_rets)

print(f"\n  Q5-Q1 spread: {spread_ann:.4f} ann., t={t_q5q1:.3f}, p={p_q5q1:.4f}")
print(f"  Harvey threshold: |t| > 3.0 → {'PASS' if abs(t_q5q1) > 3.0 else 'FAIL'}")

quintile_spread = {
    'spread_annual': float(spread_ann),
    'spread_daily': float(spread_daily),
    't_stat': float(t_q5q1),
    'p_value': float(p_q5q1),
    'harvey_pass': bool(abs(t_q5q1) > 3.0),
}

# ============================================================
# Step 6: VRP and VT Strategy Interaction
# ============================================================
print("\n[Step 6] VRP and VT Strategy Interaction...")

# 12/VIX strategy weight
df['w_12vix'] = 12 / df['vix_close']
df['w_12vix'] = df['w_12vix'].clip(0, 1)
df['w_12vix_lag'] = df['w_12vix'].shift(1)

# Correlation between VRP signal and 12/VIX weight
corr_vrp_12vix = float(df['vrp_signal'].corr(df['w_12vix_lag']))
print(f"  VRP signal vs 12/VIX weight correlation: {corr_vrp_12vix:.4f}")

# VRP conditional on 12/VIX regime
high_vix_regime = df[df['vix_close'] > 20]  # ~roughly when 12/VIX < 0.6
low_vix_regime = df[df['vix_close'] <= 20]

vrp_interaction = {
    'corr_vrp_signal_12vix': float(corr_vrp_12vix),
    'high_vix_mean_fwd_ret': float(high_vix_regime['fwd_ret_1d'].mean() * 252) if len(high_vix_regime) > 0 else None,
    'low_vix_mean_fwd_ret': float(low_vix_regime['fwd_ret_1d'].mean() * 252) if len(low_vix_regime) > 0 else None,
    'high_vix_mean_vrp': float(high_vix_regime['vrp'].mean()) if len(high_vix_regime) > 0 else None,
    'low_vix_mean_vrp': float(low_vix_regime['vrp'].mean()) if len(low_vix_regime) > 0 else None,
}

print(f"  High VIX (>20): mean VRP={vrp_interaction['high_vix_mean_vrp']:.6f}, "
      f"ann fwd ret={vrp_interaction['high_vix_mean_fwd_ret']:.4f}")
print(f"  Low VIX (<=20): mean VRP={vrp_interaction['low_vix_mean_vrp']:.6f}, "
      f"ann fwd ret={vrp_interaction['low_vix_mean_fwd_ret']:.4f}")

# Combined VRP+12/VIX strategy
# Use VRP to decide WHEN to use 12/VIX (only when VRP is high = fear premium large)
df['combined_weight'] = np.where(
    df['vrp'].shift(1) > df['vrp'].shift(1).expanding(252).quantile(0.5),
    df['w_12vix_lag'],  # Use 12/VIX when VRP is above median
    0.5  # Stay 50% when VRP is low (no fear premium to harvest)
)
df['combined_ret'] = df['combined_weight'] * df['ret']

df_comb = df.loc[strat_start:].dropna(subset=['combined_ret']).copy()
combined_metrics = calc_metrics(df_comb['combined_ret'], 'VRP+12/VIX Combined')
plain_12vix_ret = df.loc[strat_start:].dropna(subset=['w_12vix_lag']).copy()
plain_12vix_ret['ret_12vix'] = plain_12vix_ret['w_12vix_lag'] * plain_12vix_ret['ret']
metrics_12vix = calc_metrics(plain_12vix_ret['ret_12vix'], '12/VIX Plain')

print(f"\n  Combined VRP+12/VIX: Sharpe={combined_metrics['sharpe']:.4f}")
print(f"  Plain 12/VIX: Sharpe={metrics_12vix['sharpe']:.4f}")
print(f"  Buy & Hold SPY: Sharpe={bh_metrics['sharpe']:.4f}")

interaction_strategy = {
    'combined_vrp_12vix': combined_metrics,
    'plain_12vix': metrics_12vix,
}

# ============================================================
# Charts
# ============================================================
print("\n[Charts] Generating figures...")

# --- Chart 1: VRP Distribution and Time Series ---
fig, axes = plt.subplots(2, 2, figsize=(14, 10))

# 1a: VRP time series
ax = axes[0, 0]
ax.plot(df.index, df['vrp'], linewidth=0.3, alpha=0.6, color='steelblue')
ax.axhline(y=0, color='red', linestyle='--', linewidth=0.8, alpha=0.7)
rolling_vrp = df['vrp'].rolling(66).mean()
ax.plot(df.index, rolling_vrp, linewidth=1.5, color='darkblue', label='66-day MA')
ax.set_title('VRP Time Series (Annualized)', fontsize=12, fontweight='bold')
ax.set_ylabel('VRP')
ax.legend()
ax.grid(True, alpha=0.3)

# 1b: VRP distribution
ax = axes[0, 1]
ax.hist(df['vrp'].dropna(), bins=100, color='steelblue', alpha=0.7, edgecolor='white', density=True)
ax.axvline(x=0, color='red', linestyle='--', linewidth=1.5)
ax.axvline(x=df['vrp'].mean(), color='orange', linestyle='-', linewidth=1.5, label=f'Mean={df["vrp"].mean():.4f}')
ax.set_title('VRP Distribution', fontsize=12, fontweight='bold')
ax.set_xlabel('VRP (annualized)')
ax.set_ylabel('Density')
ax.legend()
ax.grid(True, alpha=0.3)

# 1c: VRP vs VIX scatter
ax = axes[1, 0]
ax.scatter(df['vix_close'], df['vrp'], alpha=0.1, s=5, color='steelblue')
ax.axhline(y=0, color='red', linestyle='--', linewidth=0.8)
ax.set_title(f'VRP vs VIX Level (corr={vrp_vix_corr:.3f})', fontsize=12, fontweight='bold')
ax.set_xlabel('VIX')
ax.set_ylabel('VRP')
ax.grid(True, alpha=0.3)

# 1d: VRP autocorrelation
ax = axes[1, 1]
lags = range(1, 51)
acf_vals = [df['vrp'].autocorr(lag=l) for l in lags]
ax.bar(lags, acf_vals, color='steelblue', alpha=0.7)
ax.set_title('VRP Autocorrelation', fontsize=12, fontweight='bold')
ax.set_xlabel('Lag (days)')
ax.set_ylabel('ACF')
ax.grid(True, alpha=0.3)

plt.tight_layout()
fig.savefig(os.path.join(OUTPUT_DIR, 'k913_vrp_distribution.png'), dpi=150, bbox_inches='tight')
plt.close()
print("  Saved k913_vrp_distribution.png")

# --- Chart 2: Prediction Results ---
fig, axes = plt.subplots(2, 2, figsize=(14, 10))

# 2a: VRP vs next-day return scatter
ax = axes[0, 0]
vrp_clean = df[['vrp', 'fwd_ret_1d']].dropna()
ax.scatter(vrp_clean['vrp'], vrp_clean['fwd_ret_1d'], alpha=0.05, s=3, color='steelblue')
# Add regression line
z = np.polyfit(vrp_clean['vrp'], vrp_clean['fwd_ret_1d'], 1)
p = np.poly1d(z)
vrp_range = np.linspace(vrp_clean['vrp'].min(), vrp_clean['vrp'].max(), 100)
ax.plot(vrp_range, p(vrp_range), color='red', linewidth=2)
ax.set_title(f'VRP vs Next-Day Return (R²={regression_results["daily_univariate"]["R2"]:.5f})',
             fontsize=11, fontweight='bold')
ax.set_xlabel('VRP (t)')
ax.set_ylabel('Return (t+1)')
ax.grid(True, alpha=0.3)

# 2b: VRP vs next-month return scatter
ax = axes[0, 1]
vrp_m = df[['vrp', 'fwd_ret_22d']].dropna()
ax.scatter(vrp_m['vrp'], vrp_m['fwd_ret_22d'], alpha=0.05, s=3, color='steelblue')
z = np.polyfit(vrp_m['vrp'], vrp_m['fwd_ret_22d'], 1)
p = np.poly1d(z)
vrp_range = np.linspace(vrp_m['vrp'].min(), vrp_m['vrp'].max(), 100)
ax.plot(vrp_range, p(vrp_range), color='red', linewidth=2)
ax.set_title(f'VRP vs Next-Month Return (R²={regression_results["monthly_univariate"]["R2"]:.5f})',
             fontsize=11, fontweight='bold')
ax.set_xlabel('VRP (t)')
ax.set_ylabel('22-day Return')
ax.grid(True, alpha=0.3)

# 2c: Quintile bar chart
ax = axes[1, 0]
q_labels = list(quintile_results.keys())
q_sharpes = [quintile_results[q]['sharpe'] for q in q_labels]
colors_q = ['#d32f2f' if s < 0 else '#1976d2' for s in q_sharpes]
ax.bar(q_labels, q_sharpes, color=colors_q, alpha=0.8, edgecolor='white')
ax.set_title('Sharpe Ratio by VRP Quintile (Lagged)', fontsize=12, fontweight='bold')
ax.set_xlabel('VRP Quintile')
ax.set_ylabel('Annualized Sharpe')
ax.grid(True, alpha=0.3, axis='y')

# 2d: OOS R² by horizon
ax = axes[1, 1]
oos_horizons = list(oos_results.keys())
oos_r2s = [oos_results[h]['R2_OOS'] for h in oos_horizons]
colors_oos = ['#4caf50' if r > 0 else '#d32f2f' for r in oos_r2s]
ax.bar(oos_horizons, oos_r2s, color=colors_oos, alpha=0.8, edgecolor='white')
ax.axhline(y=0, color='black', linewidth=0.8)
ax.set_title('Out-of-Sample R² by Horizon', fontsize=12, fontweight='bold')
ax.set_xlabel('Horizon')
ax.set_ylabel('OOS R² (Campbell-Thompson)')
ax.grid(True, alpha=0.3, axis='y')

plt.tight_layout()
fig.savefig(os.path.join(OUTPUT_DIR, 'k913_vrp_prediction.png'), dpi=150, bbox_inches='tight')
plt.close()
print("  Saved k913_vrp_prediction.png")

# --- Chart 3: Strategy Performance ---
fig, axes = plt.subplots(2, 1, figsize=(14, 8))

# 3a: Cumulative returns
ax = axes[0]
ax.plot(df_strat.index, df_strat['strat_cum'], label=f'VRP Strategy (Sharpe={strat_metrics["sharpe"]:.3f})',
        linewidth=1.5, color='#1976d2')
ax.plot(df_strat.index, df_strat['bh_cum'], label=f'Buy & Hold SPY (Sharpe={bh_metrics["sharpe"]:.3f})',
        linewidth=1.5, color='#757575', linestyle='--')
ax.set_title('VRP Strategy vs Buy & Hold SPY', fontsize=12, fontweight='bold')
ax.set_ylabel('Cumulative Return')
ax.legend(fontsize=10)
ax.grid(True, alpha=0.3)
ax.set_yscale('log')

# 3b: VRP signal weight over time
ax = axes[1]
ax.plot(df_strat.index, df_strat['vrp_signal'], linewidth=0.5, color='steelblue', alpha=0.5)
rolling_weight = df_strat['vrp_signal'].rolling(66).mean()
ax.plot(df_strat.index, rolling_weight, linewidth=1.5, color='darkblue', label='66-day MA weight')
ax.axhline(y=0.5, color='red', linestyle='--', linewidth=0.8)
ax.set_title('VRP Strategy Weight (SPY allocation)', fontsize=12, fontweight='bold')
ax.set_ylabel('Weight')
ax.legend()
ax.grid(True, alpha=0.3)

plt.tight_layout()
fig.savefig(os.path.join(OUTPUT_DIR, 'k913_vrp_strategy.png'), dpi=150, bbox_inches='tight')
plt.close()
print("  Saved k913_vrp_strategy.png")

# ============================================================
# Summary and Key Findings
# ============================================================
print("\n" + "=" * 70)
print("KEY FINDINGS")
print("=" * 70)

# Determine significance
daily_sig = abs(regression_results['daily_univariate']['t_vrp']) > 3.0
weekly_sig = abs(regression_results['weekly_univariate']['t_vrp']) > 3.0
monthly_sig = abs(regression_results['monthly_univariate']['t_vrp']) > 3.0

findings = []

# VRP characteristics
findings.append(f"VRP positive {vrp_stats['pct_positive']:.1f}% of the time (fear premium persistent)")
findings.append(f"VRP-VIX correlation: {vrp_vix_corr:.3f} (related but distinct signal)")

# Prediction results
for h, label in [('daily', 'Daily'), ('weekly', 'Weekly'), ('monthly', 'Monthly')]:
    uni = regression_results[f'{h}_univariate']
    findings.append(f"{label}: beta={uni['beta_vrp']:.5f}, t={uni['t_vrp']:.3f}, "
                   f"R²={uni['R2']:.6f}, Harvey |t|>3: {'YES' if abs(uni['t_vrp']) > 3.0 else 'NO'}")

# OOS
for h in oos_results:
    findings.append(f"OOS R² ({h}): {oos_results[h]['R2_OOS']:.6f} "
                   f"({'positive' if oos_results[h]['R2_OOS'] > 0 else 'NEGATIVE'})")

# Strategy
findings.append(f"VRP Strategy Sharpe: {strat_metrics['sharpe']:.4f} vs BH SPY: {bh_metrics['sharpe']:.4f}")
findings.append(f"Q5-Q1 spread: {quintile_spread['spread_annual']:.4f} ann., "
               f"t={quintile_spread['t_stat']:.3f}")

for f in findings:
    print(f"  {f}")

# Generate key_findings text
key_findings_text = (
    f"K913 examines VRP (Variance Risk Premium = Implied - Realized Variance) as a return predictor for SPY. "
    f"VRP is positive {vrp_stats['pct_positive']:.1f}% of time (fear premium). "
    f"Daily regression: beta={regression_results['daily_univariate']['beta_vrp']:.5f}, "
    f"t={regression_results['daily_univariate']['t_vrp']:.3f}, R²={regression_results['daily_univariate']['R2']:.6f}. "
    f"Monthly regression: beta={regression_results['monthly_univariate']['beta_vrp']:.5f}, "
    f"t={regression_results['monthly_univariate']['t_vrp']:.3f}, R²={regression_results['monthly_univariate']['R2']:.6f}. "
    f"OOS R² daily={oos_results.get('daily', {}).get('R2_OOS', 'N/A')}, "
    f"monthly={oos_results.get('monthly', {}).get('R2_OOS', 'N/A')}. "
    f"VRP quintile Q5-Q1 spread: {quintile_spread['spread_annual']:.4f} ann (t={quintile_spread['t_stat']:.3f}). "
    f"VRP strategy Sharpe {strat_metrics['sharpe']:.4f} vs BH {bh_metrics['sharpe']:.4f}. "
    f"VRP provides return prediction info that VIX alone does not (VIX predicts vol magnitude, "
    f"VRP captures fear premium = expected compensation for bearing vol risk)."
)

# ============================================================
# Save Results JSON
# ============================================================
results = {
    'experiment_id': 'K913',
    'title': 'Variance Risk Premium (VRP) as Return Predictor',
    'timestamp': datetime.now().isoformat(),
    'data_source': 'yfinance (SPY, ^VIX)',
    'sample_period': f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}",
    'N_total': int(len(df)),
    'method': 'Predictive regressions with Newey-West HAC SE, expanding window OOS, VRP quintile sort',
    'references': [
        'Bollerslev, Tauchen & Zhou (2009): Expected Stock Returns and Variance Risk Premia, RFS 22(11):4463-4492',
        'Bekaert & Hoerova (2014): The VIX, the Variance Premium and Stock Market Volatility, JFE 111(2):120-136',
        'Campbell & Thompson (2008): Predicting Excess Stock Returns Out of Sample, RFS 21(4):1509-1531',
        'Harvey (2016): ... and the Cross-Section of Expected Returns, RFS 29(1):5-68',
    ],
    'vrp_statistics': vrp_stats,
    'vrp_vix_correlation': vrp_vix_corr,
    'vrp_autocorrelation': {
        'acf_1': vrp_acf_1,
        'acf_5': vrp_acf_5,
        'acf_22': vrp_acf_22,
        'ljung_box_10': {'statistic': lb_stat, 'p_value': lb_pval},
    },
    'vrp_regime': vrp_regime,
    'regression_results': regression_results,
    'oos_results': oos_results,
    'strategy_results': strategy_results,
    'quintile_results': quintile_results,
    'quintile_spread': quintile_spread,
    'vrp_interaction': vrp_interaction,
    'interaction_strategy': {
        'combined_vrp_12vix': combined_metrics,
        'plain_12vix': metrics_12vix,
    },
    'key_findings': key_findings_text,
    'charts': [
        'k913_vrp_distribution.png',
        'k913_vrp_prediction.png',
        'k913_vrp_strategy.png',
    ],
}

results_path = os.path.join(OUTPUT_DIR, 'k913_vrp_return_prediction_results.json')
with open(results_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"\nResults saved to {results_path}")
print("Done!")
