#!/usr/bin/env python3
"""
K654: Why Piecewise Conservative Dominates — A Decomposition

Motivation: Piecewise Conservative is Pareto dominant across nearly all analyses:
  K640 (live Sharpe 3.98), K643 (beats all combos), K647 (all profiles #1),
  K648 (7.7% monthly loss rate).  K653 showed VIX-reactive deviations from
  12/VIX actually HELP.  This experiment decomposes *why* it works so well.

Piecewise Conservative rules (from daily_update.py):
  VIX < 12  → w = 1.0  (fully invested, 50/50 SPY/GLD)
  12 ≤ VIX ≤ 20 → w = (20 - VIX) / 8  (linear ramp-down)
  VIX > 20  → w = 0.0  (fully cash)

Data source: yfinance (SPY, GLD, ^VIX), 2006-01-01 to 2026-03-27
References:
  - K569: Piecewise VT validation (6/8 pass, GFC MDD -0.56%)
  - K574: Piecewise calibration (Sharpe 1.875, MDD -4.9%)
  - K640: Live performance audit (Piecewise Sharpe 3.98)
  - K643: Multi-strategy portfolio (single best beats combos)
  - K653: VIX-reactive deviations help
"""

import json
import sys
import warnings
from datetime import datetime, timezone

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────────────────
# 1. DATA
# ─────────────────────────────────────────────────────────
print("=" * 70)
print("K654: Why Piecewise Conservative Dominates — A Decomposition")
print("=" * 70)

try:
    import yfinance as yf
except ImportError:
    print("ERROR: yfinance not installed")
    sys.exit(1)

START = "2006-01-01"
END = "2026-03-27"

print(f"\nDownloading SPY, GLD, ^VIX ({START} to {END})...")
tickers = ["SPY", "GLD", "^VIX"]
data = yf.download(tickers, start=START, end=END, auto_adjust=True, progress=False)

# Extract close prices
spy_close = data["Close"]["SPY"].dropna()
gld_close = data["Close"]["GLD"].dropna()
vix_close = data["Close"]["^VIX"].dropna()

# Align dates
common_idx = spy_close.index.intersection(gld_close.index).intersection(vix_close.index)
spy_close = spy_close.loc[common_idx]
gld_close = gld_close.loc[common_idx]
vix_close = vix_close.loc[common_idx]

print(f"  Common trading days: {len(common_idx)}")
print(f"  Date range: {common_idx[0].strftime('%Y-%m-%d')} to {common_idx[-1].strftime('%Y-%m-%d')}")

# Daily returns
spy_ret = spy_close.pct_change().dropna()
gld_ret = gld_close.pct_change().dropna()
vix = vix_close.loc[spy_ret.index]

# 50/50 benchmark
bench_ret = 0.5 * spy_ret + 0.5 * gld_ret

print(f"  Return days: {len(spy_ret)}")
print(f"  VIX range: {vix.min():.2f} — {vix.max():.2f}")

# ─────────────────────────────────────────────────────────
# 2. PIECEWISE CONSERVATIVE WEIGHT FUNCTION
# ─────────────────────────────────────────────────────────
def piecewise_weight(vix_val, low=12.0, high=20.0):
    """Piecewise linear weight: 1.0 below low, 0.0 above high, linear between."""
    if vix_val < low:
        return 1.0
    elif vix_val <= high:
        return (high - vix_val) / (high - low)
    else:
        return 0.0

# Previous day's VIX determines today's weight (no look-ahead)
vix_prev = vix.shift(1).dropna()
common = spy_ret.index.intersection(vix_prev.index)
spy_r = spy_ret.loc[common]
gld_r = gld_ret.loc[common]
bench_r = bench_ret.loc[common]
vix_p = vix_prev.loc[common]

weights = vix_p.apply(piecewise_weight)
pw_ret = weights * (0.5 * spy_r + 0.5 * gld_r)  # invested portion earns 50/50

n_days = len(pw_ret)
print(f"\n  Analysis days (with lag-1 VIX): {n_days}")

# ─────────────────────────────────────────────────────────
# 3. REGIME DEFINITIONS
# ─────────────────────────────────────────────────────────
regimes = {
    "Calm (VIX<12)":     vix_p < 12,
    "Normal (12-15)":    (vix_p >= 12) & (vix_p < 15),
    "Elevated (15-20)":  (vix_p >= 15) & (vix_p < 20),
    "High (20-25)":      (vix_p >= 20) & (vix_p < 25),
    "Very High (25-30)": (vix_p >= 25) & (vix_p < 30),
    "Crisis (VIX≥30)":   vix_p >= 30,
}

print("\n" + "=" * 70)
print("3. REGIME STATISTICS")
print("=" * 70)

