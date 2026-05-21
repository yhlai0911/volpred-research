"""
K237 rewrite figures — honest narrative version (post-rerun 2026-05-07).
Reads experiments/k237/k237_international_vt_results.json and produces:
  1. fig1_mdd_comparison.png — VT vs B&H MDD per market with significance annotations
  2. fig2_sharpe_comparison.png — VT vs B&H Sharpe per market
  3. fig3_taiwan_caveat.png — Taiwan deep-dive (MDD vs Sharpe trade-off)
"""
import json
from pathlib import Path
import matplotlib.pyplot as plt
import numpy as np

plt.rcParams["font.sans-serif"] = ["PingFang HK", "PingFang TC", "Heiti TC", "Arial Unicode MS", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "k237_international_vt_results.json"
OUT = HERE / "figures"
OUT.mkdir(exist_ok=True)

with open(RESULTS) as f:
    data = json.load(f)

markets_order = ["SPY", "EWJ", "VGK", "EEM", "0050.TW"]
labels = {
    "SPY": "美國\n(SPY)",
    "EWJ": "日本\n(EWJ)",
    "VGK": "歐洲\n(VGK)",
    "EEM": "新興市場\n(EEM)",
    "0050.TW": "台灣\n(0050)",
}

vt_mdd = [abs(data["full_period_results"][m]["vt"]["max_dd"]) for m in markets_order]
bh_mdd = [abs(data["full_period_results"][m]["bh_5050"]["max_dd"]) for m in markets_order]
mdd_p = [data["statistical_tests"][m]["mdd_bootstrap_p"] for m in markets_order]

vt_sharpe = [data["full_period_results"][m]["vt"]["sharpe"] for m in markets_order]
bh_sharpe = [data["full_period_results"][m]["bh_5050"]["sharpe"] for m in markets_order]
sharpe_p = [data["statistical_tests"][m]["sharpe_diff_p"] for m in markets_order]

# ==================================================================
# Figure 1 — MDD comparison
# ==================================================================
fig, ax = plt.subplots(figsize=(10, 6))
x = np.arange(len(markets_order))
w = 0.36

bars_vt = ax.bar(x - w/2, vt_mdd, w, label="VT 策略 (50/50 + 12/VIX)", color="#2E86AB")
bars_bh = ax.bar(x + w/2, bh_mdd, w, label="50/50 買進持有", color="#A23B72")

for i, (vt_v, bh_v, p) in enumerate(zip(vt_mdd, bh_mdd, mdd_p)):
    sig_label = "顯著" if p < 0.05 else "不顯著"
    color = "#1B5E20" if p < 0.05 else "#777"
    top = max(vt_v, bh_v) + 0.025
    ax.annotate(f"{sig_label}\n(p={p:.3f})", xy=(x[i], top), ha="center",
                fontsize=9, color=color, fontweight="bold" if p < 0.05 else "normal")

ax.set_ylabel("最大回撤 (絕對值)", fontsize=11)
ax.set_title("VT 策略降低最大回撤：5 個市場中 3 個達統計顯著\n(Bootstrap, 10000 次重抽, seed=42)", fontsize=12)
ax.set_xticks(x)
ax.set_xticklabels([labels[m] for m in markets_order], fontsize=10)
ax.legend(loc="upper left", fontsize=10)
ax.set_ylim(0, max(max(vt_mdd), max(bh_mdd)) * 1.28)
ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x*100:.0f}%"))
ax.grid(axis="y", alpha=0.3)
plt.tight_layout()
plt.savefig(OUT / "fig1_mdd_comparison.png", dpi=160, bbox_inches="tight")
plt.close()
print(f"Saved {OUT / 'fig1_mdd_comparison.png'}")

# ==================================================================
# Figure 2 — Sharpe comparison
# ==================================================================
fig, ax = plt.subplots(figsize=(10, 6))
bars_vt2 = ax.bar(x - w/2, vt_sharpe, w, label="VT 策略", color="#2E86AB")
bars_bh2 = ax.bar(x + w/2, bh_sharpe, w, label="50/50 買進持有", color="#A23B72")

