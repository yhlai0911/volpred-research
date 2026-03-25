#!/usr/bin/env python3
"""
K413: ETF Fund Flows and Price Discovery — Does Creation/Redemption Drive Returns?
==================================================================================

Completely new direction: ETF STRUCTURE analysis (no VIX, no VT, no 50/50).

Research Questions:
1. Does abnormal ETF volume predict next-day returns?
2. Is there up-volume vs down-volume asymmetry in predictive power?
3. Do cross-ETF volume correlations reveal information flows?
4. What happens at extreme volume events (top 1%)?
5. Does volume divergence between risk-on/risk-off ETFs predict returns?

Data: yfinance — SPY, GLD, TLT, EEM, IWM daily OHLCV, 2005-2024.
"""

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from datetime import datetime
import json
import warnings
warnings.filterwarnings('ignore')

# ============================================================
# DATA COLLECTION
# ============================================================

def fetch_data():
    """Fetch daily OHLCV for 5 ETFs from yfinance."""
    tickers = ['SPY', 'GLD', 'TLT', 'EEM', 'IWM']
    start = '2005-01-01'
    end = '2024-12-31'

    data = {}
    for t in tickers:
        print(f"  Fetching {t}...")
        df = yf.download(t, start=start, end=end, progress=False, auto_adjust=True)
        if df.empty:
            print(f"  WARNING: No data for {t}")
            continue
        # Flatten MultiIndex columns if present
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        data[t] = df
        print(f"  {t}: {len(df)} days, {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")

    return data


def prepare_features(data):
    """Compute volume features and returns for each ETF."""
    features = {}

    for ticker, df in data.items():
        feat = pd.DataFrame(index=df.index)

        # Daily returns
        feat['return'] = df['Close'].pct_change()

        # Volume
        feat['volume'] = df['Volume']

        # Volume moving averages
        feat['vol_ma20'] = df['Volume'].rolling(20).mean()
        feat['vol_ma50'] = df['Volume'].rolling(50).mean()

        # Volume ratio (current / 20d MA)
        feat['vol_ratio'] = df['Volume'] / feat['vol_ma20']

        # Log volume change
        feat['log_vol_change'] = np.log(df['Volume'] / df['Volume'].shift(1))

        # Up-volume and down-volume
        feat['up_volume'] = df['Volume'] * (feat['return'] > 0).astype(float)
        feat['down_volume'] = df['Volume'] * (feat['return'] <= 0).astype(float)

        # Up/Down volume ratio (20d)
        feat['up_vol_ma20'] = feat['up_volume'].rolling(20).mean()
        feat['down_vol_ma20'] = feat['down_volume'].rolling(20).mean()
        feat['updown_vol_ratio'] = feat['up_vol_ma20'] / feat['down_vol_ma20'].replace(0, np.nan)

        # Dollar volume (proxy for fund flows)
        feat['dollar_volume'] = df['Close'] * df['Volume']
        feat['dollar_vol_ma20'] = feat['dollar_volume'].rolling(20).mean()
        feat['dollar_vol_ratio'] = feat['dollar_volume'] / feat['dollar_vol_ma20']

        # Realized volatility (20d)
        feat['rvol_20d'] = feat['return'].rolling(20).std() * np.sqrt(252)

        # Forward returns (for prediction)
        feat['fwd_1d'] = feat['return'].shift(-1)
        feat['fwd_5d'] = feat['return'].shift(-1).rolling(5).sum().shift(-4)
        feat['fwd_20d'] = feat['return'].shift(-1).rolling(20).sum().shift(-19)

        # Volume percentile (expanding)
        feat['vol_pctile'] = feat['volume'].expanding(min_periods=252).rank(pct=True)

        features[ticker] = feat.dropna(subset=['vol_ratio', 'fwd_1d'])

    return features


# ============================================================
# ANALYSIS 1: Volume Anomaly Detection
# ============================================================

