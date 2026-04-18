"""
K247: Dual Momentum (Antonacci 2014) — The Classic Retail Strategy
===================================================================
[提出: 用戶, 執行: Claude]

Research Question:
1. Does Antonacci's Dual Momentum still work in recent years (2005-2024)?
2. How does it compare to our 50/50 SPY/GLD + VT and TSMOM?
3. Does adding a VT overlay improve Dual Momentum?

Methodology:
- Classic Dual Momentum: monthly rebalance
  - Absolute momentum: 12-month return > 0 (T-bill proxy)
  - Relative momentum: highest 12-month return asset
  - Rule: 100% in best asset IF return > 0; else bonds/cash
- Variants:
  a. SPY vs EFA (original Antonacci)
  b. SPY vs GLD (our universe)
  c. SPY vs GLD vs AGG (3-asset)
  d. SPY vs GLD with VT overlay (dual momentum + 12/VIX sizing)
- Benchmarks: 50/50 SPY/GLD + VT, SPY B&H, TSMOM 6_1
- Metrics: Sharpe, MDD, Calmar, Sortino, turnover
- 5-period cross-OOS, Harvey threshold (t>3.0), DM test

Data: yfinance daily 2005-2024, real data only.
"""

import json
import os
import sys
from pathlib import Path
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

import numpy as np
import pandas as pd
from scipy import stats
import yfinance as yf

RESULTS_FILE = Path(__file__).resolve().parent / "k247_dual_momentum_results.json"
STORAGE_DIR = Path(__file__).resolve().parent.parent / "storage" / "experiments"

# ===========================================================================
# 1. DATA
# ===========================================================================

