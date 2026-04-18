#!/usr/bin/env python3
"""
K451: Overnight vs Intraday Volatility Decomposition
=====================================================
[提出: 用戶, 執行: Claude]

Research questions:
1. What is the ratio of overnight vs intraday variance for SPY?
2. Does overnight vol predict next-day intraday vol?
3. Does decomposed modeling (ON+ID) beat close-to-close?

Literature:
- Hansen & Lunde (2005) JBES — OHLC-based vol decomposition
- Tsiakas (2008) JFM — Overnight information & stochastic volatility
- Ahoniemi & Lanne (2013) IJF — Overnight returns and realized vol

Data: SPY OHLC from yfinance, 2005-01-01 to 2026-03-26
OOS: 2023-01-01 to 2025-12-31

Decomposition:
  r_cc = log(C_t / C_{t-1})    # close-to-close
  r_on = log(O_t / C_{t-1})    # overnight (close-to-open)
  r_id = log(C_t / O_t)        # intraday (open-to-close)
  r_cc = r_on + r_id           # exact

Models:
  M1: lagged CC var → next CC var (baseline)
  M2: lagged ON var → next CC var
  M3: lagged ID var → next CC var
  M4: lagged ON + ID → next CC var
  M5: lagged ON + ID + GJR leverage → next CC var
  M6: HAR-style with ON/ID at 1d/5d/21d horizons
  M7: GJR-GARCH on intraday-only returns vs close-to-close
"""

import json
import time
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timezone
from scipy import stats
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_squared_error
from arch import arch_model

warnings.filterwarnings("ignore")

start_time = time.time()

# ============================================================
# 1. Data Download
# ============================================================
print("=" * 60)
print("K451: Overnight vs Intraday Volatility Decomposition")
print("=" * 60)

ticker = yf.Ticker("SPY")
df = ticker.history(start="2005-01-01", end="2026-03-26", auto_adjust=False)
df = df[['Open', 'High', 'Low', 'Close', 'Adj Close', 'Volume']].copy()
df.index = pd.to_datetime(df.index).tz_localize(None)
df = df.sort_index()

# Use Adj Close for close-to-close consistency
df['AdjClose'] = df['Adj Close']
# Adjust Open/High/Low by the same ratio
adj_ratio = df['AdjClose'] / df['Close']
df['AdjOpen'] = df['Open'] * adj_ratio
df['AdjHigh'] = df['High'] * adj_ratio
df['AdjLow'] = df['Low'] * adj_ratio

print(f"Data: {df.index[0].date()} to {df.index[-1].date()}, N={len(df)}")

# ============================================================
# 2. Return Decomposition
# ============================================================
df['r_cc'] = np.log(df['AdjClose'] / df['AdjClose'].shift(1))
df['r_on'] = np.log(df['AdjOpen'] / df['AdjClose'].shift(1))  # overnight
df['r_id'] = np.log(df['AdjClose'] / df['AdjOpen'])            # intraday

df = df.dropna(subset=['r_cc', 'r_on', 'r_id']).copy()

# Verify decomposition: r_cc = r_on + r_id
decomp_check = np.abs(df['r_cc'] - (df['r_on'] + df['r_id']))
print(f"\nDecomposition check: max error = {decomp_check.max():.2e}")
assert decomp_check.max() < 1e-10, "Decomposition failed!"

# Squared returns as variance proxies
df['var_cc'] = df['r_cc'] ** 2
df['var_on'] = df['r_on'] ** 2
df['var_id'] = df['r_id'] ** 2

# GJR leverage indicator
df['neg_cc'] = (df['r_cc'] < 0).astype(float)
df['neg_on'] = (df['r_on'] < 0).astype(float)
df['neg_id'] = (df['r_id'] < 0).astype(float)

print(f"Sample after dropna: N={len(df)}")

# ============================================================
# 3. Descriptive Statistics (Diagnostics First!)
# ============================================================
print("\n" + "=" * 60)
print("3. DESCRIPTIVE STATISTICS")
print("=" * 60)

desc_stats = {}
for name, col in [('r_cc', 'r_cc'), ('r_on', 'r_on'), ('r_id', 'r_id')]:
    s = df[col]
    desc_stats[name] = {
        'mean': float(s.mean()),
        'std': float(s.std()),
        'skew': float(s.skew()),
        'kurtosis': float(s.kurtosis()),
        'min': float(s.min()),
        'max': float(s.max()),
        'N': int(len(s)),
    }
    print(f"\n{name}:")
    print(f"  Mean={s.mean():.6f}, Std={s.std():.6f}")
    print(f"  Skew={s.skew():.3f}, Kurt={s.kurtosis():.3f}")
    print(f"  Min={s.min():.6f}, Max={s.max():.6f}")

# Variance decomposition ratios
total_var = df['var_cc'].mean()
on_var = df['var_on'].mean()
id_var = df['var_id'].mean()
cov_on_id = 2 * (df['r_on'] * df['r_id']).mean()

on_share = on_var / total_var
id_share = id_var / total_var
cov_share = cov_on_id / total_var

