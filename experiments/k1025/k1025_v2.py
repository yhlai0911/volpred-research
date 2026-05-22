"""
K1025: Crypto Fear Channel — BTC Vol Spillover to Equity
=========================================================

Purpose: Deep analysis of BTC volatility spillover to equity markets for Paper 6.
Building on K639 (BTC→SPY Granger) and K746b (BTC vol asymmetrically Granger-causes VIX).

Methods:
1. Granger causality: BTC realized vol (20d) → VIX, bidirectional
2. Asymmetric test: BTC up-moves vs down-moves Granger tests
3. Quantile regression: tail dependence at τ = 0.05, 0.25, 0.50, 0.75, 0.95
4. Rolling Diebold-Yilmaz spillover index (252d)
5. DCC correlation: BTC-SPY dynamic conditional correlation by VIX regime
6. Forecasting test: BTC vol added to AR(VIX) model, DM test

Data: SPY, BTC-USD, ^VIX from yfinance, 2015-01-01 to 2026-04-08 (pinned)
References: Diebold & Yilmaz (2012), Engle (2002), Koenker & Bassett (1978)

Author: VolPred Research System
Seed: 42
"""

import numpy as np
import pandas as pd
import yfinance as yf
import json
import os
import random
import warnings
from datetime import datetime, timezone

warnings.filterwarnings('ignore')
random.seed(42)
np.random.seed(42)
from statsmodels.tsa.vector_ar.var_model import VAR

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_FILE = os.path.join(SCRIPT_DIR, 'k1025_v2_results.json')

# ============================================================
# 1. DATA COLLECTION
# ============================================================
print("=" * 60)
print("K1025: Crypto Fear Channel — BTC Vol Spillover to Equity")
print("=" * 60)

print("\n[1/7] Downloading data from yfinance...")
start_date = '2015-01-01'
end_date = '2026-04-09'  # yfinance end is exclusive; data through 2026-04-08 per paper

spy = yf.download('SPY', start=start_date, end=end_date, progress=False, auto_adjust=True)
btc = yf.download('BTC-USD', start=start_date, end=end_date, progress=False, auto_adjust=True)
vix = yf.download('^VIX', start=start_date, end=end_date, progress=False, auto_adjust=True)

# Flatten multi-level columns if needed
for df in [spy, btc, vix]:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

# Calculate returns
spy_ret = spy['Close'].pct_change().dropna()
btc_ret = np.log(btc['Close'] / btc['Close'].shift(1)).dropna()
vix_level = vix['Close'].dropna()

# Align all series on common dates
common_idx = spy_ret.index.intersection(btc_ret.index).intersection(vix_level.index)
spy_ret = spy_ret.loc[common_idx]
btc_ret = btc_ret.loc[common_idx]
vix_level = vix_level.loc[common_idx]

# BTC realized volatility (20-day rolling std of returns, annualized)
btc_rv20 = btc_ret.rolling(20).std() * np.sqrt(252)
btc_rv20 = btc_rv20.dropna()

# SPY realized volatility (20-day)
spy_rv20 = spy_ret.rolling(20).std() * np.sqrt(252)
spy_rv20 = spy_rv20.dropna()

# Re-align after rolling
common_idx2 = btc_rv20.index.intersection(spy_rv20.index).intersection(vix_level.index)
btc_rv20 = btc_rv20.loc[common_idx2]
spy_rv20 = spy_rv20.loc[common_idx2]
vix_level_aligned = vix_level.loc[common_idx2]
spy_ret_aligned = spy_ret.loc[common_idx2]
btc_ret_aligned = btc_ret.loc[common_idx2]

print(f"  Sample period: {common_idx2[0].strftime('%Y-%m-%d')} to {common_idx2[-1].strftime('%Y-%m-%d')}")
print(f"  Total observations: {len(common_idx2)}")

# Descriptive statistics
desc_stats = {
    'btc_ret': {
        'mean': float(btc_ret_aligned.mean()),
        'std': float(btc_ret_aligned.std()),
        'skew': float(btc_ret_aligned.skew()),
        'kurtosis': float(btc_ret_aligned.kurtosis()),
    },
    'spy_ret': {
        'mean': float(spy_ret_aligned.mean()),
        'std': float(spy_ret_aligned.std()),
        'skew': float(spy_ret_aligned.skew()),
        'kurtosis': float(spy_ret_aligned.kurtosis()),
    },
    'vix': {
        'mean': float(vix_level_aligned.mean()),
        'std': float(vix_level_aligned.std()),
        'min': float(vix_level_aligned.min()),
        'max': float(vix_level_aligned.max()),
    },
    'btc_rv20': {
        'mean': float(btc_rv20.mean()),
        'std': float(btc_rv20.std()),
        'min': float(btc_rv20.min()),
        'max': float(btc_rv20.max()),
    },
}

print(f"\n  Descriptive Statistics:")
print(f"  BTC return: mean={desc_stats['btc_ret']['mean']:.6f}, std={desc_stats['btc_ret']['std']:.4f}, skew={desc_stats['btc_ret']['skew']:.2f}, kurt={desc_stats['btc_ret']['kurtosis']:.2f}")
print(f"  SPY return: mean={desc_stats['spy_ret']['mean']:.6f}, std={desc_stats['spy_ret']['std']:.4f}, skew={desc_stats['spy_ret']['skew']:.2f}, kurt={desc_stats['spy_ret']['kurtosis']:.2f}")
print(f"  VIX: mean={desc_stats['vix']['mean']:.2f}, std={desc_stats['vix']['std']:.2f}")
print(f"  BTC RV(20): mean={desc_stats['btc_rv20']['mean']:.4f}, std={desc_stats['btc_rv20']['std']:.4f}")

# ============================================================
# 2. GRANGER CAUSALITY (corrected version)
# ============================================================
print("\n[2/7] Granger Causality Tests...")
from statsmodels.tsa.stattools import grangercausalitytests, adfuller

