"""
K1028: Financial Stock Early Warning System - Fubon/Financial ETF -> TSMC/0050.TW Vol Transmission

Research Questions:
1. Do Taiwan financial stocks (2881 Fubon, 0055 Financial ETF) volatility lead 0050.TW/TSMC?
2. Can financial stress indicators serve as regime overlay for Taiwan VT?
3. How much overlap with VIX information?

Related: K757 (Fubon->TSMC Granger F=6.11), K55/K82/K88 (Taiwan VT guide)

Data: yfinance 2015-2026
References:
- Granger (1969) causality framework
- Engle & Kroner (1995) BEKK for volatility transmission
- Patton (2011) QLIKE for model evaluation

Author: VolPred Research System (Claude)
Date: 2026-04-10
"""

import numpy as np
import pandas as pd
import yfinance as yf
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec
import json
import warnings
import os
from datetime import datetime, timezone
from scipy import stats
from statsmodels.tsa.stattools import grangercausalitytests
from arch import arch_model

warnings.filterwarnings('ignore')
np.random.seed(42)

# ============================================================
# CONFIGURATION
# ============================================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TICKERS = {
    '0050.TW': 'Taiwan 50 ETF',
    '2330.TW': 'TSMC',
    '2881.TW': 'Fubon Financial',
    '0055.TW': 'Yuanta Financial ETF',
    '^VIX': 'VIX'
}
START_DATE = '2015-01-01'
END_DATE = '2026-04-09'
GRANGER_MAX_LAG = 5
FINSTRESS_WINDOW = 22  # ~1 month rolling window
FINSTRESS_PERCENTILE = 80
VT_SIGMA = 8.63  # K55 standard

# ============================================================
# STEP 0: DATA COLLECTION
# ============================================================
print("=" * 70)
print("K1028: Financial Stock Early Warning System")
print("=" * 70)

