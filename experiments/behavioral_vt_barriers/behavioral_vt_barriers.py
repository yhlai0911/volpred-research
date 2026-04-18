"""
K118: Behavioral Finance — Why Investors Don't Use VT
=====================================================
[提出: Claude, 執行: Claude]

Research Question:
  VT demonstrably reduces MDD (p=0.0004, K14: 253/253 starting dates win).
  Yet real-world VT adoption is ~5%. Why?

  Hypothesis: Behavioral biases systematically penalize VT in the investor's
  subjective experience, making it "feel" worse than B&H despite being
  objectively superior on risk-adjusted metrics.

Behavioral Biases Tested:
  1. Loss Aversion (Kahneman-Tversky, 1979): λ=2.25 asymmetric utility
  2. Regret Aversion: Tracking error vs B&H creates ongoing pain
  3. Mental Accounting (Thaler, 1985): Insurance premium framed as certain loss
  4. Disposition Effect (Shefrin-Statman, 1985): VT forces selling during losses
  5. Myopic Loss Aversion (Benartzi-Thaler, 1995): Evaluation frequency matters

Data: SPY 2007-2024, 12/VIX VT strategy (lagged weights)
"""

import sys
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from datetime import datetime
import json
import os

np.random.seed(42)

WORKTREE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(WORKTREE)

# ============================================================
# 1. Download and prepare historical data
# ============================================================
print("=" * 72)
print("K118: Behavioral Finance — Why Investors Don't Use VT")
print("=" * 72)
print(f"\nStarted: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

print("\n[1/7] Downloading SPY and VIX data...")
spy_raw = yf.download("SPY", start="2006-01-01", end="2026-12-31",
                       progress=False, auto_adjust=False)
vix_raw = yf.download("^VIX", start="2006-01-01", end="2026-12-31",
                       progress=False, auto_adjust=False)

# Flatten MultiIndex if needed
if isinstance(spy_raw.columns, pd.MultiIndex):
    spy_raw.columns = spy_raw.columns.get_level_values(0)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)

spy = spy_raw[["Close"]].rename(columns={"Close": "spy_close"})
vix = vix_raw[["Close"]].rename(columns={"Close": "vix_close"})

data = spy.join(vix, how="inner").dropna()
data["returns"] = data["spy_close"].pct_change()  # simple returns for wealth
data["log_returns"] = np.log(data["spy_close"] / data["spy_close"].shift(1))
data = data.dropna()

# Focus on 2007-2024
data = data.loc["2007-01-01":"2024-12-31"]
print(f"  Data range: {data.index[0].date()} to {data.index[-1].date()}")
print(f"  Trading days: {len(data)}")

returns = data["returns"].values
vix_levels = data["vix_close"].values
dates = data.index

# ============================================================
# 2. Construct VT strategy (12/VIX, lagged weights)
# ============================================================
print("\n[2/7] Constructing 12/VIX VT strategy...")

# Lagged weight: use yesterday's VIX to determine today's allocation
vt_weights = np.minimum(12.0 / vix_levels, 1.5)
vt_weights_lagged = np.roll(vt_weights, 1)
vt_weights_lagged[0] = 1.0  # first day: full allocation

# VT daily returns
vt_returns = vt_weights_lagged * returns
# B&H daily returns = returns (100% allocation)
bh_returns = returns

# Cumulative wealth
vt_wealth = np.cumprod(1 + vt_returns)
bh_wealth = np.cumprod(1 + bh_returns)

# Annualized stats
n_years = len(returns) / 252
vt_ann_ret = (vt_wealth[-1] ** (1 / n_years)) - 1
bh_ann_ret = (bh_wealth[-1] ** (1 / n_years)) - 1
vt_ann_vol = np.std(vt_returns) * np.sqrt(252)
bh_ann_vol = np.std(bh_returns) * np.sqrt(252)
vt_sharpe = vt_ann_ret / vt_ann_vol
bh_sharpe = bh_ann_ret / bh_ann_vol

# Max drawdown
def max_drawdown(wealth):
    peak = np.maximum.accumulate(wealth)
    dd = (wealth - peak) / peak
    return np.min(dd)

vt_mdd = max_drawdown(vt_wealth)
bh_mdd = max_drawdown(bh_wealth)

