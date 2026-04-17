"""
K668: VT Strategies for Retirement Portfolios — Sequence of Returns Risk
=========================================================================
Motivation: Jump exploration into retirement finance. Retirees face "sequence
of returns risk" — a market crash early in retirement is devastating because
you're withdrawing from a shrinking portfolio. VT's drawdown protection could
be especially valuable here.

Method:
- Starting portfolio: $1,000,000
- Annual withdrawal: $40,000 (4% rule), adjusted for inflation (2.5%/yr)
- Monthly withdrawal = annual / 12, compounded by inflation each year
- Rolling retirement windows: 10yr, 15yr, and 20yr (where data permits)
- Start dates: every month from 2006 to (data end - horizon)
- Compare 5 strategies: BH 60/40, 50/50 12/VIX, Piecewise Conservative,
  BH SPY, 80/20 12/VIX
- Key metrics: survival rate, median terminal wealth, worst-case terminal
  wealth, ruin probability, sustainable withdrawal rate
- Stress tests: retirees starting in 2007 (GFC) and 2019 (COVID)

Data source: yfinance (SPY, GLD, ^VIX), 2006-01-01 to 2026-03-27 (empirical)
Type: Empirical analysis (real data)

References:
- Bengen (1994) "Determining Withdrawal Rates Using Historical Data" — 4% rule
- Pfau (2012) "Capital Market Expectations" — sequence of returns risk
- Kitces (2008) "Resolving the Paradox" — dynamic withdrawal strategies
- Estrada (2018) "Sequence Risk: Is It Really a Big Deal?" — empirical evidence
- Blanchett et al. (2012) "Low Bond Yields and Safe Portfolio Withdrawal Rates"
"""

import json
import numpy as np
import yfinance as yf
from pathlib import Path
from datetime import datetime

# ── Configuration ──────────────────────────────────────────────────────
START_DATE = "2006-01-01"
END_DATE = "2026-03-27"
INITIAL_PORTFOLIO = 1_000_000
ANNUAL_WITHDRAWAL = 40_000   # 4% of initial
INFLATION_RATE = 0.025       # 2.5% annual
TRADING_DAYS_PER_YEAR = 252
TRADING_DAYS_PER_MONTH = 21  # approximate

RETIREMENT_HORIZONS = [10, 15, 20]  # years

np.random.seed(42)


def download_data():
    """Download SPY, GLD, VIX daily data from yfinance."""
    print("Downloading data from yfinance...")
    tickers = {"SPY": "SPY", "GLD": "GLD", "VIX": "^VIX"}
    data = {}
    for name, ticker in tickers.items():
        df = yf.download(ticker, start=START_DATE, end=END_DATE,
                         progress=False, auto_adjust=True)
        if df.empty:
            raise ValueError(f"No data for {ticker}")
        if hasattr(df.columns, 'levels') and len(df.columns.levels) > 1:
            df.columns = df.columns.get_level_values(0)
        data[name] = df
        print(f"  {name}: {len(df)} days ({df.index[0].date()} to {df.index[-1].date()})")
    return data


def align_data(data):
    """Align all series to common dates and compute daily returns."""
    common = data["SPY"].index.intersection(data["GLD"].index).intersection(data["VIX"].index)
    common = common.sort_values()
    print(f"Common trading days: {len(common)}")

    spy_close = data["SPY"].loc[common, "Close"].values.flatten()
    gld_close = data["GLD"].loc[common, "Close"].values.flatten()
    vix_close = data["VIX"].loc[common, "Close"].values.flatten()
    dates = [d.strftime("%Y-%m-%d") for d in common]

    spy_ret = np.diff(spy_close) / spy_close[:-1]
    gld_ret = np.diff(gld_close) / gld_close[:-1]
    vix_levels = vix_close[1:]
    dates = dates[1:]

    return dates, spy_ret, gld_ret, vix_levels


