#!/usr/bin/env python3
"""
K630: Overnight/Intraday Volatility Decomposition
====================================================
[提出: Codex(研究建議#2 overnight/intraday decomposition), 執行: Claude]

背景:
Daily return = overnight return + intraday return. 這兩個成分有不同的動態：
- Overnight (close-to-open): 受全球新聞、財報、總經驅動 (information asymmetry)
- Intraday (open-to-close): 受交易活動、order flow 驅動 (market microstructure)

如果能分別預測這兩個成分的波動率，或許能改善整日波動率預測。

研究問題:
1. 每日變異數中 overnight vs intraday 各佔多少比例？
2. Overnight 和 intraday return 是否相關？
3. Overnight vol 是否比 intraday vol 更具持續性？
4. 將兩者分開建模是否能改善 OOS 預測？

方法:
a. GJR-GARCH on close-to-close (baseline)
b. HAR-OI: HAR 加入分離的 overnight/intraday vol 成分
c. GJR-GARCH-X(overnight): 加入隔夜報酬作為外生迴歸變數
d. Separate GJR: 分別對 overnight/intraday 估計 GJR, 組合預測

Rolling OOS: w=2000, OOS 2023-01-01 to 2024-12-31, refit every 21 days
Proxy: r²_cc (close-to-close squared return)
Metrics: QLIKE, MSE, DM test vs baseline GJR

Reference:
- Tsiakas (2008) "Overnight Information and Stochastic Volatility" JFQA
- Martens (2002) "Measuring Volatility with the Realized Range" JFE
- Hansen & Lunde (2005) "A Forecast Comparison of Volatility Models" JBES
- Bollerslev, Li, Todorov (2016) "Roughing Up Beta" JFE (overnight/intraday beta)
- Harvey, Liu, Zhu (2016) t>3.0 threshold
"""

import json
import warnings
import time
from datetime import datetime, timezone
import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from arch import arch_model

warnings.filterwarnings('ignore')

# ── Configuration ──────────────────────────────────────────────────
DATA_START = '2006-01-01'
DATA_END = '2026-03-27'
OOS_START = '2023-01-03'
OOS_END = '2024-12-31'
WINDOW = 2000          # rolling estimation window
REFIT_EVERY = 21       # refit every 21 days


# ── Data Collection ────────────────────────────────────────────────
def collect_data():
    """Download SPY with Open/Close from yfinance."""
    print("=" * 70)
    print("K630: Overnight/Intraday Volatility Decomposition")
    print("=" * 70)
    print(f"\nData source: yfinance")
    print(f"Period: {DATA_START} to {DATA_END}")

    spy = yf.download('SPY', start=DATA_START, end=DATA_END, progress=False)

    # Handle multi-level columns
    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.get_level_values(0)

    df = pd.DataFrame(index=spy.index)
    df['open'] = spy['Open']
    df['close'] = spy['Close']
    df['high'] = spy['High']
    df['low'] = spy['Low']
    df['volume'] = spy['Volume']

    # Drop NaN rows
    df = df.dropna()

    # ── Compute returns ──
    # Close-to-close return: r_cc = ln(Close_t / Close_{t-1})
    df['r_cc'] = np.log(df['close'] / df['close'].shift(1))

    # Overnight return: r_on = ln(Open_t / Close_{t-1})
    df['r_on'] = np.log(df['open'] / df['close'].shift(1))

    # Intraday return: r_id = ln(Close_t / Open_t)
    df['r_id'] = np.log(df['close'] / df['open'])

    # Drop first row (NaN from shift)
    df = df.dropna()

    # Verify decomposition: r_cc ≈ r_on + r_id
    decomp_error = (df['r_cc'] - (df['r_on'] + df['r_id'])).abs()
    max_error = decomp_error.max()
    mean_error = decomp_error.mean()
    print(f"\nDecomposition verification:")
    print(f"  r_cc = r_on + r_id")
    print(f"  Max absolute error: {max_error:.2e}")
    print(f"  Mean absolute error: {mean_error:.2e}")
    assert max_error < 1e-10, "Decomposition error too large!"

    # Squared returns as vol proxies
    df['rv_cc'] = df['r_cc'] ** 2
    df['rv_on'] = df['r_on'] ** 2
    df['rv_id'] = df['r_id'] ** 2

    print(f"\nTotal observations: {len(df)}")
    print(f"Date range: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")

    return df