print(f"\n  Strategy Summary (2007-2024):")
print(f"  {'Metric':<25} {'VT (12/VIX)':<18} {'B&H':<18}")
print(f"  {'-'*60}")
print(f"  {'Ann. Return':<25} {vt_ann_ret:.3%}{'':<12} {bh_ann_ret:.3%}")
print(f"  {'Ann. Volatility':<25} {vt_ann_vol:.3%}{'':<12} {bh_ann_vol:.3%}")
print(f"  {'Sharpe Ratio':<25} {vt_sharpe:.3f}{'':<15} {bh_sharpe:.3f}")
print(f"  {'Max Drawdown':<25} {vt_mdd:.3%}{'':<12} {bh_mdd:.3%}")

# ============================================================
# 3. BIAS 1: Loss Aversion (Prospect Theory)
# ============================================================
print("\n" + "=" * 72)
print("[3/7] BIAS 1: Loss Aversion (Kahneman-Tversky Prospect Theory)")
print("=" * 72)

def prospect_value(x, alpha=0.88, beta=0.88, lam=2.25):
    """
    Prospect theory value function (Tversky-Kahneman 1992).
    v(x) = x^α          if x >= 0
    v(x) = -λ(-x)^β     if x < 0
    """
    if x >= 0:
        return x ** alpha
    else:
        return -lam * ((-x) ** beta)

prospect_value_v = np.vectorize(prospect_value)

# Monthly aggregation for realistic evaluation frequency
vt_monthly = pd.Series(vt_returns, index=dates).resample("ME").apply(
    lambda x: np.prod(1 + x) - 1
)
bh_monthly = pd.Series(bh_returns, index=dates).resample("ME").apply(
    lambda x: np.prod(1 + x) - 1
)

# Daily prospect utility
vt_daily_ptu = prospect_value_v(vt_returns)
bh_daily_ptu = prospect_value_v(bh_returns)
vt_daily_ptu_mean = np.mean(vt_daily_ptu)
bh_daily_ptu_mean = np.mean(bh_daily_ptu)

# Monthly prospect utility
vt_monthly_ptu = prospect_value_v(vt_monthly.values)
bh_monthly_ptu = prospect_value_v(bh_monthly.values)
vt_monthly_ptu_mean = np.mean(vt_monthly_ptu)
bh_monthly_ptu_mean = np.mean(bh_monthly_ptu)

# Annual prospect utility
vt_annual = pd.Series(vt_returns, index=dates).resample("YE").apply(
    lambda x: np.prod(1 + x) - 1
)
bh_annual = pd.Series(bh_returns, index=dates).resample("YE").apply(
    lambda x: np.prod(1 + x) - 1
)
vt_annual_ptu = prospect_value_v(vt_annual.values)
bh_annual_ptu = prospect_value_v(bh_annual.values)
vt_annual_ptu_mean = np.mean(vt_annual_ptu)
bh_annual_ptu_mean = np.mean(bh_annual_ptu)

# Win rates at different frequencies
daily_vt_wins = np.mean(vt_returns > bh_returns)
monthly_vt_wins = np.mean(vt_monthly.values > bh_monthly.values)
annual_vt_wins = np.mean(vt_annual.values > bh_annual.values)

# Proportion of negative months
vt_neg_months = np.mean(vt_monthly.values < 0)
bh_neg_months = np.mean(bh_monthly.values < 0)

print(f"\n  Prospect Theory Value (λ=2.25, α=β=0.88):")
print(f"  {'Frequency':<15} {'VT PTU':<18} {'B&H PTU':<18} {'VT/B&H Ratio':<15}")
print(f"  {'-'*65}")
print(f"  {'Daily':<15} {vt_daily_ptu_mean:.6f}{'':<10} {bh_daily_ptu_mean:.6f}{'':<10} {vt_daily_ptu_mean/bh_daily_ptu_mean:.3f}")
print(f"  {'Monthly':<15} {vt_monthly_ptu_mean:.6f}{'':<10} {bh_monthly_ptu_mean:.6f}{'':<10} {vt_monthly_ptu_mean/bh_monthly_ptu_mean:.3f}")
print(f"  {'Annual':<15} {vt_annual_ptu_mean:.6f}{'':<10} {bh_annual_ptu_mean:.6f}{'':<10} {vt_annual_ptu_mean/bh_annual_ptu_mean:.3f}")

print(f"\n  VT Win Rate vs B&H (days/months/years VT outperforms):")
print(f"  {'Daily':<15} {daily_vt_wins:.1%}")
print(f"  {'Monthly':<15} {monthly_vt_wins:.1%}")
print(f"  {'Annual':<15} {annual_vt_wins:.1%}")

