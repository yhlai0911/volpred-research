#!/usr/bin/env python3
"""
K911: Quantile Connectedness & Tail Contagion (QDVC)
=====================================================
[提出: Gemini G3-2, 執行: Claude]

Motivation:
  K907 found mean TCI ~50%, orthogonal to VIX (r=0.001).
  K910 confirmed mean TCI has no directional predictive power.
  But risk management cares about TAILS, not means.
  This experiment tests whether Tail TCI (tau=0.05/0.95) behaves
  differently from Mean TCI and whether it predicts tail risk events.

  Hypothesis: mean TCI is null because we looked at the wrong dimension.
  Tail connectedness (left-tail tau=0.05 TCI) may spike during extreme
  events, independently of VIX.

Data:
  - yfinance daily OHLC for 4 assets + VIX (2006-01-01 to 2026-04-01)
  - Assets: SPY, QQQ, GLD, 0050.TW (reduced from 9 for efficiency)
  - Vol proxy: Garman-Klass realized volatility (OHLC-based)

Method:
  - Quantile VAR(2) at tau = {0.05, 0.50, 0.95}
  - Generalized FEVD at each quantile
  - Rolling 250-day windows, step=5 (every 5 trading days)
  - Compare Tail TCI vs Mean TCI vs Upper TCI
  - Correlate with VIX
  - Tail risk prediction via logistic regression

Error Log rules:
  - 0050.TW: must use clean_tw50_data (volpred.utils)
  - np.random.seed(42) for reproducibility
  - Cross-market holidays: ffill prices
  - DM test: use volpred.stats.model_evaluation if needed

References:
  - Ando, Greenwood-Nimmo, Shin (2022): Quantile Connectedness
  - Diebold & Yilmaz (2012, 2014): Standard Connectedness
  - Koenker & Bassett (1978): Quantile Regression
  - K907: Volatility Spillover Network (mean TCI)
  - K910: TCI not a trading signal (mean level)

Author: VolPred Research System
Date: 2026-04-06
"""

import os
import sys
import json
import time
import warnings
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from concurrent.futures import ProcessPoolExecutor, as_completed

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from scipy import stats as sp_stats

warnings.filterwarnings('ignore')
np.random.seed(42)


class NumpyEncoder(json.JSONEncoder):
    """JSON encoder that handles numpy types."""
    def default(self, obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, np.bool_):
            return bool(obj)
        return super().default(obj)


# ============================================================
# Configuration
# ============================================================
ASSETS = ['SPY', 'QQQ', 'GLD', '0050.TW']
ASSET_LABELS = ['SPY', 'QQQ', 'GLD', 'TW50']
VIX_TICKER = '^VIX'
START_DATE = '2006-01-01'
END_DATE = '2026-04-01'
ROLLING_WINDOW = 250  # trading days
ROLLING_STEP = 5      # estimate every 5 days for efficiency
FORECAST_HORIZON = 10  # H in GFEVD
VAR_LAG = 2           # fixed at 2 for efficiency (quantile reg is slow)
QUANTILES = [0.05, 0.50, 0.95]
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))


# ============================================================
# Data Download & Preparation
# ============================================================