# Check stationarity
def adf_test(series, name):
    result = adfuller(series.dropna(), maxlag=20, autolag='AIC')
    return {
        'name': name,
        'adf_stat': float(result[0]),
        'p_value': float(result[1]),
        'lags': int(result[2]),
        'stationary': result[1] < 0.05
    }

adf_btc_rv = adf_test(btc_rv20, 'BTC_RV20')
adf_vix = adf_test(vix_level_aligned, 'VIX')
adf_spy_rv = adf_test(spy_rv20, 'SPY_RV20')

print(f"  ADF Tests:")
print(f"    BTC_RV20: stat={adf_btc_rv['adf_stat']:.4f}, p={adf_btc_rv['p_value']:.4f}, stationary={adf_btc_rv['stationary']}")
print(f"    VIX:      stat={adf_vix['adf_stat']:.4f}, p={adf_vix['p_value']:.4f}, stationary={adf_vix['stationary']}")
print(f"    SPY_RV20: stat={adf_spy_rv['adf_stat']:.4f}, p={adf_spy_rv['p_value']:.4f}, stationary={adf_spy_rv['stationary']}")

# If not stationary, use first differences
btc_rv20_d = btc_rv20.diff().dropna() if not adf_btc_rv['stationary'] else btc_rv20
vix_d = vix_level_aligned.diff().dropna() if not adf_vix['stationary'] else vix_level_aligned
spy_rv20_d = spy_rv20.diff().dropna() if not adf_spy_rv['stationary'] else spy_rv20

# Re-align after differencing
common_d = btc_rv20_d.index.intersection(vix_d.index).intersection(spy_rv20_d.index)
btc_rv20_d = btc_rv20_d.loc[common_d]
vix_d = vix_d.loc[common_d]
spy_rv20_d = spy_rv20_d.loc[common_d]

# Granger tests with multiple lags
max_lag = 10
granger_results = {}

# BTC_RV → VIX
print(f"\n  Granger: BTC_RV(20) → VIX (max_lag={max_lag})")
data_gc1 = pd.DataFrame({'VIX': vix_d, 'BTC_RV': btc_rv20_d}).dropna()
try:
    gc1 = grangercausalitytests(data_gc1[['VIX', 'BTC_RV']], maxlag=max_lag, verbose=False)
    btc_to_vix = {}
    for lag in range(1, max_lag + 1):
        f_stat = gc1[lag][0]['ssr_ftest'][0]
        p_val = gc1[lag][0]['ssr_ftest'][1]
        btc_to_vix[str(lag)] = {'F': float(f_stat), 'p': float(p_val)}
        if lag <= 5:
            sig = "***" if p_val < 0.01 else "**" if p_val < 0.05 else "*" if p_val < 0.10 else ""
            print(f"    lag={lag}: F={f_stat:.4f}, p={p_val:.4f} {sig}")
    granger_results['btc_rv_to_vix'] = btc_to_vix
except Exception as e:
    print(f"    ERROR: {e}")
    granger_results['btc_rv_to_vix'] = {'error': str(e)}

# VIX → BTC_RV
print(f"\n  Granger: VIX → BTC_RV(20)")
data_gc2 = pd.DataFrame({'BTC_RV': btc_rv20_d, 'VIX': vix_d}).dropna()
try:
    gc2 = grangercausalitytests(data_gc2[['BTC_RV', 'VIX']], maxlag=max_lag, verbose=False)
    vix_to_btc = {}
    for lag in range(1, max_lag + 1):
        f_stat = gc2[lag][0]['ssr_ftest'][0]
        p_val = gc2[lag][0]['ssr_ftest'][1]
        vix_to_btc[str(lag)] = {'F': float(f_stat), 'p': float(p_val)}
        if lag <= 5:
            sig = "***" if p_val < 0.01 else "**" if p_val < 0.05 else "*" if p_val < 0.10 else ""
            print(f"    lag={lag}: F={f_stat:.4f}, p={p_val:.4f} {sig}")
    granger_results['vix_to_btc_rv'] = vix_to_btc
except Exception as e:
    print(f"    ERROR: {e}")
    granger_results['vix_to_btc_rv'] = {'error': str(e)}

# BTC_RV → SPY_RV
print(f"\n  Granger: BTC_RV(20) → SPY_RV(20)")
data_gc3 = pd.DataFrame({'SPY_RV': spy_rv20_d, 'BTC_RV': btc_rv20_d}).dropna()
try:
    gc3 = grangercausalitytests(data_gc3[['SPY_RV', 'BTC_RV']], maxlag=max_lag, verbose=False)
    btc_to_spy = {}
    for lag in range(1, max_lag + 1):
        f_stat = gc3[lag][0]['ssr_ftest'][0]
        p_val = gc3[lag][0]['ssr_ftest'][1]
        btc_to_spy[str(lag)] = {'F': float(f_stat), 'p': float(p_val)}
        if lag <= 5:
            sig = "***" if p_val < 0.01 else "**" if p_val < 0.05 else "*" if p_val < 0.10 else ""
            print(f"    lag={lag}: F={f_stat:.4f}, p={p_val:.4f} {sig}")
    granger_results['btc_rv_to_spy_rv'] = btc_to_spy
except Exception as e:
    print(f"    ERROR: {e}")
    granger_results['btc_rv_to_spy_rv'] = {'error': str(e)}

# ============================================================
# 3. ASYMMETRIC GRANGER TEST
# ============================================================
print("\n[3/7] Asymmetric Granger Tests (BTC up vs down moves)...")

# Split BTC returns into positive and negative components
btc_ret_pos = btc_ret_aligned.clip(lower=0)  # positive moves
btc_ret_neg = btc_ret_aligned.clip(upper=0).abs()  # negative moves (absolute value)

# RV from positive BTC returns (proxy: rolling std of positive component)
btc_rv_pos = btc_ret_pos.rolling(20).apply(lambda x: np.sqrt(np.mean(x**2)) * np.sqrt(252), raw=True).dropna()
btc_rv_neg = btc_ret_neg.rolling(20).apply(lambda x: np.sqrt(np.mean(x**2)) * np.sqrt(252), raw=True).dropna()

