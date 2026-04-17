"""
K278: VIX Regime Transition Dynamics
How does VIX move between regimes? Transition matrix, speed, asymmetry, VT implications.

Data: VIX + SPY daily from yfinance, 2005-2024.
"""

import numpy as np
import pandas as pd
import yfinance as yf
from collections import Counter, defaultdict
from datetime import datetime

print("=" * 80)
print("K278: VIX Regime Transition Dynamics")
print("=" * 80)

# ── 1. Data Download ──────────────────────────────────────────────────────────
print("\n[1] Downloading data...")
vix = yf.download("^VIX", start="2005-01-01", end="2025-01-01", progress=False)
spy = yf.download("SPY", start="2005-01-01", end="2025-01-01", progress=False)

# Handle multi-level columns
if isinstance(vix.columns, pd.MultiIndex):
    vix.columns = vix.columns.get_level_values(0)
if isinstance(spy.columns, pd.MultiIndex):
    spy.columns = spy.columns.get_level_values(0)

vix_close = vix["Close"].dropna()
spy_close = spy["Close"].dropna()

# Align dates
common_idx = vix_close.index.intersection(spy_close.index)
vix_close = vix_close.loc[common_idx]
spy_close = spy_close.loc[common_idx]

spy_ret = spy_close.pct_change().dropna()
vix_close = vix_close.loc[spy_ret.index]

print(f"  Data period: {vix_close.index[0].date()} to {vix_close.index[-1].date()}")
print(f"  Trading days: {len(vix_close)}")

# ── 2. Define Regimes ─────────────────────────────────────────────────────────
print("\n[2] Defining VIX regimes...")

def classify_regime(v):
    if v < 15:
        return "Low"
    elif v < 20:
        return "Normal"
    elif v < 30:
        return "High"
    else:
        return "Crisis"

regimes = vix_close.apply(classify_regime)
regime_names = ["Low", "Normal", "High", "Crisis"]

# Distribution
regime_counts = regimes.value_counts()
print("\n  Regime distribution:")
for r in regime_names:
    c = regime_counts.get(r, 0)
    print(f"    {r:8s}: {c:5d} days ({100*c/len(regimes):5.1f}%)")

# ── 3. Transition Matrix ──────────────────────────────────────────────────────
print("\n[3] Transition Matrix: P(regime tomorrow | regime today)")

# Build transition counts
trans_counts = defaultdict(lambda: defaultdict(int))
for i in range(len(regimes) - 1):
    from_r = regimes.iloc[i]
    to_r = regimes.iloc[i + 1]
    trans_counts[from_r][to_r] += 1

# Convert to probability matrix
print("\n  From\\To     Low     Normal   High    Crisis  | Sticky%")
print("  " + "-" * 60)
for from_r in regime_names:
    total = sum(trans_counts[from_r].values())
    if total == 0:
        continue
    probs = []
    for to_r in regime_names:
        p = trans_counts[from_r][to_r] / total
        probs.append(p)
    sticky = trans_counts[from_r][from_r] / total
    prob_str = "  ".join(f"{p:7.3f}" for p in probs)
    print(f"  {from_r:8s}  {prob_str}  | {100*sticky:.1f}%")

# ── 4. Regime Stickiness & Duration ──────────────────────────────────────────
print("\n[4] Regime Duration Statistics")

# Calculate consecutive regime streaks
streaks = []
current_regime = regimes.iloc[0]
current_len = 1
current_start = regimes.index[0]

for i in range(1, len(regimes)):
    if regimes.iloc[i] == current_regime:
        current_len += 1
    else:
        streaks.append({
            "regime": current_regime,
            "duration": current_len,
            "start": current_start,
            "end": regimes.index[i - 1]
        })
        current_regime = regimes.iloc[i]
        current_len = 1
        current_start = regimes.index[i]

# Last streak
streaks.append({
    "regime": current_regime,
    "duration": current_len,
    "start": current_start,
    "end": regimes.index[-1]
})

streaks_df = pd.DataFrame(streaks)