# ── Descriptive Analysis ──────────────────────────────────────────
def descriptive_analysis(df):
    """Analyze overnight vs intraday return characteristics."""
    print("\n" + "=" * 70)
    print("DESCRIPTIVE ANALYSIS")
    print("=" * 70)

    results = {}

    # ── 1. Basic statistics ──
    print("\n── Return Statistics (annualized where applicable) ──")
    for name, col in [('Close-to-Close', 'r_cc'), ('Overnight', 'r_on'), ('Intraday', 'r_id')]:
        r = df[col]
        ann_mean = r.mean() * 252
        ann_std = r.std() * np.sqrt(252)
        skew = r.skew()
        kurt = r.kurtosis()
        print(f"\n  {name}:")
        print(f"    Ann. Mean:  {ann_mean:.4f} ({ann_mean*100:.2f}%)")
        print(f"    Ann. Std:   {ann_std:.4f} ({ann_std*100:.2f}%)")
        print(f"    Skewness:   {skew:.4f}")
        print(f"    Kurtosis:   {kurt:.4f}")
        print(f"    Daily obs:  {len(r)}")

        results[f'{col}_ann_mean'] = float(ann_mean)
        results[f'{col}_ann_std'] = float(ann_std)
        results[f'{col}_skewness'] = float(skew)
        results[f'{col}_kurtosis'] = float(kurt)

    # ── 2. Variance decomposition ──
    print("\n── Variance Decomposition ──")
    var_cc = df['r_cc'].var()
    var_on = df['r_on'].var()
    var_id = df['r_id'].var()
    cov_on_id = df[['r_on', 'r_id']].cov().iloc[0, 1]

    # var(r_cc) = var(r_on) + var(r_id) + 2*cov(r_on, r_id)
    var_sum = var_on + var_id + 2 * cov_on_id

    pct_on = var_on / var_cc * 100
    pct_id = var_id / var_cc * 100
    pct_cov = 2 * cov_on_id / var_cc * 100

    print(f"  Var(r_cc):       {var_cc:.8f}")
    print(f"  Var(r_on):       {var_on:.8f} ({pct_on:.1f}%)")
    print(f"  Var(r_id):       {var_id:.8f} ({pct_id:.1f}%)")
    print(f"  2*Cov(on,id):    {2*cov_on_id:.8f} ({pct_cov:.1f}%)")
    print(f"  Sum check:       {var_sum:.8f} (should ≈ {var_cc:.8f})")

    results['var_cc'] = float(var_cc)
    results['var_on'] = float(var_on)
    results['var_id'] = float(var_id)
    results['cov_on_id'] = float(cov_on_id)
    results['pct_overnight'] = float(pct_on)
    results['pct_intraday'] = float(pct_id)
    results['pct_covariance'] = float(pct_cov)

    # ── 3. Correlation between overnight and intraday ──
    print("\n── Correlation Structure ──")
    corr_on_id = df['r_on'].corr(df['r_id'])
    corr_on_id_sq = df['rv_on'].corr(df['rv_id'])
    print(f"  Corr(r_on, r_id):     {corr_on_id:.4f}")
    print(f"  Corr(r²_on, r²_id):   {corr_on_id_sq:.4f}")

    results['corr_returns_on_id'] = float(corr_on_id)
    results['corr_sq_returns_on_id'] = float(corr_on_id_sq)

    # ── 4. Autocorrelation / persistence ──
    print("\n── Autocorrelation of Squared Returns (persistence) ──")
    for name, col in [('r²_cc', 'rv_cc'), ('r²_on', 'rv_on'), ('r²_id', 'rv_id')]:
        ac1 = df[col].autocorr(lag=1)
        ac5 = df[col].autocorr(lag=5)
        ac22 = df[col].autocorr(lag=22)
        print(f"  {name}: AC(1)={ac1:.4f}, AC(5)={ac5:.4f}, AC(22)={ac22:.4f}")
        results[f'{col}_ac1'] = float(ac1)
        results[f'{col}_ac5'] = float(ac5)
        results[f'{col}_ac22'] = float(ac22)

    # ── 5. ADF stationarity test on squared returns ──
    print("\n── ADF Test on Squared Returns ──")
    from statsmodels.tsa.stattools import adfuller
    for name, col in [('r²_cc', 'rv_cc'), ('r²_on', 'rv_on'), ('r²_id', 'rv_id')]:
        adf_stat, adf_p, _, _, _, _ = adfuller(df[col].dropna(), maxlag=22)
        print(f"  {name}: ADF stat={adf_stat:.4f}, p-value={adf_p:.6f}")
        results[f'{col}_adf_stat'] = float(adf_stat)
        results[f'{col}_adf_pvalue'] = float(adf_p)

    # ── 6. ARCH LM test ──
    print("\n── ARCH LM Test (5 lags) ──")
    from statsmodels.stats.diagnostic import het_arch
    for name, col in [('r_cc', 'r_cc'), ('r_on', 'r_on'), ('r_id', 'r_id')]:
        lm_stat, lm_p, _, _ = het_arch(df[col].dropna(), nlags=5)
        print(f"  {name}: LM stat={lm_stat:.4f}, p-value={lm_p:.6f}")
        results[f'{col}_arch_lm_stat'] = float(lm_stat)
        results[f'{col}_arch_lm_pvalue'] = float(lm_p)

    # ── 7. Rolling variance ratio (overnight share over time) ──
    print("\n── Rolling Overnight Variance Share (252-day window) ──")
    roll_var_on = df['r_on'].rolling(252).var()
    roll_var_cc = df['r_cc'].rolling(252).var()
    roll_pct_on = (roll_var_on / roll_var_cc * 100).dropna()
    print(f"  Mean:   {roll_pct_on.mean():.1f}%")
    print(f"  Min:    {roll_pct_on.min():.1f}%")
    print(f"  Max:    {roll_pct_on.max():.1f}%")
    print(f"  Std:    {roll_pct_on.std():.1f}%")

    results['rolling_pct_on_mean'] = float(roll_pct_on.mean())
    results['rolling_pct_on_min'] = float(roll_pct_on.min())
    results['rolling_pct_on_max'] = float(roll_pct_on.max())
    results['rolling_pct_on_std'] = float(roll_pct_on.std())

    return results


