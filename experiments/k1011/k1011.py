"""
K1011: Financial Stock Early Warning System for Taiwan Market Volatility
=========================================================================
Research Question:
1. Do financial stock volatilities Granger-cause 0050.TW volatility?
2. Which financial stocks have the most predictive power?
3. Can a financial stress indicator improve Taiwan VT strategy signals?

Data Source: yfinance (2012-2026)
References: K757 (Fubon→TSMC Granger F=6.11)

Author: Yi-Hao Lai / VolPred Research System
"""

import numpy as np
import pandas as pd
import yfinance as yf
import json
import warnings
import os
import sys
from datetime import datetime
from scipy import stats
from statsmodels.tsa.stattools import grangercausalitytests, adfuller
from sklearn.decomposition import PCA

# Add project root to path for imports
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(project_root, 'src'))
from volpred.utils import clean_tw50_data

warnings.filterwarnings('ignore')
np.random.seed(42)

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))

# ============================================================
# Step 0: Data Download
# ============================================================
print("=" * 60)
print("K1011: Financial Stock Early Warning System")
print("=" * 60)

tickers = {
    '2881.TW': 'Fubon Financial',
    '2882.TW': 'Cathay Financial',
    '2886.TW': 'Mega Financial',
    '2891.TW': 'CTBC Financial',
    '2330.TW': 'TSMC',
    '0050.TW': 'TW50 ETF',
    '^TWII': 'TWSE Index',
}

