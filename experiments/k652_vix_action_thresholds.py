"""
K652: Practical VIX Action Thresholds — When Should Investors Act?
===================================================================
Motivation:
  Our strategies use continuous VIX scaling (12/VIX) or discrete brackets.
  But for a retail investor who checks VIX once a day, what are the ACTIONABLE
  thresholds? When does a VIX change actually warrant portfolio adjustment?

  Prior knowledge:
    - K1: VIX is the single most informative predictor (confirmed 31+ times)
    - K456/K457: 12/VIX rule confirmed robust across assets
    - K503: VIX mean-reversion is well-documented
    - K641: VIX regime decomposition — calm/normal/stress/crisis
    - K649: Vol-of-vol regime change prediction

Data source: yfinance (SPY, GLD, ^VIX), 2006-01-01 to 2026-03-27
Type: Empirical analysis (real data)

References:
  - Whaley (2000) "The Investor Fear Gauge" JPC — VIX as fear index
  - Szado (2009) "VIX Futures and Options" JPM — VIX trading strategies
  - Banerjee et al. (2007) "Forecasting Realized Volatility" JFM — VIX predictive power
  - Simon & Wiggins (2001) "S&P Futures Returns and Contrary Sentiment" JFQA
  - Giot (2005) "Relationships Between Implied Volatility Indexes and Stock Index Returns"
"""

import json
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime
from pathlib import Path
from scipy import stats
import warnings
warnings.filterwarnings('ignore')

# ── Configuration ─────────────────────────────────────────────────────
START_DATE = "2006-01-01"
END_DATE = "2026-03-27"
VIX_LEVEL_THRESHOLDS = [12, 15, 18, 20, 22, 25, 28, 30, 35, 40]
VIX_CHANGE_THRESHOLDS = [2, 3, 5, 8, 10]
ACT_THRESHOLDS = [0, 1, 2, 3, 5, 10]
FORWARD_WINDOWS = [1, 5, 20, 60]  # days
TX_COST_BPS = 10  # 10 bps round-trip
RESULTS_FILE = Path(__file__).resolve().parent / "k652_results.json"


def download_data():
    """Download SPY, GLD, VIX data."""
    print("=" * 70)
    print("K652: Practical VIX Action Thresholds")
    print("=" * 70)
    print(f"\nDownloading data: SPY, GLD, ^VIX ({START_DATE} to {END_DATE})")

    spy = yf.download("SPY", start=START_DATE, end=END_DATE, progress=False)
    gld = yf.download("GLD", start=START_DATE, end=END_DATE, progress=False)
    vix = yf.download("^VIX", start=START_DATE, end=END_DATE, progress=False)

    # Handle multi-level columns from yfinance
    for df in [spy, gld, vix]:
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

    # Build aligned DataFrame
    data = pd.DataFrame({
        'spy_close': spy['Close'],
        'gld_close': gld['Close'],
        'vix_close': vix['Close']
    }).dropna()

    # Compute returns
    data['spy_ret'] = data['spy_close'].pct_change()
    data['gld_ret'] = data['gld_close'].pct_change()
    data['vix_change'] = data['vix_close'].diff()
    data['vix_pct_change'] = data['vix_close'].pct_change()
    data = data.dropna()

    print(f"Data: {len(data)} trading days ({data.index[0].strftime('%Y-%m-%d')} to {data.index[-1].strftime('%Y-%m-%d')})")
    return data


def descriptive_stats(data):
    """Basic VIX descriptive statistics."""
    print("\n" + "=" * 70)
    print("DESCRIPTIVE STATISTICS")
    print("=" * 70)

    vix = data['vix_close']
    print(f"\nVIX Close:")
    print(f"  Mean:     {vix.mean():.2f}")
    print(f"  Median:   {vix.median():.2f}")
    print(f"  Std:      {vix.std():.2f}")
    print(f"  Min:      {vix.min():.2f}")
    print(f"  Max:      {vix.max():.2f}")
    print(f"  Skewness: {vix.skew():.2f}")
    print(f"  Kurtosis: {vix.kurtosis():.2f}")

    # VIX distribution by percentile
    percentiles = [5, 10, 25, 50, 75, 90, 95]
    print(f"\nVIX Percentiles:")
    for p in percentiles:
        print(f"  {p}th: {np.percentile(vix, p):.2f}")

    # Time in each regime
    print(f"\nTime in VIX regimes:")
    regimes = [(0, 15), (15, 20), (20, 25), (25, 30), (30, 100)]
    for lo, hi in regimes:
        pct = ((vix >= lo) & (vix < hi)).mean() * 100
        print(f"  VIX {lo}-{hi}: {pct:.1f}% of days")

    return {
        'vix_mean': round(vix.mean(), 2),
        'vix_median': round(vix.median(), 2),
        'vix_std': round(vix.std(), 2),
        'vix_skewness': round(vix.skew(), 2),
        'vix_kurtosis': round(vix.kurtosis(), 2),
        'percentiles': {str(p): round(np.percentile(vix, p), 2) for p in percentiles},
        'regime_pct': {f"{lo}-{hi}": round(((vix >= lo) & (vix < hi)).mean() * 100, 1) for lo, hi in regimes}
    }