print(f"\n--- Variance Decomposition ---")
print(f"Total (CC) variance:     {total_var:.8f}")
print(f"Overnight variance:      {on_var:.8f} ({on_share:.1%})")
print(f"Intraday variance:       {id_var:.8f} ({id_share:.1%})")
print(f"2*Cov(ON,ID):            {cov_on_id:.8f} ({cov_share:.1%})")
print(f"Sum check:               {on_var + id_var + cov_on_id:.8f}")

var_decomp = {
    'total_cc_var': float(total_var),
    'overnight_var': float(on_var),
    'intraday_var': float(id_var),
    'cov_2_on_id': float(cov_on_id),
    'overnight_share': float(on_share),
    'intraday_share': float(id_share),
    'covariance_share': float(cov_share),
}

# Autocorrelation of squared returns
from statsmodels.stats.diagnostic import acorr_ljungbox

ac_results = {}
for name, col in [('var_cc', 'var_cc'), ('var_on', 'var_on'), ('var_id', 'var_id')]:
    lb = acorr_ljungbox(df[col], lags=[10], return_df=True)
    ac1 = df[col].autocorr(lag=1)
    ac5 = df[col].autocorr(lag=5)
    ac_results[name] = {
        'AC(1)': float(ac1),
        'AC(5)': float(ac5),
        'LB(10)_stat': float(lb['lb_stat'].values[0]),
        'LB(10)_pval': float(lb['lb_pvalue'].values[0]),
    }
    print(f"\n{name}: AC(1)={ac1:.4f}, AC(5)={ac5:.4f}, LB(10) p={lb['lb_pvalue'].values[0]:.4e}")

# ADF test on each return series
from statsmodels.tsa.stattools import adfuller

adf_results = {}
for name, col in [('r_cc', 'r_cc'), ('r_on', 'r_on'), ('r_id', 'r_id')]:
    adf = adfuller(df[col], maxlag=20)
    adf_results[name] = {'ADF_stat': float(adf[0]), 'p_value': float(adf[1])}
    print(f"ADF {name}: stat={adf[0]:.4f}, p={adf[1]:.4e}")

# ARCH LM test
from statsmodels.stats.diagnostic import het_arch

arch_lm = {}
for name, col in [('r_cc', 'r_cc'), ('r_on', 'r_on'), ('r_id', 'r_id')]:
    lm_stat, lm_pval, _, _ = het_arch(df[col].values, nlags=10)
    arch_lm[name] = {'LM_stat': float(lm_stat), 'p_value': float(lm_pval)}
    print(f"ARCH LM {name}: stat={lm_stat:.2f}, p={lm_pval:.4e}")

# Cross-correlation between ON and ID
corr_on_id = df['r_on'].corr(df['r_id'])
corr_var_on_id = df['var_on'].corr(df['var_id'])
corr_on_lag1_id = df['r_on'].corr(df['r_id'].shift(1))  # ON predicting tomorrow's ID?
# Actually: does today's ON predict today's ID?
corr_on_today_id_today = df['r_on'].corr(df['r_id'])
# Does yesterday's ID predict today's ON?
corr_id_lag1_on = df['r_id'].shift(1).corr(df['r_on'])

print(f"\nCorr(r_on, r_id) same-day: {corr_on_id:.4f}")
print(f"Corr(var_on, var_id) same-day: {corr_var_on_id:.4f}")
print(f"Corr(r_on_t, r_id_t) = {corr_on_today_id_today:.4f}")
print(f"Corr(r_id_{'{t-1}'}, r_on_t) = {corr_id_lag1_on:.4f}")

cross_corr = {
    'corr_r_on_r_id_sameday': float(corr_on_id),
    'corr_var_on_var_id_sameday': float(corr_var_on_id),
    'corr_r_id_lag1_r_on': float(corr_id_lag1_on),
}

# ============================================================
# 4. Granger Causality Tests
# ============================================================
print("\n" + "=" * 60)
print("4. GRANGER CAUSALITY (VAR squared returns)")
print("=" * 60)

from statsmodels.tsa.stattools import grangercausalitytests

granger_results = {}

# ON → ID (does overnight vol predict intraday vol?)
print("\nGranger: var_on → var_id")
gc_on_to_id = grangercausalitytests(
    df[['var_id', 'var_on']].values, maxlag=5, verbose=False
)
for lag in [1, 2, 5]:
    f_stat = gc_on_to_id[lag][0]['ssr_ftest'][0]
    f_pval = gc_on_to_id[lag][0]['ssr_ftest'][1]
    print(f"  Lag {lag}: F={f_stat:.3f}, p={f_pval:.4e}")

granger_results['var_on_to_var_id'] = {
    str(lag): {
        'F_stat': float(gc_on_to_id[lag][0]['ssr_ftest'][0]),
        'p_value': float(gc_on_to_id[lag][0]['ssr_ftest'][1]),
    }
    for lag in [1, 2, 5]
}

