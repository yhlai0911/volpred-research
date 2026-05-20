"""Generate K696 article PNGs from k696_results.json."""
import json
from pathlib import Path
import matplotlib.pyplot as plt
import matplotlib
matplotlib.rcParams['axes.unicode_minus'] = False

ROOT = Path(__file__).resolve().parent
results = json.loads((ROOT / "k696_results.json").read_text())

sweep = results["floor_sweep_results"]
floors = [0, 10, 20, 30, 40, 50, 60, 70]
sharpe_vals = [sweep[f"floor_{f}"]["sharpe"] for f in floors]
bh_sharpe = sweep["bh_5050"]["sharpe"]
cagr_vals = [sweep[f"floor_{f}"]["cagr"] * 100 for f in floors]
bh_cagr = sweep["bh_5050"]["cagr"] * 100
mdd_vals = [sweep[f"floor_{f}"]["mdd"] * 100 for f in floors]
bh_mdd = sweep["bh_5050"]["mdd"] * 100

# Figure 1: Sharpe by floor with B&H reference line
fig, ax = plt.subplots(figsize=(9, 5.2))
labels = [f"VT floor {f}%" for f in floors]
bars = ax.bar(labels, sharpe_vals, color="#4C78A8", alpha=0.85, label="VT-with-floor")
ax.axhline(bh_sharpe, color="#E45756", linestyle="--", linewidth=2,
           label=f"Buy & Hold 50/50 SPY+GLD = {bh_sharpe:.4f}")
for bar, val in zip(bars, sharpe_vals):
    ax.text(bar.get_x() + bar.get_width() / 2, val + 0.005,
            f"{val:.4f}", ha="center", fontsize=9)
ax.set_ylabel("Annualized Sharpe Ratio")
ax.set_title("K696: Sharpe vs minimum-exposure floor (no floor beats B&H)")
ax.set_ylim(0, max(bh_sharpe, max(sharpe_vals)) * 1.18)
ax.legend(loc="lower right")
ax.grid(axis="y", alpha=0.3)
plt.xticks(rotation=20)
plt.tight_layout()
plt.savefig(ROOT / "k696_floor_sharpe.png", dpi=140, bbox_inches="tight")
plt.close()

# Figure 2: Sharpe gap (VT - B&H) — all negative
fig, ax = plt.subplots(figsize=(9, 5.2))
gaps = [s - bh_sharpe for s in sharpe_vals]
ax.plot(floors, gaps, marker="o", linewidth=2.2, color="#54A24B",
        markersize=8, label="Sharpe(VT-floor) − Sharpe(B&H)")
ax.axhline(0, color="black", linewidth=1)
ax.fill_between(floors, gaps, 0, alpha=0.18, color="#54A24B")
for x, y in zip(floors, gaps):
    ax.text(x, y - 0.005, f"{y:+.4f}", ha="center", fontsize=8.5)
ax.set_xlabel("Minimum exposure floor (%)")
ax.set_ylabel("Sharpe gap vs Buy & Hold")
ax.set_title("K696: every floor leaves a Sharpe deficit vs B&H (gap closes but never crosses zero)")
ax.grid(alpha=0.3)
ax.legend()
plt.tight_layout()
plt.savefig(ROOT / "k696_sharpe_gap.png", dpi=140, bbox_inches="tight")
plt.close()

# Figure 3: Crisis-period drawdown comparison (B&H vs floor 0/40/60)
crisis = results["crisis_period_analysis"]
crises_dd = ["GFC (2008-09 to 2009-03)", "COVID Crash (2020-02 to 2020-04)",
             "2022 Bear (2022-01 to 2022-10)"]
labels_short = ["GFC 2008-09", "COVID 2020", "2022 Bear"]
bh_dd = [crisis[c]["BH"] for c in crises_dd]
f0_dd = [crisis[c]["floor_0"] for c in crises_dd]
f40_dd = [crisis[c]["floor_40"] for c in crises_dd]
f60_dd = [crisis[c]["floor_60"] for c in crises_dd]

import numpy as np
x = np.arange(len(labels_short))
w = 0.2
fig, ax = plt.subplots(figsize=(9, 5.2))
ax.bar(x - 1.5 * w, bh_dd, w, color="#E45756", label="Buy & Hold")
ax.bar(x - 0.5 * w, f0_dd, w, color="#4C78A8", label="VT floor 0%")
ax.bar(x + 0.5 * w, f40_dd, w, color="#72B7B2", label="VT floor 40%")
ax.bar(x + 1.5 * w, f60_dd, w, color="#F58518", label="VT floor 60%")
for i, (b, f0, f4, f6) in enumerate(zip(bh_dd, f0_dd, f40_dd, f60_dd)):
    for j, v in enumerate([b, f0, f4, f6]):
        ax.text(i + (j - 1.5) * w, v - 0.6, f"{v:.1f}%",
                ha="center", fontsize=8)
ax.axhline(0, color="black", linewidth=0.7)
ax.set_xticks(x)
ax.set_xticklabels(labels_short)
ax.set_ylabel("Crisis-period return (%)")
ax.set_title("K696: VT-with-floor cuts crisis losses dramatically, regardless of floor level")
ax.legend()
ax.grid(axis="y", alpha=0.3)
plt.tight_layout()
plt.savefig(ROOT / "k696_crisis_dd.png", dpi=140, bbox_inches="tight")
plt.close()

print("OK: 3 PNGs written to", ROOT)
print(f"BH Sharpe={bh_sharpe:.4f}, best floor 70%={sharpe_vals[-1]:.4f}, gap={sharpe_vals[-1]-bh_sharpe:+.4f}")