def download_data():
    """Download OHLC data for all assets + VIX."""
    import yfinance as yf

    all_tickers = ASSETS + [VIX_TICKER]
    print(f"Downloading data for {len(all_tickers)} tickers: {START_DATE} to {END_DATE}")

    data = {}
    for ticker in all_tickers:
        try:
            df = yf.download(ticker, start=START_DATE, end=END_DATE, progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            if len(df) > 0:
                data[ticker] = df
                print(f"  {ticker}: {len(df)} days "
                      f"({df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')})")
            else:
                print(f"  {ticker}: NO DATA")
        except Exception as e:
            print(f"  {ticker}: ERROR - {e}")

    return data


def compute_garman_klass_vol(ohlc_df):
    """Compute Garman-Klass volatility proxy from OHLC data.

    GK = 0.5 * (log(H/L))^2 - (2*ln(2) - 1) * (log(C/O))^2
    """
    h = ohlc_df['High'].values
    l = ohlc_df['Low'].values
    c = ohlc_df['Close'].values
    o = ohlc_df['Open'].values

    mask = (h > 0) & (l > 0) & (c > 0) & (o > 0) & (h >= l)
    gk = np.full(len(ohlc_df), np.nan)

    idx = mask
    log_hl = np.log(h[idx] / l[idx])
    log_co = np.log(c[idx] / o[idx])

    gk[idx] = 0.5 * log_hl**2 - (2 * np.log(2) - 1) * log_co**2
    gk = np.maximum(gk, 1e-10)

    return pd.Series(gk, index=ohlc_df.index, name='GK_vol')


def prepare_vol_panel(raw_data):
    """Create aligned panel of vol proxies for all assets."""
    from volpred.utils import clean_tw50_data

    vol_series = {}

    for ticker, label in zip(ASSETS, ASSET_LABELS):
        if ticker not in raw_data:
            print(f"  WARNING: {ticker} not in data, skipping")
            continue

        df = raw_data[ticker].copy()

        if ticker == '0050.TW':
            close = df['Close']
            prices, _ = clean_tw50_data(close)
            df['Close'] = prices

        gk = compute_garman_klass_vol(df)
        vol_series[label] = gk

    vol_panel = pd.DataFrame(vol_series)
    vol_panel = vol_panel.ffill()
    vol_panel = vol_panel.dropna()

    print(f"\nAligned vol panel: {len(vol_panel)} days, {vol_panel.shape[1]} assets")
    print(f"  Period: {vol_panel.index[0].strftime('%Y-%m-%d')} to "
          f"{vol_panel.index[-1].strftime('%Y-%m-%d')}")

    return vol_panel


def prepare_return_panel(raw_data):
    """Create aligned panel of log returns for tail event detection."""
    from volpred.utils import clean_tw50_data

    ret_series = {}

    for ticker, label in zip(ASSETS, ASSET_LABELS):
        if ticker not in raw_data:
            continue

        df = raw_data[ticker].copy()

        if ticker == '0050.TW':
            close = df['Close']
            prices, _ = clean_tw50_data(close)
            df['Close'] = prices

        log_ret = np.log(df['Close'] / df['Close'].shift(1))
        ret_series[label] = log_ret

    ret_panel = pd.DataFrame(ret_series)
    ret_panel = ret_panel.ffill()
    ret_panel = ret_panel.dropna()

    return ret_panel


# ============================================================
# Quantile VAR Estimation
# ============================================================

def estimate_quantile_var(data_matrix, lag_order, tau):
    """Estimate Quantile VAR(p) at quantile tau.

    For each variable y_i, run quantile regression:
      y_i,t = c_i(tau) + sum_j sum_l A_{ij,l}(tau) * y_{j,t-l} + eps

    Args:
        data_matrix: (T, K) numpy array
        lag_order: int, number of lags
        tau: float, quantile level (0 < tau < 1)

    Returns:
        coefficients: list of K arrays, each (1 + K*lag_order,) coefficients
        residuals: (T-lag_order, K) array of residuals
    """
    from statsmodels.regression.quantile_regression import QuantReg

    T, K = data_matrix.shape

    # Build lagged matrices
    Y = data_matrix[lag_order:]  # (T-p, K)
    n = Y.shape[0]

    # X = [1, y_{t-1}, y_{t-2}, ..., y_{t-p}]
    X_parts = [np.ones((n, 1))]
    for lag in range(1, lag_order + 1):
        X_parts.append(data_matrix[lag_order - lag: T - lag])
    X = np.hstack(X_parts)  # (T-p, 1 + K*p)

    coefficients = []
    residuals = np.zeros((n, K))

    for i in range(K):
        y_i = Y[:, i]
        try:
            model = QuantReg(y_i, X)
            result = model.fit(q=tau, max_iter=1000)
            coefficients.append(result.params)
            residuals[:, i] = y_i - X @ result.params
        except Exception:
            # Fallback: OLS if quantile regression fails
            from numpy.linalg import lstsq
            params, _, _, _ = lstsq(X, y_i, rcond=None)
            coefficients.append(params)
            residuals[:, i] = y_i - X @ params

    return coefficients, residuals


def quantile_var_to_companion(coefficients, K, lag_order):
    """Convert Quantile VAR coefficients to companion form.

    Returns:
        A_list: list of (K, K) coefficient matrices A_1, A_2, ..., A_p
    """
    A_list = []
    for lag in range(lag_order):
        A_l = np.zeros((K, K))
        for i in range(K):
            # coefficients[i] = [const, A_{i,1,1}, ..., A_{i,K,1}, A_{i,1,2}, ..., A_{i,K,p}]
            start = 1 + lag * K
            end = 1 + (lag + 1) * K
            A_l[i, :] = coefficients[i][start:end]
        A_list.append(A_l)
    return A_list


def compute_ma_coefficients(A_list, H):
    """Compute MA(infinity) coefficients Phi_0, Phi_1, ..., Phi_{H-1}
    from VAR coefficient matrices.

    Phi_0 = I
    Phi_s = sum_{j=1}^{min(s,p)} A_j * Phi_{s-j}
    """
    K = A_list[0].shape[0]
    p = len(A_list)

    Phi = np.zeros((H, K, K))
    Phi[0] = np.eye(K)

    for s in range(1, H):
        for j in range(1, min(s, p) + 1):
            Phi[s] += A_list[j - 1] @ Phi[s - j]

    return Phi


def compute_gfevd_from_quantile_var(coefficients, residuals, K, lag_order, H):
    """Compute Generalized FEVD from Quantile VAR results.

    Uses the residual covariance as Sigma (approximation for quantile case).

    Returns:
        theta: (K, K) normalized GFEVD matrix
    """
    A_list = quantile_var_to_companion(coefficients, K, lag_order)
    Phi = compute_ma_coefficients(A_list, H)

    # Residual covariance
    Sigma = np.cov(residuals, rowvar=False)
    sigma_diag = np.diag(Sigma)

    # Avoid division by zero
    sigma_diag = np.maximum(sigma_diag, 1e-12)

    theta = np.zeros((K, K))

    for i in range(K):
        denom = 0.0
        for h in range(H):
            denom += Phi[h, i, :] @ Sigma @ Phi[h, i, :]

        if denom < 1e-12:
            theta[i, :] = 1.0 / K
            continue

        for j in range(K):
            numer = 0.0
            for h in range(H):
                val = Phi[h, i, :] @ Sigma[:, j]
                numer += val ** 2
            numer /= sigma_diag[j]
            theta[i, j] = numer / denom

    # Normalize rows to sum to 1
    row_sums = theta.sum(axis=1, keepdims=True)
    row_sums[row_sums < 1e-12] = 1.0
    theta = theta / row_sums

    return theta


def compute_connectedness_measures(theta):
    """Compute Diebold-Yilmaz connectedness measures from GFEVD matrix."""
    K = theta.shape[0]

    off_diag_sum = theta.sum() - np.trace(theta)
    TCI = off_diag_sum / K * 100

    FROM = np.zeros(K)
    for i in range(K):
        FROM[i] = (theta[i, :].sum() - theta[i, i]) * 100

    TO = np.zeros(K)
    for j in range(K):
        TO[j] = (theta[:, j].sum() - theta[j, j]) * 100

    NET = TO - FROM

    return {
        'TCI': TCI,
        'FROM': FROM,
        'TO': TO,
        'NET': NET,
        'theta': theta
    }


# ============================================================
# Rolling Quantile Connectedness
# ============================================================

def _estimate_single_window_quantile(args):
    """Worker for parallel rolling quantile estimation."""
    window_data, lag_order, H, tau, date_str, K = args
    try:
        coefficients, residuals = estimate_quantile_var(window_data, lag_order, tau)
        theta = compute_gfevd_from_quantile_var(coefficients, residuals, K, lag_order, H)
        measures = compute_connectedness_measures(theta)
        return date_str, tau, measures['TCI'], measures['FROM'], measures['TO'], measures['NET']
    except Exception as e:
        return date_str, tau, np.nan, np.full(K, np.nan), np.full(K, np.nan), np.full(K, np.nan)


def rolling_quantile_connectedness(vol_panel, window=250, step=5, H=10,
                                    lag_order=2, quantiles=None, n_jobs=4):
    """Compute time-varying quantile connectedness via rolling windows.

    Args:
        vol_panel: DataFrame of volatility proxies
        window: rolling window size
        step: step between windows (5 = every 5 days)
        H: forecast horizon for GFEVD
        lag_order: VAR lag order
        quantiles: list of quantile levels
        n_jobs: number of parallel workers

    Returns:
        dict of {tau: DataFrame with columns [date, TCI, FROM_*, TO_*, NET_*]}
    """
    if quantiles is None:
        quantiles = QUANTILES

    T, K = vol_panel.shape
    dates = vol_panel.index
    data_values = vol_panel.values

    n_windows = (T - window) // step + 1
    if n_windows < 5:
        print(f"ERROR: Only {n_windows} windows, need at least 5")
        return None

    print(f"\nRolling quantile connectedness:")
    print(f"  Windows: {n_windows}, Window size: {window}, Step: {step}")
    print(f"  Quantiles: {quantiles}")
    print(f"  VAR lag: {lag_order}, Forecast horizon: {H}")

    # Prepare tasks for all quantiles
    tasks = []
    for w_idx in range(n_windows):
        start = w_idx * step
        end = start + window
        window_data = data_values[start:end]
        date_str = dates[end - 1].strftime('%Y-%m-%d')

        for tau in quantiles:
            tasks.append((window_data, lag_order, H, tau, date_str, K))

    print(f"  Total tasks: {len(tasks)} ({n_windows} windows x {len(quantiles)} quantiles)")

    # Execute with multiprocessing
    results_raw = []
    start_time = time.time()

    with ProcessPoolExecutor(max_workers=n_jobs) as executor:
        futures = {executor.submit(_estimate_single_window_quantile, task): task
                   for task in tasks}

        done_count = 0
        for future in as_completed(futures):
            done_count += 1
            try:
                result = future.result(timeout=120)
                results_raw.append(result)
            except Exception as e:
                task = futures[future]
                results_raw.append((task[4], task[3], np.nan,
                                   np.full(K, np.nan), np.full(K, np.nan), np.full(K, np.nan)))

            if done_count % 50 == 0:
                elapsed = time.time() - start_time
                rate = done_count / elapsed
                remaining = (len(tasks) - done_count) / rate if rate > 0 else 0
                print(f"  Progress: {done_count}/{len(tasks)} "
                      f"({elapsed:.0f}s elapsed, ~{remaining:.0f}s remaining)")

    elapsed = time.time() - start_time
    print(f"  Completed in {elapsed:.1f}s")

    # Organize results by quantile
    results_by_tau = {tau: {'dates': [], 'TCI': [], 'FROM': [], 'TO': [], 'NET': []}
                      for tau in quantiles}

    for res in results_raw:
        date_str, tau, tci, from_arr, to_arr, net_arr = res
        results_by_tau[tau]['dates'].append(date_str)
        results_by_tau[tau]['TCI'].append(tci)
        results_by_tau[tau]['FROM'].append(from_arr)
        results_by_tau[tau]['TO'].append(to_arr)
        results_by_tau[tau]['NET'].append(net_arr)

    # Sort by date and convert to DataFrames
    output = {}
    for tau in quantiles:
        data = results_by_tau[tau]
        df = pd.DataFrame({
            'date': pd.to_datetime(data['dates']),
            'TCI': data['TCI']
        })
        # Add per-asset FROM, TO, NET
        from_arr = np.array(data['FROM'])
        to_arr = np.array(data['TO'])
        net_arr = np.array(data['NET'])

        for i, label in enumerate(ASSET_LABELS):
            df[f'FROM_{label}'] = from_arr[:, i] if from_arr.ndim > 1 else np.nan
            df[f'TO_{label}'] = to_arr[:, i] if to_arr.ndim > 1 else np.nan
            df[f'NET_{label}'] = net_arr[:, i] if net_arr.ndim > 1 else np.nan

        df = df.sort_values('date').reset_index(drop=True)
        df = df.dropna(subset=['TCI'])
        output[tau] = df
        print(f"  tau={tau}: {len(df)} valid observations")

    return output


# ============================================================
# Analysis Functions
# ============================================================

def analyze_tail_vs_mean(rolling_results, vix_data):
    """Compare Tail TCI (0.05) vs Mean TCI (0.50) vs Upper TCI (0.95)."""
    print("\n" + "=" * 60)
    print("ANALYSIS: Tail TCI vs Mean TCI")
    print("=" * 60)

    results = {}

    # Get TCI series for each quantile
    tci_series = {}
    for tau in QUANTILES:
        if tau in rolling_results:
            df = rolling_results[tau]
            tci = pd.Series(df['TCI'].values, index=df['date'])
            tci_series[tau] = tci

    if len(tci_series) < 2:
        print("  Not enough quantile results for comparison")
        return results

    # 1. Cross-quantile TCI correlations
    print("\n1. Cross-quantile TCI correlations:")
    combined = pd.DataFrame(tci_series)
    combined.columns = [f'tau_{t}' for t in combined.columns]
    corr_matrix = combined.corr()
    print(corr_matrix.to_string())

    results['cross_quantile_corr'] = {}
    for i, tau_i in enumerate(QUANTILES):
        for j, tau_j in enumerate(QUANTILES):
            if i < j:
                key = f'tau_{tau_i}_vs_tau_{tau_j}'
                r = corr_matrix.iloc[i, j]
                results['cross_quantile_corr'][key] = float(r)
                print(f"  tau={tau_i} vs tau={tau_j}: r = {r:.4f}")

    # 2. TCI vs VIX correlations for each quantile
    print("\n2. TCI vs VIX correlations:")
    vix = pd.Series(vix_data['Close'].values, index=vix_data.index, name='VIX')

    results['tci_vix_corr'] = {}
    for tau in QUANTILES:
        if tau in tci_series:
            tci = tci_series[tau]
            # Align dates
            common = pd.concat([tci, vix], axis=1, join='inner').dropna()
            if len(common) > 30:
                r, p = sp_stats.pearsonr(common.iloc[:, 0], common.iloc[:, 1])
                rho, p_rho = sp_stats.spearmanr(common.iloc[:, 0], common.iloc[:, 1])
                results['tci_vix_corr'][f'tau_{tau}_pearson'] = float(r)
                results['tci_vix_corr'][f'tau_{tau}_pearson_p'] = float(p)
                results['tci_vix_corr'][f'tau_{tau}_spearman'] = float(rho)
                results['tci_vix_corr'][f'tau_{tau}_spearman_p'] = float(p_rho)
                print(f"  tau={tau}: Pearson r={r:.4f} (p={p:.4e}), Spearman rho={rho:.4f} (p={p_rho:.4e})")

    # 3. Descriptive statistics
    print("\n3. TCI descriptive statistics by quantile:")
    results['tci_descriptive'] = {}
    for tau in QUANTILES:
        if tau in tci_series:
            tci = tci_series[tau]
            desc = {
                'mean': float(tci.mean()),
                'std': float(tci.std()),
                'min': float(tci.min()),
                'max': float(tci.max()),
                'median': float(tci.median()),
                'skewness': float(sp_stats.skew(tci.dropna())),
                'kurtosis': float(sp_stats.kurtosis(tci.dropna()))
            }
            results['tci_descriptive'][f'tau_{tau}'] = desc
            print(f"  tau={tau}: mean={desc['mean']:.2f}, std={desc['std']:.2f}, "
                  f"range=[{desc['min']:.2f}, {desc['max']:.2f}]")

    # 4. Tail TCI "excess" over mean TCI
    if 0.05 in tci_series and 0.50 in tci_series:
        tail = tci_series[0.05]
        mean = tci_series[0.50]
        common = pd.concat([tail, mean], axis=1, join='inner').dropna()
        excess = common.iloc[:, 0] - common.iloc[:, 1]
        results['tail_excess'] = {
            'mean': float(excess.mean()),
            'std': float(excess.std()),
            'mean_positive': float((excess > 0).mean()),
            'corr_with_vix': None
        }
        # Correlate excess with VIX
        common2 = pd.concat([excess, vix], axis=1, join='inner').dropna()
        if len(common2) > 30:
            r, p = sp_stats.pearsonr(common2.iloc[:, 0], common2.iloc[:, 1])
            results['tail_excess']['corr_with_vix'] = float(r)
            results['tail_excess']['corr_with_vix_p'] = float(p)
            print(f"\n  Tail excess (tau=0.05 - tau=0.50) vs VIX: r={r:.4f} (p={p:.4e})")

    return results


def analyze_tail_risk_prediction(rolling_results, return_panel, vix_data):
    """Test if Tail TCI predicts tail risk events (|r| > 2sigma)."""
    print("\n" + "=" * 60)
    print("ANALYSIS: Tail TCI as Risk Predictor")
    print("=" * 60)

    results = {}

    if 0.05 not in rolling_results:
        print("  No tau=0.05 results available")
        return results

    df_tail = rolling_results[0.05]
    tail_tci = pd.Series(df_tail['TCI'].values, index=df_tail['date'])

    # SPY returns for tail event detection
    spy_ret = return_panel['SPY'] if 'SPY' in return_panel.columns else None
    if spy_ret is None:
        print("  No SPY returns available")
        return results

    # Define tail events: |return| > 2 * rolling_std (using 60-day window)
    rolling_std = spy_ret.rolling(60).std()
    tail_events = (spy_ret.abs() > 2 * rolling_std).astype(int)

    # Align TCI(t-1) with tail_event(t) -- lag=1 to avoid lookahead
    combined = pd.DataFrame({
        'tail_tci': tail_tci,
        'vix': vix_data['Close'] if isinstance(vix_data, pd.DataFrame) else vix_data,
        'tail_event': tail_events
    }).dropna()

    if len(combined) < 100:
        print(f"  Not enough aligned data: {len(combined)} rows")
        return results

    # Shift TCI by 1 day (signal from t-1)
    combined['tail_tci_lag1'] = combined['tail_tci'].shift(1)
    combined['vix_lag1'] = combined['vix'].shift(1)
    combined = combined.dropna()

    print(f"  Aligned data: {len(combined)} observations")
    print(f"  Tail events: {combined['tail_event'].sum()} ({combined['tail_event'].mean()*100:.1f}%)")

    # Logistic regression: P(tail_event) = f(tail_tci_lag1)
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score

    # Model 1: Tail TCI only
    X1 = combined[['tail_tci_lag1']].values
    y = combined['tail_event'].values

    try:
        lr1 = LogisticRegression(max_iter=1000)
        lr1.fit(X1, y)
        y_prob1 = lr1.predict_proba(X1)[:, 1]
        auc1 = roc_auc_score(y, y_prob1)
        results['logistic_tail_tci_only'] = {
            'auc': float(auc1),
            'coef': float(lr1.coef_[0][0]),
            'intercept': float(lr1.intercept_[0])
        }
        print(f"\n  Model 1 (Tail TCI only): AUC = {auc1:.4f}, coef = {lr1.coef_[0][0]:.4f}")
    except Exception as e:
        print(f"  Model 1 failed: {e}")

    # Model 2: VIX only
    X2 = combined[['vix_lag1']].values
    try:
        lr2 = LogisticRegression(max_iter=1000)
        lr2.fit(X2, y)
        y_prob2 = lr2.predict_proba(X2)[:, 1]
        auc2 = roc_auc_score(y, y_prob2)
        results['logistic_vix_only'] = {
            'auc': float(auc2),
            'coef': float(lr2.coef_[0][0]),
            'intercept': float(lr2.intercept_[0])
        }
        print(f"  Model 2 (VIX only):      AUC = {auc2:.4f}, coef = {lr2.coef_[0][0]:.4f}")
    except Exception as e:
        print(f"  Model 2 failed: {e}")

    # Model 3: Both
    X3 = combined[['tail_tci_lag1', 'vix_lag1']].values
    try:
        lr3 = LogisticRegression(max_iter=1000)
        lr3.fit(X3, y)
        y_prob3 = lr3.predict_proba(X3)[:, 1]
        auc3 = roc_auc_score(y, y_prob3)
        results['logistic_both'] = {
            'auc': float(auc3),
            'coef_tail_tci': float(lr3.coef_[0][0]),
            'coef_vix': float(lr3.coef_[0][1]),
            'intercept': float(lr3.intercept_[0])
        }
        print(f"  Model 3 (Both):          AUC = {auc3:.4f}, "
              f"coef_tci = {lr3.coef_[0][0]:.4f}, coef_vix = {lr3.coef_[0][1]:.4f}")
    except Exception as e:
        print(f"  Model 3 failed: {e}")

    # AUC improvement
    if 'logistic_vix_only' in results and 'logistic_both' in results:
        auc_improvement = results['logistic_both']['auc'] - results['logistic_vix_only']['auc']
        results['auc_improvement_tail_tci_over_vix'] = float(auc_improvement)
        print(f"\n  AUC improvement from adding Tail TCI to VIX: {auc_improvement:.4f}")

    return results


def analyze_crisis_behavior(rolling_results, vix_data):
    """Analyze Tail TCI behavior during crisis periods."""
    print("\n" + "=" * 60)
    print("ANALYSIS: Crisis Period Behavior")
    print("=" * 60)

    crisis_periods = {
        'GFC_2008': ('2008-09-01', '2009-03-31'),
        'COVID_2020': ('2020-02-15', '2020-05-31'),
        'Rate_Hike_2022': ('2022-01-01', '2022-10-31'),
        'Normal_2017': ('2017-01-01', '2017-12-31'),  # Low vol benchmark
    }

    results = {}

    for crisis_name, (start, end) in crisis_periods.items():
        start_dt = pd.Timestamp(start)
        end_dt = pd.Timestamp(end)

        crisis_data = {}
        for tau in QUANTILES:
            if tau in rolling_results:
                df = rolling_results[tau]
                mask = (df['date'] >= start_dt) & (df['date'] <= end_dt)
                subset = df[mask]
                if len(subset) > 0:
                    crisis_data[f'tau_{tau}_mean_TCI'] = float(subset['TCI'].mean())
                    crisis_data[f'tau_{tau}_max_TCI'] = float(subset['TCI'].max())
                    crisis_data[f'tau_{tau}_std_TCI'] = float(subset['TCI'].std())

        # VIX during crisis
        vix = vix_data['Close'] if isinstance(vix_data, pd.DataFrame) else vix_data
        vix_mask = (vix.index >= start_dt) & (vix.index <= end_dt)
        vix_subset = vix[vix_mask]
        if len(vix_subset) > 0:
            crisis_data['vix_mean'] = float(vix_subset.mean())
            crisis_data['vix_max'] = float(vix_subset.max())

        results[crisis_name] = crisis_data
        print(f"\n  {crisis_name} ({start} to {end}):")
        for k, v in crisis_data.items():
            print(f"    {k}: {v:.2f}")

    # Tail TCI spike ratio: crisis mean / normal mean
    if 'Normal_2017' in results and 'GFC_2008' in results:
        for tau in QUANTILES:
            key = f'tau_{tau}_mean_TCI'
            normal_val = results['Normal_2017'].get(key, 1)
            if normal_val > 0:
                for crisis in ['GFC_2008', 'COVID_2020', 'Rate_Hike_2022']:
                    if crisis in results and key in results[crisis]:
                        ratio = results[crisis][key] / normal_val
                        results[crisis][f'tau_{tau}_spike_ratio_vs_normal'] = float(ratio)

    return results


# ============================================================
# Visualization
# ============================================================

def plot_rolling_quantile_tci(rolling_results, vix_data, output_dir):
    """Plot rolling TCI for different quantiles with VIX overlay."""
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10), sharex=True,
                                     gridspec_kw={'height_ratios': [3, 1]})

    colors = {0.05: '#e74c3c', 0.50: '#2c3e50', 0.95: '#3498db'}
    labels = {0.05: 'Left Tail (τ=0.05)', 0.50: 'Median (τ=0.50)', 0.95: 'Right Tail (τ=0.95)'}

    for tau in QUANTILES:
        if tau in rolling_results:
            df = rolling_results[tau]
            ax1.plot(df['date'], df['TCI'], color=colors[tau],
                     label=labels[tau], alpha=0.8, linewidth=1.2)

    ax1.set_ylabel('Total Connectedness Index (%)', fontsize=12)
    ax1.set_title('K911: Quantile Connectedness — Tail vs Mean TCI\n'
                  '(4 assets: SPY, QQQ, GLD, 0050.TW; Rolling 250-day; Quantile VAR(2))',
                  fontsize=13, fontweight='bold')
    ax1.legend(fontsize=10, loc='upper left')
    ax1.grid(True, alpha=0.3)

    # Crisis shading
    crisis_spans = [
        ('2008-09-01', '2009-03-31', 'GFC', '#ffcccc'),
        ('2020-02-15', '2020-05-31', 'COVID', '#ffe0cc'),
        ('2022-01-01', '2022-10-31', 'Rate Hike', '#fff3cc'),
    ]
    for start, end, name, color in crisis_spans:
        ax1.axvspan(pd.Timestamp(start), pd.Timestamp(end), alpha=0.15, color=color)
        ax1.text(pd.Timestamp(start), ax1.get_ylim()[1] * 0.95, name,
                 fontsize=8, color='gray', ha='left', va='top')

    # VIX subplot
    vix = vix_data['Close'] if isinstance(vix_data, pd.DataFrame) else vix_data
    ax2.plot(vix.index, vix.values, color='purple', alpha=0.7, linewidth=0.8)
    ax2.set_ylabel('VIX', fontsize=12)
    ax2.set_xlabel('Date', fontsize=12)
    ax2.grid(True, alpha=0.3)

    for start, end, name, color in crisis_spans:
        ax2.axvspan(pd.Timestamp(start), pd.Timestamp(end), alpha=0.15, color=color)

    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
    ax2.xaxis.set_major_locator(mdates.YearLocator(2))

    plt.tight_layout()
    path = os.path.join(output_dir, 'k911_rolling_quantile_tci.png')
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {path}")
    return path


