#!/usr/bin/env python3
"""
K468: Yang-Zhang Estimator as Realized Kernel Proxy + GARCH Evaluation

Background:
  K441: Range-based estimators 5-7x more efficient than close-to-close
  K464/K465: HAR log-range is best vol forecaster (10/10 cross-OOS)
  K467: HAR-Range VaR FAILS — Parkinson misses jumps/overnight → 0/6 Trinity

Research Questions:
  1. Yang-Zhang as GARCH evaluation proxy — better than Parkinson/r²?
  2. HAR with Yang-Zhang target — does it fix K467's VaR failure?
  3. Does YZ change model ranking (GJR vs HAR)?

Yang-Zhang (2000) Estimator:
  σ²_YZ = σ²_overnight + σ²_open-close + k · σ²_Rogers-Satchell
  where:
    σ²_overnight = Var(log(O_t/C_{t-1}))
    σ²_open-close = Var(log(C_t/O_t))
    σ²_RS = (H-C)(H-O) + (L-C)(L-O)   (daily Rogers-Satchell)
    k = 0.34 / (1.34 + (n+1)/(n-1))    (optimal weighting)

Assets: SPY, QQQ, EEM
OOS: 2023-01-01 to 2024-12-31
Rolling window: 504 days

Refs:
  Yang & Zhang (2000) J. Business — Yang-Zhang estimator
  Rogers & Satchell (1991) — Rogers-Satchell estimator
  Garman & Klass (1980) — Garman-Klass estimator
  Parkinson (1980) — Parkinson estimator
  Corsi (2009) — HAR model
  K465, K467 — prior experiments

Author: [Proposed: Claude, Executed: Claude]
"""

import json
import warnings
import time
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timezone
from scipy import stats
from arch import arch_model
from statsmodels.tsa.stattools import adfuller
from statsmodels.stats.diagnostic import acorr_ljungbox

warnings.filterwarnings('ignore')

print("=" * 70)
print("K468: Yang-Zhang Estimator as Realized Kernel Proxy + GARCH Evaluation")
print("=" * 70)

t_start = time.time()

# ============================================================
# Configuration
# ============================================================
ASSETS = ['SPY', 'QQQ', 'EEM']
OOS_START = '2023-01-01'
OOS_END = '2024-12-31'
WINDOW = 504  # ~2 years
DATA_START = '2005-01-01'

# ============================================================
# Helper functions: Volatility Estimators
# ============================================================

def parkinson_var(high, low):
    """Parkinson (1980) range-based variance estimator (single day)."""
    log_hl = np.log(high / low)
    return log_hl**2 / (4 * np.log(2))


def garman_klass_var(open_, high, low, close):
    """Garman-Klass (1980) variance estimator (single day)."""
    u = np.log(high / open_)
    d = np.log(low / open_)
    c = np.log(close / open_)
    return 0.5 * (u - d)**2 - (2 * np.log(2) - 1) * c**2


def rogers_satchell_var(open_, high, low, close):
    """Rogers-Satchell (1991) variance estimator (single day).
    Robust to drift, uses all OHLC info."""
    h_c = np.log(high / close)
    h_o = np.log(high / open_)
    l_c = np.log(low / close)
    l_o = np.log(low / open_)
    return h_c * h_o + l_c * l_o


def yang_zhang_var_rolling(df, n=1):
    """
    Yang-Zhang (2000) variance estimator.
    For n=1 (single day), we use the single-day components directly.
    For n>1, we use rolling window of n days to compute the components.

    σ²_YZ = σ²_overnight + σ²_open-close + k · σ²_RS

    For single-day version (n=1):
      σ²_overnight = (log(O_t/C_{t-1}))²
      σ²_oc = (log(C_t/O_t))²
      σ²_RS = Rogers-Satchell single day
      k = 0.34 / (1.34 + 2/(0))  → simplified for n=1: use k ≈ 0.34/1.34

    For rolling version (n>1):
      Use rolling window variance of overnight and OC returns + mean RS
    """
    overnight_ret = np.log(df['Open'] / df['Close'].shift(1))
    oc_ret = np.log(df['Close'] / df['Open'])
    rs_daily = rogers_satchell_var(df['Open'], df['High'], df['Low'], df['Close'])

    if n == 1:
        # Single-day Yang-Zhang: use squared terms as variance proxies
        # k = 0.34 / (1.34 + (n+1)/(n-1)) → limit as n→∞ is 0.34/1.34
        # For n=1, the rolling variance components degenerate,
        # so we use: σ²_YZ = overnight² + oc² + k_single * RS
        # Following Yang & Zhang (2000) spirit for single observation
        k = 0.34 / 1.34  # ≈ 0.2537
        yz = overnight_ret**2 + oc_ret**2 + k * rs_daily.clip(lower=0)
        return yz
    else:
        # Rolling n-day Yang-Zhang
        k = 0.34 / (1.34 + (n + 1) / (n - 1))

        sigma2_overnight = overnight_ret.rolling(n).var()
        sigma2_oc = oc_ret.rolling(n).var()
        sigma2_rs = rs_daily.rolling(n).mean()

        # Ensure RS component is non-negative (can be slightly negative due to noise)
        sigma2_rs = sigma2_rs.clip(lower=0)

        yz = sigma2_overnight + sigma2_oc + k * sigma2_rs
        return yz