def analysis_volume_anomaly(features):
    """When volume > 2x average, what happens to returns?"""
    print("\n" + "="*70)
    print("ANALYSIS 1: Volume Anomaly Detection")
    print("="*70)
    print("Question: When volume > 2x the 20-day average, what happens to returns?\n")

    results = {}

    for ticker, feat in features.items():
        normal = feat[feat['vol_ratio'] <= 2.0]
        anomaly = feat[feat['vol_ratio'] > 2.0]

        if len(anomaly) < 10:
            print(f"  {ticker}: Only {len(anomaly)} anomaly days, skipping")
            continue

        # Compare forward returns
        normal_fwd1 = normal['fwd_1d'].dropna()
        anomaly_fwd1 = anomaly['fwd_1d'].dropna()
        normal_fwd5 = normal['fwd_5d'].dropna()
        anomaly_fwd5 = anomaly['fwd_5d'].dropna()

        # Welch t-test
        t1, p1 = stats.ttest_ind(anomaly_fwd1, normal_fwd1, equal_var=False)
        t5, p5 = stats.ttest_ind(anomaly_fwd5, normal_fwd5, equal_var=False)

        results[ticker] = {
            'n_anomaly': len(anomaly),
            'n_normal': len(normal),
            'pct_anomaly': len(anomaly) / (len(anomaly) + len(normal)) * 100,
            'anomaly_fwd1_mean': anomaly_fwd1.mean() * 100,
            'normal_fwd1_mean': normal_fwd1.mean() * 100,
            'anomaly_fwd5_mean': anomaly_fwd5.mean() * 100,
            'normal_fwd5_mean': normal_fwd5.mean() * 100,
            't_stat_1d': t1,
            'p_value_1d': p1,
            't_stat_5d': t5,
            'p_value_5d': p5,
        }

        # Also check: same-day returns on anomaly days
        anomaly_same = anomaly['return'].dropna()
        normal_same = normal['return'].dropna()
        t_same, p_same = stats.ttest_ind(anomaly_same, normal_same, equal_var=False)
        results[ticker]['anomaly_sameday_mean'] = anomaly_same.mean() * 100
        results[ticker]['normal_sameday_mean'] = normal_same.mean() * 100
        results[ticker]['t_stat_sameday'] = t_same
        results[ticker]['p_value_sameday'] = p_same

        print(f"  {ticker}:")
        print(f"    Anomaly days: {len(anomaly)} ({results[ticker]['pct_anomaly']:.1f}%)")
        print(f"    Same-day return:  Anomaly={anomaly_same.mean()*100:.3f}% vs Normal={normal_same.mean()*100:.3f}%  (t={t_same:.2f}, p={p_same:.4f})")
        print(f"    Fwd 1-day return: Anomaly={anomaly_fwd1.mean()*100:.3f}% vs Normal={normal_fwd1.mean()*100:.3f}%  (t={t1:.2f}, p={p1:.4f})")
        print(f"    Fwd 5-day return: Anomaly={anomaly_fwd5.mean()*100:.3f}% vs Normal={normal_fwd5.mean()*100:.3f}%  (t={t5:.2f}, p={p5:.4f})")
        print()

    return results


# ============================================================
# ANALYSIS 2: Volume-Return Lead-Lag
# ============================================================

def analysis_volume_return_leadlag(features):
    """Does abnormal volume predict next-day returns?"""
    print("\n" + "="*70)
    print("ANALYSIS 2: Volume-Return Lead-Lag Analysis")
    print("="*70)
    print("Question: Does volume ratio predict forward returns? Up vs Down volume asymmetry?\n")

    results = {}

    for ticker, feat in features.items():
        f = feat.dropna(subset=['vol_ratio', 'fwd_1d', 'fwd_5d'])

        # Correlation: vol_ratio vs forward returns
        corr_1d, p_1d = stats.spearmanr(f['vol_ratio'], f['fwd_1d'])
        corr_5d, p_5d = stats.spearmanr(f['vol_ratio'], f['fwd_5d'])

        # Up/Down volume ratio vs forward returns
        f2 = f.dropna(subset=['updown_vol_ratio'])
        corr_ud_1d, p_ud_1d = stats.spearmanr(f2['updown_vol_ratio'], f2['fwd_1d'])
        corr_ud_5d, p_ud_5d = stats.spearmanr(f2['updown_vol_ratio'], f2['fwd_5d'])

        # Quintile analysis: sort by vol_ratio, check returns in each quintile
        f['vol_quintile'] = pd.qcut(f['vol_ratio'], 5, labels=False, duplicates='drop')
        quintile_returns = f.groupby('vol_quintile')['fwd_1d'].agg(['mean', 'std', 'count'])
        quintile_returns['mean'] *= 100
        quintile_returns['std'] *= 100

        # Monotonicity test: Jonckheere-Terpstra style — just check Q5-Q1 spread
        q1_ret = f[f['vol_quintile'] == 0]['fwd_1d']
        q5_ret = f[f['vol_quintile'] == 4]['fwd_1d']
        t_q5q1, p_q5q1 = stats.ttest_ind(q5_ret, q1_ret, equal_var=False)
        spread_q5q1 = (q5_ret.mean() - q1_ret.mean()) * 100

        results[ticker] = {
            'spearman_volratio_fwd1d': corr_1d,
            'p_volratio_fwd1d': p_1d,
            'spearman_volratio_fwd5d': corr_5d,
            'p_volratio_fwd5d': p_5d,
            'spearman_udvolratio_fwd1d': corr_ud_1d,
            'p_udvolratio_fwd1d': p_ud_1d,
            'spearman_udvolratio_fwd5d': corr_ud_5d,
            'p_udvolratio_fwd5d': p_ud_5d,
            'quintile_means_bps': quintile_returns['mean'].to_dict(),
            'q5_minus_q1_bps': spread_q5q1,
            't_q5q1': t_q5q1,
            'p_q5q1': p_q5q1,
            'n_obs': len(f),
        }

        print(f"  {ticker} (n={len(f)}):")
        print(f"    Vol ratio → Fwd 1d: Spearman r={corr_1d:.4f} (p={p_1d:.4f})")
        print(f"    Vol ratio → Fwd 5d: Spearman r={corr_5d:.4f} (p={p_5d:.4f})")
        print(f"    Up/Down vol ratio → Fwd 1d: Spearman r={corr_ud_1d:.4f} (p={p_ud_1d:.4f})")
        print(f"    Up/Down vol ratio → Fwd 5d: Spearman r={corr_ud_5d:.4f} (p={p_ud_5d:.4f})")
        print(f"    Quintile Fwd-1d returns (bps):")
        for q in range(5):
            if q in quintile_returns.index:
                row = quintile_returns.loc[q]
                print(f"      Q{q+1} (lowest vol → highest vol): {row['mean']:.3f}% (n={int(row['count'])})")
        print(f"    Q5-Q1 spread: {spread_q5q1:.3f}% (t={t_q5q1:.2f}, p={p_q5q1:.4f})")
        print()

    return results


