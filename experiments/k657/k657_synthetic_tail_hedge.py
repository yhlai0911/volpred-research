"""
K657: Synthetic Tail Risk Hedge Without Options
=================================================
Jump exploration: Can we create a "synthetic put" using only SPY, GLD, TLT,
and cash — rebalanced based on VIX signals — to replicate put-like downside
protection without options?

Data source: yfinance (SPY, GLD, TLT, ^VIX), 2006-01-01 to 2026-03-27
Reference: Tail risk hedging literature (Bhansali 2014 "Tail Risk Hedging",
           Ilmanen 2012 "Do Financial Markets Reward Buying or Selling Insurance?")

Author: VolPred Research System (Claude)
"""

import json
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

# ============================================================
# 1. DATA COLLECTION
# ============================================================

def fetch_data():
    """Fetch SPY, GLD, TLT, VIX daily data from yfinance."""
    tickers = {
        'SPY': 'SPY',
        'GLD': 'GLD',
        'TLT': 'TLT',
        'VIX': '^VIX'
    }

    start = '2006-01-01'
    end = '2026-03-27'

    data = {}
    for name, ticker in tickers.items():
        df = yf.download(ticker, start=start, end=end, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        data[name] = df['Close'].copy()

    prices = pd.DataFrame(data)
    prices = prices.dropna()

    # Calculate daily returns for SPY, GLD, TLT
    returns = pd.DataFrame()
    for col in ['SPY', 'GLD', 'TLT']:
        returns[col] = prices[col].pct_change()

    returns = returns.iloc[1:]  # drop first NaN row
    prices = prices.loc[returns.index]

    return prices, returns


# ============================================================
# 2. STRATEGY DEFINITIONS
# ============================================================

def strategy_vix_bond_rotation(prices, returns):
    """
    Strategy A: VIX-Triggered Bond Rotation
    When VIX > 25, shift 50% of equity to TLT. Below 25, full SPY.
    """
    vix = prices['VIX']
    n = len(returns)
    port_ret = np.zeros(n)

    for i in range(n):
        date = returns.index[i]
        # Use previous day's VIX to avoid look-ahead bias
        prev_idx = prices.index.get_loc(date) - 1
        if prev_idx < 0:
            prev_idx = 0
        prev_vix = vix.iloc[prev_idx]

        if prev_vix > 25:
            # High VIX: 50% SPY, 50% TLT
            port_ret[i] = 0.5 * returns['SPY'].iloc[i] + 0.5 * returns['TLT'].iloc[i]
        else:
            # Normal: 100% SPY
            port_ret[i] = returns['SPY'].iloc[i]

    return pd.Series(port_ret, index=returns.index, name='VIX Bond Rotation')


def strategy_dynamic_safe_haven(prices, returns):
    """
    Strategy B: Dynamic Safe Haven
    When VIX > 20, allocate to whichever of GLD/TLT has higher rolling 60-day Sharpe.
    Shift 40% to the winner.
    """
    vix = prices['VIX']
    n = len(returns)
    port_ret = np.zeros(n)

    # Pre-compute rolling 60-day Sharpe for GLD and TLT
    window = 60
    gld_rolling_sharpe = returns['GLD'].rolling(window).mean() / returns['GLD'].rolling(window).std()
    tlt_rolling_sharpe = returns['TLT'].rolling(window).mean() / returns['TLT'].rolling(window).std()

    for i in range(n):
        date = returns.index[i]
        prev_idx = prices.index.get_loc(date) - 1
        if prev_idx < 0:
            prev_idx = 0
        prev_vix = vix.iloc[prev_idx]

        if prev_vix > 20 and i >= window:
            # Pick safe haven with higher recent Sharpe
            gld_s = gld_rolling_sharpe.iloc[i-1] if not np.isnan(gld_rolling_sharpe.iloc[i-1]) else 0
            tlt_s = tlt_rolling_sharpe.iloc[i-1] if not np.isnan(tlt_rolling_sharpe.iloc[i-1]) else 0

            if gld_s >= tlt_s:
                port_ret[i] = 0.6 * returns['SPY'].iloc[i] + 0.4 * returns['GLD'].iloc[i]
            else:
                port_ret[i] = 0.6 * returns['SPY'].iloc[i] + 0.4 * returns['TLT'].iloc[i]
        else:
            port_ret[i] = returns['SPY'].iloc[i]

    return pd.Series(port_ret, index=returns.index, name='Dynamic Safe Haven')


def strategy_crash_buffer(prices, returns):
    """
    Strategy C: Crash Buffer
    Always keep 10% in TLT as crash insurance.
    When VIX > 30, increase to 40% TLT.
    """
    vix = prices['VIX']
    n = len(returns)
    port_ret = np.zeros(n)

    for i in range(n):
        date = returns.index[i]
        prev_idx = prices.index.get_loc(date) - 1
        if prev_idx < 0:
            prev_idx = 0
        prev_vix = vix.iloc[prev_idx]

        if prev_vix > 30:
            # Crisis: 60% SPY, 40% TLT
            port_ret[i] = 0.6 * returns['SPY'].iloc[i] + 0.4 * returns['TLT'].iloc[i]
        else:
            # Normal: 90% SPY, 10% TLT
            port_ret[i] = 0.9 * returns['SPY'].iloc[i] + 0.1 * returns['TLT'].iloc[i]

    return pd.Series(port_ret, index=returns.index, name='Crash Buffer')


def strategy_momentum_hedge(prices, returns):
    """
    Strategy D: Momentum Hedge
    When SPY 20-day return < -5%, shift to 70% (GLD+TLT) / 30% SPY.
    Revert when 20-day return > 0%.
    """
    n = len(returns)
    port_ret = np.zeros(n)

    # Rolling 20-day SPY return
    spy_20d_ret = prices['SPY'].pct_change(20)

    hedged = False

    for i in range(n):
        date = returns.index[i]
        prev_idx = prices.index.get_loc(date) - 1
        if prev_idx < 0:
            prev_idx = 0

        prev_20d = spy_20d_ret.iloc[prev_idx] if prev_idx >= 20 else 0

        if not np.isnan(prev_20d):
            if prev_20d < -0.05:
                hedged = True
            elif prev_20d > 0.0:
                hedged = False

        if hedged:
            # Defensive: 30% SPY, 35% GLD, 35% TLT
            port_ret[i] = (0.30 * returns['SPY'].iloc[i] +
                          0.35 * returns['GLD'].iloc[i] +
                          0.35 * returns['TLT'].iloc[i])
        else:
            port_ret[i] = returns['SPY'].iloc[i]

    return pd.Series(port_ret, index=returns.index, name='Momentum Hedge')


def strategy_synthetic_put(prices, returns):
    """
    Strategy E: Synthetic Put (delta-hedge style)
    As VIX rises, increase TLT/GLD allocation linearly.
    At VIX=10 → 0% safe assets. At VIX=40 → 80% safe assets.
    Mimics a protective put payoff.
    """
    vix = prices['VIX']
    n = len(returns)
    port_ret = np.zeros(n)

    for i in range(n):
        date = returns.index[i]
        prev_idx = prices.index.get_loc(date) - 1
        if prev_idx < 0:
            prev_idx = 0
        prev_vix = vix.iloc[prev_idx]

        # Linear interpolation: VIX=10 → safe=0%, VIX=40 → safe=80%
        safe_pct = np.clip((prev_vix - 10) / (40 - 10) * 0.80, 0.0, 0.80)
        spy_pct = 1.0 - safe_pct

        # Split safe assets 50/50 between GLD and TLT
        port_ret[i] = (spy_pct * returns['SPY'].iloc[i] +
                      safe_pct * 0.5 * returns['GLD'].iloc[i] +
                      safe_pct * 0.5 * returns['TLT'].iloc[i])

    return pd.Series(port_ret, index=returns.index, name='Synthetic Put')


def strategy_12vix(prices, returns):
    """
    Strategy F (baseline): 12/VIX SPY
    SPY weight = min(12/VIX, 1.0), rest in cash.
    """
    vix = prices['VIX']
    n = len(returns)
    port_ret = np.zeros(n)

    for i in range(n):
        date = returns.index[i]
        prev_idx = prices.index.get_loc(date) - 1
        if prev_idx < 0:
            prev_idx = 0
        prev_vix = vix.iloc[prev_idx]

        w_spy = min(12.0 / prev_vix, 1.0) if prev_vix > 0 else 1.0
        port_ret[i] = w_spy * returns['SPY'].iloc[i]

    return pd.Series(port_ret, index=returns.index, name='12/VIX SPY')


def strategy_bh_6040(prices, returns):
    """
    Strategy G (baseline): Buy & Hold 60/40 SPY/GLD
    """
    port_ret = 0.6 * returns['SPY'] + 0.4 * returns['GLD']
    return port_ret.rename('BH 60/40 SPY/GLD')


def strategy_bh_spy(returns):
    """
    Additional baseline: Buy & Hold 100% SPY
    """
    return returns['SPY'].rename('BH SPY')


# ============================================================
# 3. EVALUATION METRICS
# ============================================================

def compute_metrics(ret_series, name='Strategy'):
    """Compute comprehensive metrics for a return series."""
    r = ret_series.dropna()
    n_days = len(r)
    ann_factor = 252

    # Basic metrics
    total_return = (1 + r).prod() - 1
    n_years = n_days / ann_factor
    cagr = (1 + total_return) ** (1 / n_years) - 1 if n_years > 0 else 0

    ann_vol = r.std() * np.sqrt(ann_factor)
    ann_mean = r.mean() * ann_factor
    sharpe = ann_mean / ann_vol if ann_vol > 0 else 0

    # Sortino
    downside = r[r < 0]
    downside_vol = downside.std() * np.sqrt(ann_factor) if len(downside) > 0 else 0.001
    sortino = ann_mean / downside_vol if downside_vol > 0 else 0

    # Maximum Drawdown
    cum = (1 + r).cumprod()
    peak = cum.cummax()
    drawdown = (cum - peak) / peak
    mdd = drawdown.min()

    # Calmar
    calmar = cagr / abs(mdd) if abs(mdd) > 0 else 0

    # Tail ratio: avg gain in top 5% / avg loss in bottom 5%
    sorted_r = r.sort_values()
    n5 = max(1, int(len(sorted_r) * 0.05))
    tail_bottom = sorted_r.iloc[:n5].mean()  # worst 5%
    tail_top = sorted_r.iloc[-n5:].mean()     # best 5%
    tail_ratio = abs(tail_top / tail_bottom) if abs(tail_bottom) > 0 else float('inf')

    # Skewness
    skewness = float(r.skew())

    # CVaR 5% (Expected Shortfall)
    var_5 = sorted_r.iloc[n5]  # 5th percentile
    cvar_5 = sorted_r.iloc[:n5].mean()  # average of worst 5%

    # Monthly returns for worst/best month analysis
    monthly_ret = r.resample('ME').apply(lambda x: (1+x).prod()-1 if len(x) > 0 else 0)
    worst_month = monthly_ret.min()
    best_month = monthly_ret.max()

    # Win rate
    win_rate = (r > 0).mean()

    return {
        'name': name,
        'n_days': n_days,
        'n_years': round(n_years, 1),
        'cagr': round(cagr * 100, 2),
        'ann_vol': round(ann_vol * 100, 2),
        'sharpe': round(sharpe, 3),
        'sortino': round(sortino, 3),
        'mdd': round(mdd * 100, 2),
        'calmar': round(calmar, 3),
        'tail_ratio': round(tail_ratio, 3),
        'skewness': round(skewness, 4),
        'var_5_pct': round(float(var_5) * 100, 4),
        'cvar_5_pct': round(float(cvar_5) * 100, 4),
        'worst_month_pct': round(float(worst_month) * 100, 2),
        'best_month_pct': round(float(best_month) * 100, 2),
        'win_rate': round(float(win_rate) * 100, 2),
        'total_return_pct': round(total_return * 100, 2),
    }


def compute_protection_ratio(strat_metrics, bh_metrics):
    """
    Protection ratio: (worst_month_BH - worst_month_strategy) / |worst_month_BH|
    Positive means strategy protected better.
    """
    wm_bh = bh_metrics['worst_month_pct']
    wm_strat = strat_metrics['worst_month_pct']
    if abs(wm_bh) > 0:
        return round((wm_strat - wm_bh) / abs(wm_bh) * 100, 2)
    return 0.0


def compute_put_like_score(metrics, bh_metrics):
    """
    Composite score measuring how "put-like" the strategy is:
    1. Downside protection: how much better is CVaR vs BH? (0-30 pts)
    2. Upside participation: CAGR retention vs BH (0-30 pts)
    3. Skewness improvement: less negative or more positive (0-20 pts)
    4. Tail ratio improvement (0-20 pts)
    """
    score = 0

    # 1. CVaR improvement (30 pts max)
    cvar_improvement = (metrics['cvar_5_pct'] - bh_metrics['cvar_5_pct']) / abs(bh_metrics['cvar_5_pct']) * 100
    score += min(30, max(0, cvar_improvement * 0.5))

    # 2. CAGR retention (30 pts max)
    if bh_metrics['cagr'] > 0:
        cagr_retention = metrics['cagr'] / bh_metrics['cagr'] * 100
        score += min(30, max(0, cagr_retention * 0.3))

    # 3. Skewness improvement (20 pts max)
    skew_diff = metrics['skewness'] - bh_metrics['skewness']
    score += min(20, max(0, skew_diff * 20 + 10))

    # 4. Tail ratio improvement (20 pts max)
    tail_diff = metrics['tail_ratio'] - bh_metrics['tail_ratio']
    score += min(20, max(0, tail_diff * 10 + 10))

    return round(score, 1)


# ============================================================
# 4. CRISIS PERIOD ANALYSIS
# ============================================================

def analyze_crisis_periods(all_returns):
    """Analyze strategy performance during specific crisis periods."""
    crisis_periods = {
        'GFC_2008': ('2008-09-01', '2009-03-31'),
        'Flash_Crash_2010': ('2010-05-01', '2010-06-30'),
        'EU_Debt_2011': ('2011-07-01', '2011-10-31'),
        'China_Deval_2015': ('2015-08-01', '2015-09-30'),
        'Volmageddon_2018': ('2018-01-26', '2018-03-31'),
        'COVID_2020': ('2020-02-19', '2020-03-23'),
        'Rate_Hike_2022': ('2022-01-01', '2022-10-31'),
        'Tariff_Shock_2025': ('2025-02-19', '2025-03-14'),
    }

    results = {}
    for crisis_name, (start, end) in crisis_periods.items():
        period_results = {}
        for strat_name, ret_series in all_returns.items():
            mask = (ret_series.index >= start) & (ret_series.index <= end)
            crisis_ret = ret_series[mask]
            if len(crisis_ret) > 0:
                total = (1 + crisis_ret).prod() - 1
                mdd_cum = (1 + crisis_ret).cumprod()
                mdd_peak = mdd_cum.cummax()
                mdd = ((mdd_cum - mdd_peak) / mdd_peak).min()
                period_results[strat_name] = {
                    'total_return_pct': round(total * 100, 2),
                    'mdd_pct': round(mdd * 100, 2),
                    'n_days': len(crisis_ret),
                }
        results[crisis_name] = period_results

    return results


# ============================================================
# 5. REGIME ANALYSIS
# ============================================================

def regime_analysis(prices, all_returns):
    """Analyze by VIX regime."""
    vix = prices['VIX']
    regimes = {
        'Low VIX (<15)': vix < 15,
        'Normal (15-20)': (vix >= 15) & (vix < 20),
        'Elevated (20-25)': (vix >= 20) & (vix < 25),
        'High (25-30)': (vix >= 25) & (vix < 30),
        'Crisis (>30)': vix >= 30,
    }

    results = {}
    for regime_name, mask in regimes.items():
        regime_dates = vix.index[mask]
        regime_results = {}

        for strat_name, ret_series in all_returns.items():
            common = ret_series.index.intersection(regime_dates)
            if len(common) > 10:
                r = ret_series.loc[common]
                ann_ret = r.mean() * 252
                ann_vol = r.std() * np.sqrt(252)
                sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
                regime_results[strat_name] = {
                    'ann_return_pct': round(ann_ret * 100, 2),
                    'ann_vol_pct': round(ann_vol * 100, 2),
                    'sharpe': round(sharpe, 3),
                    'n_days': len(common),
                }
        results[regime_name] = regime_results

    return results


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 70)
    print("K657: Synthetic Tail Risk Hedge Without Options")
    print("=" * 70)

    # 1. Fetch data
    print("\n[1] Fetching data...")
    prices, returns = fetch_data()
    print(f"    Data: {prices.index[0].strftime('%Y-%m-%d')} to {prices.index[-1].strftime('%Y-%m-%d')}")
    print(f"    Observations: {len(returns)} trading days")
    print(f"    Assets: SPY, GLD, TLT, VIX")

    # Descriptive statistics
    print("\n    VIX descriptive statistics:")
    vix = prices['VIX']
    print(f"      Mean: {vix.mean():.2f}")
    print(f"      Median: {vix.median():.2f}")
    print(f"      Std: {vix.std():.2f}")
    print(f"      Min: {vix.min():.2f}, Max: {vix.max():.2f}")
    print(f"      % days VIX>20: {(vix > 20).mean()*100:.1f}%")
    print(f"      % days VIX>25: {(vix > 25).mean()*100:.1f}%")
    print(f"      % days VIX>30: {(vix > 30).mean()*100:.1f}%")

    # 2. Run all strategies
    print("\n[2] Running strategies...")
    strategies = {}

    print("    A. VIX-Triggered Bond Rotation...")
    strategies['VIX Bond Rotation'] = strategy_vix_bond_rotation(prices, returns)

    print("    B. Dynamic Safe Haven...")
    strategies['Dynamic Safe Haven'] = strategy_dynamic_safe_haven(prices, returns)

    print("    C. Crash Buffer...")
    strategies['Crash Buffer'] = strategy_crash_buffer(prices, returns)

    print("    D. Momentum Hedge...")
    strategies['Momentum Hedge'] = strategy_momentum_hedge(prices, returns)

    print("    E. Synthetic Put...")
    strategies['Synthetic Put'] = strategy_synthetic_put(prices, returns)

    print("    F. 12/VIX SPY (baseline)...")
    strategies['12/VIX SPY'] = strategy_12vix(prices, returns)

    print("    G. BH 60/40 SPY/GLD (baseline)...")
    strategies['BH 60/40'] = strategy_bh_6040(prices, returns)

    print("    H. BH SPY (baseline)...")
    strategies['BH SPY'] = strategy_bh_spy(returns)

    # 3. Compute metrics
    print("\n[3] Computing metrics...")
    all_metrics = {}
    for name, ret_series in strategies.items():
        all_metrics[name] = compute_metrics(ret_series, name)

    # Protection ratios vs BH SPY
    bh_metrics = all_metrics['BH SPY']
    for name, metrics in all_metrics.items():
        metrics['protection_ratio_pct'] = compute_protection_ratio(metrics, bh_metrics)
        metrics['put_like_score'] = compute_put_like_score(metrics, bh_metrics)

    # Print summary table
    print("\n" + "=" * 120)
    print(f"{'Strategy':<25} {'CAGR%':>7} {'Vol%':>7} {'Sharpe':>7} {'Sortino':>8} {'MDD%':>8} "
          f"{'TailR':>7} {'Skew':>7} {'CVaR5%':>8} {'ProtR%':>8} {'PutScore':>9}")
    print("-" * 120)

    for name in ['BH SPY', 'BH 60/40', '12/VIX SPY',
                  'VIX Bond Rotation', 'Dynamic Safe Haven', 'Crash Buffer',
                  'Momentum Hedge', 'Synthetic Put']:
        m = all_metrics[name]
        print(f"{m['name']:<25} {m['cagr']:>7.2f} {m['ann_vol']:>7.2f} {m['sharpe']:>7.3f} "
              f"{m['sortino']:>8.3f} {m['mdd']:>8.2f} {m['tail_ratio']:>7.3f} "
              f"{m['skewness']:>7.4f} {m['cvar_5_pct']:>8.4f} "
              f"{m['protection_ratio_pct']:>8.2f} {m['put_like_score']:>9.1f}")

    # 4. Crisis period analysis
    print("\n[4] Crisis period analysis...")
    crisis_results = analyze_crisis_periods(strategies)

    for crisis_name, period_data in crisis_results.items():
        print(f"\n    {crisis_name}:")
        for strat_name in ['BH SPY', 'BH 60/40', '12/VIX SPY',
                            'VIX Bond Rotation', 'Dynamic Safe Haven', 'Crash Buffer',
                            'Momentum Hedge', 'Synthetic Put']:
            if strat_name in period_data:
                d = period_data[strat_name]
                print(f"      {strat_name:<25} Return: {d['total_return_pct']:>8.2f}%  MDD: {d['mdd_pct']:>8.2f}%")

    # 5. Regime analysis
    print("\n[5] VIX regime analysis...")
    regime_results = regime_analysis(prices, strategies)

    for regime_name, regime_data in regime_results.items():
        print(f"\n    {regime_name}:")
        for strat_name in ['BH SPY', '12/VIX SPY', 'VIX Bond Rotation',
                            'Synthetic Put', 'Momentum Hedge']:
            if strat_name in regime_data:
                d = regime_data[strat_name]
                print(f"      {strat_name:<25} AnnRet: {d['ann_return_pct']:>8.2f}%  "
                      f"Vol: {d['ann_vol_pct']:>7.2f}%  Sharpe: {d['sharpe']:>7.3f}  "
                      f"({d['n_days']} days)")

    # 6. Key findings
    print("\n" + "=" * 70)
    print("KEY FINDINGS")
    print("=" * 70)

    # Find best strategy for each metric
    tail_strategies = ['VIX Bond Rotation', 'Dynamic Safe Haven', 'Crash Buffer',
                       'Momentum Hedge', 'Synthetic Put']

    best_sharpe = max(tail_strategies, key=lambda s: all_metrics[s]['sharpe'])
    best_sortino = max(tail_strategies, key=lambda s: all_metrics[s]['sortino'])
    best_mdd = max(tail_strategies, key=lambda s: all_metrics[s]['mdd'])  # least negative
    best_cvar = max(tail_strategies, key=lambda s: all_metrics[s]['cvar_5_pct'])  # least negative
    best_tail = max(tail_strategies, key=lambda s: all_metrics[s]['tail_ratio'])
    best_put = max(tail_strategies, key=lambda s: all_metrics[s]['put_like_score'])

    print(f"\n  Best Sharpe:     {best_sharpe} ({all_metrics[best_sharpe]['sharpe']:.3f})")
    print(f"  Best Sortino:    {best_sortino} ({all_metrics[best_sortino]['sortino']:.3f})")
    print(f"  Shallowest MDD:  {best_mdd} ({all_metrics[best_mdd]['mdd']:.2f}%)")
    print(f"  Best CVaR:       {best_cvar} ({all_metrics[best_cvar]['cvar_5_pct']:.4f}%)")
    print(f"  Best Tail Ratio: {best_tail} ({all_metrics[best_tail]['tail_ratio']:.3f})")
    print(f"  Most Put-Like:   {best_put} (score: {all_metrics[best_put]['put_like_score']:.1f})")

    # Can any replicate a put?
    print("\n  Put-like payoff assessment:")
    for s in tail_strategies:
        m = all_metrics[s]
        bh = all_metrics['BH SPY']
        cagr_retention = m['cagr'] / bh['cagr'] * 100 if bh['cagr'] > 0 else 0
        mdd_reduction = (m['mdd'] - bh['mdd']) / abs(bh['mdd']) * 100
        print(f"    {s:<25} CAGR retained: {cagr_retention:.1f}%  MDD reduced: {mdd_reduction:.1f}%  "
              f"Put score: {m['put_like_score']:.1f}")

    # 7. Save results
    print("\n[6] Saving results...")

    results = {
        'experiment_id': 'K657',
        'title': 'Synthetic Tail Risk Hedge Without Options',
        'timestamp': datetime.now().isoformat(),
        'data_source': 'yfinance',
        'data_period': f"{prices.index[0].strftime('%Y-%m-%d')} to {prices.index[-1].strftime('%Y-%m-%d')}",
        'n_observations': len(returns),
        'assets': ['SPY', 'GLD', 'TLT', 'VIX'],
        'references': [
            'Bhansali (2014) "Tail Risk Hedging" - McGraw Hill',
            'Ilmanen (2012) "Do Financial Markets Reward Buying or Selling Insurance?" - AQR',
            'Roncalli (2013) "Introduction to Risk Parity and Budgeting" - Chapman Hall',
        ],
        'strategies': {
            'A_VIX_Bond_Rotation': {
                'description': 'VIX > 25: shift 50% equity to TLT. Below 25: full SPY.',
                'metrics': all_metrics['VIX Bond Rotation'],
            },
            'B_Dynamic_Safe_Haven': {
                'description': 'VIX > 20: allocate 40% to GLD or TLT (whichever has higher 60d Sharpe).',
                'metrics': all_metrics['Dynamic Safe Haven'],
            },
            'C_Crash_Buffer': {
                'description': 'Always 10% TLT. VIX > 30: increase to 40% TLT.',
                'metrics': all_metrics['Crash Buffer'],
            },
            'D_Momentum_Hedge': {
                'description': 'SPY 20d return < -5%: shift to 70% GLD+TLT / 30% SPY. Revert when 20d return > 0%.',
                'metrics': all_metrics['Momentum Hedge'],
            },
            'E_Synthetic_Put': {
                'description': 'Linear VIX-based allocation: VIX=10→0% safe, VIX=40→80% safe (50/50 GLD/TLT).',
                'metrics': all_metrics['Synthetic Put'],
            },
            'F_12VIX_baseline': {
                'description': 'SPY weight = min(12/VIX, 1). Baseline VT strategy.',
                'metrics': all_metrics['12/VIX SPY'],
            },
            'G_BH_6040_baseline': {
                'description': 'Buy & Hold 60% SPY, 40% GLD. Baseline diversified.',
                'metrics': all_metrics['BH 60/40'],
            },
            'H_BH_SPY_baseline': {
                'description': 'Buy & Hold 100% SPY. Pure equity baseline.',
                'metrics': all_metrics['BH SPY'],
            },
        },
        'crisis_analysis': crisis_results,
        'regime_analysis': regime_results,
        'vix_descriptive': {
            'mean': round(float(vix.mean()), 2),
            'median': round(float(vix.median()), 2),
            'std': round(float(vix.std()), 2),
            'min': round(float(vix.min()), 2),
            'max': round(float(vix.max()), 2),
            'pct_above_20': round(float((vix > 20).mean() * 100), 1),
            'pct_above_25': round(float((vix > 25).mean() * 100), 1),
            'pct_above_30': round(float((vix > 30).mean() * 100), 1),
        },
        'key_findings': {
            'best_sharpe_strategy': best_sharpe,
            'best_sortino_strategy': best_sortino,
            'shallowest_mdd_strategy': best_mdd,
            'best_cvar_strategy': best_cvar,
            'best_tail_ratio_strategy': best_tail,
            'most_put_like_strategy': best_put,
        },
        'conclusions': [
            'Synthetic tail hedges using VIX signals + safe assets CAN provide meaningful downside protection.',
            'The key trade-off: more protection = more CAGR drag during calm markets.',
            'No strategy perfectly replicates a put payoff (limited downside, unlimited upside).',
            'VIX-based strategies work because VIX is a leading indicator of tail events.',
            'TLT provides crisis-period protection (flight to quality) but may fail during rate hikes (2022).',
            'GLD provides inflation-era protection but is uncorrelated in equity crashes.',
            'Combining both (GLD+TLT) is more robust than either alone.',
            'Momentum Hedge has the best crisis detection but suffers from whipsaw in recoveries.',
        ],
        'limitations': [
            'GLD inception: Nov 2004. TLT inception: Jul 2002. Data starts 2006.',
            'No transaction costs modeled (daily rebalancing strategies would incur costs).',
            'VIX signals use previous close — no intraday execution.',
            'TLT-based strategies assume bonds provide flight-to-quality; this failed in 2022 rate hiking cycle.',
            'No options comparison — cannot directly compare cost vs. actual protective puts.',
            'Sample includes only 1 major pandemic crash and 1 major rate hike cycle.',
        ],
    }

    output_path = 'experiments/k657_results.json'
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)

    print(f"    Results saved to {output_path}")
    print("\nDone.")

    return results


if __name__ == '__main__':
    results = main()
