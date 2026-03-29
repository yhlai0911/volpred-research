"""
K697: Is ANY Daily Alpha Possible? — Upper Bound Analysis

Motivation:
K687-K696 showed no VT strategy beats BH 50/50 on Sharpe after lag.
Is this because:
  (a) VT is fundamentally unable to generate alpha, OR
  (b) Our specific VT implementations are suboptimal?

Test: theoretical MAXIMUM Sharpe achievable with a lagged daily signal.

Upper bounds:
1. Perfect foresight (1-day lagged momentum) — weight_t = sign(ret_{t-1})
2. Oracle VIX — ex-post optimal weight per VIX bin, applied with 1-day lag
3. Perfect oracle (no lag) — weight_t = sign(ret_t), impossible but theoretical max
4. BH 50/50 — passive benchmark

Data: SPY, GLD, VIX daily via yfinance (2006-01-01 to 2026-03-27)

References:
- DeMiguel, Garlappi, Uppal (2009) RFS — 1/N benchmark hard to beat
- Kirby & Ostdiek (2012) JFE — volatility timing transaction costs
- Moreira & Muir (2017) JF — volatility managed portfolios
"""

import json
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime

# ── Data ─────────────────────────────────────────────────────────────
print("Downloading data...")
tickers = {"SPY": "SPY", "GLD": "GLD", "VIX": "^VIX"}
data = {}
for name, ticker in tickers.items():
    df = yf.download(ticker, start="2006-01-01", end="2026-03-28", auto_adjust=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    data[name] = df["Close"].rename(name)

prices = pd.DataFrame(data).dropna()
print(f"Data: {prices.index[0].strftime('%Y-%m-%d')} to {prices.index[-1].strftime('%Y-%m-%d')}, {len(prices)} days")

# Returns
ret_spy = prices["SPY"].pct_change()
ret_gld = prices["GLD"].pct_change()
vix = prices["VIX"]

# Drop first row (NaN)
valid = ret_spy.dropna().index
ret_spy = ret_spy.loc[valid]
ret_gld = ret_gld.loc[valid]
vix = vix.loc[valid]

N = len(ret_spy)
print(f"Return series: {N} observations")

# ── Helper: compute strategy stats ──────────────────────────────────
def strategy_stats(weights_spy, ret_spy, ret_gld, name):
    """Compute Sharpe, CAGR, MaxDD, Turnover for a strategy."""
    weights_gld = 1.0 - weights_spy
    port_ret = weights_spy * ret_spy + weights_gld * ret_gld

    # Sharpe (annualized)
    sharpe = port_ret.mean() / port_ret.std() * np.sqrt(252)

    # CAGR
    cumret = (1 + port_ret).cumprod()
    years = len(port_ret) / 252
    cagr = cumret.iloc[-1] ** (1 / years) - 1

    # Max Drawdown
    running_max = cumret.cummax()
    drawdown = (cumret - running_max) / running_max
    max_dd = drawdown.min()

    # Annualized volatility
    ann_vol = port_ret.std() * np.sqrt(252)

    # Daily turnover (absolute weight change)
    turnover = weights_spy.diff().abs().mean() * 252  # annualized

    # Net Sharpe (after 10bps round-trip TX cost)
    tx_cost = 0.001  # 10bps per trade
    daily_tx = weights_spy.diff().abs() * tx_cost
    net_ret = port_ret - daily_tx
    net_sharpe = net_ret.mean() / net_ret.std() * np.sqrt(252)

    return {
        "name": name,
        "sharpe": round(float(sharpe), 4),
        "net_sharpe_10bps": round(float(net_sharpe), 4),
        "cagr": round(float(cagr), 4),
        "ann_vol": round(float(ann_vol), 4),
        "max_dd": round(float(max_dd), 4),
        "turnover_ann": round(float(turnover), 2),
        "mean_weight_spy": round(float(weights_spy.mean()), 4),
    }

# ── Strategy 1: BH 50/50 ────────────────────────────────────────────
print("\n=== BH 50/50 ===")
w_bh = pd.Series(0.5, index=ret_spy.index)
stats_bh = strategy_stats(w_bh, ret_spy, ret_gld, "BH 50/50")
print(f"  Sharpe: {stats_bh['sharpe']}, CAGR: {stats_bh['cagr']:.4f}")

# ── Strategy 2: BH 100% SPY ─────────────────────────────────────────
print("\n=== BH 100% SPY ===")
w_spy100 = pd.Series(1.0, index=ret_spy.index)
stats_spy100 = strategy_stats(w_spy100, ret_spy, ret_gld, "BH 100% SPY")
print(f"  Sharpe: {stats_spy100['sharpe']}, CAGR: {stats_spy100['cagr']:.4f}")

# ── Strategy 3: Perfect Oracle (NO lag) — Theoretical Maximum ────────
print("\n=== Perfect Oracle (NO lag) ===")
# If SPY return > 0, go 100% SPY; otherwise 100% GLD
# Uses SAME-DAY return → impossible in practice
w_oracle = pd.Series(np.where(ret_spy > 0, 1.0, 0.0), index=ret_spy.index)
stats_oracle = strategy_stats(w_oracle, ret_spy, ret_gld, "Perfect Oracle (no lag)")
print(f"  Sharpe: {stats_oracle['sharpe']}, CAGR: {stats_oracle['cagr']:.4f}")
print(f"  SPY up-days: {(ret_spy > 0).sum()}/{N} = {(ret_spy > 0).mean():.1%}")

# ── Strategy 4: Perfect Momentum (1-day lag) ─────────────────────────
print("\n=== Perfect Momentum (1-day lag) ===")
# weight_t = 1.0 if ret_{t-1} > 0, else 0.0
w_mom = pd.Series(np.where(ret_spy.shift(1) > 0, 1.0, 0.0), index=ret_spy.index)
w_mom.iloc[0] = 0.5  # no signal on first day
stats_mom = strategy_stats(w_mom, ret_spy, ret_gld, "Perfect Momentum (1-day lag)")
print(f"  Sharpe: {stats_mom['sharpe']}, CAGR: {stats_mom['cagr']:.4f}")

# ── Strategy 5: Reverse Momentum (contrarian) ───────────────────────
print("\n=== Contrarian (1-day lag) ===")
# weight_t = 0.0 if ret_{t-1} > 0, else 1.0 (buy after down days)
w_contra = pd.Series(np.where(ret_spy.shift(1) > 0, 0.0, 1.0), index=ret_spy.index)
w_contra.iloc[0] = 0.5
stats_contra = strategy_stats(w_contra, ret_spy, ret_gld, "Contrarian (1-day lag)")
print(f"  Sharpe: {stats_contra['sharpe']}, CAGR: {stats_contra['cagr']:.4f}")

# ── Strategy 6: Oracle VIX (1-day lag) ───────────────────────────────
print("\n=== Oracle VIX (1-day lag) ===")
# For each VIX decile, compute the ex-post optimal SPY weight
# Then apply: weight_t = optimal_weight(VIX_{t-1})

vix_lag = vix.shift(1)
vix_lag.iloc[0] = vix.iloc[0]

# Method A: VIX decile bins
n_bins = 20  # finer bins for better fit
vix_bins = pd.qcut(vix_lag, q=n_bins, duplicates="drop")
bin_labels = vix_bins.cat.categories

optimal_weights = {}
for b in bin_labels:
    mask = vix_bins == b
    if mask.sum() < 10:
        continue
    # Find weight that maximizes Sharpe in this bin
    best_w, best_sharpe = 0.5, -999
    for w in np.linspace(0, 1, 101):
        port = w * ret_spy[mask] + (1 - w) * ret_gld[mask]
        if port.std() == 0:
            continue
        sr = port.mean() / port.std() * np.sqrt(252)
        if sr > best_sharpe:
            best_sharpe = sr
            best_w = w
    optimal_weights[b] = best_w

# Apply oracle VIX weights
w_oracle_vix = pd.Series(0.5, index=ret_spy.index)
for b, w in optimal_weights.items():
    mask = vix_bins == b
    w_oracle_vix[mask] = w

stats_oracle_vix = strategy_stats(w_oracle_vix, ret_spy, ret_gld, "Oracle VIX (1-day lag, 20 bins)")
print(f"  Sharpe: {stats_oracle_vix['sharpe']}, CAGR: {stats_oracle_vix['cagr']:.4f}")

# Print optimal weights by VIX bin
print("\n  Optimal weights by VIX bin:")
for b in sorted(optimal_weights.keys(), key=lambda x: x.left):
    mask = vix_bins == b
    print(f"    VIX {b}: w_SPY={optimal_weights[b]:.2f} (n={mask.sum()})")

# ── Strategy 7: Oracle VIX (continuous, 1-day lag) ────────────────────
print("\n=== Oracle VIX Continuous (1-day lag) ===")
# Fit a polynomial: optimal_weight = f(VIX_lag)
# For each VIX level, find the ex-post optimal weight using a smooth function

# Build training data: for small VIX ranges, compute optimal weight
vix_grid = np.percentile(vix_lag.dropna(), np.arange(2.5, 100, 5))
grid_weights = []
for i in range(len(vix_grid)):
    low = vix_grid[i] - (vix_grid[1] - vix_grid[0]) / 2 if i > 0 else 0
    high = vix_grid[i] + (vix_grid[1] - vix_grid[0]) / 2 if i < len(vix_grid) - 1 else 200
    mask = (vix_lag >= low) & (vix_lag < high)
    if mask.sum() < 20:
        continue
    best_w, best_sr = 0.5, -999
    for w in np.linspace(0, 1, 101):
        port = w * ret_spy[mask] + (1 - w) * ret_gld[mask]
        if port.std() == 0:
            continue
        sr = port.mean() / port.std() * np.sqrt(252)
        if sr > best_sr:
            best_sr = sr
            best_w = w
    grid_weights.append((vix_grid[i], best_w))

grid_vix = [g[0] for g in grid_weights]
grid_w = [g[1] for g in grid_weights]

# Fit polynomial
poly_coefs = np.polyfit(grid_vix, grid_w, 3)
poly_fn = np.poly1d(poly_coefs)

w_oracle_vix_cont = poly_fn(vix_lag.values)
w_oracle_vix_cont = np.clip(w_oracle_vix_cont, 0, 1)
w_oracle_vix_cont = pd.Series(w_oracle_vix_cont, index=ret_spy.index)

stats_oracle_vix_cont = strategy_stats(w_oracle_vix_cont, ret_spy, ret_gld, "Oracle VIX Continuous (1-day lag)")
print(f"  Sharpe: {stats_oracle_vix_cont['sharpe']}, CAGR: {stats_oracle_vix_cont['cagr']:.4f}")
print(f"  Polynomial: {' + '.join(f'{c:.6f}*x^{3-i}' for i, c in enumerate(poly_coefs))}")

# ── Strategy 8: Oracle Perfect (both SPY & GLD foresight, no lag) ─────
print("\n=== Perfect Oracle 2-Asset (no lag) ===")
# Pick the BETTER asset each day → true theoretical max for 2-asset switching
w_oracle2 = pd.Series(np.where(ret_spy > ret_gld, 1.0, 0.0), index=ret_spy.index)
stats_oracle2 = strategy_stats(w_oracle2, ret_spy, ret_gld, "Perfect Oracle 2-Asset (no lag)")
print(f"  Sharpe: {stats_oracle2['sharpe']}, CAGR: {stats_oracle2['cagr']:.4f}")

# ── Strategy 9: VIX Threshold Sweep (1-day lag) ──────────────────────
print("\n=== VIX Threshold Sweep (1-day lag) ===")
# Simple rule: if VIX > threshold, go GLD; else go SPY
# Find the best threshold ex-post
best_thresh, best_sharpe = 20, -999
results_sweep = []
for thresh in np.arange(10, 50, 0.5):
    w = pd.Series(np.where(vix_lag > thresh, 0.0, 1.0), index=ret_spy.index)
    port = w * ret_spy + (1 - w) * ret_gld
    sr = port.mean() / port.std() * np.sqrt(252)
    results_sweep.append({"threshold": thresh, "sharpe": round(float(sr), 4)})
    if sr > best_sharpe:
        best_sharpe = sr
        best_thresh = thresh

w_vix_thresh = pd.Series(np.where(vix_lag > best_thresh, 0.0, 1.0), index=ret_spy.index)
stats_vix_thresh = strategy_stats(w_vix_thresh, ret_spy, ret_gld, f"Best VIX Threshold ({best_thresh:.1f})")
print(f"  Best threshold: {best_thresh:.1f}, Sharpe: {stats_vix_thresh['sharpe']}")

# ── Strategy 10: VIX-Scaled (Moreira-Muir style, 1-day lag) ──────────
print("\n=== VIX-Scaled (Moreira-Muir, 1-day lag) ===")
# weight_t = target_vol / VIX_{t-1} (scaled to [0, 1])
# Try different target vols
best_target, best_sr_mm = 15, -999
for target in np.arange(5, 40, 0.5):
    w = target / vix_lag
    w = w.clip(0, 1)
    port = w * ret_spy + (1 - w) * ret_gld
    sr = port.mean() / port.std() * np.sqrt(252)
    if sr > best_sr_mm:
        best_sr_mm = sr
        best_target = target

w_mm = (best_target / vix_lag).clip(0, 1)
stats_mm = strategy_stats(w_mm, ret_spy, ret_gld, f"VIX-Scaled (target={best_target:.1f})")
print(f"  Best target vol: {best_target:.1f}, Sharpe: {stats_mm['sharpe']}")

# ── Summary ──────────────────────────────────────────────────────────
print("\n" + "=" * 80)
print("SUMMARY: Upper Bound Analysis")
print("=" * 80)

all_strategies = [
    stats_bh,
    stats_spy100,
    stats_mom,
    stats_contra,
    stats_vix_thresh,
    stats_mm,
    stats_oracle_vix,
    stats_oracle_vix_cont,
    stats_oracle,
    stats_oracle2,
]

print(f"\n{'Strategy':<42} {'Sharpe':>7} {'NetSR':>7} {'CAGR':>7} {'MaxDD':>8} {'Turn':>6}")
print("-" * 80)
for s in all_strategies:
    print(f"{s['name']:<42} {s['sharpe']:>7.3f} {s['net_sharpe_10bps']:>7.3f} {s['cagr']:>7.3f} {s['max_dd']:>8.3f} {s['turnover_ann']:>6.1f}")

# ── Alpha gaps ───────────────────────────────────────────────────────
print("\n" + "=" * 80)
print("ALPHA GAP ANALYSIS")
print("=" * 80)

bh_sharpe = stats_bh["sharpe"]
oracle_sharpe = stats_oracle["sharpe"]
oracle2_sharpe = stats_oracle2["sharpe"]
oracle_vix_sharpe = stats_oracle_vix["sharpe"]
mom_sharpe = stats_mom["sharpe"]

print(f"\n  Perfect Oracle 2-Asset (no lag):   Sharpe = {oracle2_sharpe:.3f}")
print(f"  Perfect Oracle SPY-only (no lag):  Sharpe = {oracle_sharpe:.3f}")
print(f"  Oracle VIX (1-day lag, 20 bins):   Sharpe = {oracle_vix_sharpe:.3f}")
print(f"  Best VIX threshold (1-day lag):    Sharpe = {stats_vix_thresh['sharpe']:.3f}")
print(f"  VIX-Scaled Moreira-Muir (lag):     Sharpe = {stats_mm['sharpe']:.3f}")
print(f"  Perfect Momentum (1-day lag):      Sharpe = {mom_sharpe:.3f}")
print(f"  BH 50/50:                          Sharpe = {bh_sharpe:.3f}")
print(f"\n  Alpha gap (Oracle VIX vs BH):   {oracle_vix_sharpe - bh_sharpe:+.3f}")
print(f"  Alpha gap (Best VIX thresh vs BH): {stats_vix_thresh['sharpe'] - bh_sharpe:+.3f}")
print(f"  Alpha gap (VIX-Scaled vs BH):   {stats_mm['sharpe'] - bh_sharpe:+.3f}")
print(f"  Alpha gap (Momentum vs BH):     {mom_sharpe - bh_sharpe:+.3f}")
print(f"  Alpha gap (Oracle no-lag vs BH): {oracle_sharpe - bh_sharpe:+.3f}")

# ── Autocorrelation analysis ─────────────────────────────────────────
print("\n" + "=" * 80)
print("WHY LAG KILLS ALPHA — Autocorrelation Analysis")
print("=" * 80)

from scipy import stats as sp_stats

# SPY return autocorrelation
acf_1 = ret_spy.autocorr(lag=1)
acf_5 = ret_spy.autocorr(lag=5)
print(f"\n  SPY return autocorrelation:")
print(f"    lag-1: {acf_1:.4f}")
print(f"    lag-5: {acf_5:.4f}")

# Conditional probability: P(ret_t > 0 | ret_{t-1} > 0)
up_after_up = ((ret_spy > 0) & (ret_spy.shift(1) > 0)).sum()
up_after_anything = (ret_spy.shift(1) > 0).sum()
p_up_after_up = up_after_up / up_after_anything if up_after_anything > 0 else 0

down_after_down = ((ret_spy <= 0) & (ret_spy.shift(1) <= 0)).sum()
down_after_anything = (ret_spy.shift(1) <= 0).sum()
p_down_after_down = down_after_down / down_after_anything if down_after_anything > 0 else 0

unconditional_up = (ret_spy > 0).mean()

print(f"\n  Conditional probabilities:")
print(f"    P(up | prev up)   = {p_up_after_up:.4f}")
print(f"    P(down | prev dn) = {p_down_after_down:.4f}")
print(f"    P(up) unconditional = {unconditional_up:.4f}")
print(f"    Momentum edge:      {p_up_after_up - unconditional_up:+.4f}")

# VIX predictive power
# Correlation between lagged VIX and next-day |return|
corr_vix_absret = vix_lag.corr(ret_spy.abs())
corr_vix_ret = vix_lag.corr(ret_spy)
corr_vix_ret_sq = vix_lag.corr(ret_spy ** 2)

print(f"\n  VIX predictive power (lagged):")
print(f"    corr(VIX_lag, |ret|)  = {corr_vix_absret:.4f}  (volatility)")
print(f"    corr(VIX_lag, ret)    = {corr_vix_ret:.4f}  (direction)")
print(f"    corr(VIX_lag, ret^2)  = {corr_vix_ret_sq:.4f}  (variance)")
print(f"\n  → VIX predicts VOLATILITY ({corr_vix_absret:.3f}) but NOT DIRECTION ({corr_vix_ret:.3f})")
print(f"  → This is why VIX-based timing barely beats BH: it can't predict up/down")

# ── VIX regime analysis ──────────────────────────────────────────────
print("\n" + "=" * 80)
print("VIX REGIME — Sharpe by VIX Level")
print("=" * 80)

regime_results = []
for lo, hi, label in [(0, 15, "Low (<15)"), (15, 20, "Normal (15-20)"),
                       (20, 25, "Elevated (20-25)"), (25, 30, "High (25-30)"),
                       (30, 100, "Crisis (30+)")]:
    mask = (vix_lag >= lo) & (vix_lag < hi)
    n_days = mask.sum()
    if n_days < 30:
        continue

    spy_mean = ret_spy[mask].mean() * 252
    spy_std = ret_spy[mask].std() * np.sqrt(252)
    spy_sharpe = spy_mean / spy_std if spy_std > 0 else 0

    gld_mean = ret_gld[mask].mean() * 252
    gld_std = ret_gld[mask].std() * np.sqrt(252)
    gld_sharpe = gld_mean / gld_std if gld_std > 0 else 0

    bh_ret = 0.5 * ret_spy[mask] + 0.5 * ret_gld[mask]
    bh_mean = bh_ret.mean() * 252
    bh_std = bh_ret.std() * np.sqrt(252)
    bh_sharpe = bh_mean / bh_std if bh_std > 0 else 0

    regime_results.append({
        "regime": label,
        "n_days": int(n_days),
        "spy_sharpe": round(float(spy_sharpe), 3),
        "gld_sharpe": round(float(gld_sharpe), 3),
        "bh5050_sharpe": round(float(bh_sharpe), 3),
        "better_asset": "SPY" if spy_sharpe > gld_sharpe else "GLD",
    })

    print(f"  {label:>18}: n={n_days:>4}, SPY Sharpe={spy_sharpe:.3f}, GLD Sharpe={gld_sharpe:.3f}, BH={bh_sharpe:.3f}, Better={regime_results[-1]['better_asset']}")

# ── Conclusion ───────────────────────────────────────────────────────
print("\n" + "=" * 80)
print("CONCLUSION")
print("=" * 80)

# Determine the answer
oracle_vix_gap = oracle_vix_sharpe - bh_sharpe
oracle_nolap_gap = oracle_sharpe - bh_sharpe

if oracle_vix_gap < 0.1:
    conclusion = "VIX contains NEGLIGIBLE exploitable alpha for SPY/GLD allocation"
    answer = "(a) VT is fundamentally limited — VIX predicts volatility, not direction"
elif oracle_vix_gap < 0.2:
    conclusion = "VIX contains SMALL but real alpha — our implementations capture most of it"
    answer = "(b) Small alpha exists but our methods are near-optimal"
else:
    conclusion = "VIX contains MEANINGFUL alpha — our implementations are suboptimal"
    answer = "(b) Our implementations are suboptimal"

print(f"\n  {conclusion}")
print(f"  Answer: {answer}")
print(f"\n  Key insight: VIX-return correlation is {corr_vix_ret:.4f} (direction)")
print(f"  vs VIX-|return| correlation is {corr_vix_absret:.4f} (volatility)")
print(f"  VIX tells you HOW MUCH the market will move, not WHICH WAY")
print(f"\n  Even the BEST possible VIX-based strategy (oracle, 20 bins)")
print(f"  achieves Sharpe = {oracle_vix_sharpe:.3f} vs BH 50/50 = {bh_sharpe:.3f}")
print(f"  Gap = {oracle_vix_gap:+.3f}")

# ── Save results ─────────────────────────────────────────────────────
results = {
    "experiment_id": "K697",
    "title": "Is ANY Daily Alpha Possible? — Upper Bound Analysis",
    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "data_source": "yfinance (SPY, GLD, ^VIX)",
    "data_period": f"{prices.index[0].strftime('%Y-%m-%d')} to {prices.index[-1].strftime('%Y-%m-%d')}",
    "n_observations": int(N),
    "strategies": all_strategies,
    "alpha_gap_analysis": {
        "oracle_vix_vs_bh": round(float(oracle_vix_gap), 4),
        "oracle_nolap_vs_bh": round(float(oracle_nolap_gap), 4),
        "momentum_vs_bh": round(float(mom_sharpe - bh_sharpe), 4),
        "best_vix_thresh_vs_bh": round(float(stats_vix_thresh['sharpe'] - bh_sharpe), 4),
        "vix_scaled_vs_bh": round(float(stats_mm['sharpe'] - bh_sharpe), 4),
    },
    "autocorrelation": {
        "spy_acf_lag1": round(float(acf_1), 4),
        "spy_acf_lag5": round(float(acf_5), 4),
        "p_up_after_up": round(float(p_up_after_up), 4),
        "p_down_after_down": round(float(p_down_after_down), 4),
        "unconditional_up": round(float(unconditional_up), 4),
        "momentum_edge": round(float(p_up_after_up - unconditional_up), 4),
    },
    "vix_predictive_power": {
        "corr_vix_lag_absret": round(float(corr_vix_absret), 4),
        "corr_vix_lag_ret": round(float(corr_vix_ret), 4),
        "corr_vix_lag_ret_sq": round(float(corr_vix_ret_sq), 4),
    },
    "vix_regime_analysis": regime_results,
    "optimal_vix_threshold": round(float(best_thresh), 1),
    "optimal_vix_scaled_target": round(float(best_target), 1),
    "vix_threshold_sweep": results_sweep,
    "conclusion": conclusion,
    "answer": answer,
    "key_insight": f"VIX predicts volatility (corr={corr_vix_absret:.3f}) but not direction (corr={corr_vix_ret:.3f}). Even an oracle VIX strategy barely beats BH.",
    "references": [
        "DeMiguel, Garlappi, Uppal (2009) RFS — Optimal vs Naive Diversification",
        "Kirby & Ostdiek (2012) JFE — Volatility timing transaction costs",
        "Moreira & Muir (2017) JF — Volatility Managed Portfolios",
    ],
}

out_path = "experiments/k697_results.json"
with open(out_path, "w") as f:
    json.dump(results, f, indent=2, ensure_ascii=False)

print(f"\nResults saved to {out_path}")
print("Done.")