regime_stats = {}
for name, mask in regimes.items():
    n = mask.sum()
    pct = n / n_days * 100

    # Benchmark (always 50/50) stats in this regime
    b_mean = bench_r[mask].mean() * 252 * 100  # annualized %
    b_std = bench_r[mask].std() * np.sqrt(252) * 100
    b_total = bench_r[mask].sum() * 100  # total cumulative contribution

    # SPY only stats
    s_mean = spy_r[mask].mean() * 252 * 100
    s_total = spy_r[mask].sum() * 100

    # Piecewise stats
    p_mean = pw_ret[mask].mean() * 252 * 100
    p_total = pw_ret[mask].sum() * 100

    # Average weight in regime
    w_avg = weights[mask].mean()

    regime_stats[name] = {
        "n_days": int(n),
        "pct_days": round(pct, 1),
        "avg_weight": round(w_avg, 3),
        "bench_ann_ret_pct": round(b_mean, 2),
        "bench_ann_vol_pct": round(b_std, 2),
        "bench_cum_contrib_pct": round(b_total, 2),
        "spy_ann_ret_pct": round(s_mean, 2),
        "spy_cum_contrib_pct": round(s_total, 2),
        "pw_ann_ret_pct": round(p_mean, 2),
        "pw_cum_contrib_pct": round(p_total, 2),
    }

    print(f"\n  {name}:")
    print(f"    Days: {n} ({pct:.1f}%),  Avg weight: {w_avg:.3f}")
    print(f"    50/50 ann ret: {b_mean:+.2f}%,  ann vol: {b_std:.2f}%")
    print(f"    50/50 cum contrib: {b_total:+.2f}%,  SPY cum: {s_total:+.2f}%")
    print(f"    Piecewise ann ret: {p_mean:+.2f}%,  cum contrib: {p_total:+.2f}%")

# ─────────────────────────────────────────────────────────
# 4. THE KEY QUESTION: LOSSES AVOIDED vs GAINS MISSED
# ─────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("4. LOSSES AVOIDED vs GAINS MISSED (VIX ≥ 20 zone)")
print("=" * 70)

mask_high = vix_p >= 20  # Piecewise = 0% invested
mask_low = vix_p < 12    # Piecewise = 100% invested
mask_mid = (vix_p >= 12) & (vix_p < 20)  # Partial

n_high = mask_high.sum()
n_low = mask_low.sum()
n_mid = mask_mid.sum()

# In VIX≥20 zone: what did 50/50 earn?
bench_high = bench_r[mask_high]
spy_high = spy_r[mask_high]

high_total_bench = bench_high.sum() * 100
high_pos_days = (bench_high > 0).sum()
high_neg_days = (bench_high < 0).sum()
high_pos_sum = bench_high[bench_high > 0].sum() * 100
high_neg_sum = bench_high[bench_high < 0].sum() * 100

print(f"\n  VIX ≥ 20 zone ({n_high} days, {n_high/n_days*100:.1f}% of sample):")
print(f"    50/50 total return in zone: {high_total_bench:+.2f}%")
print(f"    Positive days: {high_pos_days} ({high_pos_days/n_high*100:.1f}%), total: {high_pos_sum:+.2f}%")
print(f"    Negative days: {high_neg_days} ({high_neg_days/n_high*100:.1f}%), total: {high_neg_sum:+.2f}%")
print(f"    Gains MISSED by exiting: {high_pos_sum:+.2f}%")
print(f"    Losses AVOIDED by exiting: {abs(high_neg_sum):+.2f}%")
print(f"    Net benefit of exit: {-high_total_bench:+.2f}%  (losses avoided − gains missed)")

# SPY only in high zone
spy_high_total = spy_high.sum() * 100
spy_high_pos = spy_high[spy_high > 0].sum() * 100
spy_high_neg = spy_high[spy_high < 0].sum() * 100
print(f"\n  SPY only in VIX≥20 zone:")
print(f"    Total: {spy_high_total:+.2f}%")
print(f"    Gains missed: {spy_high_pos:+.2f}%, Losses avoided: {abs(spy_high_neg):+.2f}%")
print(f"    Net benefit: {-spy_high_total:+.2f}%")

# Breakdown: VIX 20-25 vs 25-30 vs 30+
for sub_name, sub_mask in [("VIX 20-25", (vix_p >= 20) & (vix_p < 25)),
                            ("VIX 25-30", (vix_p >= 25) & (vix_p < 30)),
                            ("VIX ≥ 30", vix_p >= 30)]:
    n_sub = sub_mask.sum()
    if n_sub == 0:
        continue
    b_sub = bench_r[sub_mask]
    b_sub_total = b_sub.sum() * 100
    b_sub_avg = b_sub.mean() * 252 * 100
    b_sub_vol = b_sub.std() * np.sqrt(252) * 100
    sharpe_sub = b_sub_avg / b_sub_vol if b_sub_vol > 0 else 0
    print(f"\n    {sub_name} ({n_sub} days, {n_sub/n_days*100:.1f}%):")
    print(f"      50/50 cum: {b_sub_total:+.2f}%, ann ret: {b_sub_avg:+.2f}%, vol: {b_sub_vol:.2f}%")
    print(f"      Sharpe: {sharpe_sub:.3f} — {'NEGATIVE expected return!' if b_sub_avg < 0 else 'Positive but very volatile'}")

