"""Generate K222b SWR overlay figures for SWR articles update.

Outputs:
- experiments/k222b/fig_wr_sweep_heatmap.png (5 WR x 3 strategies survival heatmap)
- experiments/k222b/fig_strategy_survival_curves.png (line chart: survival vs WR for 3 strategies)

Source: experiments/k222b/k222b_mc_swr_overlay_results.json (10K path block-bootstrap MC)
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).parent
RESULTS = json.loads((ROOT / "k222b_mc_swr_overlay_results.json").read_text())

WR = sorted(float(k) for k in RESULTS["wr_sweep"].keys())
STRATS = ["spy_bh", "5050_bh", "5050_vt"]
LABELS = {"spy_bh": "SPY B&H", "5050_bh": "50/50 B&H", "5050_vt": "50/50 VT"}

# Build matrix [strategy x WR]
mat = np.array([[RESULTS["wr_sweep"][f"{w:g}"][s] for w in WR] for s in STRATS])

# --- Figure 1: Heatmap ---
fig, ax = plt.subplots(figsize=(8, 4))
im = ax.imshow(mat, cmap="RdYlGn", vmin=0.3, vmax=1.0, aspect="auto")
ax.set_xticks(range(len(WR)))
ax.set_xticklabels([f"{int(w * 100)}%" for w in WR])
ax.set_yticks(range(len(STRATS)))
ax.set_yticklabels([LABELS[s] for s in STRATS])
ax.set_xlabel("Withdrawal Rate (initial)")
ax.set_title("K222b: 30-yr survival rate (10,000-path block-bootstrap MC)")
for i in range(mat.shape[0]):
    for j in range(mat.shape[1]):
        v = mat[i, j]
        color = "white" if v < 0.6 else "black"
        ax.text(j, i, f"{v * 100:.1f}%", ha="center", va="center", color=color, fontsize=11)
fig.colorbar(im, ax=ax, label="Survival")
fig.tight_layout()
fig.savefig(ROOT / "fig_wr_sweep_heatmap.png", dpi=140)
plt.close(fig)

# --- Figure 2: Line chart ---
fig, ax = plt.subplots(figsize=(8, 5))
markers = {"spy_bh": "o", "5050_bh": "s", "5050_vt": "^"}
colors = {"spy_bh": "#1f77b4", "5050_bh": "#2ca02c", "5050_vt": "#d62728"}
for s in STRATS:
    y = [RESULTS["wr_sweep"][f"{w:g}"][s] for w in WR]
    ax.plot(
        [w * 100 for w in WR],
        [v * 100 for v in y],
        marker=markers[s],
        color=colors[s],
        label=LABELS[s],
        linewidth=2,
        markersize=8,
    )
ax.set_xlabel("Withdrawal Rate (%)")
ax.set_ylabel("30-yr Survival Rate (%)")
ax.set_title("K222b: 50/50 VT collapses faster than 50/50 B&H at high WR (10K-path MC)")
ax.axhline(y=50, color="gray", linestyle=":", alpha=0.5, label="50% reference")
ax.grid(alpha=0.3)
ax.legend(loc="lower left")
ax.set_ylim(30, 102)
fig.tight_layout()
fig.savefig(ROOT / "fig_strategy_survival_curves.png", dpi=140)
plt.close(fig)

print("[OK] Generated:")
print(f"  - {ROOT / 'fig_wr_sweep_heatmap.png'}")
print(f"  - {ROOT / 'fig_strategy_survival_curves.png'}")
