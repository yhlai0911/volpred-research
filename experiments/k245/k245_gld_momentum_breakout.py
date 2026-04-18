"""
K245: GLD Momentum Breakout Strategy — Can Gold Trends Generate Alpha?
======================================================================
Background: K203 found GLD momentum partial r=0.39 (Harvey pass t=6.5) for
vol prediction. K204 showed this doesn't translate to VT alpha. This experiment
tests GLD momentum as a DIRECT trading signal (not vol predictor).

Data: GLD, SPY, VIX daily from yfinance, 2005-2024.

Signals:
  1. 12-1 month return > 0 (classic TSMOM)
  2. 52-week high breakout: price > 95% of 252-day high
  3. Golden cross: 50d MA > 200d MA
  4. Dual momentum (Antonacci): GLD 12m ret > T-bill AND GLD 12m ret > SPY 12m ret

For each signal, two variants:
  a. GLD-only: long GLD when signal positive, cash (SHY) otherwise
  b. Rotation: long GLD when signal positive, long SPY when negative

Benchmarks: GLD B&H, SPY B&H, 50/50 SPY/GLD

Metrics: Sharpe, MDD, Calmar, win rate (annual)
Statistical: 5-period cross-OOS, DM test, Harvey threshold (t>3.0)
Transaction costs: 0bps, 5bps, 10bps

[提出: User, 執行: Claude]
"""

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
import json
from datetime import datetime

# ============================================================
# 1. Download data
# ============================================================
print("=" * 70)
print("K245: GLD Momentum Breakout Strategy")
print("=" * 70)

print("\n[1/8] Downloading data from yfinance...")

START = "2004-01-01"  # extra lookback for 252-day signals
END = "2025-01-01"