# ─────────────────────────────────────────────────────────
# 5. PARTIAL INVESTMENT ZONE (VIX 12-20)
# ─────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("5. PARTIAL INVESTMENT ZONE (VIX 12-20)")
print("=" * 70)

bench_mid = bench_r[mask_mid]
pw_mid = pw_ret[mask_mid]
w_mid = weights[mask_mid]

print(f"  Days: {n_mid} ({n_mid/n_days*100:.1f}%)")
print(f"  Avg weight: {w_mid.mean():.3f}")
print(f"  50/50 cum return: {bench_mid.sum()*100:+.2f}%")
print(f"  Piecewise cum return: {pw_mid.sum()*100:+.2f}%")
print(f"  Return sacrificed by partial exposure: {(bench_mid.sum() - pw_mid.sum())*100:.2f}%")

# Sub-bands within 12-20
for lo, hi in [(12, 14), (14, 16), (16, 18), (18, 20)]:
    band = (vix_p >= lo) & (vix_p < hi)
    n_b = band.sum()
    if n_b == 0:
        continue
    b_b = bench_r[band].sum() * 100
    p_b = pw_ret[band].sum() * 100
    w_b = weights[band].mean()
    print(f"    VIX {lo}-{hi}: {n_b} days, avg w={w_b:.3f}, 50/50={b_b:+.1f}%, PW={p_b:+.1f}%, diff={p_b-b_b:+.1f}%")

# ─────────────────────────────────────────────────────────
# 6. TIMING VALUE ANALYSIS
# ─────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("6. TIMING VALUE (vs static allocations)")
print("=" * 70)

# Average weight over full sample
w_avg_full = weights.mean()
print(f"  Average Piecewise weight: {w_avg_full:.4f}")
print(f"  → Equivalent static allocation: {w_avg_full*50:.1f}% SPY + {w_avg_full*50:.1f}% GLD + {(1-w_avg_full)*100:.1f}% cash")

# Static equivalent: same average equity exposure, no timing
static_equiv_ret = w_avg_full * bench_r

# Timing alpha
timing_alpha = pw_ret - static_equiv_ret
timing_alpha_total = timing_alpha.sum() * 100
timing_alpha_ann = timing_alpha.mean() * 252 * 100

def calc_metrics(returns, name):
    """Calculate Sharpe, CAGR, MDD for a return series."""
    cum = (1 + returns).cumprod()
    n_years = len(returns) / 252
    cagr = (cum.iloc[-1] ** (1 / n_years) - 1) * 100
    ann_ret = returns.mean() * 252 * 100
    ann_vol = returns.std() * np.sqrt(252) * 100
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    drawdown = cum / cum.cummax() - 1
    mdd = drawdown.min() * 100
    # Sortino
    downside = returns[returns < 0].std() * np.sqrt(252) * 100
    sortino = ann_ret / downside if downside > 0 else 0
    return {
        "name": name,
        "cagr_pct": round(cagr, 2),
        "ann_ret_pct": round(ann_ret, 2),
        "ann_vol_pct": round(ann_vol, 2),
        "sharpe": round(sharpe, 3),
        "sortino": round(sortino, 3),
        "mdd_pct": round(mdd, 2),
        "cum_ret_pct": round((cum.iloc[-1] - 1) * 100, 2),
    }

strats = {
    "Piecewise Conservative": pw_ret,
    "Always 50/50 SPY/GLD": bench_r,
    "Static Equiv (same avg exposure)": static_equiv_ret,
    "SPY only (buy & hold)": spy_r,
    "GLD only (buy & hold)": gld_r.loc[common],
}

strat_metrics = {}
print(f"\n  {'Strategy':<35} {'CAGR':>6} {'Sharpe':>7} {'Sortino':>8} {'MDD':>7} {'Vol':>6}")
print(f"  {'-'*35} {'---':>6} {'---':>7} {'---':>8} {'---':>7} {'---':>6}")
for name, ret in strats.items():
    m = calc_metrics(ret, name)
    strat_metrics[name] = m
    print(f"  {name:<35} {m['cagr_pct']:>5.1f}% {m['sharpe']:>7.3f} {m['sortino']:>8.3f} {m['mdd_pct']:>6.1f}% {m['ann_vol_pct']:>5.1f}%")

timing_alpha_detail = {
    "avg_weight": round(w_avg_full, 4),
    "timing_alpha_total_pct": round(timing_alpha_total, 2),
    "timing_alpha_ann_pct": round(timing_alpha_ann, 2),
    "piecewise_sharpe": strat_metrics["Piecewise Conservative"]["sharpe"],
    "static_equiv_sharpe": strat_metrics["Static Equiv (same avg exposure)"]["sharpe"],
    "benchmark_sharpe": strat_metrics["Always 50/50 SPY/GLD"]["sharpe"],
}