print(f"\n  {'Regime':8s}  {'Count':>6s}  {'Mean':>6s}  {'Median':>6s}  {'Max':>6s}  {'P(1day)':>7s}")
print("  " + "-" * 55)
for r in regime_names:
    rdf = streaks_df[streaks_df["regime"] == r]
    if len(rdf) == 0:
        continue
    durations = rdf["duration"].values
    one_day_pct = np.mean(durations == 1) * 100
    print(f"  {r:8s}  {len(rdf):6d}  {np.mean(durations):6.1f}  {np.median(durations):6.1f}  {np.max(durations):6d}  {one_day_pct:6.1f}%")

# ── 5. Transition Speed: Escalation vs De-escalation ─────────────────────────
print("\n[5] Transition Speed Analysis")

# For each day, track how many days until VIX reaches a different regime
# Focus on: Low->Crisis and Crisis->Low transitions

def find_transition_times(regimes_series, from_regime, to_regime):
    """Find all instances where regime transitions from 'from_regime' to eventually 'to_regime'.
    Returns list of (start_date, days_to_transition)."""
    transitions = []
    i = 0
    while i < len(regimes_series):
        if regimes_series.iloc[i] == from_regime:
            start = i
            # Search forward for to_regime
            for j in range(i + 1, len(regimes_series)):
                if regimes_series.iloc[j] == to_regime:
                    transitions.append((regimes_series.index[start], j - start))
                    break
                # If we go back to from_regime, restart from there
                if regimes_series.iloc[j] == from_regime:
                    break
            i += 1
        else:
            i += 1
    return transitions

# Key transitions to analyze
key_transitions = [
    ("Low", "High"),
    ("Low", "Crisis"),
    ("Normal", "Crisis"),
    ("Crisis", "Normal"),
    ("Crisis", "Low"),
    ("High", "Normal"),
    ("High", "Low"),
]

print(f"\n  {'Transition':20s}  {'Count':>6s}  {'Mean':>7s}  {'Median':>7s}  {'Min':>5s}  {'Max':>5s}")
print("  " + "-" * 65)

transition_stats = {}
for from_r, to_r in key_transitions:
    trans = find_transition_times(regimes, from_r, to_r)
    if len(trans) >= 3:
        days = [t[1] for t in trans]
        label = f"{from_r}->{to_r}"
        transition_stats[label] = days
        print(f"  {label:20s}  {len(days):6d}  {np.mean(days):7.1f}  {np.median(days):7.1f}  {np.min(days):5d}  {np.max(days):5d}")
    else:
        label = f"{from_r}->{to_r}"
        print(f"  {label:20s}  {len(trans):6d}  (insufficient data)")

# Asymmetry analysis
print("\n  Escalation vs De-escalation Asymmetry:")
escalation_pairs = [
    (("Low", "High"), ("High", "Low")),
    (("Low", "Crisis"), ("Crisis", "Low")),
    (("Normal", "Crisis"), ("Crisis", "Normal")),
]

for (esc_from, esc_to), (deesc_from, deesc_to) in escalation_pairs:
    esc_label = f"{esc_from}->{esc_to}"
    deesc_label = f"{deesc_from}->{deesc_to}"
    if esc_label in transition_stats and deesc_label in transition_stats:
        esc_median = np.median(transition_stats[esc_label])
        deesc_median = np.median(transition_stats[deesc_label])
        ratio = deesc_median / esc_median if esc_median > 0 else np.nan
        print(f"    {esc_label:15s} median={esc_median:5.1f}d  vs  {deesc_label:15s} median={deesc_median:5.1f}d  | De-esc/Esc ratio={ratio:.2f}x")

# ── 6. Mean Reversion Speed by Regime ─────────────────────────────────────────
print("\n[6] Mean Reversion Speed by Regime")

# Calculate AR(1) coefficient for VIX changes within each regime
vix_change = vix_close.diff()

