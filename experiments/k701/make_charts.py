"""Generate K701 article PNG charts (3 charts) from k701_results.json."""
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).parent
RESULTS = json.loads((ROOT / "k701_results.json").read_text())

freqs = ["daily", "weekly", "monthly"]
labels = ["日頻 (Daily)", "週頻 (Weekly)", "月頻 (Monthly)"]
colors = ["#1f77b4", "#ff7f0e", "#2ca02c"]

corr = [RESULTS["cross_frequency_comparison"][f]["corr_vix_next_ret"] for f in freqs]
alpha = [RESULTS["cross_frequency_comparison"][f]["alpha_sharpe"] for f in freqs]
strat_sharpe = [RESULTS["cross_frequency_comparison"][f]["strat_sharpe_net"] for f in freqs]
bh_sharpe = [RESULTS["cross_frequency_comparison"][f]["bh_sharpe"] for f in freqs]
strat_mdd = [RESULTS["cross_frequency_comparison"][f]["strat_mdd"] for f in freqs]
bh_mdd = [RESULTS["cross_frequency_comparison"][f]["bh_mdd"] for f in freqs]
tx_cost = [RESULTS["strategy_performance"][f]["total_tx_cost"] for f in freqs]

# 中文字型
plt.rcParams["font.sans-serif"] = ["Heiti TC", "PingFang TC", "Arial Unicode MS",
                                   "Hiragino Sans GB", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

# ── Chart 1: VIX→next-period return correlation by frequency ──────────
fig, ax = plt.subplots(figsize=(8, 5))
bars = ax.bar(labels, corr, color=colors, edgecolor="black", linewidth=0.8)
ax.axhline(0, color="black", linewidth=0.5)
ax.axhline(0.1, color="gray", linestyle="--", linewidth=0.7, alpha=0.6,
           label="弱相關門檻 (≈0.1)")
for b, v in zip(bars, corr):
    ax.text(b.get_x() + b.get_width() / 2, v + 0.001,
            f"{v:.4f}", ha="center", va="bottom", fontsize=11, fontweight="bold")
ax.set_ylabel("相關係數 (VIX vs 下期 SPY 報酬)", fontsize=11)
ax.set_title("圖 1｜三頻率下 VIX → 下期報酬相關性都很弱\n"
             "(K701, 2006-2026, n_daily=5087)", fontsize=12)
ax.set_ylim(0, max(corr) * 1.5)
ax.legend(loc="upper right", fontsize=9)
ax.grid(True, axis="y", alpha=0.3)
plt.tight_layout()
plt.savefig(ROOT / "k701_corr_by_freq.png", dpi=150, bbox_inches="tight")
plt.close()
print("saved k701_corr_by_freq.png")

# ── Chart 2: Strategy Sharpe vs B&H Sharpe + alpha annotation ─────────
fig, ax = plt.subplots(figsize=(9, 5.5))
x = np.arange(len(freqs))
width = 0.35
b1 = ax.bar(x - width / 2, strat_sharpe, width, label="12/VIX VT 策略 (淨)",
            color="#1f77b4", edgecolor="black", linewidth=0.8)
b2 = ax.bar(x + width / 2, bh_sharpe, width, label="50/50 SPY+GLD Buy & Hold",
            color="#bcbd22", edgecolor="black", linewidth=0.8)
for bar, v in zip(b1, strat_sharpe):
    ax.text(bar.get_x() + bar.get_width() / 2, v + 0.01,
            f"{v:.3f}", ha="center", va="bottom", fontsize=10)
for bar, v in zip(b2, bh_sharpe):
    ax.text(bar.get_x() + bar.get_width() / 2, v + 0.01,
            f"{v:.3f}", ha="center", va="bottom", fontsize=10)
# 標 alpha
for i, a in enumerate(alpha):
    color = "red" if a < 0 else "darkgreen"
    sign = "+" if a >= 0 else ""
    ax.annotate(f"alpha = {sign}{a:.3f}",
                xy=(i, max(strat_sharpe[i], bh_sharpe[i]) + 0.08),
                ha="center", fontsize=10, color=color, fontweight="bold")
ax.set_xticks(x)
ax.set_xticklabels(labels)
ax.set_ylabel("年化 Sharpe 比率", fontsize=11)
ax.set_title("圖 2｜三頻率 Sharpe alpha 都接近 0：拉低頻率沒有擠出 alpha\n"
             "(月度 alpha = +0.017，仍在統計噪音範圍)", fontsize=12)
ax.set_ylim(0, max(max(strat_sharpe), max(bh_sharpe)) * 1.3)
ax.legend(loc="upper left", fontsize=10)
ax.grid(True, axis="y", alpha=0.3)
plt.tight_layout()
plt.savefig(ROOT / "k701_sharpe_alpha.png", dpi=150, bbox_inches="tight")
plt.close()
print("saved k701_sharpe_alpha.png")

# ── Chart 3: TX cost decay + MDD comparison (sizing benefit) ──────────
fig, axes = plt.subplots(1, 2, figsize=(12, 5))

# Left: Total transaction cost (decays with lower freq)
axes[0].bar(labels, tx_cost, color=colors, edgecolor="black", linewidth=0.8)
for i, v in enumerate(tx_cost):
    axes[0].text(i, v + 0.005, f"{v:.3f}", ha="center", va="bottom",
                 fontsize=11, fontweight="bold")
axes[0].set_ylabel("累計交易成本 (20 年, 對數)", fontsize=11)
axes[0].set_title("(a) 交易成本：頻率越低越省\n"
                  "從日頻 0.32 降到月頻 0.05", fontsize=11)
axes[0].grid(True, axis="y", alpha=0.3)

# Right: MDD comparison — VT 在三頻率都比 BH MDD 更小 (sizing 價值)
x = np.arange(len(freqs))
width = 0.35
mdd_strat = [-m for m in strat_mdd]  # convert to positive %
mdd_bh = [-m for m in bh_mdd]
b1 = axes[1].bar(x - width / 2, mdd_strat, width, label="12/VIX VT 策略",
                 color="#1f77b4", edgecolor="black")
b2 = axes[1].bar(x + width / 2, mdd_bh, width, label="50/50 Buy & Hold",
                 color="#bcbd22", edgecolor="black")
for bar, v in zip(b1, mdd_strat):
    axes[1].text(bar.get_x() + bar.get_width() / 2, v + 0.005,
                 f"{v * 100:.1f}%", ha="center", va="bottom", fontsize=9)
for bar, v in zip(b2, mdd_bh):
    axes[1].text(bar.get_x() + bar.get_width() / 2, v + 0.005,
                 f"{v * 100:.1f}%", ha="center", va="bottom", fontsize=9)
axes[1].set_xticks(x)
axes[1].set_xticklabels(labels)
axes[1].set_ylabel("最大回撤 |MDD| (絕對值)", fontsize=11)
axes[1].set_title("(b) MDD：VT 在三頻率都 ≤ B&H\n"
                  "VT 真正價值是 sizing/風險控管", fontsize=11)
axes[1].legend(loc="upper right", fontsize=10)
axes[1].grid(True, axis="y", alpha=0.3)

plt.suptitle("圖 3｜頻率降低省成本，但 alpha 沒擠出來；VT 的價值在 sizing",
             fontsize=12, y=1.02)
plt.tight_layout()
plt.savefig(ROOT / "k701_cost_mdd.png", dpi=150, bbox_inches="tight")
plt.close()
print("saved k701_cost_mdd.png")
print("All charts written to", ROOT)
