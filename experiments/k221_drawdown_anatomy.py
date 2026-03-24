"""
K221: Anatomy of Drawdowns — When Does 50/50+VT Fail?
=====================================================
50/50+VT has been validated 9 times. But WHEN does it fail?
Understanding failure modes helps investors prepare psychologically.

Methodology:
1. Identify all drawdown episodes (>5%) for 50/50+VT portfolio
2. Classify each episode (equity-driven, gold-driven, both-crash, VT-failure)
3. Compare each episode: 50/50+VT vs 50/50 B&H vs SPY-only
4. VIX level at drawdown start — does VIX predict severity?
5. Longest underwater period
6. Psychological metrics: consecutive losing months, worst month, worst quarter

Data: SPY, GLD daily from yfinance. Full history 2005-2024.
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
DATA_START = "2004-06-01"  # GLD inception is ~Nov 2004, give buffer
DATA_END = "2025-01-01"
ANALYSIS_START = "2005-01-03"  # Start after enough data for GLD
DD_THRESHOLD = 0.05  # 5% = "significant" drawdown
TARGET_VOL_CONSTANT = 12.0  # 12/VIX rule
RF_ANNUAL = 0.04
RF_DAILY = RF_ANNUAL / 252

print("=" * 80)
print("K221: ANATOMY OF DRAWDOWNS — WHEN DOES 50/50+VT FAIL?")
print("=" * 80)

# ==================================================================
# 1. Download Data
# ==================================================================
print("\n[1/6] Downloading SPY, GLD, ^VIX data...")

tickers = ["SPY", "GLD", "^VIX"]
raw_data = {}
for t in tickers:
    df = yf.download(t, start=DATA_START, end=DATA_END, progress=False, auto_adjust=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    raw_data[t] = df[["Close"]].rename(columns={"Close": t.replace("^", "")})
    print(f"  {t}: {len(df)} rows, {df.index[0].date()} to {df.index[-1].date()}")

# Merge
merged = raw_data["SPY"]
for t in ["GLD", "^VIX"]:
    key = t.replace("^", "")
    merged = merged.join(raw_data[t], how="inner")
merged = merged.dropna()

# Simple returns (not log) for portfolio arithmetic
merged["SPY_ret"] = merged["SPY"].pct_change()
merged["GLD_ret"] = merged["GLD"].pct_change()
merged = merged.dropna()

# Filter to analysis period
merged = merged.loc[ANALYSIS_START:]
print(f"\n  Analysis period: {merged.index[0].date()} to {merged.index[-1].date()} ({len(merged)} days)")


# ==================================================================
# 2. Build Three Portfolios
# ==================================================================
print("\n[2/6] Building portfolios...")

# --- Portfolio A: 50/50+VT (12/VIX rule, monthly rebalance) ---
# Use lagged VIX (VIX_t determines weight for t+1)
merged["VIX_weight"] = (TARGET_VOL_CONSTANT / merged["VIX"]).clip(upper=1.0)
merged["VIX_weight_lagged"] = merged["VIX_weight"].shift(1)

# Monthly rebalance: only update weight on first trading day of month
merged["month"] = merged.index.to_period("M")
merged["is_month_start"] = merged["month"] != merged["month"].shift(1)

weight_vt = np.full(len(merged), np.nan)
current_w = 1.0  # initial weight
for i in range(len(merged)):
    if merged["is_month_start"].iloc[i] or np.isnan(weight_vt[max(0, i-1)]):
        current_w = merged["VIX_weight_lagged"].iloc[i]
        if np.isnan(current_w):
            current_w = 1.0
    weight_vt[i] = current_w

merged["w_vt"] = weight_vt
merged["ret_5050vt"] = merged["w_vt"] * 0.5 * (merged["SPY_ret"] + merged["GLD_ret"]) + \
                        (1 - merged["w_vt"]) * RF_DAILY

# --- Portfolio B: 50/50 Buy & Hold (no VT) ---
merged["ret_5050bh"] = 0.5 * (merged["SPY_ret"] + merged["GLD_ret"])

# --- Portfolio C: SPY-only ---
merged["ret_spy"] = merged["SPY_ret"]

# Compute cumulative wealth
for col in ["ret_5050vt", "ret_5050bh", "ret_spy"]:
    merged[f"wealth_{col.replace('ret_', '')}"] = (1 + merged[col]).cumprod()

print(f"  50/50+VT final wealth: ${merged['wealth_5050vt'].iloc[-1]:.2f}")
print(f"  50/50 B&H final wealth: ${merged['wealth_5050bh'].iloc[-1]:.2f}")
print(f"  SPY-only final wealth: ${merged['wealth_spy'].iloc[-1]:.2f}")


# ==================================================================
# 3. Identify Drawdown Episodes (50/50+VT)
# ==================================================================
print("\n[3/6] Identifying drawdown episodes for 50/50+VT...")

def find_drawdown_episodes(wealth_series, threshold=0.05):
    """Find all drawdown episodes exceeding threshold.
    Returns list of dicts with start, trough, recovery dates and metrics."""
    running_max = wealth_series.cummax()
    drawdown = (wealth_series - running_max) / running_max

    episodes = []
    in_drawdown = False
    start_idx = None

    for i in range(len(drawdown)):
        dd = drawdown.iloc[i]

        if not in_drawdown and dd < -0.001:  # entering drawdown
            in_drawdown = True
            start_idx = i - 1 if i > 0 else i  # peak is one before

        if in_drawdown and dd >= 0:  # recovered
            in_drawdown = False
            # Find trough in this episode
            episode_dd = drawdown.iloc[start_idx:i+1]
            trough_idx = episode_dd.idxmin()
            max_dd = episode_dd.min()

            if abs(max_dd) >= threshold:
                episodes.append({
                    "start_date": drawdown.index[start_idx],
                    "trough_date": trough_idx,
                    "recovery_date": drawdown.index[i],
                    "max_dd": max_dd,
                    "duration_to_trough": (trough_idx - drawdown.index[start_idx]).days,
                    "recovery_days": (drawdown.index[i] - trough_idx).days,
                    "total_days": (drawdown.index[i] - drawdown.index[start_idx]).days,
                })
            start_idx = None

    # Handle ongoing drawdown at end of data
    if in_drawdown and start_idx is not None:
        episode_dd = drawdown.iloc[start_idx:]
        trough_idx = episode_dd.idxmin()
        max_dd = episode_dd.min()

        if abs(max_dd) >= threshold:
            episodes.append({
                "start_date": drawdown.index[start_idx],
                "trough_date": trough_idx,
                "recovery_date": None,  # not recovered
                "max_dd": max_dd,
                "duration_to_trough": (trough_idx - drawdown.index[start_idx]).days,
                "recovery_days": None,
                "total_days": None,
            })

    return episodes


episodes_vt = find_drawdown_episodes(merged["wealth_5050vt"], DD_THRESHOLD)
episodes_bh = find_drawdown_episodes(merged["wealth_5050bh"], DD_THRESHOLD)
episodes_spy = find_drawdown_episodes(merged["wealth_spy"], DD_THRESHOLD)

print(f"\n  50/50+VT: {len(episodes_vt)} episodes > {DD_THRESHOLD*100:.0f}%")
print(f"  50/50 B&H: {len(episodes_bh)} episodes > {DD_THRESHOLD*100:.0f}%")
print(f"  SPY-only: {len(episodes_spy)} episodes > {DD_THRESHOLD*100:.0f}%")

# ==================================================================
# 4. Detailed Episode Analysis
# ==================================================================
print("\n[4/6] Detailed episode analysis (50/50+VT)...")
print("=" * 80)

episode_details = []

for i, ep in enumerate(episodes_vt):
    start = ep["start_date"]
    trough = ep["trough_date"]
    end = ep["recovery_date"]

    # Get data for this episode window
    if end is not None:
        mask = (merged.index >= start) & (merged.index <= end)
    else:
        mask = merged.index >= start
    window = merged.loc[mask]

    # Asset-level returns during peak-to-trough
    mask_pt = (merged.index >= start) & (merged.index <= trough)
    pt_data = merged.loc[mask_pt]

    spy_dd = (pt_data["SPY"].iloc[-1] / pt_data["SPY"].iloc[0]) - 1
    gld_dd = (pt_data["GLD"].iloc[-1] / pt_data["GLD"].iloc[0]) - 1

    # VIX at start of drawdown
    vix_at_start = merged.loc[start, "VIX"] if start in merged.index else np.nan
    vix_at_trough = merged.loc[trough, "VIX"] if trough in merged.index else np.nan

    # Average VT weight during episode
    avg_vt_weight = pt_data["w_vt"].mean()

    # Classify episode
    if spy_dd < -0.10 and gld_dd < -0.05:
        classification = "Both-Crash"
    elif spy_dd < -0.10 and gld_dd >= -0.05:
        classification = "Equity-Driven"
    elif gld_dd < -0.10 and spy_dd >= -0.05:
        classification = "Gold-Driven"
    elif spy_dd < -0.05 and gld_dd < -0.03:
        classification = "Mild-Both"
    elif spy_dd < -0.05:
        classification = "Equity-Driven"
    elif gld_dd < -0.05:
        classification = "Gold-Driven"
    else:
        classification = "Gradual-Erosion"

    # Compare: What was 50/50 B&H drawdown over same period?
    bh_dd = (pt_data["wealth_5050bh"].iloc[-1] / pt_data["wealth_5050bh"].iloc[0]) - 1
    spy_only_dd = (pt_data["wealth_spy"].iloc[-1] / pt_data["wealth_spy"].iloc[0]) - 1
    vt_dd = ep["max_dd"]

    # Did VT help or hurt?
    # Both vt_dd and bh_dd are negative (drawdowns).
    # vt_dd - bh_dd > 0 means VT had LESS drawdown (less negative) → VT HELPED
    # vt_dd - bh_dd < 0 means VT had MORE drawdown (more negative) → VT HURT
    vt_vs_bh = vt_dd - bh_dd
    vt_helped = vt_vs_bh > 0.005  # VT reduced DD by >0.5% → HELPED
    vt_hurt = vt_vs_bh < -0.005   # VT increased DD by >0.5% → HURT

    detail = {
        "episode": i + 1,
        "start": str(start.date()),
        "trough": str(trough.date()),
        "recovery": str(end.date()) if end else "ONGOING",
        "max_dd_vt": round(float(vt_dd) * 100, 2),
        "max_dd_bh": round(float(bh_dd) * 100, 2),
        "max_dd_spy": round(float(spy_only_dd) * 100, 2),
        "spy_return": round(float(spy_dd) * 100, 2),
        "gld_return": round(float(gld_dd) * 100, 2),
        "vix_at_start": round(float(vix_at_start), 1) if not np.isnan(vix_at_start) else None,
        "vix_at_trough": round(float(vix_at_trough), 1) if not np.isnan(vix_at_trough) else None,
        "avg_vt_weight": round(float(avg_vt_weight), 3),
        "classification": classification,
        "duration_to_trough_days": ep["duration_to_trough"],
        "recovery_days": ep["recovery_days"],
        "total_underwater_days": ep["total_days"],
        "vt_vs_bh_pct": round(float(vt_vs_bh) * 100, 2),
        "vt_helped": bool(vt_helped),
        "vt_hurt": bool(vt_hurt),
    }
    episode_details.append(detail)

    print(f"\n  Episode {i+1}: {detail['start']} → {detail['trough']} → {detail['recovery']}")
    print(f"    Classification: {classification}")
    print(f"    Max DD: VT={detail['max_dd_vt']:.1f}%  B&H={detail['max_dd_bh']:.1f}%  SPY={detail['max_dd_spy']:.1f}%")
    print(f"    SPY return: {detail['spy_return']:.1f}%  GLD return: {detail['gld_return']:.1f}%")
    print(f"    VIX: start={detail['vix_at_start']}  trough={detail['vix_at_trough']}")
    print(f"    Avg VT weight: {detail['avg_vt_weight']:.1%}")
    print(f"    VT vs B&H: {detail['vt_vs_bh_pct']:+.2f}%  {'HELPED' if vt_helped else ('HURT' if vt_hurt else 'NEUTRAL')}")
    if detail['total_underwater_days']:
        print(f"    Duration: {detail['duration_to_trough_days']}d to trough, {detail['recovery_days']}d recovery, {detail['total_underwater_days']}d total")


# ==================================================================
# 5. VT Failure Analysis
# ==================================================================
print("\n" + "=" * 80)
print("[5/6] VT Failure & Success Analysis")
print("=" * 80)

# Count classifications
from collections import Counter
class_counts = Counter([d["classification"] for d in episode_details])
print(f"\n  Episode classification breakdown:")
for cls, cnt in sorted(class_counts.items(), key=lambda x: -x[1]):
    print(f"    {cls}: {cnt}")

# VT helped vs hurt
helped = sum(1 for d in episode_details if d["vt_helped"])
hurt = sum(1 for d in episode_details if d["vt_hurt"])
neutral = len(episode_details) - helped - hurt
print(f"\n  VT impact on drawdowns:")
print(f"    Helped (reduced DD by >0.5%): {helped}/{len(episode_details)}")
print(f"    Hurt (increased DD by >0.5%): {hurt}/{len(episode_details)}")
print(f"    Neutral: {neutral}/{len(episode_details)}")

# When VT hurt — which episodes?
if hurt > 0:
    print(f"\n  Episodes where VT HURT:")
    for d in episode_details:
        if d["vt_hurt"]:
            print(f"    Ep{d['episode']}: {d['start']} ({d['classification']}) VT DD={d['max_dd_vt']:.1f}% vs B&H DD={d['max_dd_bh']:.1f}% (diff={d['vt_vs_bh_pct']:+.1f}%)")

# VIX → severity correlation
vix_starts = [d["vix_at_start"] for d in episode_details if d["vix_at_start"] is not None]
dd_values = [d["max_dd_vt"] for d in episode_details if d["vix_at_start"] is not None]
if len(vix_starts) >= 3:
    corr = np.corrcoef(vix_starts, dd_values)[0, 1]
    print(f"\n  VIX at start vs DD severity: r = {corr:.3f}")
    # Low VIX starts (< 15) vs high VIX starts (> 20)
    low_vix = [(v, d) for v, d in zip(vix_starts, dd_values) if v < 15]
    mid_vix = [(v, d) for v, d in zip(vix_starts, dd_values) if 15 <= v <= 25]
    high_vix = [(v, d) for v, d in zip(vix_starts, dd_values) if v > 25]
    if low_vix:
        avg_dd_low = np.mean([d for _, d in low_vix])
        print(f"    Low VIX (<15) start: {len(low_vix)} episodes, avg DD = {avg_dd_low:.1f}%")
    if mid_vix:
        avg_dd_mid = np.mean([d for _, d in mid_vix])
        print(f"    Mid VIX (15-25) start: {len(mid_vix)} episodes, avg DD = {avg_dd_mid:.1f}%")
    if high_vix:
        avg_dd_high = np.mean([d for _, d in high_vix])
        print(f"    High VIX (>25) start: {len(high_vix)} episodes, avg DD = {avg_dd_high:.1f}%")


# ==================================================================
# 6. Underwater Period & Psychological Metrics
# ==================================================================
print("\n" + "=" * 80)
print("[6/6] Underwater Period & Psychological Metrics")
print("=" * 80)

# --- Longest underwater period ---
running_max_vt = merged["wealth_5050vt"].cummax()
dd_series_vt = (merged["wealth_5050vt"] - running_max_vt) / running_max_vt

# Find underwater streaks
underwater_start = None
max_underwater = 0
max_underwater_start = None
max_underwater_end = None

for i in range(len(dd_series_vt)):
    if dd_series_vt.iloc[i] < -0.001:
        if underwater_start is None:
            underwater_start = dd_series_vt.index[i]
    else:
        if underwater_start is not None:
            uw_days = (dd_series_vt.index[i] - underwater_start).days
            if uw_days > max_underwater:
                max_underwater = uw_days
                max_underwater_start = underwater_start
                max_underwater_end = dd_series_vt.index[i]
            underwater_start = None

# Check if still underwater at end
if underwater_start is not None:
    uw_days = (dd_series_vt.index[-1] - underwater_start).days
    if uw_days > max_underwater:
        max_underwater = uw_days
        max_underwater_start = underwater_start
        max_underwater_end = dd_series_vt.index[-1]

print(f"\n  Longest underwater period (50/50+VT):")
print(f"    {max_underwater} calendar days ({max_underwater/30.44:.1f} months)")
if max_underwater_start:
    print(f"    From {max_underwater_start.date()} to {max_underwater_end.date()}")

# Same for B&H and SPY
for name, wcol in [("50/50 B&H", "wealth_5050bh"), ("SPY-only", "wealth_spy")]:
    rm = merged[wcol].cummax()
    dd_s = (merged[wcol] - rm) / rm
    uw_start = None
    max_uw = 0
    for i in range(len(dd_s)):
        if dd_s.iloc[i] < -0.001:
            if uw_start is None:
                uw_start = dd_s.index[i]
        else:
            if uw_start is not None:
                uw_d = (dd_s.index[i] - uw_start).days
                if uw_d > max_uw:
                    max_uw = uw_d
                uw_start = None
    if uw_start is not None:
        uw_d = (dd_s.index[-1] - uw_start).days
        if uw_d > max_uw:
            max_uw = uw_d
    print(f"  Longest underwater ({name}): {max_uw} days ({max_uw/30.44:.1f} months)")

# --- Monthly returns ---
monthly_ret = {}
for col in ["ret_5050vt", "ret_5050bh", "ret_spy"]:
    monthly = merged[col].resample("ME").apply(lambda x: (1 + x).prod() - 1)
    monthly_ret[col] = monthly

# --- Quarterly returns ---
quarterly_ret = {}
for col in ["ret_5050vt", "ret_5050bh", "ret_spy"]:
    quarterly = merged[col].resample("QE").apply(lambda x: (1 + x).prod() - 1)
    quarterly_ret[col] = quarterly

print("\n  Worst single month:")
for name, col in [("50/50+VT", "ret_5050vt"), ("50/50 B&H", "ret_5050bh"), ("SPY", "ret_spy")]:
    worst_m = monthly_ret[col].min()
    worst_m_date = monthly_ret[col].idxmin()
    print(f"    {name}: {worst_m*100:.2f}% ({worst_m_date.strftime('%Y-%m')})")

print("\n  Worst quarter:")
for name, col in [("50/50+VT", "ret_5050vt"), ("50/50 B&H", "ret_5050bh"), ("SPY", "ret_spy")]:
    worst_q = quarterly_ret[col].min()
    worst_q_date = quarterly_ret[col].idxmin()
    print(f"    {name}: {worst_q*100:.2f}% ({worst_q_date.strftime('%Y-Q')}{'%d' % ((worst_q_date.month-1)//3+1)})")

# --- Consecutive losing months ---
print("\n  Max consecutive losing months:")
for name, col in [("50/50+VT", "ret_5050vt"), ("50/50 B&H", "ret_5050bh"), ("SPY", "ret_spy")]:
    m = monthly_ret[col]
    max_consec = 0
    current_consec = 0
    max_start = None
    current_start = None
    for idx, val in m.items():
        if val < 0:
            if current_consec == 0:
                current_start = idx
            current_consec += 1
            if current_consec > max_consec:
                max_consec = current_consec
                max_start = current_start
        else:
            current_consec = 0
    if max_start is not None:
        print(f"    {name}: {max_consec} months (starting {max_start.strftime('%Y-%m')})")
    else:
        print(f"    {name}: 0 months")

# --- Win rate ---
print("\n  Monthly win rate:")
for name, col in [("50/50+VT", "ret_5050vt"), ("50/50 B&H", "ret_5050bh"), ("SPY", "ret_spy")]:
    m = monthly_ret[col]
    wr = (m > 0).mean()
    print(f"    {name}: {wr*100:.1f}% ({(m>0).sum()}/{len(m)} months positive)")

# --- Annual returns distribution ---
annual_ret = {}
for col in ["ret_5050vt", "ret_5050bh", "ret_spy"]:
    annual = merged[col].resample("YE").apply(lambda x: (1 + x).prod() - 1)
    annual_ret[col] = annual

print("\n  Annual returns (50/50+VT):")
for yr, ret in annual_ret["ret_5050vt"].items():
    bh_ret = annual_ret["ret_5050bh"].get(yr, np.nan)
    spy_ret_yr = annual_ret["ret_spy"].get(yr, np.nan)
    marker = " <<<" if ret < 0 else ""
    print(f"    {yr.year}: VT={ret*100:+6.2f}%  B&H={bh_ret*100:+6.2f}%  SPY={spy_ret_yr*100:+6.2f}%{marker}")

# --- Worst drawdown year-by-year ---
print("\n  Maximum drawdown by year:")
for yr in sorted(set(merged.index.year)):
    yr_data = merged.loc[str(yr)]
    if len(yr_data) < 10:
        continue
    for name, col in [("VT", "wealth_5050vt"), ("B&H", "wealth_5050bh"), ("SPY", "wealth_spy")]:
        w = yr_data[col]
        rm = w.cummax()
        dd = ((w - rm) / rm).min()
        if name == "VT":
            vt_dd = dd
            bh_dd_val = None
            spy_dd_val = None
        elif name == "B&H":
            bh_dd_val = dd
        else:
            spy_dd_val = dd
    print(f"    {yr}: VT={vt_dd*100:+6.2f}%  B&H={bh_dd_val*100:+6.2f}%  SPY={spy_dd_val*100:+6.2f}%  VT_saved={abs(vt_dd)-abs(bh_dd_val):.2f}%pts")


# ==================================================================
# 7. Summary & Key Insights
# ==================================================================
print("\n" + "=" * 80)
print("SUMMARY: WHEN DOES 50/50+VT FAIL?")
print("=" * 80)

# Classification summary
both_crash_eps = [d for d in episode_details if "Both" in d["classification"]]
equity_eps = [d for d in episode_details if "Equity" in d["classification"]]
gold_eps = [d for d in episode_details if "Gold" in d["classification"]]
gradual_eps = [d for d in episode_details if "Gradual" in d["classification"]]

print(f"""
KEY FINDINGS:
=============

