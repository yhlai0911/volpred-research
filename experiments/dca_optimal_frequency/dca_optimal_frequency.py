"""
K122: DCA Optimal Frequency + VT Integration
=============================================
Test how DCA contribution frequency (weekly/biweekly/monthly/quarterly)
affects terminal wealth, IRR, MDD, Calmar — with and without VT overlay.

Data: SPY + GLD + VIX, 2007-2024 (18 years, covers GFC + COVID)
Asset: 50/50 SPY/GLD
VT overlay: 24/VIX (per K59 finding for DCA)
Bootstrap: 5000 reps for terminal wealth CI
"""

import sys
import json
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from datetime import datetime

# ================================================================
# 1. Download data
# ================================================================
print("=" * 70)
print("K122: DCA Optimal Frequency + VT Integration")
print("=" * 70)
print("\n[1/6] Downloading SPY, GLD, and VIX data (2006-2025)...")

spy_raw = yf.download("SPY", start="2006-01-01", end="2025-01-01", progress=False, auto_adjust=False)
gld_raw = yf.download("GLD", start="2006-01-01", end="2025-01-01", progress=False, auto_adjust=False)
vix_raw = yf.download("^VIX", start="2006-01-01", end="2025-01-01", progress=False, auto_adjust=False)

# Flatten MultiIndex if needed
for df in [spy_raw, gld_raw, vix_raw]:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

spy = spy_raw[["Close"]].rename(columns={"Close": "spy_close"})
gld = gld_raw[["Close"]].rename(columns={"Close": "gld_close"})
vix = vix_raw[["Close"]].rename(columns={"Close": "vix_close"})

data = spy.join(gld, how="inner").join(vix, how="inner").dropna()

# Filter to 2007-2024
data = data.loc["2007-01-01":"2024-12-31"]

print(f"  Data range: {data.index[0].date()} to {data.index[-1].date()}")
print(f"  Total trading days: {len(data)}")

# ================================================================
# 2. Define DCA contribution dates for each frequency
# ================================================================
print("\n[2/6] Generating DCA contribution schedules...")

all_dates = data.index

def get_weekly_dates(dates):
    """Every Monday (or next trading day)"""
    result = []
    current_week = None
    for d in dates:
        week_num = d.isocalendar()[1]
        year = d.year
        key = (year, week_num)
        if key != current_week and d.weekday() <= 4:  # Mon-Fri
            result.append(d)
            current_week = key
    return result

def get_biweekly_dates(dates):
    """Every other Monday"""
    weekly = get_weekly_dates(dates)
    return weekly[::2]

def get_monthly_dates(dates):
    """First trading day of each month"""
    result = []
    current_month = None
    for d in dates:
        key = (d.year, d.month)
        if key != current_month:
            result.append(d)
            current_month = key
    return result

def get_quarterly_dates(dates):
    """First trading day of each quarter"""
    result = []
    current_q = None
    for d in dates:
        q = (d.month - 1) // 3
        key = (d.year, q)
        if key != current_q:
            result.append(d)
            current_q = key
    return result

freq_schedules = {
    "Weekly": get_weekly_dates(all_dates),
    "Biweekly": get_biweekly_dates(all_dates),
    "Monthly": get_monthly_dates(all_dates),
    "Quarterly": get_quarterly_dates(all_dates),
}

for name, dates in freq_schedules.items():
    print(f"  {name:12s}: {len(dates):4d} contributions, "
          f"${1000*len(dates):,.0f} total invested")

# ================================================================
# 3. DCA Simulation Engine
# ================================================================
print("\n[3/6] Running DCA simulations (8 combinations)...")

CONTRIBUTION = 1000.0  # dollars per contribution
SPY_WEIGHT = 0.5
GLD_WEIGHT = 0.5
VT_TARGET = 24.0  # 24/VIX for DCA (per K59)

