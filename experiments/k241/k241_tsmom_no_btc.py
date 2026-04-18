"""
K241: TSMOM Robustness — Does It Survive Without BTC?
=====================================================
Background: K240 found cross-asset TSMOM passes Harvey (t=3.07, Sharpe 0.979).
BUT BTC is the dominant driver (25% weight, huge momentum).
This experiment validates whether TSMOM works WITHOUT Bitcoin.

Data: SPY, GLD, TLT daily from yfinance. 2005-2024 (20 years).
Methodology:
  1. TSMOM (12_1, 6_1, 3_1) on 3 assets: SPY, GLD, TLT
  2. Vol-scaled variant
  3. Benchmarks: SPY B&H, 50/50 SPY/GLD, 33/33/33 EW, 50/50+VT
  4. 5-period cross-OOS
  5. Harvey threshold (t>3.0), DM test
  6. Transaction costs: 5, 10, 20 bps

[提出: 用戶, 執行: Claude]
"""

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
import json
import warnings
warnings.filterwarnings('ignore')

# ============================================================
# 1. DATA DOWNLOAD
# ============================================================
def download_data():
    """Download SPY, GLD, TLT daily data from yfinance."""
    tickers = ['SPY', 'GLD', 'TLT']
    print("Downloading data from yfinance...")
    data = {}
    for ticker in tickers:
        df = yf.download(ticker, start='2004-06-01', end='2025-01-01', progress=False, auto_adjust=True)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        data[ticker] = df['Close']
        print(f"  {ticker}: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}, {len(df)} obs")

    prices = pd.DataFrame(data)
    prices = prices.dropna()
    print(f"\nCommon date range: {prices.index[0].strftime('%Y-%m-%d')} to {prices.index[-1].strftime('%Y-%m-%d')}")
    print(f"Total trading days: {len(prices)}")
    return prices


# ============================================================
# 2. TSMOM STRATEGY
# ============================================================
def compute_tsmom_returns(prices, lookback_months=12, skip_months=1, vol_scale=False,
                          target_vol=0.10, rebal_freq='M'):
    """
    Time-Series Momentum (TSMOM) strategy.

    For each asset:
      - Compute trailing `lookback_months` return (skip last `skip_months`)
      - If return > 0: go long; else: go to cash (0)
      - Equal-weight among assets with positive momentum
      - Monthly rebalance

    If vol_scale=True, scale position by inverse realized vol targeting target_vol.
    """
    assets = list(prices.columns)

    # Monthly prices for signal computation
    monthly_prices = prices.resample('ME').last()

    # Daily returns
    daily_returns = prices.pct_change().dropna()

    # Compute momentum signals at each month-end
    # Use vectorized approach: rolling return over lookback period (skipping last skip_months)
    # For 12_1: return from t-12 to t-1
    monthly_returns_cum = {}
    for col in assets:
        mom = monthly_prices[col].pct_change(lookback_months).shift(skip_months)
        monthly_returns_cum[col] = mom

    mom_df = pd.DataFrame(monthly_returns_cum)
    # Signal: 1 if momentum > 0, else 0
    signals = (mom_df > 0).astype(float)
    signals = signals.dropna(how='any')  # drop rows where any asset has NaN

    # Vol scaling
    if vol_scale:
        # 63-day realized vol (annualized)
        realized_vol = daily_returns.rolling(63).std() * np.sqrt(252)
        monthly_vol = realized_vol.resample('ME').last()
        vol_scalar = target_vol / monthly_vol.clip(lower=0.05)
        vol_scalar = vol_scalar.clip(upper=2.0)  # cap leverage at 2x

    # Build daily portfolio returns
    # At each month-end, determine weights for the next month
    portfolio_returns = pd.Series(0.0, index=daily_returns.index)

    # Get month-end dates that exist in signals
    signal_dates = signals.index

    for i in range(len(signal_dates) - 1):
        sig_date = signal_dates[i]
        next_sig_date = signal_dates[i + 1]

        # Current signals
        current_signals = signals.loc[sig_date]

        # Number of assets with positive momentum
        n_positive = current_signals.sum()

        if n_positive == 0:
            # All negative momentum -> 100% cash
            weights = pd.Series(0.0, index=assets)
        else:
            # Equal weight among positive-momentum assets
            weights = current_signals / n_positive

        if vol_scale and sig_date in monthly_vol.index:
            for col in weights.index:
                if weights[col] > 0 and sig_date in vol_scalar.index:
                    weights[col] *= vol_scalar.loc[sig_date, col]

        # Apply weights to daily returns for the next month
        mask = (daily_returns.index > sig_date) & (daily_returns.index <= next_sig_date)
        daily_slice = daily_returns.loc[mask]

        for col in assets:
            portfolio_returns.loc[mask] += weights[col] * daily_slice[col]

    return portfolio_returns