def analysis1_level_thresholds(data):
    """Analysis 1: VIX level crossing thresholds."""
    print("\n" + "=" * 70)
    print("ANALYSIS 1: VIX LEVEL THRESHOLDS")
    print("=" * 70)

    vix = data['vix_close'].values
    spy_ret = data['spy_ret'].values
    n = len(data)

    # Compute forward returns for various windows
    fwd_rets = {}
    for w in FORWARD_WINDOWS:
        fr = np.full(n, np.nan)
        spy_close = data['spy_close'].values
        for i in range(n - w):
            fr[i] = (spy_close[i + w] / spy_close[i]) - 1
        fwd_rets[w] = fr

    # Unconditional stats
    uncond_20d = fwd_rets[20][~np.isnan(fwd_rets[20])]
    uncond_mean = np.mean(uncond_20d)
    uncond_std = np.std(uncond_20d)
    print(f"\nUnconditional 20-day SPY return: mean={uncond_mean*100:.2f}%, std={uncond_std*100:.2f}%")

    results = {}
    print(f"\n{'Threshold':>10} | {'Cross Up':>10} | {'Mean 20d':>10} | {'Win Rate':>10} | {'t-stat':>8} | {'Cross Dn':>10} | {'Mean 20d':>10} | {'Win Rate':>10} | {'t-stat':>8}")
    print("-" * 110)

    for t in VIX_LEVEL_THRESHOLDS:
        # Cross ABOVE: VIX was below t yesterday, now >= t
        cross_up = np.zeros(n, dtype=bool)
        cross_dn = np.zeros(n, dtype=bool)
        for i in range(1, n):
            if vix[i-1] < t and vix[i] >= t:
                cross_up[i] = True
            if vix[i-1] >= t and vix[i] < t:
                cross_dn[i] = True

        # Also: being ABOVE t (level condition, not just crossing)
        above_t = vix >= t
        below_t = vix < t

        # Forward returns after crossing above
        fwd_20_up = fwd_rets[20][cross_up]
        fwd_20_up = fwd_20_up[~np.isnan(fwd_20_up)]

        # Forward returns after crossing below
        fwd_20_dn = fwd_rets[20][cross_dn]
        fwd_20_dn = fwd_20_dn[~np.isnan(fwd_20_dn)]

        # Stats
        if len(fwd_20_up) > 5:
            mean_up = np.mean(fwd_20_up)
            wr_up = np.mean(fwd_20_up > 0) * 100
            t_stat_up, p_val_up = stats.ttest_1samp(fwd_20_up, uncond_mean)
        else:
            mean_up = np.nan
            wr_up = np.nan
            t_stat_up = np.nan

        if len(fwd_20_dn) > 5:
            mean_dn = np.mean(fwd_20_dn)
            wr_dn = np.mean(fwd_20_dn > 0) * 100
            t_stat_dn, p_val_dn = stats.ttest_1samp(fwd_20_dn, uncond_mean)
        else:
            mean_dn = np.nan
            wr_dn = np.nan
            t_stat_dn = np.nan

        print(f"  VIX={t:>3} | {int(cross_up.sum()):>10} | {mean_up*100:>9.2f}% | {wr_up:>9.1f}% | {t_stat_up:>7.2f} | {int(cross_dn.sum()):>10} | {mean_dn*100:>9.2f}% | {wr_dn:>9.1f}% | {t_stat_dn:>7.2f}")

        # Full forward return analysis for all windows (being above/below, not just crossing)
        threshold_detail = {
            'threshold': t,
            'n_cross_above': int(cross_up.sum()),
            'n_cross_below': int(cross_dn.sum()),
            'n_days_above': int(above_t.sum()),
            'pct_days_above': round(above_t.mean() * 100, 1),
        }

        for w in FORWARD_WINDOWS:
            fr = fwd_rets[w]
            # After crossing above
            fr_up = fr[cross_up]
            fr_up = fr_up[~np.isnan(fr_up)]
            if len(fr_up) > 5:
                threshold_detail[f'cross_above_{w}d_mean'] = round(float(np.mean(fr_up) * 100), 3)
                threshold_detail[f'cross_above_{w}d_win_rate'] = round(float(np.mean(fr_up > 0) * 100), 1)
                t_s, _ = stats.ttest_1samp(fr_up, np.nanmean(fr[~np.isnan(fr)]))
                threshold_detail[f'cross_above_{w}d_tstat'] = round(float(t_s), 3)
            else:
                threshold_detail[f'cross_above_{w}d_mean'] = None
                threshold_detail[f'cross_above_{w}d_win_rate'] = None
                threshold_detail[f'cross_above_{w}d_tstat'] = None

            # After crossing below
            fr_dn = fr[cross_dn]
            fr_dn = fr_dn[~np.isnan(fr_dn)]
            if len(fr_dn) > 5:
                threshold_detail[f'cross_below_{w}d_mean'] = round(float(np.mean(fr_dn) * 100), 3)
                threshold_detail[f'cross_below_{w}d_win_rate'] = round(float(np.mean(fr_dn > 0) * 100), 1)
                t_s, _ = stats.ttest_1samp(fr_dn, np.nanmean(fr[~np.isnan(fr)]))
                threshold_detail[f'cross_below_{w}d_tstat'] = round(float(t_s), 3)
            else:
                threshold_detail[f'cross_below_{w}d_mean'] = None
                threshold_detail[f'cross_below_{w}d_win_rate'] = None
                threshold_detail[f'cross_below_{w}d_tstat'] = None

            # Being above threshold (level condition)
            fr_above = fr[above_t]
            fr_above = fr_above[~np.isnan(fr_above)]
            fr_below = fr[below_t]
            fr_below = fr_below[~np.isnan(fr_below)]
            if len(fr_above) > 20 and len(fr_below) > 20:
                threshold_detail[f'above_{w}d_mean'] = round(float(np.mean(fr_above) * 100), 3)
                threshold_detail[f'below_{w}d_mean'] = round(float(np.mean(fr_below) * 100), 3)
                threshold_detail[f'above_{w}d_win_rate'] = round(float(np.mean(fr_above > 0) * 100), 1)
                threshold_detail[f'below_{w}d_win_rate'] = round(float(np.mean(fr_below > 0) * 100), 1)
                # Two-sample t-test: above vs below
                t_s2, p_s2 = stats.ttest_ind(fr_above, fr_below)
                threshold_detail[f'level_{w}d_tstat'] = round(float(t_s2), 3)
                threshold_detail[f'level_{w}d_pval'] = round(float(p_s2), 4)

        results[str(t)] = threshold_detail

    return results


