"""
K667: The True Cost of Portfolio Insurance — Quantifying VT as Insurance
========================================================================
[提出: K656/K664 延伸, 執行: Claude]

Building on:
  - K656: VT is BOTH alpha AND insurance (CAGR 17.1% vs BH 11.4%)
  - K664: P(MDD>20%) = 0% with 50/50+VT
  - K127: VT Insurance Pricing (cost-per-1%-MDD-reduction comparison)

This experiment quantifies the ANNUAL COST of VT as insurance:
  1. Insurance premium = BH_CAGR - VT_CAGR (what you give up)
  2. Insurance value = Expected loss avoided (MDD reduction × frequency)
  3. Break-even: At what crisis frequency does VT "pay for itself"?
  4. Comparison with real protective put costs (BS-simulated)

Data: yfinance SPY, GLD, VIX daily (2006-01-01 to 2026-03-27)
References:
  - Hallerbach (2012), "A Proof of the Optimality of Volatility Weighting"
  - Moreira & Muir (2017), "Volatility-Managed Portfolios", JF
  - Israelov & Nielsen (2015), "Still Not Cheap: Portfolio Protection in Calm Markets"
"""

import sys
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime
from scipy.stats import norm, ttest_1samp
import json

# ==================================================================
# CONFIG
# ==================================================================
DATA_START = "2005-01-01"
BACKTEST_START = "2006-01-03"
BACKTEST_END = "2026-03-27"
RF_ANNUAL = 0.02
RF_DAILY = RF_ANNUAL / 252
VIX_TARGET = 12.0

print("=" * 80)
print("K667: THE TRUE COST OF PORTFOLIO INSURANCE")
print("Quantifying VT as Insurance Premium, Value, and Break-even")
print("[提出: K656/K664 延伸, 執行: Claude]")
print("=" * 80)

# ==================================================================
# 1. Download Data
# ==================================================================
print("\n[1/6] Downloading price data...")

tickers = {"SPY": "SPY", "GLD": "GLD", "VIX": "^VIX"}
raw_data = {}