def download_data(tickers, start='2003-01-01', end='2024-12-31'):
    """Download daily adjusted close prices from yfinance."""
    print(f"Downloading {tickers} from {start} to {end}...")
    data = {}
    for t in tickers:
        df = yf.download(t, start=start, end=end, auto_adjust=True, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        data[t] = df['Close'].copy()
        print(f"  {t}: {len(data[t])} days ({data[t].index[0].strftime('%Y-%m-%d')} to {data[t].index[-1].strftime('%Y-%m-%d')})")

    prices = pd.DataFrame(data)
    prices = prices.ffill().dropna()
    print(f"Combined: {len(prices)} days after ffill+dropna")
    return prices

def get_vix_data(start='2003-01-01', end='2024-12-31'):
    """Download VIX data."""
    vix = yf.download('^VIX', start=start, end=end, auto_adjust=True, progress=False)
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.get_level_values(0)
    return vix['Close']

# ===========================================================================
# 2. STRATEGY IMPLEMENTATIONS
# ===========================================================================

def compute_monthly_returns(prices):
    """Convert daily prices to monthly returns (end-of-month)."""
    monthly = prices.resample('ME').last()
    returns = monthly.pct_change().dropna()
    return monthly, returns

def dual_momentum_strategy(prices, risky_assets, safe_asset, lookback=252,
                            rebal_freq='ME', name='DualMom'):
    """
    Classic Dual Momentum (Antonacci 2014).

    Monthly rebalance:
    1. Compute 12-month return for each risky asset
    2. Absolute momentum: is best risky asset return > 0?
    3. If yes: invest 100% in best risky asset (relative momentum)
    4. If no: invest 100% in safe asset (bonds/cash)

    Returns daily returns of the strategy.
    """
    all_assets = risky_assets + [safe_asset]
    daily_returns = prices[all_assets].pct_change().dropna()

    # Monthly rebalance dates
    monthly_dates = prices.resample(rebal_freq).last().index

    # We need lookback days of history
    start_idx = lookback + 1
    valid_dates = prices.index[start_idx:]

    strategy_returns = []
    positions = []
    current_position = safe_asset
    turnover_count = 0

    last_rebal_month = None

    for date in valid_dates:
        if date not in daily_returns.index:
            continue

        current_month = (date.year, date.month)

        # Check if we should rebalance (new month)
        if current_month != last_rebal_month:
            last_rebal_month = current_month

            # Get lookback window
            loc = prices.index.get_loc(date)
            if loc < lookback:
                strategy_returns.append({
                    'date': date, 'return': daily_returns.loc[date, safe_asset],
                    'position': safe_asset
                })
                continue

            lookback_start = prices.index[loc - lookback]

            # 12-month returns for risky assets
            mom_returns = {}
            for asset in risky_assets:
                price_now = prices.loc[date, asset]
                price_past = prices.loc[lookback_start, asset]
                mom_returns[asset] = (price_now / price_past) - 1.0

            # Relative momentum: best risky asset
            best_asset = max(mom_returns, key=mom_returns.get)
            best_return = mom_returns[best_asset]

            # Absolute momentum: is best return > 0?
            old_position = current_position
            if best_return > 0:
                current_position = best_asset
            else:
                current_position = safe_asset

            if old_position != current_position:
                turnover_count += 1

        # Daily return based on current position
        ret = daily_returns.loc[date, current_position]
        strategy_returns.append({
            'date': date,
            'return': ret,
            'position': current_position
        })
        positions.append({'date': date, 'position': current_position})

    df = pd.DataFrame(strategy_returns)
    df = df.set_index('date')

    n_years = (df.index[-1] - df.index[0]).days / 365.25
    annual_turnover = turnover_count / n_years if n_years > 0 else 0

    return df, annual_turnover, positions

def tsmom_strategy(prices, asset, lookback_days=126, holding_days=21, name='TSMOM'):
    """
    Time-Series Momentum (Moskowitz, Ooi, Pedersen 2012).
    lookback_days=126 (~6 months), holding_days=21 (~1 month).
    Long if past return > 0, else short (or cash).
    For equity, we use long/cash instead of long/short.
    """
    daily_returns = prices[asset].pct_change().dropna()

    strategy_returns = []
    current_signal = 0  # 0 = cash, 1 = long
    last_rebal = None
    turnover_count = 0

    for i in range(lookback_days, len(daily_returns)):
        date = daily_returns.index[i]

        # Rebalance every holding_days
        should_rebal = False
        if last_rebal is None:
            should_rebal = True
        else:
            days_since = (date - last_rebal).days
            if days_since >= holding_days:
                should_rebal = True

        if should_rebal:
            last_rebal = date
            # Lookback return
            past_ret = (prices[asset].iloc[i] / prices[asset].iloc[i - lookback_days]) - 1.0
            old_signal = current_signal
            current_signal = 1 if past_ret > 0 else 0
            if old_signal != current_signal:
                turnover_count += 1

        ret = daily_returns.iloc[i] * current_signal
        strategy_returns.append({'date': date, 'return': ret})

    df = pd.DataFrame(strategy_returns).set_index('date')
    n_years = (df.index[-1] - df.index[0]).days / 365.25
    annual_turnover = turnover_count / n_years if n_years > 0 else 0

    return df, annual_turnover

def vt_overlay_strategy(prices, vix, risky_assets, safe_asset,
                         lookback=252, vt_threshold=12, name='DualMom+VT'):
    """
    Dual Momentum with VT overlay.

    1. Run dual momentum to pick asset
    2. Apply 12/VIX sizing: weight = min(1, vt_threshold / VIX)
    3. Remainder in safe asset
    """
    all_assets = risky_assets + [safe_asset]
    daily_returns = prices[all_assets].pct_change().dropna()

    # Align VIX with price dates
    vix_aligned = vix.reindex(prices.index).ffill()

    start_idx = lookback + 1
    valid_dates = prices.index[start_idx:]

    strategy_returns = []
    current_position = safe_asset
    last_rebal_month = None
    turnover_count = 0

    for date in valid_dates:
        if date not in daily_returns.index:
            continue
        if date not in vix_aligned.index or pd.isna(vix_aligned.loc[date]):
            continue

        current_month = (date.year, date.month)

        if current_month != last_rebal_month:
            last_rebal_month = current_month

            loc = prices.index.get_loc(date)
            if loc < lookback:
                strategy_returns.append({'date': date, 'return': 0.0})
                continue

            lookback_start = prices.index[loc - lookback]

            mom_returns = {}
            for asset in risky_assets:
                price_now = prices.loc[date, asset]
                price_past = prices.loc[lookback_start, asset]
                mom_returns[asset] = (price_now / price_past) - 1.0

            best_asset = max(mom_returns, key=mom_returns.get)
            best_return = mom_returns[best_asset]

            old_position = current_position
            if best_return > 0:
                current_position = best_asset
            else:
                current_position = safe_asset

            if old_position != current_position:
                turnover_count += 1

        # VT sizing using lagged VIX (VIX_t -> weight for r_{t+1})
        # For daily, we use previous day's VIX
        loc_today = daily_returns.index.get_loc(date)
        if loc_today > 0:
            prev_date = daily_returns.index[loc_today - 1]
            if prev_date in vix_aligned.index:
                vix_val = vix_aligned.loc[prev_date]
            else:
                vix_val = vt_threshold  # default to full weight
        else:
            vix_val = vt_threshold

        if pd.isna(vix_val) or vix_val <= 0:
            vix_val = vt_threshold

        vt_weight = min(1.0, vt_threshold / vix_val)

        if current_position == safe_asset:
            # Already in safe asset, VT doesn't change allocation
            ret = daily_returns.loc[date, safe_asset]
        else:
            # Apply VT sizing
            ret_risky = daily_returns.loc[date, current_position]
            ret_safe = daily_returns.loc[date, safe_asset]
            ret = vt_weight * ret_risky + (1 - vt_weight) * ret_safe

        strategy_returns.append({'date': date, 'return': ret})

    df = pd.DataFrame(strategy_returns).set_index('date')
    n_years = (df.index[-1] - df.index[0]).days / 365.25
    annual_turnover = turnover_count / n_years if n_years > 0 else 0

    return df, annual_turnover

def buy_and_hold_strategy(prices, asset):
    """Simple buy and hold."""
    returns = prices[asset].pct_change().dropna()
    df = pd.DataFrame({'return': returns})
    return df, 0.0

def fifty_fifty_vt_strategy(prices, vix, asset1='SPY', asset2='GLD',
                              safe_asset='AGG', vt_threshold=12):
    """
    50/50 SPY/GLD with 12/VIX sizing, monthly rebalance.
    """
    daily_returns = prices[[asset1, asset2, safe_asset]].pct_change().dropna()
    vix_aligned = vix.reindex(daily_returns.index).ffill()

    strategy_returns = []

    for i in range(1, len(daily_returns)):
        date = daily_returns.index[i]
        prev_date = daily_returns.index[i - 1]

        # Lagged VIX
        vix_val = vix_aligned.loc[prev_date] if prev_date in vix_aligned.index else vt_threshold
        if pd.isna(vix_val) or vix_val <= 0:
            vix_val = vt_threshold

        vt_weight = min(1.0, vt_threshold / vix_val)

        r1 = daily_returns.loc[date, asset1]
        r2 = daily_returns.loc[date, asset2]
        r_safe = daily_returns.loc[date, safe_asset]

        # 50/50 in risky assets, VT scaled
        ret = vt_weight * (0.5 * r1 + 0.5 * r2) + (1 - vt_weight) * r_safe
        strategy_returns.append({'date': date, 'return': ret})

    df = pd.DataFrame(strategy_returns).set_index('date')
    return df, 12.0  # monthly rebalance ~ 12 turnover/yr

# ===========================================================================
# 3. METRICS
# ===========================================================================

def compute_metrics(returns_series, name='Strategy', annual_turnover=0.0,
                     tx_cost_bps=10):
    """Compute comprehensive strategy metrics."""
    r = returns_series.values
    n_days = len(r)
    n_years = n_days / 252.0

    # Annualized return
    cum = np.prod(1 + r)
    ann_ret = cum ** (1 / n_years) - 1 if n_years > 0 else 0

    # Annualized vol
    ann_vol = np.std(r, ddof=1) * np.sqrt(252)

    # Sharpe
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    # Sharpe t-stat (Lo 2002)
    sharpe_se = np.sqrt((1 + 0.5 * sharpe**2) / n_years) if n_years > 0 else 1
    sharpe_t = sharpe / sharpe_se if sharpe_se > 0 else 0

    # MDD
    cumulative = np.cumprod(1 + r)
    running_max = np.maximum.accumulate(cumulative)
    drawdowns = cumulative / running_max - 1
    mdd = np.min(drawdowns)

    # Calmar
    calmar = ann_ret / abs(mdd) if abs(mdd) > 0 else 0

    # Sortino
    downside = r[r < 0]
    downside_vol = np.std(downside, ddof=1) * np.sqrt(252) if len(downside) > 1 else ann_vol
    sortino = ann_ret / downside_vol if downside_vol > 0 else 0

    # Win rate
    win_rate = np.mean(r > 0) if len(r) > 0 else 0

    # Net Sharpe (after transaction costs)
    tx_drag = annual_turnover * (tx_cost_bps / 10000.0)
    net_ret = ann_ret - tx_drag
    net_sharpe = net_ret / ann_vol if ann_vol > 0 else 0

    # Skewness and kurtosis
    skew = stats.skew(r)
    kurt = stats.kurtosis(r)

    return {
        'name': name,
        'n_days': n_days,
        'n_years': round(n_years, 2),
        'ann_return': round(ann_ret * 100, 2),
        'ann_vol': round(ann_vol * 100, 2),
        'sharpe': round(sharpe, 3),
        'sharpe_t': round(sharpe_t, 2),
        'mdd': round(mdd * 100, 2),
        'calmar': round(calmar, 3),
        'sortino': round(sortino, 3),
        'win_rate': round(win_rate * 100, 1),
        'annual_turnover': round(annual_turnover, 1),
        'tx_drag_pct': round(tx_drag * 100, 3),
        'net_sharpe': round(net_sharpe, 3),
        'skewness': round(skew, 3),
        'kurtosis': round(kurt, 3),
    }

def bootstrap_mdd_pvalue(strategy_returns, benchmark_returns, n_bootstrap=10000, seed=42):
    """Bootstrap test for MDD improvement."""
    rng = np.random.RandomState(seed)

    def compute_mdd(r):
        cumulative = np.cumprod(1 + r)
        running_max = np.maximum.accumulate(cumulative)
        return np.min(cumulative / running_max - 1)

    obs_diff = compute_mdd(strategy_returns) - compute_mdd(benchmark_returns)

    combined = np.column_stack([strategy_returns, benchmark_returns])
    n = len(combined)

    count_more_extreme = 0
    for _ in range(n_bootstrap):
        idx = rng.randint(0, n, size=n)
        boot_strat = combined[idx, 0]
        boot_bench = combined[idx, 1]
        boot_diff = compute_mdd(boot_strat) - compute_mdd(boot_bench)
        if boot_diff <= obs_diff:
            count_more_extreme += 1

    return count_more_extreme / n_bootstrap

def dm_test(loss1, loss2, h=1):
    """
    Diebold-Mariano test.
    H0: E[d_t] = 0 where d_t = loss1_t - loss2_t
    Positive t-stat means loss1 > loss2 (strategy 2 is better).
    Here we use squared return differences as losses.
    """
    d = loss1 - loss2
    n = len(d)
    d_mean = np.mean(d)

    # Newey-West variance estimate
    max_lag = int(np.ceil(n ** (1/3)))
    gamma_0 = np.var(d, ddof=1)
    gamma_sum = 0
    for k in range(1, max_lag + 1):
        weight = 1 - k / (max_lag + 1)
        gamma_k = np.mean((d[k:] - d_mean) * (d[:-k] - d_mean))
        gamma_sum += 2 * weight * gamma_k

    var_d = (gamma_0 + gamma_sum) / n
    if var_d <= 0:
        return 0, 1.0

    t_stat = d_mean / np.sqrt(var_d)
    p_value = 2 * (1 - stats.norm.cdf(abs(t_stat)))

    return t_stat, p_value

# ===========================================================================
# 4. CROSS-OOS VALIDATION
# ===========================================================================

def cross_oos_validation(prices, vix, strategy_func, strategy_kwargs,
                          benchmark_func, benchmark_kwargs,
                          n_periods=5, name='Strategy'):
    """
    5-period cross-OOS validation.
    Split the full sample into 5 equal non-overlapping periods.
    Run strategy and benchmark on each.
    """
    # Get the common date range where strategy can run
    # (need 252 days lookback)
    start_date = prices.index[252]
    end_date = prices.index[-1]

    total_days = (end_date - start_date).days
    period_days = total_days // n_periods

    results = []

    for i in range(n_periods):
        p_start = start_date + pd.Timedelta(days=i * period_days)
        p_end = start_date + pd.Timedelta(days=(i + 1) * period_days)
        if i == n_periods - 1:
            p_end = end_date

        # Filter prices and vix for this period (with lookback)
        lookback_start = p_start - pd.Timedelta(days=300)  # extra buffer
        mask = (prices.index >= lookback_start) & (prices.index <= p_end)
        period_prices = prices[mask].copy()

        if vix is not None:
            period_vix = vix[(vix.index >= lookback_start) & (vix.index <= p_end)].copy()
        else:
            period_vix = None

        # Run strategy
        try:
            if 'vix' in strategy_kwargs:
                strat_df, strat_to, _ = strategy_func(
                    period_prices, **{k: v for k, v in strategy_kwargs.items() if k != 'vix'},
                    **({'vix': period_vix} if period_vix is not None else {})
                )
            elif strategy_func.__name__ == 'vt_overlay_strategy':
                strat_df, strat_to = strategy_func(period_prices, period_vix,
                                                     **strategy_kwargs)
            elif strategy_func.__name__ == 'fifty_fifty_vt_strategy':
                strat_df, strat_to = strategy_func(period_prices, period_vix,
                                                     **strategy_kwargs)
            elif strategy_func.__name__ == 'dual_momentum_strategy':
                strat_df, strat_to, _ = strategy_func(period_prices, **strategy_kwargs)
            else:
                strat_df, strat_to = strategy_func(period_prices, **strategy_kwargs)
        except Exception as e:
            print(f"  Period {i+1} strategy error: {e}")
            continue

        # Filter to OOS period only
        strat_df = strat_df[(strat_df.index >= p_start) & (strat_df.index <= p_end)]

        if len(strat_df) < 50:
            print(f"  Period {i+1}: too few days ({len(strat_df)}), skipping")
            continue

        # Run benchmark
        try:
            if benchmark_func.__name__ == 'buy_and_hold_strategy':
                bench_df, bench_to = benchmark_func(period_prices, **benchmark_kwargs)
            elif benchmark_func.__name__ == 'fifty_fifty_vt_strategy':
                bench_df, bench_to = benchmark_func(period_prices, period_vix,
                                                      **benchmark_kwargs)
            else:
                bench_df, bench_to = benchmark_func(period_prices, **benchmark_kwargs)
        except Exception as e:
            print(f"  Period {i+1} benchmark error: {e}")
            continue

        bench_df = bench_df[(bench_df.index >= p_start) & (bench_df.index <= p_end)]

        # Align dates
        common_dates = strat_df.index.intersection(bench_df.index)
        if len(common_dates) < 50:
            continue

        strat_r = strat_df.loc[common_dates, 'return'].values
        bench_r = bench_df.loc[common_dates, 'return'].values

        strat_metrics = compute_metrics(pd.Series(strat_r), name=f'{name}_P{i+1}')
        bench_metrics = compute_metrics(pd.Series(bench_r), name=f'Bench_P{i+1}')

        # DM test on daily returns (using negative returns as "loss")
        strat_loss = -strat_r  # lower is better
        bench_loss = -bench_r
        dm_t, dm_p = dm_test(bench_loss, strat_loss)

        results.append({
            'period': i + 1,
            'start': p_start.strftime('%Y-%m-%d'),
            'end': p_end.strftime('%Y-%m-%d'),
            'n_days': len(common_dates),
            'strategy_sharpe': strat_metrics['sharpe'],
            'benchmark_sharpe': bench_metrics['sharpe'],
            'strategy_mdd': strat_metrics['mdd'],
            'benchmark_mdd': bench_metrics['mdd'],
            'sharpe_diff': round(strat_metrics['sharpe'] - bench_metrics['sharpe'], 3),
            'dm_t': round(dm_t, 2),
            'dm_p': round(dm_p, 4),
        })

    return results

# ===========================================================================
# 5. MAIN EXPERIMENT
# ===========================================================================

def main():
    print("=" * 70)
    print("K247: Dual Momentum (Antonacci 2014)")
    print("=" * 70)

    # Download data
    tickers = ['SPY', 'EFA', 'GLD', 'AGG']
    prices = download_data(tickers, start='2003-01-01', end='2024-12-31')
    vix = get_vix_data(start='2003-01-01', end='2024-12-31')

    # Align all data - GLD starts 2004-11, EFA starts 2001
    # AGG starts 2003-09
    common_start = prices.dropna().index[0]
    prices = prices.loc[common_start:]
    print(f"\nCommon start date: {common_start.strftime('%Y-%m-%d')}")
    print(f"Data range: {prices.index[0].strftime('%Y-%m-%d')} to {prices.index[-1].strftime('%Y-%m-%d')}")
    print(f"Total trading days: {len(prices)}")

    # -----------------------------------------------------------------------
    # Run all strategies
    # -----------------------------------------------------------------------
    all_results = {}
    all_returns = {}

    # Strategy 1: DualMom SPY vs EFA (Original Antonacci)
    print("\n--- Strategy 1: Dual Momentum SPY vs EFA ---")
    dm_efa_df, dm_efa_to, dm_efa_pos = dual_momentum_strategy(
        prices, risky_assets=['SPY', 'EFA'], safe_asset='AGG',
        lookback=252, name='DM_SPY_EFA'
    )
    m = compute_metrics(dm_efa_df['return'], 'DM SPY vs EFA', dm_efa_to)
    all_results['dm_spy_efa'] = m
    all_returns['dm_spy_efa'] = dm_efa_df
    print(f"  Sharpe={m['sharpe']:.3f} (t={m['sharpe_t']:.2f}), MDD={m['mdd']:.1f}%, "
          f"Turnover={m['annual_turnover']:.1f}/yr")

    # Analyze position allocation
    pos_df = pd.DataFrame(dm_efa_pos)
    pos_counts = pos_df['position'].value_counts(normalize=True)
    print(f"  Position breakdown: {dict(pos_counts.round(3))}")

    # Strategy 2: DualMom SPY vs GLD
    print("\n--- Strategy 2: Dual Momentum SPY vs GLD ---")
    dm_gld_df, dm_gld_to, dm_gld_pos = dual_momentum_strategy(
        prices, risky_assets=['SPY', 'GLD'], safe_asset='AGG',
        lookback=252, name='DM_SPY_GLD'
    )
    m = compute_metrics(dm_gld_df['return'], 'DM SPY vs GLD', dm_gld_to)
    all_results['dm_spy_gld'] = m
    all_returns['dm_spy_gld'] = dm_gld_df
    print(f"  Sharpe={m['sharpe']:.3f} (t={m['sharpe_t']:.2f}), MDD={m['mdd']:.1f}%, "
          f"Turnover={m['annual_turnover']:.1f}/yr")

    pos_df = pd.DataFrame(dm_gld_pos)
    pos_counts = pos_df['position'].value_counts(normalize=True)
    print(f"  Position breakdown: {dict(pos_counts.round(3))}")

    # Strategy 3: DualMom SPY vs GLD vs AGG (3-asset)
    print("\n--- Strategy 3: Dual Momentum SPY vs GLD (3-asset with EFA) ---")
    dm_3asset_df, dm_3asset_to, dm_3asset_pos = dual_momentum_strategy(
        prices, risky_assets=['SPY', 'GLD', 'EFA'], safe_asset='AGG',
        lookback=252, name='DM_3Asset'
    )
    m = compute_metrics(dm_3asset_df['return'], 'DM 3-Asset', dm_3asset_to)
    all_results['dm_3asset'] = m
    all_returns['dm_3asset'] = dm_3asset_df
    print(f"  Sharpe={m['sharpe']:.3f} (t={m['sharpe_t']:.2f}), MDD={m['mdd']:.1f}%, "
          f"Turnover={m['annual_turnover']:.1f}/yr")

    pos_df = pd.DataFrame(dm_3asset_pos)
    pos_counts = pos_df['position'].value_counts(normalize=True)
    print(f"  Position breakdown: {dict(pos_counts.round(3))}")

    # Strategy 4: DualMom SPY vs GLD + VT overlay
    print("\n--- Strategy 4: Dual Momentum SPY vs GLD + VT Overlay ---")
    dm_vt_df, dm_vt_to = vt_overlay_strategy(
        prices, vix, risky_assets=['SPY', 'GLD'], safe_asset='AGG',
        lookback=252, vt_threshold=12, name='DM_SPY_GLD_VT'
    )
    m = compute_metrics(dm_vt_df['return'], 'DM SPY vs GLD + VT', dm_vt_to)
    all_results['dm_spy_gld_vt'] = m
    all_returns['dm_spy_gld_vt'] = dm_vt_df
    print(f"  Sharpe={m['sharpe']:.3f} (t={m['sharpe_t']:.2f}), MDD={m['mdd']:.1f}%, "
          f"Turnover={m['annual_turnover']:.1f}/yr")

    # Benchmark 1: 50/50 SPY/GLD + VT
    print("\n--- Benchmark 1: 50/50 SPY/GLD + 12/VIX ---")
    ff_vt_df, ff_vt_to = fifty_fifty_vt_strategy(prices, vix)
    m = compute_metrics(ff_vt_df['return'], '50/50 SPY/GLD + VT', ff_vt_to)
    all_results['fifty_fifty_vt'] = m
    all_returns['fifty_fifty_vt'] = ff_vt_df
    print(f"  Sharpe={m['sharpe']:.3f} (t={m['sharpe_t']:.2f}), MDD={m['mdd']:.1f}%, "
          f"Turnover={m['annual_turnover']:.1f}/yr")

    # Benchmark 2: SPY B&H
    print("\n--- Benchmark 2: SPY Buy & Hold ---")
    spy_bh_df, spy_bh_to = buy_and_hold_strategy(prices, 'SPY')
    # Trim to same period as dual momentum strategies
    common_start_dm = dm_efa_df.index[0]
    spy_bh_df = spy_bh_df[spy_bh_df.index >= common_start_dm]
    m = compute_metrics(spy_bh_df['return'], 'SPY B&H', spy_bh_to)
    all_results['spy_bh'] = m
    all_returns['spy_bh'] = spy_bh_df
    print(f"  Sharpe={m['sharpe']:.3f} (t={m['sharpe_t']:.2f}), MDD={m['mdd']:.1f}%, "
          f"Turnover={m['annual_turnover']:.1f}/yr")

    # Benchmark 3: TSMOM 6_1 on SPY
    print("\n--- Benchmark 3: TSMOM 6_1 (SPY) ---")
    tsmom_df, tsmom_to = tsmom_strategy(prices, 'SPY', lookback_days=126, holding_days=21)
    tsmom_df = tsmom_df[tsmom_df.index >= common_start_dm]
    m = compute_metrics(tsmom_df['return'], 'TSMOM 6_1 SPY', tsmom_to)
    all_results['tsmom_6_1'] = m
    all_returns['tsmom_6_1'] = tsmom_df
    print(f"  Sharpe={m['sharpe']:.3f} (t={m['sharpe_t']:.2f}), MDD={m['mdd']:.1f}%, "
          f"Turnover={m['annual_turnover']:.1f}/yr")

    # Benchmark 4: GLD B&H
    print("\n--- Benchmark 4: GLD Buy & Hold ---")
    gld_bh_df, gld_bh_to = buy_and_hold_strategy(prices, 'GLD')
    gld_bh_df = gld_bh_df[gld_bh_df.index >= common_start_dm]
    m = compute_metrics(gld_bh_df['return'], 'GLD B&H', gld_bh_to)
    all_results['gld_bh'] = m
    all_returns['gld_bh'] = gld_bh_df
    print(f"  Sharpe={m['sharpe']:.3f} (t={m['sharpe_t']:.2f}), MDD={m['mdd']:.1f}%, "
          f"Turnover={m['annual_turnover']:.1f}/yr")

    # -----------------------------------------------------------------------
    # Summary Table
    # -----------------------------------------------------------------------
    print("\n" + "=" * 90)
    print("FULL-SAMPLE RESULTS SUMMARY")
    print("=" * 90)
    header = f"{'Strategy':<30} {'Sharpe':>7} {'t-stat':>7} {'MDD%':>7} {'Calmar':>7} {'Sortino':>8} {'TO/yr':>6} {'NetSh':>7}"
    print(header)
    print("-" * 90)

    for key in ['dm_spy_efa', 'dm_spy_gld', 'dm_3asset', 'dm_spy_gld_vt',
                'fifty_fifty_vt', 'spy_bh', 'tsmom_6_1', 'gld_bh']:
        r = all_results[key]
        print(f"{r['name']:<30} {r['sharpe']:>7.3f} {r['sharpe_t']:>7.2f} "
              f"{r['mdd']:>7.1f} {r['calmar']:>7.3f} {r['sortino']:>8.3f} "
              f"{r['annual_turnover']:>6.1f} {r['net_sharpe']:>7.3f}")

    # -----------------------------------------------------------------------
    # Pairwise DM Tests
    # -----------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("PAIRWISE DM TESTS (vs SPY B&H)")
    print("=" * 70)

    dm_test_results = {}
    spy_r = spy_bh_df['return']

    for key in ['dm_spy_efa', 'dm_spy_gld', 'dm_3asset', 'dm_spy_gld_vt',
                'fifty_fifty_vt', 'tsmom_6_1']:
        strat_r = all_returns[key]['return']

        # Align dates
        common = spy_r.index.intersection(strat_r.index)
        s = strat_r.loc[common].values
        b = spy_r.loc[common].values

        # DM test: using daily returns as the criterion
        # Positive t means strategy has higher average return
        loss_bench = -b
        loss_strat = -s
        t_stat, p_val = dm_test(loss_bench, loss_strat)

        dm_test_results[key] = {'t_stat': round(t_stat, 2), 'p_value': round(p_val, 4)}
        sig = '***' if p_val < 0.01 else ('**' if p_val < 0.05 else ('*' if p_val < 0.10 else ''))
        print(f"  {all_results[key]['name']:<30} DM t={t_stat:>6.2f}, p={p_val:.4f} {sig}")

    # DM test: DualMom vs 50/50 VT
    print("\n  --- DualMom variants vs 50/50 VT ---")
    ff_r = all_returns['fifty_fifty_vt']['return']
    for key in ['dm_spy_efa', 'dm_spy_gld', 'dm_3asset', 'dm_spy_gld_vt']:
        strat_r = all_returns[key]['return']
        common = ff_r.index.intersection(strat_r.index)
        s = strat_r.loc[common].values
        b = ff_r.loc[common].values
        t_stat, p_val = dm_test(-b, -s)
        sig = '***' if p_val < 0.01 else ('**' if p_val < 0.05 else ('*' if p_val < 0.10 else ''))
        print(f"  {all_results[key]['name']:<30} vs 50/50VT: DM t={t_stat:>6.2f}, p={p_val:.4f} {sig}")

    # -----------------------------------------------------------------------
    # Bootstrap MDD tests
    # -----------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("BOOTSTRAP MDD TESTS (vs SPY B&H, 10000 reps)")
    print("=" * 70)

    mdd_tests = {}
    for key in ['dm_spy_efa', 'dm_spy_gld', 'dm_3asset', 'dm_spy_gld_vt', 'fifty_fifty_vt']:
        strat_r = all_returns[key]['return']
        common = spy_r.index.intersection(strat_r.index)
        s = strat_r.loc[common].values
        b = spy_r.loc[common].values

        p_val = bootstrap_mdd_pvalue(s, b, n_bootstrap=10000)
        mdd_tests[key] = round(p_val, 4)
        sig = '***' if p_val < 0.01 else ('**' if p_val < 0.05 else ('*' if p_val < 0.10 else ''))
        strat_mdd = all_results[key]['mdd']
        bench_mdd = all_results['spy_bh']['mdd']
        print(f"  {all_results[key]['name']:<30} MDD={strat_mdd:>6.1f}% vs {bench_mdd:.1f}%, "
              f"bootstrap p={p_val:.4f} {sig}")

    # -----------------------------------------------------------------------
    # 5-Period Cross-OOS Validation
    # -----------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("5-PERIOD CROSS-OOS VALIDATION")
    print("=" * 70)

    cross_oos = {}

    # DualMom SPY vs GLD cross-OOS vs SPY B&H
    print("\n  DM SPY vs GLD (5 periods vs SPY B&H):")
    oos_results = []

    # Manual 5-period split
    start_date = prices.index[252]
    end_date = prices.index[-1]
    total_days = len(prices.index[prices.index >= start_date])
    period_size = total_days // 5

    for i in range(5):
        all_valid = prices.index[prices.index >= start_date]
        p_start = all_valid[i * period_size]
        p_end = all_valid[min((i + 1) * period_size - 1, len(all_valid) - 1)]
        if i == 4:
            p_end = all_valid[-1]

        # Get data with lookback buffer
        lookback_start = p_start - pd.Timedelta(days=300)
        period_prices = prices[(prices.index >= lookback_start) & (prices.index <= p_end)].copy()
        period_vix_data = vix[(vix.index >= lookback_start) & (vix.index <= p_end)].copy()

        # Run strategies on full period (includes lookback)
        try:
            dm_df, dm_to, _ = dual_momentum_strategy(
                period_prices, risky_assets=['SPY', 'GLD'], safe_asset='AGG',
                lookback=252, name=f'DM_P{i+1}'
            )
            spy_df, _ = buy_and_hold_strategy(period_prices, 'SPY')
            ff_df, _ = fifty_fifty_vt_strategy(period_prices, period_vix_data)

            # Filter to OOS period only
            dm_oos = dm_df[(dm_df.index >= p_start) & (dm_df.index <= p_end)]
            spy_oos = spy_df[(spy_df.index >= p_start) & (spy_df.index <= p_end)]
            ff_oos = ff_df[(ff_df.index >= p_start) & (ff_df.index <= p_end)]

            # Align
            common = dm_oos.index.intersection(spy_oos.index)
            if len(common) < 50:
                print(f"    Period {i+1}: too few days ({len(common)})")
                continue

            dm_r = dm_oos.loc[common, 'return'].values
            spy_r_period = spy_oos.loc[common, 'return'].values

            dm_m = compute_metrics(pd.Series(dm_r), f'DM_P{i+1}')
            spy_m = compute_metrics(pd.Series(spy_r_period), f'SPY_P{i+1}')

            # Also compare with 50/50 VT
            common_ff = dm_oos.index.intersection(ff_oos.index)
            ff_r = ff_oos.loc[common_ff, 'return'].values if len(common_ff) > 50 else None
            ff_m = compute_metrics(pd.Series(ff_r), f'FF_P{i+1}') if ff_r is not None else None

            # DM test
            t_dm, p_dm = dm_test(-spy_r_period, -dm_r)

            period_result = {
                'period': i + 1,
                'start': p_start.strftime('%Y-%m-%d'),
                'end': p_end.strftime('%Y-%m-%d'),
                'n_days': len(common),
                'dm_sharpe': dm_m['sharpe'],
                'spy_sharpe': spy_m['sharpe'],
                'ff_sharpe': ff_m['sharpe'] if ff_m else None,
                'dm_mdd': dm_m['mdd'],
                'spy_mdd': spy_m['mdd'],
                'dm_wins_spy': dm_m['sharpe'] > spy_m['sharpe'],
                'dm_wins_ff': dm_m['sharpe'] > ff_m['sharpe'] if ff_m else None,
                'dm_t_vs_spy': round(t_dm, 2),
                'dm_p_vs_spy': round(p_dm, 4),
            }
            oos_results.append(period_result)

            spy_win = "DM" if dm_m['sharpe'] > spy_m['sharpe'] else "SPY"
            ff_win = ""
            if ff_m:
                ff_win = f", vs 50/50VT: {'DM' if dm_m['sharpe'] > ff_m['sharpe'] else '50/50VT'}"

            print(f"    P{i+1} ({p_start.strftime('%Y-%m')} to {p_end.strftime('%Y-%m')}): "
                  f"DM={dm_m['sharpe']:.3f} vs SPY={spy_m['sharpe']:.3f} → {spy_win}"
                  f"{ff_win}")

        except Exception as e:
            print(f"    Period {i+1} error: {e}")
            import traceback
            traceback.print_exc()

    cross_oos['dm_spy_gld'] = oos_results

    # Count wins
    dm_wins_spy = sum(1 for r in oos_results if r.get('dm_wins_spy', False))
    dm_wins_ff = sum(1 for r in oos_results if r.get('dm_wins_ff', False))
    print(f"\n  DM wins vs SPY: {dm_wins_spy}/{len(oos_results)}")
    print(f"  DM wins vs 50/50 VT: {dm_wins_ff}/{len(oos_results)}")

    # -----------------------------------------------------------------------
    # Sub-period Analysis (has DualMom degraded?)
    # -----------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("SUB-PERIOD ANALYSIS: Has Dual Momentum Degraded?")
    print("=" * 70)

    subperiods = [
        ('2005-2009', '2005-01-01', '2009-12-31'),
        ('2010-2014', '2010-01-01', '2014-12-31'),
        ('2015-2019', '2015-01-01', '2019-12-31'),
        ('2020-2024', '2020-01-01', '2024-12-31'),
    ]

    subperiod_results = []
    for label, s, e in subperiods:
        # Need lookback data
        s_dt = pd.Timestamp(s)
        e_dt = pd.Timestamp(e)
        lookback_s = s_dt - pd.Timedelta(days=300)

        mask = (prices.index >= lookback_s) & (prices.index <= e_dt)
        sp_prices = prices[mask].copy()
        sp_vix = vix[(vix.index >= lookback_s) & (vix.index <= e_dt)].copy()

        if len(sp_prices) < 300:
            print(f"  {label}: insufficient data")
            continue

        try:
            dm_df, dm_to, _ = dual_momentum_strategy(
                sp_prices, risky_assets=['SPY', 'GLD'], safe_asset='AGG',
                lookback=252, name=f'DM_{label}'
            )
            dm_df = dm_df[(dm_df.index >= s_dt) & (dm_df.index <= e_dt)]

            spy_df, _ = buy_and_hold_strategy(sp_prices, 'SPY')
            spy_df = spy_df[(spy_df.index >= s_dt) & (spy_df.index <= e_dt)]

            ff_df, _ = fifty_fifty_vt_strategy(sp_prices, sp_vix)
            ff_df = ff_df[(ff_df.index >= s_dt) & (ff_df.index <= e_dt)]

            if len(dm_df) < 100:
                print(f"  {label}: too few days after filtering ({len(dm_df)})")
                continue

            dm_m = compute_metrics(dm_df['return'], f'DM {label}', dm_to)
            spy_m = compute_metrics(spy_df['return'], f'SPY {label}')
            ff_m = compute_metrics(ff_df['return'], f'50/50VT {label}')

            subperiod_results.append({
                'period': label,
                'dm_sharpe': dm_m['sharpe'],
                'dm_mdd': dm_m['mdd'],
                'spy_sharpe': spy_m['sharpe'],
                'spy_mdd': spy_m['mdd'],
                'ff_sharpe': ff_m['sharpe'],
                'ff_mdd': ff_m['mdd'],
            })

            print(f"  {label}: DM Sharpe={dm_m['sharpe']:.3f}, SPY={spy_m['sharpe']:.3f}, "
                  f"50/50VT={ff_m['sharpe']:.3f} | DM MDD={dm_m['mdd']:.1f}%, "
                  f"SPY MDD={spy_m['mdd']:.1f}%")

        except Exception as e:
            print(f"  {label} error: {e}")

    # -----------------------------------------------------------------------
    # Position Regime Analysis
    # -----------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("POSITION REGIME ANALYSIS (DM SPY vs GLD)")
    print("=" * 70)

    pos_df = pd.DataFrame(dm_gld_pos)
    pos_df['date'] = pd.to_datetime(pos_df['date'])
    pos_df['year'] = pos_df['date'].dt.year

    yearly_pos = pos_df.groupby(['year', 'position']).size().unstack(fill_value=0)
    yearly_pct = yearly_pos.div(yearly_pos.sum(axis=1), axis=0) * 100

    print(f"\n  Yearly position allocation (%):")
    for year in sorted(yearly_pct.index):
        row = yearly_pct.loc[year]
        parts = [f"{col}={row.get(col, 0):.0f}%" for col in ['SPY', 'GLD', 'AGG'] if col in row.index]
        print(f"    {year}: {', '.join(parts)}")

    # -----------------------------------------------------------------------
    # Harvey threshold check
    # -----------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("HARVEY (2016) THRESHOLD CHECK (t > 3.0)")
    print("=" * 70)

    for key in ['dm_spy_efa', 'dm_spy_gld', 'dm_3asset', 'dm_spy_gld_vt',
                'fifty_fifty_vt', 'tsmom_6_1']:
        r = all_results[key]
        passes = "PASS" if r['sharpe_t'] > 3.0 else "FAIL"
        print(f"  {r['name']:<30} t={r['sharpe_t']:>6.2f} → {passes}")

    # -----------------------------------------------------------------------
    # CONCLUSIONS
    # -----------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("CONCLUSIONS")
    print("=" * 70)

    best_dm = max(['dm_spy_efa', 'dm_spy_gld', 'dm_3asset', 'dm_spy_gld_vt'],
                  key=lambda k: all_results[k]['sharpe'])
    best_dm_name = all_results[best_dm]['name']
    best_dm_sharpe = all_results[best_dm]['sharpe']
    ff_sharpe = all_results['fifty_fifty_vt']['sharpe']
    spy_sharpe = all_results['spy_bh']['sharpe']

    print(f"\n  1. Best Dual Momentum variant: {best_dm_name} (Sharpe={best_dm_sharpe:.3f})")
    print(f"  2. vs SPY B&H (Sharpe={spy_sharpe:.3f}): {'Better' if best_dm_sharpe > spy_sharpe else 'Worse'}")
    print(f"  3. vs 50/50 VT (Sharpe={ff_sharpe:.3f}): {'Better' if best_dm_sharpe > ff_sharpe else 'Worse'}")
    print(f"  4. Cross-OOS: DM wins {dm_wins_spy}/5 vs SPY, {dm_wins_ff}/5 vs 50/50 VT")

    any_passes_harvey = any(all_results[k]['sharpe_t'] > 3.0
                           for k in ['dm_spy_efa', 'dm_spy_gld', 'dm_3asset', 'dm_spy_gld_vt'])
    print(f"  5. Harvey threshold: {'Some variants pass' if any_passes_harvey else 'No variant passes t>3.0'}")

    # Check degradation
    if len(subperiod_results) >= 3:
        early = np.mean([r['dm_sharpe'] for r in subperiod_results[:2]])
        late = np.mean([r['dm_sharpe'] for r in subperiod_results[2:]])
        degraded = late < early
        print(f"  6. Degradation: Early Sharpe={early:.3f}, Late Sharpe={late:.3f} → "
              f"{'YES degraded' if degraded else 'NO degradation'}")

    # -----------------------------------------------------------------------
    # Save Results
    # -----------------------------------------------------------------------
    output = {
        'experiment': 'K247',
        'title': 'Dual Momentum (Antonacci 2014)',
        'timestamp': datetime.now().isoformat(),
        'data': {
            'tickers': tickers,
            'start_date': prices.index[0].strftime('%Y-%m-%d'),
            'end_date': prices.index[-1].strftime('%Y-%m-%d'),
            'n_days': len(prices),
        },
        'full_sample_metrics': all_results,
        'dm_test_vs_spy': dm_test_results,
        'mdd_bootstrap': mdd_tests,
        'cross_oos': cross_oos,
        'subperiod_analysis': subperiod_results,
        'conclusions': {
            'best_dm_variant': best_dm_name,
            'best_dm_sharpe': best_dm_sharpe,
            'beats_spy': best_dm_sharpe > spy_sharpe,
            'beats_fifty_fifty_vt': best_dm_sharpe > ff_sharpe,
            'cross_oos_wins_vs_spy': f'{dm_wins_spy}/5',
            'cross_oos_wins_vs_ff': f'{dm_wins_ff}/5',
            'passes_harvey': any_passes_harvey,
        }
    }

    with open(RESULTS_FILE, 'w') as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nResults saved to {RESULTS_FILE}")

    # Also save to storage
    os.makedirs(STORAGE_DIR, exist_ok=True)
    storage_file = STORAGE_DIR / 'k247_dual_momentum.json'
    with open(storage_file, 'w') as f:
        json.dump(output, f, indent=2, default=str)
    print(f"Results also saved to {storage_file}")

if __name__ == '__main__':
    main()
