#!/usr/bin/env python3
"""六月科技股回檔 懶人包圖組 renderer（data-bound，數字全讀 results.json）。

Codex 額度用盡（2026-07-09，至 7/11 recharge）→ 主線程自寫 matplotlib poster
renderer 作 primary-path 等效替代：每個數字皆對應 <exp>_results.json 欄位，
可復現、零成本、無 AI 影像幻覺。professional 版面（深色標題列 + 大數字 + 分區）。
"""
import json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
from pathlib import Path

matplotlib.rcParams["font.sans-serif"] = ["Arial Unicode MS", "Heiti TC",
                                          "Hiragino Sans GB", "STHeiti"]
matplotlib.rcParams["axes.unicode_minus"] = False

BASE = Path(__file__).resolve().parent
OUT = BASE / "lazypack"
OUT.mkdir(exist_ok=True)
R = json.load(open(BASE / "trending_mag7_jun2026_vol_results.json"))

INK = "#1a2330"
BAND = "#16283d"
ACCENT = "#c0392b"
BLUE = "#2c6fb0"
GREY = "#6b7683"
SRC = "資料來源：yfinance 日收盤價 2026-01-01~07-09（experiment trending_mag7_jun2026_vol）"


def _canvas():
    fig = plt.figure(figsize=(10.67, 6.67), dpi=150)  # ~1600x1000
    fig.patch.set_facecolor("white")
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")
    return fig, ax


def _band(ax, title):
    ax.add_patch(plt.Rectangle((0, 88), 100, 12, color=BAND, zorder=1))
    ax.text(4, 94, title, color="white", fontsize=23, fontweight="bold",
            va="center", ha="left")
    ax.text(50, 2.5, SRC, color=GREY, fontsize=8.5, va="center", ha="center")


def save(fig, name):
    fig.savefig(OUT / name, dpi=150, facecolor="white", bbox_inches=None)
    plt.close(fig)
    print("[ok]", OUT / name)


# ---------- Panel 1: framework ----------
fig, ax = _canvas()
_band(ax, "六月科技股回檔：一句話看懂")
ax.text(4, 80, "指數看起來只跌一點，個股卻很痛——這篇拆給你看為什麼。",
        fontsize=15.5, color=INK, va="center")
# two concept cards
def card(x, w, head, body, col):
    ax.add_patch(FancyBboxPatch((x, 30), w, 40, boxstyle="round,pad=0.6,rounding_size=2",
                                fc="#f3f5f8", ec=col, lw=2, zorder=2))
    ax.text(x + w / 2, 63, head, fontsize=16.5, fontweight="bold", color=col,
            ha="center", va="center")
    ax.text(x + w / 2, 46, body, fontsize=12.5, color=INK, ha="center", va="center",
            wrap=True, linespacing=1.5)
card(6, 40, "已實現波動率", "過去 20 個交易日\n價格「實際」抖多兇\n（後顧、慢半拍）", BLUE)
card(54, 40, "VIX 恐慌指數", "市場對「未來」\n波動的猜測\n（前瞻、退得早）", ACCENT)
ax.text(50, 18, "兩者描述不同時間軸——用錯會誤判「風暴過了沒」", fontsize=13,
        color=INK, ha="center", fontstyle="italic")
save(fig, "1_framework.png")

# ---------- Panel 2: drawdown ----------
dd = R["drawdown_june2026"]
order = ["QQQ", "MSFT", "NVDA", "META", "AMZN", "AAPL", "TSLA", "GOOGL"]
labels_zh = {"QQQ": "QQQ 指數", "MSFT": "微軟", "NVDA": "輝達", "META": "META",
             "AMZN": "亞馬遜", "AAPL": "蘋果", "TSLA": "特斯拉", "GOOGL": "谷歌"}
