"""K694 chart generator: lookahead inflation rank + corrected vs original scatter."""
from __future__ import annotations
import json
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parent
RES = json.loads((ROOT / "k694_results.json").read_text(encoding="utf-8"))

# --- Chart 1: 14-strategy Sharpe inflation rank bar ---
infl = RES["most_inflated_by_lookahead"]
names = [r["strategy"] for r in infl]
deltas = [r["sharpe_delta"] for r in infl]

fig, ax = plt.subplots(figsize=(11, 6.5))
colors = ["#d62728" if d > 1 else "#ff7f0e" if d > 0.3 else "#2ca02c" if d >= 0 else "#1f77b4"
          for d in deltas]
y = np.arange(len(names))
ax.barh(y, deltas, color=colors, edgecolor="black", linewidth=0.6)
ax.set_yticks(y)
ax.set_yticklabels(names, fontsize=10)
ax.invert_yaxis()
ax.axvline(0, color="black", linewidth=0.7)
ax.axvline(0.3, color="gray", linestyle="--", linewidth=0.6, alpha=0.7)
ax.axvline(1.0, color="red", linestyle="--", linewidth=0.6, alpha=0.7)
ax.set_xlabel("Sharpe Inflation (K640 buggy − K694 corrected)", fontsize=11)
ax.set_title("K694: 14 策略 Lookahead 修正後 Sharpe 通膨幅度\n"
             "(紅 = 高通膨 >1.0；橘 = 中度 0.3-1.0；綠 = 低 <0.3；藍 = 修正後反升)",
             fontsize=12, pad=10)
for i, d in enumerate(deltas):
    ax.text(d + (0.04 if d >= 0 else -0.04), i, f"{d:+.2f}",
            va="center", ha="left" if d >= 0 else "right", fontsize=9)
ax.set_xlim(-0.4, 2.4)
ax.grid(axis="x", alpha=0.3)
fig.tight_layout()
out1 = ROOT / "k694_inflation_rank.png"
fig.savefig(out1, dpi=140, bbox_inches="tight")
plt.close(fig)
print(f"wrote {out1}")

# --- Chart 2: corrected vs original scatter ---
fig, ax = plt.subplots(figsize=(9, 7.5))
x_buggy = [r["k640_sharpe"] for r in infl]
y_corr = [r["k694_sharpe"] for r in infl]
sizes = [80 + abs(r["sharpe_delta"]) * 240 for r in infl]
ax.scatter(x_buggy, y_corr, s=sizes, c=colors, edgecolors="black",
           linewidths=0.7, alpha=0.85)
lim = max(max(x_buggy), max(y_corr)) + 0.3
ax.plot([0, lim], [0, lim], "k--", linewidth=1, alpha=0.5,
        label="y = x（無 lookahead 偏差）")
for i, r in enumerate(infl):
    offset = (0.06, 0.06)
    if r["strategy"] in ("adaptive_tier", "piecewise_conservative"):
        offset = (0.08, -0.18)
    elif r["strategy"] == "taiwan_hybrid_leverage":
        offset = (0.08, -0.05)
    elif r["strategy"] == "fear_dca":
        offset = (0.08, -0.05)
    ax.annotate(r["strategy"], (x_buggy[i], y_corr[i]),
                xytext=(x_buggy[i] + offset[0], y_corr[i] + offset[1]),
                fontsize=8.5)
ax.set_xlabel("K640 Sharpe（lookahead 偏差版本）", fontsize=11)
ax.set_ylabel("K694 Sharpe（修正版本）", fontsize=11)
ax.set_title("K694: 修正前 vs 修正後 Sharpe 散佈圖\n"
             "（離 y=x 越遠 → lookahead 偏差越大；點面積=|delta|）",
             fontsize=12, pad=10)
ax.set_xlim(0, lim)
ax.set_ylim(0, lim)
ax.legend(loc="lower right", fontsize=9)
ax.grid(alpha=0.3)
fig.tight_layout()
out2 = ROOT / "k694_corrected_vs_original.png"
fig.savefig(out2, dpi=140, bbox_inches="tight")
plt.close(fig)
print(f"wrote {out2}")

# --- Chart 3: SPY beat visualization ---
ranking = RES["ranking_corrected"][:10]  # active strategies
fig, ax = plt.subplots(figsize=(11, 6))
labels = [r["strategy"] for r in ranking]
sharpes = [r["sharpe"] for r in ranking]
spy_sharpe = 0.85  # SPY buy-and-hold approximate over period
bar_colors = ["#2ca02c" if s > spy_sharpe else "#d62728" for s in sharpes]
xs = np.arange(len(labels))
ax.bar(xs, sharpes, color=bar_colors, edgecolor="black", linewidth=0.6)
ax.axhline(spy_sharpe, color="black", linestyle="--", linewidth=1,
           label=f"SPY 買進持有約 Sharpe ≈ {spy_sharpe}")
ax.set_xticks(xs)
ax.set_xticklabels(labels, rotation=35, ha="right", fontsize=9)
ax.set_ylabel("修正後 Sharpe (K694)", fontsize=11)
ax.set_title("K694: 修正後 10 個 active 策略 Sharpe vs SPY\n"
             "(綠 = 仍 beat SPY，7/10；紅 = 低於 SPY，3/10)",
             fontsize=12, pad=10)
for i, s in enumerate(sharpes):
    ax.text(i, s + 0.05, f"{s:.2f}", ha="center", fontsize=9)
ax.legend(loc="upper right", fontsize=9)
ax.grid(axis="y", alpha=0.3)
fig.tight_layout()
out3 = ROOT / "k694_beat_spy.png"
fig.savefig(out3, dpi=140, bbox_inches="tight")
plt.close(fig)
print(f"wrote {out3}")