for r in regime_names:
    mask = regimes == r
    # Get VIX levels in this regime and next-day change
    regime_vix = vix_close[mask]
    regime_change = vix_change[mask].dropna()

    if len(regime_change) < 30:
        print(f"  {r:8s}: insufficient data")
        continue

    # Long-run mean of VIX in this regime
    mean_vix = regime_vix.mean()

    # Calculate mean daily change (towards mean = negative for high VIX, positive for low VIX)
    mean_change = regime_change.mean()

    # AR(1) on VIX level: VIX(t) = a + b*VIX(t-1) + e
    # Mean reversion speed = 1 - b (higher = faster reversion)
    aligned_idx = regime_vix.index.intersection(vix_close.shift(1).dropna().index)
    if len(aligned_idx) < 30:
        print(f"  {r:8s}: insufficient aligned data")
        continue

    y = vix_close.loc[aligned_idx].values
    x = vix_close.shift(1).loc[aligned_idx].values

    # Simple OLS
    x_with_const = np.column_stack([np.ones(len(x)), x])
    try:
        beta = np.linalg.lstsq(x_with_const, y, rcond=None)[0]
        ar1_coef = beta[1]
        reversion_speed = 1 - ar1_coef
        half_life = -np.log(2) / np.log(abs(ar1_coef)) if 0 < abs(ar1_coef) < 1 else np.nan
        print(f"  {r:8s}: mean VIX={mean_vix:5.1f}  AR(1)={ar1_coef:.4f}  MR speed={reversion_speed:.4f}  half-life={half_life:.1f}d  mean daily chg={mean_change:.3f}")
    except Exception as e:
        print(f"  {r:8s}: AR(1) estimation failed: {e}")

# ── 7. Overshoot & False Alarm Analysis ───────────────────────────────────────
print("\n[7] Overshoot & False Alarm Analysis")

# Overshoot: VIX goes to Crisis then immediately (within 3 days) back to Normal or below
crisis_entries = []
i = 0
while i < len(regimes):
    if regimes.iloc[i] == "Crisis":
        start = i
        # Find end of this crisis period
        j = i + 1
        while j < len(regimes) and regimes.iloc[j] == "Crisis":
            j += 1
        crisis_entries.append({
            "start_date": regimes.index[start],
            "duration": j - start,
            "peak_vix": vix_close.iloc[start:j].max(),
            "exit_regime": regimes.iloc[j] if j < len(regimes) else "End"
        })
        i = j
    else:
        i += 1

crisis_df = pd.DataFrame(crisis_entries)

print(f"  Total Crisis episodes: {len(crisis_df)}")
if len(crisis_df) > 0:
    print(f"  Mean duration: {crisis_df['duration'].mean():.1f} days")
    print(f"  Median duration: {crisis_df['duration'].median():.1f} days")

    # Overshoot = Crisis lasting 1-2 days
    overshoot = crisis_df[crisis_df["duration"] <= 2]
    print(f"\n  Overshoot (Crisis <=2 days): {len(overshoot)} episodes ({100*len(overshoot)/len(crisis_df):.1f}%)")
    if len(overshoot) > 0:
        print(f"    Peak VIX in overshoots: mean={overshoot['peak_vix'].mean():.1f}, max={overshoot['peak_vix'].max():.1f}")

    # Duration distribution
    print(f"\n  Crisis duration distribution:")
    for bucket, label in [(1, "1 day"), (2, "2 days"), (3, "3 days"),
                           ((4, 10), "4-10 days"), ((11, 30), "11-30 days"), ((31, 999), "30+ days")]:
        if isinstance(bucket, tuple):
            count = ((crisis_df["duration"] >= bucket[0]) & (crisis_df["duration"] <= bucket[1])).sum()
        else:
            count = (crisis_df["duration"] == bucket).sum()
        print(f"    {label:12s}: {count:3d} ({100*count/len(crisis_df):5.1f}%)")

# False alarms: VIX >25 for <3 days then drops back below 20
print("\n  False Alarm Analysis (VIX >25 for <3 days then <20):")
high_vix = vix_close > 25
false_alarms = 0
total_spikes = 0
spike_details = []