# Align
common_asym = btc_rv_pos.index.intersection(btc_rv_neg.index).intersection(vix_d.index)
btc_rv_pos_a = btc_rv_pos.loc[common_asym]
btc_rv_neg_a = btc_rv_neg.loc[common_asym]
vix_d_a = vix_d.loc[common_asym]

# Difference for stationarity
btc_rv_pos_d = btc_rv_pos_a.diff().dropna()
btc_rv_neg_d = btc_rv_neg_a.diff().dropna()
vix_d_asym = vix_d_a.loc[btc_rv_pos_d.index]

asymmetric_results = {}

# Positive BTC vol → VIX
print(f"  BTC positive vol → VIX:")
data_pos = pd.DataFrame({'VIX': vix_d_asym, 'BTC_RV_pos': btc_rv_pos_d}).dropna()
try:
    gc_pos = grangercausalitytests(data_pos[['VIX', 'BTC_RV_pos']], maxlag=5, verbose=False)
    pos_results = {}
    for lag in range(1, 6):
        f_stat = gc_pos[lag][0]['ssr_ftest'][0]
        p_val = gc_pos[lag][0]['ssr_ftest'][1]
        pos_results[str(lag)] = {'F': float(f_stat), 'p': float(p_val)}
        sig = "***" if p_val < 0.01 else "**" if p_val < 0.05 else "*" if p_val < 0.10 else ""
        print(f"    lag={lag}: F={f_stat:.4f}, p={p_val:.4f} {sig}")
    asymmetric_results['btc_pos_to_vix'] = pos_results
except Exception as e:
    print(f"    ERROR: {e}")
    asymmetric_results['btc_pos_to_vix'] = {'error': str(e)}

# Negative BTC vol → VIX
print(f"\n  BTC negative vol → VIX:")
data_neg = pd.DataFrame({'VIX': vix_d_asym, 'BTC_RV_neg': btc_rv_neg_d}).dropna()
try:
    gc_neg = grangercausalitytests(data_neg[['VIX', 'BTC_RV_neg']], maxlag=5, verbose=False)
    neg_results = {}
    for lag in range(1, 6):
        f_stat = gc_neg[lag][0]['ssr_ftest'][0]
        p_val = gc_neg[lag][0]['ssr_ftest'][1]
        neg_results[str(lag)] = {'F': float(f_stat), 'p': float(p_val)}
        sig = "***" if p_val < 0.01 else "**" if p_val < 0.05 else "*" if p_val < 0.10 else ""
        print(f"    lag={lag}: F={f_stat:.4f}, p={p_val:.4f} {sig}")
    asymmetric_results['btc_neg_to_vix'] = neg_results
except Exception as e:
    print(f"    ERROR: {e}")
    asymmetric_results['btc_neg_to_vix'] = {'error': str(e)}

# ============================================================
# 4. QUANTILE REGRESSION — Tail Dependence
# ============================================================
print("\n[4/7] Quantile Regression (BTC_RV → VIX at different quantiles)...")
import statsmodels.api as sm
from statsmodels.regression.quantile_regression import QuantReg

# Use levels (not differences) for economic interpretation
# VIX_t ~ alpha + beta * BTC_RV_{t-1} at different quantiles
btc_rv20_lagged = btc_rv20.shift(1)
qr_data = pd.DataFrame({
    'BTC_RV_lag1': btc_rv20_lagged,
    'VIX': vix_level_aligned,
}).dropna()
X_qr = sm.add_constant(qr_data[['BTC_RV_lag1']])
y_qr = qr_data['VIX']

quantiles = [0.05, 0.25, 0.50, 0.75, 0.95]
qr_results = {}
n_boot = 1000
rng = np.random.default_rng(42)

for tau in quantiles:
    model = QuantReg(y_qr, X_qr)
    res = model.fit(q=tau)
    beta = res.params.iloc[1] if hasattr(res.params, 'iloc') else res.params[1]
    se = res.bse.iloc[1] if hasattr(res.bse, 'iloc') else res.bse[1]
    boot_betas = []
    for _ in range(n_boot):
        idx = rng.integers(0, len(X_qr), size=len(X_qr))
        X_b, y_b = X_qr.iloc[idx], y_qr.iloc[idx]
        res_b = QuantReg(y_b, X_b).fit(q=tau)
        boot_betas.append(res_b.params.iloc[1])
    boot_arr = np.array(boot_betas)
    se_boot = boot_arr.std()
    ci_lo = np.percentile(boot_arr, 2.5)
    ci_hi = np.percentile(boot_arr, 97.5)
    t_stat = beta / se_boot if se_boot > 0 else 0.0
    p_val = res.pvalues.iloc[1] if hasattr(res.pvalues, 'iloc') else res.pvalues[1]

    qr_results[str(tau)] = {
        'beta': float(beta),
        'se': float(se),
        'se_boot': float(se_boot),
        'ci_lo': float(ci_lo),
        'ci_hi': float(ci_hi),
        't_stat': float(t_stat),
        'p_value': float(p_val),
        'significant': bool(ci_lo > 0 or ci_hi < 0)
    }
    sig = "***" if p_val < 0.01 else "**" if p_val < 0.05 else "*" if p_val < 0.10 else ""
    print(
        f"  τ={tau:.2f}: β={beta:.4f}, SE_boot={se_boot:.4f}, "
        f"95% CI=[{ci_lo:.4f}, {ci_hi:.4f}], t={t_stat:.2f}, p={p_val:.4f} {sig}"
    )

# Key insight: does beta increase at extreme quantiles? (tail dependence)
beta_05 = qr_results['0.05']['beta']
beta_50 = qr_results['0.5']['beta']
beta_95 = qr_results['0.95']['beta']
print(f"\n  Tail dependence pattern:")
print(f"    β(0.05)/β(0.50) = {beta_05/beta_50:.2f} (left tail amplification)")
print(f"    β(0.95)/β(0.50) = {beta_95/beta_50:.2f} (right tail amplification)")

