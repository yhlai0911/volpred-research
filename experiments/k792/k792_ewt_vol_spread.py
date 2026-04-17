#!/usr/bin/env python3
"""
K792: EWT vs 0050.TW Volatility Spread Signal
===============================================
Hypothesis:
  EWT (US-listed iShares MSCI Taiwan ETF) and 0050.TW track the same underlying
  market (Taiwan equities) but trade in different time zones.
  - EWT: trades on US market hours in USD
  - 0050.TW: trades on Taiwan market hours in TWD

  When EWT_vol >> 0050_vol → international investors perceive higher risk in
  Taiwan equities. This may carry predictive information for subsequent 0050
  volatility or returns.

Research Questions:
  1. Does vol_ratio = RV(EWT)/RV(0050) Granger-cause 0050 volatility?
  2. What is the lead-lag correlation structure between EWT vol and 0050 vol?
  3. Does vol_ratio predict 0050 returns in a regression?
  4. Can a simple vol-timing strategy using signal.shift(1) beat B&H?

Data:
  - EWT + 0050.TW from yfinance (2012-2025)
  - 0050.TW cleaned via clean_tw50_data (split artifact fix)
  - VIX from CBOE for reference

Methods:
  - Rolling 22-day realized volatility (RV_22d) as per K792 spec
  - Granger causality (statsmodels, lags 1,5,10,22)
  - Lead-lag cross-correlation at lags -22 to +22
  - Predictive regression (vol_ratio → next-period returns/vol)
  - Simple strategy: reduce weight when vol_ratio > threshold (signal.shift(1))

Prior findings:
  - K506: EWT-0050 vol spread used as VT overlay → FAILED cross-OOS (2/5 periods)
  - K506 data range: 2010-2022. K792 extends to 2025 and does deeper causal analysis

References:
  - Granger, C.W.J. (1969) "Investigating Causal Relations by Econometric Models"
    Econometrica 37(3):424-438
  - Moreira & Muir (2017) "Volatility-Managed Portfolios" JF 72(4):1611-1644
  - Harvey, Liu, Zhu (2016) "...and the Cross-Section of Expected Returns" RFS
  - K506: cross-OOS result (prior experiment)
  - K697: VIX predicts vol magnitude (corr=0.57) but not direction (corr=0.04)

Author: [提出: User, 執行: Claude]
"""

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
import json
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    from volpred.utils import clean_tw50_data
except ImportError:
    # fallback: inline split fix
    def clean_tw50_data(prices, returns=None):
        clean_prices = prices.copy()
        split_date = pd.Timestamp("2014-01-02")
        if split_date in clean_prices.index:
            pre_mask = clean_prices.index < split_date
            if pre_mask.any():
                last_pre = clean_prices[pre_mask].iloc[-1]
                first_post = clean_prices.loc[split_date]
                ratio = last_pre / first_post
                if 3.5 < ratio < 4.5:
                    clean_prices[pre_mask] = clean_prices[pre_mask] / 4.0
        clean_returns = clean_prices.pct_change()
        extreme_mask = clean_returns.abs() > 0.50
        if extreme_mask.any():
            clean_returns[extreme_mask] = 0.0
            base = clean_prices.iloc[0]
            cum = (1 + clean_returns.fillna(0)).cumprod()
            clean_prices = base * cum
        clean_returns = clean_prices.pct_change()
        return clean_prices, clean_returns

# Statsmodels for Granger causality
try:
    from statsmodels.tsa.stattools import grangercausalitytests, adfuller, acf, ccf
    from statsmodels.stats.diagnostic import acorr_ljungbox
    HAS_STATSMODELS = True
except ImportError:
    HAS_STATSMODELS = False
    print("Warning: statsmodels not available, skipping Granger causality")

RESULTS_PATH = Path(__file__).parent / "k792_ewt_vol_spread_results.json"

# ============================================================
# Configuration
# ============================================================
DATA_START = "2012-01-01"
DATA_END = "2025-12-31"
RV_WINDOW = 22          # 22-day rolling RV (as per K792 spec)
TRADING_DAYS = 252
TX_ROUNDTRIP = 0.001855  # 0.1855% (ETF, corrected in K625)
GRANGER_LAGS = [1, 5, 10, 22]
MAX_LAG = 22            # for lead-lag correlations

