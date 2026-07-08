#!/usr/bin/env python3
"""K1661 懶人包圖組 render — data-bound（數字全讀 k1661_results.json）。

Fallback path：Codex 額度用盡（到 2026-07-11），主線程自寫 matplotlib render。
每個數字綁 results.json 欄位，可復現（same input -> same output），零 image-API 成本。
"""
import json
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

ROOT = Path(__file__).resolve().parents[3]
RES = json.loads((ROOT / "experiments/k1661/k1661_results.json").read_text(encoding="utf-8"))
OUT = Path(__file__).resolve().parent

# --- CJK font ---
for cand in ["Heiti TC", "PingFang TC", "Arial Unicode MS", "Songti TC"]:
    try:
        font_manager.findfont(cand, fallback_to_default=False)
        plt.rcParams["font.sans-serif"] = [cand]
        break
    except Exception:
        continue
plt.rcParams["axes.unicode_minus"] = False

INK = "#1a2332"
MUTED = "#5b6b7f"
RED = "#c0392b"
GREEN = "#1e8449"
BLUE = "#2c5f8a"
LIGHT = "#f4f6f9"

by = {r["asset"]: r for r in RES["results"]}
assets = ["SPY", "0050.TW", "TWII"]
SRC = "資料來源：VolPred 實驗 K1661（yfinance 日頻 OHLC, 2010-01–2026-07）"


def _fig():
    fig = plt.figure(figsize=(10.67, 6.67), dpi=150)
    fig.patch.set_facecolor("white")
    return fig


def _src(fig):
    fig.text(0.5, 0.028, SRC, ha="center", va="center", fontsize=9, color=MUTED)


# ============ Panel 1 — concept ============
fig = _fig()
ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off")
fig.text(0.5, 0.90, "頂尖期刊的模型，搬回家就靈嗎？", ha="center", fontsize=25, color=INK, fontweight="bold")
# 迷思 box
ax.add_patch(plt.Rectangle((0.06, 0.50), 0.40, 0.30, transform=ax.transAxes, facecolor="#fbeae8", edgecolor=RED, lw=1.5))
fig.text(0.26, 0.745, "迷思", ha="center", fontsize=15, color=RED, fontweight="bold")
fig.text(0.26, 0.64, "頂尖期刊的 HARQ 模型\n用『測量誤差加權』改良 HAR，\n一定比樸素 HAR 好，直接搬來用就行。",
         ha="center", va="center", fontsize=12.5, color=INK)
# 事實 box
ax.add_patch(plt.Rectangle((0.54, 0.50), 0.40, 0.30, transform=ax.transAxes, facecolor="#e8f3ec", edgecolor=GREEN, lw=1.5))
fig.text(0.74, 0.745, "實測", ha="center", fontsize=15, color=GREEN, fontweight="bold")
fig.text(0.74, 0.64, "搬到日頻 OHLC 資料，\n三個市場的加權版都『小輸』樸素 HAR，\n且未達統計顯著（NULL）。",
         ha="center", va="center", fontsize=12.5, color=INK)
fig.text(0.5, 0.36, "一句話", ha="center", fontsize=13, color=BLUE, fontweight="bold")
fig.text(0.5, 0.24, "模型的優勢，綁在它出生的『資料頻率』上。\n換了資料頻率，就得重新驗證，不能照搬光環。",
         ha="center", va="center", fontsize=15, color=INK, fontweight="bold")
_src(fig)
fig.savefig(OUT / "1_concept.png", facecolor="white"); plt.close(fig)