def plot_tail_vs_mean_scatter(rolling_results, output_dir):
    """Scatter plot of Tail TCI vs Mean TCI."""
    if 0.05 not in rolling_results or 0.50 not in rolling_results:
        print("  Cannot create scatter plot: missing quantile data")
        return None

    df_tail = rolling_results[0.05]
    df_mean = rolling_results[0.50]

    # Align by date
    merged = pd.merge(
        df_tail[['date', 'TCI']].rename(columns={'TCI': 'tail_tci'}),
        df_mean[['date', 'TCI']].rename(columns={'TCI': 'mean_tci'}),
        on='date'
    ).dropna()

    fig, ax = plt.subplots(1, 1, figsize=(8, 8))

    ax.scatter(merged['mean_tci'], merged['tail_tci'], alpha=0.3, s=10, c='steelblue')

    # Fit line
    slope, intercept, r_val, p_val, _ = sp_stats.linregress(merged['mean_tci'], merged['tail_tci'])
    x_range = np.linspace(merged['mean_tci'].min(), merged['mean_tci'].max(), 100)
    ax.plot(x_range, slope * x_range + intercept, 'r-', linewidth=2,
            label=f'r = {r_val:.3f} (p = {p_val:.2e})')

    # 45-degree line
    lims = [min(ax.get_xlim()[0], ax.get_ylim()[0]),
            max(ax.get_xlim()[1], ax.get_ylim()[1])]
    ax.plot(lims, lims, '--', color='gray', alpha=0.5, label='45° line')

    ax.set_xlabel('Mean TCI (τ=0.50) (%)', fontsize=12)
    ax.set_ylabel('Tail TCI (τ=0.05) (%)', fontsize=12)
    ax.set_title('K911: Left-Tail TCI vs Mean TCI\n'
                 'If points scatter above 45° → tail connectedness exceeds mean',
                 fontsize=13, fontweight='bold')
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    path = os.path.join(output_dir, 'k911_tail_vs_mean_tci.png')
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {path}")
    return path