# ── Model A: GJR-GARCH Baseline ──────────────────────────────────
def fit_gjr_baseline(returns, window):
    """Fit GJR-GARCH(1,1) on close-to-close returns."""
    r = returns * 100  # scale to percentage
    try:
        am = arch_model(r, vol='GARCH', p=1, o=1, q=1, dist='t', mean='Zero')
        res = am.fit(disp='off', options={'maxiter': 1000})
        # Accept convergence flags 0 and 1 (1 = max iterations but often fine)
        if res.convergence_flag > 1:
            # Try with normal distribution as fallback
            am2 = arch_model(r, vol='GARCH', p=1, o=1, q=1, dist='normal', mean='Zero')
            res = am2.fit(disp='off', options={'maxiter': 1000})
            if res.convergence_flag > 1:
                return None, None
        # One-step-ahead forecast (variance in %² units)
        fcast = res.forecast(horizon=1)
        h = fcast.variance.iloc[-1, 0] / 10000  # convert back to decimal
        params = {
            'omega': float(res.params.get('omega', 0)),
            'alpha': float(res.params.get('alpha[1]', 0)),
            'gamma': float(res.params.get('gamma[1]', 0)),
            'beta': float(res.params.get('beta[1]', 0)),
            'nu': float(res.params.get('nu', 0)) if 'nu' in res.params else 0,
        }
        persistence = params['alpha'] + params['gamma']/2 + params['beta']
        if persistence >= 1.0:
            return None, None
        if h <= 0 or np.isnan(h) or np.isinf(h):
            return None, None
        return h, params
    except Exception:
        return None, None


# ── Model B: HAR-OI ───────────────────────────────────────────────
def fit_har_oi(df_window, target_col='rv_cc'):
    """
    HAR with Overnight/Intraday decomposition.
    σ²_t = β₀ + β₁ r²_{on,t-1} + β₂ r²_{id,t-1}
           + β₃ avg5(r²_on) + β₄ avg5(r²_id)
           + β₅ avg22(r²_cc) + ε
    """
    from numpy.linalg import lstsq

    d = df_window.copy()

    # Lagged regressors
    d['rv_on_l1'] = d['rv_on'].shift(1)
    d['rv_id_l1'] = d['rv_id'].shift(1)
    d['rv_on_avg5'] = d['rv_on'].rolling(5).mean().shift(1)
    d['rv_id_avg5'] = d['rv_id'].rolling(5).mean().shift(1)
    d['rv_cc_avg22'] = d['rv_cc'].rolling(22).mean().shift(1)

    d = d.dropna()

    if len(d) < 50:
        return None, None

    y = d[target_col].values
    X = np.column_stack([
        np.ones(len(d)),
        d['rv_on_l1'].values,
        d['rv_id_l1'].values,
        d['rv_on_avg5'].values,
        d['rv_id_avg5'].values,
        d['rv_cc_avg22'].values,
    ])

    # OLS
    beta, residuals, _, _ = lstsq(X, y, rcond=None)

    # One-step-ahead forecast: use last available data
    last_row = d.iloc[-1]
    x_new = np.array([
        1,
        last_row['rv_on'],       # today's rv_on → tomorrow's lag1
        last_row['rv_id'],
        d['rv_on'].iloc[-5:].mean(),
        d['rv_id'].iloc[-5:].mean(),
        d['rv_cc'].iloc[-22:].mean(),
    ])
    h = float(x_new @ beta)

    # Ensure non-negative
    h = max(h, 1e-10)

    return h, {'beta': beta.tolist()}


# ── Model C: GJR-GARCH-X (overnight) ──────────────────────────────
def fit_gjr_x_overnight(df_window):
    """
    GJR-GARCH with overnight information via a two-stage approach.
    Stage 1: Fit GJR on close-to-close
    Stage 2: Regress rv_cc on (h_gjr, rv_on_lag, |r_on_lag|) to get combined forecast
    This avoids the problematic additive delta adjustment.
    """
    from numpy.linalg import lstsq

    r_cc = df_window['r_cc']
    r_on = df_window['r_on']
    rv_on = df_window['rv_on']

    try:
        # Stage 1: GJR on close-to-close
        r = r_cc * 100
        am = arch_model(r, vol='GARCH', p=1, o=1, q=1, dist='t', mean='Zero')
        res = am.fit(disp='off', options={'maxiter': 1000})
        if res.convergence_flag > 1:
            am2 = arch_model(r, vol='GARCH', p=1, o=1, q=1, dist='normal', mean='Zero')
            res = am2.fit(disp='off', options={'maxiter': 1000})
            if res.convergence_flag > 1:
                return None, None

        h_gjr = res.conditional_volatility.values ** 2 / 10000  # decimal scale

        # Stage 2: Regress rv_cc on h_gjr and overnight features
        rv_cc = (r_cc ** 2).values
        rv_on_lag = rv_on.shift(1).values
        abs_r_on_lag = np.abs(r_on.shift(1).values)

        # Align (drop first obs due to lag)
        valid = ~np.isnan(rv_on_lag)
        n = np.sum(valid)
        if n < 50:
            return None, None

        y = rv_cc[valid]
        X = np.column_stack([
            np.ones(n),
            h_gjr[valid],
            rv_on_lag[valid],
            abs_r_on_lag[valid],
        ])

        beta, _, _, _ = lstsq(X, y, rcond=None)

        # Forecast
        fcast = res.forecast(horizon=1)
        h_gjr_next = fcast.variance.iloc[-1, 0] / 10000
        last_rv_on = rv_on.iloc[-1]
        last_abs_on = abs(r_on.iloc[-1])

        h = beta[0] + beta[1] * h_gjr_next + beta[2] * last_rv_on + beta[3] * last_abs_on
        h = max(h, 1e-10)

        if np.isnan(h) or np.isinf(h):
            return None, None

        return h, {
            'beta_const': float(beta[0]),
            'beta_gjr': float(beta[1]),
            'beta_rv_on': float(beta[2]),
            'beta_abs_on': float(beta[3]),
        }
    except Exception:
        return None, None