print(f"\n  Timing Alpha:")
print(f"    Total cumulative: {timing_alpha_total:+.2f}%")
print(f"    Annualized: {timing_alpha_ann:+.2f}%/yr")
print(f"    Sharpe improvement over static equiv: {strat_metrics['Piecewise Conservative']['sharpe'] - strat_metrics['Static Equiv (same avg exposure)']['sharpe']:+.3f}")
print(f"    Sharpe improvement over 50/50: {strat_metrics['Piecewise Conservative']['sharpe'] - strat_metrics['Always 50/50 SPY/GLD']['sharpe']:+.3f}")

# ─────────────────────────────────────────────────────────
# 7. THRESHOLD SENSITIVITY
# ─────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("7. THRESHOLD SENSITIVITY (varying upper cutoff)")
print("=" * 70)

thresholds_to_test = [15, 16, 17, 18, 19, 20, 22, 25, 30, 35, 50]
threshold_results = {}

print(f"\n  {'Upper Cut':>10} {'CAGR':>6} {'Sharpe':>7} {'Sortino':>8} {'MDD':>7} {'Vol':>6} {'Avg W':>6}")
print(f"  {'---':>10} {'---':>6} {'---':>7} {'---':>8} {'---':>7} {'---':>6} {'---':>6}")

for thresh in thresholds_to_test:
    w_t = vix_p.apply(lambda v: piecewise_weight(v, low=12.0, high=float(thresh)))
    ret_t = w_t * (0.5 * spy_r + 0.5 * gld_r)
    m = calc_metrics(ret_t, f"upper={thresh}")
    avg_w = w_t.mean()
    threshold_results[str(thresh)] = {
        **m,
        "avg_weight": round(avg_w, 4),
    }
    print(f"  {thresh:>10} {m['cagr_pct']:>5.1f}% {m['sharpe']:>7.3f} {m['sortino']:>8.3f} {m['mdd_pct']:>6.1f}% {m['ann_vol_pct']:>5.1f}% {avg_w:>5.3f}")

# Also vary lower threshold
print(f"\n  Varying lower threshold (upper fixed at 20):")
print(f"  {'Lower Cut':>10} {'CAGR':>6} {'Sharpe':>7} {'Sortino':>8} {'MDD':>7} {'Avg W':>6}")
print(f"  {'---':>10} {'---':>6} {'---':>7} {'---':>8} {'---':>7} {'---':>6}")

lower_thresh_results = {}
for lo in [10, 11, 12, 13, 14, 15, 16, 18]:
    w_t = vix_p.apply(lambda v: piecewise_weight(v, low=float(lo), high=20.0))
    ret_t = w_t * (0.5 * spy_r + 0.5 * gld_r)
    m = calc_metrics(ret_t, f"lower={lo}")
    avg_w = w_t.mean()
    lower_thresh_results[str(lo)] = {
        **m,
        "avg_weight": round(avg_w, 4),
    }
    print(f"  {lo:>10} {m['cagr_pct']:>5.1f}% {m['sharpe']:>7.3f} {m['sortino']:>8.3f} {m['mdd_pct']:>6.1f}% {avg_w:>5.3f}")

# ─────────────────────────────────────────────────────────
# 8. COMPARISON WITH OTHER EXIT STRATEGIES
# ─────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("8. COMPARISON WITH ALTERNATIVE EXIT STRATEGIES")
print("=" * 70)

def weight_12vix(vix_val):
    """12/VIX continuous weight (capped at 1.0)."""
    return min(12.0 / vix_val, 1.0) if vix_val > 0 else 1.0

def weight_hard_exit(vix_val, cutoff=20):
    """Hard exit: 100% below cutoff, 0% above."""
    return 1.0 if vix_val < cutoff else 0.0

def weight_gradual_taper(vix_val, start=15, end=30):
    """Linear taper from 100% at start to 0% at end."""
    if vix_val < start:
        return 1.0
    elif vix_val > end:
        return 0.0
    else:
        return (end - vix_val) / (end - start)

alt_strategies = {
    "Piecewise (12→20)": lambda v: piecewise_weight(v, 12, 20),
    "Hard exit VIX=20": lambda v: weight_hard_exit(v, 20),
    "Hard exit VIX=25": lambda v: weight_hard_exit(v, 25),
    "Gradual 15→30": lambda v: weight_gradual_taper(v, 15, 30),
    "Gradual 15→25": lambda v: weight_gradual_taper(v, 15, 25),
    "12/VIX continuous": weight_12vix,
    "Always 50/50": lambda v: 1.0,
}

alt_results = {}
print(f"\n  {'Strategy':<25} {'CAGR':>6} {'Sharpe':>7} {'Sortino':>8} {'MDD':>7} {'Vol':>6} {'Avg W':>6}")
print(f"  {'-'*25} {'---':>6} {'---':>7} {'---':>8} {'---':>7} {'---':>6} {'---':>6}")

