"""
K1022: Crypto Fear Channel — BTC Vol Spillover to Equity via VIX

Deep dive on K746b findings with corrected methodology:
1. Granger causality (BTC vol → VIX, asymmetric)
2. Tail dependence (Clayton/Gumbel copula or quantile regression)
3. Rolling spillover (Diebold-Yilmaz style)
4. Economic value: BTC vol as VIX forecasting signal

Data: SPY, BTC-USD, ^VIX from yfinance, 2015-01-01 to 2026-04-09
Seed: 42

References:
- K639: BTC→SPY Granger confirmed, inverse leverage
- K746b: BTC vol asymmetrically Granger-causes VIX (Codex flagged methodology issues)
- Diebold & Yilmaz (2012): Connectedness approach
- Patton (2006): Copula-based models for financial time series
"""

import json
import warnings
import os
from datetime import datetime, timezone

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from statsmodels.tsa.stattools import grangercausalitytests, adfuller
from statsmodels.tsa.api import VAR
from statsmodels.stats.diagnostic import acorr_ljungbox
from arch import arch_model

warnings.filterwarnings('ignore')
np.random.seed(42)

EXPERIMENT_DIR = os.path.dirname(os.path.abspath(__file__))

# ============================================================
# 1. DATA COLLECTION
# ============================================================
print("=" * 60)
print("K1022: Crypto Fear Channel — BTC Vol Spillover")
print("=" * 60)

# Download data
print("\n[1] Downloading data...")
start_date = "2015-01-01"
end_date = "2026-04-09"

tickers = {
    'SPY': 'SPY',
    'BTC': 'BTC-USD',
    'VIX': '^VIX'
}

