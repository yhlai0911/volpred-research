"""
K188: HAR Ceiling Test — Does HAR-RV Beat GARCH on Daily Data?
===============================================================
[提出: 用戶, 執行: Claude]

Research Question:
  If HAR (the high-frequency workhorse) also hits the same predictive ceiling
  as GARCH on daily data, then the ceiling is in the DATA, not the MODEL.

Methodology:
  1. Construct daily realized vol proxies from OHLC:
     - Squared return (c2c): r²
     - Parkinson: (H-L)² / (4*ln2)
     - Garman-Klass: 0.5*(H-L)² - (2*ln2-1)*C²
     - Rogers-Satchell
  2. HAR model on each proxy (rolling w=500):
     RV_t = β0 + β1*RV_{t-1} + β5*mean(RV_{t-5:t-1}) + β22*mean(RV_{t-22:t-1})
  3. Extensions:
     - HAR-X: add VIX as exogenous regressor
     - AHAR: separate negative/positive RV components
  4. Benchmark: GJR-GARCH(1,1,1) w=2000
  5. Evaluation: QLIKE, MSE, DM test with Newey-West HAC

Assets: SPY, QQQ, GLD, TLT, BTC-USD
OOS: 2023-01-01 to 2024-12-31
"""

import sys
import json
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime
from pathlib import Path
from arch import arch_model
from scipy import stats

warnings.filterwarnings('ignore')

# ============================================================
# CONFIGURATION
# ============================================================
ASSETS = ['SPY', 'QQQ', 'GLD', 'TLT', 'BTC-USD']
HAR_WINDOW = 500
GARCH_WINDOW = 2000
OOS_START = '2023-01-01'
OOS_END = '2024-12-31'
DATA_START = '2007-01-01'

RESULTS_DIR = Path(__file__).resolve().parent
RESULTS_FILE = RESULTS_DIR / 'k188_har_ceiling_results.json'

print("=" * 70)
print("K188: HAR Ceiling Test — Does HAR-RV Beat GARCH on Daily Data?")
print("=" * 70)
print(f"Assets: {ASSETS}")
print(f"HAR window: {HAR_WINDOW}, GARCH window: {GARCH_WINDOW}")
print(f"OOS: {OOS_START} to {OOS_END}")

# ============================================================
# 1. REALIZED VARIANCE PROXIES FROM DAILY OHLC
# ============================================================

def compute_rv_proxies(df):
    """
    Compute 4 daily realized variance proxies from OHLC data.
    All in log-return² units.
    """
    close = df['close'].values
    high = df['high'].values
    low = df['low'].values
    opn = df['open'].values

    n = len(df)
    proxies = {}

    # Log values
    log_close = np.log(close)
    log_high = np.log(high)
    log_low = np.log(low)
    log_open = np.log(opn)

    # 1. Squared return (close-to-close)
    ret = np.diff(log_close)
    c2c = ret ** 2
    proxies['c2c'] = pd.Series(c2c, index=df.index[1:])

    # 2. Parkinson (1980): uses H-L range
    # Var = (H-L)² / (4*ln2)
    hl = log_high - log_low
    parkinson = hl ** 2 / (4.0 * np.log(2.0))
    proxies['parkinson'] = pd.Series(parkinson, index=df.index)

    # 3. Garman-Klass (1980): uses OHLC
    # Var = 0.5*(H-L)² - (2*ln2-1)*(C-O)²
    co = log_close - log_open
    gk = 0.5 * hl ** 2 - (2.0 * np.log(2.0) - 1.0) * co ** 2
    proxies['garman_klass'] = pd.Series(gk, index=df.index)

    # 4. Rogers-Satchell (1991): uses OHLC, allows for drift
    # Var = (H-C)*(H-O) + (L-C)*(L-O)
    rs = ((log_high - log_close) * (log_high - log_open) +
          (log_low - log_close) * (log_low - log_open))
    proxies['rogers_satchell'] = pd.Series(rs, index=df.index)

    return proxies


# ============================================================
# 2. HAR MODEL (OLS, ROLLING WINDOW)
# ============================================================

