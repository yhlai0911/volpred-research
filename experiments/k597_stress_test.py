"""K597: Stress Test All Listed Strategies — Extreme Scenario Analysis

Motivation: Before declaring strategies production-ready, stress test with
worst-case scenarios both from historical data and synthetic edge cases.

Strategies tested (5 core US strategies):
  1. simple_12vix     — 12/VIX SPY-only
  2. vix_cond_leverage — 50/50 SPY/GLD, 12/VIX, VIX<15 → 1.5x leverage
  3. piecewise_conservative — 50/50 SPY/GLD, piecewise VIX ramp-down
  4. fear_dca          — DCA multiplier (VIX>25 → 1.5x, VIX<15 → 0.5x)
  5. adaptive_tier     — Three-regime VIX switching

Scenarios:
  A. Flash Crash (VIX 15→80 in 1 day, like Feb 2018 Volmageddon)
  B. Prolonged Bear (2008-2009 GFC, empirical)
  C. Whipsaw (VIX oscillation 14→26→13→28 over 4 days)
  D. Slow Grind Down (2022-style, VIX elevated but not extreme)
  E. V-shaped Recovery (COVID Mar 2020 crash + Apr-Jun 2020 recovery)

Data source: yfinance (SPY, GLD, ^VIX), 2005-2026
References:
  - K289: Prior stress test (50/50+VT survives all scenarios)
  - K569/K574: Piecewise conservative design
  - K548/K551: VIX conditional leverage
  - K552: Fear DCA
  - K595: Adaptive tier
"""

import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

# ── Helper: compute strategy weight from VIX ─────────────────────────

def compute_weights(strategy: str, vix: float) -> dict:
    """Return {'SPY': w, 'GLD': w, 'cash': w} for a given VIX level."""
    if strategy == "simple_12vix":
        w = min(12.0 / vix, 1.0)
        return {"SPY": w, "GLD": 0.0, "cash": max(0, 1 - w)}

    elif strategy == "vix_cond_leverage":
        base = 12.0 / vix / 2
        lev = 1.5 if vix < 15 else 1.0
        w = min(base * lev, 1.0)
        return {"SPY": w, "GLD": w, "cash": max(0, 1 - 2*w)}

    elif strategy == "piecewise_conservative":
        if vix < 12:
            pw = 1.0
        elif vix <= 20:
            pw = (20 - vix) / 8
        else:
            pw = 0.0
        spy = 0.5 * pw
        gld = 0.5 * pw
        return {"SPY": spy, "GLD": gld, "cash": max(0, 1 - spy - gld)}

    elif strategy == "fear_dca":
        # Signal-only: multiplier on monthly DCA amount
        if vix > 25:
            mult = 1.5
        elif vix < 15:
            mult = 0.5
        else:
            mult = 1.0
        # For backtest: treat as SPY weight * multiplier on base 60% allocation
        w = 0.6 * mult
        return {"SPY": w, "GLD": 0.0, "cash": max(0, 1 - w)}

    elif strategy == "adaptive_tier":
        if vix < 15:
            base = 12.0 / vix / 2
            w = min(base * 1.5, 1.0)
        elif vix <= 20:
            w = 12.0 / vix / 2
        else:
            w = 0.0
        return {"SPY": w, "GLD": w, "cash": max(0, 1 - 2*w)}

    elif strategy == "buy_and_hold":
        return {"SPY": 0.5, "GLD": 0.5, "cash": 0.0}

    raise ValueError(f"Unknown strategy: {strategy}")


def portfolio_return(weights: dict, spy_ret: float, gld_ret: float) -> float:
    """Compute weighted portfolio return."""
    return (weights["SPY"] * spy_ret +
            weights["GLD"] * gld_ret +
            weights["cash"] * 0.0)  # cash = 0 daily return approximation


# ── Data download ────────────────────────────────────────────────────

print("Downloading data from yfinance...")
spy = yf.download("SPY", start="2005-01-01", end="2026-12-31", auto_adjust=True, progress=False)
gld = yf.download("GLD", start="2005-01-01", end="2026-12-31", auto_adjust=True, progress=False)
vix = yf.download("^VIX", start="2005-01-01", end="2026-12-31", auto_adjust=True, progress=False)