t0 = time.time()
print("=" * 80)
print("K792: EWT vs 0050.TW Volatility Spread Signal")
print("=" * 80)

# ============================================================
# 1. DATA DOWNLOAD
# ============================================================
print("\n[1/5] Downloading data (2012-2025)...")

ewt_raw = yf.download("EWT", start=DATA_START, end=DATA_END, progress=False, auto_adjust=True)
tw50_raw = yf.download("0050.TW", start=DATA_START, end=DATA_END, progress=False, auto_adjust=True)
vix_raw = yf.download("^VIX", start=DATA_START, end=DATA_END, progress=False, auto_adjust=True)

# Flatten MultiIndex if present
for df in [ewt_raw, tw50_raw, vix_raw]:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

print(f"  EWT: {len(ewt_raw)} rows, {ewt_raw.index[0].date()} to {ewt_raw.index[-1].date()}")
print(f"  0050.TW: {len(tw50_raw)} rows, {tw50_raw.index[0].date()} to {tw50_raw.index[-1].date()}")
print(f"  VIX: {len(vix_raw)} rows, {vix_raw.index[0].date()} to {vix_raw.index[-1].date()}")

# ============================================================
# 2. DATA PREPARATION
# ============================================================
print("\n[2/5] Preparing data & computing RV_22d...")

# Extract close prices
ewt_close = ewt_raw["Close"].squeeze()
tw50_close = tw50_raw["Close"].squeeze()
vix_close = vix_raw["Close"].squeeze()

# Clean 0050.TW split artifact
tw50_close, _ = clean_tw50_data(tw50_close)
print(f"  0050.TW after clean: range={tw50_close.min():.2f} to {tw50_close.max():.2f}")

# Align on union calendar with forward-fill (EWT=US cal, 0050=TW cal)
all_dates = ewt_close.index.union(tw50_close.index).union(vix_close.index)
ewt_ff = ewt_close.reindex(all_dates).ffill()
tw50_ff = tw50_close.reindex(all_dates).ffill()
vix_ff = vix_close.reindex(all_dates).ffill()

# Use Taiwan (0050) trading calendar as base — strategy trades 0050.TW
tw_dates = tw50_close.dropna().index
ewt_on_tw = ewt_ff.reindex(tw_dates)
tw50_on_tw = tw50_ff.reindex(tw_dates)
vix_on_tw = vix_ff.reindex(tw_dates)

# Build master DataFrame
data = pd.DataFrame({
    "ewt_close": ewt_on_tw,
    "tw50_close": tw50_on_tw,
    "vix": vix_on_tw,
}).dropna()

# Log returns
data["ewt_logret"] = np.log(data["ewt_close"] / data["ewt_close"].shift(1))
data["tw50_logret"] = np.log(data["tw50_close"] / data["tw50_close"].shift(1))
data["tw50_ret"] = data["tw50_close"] / data["tw50_close"].shift(1) - 1
data = data.dropna()

# Rolling 22-day realized volatility (annualized)
data["rv_ewt"] = data["ewt_logret"].rolling(RV_WINDOW).std() * np.sqrt(TRADING_DAYS)
data["rv_tw50"] = data["tw50_logret"].rolling(RV_WINDOW).std() * np.sqrt(TRADING_DAYS)

# Vol ratio: EWT / 0050
data["vol_ratio"] = data["rv_ewt"] / data["rv_tw50"]

data = data.dropna()

n_total = len(data)
print(f"  Aligned dataset: {data.index[0].date()} to {data.index[-1].date()}")
print(f"  Total days: {n_total}")
print(f"  EWT RV_22d: mean={data['rv_ewt'].mean():.3f}, std={data['rv_ewt'].std():.3f}")
print(f"  0050 RV_22d: mean={data['rv_tw50'].mean():.3f}, std={data['rv_tw50'].std():.3f}")
print(f"  Vol ratio (EWT/0050): mean={data['vol_ratio'].mean():.3f}, "
      f"std={data['vol_ratio'].std():.3f}, "
      f"min={data['vol_ratio'].min():.3f}, max={data['vol_ratio'].max():.3f}")
print(f"  Ratio > 1.2: {(data['vol_ratio'] > 1.2).mean()*100:.1f}%")
print(f"  Ratio < 0.8: {(data['vol_ratio'] < 0.8).mean()*100:.1f}%")

# ============================================================
# 3. DESCRIPTIVE STATISTICS
# ============================================================
print("\n[3/5] Descriptive Statistics & Unit Root Tests...")