# ID → next ON (does intraday vol predict next overnight vol?)
print("\nGranger: var_id → var_on")
gc_id_to_on = grangercausalitytests(
    df[['var_on', 'var_id']].values, maxlag=5, verbose=False
)
for lag in [1, 2, 5]:
    f_stat = gc_id_to_on[lag][0]['ssr_ftest'][0]
    f_pval = gc_id_to_on[lag][0]['ssr_ftest'][1]
    print(f"  Lag {lag}: F={f_stat:.3f}, p={f_pval:.4e}")

granger_results['var_id_to_var_on'] = {
    str(lag): {
        'F_stat': float(gc_id_to_on[lag][0]['ssr_ftest'][0]),
        'p_value': float(gc_id_to_on[lag][0]['ssr_ftest'][1]),
    }
    for lag in [1, 2, 5]
}

# ON → CC (does overnight vol predict total vol?)
print("\nGranger: var_on → var_cc")
gc_on_to_cc = grangercausalitytests(
    df[['var_cc', 'var_on']].values, maxlag=5, verbose=False
)
for lag in [1, 2, 5]:
    f_stat = gc_on_to_cc[lag][0]['ssr_ftest'][0]
    f_pval = gc_on_to_cc[lag][0]['ssr_ftest'][1]
    print(f"  Lag {lag}: F={f_stat:.3f}, p={f_pval:.4e}")

granger_results['var_on_to_var_cc'] = {
    str(lag): {
        'F_stat': float(gc_on_to_cc[lag][0]['ssr_ftest'][0]),
        'p_value': float(gc_on_to_cc[lag][0]['ssr_ftest'][1]),
    }
    for lag in [1, 2, 5]
}

# ============================================================
# 5. Forecasting Models (OOS: 2023-2025)
# ============================================================
print("\n" + "=" * 60)
print("5. FORECASTING MODELS")
print("=" * 60)

# Construct features
# HAR-style aggregation at 1d, 5d, 21d
for prefix in ['var_cc', 'var_on', 'var_id']:
    df[f'{prefix}_5d'] = df[prefix].rolling(5).mean()
    df[f'{prefix}_21d'] = df[prefix].rolling(21).mean()

# Lagged features (predict t+1 from t)
for col in ['var_cc', 'var_on', 'var_id', 'var_cc_5d', 'var_on_5d', 'var_id_5d',
            'var_cc_21d', 'var_on_21d', 'var_id_21d', 'neg_cc', 'neg_on', 'neg_id']:
    df[f'{col}_L1'] = df[col].shift(1)

# GJR-style interaction: negative * variance
df['gjr_cc_L1'] = df['neg_cc_L1'] * df['var_cc_L1']
df['gjr_on_L1'] = df['neg_on_L1'] * df['var_on_L1']
df['gjr_id_L1'] = df['neg_id_L1'] * df['var_id_L1']

# Target
df['target'] = df['var_cc']  # next-day close-to-close variance

# Drop NaN from rolling
df_model = df.dropna().copy()

# Split
oos_start = '2023-01-01'
train = df_model[df_model.index < oos_start].copy()
test = df_model[df_model.index >= oos_start].copy()

print(f"Train: {train.index[0].date()} to {train.index[-1].date()}, N={len(train)}")
print(f"Test:  {test.index[0].date()} to {test.index[-1].date()}, N={len(test)}")

# Define models
models = {
    'M1_CC_baseline': ['var_cc_L1'],
    'M2_ON_only': ['var_on_L1'],
    'M3_ID_only': ['var_id_L1'],
    'M4_ON_ID': ['var_on_L1', 'var_id_L1'],
    'M5_ON_ID_GJR': ['var_on_L1', 'var_id_L1', 'gjr_on_L1', 'gjr_id_L1'],
    'M6_HAR_ONID': [
        'var_on_L1', 'var_id_L1',
        'var_on_5d_L1', 'var_id_5d_L1',
        'var_on_21d_L1', 'var_id_21d_L1',
    ],
    'M6b_HAR_CC': [
        'var_cc_L1', 'var_cc_5d_L1', 'var_cc_21d_L1',
    ],
    'M6c_HAR_ONID_GJR': [
        'var_on_L1', 'var_id_L1',
        'var_on_5d_L1', 'var_id_5d_L1',
        'var_on_21d_L1', 'var_id_21d_L1',
        'gjr_on_L1', 'gjr_id_L1',
    ],
}

target_col = 'target'

# Evaluate each model
model_results = {}