for name, wf in alt_strategies.items():
    w_t = vix_p.apply(wf)
    ret_t = w_t * (0.5 * spy_r + 0.5 * gld_r)
    m = calc_metrics(ret_t, name)
    avg_w = w_t.mean()
    alt_results[name] = {
        **m,
        "avg_weight": round(avg_w, 4),
    }
    print(f"  {name:<25} {m['cagr_pct']:>5.1f}% {m['sharpe']:>7.3f} {m['sortino']:>8.3f} {m['mdd_pct']:>6.1f}% {m['ann_vol_pct']:>5.1f}% {avg_w:>5.3f}")

# ─────────────────────────────────────────────────────────
# 9. LOSS AVOIDANCE DECOMPOSITION (KEY ANALYSIS)
# ─────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("9. LOSS AVOIDANCE DECOMPOSITION")
print("=" * 70)

# Total 50/50 return
bench_total = bench_r.sum() * 100

# Piecewise total
pw_total = pw_ret.sum() * 100

# Decompose the difference
# PW - Bench = Σ (w_t - 1) × bench_r_t
# When w=1 (VIX<12): contribution = 0 (same as benchmark)
# When 0<w<1 (12≤VIX<20): contribution = -(1-w) × bench_r (negative when bench is positive)
# When w=0 (VIX≥20): contribution = -bench_r (avoid all of benchmark return)

diff = pw_ret - bench_r  # = (w-1) × bench_r

# Calm zone (VIX<12): no difference
calm_diff = diff[mask_low].sum() * 100

# Transition zone (12-20): partial
mid_diff = diff[mask_mid].sum() * 100
mid_gains_missed = diff[mask_mid & (bench_r > 0)].sum() * 100  # negative
mid_losses_avoided = diff[mask_mid & (bench_r < 0)].sum() * 100  # positive

# High zone (VIX≥20): full avoidance
high_diff = diff[mask_high].sum() * 100
high_gains_missed_d = diff[mask_high & (bench_r > 0)].sum() * 100
high_losses_avoided_d = diff[mask_high & (bench_r < 0)].sum() * 100

print(f"\n  Total 50/50 return: {bench_total:+.2f}%")
print(f"  Total Piecewise return: {pw_total:+.2f}%")
print(f"  Difference (PW - Bench): {pw_total - bench_total:+.2f}%")

print(f"\n  Decomposition of difference:")
print(f"    Calm zone (VIX<12): {calm_diff:+.2f}%  (should be ~0)")
print(f"    Transition zone (12-20): {mid_diff:+.2f}%")
print(f"      Gains missed: {mid_gains_missed:+.2f}%")
print(f"      Losses avoided: {mid_losses_avoided:+.2f}%")
print(f"    High zone (VIX≥20): {high_diff:+.2f}%")
print(f"      Gains missed: {high_gains_missed_d:+.2f}%")
print(f"      Losses avoided: {high_losses_avoided_d:+.2f}%")

# Total decomposition
total_gains_missed = mid_gains_missed + high_gains_missed_d
total_losses_avoided = mid_losses_avoided + high_losses_avoided_d
print(f"\n  Grand total:")
print(f"    Total gains missed: {total_gains_missed:+.2f}%")
print(f"    Total losses avoided: {total_losses_avoided:+.2f}%")
print(f"    Net (should = PW-Bench): {total_gains_missed + total_losses_avoided:+.2f}%")
print(f"    Ratio (losses avoided / gains missed): {abs(total_losses_avoided / total_gains_missed):.2f}x" if total_gains_missed != 0 else "")

loss_avoidance = {
    "bench_total_pct": round(bench_total, 2),
    "pw_total_pct": round(pw_total, 2),
    "difference_pct": round(pw_total - bench_total, 2),
    "calm_diff_pct": round(calm_diff, 2),
    "transition_diff_pct": round(mid_diff, 2),
    "transition_gains_missed_pct": round(mid_gains_missed, 2),
    "transition_losses_avoided_pct": round(mid_losses_avoided, 2),
    "high_diff_pct": round(high_diff, 2),
    "high_gains_missed_pct": round(high_gains_missed_d, 2),
    "high_losses_avoided_pct": round(high_losses_avoided_d, 2),
    "total_gains_missed_pct": round(total_gains_missed, 2),
    "total_losses_avoided_pct": round(total_losses_avoided, 2),
    "avoidance_ratio": round(abs(total_losses_avoided / total_gains_missed), 3) if total_gains_missed != 0 else None,
}

# ─────────────────────────────────────────────────────────
# 10. WORST DRAWDOWN ANALYSIS
# ─────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("10. DRAWDOWN ANALYSIS — KEY CRISIS PERIODS")
print("=" * 70)

crises = {
    "GFC (2008-09 to 2009-03)":    ("2008-09-01", "2009-03-31"),
    "Euro crisis (2011-08 to 2011-10)": ("2011-08-01", "2011-10-31"),
    "China scare (2015-08 to 2015-09)": ("2015-08-01", "2015-09-30"),
    "Volmageddon (2018-02)":        ("2018-02-01", "2018-02-28"),
    "COVID crash (2020-02 to 2020-03)": ("2020-02-15", "2020-03-31"),
    "2022 bear (2022-01 to 2022-10)":   ("2022-01-01", "2022-10-31"),
    "Tariff crash (2025-03)":       ("2025-03-01", "2025-03-27"),
}

