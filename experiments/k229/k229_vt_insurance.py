"""
K229: VT Insurance Pricing — How Much Does Protection Cost Per Regime?
=====================================================================
[提出: 用戶, 執行: Claude]

Background: K226 showed VT has +3.36%/yr alpha and K222 showed it helps retirees.
But the "insurance cost" of VT varies by regime. In calm markets VT pays a premium;
in crises it pays off massively. What's the exact cost/benefit by VIX regime?

Data: SPY, GLD, VIX daily from yfinance, 2005-2024.

Methodology:
  1. Define 5 VIX regimes: Very Low (<12), Low (12-15), Normal (15-20), High (20-30), Crisis (>30)
  2. For each regime: B&H return vs VT return, insurance premium, MDD improvement, insurance ratio
  3. Time spent in each regime (% of days)
  4. Expected annual cost: Σ (regime probability × regime premium)
  5. Breakeven analysis: how often does a crisis need to occur for VT to be worth it?
  6. Rolling 5-year insurance cost trend
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
DATA_START = "2004-01-01"
BACKTEST_START = "2005-01-03"
BACKTEST_END = "2024-12-31"
VIX_TARGET = 12.0
RF_ANNUAL = 0.02
RF_DAILY = RF_ANNUAL / 252

# VIX regime boundaries
REGIMES = {
    "Very Low (<12)":  (0, 12),
    "Low (12-15)":     (12, 15),
    "Normal (15-20)":  (15, 20),
    "High (20-30)":    (20, 30),
    "Crisis (>30)":    (30, 999),
}

print("=" * 90)
print("K229: VT INSURANCE PRICING — HOW MUCH DOES PROTECTION COST PER REGIME?")
print("[提出: 用戶, 執行: Claude]")
print("=" * 90)

# ==================================================================
# HELPER: compute_metrics (defined early so all sections can use it)
# ==================================================================
def compute_metrics(rets, n_years, label=""):
    """Compute standard performance metrics from a log-return series."""
    cum = np.exp(np.cumsum(rets))
    total_ret = cum[-1] / cum[0]
    cagr = total_ret ** (1 / n_years) - 1
    ann_vol = np.std(rets) * np.sqrt(252)
    excess = np.mean(rets) - RF_DAILY
    sharpe = excess / np.std(rets) * np.sqrt(252) if np.std(rets) > 0 else 0
    peak = np.maximum.accumulate(cum)
    dd = (cum - peak) / peak
    mdd = np.min(dd)
    calmar = cagr / abs(mdd) if mdd != 0 else 0
    return {
        "label": label, "cagr": cagr, "ann_vol": ann_vol,
        "sharpe": sharpe, "mdd": mdd, "calmar": calmar,
        "cum_return": total_ret - 1,
    }

def compute_mdd(rets):
    """Compute max drawdown from a return series (log returns)."""
    cum = np.exp(np.cumsum(rets))
    peak = np.maximum.accumulate(cum)
    dd = (cum - peak) / peak
    return np.min(dd) * 100  # in percent

# ==================================================================
# 1. Download Data
# ==================================================================
print("\n[1/8] Downloading price data from yfinance...")

tickers = {"SPY": "SPY", "GLD": "GLD", "VIX": "^VIX"}
raw_data = {}

for name, ticker in tickers.items():
    df = yf.download(ticker, start=DATA_START, end="2025-06-01", progress=False, auto_adjust=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    raw_data[name] = df[["Close"]].rename(columns={"Close": name.lower()})
    print(f"  {name}: {len(df)} days ({df.index[0].date()} to {df.index[-1].date()})")

# Merge
data = raw_data["SPY"].join(raw_data["GLD"], how="inner") \
                       .join(raw_data["VIX"], how="inner")
data = data.dropna()
data = data.loc[BACKTEST_START:BACKTEST_END]

# Compute log returns
data["spy_ret"] = np.log(data["spy"] / data["spy"].shift(1))
data["gld_ret"] = np.log(data["gld"] / data["gld"].shift(1))
data = data.dropna()

print(f"\n  Backtest period: {data.index[0].date()} to {data.index[-1].date()}")
print(f"  Total trading days: {len(data)}")
n = len(data)
n_years = n / 252

# ==================================================================
# 2. Build Strategy Returns
# ==================================================================
print("\n[2/8] Computing strategy returns...")

spy_rets = data["spy_ret"].values
gld_rets = data["gld_ret"].values
vix_vals = data["vix"].values

# --- Buy & Hold 50/50 SPY/GLD ---
bh_rets = 0.5 * spy_rets + 0.5 * gld_rets

# --- 50/50 SPY/GLD + 12/VIX VT (lagged VIX) ---
vt_rets = np.zeros(n)
vt_equity_weights = np.zeros(n)
for i in range(1, n):
    w_equity = min(VIX_TARGET / vix_vals[i-1], 1.0)  # lagged VIX
    vt_equity_weights[i] = w_equity
    # VT scales the entire 50/50 portfolio vs cash (0%)
    vt_rets[i] = w_equity * (0.5 * spy_rets[i] + 0.5 * gld_rets[i])

# Assign VIX regime label to each day (using lagged VIX for consistency)
regime_labels = np.empty(n, dtype=object)
lagged_vix = np.zeros(n)
lagged_vix[0] = vix_vals[0]
lagged_vix[1:] = vix_vals[:-1]

for i in range(n):
    v = lagged_vix[i]
    for rname, (lo, hi) in REGIMES.items():
        if lo <= v < hi:
            regime_labels[i] = rname
            break

data["regime"] = regime_labels
data["bh_ret"] = bh_rets
data["vt_ret"] = vt_rets
data["vt_equity_w"] = vt_equity_weights
data["lagged_vix"] = lagged_vix

print("  50/50 B&H and 50/50+VT strategies computed.")

# Compute full-period metrics EARLY (needed by later sections)
bh_metrics = compute_metrics(bh_rets, n_years, "50/50 B&H")
vt_metrics = compute_metrics(vt_rets, n_years, "50/50 + VT")

# ==================================================================
# 3. Per-Regime Analysis
# ==================================================================
print("\n[3/8] Per-regime cost/benefit analysis...")

print(f"\n{'Regime':<20} {'Days':>6} {'% Time':>7} {'B&H Ann':>9} {'VT Ann':>9} "
      f"{'Premium':>9} {'B&H MDD':>9} {'VT MDD':>9} {'MDD Impr':>9} {'Ratio':>8}")
print("-" * 105)

regime_results = {}

for rname in REGIMES:
    mask = data["regime"] == rname
    n_days = mask.sum()
    pct_time = n_days / n * 100

    if n_days < 5:
        print(f"{rname:<20} {n_days:>6} {pct_time:>6.1f}%  (insufficient data)")
        continue

    # Annualized returns for this regime
    bh_regime = data.loc[mask, "bh_ret"].values
    vt_regime = data.loc[mask, "vt_ret"].values

    bh_ann = np.mean(bh_regime) * 252 * 100  # annualized %
    vt_ann = np.mean(vt_regime) * 252 * 100

    # Insurance premium = B&H return - VT return (positive = VT costs you)
    premium = bh_ann - vt_ann

    # MDD within regime periods (concatenating all days in this regime)
    bh_mdd = compute_mdd(bh_regime)
    vt_mdd = compute_mdd(vt_regime)

    # MDD improvement (positive = VT has less drawdown)
    mdd_improve = abs(bh_mdd) - abs(vt_mdd)

    # Insurance ratio = MDD improvement / return sacrifice
    # Higher = better value (more MDD protection per unit of return sacrificed)
    if premium > 0 and mdd_improve > 0:
        ins_ratio = mdd_improve / premium
    elif premium <= 0:
        ins_ratio = float('inf')  # free protection
    else:
        ins_ratio = 0  # MDD worse

    regime_results[rname] = {
        "n_days": int(n_days),
        "pct_time": round(pct_time, 2),
        "bh_ann_ret": round(bh_ann, 2),
        "vt_ann_ret": round(vt_ann, 2),
        "insurance_premium": round(premium, 2),
        "bh_mdd": round(bh_mdd, 2),
        "vt_mdd": round(vt_mdd, 2),
        "mdd_improvement": round(mdd_improve, 2),
        "insurance_ratio": round(ins_ratio, 2) if ins_ratio != float('inf') else "FREE",
        "avg_vt_weight": round(data.loc[mask, "vt_equity_w"].mean() * 100, 1),
    }

    ratio_str = "FREE" if ins_ratio == float('inf') else f"{ins_ratio:>7.2f}x"
    print(f"{rname:<20} {n_days:>6} {pct_time:>6.1f}% {bh_ann:>+8.2f}% {vt_ann:>+8.2f}% "
          f"{premium:>+8.2f}% {bh_mdd:>8.2f}% {vt_mdd:>8.2f}% {mdd_improve:>+8.2f}% {ratio_str:>8}")

# ==================================================================
# 4. Expected Annual Insurance Cost
# ==================================================================
print("\n" + "=" * 90)
print("[4/8] Expected Annual Insurance Cost")
print("=" * 90)

print(f"\n  Formula: E[Annual Cost] = Σ (P(regime) × regime premium)")
print(f"  This answers: 'On average, how much does VT cost per year?'\n")

total_expected_cost = 0
print(f"  {'Regime':<20} {'P(regime)':>10} {'Premium':>10} {'Contribution':>12}")
print(f"  {'-'*55}")

for rname, rdata in regime_results.items():
    prob = rdata["pct_time"] / 100
    prem = rdata["insurance_premium"]
    contrib = prob * prem
    total_expected_cost += contrib
    print(f"  {rname:<20} {prob:>9.3f}  {prem:>+9.2f}%  {contrib:>+11.3f}%")

print(f"  {'-'*55}")
print(f"  {'TOTAL EXPECTED':<20} {'':>10} {'':>10} {total_expected_cost:>+11.3f}%/yr")

# Full-period verification
full_bh_ann = np.mean(bh_rets) * 252 * 100
full_vt_ann = np.mean(vt_rets) * 252 * 100
full_premium = full_bh_ann - full_vt_ann
print(f"\n  Verification (full-period): B&H={full_bh_ann:+.2f}%, VT={full_vt_ann:+.2f}%, Premium={full_premium:+.2f}%/yr")

# ==================================================================
# 5. Breakeven Analysis
# ==================================================================
print("\n" + "=" * 90)
print("[5/8] Breakeven Analysis — How Often Must Crisis Occur?")
print("=" * 90)

# Full-period MDD and return differences
full_mdd_improvement = abs(bh_metrics["mdd"]) - abs(vt_metrics["mdd"])
full_return_cost = bh_metrics["cagr"] - vt_metrics["cagr"]
cost_per_1pct_mdd = (full_return_cost * 100) / (full_mdd_improvement * 100) if full_mdd_improvement > 0 else float('inf')

# --- RETURN-BASED ANALYSIS ---
non_crisis_regimes = ["Very Low (<12)", "Low (12-15)", "Normal (15-20)"]
protection_regimes = ["High (20-30)", "Crisis (>30)"]
crisis_regime = "Crisis (>30)"

# Cost during calm regimes (VIX < 20)
calm_cost = 0
calm_prob = 0
for rname in non_crisis_regimes:
    if rname in regime_results:
        prob = regime_results[rname]["pct_time"] / 100
        prem = regime_results[rname]["insurance_premium"]
        calm_cost += prob * prem
        calm_prob += prob

calm_avg_cost = calm_cost / calm_prob if calm_prob > 0 else 0

# MDD benefit during high-vol regimes
high_vol_mdd_benefit = 0
high_vol_prob = 0
for rname in protection_regimes:
    if rname in regime_results:
        prob = regime_results[rname]["pct_time"] / 100
        high_vol_mdd_benefit += prob * regime_results[rname]["mdd_improvement"]
        high_vol_prob += prob

high_vol_avg_mdd_benefit = high_vol_mdd_benefit / high_vol_prob if high_vol_prob > 0 else 0

print(f"\n  RETURN-BASED ANALYSIS:")
print(f"  VT costs return in ALL regimes (even crisis — recovery days are VIX>30 too)")
print(f"  Total annual return cost: {total_expected_cost:+.2f}%/yr")
print(f"  Calm regime (VIX<20) contribution: {calm_cost:+.2f}%/yr ({calm_prob*100:.1f}% of time)")
print(f"  Elevated regime (VIX>20) contribution: {total_expected_cost - calm_cost:+.2f}%/yr ({(1-calm_prob)*100:.1f}% of time)")

# --- MDD-VALUE ANALYSIS ---
print(f"\n  MDD-VALUE ANALYSIS:")
print(f"  Full-period MDD improvement: {full_mdd_improvement*100:+.1f}% ({bh_metrics['mdd']*100:.1f}% -> {vt_metrics['mdd']*100:.1f}%)")
print(f"  Full-period return cost: {full_return_cost*100:+.2f}%/yr")
if cost_per_1pct_mdd != float('inf'):
    print(f"  Cost per 1% MDD reduction: {cost_per_1pct_mdd:.3f}%/yr return")
else:
    print(f"  Cost per 1% MDD reduction: N/A (no MDD improvement)")

# --- CALMAR BREAKEVEN ---
print(f"\n  CALMAR BREAKEVEN:")
print(f"  B&H Calmar:  {bh_metrics['calmar']:.4f}")
print(f"  VT Calmar:   {vt_metrics['calmar']:.4f}")
if vt_metrics['calmar'] > bh_metrics['calmar']:
    print(f"  -> VT WINS on Calmar: better return/risk ratio despite lower absolute return")
else:
    print(f"  -> B&H WINS on Calmar: VT's MDD improvement doesn't fully offset return cost")

# --- CRISIS FREQUENCY SENSITIVITY ---
print(f"\n  CRISIS FREQUENCY SENSITIVITY:")
print(f"  {'Crisis %':>10} {'Total Cost':>12} {'VT MDD':>10} {'BH MDD':>10} {'Assessment':<30}")
print(f"  {'-'*75}")

actual_crisis_pct = regime_results.get(crisis_regime, {}).get("pct_time", 0)

for crisis_pct in [0, 2, 5, actual_crisis_pct, 10, 15, 20]:
    if crisis_regime not in regime_results:
        break
    # What if crisis were X% instead of actual?
    actual_crisis_contrib = actual_crisis_pct / 100 * regime_results[crisis_regime]["insurance_premium"]
    new_crisis_contrib = crisis_pct / 100 * regime_results[crisis_regime]["insurance_premium"]
    # Non-crisis regimes scale proportionally
    non_crisis_base = total_expected_cost - actual_crisis_contrib
    if (100 - actual_crisis_pct) > 0:
        non_crisis_scale = (100 - crisis_pct) / (100 - actual_crisis_pct)
    else:
        non_crisis_scale = 1.0
    new_non_crisis = non_crisis_base * non_crisis_scale
    new_total = new_non_crisis + new_crisis_contrib

    marker = " <-- actual" if abs(crisis_pct - actual_crisis_pct) < 0.5 else ""
    assessment = "no crisis protection needed" if crisis_pct == 0 else (
        "worth it (MDD protection)" if crisis_pct >= 5 else "marginal"
    )
    print(f"  {crisis_pct:>9.1f}% {new_total:>+11.2f}%/yr {vt_metrics['mdd']*100:>9.1f}% "
          f"{bh_metrics['mdd']*100:>9.1f}% {assessment}{marker}")

# --- BREAKEVEN CONCLUSION ---
# Return-based breakeven: find crisis_pct where total cost = 0
# total_cost(x) = non_crisis_base * (100-x)/(100-actual) + x/100 * crisis_premium
# Set to 0 and solve for x
if crisis_regime in regime_results:
    crisis_premium = regime_results[crisis_regime]["insurance_premium"]
    non_crisis_base_total = total_expected_cost - actual_crisis_pct / 100 * crisis_premium
    denom_scale = 100 - actual_crisis_pct
    # total_cost(x) = non_crisis_base_total * (100-x)/denom_scale + x/100 * crisis_premium = 0
    # Let A = non_crisis_base_total / denom_scale, B = crisis_premium / 100
    # A*(100-x) + B*x = 0
    # 100A - Ax + Bx = 0
    # x(B-A) = -100A
    # x = -100A / (B-A)
    A = non_crisis_base_total / denom_scale if denom_scale != 0 else 0
    B = crisis_premium / 100
    if (B - A) != 0:
        breakeven_crisis_freq = -100 * A / (B - A)
    else:
        breakeven_crisis_freq = float('inf')
else:
    breakeven_crisis_freq = float('inf')

print(f"\n  BREAKEVEN CONCLUSION:")
if breakeven_crisis_freq > 0 and breakeven_crisis_freq < 100:
    print(f"  Return breakeven: crisis must occur {breakeven_crisis_freq:.1f}% of the time")
    print(f"  Actual crisis frequency: {actual_crisis_pct:.1f}%")
    if actual_crisis_pct > breakeven_crisis_freq:
        print(f"  -> VT breaks even on RETURN (actual > breakeven)")
    else:
        print(f"  -> VT does NOT break even on return alone")
else:
    print(f"  Return-only: VT never breaks even on return (always costs {total_expected_cost:.1f}%/yr)")

print(f"  MDD-adjusted: VT provides {full_mdd_improvement*100:.1f}% MDD improvement")
print(f"  Calmar-adjusted: VT {'wins' if vt_metrics['calmar'] > bh_metrics['calmar'] else 'loses'} "
      f"({vt_metrics['calmar']:.3f} vs {bh_metrics['calmar']:.3f})")
print(f"  -> The right question is not 'does VT break even on return' but")
if cost_per_1pct_mdd != float('inf'):
    print(f"    'is {full_return_cost*100:.2f}%/yr a fair price for {full_mdd_improvement*100:.1f}% less MDD?'")
    print(f"    ({cost_per_1pct_mdd:.3f}%/yr per 1% MDD reduction)")
else:
    print(f"    'is the risk reduction worth the return cost?'")

# ==================================================================
# 5b. Per-regime marginal analysis
# ==================================================================
print(f"\n  --- Per-regime marginal contribution ---")
print(f"  {'Regime':<20} {'Avg Cost':>10} {'If never occurs':>16} {'Marginal impact':>16}")
print(f"  {'-'*65}")

for rname in REGIMES:
    if rname not in regime_results:
        continue
    prob = regime_results[rname]["pct_time"] / 100
    prem = regime_results[rname]["insurance_premium"]
    contrib = prob * prem
    # What if this regime never happened?
    hypothetical = total_expected_cost - contrib
    print(f"  {rname:<20} {contrib:>+9.3f}%  {hypothetical:>+15.3f}%  {-contrib:>+15.3f}%")

# ==================================================================
# 6. Rolling 5-Year Insurance Cost
# ==================================================================
print("\n" + "=" * 90)
print("[6/8] Rolling 5-Year Insurance Cost Trend")
print("=" * 90)

window_days = 252 * 5  # 5 years
rolling_cost = []

for end_idx in range(window_days, n):
    start_idx = end_idx - window_days
    bh_window = bh_rets[start_idx:end_idx]
    vt_window = vt_rets[start_idx:end_idx]

    bh_ann_w = np.mean(bh_window) * 252 * 100
    vt_ann_w = np.mean(vt_window) * 252 * 100
    premium_w = bh_ann_w - vt_ann_w

    rolling_cost.append({
        "date": data.index[end_idx].strftime("%Y-%m-%d"),
        "premium": premium_w,
        "bh_ann": bh_ann_w,
        "vt_ann": vt_ann_w,
    })

rolling_df = pd.DataFrame(rolling_cost)

print(f"\n  Rolling 5-year insurance cost statistics:")
print(f"  Mean:   {rolling_df['premium'].mean():+.2f}%/yr")
print(f"  Median: {rolling_df['premium'].median():+.2f}%/yr")
print(f"  Std:    {rolling_df['premium'].std():.2f}%/yr")
print(f"  Min:    {rolling_df['premium'].min():+.2f}%/yr (best 5yr for VT)")
print(f"  Max:    {rolling_df['premium'].max():+.2f}%/yr (worst 5yr for VT)")
print(f"  % of windows where VT wins: {(rolling_df['premium'] < 0).mean()*100:.1f}%")

# Print 5yr snapshots
print(f"\n  Year-end snapshots (trailing 5yr insurance cost):")
print(f"  {'End Date':<12} {'Insurance Cost':>14} {'Interpretation':<30}")
print(f"  {'-'*60}")

for year in range(2010, 2025):
    year_mask = rolling_df["date"].str.startswith(str(year))
    if year_mask.any():
        last_row = rolling_df[year_mask].iloc[-1]
        prem = last_row["premium"]
        interp = "VT wins (free)" if prem < 0 else f"VT costs {prem:.1f}%/yr"
        print(f"  {last_row['date']:<12} {prem:>+13.2f}%  {interp}")

# ==================================================================
# 7. Detailed Regime Behavior Table
# ==================================================================
print("\n" + "=" * 90)
print("[7/8] Detailed Regime Analysis")
print("=" * 90)

print(f"\n  Avg VT equity weight by regime:")
print(f"  {'Regime':<20} {'Avg Weight':>10} {'Meaning':<40}")
print(f"  {'-'*72}")

for rname in REGIMES:
    if rname not in regime_results:
        continue
    w = regime_results[rname]["avg_vt_weight"]
    if w >= 95:
        meaning = "Fully invested — no protection, pure equity"
    elif w >= 70:
        meaning = "Mostly invested — modest de-risking"
    elif w >= 40:
        meaning = "Moderate de-risking"
    elif w >= 20:
        meaning = "Heavily de-risked"
    else:
        meaning = "Minimal equity — maximum protection"
    print(f"  {rname:<20} {w:>9.1f}%  {meaning}")

# Transition analysis: how often does the regime change?
transitions = 0
for i in range(1, n):
    if regime_labels[i] != regime_labels[i-1]:
        transitions += 1

avg_regime_duration = n / (transitions + 1)
print(f"\n  Regime transitions: {transitions} over {n} days")
print(f"  Average regime duration: {avg_regime_duration:.1f} trading days ({avg_regime_duration/21:.1f} months)")
print(f"  Transitions per year: {transitions/n_years:.1f}")

# VIX regime time distribution by decade
print(f"\n  Regime distribution by decade:")
print(f"  {'Regime':<20} {'2005-2009':>10} {'2010-2014':>10} {'2015-2019':>10} {'2020-2024':>10}")
print(f"  {'-'*65}")

for rname in REGIMES:
    row = f"  {rname:<20}"
    for decade_start, decade_end in [(2005,2010), (2010,2015), (2015,2020), (2020,2025)]:
        decade_mask = (data.index.year >= decade_start) & (data.index.year < decade_end)
        regime_mask = data["regime"] == rname
        both = decade_mask & regime_mask
        decade_total = decade_mask.sum()
        if decade_total > 0:
            pct = both.sum() / decade_total * 100
            row += f" {pct:>9.1f}%"
        else:
            row += f" {'N/A':>9}"
    print(row)

# ==================================================================
# 8. Full-Period Performance Summary
# ==================================================================
print("\n" + "=" * 90)
print("[8/8] Full-Period Performance Summary")
print("=" * 90)

print(f"\n  {'Metric':<25} {'50/50 B&H':>12} {'50/50 + VT':>12} {'Difference':>12}")
print(f"  {'-'*65}")
print(f"  {'CAGR':<25} {bh_metrics['cagr']*100:>11.2f}% {vt_metrics['cagr']*100:>11.2f}% "
      f"{(vt_metrics['cagr']-bh_metrics['cagr'])*100:>+11.2f}%")
print(f"  {'Ann. Volatility':<25} {bh_metrics['ann_vol']*100:>11.2f}% {vt_metrics['ann_vol']*100:>11.2f}% "
      f"{(vt_metrics['ann_vol']-bh_metrics['ann_vol'])*100:>+11.2f}%")
print(f"  {'Sharpe Ratio':<25} {bh_metrics['sharpe']:>11.3f}  {vt_metrics['sharpe']:>11.3f}  "
      f"{vt_metrics['sharpe']-bh_metrics['sharpe']:>+11.3f}")
print(f"  {'Max Drawdown':<25} {bh_metrics['mdd']*100:>11.2f}% {vt_metrics['mdd']*100:>11.2f}% "
      f"{(vt_metrics['mdd']-bh_metrics['mdd'])*100:>+11.2f}%")
print(f"  {'Calmar Ratio':<25} {bh_metrics['calmar']:>11.3f}  {vt_metrics['calmar']:>11.3f}  "
      f"{vt_metrics['calmar']-bh_metrics['calmar']:>+11.3f}")
print(f"  {'Cum. Return':<25} {bh_metrics['cum_return']*100:>11.1f}% {vt_metrics['cum_return']*100:>11.1f}% "
      f"{(vt_metrics['cum_return']-bh_metrics['cum_return'])*100:>+11.1f}%")

# ==================================================================
# KEY FINDINGS
# ==================================================================
print("\n" + "=" * 90)
print("KEY FINDINGS")
print("=" * 90)

print(f"""
  1. INSURANCE COST BY REGIME:""")
for rname in REGIMES:
    if rname in regime_results:
        r = regime_results[rname]
        print(f"     - {rname}: premium={r['insurance_premium']:+.2f}%/yr, "
              f"MDD improvement={r['mdd_improvement']:+.1f}%, "
              f"ratio={'FREE' if r['insurance_ratio'] == 'FREE' else str(r['insurance_ratio'])+'x'}")

print(f"""
  2. EXPECTED ANNUAL COST:
     - Probability-weighted annual premium: {total_expected_cost:+.2f}%/yr
     - This is the "insurance premium" for VT protection

  3. BREAKEVEN:
     - Actual crisis frequency: {actual_crisis_pct:.1f}%
     - MDD improvement: {full_mdd_improvement*100:+.1f}% ({bh_metrics['mdd']*100:.1f}% -> {vt_metrics['mdd']*100:.1f}%)
     - Calmar: VT {'wins' if vt_metrics['calmar'] > bh_metrics['calmar'] else 'loses'} ({vt_metrics['calmar']:.3f} vs {bh_metrics['calmar']:.3f})
     - Cost per 1% MDD reduction: {cost_per_1pct_mdd:.3f}%/yr

  4. ROLLING 5-YEAR COST:
     - Mean: {rolling_df['premium'].mean():+.2f}%/yr
     - Highly variable (std={rolling_df['premium'].std():.2f}%)
     - VT wins in {(rolling_df['premium'] < 0).mean()*100:.0f}% of 5-year windows

  5. REGIME DISTRIBUTION:""")

for rname in REGIMES:
    if rname in regime_results:
        r = regime_results[rname]
        print(f"     - {rname}: {r['pct_time']:.1f}% of time, avg weight {r['avg_vt_weight']:.0f}%")

print(f"""
  6. CONCLUSION:
     VT's insurance is regime-adaptive: negligible cost in calm markets (VIX<12),
     moderate premium in normal markets, and the protection kicks in when VIX>20.
     The critical insight: you pay {total_expected_cost:+.2f}%/yr for a {full_mdd_improvement*100:.1f}% MDD
     reduction. This is {cost_per_1pct_mdd:.3f}%/yr per 1% of MDD protection — a fair
     price for investors who value drawdown control over raw returns.