tickers = {"GLD": "GLD", "SPY": "SPY", "^VIX": "VIX", "SHY": "SHY"}
raw_data = {}
for tk, name in tickers.items():
    raw = yf.download(tk, start=START, end=END, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    col = "Adj Close" if "Adj Close" in raw.columns else "Close"
    if name == "VIX":
        col = "Close"
    raw_data[name] = raw[col].copy()
    print(f"  {tk}: {len(raw)} rows, {raw.index[0].date()} ~ {raw.index[-1].date()}")

# Build aligned DataFrame
df = pd.DataFrame(raw_data)
df = df.dropna()
print(f"\n  Aligned dataset: {len(df)} rows, {df.index[0].date()} ~ {df.index[-1].date()}")

# Returns
gld_ret = df["GLD"].pct_change()
spy_ret = df["SPY"].pct_change()
shy_ret = df["SHY"].pct_change()

# Analysis period starts 2005-11-18 (GLD inception + 252d lookback)
ANALYSIS_START = "2005-11-01"
ANALYSIS_END = "2024-12-31"

# ============================================================
# 2. Build momentum signals (daily)
# ============================================================
print("\n[2/8] Building momentum signals...")

# Signal 1: 12-1 month return > 0 (using ~252 and ~21 trading days)
gld_ret_12m = df["GLD"].pct_change(252)
gld_ret_1m = df["GLD"].pct_change(21)
sig_tsmom = (gld_ret_12m - gld_ret_1m) > 0  # 12-1 month momentum

# Signal 2: 52-week high breakout (price > 95% of 252-day rolling max)
rolling_high = df["GLD"].rolling(252).max()
sig_breakout = df["GLD"] > (0.95 * rolling_high)

# Signal 3: Golden cross (50d MA > 200d MA)
ma50 = df["GLD"].rolling(50).mean()
ma200 = df["GLD"].rolling(200).mean()
sig_golden = ma50 > ma200

# Signal 4: Dual momentum (Antonacci)
# GLD 12m ret > T-bill proxy (SHY 12m ret) AND GLD 12m ret > SPY 12m ret
spy_ret_12m = df["SPY"].pct_change(252)
shy_ret_12m = df["SHY"].pct_change(252)
sig_dual = (gld_ret_12m > shy_ret_12m) & (gld_ret_12m > spy_ret_12m)

signals = {
    "TSMOM_12_1": sig_tsmom,
    "Breakout_95": sig_breakout,
    "Golden_Cross": sig_golden,
    "Dual_Mom": sig_dual,
}

# Restrict to analysis period
mask = (df.index >= ANALYSIS_START) & (df.index <= ANALYSIS_END)
for k in signals:
    signals[k] = signals[k].loc[mask]

gld_ret_a = gld_ret.loc[mask]
spy_ret_a = spy_ret.loc[mask]
shy_ret_a = shy_ret.loc[mask]

print(f"  Analysis period: {gld_ret_a.index[0].date()} ~ {gld_ret_a.index[-1].date()}")
print(f"  Trading days: {len(gld_ret_a)}")
for name, sig in signals.items():
    pct_on = sig.sum() / len(sig) * 100
    print(f"  {name}: signal ON {pct_on:.1f}% of days")

# ============================================================
# 3. Strategy construction
# ============================================================
print("\n[3/8] Constructing strategies...")

def calc_strategy_returns(signal, gld_ret, spy_ret, shy_ret, mode="gld_only", tc_bps=0):
    """
    mode='gld_only': long GLD when signal=True, cash (SHY) otherwise
    mode='rotation': long GLD when signal=True, long SPY when signal=False
    tc_bps: round-trip transaction cost in basis points per trade
    """
    sig = signal.astype(float)
    sig_prev = sig.shift(1).fillna(0)  # use previous day signal (no lookahead)

    if mode == "gld_only":
        strat_ret = sig_prev * gld_ret + (1 - sig_prev) * shy_ret
    else:  # rotation
        strat_ret = sig_prev * gld_ret + (1 - sig_prev) * spy_ret

    # Transaction costs on signal changes
    if tc_bps > 0:
        trades = (sig_prev.diff().abs()).fillna(0)
        tc = trades * (tc_bps / 10000)
        strat_ret = strat_ret - tc

    return strat_ret.dropna()

# Build all strategies
strategies = {}
for sig_name, sig in signals.items():
    for mode in ["gld_only", "rotation"]:
        for tc in [0, 5, 10]:
            key = f"{sig_name}_{mode}_tc{tc}"
            strategies[key] = calc_strategy_returns(sig, gld_ret_a, spy_ret_a, shy_ret_a, mode, tc)

# Benchmarks
benchmarks = {
    "GLD_BH": gld_ret_a,
    "SPY_BH": spy_ret_a,
    "50_50_BH": 0.5 * gld_ret_a + 0.5 * spy_ret_a,
}

all_strats = {**benchmarks, **strategies}

print(f"  Built {len(strategies)} strategy variants + {len(benchmarks)} benchmarks")

# ============================================================
# 4. Performance metrics
# ============================================================
print("\n[4/8] Computing performance metrics...")

def compute_metrics(returns):
    """Compute standard performance metrics."""
    r = returns.dropna()
    if len(r) < 252:
        return {}
    ann_ret = r.mean() * 252
    ann_vol = r.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    cum = (1 + r).cumprod()
    rolling_max = cum.cummax()
    drawdown = (cum - rolling_max) / rolling_max
    mdd = drawdown.min()

    calmar = ann_ret / abs(mdd) if mdd != 0 else 0

    # Annual returns
    annual = r.groupby(r.index.year).apply(lambda x: (1 + x).prod() - 1)
    win_years = (annual > 0).sum()
    total_years = len(annual)
    win_rate = win_years / total_years if total_years > 0 else 0
    worst_year = annual.min()
    best_year = annual.max()

    # Sortino
    downside = r[r < 0].std() * np.sqrt(252)
    sortino = ann_ret / downside if downside > 0 else 0

    return {
        "ann_ret": ann_ret,
        "ann_vol": ann_vol,
        "sharpe": sharpe,
        "mdd": mdd,
        "calmar": calmar,
        "sortino": sortino,
        "win_rate": win_rate,
        "worst_year": worst_year,
        "best_year": best_year,
        "n_years": total_years,
    }

# Full period metrics
full_metrics = {}
for name, ret in all_strats.items():
    full_metrics[name] = compute_metrics(ret)

# Print summary table (0bps TC only + benchmarks)
print("\n" + "=" * 100)
print("FULL PERIOD RESULTS (0bps TC)")
print("=" * 100)
print(f"{'Strategy':<30} {'AnnRet':>8} {'AnnVol':>8} {'Sharpe':>8} {'MDD':>8} {'Calmar':>8} {'Sortino':>8} {'WinRate':>8}")
print("-" * 100)

display_order = list(benchmarks.keys())
for sig_name in signals:
    display_order.append(f"{sig_name}_gld_only_tc0")
    display_order.append(f"{sig_name}_rotation_tc0")

for name in display_order:
    m = full_metrics.get(name, {})
    if not m:
        continue
    print(f"{name:<30} {m['ann_ret']:>7.1%} {m['ann_vol']:>7.1%} {m['sharpe']:>8.3f} "
          f"{m['mdd']:>7.1%} {m['calmar']:>8.3f} {m['sortino']:>8.3f} {m['win_rate']:>7.0%}")

# ============================================================
# 5. Transaction cost sensitivity
# ============================================================
print("\n" + "=" * 100)
print("TRANSACTION COST SENSITIVITY (Sharpe ratio)")
print("=" * 100)
print(f"{'Strategy':<30} {'0bps':>8} {'5bps':>8} {'10bps':>8} {'Turnover':>10}")
print("-" * 80)

for sig_name in signals:
    for mode in ["gld_only", "rotation"]:
        s0 = full_metrics.get(f"{sig_name}_{mode}_tc0", {}).get("sharpe", 0)
        s5 = full_metrics.get(f"{sig_name}_{mode}_tc5", {}).get("sharpe", 0)
        s10 = full_metrics.get(f"{sig_name}_{mode}_tc10", {}).get("sharpe", 0)

        # Compute annual turnover
        sig = signals[sig_name].astype(float)
        sig_prev = sig.shift(1).fillna(0)
        trades_per_day = sig_prev.diff().abs().mean()
        annual_turnover = trades_per_day * 252

        label = f"{sig_name}_{mode}"
        print(f"{label:<30} {s0:>8.3f} {s5:>8.3f} {s10:>8.3f} {annual_turnover:>9.1f}x")

# ============================================================
# 6. 5-Period Cross-OOS validation
# ============================================================
print("\n" + "=" * 100)
print("5-PERIOD CROSS-OOS VALIDATION")
print("=" * 100)

# Split analysis period into 5 roughly equal sub-periods
dates = gld_ret_a.dropna().index
n = len(dates)
period_size = n // 5
periods = []
for i in range(5):
    start_idx = i * period_size
    end_idx = (i + 1) * period_size if i < 4 else n
    p_start = dates[start_idx]
    p_end = dates[end_idx - 1]
    periods.append((p_start, p_end))
    print(f"  Period {i+1}: {p_start.date()} ~ {p_end.date()} ({end_idx - start_idx} days)")

# Test best strategies across OOS periods
# For each period, compute metrics using the rest as "in-sample" calibration
# But since these are fixed-rule strategies, we just test each period independently
print(f"\n{'Strategy':<30}", end="")
for i in range(5):
    print(f" {'P' + str(i+1) + '_Sh':>8}", end="")
print(f" {'Mean':>8} {'Std':>8} {'Min':>8} {'t-stat':>8} {'Pass?':>6}")
print("-" * 110)

oos_results = {}
# Focus on 0bps TC strategies
key_strategies = []
for sig_name in signals:
    for mode in ["gld_only", "rotation"]:
        key_strategies.append(f"{sig_name}_{mode}_tc0")

# Add benchmarks
for bm in benchmarks:
    key_strategies.append(bm)

for strat_name in key_strategies:
    ret = all_strats[strat_name].dropna()
    period_sharpes = []

    for p_start, p_end in periods:
        p_ret = ret.loc[(ret.index >= p_start) & (ret.index <= p_end)]
        if len(p_ret) > 60:
            s = p_ret.mean() / p_ret.std() * np.sqrt(252) if p_ret.std() > 0 else 0
        else:
            s = np.nan
        period_sharpes.append(s)

    valid = [s for s in period_sharpes if not np.isnan(s)]
    mean_sh = np.mean(valid) if valid else 0
    std_sh = np.std(valid, ddof=1) if len(valid) > 1 else 0
    min_sh = np.min(valid) if valid else 0
    t_stat = mean_sh / (std_sh / np.sqrt(len(valid))) if std_sh > 0 else 0
    passes = "YES" if t_stat > 3.0 else "no"

    oos_results[strat_name] = {
        "period_sharpes": period_sharpes,
        "mean": mean_sh,
        "std": std_sh,
        "min": min_sh,
        "t_stat": t_stat,
        "passes_harvey": t_stat > 3.0,
    }

    print(f"{strat_name:<30}", end="")
    for s in period_sharpes:
        print(f" {s:>8.3f}" if not np.isnan(s) else f" {'N/A':>8}", end="")
    print(f" {mean_sh:>8.3f} {std_sh:>8.3f} {min_sh:>8.3f} {t_stat:>8.2f} {passes:>6}")

# ============================================================
# 7. DM test vs benchmarks
# ============================================================
print("\n" + "=" * 100)
print("DIEBOLD-MARIANO TEST vs BENCHMARKS")
print("=" * 100)

def dm_test(e1, e2, h=1):
    """
    Diebold-Mariano test. e1, e2 are loss series (negative returns = loss).
    H0: equal predictive accuracy.
    We use squared loss (returns^2 as proxy for utility loss).
    Positive t -> e2 has larger loss (strategy 1 is better).
    """
    d = e1 - e2  # loss differential
    d = d.dropna()
    n = len(d)
    if n < 30:
        return np.nan, np.nan

    mean_d = d.mean()
    # HAC variance (Newey-West with h-1 lags)
    gamma_0 = np.var(d, ddof=1)
    var_d = gamma_0
    for k in range(1, h):
        gamma_k = np.cov(d[k:].values, d[:-k].values)[0, 1]
        var_d += 2 * gamma_k

    se = np.sqrt(var_d / n)
    t_stat = mean_d / se if se > 0 else 0
    p_val = 2 * (1 - stats.norm.cdf(abs(t_stat)))
    return t_stat, p_val

# Use negative cumulative return as "loss" — we want to test if strategy
# generates higher mean returns than benchmark
print(f"\n{'Strategy':<30} {'vs GLD_BH':>12} {'p-val':>8} {'vs SPY_BH':>12} {'p-val':>8} {'vs 50/50':>12} {'p-val':>8}")
print("-" * 100)

bm_gld = -gld_ret_a.dropna()  # negative returns as loss
bm_spy = -spy_ret_a.dropna()
bm_5050 = -(0.5 * gld_ret_a + 0.5 * spy_ret_a).dropna()

for sig_name in signals:
    for mode in ["gld_only", "rotation"]:
        strat_name = f"{sig_name}_{mode}_tc0"
        strat_ret = strategies[strat_name]
        strat_loss = -strat_ret.dropna()

        # Align
        common_idx = strat_loss.index.intersection(bm_gld.index)

        t1, p1 = dm_test(bm_gld.loc[common_idx], strat_loss.loc[common_idx])
        t2, p2 = dm_test(bm_spy.loc[common_idx], strat_loss.loc[common_idx])

        common_idx2 = strat_loss.index.intersection(bm_5050.index)
        t3, p3 = dm_test(bm_5050.loc[common_idx2], strat_loss.loc[common_idx2])

        sig1 = "***" if p1 < 0.01 else "**" if p1 < 0.05 else "*" if p1 < 0.1 else ""
        sig2 = "***" if p2 < 0.01 else "**" if p2 < 0.05 else "*" if p2 < 0.1 else ""
        sig3 = "***" if p3 < 0.01 else "**" if p3 < 0.05 else "*" if p3 < 0.1 else ""

        label = f"{sig_name}_{mode}"
        print(f"{label:<30} {t1:>8.2f}{sig1:<4} {p1:>8.4f} {t2:>8.2f}{sig2:<4} {p2:>8.4f} {t3:>8.2f}{sig3:<4} {p3:>8.4f}")

# ============================================================
# 8. Regime analysis (VIX)
# ============================================================
print("\n" + "=" * 100)
print("REGIME ANALYSIS: STRATEGY PERFORMANCE BY VIX REGIME")
print("=" * 100)

vix_a = df["VIX"].loc[mask]
vix_med = vix_a.median()
vix_75 = vix_a.quantile(0.75)

regimes = {
    f"Low VIX (<{vix_med:.0f})": vix_a < vix_med,
    f"High VIX (>={vix_med:.0f})": vix_a >= vix_med,
    f"Crisis VIX (>={vix_75:.0f})": vix_a >= vix_75,
}

print(f"\nVIX median: {vix_med:.1f}, 75th pctile: {vix_75:.1f}")
print(f"\n{'Strategy':<30}", end="")
for regime_name in regimes:
    print(f" {regime_name:>20}", end="")
print()
print("-" * 95)

display_strats = list(benchmarks.keys())
for sig_name in signals:
    display_strats.append(f"{sig_name}_gld_only_tc0")
    display_strats.append(f"{sig_name}_rotation_tc0")

for strat_name in display_strats:
    ret = all_strats[strat_name].dropna()
    print(f"{strat_name:<30}", end="")
    for regime_name, regime_mask in regimes.items():
        common = ret.index.intersection(regime_mask[regime_mask].index)
        r_regime = ret.loc[common]
        if len(r_regime) > 60:
            sh = r_regime.mean() / r_regime.std() * np.sqrt(252)
            print(f" {sh:>20.3f}", end="")
        else:
            print(f" {'N/A':>20}", end="")
    print()

# ============================================================
# 9. Year-by-year breakdown for best strategies
# ============================================================
print("\n" + "=" * 100)
print("YEAR-BY-YEAR RETURNS: TOP STRATEGIES")
print("=" * 100)

# Identify top strategies by Sharpe
ranked = sorted(
    [(k, v["sharpe"]) for k, v in full_metrics.items() if "_tc0" in k or k in benchmarks],
    key=lambda x: x[1],
    reverse=True
)

top_strats = [r[0] for r in ranked[:6]]
years = sorted(gld_ret_a.dropna().index.year.unique())

print(f"\n{'Year':<6}", end="")
for s in top_strats:
    label = s[:20]
    print(f" {label:>20}", end="")
print()
print("-" * (6 + 21 * len(top_strats)))

for yr in years:
    print(f"{yr:<6}", end="")
    for s in top_strats:
        ret = all_strats[s].dropna()
        yr_ret = ret[ret.index.year == yr]
        if len(yr_ret) > 0:
            annual = (1 + yr_ret).prod() - 1
            print(f" {annual:>19.1%}", end="")
        else:
            print(f" {'N/A':>20}", end="")
    print()

# ============================================================
# 10. Summary and conclusions
# ============================================================
print("\n" + "=" * 70)
print("K245 SUMMARY")
print("=" * 70)

# Find best strategy
best_name = ranked[0][0]
best_sharpe = ranked[0][1]
best_m = full_metrics[best_name]

print(f"\nBest strategy: {best_name}")
print(f"  Sharpe: {best_sharpe:.3f}")
print(f"  Ann. Return: {best_m['ann_ret']:.1%}")
print(f"  MDD: {best_m['mdd']:.1%}")
print(f"  Calmar: {best_m['calmar']:.3f}")

# Compare vs benchmarks
gld_sh = full_metrics["GLD_BH"]["sharpe"]
spy_sh = full_metrics["SPY_BH"]["sharpe"]
mix_sh = full_metrics["50_50_BH"]["sharpe"]
print(f"\nBenchmark Sharpes: GLD={gld_sh:.3f}, SPY={spy_sh:.3f}, 50/50={mix_sh:.3f}")

# Harvey threshold check
print(f"\nHarvey threshold (t>3.0) check:")
for sig_name in signals:
    for mode in ["gld_only", "rotation"]:
        key = f"{sig_name}_{mode}_tc0"
        oos = oos_results.get(key, {})
        t = oos.get("t_stat", 0)
        passes = "PASS" if t > 3.0 else "FAIL"
        sh = full_metrics.get(key, {}).get("sharpe", 0)
        print(f"  {key:<35} Sharpe={sh:.3f}  OOS t={t:.2f}  {passes}")

# Count how many strategies beat benchmarks
print(f"\nStrategies beating SPY B&H (Sharpe {spy_sh:.3f}):")
for sig_name in signals:
    for mode in ["gld_only", "rotation"]:
        key = f"{sig_name}_{mode}_tc0"
        sh = full_metrics.get(key, {}).get("sharpe", 0)
        if sh > spy_sh:
            mdd = full_metrics[key]["mdd"]
            print(f"  {key:<35} Sharpe={sh:.3f}  MDD={mdd:.1%}")

print(f"\nStrategies beating 50/50 B&H (Sharpe {mix_sh:.3f}):")
for sig_name in signals:
    for mode in ["gld_only", "rotation"]:
        key = f"{sig_name}_{mode}_tc0"
        sh = full_metrics.get(key, {}).get("sharpe", 0)
        if sh > mix_sh:
            mdd = full_metrics[key]["mdd"]
            print(f"  {key:<35} Sharpe={sh:.3f}  MDD={mdd:.1%}")

# Key question answer
print("\n" + "=" * 70)
print("KEY FINDING")
print("=" * 70)

# Check if any strategy passes all tests
any_pass_harvey = any(
    oos_results.get(f"{sig}_{mode}_tc0", {}).get("passes_harvey", False)
    for sig in signals for mode in ["gld_only", "rotation"]
)

any_beat_spy = any(
    full_metrics.get(f"{sig}_{mode}_tc0", {}).get("sharpe", 0) > spy_sh
    for sig in signals for mode in ["gld_only", "rotation"]
)

any_beat_5050 = any(
    full_metrics.get(f"{sig}_{mode}_tc0", {}).get("sharpe", 0) > mix_sh
    for sig in signals for mode in ["gld_only", "rotation"]
)

if any_pass_harvey and any_beat_spy:
    print("POSITIVE: Some GLD momentum strategies pass Harvey threshold AND beat SPY.")
    print("GLD trends CAN generate tradeable alpha with simple rules.")
elif any_beat_spy:
    print("MIXED: Some strategies beat SPY on Sharpe, but fail Harvey OOS consistency.")
    print("GLD momentum shows promise but lacks robustness across sub-periods.")
elif any_beat_5050:
    print("WEAK: Some strategies beat 50/50, but none beat SPY consistently.")
    print("GLD momentum adds mild value to a diversified portfolio but no standalone alpha.")
else:
    print("NEGATIVE: No GLD momentum strategy consistently beats simple benchmarks.")
    print("Despite strong trends, timing GLD is harder than buying and holding.")

print(f"\nData source: yfinance (GLD, SPY, ^VIX, SHY)")
print(f"Period: {gld_ret_a.index[0].date()} ~ {gld_ret_a.index[-1].date()}")
print(f"Sample: {len(gld_ret_a)} trading days, ~{len(gld_ret_a)//252} years")
print(f"Limitation: Fixed rules with no optimization; results may differ with")
print(f"  adaptive parameters. SHY used as cash proxy (not true risk-free rate).")
print(f"  No regime-adaptive signal weighting tested.")

print("\n[K245 Complete]")