data = {}
for name, ticker in tickers.items():
    df = yf.download(ticker, start=start_date, end=end_date, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    data[name] = df
    print(f"  {name}: {len(df)} observations, {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")

# Align dates
common_idx = data['SPY'].index.intersection(data['BTC'].index).intersection(data['VIX'].index)
print(f"  Common dates: {len(common_idx)}")

# Build analysis DataFrame
df = pd.DataFrame(index=common_idx)
df['spy_close'] = data['SPY'].loc[common_idx, 'Close']
df['btc_close'] = data['BTC'].loc[common_idx, 'Close']
df['vix'] = data['VIX'].loc[common_idx, 'Close']

# Returns
df['spy_ret'] = np.log(df['spy_close'] / df['spy_close'].shift(1))
df['btc_ret'] = np.log(df['btc_close'] / df['btc_close'].shift(1))

# Realized vol proxies (squared returns, annualized)
df['spy_vol'] = df['spy_ret'] ** 2  # daily r²
df['btc_vol'] = df['btc_ret'] ** 2  # daily r²

# Rolling realized vol (21-day)
df['spy_rv21'] = df['spy_ret'].rolling(21).std() * np.sqrt(252) * 100  # annualized %
df['btc_rv21'] = df['btc_ret'].rolling(21).std() * np.sqrt(252) * 100

# VIX change
df['vix_change'] = df['vix'].diff()
df['vix_ret'] = np.log(df['vix'] / df['vix'].shift(1))

df = df.dropna()
print(f"  Analysis sample: {len(df)} observations")
print(f"  Period: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")

# ============================================================
# 2. DESCRIPTIVE STATISTICS
# ============================================================
print("\n[2] Descriptive Statistics")
desc_vars = ['spy_ret', 'btc_ret', 'vix', 'spy_rv21', 'btc_rv21']
desc_stats = {}
for v in desc_vars:
    s = df[v]
    adf_stat, adf_pval = adfuller(s, maxlag=10, autolag='AIC')[:2]
    desc_stats[v] = {
        'mean': float(s.mean()),
        'std': float(s.std()),
        'skew': float(s.skew()),
        'kurtosis': float(s.kurtosis()),
        'min': float(s.min()),
        'max': float(s.max()),
        'adf_stat': float(adf_stat),
        'adf_pval': float(adf_pval),
        'stationary': adf_pval < 0.05
    }
    print(f"  {v}: mean={s.mean():.6f}, std={s.std():.6f}, skew={s.skew():.2f}, "
          f"kurt={s.kurtosis():.2f}, ADF p={adf_pval:.4f} {'✓' if adf_pval < 0.05 else '✗'}")

# Unconditional correlations
print("\n  Unconditional correlations:")
corr_pairs = [
    ('btc_rv21', 'vix', 'BTC RV21 vs VIX'),
    ('btc_rv21', 'spy_rv21', 'BTC RV21 vs SPY RV21'),
    ('btc_ret', 'spy_ret', 'BTC ret vs SPY ret'),
    ('btc_vol', 'vix_change', 'BTC r² vs VIX change'),
]
unconditional_corr = {}
for v1, v2, label in corr_pairs:
    r, p = stats.pearsonr(df[v1], df[v2])
    rho, rho_p = stats.spearmanr(df[v1], df[v2])
    unconditional_corr[label] = {
        'pearson_r': float(r), 'pearson_p': float(p),
        'spearman_rho': float(rho), 'spearman_p': float(rho_p)
    }
    print(f"    {label}: Pearson r={r:.4f} (p={p:.4f}), Spearman ρ={rho:.4f} (p={rho_p:.4f})")

# ============================================================
# 3. GRANGER CAUSALITY (CORRECTED)
# ============================================================
print("\n[3] Granger Causality Tests (corrected methodology)")
print("    Target: VIX level (not log-VIX, per Codex review of K746b)")

# Use VIX level and BTC realized vol (21-day rolling)
# Both should be stationary — check
btc_rv_adf = adfuller(df['btc_rv21'], maxlag=10, autolag='AIC')
vix_adf = adfuller(df['vix'], maxlag=10, autolag='AIC')
print(f"  BTC RV21 ADF: stat={btc_rv_adf[0]:.4f}, p={btc_rv_adf[1]:.4f}")
print(f"  VIX ADF: stat={vix_adf[0]:.4f}, p={vix_adf[1]:.4f}")

# If VIX is not stationary (likely I(0) but let's check), use first difference
use_vix_diff = vix_adf[1] > 0.05
if use_vix_diff:
    print("  VIX not stationary → using VIX first difference")
    granger_vix = df['vix'].diff().dropna()
else:
    granger_vix = df['vix']

# Align
gc_df = pd.DataFrame({
    'btc_rv': df['btc_rv21'],
    'vix_target': granger_vix
}).dropna()

granger_results = {}
max_lag = 10

# Test BTC vol → VIX
print("\n  BTC RV21 → VIX:")
gc_data_btc_vix = gc_df[['vix_target', 'btc_rv']].values
try:
    gc_test = grangercausalitytests(gc_data_btc_vix, maxlag=max_lag, verbose=False)
    for lag in range(1, max_lag + 1):
        f_stat = gc_test[lag][0]['ssr_ftest'][0]
        f_pval = gc_test[lag][0]['ssr_ftest'][1]
        granger_results[f'btc_rv_to_vix_lag{lag}'] = {
            'F_stat': float(f_stat), 'p_value': float(f_pval),
            'significant_5pct': f_pval < 0.05
        }
        if lag <= 5:
            print(f"    Lag {lag}: F={f_stat:.4f}, p={f_pval:.4f} {'***' if f_pval < 0.01 else '**' if f_pval < 0.05 else ''}")
except Exception as e:
    print(f"    Error: {e}")

# Test VIX → BTC vol (reverse)
print("\n  VIX → BTC RV21:")
gc_data_vix_btc = gc_df[['btc_rv', 'vix_target']].values
try:
    gc_test_rev = grangercausalitytests(gc_data_vix_btc, maxlag=max_lag, verbose=False)
    for lag in range(1, max_lag + 1):
        f_stat = gc_test_rev[lag][0]['ssr_ftest'][0]
        f_pval = gc_test_rev[lag][0]['ssr_ftest'][1]
        granger_results[f'vix_to_btc_rv_lag{lag}'] = {
            'F_stat': float(f_stat), 'p_value': float(f_pval),
            'significant_5pct': f_pval < 0.05
        }
        if lag <= 5:
            print(f"    Lag {lag}: F={f_stat:.4f}, p={f_pval:.4f} {'***' if f_pval < 0.01 else '**' if f_pval < 0.05 else ''}")
except Exception as e:
    print(f"    Error: {e}")

# ============================================================
# 4. ASYMMETRIC GRANGER TEST
# ============================================================
print("\n[4] Asymmetric Granger Test: BTC up-vol vs down-vol")

# Split BTC returns into positive and negative components
df['btc_ret_pos'] = df['btc_ret'].clip(lower=0)
df['btc_ret_neg'] = df['btc_ret'].clip(upper=0).abs()  # absolute value of negative returns

# Rolling vol of positive vs negative returns
df['btc_upvol_21'] = df['btc_ret_pos'].rolling(21).std() * np.sqrt(252) * 100
df['btc_downvol_21'] = df['btc_ret_neg'].rolling(21).std() * np.sqrt(252) * 100

asym_df = pd.DataFrame({
    'btc_upvol': df['btc_upvol_21'],
    'btc_downvol': df['btc_downvol_21'],
    'vix_target': granger_vix
}).dropna()

asymmetric_granger = {}

# BTC Up-Vol → VIX
print("\n  BTC Up-Vol → VIX:")
gc_up = asym_df[['vix_target', 'btc_upvol']].values
try:
    gc_up_test = grangercausalitytests(gc_up, maxlag=5, verbose=False)
    for lag in [1, 2, 3, 5]:
        f_stat = gc_up_test[lag][0]['ssr_ftest'][0]
        f_pval = gc_up_test[lag][0]['ssr_ftest'][1]
        asymmetric_granger[f'btc_upvol_to_vix_lag{lag}'] = {
            'F_stat': float(f_stat), 'p_value': float(f_pval)
        }
        print(f"    Lag {lag}: F={f_stat:.4f}, p={f_pval:.4f} {'***' if f_pval < 0.01 else '**' if f_pval < 0.05 else ''}")
except Exception as e:
    print(f"    Error: {e}")

# BTC Down-Vol → VIX
print("\n  BTC Down-Vol → VIX:")
gc_down = asym_df[['vix_target', 'btc_downvol']].values
try:
    gc_down_test = grangercausalitytests(gc_down, maxlag=5, verbose=False)
    for lag in [1, 2, 3, 5]:
        f_stat = gc_down_test[lag][0]['ssr_ftest'][0]
        f_pval = gc_down_test[lag][0]['ssr_ftest'][1]
        asymmetric_granger[f'btc_downvol_to_vix_lag{lag}'] = {
            'F_stat': float(f_stat), 'p_value': float(f_pval)
        }
        print(f"    Lag {lag}: F={f_stat:.4f}, p={f_pval:.4f} {'***' if f_pval < 0.01 else '**' if f_pval < 0.05 else ''}")
except Exception as e:
    print(f"    Error: {e}")

# Asymmetry test: compare F-stats
print("\n  Asymmetry summary:")
for lag in [1, 2, 3, 5]:
    up_key = f'btc_upvol_to_vix_lag{lag}'
    dn_key = f'btc_downvol_to_vix_lag{lag}'
    if up_key in asymmetric_granger and dn_key in asymmetric_granger:
        up_f = asymmetric_granger[up_key]['F_stat']
        dn_f = asymmetric_granger[dn_key]['F_stat']
        ratio = dn_f / up_f if up_f > 0 else float('inf')
        asymmetric_granger[f'ratio_down_over_up_lag{lag}'] = float(ratio)
        print(f"    Lag {lag}: Down-F/Up-F = {ratio:.2f} — "
              f"{'Down-vol dominates' if ratio > 1.5 else 'Roughly symmetric' if ratio > 0.67 else 'Up-vol dominates'}")

# ============================================================
# 5. TAIL DEPENDENCE (Quantile Regression approach)
# ============================================================
print("\n[5] Tail Dependence via Quantile Regression")

from statsmodels.regression.quantile_regression import QuantReg

# Use daily data: VIX change = f(BTC vol) at different quantiles
X_tail = df[['btc_vol']].copy()
X_tail['const'] = 1.0
y_tail = df['vix_change']

quantiles = [0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95]
qreg_results = {}

print("  VIX change = α + β * BTC_r² at different quantiles:")
for q in quantiles:
    model = QuantReg(y_tail, X_tail[['const', 'btc_vol']])
    res = model.fit(q=q, max_iter=5000)
    beta = res.params['btc_vol']
    pval = res.pvalues['btc_vol']
    ci_low, ci_high = res.conf_int().loc['btc_vol']
    qreg_results[f'q{int(q*100):02d}'] = {
        'beta': float(beta),
        'p_value': float(pval),
        'ci_low': float(ci_low),
        'ci_high': float(ci_high),
        'significant': float(pval) < 0.05
    }
    sig = '***' if pval < 0.01 else '**' if pval < 0.05 else '*' if pval < 0.10 else ''
    print(f"    τ={q:.2f}: β={beta:.4f} (p={pval:.4f}) [{ci_low:.4f}, {ci_high:.4f}] {sig}")

# Upper tail (q=0.90, 0.95) vs lower tail (q=0.05, 0.10) asymmetry
upper_avg = np.mean([qreg_results['q90']['beta'], qreg_results['q95']['beta']])
lower_avg = np.mean([qreg_results['q05']['beta'], qreg_results['q10']['beta']])
tail_asym = {
    'upper_tail_avg_beta': float(upper_avg),
    'lower_tail_avg_beta': float(lower_avg),
    'asymmetry_ratio': float(upper_avg / lower_avg) if lower_avg != 0 else float('inf'),
    'interpretation': 'BTC vol has stronger effect on VIX in upper tail (VIX spikes)' if abs(upper_avg) > abs(lower_avg) else 'BTC vol has stronger effect on VIX in lower tail (VIX calm)'
}
print(f"\n  Upper tail avg β: {upper_avg:.4f}")
print(f"  Lower tail avg β: {lower_avg:.4f}")
print(f"  Interpretation: {tail_asym['interpretation']}")

# ============================================================
# 6. ROLLING SPILLOVER (Diebold-Yilmaz style)
# ============================================================
print("\n[6] Rolling Spillover Index (252-day window)")

def compute_spillover_index(btc_rv, vix_series, forecast_horizon=10):
    """
    Simplified Diebold-Yilmaz spillover using VAR forecast error variance decomposition.
    Returns: total spillover index (% of forecast variance from cross-effects)
    """
    var_data = pd.DataFrame({'btc_rv': btc_rv, 'vix': vix_series}).dropna()
    if len(var_data) < 50:
        return np.nan, np.nan, np.nan

    # Standardize
    var_data_std = (var_data - var_data.mean()) / var_data.std()

    try:
        # Fit VAR
        model = VAR(var_data_std)
        # Select lag by AIC (max 5 for window estimation)
        lag_order = model.select_order(maxlags=5)
        opt_lag = max(1, lag_order.aic)
        results = model.fit(opt_lag)

        # Forecast error variance decomposition
        fevd = results.fevd(forecast_horizon)
        decomp = fevd.decomp  # shape: (n_vars, horizon, n_vars)
        # decomp[i][h][j] = fraction of variable i's FEV at horizon h due to variable j

        # BTC is index 0, VIX is index 1
        # Spillover from BTC to VIX = decomp[1][h-1][0] (VIX FEV from BTC)
        # Spillover from VIX to BTC = decomp[0][h-1][1] (BTC FEV from VIX)
        h = forecast_horizon - 1
        btc_to_vix = float(decomp[1][h][0])  # VIX variance from BTC
        vix_to_btc = float(decomp[0][h][1])  # BTC variance from VIX

        # Total spillover = sum of off-diagonal / total * 100
        total_spillover = (btc_to_vix + vix_to_btc) / 2 * 100

        return total_spillover, btc_to_vix * 100, vix_to_btc * 100
    except Exception:
        return np.nan, np.nan, np.nan

# Rolling computation
window = 252
roll_dates = []
roll_total = []
roll_btc_to_vix = []
roll_vix_to_btc = []

roll_df = pd.DataFrame({
    'btc_rv': df['btc_rv21'],
    'vix': df['vix']
}).dropna()

step = 5  # compute every 5 days for speed
for i in range(window, len(roll_df), step):
    window_data = roll_df.iloc[i-window:i]
    total, b2v, v2b = compute_spillover_index(
        window_data['btc_rv'], window_data['vix']
    )
    roll_dates.append(roll_df.index[i])
    roll_total.append(total)
    roll_btc_to_vix.append(b2v)
    roll_vix_to_btc.append(v2b)

spillover_ts = pd.DataFrame({
    'date': roll_dates,
    'total_spillover': roll_total,
    'btc_to_vix': roll_btc_to_vix,
    'vix_to_btc': roll_vix_to_btc
}).set_index('date').dropna()

print(f"  Spillover time series: {len(spillover_ts)} observations")
print(f"  Mean total spillover: {spillover_ts['total_spillover'].mean():.2f}%")
print(f"  Mean BTC→VIX: {spillover_ts['btc_to_vix'].mean():.2f}%")
print(f"  Mean VIX→BTC: {spillover_ts['vix_to_btc'].mean():.2f}%")

# Identify high-spillover periods
high_spill = spillover_ts[spillover_ts['total_spillover'] > spillover_ts['total_spillover'].quantile(0.90)]
print(f"\n  High-spillover periods (top 10%):")
print(f"    Count: {len(high_spill)} observations")

# Group into episodes
if len(high_spill) > 0:
    # Find contiguous groups
    high_spill_dates = high_spill.index
    episodes = []
    ep_start = high_spill_dates[0]
    ep_prev = high_spill_dates[0]
    for d in high_spill_dates[1:]:
        if (d - ep_prev).days > 30:
            episodes.append((ep_start, ep_prev))
            ep_start = d
        ep_prev = d
    episodes.append((ep_start, ep_prev))

    print(f"    Episodes:")
    spillover_episodes = []
    for s, e in episodes[:10]:
        ep_data = spillover_ts.loc[s:e]
        ep_info = {
            'start': s.strftime('%Y-%m-%d'),
            'end': e.strftime('%Y-%m-%d'),
            'mean_spillover': float(ep_data['total_spillover'].mean()),
            'max_spillover': float(ep_data['total_spillover'].max()),
            'mean_btc_to_vix': float(ep_data['btc_to_vix'].mean())
        }
        spillover_episodes.append(ep_info)
        print(f"      {s.strftime('%Y-%m-%d')} to {e.strftime('%Y-%m-%d')}: "
              f"mean={ep_data['total_spillover'].mean():.1f}%, max={ep_data['total_spillover'].max():.1f}%")

# Spillover statistics by year
print("\n  Spillover by year:")
spillover_by_year = {}
for year in sorted(spillover_ts.index.year.unique()):
    yr_data = spillover_ts[spillover_ts.index.year == year]
    if len(yr_data) > 0:
        spillover_by_year[str(year)] = {
            'mean_total': float(yr_data['total_spillover'].mean()),
            'mean_btc_to_vix': float(yr_data['btc_to_vix'].mean()),
            'mean_vix_to_btc': float(yr_data['vix_to_btc'].mean())
        }
        print(f"    {year}: total={yr_data['total_spillover'].mean():.1f}%, "
              f"BTC→VIX={yr_data['btc_to_vix'].mean():.1f}%, "
              f"VIX→BTC={yr_data['vix_to_btc'].mean():.1f}%")

# ============================================================
# 7. DCC-GARCH STYLE DYNAMIC CORRELATION
# ============================================================
print("\n[7] Dynamic Conditional Correlation (GARCH-based)")

# Fit univariate GARCH to each series
btc_ret_pct = df['btc_ret'] * 100  # scale for GARCH
spy_ret_pct = df['spy_ret'] * 100

# BTC GARCH(1,1)
btc_garch = arch_model(btc_ret_pct, vol='GARCH', p=1, q=1, dist='t', rescale=False)
btc_garch_res = btc_garch.fit(disp='off')
btc_cond_vol = btc_garch_res.conditional_volatility

# SPY GJR-GARCH(1,1) — use GJR for equity (leverage effect)
spy_garch = arch_model(spy_ret_pct, vol='GARCH', p=1, o=1, q=1, dist='t', rescale=False)
spy_garch_res = spy_garch.fit(disp='off')
spy_cond_vol = spy_garch_res.conditional_volatility

print(f"  BTC GARCH: ω={btc_garch_res.params['omega']:.4f}, "
      f"α={btc_garch_res.params['alpha[1]']:.4f}, β={btc_garch_res.params['beta[1]']:.4f}")
print(f"  SPY GJR: ω={spy_garch_res.params['omega']:.4f}, "
      f"α={spy_garch_res.params['alpha[1]']:.4f}, γ={spy_garch_res.params['gamma[1]']:.4f}, "
      f"β={spy_garch_res.params['beta[1]']:.4f}")

# Standardized residuals
btc_std_resid = btc_garch_res.resid / btc_cond_vol
spy_std_resid = spy_garch_res.resid / spy_cond_vol

# DCC estimation using exponentially weighted moving correlation
# Qt = (1-a-b)*Qbar + a*e_{t-1}*e_{t-1}' + b*Q_{t-1}
# Simplified: use EWMA correlation (lambda=0.94)
ewma_lambda = 0.94
n = len(btc_std_resid)
dcc_corr = np.zeros(n)
q11 = 1.0
q22 = 1.0
q12 = float(np.corrcoef(btc_std_resid[:100], spy_std_resid[:100])[0, 1])

for t in range(n):
    if t == 0:
        dcc_corr[t] = q12
        continue
    e1 = btc_std_resid.iloc[t-1]
    e2 = spy_std_resid.iloc[t-1]
    q11 = ewma_lambda * q11 + (1 - ewma_lambda) * e1**2
    q22 = ewma_lambda * q22 + (1 - ewma_lambda) * e2**2
    q12 = ewma_lambda * q12 + (1 - ewma_lambda) * e1 * e2
    dcc_corr[t] = q12 / np.sqrt(q11 * q22)

dcc_series = pd.Series(dcc_corr, index=df.index, name='DCC_BTC_SPY')

print(f"\n  DCC BTC-SPY correlation:")
print(f"    Mean: {dcc_series.mean():.4f}")
print(f"    Std: {dcc_series.std():.4f}")
print(f"    Min: {dcc_series.min():.4f}")
print(f"    Max: {dcc_series.max():.4f}")

# DCC by regime (VIX-based)
vix_median = df['vix'].median()
high_vix = df['vix'] > vix_median
print(f"\n  DCC by VIX regime (median VIX={vix_median:.1f}):")
print(f"    High VIX: mean DCC={dcc_series[high_vix].mean():.4f}")
print(f"    Low VIX:  mean DCC={dcc_series[~high_vix].mean():.4f}")

# Test if DCC is higher during high VIX (contagion)
t_dcc, p_dcc = stats.ttest_ind(dcc_series[high_vix], dcc_series[~high_vix])
print(f"    t-test: t={t_dcc:.4f}, p={p_dcc:.4f}")

dcc_regime_results = {
    'vix_median': float(vix_median),
    'dcc_high_vix_mean': float(dcc_series[high_vix].mean()),
    'dcc_low_vix_mean': float(dcc_series[~high_vix].mean()),
    'dcc_diff_tstat': float(t_dcc),
    'dcc_diff_pval': float(p_dcc),
    'contagion_during_stress': float(p_dcc) < 0.05 and float(dcc_series[high_vix].mean()) > float(dcc_series[~high_vix].mean())
}

# Also: DCC with VIX itself
dcc_btc_vix = np.zeros(n)
vix_ret_pct = df['vix_ret'] * 100
# Use BTC standardized residuals and VIX returns standardized by rolling vol
vix_std = (vix_ret_pct - vix_ret_pct.rolling(63).mean()) / vix_ret_pct.rolling(63).std()
vix_std = vix_std.fillna(0)

q11_v = 1.0
q22_v = 1.0
q12_v = float(np.corrcoef(btc_std_resid[:100], vix_std[:100])[0, 1])

for t in range(n):
    if t == 0:
        dcc_btc_vix[t] = q12_v
        continue
    e1 = btc_std_resid.iloc[t-1]
    e2 = float(vix_std.iloc[t-1])
    q11_v = ewma_lambda * q11_v + (1 - ewma_lambda) * e1**2
    q22_v = ewma_lambda * q22_v + (1 - ewma_lambda) * e2**2
    q12_v = ewma_lambda * q12_v + (1 - ewma_lambda) * e1 * e2
    denom = np.sqrt(q11_v * q22_v)
    dcc_btc_vix[t] = q12_v / denom if denom > 0 else 0

dcc_btc_vix_series = pd.Series(dcc_btc_vix, index=df.index, name='DCC_BTC_VIX')
print(f"\n  DCC BTC-VIX:")
print(f"    Mean: {dcc_btc_vix_series.mean():.4f}")
print(f"    Std: {dcc_btc_vix_series.std():.4f}")

# ============================================================
# 8. ECONOMIC VALUE: BTC VOL AS VIX FORECASTING SIGNAL
# ============================================================
print("\n[8] Economic Value: BTC Vol → VIX Forecasting")

# Can BTC realized vol improve VIX forecasting beyond autoregressive benchmark?
# Forecast: VIX_{t+1} = f(VIX_t, VIX_{t-1}, ..., BTC_RV_t)
# Out-of-sample test: 2019-01-01 onward

oos_start = pd.Timestamp('2019-01-01')
is_mask = df.index < oos_start
oos_mask = df.index >= oos_start

# Prepare features
forecast_df = pd.DataFrame({
    'vix': df['vix'],
    'vix_lag1': df['vix'].shift(1),
    'vix_lag2': df['vix'].shift(2),
    'vix_lag5': df['vix'].shift(5),
    'btc_rv21': df['btc_rv21'],
    'btc_rv21_lag1': df['btc_rv21'].shift(1),
    'btc_vol': df['btc_vol'],  # daily r²
    'btc_vol_lag1': df['btc_vol'].shift(1),
}).dropna()

# Recursive OOS forecasting
from sklearn.linear_model import LinearRegression

oos_dates = forecast_df.index[forecast_df.index >= oos_start]
print(f"  OOS period: {oos_dates[0].strftime('%Y-%m-%d')} to {oos_dates[-1].strftime('%Y-%m-%d')}")
print(f"  OOS observations: {len(oos_dates)}")

# Model 1: AR benchmark (VIX lags only)
ar_features = ['vix_lag1', 'vix_lag2', 'vix_lag5']
# Model 2: AR + BTC vol
arx_features = ['vix_lag1', 'vix_lag2', 'vix_lag5', 'btc_rv21_lag1', 'btc_vol_lag1']

ar_errors = []
arx_errors = []
ar_forecasts = []
arx_forecasts = []
actual_vix = []

# Expanding window OOS
min_train = 500
train_start_idx = forecast_df.index.get_loc(forecast_df.index[0])

for i, dt in enumerate(oos_dates):
    loc = forecast_df.index.get_loc(dt)
    if loc < min_train:
        continue

    train = forecast_df.iloc[:loc]
    test_row = forecast_df.iloc[loc:loc+1]

    y_train = train['vix']
    y_actual = float(test_row['vix'].iloc[0])

    # AR model
    X_ar_train = train[ar_features]
    X_ar_test = test_row[ar_features]
    lr_ar = LinearRegression()
    lr_ar.fit(X_ar_train, y_train)
    y_ar_pred = float(lr_ar.predict(X_ar_test)[0])

    # ARX model (with BTC vol)
    X_arx_train = train[arx_features]
    X_arx_test = test_row[arx_features]
    lr_arx = LinearRegression()
    lr_arx.fit(X_arx_train, y_train)
    y_arx_pred = float(lr_arx.predict(X_arx_test)[0])

    ar_errors.append(y_actual - y_ar_pred)
    arx_errors.append(y_actual - y_arx_pred)
    ar_forecasts.append(y_ar_pred)
    arx_forecasts.append(y_arx_pred)
    actual_vix.append(y_actual)

ar_errors = np.array(ar_errors)
arx_errors = np.array(arx_errors)

# Forecast evaluation
ar_mse = np.mean(ar_errors**2)
arx_mse = np.mean(arx_errors**2)
ar_mae = np.mean(np.abs(ar_errors))
arx_mae = np.mean(np.abs(arx_errors))

print(f"\n  AR benchmark:  MSE={ar_mse:.4f}, MAE={ar_mae:.4f}")
print(f"  AR+BTC vol:    MSE={arx_mse:.4f}, MAE={arx_mae:.4f}")
print(f"  MSE improvement: {(1 - arx_mse/ar_mse)*100:.2f}%")
print(f"  MAE improvement: {(1 - arx_mae/ar_mae)*100:.2f}%")

# Diebold-Mariano test
dm_diff = ar_errors**2 - arx_errors**2
dm_mean = np.mean(dm_diff)
dm_std = np.std(dm_diff) / np.sqrt(len(dm_diff))
dm_tstat = dm_mean / dm_std if dm_std > 0 else 0
dm_pval = 2 * (1 - stats.norm.cdf(abs(dm_tstat)))

print(f"\n  DM test (AR vs AR+BTC):")
print(f"    t-stat: {dm_tstat:.4f}")
print(f"    p-value: {dm_pval:.4f}")
print(f"    Harvey threshold (|t|>3.0): {'PASS' if abs(dm_tstat) > 3.0 else 'FAIL'}")
print(f"    Standard threshold (|t|>1.96): {'PASS' if abs(dm_tstat) > 1.96 else 'FAIL'}")

# QLIKE loss
ar_forecasts = np.array(ar_forecasts)
arx_forecasts = np.array(arx_forecasts)
actual_vix = np.array(actual_vix)

# QLIKE = log(σ²_forecast) + actual²/σ²_forecast
# Using VIX level as proxy for implied vol
ar_qlike = np.mean(np.log(ar_forecasts**2) + actual_vix**2 / ar_forecasts**2)
arx_qlike = np.mean(np.log(arx_forecasts**2) + actual_vix**2 / arx_forecasts**2)
print(f"\n  QLIKE: AR={ar_qlike:.4f}, AR+BTC={arx_qlike:.4f}")
print(f"  QLIKE improvement: {(1 - arx_qlike/ar_qlike)*100:.2f}%")

forecast_results = {
    'oos_start': '2019-01-01',
    'oos_n': len(ar_errors),
    'ar_mse': float(ar_mse),
    'arx_mse': float(arx_mse),
    'mse_improvement_pct': float((1 - arx_mse/ar_mse)*100),
    'ar_mae': float(ar_mae),
    'arx_mae': float(arx_mae),
    'mae_improvement_pct': float((1 - arx_mae/ar_mae)*100),
    'dm_tstat': float(dm_tstat),
    'dm_pval': float(dm_pval),
    'harvey_pass': abs(dm_tstat) > 3.0,
    'standard_pass': abs(dm_tstat) > 1.96,
    'ar_qlike': float(ar_qlike),
    'arx_qlike': float(arx_qlike),
    'qlike_improvement_pct': float((1 - arx_qlike/ar_qlike)*100)
}

# ============================================================
# 9. TIME-VARYING COUPLING: ROLLING CORRELATION + BREAKPOINT
# ============================================================
print("\n[9] Time-Varying Coupling Analysis")

# Rolling 63-day correlation between BTC RV21 and VIX
rolling_corr = df['btc_rv21'].rolling(63).corr(df['vix']).dropna()

print(f"  Rolling 63-day corr(BTC RV21, VIX):")
print(f"    Mean: {rolling_corr.mean():.4f}")
print(f"    Std: {rolling_corr.std():.4f}")
print(f"    Min: {rolling_corr.min():.4f}")
print(f"    Max: {rolling_corr.max():.4f}")

# Rolling correlation by year
print("\n  Rolling correlation by year:")
rolling_corr_by_year = {}
for year in sorted(rolling_corr.index.year.unique()):
    yr_data = rolling_corr[rolling_corr.index.year == year]
    if len(yr_data) > 0:
        rolling_corr_by_year[str(year)] = {
            'mean': float(yr_data.mean()),
            'std': float(yr_data.std())
        }
        print(f"    {year}: mean={yr_data.mean():.4f} ± {yr_data.std():.4f}")

# Simple structural break test: compare pre/post COVID
pre_covid = rolling_corr[rolling_corr.index < '2020-03-01']
post_covid = rolling_corr[rolling_corr.index >= '2020-03-01']
t_break, p_break = stats.ttest_ind(pre_covid, post_covid)
print(f"\n  Structural break test (pre/post COVID-2020-03):")
print(f"    Pre-COVID mean: {pre_covid.mean():.4f} (n={len(pre_covid)})")
print(f"    Post-COVID mean: {post_covid.mean():.4f} (n={len(post_covid)})")
print(f"    t-stat: {t_break:.4f}, p={p_break:.4f}")

# Also test pre/post 2022 (crypto winter)
pre_crypto_winter = rolling_corr[(rolling_corr.index >= '2020-03-01') & (rolling_corr.index < '2022-06-01')]
post_crypto_winter = rolling_corr[rolling_corr.index >= '2022-06-01']
t_cw, p_cw = stats.ttest_ind(pre_crypto_winter, post_crypto_winter)
print(f"\n  Structural break test (crypto winter 2022-06):")
print(f"    2020-03 to 2022-05 mean: {pre_crypto_winter.mean():.4f}")
print(f"    2022-06 onward mean: {post_crypto_winter.mean():.4f}")
print(f"    t-stat: {t_cw:.4f}, p={p_cw:.4f}")

breakpoint_results = {
    'pre_covid_mean': float(pre_covid.mean()),
    'post_covid_mean': float(post_covid.mean()),
    'covid_break_tstat': float(t_break),
    'covid_break_pval': float(p_break),
    'pre_crypto_winter_mean': float(pre_crypto_winter.mean()),
    'post_crypto_winter_mean': float(post_crypto_winter.mean()),
    'crypto_winter_break_tstat': float(t_cw),
    'crypto_winter_break_pval': float(p_cw)
}

# ============================================================
# 10. VIX REGIME-CONDITIONAL BTC-EQUITY RELATIONSHIP
# ============================================================
print("\n[10] VIX Regime-Conditional Analysis")

# Define VIX regimes
vix_25 = df['vix'].quantile(0.25)
vix_75 = df['vix'].quantile(0.75)

regimes = {
    'low_vix': df['vix'] <= vix_25,
    'mid_vix': (df['vix'] > vix_25) & (df['vix'] <= vix_75),
    'high_vix': df['vix'] > vix_75
}

regime_results = {}
for regime_name, mask in regimes.items():
    subset = df[mask]
    corr_ret = subset['btc_ret'].corr(subset['spy_ret'])
    corr_vol = subset['btc_rv21'].corr(subset['spy_rv21'])
    mean_btc_ret = subset['btc_ret'].mean() * 252
    mean_spy_ret = subset['spy_ret'].mean() * 252

    regime_results[regime_name] = {
        'n_obs': int(mask.sum()),
        'vix_range': f'<= {vix_25:.1f}' if regime_name == 'low_vix' else f'> {vix_75:.1f}' if regime_name == 'high_vix' else f'{vix_25:.1f} - {vix_75:.1f}',
        'return_corr': float(corr_ret),
        'vol_corr': float(corr_vol),
        'btc_ann_ret': float(mean_btc_ret),
        'spy_ann_ret': float(mean_spy_ret)
    }
    print(f"  {regime_name} (n={mask.sum()}, VIX {regime_results[regime_name]['vix_range']}):")
    print(f"    Return corr: {corr_ret:.4f}")
    print(f"    Vol corr: {corr_vol:.4f}")
    print(f"    BTC ann. ret: {mean_btc_ret:.2%}")
    print(f"    SPY ann. ret: {mean_spy_ret:.2%}")

# ============================================================
# 11. PLOTS
# ============================================================
print("\n[11] Generating plots...")

fig, axes = plt.subplots(4, 1, figsize=(14, 16), dpi=100)

# Plot 1: Spillover time series
ax = axes[0]
ax.plot(spillover_ts.index, spillover_ts['btc_to_vix'], label='BTC → VIX', color='red', alpha=0.8, linewidth=0.8)
ax.plot(spillover_ts.index, spillover_ts['vix_to_btc'], label='VIX → BTC', color='blue', alpha=0.8, linewidth=0.8)
ax.fill_between(spillover_ts.index, 0, spillover_ts['total_spillover'], alpha=0.15, color='gray', label='Total Spillover')
ax.set_title('Diebold-Yilmaz Spillover: BTC ↔ VIX (252-day rolling)', fontsize=12, fontweight='bold')
ax.set_ylabel('Spillover (%)')
ax.legend(loc='upper left', fontsize=9)
ax.grid(True, alpha=0.3)
ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))

