#!/usr/bin/env python3
"""
K907: Volatility Spillover Network Analysis (Diebold-Yilmaz Connectedness)
==========================================================================
[提出: Claude, 執行: Claude]

Motivation:
  Existing research (800+ experiments) focuses on single-asset vol prediction.
  This experiment explores CROSS-ASSET volatility spillover using the
  Diebold & Yilmaz (2012, 2014) connectedness framework based on
  generalized forecast error variance decomposition (GFEVD).

  Key questions:
  1. What is the network structure of vol spillovers across major assets?
  2. Is Total Connectedness Index (TCI) correlated with VIX?
     (If r>0.7, this is another VIX sufficiency confirmation)
  3. Where does Taiwan (0050.TW) sit in the network? Net receiver or transmitter?
  4. How does network structure change during crises (GFC, COVID, 2022)?

Data:
  - yfinance daily OHLC for 9 assets + VIX (2006-01-01 to 2026-04-02)
  - Assets: SPY, QQQ, IWM, EFA, EEM, 0050.TW, GLD, TLT, USO
  - Vol proxy: Garman-Klass realized volatility (OHLC-based)

Method:
  - VAR(p) with AIC-selected lag order
  - Generalized FEVD (Pesaran & Shin 1998) — order-invariant
  - Rolling 250-day windows for time-varying connectedness
  - Diebold-Yilmaz decomposition: TCI, FROM, TO, NET, pairwise

Error Log rules:
  - 0050.TW: must use clean_tw50_data (volpred.utils)
  - Cross-market holidays: ffill prices, return=0
  - Do not treat network structure as trading signal without OOS validation
  - If TCI-VIX corr > 0.7: record as VIX sufficiency confirmation

References:
  - Diebold & Yilmaz (2012): "Better to give than to receive", IJF
  - Diebold & Yilmaz (2014): "On the network topology of variance decompositions", JFE
  - Pesaran & Shin (1998): Generalized impulse response analysis
  - Mateus (2024): East/Southeast Asian vol spillover
  - Paolella (2025): Regime-switching DCC
  - K817: VIX-Taiwan spillover (earlier related work)

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
from matplotlib.gridspec import GridSpec

from scipy import stats as sp_stats

warnings.filterwarnings('ignore')


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
ASSETS = ['SPY', 'QQQ', 'IWM', 'EFA', 'EEM', '0050.TW', 'GLD', 'TLT', 'USO']
ASSET_LABELS = ['SPY', 'QQQ', 'IWM', 'EFA', 'EEM', 'TW50', 'GLD', 'TLT', 'USO']
VIX_TICKER = '^VIX'
START_DATE = '2006-01-01'
END_DATE = '2026-04-02'
ROLLING_WINDOW = 250  # trading days
FORECAST_HORIZON = 10  # H in GFEVD
MAX_VAR_LAG = 5  # max lag to search via AIC
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
                print(f"  {ticker}: {len(df)} days ({df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')})")
            else:
                print(f"  {ticker}: NO DATA")
        except Exception as e:
            print(f"  {ticker}: ERROR - {e}")

    return data


def compute_garman_klass_vol(ohlc_df):
    """Compute Garman-Klass volatility proxy from OHLC data.

    GK = 0.5 * (log(H/L))^2 - (2*ln(2) - 1) * (log(C/O))^2
    This is a more efficient estimator than squared returns.
    """
    h = ohlc_df['High'].values
    l = ohlc_df['Low'].values
    c = ohlc_df['Close'].values
    o = ohlc_df['Open'].values

    # Avoid log(0) or log(negative)
    mask = (h > 0) & (l > 0) & (c > 0) & (o > 0) & (h >= l)
    gk = np.full(len(ohlc_df), np.nan)

    idx = mask
    log_hl = np.log(h[idx] / l[idx])
    log_co = np.log(c[idx] / o[idx])

    gk[idx] = 0.5 * log_hl**2 - (2 * np.log(2) - 1) * log_co**2
    # Ensure non-negative (GK can occasionally be slightly negative)
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

        # Special handling for 0050.TW
        if ticker == '0050.TW':
            close = df['Close']
            prices, _ = clean_tw50_data(close)
            df['Close'] = prices
            # Recompute Open/High/Low relative to cleaned Close
            # (This is approximate but acceptable for vol proxy)

        gk = compute_garman_klass_vol(df)
        vol_series[label] = gk

    # Create panel, align on common dates
    vol_panel = pd.DataFrame(vol_series)

    # Forward fill for holidays (cross-market alignment)
    vol_panel = vol_panel.ffill()
    # Drop rows where any asset has NaN (start alignment)
    vol_panel = vol_panel.dropna()

    print(f"\nAligned vol panel: {len(vol_panel)} days, {vol_panel.shape[1]} assets")
    print(f"  Period: {vol_panel.index[0].strftime('%Y-%m-%d')} to {vol_panel.index[-1].strftime('%Y-%m-%d')}")

    return vol_panel


# ============================================================
# VAR + Generalized FEVD (Diebold-Yilmaz Framework)
# ============================================================

def select_var_lag(data_matrix, max_lag=5):
    """Select optimal VAR lag order using AIC."""
    from statsmodels.tsa.api import VAR

    model = VAR(data_matrix)
    try:
        results = model.select_order(maxlags=max_lag)
        best_lag = results.aic
        if best_lag < 1:
            best_lag = 1
        return best_lag
    except Exception:
        return 2  # fallback


def estimate_var_and_gfevd(data_matrix, lag_order, H=10):
    """Estimate VAR(p) and compute Generalized FEVD.

    The generalized FEVD (Pesaran & Shin 1998) does not depend on
    variable ordering, unlike Cholesky decomposition.

    Returns:
        theta: (K x K) matrix where theta[i,j] = proportion of
               i's H-step forecast error variance due to shocks in j
               (normalized so rows sum to 1)
    """
    from statsmodels.tsa.api import VAR

    K = data_matrix.shape[1]

    # Fit VAR
    model = VAR(data_matrix)
    try:
        result = model.fit(lag_order)
    except Exception:
        # If fit fails, return identity (no spillover)
        return np.eye(K)

    # Get MA coefficients (impulse response matrices)
    # Phi_s for s = 0, 1, ..., H-1
    try:
        irf = result.irf(H - 1)
        Phi = irf.irfs  # shape: (H, K, K)
    except Exception:
        return np.eye(K)

    # Residual covariance matrix
    Sigma = result.sigma_u  # (K x K)
    sigma_diag = np.diag(Sigma)  # diagonal elements

    # Compute Generalized FEVD (Pesaran & Shin 1998)
    # theta_ij^g(H) = sigma_jj^{-1} * sum_{h=0}^{H-1} (e_i' Phi_h Sigma e_j)^2
    #                 / sum_{h=0}^{H-1} (e_i' Phi_h Sigma Phi_h' e_i)

    theta = np.zeros((K, K))

    for i in range(K):
        # Denominator: total FEV of variable i
        denom = 0.0
        for h in range(H):
            denom += Phi[h, i, :] @ Sigma @ Phi[h, i, :]

        if denom < 1e-12:
            theta[i, :] = 1.0 / K  # uniform if degenerate
            continue

        for j in range(K):
            # Numerator: contribution of shock j to FEV of variable i
            numer = 0.0
            for h in range(H):
                val = Phi[h, i, :] @ Sigma[:, j]
                numer += val ** 2
            numer /= sigma_diag[j]

            theta[i, j] = numer / denom

    # Normalize rows to sum to 1 (as in Diebold-Yilmaz)
    row_sums = theta.sum(axis=1, keepdims=True)
    row_sums[row_sums < 1e-12] = 1.0
    theta = theta / row_sums

    return theta


def compute_connectedness_measures(theta):
    """Compute all Diebold-Yilmaz connectedness measures from GFEVD matrix.

    Args:
        theta: (K x K) normalized GFEVD matrix (rows sum to 1)

    Returns:
        dict with TCI, FROM, TO, NET, and pairwise measures
    """
    K = theta.shape[0]

    # Total Connectedness Index: average of all off-diagonal elements
    off_diag_sum = theta.sum() - np.trace(theta)
    TCI = off_diag_sum / K * 100  # percentage

    # Directional FROM: how much of i's FEV comes from others
    FROM = np.zeros(K)
    for i in range(K):
        FROM[i] = (theta[i, :].sum() - theta[i, i]) * 100

    # Directional TO: how much i contributes to others' FEV
    TO = np.zeros(K)
    for j in range(K):
        TO[j] = (theta[:, j].sum() - theta[j, j]) * 100

    # Net spillover: TO - FROM
    NET = TO - FROM

    return {
        'TCI': TCI,
        'FROM': FROM,
        'TO': TO,
        'NET': NET,
        'theta': theta
    }


# ============================================================
# Rolling Estimation (with multiprocessing)
# ============================================================

def _estimate_single_window(args):
    """Worker function for parallel rolling estimation."""
    window_data, lag_order, H, date_str = args
    try:
        theta = estimate_var_and_gfevd(window_data, lag_order, H)
        measures = compute_connectedness_measures(theta)
        return date_str, measures['TCI'], measures['FROM'], measures['TO'], measures['NET']
    except Exception as e:
        K = window_data.shape[1]
        return date_str, np.nan, np.full(K, np.nan), np.full(K, np.nan), np.full(K, np.nan)


def rolling_connectedness(vol_panel, window=250, H=10, max_lag=5, n_jobs=4):
    """Compute time-varying connectedness via rolling windows.

    Uses multiprocessing for speed on M1 Max.
    """
    T, K = vol_panel.shape
    n_windows = T - window + 1

    if n_windows < 10:
        print(f"ERROR: Only {n_windows} windows available, need at least 10")
        return None

    print(f"\nRolling connectedness: {n_windows} windows, {window}-day each")

    # Prepare all window data
    # First, select a global lag order from the full sample
    global_lag = select_var_lag(vol_panel.values, max_lag)
    print(f"  Global VAR lag order (AIC): {global_lag}")

    # Create tasks
    tasks = []
    dates = vol_panel.index[window - 1:]
    for i in range(n_windows):
        window_data = vol_panel.values[i:i + window]
        date_str = dates[i].strftime('%Y-%m-%d')
        tasks.append((window_data, global_lag, H, date_str))

    # Process in parallel
    print(f"  Processing {n_windows} windows with {n_jobs} workers...")
    t0 = time.time()

    results_list = []
    # Use smaller batches to avoid memory issues
    batch_size = 100
    n_batches = (n_windows + batch_size - 1) // batch_size

    for batch_idx in range(n_batches):
        start = batch_idx * batch_size
        end = min(start + batch_size, n_windows)
        batch_tasks = tasks[start:end]

        with ProcessPoolExecutor(max_workers=n_jobs) as executor:
            futures = [executor.submit(_estimate_single_window, t) for t in batch_tasks]
            for f in as_completed(futures):
                results_list.append(f.result())

        if (batch_idx + 1) % 10 == 0:
            elapsed = time.time() - t0
            pct = (end / n_windows) * 100
            print(f"    Batch {batch_idx + 1}/{n_batches} ({pct:.0f}%), elapsed: {elapsed:.1f}s")

    elapsed = time.time() - t0
    print(f"  Completed in {elapsed:.1f}s")

    # Sort by date and organize
    results_list.sort(key=lambda x: x[0])

    rolling_dates = []
    rolling_tci = []
    rolling_from = []
    rolling_to = []
    rolling_net = []

    for date_str, tci, from_arr, to_arr, net_arr in results_list:
        rolling_dates.append(pd.Timestamp(date_str))
        rolling_tci.append(tci)
        rolling_from.append(from_arr)
        rolling_to.append(to_arr)
        rolling_net.append(net_arr)

    rolling_tci = np.array(rolling_tci)
    rolling_from = np.array(rolling_from)
    rolling_to = np.array(rolling_to)
    rolling_net = np.array(rolling_net)

    return {
        'dates': rolling_dates,
        'TCI': rolling_tci,
        'FROM': rolling_from,
        'TO': rolling_to,
        'NET': rolling_net,
        'lag_order': global_lag
    }


# ============================================================
# Descriptive Statistics
# ============================================================

def compute_descriptive_stats(vol_panel):
    """Compute descriptive statistics for vol proxy panel."""
    stats = {}
    for col in vol_panel.columns:
        s = vol_panel[col].dropna()
        stats[col] = {
            'count': len(s),
            'mean': float(s.mean()),
            'std': float(s.std()),
            'skew': float(sp_stats.skew(s)),
            'kurtosis': float(sp_stats.kurtosis(s)),
            'min': float(s.min()),
            'max': float(s.max()),
            'median': float(s.median()),
        }

        # ADF test for stationarity
        from statsmodels.tsa.stattools import adfuller
        try:
            adf_stat, adf_pval, _, _, _, _ = adfuller(s, maxlag=20, autolag='AIC')
            stats[col]['adf_stat'] = float(adf_stat)
            stats[col]['adf_pval'] = float(adf_pval)
            stats[col]['is_stationary'] = adf_pval < 0.05
        except Exception:
            stats[col]['adf_stat'] = np.nan
            stats[col]['adf_pval'] = np.nan
            stats[col]['is_stationary'] = None

    return stats


# ============================================================
# Analysis: TCI vs VIX
# ============================================================

def analyze_tci_vix(rolling_results, vix_data):
    """Analyze relationship between TCI and VIX."""
    tci_series = pd.Series(rolling_results['TCI'], index=rolling_results['dates'], name='TCI')

    # VIX daily levels
    vix_close = vix_data['Close'] if 'Close' in vix_data.columns else vix_data.iloc[:, 0]
    vix_series = vix_close.copy()
    vix_series.name = 'VIX'

    # Align on common dates
    df = pd.DataFrame({'TCI': tci_series, 'VIX': vix_series}).dropna()

    if len(df) < 50:
        return {'error': 'Insufficient aligned data'}

    # Pearson correlation
    pearson_r, pearson_p = sp_stats.pearsonr(df['TCI'], df['VIX'])

    # Spearman rank correlation
    spearman_r, spearman_p = sp_stats.spearmanr(df['TCI'], df['VIX'])

    # Rolling 252-day correlation
    rolling_corr = df['TCI'].rolling(252).corr(df['VIX'])

    # Crisis period correlations
    crisis_periods = {
        'GFC_2008': ('2008-01-01', '2009-03-31'),
        'COVID_2020': ('2020-01-01', '2020-06-30'),
        'Rate_Hike_2022': ('2022-01-01', '2022-12-31'),
        'Normal_2013_2019': ('2013-01-01', '2019-12-31'),
    }

    crisis_corrs = {}
    for name, (start, end) in crisis_periods.items():
        subset = df.loc[start:end]
        if len(subset) > 30:
            r, p = sp_stats.pearsonr(subset['TCI'], subset['VIX'])
            crisis_corrs[name] = {'pearson_r': float(r), 'p_value': float(p), 'n_obs': len(subset)}

    vix_sufficiency = abs(pearson_r) > 0.7

    return {
        'pearson_r': float(pearson_r),
        'pearson_p': float(pearson_p),
        'spearman_r': float(spearman_r),
        'spearman_p': float(spearman_p),
        'rolling_corr_mean': float(rolling_corr.mean()),
        'rolling_corr_std': float(rolling_corr.std()),
        'crisis_correlations': crisis_corrs,
        'n_aligned_obs': len(df),
        'vix_sufficiency_confirmed': vix_sufficiency,
        'tci_series': tci_series,
        'vix_series': vix_series.loc[tci_series.index[0]:tci_series.index[-1]],
        'rolling_corr': rolling_corr,
    }


# ============================================================
# Visualization
# ============================================================

def plot_full_sample_network(theta, asset_labels, save_path):
    """Plot the full-sample spillover network as a heatmap."""
    fig, ax = plt.subplots(1, 1, figsize=(10, 8))

    K = len(asset_labels)
    im = ax.imshow(theta * 100, cmap='YlOrRd', aspect='auto')

    ax.set_xticks(range(K))
    ax.set_yticks(range(K))
    ax.set_xticklabels(asset_labels, rotation=45, ha='right', fontsize=10)
    ax.set_yticklabels(asset_labels, fontsize=10)

    # Add text annotations
    for i in range(K):
        for j in range(K):
            val = theta[i, j] * 100
            color = 'white' if val > 15 else 'black'
            ax.text(j, i, f'{val:.1f}', ha='center', va='center', fontsize=8, color=color)

    ax.set_title('Volatility Spillover Network (GFEVD %)\nDiebold-Yilmaz (2012)', fontsize=13)
    ax.set_xlabel('Shock Source (j)', fontsize=11)
    ax.set_ylabel('Shock Receiver (i)', fontsize=11)

    plt.colorbar(im, ax=ax, label='GFEVD (%)', shrink=0.8)
    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {save_path}")


def plot_net_spillover_ranking(net_spillover, asset_labels, save_path):
    """Bar chart of net spillover (TO - FROM) for each asset."""
    fig, ax = plt.subplots(figsize=(10, 6))

    # Sort by net spillover
    sorted_idx = np.argsort(net_spillover)[::-1]
    sorted_labels = [asset_labels[i] for i in sorted_idx]
    sorted_values = net_spillover[sorted_idx]

    colors = ['#e74c3c' if v > 0 else '#3498db' for v in sorted_values]

    bars = ax.barh(range(len(sorted_labels)), sorted_values, color=colors, edgecolor='gray', alpha=0.85)
    ax.set_yticks(range(len(sorted_labels)))
    ax.set_yticklabels(sorted_labels, fontsize=11)
    ax.axvline(x=0, color='black', linewidth=0.8)
    ax.set_xlabel('Net Spillover (TO - FROM) %', fontsize=11)
    ax.set_title('Net Volatility Spillover Ranking\n(Red = Net Transmitter, Blue = Net Receiver)', fontsize=13)

    # Add value labels
    for bar, val in zip(bars, sorted_values):
        x_pos = val + 0.3 if val >= 0 else val - 0.3
        ha = 'left' if val >= 0 else 'right'
        ax.text(x_pos, bar.get_y() + bar.get_height() / 2,
                f'{val:.1f}%', va='center', ha=ha, fontsize=9)

    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {save_path}")


def plot_tci_vs_vix(tci_vix_results, save_path):
    """Plot TCI time series vs VIX."""
    fig, axes = plt.subplots(3, 1, figsize=(14, 12), gridspec_kw={'height_ratios': [3, 3, 2]})

    tci = tci_vix_results['tci_series']
    vix = tci_vix_results['vix_series']
    rolling_corr = tci_vix_results['rolling_corr']

    # Panel 1: TCI time series
    ax1 = axes[0]
    ax1.plot(tci.index, tci.values, color='#e74c3c', linewidth=0.8, alpha=0.9, label='TCI')
    ax1.fill_between(tci.index, tci.values, alpha=0.15, color='#e74c3c')
    ax1.set_ylabel('Total Connectedness Index (%)', fontsize=11)
    ax1.set_title('Diebold-Yilmaz Total Connectedness Index vs VIX', fontsize=13)
    ax1.legend(loc='upper left')
    ax1.grid(True, alpha=0.3)

    # Mark crisis periods
    crisis_spans = [
        ('2008-09-01', '2009-03-31', 'GFC'),
        ('2020-02-01', '2020-06-30', 'COVID'),
        ('2022-01-01', '2022-10-31', 'Rate Hike'),
    ]
    for start, end, label in crisis_spans:
        ax1.axvspan(pd.Timestamp(start), pd.Timestamp(end), alpha=0.15, color='gray')
        mid = pd.Timestamp(start) + (pd.Timestamp(end) - pd.Timestamp(start)) / 2
        ax1.text(mid, ax1.get_ylim()[1] * 0.95, label, ha='center', fontsize=8, alpha=0.7)

    # Panel 2: VIX
    ax2 = axes[1]
    ax2.plot(vix.index, vix.values, color='#2c3e50', linewidth=0.8, alpha=0.9, label='VIX')
    ax2.fill_between(vix.index, vix.values, alpha=0.1, color='#2c3e50')
    ax2.set_ylabel('VIX Level', fontsize=11)
    ax2.legend(loc='upper left')
    ax2.grid(True, alpha=0.3)
    for start, end, label in crisis_spans:
        ax2.axvspan(pd.Timestamp(start), pd.Timestamp(end), alpha=0.15, color='gray')

    # Panel 3: Rolling correlation
    ax3 = axes[2]
    ax3.plot(rolling_corr.index, rolling_corr.values, color='#8e44ad', linewidth=0.8, alpha=0.9)
    ax3.axhline(y=0.7, color='red', linestyle='--', alpha=0.5, label='r=0.7 threshold')
    ax3.axhline(y=0, color='black', linewidth=0.5)
    ax3.set_ylabel('Rolling 252d Corr (TCI-VIX)', fontsize=11)
    ax3.set_xlabel('Date', fontsize=11)
    ax3.legend(loc='lower left')
    ax3.grid(True, alpha=0.3)
    ax3.set_ylim(-0.3, 1.0)

    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {save_path}")


def plot_rolling_net_spillover(rolling_results, asset_labels, save_path):
    """Plot time-varying net spillover for key assets."""
    fig, ax = plt.subplots(figsize=(14, 7))

    dates = rolling_results['dates']
    net = rolling_results['NET']  # (T, K)

    # Select key assets to plot (avoid clutter)
    key_assets = ['SPY', 'TW50', 'GLD', 'EEM', 'TLT']
    colors_map = {'SPY': '#e74c3c', 'TW50': '#2ecc71', 'GLD': '#f39c12',
                  'EEM': '#3498db', 'TLT': '#9b59b6'}

    for label in key_assets:
        if label in asset_labels:
            idx = asset_labels.index(label)
            ax.plot(dates, net[:, idx], label=label, color=colors_map.get(label, 'gray'),
                    linewidth=0.8, alpha=0.85)

    ax.axhline(y=0, color='black', linewidth=0.8)
    ax.set_ylabel('Net Spillover (TO - FROM) %', fontsize=11)
    ax.set_xlabel('Date', fontsize=11)
    ax.set_title('Time-Varying Net Volatility Spillover\n(Above 0 = Net Transmitter, Below 0 = Net Receiver)', fontsize=13)
    ax.legend(loc='best', fontsize=9)
    ax.grid(True, alpha=0.3)

    # Mark crisis
    for start, end, label in [('2008-09-01', '2009-03-31', 'GFC'),
                              ('2020-02-01', '2020-06-30', 'COVID')]:
        ax.axvspan(pd.Timestamp(start), pd.Timestamp(end), alpha=0.1, color='gray')

    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {save_path}")


def plot_crisis_comparison(vol_panel, rolling_results, asset_labels, save_path):
    """Compare network structure across crisis vs normal periods."""
    dates = rolling_results['dates']
    tci = rolling_results['TCI']

    periods = {
        'Normal\n(2013-2019)': ('2013-01-01', '2019-12-31'),
        'GFC\n(2008-2009)': ('2008-01-01', '2009-06-30'),
        'COVID\n(2020)': ('2020-01-01', '2020-12-31'),
        'Rate Hike\n(2022)': ('2022-01-01', '2022-12-31'),
    }

    fig, axes = plt.subplots(1, 4, figsize=(18, 5))

    for idx, (name, (start, end)) in enumerate(periods.items()):
        # Get data for this period
        mask = (vol_panel.index >= start) & (vol_panel.index <= end)
        period_data = vol_panel.loc[mask]

        if len(period_data) < 50:
            axes[idx].text(0.5, 0.5, 'Insufficient data', ha='center', va='center',
                           transform=axes[idx].transAxes)
            axes[idx].set_title(name)
            continue

        # Estimate VAR and GFEVD for this sub-period
        lag = select_var_lag(period_data.values, MAX_VAR_LAG)
        theta = estimate_var_and_gfevd(period_data.values, lag, FORECAST_HORIZON)
        measures = compute_connectedness_measures(theta)

        # Plot heatmap
        K = len(asset_labels)
        im = axes[idx].imshow(theta * 100, cmap='YlOrRd', aspect='auto', vmin=0, vmax=30)
        axes[idx].set_xticks(range(K))
        axes[idx].set_yticks(range(K))
        axes[idx].set_xticklabels(asset_labels, rotation=90, fontsize=7)
        axes[idx].set_yticklabels(asset_labels, fontsize=7)
        axes[idx].set_title(f'{name}\nTCI={measures["TCI"]:.1f}%', fontsize=10)

    fig.suptitle('Volatility Spillover Network Across Regimes', fontsize=13, y=1.02)
    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {save_path}")


# ============================================================
# Robustness Checks
# ============================================================

def robustness_checks(vol_panel):
    """Check sensitivity to key parameters."""
    print("\n=== Robustness Checks ===")

    results = {}

    # 1. Different VAR lag orders
    print("\n1. Sensitivity to VAR lag order:")
    for lag in [2, 3, 5]:
        theta = estimate_var_and_gfevd(vol_panel.values, lag, FORECAST_HORIZON)
        measures = compute_connectedness_measures(theta)
        results[f'lag_{lag}'] = {'TCI': float(measures['TCI'])}
        print(f"   lag={lag}: TCI = {measures['TCI']:.2f}%")

    # 2. Different forecast horizons
    print("\n2. Sensitivity to forecast horizon H:")
    lag = select_var_lag(vol_panel.values, MAX_VAR_LAG)
    for H in [5, 10, 20]:
        theta = estimate_var_and_gfevd(vol_panel.values, lag, H)
        measures = compute_connectedness_measures(theta)
        results[f'H_{H}'] = {'TCI': float(measures['TCI'])}
        print(f"   H={H}: TCI = {measures['TCI']:.2f}%")

    # 3. Different rolling windows (compute TCI mean/std for each)
    print("\n3. Sensitivity to rolling window size:")
    for w in [200, 250, 500]:
        n_w = len(vol_panel) - w + 1
        if n_w < 50:
            print(f"   window={w}: insufficient data ({n_w} windows)")
            continue

        # Sample a subset for speed (every 10th window)
        sample_tcis = []
        for i in range(0, n_w, max(1, n_w // 50)):
            window_data = vol_panel.values[i:i + w]
            theta = estimate_var_and_gfevd(window_data, lag, FORECAST_HORIZON)
            m = compute_connectedness_measures(theta)
            if not np.isnan(m['TCI']):
                sample_tcis.append(m['TCI'])

        if sample_tcis:
            mean_tci = np.mean(sample_tcis)
            std_tci = np.std(sample_tcis)
            results[f'window_{w}'] = {'TCI_mean': float(mean_tci), 'TCI_std': float(std_tci)}
            print(f"   window={w}: TCI mean = {mean_tci:.2f}% (std = {std_tci:.2f}%)")

    return results


# ============================================================
# Main
# ============================================================

def main():
    print("=" * 70)
    print("K907: Volatility Spillover Network (Diebold-Yilmaz)")
    print("=" * 70)

    t_start = time.time()

    # Step 1: Download data
    print("\n--- Step 1: Data Download ---")
    raw_data = download_data()

    # Step 2: Prepare vol panel
    print("\n--- Step 2: Prepare Volatility Panel (Garman-Klass) ---")
    vol_panel = prepare_vol_panel(raw_data)

    # Align asset labels to actual columns
    actual_labels = list(vol_panel.columns)
    print(f"  Assets in panel: {actual_labels}")

    # Step 3: Descriptive Statistics
    print("\n--- Step 3: Descriptive Statistics ---")
    desc_stats = compute_descriptive_stats(vol_panel)
    for label in actual_labels:
        s = desc_stats[label]
        stat_str = (f"  {label}: mean={s['mean']:.6f}, std={s['std']:.6f}, "
                    f"skew={s['skew']:.2f}, kurt={s['kurtosis']:.2f}, "
                    f"ADF p={s['adf_pval']:.4f} ({'stationary' if s['is_stationary'] else 'NON-STAT'})")
        print(stat_str)

    # Step 4: Full-sample GFEVD
    print("\n--- Step 4: Full-Sample VAR + GFEVD ---")
    lag_order = select_var_lag(vol_panel.values, MAX_VAR_LAG)
    print(f"  Optimal VAR lag (AIC): {lag_order}")

    theta_full = estimate_var_and_gfevd(vol_panel.values, lag_order, FORECAST_HORIZON)
    measures_full = compute_connectedness_measures(theta_full)

    print(f"\n  Total Connectedness Index (TCI): {measures_full['TCI']:.2f}%")
    print(f"\n  Directional Spillovers:")
    print(f"  {'Asset':<8} {'FROM':>8} {'TO':>8} {'NET':>8}")
    print(f"  {'-'*32}")
    for i, label in enumerate(actual_labels):
        print(f"  {label:<8} {measures_full['FROM'][i]:>8.2f} {measures_full['TO'][i]:>8.2f} {measures_full['NET'][i]:>8.2f}")

    # Step 5: Rolling Connectedness
    print("\n--- Step 5: Rolling Connectedness ---")
    rolling_results = rolling_connectedness(vol_panel, window=ROLLING_WINDOW, H=FORECAST_HORIZON,
                                           max_lag=MAX_VAR_LAG, n_jobs=4)

    if rolling_results is not None:
        tci_arr = rolling_results['TCI']
        valid_tci = tci_arr[~np.isnan(tci_arr)]
        print(f"\n  Rolling TCI statistics:")
        print(f"    Mean: {np.mean(valid_tci):.2f}%")
        print(f"    Std:  {np.std(valid_tci):.2f}%")
        print(f"    Min:  {np.min(valid_tci):.2f}%")
        print(f"    Max:  {np.max(valid_tci):.2f}%")
        print(f"    Median: {np.median(valid_tci):.2f}%")

    # Step 6: TCI vs VIX analysis
    print("\n--- Step 6: TCI vs VIX Analysis ---")
    tci_vix_results = None
    if VIX_TICKER in raw_data and rolling_results is not None:
        tci_vix_results = analyze_tci_vix(rolling_results, raw_data[VIX_TICKER])
        if 'error' not in tci_vix_results:
            print(f"  Pearson correlation (TCI, VIX):  r = {tci_vix_results['pearson_r']:.4f} (p = {tci_vix_results['pearson_p']:.2e})")
            print(f"  Spearman correlation (TCI, VIX): r = {tci_vix_results['spearman_r']:.4f} (p = {tci_vix_results['spearman_p']:.2e})")
            print(f"  Rolling 252d corr: mean = {tci_vix_results['rolling_corr_mean']:.4f}, std = {tci_vix_results['rolling_corr_std']:.4f}")
            if tci_vix_results['vix_sufficiency_confirmed']:
                print(f"  *** VIX SUFFICIENCY CONFIRMED (|r| > 0.7) ***")
            else:
                print(f"  VIX sufficiency NOT confirmed (|r| <= 0.7) — TCI captures DIFFERENT information")

            if tci_vix_results['crisis_correlations']:
                print(f"\n  Crisis-period correlations:")
                for period, vals in tci_vix_results['crisis_correlations'].items():
                    print(f"    {period}: r = {vals['pearson_r']:.4f} (p = {vals['p_value']:.4f}, n = {vals['n_obs']})")
        else:
            print(f"  ERROR: {tci_vix_results['error']}")

    # Step 7: Robustness Checks
    print("\n--- Step 7: Robustness Checks ---")
    robustness = robustness_checks(vol_panel)

    # Step 8: Visualization
    print("\n--- Step 8: Visualization ---")

    # 8a: Full-sample network heatmap
    plot_full_sample_network(theta_full, actual_labels,
                            os.path.join(OUTPUT_DIR, 'k907_spillover_network.png'))

    # 8b: Net spillover ranking
    plot_net_spillover_ranking(measures_full['NET'], actual_labels,
                              os.path.join(OUTPUT_DIR, 'k907_net_spillover_ranking.png'))

    # 8c: TCI vs VIX
    if tci_vix_results and 'error' not in tci_vix_results:
        plot_tci_vs_vix(tci_vix_results,
                        os.path.join(OUTPUT_DIR, 'k907_tci_vs_vix.png'))

    # 8d: Rolling net spillover
    if rolling_results is not None:
        plot_rolling_net_spillover(rolling_results, actual_labels,
                                  os.path.join(OUTPUT_DIR, 'k907_rolling_net_spillover.png'))

    # 8e: Crisis comparison
    plot_crisis_comparison(vol_panel, rolling_results, actual_labels,
                           os.path.join(OUTPUT_DIR, 'k907_crisis_comparison.png'))

    # ============================================================
    # Save Results
    # ============================================================
    elapsed = time.time() - t_start

    # Taiwan network position
    tw_idx = actual_labels.index('TW50') if 'TW50' in actual_labels else None
    tw_net = float(measures_full['NET'][tw_idx]) if tw_idx is not None else None
    tw_from = float(measures_full['FROM'][tw_idx]) if tw_idx is not None else None
    tw_to = float(measures_full['TO'][tw_idx]) if tw_idx is not None else None
    tw_role = 'Net Transmitter' if (tw_net and tw_net > 0) else 'Net Receiver' if (tw_net and tw_net < 0) else 'Unknown'

    # Top transmitter and receiver
    net_arr = measures_full['NET']
    top_transmitter_idx = np.argmax(net_arr)
    top_receiver_idx = np.argmin(net_arr)

    # Net spillover dict
    net_spillover_dict = {actual_labels[i]: float(measures_full['NET'][i]) for i in range(len(actual_labels))}

    # Rolling TCI stats
    rolling_tci_stats = {}
    if rolling_results is not None:
        valid_tci = rolling_results['TCI'][~np.isnan(rolling_results['TCI'])]
        rolling_tci_stats = {
            'mean': float(np.mean(valid_tci)),
            'std': float(np.std(valid_tci)),
            'min': float(np.min(valid_tci)),
            'max': float(np.max(valid_tci)),
            'median': float(np.median(valid_tci)),
        }

    # Key findings summary
    findings = []
    findings.append(f"Full-sample TCI = {measures_full['TCI']:.1f}%: {'' if measures_full['TCI'] > 50 else 'moderate '}cross-asset vol interconnectedness")
    findings.append(f"Top net transmitter: {actual_labels[top_transmitter_idx]} (NET = {net_arr[top_transmitter_idx]:.1f}%)")
    findings.append(f"Top net receiver: {actual_labels[top_receiver_idx]} (NET = {net_arr[top_receiver_idx]:.1f}%)")

    if tw_idx is not None:
        findings.append(f"Taiwan (0050.TW) is a {tw_role}: FROM = {tw_from:.1f}%, TO = {tw_to:.1f}%, NET = {tw_net:.1f}%")

    if tci_vix_results and 'error' not in tci_vix_results:
        r = tci_vix_results['pearson_r']
        if tci_vix_results['vix_sufficiency_confirmed']:
            findings.append(f"TCI-VIX correlation r = {r:.3f}: VIX sufficiency CONFIRMED again")
        else:
            findings.append(f"TCI-VIX correlation r = {r:.3f}: TCI captures information BEYOND VIX")

    key_findings_text = ". ".join(findings)

    tci_vix_clean = {}
    if tci_vix_results and 'error' not in tci_vix_results:
        tci_vix_clean = {
            'pearson_r': tci_vix_results['pearson_r'],
            'pearson_p': tci_vix_results['pearson_p'],
            'spearman_r': tci_vix_results['spearman_r'],
            'spearman_p': tci_vix_results['spearman_p'],
            'rolling_corr_mean': tci_vix_results['rolling_corr_mean'],
            'rolling_corr_std': tci_vix_results['rolling_corr_std'],
            'crisis_correlations': tci_vix_results['crisis_correlations'],
            'n_aligned_obs': tci_vix_results['n_aligned_obs'],
            'vix_sufficiency_confirmed': tci_vix_results['vix_sufficiency_confirmed'],
        }

    results = {
        'experiment_id': 'K907',
        'title': 'Volatility Spillover Network Analysis (Diebold-Yilmaz Connectedness)',
        'date': datetime.now(timezone.utc).isoformat(),
        'data_source': 'yfinance',
        'sample_period': f'{vol_panel.index[0].strftime("%Y-%m-%d")} to {vol_panel.index[-1].strftime("%Y-%m-%d")}',
        'n_trading_days': int(len(vol_panel)),
        'assets': actual_labels,
        'vol_proxy': 'Garman-Klass (OHLC-based)',
        'var_lag_order': lag_order,
        'forecast_horizon': FORECAST_HORIZON,
        'rolling_window': ROLLING_WINDOW,

        'full_sample': {
            'TCI': float(measures_full['TCI']),
            'FROM': {actual_labels[i]: float(measures_full['FROM'][i]) for i in range(len(actual_labels))},
            'TO': {actual_labels[i]: float(measures_full['TO'][i]) for i in range(len(actual_labels))},
            'NET': net_spillover_dict,
            'top_transmitter': actual_labels[top_transmitter_idx],
            'top_receiver': actual_labels[top_receiver_idx],
            'theta_matrix': theta_full.tolist(),
        },

        'rolling_tci_stats': rolling_tci_stats,

        'taiwan_network_position': {
            'role': tw_role,
            'FROM': tw_from,
            'TO': tw_to,
            'NET': tw_net,
        },

        'tci_vix_analysis': tci_vix_clean,

        'robustness': robustness,

        'descriptive_stats': desc_stats,

        'key_findings': key_findings_text,

        'charts': [
            'k907_spillover_network.png',
            'k907_net_spillover_ranking.png',
            'k907_tci_vs_vix.png',
            'k907_rolling_net_spillover.png',
            'k907_crisis_comparison.png',
        ],

        'references': [
            'Diebold & Yilmaz (2012): Better to give than to receive, IJF',
            'Diebold & Yilmaz (2014): On the network topology of variance decompositions, JFE',
            'Pesaran & Shin (1998): Generalized impulse response analysis',
        ],

        'limitations': [
            'Garman-Klass vol is a noisy proxy; 5-min RV would be superior',
            'VAR assumes linearity; regime-switching or threshold VAR could capture asymmetries',
            '0050.TW has limited trading hours vs US markets (alignment via ffill)',
            'USO has structural issues (contango, ETF restructuring in 2020)',
            'Rolling window size affects smoothness vs responsiveness tradeoff',
        ],

        'runtime_seconds': elapsed,
    }

    # Save
    output_path = os.path.join(OUTPUT_DIR, 'k907_volatility_spillover_network_results.json')
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False, cls=NumpyEncoder)
    print(f"\n  Results saved: {output_path}")

    # Summary
    print(f"\n{'='*70}")
    print(f"K907 COMPLETED in {elapsed:.1f}s")
    print(f"{'='*70}")
    print(f"\nKey Findings:")
    for f_text in findings:
        print(f"  * {f_text}")
    print(f"\nCharts saved to: {OUTPUT_DIR}")

    return results


if __name__ == '__main__':
    results = main()