vals = [dd[t]["drawdown_pct"] for t in order]
fig, ax = _canvas()
_band(ax, "真實回檔幅度：指數 −7%，個股 −10~−23%")
ax0 = fig.add_axes([0.09, 0.12, 0.86, 0.66])
colors = [GREY] + [ACCENT] * (len(order) - 1)
bars = ax0.barh(range(len(order))[::-1], vals, color=colors)
ax0.set_yticks(range(len(order))[::-1])
ax0.set_yticklabels([labels_zh[t] for t in order], fontsize=12.5)
ax0.set_xlim(-26, 2)
for i, (t, v) in enumerate(zip(order, vals)):
    ax0.text(v - 0.5, (len(order) - 1 - i), f"{v:.1f}%", va="center", ha="right",
             fontsize=12, fontweight="bold", color="white" if v < -3 else INK)
ax0.set_xlabel("6 月高點→低點回檔幅度 (%)", fontsize=11.5)
for s in ("top", "right"):
    ax0.spines[s].set_visible(False)
ax0.axvline(0, color="#333", lw=0.8)
save(fig, "2_drawdown.png")

# ---------- Panel 3: timing (RV vs VIX) ----------
rv = R["realized_vol_segments"]  # expects pre/stress/post-ish keys
vix = R["vix"]
fig, ax = _canvas()
_band(ax, "時間差陷阱：VIX 早退，你的波動晚退")
# RV three-stage big numbers
def big(x, y, num, cap, col):
    ax.text(x, y, num, fontsize=30, fontweight="bold", color=col, ha="center", va="center")
    ax.text(x, y - 11, cap, fontsize=11.5, color=INK, ha="center", va="center")

# pull QQQ segment values robustly
seg = rv["QQQ"]
pre = seg["before_peak"]
stress = seg["during_selloff"]
post = seg["after_trough"]
ax.text(50, 80, "QQQ 年化已實現波動率（20 日）", fontsize=14, color=INK, ha="center")
big(20, 62, f"{pre:.1f}%", "回檔前", BLUE)
big(50, 62, f"{stress:.1f}%", "壓力段", "#e08e0b")
big(80, 62, f"{post:.1f}%", "觸底後", ACCENT)
ax.annotate("", xy=(72, 62), xytext=(30, 62),
            arrowprops=dict(arrowstyle="->", color=GREY, lw=1.5))
ax.text(50, 40, f"VIX 6/10 見高 {vix['peak_during_selloff']:.2f} 後就回落；\n"
        f"但六檔個股 6/25–26 才落底，已實現波動率更拖到觸底後才見頂。",
        fontsize=13, color=INK, ha="center", va="center", linespacing=1.6)
ax.text(50, 20, "VIX 降 ≠ 你的持股不抖了", fontsize=15, fontweight="bold",
        color=ACCENT, ha="center")
save(fig, "3_timing.png")

# ---------- Panel 4: dispersion ----------
cs = R["cross_section_rv_during_selloff"]
items = sorted(cs.items(), key=lambda kv: kv[1], reverse=True)
fig, ax = _canvas()
_band(ax, "「七巨頭」根本不是同一筆交易")
ax0 = fig.add_axes([0.30, 0.12, 0.64, 0.66])
names = [labels_zh.get(k, k) for k, _ in items]
vv = [v for _, v in items]
cols = [ACCENT if i == 0 else (BLUE if i == len(items) - 1 else GREY)
        for i in range(len(items))]
ax0.barh(range(len(items))[::-1], vv, color=cols)
ax0.set_yticks(range(len(items))[::-1])
ax0.set_yticklabels(names, fontsize=12.5)
for i, v in enumerate(vv):
    ax0.text(v + 0.5, len(items) - 1 - i, f"{v:.1f}%", va="center", fontsize=11.5,
             fontweight="bold", color=INK)
ax0.set_xlabel("壓力段年化已實現波動率 (%)", fontsize=11.5)
ax0.set_xlim(0, max(vv) * 1.18)
for s in ("top", "right"):
    ax0.spines[s].set_visible(False)
diff = vv[0] - vv[-1]
ax.text(4, 62, "最抖 vs 最穩\n差", fontsize=13, color=INK, va="center", linespacing=1.5)
ax.text(4, 44, f"{diff:.1f}pp", fontsize=26, fontweight="bold", color=ACCENT, va="center")
ax.text(4, 30, "跌最深 ≠\n抖最兇", fontsize=12.5, color=GREY, va="center", linespacing=1.5)
save(fig, "4_dispersion.png")

print("DONE 4 panels")