# ── Model D: Separate GJR (overnight + intraday) ──────────────────
def fit_separate_gjr(df_window):
    """
    Fit GJR separately on overnight and intraday returns.
    Combined forecast: h_cc = h_on + h_id + 2*rho*sqrt(h_on*h_id)
    where rho is the rolling correlation.
    """
    r_on = df_window['r_on'] * 100
    r_id = df_window['r_id'] * 100

    try:
        # Fit GJR on overnight
        am_on = arch_model(r_on, vol='GARCH', p=1, o=1, q=1, dist='t', mean='Zero')
        res_on = am_on.fit(disp='off', options={'maxiter': 1000})
        if res_on.convergence_flag > 1:
            am_on2 = arch_model(r_on, vol='GARCH', p=1, o=1, q=1, dist='normal', mean='Zero')
            res_on = am_on2.fit(disp='off', options={'maxiter': 1000})
            if res_on.convergence_flag > 1:
                return None, None

        # Fit GJR on intraday
        am_id = arch_model(r_id, vol='GARCH', p=1, o=1, q=1, dist='t', mean='Zero')
        res_id = am_id.fit(disp='off', options={'maxiter': 1000})
        if res_id.convergence_flag > 1:
            am_id2 = arch_model(r_id, vol='GARCH', p=1, o=1, q=1, dist='normal', mean='Zero')
            res_id = am_id2.fit(disp='off', options={'maxiter': 1000})
            if res_id.convergence_flag > 1:
                return None, None

        # Check persistence
        for res, name in [(res_on, 'overnight'), (res_id, 'intraday')]:
            a = float(res.params.get('alpha[1]', 0))
            g = float(res.params.get('gamma[1]', 0))
            b = float(res.params.get('beta[1]', 0))
            if a + g/2 + b >= 1.0:
                return None, None

        # Forecasts
        h_on = res_on.forecast(horizon=1).variance.iloc[-1, 0] / 10000
        h_id = res_id.forecast(horizon=1).variance.iloc[-1, 0] / 10000

        # Rolling correlation for covariance term
        rho = df_window['r_on'].corr(df_window['r_id'])

        # Combined forecast
        h_cc = h_on + h_id + 2 * rho * np.sqrt(max(h_on, 0) * max(h_id, 0))
        h_cc = max(h_cc, 1e-10)

        return h_cc, {
            'h_on': float(h_on),
            'h_id': float(h_id),
            'rho': float(rho),
        }
    except Exception:
        return None, None


# ── EWMA Fallback ─────────────────────────────────────────────────
def ewma_forecast(returns, lam=0.94):
    """Simple EWMA forecast as fallback when GJR fails."""
    r2 = (returns ** 2).values
    h = r2[0]
    for t in range(1, len(r2)):
        h = lam * h + (1 - lam) * r2[t]
    return float(h)