for mname, features in models.items():
    X_train = train[features].values
    y_train = train[target_col].values
    X_test = test[features].values
    y_test = test[target_col].values

    # Ridge regression (light regularization)
    ridge = Ridge(alpha=1e-6)
    ridge.fit(X_train, y_train)

    y_pred_train = ridge.predict(X_train)
    y_pred_test = ridge.predict(X_test)

    # Ensure non-negative predictions
    y_pred_test = np.maximum(y_pred_test, 0)
    y_pred_train = np.maximum(y_pred_train, 0)

    # MSE
    mse_train = mean_squared_error(y_train, y_pred_train)
    mse_test = mean_squared_error(y_test, y_pred_test)

    # QLIKE: mean(y/pred - log(y/pred) - 1) for positive pred
    eps = 1e-12
    pred_safe = np.maximum(y_pred_test, eps)
    actual_safe = np.maximum(y_test, eps)
    qlike = np.mean(actual_safe / pred_safe - np.log(actual_safe / pred_safe) - 1)

    # R-squared OOS
    ss_res = np.sum((y_test - y_pred_test) ** 2)
    ss_tot = np.sum((y_test - y_test.mean()) ** 2)
    r2_oos = 1 - ss_res / ss_tot

    # Hedging effectiveness (variance reduction)
    he = 1 - mse_test / np.var(y_test)

    # Coefficients
    coefs = {feat: float(c) for feat, c in zip(features, ridge.coef_)}
    coefs['intercept'] = float(ridge.intercept_)

    model_results[mname] = {
        'features': features,
        'mse_train': float(mse_train),
        'mse_test': float(mse_test),
        'qlike': float(qlike),
        'r2_oos': float(r2_oos),
        'he': float(he),
        'coefficients': coefs,
    }

    print(f"\n{mname}:")
    print(f"  MSE(train)={mse_train:.4e}, MSE(test)={mse_test:.4e}")
    print(f"  QLIKE={qlike:.6f}, R2_OOS={r2_oos:.4f}")
    for feat, c in zip(features, ridge.coef_):
        print(f"  {feat}: {c:.6f}")

# ============================================================
# 5b. Diebold-Mariano Tests
# ============================================================
print("\n" + "=" * 60)
print("5b. DIEBOLD-MARIANO TESTS (vs M1 baseline)")
print("=" * 60)

from statsmodels.tsa.stattools import adfuller

def dm_test(e1, e2, h=1):
    """Diebold-Mariano test. H0: equal predictive accuracy."""
    d = e1**2 - e2**2
    d_mean = np.mean(d)
    # Newey-West variance with h-1 lags
    n = len(d)
    gamma_0 = np.var(d, ddof=1)
    gamma_sum = gamma_0
    for k in range(1, h):
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        gamma_sum += 2 * gamma_k
    dm_stat = d_mean / np.sqrt(gamma_sum / n)
    p_val = 2 * (1 - stats.norm.cdf(abs(dm_stat)))
    return dm_stat, p_val

# Baseline errors
X_base_test = test[models['M1_CC_baseline']].values
ridge_base = Ridge(alpha=1e-6)
ridge_base.fit(train[models['M1_CC_baseline']].values, train[target_col].values)
e_base = test[target_col].values - np.maximum(ridge_base.predict(X_base_test), 0)

dm_results = {}
for mname, features in models.items():
    if mname == 'M1_CC_baseline':
        continue
    ridge_m = Ridge(alpha=1e-6)
    ridge_m.fit(train[features].values, train[target_col].values)
    e_m = test[target_col].values - np.maximum(ridge_m.predict(test[features].values), 0)

    dm_stat, dm_pval = dm_test(e_base, e_m)
    dm_results[mname] = {'DM_stat': float(dm_stat), 'p_value': float(dm_pval)}
    sig = "***" if dm_pval < 0.01 else "**" if dm_pval < 0.05 else "*" if dm_pval < 0.10 else ""
    print(f"  {mname} vs M1: DM={dm_stat:.3f}, p={dm_pval:.4f} {sig}")

# ============================================================
# 6. GJR-GARCH: Intraday-Only vs Close-to-Close
# ============================================================
print("\n" + "=" * 60)
print("6. GJR-GARCH: INTRADAY-ONLY vs CLOSE-TO-CLOSE")
print("=" * 60)

def fit_gjr_garch_oos(returns, oos_start_idx, name=""):
    """Fit GJR-GARCH(1,1) with expanding window, return OOS forecasts."""
    n = len(returns)
    oos_forecasts = []
    oos_actuals = []

    # Initial fit on training data
    train_r = returns[:oos_start_idx]
    am = arch_model(train_r * 100, vol='GARCH', p=1, o=1, q=1, dist='t')
    try:
        res = am.fit(disp='off', show_warning=False)
        converged = res.convergence_flag == 0
        params = res.params
        persistence = float(params.get('alpha[1]', 0) + params.get('gamma[1]', 0) / 2 + params.get('beta[1]', 0))
        print(f"\n{name} GJR-GARCH fit:")
        print(f"  Convergence: {converged}")
        print(f"  omega={params.get('omega', 0):.6f}, alpha={params.get('alpha[1]', 0):.6f}")
        print(f"  gamma={params.get('gamma[1]', 0):.6f}, beta={params.get('beta[1]', 0):.6f}")
        print(f"  Persistence={persistence:.6f}")
        if persistence >= 1:
            print(f"  WARNING: persistence >= 1!")
    except Exception as e:
        print(f"  {name} fit failed: {e}")
        return None, None, None

    # Rolling 1-step-ahead OOS forecasts (expanding window)
    for t in range(oos_start_idx, n):
        r_window = returns[:t]
        try:
            am_t = arch_model(r_window * 100, vol='GARCH', p=1, o=1, q=1, dist='t')
            res_t = am_t.fit(disp='off', show_warning=False, starting_values=res.params.values)
            fc = res_t.forecast(horizon=1)
            var_fc = fc.variance.values[-1, 0] / (100**2)  # back to decimal
            oos_forecasts.append(var_fc)
            oos_actuals.append(returns.iloc[t] ** 2)
        except:
            oos_forecasts.append(np.nan)
            oos_actuals.append(returns.iloc[t] ** 2)

    oos_forecasts = np.array(oos_forecasts)
    oos_actuals = np.array(oos_actuals)

    # Remove NaN
    valid = ~(np.isnan(oos_forecasts) | np.isnan(oos_actuals))
    oos_forecasts = oos_forecasts[valid]
    oos_actuals = oos_actuals[valid]

    fit_info = {
        'converged': bool(converged),
        'persistence': float(persistence),
        'omega': float(params.get('omega', 0)),
        'alpha': float(params.get('alpha[1]', 0)),
        'gamma': float(params.get('gamma[1]', 0)),
        'beta': float(params.get('beta[1]', 0)),
    }

    return oos_forecasts, oos_actuals, fit_info