print(f"\n  Negative Return Frequency:")
print(f"  {'VT neg months':<25} {vt_neg_months:.1%}")
print(f"  {'B&H neg months':<25} {bh_neg_months:.1%}")

# Myopic Loss Aversion (Benartzi-Thaler 1995)
# Key insight: shorter evaluation periods → more loss observations → more pain
print(f"\n  Myopic Loss Aversion Analysis:")
print(f"  {'Eval Period':<15} {'VT Loss Freq':<18} {'B&H Loss Freq':<18} {'VT Disadvantage':<18}")
print(f"  {'-'*70}")
for freq, label in [("D", "Daily"), ("W", "Weekly"), ("ME", "Monthly"), ("QE", "Quarterly"), ("YE", "Annual")]:
    vt_freq = pd.Series(vt_returns, index=dates).resample(freq).apply(
        lambda x: np.prod(1 + x) - 1
    )
    bh_freq = pd.Series(bh_returns, index=dates).resample(freq).apply(
        lambda x: np.prod(1 + x) - 1
    )
    vt_loss = np.mean(vt_freq.values < 0)
    bh_loss = np.mean(bh_freq.values < 0)
    diff = vt_loss - bh_loss
    print(f"  {label:<15} {vt_loss:.1%}{'':<12} {bh_loss:.1%}{'':<12} {diff:+.1%}")


# ============================================================
# 4. BIAS 2: Regret Aversion
# ============================================================
print("\n" + "=" * 72)
print("[4/7] BIAS 2: Regret Aversion (Tracking Error Pain)")
print("=" * 72)

# Relative performance: VT - B&H
relative_monthly = vt_monthly.values - bh_monthly.values
regret_months = relative_monthly < 0  # months where VT underperforms
regret_freq = np.mean(regret_months)
regret_magnitude = relative_monthly[regret_months]  # underperformance amounts
joy_months = relative_monthly >= 0
joy_magnitude = relative_monthly[joy_months]

print(f"\n  Monthly Relative Performance (VT minus B&H):")
print(f"  {'Regret frequency (VT < B&H)':<40} {regret_freq:.1%}")
print(f"  {'Joy frequency (VT >= B&H)':<40} {1-regret_freq:.1%}")
print(f"  {'Mean regret magnitude':<40} {np.mean(regret_magnitude):.3%}")
print(f"  {'Mean joy magnitude':<40} {np.mean(joy_magnitude):.3%}")
print(f"  {'Median regret':<40} {np.median(regret_magnitude):.3%}")
print(f"  {'Max regret (worst month)':<40} {np.min(relative_monthly):.3%}")
print(f"  {'Max joy (best month)':<40} {np.max(relative_monthly):.3%}")

# Rolling 12-month tracking error
relative_daily = pd.Series(vt_returns - bh_returns, index=dates)
rolling_te = relative_daily.rolling(252).std() * np.sqrt(252)
rolling_te = rolling_te.dropna()

print(f"\n  Rolling 12-Month Tracking Error vs B&H:")
print(f"  {'Mean TE':<40} {rolling_te.mean():.2%}")
print(f"  {'Max TE':<40} {rolling_te.max():.2%}")
print(f"  {'Min TE':<40} {rolling_te.min():.2%}")

# Regret asymmetry: prospect theory applied to relative returns
regret_ptu = prospect_value_v(relative_monthly)
mean_regret_ptu = np.mean(regret_ptu)
print(f"\n  Prospect Theory Value of Relative Performance:")
print(f"  {'Mean PT(VT-B&H) monthly':<40} {mean_regret_ptu:.6f}")
print(f"  (Negative = net subjective pain from tracking B&H)")

# Cumulative regret periods
cumrel = np.cumsum(relative_monthly)
underwater = cumrel < 0  # "underwater" relative to B&H
max_underwater_streak = 0
current_streak = 0
for u in underwater:
    if u:
        current_streak += 1
        max_underwater_streak = max(max_underwater_streak, current_streak)
    else:
        current_streak = 0

print(f"\n  Cumulative Underperformance Streaks:")
print(f"  {'% months cum. trailing B&H':<40} {np.mean(underwater):.1%}")
print(f"  {'Longest trailing streak':<40} {max_underwater_streak} months")

# ============================================================
# 5. BIAS 3: Mental Accounting — Insurance Premium Framing
# ============================================================
print("\n" + "=" * 72)
print("[5/7] BIAS 3: Mental Accounting (Insurance Premium Framing)")
print("=" * 72)