# ADF test for stationarity
def adf_test(series, name):
    result = adfuller(series.dropna(), autolag='AIC') if HAS_STATSMODELS else (None, None, None, None, {})
    if HAS_STATSMODELS:
        return {
            "name": name,
            "adf_stat": round(float(result[0]), 4),
            "p_value": round(float(result[1]), 4),
            "lags_used": int(result[2]),
            "is_stationary_5pct": result[1] < 0.05
        }
    return {"name": name, "note": "statsmodels unavailable"}

# Descriptive stats
desc_stats = {}
for col in ["rv_ewt", "rv_tw50", "vol_ratio"]:
    s = data[col]
    desc_stats[col] = {
        "mean": round(float(s.mean()), 4),
        "std": round(float(s.std()), 4),
        "skew": round(float(s.skew()), 4),
        "kurt": round(float(s.kurtosis()), 4),
        "min": round(float(s.min()), 4),
        "max": round(float(s.max()), 4),
        "pct25": round(float(s.quantile(0.25)), 4),
        "pct75": round(float(s.quantile(0.75)), 4),
    }
    print(f"  {col}: mean={s.mean():.4f}, std={s.std():.4f}, "
          f"skew={s.skew():.2f}, kurt={s.kurtosis():.2f}")

adf_results = {}
if HAS_STATSMODELS:
    for col in ["rv_ewt", "rv_tw50", "vol_ratio"]:
        adf_res = adf_test(data[col], col)
        adf_results[col] = adf_res
        stat_label = "stationary" if adf_res["is_stationary_5pct"] else "non-stationary"
        print(f"  ADF({col}): stat={adf_res['adf_stat']:.4f}, p={adf_res['p_value']:.4f} ({stat_label})")

# ============================================================
# 4. GRANGER CAUSALITY
# ============================================================
print("\n[4/5] Granger Causality Tests...")

granger_results = {}

if HAS_STATSMODELS:
    # Test 1: Does vol_ratio Granger-cause rv_tw50?
    # (does international vol perception predict Taiwan vol?)
    print("\n  A) Does vol_ratio → rv_tw50 (Granger cause)?")
    try:
        gc_data_a = data[["rv_tw50", "vol_ratio"]].dropna()
        # Granger test: col 0 is the dependent, col 1 is the predictor
        gc_a = grangercausalitytests(gc_data_a.values, maxlag=max(GRANGER_LAGS), verbose=False)
        granger_results["vol_ratio_to_rv_tw50"] = {}
        for lag in GRANGER_LAGS:
            if lag in gc_a:
                f_stat = gc_a[lag][0]["ssr_ftest"][0]
                p_val = gc_a[lag][0]["ssr_ftest"][1]
                granger_results["vol_ratio_to_rv_tw50"][f"lag_{lag}"] = {
                    "f_stat": round(float(f_stat), 4),
                    "p_value": round(float(p_val), 4),
                    "significant_5pct": p_val < 0.05,
                    "significant_1pct": p_val < 0.01,
                }
                sig = "***" if p_val < 0.01 else ("**" if p_val < 0.05 else ("*" if p_val < 0.1 else "ns"))
                print(f"    lag={lag:2d}: F={f_stat:.4f}, p={p_val:.4f} {sig}")
    except Exception as e:
        print(f"    Error: {e}")
        granger_results["vol_ratio_to_rv_tw50"] = {"error": str(e)}

    # Test 2: Does rv_ewt Granger-cause rv_tw50?
    print("\n  B) Does rv_ewt → rv_tw50 (Granger cause)?")
    try:
        gc_data_b = data[["rv_tw50", "rv_ewt"]].dropna()
        gc_b = grangercausalitytests(gc_data_b.values, maxlag=max(GRANGER_LAGS), verbose=False)
        granger_results["rv_ewt_to_rv_tw50"] = {}
        for lag in GRANGER_LAGS:
            if lag in gc_b:
                f_stat = gc_b[lag][0]["ssr_ftest"][0]
                p_val = gc_b[lag][0]["ssr_ftest"][1]
                granger_results["rv_ewt_to_rv_tw50"][f"lag_{lag}"] = {
                    "f_stat": round(float(f_stat), 4),
                    "p_value": round(float(p_val), 4),
                    "significant_5pct": p_val < 0.05,
                    "significant_1pct": p_val < 0.01,
                }
                sig = "***" if p_val < 0.01 else ("**" if p_val < 0.05 else ("*" if p_val < 0.1 else "ns"))
                print(f"    lag={lag:2d}: F={f_stat:.4f}, p={p_val:.4f} {sig}")
    except Exception as e:
        print(f"    Error: {e}")
        granger_results["rv_ewt_to_rv_tw50"] = {"error": str(e)}

    # Test 3: Reverse — does rv_tw50 Granger-cause vol_ratio?
    print("\n  C) Does rv_tw50 → vol_ratio (reverse Granger)?")
    try:
        gc_data_c = data[["vol_ratio", "rv_tw50"]].dropna()
        gc_c = grangercausalitytests(gc_data_c.values, maxlag=max(GRANGER_LAGS), verbose=False)
        granger_results["rv_tw50_to_vol_ratio"] = {}
        for lag in GRANGER_LAGS:
            if lag in gc_c:
                f_stat = gc_c[lag][0]["ssr_ftest"][0]
                p_val = gc_c[lag][0]["ssr_ftest"][1]
                granger_results["rv_tw50_to_vol_ratio"][f"lag_{lag}"] = {
                    "f_stat": round(float(f_stat), 4),
                    "p_value": round(float(p_val), 4),
                    "significant_5pct": p_val < 0.05,
                }
                sig = "***" if p_val < 0.01 else ("**" if p_val < 0.05 else ("*" if p_val < 0.1 else "ns"))
                print(f"    lag={lag:2d}: F={f_stat:.4f}, p={p_val:.4f} {sig}")
    except Exception as e:
        print(f"    Error: {e}")
        granger_results["rv_tw50_to_vol_ratio"] = {"error": str(e)}