# Handle multi-level columns from yfinance
for df_name, df in [("SPY", spy), ("GLD", gld), ("VIX", vix)]:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

# Align dates
common_idx = spy.index.intersection(gld.index).intersection(vix.index)
spy = spy.loc[common_idx].copy()
gld = gld.loc[common_idx].copy()
vix = vix.loc[common_idx].copy()

spy["ret"] = spy["Close"].pct_change()
gld["ret"] = gld["Close"].pct_change()
vix_close = vix["Close"].copy()

print(f"Data: {len(common_idx)} trading days, {common_idx[0].date()} to {common_idx[-1].date()}")
print(f"VIX range: {vix_close.min():.1f} to {vix_close.max():.1f}")

# ── Strategy definitions ─────────────────────────────────────────────

STRATEGIES = [
    "simple_12vix",
    "vix_cond_leverage",
    "piecewise_conservative",
    "fear_dca",
    "adaptive_tier",
]

STRATEGY_NAMES = {
    "simple_12vix": "12/VIX (SPY)",
    "vix_cond_leverage": "VIX 條件槓桿",
    "piecewise_conservative": "保守型 VT (Piecewise)",
    "fear_dca": "恐慌加碼 DCA",
    "adaptive_tier": "自適應三階 VT",
    "buy_and_hold": "Buy & Hold 50/50",
}

# ── Full backtest (compute daily returns for each strategy) ──────────

print("\n=== Full Backtest ===")
strat_returns = {}
strat_weights_history = {}

for strat in STRATEGIES + ["buy_and_hold"]:
    daily_rets = []
    weights_hist = []
    for i in range(1, len(common_idx)):
        v = float(vix_close.iloc[i-1])  # previous day VIX (signal available at close)
        w = compute_weights(strat, v)
        r_spy = float(spy["ret"].iloc[i])
        r_gld = float(gld["ret"].iloc[i])
        pr = portfolio_return(w, r_spy, r_gld)
        daily_rets.append(pr)
        weights_hist.append({"date": str(common_idx[i].date()), "vix": v, **w})

    strat_returns[strat] = pd.Series(daily_rets, index=common_idx[1:])
    strat_weights_history[strat] = weights_hist

# Compute cumulative returns
strat_cum = {}
for strat, rets in strat_returns.items():
    strat_cum[strat] = (1 + rets).cumprod()

# Full-period stats
print(f"\n{'Strategy':<30} {'CAGR':>8} {'Sharpe':>8} {'MDD':>8} {'MaxDDdays':>10}")
print("-" * 70)
full_stats = {}
for strat in STRATEGIES + ["buy_and_hold"]:
    cum = strat_cum[strat]
    rets = strat_returns[strat]
    n_years = len(rets) / 252
    cagr = (cum.iloc[-1]) ** (1 / n_years) - 1
    sharpe = rets.mean() / rets.std() * np.sqrt(252) if rets.std() > 0 else 0
    # Max drawdown
    running_max = cum.cummax()
    dd = (cum - running_max) / running_max
    mdd = dd.min()
    # Max drawdown duration (days)
    underwater = dd < 0
    uw_groups = (~underwater).cumsum()
    if underwater.any():
        dd_durations = underwater.groupby(uw_groups).sum()
        max_dd_days = int(dd_durations.max())
    else:
        max_dd_days = 0

    full_stats[strat] = {
        "cagr": round(float(cagr), 4),
        "sharpe": round(float(sharpe), 3),
        "mdd": round(float(mdd), 4),
        "max_dd_days": max_dd_days,
    }
    print(f"{STRATEGY_NAMES[strat]:<30} {cagr:>7.1%} {sharpe:>8.3f} {mdd:>7.1%} {max_dd_days:>10d}")


# ── Scenario Analysis ────────────────────────────────────────────────