for i, (v, b, p) in enumerate(zip(vt_sharpe, bh_sharpe, sharpe_p)):
    top = max(v, b) + 0.04
    if markets_order[i] == "0050.TW":
        ax.annotate(f"VT 反而較差\n(p={p:.3f})", xy=(x[i], top), ha="center",
                    fontsize=9, color="#B71C1C", fontweight="bold")
    else:
        ax.annotate(f"無顯著差異\n(p={p:.3f})", xy=(x[i], top), ha="center",
                    fontsize=9, color="#777")

ax.set_ylabel("Sharpe Ratio (年化)", fontsize=11)
ax.set_title("VT 策略未顯著提升 Sharpe：5/5 市場 Sharpe 差異不顯著\n台灣 0050 反向（VT 表現顯著較差，p=0.027）", fontsize=12)
ax.set_xticks(x)
ax.set_xticklabels([labels[m] for m in markets_order], fontsize=10)
ax.legend(loc="upper right", fontsize=10)
ax.axhline(0, color="k", lw=0.6)
ax.set_ylim(0, max(max(vt_sharpe), max(bh_sharpe)) * 1.32)
ax.grid(axis="y", alpha=0.3)
plt.tight_layout()
plt.savefig(OUT / "fig2_sharpe_comparison.png", dpi=160, bbox_inches="tight")
plt.close()
print(f"Saved {OUT / 'fig2_sharpe_comparison.png'}")

# ==================================================================
# Figure 3 — Taiwan caveat (VIX-mkt corr & VT weight effect)
# ==================================================================
fig, axes = plt.subplots(1, 2, figsize=(12, 5))

# Left panel: VIX-market correlation per market
vix_corr = [abs(data["full_period_results"][m]["vix_mkt_corr"]) for m in markets_order]
colors = ["#B71C1C" if m == "0050.TW" else "#2E86AB" for m in markets_order]
ax0 = axes[0]
b = ax0.bar([labels[m] for m in markets_order], vix_corr, color=colors)
ax0.set_ylabel("|VIX vs 市場日報酬相關係數|", fontsize=10)
ax0.set_title("VIX 對台灣 0050 的訊號最弱\n（|相關| 僅 0.08，其他市場 0.64–0.82）", fontsize=11)
ax0.set_ylim(0, 1)
for i, v in enumerate(vix_corr):
    ax0.text(i, v + 0.02, f"{v:.3f}", ha="center", fontsize=9)
ax0.grid(axis="y", alpha=0.3)

# Right panel: Taiwan VT vs B&H Sharpe + MDD trade-off
ax1 = axes[1]
metrics = ["Sharpe", "最大回撤(絕對)", "Sortino", "Calmar"]
tw_vt = [data["full_period_results"]["0050.TW"]["vt"]["sharpe"],
         abs(data["full_period_results"]["0050.TW"]["vt"]["max_dd"]),
         data["full_period_results"]["0050.TW"]["vt"]["sortino"],
         data["full_period_results"]["0050.TW"]["vt"]["calmar"]]
tw_bh = [data["full_period_results"]["0050.TW"]["bh_5050"]["sharpe"],
         abs(data["full_period_results"]["0050.TW"]["bh_5050"]["max_dd"]),
         data["full_period_results"]["0050.TW"]["bh_5050"]["sortino"],
         data["full_period_results"]["0050.TW"]["bh_5050"]["calmar"]]
xx = np.arange(len(metrics))
ax1.bar(xx - w/2, tw_vt, w, label="VT 策略", color="#2E86AB")
ax1.bar(xx + w/2, tw_bh, w, label="50/50 B&H", color="#A23B72")
ax1.set_xticks(xx)
ax1.set_xticklabels(metrics, fontsize=10)
ax1.set_title("台灣 0050：VT 在 Sharpe / Sortino / Calmar 全面落後", fontsize=11)
ax1.legend(fontsize=9)
ax1.grid(axis="y", alpha=0.3)
for i, (v, b) in enumerate(zip(tw_vt, tw_bh)):
    ax1.text(xx[i] - w/2, v + 0.01, f"{v:.3f}", ha="center", fontsize=8)
    ax1.text(xx[i] + w/2, b + 0.01, f"{b:.3f}", ha="center", fontsize=8)

plt.suptitle("台灣 0050 反例：當地市場與 VIX 訊號脫鉤", fontsize=12, fontweight="bold")
plt.tight_layout()
plt.savefig(OUT / "fig3_taiwan_caveat.png", dpi=160, bbox_inches="tight")
plt.close()
print(f"Saved {OUT / 'fig3_taiwan_caveat.png'}")
