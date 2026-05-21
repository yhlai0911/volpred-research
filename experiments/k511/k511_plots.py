"""K511 visualization — generate 3 PNG figures from results JSON.

Outputs:
  k511_strategy_sharpe_bars.png  — Sharpe of 5 strategies vs benchmarks
  k511_cointegration_pct.png      — % rolling-window cointegration per pair
  k511_cross_oos_sharpe.png       — cross-OOS Sharpe per period x strategy
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).parent
RESULTS = ROOT / "k511_pairs_trading_results.json"

with RESULTS.open() as f:
    R = json.load(f)

# ---- Figure 1: Sharpe bars (strategies vs benchmarks) ----
strats = R["strategies"]
bench = R["benchmarks"]

names = []
sharpes = []
colors = []
for k in ["S1_Basic_Pairs_SQ", "S2_VolCond_Pairs_SQ", "S3_Pairs_VT_Overlay",
         "S4_MultiPair", "S5_SPY_GLD_Pair"]:
    names.append(k.replace("_", " "))
    sharpes.append(strats[k]["sharpe"])
    colors.append("#d9534f")  # red — all FAIL
for k in ["BuyHold_SPY", "VT_12VIX_SPY"]:
    names.append(k.replace("_", " "))
    sharpes.append(bench[k]["sharpe"])
    colors.append("#5cb85c")  # green — benchmark

fig, ax = plt.subplots(figsize=(10, 5.2))
bars = ax.barh(names, sharpes, color=colors, edgecolor="black", linewidth=0.5)
ax.axvline(0, color="black", lw=0.8)
ax.axvline(0.30, color="#666", lw=0.8, ls="--", label="Sharpe = 0.30 baseline")
ax.set_xlabel("Sharpe Ratio (full sample, 2006-04 to 2025-12)")
ax.set_title("K511 — 5 Pairs Trading Strategies vs Benchmarks (all 5 strategies FAIL)")
ax.invert_yaxis()
for b, s in zip(bars, sharpes):
    ax.text(s + (0.02 if s >= 0 else -0.02), b.get_y() + b.get_height() / 2,
            f"{s:+.2f}", va="center",
            ha="left" if s >= 0 else "right", fontsize=9)
ax.legend(loc="lower right", fontsize=9)
ax.grid(axis="x", alpha=0.3)
plt.tight_layout()
plt.savefig(ROOT / "k511_strategy_sharpe_bars.png", dpi=140)
plt.close()

# ---- Figure 2: Cointegration % bar ----
coint_diag = R["cointegration_diagnostics"]
pairs = ["SPY-QQQ", "SPY-IWM", "SPY-GLD"]
pcts = [coint_diag[p]["rolling_pct_cointegrated"] for p in pairs]
corrs = [coint_diag[p]["correlation"] for p in pairs]

fig, ax = plt.subplots(figsize=(9, 4.8))
bars = ax.bar(pairs, pcts, color=["#d9534f", "#d9534f", "#9a3a35"],
              edgecolor="black", linewidth=0.5)
ax.axhline(50, color="#5cb85c", lw=1.0, ls="--",
           label="Stable cointegration threshold (≈50%)")
ax.set_ylabel("% of rolling 252-day windows cointegrated (Engle-Granger 5%)")
ax.set_title("K511 — ETF pairs are NOT structurally cointegrated")
ax.set_ylim(0, 100)
for bar, pct, corr in zip(bars, pcts, corrs):
    ax.text(bar.get_x() + bar.get_width() / 2, pct + 2,
            f"{pct:.1f}%\n(ρ = {corr:+.2f})",
            ha="center", va="bottom", fontsize=10)
ax.legend(loc="upper right", fontsize=9)
ax.grid(axis="y", alpha=0.3)
plt.tight_layout()
plt.savefig(ROOT / "k511_cointegration_pct.png", dpi=140)
plt.close()

# ---- Figure 3: Cross-OOS Sharpe heat ----
cross = R["cross_oos"]
strat_keys = ["S1_Basic_Pairs_SQ", "S2_VolCond_Pairs_SQ", "S3_Pairs_VT_Overlay",
              "S4_MultiPair", "S5_SPY_GLD_Pair"]
periods = [d["period"] for d in cross[strat_keys[0]]["details"]]
matrix = np.array([cross[k]["oos_sharpes"] for k in strat_keys])

fig, ax = plt.subplots(figsize=(10, 4.6))
im = ax.imshow(matrix, cmap="RdYlGn", vmin=-2.0, vmax=1.0, aspect="auto")
ax.set_xticks(range(len(periods)))
ax.set_xticklabels(periods, rotation=20, ha="right", fontsize=9)
ax.set_yticks(range(len(strat_keys)))
ax.set_yticklabels([k.replace("_", " ") for k in strat_keys])
for i in range(matrix.shape[0]):
    for j in range(matrix.shape[1]):
        ax.text(j, i, f"{matrix[i, j]:+.2f}", ha="center", va="center",
                color="black", fontsize=9)
cbar = plt.colorbar(im, ax=ax, fraction=0.04)
cbar.set_label("OOS Sharpe Ratio")
ax.set_title("K511 — Cross-OOS Sharpe (5 periods × 5 strategies): 0/25 positive*")
ax.set_xlabel("Out-of-sample window")
plt.tight_layout()
plt.savefig(ROOT / "k511_cross_oos_sharpe.png", dpi=140)
plt.close()

print("Saved 3 PNGs to", ROOT)