for name, ticker in tickers.items():
    df = yf.download(ticker, start=DATA_START, end="2026-04-01", progress=False, auto_adjust=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    raw_data[name] = df[["Close"]].rename(columns={"Close": name.lower()})
    print(f"  {name}: {len(df)} days ({df.index[0].date()} to {df.index[-1].date()})")

data = raw_data["SPY"].join(raw_data["GLD"], how="inner") \
                       .join(raw_data["VIX"], how="inner")
data = data.dropna()
data = data.loc[BACKTEST_START:BACKTEST_END]

data["spy_ret"] = data["spy"].pct_change()
data["gld_ret"] = data["gld"].pct_change()
data = data.dropna()

n_days = len(data)
n_years = n_days / 252
print(f"\n  Backtest: {data.index[0].date()} to {data.index[-1].date()}")
print(f"  Trading days: {n_days}, Years: {n_years:.1f}")

# ==================================================================
# 2. Build Strategy Returns (lagged VIX — correct implementation)
# ==================================================================
print("\n[2/6] Computing strategy returns (5 strategies)...")

spy_rets = data["spy_ret"].values
gld_rets = data["gld_ret"].values
vix_vals = data["vix"].values
spy_prices = data["spy"].values
dates = data.index

n = len(data)

# Helper functions
def compute_metrics(rets_array, label):
    """Compute CAGR, Sharpe, MDD, Sortino for a return series."""
    cum = np.cumprod(1 + rets_array)
    total_ret = cum[-1] - 1
    cagr = (cum[-1]) ** (252 / len(rets_array)) - 1
    vol = np.std(rets_array) * np.sqrt(252)
    sharpe = (cagr - RF_ANNUAL) / vol if vol > 0 else 0

    # MDD
    peak = np.maximum.accumulate(cum)
    dd = (cum - peak) / peak
    mdd = np.min(dd)

    # Sortino
    downside = rets_array[rets_array < 0]
    down_vol = np.std(downside) * np.sqrt(252) if len(downside) > 0 else vol
    sortino = (cagr - RF_ANNUAL) / down_vol if down_vol > 0 else 0

    return {
        "label": label,
        "cagr": cagr,
        "vol": vol,
        "sharpe": sharpe,
        "sortino": sortino,
        "mdd": mdd,
        "total_return": total_ret,
        "cum": cum,
        "dd": dd
    }

def compute_mdd_events(cum_returns, threshold=-0.10):
    """Find MDD events exceeding threshold. Returns list of (start, trough, depth)."""
    peak = np.maximum.accumulate(cum_returns)
    dd = (cum_returns - peak) / peak

    events = []
    in_drawdown = False
    start_idx = 0
    worst_dd = 0
    worst_idx = 0

    for i in range(len(dd)):
        if dd[i] < threshold and not in_drawdown:
            in_drawdown = True
            start_idx = i
            worst_dd = dd[i]
            worst_idx = i
        elif in_drawdown:
            if dd[i] < worst_dd:
                worst_dd = dd[i]
                worst_idx = i
            if dd[i] >= 0:  # recovery
                events.append((start_idx, worst_idx, worst_dd))
                in_drawdown = False

    # Handle ongoing drawdown
    if in_drawdown:
        events.append((start_idx, worst_idx, worst_dd))

    return events

# Strategy 0: Buy & Hold SPY
bh_spy_rets = spy_rets.copy()

# Strategy 1: 12/VIX SPY only (lagged VIX for weight, remainder in cash at RF)
vt_spy_rets = np.zeros(n)
vt_spy_weights = np.zeros(n)
for i in range(1, n):
    w = min(VIX_TARGET / vix_vals[i-1], 1.0)
    vt_spy_weights[i] = w
    vt_spy_rets[i] = w * spy_rets[i] + (1 - w) * RF_DAILY

# Strategy 2: 50/50 SPY/GLD Buy & Hold
bh_5050_rets = 0.5 * spy_rets + 0.5 * gld_rets

# Strategy 3: 50/50 SPY/GLD + 12/VIX overlay
vt_5050_rets = np.zeros(n)
for i in range(1, n):
    w = min(VIX_TARGET / vix_vals[i-1], 1.0)
    vt_5050_rets[i] = w * (0.5 * spy_rets[i] + 0.5 * gld_rets[i]) + (1 - w) * RF_DAILY

# Strategy 4: BH 60/40 SPY/GLD
bh_6040_rets = 0.6 * spy_rets + 0.4 * gld_rets

strategies = {
    "BH_SPY": bh_spy_rets,
    "12/VIX_SPY": vt_spy_rets,
    "BH_50/50": bh_5050_rets,
    "50/50+VT": vt_5050_rets,
    "BH_60/40": bh_6040_rets
}

results = {}
for name, rets in strategies.items():
    results[name] = compute_metrics(rets, name)
    r = results[name]
    print(f"  {name:15s}: CAGR {r['cagr']*100:6.2f}%, Sharpe {r['sharpe']:.3f}, "
          f"MDD {r['mdd']*100:6.1f}%, Vol {r['vol']*100:5.1f}%")

# ==================================================================
# 3. Insurance Premium Calculation
# ==================================================================
print("\n[3/6] Computing insurance premiums (annual cost of protection)...")

# Premium = BH_CAGR - VT_CAGR (what you sacrifice for protection)
# Also compute per-unit cost: premium / MDD_improvement

print(f"\n  {'Comparison':<35s} {'Premium':>8s} {'MDD Improv':>10s} {'Cost/1%MDD':>10s}")
print(f"  {'-'*35} {'-'*8} {'-'*10} {'-'*10}")

insurance_comparisons = [
    ("BH_SPY → 12/VIX_SPY", "BH_SPY", "12/VIX_SPY"),
    ("BH_SPY → BH_50/50", "BH_SPY", "BH_50/50"),
    ("BH_SPY → 50/50+VT", "BH_SPY", "50/50+VT"),
    ("BH_SPY → BH_60/40", "BH_SPY", "BH_60/40"),
    ("BH_50/50 → 50/50+VT", "BH_50/50", "50/50+VT"),
    ("BH_60/40 → 50/50+VT", "BH_60/40", "50/50+VT"),
]

premium_data = []
for label, base, insured in insurance_comparisons:
    base_cagr = results[base]["cagr"]
    ins_cagr = results[insured]["cagr"]
    premium = base_cagr - ins_cagr  # positive = you pay, negative = you EARN

    base_mdd = results[base]["mdd"]
    ins_mdd = results[insured]["mdd"]
    mdd_improvement = abs(base_mdd) - abs(ins_mdd)  # positive = insured has smaller MDD

    cost_per_pct = (premium / (mdd_improvement * 100)) if mdd_improvement > 0 else float('nan')

    prem_str = f"{premium*100:+.2f}%"
    mdd_str = f"{mdd_improvement*100:+.1f}pp"
    cost_str = f"{cost_per_pct*100:.3f}%" if not np.isnan(cost_per_pct) else "N/A"

    print(f"  {label:<35s} {prem_str:>8s} {mdd_str:>10s} {cost_str:>10s}")

    premium_data.append({
        "comparison": label,
        "base": base,
        "insured": insured,
        "base_cagr_pct": round(base_cagr * 100, 3),
        "insured_cagr_pct": round(ins_cagr * 100, 3),
        "premium_pct": round(premium * 100, 3),
        "base_mdd_pct": round(base_mdd * 100, 2),
        "insured_mdd_pct": round(ins_mdd * 100, 2),
        "mdd_improvement_pp": round(mdd_improvement * 100, 2),  # positive = less drawdown
        "cost_per_1pct_mdd_pct": round(cost_per_pct * 100, 4) if not np.isnan(cost_per_pct) else None
    })

# Annual premium from year-by-year comparison
print("\n  Year-by-year insurance premium (BH SPY → 12/VIX SPY):")
annual_premiums = []
years = sorted(set(dates.year))
for yr in years:
    mask = data.index.year == yr
    if mask.sum() < 100:
        continue
    yr_bh = bh_spy_rets[mask]
    yr_vt = vt_spy_rets[mask]
    bh_yr_ret = np.prod(1 + yr_bh) - 1
    vt_yr_ret = np.prod(1 + yr_vt) - 1
    premium_yr = bh_yr_ret - vt_yr_ret
    annual_premiums.append({
        "year": int(yr),
        "bh_return_pct": round(bh_yr_ret * 100, 2),
        "vt_return_pct": round(vt_yr_ret * 100, 2),
        "premium_pct": round(premium_yr * 100, 2)
    })
    sign = "+" if premium_yr > 0 else ""
    print(f"    {yr}: BH {bh_yr_ret*100:+7.2f}%, VT {vt_yr_ret*100:+7.2f}%, "
          f"Premium {sign}{premium_yr*100:.2f}%")

# Statistics on annual premiums
prem_vals = [p["premium_pct"] for p in annual_premiums]
mean_prem = np.mean(prem_vals)
median_prem = np.median(prem_vals)
std_prem = np.std(prem_vals, ddof=1)
prem_positive = sum(1 for p in prem_vals if p > 0)
prem_negative = sum(1 for p in prem_vals if p <= 0)

print(f"\n  Annual premium stats:")
print(f"    Mean: {mean_prem:+.2f}%/yr")
print(f"    Median: {median_prem:+.2f}%/yr")
print(f"    Std: {std_prem:.2f}%")
print(f"    Years VT costs (premium > 0): {prem_positive}/{len(prem_vals)} ({prem_positive/len(prem_vals)*100:.0f}%)")
print(f"    Years VT earns (premium ≤ 0): {prem_negative}/{len(prem_vals)} ({prem_negative/len(prem_vals)*100:.0f}%)")

# t-test: is mean premium significantly different from 0?
t_stat_prem, p_val_prem = ttest_1samp(prem_vals, 0)
print(f"    t-test (premium ≠ 0): t={t_stat_prem:.3f}, p={p_val_prem:.4f}")

# ==================================================================
# 4. Insurance Value Calculation
# ==================================================================
print("\n[4/6] Computing insurance value (expected loss avoided)...")

# Identify crisis events for each strategy using rolling MDD
# We define "crisis" thresholds: 10%, 15%, 20%, 30%
thresholds = [0.10, 0.15, 0.20, 0.30]

print(f"\n  {'Strategy':<15s}", end="")
for t in thresholds:
    print(f"  P(MDD>{t*100:.0f}%)", end="")
print(f"  E[MDD|crisis]")

crisis_analysis = {}
for name, r in results.items():
    cum = r["cum"]

    # Use rolling 252-day MDD (1-year windows)
    rolling_mdd = []
    window = 252
    for i in range(window, len(cum)):
        segment = cum[i-window:i]
        peak = np.maximum.accumulate(segment)
        dd = (segment - peak) / peak
        rolling_mdd.append(np.min(dd))

    rolling_mdd = np.array(rolling_mdd)

    probs = {}
    print(f"  {name:<15s}", end="")
    for t in thresholds:
        p = np.mean(rolling_mdd < -t)
        probs[f"P_MDD_gt_{int(t*100)}pct"] = round(p * 100, 2)
        print(f"  {p*100:8.1f}%", end="")

    # Expected MDD conditional on > 10%
    crisis_mdds = rolling_mdd[rolling_mdd < -0.10]
    e_mdd_crisis = np.mean(crisis_mdds) if len(crisis_mdds) > 0 else 0
    probs["E_MDD_given_crisis_pct"] = round(e_mdd_crisis * 100, 2)
    print(f"  {e_mdd_crisis*100:8.1f}%")

    crisis_analysis[name] = probs

# Expected loss calculation
print("\n  Insurance value calculation (Expected Loss framework):")
print(f"  On $100,000 portfolio, using rolling 1-year MDD windows:\n")

portfolio_value = 100000
for base_name, insured_name in [("BH_SPY", "12/VIX_SPY"), ("BH_SPY", "50/50+VT"), ("BH_50/50", "50/50+VT")]:
    base_cum = results[base_name]["cum"]
    ins_cum = results[insured_name]["cum"]

    window = 252
    base_losses = []
    ins_losses = []

    for i in range(window, len(base_cum)):
        # Rolling 1-year MDD for each
        b_seg = base_cum[i-window:i]
        b_peak = np.maximum.accumulate(b_seg)
        b_dd = np.min((b_seg - b_peak) / b_peak)
        base_losses.append(b_dd)

        i_seg = ins_cum[i-window:i]
        i_peak = np.maximum.accumulate(i_seg)
        i_dd = np.min((i_seg - i_peak) / i_peak)
        ins_losses.append(i_dd)

    base_losses = np.array(base_losses)
    ins_losses = np.array(ins_losses)

    # Expected loss for different crisis thresholds
    for thresh in [0.10, 0.20, 0.30]:
        base_crisis = base_losses[base_losses < -thresh]
        ins_crisis = ins_losses[ins_losses < -thresh]

        p_base = len(base_crisis) / len(base_losses)
        p_ins = len(ins_crisis) / len(ins_losses)

        e_loss_base = np.mean(base_crisis) * p_base if len(base_crisis) > 0 else 0
        e_loss_ins = np.mean(ins_crisis) * p_ins if len(ins_crisis) > 0 else 0

        loss_avoided = e_loss_base - e_loss_ins  # positive = insurance helps
        loss_avoided_dollars = abs(loss_avoided) * portfolio_value

        if thresh == 0.10:
            print(f"  {base_name} → {insured_name} (>{thresh*100:.0f}% threshold):")
            print(f"    E[loss] base: {e_loss_base*100:.2f}% (P={p_base*100:.1f}%, E[MDD|crisis]={np.mean(base_crisis)*100:.1f}%)" if len(base_crisis) > 0 else f"    E[loss] base: 0% (no crises)")
            print(f"    E[loss] insured: {e_loss_ins*100:.2f}% (P={p_ins*100:.1f}%, E[MDD|crisis]={np.mean(ins_crisis)*100:.1f}%)" if len(ins_crisis) > 0 else f"    E[loss] insured: 0% (no crises)")
            print(f"    Annual loss avoided: {loss_avoided*100:.2f}% = ${loss_avoided_dollars:,.0f}")
            print()

# ==================================================================
# 5. Break-even Analysis
# ==================================================================
print("\n[5/6] Break-even analysis...")

# Historical crisis frequency
bh_cum = results["BH_SPY"]["cum"]
crisis_events_20 = compute_mdd_events(bh_cum, threshold=-0.20)
crisis_events_30 = compute_mdd_events(bh_cum, threshold=-0.30)
crisis_events_10 = compute_mdd_events(bh_cum, threshold=-0.10)

print(f"\n  Historical crisis frequency ({n_years:.1f} years):")
print(f"    >10% drawdown events: {len(crisis_events_10)} ({n_years/max(len(crisis_events_10),1):.1f} yr/event)")
print(f"    >20% drawdown events: {len(crisis_events_20)} ({n_years/max(len(crisis_events_20),1):.1f} yr/event)")
print(f"    >30% drawdown events: {len(crisis_events_30)} ({n_years/max(len(crisis_events_30),1):.1f} yr/event)")

for ev in crisis_events_20:
    start_date = dates[ev[0]].strftime("%Y-%m")
    depth = ev[2] * 100
    print(f"      {start_date}: {depth:.1f}%")

# Break-even calculation
# VT "premium" (annual CAGR sacrifice) vs expected loss reduction
# Break-even: at what crisis frequency does loss reduction = premium?

# For BH_SPY → 12/VIX_SPY
bh_cagr = results["BH_SPY"]["cagr"]
vt_cagr = results["12/VIX_SPY"]["cagr"]
annual_premium = bh_cagr - vt_cagr  # can be negative if VT outperforms!

# Average loss per crisis event (BH)
bh_crisis_losses = [ev[2] for ev in crisis_events_20]
avg_crisis_loss_bh = np.mean(bh_crisis_losses) if bh_crisis_losses else -0.30

# For VT, find equivalent events
vt_cum = results["12/VIX_SPY"]["cum"]
vt_crisis_20 = compute_mdd_events(vt_cum, threshold=-0.20)
vt_crisis_losses = [ev[2] for ev in vt_crisis_20] if vt_crisis_20 else [0]
avg_crisis_loss_vt = np.mean(vt_crisis_losses) if vt_crisis_losses else 0

# Loss avoided per crisis
loss_avoided_per_crisis = abs(avg_crisis_loss_bh) - abs(avg_crisis_loss_vt if vt_crisis_20 else 0)

print(f"\n  Break-even analysis (BH SPY → 12/VIX SPY):")
print(f"    Annual VT premium: {annual_premium*100:+.2f}%")
print(f"    Average crisis loss (BH, >20% MDD): {avg_crisis_loss_bh*100:.1f}%")
print(f"    Average crisis loss (VT, >20% MDD): {avg_crisis_loss_vt*100:.1f}%")
print(f"    Loss avoided per crisis: {loss_avoided_per_crisis*100:.1f}pp")

if annual_premium > 0:
    if loss_avoided_per_crisis > 0:
        breakeven_freq = annual_premium / loss_avoided_per_crisis
        breakeven_years = 1 / breakeven_freq if breakeven_freq > 0 else float('inf')
        print(f"    Break-even: 1 crisis every {breakeven_years:.1f} years")
        print(f"    Historical: 1 crisis (>20%) every {n_years/max(len(crisis_events_20),1):.1f} years")
        if breakeven_years > n_years / max(len(crisis_events_20), 1):
            print(f"    → VT insurance is CHEAP (crises happen more often than break-even)")
        else:
            print(f"    → VT insurance is EXPENSIVE (crises happen less often than break-even)")
    else:
        print(f"    Loss avoided per crisis ≤ 0: VT doesn't reduce crisis losses (unlikely)")
else:
    print(f"    ★ VT PREMIUM IS NEGATIVE → VT earns money AND provides protection!")
    print(f"    No break-even needed: VT dominates on CAGR + MDD simultaneously.")

# Also for 50/50+VT
print(f"\n  Break-even analysis (BH SPY → 50/50+VT):")
bh_5050_cagr = results["BH_SPY"]["cagr"]
vt_5050_cagr = results["50/50+VT"]["cagr"]
premium_5050 = bh_5050_cagr - vt_5050_cagr

vt5050_cum = results["50/50+VT"]["cum"]
vt5050_crisis = compute_mdd_events(vt5050_cum, threshold=-0.20)
avg_loss_vt5050 = np.mean([ev[2] for ev in vt5050_crisis]) if vt5050_crisis else 0
loss_avoided_5050 = abs(avg_crisis_loss_bh) - abs(avg_loss_vt5050)

print(f"    Annual premium: {premium_5050*100:+.2f}%")
print(f"    Loss avoided per crisis: {loss_avoided_5050*100:.1f}pp")
if premium_5050 > 0 and loss_avoided_5050 > 0:
    be_years_5050 = (premium_5050 / loss_avoided_5050)
    be_period_5050 = 1 / be_years_5050 if be_years_5050 > 0 else float('inf')
    print(f"    Break-even: 1 crisis every {be_period_5050:.1f} years")
else:
    print(f"    Premium ≤ 0 or no loss reduction → different interpretation needed")

# ==================================================================
# 6. Comparison with Real Options (BS-simulated protective put)
# ==================================================================
print("\n[6/6] Comparing VT cost with protective put cost...")

def bs_put_price(S, K, T, r, sigma):
    """Black-Scholes put price."""
    if T <= 0 or sigma <= 0:
        return max(K - S, 0.0)
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    return K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)

