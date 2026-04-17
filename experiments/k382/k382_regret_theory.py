"""
K382: Regret Theory Application — Optimal VT Under Regret Aversion
====================================================================
[提出: 用戶, 執行: Claude]

Research Question:
  Regret theory (Loomes & Sugden 1982) says investors feel pain from COMPARING
  outcomes to what they COULD HAVE had. A VT investor who reduces equity at
  VIX=25 then sees the market rally feels REGRET. How does this affect optimal VT?

Background:
  - K323-K326: Empirical behavioral analysis of VT barriers
  - K378: CRRA utility (gamma=5) shows VT is welfare-improving
  - K324: ~40% of months VT underperforms B&H → frequent regret episodes
  - K325: Behavioral scorecard

Methodology:
  1. Regret-adjusted utility:
     U_regret = U(VT_return) - k * max(0, BH_return - VT_return)
     k = regret intensity (0 = no regret, 1 = strong regret)
  2. For each k, find optimal K-value in K/VIX allocation
  3. Measure regret frequency and magnitude
  4. Find "regret-minimizing" VT (minimax regret)
  5. Test whether regret theory explains VT abandonment

Data: SPY, GLD, VIX daily from yfinance. 2005-2024.
"""

import sys
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from scipy.optimize import minimize_scalar
from datetime import datetime
import json
import os

np.random.seed(42)

WORKTREE = os.path.dirname(os.path.abspath(__file__))

# ============================================================
# CONFIG
# ============================================================
DATA_START = "2004-01-01"
BACKTEST_START = "2005-01-03"
BACKTEST_END = "2024-12-31"
RF_ANNUAL = 0.02
RF_DAILY = RF_ANNUAL / 252

# K values to test (in K/VIX allocation rule)
K_VALUES = np.arange(4, 25, 1)  # 4 to 24

# Regret intensity parameters
REGRET_K_VALUES = [0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0]

# CRRA risk aversion for base utility
GAMMA = 5  # consistent with K378