def analysis2_vix_change_thresholds(data):
    """Analysis 2: VIX change (spike) thresholds."""
    print("\n" + "=" * 70)
    print("ANALYSIS 2: VIX CHANGE THRESHOLDS (SPIKE ANALYSIS)")
    print("=" * 70)

    vix = data['vix_close'].values
    vix_change = data['vix_change'].values
    spy_close = data['spy_close'].values
    n = len(data)

    # Compute forward SPY returns
    fwd_rets = {}
    for w in FORWARD_WINDOWS:
        fr = np.full(n, np.nan)
        for i in range(n - w):
            fr[i] = (spy_close[i + w] / spy_close[i]) - 1
        fwd_rets[w] = fr

    results = {}

    print(f"\n{'dVIX >':>8} | {'N spikes':>8} | {'1d ret':>10} | {'5d ret':>10} | {'20d ret':>10} | {'60d ret':>10} | {'20d WR':>8} | {'MR days':>8}")
    print("-" * 95)

    for dv in VIX_CHANGE_THRESHOLDS:
        # VIX spike up
        spike_up = vix_change > dv
        # VIX spike down
        spike_dn = vix_change < -dv

        n_up = int(spike_up.sum())
        n_dn = int(spike_dn.sum())

        spike_detail = {
            'threshold_points': dv,
            'n_spikes_up': n_up,
            'n_spikes_down': n_dn,
        }

        # Forward returns after spike UP
        for w in FORWARD_WINDOWS:
            fr = fwd_rets[w]
            fr_up = fr[spike_up]
            fr_up = fr_up[~np.isnan(fr_up)]
            if len(fr_up) > 5:
                spike_detail[f'spike_up_{w}d_mean'] = round(float(np.mean(fr_up) * 100), 3)
                spike_detail[f'spike_up_{w}d_median'] = round(float(np.median(fr_up) * 100), 3)
                spike_detail[f'spike_up_{w}d_win_rate'] = round(float(np.mean(fr_up > 0) * 100), 1)
                t_s, p_v = stats.ttest_1samp(fr_up, 0)
                spike_detail[f'spike_up_{w}d_tstat'] = round(float(t_s), 3)
            else:
                spike_detail[f'spike_up_{w}d_mean'] = None

            # Forward returns after spike DOWN
            fr_dn = fr[spike_dn]
            fr_dn = fr_dn[~np.isnan(fr_dn)]
            if len(fr_dn) > 5:
                spike_detail[f'spike_dn_{w}d_mean'] = round(float(np.mean(fr_dn) * 100), 3)
                spike_detail[f'spike_dn_{w}d_median'] = round(float(np.median(fr_dn) * 100), 3)
                spike_detail[f'spike_dn_{w}d_win_rate'] = round(float(np.mean(fr_dn > 0) * 100), 1)
                t_s, p_v = stats.ttest_1samp(fr_dn, 0)
                spike_detail[f'spike_dn_{w}d_tstat'] = round(float(t_s), 3)

        # Mean-reversion speed: how many days until VIX returns to pre-spike level?
        spike_indices = np.where(spike_up)[0]
        mr_days = []
        for idx in spike_indices:
            pre_level = vix[idx - 1] if idx > 0 else vix[idx]
            # Search forward for VIX returning to pre-spike level
            found = False
            for d in range(1, min(126, n - idx)):  # max 6 months
                if vix[idx + d] <= pre_level:
                    mr_days.append(d)
                    found = True
                    break
            if not found:
                mr_days.append(126)  # censored at 6 months

        if len(mr_days) > 0:
            spike_detail['mean_reversion_days_mean'] = round(float(np.mean(mr_days)), 1)
            spike_detail['mean_reversion_days_median'] = round(float(np.median(mr_days)), 1)
            spike_detail['mean_reversion_pct_within_20d'] = round(float(np.mean(np.array(mr_days) <= 20) * 100), 1)
            spike_detail['mean_reversion_pct_within_60d'] = round(float(np.mean(np.array(mr_days) <= 60) * 100), 1)
        else:
            spike_detail['mean_reversion_days_mean'] = None

        # Print summary
        up_1d = spike_detail.get(f'spike_up_1d_mean', None)
        up_5d = spike_detail.get(f'spike_up_5d_mean', None)
        up_20d = spike_detail.get(f'spike_up_20d_mean', None)
        up_60d = spike_detail.get(f'spike_up_60d_mean', None)
        wr_20d = spike_detail.get(f'spike_up_20d_win_rate', None)
        mr_d = spike_detail.get('mean_reversion_days_median', None)

        print(f"  +{dv:>5} | {n_up:>8} | {up_1d:>9.2f}% | {up_5d:>9.2f}% | {up_20d:>9.2f}% | {up_60d if up_60d else 0:>9.2f}% | {wr_20d:>7.1f}% | {mr_d:>7.1f}")

        results[str(dv)] = spike_detail

    # Contrarian signal analysis
    print("\n--- Contrarian Signal Analysis ---")
    print("Are VIX spikes buy signals? (next 20-day return after spike vs unconditional)")
    uncond_20d = fwd_rets[20][~np.isnan(fwd_rets[20])]
    uncond_mean = np.mean(uncond_20d)
    print(f"Unconditional 20d mean: {uncond_mean*100:.2f}%")

    for dv in VIX_CHANGE_THRESHOLDS:
        spike_up = vix_change > dv
        fr = fwd_rets[20][spike_up]
        fr = fr[~np.isnan(fr)]
        if len(fr) > 5:
            excess = np.mean(fr) - uncond_mean
            t_s, p_v = stats.ttest_1samp(fr, uncond_mean)
            print(f"  dVIX > +{dv}: n={len(fr)}, excess 20d ret = {excess*100:+.2f}%, t={t_s:.2f}, p={p_v:.3f}")
            results[str(dv)]['contrarian_excess_20d'] = round(float(excess * 100), 3)
            results[str(dv)]['contrarian_tstat'] = round(float(t_s), 3)
            results[str(dv)]['contrarian_pval'] = round(float(p_v), 4)

    return results