def analyze_scenario(start_date, end_date, label, strat_returns_dict, strat_cum_dict):
    """Analyze strategy performance in a specific date range scenario."""
    results = {}
    for strat in STRATEGIES + ["buy_and_hold"]:
        rets = strat_returns_dict[strat]
        mask = (rets.index >= start_date) & (rets.index <= end_date)
        scenario_rets = rets[mask]
        if len(scenario_rets) == 0:
            results[strat] = {"error": "no data in range"}
            continue

        cum = (1 + scenario_rets).cumprod()
        total_ret = cum.iloc[-1] - 1
        max_1d_loss = scenario_rets.min()

        # 5-day rolling loss
        if len(scenario_rets) >= 5:
            rolling_5d = scenario_rets.rolling(5).sum()
            max_5d_loss = rolling_5d.min()
        else:
            max_5d_loss = scenario_rets.sum()

        # Max drawdown in scenario
        running_max = cum.cummax()
        dd = (cum - running_max) / running_max
        mdd = dd.min()

        # Recovery time: days from max drawdown to new high
        if mdd < 0:
            dd_trough_idx = dd.idxmin()
            post_trough = cum[cum.index >= dd_trough_idx]
            pre_trough_max = running_max[dd_trough_idx]
            recovered = post_trough[post_trough >= pre_trough_max]
            if len(recovered) > 0:
                recovery_days = (recovered.index[0] - dd_trough_idx).days
            else:
                recovery_days = -1  # did not recover within scenario
        else:
            recovery_days = 0

        # Did strategy HELP or HURT vs B&H?
        bh_rets = strat_returns_dict["buy_and_hold"][mask]
        bh_total = (1 + bh_rets).cumprod().iloc[-1] - 1
        bh_max_1d = bh_rets.min()
        relative_return = total_ret - bh_total
        relative_max_1d = max_1d_loss - bh_max_1d  # negative = worse
        helped = "HELPED" if total_ret > bh_total else "HURT"

        results[strat] = {
            "n_days": int(len(scenario_rets)),
            "total_return": round(float(total_ret), 4),
            "max_1d_loss": round(float(max_1d_loss), 4),
            "max_5d_loss": round(float(max_5d_loss), 4),
            "max_drawdown": round(float(mdd), 4),
            "recovery_days": int(recovery_days),
            "vs_bh_return": round(float(relative_return), 4),
            "vs_bh_verdict": helped,
        }

    return results


print("\n" + "=" * 80)
print("SCENARIO A: Flash Crash (Feb 2018 Volmageddon)")
print("=" * 80)
# VIX went from ~11 to 37 on Feb 5, 2018
scenario_a = analyze_scenario("2018-01-26", "2018-03-30", "Flash Crash 2018",
                               strat_returns, strat_cum)
for strat in STRATEGIES:
    s = scenario_a[strat]
    print(f"  {STRATEGY_NAMES[strat]:<30} return={s['total_return']:>+.1%}  "
          f"max1d={s['max_1d_loss']:>+.2%}  max5d={s['max_5d_loss']:>+.2%}  "
          f"MDD={s['max_drawdown']:>+.1%}  recovery={s['recovery_days']}d  "
          f"vs B&H: {s['vs_bh_verdict']} ({s['vs_bh_return']:>+.1%})")

bh = scenario_a["buy_and_hold"]
print(f"  {'B&H 50/50':<30} return={bh['total_return']:>+.1%}  max1d={bh['max_1d_loss']:>+.2%}")


print("\n" + "=" * 80)
print("SCENARIO B: Prolonged Bear (2008 GFC: Sep 2008 - Mar 2009)")
print("=" * 80)
scenario_b = analyze_scenario("2008-09-01", "2009-03-31", "GFC 2008-2009",
                               strat_returns, strat_cum)
for strat in STRATEGIES:
    s = scenario_b[strat]
    print(f"  {STRATEGY_NAMES[strat]:<30} return={s['total_return']:>+.1%}  "
          f"max1d={s['max_1d_loss']:>+.2%}  max5d={s['max_5d_loss']:>+.2%}  "
          f"MDD={s['max_drawdown']:>+.1%}  recovery={s['recovery_days']}d  "
          f"vs B&H: {s['vs_bh_verdict']} ({s['vs_bh_return']:>+.1%})")
bh = scenario_b["buy_and_hold"]
print(f"  {'B&H 50/50':<30} return={bh['total_return']:>+.1%}  max1d={bh['max_1d_loss']:>+.2%}")


print("\n" + "=" * 80)
print("SCENARIO C: Whipsaw (Oct-Dec 2018 — rapid VIX oscillations)")
print("=" * 80)
scenario_c = analyze_scenario("2018-10-01", "2018-12-31", "Whipsaw 2018Q4",
                               strat_returns, strat_cum)