crisis_results = {}
for name, (start, end) in crises.items():
    mask_c = (pw_ret.index >= start) & (pw_ret.index <= end)
    if mask_c.sum() == 0:
        continue
    bench_crisis = bench_r[mask_c].sum() * 100
    pw_crisis = pw_ret[mask_c].sum() * 100
    spy_crisis = spy_r[mask_c].sum() * 100
    avg_vix = vix_p[mask_c].mean()
    avg_w = weights[mask_c].mean()
    n_c = mask_c.sum()

    crisis_results[name] = {
        "n_days": int(n_c),
        "avg_vix": round(avg_vix, 1),
        "avg_weight": round(avg_w, 3),
        "spy_return_pct": round(spy_crisis, 2),
        "bench_return_pct": round(bench_crisis, 2),
        "pw_return_pct": round(pw_crisis, 2),
        "protection_pct": round(bench_crisis - pw_crisis, 2),
    }

    print(f"\n  {name} ({n_c} days):")
    print(f"    Avg VIX: {avg_vix:.1f}, Avg weight: {avg_w:.3f}")
    print(f"    SPY: {spy_crisis:+.2f}%, 50/50: {bench_crisis:+.2f}%, Piecewise: {pw_crisis:+.2f}%")
    print(f"    Protection value: {bench_crisis - pw_crisis:+.2f}%")

# ─────────────────────────────────────────────────────────
# 11. ALPHA SOURCE SUMMARY
# ─────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("11. ALPHA SOURCE SUMMARY")
print("=" * 70)

# What % of Piecewise total return comes from each zone?
pw_calm = pw_ret[mask_low].sum() * 100
pw_mid_total = pw_ret[mask_mid].sum() * 100
pw_high_total = pw_ret[mask_high].sum() * 100

print(f"\n  Return contribution by zone (Piecewise):")
print(f"    Calm (VIX<12):    {pw_calm:+.2f}% ({pw_calm/pw_total*100:.1f}% of total)" if pw_total != 0 else "")
print(f"    Transition (12-20): {pw_mid_total:+.2f}% ({pw_mid_total/pw_total*100:.1f}% of total)" if pw_total != 0 else "")
print(f"    High (VIX≥20):    {pw_high_total:+.2f}% ({pw_high_total/pw_total*100:.1f}% of total)" if pw_total != 0 else "")

# Risk-adjusted contribution
pw_calm_vol = pw_ret[mask_low].std() * np.sqrt(252) * 100
pw_mid_vol = pw_ret[mask_mid].std() * np.sqrt(252) * 100
pw_high_vol = pw_ret[mask_high].std() * np.sqrt(252) * 100

print(f"\n  Vol contribution by zone:")
print(f"    Calm:       {pw_calm_vol:.2f}%")
print(f"    Transition: {pw_mid_vol:.2f}%")
print(f"    High:       {pw_high_vol:.2f}% (should be ~0)")

# Monthly loss rate
monthly_ret = pw_ret.resample('ME').sum()
monthly_loss_rate = (monthly_ret < 0).sum() / len(monthly_ret) * 100
monthly_bench_ret = bench_r.resample('ME').sum()
monthly_bench_loss_rate = (monthly_bench_ret < 0).sum() / len(monthly_bench_ret) * 100

print(f"\n  Monthly loss rate:")
print(f"    Piecewise: {monthly_loss_rate:.1f}%")
print(f"    50/50 benchmark: {monthly_bench_loss_rate:.1f}%")
print(f"    Improvement: {monthly_bench_loss_rate - monthly_loss_rate:.1f}pp")

# ─────────────────────────────────────────────────────────
# 12. YEAR-BY-YEAR ANALYSIS
# ─────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("12. YEAR-BY-YEAR PERFORMANCE")
print("=" * 70)

yearly_pw = pw_ret.resample('YE').apply(lambda x: (1 + x).prod() - 1) * 100
yearly_bench = bench_r.resample('YE').apply(lambda x: (1 + x).prod() - 1) * 100
yearly_spy = spy_r.resample('YE').apply(lambda x: (1 + x).prod() - 1) * 100
yearly_avg_w = weights.resample('YE').mean()