def compute_strategy_returns(spy_ret, gld_ret, vix_levels):
    """
    Compute daily returns for each retirement strategy.
    Uses previous day's VIX for signal (no lookahead bias).
    """
    n = len(spy_ret)
    strategies = {}

    # (a) Buy-and-Hold 60/40 SPY/GLD (traditional retirement)
    strategies["BH 60/40 SPY/GLD"] = 0.6 * spy_ret + 0.4 * gld_ret

    # (b) 50/50 SPY/GLD + 12/VIX
    ret_5050 = np.zeros(n)
    for i in range(n):
        vix_prev = vix_levels[i - 1] if i > 0 else vix_levels[0]
        w = min(12.0 / vix_prev, 1.0)
        ret_5050[i] = w * (0.5 * spy_ret[i] + 0.5 * gld_ret[i])
    strategies["50/50 SPY/GLD (12/VIX)"] = ret_5050

    # (c) Piecewise Conservative: 50/50 SPY/GLD with piecewise VIX mapping
    ret_pw = np.zeros(n)
    for i in range(n):
        vix_prev = vix_levels[i - 1] if i > 0 else vix_levels[0]
        if vix_prev < 12:
            w = 1.0
        elif vix_prev <= 20:
            w = (20 - vix_prev) / 8.0
        else:
            w = 0.0
        ret_pw[i] = w * (0.5 * spy_ret[i] + 0.5 * gld_ret[i])
    strategies["Piecewise Conservative"] = ret_pw

    # (d) Buy-and-Hold SPY (aggressive)
    strategies["BH SPY"] = spy_ret.copy()

    # (e) 80/20 SPY/GLD + 12/VIX (growth-oriented VT)
    ret_8020 = np.zeros(n)
    for i in range(n):
        vix_prev = vix_levels[i - 1] if i > 0 else vix_levels[0]
        w = min(12.0 / vix_prev, 1.0)
        ret_8020[i] = w * (0.8 * spy_ret[i] + 0.2 * gld_ret[i])
    strategies["80/20 SPY/GLD (12/VIX)"] = ret_8020

    return strategies


def simulate_retirement(daily_returns, initial_portfolio=INITIAL_PORTFOLIO,
                        annual_withdrawal=ANNUAL_WITHDRAWAL,
                        inflation_rate=INFLATION_RATE,
                        n_years=20):
    """
    Simulate a retirement drawdown path.

    Returns:
        survived: bool
        terminal_wealth: float
        ruin_day: int or None
        min_portfolio: float — minimum portfolio value during the period
        monthly_path: list — portfolio value sampled monthly
    """
    n_days = n_years * TRADING_DAYS_PER_YEAR
    if len(daily_returns) < n_days:
        return None, None, None, None, None

    portfolio = float(initial_portfolio)
    monthly_withdrawal_base = annual_withdrawal / 12.0

    monthly_path = [portfolio]
    ruin_day = None
    min_portfolio = portfolio
    days_in_month = 0
    months_elapsed = 0

    for day in range(n_days):
        portfolio *= (1 + daily_returns[day])
        days_in_month += 1
        min_portfolio = min(min_portfolio, portfolio)

        if days_in_month >= TRADING_DAYS_PER_MONTH:
            year_idx = months_elapsed // 12
            current_monthly = monthly_withdrawal_base * ((1 + inflation_rate) ** year_idx)
            portfolio -= current_monthly
            months_elapsed += 1
            days_in_month = 0
            monthly_path.append(max(portfolio, 0))
            min_portfolio = min(min_portfolio, portfolio)

        if portfolio <= 0:
            portfolio = 0
            ruin_day = day
            remaining = (n_years * 12) - len(monthly_path) + 1
            monthly_path.extend([0] * remaining)
            break

    survived = portfolio > 0
    terminal_wealth = max(portfolio, 0)

    return survived, terminal_wealth, ruin_day, min_portfolio, monthly_path


def find_sustainable_withdrawal_rate(strat_ret, start_indices, n_years,
                                      initial_portfolio=INITIAL_PORTFOLIO,
                                      target_survival=0.95):
    """
    Binary search for the maximum annual withdrawal rate where survival > target_survival.
    """
    if not start_indices:
        return 0.0

    n_days = n_years * TRADING_DAYS_PER_YEAR
    low_rate = 0.01
    high_rate = 0.15

    for _ in range(25):  # binary search iterations
        mid_rate = (low_rate + high_rate) / 2
        test_withdrawal = initial_portfolio * mid_rate

        n_survived = 0
        n_total = 0
        for idx in start_indices:
            if idx + n_days > len(strat_ret):
                continue
            survived, _, _, _, _ = simulate_retirement(
                strat_ret[idx:idx + n_days],
                initial_portfolio=initial_portfolio,
                annual_withdrawal=test_withdrawal,
                n_years=n_years,
            )
            if survived is not None:
                n_total += 1
                if survived:
                    n_survived += 1

        if n_total == 0:
            return 0.0

        survival_rate = n_survived / n_total
        if survival_rate >= target_survival:
            low_rate = mid_rate
        else:
            high_rate = mid_rate

    return round((low_rate + high_rate) / 2, 4)


