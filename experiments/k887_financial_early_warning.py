"""
K887: Taiwan Financial Stock Early Warning System

Builds a Financial Stress Index (FSI) from Taiwan's major financial holding companies
and tests whether it predicts 0050.TW volatility spikes beyond what VIX already captures.

Background (K757/K757b):
- Fubon Financial (2881.TW) Granger-causes TSMC volatility (F=6.11, p<0.001)
- Financial sector → TSMC, NOT the reverse
- Crisis amplification: 0050-TSMC correlation jumps 0.45→0.91 when VIX>30
- But: TSMC RV does NOT improve OOS vol prediction beyond VIX

This experiment asks: can we build a *practical* early warning signal from financial
stocks for the 0050.TW VT strategy?

Error log rules applied:
- 0050.TW: MUST call clean_tw50_data
- Cross-market: TW calendar primary, VIX forward-filled
- Signal must use shift(1) — NO lookahead
- DM test: use proper implementation
- Sharpe > 2x baseline = almost certainly a bug

References:
- Adrian & Brunnermeier (2016) "CoVaR", American Economic Review
- Acharya et al. (2017) "Measuring Systemic Risk", RFS
- Billio et al. (2012) "Econometric measures of connectedness", JFE

Data source: yfinance (2881.TW, 2882.TW, 2891.TW, 2886.TW, 0050.TW, 2330.TW, ^VIX)
Period: 2010-01-01 to 2026-04-01

[提出: Claude (K757 follow-up), 執行: Claude]
"""

import numpy as np
import pandas as pd
import json
import warnings
import os
from datetime import datetime, timezone
from scipy import stats
from statsmodels.tsa.stattools import grangercausalitytests, adfuller
from sklearn.metrics import roc_auc_score, precision_recall_curve

warnings.filterwarnings('ignore')

# ============================================================
# UTILITY: DM test (fallback if volpred not importable)
# ============================================================
try:
    from volpred.stats.model_evaluation import strategy_dm_test
    dm_available = True
except ImportError:
    dm_available = False

    def strategy_dm_test(r1, r2, h=1, loss_fn="negative_return"):
        """DM test for strategy comparison. Negative t → r1 better."""
        r1 = np.asarray(r1, dtype=np.float64)
        r2 = np.asarray(r2, dtype=np.float64)
        if loss_fn == "negative_return":
            d = -r1 - (-r2)  # d = r2 - r1
        elif loss_fn == "downside":
            d = np.where(r1 < 0, r1 ** 2, 0.0) - np.where(r2 < 0, r2 ** 2, 0.0)
        else:
            raise ValueError(f"Unknown loss_fn: {loss_fn}")
        n_d = len(d)
        d_bar = np.mean(d)
        gamma0 = np.var(d, ddof=0)
        # Newey-West with h-1 lags
        for k in range(1, h):
            w = 1 - k / h
            gamma_k = np.mean((d[k:] - d_bar) * (d[:-k] - d_bar))
            gamma0 += 2 * w * gamma_k
        se = np.sqrt(gamma0 / n_d) if gamma0 > 0 else 1e-15
        t_stat = d_bar / se
        p_val = 2 * (1 - stats.t.cdf(abs(t_stat), df=n_d - 1))
        return float(t_stat), float(p_val)

# ============================================================
# UTILITY: clean_tw50_data
# ============================================================
try:
    from volpred.utils import clean_tw50_data
except ImportError:
    def clean_tw50_data(prices, returns=None):
        """Inline fallback for 0050.TW split fix."""
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


# ============================================================
# Part 0: Data Download
# ============================================================
print("=" * 70)
print("K887: Taiwan Financial Stock Early Warning System")
print("=" * 70)

import yfinance as yf

# Financial holding companies
financial_tickers = {
    'Fubon': '2881.TW',
    'Cathay': '2882.TW',
    'CTBC': '2891.TW',
    'Mega': '2886.TW',
}

# Target + benchmark
other_tickers = {
    '0050': '0050.TW',
    'TSMC': '2330.TW',
}

START = '2010-01-01'
END = '2026-04-01'