# ============================================================
# 5. ROLLING DIEBOLD-YILMAZ SPILLOVER INDEX
# ============================================================
print("\n[5/7] Rolling Diebold-Yilmaz Spillover Index (252d window)...")
from statsmodels.tsa.api import VAR

def compute_spillover_index(data, horizon=10):
    """Compute Diebold-Yilmaz (2012) spillover index from VAR."""
    try:
        model = VAR(data)
        # Select optimal lag by AIC, cap at 5 for stability
        lag_order = model.select_order(maxlags=5)
        optimal_lag = lag_order.aic
        if optimal_lag < 1:
            optimal_lag = 1

        results = model.fit(optimal_lag)

        # Forecast error variance decomposition
        fevd = results.fevd(horizon)

        # Spillover matrix: each row i shows proportion of variable i's
        # forecast error variance due to shocks in variable j
        decomp = fevd.decomp  # shape: (horizon, n_vars, n_vars)
        # Use the last horizon step
        spillover_matrix = decomp[-1]  # (n_vars, n_vars)

        # Normalize rows to sum to 1
        row_sums = spillover_matrix.sum(axis=1, keepdims=True)
        spillover_matrix_norm = spillover_matrix / row_sums

        # Total spillover index: sum of off-diagonal / total * 100
        n = spillover_matrix_norm.shape[0]
        off_diag = spillover_matrix_norm.sum() - np.trace(spillover_matrix_norm)
        total_spillover = off_diag / n * 100

        # Directional: from BTC to others
        # BTC is column 0 (or whichever index)
        from_btc = spillover_matrix_norm[:, 0].sum() - spillover_matrix_norm[0, 0]
        to_btc = spillover_matrix_norm[0, :].sum() - spillover_matrix_norm[0, 0]

        return {
            'total_spillover': float(total_spillover),
            'from_btc': float(from_btc * 100),
            'to_btc': float(to_btc * 100),
            'net_btc': float((from_btc - to_btc) * 100),
            'lag': int(optimal_lag)
        }
    except Exception as e:
        return None

# Prepare data for VAR: use changes in RV and VIX for stationarity
var_data = pd.DataFrame({
    'BTC_RV': btc_rv20_d,
    'SPY_RV': spy_rv20_d,
    'VIX': vix_d
}).dropna()

# Rolling spillover (252d window)
window_size = 252
rolling_dates = []
rolling_spillover = []
rolling_from_btc = []
rolling_net_btc = []

print(f"  Computing rolling spillover (window={window_size}, n={len(var_data)})...")
for i in range(window_size, len(var_data), 5):  # step=5 for efficiency
    window_data = var_data.iloc[i-window_size:i]
    result = compute_spillover_index(window_data)
    if result is not None:
        rolling_dates.append(var_data.index[i].strftime('%Y-%m-%d'))
        rolling_spillover.append(result['total_spillover'])
        rolling_from_btc.append(result['from_btc'])
        rolling_net_btc.append(result['net_btc'])

if len(rolling_spillover) > 0:
    spillover_summary = {
        'mean_total': float(np.mean(rolling_spillover)),
        'std_total': float(np.std(rolling_spillover)),
        'max_total': float(np.max(rolling_spillover)),
        'min_total': float(np.min(rolling_spillover)),
        'mean_from_btc': float(np.mean(rolling_from_btc)),
        'mean_net_btc': float(np.mean(rolling_net_btc)),
        'n_windows': len(rolling_spillover),
    }
    print(f"  Total spillover: mean={spillover_summary['mean_total']:.2f}%, max={spillover_summary['max_total']:.2f}%, min={spillover_summary['min_total']:.2f}%")
    print(f"  From BTC: mean={spillover_summary['mean_from_btc']:.2f}%")
    print(f"  Net BTC (from - to): mean={spillover_summary['mean_net_btc']:.2f}%")
else:
    spillover_summary = {'error': 'No valid windows'}
    print("  ERROR: No valid spillover windows computed")

# Identify crisis periods with elevated spillover
if len(rolling_spillover) > 0:
    spillover_df = pd.DataFrame({
        'date': rolling_dates,
        'total': rolling_spillover,
        'from_btc': rolling_from_btc,
        'net_btc': rolling_net_btc
    })
    spillover_df['date'] = pd.to_datetime(spillover_df['date'])

    # High spillover periods (>75th percentile)
    threshold = np.percentile(rolling_spillover, 75)
    high_spillover = spillover_df[spillover_df['total'] > threshold]

    # Identify clusters
    if len(high_spillover) > 0:
        # Group by year
        high_by_year = high_spillover.groupby(high_spillover['date'].dt.year).agg({
            'total': ['mean', 'count'],
            'from_btc': 'mean'
        }).round(2)
        print(f"\n  High spillover periods (>{threshold:.1f}%):")
        for year in high_by_year.index:
            total_mean = high_by_year.loc[year, ('total', 'mean')]
            count = high_by_year.loc[year, ('total', 'count')]
            from_btc_mean = high_by_year.loc[year, ('from_btc', 'mean')]
            print(f"    {year}: mean={total_mean:.1f}%, count={count}, from_btc={from_btc_mean:.1f}%")

# ============================================================
# 6. DCC CORRELATION by VIX Regime
# ============================================================
print("\n[6/7] DCC-like Dynamic Correlation (BTC-SPY) by VIX Regime...")

# Simple EWMA correlation as DCC proxy (avoid complex DCC estimation issues)
def ewma_correlation(x, y, lambda_=0.94):
    """EWMA dynamic correlation (RiskMetrics style)."""
    n = len(x)
    var_x = np.zeros(n)
    var_y = np.zeros(n)
    cov_xy = np.zeros(n)
    corr = np.zeros(n)

    # Initialize with sample moments
    var_x[0] = x.iloc[0]**2
    var_y[0] = y.iloc[0]**2
    cov_xy[0] = x.iloc[0] * y.iloc[0]

    for t in range(1, n):
        var_x[t] = lambda_ * var_x[t-1] + (1 - lambda_) * x.iloc[t]**2
        var_y[t] = lambda_ * var_y[t-1] + (1 - lambda_) * y.iloc[t]**2
        cov_xy[t] = lambda_ * cov_xy[t-1] + (1 - lambda_) * x.iloc[t] * y.iloc[t]

        denom = np.sqrt(var_x[t] * var_y[t])
        if denom > 1e-10:
            corr[t] = cov_xy[t] / denom
        else:
            corr[t] = 0.0

    return pd.Series(corr, index=x.index)