# ── Rolling OOS Evaluation ─────────────────────────────────────────
def rolling_oos(df):
    """Rolling OOS evaluation of all 4 models."""
    print("\n" + "=" * 70)
    print("ROLLING OUT-OF-SAMPLE EVALUATION")
    print("=" * 70)
    print(f"  Window:        {WINDOW}")
    print(f"  OOS period:    {OOS_START} to {OOS_END}")
    print(f"  Refit every:   {REFIT_EVERY} days")

    # Identify OOS dates
    oos_mask = (df.index >= OOS_START) & (df.index <= OOS_END)
    oos_dates = df.index[oos_mask]
    print(f"  OOS days:      {len(oos_dates)}")

    if len(oos_dates) == 0:
        print("ERROR: No OOS dates found!")
        return {}

    # Find first OOS position
    all_dates = df.index
    first_oos_pos = all_dates.get_loc(oos_dates[0])

    if first_oos_pos < WINDOW:
        print(f"ERROR: Not enough data before OOS start. Need {WINDOW}, have {first_oos_pos}")
        return {}

    # Storage for forecasts
    forecasts = {
        'gjr_baseline': [],
        'har_oi': [],
        'gjr_x_on': [],
        'separate_gjr': [],
    }
    actuals = []
    valid_dates = []

    # Cache for fitted model RESULTS (not just forecasts)
    last_fit_day = -REFIT_EVERY  # force fit on first day
    cached_gjr_res = None   # arch model result object
    cached_gjrx_delta = None
    cached_sep_res = None   # (res_on, res_id)

    gjr_fail_count = 0
    gjrx_fail_count = 0
    sep_fail_count = 0

    t0 = time.time()

    for i, date in enumerate(oos_dates):
        pos = all_dates.get_loc(date)
        window_start = pos - WINDOW
        if window_start < 0:
            continue

        window_data = df.iloc[window_start:pos]
        actual_rv = df.iloc[pos]['rv_cc']

        need_refit = (i - last_fit_day) >= REFIT_EVERY or i == 0

        # ── Model A: GJR Baseline ──
        # Always refit GJR on full window (fast: ~6ms)
        h_gjr, p_gjr = fit_gjr_baseline(window_data['r_cc'], WINDOW)
        if h_gjr is None:
            # Fallback to EWMA
            h_gjr = ewma_forecast(window_data['r_cc'])
            gjr_fail_count += 1

        # ── Model B: HAR-OI ──
        # Always refit (OLS is instant)
        h_har, _ = fit_har_oi(window_data)
        if h_har is None:
            h_har = h_gjr  # fallback

        # ── Model C: GJR-X(overnight) ──
        if need_refit:
            last_fit_day = i
            h_gjrx, p_gjrx = fit_gjr_x_overnight(window_data)
            if h_gjrx is not None:
                cached_gjrx_delta = p_gjrx
            else:
                gjrx_fail_count += 1
                h_gjrx = h_gjr  # fallback

            # ── Model D: Separate GJR ──
            h_sep, p_sep = fit_separate_gjr(window_data)
            if h_sep is None:
                sep_fail_count += 1
                h_sep = h_gjr  # fallback
        else:
            # GJR-X: refit (uses OLS stage 2, fast enough)
            h_gjrx, p_gjrx = fit_gjr_x_overnight(window_data)
            if h_gjrx is None:
                h_gjrx = h_gjr

            # Separate GJR: slower but refit for proper comparison
            h_sep, _ = fit_separate_gjr(window_data)
            if h_sep is None:
                h_sep = h_gjr

        # Always record (no skip)
        forecasts['gjr_baseline'].append(h_gjr)
        forecasts['har_oi'].append(h_har)
        forecasts['gjr_x_on'].append(h_gjrx)
        forecasts['separate_gjr'].append(h_sep)
        actuals.append(actual_rv)
        valid_dates.append(date)

        if (i + 1) % 100 == 0:
            elapsed = time.time() - t0
            print(f"  Processed {i+1}/{len(oos_dates)} OOS days ({elapsed:.1f}s)")

    elapsed = time.time() - t0
    print(f"\n  Total time: {elapsed:.1f}s")
    print(f"  Valid forecasts: {len(actuals)}/{len(oos_dates)}")
    print(f"  GJR baseline fallbacks (EWMA): {gjr_fail_count}")
    print(f"  GJR-X fallbacks: {gjrx_fail_count}")
    print(f"  Separate GJR fallbacks: {sep_fail_count}")

    return forecasts, np.array(actuals), valid_dates


# ── Loss Functions ─────────────────────────────────────────────────
def qlike(actual, forecast):
    """QLIKE loss: actual/forecast - ln(actual/forecast) - 1"""
    forecast = np.maximum(forecast, 1e-12)
    actual = np.maximum(actual, 1e-12)
    return np.mean(actual / forecast - np.log(actual / forecast) - 1)


def mse(actual, forecast):
    """MSE loss"""
    return np.mean((actual - forecast) ** 2)


def dm_test(actual, h1_forecast, h0_forecast, loss_fn='qlike'):
    """
    Diebold-Mariano test (H0: equal predictive ability).
    Negative t-stat means h1 is better than h0.
    """
    if loss_fn == 'qlike':
        d1 = actual / np.maximum(h1_forecast, 1e-12) - np.log(np.maximum(actual, 1e-12) / np.maximum(h1_forecast, 1e-12)) - 1
        d0 = actual / np.maximum(h0_forecast, 1e-12) - np.log(np.maximum(actual, 1e-12) / np.maximum(h0_forecast, 1e-12)) - 1
    else:  # MSE
        d1 = (actual - h1_forecast) ** 2
        d0 = (actual - h0_forecast) ** 2

    d = d1 - d0  # negative if h1 better
    n = len(d)

    # HAC standard error (Newey-West with bandwidth = int(n^(1/3)))
    bandwidth = max(1, int(n ** (1/3)))
    d_mean = d.mean()
    gamma0 = np.var(d, ddof=1)

    # Autocovariances
    gamma_sum = 0
    for j in range(1, bandwidth + 1):
        w = 1 - j / (bandwidth + 1)  # Bartlett kernel
        gamma_j = np.mean((d[j:] - d_mean) * (d[:-j] - d_mean))
        gamma_sum += 2 * w * gamma_j

    var_d = gamma0 + gamma_sum
    se = np.sqrt(max(var_d / n, 1e-20))
    t_stat = d_mean / se
    p_value = 2 * stats.t.sf(abs(t_stat), df=n - 1)

    return float(t_stat), float(p_value)