# Annual VT vs B&H return difference = "insurance premium"
annual_premium = vt_annual.values - bh_annual.values
premium_positive = annual_premium > 0  # years where VT beat B&H (crisis years)
premium_negative = annual_premium < 0  # years where VT cost return (normal years)

print(f"\n  Annual 'Insurance Premium' (VT - B&H annual return):")
print(f"  {'Mean annual premium':<40} {np.mean(annual_premium):.2%}")
print(f"  {'Median annual premium':<40} {np.median(annual_premium):.2%}")
print(f"  {'Years premium > 0 (VT wins)':<40} {np.sum(premium_positive)}/{len(annual_premium)}")
print(f"  {'Years premium < 0 (B&H wins)':<40} {np.sum(premium_negative)}/{len(annual_premium)}")

print(f"\n  Year-by-Year Breakdown:")
print(f"  {'Year':<8} {'VT Return':<14} {'B&H Return':<14} {'Premium':<14} {'Frame':<20}")
print(f"  {'-'*70}")
for i, year in enumerate(vt_annual.index):
    yr = year.year
    vt_r = vt_annual.values[i]
    bh_r = bh_annual.values[i]
    prem = annual_premium[i]
    if prem < -0.02:
        frame = "COST (drag)"
    elif prem > 0.02:
        frame = "PAYOFF (protection)"
    else:
        frame = "~neutral"
    print(f"  {yr:<8} {vt_r:>+.2%}{'':<7} {bh_r:>+.2%}{'':<7} {prem:>+.2%}{'':<7} {frame}")

# Mental accounting amplification
# Thaler's mental accounting: people evaluate losses more acutely
# "Certain loss" (annual premium) vs "probabilistic gain" (crisis protection)
# Compute: how often is the premium negative, and by how much?
drag_years = annual_premium[annual_premium < 0]
payoff_years = annual_premium[annual_premium > 0]

mean_drag = np.mean(drag_years) if len(drag_years) > 0 else 0
mean_payoff = np.mean(payoff_years) if len(payoff_years) > 0 else 0

# Under mental accounting: the drag is "certain" (happens most years)
# but the payoff is "uncertain" (only during crises)
# Subjective amplification: λ * |drag| / |payoff| vs actual |drag|/|payoff|
if mean_payoff != 0:
    actual_ratio = abs(mean_drag) / abs(mean_payoff)
    subjective_ratio = 2.25 * actual_ratio  # loss aversion amplification
else:
    actual_ratio = float('inf')
    subjective_ratio = float('inf')

print(f"\n  Mental Accounting Analysis:")
print(f"  {'Mean annual drag (normal years)':<40} {mean_drag:.2%}")
print(f"  {'Mean annual payoff (crisis years)':<40} {mean_payoff:+.2%}")
print(f"  {'Objective |drag|/|payoff| ratio':<40} {actual_ratio:.2f}")
print(f"  {'Subjective ratio (×λ=2.25)':<40} {subjective_ratio:.2f}")
print(f"  {'Amplification factor':<40} {subjective_ratio/actual_ratio if actual_ratio > 0 else 'N/A':.1f}x")

# Narrow framing: each month evaluated independently
# vs broad framing: total wealth at end
print(f"\n  Narrow vs Broad Framing:")
print(f"  {'Narrow (monthly avg VT-B&H PTU)':<40} {mean_regret_ptu:.6f}")
narrow_total = np.sum(regret_ptu)
broad_total_wealth_diff = vt_wealth[-1] - bh_wealth[-1]
broad_ptu = prospect_value(broad_total_wealth_diff / bh_wealth[-1])
print(f"  {'Narrow (sum monthly PTU)':<40} {narrow_total:.4f}")
print(f"  {'Broad (PTU of total wealth diff)':<40} {broad_ptu:.6f}")
print(f"  {'Total wealth: VT':<40} ${vt_wealth[-1]:.2f} (from $1)")
print(f"  {'Total wealth: B&H':<40} ${bh_wealth[-1]:.2f} (from $1)")

# ============================================================
# 6. BIAS 4: Disposition Effect — Forced Selling at Losses
# ============================================================
print("\n" + "=" * 72)
print("[6/7] BIAS 4: Disposition Effect (Forced Selling During Drawdowns)")
print("=" * 72)

# When SPY is in drawdown, does VT reduce allocation? (i.e., sell)
spy_peak = np.maximum.accumulate(data["spy_close"].values)
spy_dd = (data["spy_close"].values - spy_peak) / spy_peak