# Compute EWMA correlation
dcc_corr = ewma_correlation(btc_ret_aligned, spy_ret_aligned, lambda_=0.94)

# Define VIX regimes
vix_regime = pd.Series('Normal', index=vix_level_aligned.index)
vix_regime[vix_level_aligned < 15] = 'Low'
vix_regime[vix_level_aligned > 25] = 'High'
vix_regime[vix_level_aligned > 35] = 'Crisis'

# Statistics by regime
dcc_by_regime = {}
print(f"\n  BTC-SPY Dynamic Correlation by VIX Regime:")
for regime in ['Low', 'Normal', 'High', 'Crisis']:
    mask = vix_regime == regime
    if mask.sum() > 20:
        corr_vals = dcc_corr[mask]
        stats = {
            'mean': float(corr_vals.mean()),
            'median': float(corr_vals.median()),
            'std': float(corr_vals.std()),
            'min': float(corr_vals.min()),
            'max': float(corr_vals.max()),
            'n_days': int(mask.sum()),
            'pct_positive': float((corr_vals > 0).mean() * 100),
        }
        dcc_by_regime[regime] = stats
        print(f"  {regime:8s} (n={stats['n_days']:5d}): mean={stats['mean']:.4f}, median={stats['median']:.4f}, pct_positive={stats['pct_positive']:.1f}%")

# Rolling 60d correlation for comparison
rolling_corr_60 = btc_ret_aligned.rolling(60).corr(spy_ret_aligned).dropna()
rolling_corr_by_regime = {}
for regime in ['Low', 'Normal', 'High', 'Crisis']:
    mask = vix_regime.loc[rolling_corr_60.index] == regime
    if mask.sum() > 20:
        rc = rolling_corr_60[mask]
        rolling_corr_by_regime[regime] = {
            'mean': float(rc.mean()),
            'std': float(rc.std()),
            'n': int(mask.sum())
        }

print(f"\n  Rolling 60d Correlation by VIX Regime:")
for regime, stats in rolling_corr_by_regime.items():
    print(f"  {regime:8s} (n={stats['n']:5d}): mean={stats['mean']:.4f}, std={stats['std']:.4f}")

# ============================================================
# 7. FORECASTING TEST: AR(VIX) + BTC_RV
# ============================================================
print("\n[7/7] Forecasting Test: AR(VIX) vs AR(VIX) + BTC_RV...")
from statsmodels.tsa.ar_model import AutoReg
from scipy import stats as scipy_stats

# Prepare data
forecast_dict = {
    'VIX': vix_level_aligned,
    'BTC_RV': btc_rv20,
    'BTC_RV_lag1': btc_rv20.shift(1),
}
for lag in range(1, 11):
    forecast_dict[f'VIX_lag{lag}'] = vix_level_aligned.shift(lag)
forecast_data = pd.DataFrame(forecast_dict).dropna()

# OOS split: 2019-01-01
oos_start = '2019-01-01'
is_data = forecast_data.loc[:'2018-12-31']
oos_data = forecast_data.loc['2019-01-01':]

aic_scores = {}
for p in range(1, 11):
    model = AutoReg(is_data['VIX'], lags=p).fit()
    aic_scores[p] = model.aic
ar_order = min(aic_scores, key=aic_scores.get)

print(f"  IS period: {is_data.index[0].strftime('%Y-%m-%d')} to {is_data.index[-1].strftime('%Y-%m-%d')} (n={len(is_data)})")
print(f"  OOS period: {oos_data.index[0].strftime('%Y-%m-%d')} to {oos_data.index[-1].strftime('%Y-%m-%d')} (n={len(oos_data)})")
print(f"  AIC-selected AR order: p={ar_order}")

# Model 1: AR(p) for VIX (baseline)
# Model 2: AR(p) + BTC_RV_lag1 (extended)
from sklearn.linear_model import LinearRegression

# Features
ar_features = [f'VIX_lag{p}' for p in range(1, ar_order + 1)]
ext_features = ar_features + ['BTC_RV_lag1']

# Rolling window OOS forecast
forecast_ar = []
forecast_ext = []
actual_vix = []
forecast_dates = []
roll_size = 756
oos_positions = forecast_data.index.get_indexer(oos_data.index)

for row_pos in oos_positions:
    train_start = max(0, row_pos - roll_size)
    train = forecast_data.iloc[train_start:row_pos]
    test_row = forecast_data.iloc[row_pos:row_pos + 1]

    if len(test_row) == 0 or len(train) < ar_order:
        break

    # AR model
    X_ar_train = train[ar_features]
    y_train = train['VIX']
    X_ar_test = test_row[ar_features]

    model_ar = LinearRegression()
    model_ar.fit(X_ar_train, y_train)
    pred_ar = model_ar.predict(X_ar_test)[0]

    # Extended model
    X_ext_train = train[ext_features]
    X_ext_test = test_row[ext_features]

    model_ext = LinearRegression()
    model_ext.fit(X_ext_train, y_train)
    pred_ext = model_ext.predict(X_ext_test)[0]

    forecast_ar.append(pred_ar)
    forecast_ext.append(pred_ext)
    actual_vix.append(test_row['VIX'].values[0])
    forecast_dates.append(test_row.index[0])

forecast_ar = np.array(forecast_ar)
forecast_ext = np.array(forecast_ext)
actual_vix = np.array(actual_vix)

# Forecast evaluation
e_ar = actual_vix - forecast_ar
e_ext = actual_vix - forecast_ext