def har_rolling_forecast(rv_series, window=500, oos_start_idx=None):
    """
    HAR(1,5,22) rolling window forecast.
    RV_t = β0 + β1*RV_{t-1} + β5*mean(RV_{t-5:t-1}) + β22*mean(RV_{t-22:t-1}) + ε

    Returns: Series of one-step-ahead forecasts for OOS period.
    """
    rv = rv_series.values
    n = len(rv)
    forecasts = []
    forecast_dates = []

    for t in range(oos_start_idx, n):
        # Need at least window + 22 obs before t
        start = max(0, t - window)
        if t - start < 50:  # need minimum obs for OLS
            continue

        # Build regressors for in-sample [start, t)
        y_train = []
        X_train = []
        for i in range(start + 22, t):
            y_train.append(rv[i])
            rv_1 = rv[i - 1]
            rv_5 = np.mean(rv[i - 5:i])
            rv_22 = np.mean(rv[i - 22:i])
            X_train.append([1.0, rv_1, rv_5, rv_22])

        if len(y_train) < 30:
            continue

        y_train = np.array(y_train)
        X_train = np.array(X_train)

        # OLS: β = (X'X)^{-1} X'y
        try:
            XtX = X_train.T @ X_train
            Xty = X_train.T @ y_train
            beta = np.linalg.solve(XtX, Xty)
        except np.linalg.LinAlgError:
            continue

        # Forecast for t
        rv_1 = rv[t - 1]
        rv_5 = np.mean(rv[t - 5:t])
        rv_22 = np.mean(rv[t - 22:t])
        x_new = np.array([1.0, rv_1, rv_5, rv_22])
        fcast = x_new @ beta

        # Floor at small positive to avoid negative variance forecasts
        fcast = max(fcast, 1e-10)

        forecasts.append(fcast)
        forecast_dates.append(rv_series.index[t])

    return pd.Series(forecasts, index=forecast_dates)


def har_x_rolling_forecast(rv_series, vix_series, window=500, oos_start_idx=None):
    """
    HAR-X: HAR + VIX as exogenous regressor.
    RV_t = β0 + β1*RV_{t-1} + β5*RV5 + β22*RV22 + β_vix*VIX²_{t-1} + ε

    VIX² converted to daily variance scale: (VIX/100)² / 252
    """
    rv = rv_series.values
    # Align VIX to rv dates
    vix_aligned = vix_series.reindex(rv_series.index).ffill().values
    # Convert VIX to daily variance: (VIX/100)² / 252
    vix_var = (vix_aligned / 100.0) ** 2 / 252.0
    n = len(rv)
    forecasts = []
    forecast_dates = []

    for t in range(oos_start_idx, n):
        start = max(0, t - window)
        if t - start < 50:
            continue

        y_train = []
        X_train = []
        for i in range(start + 22, t):
            y_train.append(rv[i])
            rv_1 = rv[i - 1]
            rv_5 = np.mean(rv[i - 5:i])
            rv_22 = np.mean(rv[i - 22:i])
            vix_v = vix_var[i - 1]
            if np.isnan(vix_v):
                continue
            X_train.append([1.0, rv_1, rv_5, rv_22, vix_v])

        if len(y_train) < 30:
            continue

        y_train = np.array(y_train)
        X_train = np.array(X_train)

        try:
            beta = np.linalg.solve(X_train.T @ X_train, X_train.T @ y_train)
        except np.linalg.LinAlgError:
            continue

        rv_1 = rv[t - 1]
        rv_5 = np.mean(rv[t - 5:t])
        rv_22 = np.mean(rv[t - 22:t])
        vix_v = vix_var[t - 1]
        if np.isnan(vix_v):
            vix_v = np.nanmean(vix_var[max(0, t - 22):t])
        x_new = np.array([1.0, rv_1, rv_5, rv_22, vix_v])
        fcast = max(x_new @ beta, 1e-10)

        forecasts.append(fcast)
        forecast_dates.append(rv_series.index[t])

    return pd.Series(forecasts, index=forecast_dates)