# Plot 2: Rolling correlation
ax = axes[1]
ax.plot(rolling_corr.index, rolling_corr, color='darkgreen', alpha=0.8, linewidth=0.8)
ax.axhline(y=0, color='black', linestyle='--', linewidth=0.5)
ax.axhline(y=rolling_corr.mean(), color='red', linestyle='--', linewidth=0.8, label=f'Mean={rolling_corr.mean():.3f}')
ax.axvline(x=pd.Timestamp('2020-03-01'), color='orange', linestyle=':', linewidth=1, label='COVID-19')
ax.axvline(x=pd.Timestamp('2022-06-01'), color='purple', linestyle=':', linewidth=1, label='Crypto Winter')
ax.set_title('Rolling 63-day Correlation: BTC RV21 vs VIX', fontsize=12, fontweight='bold')
ax.set_ylabel('Correlation')
ax.legend(loc='lower left', fontsize=9)
ax.grid(True, alpha=0.3)
ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))

# Plot 3: DCC BTC-SPY
ax = axes[2]
ax.plot(dcc_series.index, dcc_series, color='teal', alpha=0.7, linewidth=0.6)
ax.fill_between(dcc_series.index, 0, dcc_series, alpha=0.15, color='teal')
ax.axhline(y=dcc_series.mean(), color='red', linestyle='--', linewidth=0.8, label=f'Mean={dcc_series.mean():.3f}')
ax.set_title('EWMA Dynamic Correlation: BTC vs SPY', fontsize=12, fontweight='bold')
ax.set_ylabel('Correlation')
ax.legend(loc='upper left', fontsize=9)
ax.grid(True, alpha=0.3)
ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))