# ── Evaluation ─────────────────────────────────────────────────────
def evaluate_models(forecasts, actuals, valid_dates):
    """Calculate loss metrics and DM tests."""
    print("\n" + "=" * 70)
    print("MODEL EVALUATION")
    print("=" * 70)

    actuals = np.array(actuals)
    results = {}

    model_names = {
        'gjr_baseline': 'GJR-GARCH (baseline)',
        'har_oi': 'HAR-OI',
        'gjr_x_on': 'GJR-X(overnight)',
        'separate_gjr': 'Separate GJR',
    }

    # ── Loss metrics ──
    print("\n── Loss Metrics ──")
    print(f"  {'Model':<25} {'QLIKE':>12} {'MSE (×10⁸)':>12} {'QLIKE rank':>12}")
    print("  " + "-" * 63)

    losses = {}
    for key in forecasts:
        f = np.array(forecasts[key])
        q = qlike(actuals, f)
        m = mse(actuals, f)
        losses[key] = {'qlike': q, 'mse': m}
        results[f'{key}_qlike'] = float(q)
        results[f'{key}_mse'] = float(m)

    # Rank by QLIKE
    ranked = sorted(losses.items(), key=lambda x: x[1]['qlike'])
    for rank, (key, loss) in enumerate(ranked, 1):
        name = model_names[key]
        print(f"  {name:<25} {loss['qlike']:>12.6f} {loss['mse']*1e8:>12.4f} {rank:>12}")
        results[f'{key}_qlike_rank'] = rank

    # ── DM tests vs baseline ──
    print("\n── Diebold-Mariano Tests vs GJR Baseline ──")
    print(f"  {'Model':<25} {'DM(QLIKE)':>10} {'p-value':>10} {'DM(MSE)':>10} {'p-value':>10} {'Better?':>10}")
    print("  " + "-" * 75)

    baseline = np.array(forecasts['gjr_baseline'])

    for key in ['har_oi', 'gjr_x_on', 'separate_gjr']:
        f = np.array(forecasts[key])
        dm_q, p_q = dm_test(actuals, f, baseline, 'qlike')
        dm_m, p_m = dm_test(actuals, f, baseline, 'mse')
        better = "Yes*" if (dm_q < 0 and p_q < 0.05) else ("Yes" if dm_q < 0 else "No")
        name = model_names[key]
        print(f"  {name:<25} {dm_q:>10.4f} {p_q:>10.4f} {dm_m:>10.4f} {p_m:>10.4f} {better:>10}")

        results[f'{key}_dm_qlike_t'] = float(dm_q)
        results[f'{key}_dm_qlike_p'] = float(p_q)
        results[f'{key}_dm_mse_t'] = float(dm_m)
        results[f'{key}_dm_mse_p'] = float(p_m)

    # Harvey (2016) threshold check
    print("\n  Note: Harvey (2016) requires |t| > 3.0 for claimed significance")
    for key in ['har_oi', 'gjr_x_on', 'separate_gjr']:
        dm_q = results[f'{key}_dm_qlike_t']
        if abs(dm_q) > 3.0:
            print(f"  ✓ {model_names[key]}: |t|={abs(dm_q):.2f} > 3.0 — passes Harvey threshold")
        else:
            print(f"  ✗ {model_names[key]}: |t|={abs(dm_q):.2f} ≤ 3.0 — does NOT pass Harvey threshold")

    # ── Forecast correlation ──
    print("\n── Forecast Correlations ──")
    corr_matrix = {}
    keys = list(forecasts.keys())
    for i, k1 in enumerate(keys):
        for k2 in keys[i+1:]:
            corr = np.corrcoef(forecasts[k1], forecasts[k2])[0, 1]
            print(f"  Corr({model_names[k1]}, {model_names[k2]}): {corr:.4f}")
            results[f'corr_{k1}_{k2}'] = float(corr)

    # ── Mincer-Zarnowitz regression ──
    print("\n── Mincer-Zarnowitz Regressions (actual = a + b*forecast) ──")
    print(f"  {'Model':<25} {'a':>10} {'b':>10} {'R²':>10} {'b=1 t-stat':>12}")
    print("  " + "-" * 70)

    for key in forecasts:
        f = np.array(forecasts[key])
        slope, intercept, r_value, p_value, std_err = stats.linregress(f, actuals)
        r2 = r_value ** 2
        t_b1 = (slope - 1) / std_err  # test H0: b=1
        name = model_names[key]
        print(f"  {name:<25} {intercept:>10.6f} {slope:>10.4f} {r2:>10.4f} {t_b1:>12.4f}")

        results[f'{key}_mz_intercept'] = float(intercept)
        results[f'{key}_mz_slope'] = float(slope)
        results[f'{key}_mz_r2'] = float(r2)
        results[f'{key}_mz_b1_tstat'] = float(t_b1)

    return results