def plot_crisis_comparison(rolling_results, output_dir):
    """Bar chart comparing quantile TCIs during crisis vs normal periods."""
    crisis_periods = {
        'Normal\n2017': ('2017-01-01', '2017-12-31'),
        'GFC\n2008': ('2008-09-01', '2009-03-31'),
        'COVID\n2020': ('2020-02-15', '2020-05-31'),
        'Rate Hike\n2022': ('2022-01-01', '2022-10-31'),
    }

    tau_labels = {0.05: 'Left Tail (τ=0.05)', 0.50: 'Median (τ=0.50)', 0.95: 'Right Tail (τ=0.95)'}
    colors = {0.05: '#e74c3c', 0.50: '#2c3e50', 0.95: '#3498db'}

    data = {}
    for period_name, (start, end) in crisis_periods.items():
        start_dt = pd.Timestamp(start)
        end_dt = pd.Timestamp(end)
        data[period_name] = {}
        for tau in QUANTILES:
            if tau in rolling_results:
                df = rolling_results[tau]
                mask = (df['date'] >= start_dt) & (df['date'] <= end_dt)
                subset = df[mask]
                data[period_name][tau] = float(subset['TCI'].mean()) if len(subset) > 0 else 0

    fig, ax = plt.subplots(figsize=(10, 6))

    x = np.arange(len(crisis_periods))
    width = 0.25
    period_names = list(crisis_periods.keys())

    for i, tau in enumerate(QUANTILES):
        values = [data[p].get(tau, 0) for p in period_names]
        ax.bar(x + i * width, values, width, label=tau_labels[tau], color=colors[tau], alpha=0.85)

    ax.set_ylabel('Mean TCI (%)', fontsize=12)
    ax.set_title('K911: Quantile TCI During Crisis vs Normal Periods\n'
                 'Does tail connectedness spike more than mean?',
                 fontsize=13, fontweight='bold')
    ax.set_xticks(x + width)
    ax.set_xticklabels(period_names, fontsize=11)
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3, axis='y')

    plt.tight_layout()
    path = os.path.join(output_dir, 'k911_crisis_comparison.png')
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {path}")
    return path


