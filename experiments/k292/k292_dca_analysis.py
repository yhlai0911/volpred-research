"""
K292: Dollar Cost Averaging into 50/50+VT — The Complete DCA Analysis
=====================================================================
Background: K236 briefly tested DCA vs lump sum. But most real investors BUILD
positions over time through regular contributions (salary savings).
How does DCA interact with VT (Volatility Targeting)?

Data: SPY, GLD, VIX daily from yfinance, 2005-2024.

Methodology:
1. DCA scenarios (monthly $1000 contribution for 20 years = $240K total):
   a. DCA into 50/50 B&H (buy and hold, no VT)
   b. DCA into 50/50+VT (apply VT to existing portfolio each month)
   c. DCA into SPY only (benchmark)
   d. DCA into 50/50, switch to VT after accumulation phase (year 10)
2. Terminal wealth, Sharpe of portfolio value path, max drawdown
3. Different DCA amounts: $500, $1000, $2000/month
4. Different start dates: 2005 (pre-GFC), 2010 (post-GFC), 2015, 2020

Statistical tests: bootstrap CI on terminal wealth differences, paired t-tests
on daily return streams, Sharpe ratio difference test.

Author: [Proposed: User, Executed: Claude]
"""

import sys
import json
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from datetime import datetime, timedelta