# ============================================================
# 1. Download and prepare data
# ============================================================
print("=" * 72)
print("K382: Regret Theory Application — Optimal VT Under Regret Aversion")
print("=" * 72)
print(f"\nStarted: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

print("\n[1/8] Downloading SPY, GLD, and VIX data...")
tickers = {"SPY": "SPY", "GLD": "GLD", "VIX": "^VIX"}
raw_data = {}
for name, ticker in tickers.items():
    df = yf.download(ticker, start=DATA_START, end="2026-12-31",
                     progress=False, auto_adjust=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    raw_data[name] = df[["Close"]].rename(columns={"Close": f"{name.lower()}_close"})

data = raw_data["SPY"].join(raw_data["GLD"], how="inner").join(raw_data["VIX"], how="inner")
data = data.dropna()
data = data.loc[BACKTEST_START:BACKTEST_END]

data["spy_ret"] = data["spy_close"].pct_change()
data["gld_ret"] = data["gld_close"].pct_change()
data = data.dropna()

print(f"  Data range: {data.index[0].date()} to {data.index[-1].date()}")
print(f"  Trading days: {len(data)}")

spy_ret = data["spy_ret"].values
gld_ret = data["gld_ret"].values
vix = data["vix_close"].values
dates = data.index


# ============================================================
# 2. VT strategy builder (K/VIX, lagged weights, 50/50 SPY/GLD)
# ============================================================
def build_vt_strategy(k_val, spy_ret, gld_ret, vix, use_5050=True):
    """
    Build VT strategy with K/VIX equity allocation, lagged weights.
    Returns: daily portfolio returns, daily equity weights.
    """
    n = len(spy_ret)
    weights = np.zeros(n)
    port_ret = np.zeros(n)

    for t in range(1, n):
        # Lagged: use yesterday's VIX to set today's weight
        w_eq = min(k_val / vix[t-1], 1.0)
        weights[t] = w_eq

        if use_5050:
            # 50/50 SPY/GLD within equity allocation
            port_ret[t] = w_eq * (0.5 * spy_ret[t] + 0.5 * gld_ret[t]) + (1 - w_eq) * RF_DAILY
        else:
            port_ret[t] = w_eq * spy_ret[t] + (1 - w_eq) * RF_DAILY

    return port_ret[1:], weights[1:]


def build_bh_strategy(spy_ret, gld_ret, use_5050=True):
    """Buy-and-hold benchmark."""
    if use_5050:
        return 0.5 * spy_ret + 0.5 * gld_ret
    else:
        return spy_ret.copy()


# ============================================================
# 3. Utility functions
# ============================================================
def crra_utility(returns, gamma=GAMMA):
    """CRRA utility: E[W^(1-gamma)/(1-gamma)] using wealth path."""
    wealth = np.cumprod(1 + returns)
    final_w = wealth[-1]
    if gamma == 1:
        return np.log(final_w)
    else:
        return (final_w ** (1 - gamma)) / (1 - gamma)


def crra_daily_utility(r, gamma=GAMMA):
    """Period-by-period CRRA utility for daily return r."""
    w = 1 + r
    w = np.maximum(w, 1e-10)  # avoid zero/negative wealth
    if gamma == 1:
        return np.log(w)
    else:
        return (w ** (1 - gamma)) / (1 - gamma)


def regret_adjusted_utility(vt_ret, bh_ret, k_regret, gamma=GAMMA):
    """
    Regret-adjusted utility (Loomes & Sugden 1982, adapted):
    U_regret = E[u(r_VT)] - k * E[max(0, r_BH - r_VT)]

    This captures the asymmetric pain of seeing the benchmark do better.
    Regret only applies when BH outperforms VT.
    """
    # Base utility: average daily CRRA utility
    u_vt = np.mean(crra_daily_utility(vt_ret, gamma))

    # Regret component: only when BH beats VT
    regret_episodes = np.maximum(0, bh_ret - vt_ret)
    avg_regret = np.mean(regret_episodes)

    return u_vt - k_regret * avg_regret


def modified_regret_utility(vt_ret, bh_ret, k_regret, gamma=GAMMA):
    """
    Bell (1982) / Bleichrodt et al. (2010) variant:
    U = E[u(r_VT) - k * Q(max(0, u(r_BH) - u(r_VT)))]

    where Q is a convex regret function (here Q(x) = x for simplicity).
    This version operates on utility differences, not return differences.
    """
    u_vt = crra_daily_utility(vt_ret, gamma)
    u_bh = crra_daily_utility(bh_ret, gamma)

    regret = np.maximum(0, u_bh - u_vt)
    return np.mean(u_vt) - k_regret * np.mean(regret)


# ============================================================
# 4. Performance metrics
# ============================================================
def calc_metrics(returns):
    """Calculate standard performance metrics."""
    ann_ret = np.mean(returns) * 252
    ann_vol = np.std(returns, ddof=1) * np.sqrt(252)
    sharpe = (ann_ret - RF_ANNUAL) / ann_vol if ann_vol > 0 else 0

    # MDD
    wealth = np.cumprod(1 + returns)
    peak = np.maximum.accumulate(wealth)
    dd = (wealth - peak) / peak
    mdd = np.min(dd)

    return {
        "ann_ret": ann_ret,
        "ann_vol": ann_vol,
        "sharpe": sharpe,
        "mdd": mdd,
        "total_ret": wealth[-1] - 1
    }


# ============================================================
# 5. MAIN ANALYSIS: Optimal K under different regret intensities
# ============================================================
print("\n[2/8] Computing optimal K under different regret intensities...")
print("       (Testing K values from 4 to 24 with regret k from 0 to 2)")

# Build B&H benchmark (50/50 SPY/GLD)
bh_ret_5050 = build_bh_strategy(spy_ret[1:], gld_ret[1:], use_5050=True)
bh_ret_spy = build_bh_strategy(spy_ret[1:], gld_ret[1:], use_5050=False)

results_by_regret = {}
optimal_K_by_regret = {}

for k_regret in REGRET_K_VALUES:
    best_K = None
    best_util = -np.inf
    k_results = []

    for k_val in K_VALUES:
        vt_ret, weights = build_vt_strategy(k_val, spy_ret, gld_ret, vix, use_5050=True)

        # Ensure same length as B&H
        min_len = min(len(vt_ret), len(bh_ret_5050))
        vt_r = vt_ret[:min_len]
        bh_r = bh_ret_5050[:min_len]

        # Regret-adjusted utility
        u_regret = regret_adjusted_utility(vt_r, bh_r, k_regret, GAMMA)

        # Also compute Bell variant
        u_bell = modified_regret_utility(vt_r, bh_r, k_regret, GAMMA)

        # Standard metrics
        metrics = calc_metrics(vt_r)

        # Regret statistics
        regret_days = np.sum(bh_r > vt_r) / len(vt_r) * 100  # % days BH beats VT
        avg_regret_mag = np.mean(np.maximum(0, bh_r - vt_r)) * 252 * 100  # annualized bps
        max_regret = np.max(np.maximum(0, bh_r - vt_r)) * 100  # worst single day

        k_results.append({
            "K": int(k_val),
            "u_regret": u_regret,
            "u_bell": u_bell,
            "sharpe": metrics["sharpe"],
            "mdd": metrics["mdd"],
            "ann_ret": metrics["ann_ret"],
            "regret_freq_pct": regret_days,
            "avg_regret_bps_ann": avg_regret_mag,
            "max_regret_day_pct": max_regret
        })

        if u_regret > best_util:
            best_util = u_regret
            best_K = int(k_val)

    results_by_regret[k_regret] = k_results
    optimal_K_by_regret[k_regret] = best_K

print("\n  Optimal K by regret intensity:")
print(f"  {'Regret k':>10} {'Optimal K':>10} {'Interpretation':>30}")
print(f"  {'─'*10} {'─'*10} {'─'*30}")
for k_regret in REGRET_K_VALUES:
    opt_k = optimal_K_by_regret[k_regret]
    if k_regret == 0:
        interp = "Pure utility maximizer"
    elif k_regret <= 0.5:
        interp = "Moderate regret aversion"
    elif k_regret <= 1.0:
        interp = "Strong regret aversion"
    else:
        interp = "Extreme regret aversion"
    print(f"  {k_regret:>10.2f} {opt_k:>10d} {interp:>30}")

# ============================================================
# 6. Detailed regret analysis for K=12 (standard VT)
# ============================================================
print("\n[3/8] Detailed regret analysis for K=12 (standard VT)...")

vt_ret_12, weights_12 = build_vt_strategy(12, spy_ret, gld_ret, vix, use_5050=True)
min_len = min(len(vt_ret_12), len(bh_ret_5050))
vt_12 = vt_ret_12[:min_len]
bh_50 = bh_ret_5050[:min_len]
# dates alignment: spy_ret starts at index 1 (pct_change drops first),
# build_vt_strategy skips index 0 (lagged), so effective start = dates[2]
# But bh_ret_5050 = spy_ret[1:], also length n-1, starting from dates[1]
# vt_ret from build_vt_strategy: port_ret[1:] starts from index 1 of
# the passed array, which is dates[1] in the original data
# Use dates[1:1+min_len] to align
dates_aligned = dates[1:1+min_len]

# Daily regret
daily_regret = bh_50 - vt_12  # positive = BH did better = regret
regret_mask = daily_regret > 0

print(f"\n  Daily regret analysis (K=12, 50/50 SPY/GLD):")
print(f"  Days VT underperforms B&H: {np.sum(regret_mask)} / {len(daily_regret)} "
      f"({np.sum(regret_mask)/len(daily_regret)*100:.1f}%)")
print(f"  Days VT outperforms B&H:   {np.sum(~regret_mask)} / {len(daily_regret)} "
      f"({np.sum(~regret_mask)/len(daily_regret)*100:.1f}%)")

# Magnitude analysis
regret_when_positive = daily_regret[regret_mask]
rejoice_when_negative = -daily_regret[~regret_mask]

print(f"\n  Regret magnitude (when BH beats VT):")
print(f"    Mean daily:    {np.mean(regret_when_positive)*100:.4f}%")
print(f"    Median daily:  {np.median(regret_when_positive)*100:.4f}%")
print(f"    95th pctile:   {np.percentile(regret_when_positive, 95)*100:.4f}%")
print(f"    Max daily:     {np.max(regret_when_positive)*100:.4f}%")
print(f"    Annualized:    {np.mean(regret_when_positive)*252*100:.2f} bps")

print(f"\n  Rejoice magnitude (when VT beats BH):")
print(f"    Mean daily:    {np.mean(rejoice_when_negative)*100:.4f}%")
print(f"    Median daily:  {np.median(rejoice_when_negative)*100:.4f}%")
print(f"    95th pctile:   {np.percentile(rejoice_when_negative, 95)*100:.4f}%")
print(f"    Max daily:     {np.max(rejoice_when_negative)*100:.4f}%")
print(f"    Annualized:    {np.mean(rejoice_when_negative)*252*100:.2f} bps")

# Asymmetry test: Is regret > rejoice on average? (regret theory prediction)
t_asym, p_asym = stats.ttest_ind(regret_when_positive, rejoice_when_negative)
print(f"\n  Asymmetry test (regret vs rejoice magnitudes):")
print(f"    Mean regret:   {np.mean(regret_when_positive)*100:.4f}%")
print(f"    Mean rejoice:  {np.mean(rejoice_when_negative)*100:.4f}%")
print(f"    t-stat: {t_asym:.3f}, p-value: {p_asym:.4f}")

# ============================================================
# 7. Monthly regret analysis (more realistic evaluation horizon)
# ============================================================
print("\n[4/8] Monthly regret analysis...")

# Aggregate to monthly
monthly_data = pd.DataFrame({
    "vt_ret": vt_12,
    "bh_ret": bh_50
}, index=dates_aligned)
monthly = monthly_data.resample("ME").apply(lambda x: np.prod(1 + x) - 1)

monthly_regret = monthly["bh_ret"] - monthly["vt_ret"]
monthly_regret_mask = monthly_regret > 0

print(f"\n  Monthly regret analysis:")
print(f"  Months VT underperforms B&H: {monthly_regret_mask.sum()} / {len(monthly_regret)} "
      f"({monthly_regret_mask.sum()/len(monthly_regret)*100:.1f}%)")
print(f"  Months VT outperforms B&H:   {(~monthly_regret_mask).sum()} / {len(monthly_regret)} "
      f"({(~monthly_regret_mask).sum()/len(monthly_regret)*100:.1f}%)")

# Monthly magnitude
m_regret_pos = monthly_regret[monthly_regret_mask]
m_rejoice = -monthly_regret[~monthly_regret_mask]

print(f"\n  Monthly regret magnitude:")
print(f"    Mean:    {m_regret_pos.mean()*100:.2f}%")
print(f"    Median:  {m_regret_pos.median()*100:.2f}%")
print(f"    Max:     {m_regret_pos.max()*100:.2f}%")

print(f"\n  Monthly rejoice magnitude:")
print(f"    Mean:    {m_rejoice.mean()*100:.2f}%")
print(f"    Median:  {m_rejoice.median()*100:.2f}%")
print(f"    Max:     {m_rejoice.max()*100:.2f}%")

# ============================================================
# 8. Regret by VIX regime
# ============================================================
print("\n[5/8] Regret by VIX regime...")

vix_aligned = vix[1:min_len+1]
regimes = {
    "Low VIX (<15)": vix_aligned < 15,
    "Normal VIX (15-25)": (vix_aligned >= 15) & (vix_aligned < 25),
    "High VIX (25-35)": (vix_aligned >= 25) & (vix_aligned < 35),
    "Crisis VIX (>=35)": vix_aligned >= 35
}

print(f"\n  {'Regime':<25} {'N days':>8} {'Regret %':>10} {'Avg Regret':>12} {'Avg Rejoice':>13}")
print(f"  {'─'*25} {'─'*8} {'─'*10} {'─'*12} {'─'*13}")

regime_regret_data = {}
for regime_name, mask in regimes.items():
    if mask.sum() == 0:
        continue
    regime_daily_regret = daily_regret[mask]
    regime_regret_pct = (regime_daily_regret > 0).sum() / len(regime_daily_regret) * 100
    avg_reg = np.mean(np.maximum(0, regime_daily_regret)) * 100
    avg_rej = np.mean(np.maximum(0, -regime_daily_regret)) * 100

    regime_regret_data[regime_name] = {
        "n_days": int(mask.sum()),
        "regret_pct": regime_regret_pct,
        "avg_regret_bps": avg_reg * 100,
        "avg_rejoice_bps": avg_rej * 100
    }

    print(f"  {regime_name:<25} {mask.sum():>8d} {regime_regret_pct:>9.1f}% "
          f"{avg_reg:>11.4f}% {avg_rej:>12.4f}%")

# ============================================================
# 9. Minimax regret VT (find K that minimizes maximum regret)
# ============================================================
print("\n[6/8] Minimax regret analysis...")

minimax_results = []
for k_val in K_VALUES:
    vt_ret_k, _ = build_vt_strategy(k_val, spy_ret, gld_ret, vix, use_5050=True)
    min_len_k = min(len(vt_ret_k), len(bh_ret_5050))
    vt_k = vt_ret_k[:min_len_k]
    bh_k = bh_ret_5050[:min_len_k]

    # Max single-day regret
    max_daily_regret = np.max(np.maximum(0, bh_k - vt_k))

    # Max monthly regret
    monthly_k = pd.DataFrame({
        "vt": vt_k, "bh": bh_k
    }, index=dates_aligned[:min_len_k])
    monthly_k = monthly_k.resample("ME").apply(lambda x: np.prod(1 + x) - 1)
    max_monthly_regret = np.max(np.maximum(0, monthly_k["bh"] - monthly_k["vt"]))

    # Max annual regret
    annual_k = monthly_k.resample("YE").apply(lambda x: np.prod(1 + x) - 1)
    max_annual_regret = np.max(np.maximum(0, annual_k["bh"] - annual_k["vt"]))

    # Also compute max rejoice (VT beats BH)
    max_monthly_rejoice = np.max(np.maximum(0, monthly_k["vt"] - monthly_k["bh"]))
    max_annual_rejoice = np.max(np.maximum(0, annual_k["vt"] - annual_k["bh"]))

    metrics_k = calc_metrics(vt_k)

    minimax_results.append({
        "K": int(k_val),
        "max_daily_regret_pct": max_daily_regret * 100,
        "max_monthly_regret_pct": max_monthly_regret * 100,
        "max_annual_regret_pct": max_annual_regret * 100,
        "max_monthly_rejoice_pct": max_monthly_rejoice * 100,
        "max_annual_rejoice_pct": max_annual_rejoice * 100,
        "sharpe": metrics_k["sharpe"],
        "mdd": metrics_k["mdd"]
    })

minimax_df = pd.DataFrame(minimax_results)

# Best K for minimax monthly regret
best_minimax_monthly = minimax_df.loc[minimax_df["max_monthly_regret_pct"].idxmin()]
best_minimax_annual = minimax_df.loc[minimax_df["max_annual_regret_pct"].idxmin()]

print(f"\n  Minimax regret results:")
print(f"  {'K':>5} {'Max Day Reg':>12} {'Max Mo Reg':>12} {'Max Yr Reg':>12} "
      f"{'Max Mo Rej':>12} {'Max Yr Rej':>12} {'Sharpe':>8} {'MDD':>8}")
print(f"  {'─'*5} {'─'*12} {'─'*12} {'─'*12} {'─'*12} {'─'*12} {'─'*8} {'─'*8}")

for _, row in minimax_df.iterrows():
    marker = " *" if row["K"] == best_minimax_monthly["K"] else ""
    print(f"  {row['K']:>5.0f} {row['max_daily_regret_pct']:>11.3f}% "
          f"{row['max_monthly_regret_pct']:>11.2f}% {row['max_annual_regret_pct']:>11.2f}% "
          f"{row['max_monthly_rejoice_pct']:>11.2f}% {row['max_annual_rejoice_pct']:>11.2f}% "
          f"{row['sharpe']:>7.3f} {row['mdd']:>7.1f}%{marker}")

print(f"\n  * Best minimax-monthly K = {best_minimax_monthly['K']:.0f}")
print(f"    Best minimax-annual K  = {best_minimax_annual['K']:.0f}")

# ============================================================
# 10. Regret-modified Sharpe (penalize for tracking error regret)
# ============================================================
print("\n[7/8] Regret-modified Sharpe ratios...")

print(f"\n  {'K':>5}", end="")
for k_regret in REGRET_K_VALUES:
    print(f"  {'k='+str(k_regret):>10}", end="")
print(f"  {'Sharpe':>8}")
print(f"  {'─'*5}", end="")
for _ in REGRET_K_VALUES:
    print(f"  {'─'*10}", end="")
print(f"  {'─'*8}")

regret_sharpe_data = {}
for k_val in [8, 10, 12, 14, 16, 18, 20, 24]:
    vt_ret_k, _ = build_vt_strategy(k_val, spy_ret, gld_ret, vix, use_5050=True)
    min_len_k = min(len(vt_ret_k), len(bh_ret_5050))
    vt_k = vt_ret_k[:min_len_k]
    bh_k = bh_ret_5050[:min_len_k]
    metrics_k = calc_metrics(vt_k)

    print(f"  {k_val:>5d}", end="")
    row_data = {}
    for k_regret in REGRET_K_VALUES:
        # Regret-modified return: penalize mean return by regret
        regret_penalty = k_regret * np.mean(np.maximum(0, bh_k - vt_k)) * 252
        modified_ann_ret = metrics_k["ann_ret"] - regret_penalty
        modified_sharpe = (modified_ann_ret - RF_ANNUAL) / metrics_k["ann_vol"] if metrics_k["ann_vol"] > 0 else 0
        row_data[k_regret] = modified_sharpe
        print(f"  {modified_sharpe:>10.3f}", end="")
    print(f"  {metrics_k['sharpe']:>7.3f}")
    regret_sharpe_data[k_val] = row_data

# ============================================================
# 11. Consecutive regret streaks (abandonment pressure)
# ============================================================
print("\n[8/8] Consecutive regret streak analysis...")

# Monthly streaks
monthly_underperform = (monthly_regret > 0).astype(int)
streaks = []
current_streak = 0
for val in monthly_underperform:
    if val == 1:
        current_streak += 1
    else:
        if current_streak > 0:
            streaks.append(current_streak)
        current_streak = 0
if current_streak > 0:
    streaks.append(current_streak)

streaks = np.array(streaks)

print(f"\n  Monthly underperformance streak analysis:")
print(f"  Total streaks: {len(streaks)}")
print(f"  Mean streak length: {np.mean(streaks):.1f} months")
print(f"  Median streak length: {np.median(streaks):.1f} months")
print(f"  Max streak length: {np.max(streaks)} months")
print(f"  Streaks >= 3 months: {np.sum(streaks >= 3)} ({np.sum(streaks >= 3)/len(streaks)*100:.1f}%)")
print(f"  Streaks >= 6 months: {np.sum(streaks >= 6)} ({np.sum(streaks >= 6)/len(streaks)*100:.1f}%)")
print(f"  Streaks >= 12 months: {np.sum(streaks >= 12)} ({np.sum(streaks >= 12)/len(streaks)*100:.1f}%)")

# What happens AFTER long regret streaks?
print(f"\n  Performance after long regret streaks (>= 3 months):")
months_list = list(monthly_regret.index)
post_streak_returns = []
current_streak = 0
for i, val in enumerate(monthly_underperform):
    if val == 1:
        current_streak += 1
    else:
        if current_streak >= 3 and i < len(monthly_regret):
            # Next 3 months after streak ends
            next_3m = monthly_regret.iloc[i:i+3]
            post_streak_returns.append({
                "streak_end": months_list[i-1] if i > 0 else None,
                "streak_len": current_streak,
                "next_3m_vt_minus_bh": next_3m.mean() if len(next_3m) > 0 else np.nan
            })
        current_streak = 0

if post_streak_returns:
    avg_post = np.nanmean([p["next_3m_vt_minus_bh"] for p in post_streak_returns])
    print(f"  Number of 3+ month regret streaks: {len(post_streak_returns)}")
    print(f"  Avg VT-BH in 3 months after streak: {avg_post*100:.3f}%/month")
    if avg_post < 0:
        print(f"  → VT continues to underperform (regret persists)")
    else:
        print(f"  → VT tends to recover (mean reversion in regret)")

# ============================================================
# 12. Cumulative regret vs cumulative rejoice over time
# ============================================================
print("\n" + "=" * 72)
print("CUMULATIVE REGRET vs REJOICE ANALYSIS")
print("=" * 72)

cum_regret = np.cumsum(np.maximum(0, daily_regret))
cum_rejoice = np.cumsum(np.maximum(0, -daily_regret))

# By year
yearly_data = pd.DataFrame({
    "regret": np.maximum(0, daily_regret),
    "rejoice": np.maximum(0, -daily_regret)
}, index=dates_aligned)
yearly_sums = yearly_data.resample("YE").sum() * 100  # convert to percentage points

print(f"\n  {'Year':>6} {'Cum Regret':>12} {'Cum Rejoice':>13} {'Net':>8} {'Interpretation':>20}")
print(f"  {'─'*6} {'─'*12} {'─'*13} {'─'*8} {'─'*20}")

for idx, row in yearly_sums.iterrows():
    net = row["rejoice"] - row["regret"]
    interp = "VT wins" if net > 0 else "Regret year"
    print(f"  {idx.year:>6d} {row['regret']:>11.2f}% {row['rejoice']:>12.2f}% "
          f"{net:>7.2f}% {interp:>20}")

total_regret = yearly_sums["regret"].sum()
total_rejoice = yearly_sums["rejoice"].sum()
print(f"\n  Total cumulative regret:  {total_regret:.2f}%")
print(f"  Total cumulative rejoice: {total_rejoice:.2f}%")
print(f"  Net (rejoice - regret):   {total_rejoice - total_regret:.2f}%")

regret_years = (yearly_sums["regret"] > yearly_sums["rejoice"]).sum()
rejoice_years = (yearly_sums["rejoice"] > yearly_sums["regret"]).sum()
print(f"  Years dominated by regret:  {regret_years}/{len(yearly_sums)}")
print(f"  Years dominated by rejoice: {rejoice_years}/{len(yearly_sums)}")

# ============================================================
# 13. Does regret theory explain VT abandonment?
# ============================================================
print("\n" + "=" * 72)
print("SYNTHESIS: Does Regret Theory Explain VT Abandonment?")
print("=" * 72)

# Key findings compilation
k12_data = [r for r in results_by_regret[0.0] if r["K"] == 12][0]
opt_k_no_regret = optimal_K_by_regret[0.0]
opt_k_strong = optimal_K_by_regret[1.0]
opt_k_extreme = optimal_K_by_regret[2.0]

print(f"""
  FINDING 1: Optimal K shifts with regret aversion
  ─────────────────────────────────────────────────
  No regret (k=0):     Optimal K = {opt_k_no_regret}
  Moderate (k=0.5):    Optimal K = {optimal_K_by_regret[0.5]}
  Strong (k=1.0):      Optimal K = {opt_k_strong}
  Extreme (k=2.0):     Optimal K = {opt_k_extreme}
  Direction: {'Higher K → less aggressive VT' if opt_k_extreme > opt_k_no_regret else 'Lower K → more aggressive VT' if opt_k_extreme < opt_k_no_regret else 'K unchanged'}

  FINDING 2: Regret frequency is substantial
  ──────────────────────────────────────────
  Daily: VT underperforms B&H {k12_data['regret_freq_pct']:.1f}% of trading days
  Monthly: VT underperforms B&H {monthly_regret_mask.sum()/len(monthly_regret)*100:.1f}% of months
  → Investors face regret episodes {'more often than not' if k12_data['regret_freq_pct'] > 50 else 'frequently but not majority'}

  FINDING 3: Regret streaks create abandonment pressure
  ────────────────────────────────────────────────────
  Max consecutive months of underperformance: {np.max(streaks)}
  Streaks >= 6 months: {np.sum(streaks >= 6)}
  → {'Long streaks likely trigger abandonment' if np.max(streaks) >= 6 else 'Streaks are manageable'}

  FINDING 4: Minimax regret strategy
  ──────────────────────────────────
  Minimax-monthly K = {best_minimax_monthly['K']:.0f} (vs standard K=12)
  Minimax-annual K  = {best_minimax_annual['K']:.0f}
  → {'More conservative than K=12' if best_minimax_monthly['K'] < 12 else 'Similar to or more aggressive than K=12'}

  FINDING 5: Net regret accounting
  ───────────────────────────────
  Total cumulative regret:  {total_regret:.1f}%
  Total cumulative rejoice: {total_rejoice:.1f}%
  Net balance: {'Rejoice wins overall' if total_rejoice > total_regret else 'Regret wins overall'}
  But: Regret years = {regret_years}/{len(yearly_sums)} ({regret_years/len(yearly_sums)*100:.0f}%)
""")

# ============================================================
# 14. SPY-only version (compare with 50/50)
# ============================================================
print("=" * 72)
print("ROBUSTNESS: SPY-only VT (no GLD diversification)")
print("=" * 72)

bh_ret_spy_only = build_bh_strategy(spy_ret[1:], gld_ret[1:], use_5050=False)

spy_optimal_by_regret = {}
for k_regret in [0.0, 0.5, 1.0, 2.0]:
    best_K = None
    best_util = -np.inf

    for k_val in K_VALUES:
        vt_ret_k, _ = build_vt_strategy(k_val, spy_ret, gld_ret, vix, use_5050=False)
        min_len_k = min(len(vt_ret_k), len(bh_ret_spy_only))
        vt_k = vt_ret_k[:min_len_k]
        bh_k = bh_ret_spy_only[:min_len_k]

        u_regret = regret_adjusted_utility(vt_k, bh_k, k_regret, GAMMA)
        if u_regret > best_util:
            best_util = u_regret
            best_K = int(k_val)

    spy_optimal_by_regret[k_regret] = best_K

print(f"\n  Optimal K (SPY-only):")
print(f"  {'Regret k':>10} {'Optimal K (5050)':>18} {'Optimal K (SPY)':>17}")
print(f"  {'─'*10} {'─'*18} {'─'*17}")
for k_regret in [0.0, 0.5, 1.0, 2.0]:
    print(f"  {k_regret:>10.1f} {optimal_K_by_regret[k_regret]:>18d} "
          f"{spy_optimal_by_regret[k_regret]:>17d}")

# ============================================================
# 15. Statistical tests
# ============================================================
print("\n" + "=" * 72)
print("STATISTICAL VALIDATION")
print("=" * 72)

# Test: Is the average regret significantly different from zero?
avg_daily_regret_all = daily_regret.mean()
se_daily = daily_regret.std() / np.sqrt(len(daily_regret))
t_regret_zero = avg_daily_regret_all / se_daily
p_regret_zero = 2 * stats.t.sf(abs(t_regret_zero), len(daily_regret) - 1)

print(f"\n  Test 1: Is mean daily (BH - VT) significantly different from zero?")
print(f"  Mean daily BH - VT: {avg_daily_regret_all*100:.5f}%")
print(f"  t-stat: {t_regret_zero:.3f}, p-value: {p_regret_zero:.4f}")
if p_regret_zero < 0.05:
    if avg_daily_regret_all > 0:
        print(f"  → Significant: BH tends to outperform VT on average daily basis")
    else:
        print(f"  → Significant: VT tends to outperform BH on average daily basis")
else:
    print(f"  → Not significant: no systematic daily advantage")

# Bootstrap test: Is optimal K under regret significantly different from K=12?
print(f"\n  Test 2: Bootstrap stability of optimal K under regret k=1.0")
n_boot = 5000
boot_optimal_K = []
for b in range(n_boot):
    # Block bootstrap (blocks of 21 days = 1 month)
    block_size = 21
    n_blocks = len(vt_12) // block_size
    block_indices = np.random.randint(0, n_blocks, size=n_blocks)
    boot_idx = np.concatenate([np.arange(i*block_size, (i+1)*block_size) for i in block_indices])
    boot_idx = boot_idx[:len(vt_12)]

    boot_vt = vt_12[boot_idx]
    boot_bh = bh_50[boot_idx]

    best_K_boot = None
    best_util_boot = -np.inf

    for k_val in [8, 10, 12, 14, 16, 18, 20]:
        vt_k_boot, _ = build_vt_strategy(k_val, spy_ret, gld_ret, vix, use_5050=True)
        min_len_boot = min(len(vt_k_boot), len(bh_ret_5050))
        vt_kb = vt_k_boot[:min_len_boot]
        bh_kb = bh_ret_5050[:min_len_boot]

        # Use same bootstrap indices
        idx_clip = boot_idx[boot_idx < min_len_boot]
        if len(idx_clip) == 0:
            continue
        u_b = regret_adjusted_utility(vt_kb[idx_clip], bh_kb[idx_clip], 1.0, GAMMA)
        if u_b > best_util_boot:
            best_util_boot = u_b
            best_K_boot = k_val

    if best_K_boot is not None:
        boot_optimal_K.append(best_K_boot)

boot_optimal_K = np.array(boot_optimal_K)
print(f"  Bootstrap optimal K distribution (k=1.0, {n_boot} iterations):")
print(f"  Mean: {np.mean(boot_optimal_K):.1f}")
print(f"  Std:  {np.std(boot_optimal_K):.1f}")
print(f"  95% CI: [{np.percentile(boot_optimal_K, 2.5):.0f}, {np.percentile(boot_optimal_K, 97.5):.0f}]")
for kv in sorted(set(boot_optimal_K)):
    pct = (boot_optimal_K == kv).sum() / len(boot_optimal_K) * 100
    print(f"    K={kv}: {pct:.1f}%")

# ============================================================
# 16. Save results
# ============================================================
print("\n" + "=" * 72)
print("SAVING RESULTS")
print("=" * 72)

results = {
    "experiment": "K382",
    "title": "Regret Theory Application — Optimal VT Under Regret Aversion",
    "attribution": "[提出: 用戶, 執行: Claude]",
    "data": {
        "source": "yfinance (SPY, GLD, ^VIX)",
        "period": f"{data.index[0].date()} to {data.index[-1].date()}",
        "trading_days": len(data),
        "methodology": "Regret-adjusted CRRA utility (Loomes & Sugden 1982)"
    },
    "optimal_K_by_regret": {str(k): v for k, v in optimal_K_by_regret.items()},
    "optimal_K_spy_only": {str(k): v for k, v in spy_optimal_by_regret.items()},
    "regret_frequency": {
        "daily_pct": float(k12_data["regret_freq_pct"]),
        "monthly_pct": float(monthly_regret_mask.sum()/len(monthly_regret)*100)
    },
    "regret_magnitude": {
        "avg_daily_regret_pct": float(np.mean(regret_when_positive) * 100),
        "avg_daily_rejoice_pct": float(np.mean(rejoice_when_negative) * 100),
        "avg_monthly_regret_pct": float(m_regret_pos.mean() * 100),
        "avg_monthly_rejoice_pct": float(m_rejoice.mean() * 100)
    },
    "minimax": {
        "minimax_monthly_K": int(best_minimax_monthly["K"]),
        "minimax_annual_K": int(best_minimax_annual["K"]),
        "minimax_monthly_max_regret_pct": float(best_minimax_monthly["max_monthly_regret_pct"])
    },
    "streaks": {
        "max_consecutive_months_underperform": int(np.max(streaks)),
        "mean_streak_length": float(np.mean(streaks)),
        "streaks_ge_6_months": int(np.sum(streaks >= 6)),
        "streaks_ge_3_months": int(np.sum(streaks >= 3))
    },
    "cumulative_balance": {
        "total_regret_pct": float(total_regret),
        "total_rejoice_pct": float(total_rejoice),
        "net_pct": float(total_rejoice - total_regret),
        "regret_years": int(regret_years),
        "total_years": int(len(yearly_sums))
    },
    "statistical_tests": {
        "mean_daily_bh_minus_vt_pct": float(avg_daily_regret_all * 100),
        "t_stat": float(t_regret_zero),
        "p_value": float(p_regret_zero),
        "bootstrap_optimal_K_mean": float(np.mean(boot_optimal_K)),
        "bootstrap_optimal_K_std": float(np.std(boot_optimal_K)),
        "bootstrap_95ci": [float(np.percentile(boot_optimal_K, 2.5)),
                          float(np.percentile(boot_optimal_K, 97.5))]
    },
    "regime_regret": regime_regret_data,
    "regret_sharpe_table": {str(k): v for k, v in regret_sharpe_data.items()},
    "yearly_regret_rejoice": {
        str(idx.year): {"regret": float(row["regret"]), "rejoice": float(row["rejoice"])}
        for idx, row in yearly_sums.iterrows()
    }
}

output_path = os.path.join(WORKTREE, "k382_regret_theory_results.json")
with open(output_path, "w") as f:
    json.dump(results, f, indent=2, default=str)
print(f"  Results saved to: {output_path}")

print(f"\nCompleted: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 72)