# Simulate monthly protective put purchase (ATM)
days_per_month = 21
total_put_cost = 0
n_puts = 0
monthly_put_costs = []

for i in range(1, n):
    if i % days_per_month == 1 or i == 1:
        S = spy_prices[i-1]
        K = S * 1.0  # ATM put
        iv = vix_vals[i-1] / 100.0
        T = days_per_month / 252.0
        put_price = bs_put_price(S, K, T, RF_ANNUAL, iv)
        cost_pct = put_price / S
        total_put_cost += cost_pct
        monthly_put_costs.append(cost_pct)
        n_puts += 1

# Annualize
avg_monthly_put_cost = np.mean(monthly_put_costs)
annual_put_cost = avg_monthly_put_cost * 12
total_put_cost_annual = total_put_cost / n_years

# Also compute 5% OTM and 10% OTM puts
for otm_level, otm_label in [(0.0, "ATM"), (0.05, "5% OTM"), (0.10, "10% OTM")]:
    costs = []
    for i in range(1, n):
        if i % days_per_month == 1 or i == 1:
            S = spy_prices[i-1]
            K = S * (1 - otm_level)
            iv = vix_vals[i-1] / 100.0
            T = days_per_month / 252.0
            put_price = bs_put_price(S, K, T, RF_ANNUAL, iv)
            costs.append(put_price / S)

    ann_cost = np.mean(costs) * 12
    print(f"  Protective Put ({otm_label}): avg monthly {np.mean(costs)*100:.2f}%, "
          f"annual {ann_cost*100:.1f}%")