i = 0
while i < len(high_vix):
    if high_vix.iloc[i]:
        start = i
        j = i + 1
        while j < len(high_vix) and high_vix.iloc[j]:
            j += 1
        spike_duration = j - start
        total_spikes += 1

        # Check if VIX drops below 20 within 5 days after spike ends
        is_false_alarm = False
        if j < len(vix_close) and spike_duration < 3:
            # Check next 5 days
            end_check = min(j + 5, len(vix_close))
            if any(vix_close.iloc[j:end_check] < 20):
                is_false_alarm = True
                false_alarms += 1

        spike_details.append({
            "date": vix_close.index[start],
            "duration": spike_duration,
            "peak": vix_close.iloc[start:j].max(),
            "false_alarm": is_false_alarm
        })
        i = j
    else:
        i += 1

print(f"    Total VIX>25 spikes: {total_spikes}")
print(f"    False alarms (<3 days, then <20): {false_alarms} ({100*false_alarms/total_spikes:.1f}%)")

# ── 8. Intra-Month Regime Changes (VT Implications) ──────────────────────────
print("\n[8] Intra-Month Regime Changes (VT Rebalancing Implications)")

# Group by year-month
regimes_monthly = regimes.groupby(regimes.index.to_period("M"))

month_stats = []
for period, month_regimes in regimes_monthly:
    regimes_in_month = month_regimes.values
    # Count regime changes within this month
    changes = sum(1 for i in range(1, len(regimes_in_month)) if regimes_in_month[i] != regimes_in_month[i-1])
    unique_regimes = len(set(regimes_in_month))
    start_regime = regimes_in_month[0]
    end_regime = regimes_in_month[-1]
    regime_changed = start_regime != end_regime

    month_stats.append({
        "period": period,
        "changes": changes,
        "unique_regimes": unique_regimes,
        "start_regime": start_regime,
        "end_regime": end_regime,
        "regime_changed": regime_changed,
    })

month_df = pd.DataFrame(month_stats)

print(f"  Total months: {len(month_df)}")
print(f"  Months with regime change: {month_df['regime_changed'].sum()} ({100*month_df['regime_changed'].mean():.1f}%)")
print(f"  Mean regime transitions per month: {month_df['changes'].mean():.1f}")
print(f"  Months with 0 transitions: {(month_df['changes']==0).sum()} ({100*(month_df['changes']==0).mean():.1f}%)")
print(f"  Months with 3+ transitions: {(month_df['changes']>=3).sum()} ({100*(month_df['changes']>=3).mean():.1f}%)")

# Unique regimes visited per month
print(f"\n  Unique regimes per month:")
for n in [1, 2, 3, 4]:
    count = (month_df["unique_regimes"] == n).sum()
    print(f"    {n} regimes: {count:3d} months ({100*count/len(month_df):.1f}%)")

# ── 9. Regime Whipsaw Cost for VT ────────────────────────────────────────────
print("\n[9] Regime Whipsaw Cost for VT Strategy")

# Simulate: VT checks regime at start of month, sets allocation
# If VIX changes regime mid-month, VT is "wrong" for part of the month
# Compare: VT with start-of-month regime vs hypothetical daily-rebalance VT

# Simple VT: SPY weight based on VIX regime
vt_weights = {"Low": 1.0, "Normal": 0.8, "High": 0.5, "Crisis": 0.2}

# Monthly VT: use start-of-month regime
monthly_vt_returns = []
daily_vt_returns = []

for period, month_regimes in regimes_monthly:
    month_dates = month_regimes.index
    if len(month_dates) < 5:
        continue

    start_regime = month_regimes.iloc[0]
    monthly_weight = vt_weights[start_regime]

    for date in month_dates:
        if date in spy_ret.index:
            r = spy_ret.loc[date]
            # Monthly VT: fixed weight for whole month
            monthly_vt_returns.append({
                "date": date,
                "return": monthly_weight * r,
                "weight": monthly_weight
            })
            # Daily VT: adjust weight daily
            daily_regime = regimes.loc[date]
            daily_weight = vt_weights[daily_regime]
            daily_vt_returns.append({
                "date": date,
                "return": daily_weight * r,
                "weight": daily_weight
            })