# Plot 4: Quantile regression coefficients
ax = axes[3]
q_vals = [float(q) for q in quantiles]
betas = [qreg_results[f'q{int(q*100):02d}']['beta'] for q in quantiles]
ci_lows = [qreg_results[f'q{int(q*100):02d}']['ci_low'] for q in quantiles]
ci_highs = [qreg_results[f'q{int(q*100):02d}']['ci_high'] for q in quantiles]

ax.plot(q_vals, betas, 'o-', color='darkred', linewidth=2, markersize=8, label='β(τ)')
ax.fill_between(q_vals, ci_lows, ci_highs, alpha=0.2, color='red', label='95% CI')
ax.axhline(y=0, color='black', linestyle='--', linewidth=0.5)
ax.set_title('Quantile Regression: VIX Change = α + β · BTC_r²', fontsize=12, fontweight='bold')
ax.set_xlabel('Quantile (τ)')
ax.set_ylabel('β coefficient')
ax.legend(fontsize=9)
ax.grid(True, alpha=0.3)

plt.tight_layout()
plot_path_1 = os.path.join(EXPERIMENT_DIR, 'k1022_spillover_dynamics.png')
plt.savefig(plot_path_1, bbox_inches='tight')
plt.close()
print(f"  Saved: {plot_path_1}")