def analysis3_act_vs_ignore(data):
    """Analysis 3: Optimal 'act vs ignore' threshold for portfolio adjustment."""
    print("\n" + "=" * 70)
    print("ANALYSIS 3: OPTIMAL ACT VS IGNORE THRESHOLD")
    print("=" * 70)
    print("Strategy: 50/50 SPY/GLD with 12/VIX equity weight")
    print(f"TX cost: {TX_COST_BPS} bps per trade")

    spy_ret = data['spy_ret'].values
    gld_ret = data['gld_ret'].values
    vix = data['vix_close'].values
    vix_change = data['vix_change'].values
    n = len(data)

    results = {}

    print(f"\n{'Threshold':>10} | {'Trades':>7} | {'Trades/yr':>10} | {'CAGR':>8} | {'Vol':>8} | {'Sharpe':>8} | {'MDD':>8} | {'Net Sharpe':>10}")
    print("-" * 90)

    for act_thresh in ACT_THRESHOLDS:
        # Simulate the strategy
        equity = np.zeros(n)
        portfolio_ret = np.zeros(n)
        n_trades = 0

        # Initial weight: 12/VIX clipped [0, 1]
        current_w = np.clip(12.0 / vix[0], 0, 1)
        equity[0] = 1.0

        for i in range(1, n):
            target_w = np.clip(12.0 / vix[i], 0, 1)

            # Decide whether to act
            if act_thresh == 0:
                # Always adjust
                actual_w = target_w
                if i > 0:
                    w_change = abs(actual_w - current_w)
                    if w_change > 0.001:
                        n_trades += 1
                current_w = actual_w
            else:
                # Only adjust if VIX changed by more than threshold
                if abs(vix_change[i]) >= act_thresh:
                    actual_w = target_w
                    w_change = abs(actual_w - current_w)
                    if w_change > 0.001:
                        n_trades += 1
                    current_w = actual_w
                else:
                    actual_w = current_w  # keep old weight

            # Portfolio return: w * SPY + (1-w) * GLD
            port_r = actual_w * spy_ret[i] + (1 - actual_w) * gld_ret[i]

            # TX cost on weight change
            w_change_actual = abs(actual_w - current_w) if act_thresh > 0 and abs(vix_change[i]) >= act_thresh else 0
            # For threshold=0, we already set actual_w = target_w, so compute change differently
            if act_thresh == 0 and i > 0:
                # Weight drift from previous day
                w_prev = np.clip(12.0 / vix[i-1], 0, 1)
                w_change_actual = abs(target_w - w_prev)

            tx = w_change_actual * TX_COST_BPS / 10000
            port_r -= tx

            portfolio_ret[i] = port_r
            equity[i] = equity[i-1] * (1 + port_r)

        # Compute metrics
        years = n / 252
        cagr = (equity[-1] / equity[0]) ** (1 / years) - 1
        vol = np.std(portfolio_ret[1:]) * np.sqrt(252)
        sharpe = (np.mean(portfolio_ret[1:]) * 252) / vol if vol > 0 else 0

        # Max drawdown
        running_max = np.maximum.accumulate(equity)
        drawdowns = (equity - running_max) / running_max
        mdd = np.min(drawdowns)

        # Net Sharpe (already includes TX cost)
        net_sharpe = sharpe  # TX already deducted

        # Trades per year
        trades_per_year = n_trades / years

        # Gross Sharpe (without TX)
        gross_ret = np.zeros(n)
        eq_gross = np.zeros(n)
        cw = np.clip(12.0 / vix[0], 0, 1)
        eq_gross[0] = 1.0
        for i in range(1, n):
            tw = np.clip(12.0 / vix[i], 0, 1)
            if act_thresh == 0:
                w = tw
                cw = tw
            else:
                if abs(vix_change[i]) >= act_thresh:
                    w = tw
                    cw = tw
                else:
                    w = cw
            gross_ret[i] = w * spy_ret[i] + (1 - w) * gld_ret[i]
            eq_gross[i] = eq_gross[i-1] * (1 + gross_ret[i])

        gross_vol = np.std(gross_ret[1:]) * np.sqrt(252)
        gross_sharpe = (np.mean(gross_ret[1:]) * 252) / gross_vol if gross_vol > 0 else 0

        print(f"  dVIX>{act_thresh:>3} | {n_trades:>7} | {trades_per_year:>9.1f} | {cagr*100:>7.2f}% | {vol*100:>7.2f}% | {gross_sharpe:>7.3f} | {mdd*100:>7.2f}% | {net_sharpe:>9.3f}")

        results[str(act_thresh)] = {
            'act_threshold': act_thresh,
            'n_trades': n_trades,
            'trades_per_year': round(trades_per_year, 1),
            'cagr_pct': round(cagr * 100, 3),
            'annual_vol_pct': round(vol * 100, 3),
            'gross_sharpe': round(gross_sharpe, 4),
            'net_sharpe': round(net_sharpe, 4),
            'max_drawdown_pct': round(mdd * 100, 2),
            'final_equity': round(float(equity[-1]), 4),
        }

    # Find optimal threshold
    best_thresh = max(results.keys(), key=lambda k: results[k]['net_sharpe'])
    print(f"\n>>> Optimal threshold: dVIX > {best_thresh} (Net Sharpe = {results[best_thresh]['net_sharpe']:.4f})")
    print(f"    Trades/year: {results[best_thresh]['trades_per_year']:.1f}")
    print(f"    vs always-adjust: saves {results['0']['n_trades'] - results[best_thresh]['n_trades']} trades")

    return results, best_thresh