for strat in STRATEGIES:
    s = scenario_c[strat]
    print(f"  {STRATEGY_NAMES[strat]:<30} return={s['total_return']:>+.1%}  "
          f"max1d={s['max_1d_loss']:>+.2%}  max5d={s['max_5d_loss']:>+.2%}  "
          f"MDD={s['max_drawdown']:>+.1%}  recovery={s['recovery_days']}d  "
          f"vs B&H: {s['vs_bh_verdict']} ({s['vs_bh_return']:>+.1%})")
bh = scenario_c["buy_and_hold"]
print(f"  {'B&H 50/50':<30} return={bh['total_return']:>+.1%}  max1d={bh['max_1d_loss']:>+.2%}")


print("\n" + "=" * 80)
print("SCENARIO D: Slow Grind Down (2022 Bear — Jan-Oct 2022)")
print("=" * 80)
scenario_d = analyze_scenario("2022-01-03", "2022-10-31", "2022 Bear",
                               strat_returns, strat_cum)
for strat in STRATEGIES:
    s = scenario_d[strat]
    print(f"  {STRATEGY_NAMES[strat]:<30} return={s['total_return']:>+.1%}  "
          f"max1d={s['max_1d_loss']:>+.2%}  max5d={s['max_5d_loss']:>+.2%}  "
          f"MDD={s['max_drawdown']:>+.1%}  recovery={s['recovery_days']}d  "
          f"vs B&H: {s['vs_bh_verdict']} ({s['vs_bh_return']:>+.1%})")
bh = scenario_d["buy_and_hold"]
print(f"  {'B&H 50/50':<30} return={bh['total_return']:>+.1%}  max1d={bh['max_1d_loss']:>+.2%}")


print("\n" + "=" * 80)
print("SCENARIO E: V-shaped Recovery (COVID Feb-Jun 2020)")
print("=" * 80)
scenario_e = analyze_scenario("2020-02-19", "2020-06-30", "COVID V-Recovery",
                               strat_returns, strat_cum)
for strat in STRATEGIES:
    s = scenario_e[strat]
    print(f"  {STRATEGY_NAMES[strat]:<30} return={s['total_return']:>+.1%}  "
          f"max1d={s['max_1d_loss']:>+.2%}  max5d={s['max_5d_loss']:>+.2%}  "
          f"MDD={s['max_drawdown']:>+.1%}  recovery={s['recovery_days']}d  "
          f"vs B&H: {s['vs_bh_verdict']} ({s['vs_bh_return']:>+.1%})")
bh = scenario_e["buy_and_hold"]
print(f"  {'B&H 50/50':<30} return={bh['total_return']:>+.1%}  max1d={bh['max_1d_loss']:>+.2%}")


# ── Synthetic Scenario: VIX spike 15→80 ──────────────────────────────

print("\n" + "=" * 80)
print("SCENARIO F: SYNTHETIC Flash Crash — VIX 15→80 in 1 day")
print("=" * 80)
# Simulate what weights the strategies would produce at different VIX levels
# and the implied exposure change
print(f"\n{'Strategy':<30} {'VIX=15 wt':>10} {'VIX=80 wt':>10} {'Weight Δ':>10} {'Exposure Cut':>12}")
print("-" * 75)
synth_results = {}
for strat in STRATEGIES:
    w15 = compute_weights(strat, 15.0)
    w80 = compute_weights(strat, 80.0)
    total_w15 = w15["SPY"] + w15["GLD"]
    total_w80 = w80["SPY"] + w80["GLD"]
    delta = total_w80 - total_w15
    cut_pct = (delta / total_w15 * 100) if total_w15 > 0 else 0
    synth_results[strat] = {
        "weight_vix15": round(total_w15, 3),
        "weight_vix80": round(total_w80, 3),
        "weight_delta": round(delta, 3),
        "exposure_cut_pct": round(cut_pct, 1),
    }
    print(f"  {STRATEGY_NAMES[strat]:<30} {total_w15:>9.1%} {total_w80:>9.1%} "
          f"{delta:>+9.1%} {cut_pct:>+10.1f}%")


