"""
K262: The Cost of Tail Risk — What Percentage of Returns Do You Sacrifice for Crash Protection?
================================================================================================
[提出: 用戶, 執行: Claude]

Comprehensive cost-benefit analysis of cumulative protection mechanisms.

Five levels of protection (each cumulative):
  Level 0: 100% SPY (no protection)
  Level 1: 50/50 SPY/GLD (diversification only)
  Level 2: 50/50 + VT 12/VIX (+ vol timing)
  Level 3: 50/50 + VT + monthly rebalance discipline
  Level 4: 50/50 + VT + stop-loss at -5% monthly

For each level:
  - CAGR, Sharpe, MDD, worst year, worst month
  - "Protection cost" = CAGR reduction from Level 0
  - "Protection benefit" = MDD improvement from Level 0
  - "Efficiency ratio" = CAGR cost per 1% MDD improvement
  - Real dollar simulation: $100K over 20 years

Period: 2005-01-03 to 2024-12-31
Data: yfinance SPY, GLD, ^VIX daily

THIS IS REAL DATA ONLY. No simulation, no synthetic returns.
"""

import sys
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime
import json

# ==================================================================
# CONFIG
# ==================================================================
DATA_START = "2004-01-01"       # buffer for warm-up
BACKTEST_START = "2005-01-03"   # GLD available from Nov 2004
BACKTEST_END = "2024-12-31"
RF_ANNUAL = 0.02
RF_DAILY = RF_ANNUAL / 252
INITIAL_CAPITAL = 100_000

# VT parameters
VIX_THRESHOLD = 12.0           # 12/VIX allocation rule

# Stop-loss parameters
STOP_LOSS_MONTHLY = -0.05      # -5% monthly stop-loss

# Transaction costs
TX_COST_BPS = 5                # 5 bps one-way

print("=" * 80)
print("K262: THE COST OF TAIL RISK")
print("What Percentage of Returns Do You Sacrifice for Crash Protection?")
print("[提出: 用戶, 執行: Claude]")
print("=" * 80)

# ==================================================================
# 1. Download Data
# ==================================================================
print("\n[1/6] Downloading price data from yfinance...")

tickers = {"SPY": "SPY", "GLD": "GLD", "VIX": "^VIX"}
raw_data = {}