def analysis4_vix_action_guide(data):
    """Analysis 4: Create practical VIX Action Guide with historical validation."""
    print("\n" + "=" * 70)
    print("ANALYSIS 4: VIX ACTION GUIDE (HISTORICAL VALIDATION)")
    print("=" * 70)

    vix = data['vix_close'].values
    spy_ret = data['spy_ret'].values
    gld_ret = data['gld_ret'].values
    spy_close = data['spy_close'].values
    n = len(data)

    # Define regimes
    regimes = {
        'calm': {'range': (0, 15), 'label': 'Calm', 'advice': 'Fully invested, check weekly'},
        'normal': {'range': (15, 20), 'label': 'Normal', 'advice': 'Standard allocation, check daily'},
        'elevated': {'range': (20, 25), 'label': 'Elevated', 'advice': 'Reduce equity if not already'},
        'high': {'range': (25, 30), 'label': 'High Alert', 'advice': 'Significant equity reduction'},
        'crisis': {'range': (30, 100), 'label': 'Crisis', 'advice': 'Minimum equity exposure'},
    }

    # Forward returns for validation
    fwd_rets = {}
    for w in [1, 5, 20, 60, 126, 252]:
        fr = np.full(n, np.nan)
        for i in range(n - w):
            fr[i] = (spy_close[i + w] / spy_close[i]) - 1
        fwd_rets[w] = fr

    results = {}
    print(f"\n{'Regime':>12} | {'VIX range':>10} | {'Days':>7} | {'%':>6} | {'1d ret':>8} | {'20d ret':>8} | {'60d ret':>8} | {'252d ret':>9} | {'20d WR':>7} | {'Ann Vol':>8}")
    print("-" * 115)

    for key, regime in regimes.items():
        lo, hi = regime['range']
        mask = (vix >= lo) & (vix < hi)
        n_days = int(mask.sum())
        pct_days = mask.mean() * 100

        regime_result = {
            'vix_range': f"{lo}-{hi}",
            'label': regime['label'],
            'advice': regime['advice'],
            'n_days': n_days,
            'pct_days': round(pct_days, 1),
        }

        # Forward returns in each regime
        for w in [1, 5, 20, 60, 126, 252]:
            fr = fwd_rets[w][mask]
            fr = fr[~np.isnan(fr)]
            if len(fr) > 20:
                regime_result[f'fwd_{w}d_mean_pct'] = round(float(np.mean(fr) * 100), 3)
                regime_result[f'fwd_{w}d_median_pct'] = round(float(np.median(fr) * 100), 3)
                regime_result[f'fwd_{w}d_win_rate'] = round(float(np.mean(fr > 0) * 100), 1)
                regime_result[f'fwd_{w}d_std_pct'] = round(float(np.std(fr) * 100), 3)

                # 5th percentile (worst case)
                regime_result[f'fwd_{w}d_5pct'] = round(float(np.percentile(fr, 5) * 100), 3)
                # 95th percentile (best case)
                regime_result[f'fwd_{w}d_95pct'] = round(float(np.percentile(fr, 95) * 100), 3)

        # SPY volatility in regime
        spy_r_regime = spy_ret[mask]
        ann_vol = np.std(spy_r_regime) * np.sqrt(252) * 100

        regime_result['spy_ann_vol_pct'] = round(float(ann_vol), 2)

        # Average daily SPY return in regime
        regime_result['spy_daily_mean_bps'] = round(float(np.mean(spy_r_regime) * 10000), 2)

        # 12/VIX recommended weight
        vix_in_regime = vix[mask]
        mean_12vix = np.mean(np.clip(12.0 / vix_in_regime, 0, 1))
        regime_result['recommended_12vix_weight'] = round(float(mean_12vix * 100), 1)

        fwd_1d = regime_result.get('fwd_1d_mean_pct', 0)
        fwd_20d = regime_result.get('fwd_20d_mean_pct', 0)
        fwd_60d = regime_result.get('fwd_60d_mean_pct', 0)
        fwd_252d = regime_result.get('fwd_252d_mean_pct', 0)
        wr_20d = regime_result.get('fwd_20d_win_rate', 0)

        print(f"  {regime['label']:>10} | {lo:>3}-{hi:<3}    | {n_days:>7} | {pct_days:>5.1f}% | {fwd_1d:>7.2f}% | {fwd_20d:>7.2f}% | {fwd_60d:>7.2f}% | {fwd_252d:>8.2f}% | {wr_20d:>6.1f}% | {ann_vol:>7.1f}%")

        results[key] = regime_result

    # Transition analysis: what typically comes next?
    print("\n--- Regime Transitions ---")
    regime_labels = ['calm', 'normal', 'elevated', 'high', 'crisis']
    regime_bounds = [(0, 15), (15, 20), (20, 25), (25, 30), (30, 100)]

    def get_regime(v):
        for i, (lo, hi) in enumerate(regime_bounds):
            if lo <= v < hi:
                return regime_labels[i]
        return 'crisis'

    transitions = {r: {r2: 0 for r2 in regime_labels} for r in regime_labels}
    for i in range(1, n):
        r_prev = get_regime(vix[i-1])
        r_curr = get_regime(vix[i])
        transitions[r_prev][r_curr] += 1

    # Convert to probabilities
    transition_probs = {}
    for r in regime_labels:
        total = sum(transitions[r].values())
        if total > 0:
            probs = {r2: round(transitions[r][r2] / total * 100, 1) for r2 in regime_labels}
            transition_probs[r] = probs
            print(f"  From {r:>10}: " + " | ".join(f"{r2}: {probs[r2]:5.1f}%" for r2 in regime_labels))

    results['transitions'] = transition_probs

    # Regime persistence: how long does each regime typically last?
    print("\n--- Regime Persistence ---")
    persistence = {r: [] for r in regime_labels}
    current_regime = get_regime(vix[0])
    current_duration = 1
    for i in range(1, n):
        r = get_regime(vix[i])
        if r == current_regime:
            current_duration += 1
        else:
            persistence[current_regime].append(current_duration)
            current_regime = r
            current_duration = 1
    persistence[current_regime].append(current_duration)

    for r in regime_labels:
        durations = persistence[r]
        if len(durations) > 0:
            results[r]['persistence_mean_days'] = round(float(np.mean(durations)), 1)
            results[r]['persistence_median_days'] = round(float(np.median(durations)), 1)
            results[r]['persistence_max_days'] = int(np.max(durations))
            results[r]['n_episodes'] = len(durations)
            print(f"  {r:>10}: mean={np.mean(durations):.1f}d, median={np.median(durations):.1f}d, max={np.max(durations)}d, episodes={len(durations)}")

    return results