# ── Adaptive Tier Whipsaw Analysis ───────────────────────────────────

print("\n" + "=" * 80)
print("ADAPTIVE TIER: Regime Switch Analysis")
print("=" * 80)

# Compute regime for each day
regimes = []
for i in range(len(common_idx)):
    v = float(vix_close.iloc[i])
    if v < 15:
        regimes.append("leverage")
    elif v <= 20:
        regimes.append("standard")
    else:
        regimes.append("exit")

regime_series = pd.Series(regimes, index=common_idx)

# Count regime switches per year
switches = (regime_series != regime_series.shift(1)).astype(int)
switches.iloc[0] = 0  # first day is not a switch
yearly_switches = switches.groupby(switches.index.year).sum()

print("\nRegime switches per year:")
for year, count in yearly_switches.items():
    # Distribution of regimes in that year
    year_mask = regime_series.index.year == year
    year_regimes = regime_series[year_mask]
    lev_pct = (year_regimes == "leverage").mean()
    std_pct = (year_regimes == "standard").mean()
    exit_pct = (year_regimes == "exit").mean()
    print(f"  {year}: {int(count):>3d} switches  "
          f"(leverage {lev_pct:.0%}, standard {std_pct:.0%}, exit {exit_pct:.0%})")

total_switches = int(switches.sum())
avg_switches_per_year = total_switches / (len(common_idx) / 252)
print(f"\nTotal switches: {total_switches}, avg per year: {avg_switches_per_year:.1f}")

# Average holding period per regime
holding_periods = {"leverage": [], "standard": [], "exit": []}
current_regime = regimes[0]
current_length = 1
for i in range(1, len(regimes)):
    if regimes[i] == current_regime:
        current_length += 1
    else:
        holding_periods[current_regime].append(current_length)
        current_regime = regimes[i]
        current_length = 1
holding_periods[current_regime].append(current_length)  # last segment

print("\nAverage holding period (trading days):")
for regime, periods in holding_periods.items():
    if periods:
        avg = np.mean(periods)
        med = np.median(periods)
        mn = min(periods)
        mx = max(periods)
        print(f"  {regime:<10}: mean={avg:.1f}d, median={med:.0f}d, "
              f"min={mn}d, max={mx}d, n_episodes={len(periods)}")

# Cost of false regime switches
# A "false switch" = switch to exit that lasts < 5 days and then switches back
false_exits = 0
exit_episodes = holding_periods["exit"]
short_exits = [p for p in exit_episodes if p <= 5]
false_exits = len(short_exits)
print(f"\nFalse exit episodes (≤5 days): {false_exits}/{len(exit_episodes)} "
      f"({false_exits/len(exit_episodes)*100:.0f}% of exits)" if exit_episodes else
      "\nNo exit episodes found")

# Cost analysis: what return did we miss during short exit episodes?
# Identify short exit episodes in the time series
missed_returns = []
current_regime = regimes[0]
episode_start = 0
for i in range(1, len(regimes)):
    if regimes[i] != current_regime:
        if current_regime == "exit" and (i - episode_start) <= 5:
            # This was a false exit — calculate missed return
            episode_spy_rets = spy["ret"].iloc[episode_start:i]
            episode_gld_rets = gld["ret"].iloc[episode_start:i]
            # Would have been in standard 12/VIX mode
            avg_vix = float(vix_close.iloc[episode_start:i].mean())
            hypothetical_w = 12.0 / avg_vix / 2 if avg_vix > 0 else 0.3
            missed_ret = (episode_spy_rets.sum() * hypothetical_w +
                         episode_gld_rets.sum() * hypothetical_w)
            missed_returns.append(float(missed_ret))
        episode_start = i
        current_regime = regimes[i]

if missed_returns:
    total_missed = sum(missed_returns)
    avg_missed = np.mean(missed_returns)
    print(f"\nCost of false exits: total missed return = {total_missed:+.2%} "
          f"(avg per episode = {avg_missed:+.2%})")
    print(f"  Annualized cost: ~{total_missed / (len(common_idx)/252) * 100:.2f}% per year")
else:
    print("\nNo false exit episodes found — cost = 0")


# ── Synthetic Whipsaw Test ───────────────────────────────────────────