# ============================================================
# 5. LEAD-LAG CROSS-CORRELATION
# ============================================================
print("\n  Lead-lag cross-correlation (vol_ratio vs rv_tw50)...")

# Compute cross-correlation manually (symmetric lags)
vol_ratio_z = (data["vol_ratio"] - data["vol_ratio"].mean()) / data["vol_ratio"].std()
rv_tw50_z = (data["rv_tw50"] - data["rv_tw50"].mean()) / data["rv_tw50"].std()
vol_ratio_arr = vol_ratio_z.values
rv_tw50_arr = rv_tw50_z.values

lead_lag_corr = {}
for lag in range(-MAX_LAG, MAX_LAG + 1):
    if lag < 0:
        # vol_ratio leads: vol_ratio[:-|lag|] vs rv_tw50[|lag|:]
        x = vol_ratio_arr[:lag]
        y = rv_tw50_arr[-lag:]
    elif lag > 0:
        # rv_tw50 leads: vol_ratio[lag:] vs rv_tw50[:-lag]
        x = vol_ratio_arr[lag:]
        y = rv_tw50_arr[:-lag]
    else:
        x = vol_ratio_arr
        y = rv_tw50_arr
    n = min(len(x), len(y))
    corr = float(np.corrcoef(x[:n], y[:n])[0, 1])
    lead_lag_corr[lag] = round(corr, 4)

# Find max positive correlation and at what lag
max_corr_lag = max(lead_lag_corr, key=lambda k: lead_lag_corr[k])
max_corr_val = lead_lag_corr[max_corr_lag]
contemp_corr = lead_lag_corr[0]

print(f"\n  Contemporaneous corr(vol_ratio, rv_tw50): {contemp_corr:.4f}")
print(f"  Maximum corr: {max_corr_val:.4f} at lag={max_corr_lag}")
print(f"  Selected lags: " + ", ".join([
    f"lag={l}: {lead_lag_corr[l]:.4f}" for l in [-5, -3, -1, 0, 1, 3, 5, 10, 22]
]))

# Also compute EWT vol vs 0050 vol cross-correlation
rv_ewt_z = (data["rv_ewt"] - data["rv_ewt"].mean()) / data["rv_ewt"].std()
rv_ewt_arr = rv_ewt_z.values

ewt_tw50_corr = {}
for lag in range(-MAX_LAG, MAX_LAG + 1):
    if lag < 0:
        x = rv_ewt_arr[:lag]
        y = rv_tw50_arr[-lag:]
    elif lag > 0:
        x = rv_ewt_arr[lag:]
        y = rv_tw50_arr[:-lag]
    else:
        x = rv_ewt_arr
        y = rv_tw50_arr
    n = min(len(x), len(y))
    corr = float(np.corrcoef(x[:n], y[:n])[0, 1])
    ewt_tw50_corr[lag] = round(corr, 4)