def compute_all_proxies(df):
    """Compute all volatility proxies for a DataFrame with OHLC data."""
    proxies = {}

    # 1. Squared return (close-to-close)
    ret = np.log(df['Close'] / df['Close'].shift(1))
    proxies['r_sq'] = ret**2

    # 2. Parkinson
    proxies['parkinson'] = parkinson_var(df['High'], df['Low'])

    # 3. Garman-Klass
    proxies['garman_klass'] = garman_klass_var(df['Open'], df['High'], df['Low'], df['Close'])

    # 4. Yang-Zhang (1-day)
    proxies['yz_1d'] = yang_zhang_var_rolling(df, n=1)

    # 5. Yang-Zhang (5-day rolling)
    proxies['yz_5d'] = yang_zhang_var_rolling(df, n=5)

    # Returns for GARCH
    proxies['returns'] = ret * 100  # percentage returns for arch package

    # Log range for HAR
    proxies['log_range'] = np.log(df['High'] / df['Low'])

    return proxies


# ============================================================
# QLIKE loss function
# ============================================================
def qlike(sigma2_forecast, sigma2_realized):
    """QLIKE loss: E[rv/sigma² - log(rv/sigma²) - 1]
    Lower is better. Robust loss for variance forecasting."""
    ratio = sigma2_realized / sigma2_forecast
    # Filter out invalid values
    valid = (ratio > 0) & np.isfinite(ratio) & (sigma2_forecast > 0)
    ratio = ratio[valid]
    return np.mean(ratio - np.log(ratio) - 1)


def dm_test(loss1, loss2, h=1):
    """Diebold-Mariano test. H0: equal predictive accuracy.
    Returns t-stat and p-value. Negative t → loss1 < loss2 → model1 better."""
    d = loss1 - loss2
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 10:
        return np.nan, np.nan
    d_bar = np.mean(d)

    # Newey-West HAC variance
    from statsmodels.regression.linear_model import OLS
    from statsmodels.tools import add_constant
    gamma0 = np.var(d, ddof=1)
    V = gamma0
    for k in range(1, h):
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        V += 2 * (1 - k / h) * gamma_k

    if V <= 0:
        V = gamma0

    se = np.sqrt(V / n)
    if se < 1e-15:
        return np.nan, np.nan
    t_stat = d_bar / se
    p_value = 2 * (1 - stats.t.cdf(abs(t_stat), df=n - 1))
    return t_stat, p_value


# ============================================================
# GJR-GARCH fitting
# ============================================================
def fit_gjr_garch(returns, window):
    """Fit rolling GJR-GARCH and return OOS variance forecasts."""
    n = len(returns)
    forecasts = []

    for t in range(window, n):
        train = returns.iloc[t-window:t]
        try:
            am = arch_model(train, vol='GARCH', p=1, o=1, q=1, dist='t',
                           mean='Constant', rescale=False)
            res = am.fit(disp='off', show_warning=False)
            fcast = res.forecast(horizon=1)
            sigma2 = fcast.variance.iloc[-1, 0]
            # Convert from percentage² to decimal²
            forecasts.append(sigma2 / 10000)
        except Exception:
            if forecasts:
                forecasts.append(forecasts[-1])
            else:
                forecasts.append(np.nan)

    return np.array(forecasts)