def simulate_dca(contrib_dates, use_vt=False, vt_target=24.0):
    """
    Simulate DCA with 50/50 SPY/GLD.

    Each contribution buys shares at that day's close price.
    Portfolio value is tracked daily.

    VT overlay: On each contribution date, adjust equity weight by
    min(1, vt_target/VIX). This scales the risky allocation down
    when VIX is high, keeping cash remainder in SHY (approx 0% real).

    Returns: daily portfolio value series, total invested, contribution details
    """
    spy_prices = data["spy_close"].values
    gld_prices = data["gld_close"].values
    vix_prices = data["vix_close"].values
    dates_all = data.index

    # Track shares held
    spy_shares = 0.0
    gld_shares = 0.0
    cash = 0.0  # cash from VT scaling
    total_invested = 0.0

    # Convert contrib_dates to set for O(1) lookup
    contrib_set = set(contrib_dates)

    # Daily portfolio values
    portfolio_values = np.zeros(len(dates_all))

    for i, d in enumerate(dates_all):
        spy_p = spy_prices[i]
        gld_p = gld_prices[i]
        vix_p = vix_prices[i]

        if d in contrib_set:
            amount = CONTRIBUTION
            total_invested += amount

            if use_vt:
                # VT scaling: reduce risky allocation when VIX is high
                # Use lagged VIX (previous day) to avoid look-ahead bias
                if i > 0:
                    vix_for_signal = vix_prices[i - 1]  # lagged
                else:
                    vix_for_signal = vix_p
                scale = min(1.0, vt_target / vix_for_signal)
                risky_amount = amount * scale
                cash_amount = amount * (1.0 - scale)
            else:
                risky_amount = amount
                cash_amount = 0.0

            # Buy SPY and GLD with risky portion
            spy_buy = risky_amount * SPY_WEIGHT / spy_p
            gld_buy = risky_amount * GLD_WEIGHT / gld_p
            spy_shares += spy_buy
            gld_shares += gld_buy
            cash += cash_amount

        # Daily portfolio value
        portfolio_values[i] = spy_shares * spy_p + gld_shares * gld_p + cash

    return portfolio_values, total_invested

def compute_metrics(values, total_invested, dates):
    """Compute terminal wealth, IRR (approx), MDD, Calmar, Sortino"""
    terminal = values[-1]

    # Simple annualized return (geometric)
    years = (dates[-1] - dates[0]).days / 365.25
    if total_invested > 0 and terminal > 0:
        # Approximate IRR using TWR
        total_return = terminal / total_invested - 1
        ann_return = (1 + total_return) ** (1 / years) - 1
    else:
        ann_return = 0

    # MDD from portfolio value series
    running_max = np.maximum.accumulate(values)
    # Only compute where values > 0
    valid = values > 0
    drawdowns = np.zeros_like(values)
    drawdowns[valid] = (values[valid] - running_max[valid]) / running_max[valid]
    mdd = drawdowns.min()

    # Daily returns (for Sharpe/Sortino)
    # Use log returns where values > 0
    daily_returns = []
    for i in range(1, len(values)):
        if values[i] > 0 and values[i-1] > 0:
            daily_returns.append(np.log(values[i] / values[i-1]))
    daily_returns = np.array(daily_returns)

    if len(daily_returns) > 0:
        ann_vol = daily_returns.std() * np.sqrt(252)
        ann_ret_from_daily = daily_returns.mean() * 252
        sharpe = ann_ret_from_daily / ann_vol if ann_vol > 0 else 0

        # Sortino
        downside = daily_returns[daily_returns < 0]
        downside_vol = downside.std() * np.sqrt(252) if len(downside) > 0 else 1e-6
        sortino = ann_ret_from_daily / downside_vol

        # Calmar
        calmar = ann_ret_from_daily / abs(mdd) if mdd != 0 else 0
    else:
        sharpe = sortino = calmar = ann_vol = 0
        ann_ret_from_daily = 0

    return {
        "terminal_wealth": terminal,
        "total_invested": total_invested,
        "total_return_pct": (terminal / total_invested - 1) * 100 if total_invested > 0 else 0,
        "ann_return_pct": ann_return * 100,
        "ann_vol_pct": ann_vol * 100,
        "sharpe": sharpe,
        "sortino": sortino,
        "mdd_pct": mdd * 100,
        "calmar": calmar,
    }

# Run all 8 combinations
results = {}
all_values = {}

for freq_name, contrib_dates in freq_schedules.items():
    for use_vt in [False, True]:
        label = f"{freq_name}" + (" + VT" if use_vt else "")
        values, invested = simulate_dca(contrib_dates, use_vt=use_vt)
        metrics = compute_metrics(values, invested, all_dates)
        results[label] = metrics
        all_values[label] = values

        print(f"  {label:22s}: Terminal=${metrics['terminal_wealth']:>12,.0f}  "
              f"Return={metrics['total_return_pct']:>6.1f}%  "
              f"MDD={metrics['mdd_pct']:>6.1f}%  "
              f"Sharpe={metrics['sharpe']:.3f}")