# Weight changes
weight_changes = np.diff(vt_weights_lagged)
# Note: negative weight_change = selling
# Identify sell events during drawdowns
in_drawdown = spy_dd[1:] < -0.05  # during 5%+ drawdowns
sell_events = weight_changes < -0.01  # meaningful selling (weight drop > 1%)

# Selling during drawdowns
sell_in_dd = np.logical_and(sell_events, in_drawdown)
sell_not_dd = np.logical_and(sell_events, ~in_drawdown)

total_dd_days = np.sum(in_drawdown)
total_non_dd_days = np.sum(~in_drawdown)

sell_in_dd_rate = np.sum(sell_in_dd) / total_dd_days if total_dd_days > 0 else 0
sell_not_dd_rate = np.sum(sell_not_dd) / total_non_dd_days if total_non_dd_days > 0 else 0

print(f"\n  VT Forced Selling Behavior:")
print(f"  {'Days in 5%+ drawdown':<40} {total_dd_days} ({total_dd_days/len(in_drawdown):.1%})")
print(f"  {'Sell events during drawdowns':<40} {np.sum(sell_in_dd)} ({sell_in_dd_rate:.1%} of DD days)")
print(f"  {'Sell events outside drawdowns':<40} {np.sum(sell_not_dd)} ({sell_not_dd_rate:.1%} of non-DD days)")
if sell_not_dd_rate > 0:
    sell_asymmetry = sell_in_dd_rate / sell_not_dd_rate
else:
    sell_asymmetry = float('inf')
print(f"  {'Sell asymmetry (DD vs non-DD)':<40} {sell_asymmetry:.1f}x")

# During major crises
crises = {
    "GFC (2008-09 to 2009-03)": ("2008-09-01", "2009-03-31"),
    "COVID (2020-02 to 2020-03)": ("2020-02-15", "2020-03-31"),
    "2022 Bear (2022-01 to 2022-10)": ("2022-01-01", "2022-10-31"),
}

print(f"\n  VT Behavior During Major Crises:")
print(f"  {'Crisis':<35} {'Avg Weight':<14} {'Min Weight':<14} {'Days Selling':<14}")
print(f"  {'-'*75}")
for name, (start, end) in crises.items():
    mask = (dates >= start) & (dates <= end)
    if np.sum(mask) == 0:
        continue
    crisis_weights = vt_weights_lagged[mask]
    crisis_wchg = np.diff(crisis_weights)
    crisis_sell_pct = np.mean(crisis_wchg < -0.01) if len(crisis_wchg) > 0 else 0
    print(f"  {name:<35} {np.mean(crisis_weights):.2f}{'':<8} {np.min(crisis_weights):.2f}{'':<8} {crisis_sell_pct:.1%}")

# Psychological cost: selling at lows that recover
# Count how many VT sell days are followed by positive returns in next 5/20 days
sell_indices = np.where(sell_in_dd)[0]
recovery_5d = 0
recovery_20d = 0
for idx in sell_indices:
    # returns array is aligned with weight_changes (shifted by 1)
    actual_idx = idx + 1  # align with returns
    if actual_idx + 5 < len(returns):
        fwd_5d = np.sum(returns[actual_idx:actual_idx+5])
        if fwd_5d > 0:
            recovery_5d += 1
    if actual_idx + 20 < len(returns):
        fwd_20d = np.sum(returns[actual_idx:actual_idx+20])
        if fwd_20d > 0:
            recovery_20d += 1

total_valid_5d = np.sum(sell_indices + 1 + 5 < len(returns))
total_valid_20d = np.sum(sell_indices + 1 + 20 < len(returns))

print(f"\n  'Selling at the Bottom' Regret:")
print(f"  {'VT sells during DD, followed by 5d recovery':<50} {recovery_5d}/{total_valid_5d} ({recovery_5d/total_valid_5d:.1%})" if total_valid_5d > 0 else "  N/A")
print(f"  {'VT sells during DD, followed by 20d recovery':<50} {recovery_20d}/{total_valid_20d} ({recovery_20d/total_valid_20d:.1%})" if total_valid_20d > 0 else "  N/A")
print(f"  (These are the events that trigger 'I sold at the bottom!' regret)")

# ============================================================
# 7. BIAS 5: Complexity Aversion & Status Quo Bias
# ============================================================
print("\n" + "=" * 72)
print("[7/7] BIAS 5: Complexity Aversion & Status Quo Bias")
print("=" * 72)

# Quantify the complexity tax
# B&H: 0 decisions per year
# 12/VIX monthly: 12 decisions per year
# 12/VIX daily: 252 decisions per year