# ============================================================
# ANALYSIS 3: Cross-ETF Volume Correlation
# ============================================================

def analysis_cross_etf_volume(features):
    """Cross-ETF volume correlations and divergence signals."""
    print("\n" + "="*70)
    print("ANALYSIS 3: Cross-ETF Volume Correlation & Divergence")
    print("="*70)
    print("Question: Are volume spikes synchronized? Does divergence predict returns?\n")

    tickers = list(features.keys())
    n = len(tickers)

    # Build volume ratio matrix
    vol_ratios = pd.DataFrame()
    returns_df = pd.DataFrame()
    for t in tickers:
        vol_ratios[t] = features[t]['vol_ratio']
        returns_df[t] = features[t]['fwd_1d']

    common_idx = vol_ratios.dropna().index.intersection(returns_df.dropna().index)
    vol_ratios = vol_ratios.loc[common_idx]
    returns_df = returns_df.loc[common_idx]

    print(f"  Common observations: {len(common_idx)}")
    print()

    # 3a: Volume ratio correlation matrix
    print("  3a. Volume Ratio Correlation Matrix (Spearman):")
    corr_matrix = vol_ratios.rank().corr(method='pearson')  # rank corr = spearman
    print(corr_matrix.round(3).to_string())
    print()

    results = {
        'correlation_matrix': corr_matrix.to_dict(),
        'n_common': len(common_idx),
    }

    # 3b: Synchronized volume spikes
    # Define "spike" as vol_ratio > 1.5 for each ETF
    spike_threshold = 1.5
    spikes = (vol_ratios > spike_threshold).astype(int)

    print(f"  3b. Volume Spike Synchronization (threshold: vol_ratio > {spike_threshold}):")
    spike_counts = spikes.sum()
    for t in tickers:
        print(f"    {t}: {int(spike_counts[t])} spike days ({spike_counts[t]/len(spikes)*100:.1f}%)")

    # Co-spike frequency
    print("\n  Co-spike matrix (% of days both spike):")
    co_spike = pd.DataFrame(0.0, index=tickers, columns=tickers)
    for i, t1 in enumerate(tickers):
        for j, t2 in enumerate(tickers):
            both = ((spikes[t1] == 1) & (spikes[t2] == 1)).sum()
            co_spike.loc[t1, t2] = both / len(spikes) * 100
    print(co_spike.round(2).to_string())
    print()

    results['spike_counts'] = {t: int(spike_counts[t]) for t in tickers}
    results['co_spike_pct'] = co_spike.to_dict()

    # 3c: Volume divergence signal
    # High SPY volume + Low GLD volume → risk-on signal?
    # High GLD volume + Low SPY volume → risk-off signal?
    print("  3c. Volume Divergence Signals:")

    divergence_pairs = [
        ('SPY', 'GLD', 'risk-on (equity volume up, gold down)'),
        ('SPY', 'TLT', 'risk-on (equity volume up, bond down)'),
        ('EEM', 'TLT', 'EM risk-on (EM volume up, bond down)'),
    ]

    divergence_results = {}

    for high_t, low_t, label in divergence_pairs:
        if high_t not in vol_ratios.columns or low_t not in vol_ratios.columns:
            continue

        # Divergence: high_t vol_ratio > 1.5 AND low_t vol_ratio < 0.8
        divergence = (vol_ratios[high_t] > 1.5) & (vol_ratios[low_t] < 0.8)
        convergence = (vol_ratios[high_t] < 0.8) & (vol_ratios[low_t] > 1.5)
        neutral = ~divergence & ~convergence

        n_div = divergence.sum()
        n_conv = convergence.sum()

        if n_div < 10 or n_conv < 10:
            print(f"    {high_t}/{low_t} ({label}): insufficient divergence events (div={n_div}, conv={n_conv})")
            continue

        # Forward returns of SPY after divergence vs convergence
        spy_fwd = returns_df['SPY']
        div_ret = spy_fwd[divergence].dropna()
        conv_ret = spy_fwd[convergence].dropna()
        neut_ret = spy_fwd[neutral].dropna()

        t_dc, p_dc = stats.ttest_ind(div_ret, conv_ret, equal_var=False)

        divergence_results[f"{high_t}/{low_t}"] = {
            'label': label,
            'n_divergence': int(n_div),
            'n_convergence': int(n_conv),
            'div_spy_fwd1d_mean': div_ret.mean() * 100,
            'conv_spy_fwd1d_mean': conv_ret.mean() * 100,
            'neutral_spy_fwd1d_mean': neut_ret.mean() * 100,
            't_stat': t_dc,
            'p_value': p_dc,
        }

        print(f"    {high_t} high / {low_t} low ({label}):")
        print(f"      Divergence days: {n_div}, Convergence days: {n_conv}")
        print(f"      SPY fwd-1d after divergence: {div_ret.mean()*100:.3f}%")
        print(f"      SPY fwd-1d after convergence: {conv_ret.mean()*100:.3f}%")
        print(f"      SPY fwd-1d neutral: {neut_ret.mean()*100:.3f}%")
        print(f"      Diff t-stat: {t_dc:.2f}, p={p_dc:.4f}")
        print()

    results['divergence_signals'] = divergence_results
    return results