print("\nDownloading data (2012-2026)...")
data = {}
for ticker, name in tickers.items():
    try:
        df = yf.download(ticker, start='2012-01-01', end='2026-04-08', progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        data[ticker] = df['Close']
        print(f"  {ticker} ({name}): {len(df)} obs, {df.index[0].date()} to {df.index[-1].date()}")
    except Exception as e:
        print(f"  {ticker} FAILED: {e}")

# Clean 0050.TW
if '0050.TW' in data:
    prices_0050 = data['0050.TW']
    clean_prices, clean_returns = clean_tw50_data(prices_0050)
    data['0050.TW'] = clean_prices
    print(f"\n0050.TW cleaned: {len(clean_prices)} obs")

# ============================================================
# Step 1: Compute Returns and Realized Volatility
# ============================================================
print("\n" + "=" * 60)
print("Step 1: Computing Returns & RV")
print("=" * 60)

returns = {}
rv20 = {}  # 20-day realized volatility (annualized std)

for ticker in data:
    r = data[ticker].pct_change().dropna()
    # Remove extreme outliers (> 30% daily) which are likely data errors
    r = r[r.abs() < 0.30]
    returns[ticker] = r
    # 20-day rolling RV (annualized)
    rv20[ticker] = r.rolling(20).std() * np.sqrt(252)

# Create aligned DataFrame
rv_df = pd.DataFrame(rv20).dropna()
ret_df = pd.DataFrame(returns).dropna()

print(f"\nAligned RV data: {len(rv_df)} obs, {rv_df.index[0].date()} to {rv_df.index[-1].date()}")
print(f"\nDescriptive Statistics (20d RV, annualized):")
desc = rv_df.describe()
for ticker in rv_df.columns:
    name = tickers.get(ticker, ticker)
    print(f"  {name:20s}: mean={rv_df[ticker].mean():.4f}, std={rv_df[ticker].std():.4f}, "
          f"skew={rv_df[ticker].skew():.2f}, kurt={rv_df[ticker].kurtosis():.2f}")

# ============================================================
# Step 2: Stationarity Tests (ADF)
# ============================================================
print("\n" + "=" * 60)
print("Step 2: ADF Stationarity Tests on RV")
print("=" * 60)

adf_results = {}
for ticker in rv_df.columns:
    adf_stat, adf_pval, *_ = adfuller(rv_df[ticker].dropna(), maxlag=22)
    adf_results[ticker] = {'stat': adf_stat, 'pval': adf_pval}
    name = tickers.get(ticker, ticker)
    status = "STATIONARY" if adf_pval < 0.01 else "NON-STATIONARY"
    print(f"  {name:20s}: ADF={adf_stat:.3f}, p={adf_pval:.4f} [{status}]")

# ============================================================
# Step 3: Granger Causality Tests
# ============================================================
print("\n" + "=" * 60)
print("Step 3: Granger Causality Tests")
print("=" * 60)

financial_tickers = ['2881.TW', '2882.TW', '2886.TW', '2891.TW']
target_tickers = ['0050.TW', '^TWII', '2330.TW']
lags_to_test = [1, 5, 10, 22]

granger_results = {}

for fin_tick in financial_tickers:
    fin_name = tickers[fin_tick]
    for tgt_tick in target_tickers:
        tgt_name = tickers[tgt_tick]
        key = f"{fin_tick}->{tgt_tick}"
        granger_results[key] = {}

        # Align data
        pair_df = rv_df[[tgt_tick, fin_tick]].dropna()
        if len(pair_df) < 100:
            print(f"  {key}: insufficient data ({len(pair_df)} obs)")
            continue

        print(f"\n  {fin_name} -> {tgt_name} (n={len(pair_df)}):")

        for lag in lags_to_test:
            try:
                # statsmodels grangercausalitytests: column 0 = target (y), column 1 = cause (x)
                result = grangercausalitytests(pair_df[[tgt_tick, fin_tick]], maxlag=lag, verbose=False)
                # Get F-test result for this specific lag
                f_stat = result[lag][0]['ssr_ftest'][0]
                f_pval = result[lag][0]['ssr_ftest'][1]
                granger_results[key][f"lag_{lag}"] = {
                    'F': round(f_stat, 3),
                    'p': round(f_pval, 6)
                }
                sig = "***" if f_pval < 0.001 else "**" if f_pval < 0.01 else "*" if f_pval < 0.05 else ""
                print(f"    lag={lag:2d}: F={f_stat:7.3f}, p={f_pval:.6f} {sig}")
            except Exception as e:
                print(f"    lag={lag:2d}: ERROR - {e}")

# ============================================================
# Step 4: Build Financial Stress Index
# ============================================================
print("\n" + "=" * 60)
print("Step 4: Financial Stress Index Construction")
print("=" * 60)

fin_rv = rv_df[financial_tickers].dropna()

# Method 1: Equal-weighted z-score
fin_zscores = (fin_rv - fin_rv.mean()) / fin_rv.std()
fin_stress_eq = fin_zscores.mean(axis=1)
fin_stress_eq.name = 'FIN_STRESS_EQ'

# Method 2: PCA first component
pca = PCA(n_components=1)
pca_scores = pca.fit_transform(fin_zscores)
fin_stress_pca = pd.Series(pca_scores.flatten(), index=fin_rv.index, name='FIN_STRESS_PCA')
pca_explained = pca.explained_variance_ratio_[0]

print(f"Equal-weighted stress: mean={fin_stress_eq.mean():.4f}, std={fin_stress_eq.std():.4f}")
print(f"PCA stress (PC1 explains {pca_explained:.1%}): mean={fin_stress_pca.mean():.4f}, std={fin_stress_pca.std():.4f}")
print(f"Correlation(EQ, PCA): {fin_stress_eq.corr(fin_stress_pca):.4f}")

# ============================================================
# Step 5: Granger Causality of Stress Index on Targets
# ============================================================
print("\n" + "=" * 60)
print("Step 5: Stress Index -> Target RV Granger Tests")
print("=" * 60)

stress_granger = {}
for stress_name, stress_series in [('EQ', fin_stress_eq), ('PCA', fin_stress_pca)]:
    for tgt_tick in target_tickers:
        tgt_name = tickers[tgt_tick]
        key = f"STRESS_{stress_name}->{tgt_tick}"

        pair_df = pd.DataFrame({
            'target': rv_df[tgt_tick],
            'stress': stress_series
        }).dropna()

        if len(pair_df) < 100:
            continue

        print(f"\n  FIN_STRESS_{stress_name} -> {tgt_name} (n={len(pair_df)}):")
        stress_granger[key] = {}

        for lag in lags_to_test:
            try:
                result = grangercausalitytests(pair_df[['target', 'stress']], maxlag=lag, verbose=False)
                f_stat = result[lag][0]['ssr_ftest'][0]
                f_pval = result[lag][0]['ssr_ftest'][1]
                stress_granger[key][f"lag_{lag}"] = {
                    'F': round(f_stat, 3),
                    'p': round(f_pval, 6)
                }
                sig = "***" if f_pval < 0.001 else "**" if f_pval < 0.01 else "*" if f_pval < 0.05 else ""
                print(f"    lag={lag:2d}: F={f_stat:7.3f}, p={f_pval:.6f} {sig}")
            except Exception as e:
                print(f"    lag={lag:2d}: ERROR - {e}")

# ============================================================
# Step 6: Volatility Prediction (OLS-based, HAR-style)
# ============================================================
print("\n" + "=" * 60)
print("Step 6: Volatility Prediction with Stress Index")
print("=" * 60)

# We test whether adding FIN_STRESS improves RV prediction for 0050.TW
# Using HAR-style regression: RV_t = a + b*RV_{t-1} + c*RV_{t-5} + d*RV_{t-22} + e*STRESS_{t-1} + eps_t
# Target: r² (squared return) of 0050.TW aligned to RV frequency

from statsmodels.regression.linear_model import OLS
from statsmodels.tools import add_constant

# Build features
target_rv = rv_df['0050.TW'].copy()
target_r2 = (returns.get('0050.TW', pd.Series()) ** 2)  # squared return as proxy

# Use RV as both feature and target for simplicity (HAR-RV style)
features = pd.DataFrame({
    'rv_lag1': target_rv.shift(1),
    'rv_lag5': target_rv.shift(5),
    'rv_lag22': target_rv.shift(22),
    'stress_eq_lag1': fin_stress_eq.shift(1),
    'stress_pca_lag1': fin_stress_pca.shift(1),
}, index=target_rv.index)

target = target_rv  # Predict RV itself

# Align
model_df = pd.concat([target.rename('target'), features], axis=1).dropna()

# Train/Test split (last 2 years OOS)
split_date = model_df.index[-504] if len(model_df) > 504 else model_df.index[int(len(model_df)*0.7)]
train = model_df.loc[:split_date]
test = model_df.loc[split_date:]
# Make sure test doesn't overlap with train
test = test.iloc[1:]

print(f"Train: {train.index[0].date()} to {train.index[-1].date()} (n={len(train)})")
print(f"Test:  {test.index[0].date()} to {test.index[-1].date()} (n={len(test)})")

# Model 1: Baseline HAR
har_cols = ['rv_lag1', 'rv_lag5', 'rv_lag22']
X_train_base = add_constant(train[har_cols])
X_test_base = add_constant(test[har_cols])
y_train = train['target']
y_test = test['target']

model_base = OLS(y_train, X_train_base).fit()
pred_base_is = model_base.predict(X_train_base)
pred_base_oos = model_base.predict(X_test_base)

# Model 2: HAR + Stress (EQ)
stress_eq_cols = har_cols + ['stress_eq_lag1']
X_train_eq = add_constant(train[stress_eq_cols])
X_test_eq = add_constant(test[stress_eq_cols])

model_eq = OLS(y_train, X_train_eq).fit()
pred_eq_is = model_eq.predict(X_train_eq)
pred_eq_oos = model_eq.predict(X_test_eq)

# Model 3: HAR + Stress (PCA)
stress_pca_cols = har_cols + ['stress_pca_lag1']
X_train_pca = add_constant(train[stress_pca_cols])
X_test_pca = add_constant(test[stress_pca_cols])

model_pca = OLS(y_train, X_train_pca).fit()
pred_pca_is = model_pca.predict(X_train_pca)
pred_pca_oos = model_pca.predict(X_test_pca)

# QLIKE loss function (proxy-robust)
def qlike(actual, predicted):
    """QLIKE loss: mean(actual/predicted + log(predicted))"""
    # Use actual RV as proxy
    ratio = actual / predicted
    # Clip to avoid log(0)
    predicted_clipped = np.maximum(predicted, 1e-10)
    loss = ratio + np.log(predicted_clipped)
    return loss.mean()

# MSE
def mse(actual, predicted):
    return ((actual - predicted) ** 2).mean()

# R² OOS
def r2_oos(actual, predicted):
    ss_res = ((actual - predicted) ** 2).sum()
    ss_tot = ((actual - actual.mean()) ** 2).sum()
    return 1 - ss_res / ss_tot

print("\n--- In-Sample Results ---")
print(f"  Baseline HAR:  R²={model_base.rsquared:.4f}, AIC={model_base.aic:.1f}")
print(f"  HAR + EQ:      R²={model_eq.rsquared:.4f}, AIC={model_eq.aic:.1f}")
print(f"  HAR + PCA:     R²={model_pca.rsquared:.4f}, AIC={model_pca.aic:.1f}")

print(f"\n  Stress coefficient (EQ):  {model_eq.params['stress_eq_lag1']:.6f}, "
      f"t={model_eq.tvalues['stress_eq_lag1']:.3f}, p={model_eq.pvalues['stress_eq_lag1']:.4f}")
print(f"  Stress coefficient (PCA): {model_pca.params['stress_pca_lag1']:.6f}, "
      f"t={model_pca.tvalues['stress_pca_lag1']:.3f}, p={model_pca.pvalues['stress_pca_lag1']:.4f}")

print("\n--- Out-of-Sample Results ---")
metrics_oos = {}
for name, pred in [('Baseline', pred_base_oos), ('HAR+EQ', pred_eq_oos), ('HAR+PCA', pred_pca_oos)]:
    q = qlike(y_test, pred)
    m = mse(y_test, pred)
    r2 = r2_oos(y_test, pred)
    metrics_oos[name] = {'QLIKE': q, 'MSE': m, 'R2_OOS': r2}
    print(f"  {name:12s}: QLIKE={q:.6f}, MSE={m:.8f}, R²_OOS={r2:.4f}")

# ============================================================
# Step 7: DM Test (Diebold-Mariano)
# ============================================================
print("\n" + "=" * 60)
print("Step 7: Diebold-Mariano Tests")
print("=" * 60)

def dm_test(e1, e2, h=1):
    """Diebold-Mariano test for equal predictive accuracy.
    e1, e2: forecast errors (or loss differentials)
    Returns: DM statistic, p-value
    """
    d = e1 - e2
    n = len(d)
    d_mean = d.mean()
    # Newey-West variance with h-1 lags
    gamma_0 = np.var(d, ddof=1)
    if h > 1:
        for k in range(1, h):
            gamma_k = np.cov(d[k:], d[:-k])[0, 1]
            gamma_0 += 2 * gamma_k
    se = np.sqrt(gamma_0 / n)
    if se < 1e-15:
        return 0.0, 1.0
    dm_stat = d_mean / se
    p_val = 2 * (1 - stats.norm.cdf(abs(dm_stat)))
    return dm_stat, p_val

# QLIKE losses
loss_base = y_test / pred_base_oos + np.log(np.maximum(pred_base_oos, 1e-10))
loss_eq = y_test / pred_eq_oos + np.log(np.maximum(pred_eq_oos, 1e-10))
loss_pca = y_test / pred_pca_oos + np.log(np.maximum(pred_pca_oos, 1e-10))

dm_results = {}
for name, loss_alt in [('EQ', loss_eq), ('PCA', loss_pca)]:
    dm_stat, dm_pval = dm_test(loss_base, loss_alt)
    dm_results[name] = {'DM': round(dm_stat, 3), 'p': round(dm_pval, 6)}
    sig = "SIGNIFICANT (t>3.0)" if abs(dm_stat) > 3.0 else "NOT significant"
    print(f"  Baseline vs HAR+{name}: DM={dm_stat:.3f}, p={dm_pval:.6f} [{sig}]")

# ============================================================
# Step 8: Rolling Correlation Analysis
# ============================================================
print("\n" + "=" * 60)
print("Step 8: Rolling Correlation (FIN_STRESS vs 0050.TW RV)")
print("=" * 60)

rolling_corr_eq = fin_stress_eq.rolling(252).corr(rv_df['0050.TW'])
rolling_corr_pca = fin_stress_pca.rolling(252).corr(rv_df['0050.TW'])

print(f"  EQ stress-0050 RV corr:  mean={rolling_corr_eq.mean():.4f}, std={rolling_corr_eq.std():.4f}")
print(f"  PCA stress-0050 RV corr: mean={rolling_corr_pca.mean():.4f}, std={rolling_corr_pca.std():.4f}")

# Unconditional correlation
uc_eq = fin_stress_eq.corr(rv_df['0050.TW'])
uc_pca = fin_stress_pca.corr(rv_df['0050.TW'])
print(f"\n  Unconditional corr (EQ):  {uc_eq:.4f}")
print(f"  Unconditional corr (PCA): {uc_pca:.4f}")

# ============================================================
# Step 9: VT Strategy Test (if stress index is useful)
# ============================================================
print("\n" + "=" * 60)
print("Step 9: VT Strategy with Financial Stress Signal")
print("=" * 60)

# Strategy: reduce 0050.TW weight when FIN_STRESS > threshold
# Base weight = 100% 0050.TW, reduce to 50% when stress > 1.5σ, 0% when > 2σ
ret_0050 = returns['0050.TW']

# Align stress with returns
strat_df = pd.DataFrame({
    'ret': ret_0050,
    'stress_eq': fin_stress_eq,
    'stress_pca': fin_stress_pca,
}).dropna()

# Signal lagged by 1 day (CRITICAL: avoid lookahead)
signal_eq = strat_df['stress_eq'].shift(1)  # signal.shift(1)
signal_pca = strat_df['stress_pca'].shift(1)  # signal.shift(1)

# Weight function
def compute_weight(signal, low_thresh=1.0, high_thresh=2.0):
    """Weight: 1.0 if stress < low, 0.5 if low < stress < high, 0.0 if > high"""
    weight = pd.Series(1.0, index=signal.index)
    weight[signal > low_thresh] = 0.5
    weight[signal > high_thresh] = 0.0
    return weight

weight_eq = compute_weight(signal_eq)
weight_pca = compute_weight(signal_pca)

# Portfolio returns (weight * 0050 + (1-weight) * 0 = weight * 0050)
strat_ret_eq = weight_eq * strat_df['ret']
strat_ret_pca = weight_pca * strat_df['ret']
bh_ret = strat_df['ret']

# Remove NaN from shift
strat_ret_eq = strat_ret_eq.dropna()
strat_ret_pca = strat_ret_pca.dropna()
bh_ret = bh_ret.loc[strat_ret_eq.index]

def calc_metrics(r, name):
    ann_ret = r.mean() * 252
    ann_vol = r.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    cum = (1 + r).cumprod()
    mdd = (cum / cum.cummax() - 1).min()
    return {
        'name': name,
        'ann_return': round(ann_ret, 4),
        'ann_vol': round(ann_vol, 4),
        'sharpe': round(sharpe, 4),
        'mdd': round(mdd, 4),
        'n_obs': len(r)
    }

metrics_bh = calc_metrics(bh_ret, 'BH 0050.TW')
metrics_strat_eq = calc_metrics(strat_ret_eq, 'FIN_STRESS_EQ VT')
metrics_strat_pca = calc_metrics(strat_ret_pca, 'FIN_STRESS_PCA VT')

print(f"\n{'Strategy':25s} {'Return':>8s} {'Vol':>8s} {'Sharpe':>8s} {'MDD':>8s} {'N':>6s}")
print("-" * 65)
for m in [metrics_bh, metrics_strat_eq, metrics_strat_pca]:
    print(f"  {m['name']:23s} {m['ann_return']:8.4f} {m['ann_vol']:8.4f} {m['sharpe']:8.4f} {m['mdd']:8.4f} {m['n_obs']:6d}")

# Check: Sharpe > 2x baseline?
if metrics_strat_eq['sharpe'] > 2 * metrics_bh['sharpe']:
    print("\n  ⚠️ WARNING: EQ strategy Sharpe > 2x BH — potential bug!")
if metrics_strat_pca['sharpe'] > 2 * metrics_bh['sharpe']:
    print("\n  ⚠️ WARNING: PCA strategy Sharpe > 2x BH — potential bug!")

# Signal statistics
print(f"\n  EQ signal: {(weight_eq < 1.0).mean():.1%} reduced, {(weight_eq == 0.0).mean():.1%} fully hedged")
print(f"  PCA signal: {(weight_pca < 1.0).mean():.1%} reduced, {(weight_pca == 0.0).mean():.1%} fully hedged")

# ============================================================
# Step 10: Sub-period Robustness
# ============================================================
print("\n" + "=" * 60)
print("Step 10: Sub-period Robustness (Granger)")
print("=" * 60)

# Test Granger in different regimes
periods = [
    ('2012-2016', '2012-01-01', '2016-12-31'),
    ('2017-2020', '2017-01-01', '2020-12-31'),
    ('2021-2026', '2021-01-01', '2026-12-31'),
]

subperiod_results = {}
best_fin_ticker = None
best_f_total = 0

for fin_tick in financial_tickers:
    f_total = 0
    for period_name, start, end in periods:
        sub = rv_df.loc[start:end, ['0050.TW', fin_tick]].dropna()
        if len(sub) < 50:
            continue
        try:
            result = grangercausalitytests(sub[['0050.TW', fin_tick]], maxlag=5, verbose=False)
            f_stat = result[5][0]['ssr_ftest'][0]
            f_pval = result[5][0]['ssr_ftest'][1]
            key = f"{fin_tick}_{period_name}"
            subperiod_results[key] = {'F': round(f_stat, 3), 'p': round(f_pval, 6)}
            sig = "***" if f_pval < 0.001 else "**" if f_pval < 0.01 else "*" if f_pval < 0.05 else ""
            print(f"  {tickers[fin_tick]:20s} [{period_name}]: F={f_stat:.3f}, p={f_pval:.6f} {sig} (n={len(sub)})")
            f_total += f_stat
        except:
            pass
    if f_total > best_f_total:
        best_f_total = f_total
        best_fin_ticker = fin_tick

print(f"\n  Most consistent predictor: {tickers.get(best_fin_ticker, 'N/A')} ({best_fin_ticker})")

# ============================================================
# Step 11: Compile Results
# ============================================================
print("\n" + "=" * 60)
print("Compiling Results")
print("=" * 60)

# Count significant Granger results
sig_count = 0
total_tests = 0
for key, lags in granger_results.items():
    for lag_key, vals in lags.items():
        total_tests += 1
        if vals['p'] < 0.01:
            sig_count += 1

print(f"\nGranger tests: {sig_count}/{total_tests} significant at p<0.01")

# Summary of key findings
sig_0050 = 0
for fin_tick in financial_tickers:
    key = f"{fin_tick}->0050.TW"
    if key in granger_results:
        for lag_key, vals in granger_results[key].items():
            if vals['p'] < 0.01:
                sig_0050 += 1

print(f"Financial -> 0050.TW: {sig_0050} significant at p<0.01")

results = {
    'experiment_id': 'K1011',
    'title': 'Financial Stock Early Warning System for Taiwan Market Volatility',
    'timestamp': datetime.now().isoformat(),
    'data_source': 'yfinance',
    'period': '2012-2026',
    'sample_size': len(rv_df),
    'methodology': {
        'financial_stocks': ['2881.TW (Fubon)', '2882.TW (Cathay)', '2886.TW (Mega)', '2891.TW (CTBC)'],
        'targets': ['0050.TW', '^TWII', '2330.TW'],
        'volatility_measure': '20d rolling std (annualized)',
        'stress_index': 'Equal-weighted z-score of 4 financial stock RVs + PCA',
        'prediction_model': 'HAR-style OLS (RV lags 1,5,22 + stress)',
        'strategy': 'Reduce 0050.TW weight when stress > 1σ (to 50%) or > 2σ (to 0%)',
        'lag_applied': 'signal.shift(1) for all signals',
        'seed': 42,
    },
    'stationarity': {k: {'ADF': v['stat'], 'p': v['pval'], 'stationary': v['pval'] < 0.01}
                     for k, v in adf_results.items()},
    'granger_causality': {
        'individual': granger_results,
        'stress_index': stress_granger,
        'significant_at_001': sig_count,
        'total_tests': total_tests,
        'financial_to_0050': sig_0050,
    },
    'stress_index': {
        'pca_explained_variance': round(pca_explained, 4),
        'eq_pca_correlation': round(fin_stress_eq.corr(fin_stress_pca), 4),
        'unconditional_corr_eq_0050rv': round(uc_eq, 4),
        'unconditional_corr_pca_0050rv': round(uc_pca, 4),
    },
    'volatility_prediction': {
        'in_sample': {
            'baseline_R2': round(model_base.rsquared, 4),
            'har_eq_R2': round(model_eq.rsquared, 4),
            'har_pca_R2': round(model_pca.rsquared, 4),
            'stress_eq_coef': round(float(model_eq.params['stress_eq_lag1']), 6),
            'stress_eq_tstat': round(float(model_eq.tvalues['stress_eq_lag1']), 3),
            'stress_eq_pval': round(float(model_eq.pvalues['stress_eq_lag1']), 4),
            'stress_pca_coef': round(float(model_pca.params['stress_pca_lag1']), 6),
            'stress_pca_tstat': round(float(model_pca.tvalues['stress_pca_lag1']), 3),
            'stress_pca_pval': round(float(model_pca.pvalues['stress_pca_lag1']), 4),
        },
        'out_of_sample': metrics_oos,
        'dm_test': dm_results,
        'train_period': f"{train.index[0].date()} to {train.index[-1].date()}",
        'test_period': f"{test.index[0].date()} to {test.index[-1].date()}",
    },
    'strategy_performance': {
        'buy_hold': metrics_bh,
        'fin_stress_eq': metrics_strat_eq,
        'fin_stress_pca': metrics_strat_pca,
    },
    'sub_period_robustness': subperiod_results,
    'best_predictor': {
        'ticker': best_fin_ticker,
        'name': tickers.get(best_fin_ticker, 'N/A'),
    },
    'conclusions': [],  # filled below
}

# Determine conclusions
conclusions = []

# 1. Granger causality
if sig_0050 >= 8:  # 4 stocks * 4 lags = 16 tests, 8 = half
    conclusions.append("Strong evidence: Financial stock volatility Granger-causes 0050.TW volatility")
elif sig_0050 >= 4:
    conclusions.append("Moderate evidence: Some financial stocks Granger-cause 0050.TW volatility")
elif sig_0050 > 0:
    conclusions.append("Weak evidence: Limited Granger causality from financial stocks to 0050.TW")
else:
    conclusions.append("NULL: No significant Granger causality from financial stocks to 0050.TW volatility")

# 2. Prediction improvement
for name in ['EQ', 'PCA']:
    if name in dm_results and abs(dm_results[name]['DM']) > 3.0:
        conclusions.append(f"FIN_STRESS_{name} significantly improves vol prediction (DM |t|>{abs(dm_results[name]['DM']):.1f} > 3.0)")
    else:
        dm_val = dm_results.get(name, {}).get('DM', 0)
        conclusions.append(f"FIN_STRESS_{name} does NOT significantly improve vol prediction (DM |t|={abs(dm_val):.1f} < 3.0)")

# 3. Strategy
if metrics_strat_eq['sharpe'] > metrics_bh['sharpe'] * 1.1:
    conclusions.append(f"EQ stress VT strategy outperforms BH (Sharpe {metrics_strat_eq['sharpe']:.3f} vs {metrics_bh['sharpe']:.3f})")
else:
    conclusions.append(f"EQ stress VT strategy does not meaningfully outperform BH")

results['conclusions'] = conclusions

# Save results
results_path = os.path.join(OUTPUT_DIR, 'k1011_results.json')
with open(results_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"\nResults saved to {results_path}")

# ============================================================
# Step 12: Visualization
# ============================================================
print("\n" + "=" * 60)
print("Step 12: Generating Charts")
print("=" * 60)

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

fig, axes = plt.subplots(3, 1, figsize=(14, 12))

# Chart 1: Financial Stress Index vs 0050.TW RV
ax1 = axes[0]
ax1.plot(fin_stress_eq.index, fin_stress_eq, label='FIN_STRESS (Equal-Weight)', alpha=0.7, linewidth=0.8)
ax1.axhline(y=1.0, color='orange', linestyle='--', alpha=0.5, label='1σ threshold')
ax1.axhline(y=2.0, color='red', linestyle='--', alpha=0.5, label='2σ threshold')
ax1_twin = ax1.twinx()
ax1_twin.plot(rv_df.index, rv_df['0050.TW'], color='green', alpha=0.5, linewidth=0.8, label='0050.TW RV (20d)')
ax1.set_title('Financial Stress Index vs 0050.TW Realized Volatility', fontsize=12)
ax1.set_ylabel('Stress Z-score')
ax1_twin.set_ylabel('RV (annualized)')
ax1.legend(loc='upper left')
ax1_twin.legend(loc='upper right')
ax1.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))