mse_ar = np.mean(e_ar**2)
mse_ext = np.mean(e_ext**2)
mae_ar = np.mean(np.abs(e_ar))
mae_ext = np.mean(np.abs(e_ext))

# QLIKE (proxy-robust)
qlike_ar = np.mean(np.log(forecast_ar**2) + (actual_vix**2) / (forecast_ar**2))
qlike_ext = np.mean(np.log(forecast_ext**2) + (actual_vix**2) / (forecast_ext**2))

print(f"\n  Forecast Evaluation (OOS):")
print(f"    AR(VIX):           MSE={mse_ar:.4f}, MAE={mae_ar:.4f}, QLIKE={qlike_ar:.4f}")
print(f"    AR(VIX)+BTC_RV:    MSE={mse_ext:.4f}, MAE={mae_ext:.4f}, QLIKE={qlike_ext:.4f}")
print(f"    MSE improvement:   {(1 - mse_ext/mse_ar)*100:.2f}%")
print(f"    MAE improvement:   {(1 - mae_ext/mae_ar)*100:.2f}%")

# Diebold-Mariano test (MSE loss)
d = e_ar**2 - e_ext**2
dm_mean = np.mean(d)
# Newey-West HAC standard error (lag = floor(T^(1/3)))
T = len(d)
dm_lag = int(np.floor(T**(1/3)))

# HAC variance
gamma_0 = np.var(d, ddof=1)
hac_var = gamma_0
for k in range(1, dm_lag + 1):
    weight = 1 - k / (dm_lag + 1)  # Bartlett kernel
    gamma_k = np.cov(d[k:], d[:-k])[0, 1]
    hac_var += 2 * weight * gamma_k

dm_se = np.sqrt(hac_var / T)
dm_stat = dm_mean / dm_se if dm_se > 0 else 0
dm_pval = 2 * (1 - scipy_stats.norm.cdf(abs(dm_stat)))

# Harvey et al. (1997) small-sample correction
h_correction = np.sqrt((T + 1 - 2 * 1 + 1 * (1 - 1) / T) / T)
dm_stat_harvey = dm_stat * h_correction

print(f"\n  Diebold-Mariano Test (MSE loss):")
print(f"    DM stat: {dm_stat:.4f}")
print(f"    DM stat (Harvey corrected): {dm_stat_harvey:.4f}")
print(f"    p-value: {dm_pval:.4f}")
print(f"    Harvey |t| > 3.0 threshold: {'PASS' if abs(dm_stat_harvey) > 3.0 else 'FAIL'}")

forecast_results = {
    'mse_ar': float(mse_ar),
    'mse_ext': float(mse_ext),
    'mae_ar': float(mae_ar),
    'mae_ext': float(mae_ext),
    'qlike_ar': float(qlike_ar),
    'qlike_ext': float(qlike_ext),
    'mse_improvement_pct': float((1 - mse_ext/mse_ar)*100),
    'mae_improvement_pct': float((1 - mae_ext/mae_ar)*100),
    'dm_stat': float(dm_stat),
    'dm_stat_harvey': float(dm_stat_harvey),
    'dm_pval': float(dm_pval),
    'harvey_pass': abs(dm_stat_harvey) > 3.0,
    'oos_n': int(T),
    'oos_start': oos_start,
    'ar_order': int(ar_order),
    'roll_size': int(roll_size),
}

# ============================================================
# 7b. SUBSAMPLE ANALYSIS — Crisis vs Non-Crisis forecasting
# ============================================================
print("\n[7b] Subsample Analysis: Crisis vs Non-Crisis forecasting gain...")

vix_at_forecast = pd.Series(actual_vix, index=forecast_dates)
crisis_mask = vix_at_forecast > 25
normal_mask = ~crisis_mask

subsample_results = {}
for label, mask in [('Crisis (VIX>25)', crisis_mask), ('Normal (VIX<=25)', normal_mask)]:
    if mask.sum() > 30:
        e_ar_sub = e_ar[mask]
        e_ext_sub = e_ext[mask]
        mse_ar_sub = np.mean(e_ar_sub**2)
        mse_ext_sub = np.mean(e_ext_sub**2)
        improvement = (1 - mse_ext_sub / mse_ar_sub) * 100

        # DM test for subsample
        d_sub = e_ar_sub**2 - e_ext_sub**2
        dm_sub = np.mean(d_sub) / (np.std(d_sub, ddof=1) / np.sqrt(len(d_sub))) if np.std(d_sub, ddof=1) > 0 else 0

        subsample_results[label] = {
            'mse_ar': float(mse_ar_sub),
            'mse_ext': float(mse_ext_sub),
            'improvement_pct': float(improvement),
            'dm_stat': float(dm_sub),
            'n': int(mask.sum()),
        }
        print(f"  {label} (n={mask.sum()}): MSE improvement={improvement:.2f}%, DM={dm_sub:.2f}")

# ============================================================
# 8. STRUCTURAL BREAK — Sub-period Granger Analysis
# ============================================================
print("\n[Bonus] Structural Break: Sub-period Granger Analysis...")

# Split into sub-periods
periods = {
    '2015-2017 (Pre-mania)': ('2015-02-01', '2017-12-31'),
    '2018-2019 (Crypto winter)': ('2018-01-01', '2019-12-31'),
    '2020 (COVID)': ('2020-01-01', '2020-12-31'),
    '2021-2022 (Bull-Bear)': ('2021-01-01', '2022-12-31'),
    '2023-2026 (Recovery+ETF)': ('2023-01-01', '2026-04-09'),
}