# Weight change distribution for monthly rebalance
monthly_weights = pd.Series(vt_weights_lagged, index=dates).resample("ME").last()
monthly_wchg = monthly_weights.diff().dropna()
monthly_turnover = monthly_wchg.abs().sum() / n_years

daily_wchg = pd.Series(np.abs(np.diff(vt_weights_lagged)), index=dates[1:])
daily_turnover = daily_wchg.sum() / n_years

print(f"\n  Complexity Tax:")
print(f"  {'Strategy':<30} {'Decisions/Year':<18} {'Turnover/Year':<18}")
print(f"  {'-'*65}")
print(f"  {'B&H':<30} {'0':<18} {'0%':<18}")
print(f"  {'12/VIX (monthly rebal)':<30} {'12':<18} {monthly_turnover:.2f}")
print(f"  {'12/VIX (daily rebal)':<30} {'252':<18} {daily_turnover:.2f}")

# Status quo bias: switching from B&H to VT requires action
# Omission bias: if you do nothing (B&H) and lose money, it's "fate"
# If you actively manage (VT) and lose money, it's "your fault"
print(f"\n  Status Quo Bias Framework:")
print(f"  B&H: {'Do nothing → losses attributed to market':}")
print(f"  VT:  {'Active decisions → losses attributed to investor':}")
print(f"  {'Monthly VT decisions per year':<40} 12")
print(f"  {'Annual regret-triggering events':<40} {np.sum(relative_monthly < -0.02)}/{len(relative_monthly)} months")

# ============================================================
# 8. Composite Analysis: Which Bias Is Strongest?
# ============================================================
print("\n" + "=" * 72)
print("COMPOSITE ANALYSIS: Ranking Behavioral Barriers")
print("=" * 72)

# Score each bias by quantitative impact
# We'll use a normalized "barrier score" from 0-100

# Bias 1: Loss Aversion
# Metric: How much does PT utility penalize VT vs B&H?
if bh_monthly_ptu_mean != 0:
    la_penalty = (bh_monthly_ptu_mean - vt_monthly_ptu_mean) / abs(bh_monthly_ptu_mean)
else:
    la_penalty = 0

# Bias 2: Regret Aversion
# Metric: Regret frequency × mean regret magnitude
regret_score_raw = regret_freq * abs(np.mean(regret_magnitude))

# Bias 3: Mental Accounting
# Metric: Subjective amplification of insurance premium
ma_score_raw = subjective_ratio  # higher = worse framing

# Bias 4: Disposition Effect
# Metric: Sell asymmetry × recovery rate
if total_valid_20d > 0:
    disp_score_raw = sell_asymmetry * (recovery_20d / total_valid_20d)
else:
    disp_score_raw = 0

# Bias 5: Complexity / Status Quo
# Metric: Decisions per year × regret events
complexity_score_raw = 12 * (np.sum(relative_monthly < -0.02) / len(relative_monthly))

# Normalize to 0-100 scale
raw_scores = {
    "Loss Aversion (PT)": la_penalty * 100,
    "Regret Aversion": regret_score_raw * 1000,  # scale up
    "Mental Accounting": min(ma_score_raw * 10, 100),  # cap
    "Disposition Effect": disp_score_raw * 50,
    "Complexity/Status Quo": complexity_score_raw * 100,
}

# Rescale so max = 100
max_score = max(raw_scores.values()) if max(raw_scores.values()) > 0 else 1
barrier_scores = {k: v / max_score * 100 for k, v in raw_scores.items()}

print(f"\n  {'Behavioral Bias':<30} {'Barrier Score':<18} {'Key Metric':<35}")
print(f"  {'-'*80}")
print(f"  {'Loss Aversion (PT)':<30} {barrier_scores['Loss Aversion (PT)']:>6.1f}{'':<12} PTU penalty: {la_penalty:.3f}")
print(f"  {'Regret Aversion':<30} {barrier_scores['Regret Aversion']:>6.1f}{'':<12} Freq×Mag: {regret_score_raw:.4f}")
print(f"  {'Mental Accounting':<30} {barrier_scores['Mental Accounting']:>6.1f}{'':<12} Subj. ratio: {subjective_ratio:.2f}")
print(f"  {'Disposition Effect':<30} {barrier_scores['Disposition Effect']:>6.1f}{'':<12} Sell×Recovery: {disp_score_raw:.2f}")
print(f"  {'Complexity/Status Quo':<30} {barrier_scores['Complexity/Status Quo']:>6.1f}{'':<12} Decisions×Regret: {complexity_score_raw:.2f}")