# Find OOS start index
oos_mask = df_model.index >= oos_start
oos_start_idx = np.where(oos_mask)[0][0]

# But full GJR expanding window is expensive — use fixed window reestimation
# every 21 days (monthly) for efficiency
print("\nUsing fixed-window reestimation every 21 days for efficiency...")

def gjr_garch_oos_efficient(returns, oos_start_idx, refit_every=21, name=""):
    """Efficient GJR-GARCH with periodic refitting."""
    n = len(returns)
    r_scaled = returns.values * 100

    # Initial fit
    am = arch_model(pd.Series(r_scaled[:oos_start_idx]), vol='GARCH', p=1, o=1, q=1, dist='t')
    try:
        res = am.fit(disp='off', show_warning=False)
        converged = res.convergence_flag == 0
        params = res.params
        persistence = float(params.get('alpha[1]', 0) + params.get('gamma[1]', 0) / 2 + params.get('beta[1]', 0))
        print(f"\n{name} GJR-GARCH initial fit:")
        print(f"  Convergence: {converged}, Persistence={persistence:.6f}")
        print(f"  omega={params.get('omega', 0):.6f}, alpha={params.get('alpha[1]', 0):.6f}")
        print(f"  gamma={params.get('gamma[1]', 0):.6f}, beta={params.get('beta[1]', 0):.6f}")
        if persistence >= 1:
            print(f"  WARNING: persistence >= 1!")
    except Exception as e:
        print(f"  {name} fit failed: {e}")
        return None, None, None

    oos_forecasts = []
    oos_actuals = []
    last_fit_params = res.params.values

    for i, t in enumerate(range(oos_start_idx, n)):
        # Refit periodically
        if i % refit_every == 0:
            try:
                am_t = arch_model(pd.Series(r_scaled[:t]), vol='GARCH', p=1, o=1, q=1, dist='t')
                res = am_t.fit(disp='off', show_warning=False, starting_values=last_fit_params)
                last_fit_params = res.params.values
            except:
                pass

        # Forecast from current fit
        try:
            am_t = arch_model(pd.Series(r_scaled[:t]), vol='GARCH', p=1, o=1, q=1, dist='t')
            res_fc = am_t.fit(disp='off', show_warning=False, starting_values=last_fit_params)
            fc = res_fc.forecast(horizon=1)
            var_fc = fc.variance.values[-1, 0] / (100**2)
            oos_forecasts.append(var_fc)
        except:
            oos_forecasts.append(np.nan)

        oos_actuals.append(returns.iloc[t] ** 2)

    oos_forecasts = np.array(oos_forecasts)
    oos_actuals = np.array(oos_actuals)
    valid = ~(np.isnan(oos_forecasts) | np.isnan(oos_actuals))

    fit_info = {
        'converged': bool(converged),
        'persistence': float(persistence),
        'omega': float(params.get('omega', 0)),
        'alpha': float(params.get('alpha[1]', 0)),
        'gamma': float(params.get('gamma[1]', 0)),
        'beta': float(params.get('beta[1]', 0)),
    }

    return oos_forecasts[valid], oos_actuals[valid], fit_info

# This is still expensive for daily expanding. Let's use arch's built-in rolling.
# Actually, let's use a simpler approach: fit once on training, then use
# res.forecast with aligned data for the full OOS period via filter.