def ahar_rolling_forecast(rv_series, ret_series, window=500, oos_start_idx=None):
    """
    Asymmetric HAR (AHAR): separate positive/negative RV components.
    RV_t = β0 + β1*RV+_{t-1} + β2*RV-_{t-1} + β5*RV5 + β22*RV22 + ε
    where RV+ = RV * I(r>0), RV- = RV * I(r<0)
    """
    rv = rv_series.values
    ret = ret_series.reindex(rv_series.index).values
    n = len(rv)
    forecasts = []
    forecast_dates = []

    for t in range(oos_start_idx, n):
        start = max(0, t - window)
        if t - start < 50:
            continue

        y_train = []
        X_train = []
        for i in range(start + 22, t):
            y_train.append(rv[i])
            rv_pos = rv[i - 1] * (1.0 if ret[i - 1] > 0 else 0.0)
            rv_neg = rv[i - 1] * (1.0 if ret[i - 1] <= 0 else 0.0)
            rv_5 = np.mean(rv[i - 5:i])
            rv_22 = np.mean(rv[i - 22:i])
            X_train.append([1.0, rv_pos, rv_neg, rv_5, rv_22])

        if len(y_train) < 30:
            continue

        y_train = np.array(y_train)
        X_train = np.array(X_train)

        try:
            beta = np.linalg.solve(X_train.T @ X_train, X_train.T @ y_train)
        except np.linalg.LinAlgError:
            continue

        rv_pos = rv[t - 1] * (1.0 if ret[t - 1] > 0 else 0.0)
        rv_neg = rv[t - 1] * (1.0 if ret[t - 1] <= 0 else 0.0)
        rv_5 = np.mean(rv[t - 5:t])
        rv_22 = np.mean(rv[t - 22:t])
        x_new = np.array([1.0, rv_pos, rv_neg, rv_5, rv_22])
        fcast = max(x_new @ beta, 1e-10)

        forecasts.append(fcast)
        forecast_dates.append(rv_series.index[t])

    return pd.Series(forecasts, index=forecast_dates)


# ============================================================
# 3. GJR-GARCH ROLLING FORECAST
# ============================================================

def gjr_garch_rolling_forecast(returns_pct, window=2000, oos_start_idx=None):
    """
    GJR-GARCH(1,1,1) rolling window, one-step-ahead variance forecast.
    Returns forecasts in log-return² scale (not percentage²).
    """
    ret = returns_pct.values
    n = len(ret)
    forecasts = []
    forecast_dates = []

    for t in range(oos_start_idx, n):
        start = max(0, t - window)
        if t - start < 100:
            continue

        y_train = ret[start:t]

        try:
            am = arch_model(y_train, vol='Garch', p=1, o=1, q=1,
                            mean='Zero', dist='normal')
            res = am.fit(disp='off', show_warning=False)
            # One-step-ahead forecast
            fcast = res.forecast(horizon=1)
            var_pct = fcast.variance.values[-1, 0]
            # Convert from %² to decimal²: divide by 10000
            var_dec = var_pct / 10000.0
        except Exception:
            continue

        if var_dec <= 0 or np.isnan(var_dec):
            continue

        forecasts.append(var_dec)
        forecast_dates.append(returns_pct.index[t])

    return pd.Series(forecasts, index=forecast_dates)


# ============================================================
# 4. EVALUATION METRICS
# ============================================================

def qlike_loss(actual, forecast):
    """QLIKE loss: log(forecast) + actual/forecast"""
    mask = (forecast > 0) & (actual > 0) & np.isfinite(actual) & np.isfinite(forecast)
    a = actual[mask]
    f = forecast[mask]
    return np.log(f) + a / f


def mse_loss(actual, forecast):
    """MSE loss: (actual - forecast)²"""
    mask = np.isfinite(actual) & np.isfinite(forecast)
    return (actual[mask] - forecast[mask]) ** 2