def run_rolling_simulations(strategy_returns, dates, n_years):
    """
    Run retirement simulations starting monthly.
    Returns results for each strategy.
    """
    n_days = n_years * TRADING_DAYS_PER_YEAR

    # Build start indices: every ~21 trading days where full horizon fits
    start_indices = []
    start_dates_used = []
    i = 0
    while i < len(dates):
        if i + n_days <= len(dates):
            start_indices.append(i)
            start_dates_used.append(dates[i])
        i += TRADING_DAYS_PER_MONTH

    if not start_indices:
        return {}, []

    print(f"\n  Horizon: {n_years} years | {len(start_indices)} rolling windows "
          f"({start_dates_used[0]} to {start_dates_used[-1]})")

    results = {}

    for strat_name, strat_ret in strategy_returns.items():
        survivals = []
        terminal_wealths = []
        ruin_days = []
        min_portfolios = []

        for idx in start_indices:
            survived, tw, rd, mp, _ = simulate_retirement(
                strat_ret[idx:idx + n_days], n_years=n_years,
            )
            if survived is not None:
                survivals.append(survived)
                terminal_wealths.append(tw)
                min_portfolios.append(mp)
                if rd is not None:
                    ruin_days.append(rd)

        n_sims = len(survivals)
        if n_sims == 0:
            continue

        n_survived = sum(survivals)
        survival_rate = n_survived / n_sims
        tw_arr = np.array(terminal_wealths)
        mp_arr = np.array(min_portfolios)
        tw_survived = tw_arr[tw_arr > 0]

        swr = find_sustainable_withdrawal_rate(strat_ret, start_indices, n_years)

        strat_result = {
            "n_simulations": n_sims,
            "survival_rate": round(survival_rate, 4),
            "ruin_probability": round(1 - survival_rate, 4),
            "n_survived": n_survived,
            "n_ruined": n_sims - n_survived,
            "median_terminal_wealth": round(float(np.median(tw_arr)), 2),
            "mean_terminal_wealth": round(float(np.mean(tw_arr)), 2),
            "worst_terminal_wealth": round(float(np.min(tw_arr)), 2),
            "best_terminal_wealth": round(float(np.max(tw_arr)), 2),
            "p10_terminal_wealth": round(float(np.percentile(tw_arr, 10)), 2),
            "p25_terminal_wealth": round(float(np.percentile(tw_arr, 25)), 2),
            "p75_terminal_wealth": round(float(np.percentile(tw_arr, 75)), 2),
            "worst_min_portfolio": round(float(np.min(mp_arr)), 2),
            "median_min_portfolio": round(float(np.median(mp_arr)), 2),
            "sustainable_withdrawal_rate": swr,
            "sustainable_annual_dollar": round(swr * INITIAL_PORTFOLIO, 0),
            "avg_ruin_day": round(float(np.mean(ruin_days)), 0) if ruin_days else None,
            "avg_ruin_year": round(float(np.mean(ruin_days)) / TRADING_DAYS_PER_YEAR, 1) if ruin_days else None,
        }

        results[strat_name] = strat_result

    # Print summary table
    print(f"\n  {'Strategy':<30s} {'Survival':>8s} {'Median $':>14s} {'Worst $':>14s} "
          f"{'Worst Min $':>14s} {'SWR':>6s}")
    print("  " + "-" * 92)
    for name, res in sorted(results.items(),
                             key=lambda x: (-x[1]["survival_rate"],
                                            -x[1]["median_terminal_wealth"])):
        print(f"  {name:<30s} {res['survival_rate']*100:>7.1f}% "
              f"${res['median_terminal_wealth']:>12,.0f} "
              f"${res['worst_terminal_wealth']:>12,.0f} "
              f"${res['worst_min_portfolio']:>12,.0f} "
              f"{res['sustainable_withdrawal_rate']*100:>5.2f}%")

    return results, start_indices


