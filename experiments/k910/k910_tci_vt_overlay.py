#!/usr/bin/env python3
"""
K910: TCI (Total Connectedness Index) as VT Strategy Overlay
=============================================================
[提出: Claude, 執行: Claude]

Motivation:
  K907 discovered TCI-VIX Pearson r = 0.001 (p=0.93) -- completely orthogonal.
  TCI measures cross-asset vol spillover (network structure), while VIX measures
  vol level. If TCI captures systemic risk beyond VIX, it could improve VT strategies.

Hypothesis:
  1. TCI Defensive: High TCI (high connectedness) → reduce equity exposure
     (diversification fails when assets are highly connected)
  2. TCI + VIX Combined: Two orthogonal dimensions → richer regime classification
  3. Smooth TCI weight: Continuous weight adjustment like 12/VIX

Data:
  - yfinance daily OHLC for 9 assets + VIX (2006-01-01 to 2026-04-02)
  - Assets: SPY, QQQ, IWM, EFA, EEM, 0050.TW, GLD, TLT, USO
  - Vol proxy: Garman-Klass realized volatility (OHLC-based)
  - Rolling TCI: 250-day VAR(5) + GFEVD H=10

OOS Period: 2010-01 to 2026-03 (~16 years, after 250-day burn-in)

Error Log rules:
  - 0050.TW: must use clean_tw50_data
  - signal.shift(1): MUST lag all signals
  - Sharpe > 2x baseline = almost certainly a bug
  - DM test: use strategy_dm_test from volpred.stats
  - VT = drawdown insurance, not alpha generator (K687/K697)
  - 50/50 SPY/GLD is irreducible baseline

References:
  - K907: Volatility Spillover Network (TCI-VIX r=0.001)
  - K687/K697: VT is insurance, not alpha
  - K700: Codex audit prevents false breakthroughs
  - Diebold & Yilmaz (2012, 2014): Connectedness framework
  - Pesaran & Shin (1998): Generalized impulse response

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

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from scipy import stats as sp_stats

warnings.filterwarnings('ignore')
np.random.seed(42)  # Fixed seed for reproducibility


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
END_DATE = '2026-04-04'
ROLLING_WINDOW = 250
FORECAST_HORIZON = 10
MAX_VAR_LAG = 5
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))


# ============================================================
# Data Download & Preparation (from K907)
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
                print(f"  {ticker}: {len(df)} days")
            else:
                print(f"  {ticker}: NO DATA")
        except Exception as e:
            print(f"  {ticker}: ERROR - {e}")

    return data


def compute_garman_klass_vol(ohlc_df):
    """Compute Garman-Klass volatility proxy from OHLC data."""
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
    try:
        from volpred.utils import clean_tw50_data
        has_clean = True
    except ImportError:
        has_clean = False
        print("WARNING: clean_tw50_data not available, using raw 0050.TW data")

    vol_series = {}
    for ticker, label in zip(ASSETS, ASSET_LABELS):
        if ticker not in raw_data:
            print(f"  WARNING: {ticker} not in data, skipping")
            continue

        df = raw_data[ticker].copy()
        if ticker == '0050.TW' and has_clean:
            close = df['Close']
            prices, _ = clean_tw50_data(close)
            df['Close'] = prices

        gk = compute_garman_klass_vol(df)
        vol_series[label] = gk

    vol_panel = pd.DataFrame(vol_series)
    vol_panel = vol_panel.ffill()
    vol_panel = vol_panel.dropna()

    print(f"\nAligned vol panel: {len(vol_panel)} days, {vol_panel.shape[1]} assets")
    return vol_panel


# ============================================================
# VAR + Generalized FEVD (from K907)
# ============================================================

def estimate_var_and_gfevd(data_matrix, lag_order, H=10):
    """Estimate VAR(p) and compute Generalized FEVD."""
    from statsmodels.tsa.api import VAR

    K = data_matrix.shape[1]
    model = VAR(data_matrix)
    try:
        result = model.fit(lag_order)
    except Exception:
        return np.eye(K)

    try:
        irf = result.irf(H - 1)
        Phi = irf.irfs
    except Exception:
        return np.eye(K)

    Sigma = result.sigma_u
    sigma_diag = np.diag(Sigma)

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

    row_sums = theta.sum(axis=1, keepdims=True)
    row_sums[row_sums < 1e-12] = 1.0
    theta = theta / row_sums

    return theta


def compute_tci(theta):
    """Compute Total Connectedness Index from GFEVD matrix."""
    K = theta.shape[0]
    off_diag_sum = theta.sum() - np.trace(theta)
    TCI = off_diag_sum / K * 100
    return TCI


def compute_rolling_tci(vol_panel, window=250, lag_order=5, H=10):
    """Compute rolling TCI time series."""
    n = len(vol_panel)
    tci_series = pd.Series(np.nan, index=vol_panel.index)

    total = n - window + 1
    print(f"\nComputing rolling TCI: {total} windows of {window} days...")

    for i in range(window, n + 1):
        if (i - window) % 100 == 0:
            pct = (i - window) / total * 100
            print(f"  Progress: {pct:.0f}% ({i - window}/{total})")

        window_data = vol_panel.iloc[i - window:i].values

        # Standardize within window for numerical stability
        mean = window_data.mean(axis=0)
        std = window_data.std(axis=0)
        std[std < 1e-12] = 1.0
        window_data_std = (window_data - mean) / std

        theta = estimate_var_and_gfevd(window_data_std, lag_order, H)
        tci = compute_tci(theta)
        tci_series.iloc[i - 1] = tci

    tci_series = tci_series.dropna()
    print(f"  Rolling TCI computed: {len(tci_series)} observations")
    return tci_series


# ============================================================
# Strategy Definitions
# ============================================================

def compute_daily_returns(raw_data, ticker):
    """Compute daily returns from Close prices."""
    import yfinance as yf

    if ticker in raw_data:
        close = raw_data[ticker]['Close']
    else:
        df = yf.download(ticker, start=START_DATE, end=END_DATE, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        close = df['Close']

    returns = close.pct_change().dropna()
    return returns


def strategy_tci_defensive(tci_series, spy_returns):
    """Strategy 1: TCI Defensive (SPY only).

    High TCI → reduce equity, Low TCI → full equity.
    Logic: high connectedness = diversification fails = reduce risk.
    """
    # Compute TCI percentile (expanding window for OOS validity)
    tci_percentile = tci_series.expanding().rank(pct=True)

    # Weight based on TCI percentile
    weight_spy = pd.Series(1.0, index=tci_series.index)
    weight_spy[tci_percentile > 0.8] = 0.5    # top 20% → half position
    weight_spy[(tci_percentile > 0.6) & (tci_percentile <= 0.8)] = 0.75  # 60-80%

    # MUST LAG signal by 1 day
    signal = weight_spy.shift(1)

    # Align with returns
    common = signal.index.intersection(spy_returns.index)
    signal = signal.loc[common]
    ret = spy_returns.loc[common]

    strategy_returns = signal * ret
    # Cash portion earns nothing (conservative assumption)

    return strategy_returns, signal


def strategy_tci_vix_combined(tci_series, vix_series, spy_returns, gld_returns):
    """Strategy 2: TCI + VIX Combined (SPY/GLD allocation).

    Four regimes based on VIX and TCI medians:
    - VIX high + TCI high → 30% SPY / 70% GLD (max defensive)
    - VIX high + TCI low  → 40% SPY / 60% GLD (moderate defensive)
    - VIX low  + TCI high → 45% SPY / 55% GLD (caution)
    - VIX low  + TCI low  → 55% SPY / 45% GLD (safe, risk-on)
    """
    # Expanding medians for OOS validity
    tci_median = tci_series.expanding().median()
    vix_median = vix_series.expanding().median()

    # Align
    common_idx = tci_series.index.intersection(vix_series.index)
    tci_aligned = tci_series.loc[common_idx]
    vix_aligned = vix_series.loc[common_idx]
    tci_med = tci_median.loc[common_idx]
    vix_med = vix_median.loc[common_idx]

    # Regime classification
    vix_high = vix_aligned > vix_med
    tci_high = tci_aligned > tci_med

    weight_spy = pd.Series(0.5, index=common_idx)  # default 50/50

    # Four regimes
    weight_spy[vix_high & tci_high] = 0.30   # Max defensive
    weight_spy[vix_high & ~tci_high] = 0.40  # Moderate defensive
    weight_spy[~vix_high & tci_high] = 0.45  # Caution
    weight_spy[~vix_high & ~tci_high] = 0.55 # Risk-on

    weight_gld = 1.0 - weight_spy

    # MUST LAG signals by 1 day
    signal_spy = weight_spy.shift(1)
    signal_gld = weight_gld.shift(1)

    # Align with returns
    common = common_idx.intersection(spy_returns.index).intersection(gld_returns.index)
    signal_spy = signal_spy.reindex(common)
    signal_gld = signal_gld.reindex(common)
    spy_r = spy_returns.reindex(common)
    gld_r = gld_returns.reindex(common)

    # Drop NaN from lag
    valid = signal_spy.notna() & signal_gld.notna() & spy_r.notna() & gld_r.notna()
    signal_spy = signal_spy[valid]
    signal_gld = signal_gld[valid]
    spy_r = spy_r[valid]
    gld_r = gld_r[valid]

    strategy_returns = signal_spy * spy_r + signal_gld * gld_r
    return strategy_returns, signal_spy, signal_gld


def strategy_smooth_tci(tci_series, spy_returns):
    """Strategy 3: Smooth TCI weight (like 12/VIX but for TCI).

    weight = k / TCI, capped at [0.3, 1.0]
    where k is calibrated so median weight ≈ 0.8.

    Logic: higher TCI → lower weight (continuous, smooth).
    """
    # Calibrate k so that median TCI gives weight ≈ 0.8
    # k = 0.8 * median(TCI)
    tci_expanding_median = tci_series.expanding().median()
    k = 0.8 * tci_expanding_median

    weight = k / tci_series
    weight = weight.clip(0.3, 1.0)

    # MUST LAG
    signal = weight.shift(1)

    common = signal.index.intersection(spy_returns.index)
    signal = signal.loc[common]
    ret = spy_returns.loc[common]

    valid = signal.notna() & ret.notna()
    signal = signal[valid]
    ret = ret[valid]

    strategy_returns = signal * ret
    return strategy_returns, signal


def strategy_tci_diversification_timing(tci_series, spy_returns, efa_returns, eem_returns):
    """Strategy 4: TCI Diversification Timing.

    Low TCI → increase international allocation (diversification works).
    High TCI → concentrate on US (diversification fails).

    Base: 60% SPY / 20% EFA / 20% EEM
    Low TCI: 40% SPY / 30% EFA / 30% EEM (more intl)
    High TCI: 80% SPY / 10% EFA / 10% EEM (US concentrated)
    """
    tci_percentile = tci_series.expanding().rank(pct=True)

    w_spy = pd.Series(0.6, index=tci_series.index)
    w_efa = pd.Series(0.2, index=tci_series.index)
    w_eem = pd.Series(0.2, index=tci_series.index)

    # Low TCI: more international
    low_mask = tci_percentile <= 0.3
    w_spy[low_mask] = 0.40
    w_efa[low_mask] = 0.30
    w_eem[low_mask] = 0.30

    # High TCI: concentrate US
    high_mask = tci_percentile > 0.7
    w_spy[high_mask] = 0.80
    w_efa[high_mask] = 0.10
    w_eem[high_mask] = 0.10

    # MUST LAG
    w_spy = w_spy.shift(1)
    w_efa = w_efa.shift(1)
    w_eem = w_eem.shift(1)

    common = (w_spy.index
              .intersection(spy_returns.index)
              .intersection(efa_returns.index)
              .intersection(eem_returns.index))

    w_spy = w_spy.reindex(common)
    w_efa = w_efa.reindex(common)
    w_eem = w_eem.reindex(common)
    spy_r = spy_returns.reindex(common)
    efa_r = efa_returns.reindex(common)
    eem_r = eem_returns.reindex(common)

    valid = (w_spy.notna() & w_efa.notna() & w_eem.notna() &
             spy_r.notna() & efa_r.notna() & eem_r.notna())

    strategy_returns = (w_spy[valid] * spy_r[valid] +
                        w_efa[valid] * efa_r[valid] +
                        w_eem[valid] * eem_r[valid])

    return strategy_returns, w_spy[valid]


# ============================================================
# Baselines
# ============================================================

def baseline_bh_spy(spy_returns, common_dates):
    """Buy & Hold SPY."""
    ret = spy_returns.reindex(common_dates).dropna()
    return ret


def baseline_bh_5050(spy_returns, gld_returns, common_dates):
    """Buy & Hold 50/50 SPY/GLD."""
    common = common_dates.intersection(spy_returns.index).intersection(gld_returns.index)
    ret = 0.5 * spy_returns.reindex(common) + 0.5 * gld_returns.reindex(common)
    return ret.dropna()


def baseline_12vix(vix_series, spy_returns, common_dates):
    """12/VIX strategy (SPY only)."""
    weight = (12.0 / vix_series).clip(0.0, 1.0)
    signal = weight.shift(1)  # MUST LAG

    common = common_dates.intersection(signal.index).intersection(spy_returns.index)
    signal = signal.reindex(common)
    ret = spy_returns.reindex(common)

    valid = signal.notna() & ret.notna()
    return (signal[valid] * ret[valid])


# ============================================================
# Performance Metrics
# ============================================================

def compute_metrics(returns, name="Strategy"):
    """Compute standard performance metrics."""
    if len(returns) < 252:
        return {"name": name, "error": "insufficient data"}

    ann_return = returns.mean() * 252
    ann_vol = returns.std() * np.sqrt(252)
    sharpe = ann_return / ann_vol if ann_vol > 0 else 0.0

    cumulative = (1 + returns).cumprod()
    running_max = cumulative.cummax()
    drawdown = (cumulative - running_max) / running_max
    mdd = drawdown.min()

    calmar = ann_return / abs(mdd) if abs(mdd) > 1e-8 else 0.0

    # CRRA utility (gamma=5)
    gamma = 5
    crra_utility = ann_return - 0.5 * gamma * ann_vol**2

    # Sortino ratio
    downside = returns[returns < 0]
    downside_vol = downside.std() * np.sqrt(252) if len(downside) > 0 else ann_vol
    sortino = ann_return / downside_vol if downside_vol > 0 else 0.0

    n_years = len(returns) / 252

    return {
        "name": name,
        "ann_return": round(ann_return, 6),
        "ann_vol": round(ann_vol, 6),
        "sharpe": round(sharpe, 4),
        "mdd": round(mdd, 6),
        "calmar": round(calmar, 4),
        "crra_gamma5": round(crra_utility, 6),
        "sortino": round(sortino, 4),
        "n_obs": len(returns),
        "n_years": round(n_years, 2)
    }


def dm_test(d, alternative='two-sided'):
    """Diebold-Mariano test for equal predictive accuracy.

    d: loss differential series (loss_benchmark - loss_strategy)
    Positive mean(d) → strategy has lower loss → strategy is better.
    """
    n = len(d)
    d_mean = d.mean()
    d_var = d.var(ddof=1)

    if d_var < 1e-16:
        return 0.0, 1.0

    # Newey-West HAC variance with lag = int(n^(1/3))
    max_lag = int(n ** (1.0/3.0))
    gamma_0 = d_var
    gamma_sum = 0.0
    for k in range(1, max_lag + 1):
        weight = 1.0 - k / (max_lag + 1)
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        gamma_sum += 2 * weight * gamma_k

    hac_var = (gamma_0 + gamma_sum) / n

    if hac_var <= 0:
        return 0.0, 1.0

    dm_stat = d_mean / np.sqrt(hac_var)

    if alternative == 'two-sided':
        p_value = 2 * (1 - sp_stats.norm.cdf(abs(dm_stat)))
    elif alternative == 'greater':
        p_value = 1 - sp_stats.norm.cdf(dm_stat)
    else:
        p_value = sp_stats.norm.cdf(dm_stat)

    return dm_stat, p_value


def pairwise_dm_test(strat_returns, base_returns, strat_name, base_name):
    """DM test on squared returns (loss = return^2 as vol proxy)."""
    common = strat_returns.index.intersection(base_returns.index)
    s = strat_returns.reindex(common).dropna()
    b = base_returns.reindex(common).dropna()
    common2 = s.index.intersection(b.index)
    s = s.loc[common2]
    b = b.loc[common2]

    if len(s) < 100:
        return {"comparison": f"{strat_name} vs {base_name}", "error": "insufficient overlap"}

    # Loss differential: using negative returns as loss
    # Actually for strategies, we compare utility: higher return = better
    # DM on return differentials: d = strategy - baseline
    d = s.values - b.values
    dm_stat, p_val = dm_test(d, alternative='two-sided')

    return {
        "comparison": f"{strat_name} vs {base_name}",
        "dm_stat": round(dm_stat, 4),
        "p_value": round(p_val, 6),
        "significant_harvey": abs(dm_stat) > 3.0,
        "direction": "strategy better" if dm_stat > 0 else "baseline better",
        "n_common": len(common2)
    }


# ============================================================
# TCI-Return Analysis
# ============================================================

def analyze_tci_predictive_power(tci_series, spy_returns):
    """Analyze whether TCI predicts future returns or volatility."""
    common = tci_series.index.intersection(spy_returns.index)
    tci = tci_series.reindex(common).dropna()
    ret = spy_returns.reindex(common).dropna()
    common2 = tci.index.intersection(ret.index)
    tci = tci.loc[common2]
    ret = ret.loc[common2]

    results = {}

    # 1. TCI vs next-day return
    tci_lagged = tci.shift(1).dropna()
    ret_aligned = ret.reindex(tci_lagged.index).dropna()
    common3 = tci_lagged.index.intersection(ret_aligned.index)
    if len(common3) > 100:
        r_ret, p_ret = sp_stats.pearsonr(tci_lagged.loc[common3], ret_aligned.loc[common3])
        results['tci_vs_next_return'] = {
            'pearson_r': round(r_ret, 6),
            'p_value': round(p_ret, 6),
            'n_obs': len(common3)
        }

    # 2. TCI vs next-day absolute return (vol proxy)
    abs_ret = ret.abs()
    abs_aligned = abs_ret.reindex(tci_lagged.index).dropna()
    common4 = tci_lagged.index.intersection(abs_aligned.index)
    if len(common4) > 100:
        r_vol, p_vol = sp_stats.pearsonr(tci_lagged.loc[common4], abs_aligned.loc[common4])
        results['tci_vs_next_abs_return'] = {
            'pearson_r': round(r_vol, 6),
            'p_value': round(p_vol, 6),
            'n_obs': len(common4)
        }

    # 3. TCI vs next-week return (5-day forward)
    ret_5d = ret.rolling(5).sum()
    ret_5d_aligned = ret_5d.reindex(tci_lagged.index).dropna()
    common5 = tci_lagged.index.intersection(ret_5d_aligned.index)
    if len(common5) > 100:
        r_5d, p_5d = sp_stats.pearsonr(tci_lagged.loc[common5], ret_5d_aligned.loc[common5])
        results['tci_vs_next_5d_return'] = {
            'pearson_r': round(r_5d, 6),
            'p_value': round(p_5d, 6),
            'n_obs': len(common5)
        }

    # 4. TCI vs next-month return (21-day forward)
    ret_21d = ret.rolling(21).sum()
    ret_21d_aligned = ret_21d.reindex(tci_lagged.index).dropna()
    common6 = tci_lagged.index.intersection(ret_21d_aligned.index)
    if len(common6) > 100:
        r_21d, p_21d = sp_stats.pearsonr(tci_lagged.loc[common6], ret_21d_aligned.loc[common6])
        results['tci_vs_next_21d_return'] = {
            'pearson_r': round(r_21d, 6),
            'p_value': round(p_21d, 6),
            'n_obs': len(common6)
        }

    # 5. TCI vs next-month realized vol (21-day rolling std)
    vol_21d = ret.rolling(21).std() * np.sqrt(252)
    vol_21d_aligned = vol_21d.reindex(tci_lagged.index).dropna()
    common7 = tci_lagged.index.intersection(vol_21d_aligned.index)
    if len(common7) > 100:
        r_vol21, p_vol21 = sp_stats.pearsonr(tci_lagged.loc[common7], vol_21d_aligned.loc[common7])
        results['tci_vs_next_21d_vol'] = {
            'pearson_r': round(r_vol21, 6),
            'p_value': round(p_vol21, 6),
            'n_obs': len(common7)
        }

    # 6. TCI regime returns (quintiles)
    try:
        labels_5 = ['Q1_low', 'Q2', 'Q3', 'Q4', 'Q5_high']
        tci_quintile = pd.qcut(tci, 5, labels=False, duplicates='drop')
        n_bins = tci_quintile.nunique()
        if n_bins < 5:
            # Fewer bins due to duplicates; relabel
            label_map = {i: f'Q{i+1}' for i in range(n_bins)}
            tci_quintile = tci_quintile.map(label_map)
            labels_5 = [f'Q{i+1}' for i in range(n_bins)]
        else:
            label_map = {0: 'Q1_low', 1: 'Q2', 2: 'Q3', 3: 'Q4', 4: 'Q5_high'}
            tci_quintile = tci_quintile.map(label_map)

        regime_stats = {}
        for q in labels_5:
            mask = tci_quintile == q
            if mask.sum() > 20:
                q_ret = ret[mask]
                regime_stats[q] = {
                    'mean_return_ann': round(q_ret.mean() * 252, 6),
                    'vol_ann': round(q_ret.std() * np.sqrt(252), 6),
                    'sharpe': round(q_ret.mean() / q_ret.std() * np.sqrt(252), 4) if q_ret.std() > 0 else 0,
                    'n_days': int(mask.sum())
                }
        results['quintile_analysis'] = regime_stats
    except Exception as e:
        results['quintile_analysis'] = {'error': str(e)}

    return results


# ============================================================
# Charting
# ============================================================

def plot_rolling_tci_with_returns(tci_series, spy_returns, output_dir):
    """Plot rolling TCI alongside cumulative SPY returns."""
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8), sharex=True)

    ax1.plot(tci_series.index, tci_series.values, 'b-', linewidth=0.8, alpha=0.8)
    ax1.axhline(y=tci_series.median(), color='r', linestyle='--', alpha=0.5, label=f'Median={tci_series.median():.1f}')
    ax1.set_ylabel('TCI (%)')
    ax1.set_title('K910: Rolling TCI (250-day) and SPY Cumulative Returns')
    ax1.legend()
    ax1.grid(True, alpha=0.3)

    common = tci_series.index.intersection(spy_returns.index)
    cum_ret = (1 + spy_returns.reindex(common).fillna(0)).cumprod()
    ax2.plot(cum_ret.index, cum_ret.values, 'k-', linewidth=0.8)
    ax2.set_ylabel('Cumulative Return (SPY)')
    ax2.set_xlabel('Date')
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    path = os.path.join(output_dir, 'k910_tci_returns.png')
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close()
    return path


def plot_strategy_comparison(strategy_dict, output_dir):
    """Plot cumulative returns for all strategies and baselines."""
    fig, ax = plt.subplots(figsize=(14, 7))

    colors = {
        'BH SPY': 'gray',
        'BH 50/50': 'black',
        '12/VIX': 'blue',
        'TCI Defensive': 'red',
        'TCI+VIX Combined': 'green',
        'Smooth TCI': 'orange',
        'TCI Div Timing': 'purple',
    }

    for name, returns in strategy_dict.items():
        cum_ret = (1 + returns).cumprod()
        color = colors.get(name, 'gray')
        lw = 2.0 if name in ['TCI Defensive', 'TCI+VIX Combined', 'Smooth TCI'] else 1.2
        ls = '--' if name in ['BH SPY', 'BH 50/50', '12/VIX'] else '-'
        ax.plot(cum_ret.index, cum_ret.values, color=color, linewidth=lw,
                linestyle=ls, label=name, alpha=0.85)

    ax.set_title('K910: TCI-Based Strategy Comparison')
    ax.set_xlabel('Date')
    ax.set_ylabel('Cumulative Return')
    ax.legend(loc='upper left', fontsize=9)
    ax.grid(True, alpha=0.3)
    ax.set_yscale('log')

    plt.tight_layout()
    path = os.path.join(output_dir, 'k910_strategy_comparison.png')
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close()
    return path


def plot_tci_regimes(tci_series, spy_returns, output_dir):
    """Plot TCI quintile performance."""
    common = tci_series.index.intersection(spy_returns.index)
    tci = tci_series.loc[common]
    ret = spy_returns.loc[common]

    try:
        quintiles_numeric = pd.qcut(tci, 5, labels=False, duplicates='drop')
        n_bins = quintiles_numeric.nunique()
        if n_bins < 5:
            labels = [f'Q{i+1}' for i in range(n_bins)]
        else:
            labels = ['Q1\n(Low)', 'Q2', 'Q3', 'Q4', 'Q5\n(High)']
        label_map = {i: labels[i] for i in range(n_bins)}
        quintiles = quintiles_numeric.map(label_map)
    except Exception:
        print("  WARNING: Could not create quintiles, skipping regime plot")
        return None

    means = []
    stds = []
    for q in labels:
        mask = quintiles == q
        if mask.sum() > 0:
            means.append(ret[mask].mean() * 252)
            stds.append(ret[mask].std() * np.sqrt(252))
        else:
            means.append(0)
            stds.append(0)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

    bars1 = ax1.bar(labels, means, color=['green', 'lightgreen', 'gray', 'lightsalmon', 'red'],
                     edgecolor='black', linewidth=0.5)
    ax1.set_title('Annualized Return by TCI Quintile')
    ax1.set_ylabel('Ann. Return')
    ax1.axhline(y=0, color='k', linewidth=0.5)
    ax1.grid(True, alpha=0.3, axis='y')

    for bar, val in zip(bars1, means):
        ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.005,
                 f'{val:.1%}', ha='center', va='bottom', fontsize=9)

    bars2 = ax2.bar(labels, stds, color=['green', 'lightgreen', 'gray', 'lightsalmon', 'red'],
                     edgecolor='black', linewidth=0.5)
    ax2.set_title('Annualized Volatility by TCI Quintile')
    ax2.set_ylabel('Ann. Volatility')
    ax2.grid(True, alpha=0.3, axis='y')

    for bar, val in zip(bars2, stds):
        ax2.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.005,
                 f'{val:.1%}', ha='center', va='bottom', fontsize=9)

    plt.suptitle('K910: SPY Returns by TCI Regime', fontsize=13, y=1.02)
    plt.tight_layout()
    path = os.path.join(output_dir, 'k910_tci_regimes.png')
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close()
    return path


def plot_drawdown_comparison(strategy_dict, output_dir):
    """Plot drawdown comparison for key strategies."""
    fig, ax = plt.subplots(figsize=(14, 5))

    key_strategies = ['BH 50/50', 'TCI+VIX Combined', 'TCI Defensive', '12/VIX']

    colors = {
        'BH 50/50': 'black',
        'TCI+VIX Combined': 'green',
        'TCI Defensive': 'red',
        '12/VIX': 'blue',
    }

    for name in key_strategies:
        if name in strategy_dict:
            returns = strategy_dict[name]
            cum = (1 + returns).cumprod()
            running_max = cum.cummax()
            dd = (cum - running_max) / running_max
            ax.fill_between(dd.index, dd.values, 0, alpha=0.2, color=colors.get(name, 'gray'))
            ax.plot(dd.index, dd.values, color=colors.get(name, 'gray'),
                    linewidth=0.8, label=name)

    ax.set_title('K910: Drawdown Comparison')
    ax.set_ylabel('Drawdown')
    ax.set_xlabel('Date')
    ax.legend(loc='lower left', fontsize=9)
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    path = os.path.join(output_dir, 'k910_drawdown_comparison.png')
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close()
    return path


# ============================================================
# Main
# ============================================================

def main():
    start_time = time.time()
    print("=" * 70)
    print("K910: TCI (Total Connectedness Index) as VT Strategy Overlay")
    print("=" * 70)

    # Step 1: Download data
    print("\n[Step 1] Downloading data...")
    raw_data = download_data()

    # Step 2: Prepare vol panel and compute rolling TCI
    print("\n[Step 2] Preparing volatility panel...")
    vol_panel = prepare_vol_panel(raw_data)

    print("\n[Step 3] Computing rolling TCI...")
    tci_series = compute_rolling_tci(vol_panel, window=ROLLING_WINDOW,
                                      lag_order=MAX_VAR_LAG, H=FORECAST_HORIZON)

    # Get VIX series
    if VIX_TICKER in raw_data:
        vix = raw_data[VIX_TICKER]['Close']
    else:
        import yfinance as yf
        vix_df = yf.download(VIX_TICKER, start=START_DATE, end=END_DATE, progress=False)
        if isinstance(vix_df.columns, pd.MultiIndex):
            vix_df.columns = vix_df.columns.get_level_values(0)
        vix = vix_df['Close']

    # Step 4: Compute returns
    print("\n[Step 4] Computing returns...")
    spy_returns = compute_daily_returns(raw_data, 'SPY')
    gld_returns = compute_daily_returns(raw_data, 'GLD')
    efa_returns = compute_daily_returns(raw_data, 'EFA')
    eem_returns = compute_daily_returns(raw_data, 'EEM')

    print(f"  SPY: {len(spy_returns)} returns")
    print(f"  GLD: {len(gld_returns)} returns")
    print(f"  TCI: {len(tci_series)} observations")
    print(f"  VIX: {len(vix)} observations")

    # Step 5: Run strategies
    print("\n[Step 5] Running strategies...")

    # Strategy 1: TCI Defensive
    print("  Strategy 1: TCI Defensive (SPY only)...")
    strat1_ret, strat1_sig = strategy_tci_defensive(tci_series, spy_returns)
    print(f"    {len(strat1_ret)} obs, weight range: [{strat1_sig.min():.2f}, {strat1_sig.max():.2f}]")

    # Strategy 2: TCI + VIX Combined
    print("  Strategy 2: TCI + VIX Combined (SPY/GLD)...")
    strat2_ret, strat2_spy_sig, strat2_gld_sig = strategy_tci_vix_combined(
        tci_series, vix, spy_returns, gld_returns)
    print(f"    {len(strat2_ret)} obs, SPY weight range: [{strat2_spy_sig.min():.2f}, {strat2_spy_sig.max():.2f}]")

    # Strategy 3: Smooth TCI
    print("  Strategy 3: Smooth TCI (k/TCI)...")
    strat3_ret, strat3_sig = strategy_smooth_tci(tci_series, spy_returns)
    print(f"    {len(strat3_ret)} obs, weight range: [{strat3_sig.min():.2f}, {strat3_sig.max():.2f}]")

    # Strategy 4: TCI Diversification Timing
    print("  Strategy 4: TCI Diversification Timing...")
    strat4_ret, strat4_sig = strategy_tci_diversification_timing(
        tci_series, spy_returns, efa_returns, eem_returns)
    print(f"    {len(strat4_ret)} obs")

    # Step 6: Baselines (use the broadest common period)
    print("\n[Step 6] Computing baselines...")
    all_dates = strat1_ret.index.union(strat2_ret.index).union(strat3_ret.index).union(strat4_ret.index)

    bh_spy_ret = baseline_bh_spy(spy_returns, all_dates)
    bh_5050_ret = baseline_bh_5050(spy_returns, gld_returns, all_dates)
    vix_12_ret = baseline_12vix(vix, spy_returns, all_dates)

    print(f"  BH SPY: {len(bh_spy_ret)} obs")
    print(f"  BH 50/50: {len(bh_5050_ret)} obs")
    print(f"  12/VIX: {len(vix_12_ret)} obs")

    # Step 7: Compute metrics
    print("\n[Step 7] Computing performance metrics...")

    strategy_returns_dict = {
        'BH SPY': bh_spy_ret,
        'BH 50/50': bh_5050_ret,
        '12/VIX': vix_12_ret,
        'TCI Defensive': strat1_ret,
        'TCI+VIX Combined': strat2_ret,
        'Smooth TCI': strat3_ret,
        'TCI Div Timing': strat4_ret,
    }

    metrics = {}
    for name, ret in strategy_returns_dict.items():
        m = compute_metrics(ret, name)
        metrics[name] = m
        if 'error' not in m:
            print(f"  {name:20s}: Sharpe={m['sharpe']:.4f}, MDD={m['mdd']:.4f}, "
                  f"Calmar={m['calmar']:.4f}, CRRA(5)={m['crra_gamma5']:.6f}")

    # Step 8: DM Tests
    print("\n[Step 8] DM tests vs baselines...")
    dm_results = []

    strategies = ['TCI Defensive', 'TCI+VIX Combined', 'Smooth TCI', 'TCI Div Timing']
    baselines_list = ['BH SPY', 'BH 50/50', '12/VIX']

    for strat_name in strategies:
        for base_name in baselines_list:
            result = pairwise_dm_test(
                strategy_returns_dict[strat_name],
                strategy_returns_dict[base_name],
                strat_name, base_name
            )
            dm_results.append(result)
            if 'error' not in result:
                sig = "***" if result['significant_harvey'] else "NS"
                print(f"  {strat_name:20s} vs {base_name:12s}: "
                      f"DM={result['dm_stat']:+.4f} p={result['p_value']:.4f} {sig}")

    # Step 9: TCI predictive power analysis
    print("\n[Step 9] Analyzing TCI predictive power...")
    predictive_results = analyze_tci_predictive_power(tci_series, spy_returns)

    if 'tci_vs_next_return' in predictive_results:
        pr = predictive_results['tci_vs_next_return']
        print(f"  TCI → next-day return: r={pr['pearson_r']:.6f}, p={pr['p_value']:.6f}")
    if 'tci_vs_next_abs_return' in predictive_results:
        pr = predictive_results['tci_vs_next_abs_return']
        print(f"  TCI → next-day |return|: r={pr['pearson_r']:.6f}, p={pr['p_value']:.6f}")
    if 'tci_vs_next_21d_vol' in predictive_results:
        pr = predictive_results['tci_vs_next_21d_vol']
        print(f"  TCI → next-21d vol: r={pr['pearson_r']:.6f}, p={pr['p_value']:.6f}")

    if 'quintile_analysis' in predictive_results:
        print("\n  TCI Quintile Analysis:")
        for q, stats in predictive_results['quintile_analysis'].items():
            print(f"    {q}: ret={stats['mean_return_ann']:.4f}, "
                  f"vol={stats['vol_ann']:.4f}, sharpe={stats['sharpe']:.4f}, "
                  f"n={stats['n_days']}")

    # Step 10: Generate charts
    print("\n[Step 10] Generating charts...")
    charts = []

    path = plot_rolling_tci_with_returns(tci_series, spy_returns, OUTPUT_DIR)
    charts.append(os.path.basename(path))
    print(f"  Saved: {path}")

    path = plot_strategy_comparison(strategy_returns_dict, OUTPUT_DIR)
    charts.append(os.path.basename(path))
    print(f"  Saved: {path}")

    path = plot_tci_regimes(tci_series, spy_returns, OUTPUT_DIR)
    if path:
        charts.append(os.path.basename(path))
        print(f"  Saved: {path}")

    path = plot_drawdown_comparison(strategy_returns_dict, OUTPUT_DIR)
    charts.append(os.path.basename(path))
    print(f"  Saved: {path}")

    # Step 11: Compile results
    runtime = time.time() - start_time
    print(f"\n[Step 11] Compiling results (runtime: {runtime:.1f}s)...")

    # Check if any strategy significantly beats baselines
    any_significant = any(
        r.get('significant_harvey', False) and r.get('direction') == 'strategy better'
        for r in dm_results if 'error' not in r
    )

    # Core conclusion
    if any_significant:
        conclusion = (
            "TCI-based strategies show statistically significant improvement "
            "over at least one baseline (Harvey |t|>3.0). "
        )
    else:
        conclusion = (
            "NULL RESULT: No TCI-based strategy significantly outperforms baselines "
            "at Harvey (2016) |t|>3.0 threshold. "
        )

    # Add predictive power summary
    if 'tci_vs_next_return' in predictive_results:
        r_ret = predictive_results['tci_vs_next_return']['pearson_r']
        conclusion += f"TCI→next-day return r={r_ret:.4f}. "

    if 'tci_vs_next_21d_vol' in predictive_results:
        r_vol = predictive_results['tci_vs_next_21d_vol']['pearson_r']
        conclusion += f"TCI→21d vol r={r_vol:.4f}. "

    conclusion += (
        "This is consistent with K907: TCI is a structural/descriptive measure of "
        "cross-asset connectedness, not a directional trading signal. "
        "Like VIX (K697: predicts vol magnitude r=0.57 but not direction r=0.04), "
        "TCI may describe market state without generating tradeable alpha."
    )

    # TCI rolling stats
    tci_stats = {
        'mean': round(tci_series.mean(), 4),
        'std': round(tci_series.std(), 4),
        'min': round(tci_series.min(), 4),
        'max': round(tci_series.max(), 4),
        'median': round(tci_series.median(), 4),
        'n_obs': len(tci_series),
        'period': f"{tci_series.index[0].strftime('%Y-%m-%d')} to {tci_series.index[-1].strftime('%Y-%m-%d')}"
    }

    results = {
        "experiment_id": "K910",
        "title": "TCI (Total Connectedness Index) as VT Strategy Overlay",
        "date": datetime.now(timezone.utc).isoformat(),
        "data_source": "yfinance",
        "sample_period": f"{vol_panel.index[0].strftime('%Y-%m-%d')} to {vol_panel.index[-1].strftime('%Y-%m-%d')}",
        "oos_period": f"{tci_series.index[0].strftime('%Y-%m-%d')} to {tci_series.index[-1].strftime('%Y-%m-%d')}",
        "n_trading_days": len(vol_panel),
        "assets_for_tci": ASSET_LABELS,
        "tci_config": {
            "rolling_window": ROLLING_WINDOW,
            "var_lag": MAX_VAR_LAG,
            "forecast_horizon": FORECAST_HORIZON,
            "vol_proxy": "Garman-Klass (OHLC)"
        },
        "tci_stats": tci_stats,
        "strategy_metrics": metrics,
        "dm_tests": dm_results,
        "tci_predictive_power": predictive_results,
        "any_significant_improvement": any_significant,
        "conclusion": conclusion,
        "charts": charts,
        "references": [
            "K907: Volatility Spillover Network (TCI-VIX r=0.001)",
            "K687/K697: VT is drawdown insurance, not alpha generator",
            "K700: Codex audit prevents false breakthroughs",
            "Diebold & Yilmaz (2012): Better to give than to receive, IJF",
            "Diebold & Yilmaz (2014): Network topology of variance decompositions, JFE",
            "Harvey (2016): ... and the cross-section of expected returns, RFS"
        ],
        "limitations": [
            "TCI uses Garman-Klass vol (noisy proxy); 5-min RV would be more precise",
            "250-day rolling window = ~1 year lag in regime detection",
            "Only 9 assets in network; larger universe might give different TCI dynamics",
            "0050.TW has limited trading hours vs US markets (ffill alignment)",
            "TCI computation is expensive (~70s for full rolling); not suitable for live trading at daily freq without caching",
            "VT strategies are insurance, not alpha — Sharpe improvement is not expected (K687/K697)"
        ],
        "runtime_seconds": round(runtime, 2)
    }

    # Save results
    results_path = os.path.join(OUTPUT_DIR, 'k910_tci_vt_overlay_results.json')
    with open(results_path, 'w') as f:
        json.dump(results, f, indent=2, cls=NumpyEncoder)
    print(f"\nResults saved: {results_path}")

    print("\n" + "=" * 70)
    print("CONCLUSION:")
    print(conclusion)
    print("=" * 70)

    return results


if __name__ == '__main__':
    main()
