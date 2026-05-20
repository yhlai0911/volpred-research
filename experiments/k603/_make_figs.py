"""Generate K603 publication figures (3 PNGs)."""
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

HERE = Path(__file__).parent
RESULTS = json.loads((HERE / "k603_dynamic_target_vol_results.json").read_text())

VARIANTS = ["Fixed_12", "Rate_Adj", "VIX_Regime", "Roll_Sharpe", "Inv_VIX_Pct"]
LABELS = {
    "Fixed_12": "Fixed 12% (baseline)",
    "Rate_Adj": "Rate-Adjusted",
    "VIX_Regime": "VIX-Regime",
    "Roll_Sharpe": "Rolling-Sharpe",
    "Inv_VIX_Pct": "Inverse-VIX-Pctile",
}
COLORS = {
    "Fixed_12": "#444444",
    "Rate_Adj": "#1f77b4",
    "VIX_Regime": "#ff7f0e",
    "Roll_Sharpe": "#2ca02c",
    "Inv_VIX_Pct": "#d62728",
}

# ---------- Fig 1: Sharpe by variant (full + Buy_Hold) ----------
full = RESULTS["full_sample_results"]
fig, ax = plt.subplots(figsize=(9, 5))
names = ["Buy_Hold"] + VARIANTS
sharpes = [full[n]["sharpe"] for n in names]
mdds = [full[n]["max_dd"] for n in names]
display_names = ["Buy & Hold\n(50/50)"] + [LABELS[v] for v in VARIANTS]
bar_colors = ["#888888"] + [COLORS[v] for v in VARIANTS]
bars = ax.bar(display_names, sharpes, color=bar_colors, edgecolor="black", linewidth=0.6)
for bar, s in zip(bars, sharpes):
    ax.text(bar.get_x() + bar.get_width() / 2, s + 0.012, f"{s:.3f}",
            ha="center", va="bottom", fontsize=9)
ax.axhline(full["Fixed_12"]["sharpe"], color="#444", ls="--", lw=1, alpha=0.6,
           label=f"Fixed 12% baseline = {full['Fixed_12']['sharpe']:.3f}")
ax.set_ylabel("Annualised Sharpe ratio")
ax.set_title("K603 Full-sample Sharpe (2004-11 to 2026-03, 5,371 days, 50/50 SPY/GLD)")
ax.legend(loc="upper right", fontsize=9)
ax.grid(axis="y", alpha=0.3)
plt.xticks(rotation=15, ha="right")
plt.tight_layout()
plt.savefig(HERE / "k603_fig1_sharpe_by_variant.png", dpi=140)
plt.close()

# ---------- Fig 2: DM t-stat vs Harvey threshold (Δ vs Fixed_12) ----------
tests = RESULTS["statistical_tests_vs_fixed"]
fig, ax = plt.subplots(figsize=(9, 5))
variant_names = [v for v in VARIANTS if v != "Fixed_12"]
ts = [tests[v]["dm_t"] for v in variant_names]
ps = [tests[v]["dm_p"] for v in variant_names]
bar_colors2 = [COLORS[v] for v in variant_names]
bars = ax.bar([LABELS[v] for v in variant_names], ts, color=bar_colors2,
              edgecolor="black", linewidth=0.6)
for bar, t, p in zip(bars, ts, ps):
    y = t + (0.10 if t >= 0 else -0.18)
    ax.text(bar.get_x() + bar.get_width() / 2, y, f"t={t:+.2f}\np={p:.3f}",
            ha="center", va="bottom" if t >= 0 else "top", fontsize=9)
# Harvey thresholds (Harvey 2016 JoF: t>3 strict; conventional |t|>1.96)
ax.axhline(3.0, color="red", ls="--", lw=1.4, label="Harvey strict threshold t=+3.0")
ax.axhline(-3.0, color="red", ls="--", lw=1.4)
ax.axhline(1.96, color="orange", ls=":", lw=1, alpha=0.7, label="Conventional |t|=1.96")
ax.axhline(-1.96, color="orange", ls=":", lw=1, alpha=0.7)
ax.axhline(0, color="black", lw=0.6)
ax.set_ylabel("Diebold–Mariano t-statistic (Δ utility vs Fixed 12%)")
ax.set_title("K603 Comparison test: 4 dynamic variants vs Fixed 12% baseline\n"
             "All four fall well inside the Harvey rigour band — direction wins, statistics do not")
ax.set_ylim(-3.5, 3.5)
ax.legend(loc="upper right", fontsize=9)
ax.grid(axis="y", alpha=0.3)
plt.xticks(rotation=15, ha="right")
plt.tight_layout()
plt.savefig(HERE / "k603_fig2_dm_vs_harvey.png", dpi=140)
plt.close()

# ---------- Fig 3: Sharpe across 5 OOS sub-periods ----------
cross = RESULTS["cross_oos_results"]
periods = ["P1_2005_2009", "P2_2009_2013", "P3_2013_2017",
           "P4_2017_2021", "P5_2021_2026"]
period_labels = ["P1\n2005–09", "P2\n2009–13", "P3\n2013–17",
                 "P4\n2017–21", "P5\n2021–26"]

fig, ax = plt.subplots(figsize=(10, 5))
x = np.arange(len(periods))
width = 0.15
offsets = np.linspace(-2 * width, 2 * width, 5)
for i, v in enumerate(VARIANTS):
    vals = [cross[p][v]["sharpe"] for p in periods]
    ax.bar(x + offsets[i], vals, width=width, color=COLORS[v],
           edgecolor="black", linewidth=0.4, label=LABELS[v])
ax.axhline(0, color="black", lw=0.6)
ax.set_xticks(x)
ax.set_xticklabels(period_labels)
ax.set_ylabel("Sharpe ratio per ~4-year sub-period")
ax.set_title("K603 Cross-OOS Sharpe across 5 non-overlapping windows\n"
             "Dynamic targets edge ahead in P1/P5, lose in P2/P3 — wins not concentrated")
ax.legend(loc="upper left", fontsize=8, ncol=2)
ax.grid(axis="y", alpha=0.3)
plt.tight_layout()
plt.savefig(HERE / "k603_fig3_cross_oos.png", dpi=140)
plt.close()

print("OK 3 figures written:")
for f in sorted(HERE.glob("k603_fig*.png")):
    print(" ", f.name, f.stat().st_size, "bytes")