def analysis5_optimal_check_frequency(data):
    """Analysis 5: How often should investors check VIX?"""
    print("\n" + "=" * 70)
    print("ANALYSIS 5: OPTIMAL CHECK FREQUENCY")
    print("=" * 70)
    print("Compare daily vs weekly vs monthly VIX checking + 12/VIX rebalancing")

    spy_ret = data['spy_ret'].values
    gld_ret = data['gld_ret'].values
    vix = data['vix_close'].values
    n = len(data)

    frequencies = {
        'daily': 1,
        'every_2d': 2,
        'weekly': 5,
        'biweekly': 10,
        'monthly': 21,
    }

    results = {}
    print(f"\n{'Frequency':>12} | {'Rebalances':>10} | {'CAGR':>8} | {'Vol':>8} | {'Sharpe':>8} | {'MDD':>8} | {'Net Sharpe':>10}")
    print("-" * 80)

    for freq_name, freq_days in frequencies.items():
        equity = np.zeros(n)
        equity[0] = 1.0
        current_w = np.clip(12.0 / vix[0], 0, 1)
        n_rebal = 0
        total_tx = 0

        for i in range(1, n):
            tx = 0
            if i % freq_days == 0:
                new_w = np.clip(12.0 / vix[i], 0, 1)
                w_change = abs(new_w - current_w)
                if w_change > 0.001:
                    n_rebal += 1
                    tx = w_change * TX_COST_BPS / 10000
                    total_tx += tx
                current_w = new_w

            port_r = current_w * spy_ret[i] + (1 - current_w) * gld_ret[i] - tx
            equity[i] = equity[i-1] * (1 + port_r)

        years = n / 252
        cagr = (equity[-1] / equity[0]) ** (1 / years) - 1
        daily_ret = np.diff(equity) / equity[:-1]
        vol = np.std(daily_ret) * np.sqrt(252)
        sharpe = (np.mean(daily_ret) * 252) / vol if vol > 0 else 0

        running_max = np.maximum.accumulate(equity)
        drawdowns = (equity - running_max) / running_max
        mdd = np.min(drawdowns)

        print(f"  {freq_name:>10} | {n_rebal:>10} | {cagr*100:>7.2f}% | {vol*100:>7.2f}% | {sharpe:>7.3f} | {mdd*100:>7.2f}% | {sharpe:>9.3f}")

        results[freq_name] = {
            'check_frequency_days': freq_days,
            'n_rebalances': n_rebal,
            'rebalances_per_year': round(n_rebal / years, 1),
            'cagr_pct': round(cagr * 100, 3),
            'annual_vol_pct': round(vol * 100, 3),
            'sharpe': round(sharpe, 4),
            'max_drawdown_pct': round(mdd * 100, 2),
            'total_tx_cost_pct': round(total_tx * 100, 3),
        }

    return results