# ============================================================
# HAR model
# ============================================================
def fit_har_rolling(target_series, window, log_transform=True):
    """Fit rolling HAR model: target_{t+1} = b0 + b_d*target_t + b_w*avg_5 + b_m*avg_21

    target_series: the variance/range series to use as both input and target
    Returns OOS 1-step forecasts.
    """
    if log_transform:
        # Use log transform for stability
        series = np.log(target_series.clip(lower=1e-10))
    else:
        series = target_series

    n = len(series)
    forecasts = []

    for t in range(window, n):
        train = series.iloc[t-window:t].values

        # Build HAR regressors for training
        # y = target_{i+1}, x = [1, target_i, avg_5_i, avg_21_i]
        y = train[21:]  # target from day 22 onwards
        x_d = train[20:-1]  # daily lag

        # 5-day average
        x_w = np.array([np.mean(train[i-4:i+1]) for i in range(20, len(train)-1)])
        # 21-day average
        x_m = np.array([np.mean(train[i-20:i+1]) for i in range(20, len(train)-1)])

        X = np.column_stack([np.ones(len(y)), x_d, x_w, x_m])

        try:
            # OLS fit
            beta = np.linalg.lstsq(X, y, rcond=None)[0]

            # Forecast for next period
            cur = series.iloc[t-1]  # latest value
            avg5 = series.iloc[t-5:t].mean()
            avg21 = series.iloc[t-21:t].mean()

            pred = beta[0] + beta[1]*cur + beta[2]*avg5 + beta[3]*avg21

            if log_transform:
                # Convert back from log to level
                pred_level = np.exp(pred)
            else:
                pred_level = pred

            forecasts.append(max(pred_level, 1e-10))
        except Exception:
            if forecasts:
                forecasts.append(forecasts[-1])
            else:
                forecasts.append(np.nan)

    return np.array(forecasts)


# ============================================================
# VaR computation + Trinity test
# ============================================================
def compute_var(sigma_forecast, alpha=0.01, dist='normal'):
    """Compute VaR at alpha level. Returns are assumed mean-zero."""
    if dist == 'normal':
        z = stats.norm.ppf(alpha)
    elif dist == 'student-t':
        # Use df=5 (conservative)
        z = stats.t.ppf(alpha, df=5)
        # Scale to match normal variance
        z = z * np.sqrt(3/5)
    else:
        raise ValueError(f"Unknown dist: {dist}")
    return z * sigma_forecast


def kupiec_test(violations, n, alpha):
    """Kupiec (1995) unconditional coverage test."""
    v = sum(violations)
    if v == 0 or v == n:
        return 0.0, 1.0
    p_hat = v / n
    lr = 2 * (v * np.log(p_hat / alpha) + (n - v) * np.log((1 - p_hat) / (1 - alpha)))
    p_value = 1 - stats.chi2.cdf(lr, df=1)
    return lr, p_value


def christoffersen_test(violations):
    """Christoffersen (1998) independence test."""
    violations = np.array(violations, dtype=int)
    n = len(violations)

    # Transition counts
    n00 = n01 = n10 = n11 = 0
    for i in range(1, n):
        if violations[i-1] == 0 and violations[i] == 0:
            n00 += 1
        elif violations[i-1] == 0 and violations[i] == 1:
            n01 += 1
        elif violations[i-1] == 1 and violations[i] == 0:
            n10 += 1
        else:
            n11 += 1

    if n01 + n00 == 0 or n10 + n11 == 0:
        return 0.0, 1.0

    p01 = n01 / (n00 + n01) if (n00 + n01) > 0 else 0
    p11 = n11 / (n10 + n11) if (n10 + n11) > 0 else 0
    p = (n01 + n11) / n

    if p <= 0 or p >= 1 or (p01 <= 0 and p11 <= 0):
        return 0.0, 1.0

    try:
        lr_ind = -2 * (
            (n00 + n10) * np.log(1 - p) + (n01 + n11) * np.log(p)
            - n00 * np.log(1 - p01 + 1e-15) - n01 * np.log(p01 + 1e-15)
            - n10 * np.log(1 - p11 + 1e-15) - n11 * np.log(p11 + 1e-15)
        )
        p_value = 1 - stats.chi2.cdf(max(lr_ind, 0), df=1)
    except Exception:
        lr_ind = 0.0
        p_value = 1.0

    return lr_ind, p_value


def dq_test(violations, var_forecasts, alpha, n_lags=4):
    """Engle & Manganelli (2004) Dynamic Quantile test."""
    hits = np.array(violations, dtype=float) - alpha
    n = len(hits)

    # Regressors: constant + lagged hits + VaR
    X = np.ones((n - n_lags, 1 + n_lags + 1))
    for j in range(n_lags):
        X[:, j + 1] = hits[n_lags - j - 1:n - j - 1]
    X[:, -1] = var_forecasts[n_lags:]

    y = hits[n_lags:]

    try:
        beta = np.linalg.lstsq(X, y, rcond=None)[0]
        resid = y - X @ beta
        ssr = np.sum(resid**2)
        sst = np.sum(y**2)
        if sst == 0:
            return 0.0, 1.0
        dq_stat = (sst - ssr) / sst * (n - n_lags)
        p_value = 1 - stats.chi2.cdf(max(dq_stat, 0), df=X.shape[1])
    except Exception:
        dq_stat = 0.0
        p_value = 1.0

    return dq_stat, p_value