print("\n" + "=" * 80)
print("SYNTHETIC WHIPSAW: VIX = [14, 26, 13, 28] over 4 days")
print("=" * 80)

synth_vix = [14, 26, 13, 28]
synth_spy_rets = [-0.03, 0.02, -0.02, 0.01]  # typical crash-bounce pattern
synth_gld_rets = [0.01, -0.005, 0.005, 0.002]

print(f"\n{'Strategy':<30} {'Day1':>8} {'Day2':>8} {'Day3':>8} {'Day4':>8} {'Total':>8}")
print("-" * 75)

synth_whipsaw_results = {}
for strat in STRATEGIES:
    day_rets = []
    for d in range(4):
        w = compute_weights(strat, synth_vix[d])
        pr = portfolio_return(w, synth_spy_rets[d], synth_gld_rets[d])
        day_rets.append(pr)
    total = sum(day_rets)
    synth_whipsaw_results[strat] = {
        "daily_returns": [round(r, 4) for r in day_rets],
        "total_return": round(total, 4),
    }
    print(f"  {STRATEGY_NAMES[strat]:<30} {day_rets[0]:>+7.2%} {day_rets[1]:>+7.2%} "
          f"{day_rets[2]:>+7.2%} {day_rets[3]:>+7.2%} {total:>+7.2%}")

# B&H comparison
bh_rets = [0.5*synth_spy_rets[d] + 0.5*synth_gld_rets[d] for d in range(4)]
bh_total = sum(bh_rets)
print(f"  {'B&H 50/50':<30} {bh_rets[0]:>+7.2%} {bh_rets[1]:>+7.2%} "
      f"{bh_rets[2]:>+7.2%} {bh_rets[3]:>+7.2%} {bh_total:>+7.2%}")


# ── VIX Sensitivity Curve ────────────────────────────────────────────

print("\n" + "=" * 80)
print("VIX SENSITIVITY: Total equity weight at different VIX levels")
print("=" * 80)

vix_levels = [10, 12, 14, 15, 16, 18, 20, 22, 25, 30, 35, 40, 50, 60, 80]
print(f"\n{'VIX':>5}", end="")
for strat in STRATEGIES:
    print(f"  {STRATEGY_NAMES[strat]:>18}", end="")
print()
print("-" * (5 + 20 * len(STRATEGIES)))

sensitivity_data = {}
for v in vix_levels:
    row = {}
    print(f"{v:>5}", end="")
    for strat in STRATEGIES:
        w = compute_weights(strat, float(v))
        total_w = w["SPY"] + w["GLD"]
        row[strat] = round(total_w, 3)
        print(f"  {total_w:>17.1%}", end="")
    sensitivity_data[v] = row
    print()


# ── Worst Historical Days Analysis ──────────────────────────────────

print("\n" + "=" * 80)
print("WORST 10 DAYS: Strategy returns on SPY's worst days")
print("=" * 80)

# Find the 10 worst days for SPY
worst_10_idx = spy["ret"].nsmallest(10).index

print(f"\n{'Date':<12} {'SPY':>8} {'GLD':>8} {'VIX':>6}", end="")
for strat in STRATEGIES:
    print(f" {STRATEGY_NAMES[strat][:12]:>13}", end="")
print()
print("-" * (40 + 14 * len(STRATEGIES)))

worst_days_data = []
for dt in worst_10_idx:
    spy_r = float(spy.loc[dt, "ret"])
    gld_r = float(gld.loc[dt, "ret"]) if dt in gld.index else 0.0
    v = float(vix_close.loc[dt]) if dt in vix_close.index else 20.0
    # Use previous day VIX for weight (signal delay)
    prev_idx = common_idx.get_loc(dt) - 1
    if prev_idx >= 0:
        v_signal = float(vix_close.iloc[prev_idx])
    else:
        v_signal = v

    day_data = {"date": str(dt.date()), "spy_ret": round(spy_r, 4),
                "gld_ret": round(gld_r, 4), "vix": round(v, 1), "vix_signal": round(v_signal, 1)}
    print(f"  {str(dt.date()):<12} {spy_r:>+7.2%} {gld_r:>+7.2%} {v:>5.1f}", end="")
    for strat in STRATEGIES:
        w = compute_weights(strat, v_signal)
        pr = portfolio_return(w, spy_r, gld_r)
        day_data[strat] = round(pr, 4)
        print(f" {pr:>+12.2%}", end="")
    print()
    worst_days_data.append(day_data)