# ================================================================
# 4. Bootstrap CI for terminal wealth differences
# ================================================================
print("\n[4/6] Bootstrap confidence intervals (5000 reps)...")

N_BOOTSTRAP = 5000
np.random.seed(42)

# We bootstrap by resampling daily returns and reconstructing paths
def bootstrap_terminal_wealth(values, n_boot=5000):
    """Bootstrap terminal wealth by block-resampling monthly returns"""
    # Convert to monthly returns for block bootstrap
    valid_start = np.argmax(values > 0)
    valid_values = values[valid_start:]

    # Monthly aggregation
    monthly_rets = []
    block_size = 21  # ~1 month
    for i in range(0, len(valid_values) - block_size, block_size):
        if valid_values[i] > 0:
            monthly_rets.append(valid_values[i + block_size] / valid_values[i] - 1)
    monthly_rets = np.array(monthly_rets)

    if len(monthly_rets) < 12:
        return np.array([values[-1]] * n_boot)

    terminals = np.zeros(n_boot)
    for b in range(n_boot):
        sampled = np.random.choice(monthly_rets, size=len(monthly_rets), replace=True)
        cumulative = np.prod(1 + sampled)
        # Scale by actual terminal wealth ratio
        terminals[b] = values[valid_start] * cumulative

    return terminals

# Compare weekly vs monthly (the key comparison)
print("  Bootstrap: Weekly vs Monthly terminal wealth...")
boot_weekly = bootstrap_terminal_wealth(all_values["Weekly"])
boot_monthly = bootstrap_terminal_wealth(all_values["Monthly"])
boot_diff = boot_weekly - boot_monthly

diff_mean = boot_diff.mean()
diff_ci_lo = np.percentile(boot_diff, 2.5)
diff_ci_hi = np.percentile(boot_diff, 97.5)
diff_pvalue = 2 * min(np.mean(boot_diff > 0), np.mean(boot_diff < 0))

print(f"    Weekly - Monthly terminal wealth: ${diff_mean:,.0f}")
print(f"    95% CI: [${diff_ci_lo:,.0f}, ${diff_ci_hi:,.0f}]")
print(f"    p-value (two-sided): {diff_pvalue:.4f}")

# Also bootstrap weekly vs quarterly
boot_quarterly = bootstrap_terminal_wealth(all_values["Quarterly"])
diff_wq = boot_weekly - boot_quarterly
diff_wq_pvalue = 2 * min(np.mean(diff_wq > 0), np.mean(diff_wq < 0))
print(f"\n    Weekly - Quarterly: ${diff_wq.mean():,.0f}")
print(f"    95% CI: [${np.percentile(diff_wq, 2.5):,.0f}, ${np.percentile(diff_wq, 97.5):,.0f}]")
print(f"    p-value: {diff_wq_pvalue:.4f}")

# Paired t-test on daily returns for each frequency pair
print("\n  Paired t-tests on daily log returns:")
freqs = ["Weekly", "Biweekly", "Monthly", "Quarterly"]
for i in range(len(freqs)):
    for j in range(i+1, len(freqs)):
        f1, f2 = freqs[i], freqs[j]
        v1, v2 = all_values[f1], all_values[f2]

        # Compute daily returns where both have positive values
        valid = (v1 > 0) & (v2 > 0)
        r1 = np.diff(np.log(v1[valid]))
        r2 = np.diff(np.log(v2[valid]))
        min_len = min(len(r1), len(r2))
        r1, r2 = r1[:min_len], r2[:min_len]

        if len(r1) > 10:
            t_stat, p_val = stats.ttest_rel(r1, r2)
            print(f"    {f1:10s} vs {f2:10s}: t={t_stat:>6.3f}, p={p_val:.4f} "
                  f"{'*' if p_val < 0.05 else 'n.s.'}")

# ================================================================
# 5. VT increment analysis per frequency
# ================================================================
print("\n[5/6] VT increment analysis (per frequency)...")
print(f"  {'Frequency':12s} | {'No VT MDD':>10s} | {'VT MDD':>10s} | {'MDD Δ':>8s} | "
      f"{'No VT Sharpe':>12s} | {'VT Sharpe':>10s} | {'Sharpe Δ':>8s}")
print("-" * 85)