# ── Sub-period Analysis ──────────────────────────────────────────
def subperiod_analysis(df):
    """Analyze overnight share in different volatility regimes."""
    print("\n" + "=" * 70)
    print("SUB-PERIOD ANALYSIS")
    print("=" * 70)

    results = {}

    # Split by VIX regime proxy: rolling 22-day vol of r_cc
    df = df.copy()
    df['rolling_vol'] = df['r_cc'].rolling(22).std() * np.sqrt(252)
    df = df.dropna()

    # Terciles
    q33, q67 = df['rolling_vol'].quantile([0.33, 0.67])

    regimes = {
        'low_vol': df[df['rolling_vol'] <= q33],
        'mid_vol': df[(df['rolling_vol'] > q33) & (df['rolling_vol'] <= q67)],
        'high_vol': df[df['rolling_vol'] > q67],
    }

    print(f"\n  Regime thresholds: q33={q33*100:.1f}%, q67={q67*100:.1f}%")

    for regime, rdf in regimes.items():
        var_on = rdf['r_on'].var()
        var_id = rdf['r_id'].var()
        var_cc = rdf['r_cc'].var()
        pct_on = var_on / var_cc * 100

        print(f"\n  {regime} ({len(rdf)} days):")
        print(f"    Overnight share: {pct_on:.1f}%")
        print(f"    Var(r_cc): {var_cc:.8f}")
        print(f"    AC1(r²_on): {rdf['rv_on'].autocorr(1):.4f}")
        print(f"    AC1(r²_id): {rdf['rv_id'].autocorr(1):.4f}")

        results[f'{regime}_n'] = len(rdf)
        results[f'{regime}_pct_overnight'] = float(pct_on)
        results[f'{regime}_var_cc'] = float(var_cc)

    # Pre/post COVID comparison
    print("\n── Pre-COVID vs COVID vs Post-COVID ──")
    periods = {
        'pre_covid': df[df.index < '2020-01-01'],
        'covid': df[(df.index >= '2020-01-01') & (df.index < '2021-01-01')],
        'post_covid': df[df.index >= '2021-01-01'],
    }

    for period, pdf in periods.items():
        if len(pdf) < 50:
            continue
        var_on = pdf['r_on'].var()
        var_cc = pdf['r_cc'].var()
        pct_on = var_on / var_cc * 100
        print(f"  {period} ({len(pdf)} days): overnight share = {pct_on:.1f}%")
        results[f'{period}_pct_overnight'] = float(pct_on)
        results[f'{period}_n'] = len(pdf)

    return results


# ── Overnight Asymmetry Analysis ──────────────────────────────────
def overnight_asymmetry(df):
    """
    Test whether overnight returns have asymmetric effect on next-day volatility.
    Key question: Does a large negative overnight gap predict higher intraday vol?
    """
    print("\n" + "=" * 70)
    print("OVERNIGHT ASYMMETRY ANALYSIS")
    print("=" * 70)

    results = {}

    d = df.copy()
    d['abs_r_on'] = d['r_on'].abs()
    d['r_on_neg'] = (d['r_on'] < 0).astype(int)
    d['r_on_neg_sq'] = d['r_on_neg'] * d['r_on'] ** 2

    # Next-day intraday vol (lead rv_id by 0 since r_on_t affects rv_id_t same day)
    # Actually: r_on_t = ln(Open_t/Close_{t-1}) affects rv_id_t = (Close_t-Open_t)²
    # So we test: does today's overnight gap predict today's intraday volatility?

    # Regression: rv_id_t = a + b1*rv_on_t + b2*(r_on_t<0)*rv_on_t + e
    from numpy.linalg import lstsq

    y = d['rv_id'].values
    X = np.column_stack([
        np.ones(len(d)),
        d['rv_on'].values,
        d['r_on_neg_sq'].values,  # interaction: negative overnight * r_on²
    ])

    beta, _, _, _ = lstsq(X, y, rcond=None)
    y_hat = X @ beta
    residuals = y - y_hat
    ss_res = np.sum(residuals ** 2)
    ss_tot = np.sum((y - y.mean()) ** 2)
    r2 = 1 - ss_res / ss_tot

    # Standard errors
    n, k = X.shape
    mse_resid = ss_res / (n - k)
    var_beta = mse_resid * np.linalg.inv(X.T @ X).diagonal()
    se_beta = np.sqrt(var_beta)
    t_stats = beta / se_beta

    print(f"\n  Regression: rv_id_t = a + b1*rv_on_t + b2*I(r_on<0)*r²_on_t")
    print(f"  R² = {r2:.4f}, n = {n}")
    print(f"  {'Param':<15} {'Coeff':>12} {'Std Err':>12} {'t-stat':>10}")
    print(f"  {'-'*50}")
    labels = ['intercept', 'rv_on', 'neg_overnight']
    for j, label in enumerate(labels):
        print(f"  {label:<15} {beta[j]:>12.8f} {se_beta[j]:>12.8f} {t_stats[j]:>10.4f}")
        results[f'asym_{label}_coeff'] = float(beta[j])
        results[f'asym_{label}_tstat'] = float(t_stats[j])

    results['asym_r2'] = float(r2)

    # Overnight gap quintile analysis
    print("\n── Overnight Return Quintile → Same-Day Intraday Vol ──")
    d['on_quintile'] = pd.qcut(d['r_on'], 5, labels=['Q1(neg)', 'Q2', 'Q3', 'Q4', 'Q5(pos)'])
    quintile_vol = d.groupby('on_quintile')['rv_id'].mean()
    print(f"  {'Quintile':<12} {'Mean rv_id':>12} {'Ratio to Q3':>12}")
    q3_val = quintile_vol.iloc[2]
    for q_name, val in quintile_vol.items():
        ratio = val / q3_val
        print(f"  {q_name:<12} {val:>12.8f} {ratio:>12.4f}")
        results[f'quintile_{q_name}_rv_id'] = float(val)

    return results