def compute_benchmark_returns(prices):
    """Compute benchmark strategy returns."""
    daily_returns = prices.pct_change().dropna()

    benchmarks = {}

    # 1. SPY Buy & Hold
    benchmarks['SPY_BH'] = daily_returns['SPY']

    # 2. 50/50 SPY/GLD Buy & Hold (monthly rebalance)
    benchmarks['50_50_SPY_GLD'] = 0.5 * daily_returns['SPY'] + 0.5 * daily_returns['GLD']

    # 3. 33/33/33 Equal Weight SPY/GLD/TLT (monthly rebalance)
    benchmarks['EW_SPY_GLD_TLT'] = (daily_returns['SPY'] + daily_returns['GLD'] + daily_returns['TLT']) / 3.0

    # 4. 50/50 SPY/GLD + VT overlay (approximate: reduce equity weight when VIX > 20)
    # Since we don't have VIX here easily, we'll use a simpler VT proxy:
    # Use realized vol of SPY > median as "high vol" -> reduce SPY weight
    spy_vol = daily_returns['SPY'].rolling(63).std() * np.sqrt(252)
    spy_vol_median = spy_vol.expanding().median()

    # Monthly signals for VT
    monthly_vol = spy_vol.resample('ME').last()
    monthly_vol_median = spy_vol_median.resample('ME').last()

    vt_returns = pd.Series(0.0, index=daily_returns.index)
    monthly_dates = monthly_vol.dropna().index

    for i in range(len(monthly_dates) - 1):
        sig_date = monthly_dates[i]
        next_date = monthly_dates[i + 1]

        mask = (daily_returns.index > sig_date) & (daily_returns.index <= next_date)

        if monthly_vol.loc[sig_date] > monthly_vol_median.loc[sig_date]:
            # High vol: 30/30/40 (reduce equity, increase bonds)
            w_spy, w_gld, w_tlt = 0.30, 0.30, 0.40
        else:
            # Low vol: 50/50/0
            w_spy, w_gld, w_tlt = 0.50, 0.50, 0.0

        vt_returns.loc[mask] = (w_spy * daily_returns['SPY'].loc[mask] +
                                w_gld * daily_returns['GLD'].loc[mask] +
                                w_tlt * daily_returns['TLT'].loc[mask])

    benchmarks['50_50_VT'] = vt_returns

    return benchmarks