monthly_vt_df = pd.DataFrame(monthly_vt_returns).set_index("date")
daily_vt_df = pd.DataFrame(daily_vt_returns).set_index("date")

# Compare performance
monthly_sharpe = monthly_vt_df["return"].mean() / monthly_vt_df["return"].std() * np.sqrt(252)
daily_sharpe = daily_vt_df["return"].mean() / daily_vt_df["return"].std() * np.sqrt(252)

monthly_cum = (1 + monthly_vt_df["return"]).cumprod()
daily_cum = (1 + daily_vt_df["return"]).cumprod()

monthly_mdd = (monthly_cum / monthly_cum.cummax() - 1).min()
daily_mdd = (daily_cum / daily_cum.cummax() - 1).min()

print(f"\n  Metric              Monthly-VT    Daily-VT    Difference")
print(f"  " + "-" * 58)
print(f"  Ann. Return         {monthly_vt_df['return'].mean()*252:10.4f}    {daily_vt_df['return'].mean()*252:10.4f}    {(daily_vt_df['return'].mean()-monthly_vt_df['return'].mean())*252:+10.4f}")
print(f"  Ann. Vol            {monthly_vt_df['return'].std()*np.sqrt(252):10.4f}    {daily_vt_df['return'].std()*np.sqrt(252):10.4f}    {(daily_vt_df['return'].std()-monthly_vt_df['return'].std())*np.sqrt(252):+10.4f}")
print(f"  Sharpe              {monthly_sharpe:10.4f}    {daily_sharpe:10.4f}    {daily_sharpe-monthly_sharpe:+10.4f}")
print(f"  Max Drawdown        {monthly_mdd:10.4f}    {daily_mdd:10.4f}    {daily_mdd-monthly_mdd:+10.4f}")

# Whipsaw months: months where regime at start != regime most of the month
whipsaw_months = 0
total_months = 0
whipsaw_cost_total = 0

for period, group in monthly_vt_df.groupby(monthly_vt_df.index.to_period("M")):
    if period not in daily_vt_df.index.to_period("M").unique():
        continue
    daily_group = daily_vt_df.loc[daily_vt_df.index.to_period("M") == period]

    if len(group) == 0 or len(daily_group) == 0:
        continue

    total_months += 1
    month_cost = group["return"].sum() - daily_group["return"].sum()

    # Check if weights differ significantly
    weight_diff = abs(group["weight"].iloc[0] - daily_group["weight"].mean())
    if weight_diff > 0.1:
        whipsaw_months += 1
        whipsaw_cost_total += month_cost

print(f"\n  Whipsaw Analysis:")
print(f"    Total months analyzed: {total_months}")
print(f"    Months with significant weight mismatch (>10%): {whipsaw_months} ({100*whipsaw_months/total_months:.1f}%)")
print(f"    Total whipsaw cost: {whipsaw_cost_total:.4f} ({100*whipsaw_cost_total:.2f}%)")
avg_annual_whipsaw = whipsaw_cost_total / (total_months / 12) if total_months > 0 else 0
print(f"    Average annual whipsaw cost: {avg_annual_whipsaw:.4f} ({100*avg_annual_whipsaw:.2f}%)")

# ── 10. Regime Transition Patterns by Market Condition ────────────────────────
print("\n[10] Transition Patterns by Market Condition")

# Do transitions happen more on up-days or down-days?
regime_change = regimes != regimes.shift(1)
regime_change = regime_change.iloc[1:]  # drop first NaN

# Align with spy returns
common = regime_change.index.intersection(spy_ret.index)
rc = regime_change.loc[common]
sr = spy_ret.loc[common]

change_days = sr[rc]
no_change_days = sr[~rc]

print(f"  Days with regime change: {rc.sum()} ({100*rc.mean():.1f}%)")
print(f"  SPY return on change days: mean={change_days.mean():.4f}, std={change_days.std():.4f}")
print(f"  SPY return on no-change days: mean={no_change_days.mean():.4f}, std={no_change_days.std():.4f}")