yearly_results = {}
print(f"\n  {'Year':<6} {'PW':>7} {'50/50':>7} {'SPY':>7} {'Alpha':>7} {'Avg W':>6}")
print(f"  {'----':<6} {'---':>7} {'---':>7} {'---':>7} {'---':>7} {'---':>6}")
for yr in yearly_pw.index:
    y = yr.year
    pw_y = yearly_pw.loc[yr]
    b_y = yearly_bench.loc[yr]
    s_y = yearly_spy.loc[yr]
    w_y = yearly_avg_w.loc[yr]
    alpha_y = pw_y - b_y
    yearly_results[str(y)] = {
        "pw_pct": round(pw_y, 2),
        "bench_pct": round(b_y, 2),
        "spy_pct": round(s_y, 2),
        "alpha_pct": round(alpha_y, 2),
        "avg_weight": round(w_y, 3),
    }
    print(f"  {y:<6} {pw_y:>6.1f}% {b_y:>6.1f}% {s_y:>6.1f}% {alpha_y:>+6.1f}% {w_y:>5.3f}")

pw_beat = sum(1 for y in yearly_results.values() if y["alpha_pct"] >= 0)
pw_total_years = len(yearly_results)
print(f"\n  PW beats 50/50: {pw_beat}/{pw_total_years} years ({pw_beat/pw_total_years*100:.0f}%)")

# ─────────────────────────────────────────────────────────
# 13. CONDITIONAL EXPECTED RETURN BY VIX LEVEL
# ─────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("13. CONDITIONAL EXPECTED RETURN BY VIX LEVEL")
print("=" * 70)

# Forward 5-day and 21-day returns
fwd_5d = bench_r.rolling(5).sum().shift(-5)
fwd_21d = bench_r.rolling(21).sum().shift(-21)

vix_bins = [0, 12, 15, 18, 20, 22, 25, 30, 40, 100]
vix_labels = ["<12", "12-15", "15-18", "18-20", "20-22", "22-25", "25-30", "30-40", "40+"]
vix_binned = pd.cut(vix_p, bins=vix_bins, labels=vix_labels)

print(f"\n  {'VIX Range':<10} {'N':>5} {'1d avg':>8} {'5d avg':>8} {'21d avg':>9} {'1d vol':>8} {'Sharpe-1d':>10}")
print(f"  {'-'*10} {'---':>5} {'---':>8} {'---':>8} {'---':>9} {'---':>8} {'---':>10}")

cond_return_data = {}
for label in vix_labels:
    mask_vb = vix_binned == label
    n_vb = mask_vb.sum()
    if n_vb < 10:
        continue
    avg_1d = bench_r[mask_vb].mean() * 100
    avg_5d = fwd_5d[mask_vb].mean() * 100 if fwd_5d[mask_vb].notna().sum() > 0 else float('nan')
    avg_21d = fwd_21d[mask_vb].mean() * 100 if fwd_21d[mask_vb].notna().sum() > 0 else float('nan')
    vol_1d = bench_r[mask_vb].std() * 100
    sharpe_1d = (avg_1d / vol_1d) if vol_1d > 0 else 0

    cond_return_data[label] = {
        "n_days": int(n_vb),
        "avg_1d_ret_pct": round(avg_1d, 4),
        "avg_5d_ret_pct": round(avg_5d, 4) if not np.isnan(avg_5d) else None,
        "avg_21d_ret_pct": round(avg_21d, 4) if not np.isnan(avg_21d) else None,
        "vol_1d_pct": round(vol_1d, 4),
        "daily_sharpe": round(sharpe_1d, 4),
    }

    print(f"  {label:<10} {n_vb:>5} {avg_1d:>+7.4f}% {avg_5d:>+7.4f}% {avg_21d:>+8.4f}% {vol_1d:>7.4f}% {sharpe_1d:>+9.4f}")

# ─────────────────────────────────────────────────────────
# 14. FINAL CONCLUSIONS
# ─────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("14. CONCLUSIONS")
print("=" * 70)

print(f"""
  ⚠️ CRITICAL FINDING: INITIAL HYPOTHESIS WAS WRONG

  The VIX≥20 zone does NOT have negative expected return.
  All sub-zones (20-25, 25-30, 30+) show POSITIVE annualized returns.
  Piecewise Conservative UNDERPERFORMS the 50/50 benchmark over 20 years.

  1. PIECEWISE IS A PROTECTION STRATEGY, NOT AN ALPHA STRATEGY
     - CAGR 3.1% vs 50/50 benchmark 11.4% — massive return sacrifice
     - Sharpe 0.610 vs benchmark 0.856 — lower risk-adjusted return too
     - Beats benchmark only 4/21 years (19%)
     - Its "dominance" in K640 (live Sharpe 3.98) was a SHORT-PERIOD artifact

  2. THE VIX≥20 ZONE HAS POSITIVE EXPECTED RETURNS
     - VIX 20-25: ann ret +16.2%, Sharpe 1.21 — quite good!
     - VIX 25-30: ann ret +14.9%, Sharpe 0.92
     - VIX ≥ 30: ann ret +25.0%, Sharpe 0.91 — mean reversion is real
     - Total gains missed by exiting: {high_gains_missed_d:+.1f}%
     - Total losses avoided: {high_losses_avoided_d:+.1f}%
     - NET COST of exit: {high_total_bench:+.1f}% (gains > losses)

  3. WHY IT "LOOKED" DOMINANT IN RECENT PERIOD
     - GFC protection: avoided -11.3% (50/50) / -37.0% (SPY) drawdown
     - COVID protection: avoided -11.4% drawdown
     - 2022 bear: avoided -14.0% drawdown
     - In periods WITH crises, the protection value is enormous
     - But over a full 20-year cycle, missed recoveries dominate

  4. THE TRANSITION ZONE IS COSTLY
     - VIX 12-20 partial exposure sacrifices: {mid_diff:+.1f}%
     - This is 56% of all trading days at reduced exposure
     - Even without crises, the strategy is heavily underinvested

  5. THRESHOLD SENSITIVITY REVEALS THE TRADEOFF
     - Higher threshold (25, 30, 50) → higher Sharpe AND higher CAGR
     - Best Sharpe comes from threshold=50 (essentially never exiting)
     - The "optimal" strategy is closer to always-invested than to Piecewise
     - 12/VIX continuous (Sharpe 0.895) beats Piecewise (0.610) handily

  6. WHEN PIECEWISE IS APPROPRIATE
     - Investors with LOW drawdown tolerance (MDD concern > return concern)
     - Short horizons where a single crisis could be devastating
     - The GFC/COVID protection is real — just comes at a high long-term cost
     - Monthly loss rate improvement: {monthly_bench_loss_rate - monthly_loss_rate:.1f}pp
""")