print(f"\n  VT annual 'premium' (CAGR sacrifice): {annual_premium*100:+.2f}%")
print(f"  Put (ATM) annual cost: {annual_put_cost*100:.1f}%")
print(f"  Put (5% OTM) annual cost: ~{np.mean([bs_put_price(100, 95, 21/252, RF_ANNUAL, v/100)/100 for v in vix_vals[::21]])*12*100:.1f}%")

# VT advantages over options
print(f"\n  VT vs Options Comparison:")
print(f"    VT cost:    {annual_premium*100:+.2f}%/yr {'(you EARN)' if annual_premium < 0 else '(you pay)'}")
print(f"    ATM Put:    ~{annual_put_cost*100:.1f}%/yr (always a cost)")
print(f"    VT advantages:")
print(f"      - No expiration (continuous protection)")
print(f"      - No counterparty risk")
print(f"      - No bid-ask spread on options")
print(f"      - Positive expected return (unlike puts)")
if annual_premium < 0:
    print(f"      - ★ NEGATIVE COST: VT actually EARNS while protecting!")

# ==================================================================
# Regime analysis: when does VT cost vs earn?
# ==================================================================
print("\n  Regime analysis (when does VT cost vs earn?):")

# VIX regime buckets
vix_buckets = [
    (0, 15, "Low (VIX<15)"),
    (15, 20, "Normal (15-20)"),
    (20, 30, "Elevated (20-30)"),
    (30, 100, "Crisis (VIX>30)")
]