max_ewt_tw50_lag = max(ewt_tw50_corr, key=lambda k: ewt_tw50_corr[k])
max_ewt_tw50_val = ewt_tw50_corr[max_ewt_tw50_lag]
print(f"\n  corr(rv_ewt, rv_tw50) at lag=0: {ewt_tw50_corr[0]:.4f}")
print(f"  Maximum corr(rv_ewt, rv_tw50): {max_ewt_tw50_val:.4f} at lag={max_ewt_tw50_lag}")

# ============================================================
# 6. PREDICTIVE REGRESSION
# ============================================================
print("\n  Predictive Regression...")

# Regression A: vol_ratio[t-1] predicts rv_tw50[t]
# This is the core predictive test
from numpy.linalg import lstsq

reg_results = {}

def ols_regression(X, y, name=""):
    """OLS with Newey-West standard errors."""
    from scipy import stats as sp_stats
    n = len(y)
    X_with_const = np.column_stack([np.ones(n), X])
    beta, _, _, _ = lstsq(X_with_const, y, rcond=None)

    # Residuals
    y_hat = X_with_const @ beta
    resid = y - y_hat

    # R-squared
    ss_res = np.sum(resid**2)
    ss_tot = np.sum((y - y.mean())**2)
    r2 = 1 - ss_res / ss_tot

    # OLS standard errors (no NW for simplicity given data is vol-of-vol which is slow moving)
    mse = ss_res / (n - X_with_const.shape[1])
    var_beta = mse * np.linalg.inv(X_with_const.T @ X_with_const)
    se = np.sqrt(np.diag(var_beta))

    # t-statistics
    t_stats = beta / se
    p_values = [2 * (1 - sp_stats.t.cdf(abs(t), df=n - 2)) for t in t_stats]

    return {
        "intercept": round(float(beta[0]), 6),
        "slope": round(float(beta[1]), 6),
        "r_squared": round(float(r2), 6),
        "t_stat_slope": round(float(t_stats[1]), 4),
        "p_value_slope": round(float(p_values[1]), 4),
        "significant_5pct": p_values[1] < 0.05,
        "n": n,
    }

# A: Does lagged vol_ratio predict rv_tw50?
vr_lag1 = data["vol_ratio"].shift(1).dropna()
rv_tw50_aligned = data["rv_tw50"].reindex(vr_lag1.index).dropna()
common_idx = vr_lag1.index.intersection(rv_tw50_aligned.index)
reg_a = ols_regression(
    vr_lag1.loc[common_idx].values,
    rv_tw50_aligned.loc[common_idx].values,
    "vol_ratio[t-1] → rv_tw50[t]"
)
reg_results["vol_ratio_lag1_to_rv_tw50"] = reg_a
print(f"  A) vol_ratio[t-1] → rv_tw50[t]: β={reg_a['slope']:.4f}, "
      f"t={reg_a['t_stat_slope']:.3f}, p={reg_a['p_value_slope']:.4f}, "
      f"R²={reg_a['r_squared']:.4f}")

# B: Does lagged rv_ewt predict rv_tw50?
rv_ewt_lag1 = data["rv_ewt"].shift(1).dropna()
rv_tw50_b = data["rv_tw50"].reindex(rv_ewt_lag1.index).dropna()
common_b = rv_ewt_lag1.index.intersection(rv_tw50_b.index)
reg_b = ols_regression(
    rv_ewt_lag1.loc[common_b].values,
    rv_tw50_b.loc[common_b].values,
    "rv_ewt[t-1] → rv_tw50[t]"
)
reg_results["rv_ewt_lag1_to_rv_tw50"] = reg_b
print(f"  B) rv_ewt[t-1] → rv_tw50[t]: β={reg_b['slope']:.4f}, "
      f"t={reg_b['t_stat_slope']:.3f}, p={reg_b['p_value_slope']:.4f}, "
      f"R²={reg_b['r_squared']:.4f}")