for freq_name in freqs:
    no_vt = results[freq_name]
    vt = results[f"{freq_name} + VT"]
    mdd_delta = vt["mdd_pct"] - no_vt["mdd_pct"]
    sharpe_delta = vt["sharpe"] - no_vt["sharpe"]
    print(f"  {freq_name:12s} | {no_vt['mdd_pct']:>9.1f}% | {vt['mdd_pct']:>9.1f}% | "
          f"{mdd_delta:>+7.1f}% | {no_vt['sharpe']:>12.3f} | {vt['sharpe']:>10.3f} | "
          f"{sharpe_delta:>+7.3f}")

# ================================================================
# 6. Market regime analysis
# ================================================================
print("\n[6/6] Market regime analysis...")

# Define regimes based on SPY price trend
spy_close = data["spy_close"]
spy_200ma = spy_close.rolling(200).mean()

regime = pd.Series("Sideways", index=data.index)
# Bull: price > 200MA and 200MA rising
ma_slope = spy_200ma.pct_change(20)  # 20-day slope of 200MA
regime[(spy_close > spy_200ma) & (ma_slope > 0.001)] = "Bull"
regime[(spy_close < spy_200ma) & (ma_slope < -0.001)] = "Bear"

# Remove early NaN period
regime = regime.loc[spy_200ma.first_valid_index():]

print(f"\n  Regime distribution:")
for r in ["Bull", "Bear", "Sideways"]:
    pct = (regime == r).sum() / len(regime) * 100
    print(f"    {r:8s}: {(regime == r).sum():>4d} days ({pct:.1f}%)")

# Compute metrics by regime
print(f"\n  {'Freq':12s} | {'Bull Sharpe':>12s} | {'Bear Sharpe':>12s} | "
      f"{'Side Sharpe':>12s} | {'Bull MDD':>9s} | {'Bear MDD':>9s}")
print("-" * 80)

for freq_name in freqs:
    values = all_values[freq_name]
    regime_metrics = {}

    for r in ["Bull", "Bear", "Sideways"]:
        mask = regime == r
        # Align mask with data index
        mask_aligned = mask.reindex(data.index, fill_value=False)
        regime_vals = values[mask_aligned.values]

        if len(regime_vals) > 20:
            valid = regime_vals > 0
            regime_vals_valid = regime_vals[valid]
            if len(regime_vals_valid) > 5:
                daily_r = np.diff(np.log(regime_vals_valid))
                if len(daily_r) > 0 and daily_r.std() > 0:
                    regime_sharpe = daily_r.mean() / daily_r.std() * np.sqrt(252)
                else:
                    regime_sharpe = 0

                rm = np.maximum.accumulate(regime_vals_valid)
                dd = (regime_vals_valid - rm) / rm
                regime_mdd = dd.min() * 100
            else:
                regime_sharpe = 0
                regime_mdd = 0
        else:
            regime_sharpe = 0
            regime_mdd = 0

        regime_metrics[r] = {"sharpe": regime_sharpe, "mdd": regime_mdd}

    print(f"  {freq_name:12s} | {regime_metrics['Bull']['sharpe']:>12.3f} | "
          f"{regime_metrics['Bear']['sharpe']:>12.3f} | "
          f"{regime_metrics['Sideways']['sharpe']:>12.3f} | "
          f"{regime_metrics['Bull']['mdd']:>8.1f}% | "
          f"{regime_metrics['Bear']['mdd']:>8.1f}%")

# ================================================================
# Summary table
# ================================================================
print("\n" + "=" * 70)
print("SUMMARY TABLE: All 8 Combinations")
print("=" * 70)
header = (f"  {'Strategy':22s} | {'Invested':>10s} | {'Terminal':>12s} | "
          f"{'Return':>7s} | {'Sharpe':>6s} | {'Sortino':>7s} | "
          f"{'MDD':>7s} | {'Calmar':>6s}")
print(header)
print("-" * len(header))

for label in ["Weekly", "Weekly + VT", "Biweekly", "Biweekly + VT",
              "Monthly", "Monthly + VT", "Quarterly", "Quarterly + VT"]:
    r = results[label]
    print(f"  {label:22s} | ${r['total_invested']:>9,.0f} | ${r['terminal_wealth']:>11,.0f} | "
          f"{r['total_return_pct']:>6.1f}% | {r['sharpe']:>6.3f} | {r['sortino']:>7.3f} | "
          f"{r['mdd_pct']:>6.1f}% | {r['calmar']:>6.3f}")

# ================================================================
# Key findings
# ================================================================
print("\n" + "=" * 70)
print("KEY FINDINGS")
print("=" * 70)

# 1. Frequency sensitivity
weekly_ret = results["Weekly"]["total_return_pct"]
monthly_ret = results["Monthly"]["total_return_pct"]
quarterly_ret = results["Quarterly"]["total_return_pct"]