print("\n[Step 0] Downloading data...")
data = {}
for ticker, name in TICKERS.items():
    try:
        df = yf.download(ticker, start=START_DATE, end=END_DATE, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
        data[ticker] = df
        print(f"  {ticker} ({name}): {len(df)} rows, {df.index[0].date()} to {df.index[-1].date()}")
    except Exception as e:
        print(f"  ERROR downloading {ticker}: {e}")

# Build returns DataFrame using pct_change (avoids split issues per CLAUDE.md)
returns = pd.DataFrame()
for ticker in TICKERS:
    if ticker in data and len(data[ticker]) > 0:
        returns[ticker] = data[ticker]['Close'].pct_change()

returns = returns.dropna()
print(f"\nCommon sample: {len(returns)} days, {returns.index[0].date()} to {returns.index[-1].date()}")

# Compute realized vol (squared returns) for each asset
sq_returns = returns ** 2

# ============================================================
# STEP 1: DESCRIPTIVE STATISTICS & DATA DIAGNOSTICS
# ============================================================
print("\n" + "=" * 70)
print("[Step 1] Descriptive Statistics")
print("=" * 70)

desc_stats = {}
for col in returns.columns:
    r = returns[col].dropna()
    desc_stats[col] = {
        'N': len(r),
        'mean': float(r.mean()),
        'std': float(r.std()),
        'skew': float(r.skew()),
        'kurtosis': float(r.kurtosis()),
        'min': float(r.min()),
        'max': float(r.max()),
        'ann_vol': float(r.std() * np.sqrt(252))
    }
    print(f"\n  {col} ({TICKERS.get(col, '')}):")
    print(f"    N={desc_stats[col]['N']}, Mean={desc_stats[col]['mean']:.6f}, "
          f"Std={desc_stats[col]['std']:.4f}")
    print(f"    Skew={desc_stats[col]['skew']:.3f}, Kurt={desc_stats[col]['kurtosis']:.3f}")
    print(f"    Ann Vol={desc_stats[col]['ann_vol']:.4f}")

# Check liquidity for 0055.TW
if '0055.TW' in data:
    vol_0055 = data['0055.TW']['Volume']
    avg_vol = vol_0055.mean()
    min_vol = vol_0055.min()
    zero_vol_days = (vol_0055 == 0).sum()
    print(f"\n  0055.TW Liquidity Check:")
    print(f"    Avg daily volume: {avg_vol:,.0f}")
    print(f"    Min daily volume: {min_vol:,.0f}")
    print(f"    Zero-volume days: {zero_vol_days}")

# ADF test for stationarity
from statsmodels.tsa.stattools import adfuller
print("\n  ADF Tests (returns):")
adf_results = {}
for col in returns.columns:
    result = adfuller(returns[col].dropna(), maxlag=10, autolag='AIC')
    adf_results[col] = {'stat': result[0], 'pvalue': result[1]}
    print(f"    {col}: ADF={result[0]:.4f}, p={result[1]:.6f} {'***' if result[1]<0.01 else ''}")

# Contemporaneous correlations
print("\n  Contemporaneous Return Correlations:")
corr_matrix = returns.corr()
print(corr_matrix.round(3).to_string())

# ============================================================
# STEP 2: GRANGER CAUSALITY TESTS
# ============================================================
print("\n" + "=" * 70)
print("[Step 2] Granger Causality Tests")
print("=" * 70)

# Use squared returns (volatility proxy) for Granger tests
granger_pairs = [
    ('2881.TW', '0050.TW', 'Fubon -> 0050'),
    ('0055.TW', '0050.TW', 'FinETF -> 0050'),
    ('2881.TW', '2330.TW', 'Fubon -> TSMC'),
    ('0055.TW', '2330.TW', 'FinETF -> TSMC'),
    ('^VIX', '0050.TW', 'VIX -> 0050'),
    ('0050.TW', '2881.TW', '0050 -> Fubon (reverse)'),
]

granger_results = {}
for cause, effect, label in granger_pairs:
    if cause not in sq_returns.columns or effect not in sq_returns.columns:
        print(f"  SKIP {label}: missing data")
        continue

    # Granger test on squared returns (volatility proxy)
    test_data = pd.DataFrame({
        'y': sq_returns[effect],
        'x': sq_returns[cause]
    }).dropna()

    print(f"\n  {label} (on r^2, N={len(test_data)}):")
    try:
        gc = grangercausalitytests(test_data[['y', 'x']], maxlag=GRANGER_MAX_LAG, verbose=False)
        best_lag = None
        best_f = 0
        best_p = 1
        lag_results = {}
        for lag in range(1, GRANGER_MAX_LAG + 1):
            f_stat = gc[lag][0]['ssr_ftest'][0]
            p_val = gc[lag][0]['ssr_ftest'][1]
            lag_results[lag] = {'F': float(f_stat), 'p': float(p_val)}
            sig = '***' if p_val < 0.01 else ('**' if p_val < 0.05 else ('*' if p_val < 0.10 else ''))
            print(f"    Lag {lag}: F={f_stat:.3f}, p={p_val:.4f} {sig}")
            if f_stat > best_f:
                best_f = f_stat
                best_p = p_val
                best_lag = lag

        granger_results[label] = {
            'cause': cause,
            'effect': effect,
            'best_lag': best_lag,
            'best_F': float(best_f),
            'best_p': float(best_p),
            'all_lags': lag_results,
            'significant_at_5pct': best_p < 0.05
        }
    except Exception as e:
        print(f"    ERROR: {e}")
        granger_results[label] = {'error': str(e)}

# ============================================================
# STEP 2b: PARTIAL GRANGER (controlling for VIX)
# ============================================================
print("\n" + "-" * 50)
print("[Step 2b] Partial Granger Causality (controlling for VIX)")
print("-" * 50)

# Manual partial Granger: regress out VIX effect first, then test residuals
from statsmodels.regression.linear_model import OLS
from statsmodels.tools import add_constant

partial_granger_results = {}
for cause, effect, label in [('2881.TW', '0050.TW', 'Fubon -> 0050'),
                               ('0055.TW', '0050.TW', 'FinETF -> 0050'),
                               ('2881.TW', '2330.TW', 'Fubon -> TSMC')]:
    if cause not in sq_returns.columns or effect not in sq_returns.columns or '^VIX' not in returns.columns:
        continue

    # Build dataset with lagged values
    df_test = pd.DataFrame()
    df_test['y'] = sq_returns[effect]
    for lag in range(1, 4):  # Use 3 lags for VIX control
        df_test[f'y_lag{lag}'] = sq_returns[effect].shift(lag)
        df_test[f'vix_lag{lag}'] = (returns['^VIX'].shift(lag)) ** 2  # VIX squared change
        df_test[f'cause_lag{lag}'] = sq_returns[cause].shift(lag)

    df_test = df_test.dropna()

    # Restricted model: y ~ y_lags + vix_lags
    y = df_test['y']
    X_restricted = df_test[[f'y_lag{i}' for i in range(1, 4)] + [f'vix_lag{i}' for i in range(1, 4)]]
    X_restricted = add_constant(X_restricted)

    # Unrestricted model: y ~ y_lags + vix_lags + cause_lags
    X_unrestricted = df_test[[f'y_lag{i}' for i in range(1, 4)] +
                              [f'vix_lag{i}' for i in range(1, 4)] +
                              [f'cause_lag{i}' for i in range(1, 4)]]
    X_unrestricted = add_constant(X_unrestricted)

    model_r = OLS(y, X_restricted).fit()
    model_u = OLS(y, X_unrestricted).fit()

    # F-test for restriction
    n = len(y)
    k_r = X_restricted.shape[1]
    k_u = X_unrestricted.shape[1]
    q = k_u - k_r  # number of restrictions

    ssr_r = model_r.ssr
    ssr_u = model_u.ssr

    F_stat = ((ssr_r - ssr_u) / q) / (ssr_u / (n - k_u))
    p_val = 1 - stats.f.cdf(F_stat, q, n - k_u)

    sig = '***' if p_val < 0.01 else ('**' if p_val < 0.05 else ('*' if p_val < 0.10 else 'ns'))
    print(f"  {label} | VIX-controlled: F={F_stat:.3f}, p={p_val:.4f} {sig}")

    partial_granger_results[label] = {
        'F_stat': float(F_stat),
        'p_value': float(p_val),
        'significant_at_5pct': p_val < 0.05,
        'n_obs': int(n),
        'vix_controlled': True
    }

# ============================================================
# STEP 3: FINANCIAL STRESS INDICATOR CONSTRUCTION
# ============================================================
print("\n" + "=" * 70)
print("[Step 3] Financial Stress Indicator Construction")
print("=" * 70)

# Method 1: 22-day rolling vol of 0055.TW (financial ETF)
if '0055.TW' in returns.columns:
    fin_stress_vol = returns['0055.TW'].rolling(FINSTRESS_WINDOW).std() * np.sqrt(252)
    fin_stress_vol.name = 'FinStress_Vol'

    # Method 2: 2881 5-day return momentum (negative = stress)
    fin_stress_momentum = returns['2881.TW'].rolling(5).mean()
    fin_stress_momentum.name = 'FinStress_Mom'

    # Method 3: Combined indicator (z-score)
    fin_stress_z = (fin_stress_vol - fin_stress_vol.expanding().mean()) / fin_stress_vol.expanding().std()
    fin_stress_z.name = 'FinStress_Z'

    # High stress indicator
    threshold_vol = fin_stress_vol.expanding().quantile(FINSTRESS_PERCENTILE / 100)
    high_stress = (fin_stress_vol > threshold_vol).astype(int)
    high_stress.name = 'HighStress'

    # Statistics
    stress_pct = high_stress.dropna().mean() * 100
    print(f"  FinStress (22-day rolling vol of 0055.TW):")
    print(f"    Mean: {fin_stress_vol.dropna().mean():.4f}")
    print(f"    Median: {fin_stress_vol.dropna().median():.4f}")
    print(f"    Std: {fin_stress_vol.dropna().std():.4f}")
    print(f"    High stress days (>P{FINSTRESS_PERCENTILE}): {stress_pct:.1f}%")

    # Conditional analysis: 0050 vol during high vs low stress
    combined = pd.DataFrame({
        'r2_0050': sq_returns['0050.TW'],
        'high_stress': high_stress,
        'fin_stress_vol': fin_stress_vol
    }).dropna()

    avg_r2_high = combined.loc[combined['high_stress'] == 1, 'r2_0050'].mean()
    avg_r2_low = combined.loc[combined['high_stress'] == 0, 'r2_0050'].mean()
    vol_ratio = avg_r2_high / avg_r2_low if avg_r2_low > 0 else np.nan

    print(f"\n  0050.TW avg r^2 during high stress: {avg_r2_high:.6f}")
    print(f"  0050.TW avg r^2 during low stress:  {avg_r2_low:.6f}")
    print(f"  Volatility ratio (high/low): {vol_ratio:.2f}x")

    # T-test for difference
    high_group = combined.loc[combined['high_stress'] == 1, 'r2_0050']
    low_group = combined.loc[combined['high_stress'] == 0, 'r2_0050']
    t_stat_cond, p_val_cond = stats.ttest_ind(high_group, low_group)
    print(f"  T-test (high vs low stress): t={t_stat_cond:.3f}, p={p_val_cond:.4f}")

# ============================================================
# STEP 4: GARCH-X WITH FINANCIAL STRESS REGRESSOR
# ============================================================
print("\n" + "=" * 70)
print("[Step 4] GJR-GARCH vs GJR-GARCH-X (FinStress)")
print("=" * 70)

# Prepare data for GARCH
garch_returns = returns['0050.TW'] * 100  # Scale to percentage
garch_returns = garch_returns.dropna()

# Align financial stress indicator
fin_stress_aligned = fin_stress_vol.reindex(garch_returns.index).dropna()
common_idx = garch_returns.index.intersection(fin_stress_aligned.index)
garch_returns_aligned = garch_returns.loc[common_idx]
fin_stress_aligned = fin_stress_aligned.loc[common_idx]

print(f"  GARCH sample: {len(garch_returns_aligned)} days")

# Split into in-sample (80%) and out-of-sample (20%)
n_total = len(garch_returns_aligned)
n_is = int(n_total * 0.8)
n_oos = n_total - n_is

is_returns = garch_returns_aligned.iloc[:n_is]
oos_returns = garch_returns_aligned.iloc[n_is:]
is_stress = fin_stress_aligned.iloc[:n_is]
oos_stress = fin_stress_aligned.iloc[n_is:]

print(f"  In-sample: {n_is} days ({is_returns.index[0].date()} to {is_returns.index[-1].date()})")
print(f"  Out-of-sample: {n_oos} days ({oos_returns.index[0].date()} to {oos_returns.index[-1].date()})")

# Model H0: GJR-GARCH(1,1)
print("\n  Fitting GJR-GARCH(1,1)...")
try:
    gjr_base = arch_model(is_returns, vol='GARCH', p=1, o=1, q=1, dist='t')
    gjr_base_fit = gjr_base.fit(disp='off')
    print(f"    Convergence: {gjr_base_fit.convergence_flag == 0}")
    print(f"    omega={gjr_base_fit.params.get('omega', 'N/A'):.6f}")
    print(f"    alpha={gjr_base_fit.params.get('alpha[1]', 'N/A'):.6f}")
    print(f"    gamma={gjr_base_fit.params.get('gamma[1]', 'N/A'):.6f}")
    print(f"    beta={gjr_base_fit.params.get('beta[1]', 'N/A'):.6f}")
    persistence = (gjr_base_fit.params.get('alpha[1]', 0) +
                   gjr_base_fit.params.get('gamma[1]', 0) / 2 +
                   gjr_base_fit.params.get('beta[1]', 0))
    print(f"    Persistence: {persistence:.4f} {'< 1 OK' if persistence < 1 else 'WARNING >= 1'}")
    print(f"    AIC: {gjr_base_fit.aic:.2f}")
    print(f"    BIC: {gjr_base_fit.bic:.2f}")
except Exception as e:
    print(f"    ERROR: {e}")
    gjr_base_fit = None

# Model H1: GJR-GARCH(1,1) with X = FinStress (lagged by 1 day for no lookahead)
print("\n  Fitting GJR-GARCH-X (FinStress as external regressor)...")
# arch library supports exogenous variables in the mean equation
# For variance equation X, we use a manual approach
try:
    # Use lagged financial stress as exogenous in mean equation
    exog_is = pd.DataFrame({'fin_stress': is_stress.shift(1)}).dropna()  # shift(1) for no lookahead!
    common_is = is_returns.index.intersection(exog_is.index)
    is_ret_x = is_returns.loc[common_is]
    exog_is_x = exog_is.loc[common_is]

    gjr_x = arch_model(is_ret_x, vol='GARCH', p=1, o=1, q=1, dist='t', x=exog_is_x)
    gjr_x_fit = gjr_x.fit(disp='off')
    print(f"    Convergence: {gjr_x_fit.convergence_flag == 0}")
    print(f"    AIC: {gjr_x_fit.aic:.2f}")
    print(f"    BIC: {gjr_x_fit.bic:.2f}")
    print(f"    FinStress coeff: {gjr_x_fit.params.get('fin_stress', 'N/A')}")

    # AIC/BIC comparison
    aic_diff = gjr_x_fit.aic - gjr_base_fit.aic
    bic_diff = gjr_x_fit.bic - gjr_base_fit.bic
    print(f"\n    AIC diff (X - base): {aic_diff:.2f} ({'X better' if aic_diff < 0 else 'base better'})")
    print(f"    BIC diff (X - base): {bic_diff:.2f} ({'X better' if bic_diff < 0 else 'base better'})")
except Exception as e:
    print(f"    ERROR fitting GARCH-X: {e}")
    gjr_x_fit = None

# Out-of-sample evaluation with QLIKE on r^2
print("\n  Out-of-sample forecast evaluation (QLIKE on r^2)...")

# Recursive OOS forecasting for base model
oos_forecasts_base = []
oos_forecasts_x = []
oos_r2 = []

# Use expanding window for OOS
for t in range(n_oos):
    idx = n_is + t
    # All data up to idx (exclusive of current)
    r_train = garch_returns_aligned.iloc[:idx]
    s_train = fin_stress_aligned.iloc[:idx]

    # Actual r^2 (scaled to match GARCH output)
    actual_r2 = (garch_returns_aligned.iloc[idx]) ** 2
    oos_r2.append(float(actual_r2))

    try:
        # Base model
        mod_b = arch_model(r_train, vol='GARCH', p=1, o=1, q=1, dist='t')
        fit_b = mod_b.fit(disp='off', show_warning=False)
        fcast_b = fit_b.forecast(horizon=1)
        var_b = fcast_b.variance.values[-1, 0]
        oos_forecasts_base.append(float(var_b))
    except:
        oos_forecasts_base.append(np.nan)

    try:
        # X model (with lagged stress)
        exog_t = pd.DataFrame({'fin_stress': s_train.shift(1)}).dropna()
        common_t = r_train.index.intersection(exog_t.index)
        r_t = r_train.loc[common_t]
        exog_t = exog_t.loc[common_t]

        # For forecast, use current stress as exog (it's already lagged by construction)
        mod_x = arch_model(r_t, vol='GARCH', p=1, o=1, q=1, dist='t', x=exog_t)
        fit_x = mod_x.fit(disp='off', show_warning=False)

        # Last available stress for forecast
        last_stress = fin_stress_aligned.iloc[idx - 1]  # t-1 stress
        fcast_x = fit_x.forecast(horizon=1, x={'fin_stress': last_stress})
        var_x = fcast_x.variance.values[-1, 0]
        oos_forecasts_x.append(float(var_x))
    except:
        oos_forecasts_x.append(np.nan)

    if (t + 1) % 100 == 0:
        print(f"    OOS progress: {t+1}/{n_oos}")

print(f"    OOS complete: {len(oos_r2)} observations")

# Compute QLIKE
oos_r2 = np.array(oos_r2)
oos_base = np.array(oos_forecasts_base)
oos_x = np.array(oos_forecasts_x)

# Remove NaN
valid = ~(np.isnan(oos_base) | np.isnan(oos_x) | np.isnan(oos_r2) | (oos_base <= 0) | (oos_x <= 0))
oos_r2_v = oos_r2[valid]
oos_base_v = oos_base[valid]
oos_x_v = oos_x[valid]

print(f"    Valid OOS observations: {valid.sum()}")

if valid.sum() > 50:
    # QLIKE = mean(r2/sigma2 - log(r2/sigma2) - 1) = mean(r2/sigma2 + log(sigma2)) up to constant
    qlike_base = np.mean(oos_r2_v / oos_base_v + np.log(oos_base_v))
    qlike_x = np.mean(oos_r2_v / oos_x_v + np.log(oos_x_v))

    print(f"\n    QLIKE (base GJR): {qlike_base:.6f}")
    print(f"    QLIKE (GJR-X):    {qlike_x:.6f}")
    print(f"    QLIKE diff:       {qlike_x - qlike_base:.6f} ({'X better' if qlike_x < qlike_base else 'base better'})")

    # DM test
    loss_base = oos_r2_v / oos_base_v + np.log(oos_base_v)
    loss_x = oos_r2_v / oos_x_v + np.log(oos_x_v)
    d = loss_base - loss_x  # positive = base worse = X better

    dm_mean = np.mean(d)
    dm_se = np.std(d, ddof=1) / np.sqrt(len(d))
    dm_t = dm_mean / dm_se if dm_se > 0 else 0
    dm_p = 2 * (1 - stats.t.cdf(abs(dm_t), len(d) - 1))

    print(f"\n    DM test (QLIKE): t={dm_t:.4f}, p={dm_p:.4f}")
    print(f"    Harvey (2016) threshold: |t| > 3.0 -> {'PASS' if abs(dm_t) > 3.0 else 'FAIL (not significant at Harvey threshold)'}")

    garchx_results = {
        'qlike_base': float(qlike_base),
        'qlike_x': float(qlike_x),
        'qlike_diff': float(qlike_x - qlike_base),
        'dm_t': float(dm_t),
        'dm_p': float(dm_p),
        'harvey_pass': abs(dm_t) > 3.0,
        'n_oos': int(valid.sum()),
        'x_better': qlike_x < qlike_base
    }
else:
    print("    ERROR: Not enough valid OOS observations")
    garchx_results = {'error': 'insufficient_data'}

# ============================================================
# STEP 5: VT OVERLAY TEST
# ============================================================
print("\n" + "=" * 70)
print("[Step 5] VT Strategy Overlay Test")
print("=" * 70)

# Get VIX data aligned with 0050 returns
vix_close = data['^VIX']['Close'].reindex(returns.index)

# For Taiwan, we use previous day VIX (cross-market lag)
vix_signal = vix_close.shift(1)  # signal.shift(1) - MANDATORY LAG

# Build high stress signal (also lagged)
high_stress_signal = high_stress.shift(1)  # signal.shift(1) - MANDATORY LAG

# 0050 returns (unscaled)
r_0050 = returns['0050.TW']

# Baseline: 8.63/VIX
w_baseline = VT_SIGMA / vix_signal
w_baseline = w_baseline.clip(0, 1.5)  # Cap leverage at 1.5x

# Test: 8.63/VIX * (1 - 0.3 * I(FinStress > P80))
# When financial stress is high, reduce exposure by 30%
w_overlay = w_baseline * (1 - 0.3 * high_stress_signal)
w_overlay = w_overlay.clip(0, 1.5)

# Compute strategy returns
strat_baseline = w_baseline * r_0050
strat_overlay = w_overlay * r_0050
bh_0050 = r_0050.copy()  # Buy & hold baseline

# Drop NaN and align
strat_df = pd.DataFrame({
    'BH_0050': bh_0050,
    'VT_baseline': strat_baseline,
    'VT_overlay': strat_overlay,
    'high_stress': high_stress_signal,
    'vix': vix_signal
}).dropna()

print(f"  Strategy evaluation period: {len(strat_df)} days")
print(f"  From {strat_df.index[0].date()} to {strat_df.index[-1].date()}")

# Performance metrics
def compute_metrics(r, name):
    n_years = len(r) / 252
    ann_ret = (1 + r).prod() ** (1 / n_years) - 1
    ann_vol = r.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    # Max drawdown
    cum = (1 + r).cumprod()
    peak = cum.expanding().max()
    dd = (cum - peak) / peak
    mdd = dd.min()

    return {
        'ann_return': float(ann_ret),
        'ann_vol': float(ann_vol),
        'sharpe': float(sharpe),
        'max_drawdown': float(mdd),
        'n_days': len(r),
        'n_years': float(n_years)
    }

metrics = {}
for name, col in [('BH_0050', 'BH_0050'), ('VT_baseline', 'VT_baseline'), ('VT_overlay', 'VT_overlay')]:
    m = compute_metrics(strat_df[col], name)
    metrics[name] = m
    print(f"\n  {name}:")
    print(f"    Ann Return: {m['ann_return']:.4f}")
    print(f"    Ann Vol:    {m['ann_vol']:.4f}")
    print(f"    Sharpe:     {m['sharpe']:.4f}")
    print(f"    Max DD:     {m['max_drawdown']:.4f}")

# DM test between strategies (using squared return loss)
loss_bl = (strat_df['VT_baseline'] ** 2)
loss_ov = (strat_df['VT_overlay'] ** 2)
d_strat = loss_bl - loss_ov
dm_strat_t = d_strat.mean() / (d_strat.std() / np.sqrt(len(d_strat))) if d_strat.std() > 0 else 0
dm_strat_p = 2 * (1 - stats.t.cdf(abs(dm_strat_t), len(d_strat) - 1))

print(f"\n  DM test (VT_baseline vs VT_overlay, squared return loss):")
print(f"    t={dm_strat_t:.4f}, p={dm_strat_p:.4f}")

# Sanity check: Sharpe > 2x baseline?
if metrics['VT_overlay']['sharpe'] > 2 * metrics['VT_baseline']['sharpe']:
    print("\n  WARNING: Overlay Sharpe > 2x baseline! Possible bug.")

# Check overlap with VIX information
print("\n  VIX vs FinStress overlap analysis:")
if '0055.TW' in returns.columns:
    overlap_df = pd.DataFrame({
        'fin_stress': fin_stress_vol,
        'vix': vix_close
    }).dropna()
    vix_finstress_corr = overlap_df.corr().iloc[0, 1]
    print(f"    Correlation(FinStress, VIX): {vix_finstress_corr:.4f}")

    # Regime overlap
    vix_high = vix_close > vix_close.expanding().quantile(0.80)
    stress_high = high_stress == 1
    both_high = (vix_high & stress_high).dropna()
    either_high = (vix_high | stress_high).dropna()

    overlap_common = both_high.sum()
    overlap_union = either_high.sum()
    jaccard = overlap_common / overlap_union if overlap_union > 0 else 0

    print(f"    Jaccard similarity (high VIX & high stress): {jaccard:.4f}")
    print(f"    Unique FinStress signals (stress high, VIX not): "
          f"{(stress_high & ~vix_high).dropna().sum()}")

# ============================================================
# STEP 6: CONDITIONAL ANALYSIS - DRAWDOWN OVERLAP
# ============================================================
print("\n" + "=" * 70)
print("[Step 6] Financial Stress & Drawdown Timing Analysis")
print("=" * 70)

# 0050 drawdown
cum_0050 = (1 + r_0050).cumprod()
peak_0050 = cum_0050.expanding().max()
dd_0050 = (cum_0050 - peak_0050) / peak_0050

# Combine with stress signal
timing_df = pd.DataFrame({
    'drawdown': dd_0050,
    'high_stress': high_stress,
    'fin_stress': fin_stress_vol
}).dropna()

# When high stress = 1, what's the avg drawdown?
avg_dd_stress = timing_df.loc[timing_df['high_stress'] == 1, 'drawdown'].mean()
avg_dd_no_stress = timing_df.loc[timing_df['high_stress'] == 0, 'drawdown'].mean()
print(f"  Avg 0050 drawdown during high stress: {avg_dd_stress:.4f}")
print(f"  Avg 0050 drawdown during low stress:  {avg_dd_no_stress:.4f}")

# Can stress predict future drawdowns? (Lead analysis)
leads = [1, 5, 10, 20]
lead_results = {}
for lead in leads:
    future_dd = dd_0050.shift(-lead)
    lead_df = pd.DataFrame({
        'high_stress': high_stress,
        'future_dd': future_dd
    }).dropna()

    avg_fdd_high = lead_df.loc[lead_df['high_stress'] == 1, 'future_dd'].mean()
    avg_fdd_low = lead_df.loc[lead_df['high_stress'] == 0, 'future_dd'].mean()
    t_lead, p_lead = stats.ttest_ind(
        lead_df.loc[lead_df['high_stress'] == 1, 'future_dd'],
        lead_df.loc[lead_df['high_stress'] == 0, 'future_dd']
    )

    lead_results[lead] = {
        'avg_dd_high': float(avg_fdd_high),
        'avg_dd_low': float(avg_fdd_low),
        't_stat': float(t_lead),
        'p_value': float(p_lead)
    }
    sig = '***' if p_lead < 0.01 else ('**' if p_lead < 0.05 else ('*' if p_lead < 0.10 else 'ns'))
    print(f"  Lead {lead:2d}d: DD(high)={avg_fdd_high:.4f}, DD(low)={avg_fdd_low:.4f}, "
          f"t={t_lead:.3f}, p={p_lead:.4f} {sig}")

# ============================================================
# STEP 7: ROBUSTNESS - DIFFERENT STRESS THRESHOLDS
# ============================================================
print("\n" + "=" * 70)
print("[Step 7] Robustness: Different Stress Thresholds")
print("=" * 70)

thresholds = [70, 75, 80, 85, 90]
reduction_levels = [0.2, 0.3, 0.4, 0.5]

robustness_results = {}
for pctl in thresholds:
    threshold = fin_stress_vol.expanding().quantile(pctl / 100)
    hs = (fin_stress_vol > threshold).astype(int).shift(1)  # signal.shift(1)!

    for red in reduction_levels:
        w = w_baseline * (1 - red * hs)
        w = w.clip(0, 1.5)
        r_strat = (w * r_0050).dropna()
        m = compute_metrics(r_strat, f'P{pctl}_R{int(red*100)}')
        key = f'P{pctl}_R{int(red*100)}'
        robustness_results[key] = m

print("  Sharpe ratios (Percentile x Reduction):")
print(f"  {'':8s}", end='')
for red in reduction_levels:
    print(f"  R{int(red*100):2d}%  ", end='')
print()
for pctl in thresholds:
    print(f"  P{pctl:2d}    ", end='')
    for red in reduction_levels:
        key = f'P{pctl}_R{int(red*100)}'
        print(f"  {robustness_results[key]['sharpe']:.4f}", end='')
    print()

print(f"\n  Baseline Sharpe: {metrics['VT_baseline']['sharpe']:.4f}")

# ============================================================
# CHARTS
# ============================================================
print("\n" + "=" * 70)
print("[Charts] Generating visualizations...")
print("=" * 70)

# Chart 1: Granger Causality Network
fig, axes = plt.subplots(1, 2, figsize=(16, 7))

# Panel A: Granger F-statistics heatmap
pairs_for_heatmap = [
    ('2881.TW', '0050.TW'), ('0055.TW', '0050.TW'),
    ('2881.TW', '2330.TW'), ('0055.TW', '2330.TW'),
    ('^VIX', '0050.TW'), ('0050.TW', '2881.TW')
]
labels_map = {
    ('2881.TW', '0050.TW'): 'Fubon->0050',
    ('0055.TW', '0050.TW'): 'FinETF->0050',
    ('2881.TW', '2330.TW'): 'Fubon->TSMC',
    ('0055.TW', '2330.TW'): 'FinETF->TSMC',
    ('^VIX', '0050.TW'): 'VIX->0050',
    ('0050.TW', '2881.TW'): '0050->Fubon'
}

ax = axes[0]
pair_labels = []
f_values_by_lag = {lag: [] for lag in range(1, GRANGER_MAX_LAG + 1)}

for pair in pairs_for_heatmap:
    cause, effect = pair
    label = labels_map.get(pair, f'{cause}->{effect}')
    pair_labels.append(label)

    for granger_label, gr in granger_results.items():
        if 'error' not in gr and gr.get('cause') == cause and gr.get('effect') == effect:
            for lag in range(1, GRANGER_MAX_LAG + 1):
                f_values_by_lag[lag].append(gr['all_lags'][lag]['F'])
            break
    else:
        for lag in range(1, GRANGER_MAX_LAG + 1):
            f_values_by_lag[lag].append(0)

heatmap_data = np.array([f_values_by_lag[lag] for lag in range(1, GRANGER_MAX_LAG + 1)])
im = ax.imshow(heatmap_data, aspect='auto', cmap='YlOrRd', interpolation='nearest')
ax.set_xticks(range(len(pair_labels)))
ax.set_xticklabels(pair_labels, rotation=45, ha='right', fontsize=9)
ax.set_yticks(range(GRANGER_MAX_LAG))
ax.set_yticklabels([f'Lag {i}' for i in range(1, GRANGER_MAX_LAG + 1)])
ax.set_title('(A) Granger Causality F-statistics\n(on squared returns)', fontsize=12)
plt.colorbar(im, ax=ax, label='F-statistic')

# Add significance markers
for i in range(heatmap_data.shape[0]):
    for j in range(heatmap_data.shape[1]):
        val = heatmap_data[i, j]
        # Check p-value
        for granger_label, gr in granger_results.items():
            if 'error' not in gr:
                cause_t = pairs_for_heatmap[j][0]
                effect_t = pairs_for_heatmap[j][1]
                if gr.get('cause') == cause_t and gr.get('effect') == effect_t:
                    p = gr['all_lags'][i + 1]['p']
                    if p < 0.01:
                        ax.text(j, i, '***', ha='center', va='center', fontsize=8, fontweight='bold', color='white' if val > 5 else 'black')
                    elif p < 0.05:
                        ax.text(j, i, '**', ha='center', va='center', fontsize=8, fontweight='bold', color='white' if val > 5 else 'black')
                    elif p < 0.10:
                        ax.text(j, i, '*', ha='center', va='center', fontsize=8, color='white' if val > 5 else 'black')
                    break

# Panel B: Partial Granger (VIX-controlled) bar chart
ax2 = axes[1]
partial_labels = list(partial_granger_results.keys())
partial_f = [partial_granger_results[k]['F_stat'] for k in partial_labels]
partial_p = [partial_granger_results[k]['p_value'] for k in partial_labels]
colors = ['#2ecc71' if p < 0.05 else '#e74c3c' for p in partial_p]
bars = ax2.bar(partial_labels, partial_f, color=colors, edgecolor='black', linewidth=0.5)
ax2.axhline(y=stats.f.ppf(0.95, 3, 2000), color='red', linestyle='--', alpha=0.7, label='5% critical value')
ax2.set_ylabel('F-statistic')
ax2.set_title('(B) Partial Granger (VIX-controlled)\nGreen=sig, Red=not sig', fontsize=12)
ax2.legend()

for i, (f, p) in enumerate(zip(partial_f, partial_p)):
    ax2.text(i, f + 0.1, f'p={p:.3f}', ha='center', fontsize=9)

plt.tight_layout()
plt.savefig(os.path.join(SCRIPT_DIR, 'k1028_granger_causality.png'), dpi=150, bbox_inches='tight')
plt.close()
print("  Saved k1028_granger_causality.png")

# Chart 2: Financial Stress Timeline vs 0050 Drawdown
fig, axes = plt.subplots(3, 1, figsize=(16, 12), sharex=True)

# Panel A: 0050 cumulative return
ax1 = axes[0]
cum_0050_plot = cum_0050.reindex(timing_df.index)
ax1.plot(cum_0050_plot.index, cum_0050_plot.values, color='#2c3e50', linewidth=1)
ax1.fill_between(cum_0050_plot.index, cum_0050_plot.values,
                  where=timing_df['high_stress'] == 1, alpha=0.3, color='red', label='High FinStress')
ax1.set_ylabel('0050.TW Cumulative Return')
ax1.set_title('K1028: Financial Stress Early Warning System for Taiwan 50 ETF', fontsize=14)
ax1.legend(loc='upper left')
ax1.grid(True, alpha=0.3)

# Panel B: Financial stress indicator
ax2 = axes[1]
ax2.plot(timing_df.index, timing_df['fin_stress'], color='#e67e22', linewidth=0.8, label='FinStress (22d vol of 0055.TW)')
threshold_plot = fin_stress_vol.expanding().quantile(FINSTRESS_PERCENTILE / 100).reindex(timing_df.index)
ax2.plot(timing_df.index, threshold_plot, color='red', linestyle='--', linewidth=0.8, label=f'P{FINSTRESS_PERCENTILE} threshold')
ax2.fill_between(timing_df.index, timing_df['fin_stress'], threshold_plot,
                  where=timing_df['fin_stress'] > threshold_plot, alpha=0.3, color='red')
ax2.set_ylabel('Annualized Volatility')
ax2.legend(loc='upper right')
ax2.grid(True, alpha=0.3)

# Panel C: 0050 drawdown
ax3 = axes[2]
dd_plot = dd_0050.reindex(timing_df.index)
ax3.fill_between(dd_plot.index, dd_plot.values, 0, color='#e74c3c', alpha=0.4)
ax3.plot(dd_plot.index, dd_plot.values, color='#c0392b', linewidth=0.8)
# Mark high stress periods
stress_periods = timing_df.index[timing_df['high_stress'] == 1]
for idx in stress_periods:
    ax3.axvline(idx, color='orange', alpha=0.05, linewidth=0.5)
ax3.set_ylabel('Drawdown')
ax3.set_xlabel('Date')
ax3.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig(os.path.join(SCRIPT_DIR, 'k1028_finstress_timeline.png'), dpi=150, bbox_inches='tight')
plt.close()
print("  Saved k1028_finstress_timeline.png")

# Chart 3: Strategy comparison
fig, axes = plt.subplots(2, 2, figsize=(16, 10))

# Panel A: Cumulative returns
ax1 = axes[0, 0]
for name, col, color in [('BH 0050', 'BH_0050', '#95a5a6'),
                           ('VT 8.63/VIX', 'VT_baseline', '#3498db'),
                           ('VT + FinStress', 'VT_overlay', '#e74c3c')]:
    cum = (1 + strat_df[col]).cumprod()
    ax1.plot(cum.index, cum.values, label=name, color=color, linewidth=1.2)
ax1.set_title('(A) Cumulative Returns', fontsize=11)
ax1.legend()
ax1.grid(True, alpha=0.3)
ax1.set_ylabel('Growth of $1')

# Panel B: Rolling Sharpe (252-day)
ax2 = axes[0, 1]
for name, col, color in [('VT baseline', 'VT_baseline', '#3498db'),
                           ('VT overlay', 'VT_overlay', '#e74c3c')]:
    rolling_ret = strat_df[col].rolling(252).mean() * 252
    rolling_vol = strat_df[col].rolling(252).std() * np.sqrt(252)
    rolling_sharpe = rolling_ret / rolling_vol
    ax2.plot(rolling_sharpe.index, rolling_sharpe.values, label=name, color=color, linewidth=1)
ax2.axhline(y=0, color='black', linestyle='-', linewidth=0.5)
ax2.set_title('(B) Rolling 252-day Sharpe Ratio', fontsize=11)
ax2.legend()
ax2.grid(True, alpha=0.3)

# Panel C: Robustness heatmap
ax3 = axes[1, 0]
rob_matrix = np.zeros((len(thresholds), len(reduction_levels)))
for i, pctl in enumerate(thresholds):
    for j, red in enumerate(reduction_levels):
        key = f'P{pctl}_R{int(red*100)}'
        rob_matrix[i, j] = robustness_results[key]['sharpe']

im = ax3.imshow(rob_matrix, cmap='RdYlGn', aspect='auto')
ax3.set_xticks(range(len(reduction_levels)))
ax3.set_xticklabels([f'{int(r*100)}%' for r in reduction_levels])
ax3.set_yticks(range(len(thresholds)))
ax3.set_yticklabels([f'P{p}' for p in thresholds])
ax3.set_xlabel('Reduction Level')
ax3.set_ylabel('Stress Percentile')
ax3.set_title('(C) Sharpe Robustness\n(Percentile x Reduction)', fontsize=11)
plt.colorbar(im, ax=ax3, label='Sharpe')

# Add values to heatmap
for i in range(len(thresholds)):
    for j in range(len(reduction_levels)):
        ax3.text(j, i, f'{rob_matrix[i,j]:.3f}', ha='center', va='center', fontsize=9)

# Panel D: VIX vs FinStress scatter
ax4 = axes[1, 1]
scatter_df = pd.DataFrame({
    'vix': vix_close,
    'fin_stress': fin_stress_vol
}).dropna()
ax4.scatter(scatter_df['vix'], scatter_df['fin_stress'], alpha=0.15, s=5, color='#2c3e50')
ax4.set_xlabel('VIX Level')
ax4.set_ylabel('FinStress (22d vol of 0055.TW)')
ax4.set_title(f'(D) VIX vs FinStress\n(corr={vix_finstress_corr:.3f})', fontsize=11)
ax4.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig(os.path.join(SCRIPT_DIR, 'k1028_strategy_comparison.png'), dpi=150, bbox_inches='tight')
plt.close()
print("  Saved k1028_strategy_comparison.png")

# ============================================================
# RESULTS SUMMARY & SAVE
# ============================================================
print("\n" + "=" * 70)
print("[Summary] K1028 Results")
print("=" * 70)

results = {
    'experiment_id': 'K1028',
    'title': 'Financial Stock Early Warning System - Fubon/Financial ETF -> TSMC/0050.TW Vol Transmission',
    'date': datetime.now(timezone.utc).isoformat(),
    'data_source': 'yfinance',
    'sample_period': f'{START_DATE} to {END_DATE}',
    'n_observations': len(returns),
    'seed': 42,
    'descriptive_stats': desc_stats,
    'adf_tests': adf_results,
    'return_correlations': corr_matrix.to_dict(),
    'granger_causality': granger_results,
    'partial_granger_vix_controlled': partial_granger_results,
    'financial_stress_indicator': {
        'method': '22-day rolling vol of 0055.TW',
        'threshold': f'P{FINSTRESS_PERCENTILE}',
        'stress_pct': float(stress_pct),
        'vol_ratio_high_low': float(vol_ratio),
        'conditional_ttest': {
            't_stat': float(t_stat_cond),
            'p_value': float(p_val_cond)
        }
    },
    'garchx_evaluation': garchx_results,
    'vt_strategy_metrics': metrics,
    'vt_dm_test': {
        't_stat': float(dm_strat_t),
        'p_value': float(dm_strat_p)
    },
    'vix_finstress_overlap': {
        'correlation': float(vix_finstress_corr),
        'jaccard_similarity': float(jaccard)
    },
    'lead_analysis': lead_results,
    'robustness': robustness_results,
    'conclusions': {
        'Q1_financial_vol_leads_0050': None,  # Will be filled below
        'Q2_finstress_as_regime_overlay': None,
        'Q3_vix_overlap': None,
        'overall': None
    },
    'charts': [
        'k1028_granger_causality.png',
        'k1028_finstress_timeline.png',
        'k1028_strategy_comparison.png'
    ]
}

# Fill conclusions based on results
# Q1: Does financial vol lead 0050?
granger_sig_count = sum(1 for k, v in granger_results.items() if 'error' not in v and v.get('significant_at_5pct', False))
partial_sig_count = sum(1 for k, v in partial_granger_results.items() if v.get('significant_at_5pct', False))

q1_conclusion = (f"Granger causality: {granger_sig_count}/{len(granger_results)} pairs significant at 5%. "
                 f"After controlling for VIX: {partial_sig_count}/{len(partial_granger_results)} pairs remain significant. "
                 f"Volatility ratio (high/low stress): {vol_ratio:.2f}x.")

q2_conclusion = (f"GARCH-X vs base: QLIKE diff = {garchx_results.get('qlike_diff', 'N/A')}, "
                 f"DM t = {garchx_results.get('dm_t', 'N/A')}, Harvey pass = {garchx_results.get('harvey_pass', 'N/A')}. "
                 f"VT overlay Sharpe = {metrics['VT_overlay']['sharpe']:.4f} vs baseline {metrics['VT_baseline']['sharpe']:.4f}.")

q3_conclusion = (f"VIX-FinStress correlation = {vix_finstress_corr:.4f}, "
                 f"Jaccard overlap of high regimes = {jaccard:.4f}. "
                 f"Partial Granger significance indicates {'some' if partial_sig_count > 0 else 'no'} incremental info beyond VIX.")

results['conclusions']['Q1_financial_vol_leads_0050'] = q1_conclusion
results['conclusions']['Q2_finstress_as_regime_overlay'] = q2_conclusion
results['conclusions']['Q3_vix_overlap'] = q3_conclusion

# Overall assessment
if partial_sig_count > 0 and garchx_results.get('harvey_pass', False):
    overall = "POSITIVE: Financial stress provides statistically significant incremental information beyond VIX for Taiwan VT."
elif partial_sig_count > 0 and not garchx_results.get('harvey_pass', False):
    overall = "MIXED: Granger causality exists but does not survive Harvey (2016) threshold in GARCH-X framework. Marginal practical value."
elif partial_sig_count == 0:
    overall = "NULL: Financial stress does not provide incremental information beyond VIX. VIX sufficiency confirmed again."
else:
    overall = "INCONCLUSIVE: Results require further investigation."

results['conclusions']['overall'] = overall

print(f"\n  {overall}")
print(f"\n  Q1: {q1_conclusion}")
print(f"\n  Q2: {q2_conclusion}")
print(f"\n  Q3: {q3_conclusion}")

# Save results
results_path = os.path.join(SCRIPT_DIR, 'k1028_results.json')
with open(results_path, 'w', encoding='utf-8') as f:
    json.dump(results, f, indent=2, ensure_ascii=False, default=str)
print(f"\n  Results saved to {results_path}")

print("\n" + "=" * 70)
print("K1028 COMPLETE")
print("=" * 70)