1. EPISODE COUNT:
   50/50+VT:  {len(episodes_vt)} significant drawdowns (>{DD_THRESHOLD*100:.0f}%)
   50/50 B&H: {len(episodes_bh)} significant drawdowns
   SPY-only:  {len(episodes_spy)} significant drawdowns

2. CLASSIFICATION:
   Equity-Driven: {len(equity_eps)} episodes (SPY crashes, GLD stable)
   Gold-Driven:   {len(gold_eps)} episodes (GLD crashes, SPY stable)
   Both-Crash:    {len(both_crash_eps)} episodes (rare but worst)
   Gradual:       {len(gradual_eps)} episodes (slow erosion)

3. VT EFFECTIVENESS DURING DRAWDOWNS:
   VT helped (reduced DD >0.5%):  {helped}/{len(episode_details)} episodes
   VT hurt (increased DD >0.5%):  {hurt}/{len(episode_details)} episodes
   Neutral:                        {neutral}/{len(episode_details)} episodes

4. WORST CASE:
   Worst 50/50+VT drawdown: {min(d['max_dd_vt'] for d in episode_details):.1f}%
   Worst 50/50 B&H drawdown: {min(d['max_dd_bh'] for d in episode_details):.1f}%
   Worst SPY drawdown: {min(d['max_dd_spy'] for d in episode_details):.1f}%

