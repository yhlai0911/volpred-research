"""Generate the 2 evidence charts for the Mag7 capex-intensity vs skew
cross-section snapshot (2026-07-05). Reads results.json, writes PNGs into
figures/.
"""
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

plt.rcParams["font.sans-serif"] = ["PingFang HK", "Heiti TC", "Arial Unicode MS", "STHeiti", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["figure.facecolor"] = "white"
plt.rcParams["axes.facecolor"] = "white"

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, "results.json")) as f:
    R = json.load(f)

rows = sorted(R["cross_section"], key=lambda r: -(r["capex_intensity_pct"] or 0))
tickers = [r["ticker"] for r in rows]
capex = [r["capex_intensity_pct"] for r in rows]
skew = [r["skew_10pct_otm_pp"] for r in rows]

NAVY = "#1f3a5f"
ORANGE = "#e07b39"
GREY = "#8a8f98"
BG = "#ffffff"

os.makedirs(os.path.join(HERE, "figures"), exist_ok=True)

# --- Chart 1: dual-bar, sorted by capex intensity -----------------------
fig, ax1 = plt.subplots(figsize=(9, 5.5), dpi=160)
x = np.arange(len(tickers))
w = 0.38

bars1 = ax1.bar(x - w / 2, capex, width=w, color=NAVY, label="TTM 資本支出 / 營收 (%)")
ax1.set_ylabel("資本支出強度 = TTM CapEx / TTM 營收 (%)", color=NAVY, fontsize=11)
ax1.tick_params(axis="y", labelcolor=NAVY)
ax1.set_xticks(x)
ax1.set_xticklabels(tickers, fontsize=11)
for xi, v in zip(x - w / 2, capex):
    ax1.text(xi, v + 0.8, f"{v:.1f}", ha="center", va="bottom", fontsize=9, color=NAVY)

ax2 = ax1.twinx()
colors2 = [ORANGE if v is not None and v >= 0 else "#6b8e9c" for v in skew]
bars2 = ax2.bar(x + w / 2, skew, width=w, color=colors2, label="10% OTM Put-Call IV 差 (pp)")
ax2.axhline(0, color=GREY, linewidth=0.8)
ax2.set_ylabel("Put IV − Call IV, ±10% OTM (百分點)", color=ORANGE, fontsize=11)
ax2.tick_params(axis="y", labelcolor="#b5651d")
for xi, v in zip(x + w / 2, skew):
    va = "bottom" if v >= 0 else "top"
    off = 0.15 if v >= 0 else -0.15
    ax2.text(xi, v + off, f"{v:+.1f}", ha="center", va=va, fontsize=9, color="#b5651d")

ax1.set_title("Mag 7 資本支出強度 vs. 目前選擇權偏斜（2026-07-05 快照，到期日 2026-08-07）", fontsize=12, pad=14)
fig.text(0.5, -0.02, "資料來源：yfinance 即時選擇權鏈 + 最近 4 季財報現金流量表（TTM capex/revenue）。n=7，單一快照，非統計檢定。",
          ha="center", fontsize=8.5, color=GREY)
fig.tight_layout()
fig.savefig(os.path.join(HERE, "figures", "chart1_capex_vs_skew_bars.png"), bbox_inches="tight")
plt.close(fig)

# --- Chart 2: scatter with rank correlation ------------------------------
fig, ax = plt.subplots(figsize=(7.5, 6), dpi=160)
capex_all = [r["capex_intensity_pct"] for r in rows]
skew_all = [r["skew_10pct_otm_pp"] for r in rows]
ax.scatter(capex_all, skew_all, s=140, color=NAVY, zorder=3, edgecolor="white", linewidth=1.2)
label_offsets = {"AAPL": (10, 14), "NVDA": (10, -16)}
for t, cx, sk in zip(tickers, capex_all, skew_all):
    off = label_offsets.get(t, (8, 6))
    ax.annotate(t, (cx, sk), textcoords="offset points", xytext=off, fontsize=11, fontweight="bold", color=NAVY)

# simple OLS line for visual reference only (not a claim of causal fit)
z = np.polyfit(capex_all, skew_all, 1)
xs = np.linspace(min(capex_all) - 2, max(capex_all) + 2, 50)
ax.plot(xs, np.polyval(z, xs), color=ORANGE, linestyle="--", linewidth=1.6, zorder=2,
        label="線性趨勢線（僅供視覺參考）")
ax.axhline(0, color=GREY, linewidth=0.8, zorder=1)

rho = R["spearman_capex_vs_skew"]["rho"]
ax.set_xlabel("資本支出強度：TTM CapEx / TTM 營收 (%)", fontsize=11)
ax.set_ylabel("10% OTM Put IV − Call IV (百分點)", fontsize=11)
ax.set_title(f"資本支出強度排名 vs. 下檔偏斜排名（Spearman ρ = {rho}，n=7）", fontsize=12, pad=12)
ax.legend(loc="upper right", fontsize=9, frameon=False)
fig.text(0.5, -0.02, "n=7 為描述性排名相關，非具統計檢定力的正式假設檢定；單日快照，會隨市場變化。",
          ha="center", fontsize=8.5, color=GREY)
fig.tight_layout()
fig.savefig(os.path.join(HERE, "figures", "chart2_scatter_rank_corr.png"), bbox_inches="tight")
plt.close(fig)

print("Saved chart1_capex_vs_skew_bars.png and chart2_scatter_rank_corr.png")