# Sort by score
ranked = sorted(barrier_scores.items(), key=lambda x: x[1], reverse=True)
print(f"\n  Ranking (strongest barrier first):")
for i, (bias, score) in enumerate(ranked, 1):
    bar = "█" * int(score / 2) + "░" * (50 - int(score / 2))
    print(f"  {i}. {bias:<30} {bar} {score:.1f}")

# ============================================================
# 9. Myopic Loss Aversion Deep Dive (Benartzi-Thaler 1995)
# ============================================================
print("\n" + "=" * 72)
print("DEEP DIVE: Myopic Loss Aversion by Evaluation Frequency")
print("=" * 72)

print(f"\n  Prospect Theory Utility at Different Evaluation Frequencies:")
print(f"  {'Frequency':<15} {'VT PTU':<18} {'B&H PTU':<18} {'VT Preferred?':<18}")
print(f"  {'-'*65}")

eval_freqs = [
    ("Daily", "D"),
    ("Weekly", "W"),
    ("Monthly", "ME"),
    ("Quarterly", "QE"),
    ("Annual", "YE"),
    ("3-Year", "3YE"),
    ("5-Year", "5YE"),
]

crossover_found = None
for label, freq in eval_freqs:
    try:
        vt_f = pd.Series(vt_returns, index=dates).resample(freq).apply(
            lambda x: np.prod(1 + x) - 1
        )
        bh_f = pd.Series(bh_returns, index=dates).resample(freq).apply(
            lambda x: np.prod(1 + x) - 1
        )
        if len(vt_f) < 2:
            continue
        vt_ptu = np.mean(prospect_value_v(vt_f.values))
        bh_ptu = np.mean(prospect_value_v(bh_f.values))
        preferred = "YES ✓" if vt_ptu >= bh_ptu else "NO ✗"
        if vt_ptu >= bh_ptu and crossover_found is None:
            crossover_found = label
        print(f"  {label:<15} {vt_ptu:.6f}{'':<10} {bh_ptu:.6f}{'':<10} {preferred}")
    except Exception:
        pass

if crossover_found:
    print(f"\n  → VT becomes preferred at {crossover_found} evaluation frequency!")
    print(f"    Implication: Investors who check less often would prefer VT.")
    print(f"    This is Benartzi-Thaler's myopic loss aversion in action.")
else:
    print(f"\n  → VT is never preferred under prospect theory at any frequency.")
    print(f"    The insurance premium is too persistent.")

# ============================================================
# 10. Summary and Save Results
# ============================================================
print("\n" + "=" * 72)
print("FINAL SUMMARY")
print("=" * 72)

print(f"""
  K118 Findings:

  1. LOSS AVERSION: VT loses to B&H {1-monthly_vt_wins:.0%} of months, but its
     losses are smaller. Under prospect theory (λ=2.25), B&H has
     {'higher' if bh_monthly_ptu_mean > vt_monthly_ptu_mean else 'lower'} subjective utility at monthly evaluation.

  2. REGRET AVERSION: VT underperforms B&H {regret_freq:.0%} of months.
     Mean underperformance = {np.mean(regret_magnitude):.2%}/month.
     Longest cumulative trailing streak: {max_underwater_streak} months.

  3. MENTAL ACCOUNTING: The ~{abs(np.mean(annual_premium)):.1%}/yr insurance premium
     is experienced as a "certain loss" every year, while crisis protection
     is a rare "uncertain gain." Subjective amplification: {subjective_ratio:.1f}x.

  4. DISPOSITION EFFECT: VT sells {sell_asymmetry:.1f}x more during drawdowns.
     {recovery_20d}/{total_valid_20d} ({recovery_20d/total_valid_20d:.0%}) of these sells are followed by 20-day recovery,
     triggering "sold at the bottom" regret.

  5. COMPLEXITY: VT requires 12 decisions/year (monthly rebal).
     {np.sum(relative_monthly < -0.02)}/{len(relative_monthly)} months trigger "I did something and it hurt" regret.

  STRONGEST BARRIER: {ranked[0][0]} (score: {ranked[0][1]:.0f}/100)
  SECOND BARRIER:    {ranked[1][0]} (score: {ranked[1][1]:.0f}/100)
  THIRD BARRIER:     {ranked[2][0]} (score: {ranked[2][1]:.0f}/100)

  KEY INSIGHT: VT is objectively superior (Sharpe {vt_sharpe:.2f} vs {bh_sharpe:.2f},
  MDD {vt_mdd:.0%} vs {bh_mdd:.0%}), but behaviorally inferior because it generates
  frequent small losses (regret) while its benefits are rare and large (crisis).
  This is the exact opposite of what prospect theory rewards.
""")