subperiod_granger = {}
n_periods = len(periods)
bonferroni_threshold = 0.05 / n_periods
for period_name, (start, end) in periods.items():
    mask = (var_data.index >= start) & (var_data.index <= end)
    sub_data = var_data.loc[mask, ['VIX', 'BTC_RV']].dropna()

    if len(sub_data) > 50:
        try:
            var_sel = VAR(sub_data[['VIX', 'BTC_RV']]).select_order(maxlags=5)
            best_lag_aic = var_sel.aic
            if best_lag_aic is None or pd.isna(best_lag_aic):
                best_lag_aic = 1
            best_lag_aic = max(1, int(best_lag_aic))
            gc = grangercausalitytests(
                sub_data[['VIX', 'BTC_RV']],
                maxlag=best_lag_aic,
                verbose=False,
            )
            f_stat = gc[best_lag_aic][0]['ssr_ftest'][0]
            p_val = gc[best_lag_aic][0]['ssr_ftest'][1]

            subperiod_granger[period_name] = {
                'n': int(len(sub_data)),
                'best_lag_aic': int(best_lag_aic),
                'F': float(f_stat),
                'p': float(p_val),
                'bonferroni_threshold': float(bonferroni_threshold),
                'significant': p_val < 0.05,
                'significant_bonf': p_val < bonferroni_threshold,
            }
            sig = "***" if p_val < 0.01 else "**" if p_val < 0.05 else "*" if p_val < 0.10 else ""
            bonf_sig = " [Bonf]" if p_val < bonferroni_threshold else ""
            print(
                f"  {period_name} (n={len(sub_data)}): lag={best_lag_aic}, "
                f"F={f_stat:.2f}, p={p_val:.4f} {sig}{bonf_sig}"
            )
        except Exception as e:
            subperiod_granger[period_name] = {'error': str(e)}
            print(f"  {period_name}: ERROR - {e}")

# ============================================================
# 9. GENERATE CHARTS
# ============================================================
print("\n[Charts] Generating visualization...")
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

fig, axes = plt.subplots(3, 2, figsize=(16, 14))
fig.suptitle('K1025: Crypto Fear Channel — BTC Vol Spillover to Equity', fontsize=14, fontweight='bold')

# Chart 1: BTC RV vs VIX
ax = axes[0, 0]
ax.plot(btc_rv20.index, btc_rv20.values * 100, alpha=0.7, label='BTC RV(20) %', color='orange')
ax2 = ax.twinx()
ax2.plot(vix_level_aligned.index, vix_level_aligned.values, alpha=0.7, label='VIX', color='blue')
ax.set_title('BTC Realized Vol vs VIX')
ax.set_ylabel('BTC RV (%)')
ax2.set_ylabel('VIX')
ax.legend(loc='upper left')
ax2.legend(loc='upper right')
ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))

# Chart 2: Quantile Regression coefficients
ax = axes[0, 1]
taus = [float(t) for t in qr_results.keys()]
betas = [qr_results[t]['beta'] for t in qr_results.keys()]
ses = [qr_results[t]['se_boot'] for t in qr_results.keys()]
ax.bar(taus, betas, width=0.12, color=['red' if b > 0 else 'blue' for b in betas], alpha=0.7)
ax.errorbar(taus, betas, yerr=[1.96*s for s in ses], fmt='none', color='black', capsize=3)
ax.axhline(y=0, color='gray', linestyle='--')
ax.set_xlabel('Quantile (τ)')
ax.set_ylabel('β (BTC_RV → VIX)')
ax.set_title('Quantile Regression: BTC RV → VIX')

# Chart 3: Rolling Spillover Index
ax = axes[1, 0]
if len(rolling_spillover) > 0:
    dates = pd.to_datetime(rolling_dates)
    ax.plot(dates, rolling_spillover, color='darkred', alpha=0.8, label='Total Spillover')
    ax.fill_between(dates, rolling_spillover, alpha=0.2, color='red')
    ax.axhline(y=np.mean(rolling_spillover), color='gray', linestyle='--', label=f'Mean={np.mean(rolling_spillover):.1f}%')
    ax.set_ylabel('Spillover Index (%)')
    ax.set_title('Rolling Diebold-Yilmaz Spillover Index (252d)')
    ax.legend()
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))

# Chart 4: DCC Correlation by VIX Regime (boxplot)
ax = axes[1, 1]
regime_data = []
regime_labels = []
for regime in ['Low', 'Normal', 'High', 'Crisis']:
    mask = vix_regime == regime
    if mask.sum() > 20:
        regime_data.append(dcc_corr[mask].values)
        regime_labels.append(f'{regime}\n(n={mask.sum()})')
ax.boxplot(regime_data, labels=regime_labels)
ax.axhline(y=0, color='gray', linestyle='--')
ax.set_ylabel('BTC-SPY Correlation')
ax.set_title('Dynamic Correlation by VIX Regime')

# Chart 5: Forecast comparison (cumulative squared error)
ax = axes[2, 0]
cum_se_ar = np.cumsum(e_ar**2)
cum_se_ext = np.cumsum(e_ext**2)
forecast_dates_plot = pd.to_datetime([d.strftime('%Y-%m-%d') for d in forecast_dates[:len(cum_se_ar)]])
ax.plot(forecast_dates_plot, cum_se_ar, label='AR(VIX)', color='blue', alpha=0.8)
ax.plot(forecast_dates_plot, cum_se_ext, label='AR(VIX)+BTC_RV', color='red', alpha=0.8)
ax.set_ylabel('Cumulative Squared Error')
ax.set_title('OOS Forecast: Cumulative MSE')
ax.legend()
ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))

# Chart 6: Sub-period Granger significance
ax = axes[2, 1]
if subperiod_granger:
    periods_list = list(subperiod_granger.keys())
    p_values = [subperiod_granger[p].get('p', 1.0) for p in periods_list]
    colors = ['green' if p < 0.05 else 'orange' if p < 0.10 else 'red' for p in p_values]
    bars = ax.barh(range(len(periods_list)), [-np.log10(max(p, 1e-10)) for p in p_values], color=colors, alpha=0.7)
    ax.set_yticks(range(len(periods_list)))
    ax.set_yticklabels([p[:20] for p in periods_list], fontsize=8)
    ax.axvline(x=-np.log10(0.05), color='red', linestyle='--', label='p=0.05')
    ax.axvline(x=-np.log10(0.01), color='darkred', linestyle='--', label='p=0.01')
    ax.set_xlabel('-log10(p-value)')
    ax.set_title('Sub-period BTC→VIX Granger Causality')
    ax.legend(fontsize=8)