# ============================================================
# Full Sample Analysis
# ============================================================

def full_sample_quantile_analysis(vol_panel):
    """Run quantile VAR on the full sample for each quantile."""
    print("\n" + "=" * 60)
    print("FULL SAMPLE QUANTILE CONNECTEDNESS")
    print("=" * 60)

    K = vol_panel.shape[1]
    data_matrix = vol_panel.values

    results = {}
    for tau in QUANTILES:
        print(f"\n  Estimating Quantile VAR(2) at tau={tau}...")
        t0 = time.time()

        coefficients, residuals = estimate_quantile_var(data_matrix, VAR_LAG, tau)
        theta = compute_gfevd_from_quantile_var(coefficients, residuals, K, VAR_LAG, FORECAST_HORIZON)
        measures = compute_connectedness_measures(theta)

        elapsed = time.time() - t0
        print(f"    TCI(tau={tau}) = {measures['TCI']:.2f}% ({elapsed:.1f}s)")

        results[f'tau_{tau}'] = {
            'TCI': float(measures['TCI']),
            'FROM': {label: float(v) for label, v in zip(ASSET_LABELS, measures['FROM'])},
            'TO': {label: float(v) for label, v in zip(ASSET_LABELS, measures['TO'])},
            'NET': {label: float(v) for label, v in zip(ASSET_LABELS, measures['NET'])},
            'theta': measures['theta'].tolist()
        }

        # Print FROM/TO/NET
        print(f"    FROM: {', '.join(f'{l}={v:.1f}' for l, v in zip(ASSET_LABELS, measures['FROM']))}")
        print(f"    TO:   {', '.join(f'{l}={v:.1f}' for l, v in zip(ASSET_LABELS, measures['TO']))}")
        print(f"    NET:  {', '.join(f'{l}={v:+.1f}' for l, v in zip(ASSET_LABELS, measures['NET']))}")

    return results