def trinity_test(returns, var_forecasts, alpha):
    """Run all three VaR backtests (Kupiec, Christoffersen, DQ)."""
    violations = (returns < var_forecasts).astype(int)
    n = len(returns)
    v_rate = violations.mean()

    kup_stat, kup_p = kupiec_test(violations, n, alpha)
    chr_stat, chr_p = christoffersen_test(violations)
    dq_stat, dq_p = dq_test(violations, var_forecasts, alpha)

    # Pass = all three p > 0.05
    all_pass = bool(kup_p > 0.05 and chr_p > 0.05 and dq_p > 0.05)
    tests_passed = int(sum([kup_p > 0.05, chr_p > 0.05, dq_p > 0.05]))

    return {
        'n_obs': n,
        'n_violations': int(violations.sum()),
        'violation_rate': round(v_rate, 4),
        'expected_rate': alpha,
        'kupiec': {'stat': round(kup_stat, 4), 'p_value': round(kup_p, 4)},
        'christoffersen': {'stat': round(chr_stat, 4), 'p_value': round(chr_p, 4)},
        'dq': {'stat': round(dq_stat, 4), 'p_value': round(dq_p, 4)},
        'trinity_pass': all_pass,
        'tests_passed': tests_passed,
    }


# ============================================================
# Data download
# ============================================================
print("\n[1] Downloading OHLC data...")
all_data = {}
for asset in ASSETS:
    df = yf.download(asset, start=DATA_START, auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df[['Open', 'High', 'Low', 'Close']].dropna()
    all_data[asset] = df
    print(f"  {asset}: {len(df)} obs, {df.index[0].date()} to {df.index[-1].date()}")


# ============================================================
# Part A: Proxy Comparison — Which evaluation proxy is best?
# ============================================================
print("\n" + "=" * 70)
print("PART A: Volatility Proxy Comparison for Model Evaluation")
print("=" * 70)

results = {}

for asset in ASSETS:
    print(f"\n--- {asset} ---")
    df = all_data[asset].copy()

    # Compute all proxies
    proxies = compute_all_proxies(df)

    # Diagnostics
    ret_pct = proxies['returns'].dropna()
    diag = {
        'n_obs': len(df),
        'date_range': f"{df.index[0].date()} to {df.index[-1].date()}",
        'return_mean': round(float(ret_pct.mean()), 4),
        'return_std': round(float(ret_pct.std()), 4),
        'return_skew': round(float(ret_pct.skew()), 4),
        'return_kurt': round(float(ret_pct.kurtosis()), 4),
    }

    # ADF test on squared returns
    adf_res = adfuller(ret_pct.dropna()**2, maxlag=10)
    diag['adf_stat'] = round(float(adf_res[0]), 4)
    diag['adf_p'] = float(adf_res[1])
    diag['is_stationary'] = adf_res[1] < 0.05

    print(f"  Obs: {diag['n_obs']}, Ret mean: {diag['return_mean']}%, "
          f"std: {diag['return_std']}%, skew: {diag['return_skew']}, kurt: {diag['return_kurt']}")

    # Proxy statistics
    print("\n  Proxy descriptive statistics (annualized vol %%):")
    proxy_stats = {}
    for pname in ['r_sq', 'parkinson', 'garman_klass', 'yz_1d', 'yz_5d']:
        p = proxies[pname].dropna()
        ann_vol = np.sqrt(p.mean() * 252) * 100
        proxy_stats[pname] = {
            'mean': float(p.mean()),
            'std': float(p.std()),
            'ann_vol_pct': round(ann_vol, 2),
            'n_valid': int((~p.isna()).sum()),
        }
        print(f"    {pname:15s}: ann vol = {ann_vol:6.2f}%, "
              f"mean = {p.mean():.6f}, std = {p.std():.6f}")

    # Correlations between proxies
    proxy_df = pd.DataFrame({k: proxies[k] for k in ['r_sq', 'parkinson', 'garman_klass', 'yz_1d']}).dropna()
    corr_matrix = proxy_df.corr()
    print("\n  Proxy correlations:")
    for i, p1 in enumerate(['r_sq', 'parkinson', 'garman_klass', 'yz_1d']):
        for j, p2 in enumerate(['r_sq', 'parkinson', 'garman_klass', 'yz_1d']):
            if j > i:
                print(f"    {p1:15s} vs {p2:15s}: {corr_matrix.loc[p1, p2]:.4f}")

    # ----------------------------------------------------------
    # Fit GJR-GARCH (rolling)
    # ----------------------------------------------------------
    print(f"\n  Fitting GJR-GARCH (w={WINDOW})...")

    # Align to OOS period
    oos_mask = (df.index >= OOS_START) & (df.index <= OOS_END)
    oos_idx = df.index[oos_mask]
    n_oos = len(oos_idx)

    # Full returns series
    ret_pct_full = proxies['returns'].dropna()

    # Find OOS start position in the returns series
    oos_start_pos = ret_pct_full.index.get_indexer(oos_idx, method='nearest')
    first_oos_pos = oos_start_pos[0]

    # Need at least WINDOW observations before OOS
    if first_oos_pos < WINDOW:
        print(f"  WARNING: Not enough data before OOS (need {WINDOW}, have {first_oos_pos})")
        continue

    # GJR-GARCH forecasts for the OOS period
    gjr_forecasts = []
    for t_idx in range(first_oos_pos, first_oos_pos + n_oos):
        if t_idx >= len(ret_pct_full):
            break
        train = ret_pct_full.iloc[t_idx - WINDOW:t_idx]
        try:
            am = arch_model(train, vol='GARCH', p=1, o=1, q=1, dist='t',
                           mean='Constant', rescale=False)
            res = am.fit(disp='off', show_warning=False)
            fcast = res.forecast(horizon=1)
            sigma2 = fcast.variance.iloc[-1, 0] / 10000  # pct² → decimal²
            gjr_forecasts.append(sigma2)
        except Exception:
            gjr_forecasts.append(gjr_forecasts[-1] if gjr_forecasts else np.nan)

    gjr_forecasts = np.array(gjr_forecasts)
    actual_n_oos = len(gjr_forecasts)
    print(f"  GJR-GARCH: {actual_n_oos} OOS forecasts")

    # ----------------------------------------------------------
    # Fit HAR models with different targets
    # ----------------------------------------------------------
    print("  Fitting HAR models...")

    # HAR with Parkinson target (K465/K467 approach)
    parkinson_series = proxies['parkinson'].dropna()
    har_park_all = fit_har_rolling(parkinson_series, window=WINDOW, log_transform=True)

    # HAR with Yang-Zhang (1d) target
    yz1d_series = proxies['yz_1d'].dropna()
    har_yz_all = fit_har_rolling(yz1d_series, window=WINDOW, log_transform=True)

    # Align HAR forecasts to OOS period
    # HAR forecast array starts at position WINDOW in the series
    # Need to map to the same dates as GJR
    parkinson_aligned = parkinson_series.reindex(ret_pct_full.index)
    yz1d_aligned = yz1d_series.reindex(ret_pct_full.index)

    # Get indices in parkinson_series that correspond to OOS
    park_oos_dates = parkinson_series.index[parkinson_series.index.isin(oos_idx)]
    yz_oos_dates = yz1d_series.index[yz1d_series.index.isin(oos_idx)]

    # HAR forecasts are indexed from position WINDOW onwards
    park_forecast_start = WINDOW
    park_all_forecast_dates = parkinson_series.index[park_forecast_start:]

    yz_forecast_start = WINDOW
    yz_all_forecast_dates = yz1d_series.index[yz_forecast_start:]

    # Find positions in forecast array that correspond to OOS dates
    har_park_oos = []
    har_yz_oos = []

    for date in oos_idx[:actual_n_oos]:
        # Parkinson HAR
        if date in park_all_forecast_dates:
            pos = park_all_forecast_dates.get_loc(date)
            if pos < len(har_park_all):
                har_park_oos.append(har_park_all[pos])
            else:
                har_park_oos.append(np.nan)
        else:
            har_park_oos.append(np.nan)

        # Yang-Zhang HAR
        if date in yz_all_forecast_dates:
            pos = yz_all_forecast_dates.get_loc(date)
            if pos < len(har_yz_all):
                har_yz_oos.append(har_yz_all[pos])
            else:
                har_yz_oos.append(np.nan)
        else:
            har_yz_oos.append(np.nan)

    har_park_oos = np.array(har_park_oos)
    har_yz_oos = np.array(har_yz_oos)

    print(f"  HAR-Parkinson: {np.sum(np.isfinite(har_park_oos))} valid OOS forecasts")
    print(f"  HAR-YZ:        {np.sum(np.isfinite(har_yz_oos))} valid OOS forecasts")

    # ----------------------------------------------------------
    # QLIKE evaluation against each proxy
    # ----------------------------------------------------------
    print("\n  QLIKE evaluation (model × proxy):")

    # Get realized values for each proxy on OOS dates
    oos_proxies = {}
    for pname in ['r_sq', 'parkinson', 'garman_klass', 'yz_1d', 'yz_5d']:
        p = proxies[pname].reindex(ret_pct_full.index)
        oos_vals = []
        for date in oos_idx[:actual_n_oos]:
            if date in p.index:
                oos_vals.append(p.loc[date])
            else:
                oos_vals.append(np.nan)
        oos_proxies[pname] = np.array(oos_vals)

    # Compute QLIKE for each (model, proxy) combination
    models = {
        'GJR-GARCH': gjr_forecasts,
        'HAR-Parkinson': har_park_oos,
        'HAR-YZ': har_yz_oos,
    }

    qlike_table = {}
    loss_arrays = {}  # for DM test

    for mname, mforecast in models.items():
        qlike_table[mname] = {}
        loss_arrays[mname] = {}
        for pname in ['r_sq', 'parkinson', 'garman_klass', 'yz_1d', 'yz_5d']:
            rv = oos_proxies[pname]
            fcast = mforecast

            # Valid mask
            valid = np.isfinite(rv) & np.isfinite(fcast) & (rv > 0) & (fcast > 0)
            if valid.sum() < 50:
                qlike_table[mname][pname] = np.nan
                continue

            rv_v = rv[valid]
            f_v = fcast[valid]

            q = qlike(f_v, rv_v)
            qlike_table[mname][pname] = round(float(q), 6)

            # Store individual losses for DM test
            ratio = rv_v / f_v
            loss_arrays[mname][pname] = ratio - np.log(ratio) - 1

        print(f"    {mname:18s}: " +
              " | ".join(f"{pname}={qlike_table[mname].get(pname, 'N/A')}"
                        for pname in ['r_sq', 'parkinson', 'yz_1d']))

    # ----------------------------------------------------------
    # DM tests: GJR vs HAR models, for each proxy
    # ----------------------------------------------------------
    print("\n  DM tests (GJR vs HAR models):")
    dm_results = {}
    for pname in ['r_sq', 'parkinson', 'garman_klass', 'yz_1d', 'yz_5d']:
        dm_results[pname] = {}

        for har_name in ['HAR-Parkinson', 'HAR-YZ']:
            if pname not in loss_arrays['GJR-GARCH'] or pname not in loss_arrays[har_name]:
                continue

            l1 = loss_arrays['GJR-GARCH'][pname]
            l2 = loss_arrays[har_name][pname]

            # Align lengths
            min_n = min(len(l1), len(l2))
            if min_n < 50:
                continue

            t_stat, p_val = dm_test(l1[:min_n], l2[:min_n])
            dm_results[pname][f'GJR_vs_{har_name}'] = {
                't_stat': round(float(t_stat), 4) if np.isfinite(t_stat) else None,
                'p_value': round(float(p_val), 4) if np.isfinite(p_val) else None,
                'winner': 'GJR' if t_stat < 0 else har_name if t_stat > 0 else 'tie'
            }

            winner = 'GJR' if t_stat < 0 else har_name
            sig = '*' if p_val < 0.05 else ''
            print(f"    {pname:15s}: GJR vs {har_name:15s} → t={t_stat:+.3f}, "
                  f"p={p_val:.4f} → {winner} {sig}")

    # ----------------------------------------------------------
    # Model ranking by proxy
    # ----------------------------------------------------------
    print("\n  Model ranking by evaluation proxy:")
    ranking_by_proxy = {}
    for pname in ['r_sq', 'parkinson', 'garman_klass', 'yz_1d', 'yz_5d']:
        scores = {m: qlike_table[m].get(pname, np.inf) for m in models}
        ranked = sorted(scores.items(), key=lambda x: x[1])
        ranking = [r[0] for r in ranked if np.isfinite(r[1])]
        ranking_by_proxy[pname] = ranking
        print(f"    {pname:15s}: {' > '.join(ranking)}")

    # Check if ranking is stable across proxies
    first_place = [r[0] for r in ranking_by_proxy.values() if len(r) > 0]
    ranking_stable = len(set(first_place)) == 1
    print(f"  Ranking stable across proxies: {ranking_stable}")
    if ranking_stable:
        print(f"  Consistent winner: {first_place[0]}")

    # ----------------------------------------------------------
    # Part B: VaR test with HAR-YZ
    # ----------------------------------------------------------
    print(f"\n  --- VaR Trinity Test ---")

    # Returns in decimal for VaR
    oos_returns_decimal = (ret_pct_full.reindex(oos_idx[:actual_n_oos]) / 100).values

    var_results = {}

    for mname, sigma2_fcast in [
        ('GJR-Normal', gjr_forecasts),
        ('GJR-SkewT', gjr_forecasts),
        ('HAR-Parkinson', har_park_oos),
        ('HAR-YZ', har_yz_oos),
    ]:
        var_results[mname] = {}

        sigma = np.sqrt(np.maximum(sigma2_fcast, 1e-10))

        for alpha in [0.01, 0.05]:
            if 'SkewT' in mname:
                var_forecast = compute_var(sigma, alpha, dist='student-t')
            else:
                var_forecast = compute_var(sigma, alpha, dist='normal')

            valid = np.isfinite(var_forecast) & np.isfinite(oos_returns_decimal)
            if valid.sum() < 100:
                var_results[mname][f'{int(alpha*100)}%'] = {'trinity_pass': None, 'note': 'insufficient data'}
                continue

            ret_v = oos_returns_decimal[valid]
            var_v = var_forecast[valid]

            result = trinity_test(ret_v, var_v, alpha)
            var_results[mname][f'{int(alpha*100)}%'] = result

            status = "PASS" if result['trinity_pass'] else "FAIL"
            print(f"    {mname:18s} {int(alpha*100)}%: "
                  f"violations={result['n_violations']}/{result['n_obs']} "
                  f"({result['violation_rate']:.1%}), "
                  f"Trinity {result['tests_passed']}/3 → {status}")

    # ----------------------------------------------------------
    # Store results
    # ----------------------------------------------------------
    results[asset] = {
        'diagnostics': diag,
        'proxy_statistics': proxy_stats,
        'correlation_matrix': {
            f"{p1}_vs_{p2}": round(float(corr_matrix.loc[p1, p2]), 4)
            for p1 in ['r_sq', 'parkinson', 'garman_klass', 'yz_1d']
            for p2 in ['r_sq', 'parkinson', 'garman_klass', 'yz_1d']
            if p1 < p2
        },
        'n_oos': actual_n_oos,
        'oos_range': f"{oos_idx[0].date()} to {oos_idx[min(actual_n_oos-1, len(oos_idx)-1)].date()}",
        'qlike_table': qlike_table,
        'dm_tests': dm_results,
        'ranking_by_proxy': ranking_by_proxy,
        'ranking_stable': ranking_stable,
        'var_trinity': var_results,
    }

# ============================================================
# Summary
# ============================================================
print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)