def stress_test_specific_dates(strategy_returns, dates):
    """
    Test specific retirement start dates during known crises.
    Use available data up to 20 years or whatever is available.
    """
    stress_periods = {
        "GFC_2007": {"target": "2007-01", "label": "Pre-GFC (2007-01)"},
        "GFC_2008_Sep": {"target": "2008-09", "label": "GFC Peak (2008-09)"},
        "COVID_2020_Feb": {"target": "2020-02", "label": "Pre-COVID Crash (2020-02)"},
        "COVID_2020_Mar": {"target": "2020-03", "label": "COVID Bottom (2020-03)"},
    }

    results = {}

    for period_key, period_info in stress_periods.items():
        target = period_info["target"]
        label = period_info["label"]

        start_idx = None
        for i, d in enumerate(dates):
            if d.startswith(target):
                start_idx = i
                break

        if start_idx is None:
            continue

        actual_start = dates[start_idx]
        available_days = len(dates) - start_idx
        available_years = available_days / TRADING_DAYS_PER_YEAR

        print(f"\n  {label} (start={actual_start}, {available_years:.1f} years available)")

        period_results = {}
        for strat_name, strat_ret in strategy_returns.items():
            sim_ret = strat_ret[start_idx:]
            n_sim_days = len(sim_ret)

            portfolio = float(INITIAL_PORTFOLIO)
            monthly_withdrawal_base = ANNUAL_WITHDRAWAL / 12.0
            monthly_path = [portfolio]
            days_in_month = 0
            months_elapsed = 0
            ruin_day = None
            min_portfolio = portfolio

            for day in range(n_sim_days):
                portfolio *= (1 + sim_ret[day])
                days_in_month += 1
                min_portfolio = min(min_portfolio, portfolio)

                if days_in_month >= TRADING_DAYS_PER_MONTH:
                    year_idx = months_elapsed // 12
                    current_monthly = monthly_withdrawal_base * ((1 + INFLATION_RATE) ** year_idx)
                    portfolio -= current_monthly
                    months_elapsed += 1
                    days_in_month = 0
                    monthly_path.append(max(portfolio, 0))
                    min_portfolio = min(min_portfolio, portfolio)

                if portfolio <= 0:
                    portfolio = 0
                    ruin_day = day
                    break

            # Key: the drawdown in the first 3 years (sequence of returns)
            first_3yr_days = min(3 * TRADING_DAYS_PER_YEAR, n_sim_days)
            port_3yr = float(INITIAL_PORTFOLIO)
            min_3yr = port_3yr
            dm = 0
            me = 0
            for day in range(first_3yr_days):
                port_3yr *= (1 + sim_ret[day])
                dm += 1
                if dm >= TRADING_DAYS_PER_MONTH:
                    year_idx = me // 12
                    cur_m = monthly_withdrawal_base * ((1 + INFLATION_RATE) ** year_idx)
                    port_3yr -= cur_m
                    me += 1
                    dm = 0
                min_3yr = min(min_3yr, port_3yr)

            max_drawdown_3yr = (min_3yr - INITIAL_PORTFOLIO) / INITIAL_PORTFOLIO

            period_results[strat_name] = {
                "survived_to_end": portfolio > 0,
                "terminal_wealth": round(max(portfolio, 0), 2),
                "min_portfolio": round(min_portfolio, 2),
                "min_portfolio_pct_of_initial": round(min_portfolio / INITIAL_PORTFOLIO * 100, 1),
                "years_simulated": round(n_sim_days / TRADING_DAYS_PER_YEAR, 1),
                "ruin_year": round(ruin_day / TRADING_DAYS_PER_YEAR, 1) if ruin_day else None,
                "months_elapsed": months_elapsed,
                "first_3yr_min_portfolio": round(min_3yr, 2),
                "first_3yr_max_drawdown_pct": round(max_drawdown_3yr * 100, 1),
                "portfolio_after_3yr": round(port_3yr, 2),
            }

            status = "SURVIVED" if portfolio > 0 else f"RUINED yr {period_results[strat_name]['ruin_year']}"
            print(f"    {strat_name:<30s} {status:>12s} | "
                  f"terminal=${max(portfolio,0):>12,.0f} | "
                  f"min=${min_portfolio:>10,.0f} ({min_portfolio/INITIAL_PORTFOLIO*100:.0f}%) | "
                  f"3yr-min=${min_3yr:>10,.0f} ({max_drawdown_3yr*100:+.0f}%)")

        results[period_key] = {
            "label": label,
            "start_date": actual_start,
            "available_years": round(available_years, 1),
            "strategies": period_results,
        }

    return results


def withdrawal_rate_sensitivity(strategy_returns, dates, n_years=10):
    """
    Test different withdrawal rates. Use 10-year horizon for maximum start dates.
    """
    n_days = n_years * TRADING_DAYS_PER_YEAR
    start_indices = []
    i = 0
    while i < len(dates):
        if i + n_days <= len(dates):
            start_indices.append(i)
        i += TRADING_DAYS_PER_MONTH

    withdrawal_rates = [0.03, 0.035, 0.04, 0.045, 0.05, 0.055, 0.06, 0.07, 0.08, 0.10]

    results = {}

    for strat_name, strat_ret in strategy_returns.items():
        rate_results = {}
        for wr in withdrawal_rates:
            annual_wd = INITIAL_PORTFOLIO * wr
            n_survived = 0
            n_total = 0

            for idx in start_indices:
                if idx + n_days > len(strat_ret):
                    continue
                survived, tw, _, _, _ = simulate_retirement(
                    strat_ret[idx:idx + n_days],
                    annual_withdrawal=annual_wd,
                    n_years=n_years,
                )
                if survived is not None:
                    n_total += 1
                    if survived:
                        n_survived += 1

            survival_pct = round(n_survived / n_total * 100, 1) if n_total > 0 else 0
            rate_results[f"{wr*100:.1f}%"] = {
                "survival_rate_pct": survival_pct,
                "annual_withdrawal": round(annual_wd, 0),
                "n_sims": n_total,
            }

        results[strat_name] = rate_results

    return results