# ============================================================
# 3. PERFORMANCE METRICS
# ============================================================
def compute_metrics(returns, rf_annual=0.02):
    """Compute performance metrics for a return series."""
    returns = returns.dropna()
    if len(returns) < 252:
        return {}

    ann_ret = returns.mean() * 252
    ann_vol = returns.std() * np.sqrt(252)
    sharpe = (ann_ret - rf_annual) / ann_vol if ann_vol > 0 else 0

    # Max Drawdown
    cum = (1 + returns).cumprod()
    rolling_max = cum.cummax()
    drawdown = cum / rolling_max - 1
    max_dd = drawdown.min()

    # Calmar ratio
    calmar = ann_ret / abs(max_dd) if max_dd != 0 else 0

    # Sortino ratio
    downside = returns[returns < 0]
    downside_vol = downside.std() * np.sqrt(252) if len(downside) > 10 else ann_vol
    sortino = (ann_ret - rf_annual) / downside_vol if downside_vol > 1e-8 else 0.0

    # Skewness, Kurtosis
    skew = returns.skew()
    kurt = returns.kurtosis()

    # Win rate
    win_rate = (returns > 0).mean()

    # Monthly returns for t-stat
    monthly_ret = (1 + returns).resample('ME').prod() - 1
    t_stat = monthly_ret.mean() / (monthly_ret.std() / np.sqrt(len(monthly_ret))) if monthly_ret.std() > 0 else 0

    # Time in market (for TSMOM: fraction of days with non-zero return)
    time_in_market = (returns != 0).mean()

    return {
        'ann_return': ann_ret,
        'ann_vol': ann_vol,
        'sharpe': sharpe,
        'max_dd': max_dd,
        'calmar': calmar,
        'sortino': sortino,
        'skew': skew,
        'kurtosis': kurt,
        'win_rate': win_rate,
        't_stat': t_stat,
        'n_months': len(monthly_ret),
        'time_in_market': time_in_market,
    }


def apply_transaction_costs(returns, signals_changes_per_year, cost_bps):
    """
    Approximate transaction cost impact.
    Reduce annual return by (turnover * cost_bps).
    For monthly rebalance TSMOM: ~12 potential rebalances/year,
    actual turnover depends on signal changes.
    """
    cost = signals_changes_per_year * (cost_bps / 10000.0) / 252.0  # daily cost drag
    adjusted = returns - cost
    return adjusted


# ============================================================
# 4. CROSS-OOS VALIDATION
# ============================================================
def cross_oos_validation(prices, lookback=12, skip=1, vol_scale=False, n_folds=5):
    """
    Time-series cross-validation with expanding window.
    Split 2005-2024 into n_folds OOS periods.
    """
    # Ensure we start from 2005
    prices_filtered = prices[prices.index >= '2005-01-01']

    total_days = len(prices_filtered)
    fold_size = total_days // n_folds

    oos_results = []

    for fold in range(n_folds):
        oos_start_idx = fold * fold_size
        oos_end_idx = (fold + 1) * fold_size if fold < n_folds - 1 else total_days

        oos_start = prices_filtered.index[oos_start_idx]
        oos_end = prices_filtered.index[oos_end_idx - 1]

        # Use ALL available data up to oos_end for computing signals
        # (signals are computed from price history, OOS = returns in this period)
        full_returns = compute_tsmom_returns(
            prices[prices.index <= oos_end],
            lookback_months=lookback,
            skip_months=skip,
            vol_scale=vol_scale
        )

        # Extract OOS period returns
        oos_returns = full_returns[(full_returns.index >= oos_start) & (full_returns.index <= oos_end)]

        if len(oos_returns) < 100:
            continue

        metrics = compute_metrics(oos_returns)
        metrics['fold'] = fold + 1
        metrics['oos_start'] = oos_start.strftime('%Y-%m-%d')
        metrics['oos_end'] = oos_end.strftime('%Y-%m-%d')
        metrics['n_days'] = len(oos_returns)
        oos_results.append(metrics)

    return oos_results


# ============================================================
# 5. DIEBOLD-MARIANO TEST
# ============================================================
def dm_test(returns_strategy, returns_benchmark, h=1):
    """
    Diebold-Mariano test for equal predictive ability.
    Uses squared returns as loss (lower = better risk-adjusted).
    Actually, we compare Sharpe-like: test if mean(strategy - benchmark) != 0.
    """
    # Align
    common = returns_strategy.index.intersection(returns_benchmark.index)
    r1 = returns_strategy.loc[common]
    r2 = returns_benchmark.loc[common]

    # Loss differential: we want to test if strategy excess return > 0
    d = r1 - r2
    d = d.dropna()

    if len(d) < 30:
        return np.nan, np.nan

    # Newey-West adjusted (HAC) standard error
    n = len(d)
    d_mean = d.mean()

    # Autocovariance
    max_lag = int(np.ceil(n ** (1/3)))
    gamma_0 = d.var()

    hac_var = gamma_0
    for lag in range(1, max_lag + 1):
        gamma_lag = np.cov(d.iloc[lag:].values, d.iloc[:-lag].values)[0, 1]
        weight = 1 - lag / (max_lag + 1)  # Bartlett kernel
        hac_var += 2 * weight * gamma_lag

    hac_se = np.sqrt(hac_var / n)

    if hac_se < 1e-10:
        return np.nan, np.nan

    dm_stat = d_mean / hac_se
    p_value = 2 * (1 - stats.norm.cdf(abs(dm_stat)))

    return dm_stat, p_value