""")

# ==================================================================
# Save results
# ==================================================================
output = {
    "experiment": "K229",
    "title": "VT Insurance Pricing — How Much Does Protection Cost Per Regime?",
    "proposed_by": "user",
    "executed_by": "Claude",
    "period": f"{data.index[0].date()} to {data.index[-1].date()}",
    "n_days": int(n),
    "n_years": round(n_years, 2),
    "data_source": "yfinance (SPY, GLD, ^VIX daily)",
    "regime_analysis": regime_results,
    "expected_annual_cost_pct": round(total_expected_cost, 3),
    "rolling_5yr_cost": {
        "mean": round(rolling_df["premium"].mean(), 3),
        "median": round(rolling_df["premium"].median(), 3),
        "std": round(rolling_df["premium"].std(), 3),
        "min": round(rolling_df["premium"].min(), 3),
        "max": round(rolling_df["premium"].max(), 3),
        "pct_vt_wins": round((rolling_df["premium"] < 0).mean() * 100, 1),
    },
    "full_period": {
        "bh_50_50": {
            "cagr": round(bh_metrics["cagr"] * 100, 3),
            "sharpe": round(bh_metrics["sharpe"], 4),
            "mdd": round(bh_metrics["mdd"] * 100, 2),
            "calmar": round(bh_metrics["calmar"], 4),
        },
        "vt_50_50": {
            "cagr": round(vt_metrics["cagr"] * 100, 3),
            "sharpe": round(vt_metrics["sharpe"], 4),
            "mdd": round(vt_metrics["mdd"] * 100, 2),
            "calmar": round(vt_metrics["calmar"], 4),
        },
    },
    "mdd_improvement_pct": round(full_mdd_improvement * 100, 2),
    "cost_per_1pct_mdd": round(cost_per_1pct_mdd, 4) if cost_per_1pct_mdd != float('inf') else None,
    "regime_transitions_per_year": round(transitions / n_years, 1),
    "avg_regime_duration_days": round(avg_regime_duration, 1),
}

output_path = "experiments/k229_vt_insurance_results.json"
with open(output_path, "w") as f:
    json.dump(output, f, indent=2, default=str)

print(f"\n  Results saved to: {output_path}")
print(f"\n{'='*90}")
print("K229 EXPERIMENT COMPLETE")
print(f"{'='*90}")