def dm_test_hac(loss1, loss2, max_lag=None):
    """
    Diebold-Mariano test with Newey-West HAC standard errors.
    H0: E[d_t] = 0 (equal predictive ability)
    H1: E[d_t] < 0 (model 1 better, lower loss)

    Returns: t-stat, p-value (one-sided: model 1 better)
    """
    d = loss1 - loss2
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 30:
        return np.nan, np.nan

    d_mean = np.mean(d)

    if max_lag is None:
        max_lag = int(np.floor(n ** (1.0 / 3.0)))

    # Newey-West HAC variance
    gamma_0 = np.mean((d - d_mean) ** 2)
    nw_var = gamma_0

    for k in range(1, max_lag + 1):
        w_k = 1.0 - k / (max_lag + 1.0)
        gamma_k = np.mean((d[k:] - d_mean) * (d[:-k] - d_mean))
        nw_var += 2.0 * w_k * gamma_k

    if nw_var <= 0:
        return np.nan, np.nan

    se = np.sqrt(nw_var / n)
    t_stat = d_mean / se
    p_value = stats.t.cdf(t_stat, df=n - 1)  # one-sided: model 1 better

    return t_stat, p_value


# ============================================================
# 5. LOAD VIX DATA (for HAR-X)
# ============================================================

print("\n--- Loading VIX data ---")
vix_df = yf.download('^VIX', start=DATA_START, end=OOS_END, auto_adjust=True, progress=False)
if isinstance(vix_df.columns, pd.MultiIndex):
    vix_df.columns = vix_df.columns.get_level_values(0)
vix_df.columns = [c.lower() for c in vix_df.columns]
vix_series = vix_df['close']
print(f"VIX data: {vix_series.index[0].date()} to {vix_series.index[-1].date()}, N={len(vix_series)}")


# ============================================================
# 6. MAIN EXPERIMENT LOOP
# ============================================================

all_results = {}