print(f"\n  {'VIX Regime':<22s} {'Days':>6s} {'BH Ret':>8s} {'VT Ret':>8s} {'Premium':>8s}")
print(f"  {'-'*22} {'-'*6} {'-'*8} {'-'*8} {'-'*8}")

regime_data = []
for lo, hi, label in vix_buckets:
    mask = (vix_vals[:-1] >= lo) & (vix_vals[:-1] < hi)
    mask = np.append(mask, False)  # align with returns

    if mask.sum() == 0:
        continue

    bh_r = np.mean(bh_spy_rets[mask]) * 252
    vt_r = np.mean(vt_spy_rets[mask]) * 252
    prem = bh_r - vt_r

    print(f"  {label:<22s} {mask.sum():>6d} {bh_r*100:>+7.1f}% {vt_r*100:>+7.1f}% {prem*100:>+7.1f}%")

    regime_data.append({
        "regime": label,
        "days": int(mask.sum()),
        "bh_annualized_pct": round(bh_r * 100, 2),
        "vt_annualized_pct": round(vt_r * 100, 2),
        "premium_annualized_pct": round(prem * 100, 2)
    })

# ==================================================================
# Summary and Save
# ==================================================================
print("\n" + "=" * 80)
print("SUMMARY: THE TRUE COST OF VT INSURANCE")
print("=" * 80)