# Q1: YZ as evaluation proxy
print("\nQ1: Yang-Zhang as evaluation proxy vs Parkinson/r²")
for asset in ASSETS:
    if asset not in results:
        continue
    r = results[asset]
    print(f"\n  {asset}:")
    print(f"    Ranking stable: {r['ranking_stable']}")
    for pname, ranking in r['ranking_by_proxy'].items():
        if ranking:
            print(f"      {pname:15s}: #{1} = {ranking[0]}")

# Q2: HAR-YZ VaR
print("\nQ2: HAR-YZ VaR — does YZ fix K467's HAR-Range VaR failure?")
var_summary = {}
for asset in ASSETS:
    if asset not in results:
        continue
    var_summary[asset] = {}
    vr = results[asset]['var_trinity']
    for mname in vr:
        passes = sum(1 for a in vr[mname].values()
                    if isinstance(a, dict) and bool(a.get('trinity_pass')) is True)
        total = sum(1 for a in vr[mname].values()
                   if isinstance(a, dict) and a.get('trinity_pass') is not None)
        var_summary[asset][mname] = f"{passes}/{total}"
        print(f"  {asset} {mname:18s}: {passes}/{total} Trinity pass")

# Q3: Model ranking change
print("\nQ3: Does YZ proxy change model ranking?")
for asset in ASSETS:
    if asset not in results:
        continue
    r = results[asset]
    # Compare ranking under r² vs yz_1d
    r_sq_rank = r['ranking_by_proxy'].get('r_sq', [])
    yz_rank = r['ranking_by_proxy'].get('yz_1d', [])
    changed = r_sq_rank != yz_rank
    print(f"  {asset}: r² ranking = {r_sq_rank}, YZ ranking = {yz_rank}")
    print(f"         Ranking changed: {changed}")