def build_action_guide(regime_results, change_results, act_results, best_thresh):
    """Build the final VIX Action Guide."""
    print("\n" + "=" * 70)
    print("FINAL: VIX ACTION GUIDE FOR RETAIL INVESTORS")
    print("=" * 70)

    guide = {}

    for key in ['calm', 'normal', 'elevated', 'high', 'crisis']:
        r = regime_results[key]
        guide[key] = {
            'vix_range': r['vix_range'],
            'label': r['label'],
            'pct_of_time': r['pct_days'],
            'recommended_equity_weight': r['recommended_12vix_weight'],
            'advice': r['advice'],
            'expected_20d_spy_return_pct': r.get('fwd_20d_mean_pct', None),
            'expected_252d_spy_return_pct': r.get('fwd_252d_mean_pct', None),
            'win_rate_20d': r.get('fwd_20d_win_rate', None),
            'spy_annualized_vol': r.get('spy_ann_vol_pct', None),
            'typical_duration_days': r.get('persistence_median_days', None),
        }

    print("\n  GUIDE:")
    for key in ['calm', 'normal', 'elevated', 'high', 'crisis']:
        g = guide[key]
        print(f"\n  [{g['label']}] VIX {g['vix_range']}")
        print(f"    Occurs {g['pct_of_time']:.1f}% of the time")
        print(f"    Recommended equity: {g['recommended_equity_weight']:.0f}%")
        print(f"    Expected 20d SPY return: {g['expected_20d_spy_return_pct']:.2f}%")
        print(f"    20d win rate: {g['win_rate_20d']:.1f}%")
        print(f"    SPY annualized vol: {g['spy_annualized_vol']:.1f}%")
        print(f"    Typical duration: {g['typical_duration_days']:.0f} days")
        print(f"    ACTION: {g['advice']}")

    # Add spike advice
    guide['spike_guidance'] = {
        'description': 'When VIX moves sharply in a single day',
        'small_move': {
            'vix_change_range': '1-3 points',
            'action': 'Ignore — normal fluctuation',
            'rationale': 'Occurs frequently, not predictive'
        },
        'moderate_move': {
            'vix_change_range': '3-5 points',
            'action': 'Monitor — check regime, may warrant adjustment',
            'rationale': 'May signal regime shift'
        },
        'large_spike': {
            'vix_change_range': '5+ points',
            'action': 'ACT — adjust to target weight immediately',
            'rationale': f'Historically followed by {change_results.get("5", {}).get("spike_up_20d_mean", "N/A")}% 20d return'
        },
        'extreme_spike': {
            'vix_change_range': '10+ points',
            'action': 'Crisis protocol — minimum exposure, consider contrarian entry plan',
            'rationale': 'Very rare, often near market bottoms'
        }
    }

    # Optimal rebalancing threshold
    guide['optimal_rebalancing'] = {
        'best_threshold_vix_points': int(best_thresh),
        'description': f'Only rebalance when |dVIX| > {best_thresh} points',
        'net_sharpe': act_results[best_thresh]['net_sharpe'],
        'trades_per_year': act_results[best_thresh]['trades_per_year'],
    }

    return guide