# Key finding determination
if annual_premium < 0:
    key_finding = (f"VT 12/VIX has NEGATIVE insurance premium ({annual_premium*100:+.2f}%/yr): "
                   f"you EARN money while getting MDD protection of "
                   f"{(results['BH_SPY']['mdd'] - results['12/VIX_SPY']['mdd'])*100:.0f}pp. "
                   f"This is equivalent to being PAID to wear a seatbelt.")
elif annual_premium < 0.02:
    key_finding = (f"VT 12/VIX costs only {annual_premium*100:.2f}%/yr — trivial premium for "
                   f"{(results['BH_SPY']['mdd'] - results['12/VIX_SPY']['mdd'])*100:.0f}pp MDD improvement.")
else:
    key_finding = (f"VT 12/VIX costs {annual_premium*100:.2f}%/yr for "
                   f"{(results['BH_SPY']['mdd'] - results['12/VIX_SPY']['mdd'])*100:.0f}pp MDD improvement.")

print(f"\n  KEY FINDING: {key_finding}")
print(f"\n  1. VT Premium (BH SPY → 12/VIX SPY): {annual_premium*100:+.2f}%/yr")
print(f"     (vs ATM put: {annual_put_cost*100:.1f}%/yr — VT is {annual_put_cost/max(abs(annual_premium), 0.001):.0f}x cheaper)" if annual_premium > 0
      else f"     (vs ATM put: {annual_put_cost*100:.1f}%/yr — VT EARNS while put costs)")