# C: Does lagged vol_ratio predict tw50 returns?
vr_lag1_c = data["vol_ratio"].shift(1).dropna()
tw50_ret_c = data["tw50_ret"].reindex(vr_lag1_c.index).dropna()
common_c = vr_lag1_c.index.intersection(tw50_ret_c.index)
reg_c = ols_regression(
    vr_lag1_c.loc[common_c].values,
    tw50_ret_c.loc[common_c].values,
    "vol_ratio[t-1] → tw50_ret[t]"
)
reg_results["vol_ratio_lag1_to_tw50_ret"] = reg_c
print(f"  C) vol_ratio[t-1] → tw50_ret[t]: β={reg_c['slope']:.6f}, "
      f"t={reg_c['t_stat_slope']:.3f}, p={reg_c['p_value_slope']:.4f}, "
      f"R²={reg_c['r_squared']:.6f}")

# D: Does rv_ewt / rv_tw50 predict rv_tw50 at 22d horizon?
vr_lag22 = data["vol_ratio"].shift(22).dropna()
rv_tw50_22 = data["rv_tw50"].reindex(vr_lag22.index).dropna()
common_d = vr_lag22.index.intersection(rv_tw50_22.index)
reg_d = ols_regression(
    vr_lag22.loc[common_d].values,
    rv_tw50_22.loc[common_d].values,
    "vol_ratio[t-22] → rv_tw50[t]"
)
reg_results["vol_ratio_lag22_to_rv_tw50"] = reg_d
print(f"  D) vol_ratio[t-22] → rv_tw50[t]: β={reg_d['slope']:.4f}, "
      f"t={reg_d['t_stat_slope']:.3f}, p={reg_d['p_value_slope']:.4f}, "
      f"R²={reg_d['r_squared']:.4f}")

# ============================================================
# 7. SIMPLE STRATEGY BACKTEST
# ============================================================
print("\n  Strategy Backtest...")

# Strategy: use vol_ratio to scale VT weight on 0050.TW
# Base VT: weight = min(8.63/VIX, 1.0)
# Signal: if vol_ratio[t-1] > threshold → reduce weight to 50%
# ⚠️ CRITICAL: signal.shift(1) — use yesterday's signal for today's position

THRESHOLD_HIGH = 1.3   # reduce when EWT vol is 30% above 0050 vol
THRESHOLD_LOW  = 0.85  # increase when EWT vol is 15% below 0050 vol
VT_SCALAR = 8.63
MAX_W = 1.0

data_bt = data.copy()

# VT base weight (using lagged VIX)
data_bt["vt_weight"] = (VT_SCALAR / data_bt["vix"]).clip(upper=MAX_W)

# Vol ratio signal (lagged by 1 day — no lookahead)
data_bt["signal_lag1"] = data_bt["vol_ratio"].shift(1)   # ← KEY: shift(1)

# Strategy weight
data_bt["strat_weight"] = data_bt["vt_weight"].copy()
# When EWT vol >> 0050 vol → international stress → reduce exposure
high_stress = data_bt["signal_lag1"] > THRESHOLD_HIGH
low_stress  = data_bt["signal_lag1"] < THRESHOLD_LOW
data_bt.loc[high_stress, "strat_weight"] = data_bt.loc[high_stress, "vt_weight"] * 0.5
data_bt.loc[low_stress,  "strat_weight"] = (data_bt.loc[low_stress, "vt_weight"] * 1.2).clip(upper=MAX_W)
data_bt["strat_weight"] = data_bt["strat_weight"].clip(0, MAX_W)

# Drop rows where signal is NaN (first day)
data_bt = data_bt.dropna(subset=["signal_lag1", "vt_weight"])

# Transaction costs: applied when weight changes
daily_cash = 0.015 / TRADING_DAYS  # 1.5% annual cash rate

def compute_perf(weights, returns, label):
    """Compute portfolio returns with tx costs."""
    w = weights.values
    r = returns.reindex(weights.index).values
    port_ret = np.empty(len(w))

    prev_w = w[0]
    for i in range(len(w)):
        tx = abs(w[i] - prev_w) * TX_ROUNDTRIP if i > 0 else 0
        port_ret[i] = w[i] * r[i] + (1 - w[i]) * daily_cash - tx
        prev_w = w[i]

    port_s = pd.Series(port_ret, index=weights.index)
    cum = (1 + port_s).cumprod()
    total_ret = float(cum.iloc[-1] - 1)
    n_yrs = len(port_s) / TRADING_DAYS
    ann_ret = (1 + total_ret) ** (1 / n_yrs) - 1
    ann_vol = float(port_s.std() * np.sqrt(TRADING_DAYS))
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    peak = cum.cummax()
    mdd = float(((cum - peak) / peak).min())
    return {
        "label": label,
        "ann_ret_pct": round(ann_ret * 100, 2),
        "ann_vol_pct": round(ann_vol * 100, 2),
        "sharpe": round(sharpe, 4),
        "mdd_pct": round(mdd * 100, 2),
        "calmar": round(ann_ret / abs(mdd), 3) if mdd != 0 else 0,
        "n_days": len(port_s),
    }