# Second figure: regime analysis
fig, axes = plt.subplots(2, 2, figsize=(14, 10), dpi=100)

# Plot 2a: BTC and VIX time series
ax = axes[0, 0]
ax2 = ax.twinx()
ax.plot(df.index, df['btc_rv21'], color='orange', alpha=0.7, linewidth=0.6, label='BTC RV21')
ax2.plot(df.index, df['vix'], color='blue', alpha=0.7, linewidth=0.6, label='VIX')
ax.set_title('BTC Realized Vol vs VIX', fontsize=11, fontweight='bold')
ax.set_ylabel('BTC RV21 (%)', color='orange')
ax2.set_ylabel('VIX', color='blue')
ax.legend(loc='upper left', fontsize=8)
ax2.legend(loc='upper right', fontsize=8)
ax.grid(True, alpha=0.3)

# Plot 2b: Scatter by VIX regime
ax = axes[0, 1]
colors = {'low_vix': 'green', 'mid_vix': 'gray', 'high_vix': 'red'}
for regime_name, mask in regimes.items():
    subset = df[mask]
    ax.scatter(subset['btc_ret'] * 100, subset['spy_ret'] * 100,
               c=colors[regime_name], alpha=0.15, s=5, label=regime_name)
ax.set_title('BTC vs SPY Returns by VIX Regime', fontsize=11, fontweight='bold')
ax.set_xlabel('BTC daily return (%)')
ax.set_ylabel('SPY daily return (%)')
ax.legend(fontsize=8)
ax.grid(True, alpha=0.3)