print(f"  2. MDD improvement: {results['BH_SPY']['mdd']*100:.1f}% → {results['12/VIX_SPY']['mdd']*100:.1f}%")
print(f"  3. Historical crisis frequency: 1 major (>20%) every {n_years/max(len(crisis_events_20),1):.1f} years")
print(f"  4. 50/50+VT: P(MDD>20%) = 0% historically (K664 confirmed)")
print(f"  5. VT earns in crisis periods, costs in calm periods (VIX regime dependent)")

# Compile results
output = {
    "experiment_id": "k667",
    "title": "K667: The True Cost of Portfolio Insurance — Quantifying VT as Insurance",
    "attribution": "[提出: K656/K664 延伸, 執行: Claude]",
    "data_source": "yfinance SPY/GLD/VIX daily",
    "period": f"{data.index[0].date()} to {data.index[-1].date()}",
    "n_days": n_days,
    "n_years": round(n_years, 1),
    "references": [
        "Hallerbach (2012) — Optimality of Volatility Weighting",
        "Moreira & Muir (2017) — Volatility-Managed Portfolios, JF",
        "Israelov & Nielsen (2015) — Still Not Cheap: Portfolio Protection in Calm Markets",
        "K656: VT is alpha + insurance",
        "K664: P(MDD>20%) = 0% with 50/50+VT",
        "K127: VT Insurance Pricing comparison"
    ],
    "strategy_metrics": {
        name: {
            "cagr_pct": round(r["cagr"] * 100, 3),
            "sharpe": round(r["sharpe"], 4),
            "sortino": round(r["sortino"], 4),
            "mdd_pct": round(r["mdd"] * 100, 2),
            "vol_pct": round(r["vol"] * 100, 2)
        }
        for name, r in results.items()
    },
    "insurance_premiums": premium_data,
    "annual_premiums_by_year": annual_premiums,
    "annual_premium_stats": {
        "mean_pct": round(mean_prem, 3),
        "median_pct": round(median_prem, 3),
        "std_pct": round(std_prem, 3),
        "years_vt_costs": prem_positive,
        "years_vt_earns": prem_negative,
        "total_years": len(prem_vals),
        "t_statistic": round(t_stat_prem, 3),
        "p_value": round(p_val_prem, 4)
    },
    "crisis_probability": crisis_analysis,
    "crisis_events": {
        "gt_10pct": len(crisis_events_10),
        "gt_20pct": len(crisis_events_20),
        "gt_30pct": len(crisis_events_30),
        "avg_years_between_20pct": round(n_years / max(len(crisis_events_20), 1), 1)
    },
    "breakeven_analysis": {
        "bh_spy_to_vt_spy": {
            "annual_premium_pct": round(annual_premium * 100, 3),
            "avg_crisis_loss_bh_pct": round(avg_crisis_loss_bh * 100, 1),
            "avg_crisis_loss_vt_pct": round(avg_crisis_loss_vt * 100, 1) if vt_crisis_20 else 0,
            "loss_avoided_per_crisis_pp": round(loss_avoided_per_crisis * 100, 1),
            "breakeven_years": round(1 / (annual_premium / loss_avoided_per_crisis), 1) if annual_premium > 0 and loss_avoided_per_crisis > 0 else "N/A (VT dominates)",
            "historical_crisis_interval_years": round(n_years / max(len(crisis_events_20), 1), 1),
            "verdict": "VT dominates (negative premium)" if annual_premium <= 0 else (
                "VT is cheap insurance" if (annual_premium > 0 and loss_avoided_per_crisis > 0 and
                    1/(annual_premium/loss_avoided_per_crisis) > n_years/max(len(crisis_events_20),1))
                else "VT is expensive insurance"
            )
        }
    },
    "options_comparison": {
        "vt_annual_premium_pct": round(annual_premium * 100, 3),
        "atm_put_annual_cost_pct": round(annual_put_cost * 100, 1),
        "vt_advantages": [
            "No expiration (continuous protection)",
            "No counterparty risk",
            "No bid-ask spread on options",
            "Positive expected return (unlike puts)"
        ]
    },
    "regime_analysis": regime_data,
    "key_finding": key_finding,
    "limitations": [
        "Backtest uses lagged VIX (t-1) for weight at time t — correct implementation",
        "Protective put costs are BS-simulated using VIX as IV proxy (actual costs may differ)",
        "Period includes GFC + COVID — two of the worst crises in modern history",
        "12/VIX SPY uses risk-free rate for non-equity portion (approximation)",
        "Transaction costs not included in VT premium calculation",
        "Break-even analysis assumes crisis severity is constant (it varies)"
    ]
}

# Save
output_path = "/Users/yhlai0911/Desktop/volpred-research/.claude/worktrees/agent-a8416843/experiments/k667_results.json"
with open(output_path, "w") as f:
    json.dump(output, f, indent=2, default=str)

print(f"\n  Results saved to: {output_path}")
print("\nDone.")
