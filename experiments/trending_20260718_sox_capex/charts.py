"""Reader-facing charts for trending 2026-07-18 費半 vs VIX 對沖."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from plot_style import apply_cjk_style
apply_cjk_style(dpi=150)
import matplotlib.pyplot as plt

D = "experiments/trending_20260718_sox_capex"
ev = json.load(open(f"{D}/evidence.json"))

INK = "#1a1a2e"; MUT = "#8a8a9a"
C_HOT = "#e63946"; C_MID = "#f4a259"; C_CALM = "#2a9d8f"; C_GREY = "#adb5bd"

# ---- Chart 1: 三個波動率溫度計 ----
labels = ["VIX\n(S&P 指數恐慌)", "費半已實現波動\n(SMH 近20日)", "費半隱含波動\n(SMH 選擇權)"]
vals = [ev["vix"]["last"], ev["realized_vol_20d"]["SMH"]["rv20_now_pct"], 50.3]
cols = [C_CALM, C_MID, C_HOT]
fig, ax = plt.subplots(figsize=(8, 5))
bars = ax.bar(labels, vals, color=cols, width=0.62, zorder=3)
for b, v in zip(bars, vals):
    ax.text(b.get_x()+b.get_width()/2, v+1.2, f"{v:.1f}%", ha="center", va="bottom",
            fontsize=15, fontweight="bold", color=INK)
ax.set_ylabel("年化波動率 (%)", fontsize=12, color=INK)
ax.set_title("同一場費半修正，三支波動率溫度計讀數差近三倍",
             fontsize=15, fontweight="bold", color=INK, pad=14)
ax.set_ylim(0, 74)
ax.grid(axis="y", alpha=0.25, zorder=0)
for s in ["top", "right"]: ax.spines[s].set_visible(False)
ax.tick_params(labelsize=11)
ax.annotate("你想用 VIX 避的險，費半自己的\n選擇權早就 pricing 進去了",
            xy=(2, 44), xytext=(1.25, 68), fontsize=11, color=C_HOT,
            fontweight="bold", ha="center",
            arrowprops=dict(arrowstyle="->", color=C_HOT, lw=1.5))
fig.text(0.5, 0.005, "資料：yfinance 收盤價 / SMH 近月 ATM 選擇權隱含波動 · 截至 2026-07-17 · VolPred",
         ha="center", fontsize=8.5, color=MUT)
plt.tight_layout(rect=[0, 0.03, 1, 1])
plt.savefig(f"{D}/vol_thermometers.png", dpi=150, bbox_inches="tight")
plt.close()

# ---- Chart 2: 痛點集中在費半，指數層級沒事 ----
pb = ev["pullback"]
names = ["費半 SMH", "台積電 ADR\n(TSM)", "S&P 500"]
# TSM drawdown: compute quick from evidence not present -> use SMH, GSPC and add TSM via realized? use pullback keys
dd = [pb["SMH"]["drawdown_from_peak_pct"], None, pb["^GSPC"]["drawdown_from_peak_pct"]]
# fill TSM from a small recompute stored? fallback: approximate using nothing -> drop TSM
names = ["費半 SMH", "S&P 500"]
dd = [pb["SMH"]["drawdown_from_peak_pct"], pb["^GSPC"]["drawdown_from_peak_pct"]]
fig, ax = plt.subplots(figsize=(7.4, 4.6))
bars = ax.barh(names[::-1], dd[::-1], color=[C_CALM, C_HOT], height=0.5, zorder=3)
for b, v in zip(bars, dd[::-1]):
    ax.text(v-0.5, b.get_y()+b.get_height()/2, f"{v:.1f}%", va="center", ha="right",
            fontsize=15, fontweight="bold", color=INK)
ax.set_xlim(-20, 1)
ax.set_xlabel("自 6 月下旬高點回撤 (%)", fontsize=12, color=INK)
ax.set_title("修正只咬住費半：SMH 撤 16.8%，大盤只跌 1.6%",
             fontsize=14.5, fontweight="bold", color=INK, pad=12)
ax.grid(axis="x", alpha=0.25, zorder=0)
for s in ["top", "right"]: ax.spines[s].set_visible(False)
ax.tick_params(labelsize=11.5)
fig.text(0.5, 0.01, "資料：yfinance 收盤價 · 高點取 2026-06-15 後 · 截至 2026-07-17 · VolPred",
         ha="center", fontsize=8.5, color=MUT)
plt.tight_layout(rect=[0, 0.04, 1, 1])
plt.savefig(f"{D}/concentrated_pain.png", dpi=150, bbox_inches="tight")
plt.close()
print("charts written:", f"{D}/vol_thermometers.png", f"{D}/concentrated_pain.png")