# ============================================================
# 6. ESTIMATE TURNOVER
# ============================================================
def estimate_turnover(prices, lookback_months=12, skip_months=1):
    """Estimate average annual turnover for TSMOM strategy."""
    monthly_prices = prices.resample('ME').last()

    signals_history = []
    for col in prices.columns:
        asset_signals = []
        for i in range(lookback_months, len(monthly_prices)):
            end_idx = i - skip_months
            start_idx = i - lookback_months
            if end_idx < 0 or start_idx < 0:
                asset_signals.append(np.nan)
                continue
            ret = monthly_prices[col].iloc[end_idx] / monthly_prices[col].iloc[start_idx] - 1
            asset_signals.append(1.0 if ret > 0 else 0.0)
        signals_history.append(asset_signals)

    # Count signal changes per asset per year
    total_changes = 0
    total_months = 0
    for asset_sigs in signals_history:
        sigs = [s for s in asset_sigs if not np.isnan(s)]
        changes = sum(1 for i in range(1, len(sigs)) if sigs[i] != sigs[i-1])
        total_changes += changes
        total_months = max(total_months, len(sigs))

    years = total_months / 12
    avg_changes_per_year = total_changes / years if years > 0 else 0

    # Each change = 1 trade per asset; turnover = changes * avg_weight
    # Approximate: each signal change trades ~33% of portfolio (1/3 weight)
    turnover_per_year = avg_changes_per_year * (1.0 / len(prices.columns))

    return turnover_per_year, avg_changes_per_year