# Chart 2: Individual Financial Stock RV
ax2 = axes[1]
for tick in financial_tickers:
    ax2.plot(rv_df.index, rv_df[tick], label=tickers[tick], alpha=0.7, linewidth=0.8)
ax2.plot(rv_df.index, rv_df['0050.TW'], label='0050.TW', color='black', linewidth=1.2)
ax2.set_title('Financial Stock vs 0050.TW Realized Volatility (20d)', fontsize=12)
ax2.set_ylabel('RV (annualized)')
ax2.legend(fontsize=8)
ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))

# Chart 3: Strategy Cumulative Returns
ax3 = axes[2]
cum_bh = (1 + bh_ret).cumprod()
cum_eq = (1 + strat_ret_eq).cumprod()
cum_pca = (1 + strat_ret_pca).cumprod()
ax3.plot(cum_bh.index, cum_bh, label=f'BH 0050.TW (SR={metrics_bh["sharpe"]:.3f})', linewidth=1.2)
ax3.plot(cum_eq.index, cum_eq, label=f'FIN_STRESS EQ VT (SR={metrics_strat_eq["sharpe"]:.3f})', linewidth=1.2)
ax3.plot(cum_pca.index, cum_pca, label=f'FIN_STRESS PCA VT (SR={metrics_strat_pca["sharpe"]:.3f})', linewidth=1.2)
ax3.set_title('Cumulative Returns: BH vs Financial Stress VT Strategy', fontsize=12)
ax3.set_ylabel('Cumulative Return')
ax3.legend()
ax3.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))