def main():
    """Main execution."""
    start_time = datetime.now()

    # Download data
    data = download_data()

    # Descriptive statistics
    desc_stats = descriptive_stats(data)

    # Analysis 1: VIX level thresholds
    level_results = analysis1_level_thresholds(data)

    # Analysis 2: VIX change (spike) thresholds
    change_results = analysis2_vix_change_thresholds(data)

    # Analysis 3: Act vs ignore threshold
    act_results, best_thresh = analysis3_act_vs_ignore(data)

    # Analysis 4: VIX Action Guide
    regime_results = analysis4_vix_action_guide(data)

    # Analysis 5: Check frequency
    freq_results = analysis5_optimal_check_frequency(data)

    # Build action guide
    action_guide = build_action_guide(regime_results, change_results, act_results, best_thresh)

    # Save results
    elapsed = (datetime.now() - start_time).total_seconds()

    all_results = {
        'experiment_id': 'K652',
        'title': 'Practical VIX Action Thresholds — When Should Investors Act?',
        'type': 'empirical_analysis',
        'data_source': 'yfinance (SPY, GLD, ^VIX)',
        'data_period': f'{START_DATE} to {END_DATE}',
        'n_observations': len(data),
        'date_range': f"{data.index[0].strftime('%Y-%m-%d')} to {data.index[-1].strftime('%Y-%m-%d')}",
        'run_timestamp': datetime.now().isoformat(),
        'elapsed_seconds': round(elapsed, 1),
        'references': [
            'Whaley (2000) The Investor Fear Gauge, JPC',
            'Szado (2009) VIX Futures and Options, JPM',
            'Giot (2005) Implied Volatility Indexes and Stock Returns',
            'Simon & Wiggins (2001) Contrary Sentiment, JFQA',
        ],
        'descriptive_stats': desc_stats,
        'analysis1_level_thresholds': level_results,
        'analysis2_vix_changes': change_results,
        'analysis3_act_vs_ignore': act_results,
        'analysis3_best_threshold': best_thresh,
        'analysis4_regime_guide': regime_results,
        'analysis5_check_frequency': freq_results,
        'vix_action_guide': action_guide,
    }

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"\n1. VIX Level Thresholds: {len(level_results)} thresholds analyzed")
    print(f"2. VIX Change Thresholds: {len(change_results)} spike sizes analyzed")
    print(f"3. Optimal Act Threshold: dVIX > {best_thresh} points")
    print(f"   Net Sharpe = {act_results[best_thresh]['net_sharpe']:.4f}")
    print(f"   Trades/year = {act_results[best_thresh]['trades_per_year']:.1f}")
    print(f"4. Regime Guide: 5 regimes validated with forward returns")
    print(f"5. Check Frequency: {len(freq_results)} frequencies tested")
    print(f"\nElapsed: {elapsed:.1f}s")

    with open(RESULTS_FILE, 'w') as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"\nResults saved to {RESULTS_FILE}")

    return all_results


if __name__ == '__main__':
    main()