def sequence_of_returns_decomposition(strategy_returns, dates):
    """
    Decompose how much of retirement outcome depends on the FIRST 3 years.
    Compare retirees whose first 3 years had a crash vs. those who didn't.
    """
    n_years = 10
    n_days = n_years * TRADING_DAYS_PER_YEAR

    start_indices = []
    i = 0
    while i < len(dates):
        if i + n_days <= len(dates):
            start_indices.append(i)
        i += TRADING_DAYS_PER_MONTH

    results = {}

    for strat_name, strat_ret in strategy_returns.items():
        # For each start date, compute:
        # 1) Cumulative return in first 3 years
        # 2) Terminal wealth after 10 years
        first_3yr_rets = []
        terminal_wealths = []

        for idx in start_indices:
            if idx + n_days > len(strat_ret):
                continue

            # First 3 years cumulative return (without withdrawals, just portfolio growth)
            first_3yr_days = 3 * TRADING_DAYS_PER_YEAR
            cum_ret_3yr = float(np.prod(1 + strat_ret[idx:idx + first_3yr_days]) - 1)
            first_3yr_rets.append(cum_ret_3yr)

            # Full 10-year retirement sim
            survived, tw, _, _, _ = simulate_retirement(
                strat_ret[idx:idx + n_days], n_years=n_years,
            )
            if survived is not None:
                terminal_wealths.append(tw)
            else:
                terminal_wealths.append(0)

        first_3yr_rets = np.array(first_3yr_rets)
        terminal_wealths = np.array(terminal_wealths)

        # Split into "good start" (top 50%) and "bad start" (bottom 50%)
        median_3yr = np.median(first_3yr_rets)
        bad_mask = first_3yr_rets <= median_3yr
        good_mask = first_3yr_rets > median_3yr

        # Worst quartile
        q25_3yr = np.percentile(first_3yr_rets, 25)
        worst_mask = first_3yr_rets <= q25_3yr

        results[strat_name] = {
            "n_windows": len(first_3yr_rets),
            "median_first_3yr_return": round(float(median_3yr) * 100, 1),
            "good_start_median_terminal": round(float(np.median(terminal_wealths[good_mask])), 0),
            "bad_start_median_terminal": round(float(np.median(terminal_wealths[bad_mask])), 0),
            "worst_quartile_median_terminal": round(float(np.median(terminal_wealths[worst_mask])), 0),
            "good_start_survival_pct": round(float(np.mean(terminal_wealths[good_mask] > 0)) * 100, 1),
            "bad_start_survival_pct": round(float(np.mean(terminal_wealths[bad_mask] > 0)) * 100, 1),
            "worst_quartile_survival_pct": round(float(np.mean(terminal_wealths[worst_mask] > 0)) * 100, 1),
            "correlation_3yr_ret_vs_terminal": round(float(np.corrcoef(first_3yr_rets, terminal_wealths)[0, 1]), 3),
        }

    return results