# Save results
results = {
    "experiment": "K118",
    "title": "Behavioral Finance — Why Investors Don't Use VT",
    "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "data": {
        "period": f"{data.index[0].date()} to {data.index[-1].date()}",
        "trading_days": len(data),
    },
    "strategy_stats": {
        "vt_ann_return": float(vt_ann_ret),
        "bh_ann_return": float(bh_ann_ret),
        "vt_sharpe": float(vt_sharpe),
        "bh_sharpe": float(bh_sharpe),
        "vt_mdd": float(vt_mdd),
        "bh_mdd": float(bh_mdd),
    },
    "bias_1_loss_aversion": {
        "daily_vt_ptu": float(vt_daily_ptu_mean),
        "daily_bh_ptu": float(bh_daily_ptu_mean),
        "monthly_vt_ptu": float(vt_monthly_ptu_mean),
        "monthly_bh_ptu": float(bh_monthly_ptu_mean),
        "annual_vt_ptu": float(vt_annual_ptu_mean),
        "annual_bh_ptu": float(bh_annual_ptu_mean),
        "monthly_vt_win_rate": float(monthly_vt_wins),
        "annual_vt_win_rate": float(annual_vt_wins),
        "pt_penalty": float(la_penalty),
    },
    "bias_2_regret_aversion": {
        "regret_frequency": float(regret_freq),
        "mean_regret_magnitude": float(np.mean(regret_magnitude)),
        "max_regret": float(np.min(relative_monthly)),
        "max_underwater_streak_months": int(max_underwater_streak),
        "pct_months_cum_trailing": float(np.mean(underwater)),
        "mean_tracking_error_ann": float(rolling_te.mean()),
    },
    "bias_3_mental_accounting": {
        "mean_annual_premium": float(np.mean(annual_premium)),
        "median_annual_premium": float(np.median(annual_premium)),
        "years_vt_wins": int(np.sum(premium_positive)),
        "years_bh_wins": int(np.sum(premium_negative)),
        "total_years": int(len(annual_premium)),
        "objective_drag_payoff_ratio": float(actual_ratio),
        "subjective_ratio_lambda_225": float(subjective_ratio),
    },
    "bias_4_disposition_effect": {
        "drawdown_days": int(total_dd_days),
        "sell_events_in_drawdown": int(np.sum(sell_in_dd)),
        "sell_rate_in_drawdown": float(sell_in_dd_rate),
        "sell_rate_outside_drawdown": float(sell_not_dd_rate),
        "sell_asymmetry": float(sell_asymmetry),
        "sold_then_5d_recovery_pct": float(recovery_5d / total_valid_5d) if total_valid_5d > 0 else None,
        "sold_then_20d_recovery_pct": float(recovery_20d / total_valid_20d) if total_valid_20d > 0 else None,
    },
    "bias_5_complexity": {
        "monthly_decisions_per_year": 12,
        "monthly_turnover": float(monthly_turnover),
        "daily_turnover": float(daily_turnover),
        "regret_triggering_months_pct": float(np.sum(relative_monthly < -0.02) / len(relative_monthly)),
    },
    "barrier_scores": {k: float(v) for k, v in barrier_scores.items()},
    "barrier_ranking": [{"rank": i+1, "bias": k, "score": float(v)} for i, (k, v) in enumerate(ranked)],
    "crossover_frequency": crossover_found,
    "conclusion": (
        f"Strongest behavioral barrier to VT adoption: {ranked[0][0]}. "
        f"VT underperforms B&H {regret_freq:.0%} of months, creating persistent regret. "
        f"Insurance premium of ~{abs(np.mean(annual_premium)):.1%}/yr is framed as certain loss. "
        f"VT forces selling {sell_asymmetry:.1f}x more during drawdowns, triggering disposition effect. "
        f"Myopic evaluation at monthly frequency amplifies all biases. "
        f"{'VT becomes preferred at ' + crossover_found + ' evaluation.' if crossover_found else 'VT never preferred under PT.'}"
    ),
}

output_path = os.path.join(WORKTREE, "behavioral_vt_results.json")
with open(output_path, "w") as f:
    json.dump(results, f, indent=2, default=str)

print(f"\nResults saved to: {output_path}")
print(f"Completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
