"""
每日精選導讀 chart — VIX 體制與市場狀態
所有數字來自已發佈文章的真實實驗 results.json，無虛構。
來源:
 - 左圖: K741 (experiments/k741/k741_nfp_event_study_results.json) part_b_vix_regimes
 - 右圖: k_vix_complacency_20260621 results.json — 低 VIX 體制 vs 不分狀態的前瞻 63 日最大回檔
"""
import json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
import numpy as np
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Chinese font
for cand in ["/System/Library/Fonts/PingFang.ttc",
             "/System/Library/Fonts/STHeiti Light.ttc",
             "/Library/Fonts/Arial Unicode.ttf"]:
    if Path(cand).exists():
        font_manager.fontManager.addfont(cand)
        plt.rcParams["font.family"] = font_manager.FontProperties(fname=cand).get_name()
        break
plt.rcParams["axes.unicode_minus"] = False

# ---- LEFT: K741 NFP 日波動 × VIX 體制 ----
k741 = json.load(open(ROOT / "experiments/k741/k741_nfp_event_study_results.json"))
reg = k741["part_b_vix_regimes"]
labels = ["VIX<15\n(平靜)", "VIX 15-20\n(正常)", "VIX 20-25\n(偏高)", "VIX≥25\n(恐慌)"]
keys = ["Low (VIX<15)", "Medium (15-20)", "Elevated (20-25)", "High (VIX>=25)"]
absret = [reg[k]["mean_abs_return_pct"] for k in keys]
pos = [reg[k]["pct_positive"] for k in keys]

# ---- RIGHT: 低 VIX 後的前瞻 63 日最大回檔 ----
vc = json.load(open(ROOT / "experiments/k_vix_complacency_20260621/k_vix_complacency_20260621_results.json"))
low = vc["conditional"]["bottom_quintile_realtime"]["fwd63"]["mdd"]
uncond = vc["unconditional"]["fwd63"]["mdd"]
cats = ["典型回檔\n(中位數)", "倒楣時回檔\n(第95百分位)"]
low_vals = [low["median"] * 100, low["p95"] * 100]
all_vals = [uncond["median"] * 100, uncond["p95"] * 100]

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13.5, 5.6))
BLUE, ORANGE, GREEN, RED = "#2f6fed", "#f28e2b", "#3a9d6e", "#d4493f"

# LEFT
x = np.arange(len(labels))
bars = ax1.bar(x, absret, color=[GREEN, BLUE, ORANGE, RED], width=0.62, zorder=3)
ax1.set_xticks(x); ax1.set_xticklabels(labels, fontsize=10.5)
ax1.set_ylabel("非農公佈日 SPY 平均絕對波動 (%)", fontsize=11)
ax1.set_title("恐慌越高，事件日波動越大（NFP 日，195 次）", fontsize=12.5, pad=10)
ax1.grid(axis="y", alpha=0.25, zorder=0)
for xi, v, p in zip(x, absret, pos):
    ax1.text(xi, v + 0.03, f"{v:.2f}%", ha="center", va="bottom", fontsize=10.5, fontweight="bold")
    ax1.text(xi, 0.06, f"上漲 {p:.0f}%", ha="center", va="bottom", fontsize=9, color="white", fontweight="bold")
ax1.set_ylim(0, 1.75)

# RIGHT
xx = np.arange(len(cats)); w = 0.36
b1 = ax2.bar(xx - w/2, low_vals, w, label="低 VIX 之後（n≈2,082 天）", color=BLUE, zorder=3)
b2 = ax2.bar(xx + w/2, all_vals, w, label="不分狀態（全樣本）", color="#9aa7b8", zorder=3)
ax2.set_xticks(xx); ax2.set_xticklabels(cats, fontsize=10.5)
ax2.set_ylabel("接下來三個月 SPY 最大回檔 (%)", fontsize=11)
ax2.set_title("低 VIX 之後，跌得更淺（1990 起，9,183 天）", fontsize=12.5, pad=10)
ax2.legend(fontsize=9.5, loc="upper left")
ax2.grid(axis="y", alpha=0.25, zorder=0)
for b in list(b1) + list(b2):
    ax2.text(b.get_x() + b.get_width()/2, b.get_height() + 0.2, f"{b.get_height():.1f}%",
             ha="center", va="bottom", fontsize=10, fontweight="bold")
ax2.set_ylim(0, 22)

fig.suptitle("VIX 不是計時器，是溫度計：市場狀態如何決定波動", fontsize=15, fontweight="bold", y=0.99)
fig.text(0.5, 0.005, "資料來源：yfinance（SPY, ^VIX, ^GSPC）。左圖=實驗 K741（2010–2026, 195 次 NFP）；右圖=實驗 k_vix_complacency_20260621（1990–2026, 9,183 天）。VolPred 每日精選導讀。",
         ha="center", fontsize=8, color="#555")
fig.tight_layout(rect=[0, 0.03, 1, 0.96])
out = ROOT / "experiments/digest_2026_06_21/digest_vix_regime_chart.png"
fig.savefig(out, dpi=150, bbox_inches="tight")
print("SAVED", out)
print("LEFT absret:", [round(v,3) for v in absret], "pos:", [round(v,1) for v in pos])
print("RIGHT low:", [round(v,2) for v in low_vals], "all:", [round(v,2) for v in all_vals])
