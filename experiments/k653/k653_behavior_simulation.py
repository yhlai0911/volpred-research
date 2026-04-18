"""
K653: Investor Behavior Simulation — What Happens When Investors Don't Follow the Strategy?
============================================================================================
Motivation:
  Real investors make behavioral mistakes: they panic sell during dips, chase
  performance, skip rebalancing when busy, etc. How robust are our strategies
  to these realistic behavioral deviations?

  Prior knowledge:
    - K456/K457: 12/VIX rule confirmed robust across assets
    - K499: Rebalancing frequency analysis — daily vs weekly vs monthly
    - K641: VIX regime decomposition — calm/normal/stress/crisis
    - K652: VIX action thresholds — when to act

Data source: yfinance (SPY, GLD, ^VIX), 2010-01-01 to 2026-03-27
Type: Simulation study (Monte Carlo on real data)

References:
  - Barber & Odean (2000) "Trading Is Hazardous to Your Wealth" JF
  - Dalbar (2023) QAIB Study — avg investor underperforms by 3-4% annually
  - Benartzi & Thaler (1995) "Myopic Loss Aversion" QJE — panic selling
  - Goetzmann & Kumar (2008) "Equity Portfolio Diversification" RFS
  - Frazzini (2006) "The Disposition Effect" JF — selling winners, holding losers
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
START_DATE = "2010-01-01"
END_DATE = "2026-03-27"
INITIAL_WEALTH = 100_000
N_BOOTSTRAP = 10_000
RANDOM_SEED = 42
RESULTS_FILE = Path(__file__).resolve().parent / "k653_results.json"


def download_data():
    """Download SPY, GLD, VIX data."""
    print("=" * 70)
    print("K653: Investor Behavior Simulation")
    print("=" * 70)
    print(f"\nDownloading data: SPY, GLD, ^VIX ({START_DATE} to {END_DATE})")

    spy = yf.download("SPY", start=START_DATE, end=END_DATE, progress=False)
    gld = yf.download("GLD", start=START_DATE, end=END_DATE, progress=False)
    vix = yf.download("^VIX", start=START_DATE, end=END_DATE, progress=False)

    # Handle multi-level columns from yfinance
    for df in [spy, gld, vix]:
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

    # Align all data
    common_idx = spy.index.intersection(gld.index).intersection(vix.index)
    spy = spy.loc[common_idx]
    gld = gld.loc[common_idx]
    vix = vix.loc[common_idx]

    print(f"  Common trading days: {len(common_idx)}")
    print(f"  Date range: {common_idx[0].strftime('%Y-%m-%d')} to {common_idx[-1].strftime('%Y-%m-%d')}")

    # Calculate returns
    spy_ret = spy['Close'].pct_change().dropna()
    gld_ret = gld['Close'].pct_change().dropna()
    vix_close = vix['Close']

    # Re-align after pct_change
    common_idx2 = spy_ret.index.intersection(gld_ret.index).intersection(vix_close.index)
    spy_ret = spy_ret.loc[common_idx2]
    gld_ret = gld_ret.loc[common_idx2]
    vix_close = vix_close.loc[common_idx2]

    print(f"  Return series length: {len(spy_ret)}")

    return spy_ret, gld_ret, vix_close


def compute_12vix_weights(vix_series):
    """Compute 12/VIX allocation weights for 50/50 SPY/GLD strategy."""
    total_w = np.minimum(12.0 / vix_series.values, 1.0)
    spy_w = 0.5 * total_w
    gld_w = 0.5 * total_w
    return spy_w, gld_w


def compute_portfolio_return(spy_ret, gld_ret, spy_w, gld_w):
    """Compute daily portfolio returns given weights and asset returns."""
    return spy_w * spy_ret.values + gld_w * gld_ret.values


def compute_metrics(daily_returns):
    """Compute Sharpe, MDD, terminal wealth from daily returns."""
    # Sharpe (annualized)
    if np.std(daily_returns) == 0:
        sharpe = 0.0
    else:
        sharpe = np.mean(daily_returns) / np.std(daily_returns) * np.sqrt(252)

    # Terminal wealth
    cumulative = np.cumprod(1 + daily_returns)
    terminal_wealth = INITIAL_WEALTH * cumulative[-1] if len(cumulative) > 0 else INITIAL_WEALTH

    # Max drawdown
    running_max = np.maximum.accumulate(cumulative)
    drawdowns = cumulative / running_max - 1
    mdd = np.min(drawdowns) if len(drawdowns) > 0 else 0.0

    # CAGR
    n_years = len(daily_returns) / 252
    if n_years > 0 and cumulative[-1] > 0:
        cagr = (cumulative[-1]) ** (1.0 / n_years) - 1
    else:
        cagr = 0.0

    return {
        'sharpe': float(sharpe),
        'mdd': float(mdd),
        'terminal_wealth': float(terminal_wealth),
        'cagr': float(cagr),
        'total_return': float(cumulative[-1] - 1) if len(cumulative) > 0 else 0.0,
    }


# ── Behavioral Deviation Simulators ──────────────────────────────────

def simulate_perfect_follower(spy_ret, gld_ret, vix_close, rng=None):
    """Baseline: follows strategy exactly every day."""
    spy_w, gld_w = compute_12vix_weights(vix_close)
    daily_ret = compute_portfolio_return(spy_ret, gld_ret, spy_w, gld_w)
    return daily_ret


def simulate_panic_seller(spy_ret, gld_ret, vix_close, rng=None):
    """
    Panic seller: exits to 100% cash when portfolio drops >3% in trailing 5 days.
    Re-enters only after 20 trading days.
    """
    spy_w_base, gld_w_base = compute_12vix_weights(vix_close)
    n = len(spy_ret)
    daily_ret = np.zeros(n)

    in_cash = False
    cash_countdown = 0

    # We need running portfolio value to compute weekly drawdown
    port_value = 1.0

    for i in range(n):
        if in_cash:
            daily_ret[i] = 0.0  # all cash
            cash_countdown -= 1
            if cash_countdown <= 0:
                in_cash = False
                port_value = 1.0  # reset tracking
        else:
            r = spy_w_base[i] * spy_ret.values[i] + gld_w_base[i] * gld_ret.values[i]
            daily_ret[i] = r
            port_value *= (1 + r)

            # Check trailing 5-day return
            if i >= 4:
                trailing_ret = np.prod(1 + daily_ret[i-4:i+1]) - 1
                if trailing_ret < -0.03:
                    in_cash = True
                    cash_countdown = 20
                    port_value = 1.0

    return daily_ret


def simulate_lazy_rebalancer(spy_ret, gld_ret, vix_close, rng=None):
    """
    Lazy rebalancer: only checks/rebalances with 30% probability each day.
    When not rebalancing, holds yesterday's weights (portfolio drifts).
    """
    if rng is None:
        rng = np.random.default_rng(RANDOM_SEED)

    spy_w_base, gld_w_base = compute_12vix_weights(vix_close)
    n = len(spy_ret)
    daily_ret = np.zeros(n)

    # Start with correct weights
    current_spy_w = spy_w_base[0]
    current_gld_w = gld_w_base[0]

    rebalance_mask = rng.random(n) < 0.30  # 30% chance each day
    rebalance_mask[0] = True  # always start correct

    for i in range(n):
        if rebalance_mask[i]:
            current_spy_w = spy_w_base[i]
            current_gld_w = gld_w_base[i]

        daily_ret[i] = current_spy_w * spy_ret.values[i] + current_gld_w * gld_ret.values[i]

        # Drift weights based on returns (portfolio weight drift)
        if not rebalance_mask[i] and i < n - 1:
            spy_value = current_spy_w * (1 + spy_ret.values[i])
            gld_value = current_gld_w * (1 + gld_ret.values[i])
            cash_value = (1 - current_spy_w - current_gld_w) * 1.0
            total = spy_value + gld_value + cash_value
            if total > 0:
                current_spy_w = spy_value / total
                current_gld_w = gld_value / total

    return daily_ret


def simulate_performance_chaser(spy_ret, gld_ret, vix_close, rng=None):
    """
    Performance chaser: After a good month (>2% return), increases allocation
    by 20%. After a bad month (<-2%), decreases by 20%.
    Multiplier bounded to [0.4, 1.6].
    Uses ~21 trading day blocks as proxy for months when DatetimeIndex is absent.
    """
    spy_w_base, gld_w_base = compute_12vix_weights(vix_close)
    n = len(spy_ret)
    daily_ret = np.zeros(n)

    multiplier = 1.0
    month_return = 0.0

    # Determine month boundaries
    has_datetime_index = hasattr(spy_ret.index, 'month') or (
        len(spy_ret.index) > 0 and hasattr(spy_ret.index[0], 'month'))

    for i in range(n):
        # Check if we crossed a month boundary
        if i > 0:
            if has_datetime_index:
                current_month = spy_ret.index[i].month
                prev_month = spy_ret.index[i-1].month
                new_month = (current_month != prev_month)
            else:
                # Use ~21 trading day blocks as month proxy
                new_month = (i % 21 == 0)

            if new_month:
                if month_return > 0.02:
                    multiplier = min(multiplier * 1.20, 1.6)
                elif month_return < -0.02:
                    multiplier = max(multiplier * 0.80, 0.4)
                month_return = 0.0

        adj_spy_w = spy_w_base[i] * multiplier
        adj_gld_w = gld_w_base[i] * multiplier
        # Cap at 100% total
        total = adj_spy_w + adj_gld_w
        if total > 1.0:
            adj_spy_w *= 1.0 / total
            adj_gld_w *= 1.0 / total

        r = adj_spy_w * spy_ret.values[i] + adj_gld_w * gld_ret.values[i]
        daily_ret[i] = r
        month_return = (1 + month_return) * (1 + r) - 1

    return daily_ret


def simulate_news_reactor(spy_ret, gld_ret, vix_close, rng=None):
    """
    News reactor: On days with VIX spike >3 points from previous close,
    panics to 50% of normal allocation. Normal next day.
    """
    spy_w_base, gld_w_base = compute_12vix_weights(vix_close)
    n = len(spy_ret)
    daily_ret = np.zeros(n)

    vix_vals = vix_close.values

    for i in range(n):
        # Check VIX spike (change from previous day)
        if i > 0:
            vix_change = vix_vals[i] - vix_vals[i-1]
        else:
            vix_change = 0

        if vix_change > 3.0:
            # Panic — halve allocation
            daily_ret[i] = 0.5 * spy_w_base[i] * spy_ret.values[i] + \
                           0.5 * gld_w_base[i] * gld_ret.values[i]
        else:
            daily_ret[i] = spy_w_base[i] * spy_ret.values[i] + \
                           gld_w_base[i] * gld_ret.values[i]

    return daily_ret


def simulate_overrider(spy_ret, gld_ret, vix_close, rng=None):
    """
    Overrider: Ignores strategy when VIX > 25 and goes 100% cash.
    Doesn't trust the model during stress periods.
    """
    spy_w_base, gld_w_base = compute_12vix_weights(vix_close)
    n = len(spy_ret)
    daily_ret = np.zeros(n)

    vix_vals = vix_close.values

    for i in range(n):
        if vix_vals[i] > 25:
            daily_ret[i] = 0.0  # all cash
        else:
            daily_ret[i] = spy_w_base[i] * spy_ret.values[i] + \
                           gld_w_base[i] * gld_ret.values[i]

    return daily_ret


# ── Main Experiment ──────────────────────────────────────────────────

def run_experiment():
    """Run the full behavior simulation experiment."""
    spy_ret, gld_ret, vix_close = download_data()

    # ── Descriptive Statistics ────────────────────────────────────────
    print("\n── Descriptive Statistics ──")
    print(f"  SPY: mean={spy_ret.mean():.6f}, std={spy_ret.std():.6f}, "
          f"skew={spy_ret.skew():.3f}, kurt={spy_ret.kurtosis():.3f}")
    print(f"  GLD: mean={gld_ret.mean():.6f}, std={gld_ret.std():.6f}, "
          f"skew={gld_ret.skew():.3f}, kurt={gld_ret.kurtosis():.3f}")
    print(f"  VIX: mean={vix_close.mean():.2f}, std={vix_close.std():.2f}, "
          f"min={vix_close.min():.2f}, max={vix_close.max():.2f}")

    # ── Define behavior types ────────────────────────────────────────
    behaviors = {
        'perfect_follower': {
            'name': 'Perfect Follower',
            'description': 'Follows 50/50 SPY/GLD 12/VIX strategy exactly every day',
            'simulator': simulate_perfect_follower,
            'is_deterministic': True,
        },
        'panic_seller': {
            'name': 'Panic Seller',
            'description': 'Exits to cash when portfolio drops >3% in a week, re-enters after 20 days',
            'simulator': simulate_panic_seller,
            'is_deterministic': True,
        },
        'lazy_rebalancer': {
            'name': 'Lazy Rebalancer',
            'description': 'Only rebalances 30% of days (random), weights drift otherwise',
            'simulator': simulate_lazy_rebalancer,
            'is_deterministic': False,
        },
        'performance_chaser': {
            'name': 'Performance Chaser',
            'description': 'Increases allocation 20% after good months, decreases 20% after bad months',
            'simulator': simulate_performance_chaser,
            'is_deterministic': True,
        },
        'news_reactor': {
            'name': 'News Reactor',
            'description': 'Halves allocation on days with VIX spike >3 points',
            'simulator': simulate_news_reactor,
            'is_deterministic': True,
        },
        'overrider': {
            'name': 'Overrider',
            'description': 'Goes 100% cash when VIX>25 (doesn\'t trust model during stress)',
            'simulator': simulate_overrider,
            'is_deterministic': True,
        },
    }

    # ── Run deterministic baselines ──────────────────────────────────
    print("\n── Running Deterministic Behavior Simulations ──")
    baseline_results = {}
    for key, behavior in behaviors.items():
        if behavior['is_deterministic']:
            daily_ret = behavior['simulator'](spy_ret, gld_ret, vix_close)
            metrics = compute_metrics(daily_ret)
            baseline_results[key] = metrics
            print(f"  {behavior['name']:25s} | Sharpe={metrics['sharpe']:.3f} | "
                  f"MDD={metrics['mdd']:.1%} | Terminal=${metrics['terminal_wealth']:,.0f} | "
                  f"CAGR={metrics['cagr']:.2%}")

    # ── Run stochastic simulations (bootstrap for lazy rebalancer) ───
    print(f"\n── Running Stochastic Simulations ({N_BOOTSTRAP:,} iterations) ──")

    # Lazy rebalancer needs Monte Carlo for the random rebalance mask
    rng = np.random.default_rng(RANDOM_SEED)
    lazy_metrics_list = []
    for i in range(N_BOOTSTRAP):
        daily_ret = simulate_lazy_rebalancer(spy_ret, gld_ret, vix_close, rng=rng)
        m = compute_metrics(daily_ret)
        lazy_metrics_list.append(m)
        if (i + 1) % 2500 == 0:
            print(f"    Lazy rebalancer: {i+1:,}/{N_BOOTSTRAP:,} done")

    lazy_sharpes = [m['sharpe'] for m in lazy_metrics_list]
    lazy_mdds = [m['mdd'] for m in lazy_metrics_list]
    lazy_terminals = [m['terminal_wealth'] for m in lazy_metrics_list]
    lazy_cagrs = [m['cagr'] for m in lazy_metrics_list]

    baseline_results['lazy_rebalancer'] = {
        'sharpe': float(np.mean(lazy_sharpes)),
        'sharpe_std': float(np.std(lazy_sharpes)),
        'sharpe_5pct': float(np.percentile(lazy_sharpes, 5)),
        'sharpe_95pct': float(np.percentile(lazy_sharpes, 95)),
        'mdd': float(np.mean(lazy_mdds)),
        'mdd_std': float(np.std(lazy_mdds)),
        'mdd_5pct': float(np.percentile(lazy_mdds, 5)),
        'mdd_95pct': float(np.percentile(lazy_mdds, 95)),
        'terminal_wealth': float(np.mean(lazy_terminals)),
        'terminal_wealth_std': float(np.std(lazy_terminals)),
        'terminal_wealth_5pct': float(np.percentile(lazy_terminals, 5)),
        'terminal_wealth_95pct': float(np.percentile(lazy_terminals, 95)),
        'cagr': float(np.mean(lazy_cagrs)),
        'total_return': float(np.mean([m['total_return'] for m in lazy_metrics_list])),
    }

    print(f"  Lazy Rebalancer (avg):   Sharpe={np.mean(lazy_sharpes):.3f} +/- {np.std(lazy_sharpes):.3f} | "
          f"MDD={np.mean(lazy_mdds):.1%} | Terminal=${np.mean(lazy_terminals):,.0f}")

    # ── Compute Behavioral Costs ─────────────────────────────────────
    print("\n── Behavioral Cost Analysis ──")
    perfect_terminal = baseline_results['perfect_follower']['terminal_wealth']
    perfect_cagr = baseline_results['perfect_follower']['cagr']
    perfect_sharpe = baseline_results['perfect_follower']['sharpe']

    behavioral_costs = {}
    for key in behaviors:
        if key == 'perfect_follower':
            continue
        bm = baseline_results[key]
        wealth_cost = perfect_terminal - bm['terminal_wealth']
        wealth_cost_pct = wealth_cost / perfect_terminal * 100
        cagr_cost = perfect_cagr - bm['cagr']
        sharpe_cost = perfect_sharpe - bm['sharpe']

        behavioral_costs[key] = {
            'name': behaviors[key]['name'],
            'description': behaviors[key]['description'],
            'wealth_cost_usd': float(wealth_cost),
            'wealth_cost_pct': float(wealth_cost_pct),
            'cagr_cost_bps': float(cagr_cost * 10000),
            'sharpe_cost': float(sharpe_cost),
            'terminal_wealth': float(bm['terminal_wealth']),
            'sharpe': float(bm['sharpe']),
            'mdd': float(bm['mdd']),
            'cagr': float(bm['cagr']),
        }
        print(f"  {behaviors[key]['name']:25s} | Wealth cost: ${wealth_cost:+,.0f} "
              f"({wealth_cost_pct:+.1f}%) | CAGR cost: {cagr_cost*100:+.2f}% | "
              f"Sharpe cost: {sharpe_cost:+.3f}")

    # ── Rank by wealth destruction ───────────────────────────────────
    print("\n── Ranking: Most Costly Behavioral Mistakes ──")
    ranked = sorted(behavioral_costs.items(), key=lambda x: x[1]['wealth_cost_usd'], reverse=True)
    for rank, (key, cost) in enumerate(ranked, 1):
        print(f"  #{rank}: {cost['name']:25s} — ${cost['wealth_cost_usd']:+,.0f} "
              f"({cost['wealth_cost_pct']:+.1f}% of perfect wealth)")
        behavioral_costs[key]['rank'] = rank

    # ── Statistical significance: bootstrap test ─────────────────────
    print("\n── Bootstrap Significance Tests (vs Perfect Follower) ──")

    # Block bootstrap for time-series dependence
    block_size = 20  # ~1 month trading blocks
    n_days = len(spy_ret)
    n_blocks = n_days // block_size

    rng_boot = np.random.default_rng(RANDOM_SEED + 100)
    boot_results = {key: [] for key in behaviors if key != 'perfect_follower'}

    for b in range(N_BOOTSTRAP):
        # Sample block indices with replacement
        block_starts = rng_boot.integers(0, n_days - block_size, size=n_blocks)
        indices = np.concatenate([np.arange(s, s + block_size) for s in block_starts])

        # Subset data
        spy_boot = spy_ret.iloc[indices].reset_index(drop=True)
        gld_boot = gld_ret.iloc[indices].reset_index(drop=True)
        vix_boot = vix_close.iloc[indices].reset_index(drop=True)

        # Perfect follower on bootstrap sample
        perfect_ret = simulate_perfect_follower(spy_boot, gld_boot, vix_boot)
        perfect_m = compute_metrics(perfect_ret)

        for key in boot_results:
            if key == 'lazy_rebalancer':
                behav_ret = simulate_lazy_rebalancer(spy_boot, gld_boot, vix_boot, rng=rng_boot)
            else:
                behav_ret = behaviors[key]['simulator'](spy_boot, gld_boot, vix_boot)
            behav_m = compute_metrics(behav_ret)
            boot_results[key].append(perfect_m['terminal_wealth'] - behav_m['terminal_wealth'])

        if (b + 1) % 2500 == 0:
            print(f"    Bootstrap: {b+1:,}/{N_BOOTSTRAP:,} done")

    significance_results = {}
    for key, diffs in boot_results.items():
        diffs_arr = np.array(diffs)
        mean_diff = np.mean(diffs_arr)
        se = np.std(diffs_arr)
        t_stat = mean_diff / se if se > 0 else 0
        p_value = 2 * (1 - stats.norm.cdf(abs(t_stat)))
        ci_lower = np.percentile(diffs_arr, 2.5)
        ci_upper = np.percentile(diffs_arr, 97.5)

        significance_results[key] = {
            'mean_wealth_cost': float(mean_diff),
            't_statistic': float(t_stat),
            'p_value': float(p_value),
            'ci_95_lower': float(ci_lower),
            'ci_95_upper': float(ci_upper),
            'significant_at_5pct': bool(p_value < 0.05),
            'significant_at_1pct': bool(p_value < 0.01),
        }
        sig_marker = "***" if p_value < 0.01 else ("**" if p_value < 0.05 else "")
        print(f"  {behaviors[key]['name']:25s} | t={t_stat:.2f}, p={p_value:.4f} "
              f"| 95% CI: [${ci_lower:+,.0f}, ${ci_upper:+,.0f}] {sig_marker}")

    # ── VIX regime analysis ──────────────────────────────────────────
    print("\n── Behavioral Cost by VIX Regime ──")
    vix_vals = vix_close.values
    regimes = {
        'calm (VIX<15)': vix_vals < 15,
        'normal (15-20)': (vix_vals >= 15) & (vix_vals < 20),
        'elevated (20-25)': (vix_vals >= 20) & (vix_vals < 25),
        'stress (25-35)': (vix_vals >= 25) & (vix_vals < 35),
        'crisis (VIX>35)': vix_vals >= 35,
    }

    regime_analysis = {}
    for regime_name, mask in regimes.items():
        n_days_regime = np.sum(mask)
        if n_days_regime < 10:
            continue

        regime_analysis[regime_name] = {
            'n_days': int(n_days_regime),
            'pct_of_total': float(n_days_regime / len(vix_vals) * 100),
        }

        # Perfect follower returns in this regime
        spy_w, gld_w = compute_12vix_weights(vix_close)
        perfect_regime_ret = (spy_w[mask] * spy_ret.values[mask] +
                              gld_w[mask] * gld_ret.values[mask])
        perfect_avg = np.mean(perfect_regime_ret) * 252

        print(f"\n  {regime_name} ({n_days_regime} days, {n_days_regime/len(vix_vals)*100:.1f}%):")

        for key in behavioral_costs:
            if key == 'lazy_rebalancer':
                # Use deterministic version for regime analysis (seed=42)
                rng_regime = np.random.default_rng(42)
                behav_ret_full = simulate_lazy_rebalancer(spy_ret, gld_ret, vix_close, rng=rng_regime)
            else:
                behav_ret_full = behaviors[key]['simulator'](spy_ret, gld_ret, vix_close)

            behav_regime_ret = behav_ret_full[mask]
            behav_avg = np.mean(behav_regime_ret) * 252
            cost = perfect_avg - behav_avg

            regime_analysis[regime_name][key] = {
                'annualized_cost_pct': float(cost * 100),
                'avg_daily_return_bps': float(np.mean(behav_regime_ret) * 10000),
            }
            print(f"    {behavioral_costs[key]['name']:25s} | Annualized cost: {cost*100:+.2f}%")

    # ── Practical insight ────────────────────────────────────────────
    worst_behavior = ranked[0]
    second_worst = ranked[1]

    practical_insight = (
        f"The most costly behavioral mistake is '{worst_behavior[1]['name']}' "
        f"(${worst_behavior[1]['wealth_cost_usd']:+,.0f}, "
        f"{worst_behavior[1]['wealth_cost_pct']:+.1f}% of perfect wealth). "
        f"Second worst is '{second_worst[1]['name']}' "
        f"(${second_worst[1]['wealth_cost_usd']:+,.0f}, "
        f"{second_worst[1]['wealth_cost_pct']:+.1f}%). "
        f"If you can only fix ONE behavioral tendency, fix '{worst_behavior[0].replace('_', ' ')}'."
    )
    print(f"\n── Practical Insight ──")
    print(f"  {practical_insight}")

    # ── Assemble results ─────────────────────────────────────────────
    results = {
        'experiment_id': 'K653',
        'title': 'Investor Behavior Simulation — What Happens When You Don\'t Follow the Strategy?',
        'type': 'simulation_study',
        'data_source': 'yfinance',
        'assets': ['SPY', 'GLD', '^VIX'],
        'period': f'{START_DATE} to {END_DATE}',
        'n_trading_days': int(len(spy_ret)),
        'initial_wealth': INITIAL_WEALTH,
        'base_strategy': '50/50 SPY/GLD with 12/VIX daily rebalance',
        'n_bootstrap': N_BOOTSTRAP,
        'block_size': block_size,
        'descriptive_stats': {
            'SPY': {
                'mean_daily': float(spy_ret.mean()),
                'std_daily': float(spy_ret.std()),
                'skewness': float(spy_ret.skew()),
                'kurtosis': float(spy_ret.kurtosis()),
            },
            'GLD': {
                'mean_daily': float(gld_ret.mean()),
                'std_daily': float(gld_ret.std()),
                'skewness': float(gld_ret.skew()),
                'kurtosis': float(gld_ret.kurtosis()),
            },
            'VIX': {
                'mean': float(vix_close.mean()),
                'std': float(vix_close.std()),
                'min': float(vix_close.min()),
                'max': float(vix_close.max()),
            },
        },
        'perfect_follower': baseline_results['perfect_follower'],
        'behavioral_results': baseline_results,
        'behavioral_costs': behavioral_costs,
        'ranking_by_wealth_destruction': [
            {'rank': i+1, 'behavior': key, 'name': cost['name'],
             'wealth_cost_usd': cost['wealth_cost_usd'],
             'wealth_cost_pct': cost['wealth_cost_pct']}
            for i, (key, cost) in enumerate(ranked)
        ],
        'bootstrap_significance': significance_results,
        'regime_analysis': regime_analysis,
        'practical_insight': practical_insight,
        'key_finding': f"Most costly mistake: {worst_behavior[1]['name']}",
        'recommendations': {
            'fix_first': worst_behavior[0],
            'fix_first_name': worst_behavior[1]['name'],
            'fix_first_cost': worst_behavior[1]['wealth_cost_usd'],
            'fix_second': second_worst[0],
            'fix_second_name': second_worst[1]['name'],
        },
        'limitations': [
            'Simulation assumes no transaction costs beyond weight changes',
            'Panic seller re-entry is fixed at 20 days (real investors vary)',
            'Lazy rebalancer 30% probability is assumed (real frequency varies by person)',
            'Performance chaser response is simplified to monthly evaluation',
            'VIX spike threshold of 3 points is a single fixed value',
            'Does not model partial behavioral deviations or combinations',
            'Tax implications of frequent trading not modeled',
            'Cash position earns 0% (ignores money market returns)',
        ],
        'references': [
            'Barber & Odean (2000) "Trading Is Hazardous to Your Wealth" JF',
            'Dalbar (2023) QAIB Study — avg investor underperforms by 3-4% annually',
            'Benartzi & Thaler (1995) "Myopic Loss Aversion" QJE',
            'Goetzmann & Kumar (2008) "Equity Portfolio Diversification" RFS',
            'Frazzini (2006) "The Disposition Effect" JF',
        ],
        'timestamp': datetime.now().isoformat(),
    }

    # Save results
    with open(RESULTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n  Results saved to {RESULTS_FILE}")

    return results


if __name__ == '__main__':
    run_experiment()