# ============================================================
# ANALYSIS 4: Volume at Extremes
# ============================================================

def analysis_volume_extremes(features):
    """Top 1% volume days: returns higher or lower? Mean reversion or continuation?"""
    print("\n" + "="*70)
    print("ANALYSIS 4: Volume at Extremes")
    print("="*70)
    print("Question: What happens after top/bottom 1% volume days?\n")

    results = {}

    for ticker, feat in features.items():
        f = feat.dropna(subset=['vol_pctile', 'fwd_1d', 'fwd_5d', 'fwd_20d'])

        # Extreme volume categories
        top1 = f[f['vol_pctile'] >= 0.99]
        top5 = f[(f['vol_pctile'] >= 0.95) & (f['vol_pctile'] < 0.99)]
        bottom5 = f[f['vol_pctile'] <= 0.05]
        middle = f[(f['vol_pctile'] > 0.25) & (f['vol_pctile'] < 0.75)]

        # Also split top1 into up-top1 and down-top1
        top1_up = top1[top1['return'] > 0]
        top1_down = top1[top1['return'] <= 0]

        def summarize(group, label):
            if len(group) < 5:
                return None
            return {
                'n': len(group),
                'fwd_1d_mean': group['fwd_1d'].mean() * 100,
                'fwd_5d_mean': group['fwd_5d'].mean() * 100,
                'fwd_20d_mean': group['fwd_20d'].mean() * 100,
                'fwd_1d_positive_pct': (group['fwd_1d'] > 0).mean() * 100,
                'same_day_return_mean': group['return'].mean() * 100,
            }

        ticker_results = {}
        for group, label in [(top1, 'top_1pct'), (top5, 'top_5pct'),
                              (bottom5, 'bottom_5pct'), (middle, 'middle_50pct'),
                              (top1_up, 'top1_up_day'), (top1_down, 'top1_down_day')]:
            s = summarize(group, label)
            if s is not None:
                ticker_results[label] = s

        results[ticker] = ticker_results

        # Statistical test: top1 vs middle fwd returns
        if len(top1) >= 5 and len(middle) >= 5:
            t1, p1 = stats.ttest_ind(top1['fwd_1d'], middle['fwd_1d'], equal_var=False)
            t5, p5 = stats.ttest_ind(top1['fwd_5d'], middle['fwd_5d'], equal_var=False)
            t20, p20 = stats.ttest_ind(top1['fwd_20d'], middle['fwd_20d'], equal_var=False)
            results[ticker]['tests_top1_vs_middle'] = {
                't_1d': t1, 'p_1d': p1,
                't_5d': t5, 'p_5d': p5,
                't_20d': t20, 'p_20d': p20,
            }

        print(f"  {ticker}:")
        for label, s in ticker_results.items():
            if 'n' not in s:
                continue
            print(f"    {label:20s}: n={s['n']:4d}  fwd1d={s['fwd_1d_mean']:+.3f}%  fwd5d={s['fwd_5d_mean']:+.3f}%  fwd20d={s['fwd_20d_mean']:+.3f}%  same_day={s['same_day_return_mean']:+.3f}%  fwd1d_win%={s['fwd_1d_positive_pct']:.1f}%")

        if 'tests_top1_vs_middle' in results[ticker]:
            t = results[ticker]['tests_top1_vs_middle']
            print(f"    Top1% vs Middle: fwd1d t={t['t_1d']:.2f}(p={t['p_1d']:.4f})  fwd5d t={t['t_5d']:.2f}(p={t['p_5d']:.4f})  fwd20d t={t['t_20d']:.2f}(p={t['p_20d']:.4f})")

        # Mean reversion vs continuation
        if len(top1) >= 5:
            # After extreme volume + negative return: do we get a bounce?
            n_down = len(top1_down)
            if n_down >= 5:
                bounce_rate = (top1_down['fwd_1d'] > 0).mean() * 100
                avg_bounce = top1_down['fwd_1d'].mean() * 100
                print(f"    After top1% volume DOWN day: bounce rate={bounce_rate:.1f}%, avg fwd1d={avg_bounce:+.3f}% (n={n_down})")

            n_up = len(top1_up)
            if n_up >= 5:
                continuation_rate = (top1_up['fwd_1d'] > 0).mean() * 100
                avg_cont = top1_up['fwd_1d'].mean() * 100
                print(f"    After top1% volume UP day:   continuation rate={continuation_rate:.1f}%, avg fwd1d={avg_cont:+.3f}% (n={n_up})")
        print()

    return results


# ============================================================
# ANALYSIS 5: Volume-Price Relationship Across Time
# ============================================================