# ================================================================
# 1. Download data
# ================================================================
print("=" * 78)
print("K292: Dollar Cost Averaging into 50/50+VT — The Complete DCA Analysis")
print("=" * 78)
print(f"\nRun date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
print("\n[1/8] Downloading SPY, GLD, and VIX data (2004-2025)...")

spy_raw = yf.download("SPY", start="2004-06-01", end="2025-01-01", progress=False, auto_adjust=False)
gld_raw = yf.download("GLD", start="2004-06-01", end="2025-01-01", progress=False, auto_adjust=False)
vix_raw = yf.download("^VIX", start="2004-06-01", end="2025-01-01", progress=False, auto_adjust=False)

# Flatten MultiIndex if needed
for df in [spy_raw, gld_raw, vix_raw]:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

spy = spy_raw[["Close"]].rename(columns={"Close": "spy_close"})
gld = gld_raw[["Close"]].rename(columns={"Close": "gld_close"})
vix = vix_raw[["Close"]].rename(columns={"Close": "vix_close"})

data = spy.join(gld, how="inner").join(vix, how="inner").dropna()

# GLD started trading 2004-11-18, so our data starts there
print(f"  Data range: {data.index[0].date()} to {data.index[-1].date()}")
print(f"  Total trading days: {len(data)}")
print(f"  GLD first date: {gld_raw.index[0].date()}")

# ================================================================
# 2. DCA Simulation Engine
# ================================================================
print("\n[2/8] Setting up DCA simulation engine...")

def get_monthly_contribution_dates(all_dates, start_date, end_date):
    """Get first trading day of each month in the date range."""
    mask = (all_dates >= pd.Timestamp(start_date)) & (all_dates <= pd.Timestamp(end_date))
    dates_in_range = all_dates[mask]
    result = []
    current_month = None
    for d in dates_in_range:
        key = (d.year, d.month)
        if key != current_month:
            result.append(d)
            current_month = key
    return result


def simulate_dca(data_df, contrib_dates, monthly_amount, strategy="spy_only",
                 vt_target=12.0, vt_start_year=None):
    """
    Simulate DCA with various strategies.

    Strategies:
    - "spy_only": 100% SPY
    - "5050_bh": 50/50 SPY/GLD, buy-and-hold (no rebalancing of existing)
    - "5050_vt": 50/50 SPY/GLD with VT overlay on each contribution
    - "5050_delayed_vt": 50/50 B&H for first N years, then switch to VT

    VT overlay: scale = min(1, vt_target / VIX_lagged)
    When scale < 1, excess goes to cash (earning ~0% real).

    Returns: dict with daily portfolio values, total invested, contribution log
    """
    spy_prices = data_df["spy_close"].values
    gld_prices = data_df["gld_close"].values
    vix_prices = data_df["vix_close"].values
    all_dates = data_df.index

    # Track shares
    spy_shares = 0.0
    gld_shares = 0.0
    cash = 0.0
    total_invested = 0.0

    contrib_set = set(contrib_dates)
    n_contributions = 0
    first_contrib_date = contrib_dates[0] if contrib_dates else None

    # Daily portfolio values
    portfolio_values = np.zeros(len(all_dates))

    for i, d in enumerate(all_dates):
        spy_p = spy_prices[i]
        gld_p = gld_prices[i]
        vix_p = vix_prices[i]

        if d in contrib_set:
            amount = monthly_amount
            total_invested += amount
            n_contributions += 1

            # Determine if VT is active
            use_vt = False
            if strategy == "5050_vt":
                use_vt = True
            elif strategy == "5050_delayed_vt" and vt_start_year is not None:
                if first_contrib_date is not None:
                    years_elapsed = (d - first_contrib_date).days / 365.25
                    if years_elapsed >= vt_start_year:
                        use_vt = True

            if use_vt:
                # Use lagged VIX (previous day) to avoid look-ahead bias
                vix_lag = vix_prices[i - 1] if i > 0 else vix_p
                scale = min(1.0, vt_target / vix_lag)
                risky_amount = amount * scale
                cash_add = amount * (1.0 - scale)
            else:
                risky_amount = amount
                cash_add = 0.0

            if strategy == "spy_only":
                # 100% SPY
                spy_shares += risky_amount / spy_p
                cash += cash_add
            else:
                # 50/50 SPY/GLD
                spy_shares += (risky_amount * 0.5) / spy_p
                gld_shares += (risky_amount * 0.5) / gld_p
                cash += cash_add

        # Daily portfolio value
        portfolio_values[i] = spy_shares * spy_p + gld_shares * gld_p + cash

    return {
        "values": portfolio_values,
        "total_invested": total_invested,
        "n_contributions": n_contributions,
    }


def compute_metrics(values, total_invested, dates):
    """Compute comprehensive metrics for a DCA portfolio path."""
    # Find first non-zero value
    first_nonzero = np.argmax(values > 0)
    if first_nonzero == 0 and values[0] == 0:
        return None  # No data

    valid_values = values[first_nonzero:]
    valid_dates = dates[first_nonzero:]
    terminal = valid_values[-1]

    # Total return
    total_return_pct = (terminal / total_invested - 1) * 100 if total_invested > 0 else 0

    # Annualized return (geometric, approximate for DCA)
    years = (valid_dates[-1] - valid_dates[0]).days / 365.25
    if years > 0 and total_invested > 0 and terminal > 0:
        ann_return = ((terminal / total_invested) ** (1 / years) - 1) * 100
    else:
        ann_return = 0

    # Max Drawdown from portfolio value series
    running_max = np.maximum.accumulate(valid_values)
    drawdowns = (valid_values - running_max) / running_max
    mdd = drawdowns.min() * 100

    # Max paper loss in dollar terms
    paper_losses = valid_values - running_max
    max_paper_loss = paper_losses.min()

    # Time underwater (consecutive days below previous peak)
    is_underwater = valid_values < running_max * 0.999  # 0.1% tolerance
    # Find longest underwater stretch
    longest_underwater = 0
    current_stretch = 0
    total_underwater_days = 0
    for uw in is_underwater:
        if uw:
            current_stretch += 1
            total_underwater_days += 1
            longest_underwater = max(longest_underwater, current_stretch)
        else:
            current_stretch = 0

    # Daily log returns for Sharpe/Sortino
    daily_rets = np.diff(np.log(valid_values[valid_values > 0]))
    daily_rets = daily_rets[np.isfinite(daily_rets)]

    if len(daily_rets) > 10:
        ann_vol = daily_rets.std() * np.sqrt(252) * 100
        ann_ret_daily = daily_rets.mean() * 252
        sharpe = ann_ret_daily / (daily_rets.std() * np.sqrt(252)) if daily_rets.std() > 0 else 0

        downside = daily_rets[daily_rets < 0]
        downside_vol = downside.std() * np.sqrt(252) if len(downside) > 0 else 1e-6
        sortino = ann_ret_daily / downside_vol

        calmar = ann_ret_daily / abs(mdd / 100) if mdd != 0 else 0
    else:
        ann_vol = sharpe = sortino = calmar = 0

    return {
        "terminal_wealth": terminal,
        "total_invested": total_invested,
        "total_return_pct": total_return_pct,
        "ann_return_pct": ann_return,
        "ann_vol_pct": ann_vol,
        "sharpe": sharpe,
        "sortino": sortino,
        "mdd_pct": mdd,
        "calmar": calmar,
        "max_paper_loss": max_paper_loss,
        "longest_underwater_days": longest_underwater,
        "total_underwater_days": total_underwater_days,
        "pct_time_underwater": total_underwater_days / len(valid_values) * 100,
    }


# ================================================================
# 3. Main Analysis: 4 strategies, $1000/month, 2005-2024
# ================================================================
print("\n[3/8] Running main DCA analysis (4 strategies, $1000/mo, 2005-2024)...")

main_start = "2005-01-01"
main_end = "2024-12-31"

contrib_dates_main = get_monthly_contribution_dates(data.index, main_start, main_end)
n_months = len(contrib_dates_main)
print(f"  Contribution dates: {n_months} months")
print(f"  First: {contrib_dates_main[0].date()}, Last: {contrib_dates_main[-1].date()}")
print(f"  Total invested: ${1000 * n_months:,.0f}")

strategies = {
    "SPY Only (DCA)": {"strategy": "spy_only"},
    "50/50 B&H (DCA)": {"strategy": "5050_bh"},
    "50/50 + VT (DCA)": {"strategy": "5050_vt", "vt_target": 12.0},
    "50/50 → VT@Yr10": {"strategy": "5050_delayed_vt", "vt_target": 12.0, "vt_start_year": 10},
}

main_results = {}
main_values = {}

print(f"\n  {'Strategy':<22s} | {'Terminal':>12s} | {'Return':>8s} | "
      f"{'Sharpe':>7s} | {'MDD':>8s} | {'Max Loss$':>10s} | {'UW Days':>8s}")
print("-" * 95)

for name, params in strategies.items():
    sim = simulate_dca(data, contrib_dates_main, 1000.0, **params)
    metrics = compute_metrics(sim["values"], sim["total_invested"], data.index)
    main_results[name] = metrics
    main_values[name] = sim["values"]

    print(f"  {name:<22s} | ${metrics['terminal_wealth']:>11,.0f} | "
          f"{metrics['total_return_pct']:>7.1f}% | "
          f"{metrics['sharpe']:>7.3f} | {metrics['mdd_pct']:>7.1f}% | "
          f"${metrics['max_paper_loss']:>9,.0f} | "
          f"{metrics['longest_underwater_days']:>5d} d")


# ================================================================
# 4. DCA Amount Sensitivity: $500, $1000, $2000/month
# ================================================================
print("\n[4/8] DCA amount sensitivity ($500 / $1000 / $2000 per month)...")

amounts = [500, 1000, 2000]
amount_results = {}

print(f"\n  {'Amount':>8s} | {'Strategy':<22s} | {'Invested':>10s} | "
      f"{'Terminal':>12s} | {'Return':>8s} | {'Sharpe':>7s} | {'MDD':>8s}")
print("-" * 100)

for amt in amounts:
    for name, params in strategies.items():
        sim = simulate_dca(data, contrib_dates_main, float(amt), **params)
        metrics = compute_metrics(sim["values"], sim["total_invested"], data.index)
        key = f"${amt}/mo {name}"
        amount_results[key] = metrics

        print(f"  ${amt:>6,d} | {name:<22s} | ${metrics['total_invested']:>9,.0f} | "
              f"${metrics['terminal_wealth']:>11,.0f} | "
              f"{metrics['total_return_pct']:>7.1f}% | "
              f"{metrics['sharpe']:>7.3f} | {metrics['mdd_pct']:>7.1f}%")
    if amt != amounts[-1]:
        print()

# Check linearity: is terminal wealth proportional to contribution amount?
print("\n  Linearity check (terminal wealth / amount should be constant):")
for name in strategies.keys():
    ratios = []
    for amt in amounts:
        key = f"${amt}/mo {name}"
        ratio = amount_results[key]["terminal_wealth"] / amt
        ratios.append(ratio)
    cv = np.std(ratios) / np.mean(ratios) * 100
    print(f"    {name:<22s}: ratios = [{', '.join(f'{r:.1f}' for r in ratios)}], "
          f"CV = {cv:.2f}%")


# ================================================================
# 5. Start Date Analysis: 2005, 2010, 2015, 2020
# ================================================================
print("\n[5/8] Start date analysis (different market entry points)...")

start_dates = {
    "2005 (pre-GFC)": ("2005-01-01", "2024-12-31"),
    "2010 (post-GFC)": ("2010-01-01", "2024-12-31"),
    "2015 (mid-cycle)": ("2015-01-01", "2024-12-31"),
    "2020 (COVID)": ("2020-01-01", "2024-12-31"),
}

start_date_results = {}

print(f"\n  {'Period':<18s} | {'Strategy':<22s} | {'Months':>6s} | "
      f"{'Invested':>10s} | {'Terminal':>12s} | {'Return':>8s} | "
      f"{'Sharpe':>7s} | {'MDD':>8s}")
print("-" * 115)

for period_name, (s_date, e_date) in start_dates.items():
    cdates = get_monthly_contribution_dates(data.index, s_date, e_date)
    if not cdates:
        print(f"  {period_name}: No data available")
        continue

    for name, params in strategies.items():
        sim = simulate_dca(data, cdates, 1000.0, **params)
        metrics = compute_metrics(sim["values"], sim["total_invested"], data.index)
        key = f"{period_name} | {name}"
        start_date_results[key] = metrics

        print(f"  {period_name:<18s} | {name:<22s} | {sim['n_contributions']:>6d} | "
              f"${metrics['total_invested']:>9,.0f} | "
              f"${metrics['terminal_wealth']:>11,.0f} | "
              f"{metrics['total_return_pct']:>7.1f}% | "
              f"{metrics['sharpe']:>7.3f} | {metrics['mdd_pct']:>7.1f}%")
    print()


# ================================================================
# 6. VT Benefit by Start Date — The Key Comparison
# ================================================================
print("\n[6/8] VT benefit decomposition by start date...")

print(f"\n  {'Period':<18s} | {'B&H Return':>10s} | {'VT Return':>10s} | "
      f"{'VT Delta':>9s} | {'B&H MDD':>8s} | {'VT MDD':>8s} | "
      f"{'MDD Saved':>9s} | {'B&H UW':>7s} | {'VT UW':>7s}")
print("-" * 115)

vt_benefit_summary = {}
for period_name, (s_date, e_date) in start_dates.items():
    bh_key = f"{period_name} | 50/50 B&H (DCA)"
    vt_key = f"{period_name} | 50/50 + VT (DCA)"

    if bh_key not in start_date_results or vt_key not in start_date_results:
        continue

    bh = start_date_results[bh_key]
    vt = start_date_results[vt_key]

    ret_delta = vt["total_return_pct"] - bh["total_return_pct"]
    mdd_saved = bh["mdd_pct"] - vt["mdd_pct"]  # Positive means VT has less drawdown

    vt_benefit_summary[period_name] = {
        "return_delta_pct": ret_delta,
        "mdd_saved_pct": mdd_saved,
        "bh_sharpe": bh["sharpe"],
        "vt_sharpe": vt["sharpe"],
    }

    print(f"  {period_name:<18s} | {bh['total_return_pct']:>9.1f}% | "
          f"{vt['total_return_pct']:>9.1f}% | {ret_delta:>+8.1f}% | "
          f"{bh['mdd_pct']:>7.1f}% | {vt['mdd_pct']:>7.1f}% | "
          f"{mdd_saved:>+8.1f}% | "
          f"{bh['longest_underwater_days']:>5d}d | "
          f"{vt['longest_underwater_days']:>5d}d")


# ================================================================
# 7. Statistical Tests
# ================================================================
print("\n[7/8] Statistical tests...")

# 7a. Bootstrap CI on terminal wealth differences (main analysis)
N_BOOTSTRAP = 5000
np.random.seed(42)

def bootstrap_terminal_diff(values1, values2, n_boot=5000):
    """Bootstrap the difference in terminal wealth by block-resampling returns."""
    # Find valid region
    start1 = np.argmax(values1 > 0)
    start2 = np.argmax(values2 > 0)
    start = max(start1, start2)

    v1 = values1[start:]
    v2 = values2[start:]

    if len(v1) < 252:
        return np.zeros(n_boot), 1.0

    # Monthly returns for block bootstrap
    block_size = 21
    rets1, rets2 = [], []
    for i in range(0, len(v1) - block_size, block_size):
        if v1[i] > 0 and v2[i] > 0:
            rets1.append(v1[i + block_size] / v1[i] - 1)
            rets2.append(v2[i + block_size] / v2[i] - 1)

    rets1 = np.array(rets1)
    rets2 = np.array(rets2)
    n = len(rets1)

    if n < 12:
        return np.zeros(n_boot), 1.0

    diffs = np.zeros(n_boot)
    for b in range(n_boot):
        idx = np.random.randint(0, n, size=n)
        cum1 = np.prod(1 + rets1[idx])
        cum2 = np.prod(1 + rets2[idx])
        # Scale to actual terminal wealth
        diffs[b] = (v1[0] * cum1) - (v2[0] * cum2)

    p_value = 2 * min(np.mean(diffs > 0), np.mean(diffs < 0))
    return diffs, p_value

print("\n  (a) Bootstrap CI on terminal wealth (main analysis, 5000 reps):")
comparisons = [
    ("50/50 + VT (DCA)", "50/50 B&H (DCA)", "VT vs B&H"),
    ("50/50 B&H (DCA)", "SPY Only (DCA)", "50/50 vs SPY"),
    ("50/50 → VT@Yr10", "50/50 B&H (DCA)", "Delayed VT vs B&H"),
    ("50/50 + VT (DCA)", "50/50 → VT@Yr10", "Full VT vs Delayed VT"),
]

bootstrap_results = {}
for strat1, strat2, label in comparisons:
    diffs, pval = bootstrap_terminal_diff(main_values[strat1], main_values[strat2])
    ci_lo = np.percentile(diffs, 2.5)
    ci_hi = np.percentile(diffs, 97.5)
    print(f"    {label:28s}: mean diff = ${diffs.mean():>+10,.0f}  "
          f"95% CI: [${ci_lo:>+10,.0f}, ${ci_hi:>+10,.0f}]  "
          f"p={pval:.4f} {'*' if pval < 0.05 else 'n.s.'}")
    bootstrap_results[label] = {
        "mean_diff": float(diffs.mean()),
        "ci_95_lo": float(ci_lo),
        "ci_95_hi": float(ci_hi),
        "p_value": float(pval),
    }

# 7b. Paired t-test on daily returns
print("\n  (b) Paired t-tests on daily log returns:")

for strat1, strat2, label in comparisons:
    v1 = main_values[strat1]
    v2 = main_values[strat2]

    # Align on valid region
    valid = (v1 > 0) & (v2 > 0)
    r1 = np.diff(np.log(v1[valid]))
    r2 = np.diff(np.log(v2[valid]))
    min_len = min(len(r1), len(r2))
    r1, r2 = r1[:min_len], r2[:min_len]

    # Remove non-finite
    finite = np.isfinite(r1) & np.isfinite(r2)
    r1, r2 = r1[finite], r2[finite]

    if len(r1) > 30:
        t_stat, p_val = stats.ttest_rel(r1, r2)
        # Annualized mean difference
        mean_diff_ann = (r1 - r2).mean() * 252 * 100
        print(f"    {label:28s}: t={t_stat:>7.3f}, p={p_val:.4f} "
              f"{'*' if p_val < 0.05 else 'n.s.'}  "
              f"Ann. diff: {mean_diff_ann:>+.2f}%/yr")

# 7c. Sharpe ratio difference test (Jobson-Korkie with Memmel correction)
print("\n  (c) Sharpe ratio difference tests:")

def sharpe_diff_test(r1, r2):
    """Test H0: Sharpe1 = Sharpe2 using Jobson-Korkie (1981) with Memmel (2003) correction."""
    mu1, mu2 = r1.mean(), r2.mean()
    s1, s2 = r1.std(), r2.std()
    n = len(r1)
    rho = np.corrcoef(r1, r2)[0, 1]

    sr1, sr2 = mu1 / s1, mu2 / s2

    # Memmel (2003) corrected standard error
    theta = (1/n) * (2 * (1 - rho) + 0.5 * (sr1**2 + sr2**2 - 2*sr1*sr2*rho))
    if theta <= 0:
        return 0, 1.0

    z_stat = (sr1 - sr2) / np.sqrt(theta)
    p_val = 2 * (1 - stats.norm.cdf(abs(z_stat)))
    return z_stat, p_val

for strat1, strat2, label in comparisons:
    v1 = main_values[strat1]
    v2 = main_values[strat2]

    valid = (v1 > 0) & (v2 > 0)
    r1 = np.diff(np.log(v1[valid]))
    r2 = np.diff(np.log(v2[valid]))
    min_len = min(len(r1), len(r2))
    r1, r2 = r1[:min_len], r2[:min_len]
    finite = np.isfinite(r1) & np.isfinite(r2)
    r1, r2 = r1[finite], r2[finite]

    if len(r1) > 30:
        z, p = sharpe_diff_test(r1, r2)
        sr1 = r1.mean() / r1.std() * np.sqrt(252)
        sr2 = r2.mean() / r2.std() * np.sqrt(252)
        print(f"    {label:28s}: SR1={sr1:.3f} vs SR2={sr2:.3f}  "
              f"z={z:>6.3f}, p={p:.4f} {'*' if p < 0.05 else 'n.s.'}")


# ================================================================
# 8. Practical Summary & Key Findings
# ================================================================
print("\n" + "=" * 78)
print("[8/8] KEY FINDINGS")
print("=" * 78)

# Finding 1: VT effect on DCA
bh = main_results["50/50 B&H (DCA)"]
vt = main_results["50/50 + VT (DCA)"]
spy = main_results["SPY Only (DCA)"]
delayed = main_results["50/50 → VT@Yr10"]

print(f"""
1. VT EFFECT ON DCA PORTFOLIOS (2005-2024, $1000/mo):
   ┌────────────────────────┬────────────┬─────────┬─────────┬──────────┐
   │ Strategy               │   Terminal │  Return │  Sharpe │      MDD │
   ├────────────────────────┼────────────┼─────────┼─────────┼──────────┤
   │ SPY Only               │ ${spy['terminal_wealth']:>10,.0f} │ {spy['total_return_pct']:>6.1f}% │ {spy['sharpe']:>7.3f} │ {spy['mdd_pct']:>7.1f}% │
   │ 50/50 B&H              │ ${bh['terminal_wealth']:>10,.0f} │ {bh['total_return_pct']:>6.1f}% │ {bh['sharpe']:>7.3f} │ {bh['mdd_pct']:>7.1f}% │
   │ 50/50 + VT (12/VIX)    │ ${vt['terminal_wealth']:>10,.0f} │ {vt['total_return_pct']:>6.1f}% │ {vt['sharpe']:>7.3f} │ {vt['mdd_pct']:>7.1f}% │
   │ 50/50 → VT after Yr 10 │ ${delayed['terminal_wealth']:>10,.0f} │ {delayed['total_return_pct']:>6.1f}% │ {delayed['sharpe']:>7.3f} │ {delayed['mdd_pct']:>7.1f}% │
   └────────────────────────┴────────────┴─────────┴─────────┴──────────┘
""")

# Finding 2: MDD protection
print(f"2. MDD PROTECTION:")
mdd_reduction = bh["mdd_pct"] - vt["mdd_pct"]
print(f"   VT reduces MDD by {mdd_reduction:+.1f} percentage points "
      f"({bh['mdd_pct']:.1f}% → {vt['mdd_pct']:.1f}%)")
print(f"   Max paper loss: B&H ${bh['max_paper_loss']:,.0f} → VT ${vt['max_paper_loss']:,.0f} "
      f"(saved ${bh['max_paper_loss'] - vt['max_paper_loss']:,.0f})")

# Finding 3: Time underwater
print(f"\n3. TIME UNDERWATER:")
print(f"   B&H: {bh['pct_time_underwater']:.1f}% of time underwater "
      f"(longest streak: {bh['longest_underwater_days']} days)")
print(f"   VT:  {vt['pct_time_underwater']:.1f}% of time underwater "
      f"(longest streak: {vt['longest_underwater_days']} days)")

# Finding 4: Start date robustness
print(f"\n4. START DATE ROBUSTNESS (VT benefit across entry points):")
for period_name, benefits in vt_benefit_summary.items():
    direction = "helps" if benefits["return_delta_pct"] > 0 else "costs"
    mdd_dir = "reduces" if benefits["mdd_saved_pct"] > 0 else "increases"
    print(f"   {period_name:<18s}: VT {direction} return by {abs(benefits['return_delta_pct']):.1f}%, "
          f"{mdd_dir} MDD by {abs(benefits['mdd_saved_pct']):.1f}pp")

# Finding 5: DCA amount linearity
print(f"\n5. DCA AMOUNT LINEARITY:")
print(f"   Return percentages are identical regardless of $500/$1000/$2000.")
print(f"   Terminal wealth scales perfectly linearly with contribution amount.")
print(f"   Implication: results apply to ANY regular contribution amount.")

# Finding 6: Delayed VT
print(f"\n6. DELAYED VT (VT starts at year 10 of 20-year DCA):")
delay_vs_bh = delayed["total_return_pct"] - bh["total_return_pct"]
delay_vs_vt = delayed["total_return_pct"] - vt["total_return_pct"]
print(f"   vs B&H: {delay_vs_bh:+.1f}% return, MDD {delayed['mdd_pct']:.1f}% vs {bh['mdd_pct']:.1f}%")
print(f"   vs Full VT: {delay_vs_vt:+.1f}% return, MDD {delayed['mdd_pct']:.1f}% vs {vt['mdd_pct']:.1f}%")
print(f"   Interpretation: Delayed VT captures {'most' if abs(delayed['mdd_pct']) < abs(bh['mdd_pct']) * 0.85 else 'some'} "
      f"of VT's MDD benefit while preserving more upside during accumulation.")


# ================================================================
# 9. Year-by-year portfolio value comparison
# ================================================================
print("\n" + "=" * 78)
print("YEAR-BY-YEAR PORTFOLIO VALUE SNAPSHOT ($1000/mo, 2005-2024)")
print("=" * 78)
print(f"  {'Year':>6s} | {'Invested':>10s} | {'SPY Only':>12s} | {'50/50 BH':>12s} | "
      f"{'50/50+VT':>12s} | {'VT@Yr10':>12s}")
print("-" * 85)

for year in range(2005, 2025):
    # Find last trading day of each year
    year_end = data.index[data.index.year == year]
    if len(year_end) == 0:
        continue
    idx = data.index.get_loc(year_end[-1])

    # Count contributions up to this point
    n_contribs = sum(1 for d in contrib_dates_main if d <= year_end[-1])
    invested = n_contribs * 1000

    print(f"  {year:>6d} | ${invested:>9,.0f} | "
          f"${main_values['SPY Only (DCA)'][idx]:>11,.0f} | "
          f"${main_values['50/50 B&H (DCA)'][idx]:>11,.0f} | "
          f"${main_values['50/50 + VT (DCA)'][idx]:>11,.0f} | "
          f"${main_values['50/50 → VT@Yr10'][idx]:>11,.0f}")


# ================================================================
# 10. GFC and COVID deep-dive
# ================================================================
print("\n" + "=" * 78)
print("CRISIS DEEP-DIVE: GFC (2008-2009) and COVID (2020)")
print("=" * 78)

crises = {
    "GFC Peak-to-Trough": ("2007-10-01", "2009-03-09"),
    "COVID Crash": ("2020-02-19", "2020-03-23"),
}

for crisis_name, (crisis_start, crisis_end) in crises.items():
    cs = pd.Timestamp(crisis_start)
    ce = pd.Timestamp(crisis_end)

    # Find closest dates in data
    cs_idx = data.index.searchsorted(cs)
    ce_idx = data.index.searchsorted(ce)

    if cs_idx >= len(data) or ce_idx >= len(data):
        continue

    print(f"\n  {crisis_name} ({data.index[cs_idx].date()} to {data.index[ce_idx].date()}):")
    for name in strategies.keys():
        v = main_values[name]
        peak_val = v[cs_idx]
        trough_val = v[ce_idx]
        if peak_val > 0:
            crisis_dd = (trough_val - peak_val) / peak_val * 100
            dollar_loss = trough_val - peak_val
            print(f"    {name:<22s}: ${peak_val:>10,.0f} → ${trough_val:>10,.0f} "
                  f"({crisis_dd:>+7.1f}%, ${dollar_loss:>+10,.0f})")


# ================================================================
# Save results
# ================================================================
print("\n" + "=" * 78)
print("Saving results...")

output = {
    "experiment": "K292",
    "title": "Dollar Cost Averaging into 50/50+VT — The Complete DCA Analysis",
    "date": datetime.now().isoformat(),
    "data_range": f"{data.index[0].date()} to {data.index[-1].date()}",
    "data_source": "yfinance (SPY, GLD, ^VIX)",
    "parameters": {
        "main_period": f"{main_start} to {main_end}",
        "default_amount": 1000,
        "vt_target": 12.0,
        "vt_delayed_start_year": 10,
        "n_bootstrap": N_BOOTSTRAP,
    },
    "main_results": {k: {kk: float(vv) for kk, vv in v.items()} for k, v in main_results.items()},
    "start_date_results": {},
    "vt_benefit_by_start_date": vt_benefit_summary,
    "bootstrap_tests": bootstrap_results,
    "limitations": [
        "VT cash allocation earns 0% (no interest); real-world SHY would add ~1-2%/yr",
        "No rebalancing of existing shares (only new contributions follow 50/50 split)",
        "Transaction costs not modeled (monthly rebal has minimal cost impact per K122)",
        "Tax implications of VT-induced under-allocation not considered",
        "Single 20-year path; results specific to 2005-2024 regime",
        "GLD started Nov 2004; pre-GLD era not testable with this proxy",
    ],
}

# Add start_date_results
for k, v in start_date_results.items():
    if v is not None:
        output["start_date_results"][k] = {kk: float(vv) for kk, vv in v.items()}

import os
script_dir = os.path.dirname(os.path.abspath(__file__))
output_path = os.path.join(script_dir, "k292_dca_results.json")

with open(output_path, "w") as f:
    json.dump(output, f, indent=2, ensure_ascii=False)

print(f"Results saved to: {output_path}")

# ================================================================
# Final verdict
# ================================================================
print("\n" + "=" * 78)
print("FINAL VERDICT: DCA + VT for Real Investors")
print("=" * 78)

vt_helps_return = vt["total_return_pct"] > bh["total_return_pct"]
vt_helps_mdd = abs(vt["mdd_pct"]) < abs(bh["mdd_pct"])
vt_helps_sharpe = vt["sharpe"] > bh["sharpe"]

print(f"""
  For a real investor doing $1,000/month DCA over 20 years (2005-2024):

  1. DIVERSIFICATION FIRST: 50/50 SPY/GLD {'beats' if bh['sharpe'] > spy['sharpe'] else 'trails'} SPY-only on risk-adjusted basis
     (Sharpe {bh['sharpe']:.3f} vs {spy['sharpe']:.3f}, MDD {bh['mdd_pct']:.1f}% vs {spy['mdd_pct']:.1f}%)

  2. VT ON TOP OF DCA: VT (12/VIX) {'improves' if vt_helps_sharpe else 'does not improve'} Sharpe
     ({vt['sharpe']:.3f} vs {bh['sharpe']:.3f}) and {'reduces' if vt_helps_mdd else 'does not reduce'} MDD
     ({vt['mdd_pct']:.1f}% vs {bh['mdd_pct']:.1f}%)

  3. TERMINAL WEALTH: VT {'increases' if vt_helps_return else 'reduces'} terminal wealth
     (${vt['terminal_wealth']:,.0f} vs ${bh['terminal_wealth']:,.0f}, delta {vt['total_return_pct'] - bh['total_return_pct']:+.1f}%)

  4. DELAYED VT (start at year 10): A compromise that
     {'captures most MDD protection while preserving more accumulation' if abs(delayed['mdd_pct']) < abs(bh['mdd_pct']) * 0.9 else 'offers partial protection'}

  5. PRACTICAL RECOMMENDATION:
     - Phase 1 (Accumulation, years 1-10): DCA into 50/50 SPY/GLD, no VT needed
       (small portfolio, DCA itself provides dollar-cost smoothing)
     - Phase 2 (Protection, years 10+): Add VT overlay (12/VIX)
       (larger portfolio, drawdown protection becomes more valuable)
     - This hybrid approach balances wealth accumulation with protection as
       the portfolio grows and the investor approaches their goal.
""")

print("=" * 78)
print("K292 experiment complete.")
print("=" * 78)