# ============================================================
# Main
# ============================================================

def main():
    """Run K911 experiment."""
    print("K911: Quantile Connectedness & Tail Contagion (QDVC)")
    print("=" * 60)
    print(f"Start time: {datetime.now(timezone.utc).isoformat()}")
    t_start = time.time()

    # Step 1: Download data
    print("\n--- Step 1: Download Data ---")
    raw_data = download_data()

    # Step 2: Prepare panels
    print("\n--- Step 2: Prepare Data ---")
    vol_panel = prepare_vol_panel(raw_data)
    ret_panel = prepare_return_panel(raw_data)

    vix_data = raw_data.get(VIX_TICKER)
    if vix_data is None:
        print("WARNING: No VIX data!")
        vix_data = pd.DataFrame({'Close': pd.Series(dtype=float)})

    # Step 3: Full sample analysis
    print("\n--- Step 3: Full Sample Quantile Analysis ---")
    full_sample = full_sample_quantile_analysis(vol_panel)

    # Step 4: Rolling quantile connectedness
    print("\n--- Step 4: Rolling Quantile Connectedness ---")
    rolling_results = rolling_quantile_connectedness(
        vol_panel,
        window=ROLLING_WINDOW,
        step=ROLLING_STEP,
        H=FORECAST_HORIZON,
        lag_order=VAR_LAG,
        quantiles=QUANTILES,
        n_jobs=4
    )

    if rolling_results is None:
        print("ERROR: Rolling estimation failed")
        return

    # Step 5: Analysis
    print("\n--- Step 5: Analysis ---")
    tail_vs_mean = analyze_tail_vs_mean(rolling_results, vix_data)
    tail_prediction = analyze_tail_risk_prediction(rolling_results, ret_panel, vix_data)
    crisis = analyze_crisis_behavior(rolling_results, vix_data)

    # Step 6: Plots
    print("\n--- Step 6: Generate Plots ---")
    plot_rolling_quantile_tci(rolling_results, vix_data, OUTPUT_DIR)
    plot_tail_vs_mean_scatter(rolling_results, OUTPUT_DIR)
    plot_crisis_comparison(rolling_results, OUTPUT_DIR)

    # Step 7: Compile results
    elapsed_total = time.time() - t_start
    print(f"\n--- Total runtime: {elapsed_total:.1f}s ---")

    # Build key findings summary
    key_findings = []

    # Cross-quantile correlations
    if 'cross_quantile_corr' in tail_vs_mean:
        for k, v in tail_vs_mean['cross_quantile_corr'].items():
            if 'tau_0.05_vs_tau_0.5' in k:
                if v > 0.7:
                    key_findings.append(f"Tail TCI highly correlated with Mean TCI (r={v:.3f}) — "
                                       f"tail dimension not independent")
                elif v < 0.3:
                    key_findings.append(f"Tail TCI weakly correlated with Mean TCI (r={v:.3f}) — "
                                       f"tail is an independent dimension!")
                else:
                    key_findings.append(f"Tail TCI moderately correlated with Mean TCI (r={v:.3f})")

    # TCI-VIX correlations
    if 'tci_vix_corr' in tail_vs_mean:
        for tau in QUANTILES:
            key = f'tau_{tau}_pearson'
            if key in tail_vs_mean['tci_vix_corr']:
                r = tail_vs_mean['tci_vix_corr'][key]
                if tau == 0.05:
                    key_findings.append(f"Tail TCI(0.05) vs VIX: r={r:.3f} "
                                       f"({'correlated' if abs(r) > 0.3 else 'low correlation'})")

    # Prediction
    if tail_prediction:
        if 'logistic_tail_tci_only' in tail_prediction:
            auc = tail_prediction['logistic_tail_tci_only']['auc']
            key_findings.append(f"Tail TCI predicts tail events: AUC={auc:.3f}")
        if 'auc_improvement_tail_tci_over_vix' in tail_prediction:
            imp = tail_prediction['auc_improvement_tail_tci_over_vix']
            key_findings.append(f"Adding Tail TCI to VIX improves AUC by {imp:.4f}")

    findings_text = '; '.join(key_findings) if key_findings else 'See detailed results'

    results = {
        'experiment_id': 'K911',
        'title': 'Quantile Connectedness & Tail Contagion (QDVC)',
        'date': datetime.now(timezone.utc).isoformat(),
        'data_source': 'yfinance',
        'sample_period': f"{vol_panel.index[0].strftime('%Y-%m-%d')} to "
                        f"{vol_panel.index[-1].strftime('%Y-%m-%d')}",
        'n_trading_days': len(vol_panel),
        'assets': ASSET_LABELS,
        'vol_proxy': 'Garman-Klass (OHLC-based)',
        'var_lag_order': VAR_LAG,
        'forecast_horizon': FORECAST_HORIZON,
        'rolling_window': ROLLING_WINDOW,
        'rolling_step': ROLLING_STEP,
        'quantiles': QUANTILES,
        'method': 'Quantile VAR(2) + Generalized FEVD at tau={0.05, 0.50, 0.95}',
        'full_sample': full_sample,
        'tail_vs_mean_analysis': tail_vs_mean,
        'tail_risk_prediction': tail_prediction,
        'crisis_analysis': crisis,
        'runtime_seconds': float(elapsed_total),
        'key_findings': findings_text,
        'references': [
            'Ando, Greenwood-Nimmo, Shin (2022): Quantile Connectedness',
            'Diebold & Yilmaz (2012, 2014): Standard Connectedness',
            'Koenker & Bassett (1978): Quantile Regression',
            'K907: Volatility Spillover Network (mean TCI ~50%, r_VIX=0.001)',
            'K910: TCI not a trading signal (r=0.005)'
        ]
    }

    results_path = os.path.join(OUTPUT_DIR, 'k911_quantile_connectedness_results.json')
    with open(results_path, 'w') as f:
        json.dump(results, f, indent=2, cls=NumpyEncoder)
    print(f"\nResults saved: {results_path}")

    print("\n" + "=" * 60)
    print("KEY FINDINGS:")
    for i, finding in enumerate(key_findings, 1):
        print(f"  {i}. {finding}")
    print("=" * 60)


if __name__ == '__main__':
    main()