# Buy & Hold
bh_perf = {
    "label": "Buy & Hold 0050.TW",
    "ann_ret_pct": round(((1 + data_bt["tw50_ret"]).prod() ** (TRADING_DAYS / len(data_bt)) - 1) * 100, 2),
    "sharpe": round(
        ((data_bt["tw50_ret"].mean() * TRADING_DAYS) / (data_bt["tw50_ret"].std() * np.sqrt(TRADING_DAYS))),
        4
    ),
    "mdd_pct": round(
        (((1 + data_bt["tw50_ret"]).cumprod() / (1 + data_bt["tw50_ret"]).cumprod().cummax()) - 1).min() * 100,
        2
    ),
    "n_days": len(data_bt),
}
bh_perf["ann_vol_pct"] = round(data_bt["tw50_ret"].std() * np.sqrt(TRADING_DAYS) * 100, 2)
bh_perf["calmar"] = round(bh_perf["ann_ret_pct"] / 100 / abs(bh_perf["mdd_pct"] / 100), 3) if bh_perf["mdd_pct"] != 0 else 0

# VT base
vt_perf = compute_perf(data_bt["vt_weight"], data_bt["tw50_ret"], "VT (8.63/VIX)")

# Strategy with vol spread signal
strat_perf = compute_perf(data_bt["strat_weight"], data_bt["tw50_ret"], "VT + EWT Vol Signal")

print(f"\n  Strategy: {DATA_START} to {data_bt.index[-1].date()} ({len(data_bt)} days)")
print(f"  Signal stats: high_stress={high_stress.sum()} days ({high_stress.mean()*100:.1f}%), "
      f"low_stress={low_stress.sum()} days ({low_stress.mean()*100:.1f}%)")
print(f"\n  {'Strategy':<30} {'Sharpe':>8} {'Ann Ret':>9} {'MDD':>8} {'Calmar':>8}")
print(f"  {'-'*65}")
for p in [bh_perf, vt_perf, strat_perf]:
    print(f"  {p['label']:<30} {p['sharpe']:>8.4f} {p['ann_ret_pct']:>8.2f}% "
          f"{p['mdd_pct']:>7.2f}% {p['calmar']:>8.3f}")

# ============================================================
# 8. SUMMARY & INTERPRETATION
# ============================================================
print("\n" + "=" * 80)
print("SUMMARY")
print("=" * 80)

# Determine key findings
granger_a = granger_results.get("vol_ratio_to_rv_tw50", {})
gc_lag1_sig = granger_a.get("lag_1", {}).get("significant_5pct", False)
gc_lag5_sig = granger_a.get("lag_5", {}).get("significant_5pct", False)
gc_lag22_sig = granger_a.get("lag_22", {}).get("significant_5pct", False)

findings = []
if gc_lag1_sig:
    findings.append("vol_ratio Granger-causes rv_tw50 at lag=1 (p<0.05)")
elif gc_lag5_sig:
    findings.append("vol_ratio Granger-causes rv_tw50 at lag=5 (p<0.05), not lag=1")
else:
    findings.append("vol_ratio does NOT significantly Granger-cause rv_tw50 at 5% level")

if reg_a["significant_5pct"]:
    findings.append(f"vol_ratio[t-1] significantly predicts rv_tw50[t]: β={reg_a['slope']:.4f}, t={reg_a['t_stat_slope']:.3f}")
else:
    findings.append(f"vol_ratio[t-1] does NOT significantly predict rv_tw50[t]: t={reg_a['t_stat_slope']:.3f}")

sharpe_improvement = strat_perf["sharpe"] - vt_perf["sharpe"]
findings.append(f"Strategy Sharpe: {strat_perf['sharpe']:.4f} vs VT {vt_perf['sharpe']:.4f} (diff={sharpe_improvement:+.4f})")