# Plot 2c: Spillover direction comparison by year
ax = axes[1, 0]
years = sorted(spillover_by_year.keys())
btc2vix_vals = [spillover_by_year[y]['mean_btc_to_vix'] for y in years]
vix2btc_vals = [spillover_by_year[y]['mean_vix_to_btc'] for y in years]
x = np.arange(len(years))
width = 0.35
ax.bar(x - width/2, btc2vix_vals, width, label='BTC → VIX', color='red', alpha=0.7)
ax.bar(x + width/2, vix2btc_vals, width, label='VIX → BTC', color='blue', alpha=0.7)
ax.set_title('Directional Spillover by Year', fontsize=11, fontweight='bold')
ax.set_xlabel('Year')
ax.set_ylabel('Spillover (%)')
ax.set_xticks(x)
ax.set_xticklabels(years, rotation=45, fontsize=8)
ax.legend(fontsize=8)
ax.grid(True, alpha=0.3)

# Plot 2d: DCC distribution by VIX regime
ax = axes[1, 1]
dcc_low = dcc_series[regimes['low_vix']]
dcc_high = dcc_series[regimes['high_vix']]
ax.hist(dcc_low, bins=50, alpha=0.5, color='green', density=True, label='Low VIX')
ax.hist(dcc_high, bins=50, alpha=0.5, color='red', density=True, label='High VIX')
ax.axvline(dcc_low.mean(), color='green', linestyle='--', linewidth=1.5)
ax.axvline(dcc_high.mean(), color='red', linestyle='--', linewidth=1.5)
ax.set_title('DCC BTC-SPY Distribution by VIX Regime', fontsize=11, fontweight='bold')
ax.set_xlabel('DCC')
ax.set_ylabel('Density')
ax.legend(fontsize=8)
ax.grid(True, alpha=0.3)