def analysis_volume_price_dynamics(features):
    """Additional analysis: volume-price dynamics and information content."""
    print("\n" + "="*70)
    print("ANALYSIS 5: Volume-Price Dynamics & Information Content")
    print("="*70)
    print("Question: Does volume carry different information in different regimes?\n")

    results = {}

    for ticker, feat in features.items():
        f = feat.dropna(subset=['vol_ratio', 'rvol_20d', 'fwd_1d'])

        # Split into high/low volatility regimes
        vol_median = f['rvol_20d'].median()
        high_vol = f[f['rvol_20d'] > vol_median]
        low_vol = f[f['rvol_20d'] <= vol_median]

        # Volume-return correlation in each regime
        corr_hv, p_hv = stats.spearmanr(high_vol['vol_ratio'], high_vol['fwd_1d'])
        corr_lv, p_lv = stats.spearmanr(low_vol['vol_ratio'], low_vol['fwd_1d'])

        # Dollar volume ratio predictive power
        f2 = f.dropna(subset=['dollar_vol_ratio'])
        corr_dv, p_dv = stats.spearmanr(f2['dollar_vol_ratio'], f2['fwd_1d'])

        # Volume acceleration: change in volume ratio
        f['vol_ratio_change'] = f['vol_ratio'] - f['vol_ratio'].shift(1)
        f3 = f.dropna(subset=['vol_ratio_change', 'fwd_1d'])
        corr_acc, p_acc = stats.spearmanr(f3['vol_ratio_change'], f3['fwd_1d'])

        # OLS regression: fwd_1d ~ vol_ratio + return (controlling for momentum)
        from numpy.linalg import lstsq
        f4 = f.dropna(subset=['vol_ratio', 'return', 'fwd_1d'])
        X = np.column_stack([
            np.ones(len(f4)),
            f4['vol_ratio'].values,
            f4['return'].values,
        ])
        y = f4['fwd_1d'].values
        beta, residuals, rank, sv = lstsq(X, y, rcond=None)

        # Standard errors
        y_hat = X @ beta
        resid = y - y_hat
        n_obs = len(y)
        k = X.shape[1]
        s2 = np.sum(resid**2) / (n_obs - k)
        var_beta = s2 * np.linalg.inv(X.T @ X)
        se = np.sqrt(np.diag(var_beta))
        t_stats = beta / se

        results[ticker] = {
            'corr_volratio_fwd1d_highvol': corr_hv,
            'p_highvol': p_hv,
            'corr_volratio_fwd1d_lowvol': corr_lv,
            'p_lowvol': p_lv,
            'corr_dollarvolratio_fwd1d': corr_dv,
            'p_dollarvol': p_dv,
            'corr_vol_acceleration_fwd1d': corr_acc,
            'p_acceleration': p_acc,
            'ols_beta_const': beta[0] * 100,
            'ols_beta_volratio': beta[1] * 100,
            'ols_beta_return': beta[2] * 100,
            'ols_t_const': t_stats[0],
            'ols_t_volratio': t_stats[1],
            'ols_t_return': t_stats[2],
            'ols_n': n_obs,
        }

        print(f"  {ticker}:")
        print(f"    Volume-return correlation:")
        print(f"      High vol regime: r={corr_hv:.4f} (p={p_hv:.4f})")
        print(f"      Low vol regime:  r={corr_lv:.4f} (p={p_lv:.4f})")
        print(f"      Dollar volume:   r={corr_dv:.4f} (p={p_dv:.4f})")
        print(f"      Vol acceleration: r={corr_acc:.4f} (p={p_acc:.4f})")
        print(f"    OLS: fwd_1d ~ const + vol_ratio + same_day_return")
        print(f"      const:     beta={beta[0]*10000:.2f}bps  t={t_stats[0]:.2f}")
        print(f"      vol_ratio: beta={beta[1]*10000:.2f}bps  t={t_stats[1]:.2f}")
        print(f"      return:    beta={beta[2]*100:.3f}%    t={t_stats[2]:.2f}")
        print()

    return results


# ============================================================
# ANALYSIS 6: Rolling Predictive Power (Out-of-Sample)
# ============================================================

def analysis_rolling_oos(features):
    """Rolling out-of-sample test: does volume signal work in recent data?"""
    print("\n" + "="*70)
    print("ANALYSIS 6: Rolling Out-of-Sample Predictive Power")
    print("="*70)
    print("Question: Is volume's predictive power stable across time?\n")

    results = {}

    for ticker, feat in features.items():
        f = feat.dropna(subset=['vol_ratio', 'fwd_1d']).copy()

        if len(f) < 1000:
            print(f"  {ticker}: insufficient data ({len(f)} obs)")
            continue

        # 5-year rolling windows with 1-year step
        window_size = 252 * 5  # 5 years
        step_size = 252  # 1 year

        rolling_results = []

        start = 0
        while start + window_size <= len(f):
            window = f.iloc[start:start + window_size]

            # In-sample: first 4 years, OOS: last year
            is_data = window.iloc[:252*4]
            oos_data = window.iloc[252*4:]

            year_label = oos_data.index[0].year

            # Simple strategy: go long when vol_ratio < 0.8 (low volume = complacency)
            # go short/flat when vol_ratio > 1.5 (high volume = panic/uncertainty)
            oos_signal = pd.Series(0.0, index=oos_data.index)
            oos_signal[oos_data['vol_ratio'] < 0.8] = 1.0
            oos_signal[oos_data['vol_ratio'] > 1.5] = -1.0

            # OOS return
            oos_ret = (oos_signal.shift(1) * oos_data['return']).dropna()
            buy_hold = oos_data['return']

            if len(oos_ret) > 20:
                sharpe_signal = oos_ret.mean() / oos_ret.std() * np.sqrt(252) if oos_ret.std() > 0 else 0
                sharpe_bh = buy_hold.mean() / buy_hold.std() * np.sqrt(252) if buy_hold.std() > 0 else 0

                rolling_results.append({
                    'year': year_label,
                    'sharpe_signal': sharpe_signal,
                    'sharpe_buyhold': sharpe_bh,
                    'excess_sharpe': sharpe_signal - sharpe_bh,
                    'n_long': int((oos_signal == 1).sum()),
                    'n_short': int((oos_signal == -1).sum()),
                    'n_flat': int((oos_signal == 0).sum()),
                    'total_return_signal': oos_ret.sum() * 100,
                    'total_return_bh': buy_hold.sum() * 100,
                })

            start += step_size

        results[ticker] = rolling_results

        print(f"  {ticker}:")
        print(f"    {'Year':>6s}  {'Sharpe_Sig':>11s}  {'Sharpe_BH':>10s}  {'Excess':>8s}  {'Ret_Sig':>8s}  {'Ret_BH':>8s}  {'Long':>5s}  {'Short':>5s}")
        for r in rolling_results:
            print(f"    {r['year']:>6d}  {r['sharpe_signal']:>11.3f}  {r['sharpe_buyhold']:>10.3f}  {r['excess_sharpe']:>+8.3f}  {r['total_return_signal']:>+8.1f}%  {r['total_return_bh']:>+8.1f}%  {r['n_long']:>5d}  {r['n_short']:>5d}")

        # Summary
        if rolling_results:
            avg_excess = np.mean([r['excess_sharpe'] for r in rolling_results])
            win_rate = np.mean([1 if r['excess_sharpe'] > 0 else 0 for r in rolling_results]) * 100
            print(f"    Average excess Sharpe: {avg_excess:+.3f}")
            print(f"    Win rate (beat B&H): {win_rate:.0f}%")
        print()

    return results