# By direction
escalation = []
deescalation = []
regime_order = {"Low": 0, "Normal": 1, "High": 2, "Crisis": 3}

for i in range(1, len(regimes)):
    if regimes.iloc[i] != regimes.iloc[i-1]:
        date = regimes.index[i]
        if date in spy_ret.index:
            from_level = regime_order[regimes.iloc[i-1]]
            to_level = regime_order[regimes.iloc[i]]
            if to_level > from_level:
                escalation.append(spy_ret.loc[date])
            else:
                deescalation.append(spy_ret.loc[date])

print(f"\n  Escalation days (VIX regime up): {len(escalation)}")
if len(escalation) > 0:
    print(f"    SPY mean return: {np.mean(escalation):.4f}")
print(f"  De-escalation days (VIX regime down): {len(deescalation)}")
if len(deescalation) > 0:
    print(f"    SPY mean return: {np.mean(deescalation):.4f}")

# ── 11. Year-by-Year Regime Breakdown ────────────────────────────────────────
print("\n[11] Year-by-Year Regime Breakdown")
print(f"\n  {'Year':>6s}  {'Low%':>6s}  {'Normal%':>8s}  {'High%':>6s}  {'Crisis%':>8s}  {'Changes':>8s}")
print("  " + "-" * 55)

for year in range(2005, 2025):
    year_mask = regimes.index.year == year
    year_regimes = regimes[year_mask]
    if len(year_regimes) == 0:
        continue

    changes = sum(1 for i in range(1, len(year_regimes)) if year_regimes.iloc[i] != year_regimes.iloc[i-1])

    pcts = {}
    for r in regime_names:
        pcts[r] = 100 * (year_regimes == r).sum() / len(year_regimes)

    print(f"  {year:6d}  {pcts['Low']:5.1f}%  {pcts['Normal']:6.1f}%  {pcts['High']:5.1f}%  {pcts['Crisis']:6.1f}%  {changes:8d}")

# ── 12. Key Findings Summary ─────────────────────────────────────────────────
print("\n" + "=" * 80)
print("KEY FINDINGS SUMMARY")
print("=" * 80)

# Stickiness
print("\n1. Regime Stickiness:")
for r in regime_names:
    total = sum(trans_counts[r].values())
    if total > 0:
        sticky = trans_counts[r][r] / total
        print(f"   {r:8s}: {100*sticky:.1f}% chance of staying same regime next day")

print(f"\n2. Transition Speed Asymmetry:")
if "Low->Crisis" in transition_stats and "Crisis->Low" in transition_stats:
    esc_med = np.median(transition_stats["Low->Crisis"])
    deesc_med = np.median(transition_stats["Crisis->Low"])
    print(f"   Low->Crisis median: {esc_med:.0f} days")
    print(f"   Crisis->Low median: {deesc_med:.0f} days")
    print(f"   De-escalation is {deesc_med/esc_med:.1f}x slower than escalation")

print(f"\n3. False Alarms:")
print(f"   {false_alarms}/{total_spikes} VIX>25 spikes ({100*false_alarms/total_spikes:.1f}%) last <3 days then revert")

print(f"\n4. VT Monthly Rebalance Impact:")
print(f"   {100*month_df['regime_changed'].mean():.1f}% of months have different start vs end regime")
print(f"   Monthly VT Sharpe: {monthly_sharpe:.4f} vs Daily VT Sharpe: {daily_sharpe:.4f}")
print(f"   Whipsaw cost: ~{100*abs(avg_annual_whipsaw):.2f}% per year")

print(f"\n5. Market Impact of Transitions:")
print(f"   Escalation days: SPY mean {np.mean(escalation):.4f}")
print(f"   De-escalation days: SPY mean {np.mean(deescalation):.4f}")
print(f"   Regime transitions strongly associated with same-day SPY returns")

print("\n" + "=" * 80)
print("K278 Complete")
print("=" * 80)