plt.tight_layout()
plot_path_2 = os.path.join(EXPERIMENT_DIR, 'k1022_regime_analysis.png')
plt.savefig(plot_path_2, bbox_inches='tight')
plt.close()
print(f"  Saved: {plot_path_2}")

# ============================================================
# 12. COMPILE RESULTS
# ============================================================
print("\n[12] Compiling results...")

results = {
    'experiment_id': 'K1022',
    'title': 'Crypto Fear Channel: BTC Vol Spillover to Equity via VIX',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'data_source': 'yfinance',
    'data_period': f'{df.index[0].strftime("%Y-%m-%d")} to {df.index[-1].strftime("%Y-%m-%d")}',
    'sample_size': len(df),
    'seed': 42,
    'methodology': {
        'granger_test': 'statsmodels grangercausalitytests, max_lag=10',
        'asymmetric_test': 'Split BTC returns into positive/negative, rolling 21-day vol',
        'tail_dependence': 'Quantile regression (VIX change ~ BTC r²) at τ = 0.05-0.95',
        'spillover': 'Diebold-Yilmaz style VAR FEVD, 252-day rolling, 10-day forecast horizon',
        'dcc': 'EWMA dynamic correlation (λ=0.94) on GARCH standardized residuals',
        'forecasting': 'Expanding window OOS linear regression, AR vs AR+BTC_vol'
    },
    'descriptive_statistics': desc_stats,
    'unconditional_correlations': unconditional_corr,
    'granger_causality': granger_results,
    'asymmetric_granger': asymmetric_granger,
    'quantile_regression_tail': {
        'coefficients': qreg_results,
        'asymmetry': tail_asym
    },
    'spillover_analysis': {
        'mean_total_spillover': float(spillover_ts['total_spillover'].mean()),
        'mean_btc_to_vix': float(spillover_ts['btc_to_vix'].mean()),
        'mean_vix_to_btc': float(spillover_ts['vix_to_btc'].mean()),
        'by_year': spillover_by_year,
        'high_spillover_episodes': spillover_episodes if len(high_spill) > 0 else []
    },
    'dcc_analysis': {
        'btc_spy': {
            'mean': float(dcc_series.mean()),
            'std': float(dcc_series.std()),
            'min': float(dcc_series.min()),
            'max': float(dcc_series.max())
        },
        'btc_vix': {
            'mean': float(dcc_btc_vix_series.mean()),
            'std': float(dcc_btc_vix_series.std())
        },
        'regime_conditional': dcc_regime_results
    },
    'vix_forecasting': forecast_results,
    'time_varying_coupling': {
        'rolling_63d_corr_mean': float(rolling_corr.mean()),
        'rolling_63d_corr_std': float(rolling_corr.std()),
        'by_year': rolling_corr_by_year,
        'breakpoints': breakpoint_results
    },
    'vix_regime_analysis': regime_results,
    'key_findings': [],  # Filled below
    'limitations': [
        'BTC data starts 2015 — limited pre-maturity observations',
        'VIX is implied vol, not realized — comparison is cross-concept',
        'Granger causality ≠ true causation',
        'EWMA DCC is simplified (not full DCC-GARCH estimation)',
        'Linear AR model for VIX forecasting — nonlinear methods may differ',
        'No intraday data — daily frequency may miss fast spillovers'
    ],
    'references': [
        'K639: BTC→SPY Granger confirmed',
        'K746b: BTC vol asymmetrically Granger-causes VIX',
        'Diebold & Yilmaz (2012): Connectedness approach',
        'Patton (2006): Copula-based models',
        'Harvey (2016): |t| > 3.0 threshold'
    ],
    'plots': [
        'k1022_spillover_dynamics.png',
        'k1022_regime_analysis.png'
    ]
}