# ============================================================
# ANALYSIS 7: Cross-Asset Volume-Based Trading Signal
# ============================================================

def analysis_cross_asset_signal(features):
    """Build a composite cross-asset volume signal and test it OOS."""
    print("\n" + "="*70)
    print("ANALYSIS 7: Cross-Asset Composite Volume Signal")
    print("="*70)
    print("Question: Can a multi-ETF volume signal beat single-ETF signals?\n")

    # Build aligned dataset
    tickers = list(features.keys())
    common_idx = features[tickers[0]].index
    for t in tickers[1:]:
        common_idx = common_idx.intersection(features[t].index)

    aligned = {}
    for t in tickers:
        aligned[t] = features[t].loc[common_idx]

    n = len(common_idx)
    print(f"  Common observations: {n}")

    # Composite signal: average vol_ratio across all ETFs
    vol_ratios = pd.DataFrame({t: aligned[t]['vol_ratio'] for t in tickers})
    composite_vol = vol_ratios.mean(axis=1)

    # SPY returns
    spy_fwd = aligned['SPY']['fwd_1d']
    spy_ret = aligned['SPY']['return']

    # Correlation
    valid = composite_vol.dropna().index.intersection(spy_fwd.dropna().index)
    corr, p = stats.spearmanr(composite_vol.loc[valid], spy_fwd.loc[valid])
    print(f"\n  Composite vol ratio → SPY fwd 1d: r={corr:.4f} (p={p:.4f})")

    # Signal: risk-off when composite vol > 1.3, risk-on when < 0.8
    signal = pd.Series(0.0, index=common_idx)
    signal[composite_vol < 0.8] = 1.0   # Low volume = complacent, stay long
    signal[composite_vol > 1.3] = -1.0  # High volume = stressed, go flat/short

    # Out-of-sample: train on first half, test on second half
    mid = len(common_idx) // 2
    is_idx = common_idx[:mid]
    oos_idx = common_idx[mid:]

    print(f"\n  IS period: {is_idx[0].strftime('%Y-%m-%d')} to {is_idx[-1].strftime('%Y-%m-%d')} ({len(is_idx)} days)")
    print(f"  OOS period: {oos_idx[0].strftime('%Y-%m-%d')} to {oos_idx[-1].strftime('%Y-%m-%d')} ({len(oos_idx)} days)")

    # IS performance
    is_signal_ret = (signal.loc[is_idx].shift(1) * spy_ret.loc[is_idx]).dropna()
    is_bh_ret = spy_ret.loc[is_idx].dropna()
    is_sharpe_sig = is_signal_ret.mean() / is_signal_ret.std() * np.sqrt(252)
    is_sharpe_bh = is_bh_ret.mean() / is_bh_ret.std() * np.sqrt(252)

    # OOS performance
    oos_signal_ret = (signal.loc[oos_idx].shift(1) * spy_ret.loc[oos_idx]).dropna()
    oos_bh_ret = spy_ret.loc[oos_idx].dropna()
    oos_sharpe_sig = oos_signal_ret.mean() / oos_signal_ret.std() * np.sqrt(252)
    oos_sharpe_bh = oos_bh_ret.mean() / oos_bh_ret.std() * np.sqrt(252)

    # Max drawdown
    def max_drawdown(returns):
        cum = (1 + returns).cumprod()
        peak = cum.expanding().max()
        dd = (cum - peak) / peak
        return dd.min()

    oos_mdd_sig = max_drawdown(oos_signal_ret)
    oos_mdd_bh = max_drawdown(oos_bh_ret)

    results = {
        'composite_spearman': corr,
        'composite_p': p,
        'is_sharpe_signal': is_sharpe_sig,
        'is_sharpe_bh': is_sharpe_bh,
        'oos_sharpe_signal': oos_sharpe_sig,
        'oos_sharpe_bh': oos_sharpe_bh,
        'oos_mdd_signal': oos_mdd_sig,
        'oos_mdd_bh': oos_mdd_bh,
        'oos_annual_return_signal': oos_signal_ret.mean() * 252 * 100,
        'oos_annual_return_bh': oos_bh_ret.mean() * 252 * 100,
        'oos_n': len(oos_signal_ret),
        'n_long_oos': int((signal.loc[oos_idx] == 1).sum()),
        'n_short_oos': int((signal.loc[oos_idx] == -1).sum()),
        'n_flat_oos': int((signal.loc[oos_idx] == 0).sum()),
    }

    print(f"\n  In-Sample Results:")
    print(f"    Sharpe (signal): {is_sharpe_sig:.3f}")
    print(f"    Sharpe (buy&hold): {is_sharpe_bh:.3f}")

    print(f"\n  Out-of-Sample Results:")
    print(f"    Sharpe (signal): {oos_sharpe_sig:.3f}")
    print(f"    Sharpe (buy&hold): {oos_sharpe_bh:.3f}")
    print(f"    Annual return (signal): {results['oos_annual_return_signal']:.2f}%")
    print(f"    Annual return (buy&hold): {results['oos_annual_return_bh']:.2f}%")
    print(f"    Max DD (signal): {oos_mdd_sig*100:.1f}%")
    print(f"    Max DD (buy&hold): {oos_mdd_bh*100:.1f}%")
    print(f"    Signal distribution: Long={results['n_long_oos']}, Short={results['n_short_oos']}, Flat={results['n_flat_oos']}")

    # Bootstrap test of Sharpe difference
    n_boot = 10000
    np.random.seed(42)
    sharpe_diffs = []
    for _ in range(n_boot):
        idx = np.random.choice(len(oos_signal_ret), len(oos_signal_ret), replace=True)
        sig_boot = oos_signal_ret.iloc[idx]
        bh_boot = oos_bh_ret.iloc[idx]
        s_sig = sig_boot.mean() / sig_boot.std() * np.sqrt(252)
        s_bh = bh_boot.mean() / bh_boot.std() * np.sqrt(252)
        sharpe_diffs.append(s_sig - s_bh)

    sharpe_diffs = np.array(sharpe_diffs)
    ci_low, ci_high = np.percentile(sharpe_diffs, [2.5, 97.5])
    pct_positive = (sharpe_diffs > 0).mean() * 100

    results['bootstrap_sharpe_diff_mean'] = sharpe_diffs.mean()
    results['bootstrap_ci_95'] = [ci_low, ci_high]
    results['bootstrap_pct_positive'] = pct_positive

    print(f"\n  Bootstrap (10k): Sharpe diff = {sharpe_diffs.mean():.3f} [{ci_low:.3f}, {ci_high:.3f}]")
    print(f"    Signal beats B&H in {pct_positive:.1f}% of bootstraps")

    return results