def main():
    print("=" * 70)
    print("K668: VT Strategies for Retirement Portfolios")
    print("    Sequence of Returns Risk Analysis")
    print("=" * 70)

    # ── Step 1: Download data ──────────────────────────────────────────
    data = download_data()
    dates, spy_ret, gld_ret, vix_levels = align_data(data)

    print(f"\nData: {dates[0]} to {dates[-1]}, {len(spy_ret)} trading days "
          f"({len(spy_ret)/TRADING_DAYS_PER_YEAR:.1f} years)")

    # ── Step 2: Descriptive statistics ─────────────────────────────────
    print("\n" + "=" * 60)
    print("Descriptive Statistics")
    print("=" * 60)
    for name, ret in [("SPY", spy_ret), ("GLD", gld_ret)]:
        ann_r = np.mean(ret) * 252 * 100
        ann_v = np.std(ret) * np.sqrt(252) * 100
        skew = float(np.mean(((ret - np.mean(ret)) / np.std(ret)) ** 3))
        kurt = float(np.mean(((ret - np.mean(ret)) / np.std(ret)) ** 4)) - 3
        print(f"  {name}: mean={ann_r:.2f}%/yr, vol={ann_v:.2f}%/yr, "
              f"skew={skew:.3f}, kurt={kurt:.3f}")
    print(f"  VIX: mean={np.mean(vix_levels):.1f}, median={np.median(vix_levels):.1f}, "
          f"min={np.min(vix_levels):.1f}, max={np.max(vix_levels):.1f}")

    # ── Step 3: Compute strategy returns ───────────────────────────────
    print("\n" + "=" * 60)
    print("Strategy Annualized Returns (full sample)")
    print("=" * 60)
    strategy_returns = compute_strategy_returns(spy_ret, gld_ret, vix_levels)

    strat_stats = {}
    for name, ret in strategy_returns.items():
        ann_ret = np.mean(ret) * 252 * 100
        ann_vol = np.std(ret) * np.sqrt(252) * 100
        sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
        print(f"  {name:<30s}: {ann_ret:6.2f}%/yr, vol={ann_vol:5.2f}%, Sharpe={sharpe:.3f}")
        strat_stats[name] = {
            "ann_return_pct": round(ann_ret, 2),
            "ann_vol_pct": round(ann_vol, 2),
            "sharpe": round(sharpe, 3),
        }

    # ── Step 4: Rolling retirement simulations for each horizon ────────
    all_rolling = {}
    all_start_indices = {}
    for horizon in RETIREMENT_HORIZONS:
        print(f"\n{'=' * 60}")
        print(f"Rolling Retirement Simulations — {horizon}-Year Horizon")
        print("=" * 60)
        results, si = run_rolling_simulations(strategy_returns, dates, horizon)
        if results:
            all_rolling[f"{horizon}yr"] = results
            all_start_indices[horizon] = si

    # ── Step 5: Stress tests (use all available data) ──────────────────
    print(f"\n{'=' * 60}")
    print("Stress Tests: Crisis Start Dates (use all available data)")
    print("=" * 60)
    stress_results = stress_test_specific_dates(strategy_returns, dates)

    # ── Step 6: Withdrawal rate sensitivity (10-year horizon) ──────────
    print(f"\n{'=' * 60}")
    print("Withdrawal Rate Sensitivity (10-year horizon)")
    print("=" * 60)
    sensitivity_results = withdrawal_rate_sensitivity(strategy_returns, dates, n_years=10)

    for strat_name, rates in sensitivity_results.items():
        print(f"\n  {strat_name}:")
        for rate_key, rate_data in rates.items():
            bar = "#" * int(rate_data["survival_rate_pct"] / 5)
            print(f"    {rate_key}: {rate_data['survival_rate_pct']:5.1f}% "
                  f"(${rate_data['annual_withdrawal']:,.0f}/yr, n={rate_data['n_sims']})  {bar}")

    # ── Step 7: Sequence of returns decomposition ──────────────────────
    print(f"\n{'=' * 60}")
    print("Sequence of Returns Decomposition (10-year, first 3 years impact)")
    print("=" * 60)
    sor_results = sequence_of_returns_decomposition(strategy_returns, dates)

    print(f"\n  {'Strategy':<30s} {'Corr':>6s} {'Good Start':>12s} {'Bad Start':>12s} "
          f"{'Worst Q':>12s} {'Bad Surv%':>9s}")
    print("  " + "-" * 85)
    for name, res in sor_results.items():
        print(f"  {name:<30s} {res['correlation_3yr_ret_vs_terminal']:>6.3f} "
              f"${res['good_start_median_terminal']:>10,.0f} "
              f"${res['bad_start_median_terminal']:>10,.0f} "
              f"${res['worst_quartile_median_terminal']:>10,.0f} "
              f"{res['bad_start_survival_pct']:>8.1f}%")

    # ── Step 8: Cross-horizon ranking ──────────────────────────────────
    print(f"\n{'=' * 60}")
    print("Cross-Horizon Strategy Rankings")
    print("=" * 60)

    for horizon_key, results in all_rolling.items():
        ranking = sorted(results.items(),
                         key=lambda x: (-x[1]["survival_rate"],
                                        -x[1]["median_terminal_wealth"]))
        print(f"\n  {horizon_key} horizon:")
        print(f"  {'Rank':>4s} {'Strategy':<30s} {'Survival':>8s} {'Median Terminal':>15s} "
              f"{'Worst Min $':>14s} {'SWR':>6s}")
        print("  " + "-" * 82)
        for rank, (name, res) in enumerate(ranking, 1):
            print(f"  {rank:>4d} {name:<30s} {res['survival_rate']*100:>7.1f}% "
                  f"${res['median_terminal_wealth']:>13,.0f} "
                  f"${res['worst_min_portfolio']:>12,.0f} "
                  f"{res['sustainable_withdrawal_rate']*100:>5.2f}%")

    # ── Step 9: Compile and save ───────────────────────────────────────
    # Determine primary comparison (use 10yr as it has most data points)
    primary = all_rolling.get("10yr", {})
    if primary:
        vt_strats = [n for n in primary if "12/VIX" in n or "Piecewise" in n]
        bh_strats = [n for n in primary if "BH" in n]

        if vt_strats and bh_strats:
            best_vt = max(vt_strats, key=lambda n: (primary[n]["survival_rate"],
                                                     primary[n]["median_terminal_wealth"]))
            best_bh = max(bh_strats, key=lambda n: (primary[n]["survival_rate"],
                                                     primary[n]["median_terminal_wealth"]))
        else:
            best_vt = best_bh = list(primary.keys())[0]
    else:
        best_vt = best_bh = "N/A"

    key_findings = []

    # Finding 1: Overall best
    if primary:
        overall_rank = sorted(primary.items(),
                              key=lambda x: (-x[1]["survival_rate"],
                                             -x[1]["median_terminal_wealth"]))
        best_name, best_res = overall_rank[0]
        key_findings.append(
            f"10-year horizon: best strategy is {best_name} with "
            f"{best_res['survival_rate']*100:.1f}% survival, "
            f"${best_res['median_terminal_wealth']:,.0f} median terminal wealth, "
            f"SWR {best_res['sustainable_withdrawal_rate']*100:.2f}%."
        )

    # Finding 2: VT vs BH comparison
    if primary and best_vt != "N/A" and best_vt in primary and best_bh in primary:
        vt_res = primary[best_vt]
        bh_res = primary[best_bh]
        surv_diff = (vt_res["survival_rate"] - bh_res["survival_rate"]) * 100
        worst_min_vt = vt_res["worst_min_portfolio"]
        worst_min_bh = bh_res["worst_min_portfolio"]

        if surv_diff > 0:
            key_findings.append(
                f"VT improves retirement survival: {best_vt} ({vt_res['survival_rate']*100:.1f}%) "
                f"vs {best_bh} ({bh_res['survival_rate']*100:.1f}%), +{surv_diff:.1f}pp."
            )
        elif surv_diff == 0:
            key_findings.append(
                f"VT and BH have equal survival rates ({vt_res['survival_rate']*100:.1f}%). "
                f"VT worst-case floor: ${worst_min_vt:,.0f} vs BH: ${worst_min_bh:,.0f}."
            )
        else:
            key_findings.append(
                f"BH outperforms VT on survival: {best_bh} ({bh_res['survival_rate']*100:.1f}%) "
                f"vs {best_vt} ({vt_res['survival_rate']*100:.1f}%)."
            )

    # Finding 3: Downside protection
    if primary and best_vt in primary and best_bh in primary:
        vt_worst_min = primary[best_vt]["worst_min_portfolio"]
        bh_worst_min = primary[best_bh]["worst_min_portfolio"]
        key_findings.append(
            f"Worst-case minimum portfolio (downside floor): "
            f"VT ({best_vt}) ${vt_worst_min:,.0f} vs BH ({best_bh}) ${bh_worst_min:,.0f}. "
            f"{'VT protects better.' if vt_worst_min > bh_worst_min else 'BH has better floor.'}"
        )

    # Finding 4: Sequence of returns
    if sor_results:
        for name in ["BH SPY", "50/50 SPY/GLD (12/VIX)"]:
            if name in sor_results:
                r = sor_results[name]
                key_findings.append(
                    f"Sequence of returns for {name}: "
                    f"bad-start median terminal ${r['bad_start_median_terminal']:,.0f}, "
                    f"good-start ${r['good_start_median_terminal']:,.0f} "
                    f"(corr={r['correlation_3yr_ret_vs_terminal']:.3f})."
                )

    # Finding 5: SWR range
    if primary:
        swr_vals = {n: r["sustainable_withdrawal_rate"] for n, r in primary.items()}
        max_swr_name = max(swr_vals, key=swr_vals.get)
        min_swr_name = min(swr_vals, key=swr_vals.get)
        key_findings.append(
            f"Sustainable withdrawal rate (10yr, 95% survival): "
            f"{swr_vals[min_swr_name]*100:.2f}% ({min_swr_name}) to "
            f"{swr_vals[max_swr_name]*100:.2f}% ({max_swr_name})."
        )

    # Finding 6: GFC stress test
    if "GFC_2008_Sep" in stress_results:
        gfc = stress_results["GFC_2008_Sep"]["strategies"]
        # Who had the smallest drawdown?
        least_dd = min(gfc.items(), key=lambda x: x[1]["min_portfolio_pct_of_initial"])
        most_dd = max(gfc.items(), key=lambda x: x[1]["min_portfolio_pct_of_initial"])
        key_findings.append(
            f"GFC stress test (Sep 2008 start): "
            f"best downside protection = {most_dd[0]} (min portfolio {most_dd[1]['min_portfolio_pct_of_initial']}% of initial), "
            f"worst = {least_dd[0]} ({least_dd[1]['min_portfolio_pct_of_initial']}% of initial)."
        )

    final_results = {
        "experiment_id": "K668",
        "title": "VT Strategies for Retirement Portfolios: Sequence of Returns Risk",
        "type": "empirical_analysis",
        "data_source": "yfinance",
        "data_period": f"{dates[0]} to {dates[-1]}",
        "n_trading_days": len(spy_ret),
        "methodology": {
            "initial_portfolio": INITIAL_PORTFOLIO,
            "annual_withdrawal_4pct": ANNUAL_WITHDRAWAL,
            "inflation_rate": INFLATION_RATE,
            "retirement_horizons": RETIREMENT_HORIZONS,
            "rolling_step": "~monthly (21 trading days)",
            "strategy_signal": "Previous day VIX (no lookahead)",
            "withdrawal_timing": "Monthly (every 21 trading days), inflation-adjusted annually",
        },
        "descriptive_stats": {
            "SPY_ann_return_pct": round(np.mean(spy_ret) * 252 * 100, 2),
            "SPY_ann_vol_pct": round(np.std(spy_ret) * np.sqrt(252) * 100, 2),
            "GLD_ann_return_pct": round(np.mean(gld_ret) * 252 * 100, 2),
            "GLD_ann_vol_pct": round(np.std(gld_ret) * np.sqrt(252) * 100, 2),
            "VIX_mean": round(float(np.mean(vix_levels)), 2),
            "VIX_median": round(float(np.median(vix_levels)), 2),
        },
        "strategy_annualized": strat_stats,
        "rolling_simulations": all_rolling,
        "stress_tests": stress_results,
        "withdrawal_rate_sensitivity_10yr": sensitivity_results,
        "sequence_of_returns_decomposition_10yr": sor_results,
        "key_findings": key_findings,
        "limitations": [
            "Data covers 2006-2026 only (~20 years); limited number of 20-year windows",
            "10-year and 15-year horizons provide more rolling windows for robust analysis",
            "Daily rebalanced returns (approximation; real portfolios rebalance less frequently)",
            "Inflation assumed constant 2.5%/yr (real inflation varies significantly)",
            "No transaction costs modeled",
            "Cash portion earns 0% (real SHY/T-bills would earn some yield)",
            "Withdrawals are rigid (real retirees often adjust spending in down markets)",
            "VIX signal uses previous-day close",
            "Survivorship bias in SPY (failed companies dropped from S&P 500)",
            "This period (2006-2026) includes strong bull market recovery after GFC — results may be optimistic",
        ],
        "references": [
            "Bengen (1994) 'Determining Withdrawal Rates Using Historical Data'",
            "Pfau (2012) 'Capital Market Expectations, Sequence of Returns Risk'",
            "Kitces (2008) 'Resolving the Paradox — The 4% Rule'",
            "Estrada (2018) 'Sequence Risk: Is It Really a Big Deal?'",
            "Blanchett et al. (2012) 'Low Bond Yields and Safe Portfolio Withdrawal Rates'",
        ],
        "timestamp": datetime.now().isoformat(),
    }

    out_path = Path(__file__).parent / "k668_results.json"
    with open(out_path, "w") as f:
        json.dump(final_results, f, indent=2, default=str)
    print(f"\n{'=' * 60}")
    print(f"Results saved to {out_path}")

    print(f"\n{'=' * 60}")
    print("KEY FINDINGS")
    print("=" * 60)
    for i, f_ in enumerate(key_findings, 1):
        print(f"  {i}. {f_}")

    # Final answer
    print(f"\n{'=' * 60}")
    print("ANSWER: Should a retiree use VT strategies?")
    print("=" * 60)
    if primary and best_vt in primary and best_bh in primary:
        vt_r = primary[best_vt]
        bh_r = primary[best_bh]
        print(f"\n  Best VT: {best_vt}")
        print(f"    Survival={vt_r['survival_rate']*100:.1f}%, "
              f"Terminal=${vt_r['median_terminal_wealth']:,.0f}, "
              f"SWR={vt_r['sustainable_withdrawal_rate']*100:.2f}%, "
              f"Worst floor=${vt_r['worst_min_portfolio']:,.0f}")
        print(f"\n  Best BH: {best_bh}")
        print(f"    Survival={bh_r['survival_rate']*100:.1f}%, "
              f"Terminal=${bh_r['median_terminal_wealth']:,.0f}, "
              f"SWR={bh_r['sustainable_withdrawal_rate']*100:.2f}%, "
              f"Worst floor=${bh_r['worst_min_portfolio']:,.0f}")

        if vt_r["worst_min_portfolio"] > bh_r["worst_min_portfolio"]:
            print(f"\n  VT provides BETTER downside protection (worst-case floor "
                  f"${vt_r['worst_min_portfolio']:,.0f} vs ${bh_r['worst_min_portfolio']:,.0f}).")
            print(f"  Recommendation: VT strategies are valuable for RISK-AVERSE retirees")
            print(f"  who prioritize not running out of money over maximizing terminal wealth.")
        else:
            print(f"\n  BH provides comparable or better outcomes in this sample period.")
            print(f"  Note: This period includes a strong post-GFC bull market.")

    return final_results


if __name__ == "__main__":
    main()