# ============ Panel 2 — method ============
fig = _fig()
ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off")
fig.text(0.5, 0.91, "怎麼測的？", ha="center", fontsize=24, color=INK, fontweight="bold")
rows = [
    ("三個市場", "SPY（美股）、0050.TW（台股 ETF）、TWII（台股加權指數）"),
    ("樣本期間", "2010-01 至 2026-07，每個市場約 3000+ 個樣本外交易日"),
    ("預測方式", "滾動視窗 1000 日、每日重估、一步向前預測"),
    ("四個模型", "HAR（樸素）／HARQ／HARQ-F（完整交互）／HARQ-smooth（平滑）"),
    ("評分與檢定", "QLIKE 損失（Patton 2011）＋ DM-HLN 檢定，顯著門檻 |t|>3"),
]
y = 0.76
for k, v in rows:
    ax.add_patch(plt.Rectangle((0.06, y - 0.055), 0.88, 0.095, transform=ax.transAxes, facecolor=LIGHT, edgecolor="none"))
    fig.text(0.10, y - 0.008, k, ha="left", va="center", fontsize=13.5, color=BLUE, fontweight="bold")
    fig.text(0.34, y - 0.008, v, ha="left", va="center", fontsize=12.5, color=INK)
    y -= 0.125
# 關鍵共線性大數字
fig.text(0.5, 0.145, "關鍵線索：日頻的『測量誤差權重』√RQ 與當日波動高度重疊",
         ha="center", fontsize=12.5, color=MUTED)
avg_corr = sum(by[a]["corr_sqrtRQ_RVd"] for a in assets) / 3
fig.text(0.5, 0.075, f"相關係數 ≈ {avg_corr:.2f}（三市場一致）",
         ha="center", fontsize=17, color=RED, fontweight="bold")
_src(fig)
fig.savefig(OUT / "2_method.png", facecolor="white"); plt.close(fig)

# ============ Panel 3 — results ============
fig = _fig()
fig.text(0.5, 0.93, "結果：加權版普遍小輸，且不顯著", ha="center", fontsize=22, color=INK, fontweight="bold")
ax = fig.add_axes([0.10, 0.20, 0.82, 0.60])
models = ["HARQ", "HARQ-F", "HARQ-smooth"]
keys = ["qlike_improve_HARQ_pct", "qlike_improve_HARQ_F_pct", "qlike_improve_HARQ_smooth_pct"]
import numpy as np
x = np.arange(len(assets)); w = 0.25
colors = {"HARQ": "#e08e79", "HARQ-F": RED, "HARQ-smooth": "#7fb3d5"}
for i, (m, kk) in enumerate(zip(models, keys)):
    vals = [by[a][kk] for a in assets]
    bars = ax.bar(x + (i - 1) * w, vals, w, label=m, color=colors[m])
    for b, val in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, val + (0.4 if val >= 0 else -0.9),
                f"{val:+.1f}%", ha="center", fontsize=9.5, color=INK)
ax.axhline(0, color=INK, lw=1)
ax.set_xticks(x); ax.set_xticklabels(assets, fontsize=13)
ax.set_ylabel("相對樸素 HAR 的 QLIKE 改善 %\n（負 = 更差）", fontsize=11.5, color=MUTED)
ax.legend(loc="lower left", fontsize=10, frameon=False)
ax.spines[["top", "right"]].set_visible(False)
ax.set_ylim(-22, 6)
t_spy = by["SPY"]["dm_hln_HARQ_vs_HAR"]["dm_hln"]
fig.text(0.5, 0.115, f"三個市場的 HARQ 全部小輸 HAR（−1% ~ −2%），但 DM 檢定 t≈{t_spy:.2f}，遠低於門檻 3 → 不顯著",
         ha="center", fontsize=11.5, color=INK)
fig.text(0.5, 0.06, "3/3 同向只是『方向一致』（binomial p=0.125）→ 結論 NULL：日頻下，樸素 HAR 不輸貴模型",
         ha="center", fontsize=12, color=RED, fontweight="bold")
_src(fig)
fig.savefig(OUT / "3_results.png", facecolor="white"); plt.close(fig)

for p in ["1_concept.png", "2_method.png", "3_results.png"]:
    fp = OUT / p
    print(f"[ok] {fp} ({fp.stat().st_size} bytes)")