# ─────────────────────────────────────────────────────────
# SAVE RESULTS
# ─────────────────────────────────────────────────────────

results = {
    "experiment_id": "K654",
    "title": "Why Piecewise Conservative Dominates — A Decomposition",
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "data_source": "yfinance",
    "assets": ["SPY", "GLD", "^VIX"],
    "period": f"{START} to {END}",
    "n_trading_days": n_days,
    "piecewise_rules": {
        "low_threshold": 12,
        "high_threshold": 20,
        "base_allocation": "50/50 SPY/GLD",
        "below_low": "100% invested",
        "between": "linear ramp-down",
        "above_high": "0% invested (cash)",
    },
    "regime_statistics": regime_stats,
    "loss_avoidance_decomposition": loss_avoidance,
    "strategy_metrics": strat_metrics,
    "timing_alpha": timing_alpha_detail,
    "threshold_sensitivity_upper": threshold_results,
    "threshold_sensitivity_lower": lower_thresh_results,
    "alternative_exit_strategies": alt_results,
    "crisis_analysis": crisis_results,
    "yearly_performance": yearly_results,
    "conditional_returns_by_vix": cond_return_data,
    "monthly_loss_rates": {
        "piecewise_pct": round(monthly_loss_rate, 1),
        "benchmark_pct": round(monthly_bench_loss_rate, 1),
        "improvement_pp": round(monthly_bench_loss_rate - monthly_loss_rate, 1),
    },
    "conclusions": {
        "hypothesis_refuted": True,
        "primary_finding": "Piecewise Conservative is a PROTECTION strategy, not an alpha strategy. VIX>=20 zone has POSITIVE expected returns. Long-term underperformance vs benchmark.",
        "pw_cagr_vs_bench": f"{strat_metrics['Piecewise Conservative']['cagr_pct']}% vs {strat_metrics['Always 50/50 SPY/GLD']['cagr_pct']}%",
        "pw_sharpe_vs_bench": f"{strat_metrics['Piecewise Conservative']['sharpe']} vs {strat_metrics['Always 50/50 SPY/GLD']['sharpe']}",
        "vix_ge20_has_positive_returns": True,
        "net_cost_of_exit_pct": loss_avoidance["high_diff_pct"],
        "avoidance_ratio": loss_avoidance["avoidance_ratio"],
        "optimal_upper_threshold_sharpe": max(threshold_results.items(), key=lambda x: x[1]["sharpe"])[0],
        "optimal_upper_threshold_sortino": max(threshold_results.items(), key=lambda x: x[1]["sortino"])[0],
        "timing_alpha_ann_pct": timing_alpha_detail["timing_alpha_ann_pct"],
        "timing_alpha_negative": timing_alpha_detail["timing_alpha_ann_pct"] < 0,
        "pw_beats_benchmark_years": f"{pw_beat}/{pw_total_years}",
        "appropriate_for": "Low drawdown tolerance investors, short horizons, crisis-sensitive portfolios",
        "k640_sharpe_398_explanation": "Short-period artifact — recent period happened to have crises (COVID, 2022 bear) where protection was valuable",
    },
    "references": [
        "K569: Piecewise VT validation",
        "K574: Piecewise calibration",
        "K640: Live performance audit",
        "K643: Multi-strategy portfolio",
        "K647: Strategy matcher",
        "K648: Monthly loss rate",
        "K653: VIX-reactive deviations",
    ],
}

out_path = "experiments/k654_results.json"
with open(out_path, "w") as f:
    json.dump(results, f, indent=2, default=str)
print(f"\n✓ Results saved to {out_path}")
print(f"  Total keys in results: {len(results)}")