5. LONGEST UNDERWATER:
   50/50+VT:  {max_underwater} days ({max_underwater/30.44:.1f} months)

6. PSYCHOLOGICAL BURDEN:
   Worst month (VT): {monthly_ret['ret_5050vt'].min()*100:.2f}%
   Worst quarter (VT): {quarterly_ret['ret_5050vt'].min()*100:.2f}%
   Max consecutive losing months (VT): see above
""")

# VT failure modes
print("VT FAILURE MODES:")
print("-" * 60)
worst_vt_diff = max(episode_details, key=lambda d: d["vt_vs_bh_pct"])
best_vt_diff = min(episode_details, key=lambda d: d["vt_vs_bh_pct"])
print(f"  VT worst relative to B&H: Ep{worst_vt_diff['episode']} ({worst_vt_diff['start']}) {worst_vt_diff['vt_vs_bh_pct']:+.2f}%pts")
print(f"  VT best relative to B&H: Ep{best_vt_diff['episode']} ({best_vt_diff['start']}) {best_vt_diff['vt_vs_bh_pct']:+.2f}%pts")

# When does VT fail?
# 1. VT loses when it de-risks before a recovery
# 2. VT loses during low-VIX sudden crashes (weight already = 1)
# 3. VT wins most during high-VIX periods (weight < 1 → less exposure)

low_vix_eps = [d for d in episode_details if d["vix_at_start"] is not None and d["vix_at_start"] < 15]
high_vix_eps = [d for d in episode_details if d["vix_at_start"] is not None and d["vix_at_start"] > 20]

if low_vix_eps:
    avg_vt_impact_low = np.mean([d["vt_vs_bh_pct"] for d in low_vix_eps])
    print(f"\n  Low VIX starts (<15): {len(low_vix_eps)} episodes, avg VT impact = {avg_vt_impact_low:+.2f}%pts")
    print(f"    → VT weight ≈ 1.0 at start, so VT has NO protection margin")

if high_vix_eps:
    avg_vt_impact_high = np.mean([d["vt_vs_bh_pct"] for d in high_vix_eps])
    print(f"  High VIX starts (>20): {len(high_vix_eps)} episodes, avg VT impact = {avg_vt_impact_high:+.2f}%pts")
    print(f"    → VT weight < 1.0, more cash buffer → better protection")


# ==================================================================
# 8. Save Results
# ==================================================================
print("\n" + "=" * 80)
results = {
    "experiment": "K221",
    "title": "Anatomy of Drawdowns — When Does 50/50+VT Fail?",
    "period": f"{merged.index[0].date()} to {merged.index[-1].date()}",
    "n_days": len(merged),
    "dd_threshold_pct": DD_THRESHOLD * 100,
    "episode_count": {
        "50_50_vt": len(episodes_vt),
        "50_50_bh": len(episodes_bh),
        "spy_only": len(episodes_spy),
    },
    "episodes": episode_details,
    "classification_summary": dict(class_counts),
    "vt_impact": {
        "helped": helped,
        "hurt": hurt,
        "neutral": neutral,
        "total": len(episode_details),
    },
    "psychological_metrics": {
        "worst_month_vt_pct": round(float(monthly_ret["ret_5050vt"].min()) * 100, 2),
        "worst_month_bh_pct": round(float(monthly_ret["ret_5050bh"].min()) * 100, 2),
        "worst_month_spy_pct": round(float(monthly_ret["ret_spy"].min()) * 100, 2),
        "worst_quarter_vt_pct": round(float(quarterly_ret["ret_5050vt"].min()) * 100, 2),
        "worst_quarter_bh_pct": round(float(quarterly_ret["ret_5050bh"].min()) * 100, 2),
        "worst_quarter_spy_pct": round(float(quarterly_ret["ret_spy"].min()) * 100, 2),
        "longest_underwater_vt_days": max_underwater,
        "monthly_win_rate_vt_pct": round(float((monthly_ret["ret_5050vt"] > 0).mean()) * 100, 1),
        "monthly_win_rate_bh_pct": round(float((monthly_ret["ret_5050bh"] > 0).mean()) * 100, 1),
    },
    "annual_returns": {
        str(yr.year): {
            "vt": round(float(annual_ret["ret_5050vt"].get(yr, np.nan)) * 100, 2),
            "bh": round(float(annual_ret["ret_5050bh"].get(yr, np.nan)) * 100, 2),
            "spy": round(float(annual_ret["ret_spy"].get(yr, np.nan)) * 100, 2),
        }
        for yr in annual_ret["ret_5050vt"].index
    },
}

# Save JSON results
out_path = "experiments/k221_drawdown_anatomy_results.json"
with open(out_path, "w") as f:
    json.dump(results, f, indent=2, default=str)
print(f"Results saved to {out_path}")
print("=" * 80)