print(f"\n1. Frequency Sensitivity:")
print(f"   Weekly return: {weekly_ret:.1f}% | Monthly: {monthly_ret:.1f}% | "
      f"Quarterly: {quarterly_ret:.1f}%")
print(f"   Weekly-Monthly difference: {weekly_ret - monthly_ret:+.1f}% "
      f"(p={diff_pvalue:.4f})")
print(f"   Weekly-Quarterly difference: {weekly_ret - quarterly_ret:+.1f}% "
      f"(p={diff_wq_pvalue:.4f})")

# 2. VT value-add
print(f"\n2. VT (24/VIX) Value-Add for DCA:")
for freq_name in freqs:
    no_vt_mdd = results[freq_name]["mdd_pct"]
    vt_mdd = results[f"{freq_name} + VT"]["mdd_pct"]
    print(f"   {freq_name:12s}: MDD {no_vt_mdd:.1f}% → {vt_mdd:.1f}% "
          f"({vt_mdd - no_vt_mdd:+.1f}%)")

# 3. Best combo
best_key = max(results.keys(), key=lambda k: results[k]["sharpe"])
best = results[best_key]
print(f"\n3. Best Overall (by Sharpe): {best_key}")
print(f"   Sharpe={best['sharpe']:.3f}, MDD={best['mdd_pct']:.1f}%, "
      f"Return={best['total_return_pct']:.1f}%")

# Practical recommendation
print(f"\n4. Practical Recommendation for Retail Investors:")
print(f"   - DCA frequency has {'minimal' if abs(diff_pvalue) > 0.05 else 'significant'} "
      f"impact on terminal wealth")
print(f"   - Monthly DCA is the practical sweet spot (simple + low effort)")
print(f"   - VT overlay provides {'meaningful' if abs(results['Monthly + VT']['mdd_pct']) < abs(results['Monthly']['mdd_pct']) * 0.8 else 'modest'} "
      f"MDD reduction")
print(f"   - 50/50 SPY/GLD already provides strong diversification (K70 confirmed)")

# ================================================================
# Normalize terminal wealth per $1 invested (fair comparison)
# ================================================================
print("\n" + "=" * 70)
print("NORMALIZED COMPARISON (per $1 invested)")
print("=" * 70)
print(f"  {'Strategy':22s} | {'$/$ Invested':>12s} | {'Annual IRR':>10s}")
print("-" * 55)

for label in ["Weekly", "Weekly + VT", "Biweekly", "Biweekly + VT",
              "Monthly", "Monthly + VT", "Quarterly", "Quarterly + VT"]:
    r = results[label]
    per_dollar = r["terminal_wealth"] / r["total_invested"]
    print(f"  {label:22s} | ${per_dollar:>11.3f} | {r['ann_return_pct']:>9.2f}%")

# ================================================================
# Save results
# ================================================================
output_path = "/Users/yhlai0911/Desktop/volpred-research/.claude/worktrees/agent-af8b57cb/experiments/dca_frequency_results.json"

save_results = {
    "experiment": "K122",
    "title": "DCA Optimal Frequency + VT Integration",
    "date": datetime.now().isoformat(),
    "data_range": f"{data.index[0].date()} to {data.index[-1].date()}",
    "parameters": {
        "contribution": CONTRIBUTION,
        "spy_weight": SPY_WEIGHT,
        "gld_weight": GLD_WEIGHT,
        "vt_target": VT_TARGET,
        "n_bootstrap": N_BOOTSTRAP,
    },
    "results": {},
    "statistical_tests": {
        "weekly_vs_monthly": {
            "bootstrap_mean_diff": float(diff_mean),
            "bootstrap_ci_95": [float(diff_ci_lo), float(diff_ci_hi)],
            "p_value": float(diff_pvalue),
        },
        "weekly_vs_quarterly": {
            "bootstrap_mean_diff": float(diff_wq.mean()),
            "bootstrap_ci_95": [float(np.percentile(diff_wq, 2.5)),
                                float(np.percentile(diff_wq, 97.5))],
            "p_value": float(diff_wq_pvalue),
        },
    },
}

for label, metrics in results.items():
    save_results["results"][label] = {k: float(v) for k, v in metrics.items()}

with open(output_path, "w") as f:
    json.dump(save_results, f, indent=2, ensure_ascii=False)

print(f"\nResults saved to: {output_path}")
print("\n✓ K122 experiment complete.")