# ============================================================
# 7. MAIN EXPERIMENT
# ============================================================
def main():
    print("=" * 70)
    print("K241: TSMOM Robustness — Does It Survive Without BTC?")
    print("=" * 70)
    print()

    # Download data
    prices = download_data()

    # Filter to 2005+ (GLD starts Nov 2004)
    prices = prices[prices.index >= '2005-01-01']
    print(f"\nAnalysis period: {prices.index[0].strftime('%Y-%m-%d')} to {prices.index[-1].strftime('%Y-%m-%d')}")
    print(f"Trading days: {len(prices)}")
    print()

    # --------------------------------------------------------
    # SECTION A: FULL-SAMPLE PERFORMANCE (2005-2024)
    # --------------------------------------------------------
    print("=" * 70)
    print("SECTION A: FULL-SAMPLE PERFORMANCE (2005-2024)")
    print("=" * 70)
    print()

    # TSMOM variants
    tsmom_configs = {
        'TSMOM_12_1': {'lookback': 12, 'skip': 1, 'vol_scale': False},
        'TSMOM_6_1':  {'lookback': 6,  'skip': 1, 'vol_scale': False},
        'TSMOM_3_1':  {'lookback': 3,  'skip': 1, 'vol_scale': False},
        'TSMOM_12_1_VS': {'lookback': 12, 'skip': 1, 'vol_scale': True},
    }

    strategy_returns = {}
    for name, cfg in tsmom_configs.items():
        print(f"Computing {name}...")
        ret = compute_tsmom_returns(prices,
                                     lookback_months=cfg['lookback'],
                                     skip_months=cfg['skip'],
                                     vol_scale=cfg['vol_scale'])
        strategy_returns[name] = ret

    # Benchmarks
    print("Computing benchmarks...")
    benchmarks = compute_benchmark_returns(prices)

    # Combine all
    all_returns = {**strategy_returns, **benchmarks}

    # Compute metrics
    print("\n--- Full-Sample Performance Metrics ---\n")
    header = f"{'Strategy':<20} {'Ann.Ret':>8} {'Ann.Vol':>8} {'Sharpe':>8} {'MaxDD':>8} {'Calmar':>8} {'Sortino':>8} {'Skew':>7} {'WinRate':>8} {'t-stat':>7} {'InMkt':>6}"
    print(header)
    print("-" * len(header))

    all_metrics = {}
    for name, ret in all_returns.items():
        m = compute_metrics(ret)
        all_metrics[name] = m
        if m:
            print(f"{name:<20} {m['ann_return']:>7.1%} {m['ann_vol']:>7.1%} {m['sharpe']:>8.3f} "
                  f"{m['max_dd']:>7.1%} {m['calmar']:>8.3f} {m['sortino']:>8.3f} "
                  f"{m['skew']:>7.3f} {m['win_rate']:>7.1%} {m['t_stat']:>7.3f} "
                  f"{m.get('time_in_market', 1.0):>5.1%}")

    # --------------------------------------------------------
    # SECTION B: HARVEY THRESHOLD (t > 3.0)
    # --------------------------------------------------------
    print("\n" + "=" * 70)
    print("SECTION B: HARVEY (2016) THRESHOLD — t > 3.0")
    print("=" * 70)
    print()

    print(f"{'Strategy':<20} {'t-stat':>8} {'Passes Harvey':>15}")
    print("-" * 45)
    for name in tsmom_configs:
        m = all_metrics.get(name, {})
        t = m.get('t_stat', 0)
        passes = "YES ✓" if abs(t) > 3.0 else "NO ✗"
        print(f"{name:<20} {t:>8.3f} {passes:>15}")

    # --------------------------------------------------------
    # SECTION C: DIEBOLD-MARIANO TESTS
    # --------------------------------------------------------
    print("\n" + "=" * 70)
    print("SECTION C: DIEBOLD-MARIANO TESTS (vs Benchmarks)")
    print("=" * 70)
    print()

    dm_results = {}
    for strat_name in tsmom_configs:
        strat_ret = strategy_returns[strat_name]
        for bench_name in benchmarks:
            bench_ret = benchmarks[bench_name]
            dm_stat, dm_p = dm_test(strat_ret, bench_ret)
            dm_results[(strat_name, bench_name)] = (dm_stat, dm_p)

    print(f"{'Strategy vs Benchmark':<40} {'DM-stat':>8} {'p-value':>8} {'Sig.':>6}")
    print("-" * 65)
    for (s, b), (dm_s, dm_p) in dm_results.items():
        sig = "***" if dm_p < 0.01 else ("**" if dm_p < 0.05 else ("*" if dm_p < 0.10 else ""))
        print(f"{s + ' vs ' + b:<40} {dm_s:>8.3f} {dm_p:>8.4f} {sig:>6}")

    # --------------------------------------------------------
    # SECTION D: 5-FOLD CROSS-OOS VALIDATION
    # --------------------------------------------------------
    print("\n" + "=" * 70)
    print("SECTION D: 5-FOLD CROSS-OOS VALIDATION")
    print("=" * 70)
    print()

    for name, cfg in tsmom_configs.items():
        print(f"\n--- {name} ---")
        oos_results = cross_oos_validation(
            prices, lookback=cfg['lookback'], skip=cfg['skip'],
            vol_scale=cfg['vol_scale'], n_folds=5
        )

        if not oos_results:
            print("  No valid OOS folds.")
            continue

        print(f"  {'Fold':>4} {'Period':<25} {'Sharpe':>8} {'Ann.Ret':>8} {'MaxDD':>8} {'t-stat':>8}")
        print(f"  " + "-" * 65)

        sharpes = []
        for r in oos_results:
            period = f"{r['oos_start']} - {r['oos_end']}"
            print(f"  {r['fold']:>4} {period:<25} {r.get('sharpe', 0):>8.3f} "
                  f"{r.get('ann_return', 0):>7.1%} {r.get('max_dd', 0):>7.1%} {r.get('t_stat', 0):>8.3f}")
            sharpes.append(r.get('sharpe', 0))

        avg_sharpe = np.mean(sharpes)
        std_sharpe = np.std(sharpes)
        min_sharpe = np.min(sharpes)
        all_positive = all(s > 0 for s in sharpes)

        print(f"\n  Average OOS Sharpe: {avg_sharpe:.3f} (std: {std_sharpe:.3f})")
        print(f"  Min OOS Sharpe: {min_sharpe:.3f}")
        print(f"  All folds positive: {'YES' if all_positive else 'NO'}")
        print(f"  Passes Cross-OOS: {'YES' if avg_sharpe > 0.3 and all_positive else 'MARGINAL' if avg_sharpe > 0 else 'NO'}")

    # --------------------------------------------------------
    # SECTION E: TRANSACTION COST SENSITIVITY
    # --------------------------------------------------------
    print("\n" + "=" * 70)
    print("SECTION E: TRANSACTION COST SENSITIVITY")
    print("=" * 70)
    print()

    cost_levels = [0, 5, 10, 20]

    for name, cfg in tsmom_configs.items():
        turnover, changes = estimate_turnover(prices, cfg['lookback'], cfg['skip'])
        print(f"\n--- {name} (est. {changes:.1f} signal changes/yr, turnover ~{turnover:.1f}x/yr) ---")

        ret = strategy_returns[name]

        print(f"  {'Cost (bps)':>10} {'Net Sharpe':>10} {'Net Return':>10} {'Net-Gross':>10}")
        print(f"  " + "-" * 45)

        for cost in cost_levels:
            adj_ret = apply_transaction_costs(ret, turnover * 2, cost)  # round-trip
            m = compute_metrics(adj_ret)
            gross_sharpe = all_metrics[name].get('sharpe', 0)
            delta = m.get('sharpe', 0) - gross_sharpe
            print(f"  {cost:>10} {m.get('sharpe', 0):>10.3f} {m.get('ann_return', 0):>9.1%} {delta:>+10.3f}")

    # --------------------------------------------------------
    # SECTION F: REGIME ANALYSIS
    # --------------------------------------------------------
    print("\n" + "=" * 70)
    print("SECTION F: REGIME ANALYSIS")
    print("=" * 70)
    print()

    # Define crisis periods
    regimes = {
        'GFC (2008-2009)': ('2008-01-01', '2009-12-31'),
        'Post-GFC Bull (2010-2014)': ('2010-01-01', '2014-12-31'),
        'Taper/Vol (2015-2016)': ('2015-01-01', '2016-12-31'),
        'Low Vol Bull (2017-2019)': ('2017-01-01', '2019-12-31'),
        'COVID (2020)': ('2020-01-01', '2020-12-31'),
        'Post-COVID (2021-2022)': ('2021-01-01', '2022-12-31'),
        'Recovery (2023-2024)': ('2023-01-01', '2024-12-31'),
    }

    best_tsmom = 'TSMOM_12_1'  # Use classic as representative
    tsmom_ret = strategy_returns[best_tsmom]
    spy_ret = benchmarks['SPY_BH']
    ew_ret = benchmarks['EW_SPY_GLD_TLT']

    print(f"  {'Regime':<30} {'TSMOM_12_1':>12} {'SPY_BH':>12} {'EW_3Asset':>12} {'TSMOM-SPY':>12}")
    print(f"  " + "-" * 80)

    for regime_name, (start, end) in regimes.items():
        mask_t = (tsmom_ret.index >= start) & (tsmom_ret.index <= end)
        mask_s = (spy_ret.index >= start) & (spy_ret.index <= end)
        mask_e = (ew_ret.index >= start) & (ew_ret.index <= end)

        if mask_t.sum() < 50:
            continue

        t_ann = tsmom_ret[mask_t].mean() * 252
        s_ann = spy_ret[mask_s].mean() * 252
        e_ann = ew_ret[mask_e].mean() * 252
        diff = t_ann - s_ann

        print(f"  {regime_name:<30} {t_ann:>11.1%} {s_ann:>11.1%} {e_ann:>11.1%} {diff:>+11.1%}")

    # --------------------------------------------------------
    # SECTION G: ASSET-LEVEL MOMENTUM SIGNAL ANALYSIS
    # --------------------------------------------------------
    print("\n" + "=" * 70)
    print("SECTION G: ASSET-LEVEL MOMENTUM SIGNAL ANALYSIS")
    print("=" * 70)
    print()

    monthly_prices = prices.resample('ME').last()

    for lookback in [3, 6, 12]:
        print(f"\n--- Lookback = {lookback} months ---")
        for col in prices.columns:
            # Compute hit rate: does positive momentum predict positive next-month return?
            hits = 0
            total = 0
            signal_on_pct = 0
            total_months_counted = 0

            for i in range(lookback + 1, len(monthly_prices)):
                # Signal: lookback return (skip 1)
                end_idx = i - 1
                start_idx = i - lookback - 1
                if end_idx < 0 or start_idx < 0:
                    continue

                mom_ret = monthly_prices[col].iloc[end_idx] / monthly_prices[col].iloc[start_idx] - 1
                next_ret = monthly_prices[col].iloc[i] / monthly_prices[col].iloc[i-1] - 1

                signal = 1 if mom_ret > 0 else 0
                signal_on_pct += signal
                total_months_counted += 1

                if signal == 1 and next_ret > 0:
                    hits += 1
                    total += 1
                elif signal == 1 and next_ret <= 0:
                    total += 1
                elif signal == 0 and next_ret <= 0:
                    hits += 1
                    total += 1
                else:
                    total += 1

            hit_rate = hits / total if total > 0 else 0
            pct_long = signal_on_pct / total_months_counted if total_months_counted > 0 else 0
            print(f"  {col}: Hit Rate = {hit_rate:.1%}, Time Long = {pct_long:.1%} ({total_months_counted} months)")

    # --------------------------------------------------------
    # SECTION H: BOOTSTRAP CONFIDENCE INTERVALS
    # --------------------------------------------------------
    print("\n" + "=" * 70)
    print("SECTION H: BOOTSTRAP CONFIDENCE INTERVALS (10,000 reps)")
    print("=" * 70)
    print()

    np.random.seed(42)
    n_bootstrap = 10000

    for name in ['TSMOM_12_1', 'TSMOM_6_1', 'TSMOM_3_1']:
        ret = strategy_returns[name]
        monthly_ret = (1 + ret).resample('ME').prod() - 1
        monthly_ret = monthly_ret.dropna().values

        n = len(monthly_ret)
        boot_sharpes = []

        for _ in range(n_bootstrap):
            sample = np.random.choice(monthly_ret, size=n, replace=True)
            ann_ret = sample.mean() * 12
            ann_vol = sample.std() * np.sqrt(12)
            if ann_vol > 0:
                boot_sharpes.append((ann_ret - 0.02) / ann_vol)

        boot_sharpes = np.array(boot_sharpes)
        if len(boot_sharpes) == 0:
            print(f"  {name}: No valid bootstrap samples (all zero returns?)")
            continue
        ci_5 = np.percentile(boot_sharpes, 2.5)
        ci_95 = np.percentile(boot_sharpes, 97.5)
        median_s = np.median(boot_sharpes)
        pct_positive = (boot_sharpes > 0).mean()
        pct_above_05 = (boot_sharpes > 0.5).mean()

        print(f"  {name}: Median Sharpe = {median_s:.3f}, 95% CI = [{ci_5:.3f}, {ci_95:.3f}]")
        print(f"    P(Sharpe > 0) = {pct_positive:.1%}, P(Sharpe > 0.5) = {pct_above_05:.1%}")

    # --------------------------------------------------------
    # SECTION I: COMPARISON WITH K240 (BTC-included)
    # --------------------------------------------------------
    print("\n" + "=" * 70)
    print("SECTION I: COMPARISON WITH K240 (BTC-included)")
    print("=" * 70)
    print()

    print("  K240 (SPY+GLD+TLT+BTC, 2015-2024):")
    print("    TSMOM 12_1: Sharpe = 0.979, t = 3.07 (passes Harvey)")
    print("    BTC weight: 25% of portfolio")
    print()

    k241_sharpe = all_metrics.get('TSMOM_12_1', {}).get('sharpe', 0)
    k241_t = all_metrics.get('TSMOM_12_1', {}).get('t_stat', 0)

    print(f"  K241 (SPY+GLD+TLT only, 2005-2024):")
    print(f"    TSMOM 12_1: Sharpe = {k241_sharpe:.3f}, t = {k241_t:.3f}")
    print(f"    BTC weight: 0% (removed)")
    print()

    sharpe_drop = k241_sharpe - 0.979
    print(f"  Sharpe difference (K241 - K240): {sharpe_drop:+.3f}")
    print(f"  Harvey threshold (t > 3.0): {'PASS' if abs(k241_t) > 3.0 else 'FAIL'}")

    # --------------------------------------------------------
    # CONCLUSIONS
    # --------------------------------------------------------
    print("\n" + "=" * 70)
    print("CONCLUSIONS")
    print("=" * 70)
    print()

    # Determine key findings
    best_variant = max(tsmom_configs.keys(), key=lambda x: all_metrics.get(x, {}).get('sharpe', -999))
    best_sharpe = all_metrics.get(best_variant, {}).get('sharpe', 0)
    best_t = all_metrics.get(best_variant, {}).get('t_stat', 0)

    passes_harvey = abs(best_t) > 3.0

    print(f"  1. Best TSMOM variant: {best_variant} (Sharpe = {best_sharpe:.3f}, t = {best_t:.3f})")
    print(f"  2. Harvey threshold: {'PASS' if passes_harvey else 'FAIL'}")
    print(f"  3. Without BTC: TSMOM {'retains' if best_sharpe > 0.5 else 'loses significant'} performance")

    if best_sharpe < 0.979 * 0.7:
        print(f"  4. BTC was a MAJOR driver — Sharpe drops {(1 - best_sharpe/0.979)*100:.0f}% without it")
    elif best_sharpe < 0.979:
        print(f"  4. BTC contributed moderately — Sharpe drops {(1 - best_sharpe/0.979)*100:.0f}% without it")
    else:
        print(f"  4. TSMOM works even better without BTC (!)")

    if not passes_harvey:
        print(f"  5. DOES NOT meet strategy deployment threshold (Harvey t<3.0)")
        print(f"     → TSMOM on SPY/GLD/TLT alone is NOT robust enough for live trading")
    else:
        print(f"  5. MEETS strategy deployment threshold")
        print(f"     → Consider adding to STRATEGY_REGISTRY after further validation")

    print()

    # --------------------------------------------------------
    # SAVE RESULTS
    # --------------------------------------------------------
    results = {
        'experiment': 'K241',
        'title': 'TSMOM Robustness — Does It Survive Without BTC?',
        'data_source': 'yfinance',
        'assets': ['SPY', 'GLD', 'TLT'],
        'period': f"{prices.index[0].strftime('%Y-%m-%d')} to {prices.index[-1].strftime('%Y-%m-%d')}",
        'n_trading_days': len(prices),
        'full_sample_metrics': {},
        'harvey_results': {},
        'dm_test_results': {},
        'conclusion': {
            'best_variant': best_variant,
            'best_sharpe': round(best_sharpe, 4),
            'best_t_stat': round(best_t, 4),
            'passes_harvey': passes_harvey,
            'btc_impact': f"Sharpe drops from 0.979 (K240) to {best_sharpe:.3f} (K241)",
        }
    }

    for name, m in all_metrics.items():
        results['full_sample_metrics'][name] = {k: round(v, 4) if isinstance(v, float) else v
                                                  for k, v in m.items()}

    for (s, b), (dm_s, dm_p) in dm_results.items():
        results['dm_test_results'][f"{s}_vs_{b}"] = {
            'dm_stat': round(dm_s, 4) if not np.isnan(dm_s) else None,
            'p_value': round(dm_p, 4) if not np.isnan(dm_p) else None,
        }

    output_path = 'experiments/k241_tsmom_no_btc_results.json'
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"Results saved to {output_path}")


if __name__ == '__main__':
    main()