for ticker in ASSETS:
    print(f"\n{'=' * 60}")
    print(f"Processing {ticker}")
    print(f"{'=' * 60}")

    # Download data
    df = yf.download(ticker, start=DATA_START, end=OOS_END, auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [c.lower() for c in df.columns]
    print(f"  Data: {df.index[0].date()} to {df.index[-1].date()}, N={len(df)}")

    # Compute log returns
    log_ret = np.log(df['close'] / df['close'].shift(1)).dropna()

    # Compute RV proxies
    proxies = compute_rv_proxies(df)

    # Align all proxies to start from same date (after first close-to-close)
    common_start = max(p.index[0] for p in proxies.values())
    for k in proxies:
        proxies[k] = proxies[k][proxies[k].index >= common_start]

    # Determine OOS start index
    oos_dt = pd.Timestamp(OOS_START)

    # Use c2c proxy for main evaluation (same target as GARCH)
    c2c_rv = proxies['c2c']
    oos_mask = c2c_rv.index >= oos_dt
    oos_start_idx = int(np.argmax(oos_mask))
    n_oos = int(oos_mask.sum())
    print(f"  OOS period: {c2c_rv.index[oos_start_idx].date()} to {c2c_rv.index[-1].date()}, N_OOS={n_oos}")

    # ----------------------------------------------------------
    # A. GJR-GARCH benchmark
    # ----------------------------------------------------------
    print(f"  Running GJR-GARCH(1,1,1) w={GARCH_WINDOW}...")
    ret_pct = log_ret * 100.0
    # Align ret_pct to c2c index (c2c starts 1 day later due to diff)
    ret_pct_aligned = ret_pct.reindex(c2c_rv.index)
    garch_fcast = gjr_garch_rolling_forecast(ret_pct_aligned, window=GARCH_WINDOW,
                                              oos_start_idx=oos_start_idx)
    print(f"    GARCH forecasts: {len(garch_fcast)}")

    # ----------------------------------------------------------
    # B. HAR models on each proxy
    # ----------------------------------------------------------
    har_results = {}

    for proxy_name, rv in proxies.items():
        print(f"  Running HAR on {proxy_name} proxy...")

        # HAR basic
        oos_idx = int(np.argmax(rv.index >= oos_dt))
        har_fcast = har_rolling_forecast(rv, window=HAR_WINDOW, oos_start_idx=oos_idx)
        print(f"    HAR({proxy_name}): {len(har_fcast)} forecasts")

        # HAR-X (with VIX)
        har_x_fcast = har_x_rolling_forecast(rv, vix_series, window=HAR_WINDOW,
                                              oos_start_idx=oos_idx)
        print(f"    HAR-X({proxy_name}): {len(har_x_fcast)} forecasts")

        # AHAR (asymmetric)
        ahar_fcast = ahar_rolling_forecast(rv, log_ret, window=HAR_WINDOW,
                                            oos_start_idx=oos_idx)
        print(f"    AHAR({proxy_name}): {len(ahar_fcast)} forecasts")

        har_results[proxy_name] = {
            'har': har_fcast,
            'har_x': har_x_fcast,
            'ahar': ahar_fcast,
        }

    # ----------------------------------------------------------
    # C. Evaluate all models against c2c r² (standard target)
    # ----------------------------------------------------------
    print(f"\n  --- Evaluation (target: c2c r²) ---")

    # The target is actual c2c squared returns in OOS
    target = c2c_rv[c2c_rv.index >= oos_dt]

    asset_results = {'n_oos': int(n_oos)}
    comparisons = []

    # GARCH losses
    common_idx = target.index.intersection(garch_fcast.index)
    if len(common_idx) > 30:
        garch_qlike = qlike_loss(target[common_idx].values, garch_fcast[common_idx].values)
        garch_mse = mse_loss(target[common_idx].values, garch_fcast[common_idx].values)
        asset_results['garch'] = {
            'mean_qlike': float(np.mean(garch_qlike)),
            'mean_mse': float(np.mean(garch_mse)),
            'n_forecasts': len(common_idx),
        }
        print(f"    GJR-GARCH: QLIKE={np.mean(garch_qlike):.6f}, MSE={np.mean(garch_mse):.2e}")
    else:
        print(f"    GJR-GARCH: insufficient forecasts ({len(common_idx)})")
        garch_qlike = None
        garch_mse = None

    # HAR model losses
    for proxy_name, models in har_results.items():
        for model_name, fcast in models.items():
            label = f"{model_name}({proxy_name})"

            # For HAR on non-c2c proxies, the forecast is in proxy units.
            # We still evaluate against c2c r² for apples-to-apples comparison.
            # This tests whether different RV inputs improve c2c prediction.
            common_idx_har = target.index.intersection(fcast.index)
            if len(common_idx_har) < 30:
                print(f"    {label}: insufficient forecasts ({len(common_idx_har)})")
                continue

            har_qlike = qlike_loss(target[common_idx_har].values, fcast[common_idx_har].values)
            har_mse = mse_loss(target[common_idx_har].values, fcast[common_idx_har].values)

            result_entry = {
                'mean_qlike': float(np.mean(har_qlike)),
                'mean_mse': float(np.mean(har_mse)),
                'n_forecasts': len(common_idx_har),
            }

            # DM test vs GARCH (if available)
            if garch_qlike is not None:
                # Align to common dates
                all_common = target.index.intersection(fcast.index).intersection(garch_fcast.index)
                if len(all_common) > 30:
                    g_q = qlike_loss(target[all_common].values, garch_fcast[all_common].values)
                    h_q = qlike_loss(target[all_common].values, fcast[all_common].values)
                    g_m = mse_loss(target[all_common].values, garch_fcast[all_common].values)
                    h_m = mse_loss(target[all_common].values, fcast[all_common].values)

                    # DM: negative t → HAR better
                    dm_q_t, dm_q_p = dm_test_hac(h_q, g_q)
                    dm_m_t, dm_m_p = dm_test_hac(h_m, g_m)

                    result_entry['dm_qlike_t'] = float(dm_q_t) if not np.isnan(dm_q_t) else None
                    result_entry['dm_qlike_p'] = float(dm_q_p) if not np.isnan(dm_q_p) else None
                    result_entry['dm_mse_t'] = float(dm_m_t) if not np.isnan(dm_m_t) else None
                    result_entry['dm_mse_p'] = float(dm_m_p) if not np.isnan(dm_m_p) else None

                    # Determine winner
                    har_wins_qlike = dm_q_p < 0.05  # HAR significantly better
                    garch_wins_qlike = (1 - dm_q_p) < 0.05  # GARCH significantly better
                    qlike_winner = 'HAR' if har_wins_qlike else ('GARCH' if garch_wins_qlike else 'TIE')
                    result_entry['qlike_winner'] = qlike_winner

                    comparisons.append({
                        'model': label,
                        'qlike_diff_pct': float((np.mean(h_q) - np.mean(g_q)) / np.mean(g_q) * 100),
                        'dm_qlike_t': result_entry['dm_qlike_t'],
                        'dm_qlike_p': result_entry['dm_qlike_p'],
                        'winner': qlike_winner,
                    })

                    sig_marker = '*' if dm_q_p < 0.05 or (1 - dm_q_p) < 0.05 else ''
                    print(f"    {label}: QLIKE={np.mean(har_qlike):.6f}, "
                          f"DM_QLIKE t={dm_q_t:.3f} p={dm_q_p:.4f} {sig_marker}")

            asset_results[label] = result_entry

    asset_results['comparisons'] = comparisons

    # ----------------------------------------------------------
    # D. Same-proxy evaluation (HAR predicts its own proxy)
    # ----------------------------------------------------------
    print(f"\n  --- Same-proxy evaluation (HAR predicts its own proxy) ---")
    same_proxy_results = {}

    for proxy_name, models in har_results.items():
        rv = proxies[proxy_name]
        rv_oos = rv[rv.index >= oos_dt]

        for model_name, fcast in models.items():
            if model_name != 'har':
                continue  # Only basic HAR for same-proxy test

            label = f"har_same({proxy_name})"
            common_idx_sp = rv_oos.index.intersection(fcast.index)
            if len(common_idx_sp) < 30:
                continue

            sp_qlike = qlike_loss(rv_oos[common_idx_sp].values, fcast[common_idx_sp].values)
            sp_mse = mse_loss(rv_oos[common_idx_sp].values, fcast[common_idx_sp].values)

            same_proxy_results[label] = {
                'mean_qlike': float(np.mean(sp_qlike)),
                'mean_mse': float(np.mean(sp_mse)),
                'n': len(common_idx_sp),
            }
            print(f"    {label}: QLIKE={np.mean(sp_qlike):.6f}, MSE={np.mean(sp_mse):.2e}")

    asset_results['same_proxy'] = same_proxy_results

    all_results[ticker] = asset_results


# ============================================================
# 7. CROSS-ASSET SUMMARY
# ============================================================

print("\n" + "=" * 70)
print("CROSS-ASSET SUMMARY")
print("=" * 70)

# Build comparison matrix: how many assets does each HAR variant beat GARCH?
model_wins = {}  # model_name -> {garch_wins, har_wins, ties}

for ticker, res in all_results.items():
    if 'comparisons' not in res:
        continue
    for comp in res['comparisons']:
        m = comp['model']
        if m not in model_wins:
            model_wins[m] = {'garch_wins': 0, 'har_wins': 0, 'ties': 0, 'details': []}
        if comp['winner'] == 'GARCH':
            model_wins[m]['garch_wins'] += 1
        elif comp['winner'] == 'HAR':
            model_wins[m]['har_wins'] += 1
        else:
            model_wins[m]['ties'] += 1
        model_wins[m]['details'].append({
            'asset': ticker,
            'qlike_diff_pct': comp['qlike_diff_pct'],
            'dm_t': comp['dm_qlike_t'],
            'dm_p': comp['dm_qlike_p'],
        })

print(f"\n{'Model':<30} {'GARCH wins':>10} {'HAR wins':>10} {'Ties':>6}")
print("-" * 60)
for m, w in sorted(model_wins.items()):
    print(f"{m:<30} {w['garch_wins']:>10} {w['har_wins']:>10} {w['ties']:>6}")

# Overall tally
total_garch = sum(w['garch_wins'] for w in model_wins.values())
total_har = sum(w['har_wins'] for w in model_wins.values())
total_tie = sum(w['ties'] for w in model_wins.values())
total = total_garch + total_har + total_tie

print(f"\n{'TOTAL':<30} {total_garch:>10} {total_har:>10} {total_tie:>6}")
print(f"\nOverall: GARCH wins {total_garch}/{total} ({100*total_garch/max(total,1):.0f}%), "
      f"HAR wins {total_har}/{total} ({100*total_har/max(total,1):.0f}%), "
      f"Ties {total_tie}/{total} ({100*total_tie/max(total,1):.0f}%)")

# Detailed per-asset per-model table
print(f"\n{'Asset':<10} {'Model':<30} {'QLIKE diff%':>12} {'DM t':>8} {'DM p':>8} {'Winner':>8}")
print("-" * 78)
for m, w in sorted(model_wins.items()):
    for d in w['details']:
        sig = '*' if d['dm_p'] is not None and (d['dm_p'] < 0.05 or (1 - d['dm_p']) < 0.05) else ''
        dm_t_str = f"{d['dm_t']:.3f}" if d['dm_t'] is not None else 'N/A'
        dm_p_str = f"{d['dm_p']:.4f}" if d['dm_p'] is not None else 'N/A'
        winner = 'HAR' if d['dm_p'] is not None and d['dm_p'] < 0.05 else (
            'GARCH' if d['dm_p'] is not None and (1 - d['dm_p']) < 0.05 else 'TIE')
        print(f"{d['asset']:<10} {m:<30} {d['qlike_diff_pct']:>11.2f}% {dm_t_str:>8} {dm_p_str:>8} {winner:>7}{sig}")


# ============================================================
# 8. KEY CONCLUSION
# ============================================================

print("\n" + "=" * 70)
print("KEY FINDINGS")
print("=" * 70)

if total > 0:
    if total_tie / total >= 0.5:
        conclusion = ("HAR ≈ GARCH on daily data: majority of comparisons show no significant "
                       "difference. The predictive ceiling is in the DATA (daily squared returns "
                       "are too noisy), not in the MODEL class.")
        ceiling_confirmed = True
    elif total_har > total_garch:
        conclusion = ("HAR beats GARCH in majority of comparisons. "
                       "Daily OHLC proxies may add signal not captured by close-to-close GARCH.")
        ceiling_confirmed = False
    else:
        conclusion = ("GARCH beats HAR in majority of comparisons. "
                       "HAR on daily data underperforms — needs intraday RV for its advantage.")
        ceiling_confirmed = True  # still ceiling, HAR can't break it either
else:
    conclusion = "Insufficient data for comparison."
    ceiling_confirmed = None

print(f"\n{conclusion}")
print(f"\nCeiling hypothesis {'CONFIRMED' if ceiling_confirmed else 'REJECTED' if ceiling_confirmed is False else 'INCONCLUSIVE'}")


# ============================================================
# 9. SAVE RESULTS
# ============================================================

summary = {
    'experiment': 'K188',
    'title': 'HAR Ceiling Test — Does HAR-RV Beat GARCH on Daily Data?',
    'attribution': '[提出: 用戶, 執行: Claude]',
    'timestamp': datetime.now().isoformat(),
    'config': {
        'assets': ASSETS,
        'har_window': HAR_WINDOW,
        'garch_window': GARCH_WINDOW,
        'oos_start': OOS_START,
        'oos_end': OOS_END,
        'rv_proxies': ['c2c', 'parkinson', 'garman_klass', 'rogers_satchell'],
        'models': ['HAR', 'HAR-X (with VIX)', 'AHAR (asymmetric)', 'GJR-GARCH(1,1,1)'],
    },
    'cross_asset_summary': {
        'total_comparisons': total,
        'garch_wins': total_garch,
        'har_wins': total_har,
        'ties': total_tie,
        'ceiling_confirmed': ceiling_confirmed,
    },
    'model_wins': {k: {kk: vv for kk, vv in v.items() if kk != 'details'}
                   for k, v in model_wins.items()},
    'per_asset': {},
    'conclusion': conclusion,
}

# Add per-asset summary (without large arrays)
for ticker, res in all_results.items():
    asset_summary = {}
    if 'garch' in res:
        asset_summary['garch_qlike'] = res['garch']['mean_qlike']
        asset_summary['garch_mse'] = res['garch']['mean_mse']
    if 'comparisons' in res:
        asset_summary['comparisons'] = res['comparisons']
    if 'same_proxy' in res:
        asset_summary['same_proxy'] = res['same_proxy']
    asset_summary['n_oos'] = res['n_oos']
    summary['per_asset'][ticker] = asset_summary

with open(RESULTS_FILE, 'w') as f:
    json.dump(summary, f, indent=2, default=str)

print(f"\nResults saved to {RESULTS_FILE}")
print(f"\nDone. K188 complete.")