# ── Main ──────────────────────────────────────────────────────────
def main():
    start_time = time.time()

    # Collect data
    df = collect_data()

    # Descriptive analysis
    desc_results = descriptive_analysis(df)

    # Rolling OOS evaluation
    oos_output = rolling_oos(df)
    if isinstance(oos_output, dict) and len(oos_output) == 0:
        print("ERROR: OOS evaluation failed")
        return

    forecasts, actuals, valid_dates = oos_output

    # Evaluate models
    eval_results = evaluate_models(forecasts, actuals, valid_dates)

    # Sub-period analysis
    subperiod_results = subperiod_analysis(df)

    # Overnight asymmetry analysis
    asym_results = overnight_asymmetry(df)

    # ── Compile results ──
    total_time = time.time() - start_time

    # Determine key finding
    best_model = min(
        ['gjr_baseline', 'har_oi', 'gjr_x_on', 'separate_gjr'],
        key=lambda k: eval_results.get(f'{k}_qlike', float('inf'))
    )

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"  Best model by QLIKE: {best_model}")
    print(f"  Overnight variance share: {desc_results.get('pct_overnight', 0):.1f}%")
    print(f"  Overnight/Intraday correlation: {desc_results.get('corr_returns_on_id', 0):.4f}")
    print(f"  Total runtime: {total_time:.1f}s")

    # Check if decomposition improves prediction
    baseline_qlike = eval_results.get('gjr_baseline_qlike', float('inf'))
    improvements = {}
    for model in ['har_oi', 'gjr_x_on', 'separate_gjr']:
        model_qlike = eval_results.get(f'{model}_qlike', float('inf'))
        pct_change = (model_qlike - baseline_qlike) / baseline_qlike * 100
        dm_t = eval_results.get(f'{model}_dm_qlike_t', 0)
        dm_p = eval_results.get(f'{model}_dm_qlike_p', 1)
        improvements[model] = {
            'qlike_pct_change': float(pct_change),
            'dm_t': float(dm_t),
            'dm_p': float(dm_p),
            'significant_5pct': bool(dm_p < 0.05 and dm_t < 0),
            'passes_harvey': bool(abs(dm_t) > 3.0),
        }
        print(f"\n  {model}:")
        print(f"    QLIKE change: {pct_change:+.2f}%")
        print(f"    DM t-stat: {dm_t:.4f}, p-value: {dm_p:.4f}")
        print(f"    Significant (5%): {dm_p < 0.05 and dm_t < 0}")
        print(f"    Harvey (|t|>3): {abs(dm_t) > 3.0}")

    # Save results
    all_results = {
        'experiment_id': 'K630',
        'title': 'Overnight/Intraday Volatility Decomposition',
        'proposer': 'Codex (research suggestion #2)',
        'executor': 'Claude',
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'data_source': 'yfinance',
        'asset': 'SPY',
        'period': f'{DATA_START} to {DATA_END}',
        'oos_period': f'{OOS_START} to {OOS_END}',
        'window': WINDOW,
        'refit_every': REFIT_EVERY,
        'n_observations': len(df),
        'n_oos': len(actuals),
        'analysis_type': '實證分析（真實數據）',
        'descriptive': desc_results,
        'evaluation': eval_results,
        'subperiod': subperiod_results,
        'asymmetry': asym_results,
        'improvements_vs_baseline': improvements,
        'best_model': best_model,
        'key_findings': {
            'overnight_variance_share_pct': desc_results.get('pct_overnight', 0),
            'overnight_intraday_corr': desc_results.get('corr_returns_on_id', 0),
            'overnight_more_persistent': desc_results.get('rv_on_ac1', 0) > desc_results.get('rv_id_ac1', 0),
            'decomposition_improves_forecast': any(v['significant_5pct'] for v in improvements.values()),
            'passes_harvey_threshold': any(v['passes_harvey'] for v in improvements.values()),
        },
        'references': [
            'Tsiakas (2008) "Overnight Information and Stochastic Volatility" JFQA',
            'Martens (2002) "Measuring Volatility with the Realized Range" JFE',
            'Hansen & Lunde (2005) "A Forecast Comparison of Volatility Models" JBES',
            'Bollerslev, Li, Todorov (2016) "Roughing Up Beta" JFE',
            'Harvey, Liu, Zhu (2016) t>3.0 threshold',
        ],
        'limitations': [
            'Proxy: uses r²_cc not RV (no intraday data for full realized variance)',
            'Overnight return assumes no after-hours trading adjustments',
            'Open price may reflect pre-market activity, not purely overnight news',
            'Single asset (SPY), results may differ for other assets',
            'OOS period (2023-2024) includes specific market conditions',
        ],
        'total_runtime_seconds': float(total_time),
    }

    output_path = 'experiments/k630_results.json'
    with open(output_path, 'w') as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"\n  Results saved to: {output_path}")


if __name__ == '__main__':
    main()