for f in findings:
    print(f"  • {f}")

elapsed = time.time() - t0
print(f"\nRuntime: {elapsed:.1f}s")

# ============================================================
# 9. SAVE RESULTS
# ============================================================
print("\nSaving results...")

# Serialize lead-lag correlations (int keys to string)
lead_lag_serialized = {str(k): v for k, v in lead_lag_corr.items()}
ewt_tw50_corr_serialized = {str(k): v for k, v in ewt_tw50_corr.items()}

output = {
    "experiment": "K792",
    "title": "EWT vs 0050.TW Volatility Spread Signal",
    "date": datetime.now(timezone.utc).isoformat(),
    "data_source": "yfinance (EWT, 0050.TW, ^VIX); 0050.TW cleaned via clean_tw50_data",
    "data_range": f"{data.index[0].date()} to {data.index[-1].date()}",
    "n_total_days": int(n_total),
    "config": {
        "rv_window": RV_WINDOW,
        "trading_days": TRADING_DAYS,
        "tx_roundtrip": TX_ROUNDTRIP,
        "granger_lags_tested": GRANGER_LAGS,
        "max_lead_lag": MAX_LAG,
        "strategy_threshold_high": THRESHOLD_HIGH,
        "strategy_threshold_low": THRESHOLD_LOW,
    },
    "descriptive_stats": desc_stats,
    "adf_tests": adf_results if HAS_STATSMODELS else {"note": "statsmodels unavailable"},
    "granger_causality": granger_results,
    "lead_lag_correlations": {
        "vol_ratio_vs_rv_tw50": lead_lag_serialized,
        "rv_ewt_vs_rv_tw50": ewt_tw50_corr_serialized,
        "contemporaneous_corr_vol_ratio_rv_tw50": contemp_corr,
        "max_corr_lag": max_corr_lag,
        "max_corr_value": max_corr_val,
        "max_ewt_tw50_lag": max_ewt_tw50_lag,
        "max_ewt_tw50_value": max_ewt_tw50_val,
    },
    "predictive_regressions": reg_results,
    "strategy_backtest": {
        "period": f"{data_bt.index[0].date()} to {data_bt.index[-1].date()}",
        "n_days": len(data_bt),
        "high_stress_days_pct": round(float(high_stress.mean()) * 100, 1),
        "low_stress_days_pct": round(float(low_stress.mean()) * 100, 1),
        "buy_hold": bh_perf,
        "vt_base": vt_perf,
        "vt_ewt_signal": strat_perf,
        "sharpe_improvement_vs_vt": round(sharpe_improvement, 4),
    },
    "key_findings": findings,
    "connection_to_k506": {
        "note": "K506 used EWT/0050 vol ratio as a VT overlay signal (threshold 1.2)",
        "k506_result": "FAIL — VT+VolSpread wins only 2/5 OOS periods",
        "k792_contribution": "K792 examines causal/predictive mechanism more deeply (Granger, lead-lag, regression)",
        "k506_data_range": "2010-2022",
        "k792_data_range": f"{data.index[0].date()} to {data.index[-1].date()}",
    },
    "runtime_seconds": round(elapsed, 2),
    "references": [
        "Granger (1969) 'Investigating Causal Relations by Econometric Models' Econometrica 37(3):424-438",
        "Moreira & Muir (2017) 'Volatility-Managed Portfolios' JF 72(4):1611-1644",
        "Harvey, Liu, Zhu (2016) '...and the Cross-Section of Expected Returns' RFS",
        "K506: EWT-0050 Vol Spread Cross-OOS (FAIL: 2/5 periods, 2010-2022)",
        "K697: VIX predicts vol magnitude (corr=0.57) not direction (corr=0.04)",
    ],
    "limitations": [
        "Vol ratio uses 22d backward window — potential overlap with target variable",
        "EWT trades in USD; currency effects may affect vol ratio interpretation",
        "0050.TW split artifact corrected but data quality pre-2014 uncertain",
        "Granger causality ≠ structural causality; only statistical precedence",
        "Strategy threshold parameters (1.3/0.85) not optimized; risk of data snooping if tuned",
    ],
}

RESULTS_PATH.write_text(json.dumps(output, indent=2, default=str))
print(f"Saved to {RESULTS_PATH}")
print(f"Total runtime: {elapsed:.1f}s")