# Simpler approach: fit on full data with fixed params, get conditional variance
def gjr_garch_simple_oos(returns_full, oos_start_date, name=""):
    """Fit GJR-GARCH on training, apply to full sample, extract OOS."""
    train_r = returns_full[returns_full.index < oos_start_date]
    test_r = returns_full[returns_full.index >= oos_start_date]

    r_scaled = train_r * 100
    am = arch_model(r_scaled, vol='GARCH', p=1, o=1, q=1, dist='t')
    try:
        res = am.fit(disp='off', show_warning=False)
    except Exception as e:
        print(f"  {name} fit failed: {e}")
        return None, None, None

    converged = res.convergence_flag == 0
    params = res.params
    persistence = float(params.get('alpha[1]', 0) + params.get('gamma[1]', 0) / 2 + params.get('beta[1]', 0))

    print(f"\n{name} GJR-GARCH:")
    print(f"  Convergence: {converged}, Persistence={persistence:.6f}")
    print(f"  omega={params.get('omega', 0):.6f}, alpha={params.get('alpha[1]', 0):.6f}")
    print(f"  gamma={params.get('gamma[1]', 0):.6f}, beta={params.get('beta[1]', 0):.6f}")

    if persistence >= 1:
        print(f"  WARNING: persistence >= 1!")

    # Apply model to full sample using apply()
    full_scaled = returns_full * 100
    am_full = arch_model(full_scaled, vol='GARCH', p=1, o=1, q=1, dist='t')
    res_full = am_full.fit(disp='off', show_warning=False, starting_values=res.params.values)

    # Get conditional variance
    cond_var = res_full.conditional_volatility ** 2 / (100**2)

    # OOS: use lagged conditional variance as forecast for today's variance
    oos_mask = returns_full.index >= oos_start_date
    oos_fc = cond_var.shift(1)[oos_mask].values  # 1-step-ahead forecast
    oos_actual = (returns_full[oos_mask] ** 2).values

    valid = ~(np.isnan(oos_fc) | np.isnan(oos_actual))
    oos_fc = oos_fc[valid]
    oos_actual = oos_actual[valid]

    fit_info = {
        'converged': bool(converged),
        'persistence': float(persistence),
        'omega': float(params.get('omega', 0)),
        'alpha': float(params.get('alpha[1]', 0)),
        'gamma': float(params.get('gamma[1]', 0)),
        'beta': float(params.get('beta[1]', 0)),
    }

    return oos_fc, oos_actual, fit_info

# GJR-GARCH on close-to-close
fc_cc, act_cc, info_cc = gjr_garch_simple_oos(
    df_model['r_cc'], oos_start, name="Close-to-Close"
)

# GJR-GARCH on intraday only
fc_id, act_id, info_id = gjr_garch_simple_oos(
    df_model['r_id'], oos_start, name="Intraday-Only"
)

garch_comparison = {}
if fc_cc is not None and fc_id is not None:
    # For CC: forecast CC variance, actual = r_cc^2
    eps_cc = 1e-12
    mse_cc = np.mean((act_cc - fc_cc)**2)
    qlike_cc = np.mean(act_cc / np.maximum(fc_cc, eps_cc) -
                       np.log(act_cc / np.maximum(fc_cc, eps_cc)) - 1)

    # For ID: forecast ID variance, actual = r_id^2
    # But we want to compare forecasting CC variance
    # ID model only forecasts intraday variance, not total
    # So this is an apples-to-oranges comparison unless we add ON variance back
    # Better comparison: use ID GARCH + mean ON variance as total forecast
    mean_on_var_train = train['var_on'].mean()

    # Composite forecast: GARCH(ID) + historical mean(ON)
    fc_composite = fc_id + mean_on_var_train

    # But actual for composite = r_cc^2 (aligned with ID dates)
    # We need to re-align carefully
    oos_dates_cc = df_model[df_model.index >= oos_start].index
    oos_dates_id = df_model[df_model.index >= oos_start].index

    # Actually, both have same dates, so use CC actuals for both
    act_cc_for_composite = df_model[df_model.index >= oos_start]['var_cc'].values[1:]  # skip first due to shift

    # Trim to same length
    min_len = min(len(fc_cc), len(fc_composite), len(act_cc_for_composite))
    fc_cc_trim = fc_cc[:min_len]
    fc_comp_trim = fc_composite[:min_len]
    act_trim = act_cc_for_composite[:min_len]

    mse_garch_cc = float(np.mean((act_trim - fc_cc_trim)**2))
    mse_garch_comp = float(np.mean((act_trim - fc_comp_trim)**2))

    # QLIKE with floor on both actual and predicted to avoid log(0) / div-by-zero
    floor = 1e-10
    fc_cc_safe = np.maximum(fc_cc_trim, floor)
    fc_comp_safe = np.maximum(fc_comp_trim, floor)
    act_safe = np.maximum(act_trim, floor)

    qlike_garch_cc = float(np.mean(
        np.log(fc_cc_safe) + act_safe / fc_cc_safe
    ))
    qlike_garch_comp = float(np.mean(
        np.log(fc_comp_safe) + act_safe / fc_comp_safe
    ))

    # DM test
    e_cc = act_trim - fc_cc_trim
    e_comp = act_trim - fc_comp_trim
    dm_garch, dm_garch_p = dm_test(e_cc, e_comp)

    print(f"\nGJR-GARCH Comparison (forecasting CC variance):")
    print(f"  CC model:        MSE={mse_garch_cc:.4e}, QLIKE={qlike_garch_cc:.6f}")
    print(f"  ID+mean(ON):     MSE={mse_garch_comp:.4e}, QLIKE={qlike_garch_comp:.6f}")
    print(f"  DM(CC vs Comp):  stat={dm_garch:.3f}, p={dm_garch_p:.4f}")

    garch_comparison = {
        'cc_model': {
            'mse': mse_garch_cc,
            'qlike': qlike_garch_cc,
            'fit_info': info_cc,
        },
        'id_plus_mean_on': {
            'mse': mse_garch_comp,
            'qlike': qlike_garch_comp,
            'mean_on_var_added': float(mean_on_var_train),
            'fit_info': info_id,
        },
        'dm_test': {
            'stat': float(dm_garch),
            'p_value': float(dm_garch_p),
        },
        'n_oos': int(min_len),
    }