# ── GFC Deep Dive (day-by-day Sep 2008) ──────────────────────────────

print("\n" + "=" * 80)
print("GFC DEEP DIVE: Week-by-week Sep 15 - Dec 31, 2008")
print("=" * 80)

gfc_start = "2008-09-15"
gfc_end = "2008-12-31"
gfc_mask = (common_idx >= gfc_start) & (common_idx <= gfc_end)
gfc_dates = common_idx[gfc_mask]

# Weekly performance
gfc_weekly = {}
for strat in STRATEGIES + ["buy_and_hold"]:
    rets = strat_returns[strat]
    gfc_rets = rets[(rets.index >= gfc_start) & (rets.index <= gfc_end)]
    weekly = gfc_rets.resample("W").sum()  # approximate weekly returns
    gfc_weekly[strat] = weekly

print(f"\n{'Week':<12}", end="")
for strat in STRATEGIES[:3]:  # show first 3 for width
    print(f" {STRATEGY_NAMES[strat][:15]:>16}", end="")
print(f" {'B&H 50/50':>16}")
print("-" * 80)

for i, (dt, _) in enumerate(gfc_weekly["buy_and_hold"].items()):
    print(f"  {str(dt.date()):<12}", end="")
    for strat in STRATEGIES[:3]:
        val = float(gfc_weekly[strat].iloc[i]) if i < len(gfc_weekly[strat]) else 0
        print(f" {val:>+15.2%}", end="")
    bh_val = float(gfc_weekly["buy_and_hold"].iloc[i])
    print(f" {bh_val:>+15.2%}")


# ── Summary Verdict ──────────────────────────────────────────────────

print("\n" + "=" * 80)
print("FINAL VERDICT: Strategy Stress Test Summary")
print("=" * 80)

scenarios_dict = {
    "A_flash_crash_2018": scenario_a,
    "B_gfc_2008_2009": scenario_b,
    "C_whipsaw_2018q4": scenario_c,
    "D_slow_grind_2022": scenario_d,
    "E_covid_v_recovery": scenario_e,
}

scenario_labels = {
    "A_flash_crash_2018": "Flash Crash",
    "B_gfc_2008_2009": "GFC",
    "C_whipsaw_2018q4": "Whipsaw",
    "D_slow_grind_2022": "2022 Bear",
    "E_covid_v_recovery": "COVID V",
}

# For each strategy: count scenarios where it HELPED vs HURT
verdicts = {}
for strat in STRATEGIES:
    helped = 0
    hurt = 0
    for sc_key, sc_data in scenarios_dict.items():
        if sc_data[strat]["vs_bh_verdict"] == "HELPED":
            helped += 1
        else:
            hurt += 1
    verdicts[strat] = {"helped": helped, "hurt": hurt, "total": helped + hurt}

print(f"\n{'Strategy':<30} {'Helped':>8} {'Hurt':>8} {'Score':>8} {'Verdict':>12}")
print("-" * 70)

strategy_verdicts = {}
for strat in STRATEGIES:
    v = verdicts[strat]
    score = f"{v['helped']}/{v['total']}"
    verdict = "PASS" if v["helped"] >= 3 else ("CAUTION" if v["helped"] >= 2 else "FAIL")
    strategy_verdicts[strat] = {
        "helped": v["helped"],
        "hurt": v["hurt"],
        "verdict": verdict,
    }
    print(f"  {STRATEGY_NAMES[strat]:<30} {v['helped']:>6d} {v['hurt']:>6d} "
          f"{score:>8} {verdict:>12}")


# ── Save Results ─────────────────────────────────────────────────────