plt.tight_layout()
chart_path = os.path.join(OUTPUT_DIR, 'k1011_charts.png')
plt.savefig(chart_path, dpi=150)
plt.close()
print(f"Charts saved to {chart_path}")

# Granger heatmap
fig2, ax = plt.subplots(figsize=(10, 6))
# Build matrix: rows = financial stocks, cols = lags, values = -log10(p)
heatmap_data = []
row_labels = []
col_labels = [f'lag_{l}' for l in lags_to_test]
for fin_tick in financial_tickers:
    key = f"{fin_tick}->0050.TW"
    row = []
    for lag in lags_to_test:
        lag_key = f"lag_{lag}"
        if key in granger_results and lag_key in granger_results[key]:
            p = granger_results[key][lag_key]['p']
            row.append(-np.log10(max(p, 1e-10)))
        else:
            row.append(0)
    heatmap_data.append(row)
    row_labels.append(tickers[fin_tick])

hm = np.array(heatmap_data)
im = ax.imshow(hm, cmap='YlOrRd', aspect='auto')
ax.set_xticks(range(len(col_labels)))
ax.set_xticklabels([f'Lag {l}' for l in lags_to_test])
ax.set_yticks(range(len(row_labels)))
ax.set_yticklabels(row_labels)
ax.set_title('Granger Causality: Financial Stock → 0050.TW\n(-log10 p-value, higher = more significant)')
plt.colorbar(im, label='-log10(p)')

# Add text annotations
for i in range(len(row_labels)):
    for j in range(len(col_labels)):
        key = f"{financial_tickers[i]}->0050.TW"
        lag_key = col_labels[j]
        if key in granger_results and lag_key in granger_results[key]:
            p = granger_results[key][lag_key]['p']
            f_val = granger_results[key][lag_key]['F']
            color = 'white' if hm[i, j] > 2 else 'black'
            ax.text(j, i, f'F={f_val:.1f}\np={p:.3f}', ha='center', va='center', fontsize=8, color=color)

plt.tight_layout()
heatmap_path = os.path.join(OUTPUT_DIR, 'k1011_granger_heatmap.png')
plt.savefig(heatmap_path, dpi=150)
plt.close()
print(f"Heatmap saved to {heatmap_path}")

# ============================================================
# Final Summary
# ============================================================
print("\n" + "=" * 60)
print("K1011 FINAL SUMMARY")
print("=" * 60)
for c in conclusions:
    print(f"  • {c}")
print("\nDone.")