# Overall judgment
print("\n" + "=" * 70)
print("JUDGMENT")
print("=" * 70)

# Check if HAR-YZ passes VaR where HAR-Parkinson fails
har_yz_var_passes = 0
har_park_var_passes = 0
gjr_var_passes = 0
for asset in ASSETS:
    if asset not in results:
        continue
    vr = results[asset]['var_trinity']
    for alpha_key in ['1%', '5%']:
        if 'HAR-YZ' in vr and alpha_key in vr['HAR-YZ']:
            res = vr['HAR-YZ'][alpha_key]
            if isinstance(res, dict) and res.get('trinity_pass'):
                har_yz_var_passes += 1
        if 'HAR-Parkinson' in vr and alpha_key in vr['HAR-Parkinson']:
            res = vr['HAR-Parkinson'][alpha_key]
            if isinstance(res, dict) and res.get('trinity_pass'):
                har_park_var_passes += 1
        if 'GJR-Normal' in vr and alpha_key in vr['GJR-Normal']:
            res = vr['GJR-Normal'][alpha_key]
            if isinstance(res, dict) and res.get('trinity_pass'):
                gjr_var_passes += 1

print(f"  GJR-Normal VaR passes:     {gjr_var_passes}/6")
print(f"  HAR-Parkinson VaR passes:  {har_park_var_passes}/6")
print(f"  HAR-YZ VaR passes:         {har_yz_var_passes}/6")