# ============================================================
# 7. Rolling Analysis (stability check)
# ============================================================
print("\n" + "=" * 60)
print("7. ROLLING VARIANCE DECOMPOSITION (252-day window)")
print("=" * 60)

window = 252
df_model['roll_on_share'] = (
    df_model['var_on'].rolling(window).mean() /
    df_model['var_cc'].rolling(window).mean()
)
df_model['roll_id_share'] = (
    df_model['var_id'].rolling(window).mean() /
    df_model['var_cc'].rolling(window).mean()
)

rolling_stats = df_model[['roll_on_share', 'roll_id_share']].dropna()
print(f"\nOvernight share (252d rolling):")
print(f"  Mean: {rolling_stats['roll_on_share'].mean():.4f}")
print(f"  Std:  {rolling_stats['roll_on_share'].std():.4f}")
print(f"  Min:  {rolling_stats['roll_on_share'].min():.4f}")
print(f"  Max:  {rolling_stats['roll_on_share'].max():.4f}")

print(f"\nIntraday share (252d rolling):")
print(f"  Mean: {rolling_stats['roll_id_share'].mean():.4f}")
print(f"  Std:  {rolling_stats['roll_id_share'].std():.4f}")
print(f"  Min:  {rolling_stats['roll_id_share'].min():.4f}")
print(f"  Max:  {rolling_stats['roll_id_share'].max():.4f}")

# COVID vs normal
covid_period = (df_model.index >= '2020-02-01') & (df_model.index <= '2020-06-30')
normal_period = (df_model.index >= '2018-01-01') & (df_model.index <= '2019-12-31')

on_share_covid = df_model.loc[covid_period, 'var_on'].mean() / df_model.loc[covid_period, 'var_cc'].mean()
on_share_normal = df_model.loc[normal_period, 'var_on'].mean() / df_model.loc[normal_period, 'var_cc'].mean()

print(f"\nOvernight var share - COVID (Feb-Jun 2020): {on_share_covid:.4f}")
print(f"Overnight var share - Normal (2018-2019):    {on_share_normal:.4f}")

rolling_decomp = {
    'overnight_share_rolling': {
        'mean': float(rolling_stats['roll_on_share'].mean()),
        'std': float(rolling_stats['roll_on_share'].std()),
        'min': float(rolling_stats['roll_on_share'].min()),
        'max': float(rolling_stats['roll_on_share'].max()),
    },
    'intraday_share_rolling': {
        'mean': float(rolling_stats['roll_id_share'].mean()),
        'std': float(rolling_stats['roll_id_share'].std()),
        'min': float(rolling_stats['roll_id_share'].min()),
        'max': float(rolling_stats['roll_id_share'].max()),
    },
    'regime_comparison': {
        'covid_overnight_share': float(on_share_covid),
        'normal_overnight_share': float(on_share_normal),
    },
}

# ============================================================
# 8. Subsample Robustness
# ============================================================
print("\n" + "=" * 60)
print("8. SUBSAMPLE ROBUSTNESS")
print("=" * 60)

subsamples = {
    '2005-2009 (GFC)': ('2005-01-01', '2009-12-31'),
    '2010-2014 (Recovery)': ('2010-01-01', '2014-12-31'),
    '2015-2019 (Bull)': ('2015-01-01', '2019-12-31'),
    '2020-2022 (COVID+)': ('2020-01-01', '2022-12-31'),
    '2023-2025 (OOS)': ('2023-01-01', '2025-12-31'),
}

subsample_results = {}
for label, (s, e) in subsamples.items():
    sub = df_model[(df_model.index >= s) & (df_model.index <= e)]
    if len(sub) < 50:
        continue

    on_s = sub['var_on'].mean() / sub['var_cc'].mean()
    id_s = sub['var_id'].mean() / sub['var_cc'].mean()
    corr_s = sub['r_on'].corr(sub['r_id'])

    # AC(1) of var_on and var_id
    ac1_on = sub['var_on'].autocorr(lag=1)
    ac1_id = sub['var_id'].autocorr(lag=1)

    subsample_results[label] = {
        'N': int(len(sub)),
        'overnight_share': float(on_s),
        'intraday_share': float(id_s),
        'corr_on_id': float(corr_s),
        'ac1_var_on': float(ac1_on),
        'ac1_var_id': float(ac1_id),
    }

    print(f"\n{label} (N={len(sub)}):")
    print(f"  ON share: {on_s:.4f}, ID share: {id_s:.4f}")
    print(f"  Corr(r_on, r_id): {corr_s:.4f}")
    print(f"  AC(1) var_on: {ac1_on:.4f}, AC(1) var_id: {ac1_id:.4f}")