# ============================================================
# MAIN
# ============================================================

def main():
    print("K413: ETF Fund Flows and Price Discovery")
    print("=" * 70)
    print(f"Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("Data: SPY, GLD, TLT, EEM, IWM (2005-2024, yfinance)")
    print("NO VIX, NO VT, NO 50/50 — purely ETF structure analysis")
    print("=" * 70)

    # 1. Fetch data
    print("\n[1/8] Fetching data from yfinance...")
    data = fetch_data()

    # 2. Prepare features
    print("\n[2/8] Computing volume features...")
    features = prepare_features(data)
    for t, f in features.items():
        print(f"  {t}: {len(f)} observations after feature computation")

    # 3. Analysis 1: Volume Anomaly
    print("\n[3/8] Running volume anomaly analysis...")
    r1 = analysis_volume_anomaly(features)

    # 4. Analysis 2: Lead-Lag
    print("\n[4/8] Running volume-return lead-lag analysis...")
    r2 = analysis_volume_return_leadlag(features)

    # 5. Analysis 3: Cross-ETF
    print("\n[5/8] Running cross-ETF volume analysis...")
    r3 = analysis_cross_etf_volume(features)

    # 6. Analysis 4: Extremes
    print("\n[6/8] Running volume extremes analysis...")
    r4 = analysis_volume_extremes(features)

    # 7. Analysis 5: Volume-Price Dynamics
    print("\n[7/8] Running volume-price dynamics analysis...")
    r5 = analysis_volume_price_dynamics(features)

    # 8. Analysis 6: Rolling OOS
    print("\n[8/8] Running rolling OOS and cross-asset signal...")
    r6 = analysis_rolling_oos(features)
    r7 = analysis_cross_asset_signal(features)

    # ============================================================
    # SUMMARY
    # ============================================================
    print("\n" + "=" * 70)
    print("K413 SUMMARY: ETF Fund Flows and Price Discovery")
    print("=" * 70)

    print("\n--- Key Findings ---\n")

    # Summarize Analysis 1
    print("1. VOLUME ANOMALY (>2x average):")
    for t, r in r1.items():
        sig_1d = "*" if r['p_value_1d'] < 0.05 else ""
        sig_sd = "*" if r['p_value_sameday'] < 0.05 else ""
        print(f"   {t}: same-day {r['anomaly_sameday_mean']:+.3f}%{sig_sd}  fwd1d {r['anomaly_fwd1_mean']:+.3f}%{sig_1d}  (n={r['n_anomaly']})")

    # Summarize Analysis 2
    print("\n2. VOLUME-RETURN LEAD-LAG (Spearman correlation):")
    for t, r in r2.items():
        sig = "*" if r['p_volratio_fwd1d'] < 0.05 else ""
        sig_ud = "*" if r['p_udvolratio_fwd1d'] < 0.05 else ""
        print(f"   {t}: vol_ratio→fwd1d r={r['spearman_volratio_fwd1d']:+.4f}{sig}  up/down_ratio→fwd1d r={r['spearman_udvolratio_fwd1d']:+.4f}{sig_ud}  Q5-Q1={r['q5_minus_q1_bps']:+.3f}%")

    # Summarize Analysis 3
    print("\n3. CROSS-ETF VOLUME DIVERGENCE → SPY fwd returns:")
    for pair, r in r3.get('divergence_signals', {}).items():
        sig = "*" if r['p_value'] < 0.05 else ""
        print(f"   {pair}: divergence={r['div_spy_fwd1d_mean']:+.3f}% vs convergence={r['conv_spy_fwd1d_mean']:+.3f}%{sig}")

    # Summarize Analysis 4
    print("\n4. EXTREME VOLUME (top 1%) → forward returns:")
    for t, r in r4.items():
        if 'top_1pct' in r and 'middle_50pct' in r:
            top = r['top_1pct']
            mid = r['middle_50pct']
            print(f"   {t}: top1% fwd1d={top['fwd_1d_mean']:+.3f}% vs middle={mid['fwd_1d_mean']:+.3f}%  fwd20d={top['fwd_20d_mean']:+.3f}% vs {mid['fwd_20d_mean']:+.3f}%")

    # Summarize Analysis 7
    print(f"\n5. CROSS-ASSET COMPOSITE SIGNAL (OOS):")
    print(f"   Sharpe signal={r7['oos_sharpe_signal']:.3f} vs B&H={r7['oos_sharpe_bh']:.3f}")
    print(f"   Bootstrap: signal beats B&H in {r7['bootstrap_pct_positive']:.1f}% of samples")
    print(f"   95% CI for Sharpe diff: [{r7['bootstrap_ci_95'][0]:.3f}, {r7['bootstrap_ci_95'][1]:.3f}]")

    # Overall assessment
    print("\n--- Overall Assessment ---")

    # Count significant findings
    sig_count = 0
    total_tests = 0
    for t, r in r1.items():
        total_tests += 2
        if r['p_value_1d'] < 0.05: sig_count += 1
        if r['p_value_sameday'] < 0.05: sig_count += 1
    for t, r in r2.items():
        total_tests += 2
        if r['p_volratio_fwd1d'] < 0.05: sig_count += 1
        if r['p_udvolratio_fwd1d'] < 0.05: sig_count += 1

    print(f"\n   Significant tests (p<0.05): {sig_count}/{total_tests}")
    print(f"   Expected by chance (5%): {total_tests * 0.05:.1f}")

    harvey_count = 0
    for t, r in r2.items():
        # Check if any t-stat exceeds Harvey (2016) threshold of 3.0
        if abs(r.get('t_q5q1', 0)) > 3.0:
            harvey_count += 1
    print(f"   Tests passing Harvey (2016) |t|>3.0 threshold: {harvey_count}")

    print(f"\n   OOS composite signal Sharpe: {r7['oos_sharpe_signal']:.3f}")
    if r7['oos_sharpe_signal'] > r7['oos_sharpe_bh']:
        print("   Signal OUTPERFORMS buy-and-hold OOS")
    else:
        print("   Signal UNDERPERFORMS buy-and-hold OOS")

    # Save results
    all_results = {
        'experiment': 'K413',
        'title': 'ETF Fund Flows and Price Discovery',
        'timestamp': datetime.now().isoformat(),
        'data_source': 'yfinance',
        'data_period': '2005-2024',
        'assets': ['SPY', 'GLD', 'TLT', 'EEM', 'IWM'],
        'analysis_1_volume_anomaly': r1,
        'analysis_2_leadlag': {k: {kk: (vv if not isinstance(vv, float) or not np.isnan(vv) else None) for kk, vv in v.items()} for k, v in r2.items()},
        'analysis_3_cross_etf': {
            'n_common': r3['n_common'],
            'spike_counts': r3['spike_counts'],
            'divergence_signals': r3['divergence_signals'],
        },
        'analysis_4_extremes': r4,
        'analysis_5_dynamics': r5,
        'analysis_6_rolling_oos': r6,
        'analysis_7_composite_signal': r7,
    }

    # Convert numpy types for JSON serialization
    def convert_types(obj):
        if isinstance(obj, dict):
            return {k: convert_types(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [convert_types(v) for v in obj]
        elif isinstance(obj, (np.integer,)):
            return int(obj)
        elif isinstance(obj, (np.floating,)):
            return float(obj) if not np.isnan(obj) else None
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif isinstance(obj, pd.Timestamp):
            return obj.isoformat()
        return obj

    all_results = convert_types(all_results)

    output_path = 'experiments/k413_etf_flows_results.json'
    with open(output_path, 'w') as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"\n  Results saved to {output_path}")

    print(f"\nEnd time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*70)

    return all_results


if __name__ == '__main__':
    results = main()