# Download all TW tickers
all_tw = {**financial_tickers, **other_tickers}
tw_data = {}
for name, ticker in all_tw.items():
    print(f"Downloading {name} ({ticker})...")
    df = yf.download(ticker, start=START, end=END, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    tw_data[name] = df['Close'].copy()
    print(f"  {name}: {len(df)} obs")

# Build TW prices DataFrame
tw_prices = pd.DataFrame(tw_data).dropna()
print(f"\nTW merged: {len(tw_prices)} obs, "
      f"{tw_prices.index[0].strftime('%Y-%m-%d')} to "
      f"{tw_prices.index[-1].strftime('%Y-%m-%d')}")

# Apply 0050.TW split fix
prices_0050 = tw_prices['0050']
prices_0050_clean, returns_0050_clean = clean_tw50_data(prices_0050)
tw_prices['0050'] = prices_0050_clean
print(f"Applied clean_tw50_data to 0050.TW")

# Download VIX — TW calendar primary, forward-fill
print(f"\nDownloading VIX (^VIX)...")
vix_df = yf.download('^VIX', start=START, end=END, progress=False)
if isinstance(vix_df.columns, pd.MultiIndex):
    vix_df.columns = vix_df.columns.get_level_values(0)
vix_raw = vix_df['Close'].copy()

# Align VIX to TW calendar
vix_aligned = vix_raw.reindex(tw_prices.index, method='ffill')
n_ffilled = int(vix_aligned.notna().sum() - vix_raw.reindex(tw_prices.index).notna().sum())
print(f"VIX aligned to TW calendar: {vix_aligned.notna().sum()} obs ({n_ffilled} forward-filled)")

# Drop leading NaN
valid_mask = vix_aligned.notna()
tw_prices = tw_prices[valid_mask]
vix_aligned = vix_aligned[valid_mask]

# Compute returns
returns = tw_prices.pct_change().dropna()
# Override 0050 returns with clean version
_, returns_0050 = clean_tw50_data(tw_prices['0050'])
returns['0050'] = returns_0050.reindex(returns.index)
returns = returns.dropna()

# Align VIX
vix = vix_aligned.reindex(returns.index)

N_OBS = len(returns)
print(f"\nFinal dataset: {N_OBS} obs, "
      f"{returns.index[0].strftime('%Y-%m-%d')} to "
      f"{returns.index[-1].strftime('%Y-%m-%d')}")

results = {
    "experiment_id": "K887",
    "title": "Taiwan Financial Stock Early Warning System",
    "data_source": "yfinance (2881.TW, 2882.TW, 2891.TW, 2886.TW, 0050.TW, 2330.TW, ^VIX)",
    "period": f"{returns.index[0].strftime('%Y-%m-%d')} to {returns.index[-1].strftime('%Y-%m-%d')}",
    "n_obs": N_OBS,
    "references": [
        "Adrian & Brunnermeier (2016) CoVaR, AER",
        "Acharya et al. (2017) Measuring Systemic Risk, RFS",
        "Billio et al. (2012) Econometric measures of connectedness, JFE",
    ],
    "prior_work": "K757/K757b: Financial sector Granger-causes TSMC vol (F=6.11)",
}

# ============================================================
# Part A: Financial Stress Index (FSI) Construction
# ============================================================
print("\n" + "=" * 70)
print("PART A: Financial Stress Index Construction")
print("=" * 70)

financial_names = list(financial_tickers.keys())

# 1. Rolling 20-day realized vol for each financial stock
RVOL_WINDOW = 20
ANN_FACTOR = np.sqrt(252)

fin_rvol = pd.DataFrame()
for name in financial_names:
    fin_rvol[name] = returns[name].rolling(RVOL_WINDOW).std() * ANN_FACTOR

# 2. Rolling 20-day max drawdown
fin_mdd = pd.DataFrame()
for name in financial_names:
    prices_s = tw_prices[name].reindex(returns.index)
    roll_max = prices_s.rolling(RVOL_WINDOW).max()
    dd = (prices_s - roll_max) / roll_max
    fin_mdd[name] = dd.rolling(RVOL_WINDOW).min()

# 3. 5-day momentum (negative = stress)
fin_mom = pd.DataFrame()
for name in financial_names:
    fin_mom[name] = returns[name].rolling(5).sum()

# Z-score each metric
def rolling_zscore(series, window=252):
    """Rolling z-score with expanding fallback for early data."""
    mu = series.rolling(window, min_periods=60).mean()
    sigma = series.rolling(window, min_periods=60).std()
    return (series - mu) / sigma.replace(0, np.nan)

# FSI composite: average z-score of (vol, -mdd, -momentum)
# Higher FSI = more financial stress
fsi_components = pd.DataFrame()

for name in financial_names:
    z_vol = rolling_zscore(fin_rvol[name])
    z_mdd = rolling_zscore(-fin_mdd[name])  # Negate: deeper drawdown → higher stress
    z_mom = rolling_zscore(-fin_mom[name])   # Negate: negative momentum → higher stress
    fsi_components[f'{name}_vol'] = z_vol
    fsi_components[f'{name}_mdd'] = z_mdd
    fsi_components[f'{name}_mom'] = z_mom

# Equal-weighted composite
FSI = fsi_components.mean(axis=1)
FSI.name = 'FSI'

# Simpler version: just volatility
FSI_vol = pd.DataFrame()
for name in financial_names:
    FSI_vol[name] = rolling_zscore(fin_rvol[name])
FSI_simple = FSI_vol.mean(axis=1)
FSI_simple.name = 'FSI_vol'

# Drop initial NaN period
valid_fsi = FSI.dropna()
print(f"FSI available from {valid_fsi.index[0].strftime('%Y-%m-%d')}: {len(valid_fsi)} obs")

# Descriptive stats
print(f"\nFSI descriptive statistics:")
print(f"  Mean:     {FSI.mean():.4f}")
print(f"  Std:      {FSI.std():.4f}")
print(f"  Skewness: {FSI.skew():.4f}")
print(f"  Kurtosis: {FSI.kurtosis():.4f}")
print(f"  Min:      {FSI.min():.4f}")
print(f"  Max:      {FSI.max():.4f}")

# ADF test on FSI
adf_result = adfuller(FSI.dropna(), maxlag=20, autolag='AIC')
print(f"  ADF stat: {adf_result[0]:.4f} (p={adf_result[1]:.4f})")

results["part_a"] = {
    "fsi_stats": {
        "mean": round(float(FSI.mean()), 4),
        "std": round(float(FSI.std()), 4),
        "skewness": round(float(FSI.skew()), 4),
        "kurtosis": round(float(FSI.kurtosis()), 4),
        "min": round(float(FSI.min()), 4),
        "max": round(float(FSI.max()), 4),
        "adf_stat": round(float(adf_result[0]), 4),
        "adf_pval": round(float(adf_result[1]), 4),
    },
    "fsi_components": "4 financial stocks × 3 metrics (vol, mdd, momentum), z-scored, equal-weighted",
    "n_obs_fsi": len(valid_fsi),
}

# ============================================================
# Part B: Predictive Power for 0050.TW Volatility
# ============================================================
print("\n" + "=" * 70)
print("PART B: Predictive Power for 0050.TW Volatility")
print("=" * 70)

# 0050 realized vol (20-day rolling)
rvol_0050 = returns['0050'].rolling(RVOL_WINDOW).std() * ANN_FACTOR
rvol_0050.name = 'rvol_0050'

# Build analysis DataFrame
analysis = pd.DataFrame({
    'rvol_0050': rvol_0050,
    'FSI': FSI,
    'FSI_vol': FSI_simple,
    'VIX': vix,
    'ret_0050': returns['0050'],
}).dropna()

print(f"Analysis sample: {len(analysis)} obs")

# B1: Granger Causality — FSI → 0050 vol
print("\n--- B1: Granger Causality (FSI → 0050 RVol) ---")

# Select lag by AIC using VAR
from statsmodels.tsa.api import VAR

gc_data = analysis[['rvol_0050', 'FSI']].dropna()
var_model = VAR(gc_data)
try:
    lag_order = var_model.select_order(maxlags=10)
    best_aic_lag = lag_order.aic
    print(f"AIC-selected lag: {best_aic_lag}")
except Exception as e:
    best_aic_lag = 5
    print(f"VAR lag selection failed ({e}), using lag=5")

# Run Granger test at AIC-selected lag
try:
    gc_result = grangercausalitytests(gc_data, maxlag=[best_aic_lag], verbose=False)
    gc_f = gc_result[best_aic_lag][0]['ssr_ftest'][0]
    gc_p = gc_result[best_aic_lag][0]['ssr_ftest'][1]
    print(f"Granger F-test (FSI → 0050 RVol, lag={best_aic_lag}): F={gc_f:.4f}, p={gc_p:.6f}")
except Exception as e:
    gc_f, gc_p = np.nan, np.nan
    print(f"Granger test failed: {e}")

# Also test reverse: 0050 vol → FSI
gc_data_rev = analysis[['FSI', 'rvol_0050']].dropna()
try:
    gc_result_rev = grangercausalitytests(gc_data_rev, maxlag=[best_aic_lag], verbose=False)
    gc_f_rev = gc_result_rev[best_aic_lag][0]['ssr_ftest'][0]
    gc_p_rev = gc_result_rev[best_aic_lag][0]['ssr_ftest'][1]
    print(f"Granger F-test (0050 RVol → FSI, lag={best_aic_lag}): F={gc_f_rev:.4f}, p={gc_p_rev:.6f}")
except Exception as e:
    gc_f_rev, gc_p_rev = np.nan, np.nan
    print(f"Reverse Granger test failed: {e}")

results["part_b_granger"] = {
    "aic_lag": int(best_aic_lag),
    "fsi_to_0050_F": round(float(gc_f), 4) if not np.isnan(gc_f) else None,
    "fsi_to_0050_p": round(float(gc_p), 6) if not np.isnan(gc_p) else None,
    "reverse_0050_to_fsi_F": round(float(gc_f_rev), 4) if not np.isnan(gc_f_rev) else None,
    "reverse_0050_to_fsi_p": round(float(gc_p_rev), 6) if not np.isnan(gc_p_rev) else None,
}

# B2: Regression — incremental predictive power beyond VIX
print("\n--- B2: Incremental R² Beyond VIX ---")
import statsmodels.api as sm

# Next-day vol as target (shift -1 to get forward-looking)
analysis['rvol_0050_next'] = analysis['rvol_0050'].shift(-1)
reg_data = analysis[['rvol_0050_next', 'VIX', 'FSI', 'FSI_vol']].dropna()

# Model 1: VIX only
X1 = sm.add_constant(reg_data[['VIX']])
y = reg_data['rvol_0050_next']
m1 = sm.OLS(y, X1).fit(cov_type='HC1')
print(f"\nModel 1 (VIX only): R²={m1.rsquared:.4f}, Adj R²={m1.rsquared_adj:.4f}")
print(f"  VIX coeff: {m1.params['VIX']:.6f} (t={m1.tvalues['VIX']:.2f})")

# Model 2: VIX + FSI
X2 = sm.add_constant(reg_data[['VIX', 'FSI']])
m2 = sm.OLS(y, X2).fit(cov_type='HC1')
print(f"\nModel 2 (VIX + FSI): R²={m2.rsquared:.4f}, Adj R²={m2.rsquared_adj:.4f}")
print(f"  VIX coeff: {m2.params['VIX']:.6f} (t={m2.tvalues['VIX']:.2f})")
print(f"  FSI coeff: {m2.params['FSI']:.6f} (t={m2.tvalues['FSI']:.2f})")

# Model 3: VIX + FSI_vol (simpler)
X3 = sm.add_constant(reg_data[['VIX', 'FSI_vol']])
m3 = sm.OLS(y, X3).fit(cov_type='HC1')
print(f"\nModel 3 (VIX + FSI_vol): R²={m3.rsquared:.4f}, Adj R²={m3.rsquared_adj:.4f}")
print(f"  VIX coeff:     {m3.params['VIX']:.6f} (t={m3.tvalues['VIX']:.2f})")
print(f"  FSI_vol coeff: {m3.params['FSI_vol']:.6f} (t={m3.tvalues['FSI_vol']:.2f})")

# Incremental R²
incr_r2 = m2.rsquared - m1.rsquared
incr_r2_vol = m3.rsquared - m1.rsquared
print(f"\nIncremental R² (FSI beyond VIX):     {incr_r2:.6f}")
print(f"Incremental R² (FSI_vol beyond VIX): {incr_r2_vol:.6f}")

# Partial correlation: FSI and next-day vol, controlling for VIX
from scipy.stats import pearsonr
resid_fsi = sm.OLS(reg_data['FSI'], sm.add_constant(reg_data['VIX'])).fit().resid
resid_vol = sm.OLS(reg_data['rvol_0050_next'], sm.add_constant(reg_data['VIX'])).fit().resid
partial_r, partial_p = pearsonr(resid_fsi, resid_vol)
print(f"\nPartial correlation (FSI | VIX, next-day vol): r={partial_r:.4f}, p={partial_p:.6f}")

results["part_b_regression"] = {
    "vix_only_r2": round(float(m1.rsquared), 6),
    "vix_fsi_r2": round(float(m2.rsquared), 6),
    "vix_fsivol_r2": round(float(m3.rsquared), 6),
    "incremental_r2_fsi": round(float(incr_r2), 6),
    "incremental_r2_fsivol": round(float(incr_r2_vol), 6),
    "fsi_t_stat": round(float(m2.tvalues['FSI']), 4),
    "fsi_p_value": round(float(m2.pvalues['FSI']), 6),
    "fsivol_t_stat": round(float(m3.tvalues['FSI_vol']), 4),
    "fsivol_p_value": round(float(m3.pvalues['FSI_vol']), 6),
    "partial_corr_fsi_vol_given_vix": round(float(partial_r), 4),
    "partial_corr_p": round(float(partial_p), 6),
}

# B3: Rolling OOS R² comparison (expanding window)
print("\n--- B3: Rolling OOS R² ---")

IS_WINDOW = 504  # 2 years in-sample
oos_se_vix_list = []
oos_se_fsi_list = []
oos_dates = []

# Use numpy arrays for robustness in OOS loop
y_all = reg_data['rvol_0050_next'].values
vix_all = reg_data['VIX'].values
fsi_all = reg_data['FSI'].values

for t in range(IS_WINDOW, len(reg_data) - 1):
    y_train = y_all[:t]
    y_test = y_all[t]

    # VIX only: y = a + b*VIX
    X_train_1 = np.column_stack([np.ones(t), vix_all[:t]])
    X_test_1 = np.array([1.0, vix_all[t]])
    try:
        beta_1 = np.linalg.lstsq(X_train_1, y_train, rcond=None)[0]
        pred_1 = X_test_1 @ beta_1
    except Exception:
        pred_1 = np.mean(y_train)

    # VIX + FSI: y = a + b*VIX + c*FSI
    X_train_2 = np.column_stack([np.ones(t), vix_all[:t], fsi_all[:t]])
    X_test_2 = np.array([1.0, vix_all[t], fsi_all[t]])
    try:
        beta_2 = np.linalg.lstsq(X_train_2, y_train, rcond=None)[0]
        pred_2 = X_test_2 @ beta_2
    except Exception:
        pred_2 = np.mean(y_train)

    oos_se_vix_list.append((y_test - pred_1) ** 2)
    oos_se_fsi_list.append((y_test - pred_2) ** 2)
    oos_dates.append(reg_data.index[t])

oos_se_vix = np.array(oos_se_vix_list)
oos_se_fsi = np.array(oos_se_fsi_list)

oos_mse_vix = np.mean(oos_se_vix)
oos_mse_fsi = np.mean(oos_se_fsi)
# OOS R² relative to mean forecast
y_oos = reg_data['rvol_0050_next'].iloc[IS_WINDOW:-1]
ss_tot = np.sum((y_oos.values - y_oos.mean()) ** 2)
oos_r2_vix_val = 1 - np.sum(oos_se_vix) / ss_tot
oos_r2_fsi_val = 1 - np.sum(oos_se_fsi) / ss_tot

print(f"OOS MSE (VIX only):  {oos_mse_vix:.8f}")
print(f"OOS MSE (VIX+FSI):   {oos_mse_fsi:.8f}")
print(f"OOS R² (VIX only):   {oos_r2_vix_val:.4f}")
print(f"OOS R² (VIX+FSI):    {oos_r2_fsi_val:.4f}")
print(f"MSE reduction:       {(1 - oos_mse_fsi/oos_mse_vix)*100:.2f}%")

# DM test on OOS forecast errors
d = oos_se_vix - oos_se_fsi  # positive = VIX+FSI is better
n_oos = len(d)
d_bar = np.mean(d)
se_d = np.std(d, ddof=1) / np.sqrt(n_oos)
dm_t = d_bar / se_d if se_d > 0 else 0
dm_p = 2 * (1 - stats.t.cdf(abs(dm_t), df=n_oos - 1))
print(f"\nDM test (VIX vs VIX+FSI): t={dm_t:.4f}, p={dm_p:.6f}")
print(f"  (positive t → VIX+FSI better)")

results["part_b_oos"] = {
    "is_window": IS_WINDOW,
    "n_oos": n_oos,
    "oos_mse_vix_only": round(float(oos_mse_vix), 8),
    "oos_mse_vix_fsi": round(float(oos_mse_fsi), 8),
    "oos_r2_vix_only": round(float(oos_r2_vix_val), 4),
    "oos_r2_vix_fsi": round(float(oos_r2_fsi_val), 4),
    "mse_reduction_pct": round(float((1 - oos_mse_fsi/oos_mse_vix)*100), 2),
    "dm_t_stat": round(float(dm_t), 4),
    "dm_p_value": round(float(dm_p), 6),
}

# B4: Subperiod analysis — does FSI help more during crises?
print("\n--- B4: Subperiod Analysis (VIX regimes) ---")

# Define regimes based on VIX
reg_data_with_vix = reg_data.copy()
reg_data_with_vix['regime'] = pd.cut(
    reg_data_with_vix['VIX'],
    bins=[0, 20, 25, 100],
    labels=['Low (<20)', 'Medium (20-25)', 'High (>25)']
)

subperiod_results = {}
for regime_name in ['Low (<20)', 'Medium (20-25)', 'High (>25)']:
    mask = reg_data_with_vix['regime'] == regime_name
    sub = reg_data_with_vix[mask]
    if len(sub) < 30:
        print(f"  {regime_name}: too few obs ({len(sub)})")
        subperiod_results[regime_name] = {"n": len(sub), "note": "insufficient"}
        continue

    y_sub = sub['rvol_0050_next']
    X1_sub = sm.add_constant(sub[['VIX']])
    X2_sub = sm.add_constant(sub[['VIX', 'FSI']])

    m1_sub = sm.OLS(y_sub, X1_sub).fit()
    m2_sub = sm.OLS(y_sub, X2_sub).fit()
    incr = m2_sub.rsquared - m1_sub.rsquared

    fsi_t = m2_sub.tvalues.get('FSI', 0)
    fsi_p = m2_sub.pvalues.get('FSI', 1)

    print(f"  {regime_name} (n={len(sub)}): VIX R²={m1_sub.rsquared:.4f}, "
          f"VIX+FSI R²={m2_sub.rsquared:.4f}, Δ={incr:.4f}, "
          f"FSI t={fsi_t:.2f} (p={fsi_p:.4f})")

    subperiod_results[regime_name] = {
        "n": len(sub),
        "vix_r2": round(float(m1_sub.rsquared), 4),
        "vix_fsi_r2": round(float(m2_sub.rsquared), 4),
        "incremental_r2": round(float(incr), 4),
        "fsi_t": round(float(fsi_t), 4),
        "fsi_p": round(float(fsi_p), 4),
    }

results["part_b_subperiod"] = subperiod_results

# ============================================================
# Part C: Early Warning Signal Quality
# ============================================================
print("\n" + "=" * 70)
print("PART C: Early Warning Signal Quality")
print("=" * 70)

# Define vol spike: |return| > 2σ (rolling 252-day)
rolling_sigma = returns['0050'].rolling(252, min_periods=126).std()
spike_threshold = 2.0 * rolling_sigma
abs_ret = returns['0050'].abs()
vol_spike = (abs_ret > spike_threshold).astype(int)
vol_spike.name = 'vol_spike'

# Merge with FSI (shift FSI by 1 to predict NEXT day spike — no lookahead)
signal_data = pd.DataFrame({
    'FSI': FSI.shift(1),  # Yesterday's FSI predicts today's spike
    'FSI_vol': FSI_simple.shift(1),
    'VIX': vix.shift(1),  # Yesterday's VIX
    'spike': vol_spike,
}).dropna()

n_spikes = int(signal_data['spike'].sum())
spike_rate = signal_data['spike'].mean()
print(f"Vol spikes (|ret| > 2σ rolling): {n_spikes} / {len(signal_data)} ({spike_rate*100:.1f}%)")

# C1: ROC/AUC
print("\n--- C1: ROC/AUC for Vol Spike Prediction ---")

# FSI only
try:
    auc_fsi = roc_auc_score(signal_data['spike'], signal_data['FSI'])
    print(f"AUC (FSI):     {auc_fsi:.4f}")
except Exception:
    auc_fsi = np.nan
    print("AUC (FSI): failed")

# VIX only
try:
    auc_vix = roc_auc_score(signal_data['spike'], signal_data['VIX'])
    print(f"AUC (VIX):     {auc_vix:.4f}")
except Exception:
    auc_vix = np.nan

# FSI + VIX (logistic regression score)
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

scaler = StandardScaler()
X_lr = scaler.fit_transform(signal_data[['VIX', 'FSI']])
lr = LogisticRegression(max_iter=1000)
lr.fit(X_lr, signal_data['spike'])
combined_score = lr.predict_proba(X_lr)[:, 1]
try:
    auc_combined = roc_auc_score(signal_data['spike'], combined_score)
    print(f"AUC (VIX+FSI): {auc_combined:.4f}")
except Exception:
    auc_combined = np.nan

# C2: Precision/Recall at FSI thresholds
print("\n--- C2: Precision/Recall at FSI Thresholds ---")

precisions, recalls, thresholds_pr = precision_recall_curve(
    signal_data['spike'], signal_data['FSI']
)

# Report at a few key thresholds
for pct in [75, 90, 95]:
    threshold = np.percentile(signal_data['FSI'].values, pct)
    predicted = (signal_data['FSI'] > threshold).astype(int)
    tp = ((predicted == 1) & (signal_data['spike'] == 1)).sum()
    fp = ((predicted == 1) & (signal_data['spike'] == 0)).sum()
    fn = ((predicted == 0) & (signal_data['spike'] == 1)).sum()
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0
    print(f"  FSI > P{pct} ({threshold:.2f}): Precision={precision:.3f}, "
          f"Recall={recall:.3f}, TP={tp}, FP={fp}, FN={fn}")

# C3: Lead time analysis — how early does FSI rise before a spike?
print("\n--- C3: Lead Time Analysis ---")

# Find spike events (gap at least 5 days between spikes to count as separate events)
spike_dates = signal_data.index[signal_data['spike'] == 1]
spike_events = []
prev_date = None
for d in spike_dates:
    if prev_date is None or (d - prev_date).days > 5:
        spike_events.append(d)
    prev_date = d

n_events = len(spike_events)
print(f"Distinct spike events (5-day gap): {n_events}")

# For each event, look at FSI in the 20 days before
lead_fsi = []
for event_date in spike_events:
    loc = signal_data.index.get_loc(event_date)
    if loc >= 20:
        fsi_before = signal_data['FSI'].iloc[loc-20:loc].values
        lead_fsi.append(fsi_before)

if len(lead_fsi) > 5:
    lead_fsi_arr = np.array(lead_fsi)
    mean_fsi_before = lead_fsi_arr.mean(axis=0)

    # When does FSI first exceed 1σ above unconditional mean?
    fsi_mean = signal_data['FSI'].mean()
    fsi_std = signal_data['FSI'].std()
    threshold_1sig = fsi_mean + fsi_std

    first_above = None
    for i, val in enumerate(mean_fsi_before):
        if val > threshold_1sig:
            first_above = 20 - i  # days before spike
            break

    if first_above is not None:
        print(f"Average FSI exceeds 1σ threshold {first_above} days before spike")
    else:
        print("Average FSI does not exceed 1σ before spike")

    # Also report average FSI levels at various leads
    for lead in [1, 5, 10, 20]:
        if lead <= len(mean_fsi_before):
            val = mean_fsi_before[-lead]
            print(f"  Average FSI {lead} day(s) before spike: {val:.4f}")
else:
    print("Too few events for lead time analysis")
    first_above = None

results["part_c"] = {
    "n_spikes": n_spikes,
    "spike_rate": round(float(spike_rate), 4),
    "auc_fsi": round(float(auc_fsi), 4) if not np.isnan(auc_fsi) else None,
    "auc_vix": round(float(auc_vix), 4) if not np.isnan(auc_vix) else None,
    "auc_combined": round(float(auc_combined), 4) if not np.isnan(auc_combined) else None,
    "n_spike_events": n_events,
    "lead_time_days": first_above,
}

# ============================================================
# Part D: VT Strategy Improvement (conditional on Part B)
# ============================================================
print("\n" + "=" * 70)
print("PART D: VT Strategy Improvement")
print("=" * 70)

# Check if FSI has any signal
fsi_has_signal = (results["part_b_regression"]["fsi_t_stat"] is not None and
                  abs(results["part_b_regression"]["fsi_t_stat"]) > 1.96)

print(f"FSI t-stat in regression: {results['part_b_regression']['fsi_t_stat']}")
print(f"Proceeding with strategy test regardless (report null if no signal)")

# Build strategy data
strat_data = pd.DataFrame({
    'ret_0050': returns['0050'],
    'VIX': vix,
    'FSI': FSI,
}).dropna()

# Need at least 252 days for rolling baseline
strat_data = strat_data.iloc[252:]

# Baseline: 8.63/VIX VT for 0050.TW
# Weight = min(8.63/VIX, 1.0), using YESTERDAY's VIX (shift 1)
K_BASE = 8.63
strat_data['w_base'] = (K_BASE / strat_data['VIX']).clip(0, 1)
strat_data['w_base'] = strat_data['w_base'].shift(1)  # NO LOOKAHEAD

# Enhanced: when FSI > threshold (75th percentile), reduce weight by 50%
FSI_THRESHOLD = strat_data['FSI'].quantile(0.75)
strat_data['fsi_flag'] = (strat_data['FSI'].shift(1) > FSI_THRESHOLD).astype(int)  # shift(1) = yesterday's FSI
strat_data['w_enhanced'] = strat_data['w_base'] * (1 - 0.5 * strat_data['fsi_flag'])

# Also test a more aggressive variant: FSI > 90th percentile → reduce by 70%
FSI_THRESHOLD_90 = strat_data['FSI'].quantile(0.90)
strat_data['fsi_flag_90'] = (strat_data['FSI'].shift(1) > FSI_THRESHOLD_90).astype(int)
strat_data['w_enhanced_90'] = strat_data['w_base'] * (1 - 0.7 * strat_data['fsi_flag_90'])

# Buy-and-hold baseline
strat_data['w_bh'] = 1.0

# Drop NaN from shift
strat_data = strat_data.dropna()

# Compute returns
strat_data['ret_base'] = strat_data['w_base'] * strat_data['ret_0050']
strat_data['ret_enhanced'] = strat_data['w_enhanced'] * strat_data['ret_0050']
strat_data['ret_enhanced_90'] = strat_data['w_enhanced_90'] * strat_data['ret_0050']
strat_data['ret_bh'] = strat_data['ret_0050']

# Compute metrics
def compute_metrics(ret_series, name):
    """Compute Sharpe, CAGR, MDD, Calmar."""
    ret = ret_series.dropna()
    n_years = len(ret) / 252
    ann_ret = ret.mean() * 252
    ann_vol = ret.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    cum = (1 + ret).cumprod()
    cagr = (cum.iloc[-1] ** (1 / n_years) - 1) if n_years > 0 else 0
    peak = cum.cummax()
    dd = (cum - peak) / peak
    mdd = dd.min()
    calmar = cagr / abs(mdd) if mdd != 0 else 0

    print(f"  {name:30s}: Sharpe={sharpe:.3f}, CAGR={cagr*100:.2f}%, "
          f"MDD={mdd*100:.1f}%, Calmar={calmar:.3f}")

    return {
        "sharpe": round(float(sharpe), 4),
        "cagr": round(float(cagr * 100), 2),
        "mdd": round(float(mdd * 100), 1),
        "calmar": round(float(calmar), 4),
        "ann_vol": round(float(ann_vol * 100), 2),
    }

print(f"\nStrategy Period: {strat_data.index[0].strftime('%Y-%m-%d')} to "
      f"{strat_data.index[-1].strftime('%Y-%m-%d')} ({len(strat_data)} days)")
print(f"FSI threshold (P75): {FSI_THRESHOLD:.4f}")
print(f"FSI threshold (P90): {FSI_THRESHOLD_90:.4f}")
print(f"Days FSI > P75: {strat_data['fsi_flag'].sum()} ({strat_data['fsi_flag'].mean()*100:.1f}%)")
print(f"Days FSI > P90: {strat_data['fsi_flag_90'].sum()} ({strat_data['fsi_flag_90'].mean()*100:.1f}%)")

metrics = {}
metrics['Buy&Hold 0050'] = compute_metrics(strat_data['ret_bh'], 'Buy&Hold 0050')
metrics['8.63/VIX VT'] = compute_metrics(strat_data['ret_base'], '8.63/VIX VT (baseline)')
metrics['VT + FSI P75 (-50%)'] = compute_metrics(strat_data['ret_enhanced'], 'VT + FSI P75 (-50%)')
metrics['VT + FSI P90 (-70%)'] = compute_metrics(strat_data['ret_enhanced_90'], 'VT + FSI P90 (-70%)')

# DM tests
print("\n--- DM Tests (Harvey t>3.0 threshold) ---")

dm_results = {}
# VT baseline vs enhanced
t1, p1 = strategy_dm_test(
    strat_data['ret_base'].values,
    strat_data['ret_enhanced'].values,
)
print(f"VT baseline vs VT+FSI(P75): t={t1:.4f}, p={p1:.6f}")
dm_results['baseline_vs_fsi75'] = {"t": round(float(t1), 4), "p": round(float(p1), 6)}

t2, p2 = strategy_dm_test(
    strat_data['ret_base'].values,
    strat_data['ret_enhanced_90'].values,
)
print(f"VT baseline vs VT+FSI(P90): t={t2:.4f}, p={p2:.6f}")
dm_results['baseline_vs_fsi90'] = {"t": round(float(t2), 4), "p": round(float(p2), 6)}

# BH vs VT baseline
t3, p3 = strategy_dm_test(
    strat_data['ret_bh'].values,
    strat_data['ret_base'].values,
)
print(f"BH vs VT baseline:          t={t3:.4f}, p={p3:.6f}")
dm_results['bh_vs_baseline'] = {"t": round(float(t3), 4), "p": round(float(p3), 6)}

# Sanity check: Sharpe > 2x baseline?
base_sharpe = metrics['8.63/VIX VT']['sharpe']
for name, m in metrics.items():
    if name != '8.63/VIX VT' and m['sharpe'] > 2 * base_sharpe and base_sharpe > 0:
        print(f"⚠️ WARNING: {name} Sharpe ({m['sharpe']}) > 2x baseline ({base_sharpe}) — likely bug!")

results["part_d"] = {
    "period": f"{strat_data.index[0].strftime('%Y-%m-%d')} to {strat_data.index[-1].strftime('%Y-%m-%d')}",
    "n_days": len(strat_data),
    "fsi_threshold_p75": round(float(FSI_THRESHOLD), 4),
    "fsi_threshold_p90": round(float(FSI_THRESHOLD_90), 4),
    "fsi_has_statistical_signal": bool(fsi_has_signal),
    "metrics": metrics,
    "dm_tests": dm_results,
}

# ============================================================
# Part E: Cross-OOS Validation (2 non-overlapping periods)
# ============================================================
print("\n" + "=" * 70)
print("PART E: Cross-OOS Validation")
print("=" * 70)

# Split into 2 non-overlapping periods
mid_date = strat_data.index[len(strat_data) // 2]
periods = {
    'Period 1': strat_data[strat_data.index <= mid_date],
    'Period 2': strat_data[strat_data.index > mid_date],
}

cross_oos = {}
for period_name, period_data in periods.items():
    if len(period_data) < 252:
        print(f"\n{period_name}: too few obs ({len(period_data)})")
        continue

    print(f"\n{period_name}: {period_data.index[0].strftime('%Y-%m-%d')} to "
          f"{period_data.index[-1].strftime('%Y-%m-%d')} ({len(period_data)} days)")

    m_base = compute_metrics(period_data['ret_base'], f'{period_name} VT baseline')
    m_enh = compute_metrics(period_data['ret_enhanced'], f'{period_name} VT+FSI(P75)')

    t_sub, p_sub = strategy_dm_test(
        period_data['ret_base'].values,
        period_data['ret_enhanced'].values,
    )
    print(f"  DM test: t={t_sub:.4f}, p={p_sub:.6f}")

    cross_oos[period_name] = {
        "dates": f"{period_data.index[0].strftime('%Y-%m-%d')} to {period_data.index[-1].strftime('%Y-%m-%d')}",
        "n_days": len(period_data),
        "baseline": m_base,
        "enhanced": m_enh,
        "dm_t": round(float(t_sub), 4),
        "dm_p": round(float(p_sub), 6),
    }

results["part_e_cross_oos"] = cross_oos

# ============================================================
# Summary & Conclusions
# ============================================================
print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)

# Determine key findings
fsi_granger_sig = results["part_b_granger"]["fsi_to_0050_p"] is not None and results["part_b_granger"]["fsi_to_0050_p"] < 0.05
fsi_incr_sig = abs(results["part_b_regression"]["fsi_t_stat"]) > 1.96 if results["part_b_regression"]["fsi_t_stat"] is not None else False
fsi_auc_useful = results["part_c"]["auc_fsi"] is not None and results["part_c"]["auc_fsi"] > 0.55
strategy_improved = False

# Check if enhanced strategy has higher Sharpe without triggering 2x bug check
if 'VT + FSI P75 (-50%)' in metrics and '8.63/VIX VT' in metrics:
    enh_sharpe = metrics['VT + FSI P75 (-50%)']['sharpe']
    base_sharpe_val = metrics['8.63/VIX VT']['sharpe']
    if enh_sharpe > base_sharpe_val:
        strategy_improved = True

conclusions = []
if fsi_granger_sig:
    conclusions.append(f"FSI Granger-causes 0050 RVol (F={results['part_b_granger']['fsi_to_0050_F']}, p={results['part_b_granger']['fsi_to_0050_p']:.4f}) — confirms K757")
else:
    conclusions.append("FSI does NOT Granger-cause 0050 RVol at 5% level")

if fsi_incr_sig:
    conclusions.append(f"FSI adds incremental predictive power beyond VIX (t={results['part_b_regression']['fsi_t_stat']:.2f}, ΔR²={results['part_b_regression']['incremental_r2_fsi']:.4f})")
else:
    conclusions.append(f"FSI does NOT add significant incremental power beyond VIX (t={results['part_b_regression']['fsi_t_stat']:.2f})")

if fsi_auc_useful:
    conclusions.append(f"FSI has moderate early warning value (AUC={results['part_c']['auc_fsi']:.4f})")
else:
    conclusions.append(f"FSI has limited early warning value (AUC={results['part_c']['auc_fsi']})")

if strategy_improved:
    conclusions.append("FSI overlay improves VT strategy (but check DM significance)")
else:
    conclusions.append("FSI overlay does NOT improve VT strategy")

for i, c in enumerate(conclusions, 1):
    print(f"  {i}. {c}")

# Limitations
limitations = [
    "FSI construction uses equal weights — optimal weighting may differ",
    "Only 4 financial stocks — broader coverage (insurance, banks) may help",
    "VIX already captures much of the same information (global risk)",
    "0050.TW split fix applied — pre-2014 data quality uncertain",
    "No transaction costs in strategy backtest",
    "FSI z-scoring uses lookback that may overfit in-sample",
]

print("\nLimitations:")
for lim in limitations:
    print(f"  - {lim}")

results["conclusions"] = conclusions
results["limitations"] = limitations
results["fsi_granger_significant"] = fsi_granger_sig
results["fsi_incremental_significant"] = fsi_incr_sig
results["strategy_improved"] = strategy_improved
results["timestamp"] = datetime.now(timezone.utc).isoformat()

# ============================================================
# Save Results
# ============================================================
script_dir = os.path.dirname(os.path.abspath(__file__))
output_path = os.path.join(script_dir, 'k887_financial_early_warning_results.json')

with open(output_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"\nResults saved to {output_path}")
print("=" * 70)
print("K887 COMPLETE")
print("=" * 70)