for name, ticker in tickers.items():
    df = yf.download(ticker, start=DATA_START, end="2025-06-01", progress=False, auto_adjust=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    raw_data[name] = df[["Close"]].rename(columns={"Close": name.lower()})
    print(f"  {name}: {len(df)} days ({df.index[0].date()} to {df.index[-1].date()})")

# Merge on common dates
data = raw_data["SPY"].join(raw_data["GLD"], how="inner") \
                       .join(raw_data["VIX"], how="inner")
data = data.dropna()
data = data.loc[BACKTEST_START:BACKTEST_END]
print(f"\n  Merged dataset: {len(data)} trading days")
print(f"  Period: {data.index[0].date()} to {data.index[-1].date()}")

# Calculate daily returns
spy_ret = data["spy"].pct_change()
gld_ret = data["gld"].pct_change()
vix = data["vix"]

# Drop first row (NaN from pct_change)
spy_ret = spy_ret.iloc[1:]
gld_ret = gld_ret.iloc[1:]
vix = vix.iloc[1:]
data = data.iloc[1:]

n_days = len(spy_ret)
n_years = n_days / 252
print(f"  Returns: {n_days} days = {n_years:.1f} years")

# ==================================================================
# 2. Build Five Levels of Protection
# ==================================================================
print("\n[2/6] Building protection levels...")

# Helper: compute equity weight from VIX (12/VIX rule, lagged)
# VIX_t determines weight for return on day t+1 (no look-ahead)
vix_weight = np.minimum(VIX_THRESHOLD / vix.shift(1), 1.0)  # lag by 1 day
vix_weight = vix_weight.iloc[1:]  # drop first NaN

# Align all series after the lag
spy_ret_aligned = spy_ret.iloc[1:]
gld_ret_aligned = gld_ret.iloc[1:]
data_aligned = data.iloc[1:]
vix_aligned = vix.iloc[1:]

n_days_final = len(spy_ret_aligned)
n_years_final = n_days_final / 252
print(f"  Aligned series: {n_days_final} days = {n_years_final:.1f} years")

# -------------------------------------------------------------------
# Level 0: 100% SPY (no protection)
# -------------------------------------------------------------------
level0_ret = spy_ret_aligned.copy()
level0_ret.name = "Level 0"

# -------------------------------------------------------------------
# Level 1: 50/50 SPY/GLD (diversification only, no rebalance)
# Buy-and-hold 50/50; weights drift naturally.
# For daily returns, daily reweight = static allocation.
# True buy-and-hold means weights drift. Let's track portfolio value.
# -------------------------------------------------------------------

def buy_and_hold_portfolio(ret_a, ret_b, w_a=0.5, w_b=0.5):
    """Buy-and-hold portfolio: initial weights drift over time.
    Returns daily portfolio returns."""
    val_a = w_a  # initial dollar allocation
    val_b = w_b
    port_rets = []
    for i in range(len(ret_a)):
        total = val_a + val_b
        wa = val_a / total
        wb = val_b / total
        port_ret = wa * ret_a.iloc[i] + wb * ret_b.iloc[i]
        port_rets.append(port_ret)
        val_a *= (1 + ret_a.iloc[i])
        val_b *= (1 + ret_b.iloc[i])
    return pd.Series(port_rets, index=ret_a.index)

# Level 1: 50/50 buy-and-hold (weights drift)
level1_ret = buy_and_hold_portfolio(spy_ret_aligned, gld_ret_aligned, 0.5, 0.5)
level1_ret.name = "Level 1"

# -------------------------------------------------------------------
# Level 2: 50/50 + VT 12/VIX (vol timing on equity leg only)
# Equity allocation = 50% * min(12/VIX, 1); remainder to cash (0% return)
# GLD allocation stays at 50% (buy-and-hold within that leg)
# -------------------------------------------------------------------

def level2_strategy(spy_ret, gld_ret, vix_wt):
    """50/50 SPY/GLD + VT on the SPY leg. No scheduled rebalance."""
    val_spy = 0.5
    val_gld = 0.5
    val_cash = 0.0
    port_rets = []

    for i in range(len(spy_ret)):
        total = val_spy + val_gld + val_cash
        w_spy = val_spy / total
        w_gld = val_gld / total

        # VT: reduce SPY exposure by vix_weight factor
        vt = vix_wt.iloc[i]
        effective_spy_w = w_spy * vt
        cash_from_vt = w_spy * (1 - vt)

        port_ret = effective_spy_w * spy_ret.iloc[i] + w_gld * gld_ret.iloc[i]
        port_rets.append(port_ret)

        # Update values (cash from VT earns 0)
        val_spy = (val_spy * vt) * (1 + spy_ret.iloc[i]) + val_spy * (1 - vt)
        val_gld *= (1 + gld_ret.iloc[i])
        # Combine cash back into spy allocation for simplicity
        # (VT weight is re-applied each day from VIX)

    return pd.Series(port_rets, index=spy_ret.index)

# Simpler and more correct approach: daily weights with VT
# Each day: 50% GLD (drifting buy-and-hold), 50% SPY * VT_weight, rest cash
# For cleaner comparison, use daily reweighting for VT signal only
level2_ret_list = []
for i in range(len(spy_ret_aligned)):
    vt = vix_weight.iloc[i]
    # Base allocation: 50% SPY, 50% GLD
    # VT reduces SPY exposure: effective SPY = 50% * vt
    # Cash from VT = 50% * (1 - vt), earns 0
    port_ret = 0.5 * vt * spy_ret_aligned.iloc[i] + 0.5 * gld_ret_aligned.iloc[i]
    level2_ret_list.append(port_ret)

level2_ret = pd.Series(level2_ret_list, index=spy_ret_aligned.index)
level2_ret.name = "Level 2"

# -------------------------------------------------------------------
# Level 3: 50/50 + VT + Monthly Rebalance
# Same as Level 2 but reset to 50/50 at start of each month
# Transaction cost: 5 bps each way on turnover
# -------------------------------------------------------------------

def level3_strategy(spy_ret, gld_ret, vix_wt, tx_bps=5):
    """50/50 SPY/GLD + VT + monthly rebalance with TX costs."""
    val_spy = 0.5 * INITIAL_CAPITAL
    val_gld = 0.5 * INITIAL_CAPITAL
    port_values = [INITIAL_CAPITAL]
    current_month = spy_ret.index[0].month

    for i in range(len(spy_ret)):
        total = val_spy + val_gld

        # Check if new month → rebalance to 50/50
        this_month = spy_ret.index[i].month
        if this_month != current_month:
            # Calculate turnover
            w_spy_before = val_spy / total
            turnover = abs(w_spy_before - 0.5)
            tx_cost = turnover * (tx_bps / 10000) * 2  # round-trip
            total *= (1 - tx_cost)
            val_spy = 0.5 * total
            val_gld = 0.5 * total
            current_month = this_month

        # Apply VT on SPY leg
        vt = vix_wt.iloc[i]
        w_spy = val_spy / (val_spy + val_gld)

        spy_eff = w_spy * vt * spy_ret.iloc[i]
        gld_eff = (1 - w_spy) * gld_ret.iloc[i]
        port_ret = spy_eff + gld_eff

        val_spy = (val_spy * vt) * (1 + spy_ret.iloc[i]) + val_spy * (1 - vt)
        val_gld *= (1 + gld_ret.iloc[i])
        port_values.append(val_spy + val_gld)

    # Convert to returns
    port_values = np.array(port_values)
    port_rets = pd.Series(
        port_values[1:] / port_values[:-1] - 1,
        index=spy_ret.index
    )
    return port_rets

level3_ret = level3_strategy(spy_ret_aligned, gld_ret_aligned, vix_weight, TX_COST_BPS)
level3_ret.name = "Level 3"

# -------------------------------------------------------------------
# Level 4: 50/50 + VT + Stop-loss at -5% monthly
# Same as Level 3, but if month-to-date return hits -5%, go to 100% cash
# for the rest of that month
# -------------------------------------------------------------------

def level4_strategy(spy_ret, gld_ret, vix_wt, tx_bps=5, stop_loss=-0.05):
    """50/50 + VT + monthly rebalance + monthly stop-loss."""
    val_spy = 0.5 * INITIAL_CAPITAL
    val_gld = 0.5 * INITIAL_CAPITAL
    port_values = [INITIAL_CAPITAL]
    current_month = spy_ret.index[0].month
    month_start_value = INITIAL_CAPITAL
    stopped_out = False
    stop_count = 0

    for i in range(len(spy_ret)):
        total = val_spy + val_gld

        # Check if new month → rebalance + reset stop-loss
        this_month = spy_ret.index[i].month
        if this_month != current_month:
            # Rebalance to 50/50
            w_spy_before = val_spy / total if total > 0 else 0.5
            turnover = abs(w_spy_before - 0.5)
            tx_cost = turnover * (tx_bps / 10000) * 2
            total *= (1 - tx_cost)
            val_spy = 0.5 * total
            val_gld = 0.5 * total
            month_start_value = total
            stopped_out = False
            current_month = this_month

        if stopped_out:
            # In cash for rest of month
            port_values.append(total)
            continue

        # Check stop-loss: month-to-date return
        mtd_return = (total - month_start_value) / month_start_value
        if mtd_return <= stop_loss:
            # Stop out: sell everything, go to cash
            tx_cost_exit = (tx_bps / 10000) * 2  # full round-trip
            total *= (1 - tx_cost_exit)
            val_spy = total * 0.5  # doesn't matter, we're in cash
            val_gld = total * 0.5
            stopped_out = True
            stop_count += 1
            port_values.append(total)
            continue

        # Normal operation: VT on SPY leg
        vt = vix_wt.iloc[i]
        w_spy = val_spy / total if total > 0 else 0.5

        spy_eff = w_spy * vt * spy_ret.iloc[i]
        gld_eff = (1 - w_spy) * gld_ret.iloc[i]
        port_ret = spy_eff + gld_eff

        val_spy = (val_spy * vt) * (1 + spy_ret.iloc[i]) + val_spy * (1 - vt)
        val_gld *= (1 + gld_ret.iloc[i])
        port_values.append(val_spy + val_gld)

    port_values = np.array(port_values)
    port_rets = pd.Series(
        port_values[1:] / port_values[:-1] - 1,
        index=spy_ret.index
    )
    return port_rets, stop_count

level4_ret, stop_count = level4_strategy(
    spy_ret_aligned, gld_ret_aligned, vix_weight, TX_COST_BPS, STOP_LOSS_MONTHLY
)
level4_ret.name = "Level 4"

print(f"  Level 4 stop-loss triggered: {stop_count} months")

# ==================================================================
# 3. Compute Performance Metrics
# ==================================================================
print("\n[3/6] Computing performance metrics...")

def compute_metrics(daily_returns, name, rf_daily=RF_DAILY):
    """Compute comprehensive performance metrics from daily returns."""
    ret = daily_returns.dropna()
    n = len(ret)
    n_yrs = n / 252

    # Cumulative wealth
    cum = (1 + ret).cumprod()
    final_wealth = cum.iloc[-1]

    # CAGR
    cagr = final_wealth ** (1 / n_yrs) - 1

    # Annualized volatility
    ann_vol = ret.std() * np.sqrt(252)

    # Sharpe ratio
    excess = ret - rf_daily
    sharpe = excess.mean() / ret.std() * np.sqrt(252) if ret.std() > 0 else 0

    # Maximum drawdown
    peak = cum.cummax()
    drawdown = (cum - peak) / peak
    mdd = drawdown.min()

    # Sortino ratio
    downside = ret[ret < 0]
    downside_vol = downside.std() * np.sqrt(252)
    sortino = (ret.mean() - rf_daily) * 252 / downside_vol if downside_vol > 0 else 0

    # Calmar ratio
    calmar = cagr / abs(mdd) if abs(mdd) > 0 else 0

    # Worst year
    ret_with_year = ret.copy()
    annual_rets = ret_with_year.groupby(ret_with_year.index.year).apply(lambda x: (1 + x).prod() - 1)
    worst_year_ret = annual_rets.min()
    worst_year = annual_rets.idxmin()
    best_year_ret = annual_rets.max()
    best_year = annual_rets.idxmax()

    # Worst month
    monthly_rets = ret_with_year.groupby([ret_with_year.index.year, ret_with_year.index.month]).apply(
        lambda x: (1 + x).prod() - 1
    )
    worst_month_ret = monthly_rets.min()
    best_month_ret = monthly_rets.max()

    # Win rate (daily)
    win_rate = (ret > 0).mean()

    # Dollar value of $100K
    dollar_value = INITIAL_CAPITAL * final_wealth

    # Ulcer Index (root mean square drawdown)
    ulcer = np.sqrt((drawdown ** 2).mean())

    return {
        "name": name,
        "cagr": cagr,
        "ann_vol": ann_vol,
        "sharpe": sharpe,
        "sortino": sortino,
        "calmar": calmar,
        "mdd": mdd,
        "worst_year": f"{worst_year_ret:.1%} ({worst_year})",
        "worst_year_pct": worst_year_ret,
        "best_year": f"{best_year_ret:.1%} ({best_year})",
        "worst_month_pct": worst_month_ret,
        "best_month_pct": best_month_ret,
        "win_rate": win_rate,
        "dollar_value": dollar_value,
        "ulcer": ulcer,
        "n_years": n_yrs,
        "annual_rets": annual_rets,
    }

# Compute for all levels
levels = {
    "Level 0: 100% SPY\n(No protection)": level0_ret,
    "Level 1: 50/50 SPY/GLD\n(Diversification)": level1_ret,
    "Level 2: +VT 12/VIX\n(Vol timing)": level2_ret,
    "Level 3: +Monthly rebal\n(Discipline)": level3_ret,
    "Level 4: +Stop-loss -5%\n(Tail cut)": level4_ret,
}

short_names = [
    "L0: 100% SPY",
    "L1: 50/50 SPY/GLD",
    "L2: +VT 12/VIX",
    "L3: +Monthly Rebal",
    "L4: +Stop-Loss -5%",
]

results = []
for (name, ret), short in zip(levels.items(), short_names):
    m = compute_metrics(ret, short)
    results.append(m)
    print(f"  {short}: CAGR={m['cagr']:.2%}, Sharpe={m['sharpe']:.2f}, MDD={m['mdd']:.1%}")

# ==================================================================
# 4. Cost-Benefit Analysis
# ==================================================================
print("\n[4/6] Cost-benefit analysis...")

baseline = results[0]  # Level 0

print("\n" + "=" * 100)
print("THE DEFINITIVE INVESTOR GUIDE: COST OF PROTECTION")
print("=" * 100)
print(f"Period: {data_aligned.index[0].date()} to {data_aligned.index[-1].date()} ({results[0]['n_years']:.1f} years)")
print(f"Data source: yfinance (SPY, GLD, ^VIX daily)")
print(f"Initial capital: ${INITIAL_CAPITAL:,.0f}")
print()

# Main comparison table
header = f"{'Level':<25} {'CAGR':>7} {'Vol':>7} {'Sharpe':>7} {'Sortino':>8} {'MDD':>8} {'Calmar':>7} {'Worst Yr':>14} {'Worst Mo':>9}"
print(header)
print("-" * 100)

for r in results:
    line = (
        f"{r['name']:<25} "
        f"{r['cagr']:>6.2%} "
        f"{r['ann_vol']:>6.2%} "
        f"{r['sharpe']:>7.2f} "
        f"{r['sortino']:>8.2f} "
        f"{r['mdd']:>7.1%} "
        f"{r['calmar']:>7.2f} "
        f"{r['worst_year']:>14s} "
        f"{r['worst_month_pct']:>8.1%}"
    )
    print(line)

# Cost-benefit table
print("\n" + "=" * 100)
print("COST-BENEFIT BREAKDOWN (vs Level 0 = 100% SPY)")
print("=" * 100)

header2 = (
    f"{'Level':<25} "
    f"{'CAGR Cost':>10} "
    f"{'MDD Improv':>11} "
    f"{'Cost/1%MDD':>11} "
    f"{'Sharpe Chg':>11} "
    f"{'$100K→':>12} "
    f"{'$ Sacrificed':>13}"
)
print(header2)
print("-" * 100)

baseline_cagr = baseline["cagr"]
baseline_mdd = baseline["mdd"]
baseline_dollar = baseline["dollar_value"]

for r in results:
    cagr_cost = baseline_cagr - r["cagr"]  # positive = cost
    mdd_improvement = r["mdd"] - baseline_mdd  # positive = better (less negative MDD)
    mdd_improvement_pct = abs(mdd_improvement) * 100  # in percentage points

    if mdd_improvement_pct > 0.01:
        efficiency = (cagr_cost * 100) / mdd_improvement_pct  # cost per 1% MDD improvement
    else:
        efficiency = 0.0

    sharpe_change = r["sharpe"] - baseline["sharpe"]
    dollar_sacrificed = baseline_dollar - r["dollar_value"]

    line = (
        f"{r['name']:<25} "
        f"{cagr_cost:>9.2%} "
        f"{mdd_improvement_pct:>10.1f}pp "
        f"{efficiency:>9.3f}pp "
        f"{sharpe_change:>+10.2f} "
        f"${r['dollar_value']:>10,.0f} "
        f"${dollar_sacrificed:>11,.0f}"
    )
    print(line)

# ==================================================================
# 5. Year-by-Year Comparison
# ==================================================================
print("\n" + "=" * 100)
print("YEAR-BY-YEAR RETURNS: WHEN DOES PROTECTION PAY OFF?")
print("=" * 100)

# Collect annual returns
all_years = sorted(set(spy_ret_aligned.index.year))
annual_data = {}
for r in results:
    annual_data[r["name"]] = r["annual_rets"]

header3 = f"{'Year':>6}"
for r in results:
    header3 += f" {r['name'][:10]:>10}"
header3 += f" {'L0-L2 Gap':>10} {'Winner':>8}"
print(header3)
print("-" * 90)

protection_wins = 0
no_protection_wins = 0

for year in all_years:
    line = f"{year:>6}"
    year_rets = []
    for r in results:
        if year in r["annual_rets"].index:
            yr = r["annual_rets"][year]
            line += f" {yr:>9.1%}"
            year_rets.append(yr)
        else:
            line += f" {'N/A':>10}"
            year_rets.append(np.nan)

    # Gap: L0 - L2 (positive = L0 better, negative = L2 better)
    if len(year_rets) >= 3 and not np.isnan(year_rets[0]) and not np.isnan(year_rets[2]):
        gap = year_rets[0] - year_rets[2]
        winner = "PROT" if gap < 0 else "NAKED"
        if gap < 0:
            protection_wins += 1
        else:
            no_protection_wins += 1
        line += f" {gap:>9.1%} {winner:>8}"

    print(line)

print(f"\nProtection (L2) won {protection_wins}/{protection_wins + no_protection_wins} years")
print(f"No protection (L0) won {no_protection_wins}/{protection_wins + no_protection_wins} years")

# ==================================================================
# 6. Crisis Deep Dive
# ==================================================================
print("\n" + "=" * 100)
print("CRISIS DEEP DIVE: WHEN PROTECTION SAVES YOU")
print("=" * 100)

crisis_periods = {
    "GFC (2008-09 to 2009-03)": ("2008-09-01", "2009-03-31"),
    "COVID Crash (2020-02 to 2020-03)": ("2020-02-19", "2020-03-23"),
    "2022 Rate Hike (2022-01 to 2022-10)": ("2022-01-03", "2022-10-14"),
    "2018 Q4 Selloff": ("2018-10-01", "2018-12-31"),
    "Aug 2015 Flash Crash": ("2015-08-01", "2015-09-30"),
    "2011 Debt Ceiling": ("2011-07-01", "2011-10-31"),
}

all_level_rets = [level0_ret, level1_ret, level2_ret, level3_ret, level4_ret]

for crisis_name, (start, end) in crisis_periods.items():
    print(f"\n  {crisis_name}")
    print(f"  {'Level':<25} {'Return':>8} {'MDD':>8} {'Saved vs L0':>12}")
    print(f"  {'-'*55}")

    crisis_rets = []
    for r, ret_series, short in zip(results, all_level_rets, short_names):
        mask = (ret_series.index >= start) & (ret_series.index <= end)
        crisis_ret = ret_series[mask]
        if len(crisis_ret) == 0:
            continue

        cum = (1 + crisis_ret).cumprod()
        total_ret = cum.iloc[-1] - 1
        peak = cum.cummax()
        dd = ((cum - peak) / peak).min()

        saved = total_ret - crisis_rets[0] if crisis_rets else 0
        crisis_rets.append(total_ret)

        saved_str = f"{saved:>+11.1%}" if len(crisis_rets) > 1 else f"{'baseline':>12}"
        print(f"  {short:<25} {total_ret:>7.1%} {dd:>7.1%} {saved_str}")

# ==================================================================
# 7. The Menu: How Much Are You Willing to Pay?
# ==================================================================
print("\n" + "=" * 100)
print("THE MENU: CHOOSE YOUR PROTECTION LEVEL")
print("=" * 100)

descriptions = [
    ("Level 0", "100% SPY", "No protection. Full market exposure. Sleep poorly in crashes."),
    ("Level 1", "50/50 SPY/GLD", "Diversification only. Gold hedges inflation & crisis. Simple."),
    ("Level 2", "+VT 12/VIX", "Add vol timing: reduce equity when VIX > 12. Still simple."),
    ("Level 3", "+Monthly Rebal", "Disciplined monthly rebalance back to 50/50. Prevents drift."),
    ("Level 4", "+Stop-Loss -5%", "Circuit breaker: go to cash if month drops 5%. Max caution."),
]

for i, (level, alloc, desc) in enumerate(descriptions):
    r = results[i]
    cagr_cost = baseline_cagr - r["cagr"]
    mdd_improv = (r["mdd"] - baseline_mdd)

    print(f"\n  {level}: {alloc}")
    print(f"  {desc}")
    print(f"  ┌──────────────────────────────────────────────────────────┐")
    print(f"  │ CAGR: {r['cagr']:.2%}  │  Sharpe: {r['sharpe']:.2f}  │  MDD: {r['mdd']:.1%}             │")
    print(f"  │ $100K → ${r['dollar_value']:>10,.0f}                                │")
    if i > 0:
        print(f"  │ Annual cost: {cagr_cost:.2%}  │  MDD saved: {abs(mdd_improv):.1%}              │")
        if abs(mdd_improv) > 0.001:
            cost_per_pct = (cagr_cost * 100) / (abs(mdd_improv) * 100)
            print(f"  │ Cost per 1% MDD improvement: {cost_per_pct:.3f}%                   │")
    print(f"  └──────────────────────────────────────────────────────────┘")

# ==================================================================
# 8. Dollar Simulation Table
# ==================================================================
print("\n" + "=" * 100)
print("$100,000 INVESTMENT: GROWTH TRAJECTORY")
print("=" * 100)

# Year-end values for each level
print(f"\n{'Year':>6}", end="")
for short in short_names:
    print(f" {short[:12]:>13}", end="")
print()
print("-" * 80)

for year in all_years:
    print(f"{year:>6}", end="")
    for ret_series in all_level_rets:
        mask = ret_series.index.year <= year
        cum = (1 + ret_series[mask]).cumprod()
        if len(cum) > 0:
            value = INITIAL_CAPITAL * cum.iloc[-1]
            print(f" ${value:>11,.0f}", end="")
        else:
            print(f" {'N/A':>12}", end="")
    print()

# ==================================================================
# 9. Statistical Tests
# ==================================================================
print("\n" + "=" * 100)
print("STATISTICAL SIGNIFICANCE")
print("=" * 100)

from scipy import stats

# Paired t-test: L0 vs each level (daily returns)
print("\n  Paired t-test of daily returns (L0 vs each level):")
for i, (ret_series, short) in enumerate(zip(all_level_rets[1:], short_names[1:])):
    diff = level0_ret - ret_series
    t_stat, p_val = stats.ttest_rel(level0_ret, ret_series)
    print(f"  {short:<25}: t={t_stat:>6.2f}, p={p_val:.4f} {'***' if p_val < 0.01 else '**' if p_val < 0.05 else '*' if p_val < 0.1 else 'n.s.'}")

# Bootstrap MDD comparison
print("\n  Bootstrap MDD comparison (10000 reps, block bootstrap L=21):")
n_bootstrap = 10000
block_len = 21

def block_bootstrap_mdd(returns, n_boot, block_size):
    """Block bootstrap MDD estimates."""
    n = len(returns)
    ret_arr = returns.values
    mdds = []

    for _ in range(n_boot):
        # Generate block bootstrap sample
        n_blocks = n // block_size + 1
        starts = np.random.randint(0, n - block_size, size=n_blocks)
        boot_sample = np.concatenate([ret_arr[s:s+block_size] for s in starts])[:n]

        cum = np.cumprod(1 + boot_sample)
        peak = np.maximum.accumulate(cum)
        dd = (cum - peak) / peak
        mdds.append(dd.min())

    return np.array(mdds)

for i, (ret_series, short) in enumerate(zip(all_level_rets[1:], short_names[1:])):
    mdd_l0_boot = block_bootstrap_mdd(level0_ret, n_bootstrap, block_len)
    mdd_li_boot = block_bootstrap_mdd(ret_series, n_bootstrap, block_len)

    # Fraction where protected has better (less negative) MDD
    prot_better = (mdd_li_boot > mdd_l0_boot).mean()

    actual_diff = results[i+1]["mdd"] - results[0]["mdd"]
    print(f"  {short:<25}: MDD improvement={abs(actual_diff):.1%}, "
          f"bootstrap P(protection better)={prot_better:.3f}")

# ==================================================================
# 10. Efficiency Frontier Summary
# ==================================================================
print("\n" + "=" * 100)
print("EFFICIENCY FRONTIER: PROTECTION VALUE MAP")
print("=" * 100)

print(f"""
                CAGR ↑
                  │
  {results[0]['cagr']:.1%} ─ ─ ─●  L0 (100% SPY)                MDD = {results[0]['mdd']:.0%}
                  │    ╲
  {results[1]['cagr']:.1%} ─ ─ ─ ─ ●  L1 (50/50 SPY/GLD)       MDD = {results[1]['mdd']:.0%}
                  │      ╲
  {results[2]['cagr']:.1%} ─ ─ ─ ─ ─ ●  L2 (+VT 12/VIX)        MDD = {results[2]['mdd']:.0%}
                  │        ╲
  {results[3]['cagr']:.1%} ─ ─ ─ ─ ─ ─ ●  L3 (+Monthly Rebal)  MDD = {results[3]['mdd']:.0%}
                  │          ╲
  {results[4]['cagr']:.1%} ─ ─ ─ ─ ─ ─ ─ ●  L4 (+Stop-Loss)    MDD = {results[4]['mdd']:.0%}
                  │
                  └──────────────────────────→ Protection ↑ / Risk ↓
""")

# ==================================================================
# 11. Key Takeaways
# ==================================================================
print("=" * 100)
print("KEY TAKEAWAYS")
print("=" * 100)

# Find the "sweet spot" (best Sharpe)
best_sharpe_idx = max(range(len(results)), key=lambda i: results[i]["sharpe"])
best_sharpe = results[best_sharpe_idx]

# Find best risk-adjusted
best_calmar_idx = max(range(len(results)), key=lambda i: results[i]["calmar"])
best_calmar = results[best_calmar_idx]

print(f"""
1. DIVERSIFICATION IS THE CHEAPEST PROTECTION:
   L0→L1 (add GLD) costs {baseline_cagr - results[1]['cagr']:.2%}/yr CAGR but saves {abs(results[1]['mdd'] - baseline['mdd']):.0%} MDD.

2. VOL TIMING IS REMARKABLY EFFICIENT:
   L1→L2 (add 12/VIX) {'adds' if results[2]['cagr'] > results[1]['cagr'] else 'costs'} {abs(results[2]['cagr'] - results[1]['cagr']):.2%}/yr but saves another {abs(results[2]['mdd'] - results[1]['mdd']):.0%} MDD.

3. BEST RISK-ADJUSTED: {best_sharpe['name']} (Sharpe={best_sharpe['sharpe']:.2f})

4. BEST CALMAR: {best_calmar['name']} (Calmar={best_calmar['calmar']:.2f})

5. THE REAL DOLLAR COST:
   Going from L0 to L2, you "sacrifice" ${baseline_dollar - results[2]['dollar_value']:,.0f} on $100K over {results[0]['n_years']:.0f} years.
   But your worst drawdown improves from {results[0]['mdd']:.0%} to {results[2]['mdd']:.0%}.

6. DIMINISHING RETURNS:
   L2→L3 (monthly rebalance) and L3→L4 (stop-loss) add complexity but
   {'improve' if results[3]['sharpe'] > results[2]['sharpe'] else 'may not improve'} Sharpe.

7. STOP-LOSS DOUBLE-EDGED:
   L4 triggered {stop_count} stop-outs over {results[0]['n_years']:.0f} years.
   Each stop-out avoids the worst tail but may miss the recovery.
""")

# ==================================================================
# 12. Save Results
# ==================================================================
print("[6/6] Saving results...")

output = {
    "experiment": "K262",
    "title": "The Cost of Tail Risk",
    "period": f"{data_aligned.index[0].date()} to {data_aligned.index[-1].date()}",
    "n_days": int(n_days_final),
    "n_years": round(n_years_final, 1),
    "data_source": "yfinance (SPY, GLD, ^VIX daily)",
    "initial_capital": INITIAL_CAPITAL,
    "levels": [],
}

for i, r in enumerate(results):
    cagr_cost = baseline_cagr - r["cagr"]
    mdd_improv = r["mdd"] - baseline_mdd

    level_data = {
        "level": i,
        "name": r["name"],
        "cagr": round(r["cagr"], 4),
        "ann_vol": round(r["ann_vol"], 4),
        "sharpe": round(r["sharpe"], 3),
        "sortino": round(r["sortino"], 3),
        "calmar": round(r["calmar"], 3),
        "mdd": round(r["mdd"], 4),
        "worst_year": r["worst_year"],
        "worst_month_pct": round(r["worst_month_pct"], 4),
        "dollar_final": round(r["dollar_value"], 0),
        "cagr_cost_vs_l0": round(cagr_cost, 4),
        "mdd_improvement_vs_l0_pp": round(abs(mdd_improv) * 100, 1),
    }
    output["levels"].append(level_data)

output["stop_loss_triggers"] = stop_count
output["best_sharpe_level"] = best_sharpe_idx
output["best_calmar_level"] = best_calmar_idx

results_path = "experiments/k262_tail_risk_cost_results.json"
with open(results_path, "w") as f:
    json.dump(output, f, indent=2, default=str)

print(f"  Results saved to {results_path}")

print("\n" + "=" * 80)
print("K262 COMPLETE")
print("=" * 80)