plt.tight_layout()
chart_path = os.path.join(SCRIPT_DIR, 'k1025_v2_results.png')
plt.savefig(chart_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Chart saved: {chart_path}")

# ============================================================
# 10. SAVE RESULTS
# ============================================================
print("\n[Results] Saving to JSON...")

results = {
    'experiment_id': 'K1025_v2',
    'title': 'Crypto Fear Channel — BTC Vol Spillover to Equity',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'seed': 42,
    'data_source': 'yfinance (SPY, BTC-USD, ^VIX)',
    'sample_period': f"{common_idx2[0].strftime('%Y-%m-%d')} to {common_idx2[-1].strftime('%Y-%m-%d')}",
    'n_observations': len(common_idx2),
    'oos_period': f"{oos_start} to {common_idx2[-1].strftime('%Y-%m-%d')}",
    'references': [
        'Diebold & Yilmaz (2012) - Better to Give than to Receive: Predictive Directional Measurement of Volatility Spillovers',
        'Engle (2002) - Dynamic Conditional Correlation',
        'Koenker & Bassett (1978) - Regression Quantiles',
        'Harvey et al. (2016) - Testing for multiple bubbles',
    ],
    'descriptive_statistics': desc_stats,
    'adf_tests': {
        'btc_rv20': adf_btc_rv,
        'vix': adf_vix,
        'spy_rv20': adf_spy_rv,
    },
    'granger_causality': granger_results,
    'asymmetric_granger': asymmetric_results,
    'quantile_regression': qr_results,
    'spillover_index': spillover_summary,
    'dcc_correlation_by_regime': dcc_by_regime,
    'rolling_correlation_by_regime': rolling_corr_by_regime,
    'forecast_evaluation': forecast_results,
    'subsample_forecast': subsample_results,
    'subperiod_granger': subperiod_granger,
    'conclusions': {
        'granger_btc_to_vix': 'See granger_causality.btc_rv_to_vix for significance at each lag',
        'asymmetry': 'Compare btc_neg_to_vix vs btc_pos_to_vix p-values',
        'tail_dependence': f'QR beta ratio: left tail (0.05/0.50) = {beta_05/beta_50:.2f}, right tail (0.95/0.50) = {beta_95/beta_50:.2f}',
        'dm_test': f'Harvey-corrected DM = {dm_stat_harvey:.4f}, pass = {abs(dm_stat_harvey) > 3.0}',
        'spillover_direction': spillover_summary.get('mean_net_btc', 'N/A'),
    }
}

with open(RESULTS_FILE, 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"\n  Results saved to: {RESULTS_FILE}")

# ============================================================
# SUMMARY
# ============================================================
print("\n" + "=" * 60)
print("SUMMARY")
print("=" * 60)

# Granger summary
if 'btc_rv_to_vix' in granger_results and isinstance(granger_results['btc_rv_to_vix'], dict):
    best_gc_lag = min(granger_results['btc_rv_to_vix'].keys(),
                       key=lambda k: granger_results['btc_rv_to_vix'][k].get('p', 1.0))
    best_gc = granger_results['btc_rv_to_vix'][best_gc_lag]
    print(f"\n1. Granger BTC_RV → VIX: Best lag={best_gc_lag}, F={best_gc.get('F', 'N/A'):.4f}, p={best_gc.get('p', 'N/A'):.4f}")

# Asymmetry summary
if 'btc_neg_to_vix' in asymmetric_results and 'btc_pos_to_vix' in asymmetric_results:
    neg_p = min([asymmetric_results['btc_neg_to_vix'].get(str(l), {}).get('p', 1.0) for l in range(1, 6)])
    pos_p = min([asymmetric_results['btc_pos_to_vix'].get(str(l), {}).get('p', 1.0) for l in range(1, 6)])
    print(f"\n2. Asymmetry: Negative BTC best p={neg_p:.4f}, Positive BTC best p={pos_p:.4f}")
    if neg_p < pos_p:
        print(f"   → BTC DOWNSIDE vol spillover to VIX is STRONGER (confirms K746b)")
    else:
        print(f"   → No clear asymmetry detected")

# Quantile regression
print(f"\n3. Quantile Regression: β increases from {beta_05:.4f} (τ=0.05) to {beta_95:.4f} (τ=0.95)")
print(f"   → {'TAIL DEPENDENCE CONFIRMED' if beta_95 > beta_50 * 1.3 else 'Moderate tail dependence'}")

# Spillover
if 'mean_net_btc' in spillover_summary:
    print(f"\n4. Spillover: Mean total={spillover_summary['mean_total']:.2f}%, Net BTC={spillover_summary['mean_net_btc']:.2f}%")
    print(f"   → BTC is {'NET TRANSMITTER' if spillover_summary['mean_net_btc'] > 0 else 'NET RECEIVER'} of volatility")

# DCC
if 'Crisis' in dcc_by_regime:
    print(f"\n5. BTC-SPY Correlation: Normal={dcc_by_regime.get('Normal', {}).get('mean', 'N/A'):.4f}, Crisis={dcc_by_regime['Crisis']['mean']:.4f}")
    if dcc_by_regime['Crisis']['mean'] > dcc_by_regime.get('Normal', {}).get('mean', 0):
        print(f"   → CONTAGION: Correlation increases in crisis (BTC NOT a hedge)")

# Forecasting
print(f"\n6. Forecasting: AR(VIX)+BTC_RV MSE improvement = {forecast_results['mse_improvement_pct']:.2f}%")
print(f"   DM stat (Harvey) = {dm_stat_harvey:.4f}, {'SIGNIFICANT' if abs(dm_stat_harvey) > 3.0 else 'NOT significant at Harvey threshold'}")

print(f"\n{'=' * 60}")
print(f"K1025 COMPLETE")
print(f"{'=' * 60}")