results = {
    "experiment_id": "K597",
    "title": "Stress Test All Listed Strategies — Extreme Scenario Analysis",
    "data_source": "yfinance (SPY, GLD, ^VIX)",
    "data_period": f"{common_idx[0].date()} to {common_idx[-1].date()}",
    "n_trading_days": len(common_idx),
    "strategies_tested": list(STRATEGY_NAMES.keys()),
    "full_period_stats": full_stats,
    "scenarios": {
        "A_flash_crash_2018": {
            "description": "Feb 2018 Volmageddon — VIX spike from ~11 to 37",
            "period": "2018-01-26 to 2018-03-30",
            "results": scenario_a,
        },
        "B_gfc_2008_2009": {
            "description": "Global Financial Crisis — Sep 2008 to Mar 2009",
            "period": "2008-09-01 to 2009-03-31",
            "results": scenario_b,
        },
        "C_whipsaw_2018q4": {
            "description": "Whipsaw — Oct-Dec 2018 rapid VIX oscillations",
            "period": "2018-10-01 to 2018-12-31",
            "results": scenario_c,
        },
        "D_slow_grind_2022": {
            "description": "2022 Slow Bear — elevated VIX, gradual decline",
            "period": "2022-01-03 to 2022-10-31",
            "results": scenario_d,
        },
        "E_covid_v_recovery": {
            "description": "COVID V-shaped recovery — Feb-Jun 2020",
            "period": "2020-02-19 to 2020-06-30",
            "results": scenario_e,
        },
    },
    "synthetic_flash_crash": synth_results,
    "synthetic_whipsaw": synth_whipsaw_results,
    "vix_sensitivity": sensitivity_data,
    "adaptive_tier_regime_analysis": {
        "total_switches": total_switches,
        "avg_switches_per_year": round(avg_switches_per_year, 1),
        "yearly_switches": {str(k): int(v) for k, v in yearly_switches.items()},
        "holding_periods": {
            regime: {
                "mean_days": round(np.mean(periods), 1) if periods else 0,
                "median_days": round(float(np.median(periods)), 0) if periods else 0,
                "min_days": min(periods) if periods else 0,
                "max_days": max(periods) if periods else 0,
                "n_episodes": len(periods),
            }
            for regime, periods in holding_periods.items()
        },
        "false_exit_episodes": false_exits,
        "total_exit_episodes": len(exit_episodes) if exit_episodes else 0,
        "missed_return_from_false_exits": round(sum(missed_returns), 4) if missed_returns else 0,
    },
    "worst_10_days": worst_days_data,
    "strategy_verdicts": strategy_verdicts,
    "overall_conclusion": "",  # filled below
    "limitations": [
        "Stress test uses historical data — future crises may be structurally different",
        "VIX signal uses previous day close — intraday crashes not captured",
        "Fear DCA modeled as daily weight adjustment, actual is monthly contribution",
        "Transaction costs not included in scenario analysis",
        "GLD data starts Nov 2004 — pre-GLD era not tested",
    ],
    "references": [
        "K289: Prior stress test (50/50+VT survives all)",
        "K569/K574: Piecewise conservative design",
        "K548/K551: VIX conditional leverage",
        "K552: Fear DCA",
        "K595: Adaptive tier",
    ],
    "timestamp": datetime.now().isoformat(),
}

# Generate overall conclusion
pass_count = sum(1 for v in strategy_verdicts.values() if v["verdict"] == "PASS")
caution_count = sum(1 for v in strategy_verdicts.values() if v["verdict"] == "CAUTION")
fail_count = sum(1 for v in strategy_verdicts.values() if v["verdict"] == "FAIL")

conclusion_parts = []
conclusion_parts.append(f"{pass_count}/5 strategies PASS stress test (helped in ≥3/5 scenarios vs B&H).")
if caution_count:
    conclusion_parts.append(f"{caution_count} strategies CAUTION (helped in 2/5).")
if fail_count:
    conclusion_parts.append(f"{fail_count} strategies FAIL (helped in ≤1/5).")

# Adaptive tier specific finding
conclusion_parts.append(
    f"Adaptive Tier: {avg_switches_per_year:.1f} regime switches/year, "
    f"{false_exits} false exits out of {len(exit_episodes) if exit_episodes else 0} total exits."
)

results["overall_conclusion"] = " ".join(conclusion_parts)

# Save
out_path = Path("experiments/k597_stress_test_results.json")
out_path.write_text(json.dumps(results, indent=2, default=str))
print(f"\n\nResults saved to {out_path}")
print(f"\nOverall conclusion: {results['overall_conclusion']}")