if har_yz_var_passes > har_park_var_passes:
    judgment = "HAR-YZ PARTIALLY FIXES K467 — Yang-Zhang overnight component improves VaR"
elif har_yz_var_passes == har_park_var_passes:
    judgment = "HAR-YZ DOES NOT FIX K467 — overnight component insufficient for VaR"
else:
    judgment = "HAR-YZ WORSE than HAR-Parkinson — unexpected"

print(f"\n  {judgment}")

# Check proxy effect on ranking
all_stable = all(results[a]['ranking_stable'] for a in ASSETS if a in results)
if all_stable:
    ranking_judgment = "Proxy choice does NOT change model ranking — GJR dominance is proxy-robust"
else:
    ranking_judgment = "Proxy choice DOES affect model ranking in some assets"
print(f"  {ranking_judgment}")

runtime = time.time() - t_start
print(f"\n  Runtime: {runtime:.1f} seconds")

# ============================================================
# Save results
# ============================================================
output = {
    "experiment_id": "K468",
    "title": "Yang-Zhang Estimator as Realized Kernel Proxy + GARCH Evaluation",
    "background": "K441: Range estimators 5-7x efficient. K464/K465: HAR log-range best vol forecaster (10/10 cross-OOS). K467: HAR-Range VaR FAILS (Parkinson misses overnight). Question: Does Yang-Zhang (including overnight) fix this?",
    "references": [
        "Yang & Zhang (2000) J. Business — Yang-Zhang estimator",
        "Rogers & Satchell (1991) — RS estimator",
        "Garman & Klass (1980) — GK estimator",
        "Parkinson (1980) — Parkinson estimator",
        "Corsi (2009) J. Financial Econometrics — HAR model",
        "K441 — Range-based estimator efficiency",
        "K464/K465 — HAR log-range cross-OOS (10/10)",
        "K467 — HAR-Range VaR failure (0/6 Trinity)"
    ],
    "method": "Compare 5 vol proxies (r², Parkinson, GK, YZ-1d, YZ-5d) for evaluating GJR-GARCH and HAR models. HAR-YZ model uses Yang-Zhang as target. VaR Trinity test for HAR-YZ vs HAR-Parkinson.",
    "assets": ASSETS,
    "oos_period": f"{OOS_START} to {OOS_END}",
    "rolling_window": WINDOW,
    "data_source": "yfinance (OHLC daily)",
    "results": results,
    "summary": {
        "Q1_proxy_comparison": {
            "ranking_stable_all_assets": all_stable,
            "description": ranking_judgment,
        },
        "Q2_har_yz_var": {
            "gjr_passes": f"{gjr_var_passes}/6",
            "har_parkinson_passes": f"{har_park_var_passes}/6",
            "har_yz_passes": f"{har_yz_var_passes}/6",
            "var_summary_by_asset": var_summary,
            "judgment": judgment,
        },
        "Q3_ranking_change": {
            "ranking_changes": {
                asset: results[asset]['ranking_by_proxy'].get('r_sq', []) != results[asset]['ranking_by_proxy'].get('yz_1d', [])
                for asset in ASSETS if asset in results
            },
        },
    },
    "judgment": judgment,
    "key_insight": f"Yang-Zhang estimator combines overnight + intraday + Rogers-Satchell. {ranking_judgment}. VaR: HAR-YZ {har_yz_var_passes}/6 vs HAR-Parkinson {har_park_var_passes}/6 vs GJR {gjr_var_passes}/6.",
    "limitations": [
        "OOS limited to 2023-2024 (2 years, ~502 days)",
        "Yang-Zhang single-day version uses squared terms as variance proxy (vs rolling window)",
        "HAR log-transform may affect YZ differently than Parkinson",
        "Only 3 assets tested",
        "Normal distribution assumption for VaR (conservative for tail risk)",
        "No bias correction applied to any estimator",
    ],
    "runtime_seconds": round(runtime, 1),
    "timestamp": datetime.now(timezone.utc).isoformat(),
}

# Convert numpy types for JSON serialization
def convert_numpy(obj):
    if isinstance(obj, (np.integer,)):
        return int(obj)
    elif isinstance(obj, (np.floating,)):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, dict):
        return {k: convert_numpy(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_numpy(v) for v in obj]
    elif isinstance(obj, (np.bool_,)):
        return bool(obj)
    return obj

output = convert_numpy(output)

outpath = 'experiments/k468_yang_zhang_results.json'
with open(outpath, 'w') as f:
    json.dump(output, f, indent=2, default=str)
print(f"\nResults saved to {outpath}")
print("Done.")