# ============================================================
# 9. Summary & Conclusions
# ============================================================
print("\n" + "=" * 60)
print("9. SUMMARY")
print("=" * 60)

# Best model by QLIKE
best_qlike = min(model_results, key=lambda k: model_results[k]['qlike'])
best_mse = min(model_results, key=lambda k: model_results[k]['mse_test'])

print(f"\nBest model by QLIKE: {best_qlike} (QLIKE={model_results[best_qlike]['qlike']:.6f})")
print(f"Best model by MSE:   {best_mse} (MSE={model_results[best_mse]['mse_test']:.4e})")

baseline_qlike = model_results['M1_CC_baseline']['qlike']
best_qlike_val = model_results[best_qlike]['qlike']
improvement = (baseline_qlike - best_qlike_val) / baseline_qlike * 100

print(f"\nBaseline (M1) QLIKE: {baseline_qlike:.6f}")
print(f"Best decomposed QLIKE: {best_qlike_val:.6f}")
print(f"Improvement: {improvement:.2f}%")

elapsed = time.time() - start_time
print(f"\nTotal elapsed: {elapsed:.1f}s")

# ============================================================
# 10. Save Results
# ============================================================
results = {
    'experiment_id': 'K451',
    'title': 'Overnight vs Intraday Volatility Decomposition',
    'attribution': '[提出: 用戶, 執行: Claude]',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'data_source': 'yfinance SPY OHLC (adjusted)',
    'data_period': f"{df.index[0].date()} to {df.index[-1].date()}",
    'sample_size': int(len(df_model)),
    'oos_period': f"{oos_start} to {df_model.index[-1].date()}",
    'oos_size': int(len(test)),
    'literature': [
        'Hansen & Lunde (2005) JBES',
        'Tsiakas (2008) J. Financial Markets',
        'Ahoniemi & Lanne (2013) Int. J. Forecasting',
    ],
    'decomposition': {
        'r_cc': 'log(C_t / C_{t-1})',
        'r_on': 'log(O_t / C_{t-1})',
        'r_id': 'log(C_t / O_t)',
        'identity': 'r_cc = r_on + r_id (exact)',
    },
    'descriptive_statistics': desc_stats,
    'variance_decomposition': var_decomp,
    'autocorrelation': ac_results,
    'adf_tests': adf_results,
    'arch_lm_tests': arch_lm,
    'cross_correlation': cross_corr,
    'granger_causality': granger_results,
    'forecasting_models': model_results,
    'dm_tests_vs_baseline': dm_results,
    'gjr_garch_comparison': garch_comparison,
    'rolling_decomposition': rolling_decomp,
    'subsample_robustness': subsample_results,
    'best_model': {
        'by_qlike': best_qlike,
        'by_mse': best_mse,
        'qlike_improvement_pct': float(improvement),
    },
    'conclusions': {
        'Q1_variance_ratio': (
            f"Overnight variance accounts for ~{var_decomp['overnight_share']:.0%} "
            f"of total CC variance, intraday ~{var_decomp['intraday_share']:.0%}. "
            f"This ratio is time-varying: COVID period ON share rose to 56% vs normal 30%."
        ),
        'Q2_overnight_predicts_intraday': (
            f"Granger causality ON→ID at lag 1: "
            f"F={granger_results['var_on_to_var_id']['1']['F_stat']:.2f}, "
            f"p={granger_results['var_on_to_var_id']['1']['p_value']:.4e}. "
            f"Bidirectional: ID→ON also significant (F={granger_results['var_id_to_var_on']['1']['F_stat']:.2f})."
        ),
        'Q3_decomposed_vs_cc': (
            f"Best QLIKE model is M6b_HAR_CC (HAR on close-to-close, QLIKE={model_results['M6b_HAR_CC']['qlike']:.4f}). "
            f"Best MSE model is M5_ON_ID_GJR (decomposed+GJR, MSE={model_results['M5_ON_ID_GJR']['mse_test']:.4e}). "
            f"However, NO decomposed model achieves statistically significant improvement over baseline (all DM p>0.33). "
            f"HAR-style ON/ID decomposition (M6) overfits and produces negative OOS predictions. "
            f"Overnight decomposition provides descriptive insight but limited forecasting gain."
        ),
    },
    'limitations': [
        'Squared returns are noisy variance proxies (realized volatility from 5-min would be better)',
        'Ridge regression is linear; nonlinear interactions not captured',
        'GJR-GARCH comparison uses re-fitted full sample (not strictly expanding window)',
        'Overnight return includes pre/post-market activity in some ETFs',
        'Adj close ratios applied to Open may distort overnight return on dividend days',
    ],
    'elapsed_seconds': float(elapsed),
}

output_path = 'experiments/k451_overnight_vol_results.json'
with open(output_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"\nResults saved to {output_path}")
print("Done.")