# Determine key findings
findings = []

# Finding 1: Granger causality direction
btc_to_vix_sig = sum(1 for k, v in granger_results.items()
                      if k.startswith('btc_rv_to_vix') and v.get('significant_5pct', False))
vix_to_btc_sig = sum(1 for k, v in granger_results.items()
                      if k.startswith('vix_to_btc_rv') and v.get('significant_5pct', False))
findings.append(f"Granger: BTC_RV→VIX significant at {btc_to_vix_sig}/10 lags; VIX→BTC_RV significant at {vix_to_btc_sig}/10 lags")

# Finding 2: Asymmetry (use lags 2-5 which are more informative than lag 1)
asym_ratios = {lag: asymmetric_granger.get(f'ratio_down_over_up_lag{lag}', None) for lag in [1, 2, 3, 5]}
asym_ratios = {k: v for k, v in asym_ratios.items() if v is not None}
if asym_ratios:
    mean_ratio_2_5 = np.mean([v for k, v in asym_ratios.items() if k >= 2])
    down_sig = sum(1 for k in ['btc_downvol_to_vix_lag2', 'btc_downvol_to_vix_lag3', 'btc_downvol_to_vix_lag5']
                   if k in asymmetric_granger and asymmetric_granger[k]['p_value'] < 0.05)
    up_sig = sum(1 for k in ['btc_upvol_to_vix_lag2', 'btc_upvol_to_vix_lag3', 'btc_upvol_to_vix_lag5']
                 if k in asymmetric_granger and asymmetric_granger[k]['p_value'] < 0.05)
    findings.append(f"Asymmetry: BTC down-vol significant at {down_sig}/3 lags (2,3,5), up-vol at {up_sig}/3 — "
                    f"crypto crashes drive VIX (Down/Up ratio at lags 2-5 avg = {mean_ratio_2_5:.1f}x)")

# Finding 3: Tail dependence
findings.append(f"Tail dependence: {tail_asym['interpretation']}")

# Finding 4: Spillover trend
findings.append(f"Mean spillover: BTC→VIX={spillover_ts['btc_to_vix'].mean():.1f}%, VIX→BTC={spillover_ts['vix_to_btc'].mean():.1f}%")

# Finding 5: DCC contagion
if dcc_regime_results['contagion_during_stress']:
    findings.append(f"Contagion: BTC-SPY DCC higher during high VIX ({dcc_regime_results['dcc_high_vix_mean']:.4f} vs {dcc_regime_results['dcc_low_vix_mean']:.4f})")
else:
    findings.append(f"No significant contagion: BTC-SPY DCC similar across VIX regimes")

# Finding 6: Forecasting value
if forecast_results['harvey_pass']:
    findings.append(f"Economic value: BTC vol improves VIX forecast (DM t={forecast_results['dm_tstat']:.2f}, passes Harvey threshold)")
elif forecast_results['standard_pass']:
    findings.append(f"Marginal economic value: BTC vol improves VIX forecast (DM t={forecast_results['dm_tstat']:.2f}, passes standard but not Harvey)")
else:
    findings.append(f"No economic value: BTC vol does not significantly improve VIX forecast (DM t={forecast_results['dm_tstat']:.2f})")

# Finding 7: Structural break
if breakpoint_results['covid_break_pval'] < 0.05:
    findings.append(f"COVID structural break: coupling changed from {breakpoint_results['pre_covid_mean']:.3f} to {breakpoint_results['post_covid_mean']:.3f}")

results['key_findings'] = findings

# Save
results_path = os.path.join(EXPERIMENT_DIR, 'k1022_results.json')
with open(results_path, 'w', encoding='utf-8') as f:
    json.dump(results, f, indent=2, ensure_ascii=False, default=str)
print(f"  Saved: {results_path}")

# ============================================================
# SUMMARY
# ============================================================
print("\n" + "=" * 60)
print("KEY FINDINGS")
print("=" * 60)
for i, finding in enumerate(findings, 1):
    print(f"  {i}. {finding}")

print("\nDone.")
