"""Lazypack (懶人包圖組) renderer for AI-capex vs defensive rotation trending article.

Data-bound: every number is read from results.json (research honesty).
Produces 3 poster-style PNGs: concept / results-rv / results-return.
Reproducible: same results.json -> same PNGs. seed not needed (deterministic layout).
"""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

HERE = Path(__file__).resolve().parent
RESULTS = json.loads((HERE / "results.json").read_text())
OUT = HERE.parent.parent / "storage/drafts/assets/lazypack_ai_capex_20260707"
OUT.mkdir(parents=True, exist_ok=True)

# CJK font
for name in ["PingFang TC", "Heiti TC", "Arial Unicode MS", "Songti TC"]:
    try:
        font_manager.findfont(name, fallback_to_default=False)
        plt.rcParams["font.sans-serif"] = [name]
        break
    except Exception:
        continue
plt.rcParams["axes.unicode_minus"] = False

INK = "#1a2233"
MUTED = "#6b7280"
TECH = "#e2493b"   # 科技 red
DEF = "#2f8f6b"    # 防禦 green
ACCENT = "#c8922a"
BG = "#ffffff"
SOURCE = "資料來源：yfinance 日收盤，2025-10-01 至 2026-07-06（191 交易日）"

lat = RESULTS["latest_rv20_pct"]
ago = RESULTS["rv20_1m_ago_pct"]
ret = RESULTS["cumulative_return_pct"]
spread = RESULTS["qqq_minus_defensive_rv_spread"]
vix = RESULTS["vix"]
skew = RESULTS["skew_index"]
corr = RESULTS["rolling60_corr_qqq_vs_defensive"]


def _footer(fig):
    fig.text(0.5, 0.03, SOURCE, ha="center", fontsize=11, color=MUTED)


def _title_bar(ax, text):
    ax.text(0.5, 0.5, text, ha="center", va="center", fontsize=22,
            color="white", fontweight="bold", transform=ax.transAxes)
    ax.set_facecolor(INK)
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)


# ---------- Panel 1: concept ----------
fig = plt.figure(figsize=(10.7, 6.7), dpi=150, facecolor=BG)
gs = fig.add_gridspec(4, 2, height_ratios=[0.7, 1.4, 1.4, 0.2],
                      hspace=0.35, wspace=0.15, left=0.06, right=0.94, top=0.95, bottom=0.1)
tb = fig.add_subplot(gs[0, :]); _title_bar(tb, "AI 資本支出疑慮：這是板塊震動，不是全市場恐慌")

def big_stat(ax, top, num, sub, color):
    ax.axis("off")
    ax.text(0.5, 0.86, top, ha="center", va="center", fontsize=14, color=MUTED)
    ax.text(0.5, 0.46, num, ha="center", va="center", fontsize=44, color=color, fontweight="bold")
    ax.text(0.5, 0.08, sub, ha="center", va="center", fontsize=12.5, color=INK)

a1 = fig.add_subplot(gs[1, 0]); big_stat(a1, "QQQ 20日已實現波動率", f"{lat['QQQ']:.1f}%",
        f"一個月前 {ago['QQQ']:.1f}% → 翻倍", TECH)
a2 = fig.add_subplot(gs[1, 1]); big_stat(a2, "大盤恐慌指數 VIX", f"{vix['now']:.1f}",
        f"三個月前 {vix['3m_ago']:.1f} → 仍在低檔", DEF)
a3 = fig.add_subplot(gs[2, 0]); big_stat(a3, "防禦籃 20日波動率", f"{lat['DEF_BASKET']:.1f}%",
        "XLV／XLP／XLU 等權，幾乎沒動", DEF)
a4 = fig.add_subplot(gs[2, 1]); big_stat(a4, "尾部風險定價 SKEW", f"{skew['now']:.0f}",
        "偏高：選擇權市場仍為尾部付費", ACCENT)
_footer(fig)
fig.savefig(OUT / "concept.png", facecolor=BG, bbox_inches="tight")
plt.close(fig)


# ---------- Panel 2: results-rv ----------
fig = plt.figure(figsize=(10.7, 6.7), dpi=150, facecolor=BG)
gs = fig.add_gridspec(3, 1, height_ratios=[0.55, 2.2, 0.5], hspace=0.3,
                      left=0.1, right=0.94, top=0.95, bottom=0.12)
tb = fig.add_subplot(gs[0]); _title_bar(tb, "波動率背離：科技炸開，防禦躺平")
ax = fig.add_subplot(gs[1])
labels = ["XLK\n純科技", "QQQ\n那斯達克100", "XLV\n醫療", "XLP\n必需消費", "XLU\n公用事業", "防禦籃\n等權"]
vals = [lat["XLK"], lat["QQQ"], lat["XLV"], lat["XLP"], lat["XLU"], lat["DEF_BASKET"]]
colors = [TECH, TECH, DEF, DEF, DEF, DEF]
bars = ax.bar(labels, vals, color=colors, width=0.62)
for b, v in zip(bars, vals):
    ax.text(b.get_x() + b.get_width()/2, v + 0.8, f"{v:.1f}%", ha="center",
            fontsize=13, fontweight="bold", color=INK)
ax.set_ylabel("20 日已實現波動率（年化 %）", fontsize=12)
ax.set_ylim(0, max(vals) * 1.18)
ax.spines[["top", "right"]].set_visible(False)
ax.tick_params(labelsize=11)
ax.text(0.98, 0.93,
        f"科技−防禦利差 {spread['now']:.1f} pp\n一個月前僅 {spread['1m_ago']:.1f}｜近90日高點 {spread['window_max']:.1f}",
        transform=ax.transAxes, ha="right", va="top", fontsize=12.5, color=TECH,
        fontweight="bold", bbox=dict(boxstyle="round,pad=0.5", fc="#fdeeec", ec=TECH))
_footer(fig)
fig.savefig(OUT / "results-rv.png", facecolor=BG, bbox_inches="tight")
plt.close(fig)


# ---------- Panel 3: results-return ----------
fig = plt.figure(figsize=(10.7, 6.7), dpi=150, facecolor=BG)
gs = fig.add_gridspec(3, 1, height_ratios=[0.55, 2.2, 0.5], hspace=0.3,
                      left=0.1, right=0.94, top=0.95, bottom=0.12)
tb = fig.add_subplot(gs[0]); _title_bar(tb, "近一個月報酬翻轉：防禦股接棒")
ax = fig.add_subplot(gs[1])
order = ["QQQ", "XLK", "XLV", "XLP", "XLU"]
names = {"QQQ": "QQQ", "XLK": "XLK 純科技", "XLV": "XLV 醫療", "XLP": "XLP 必需消費", "XLU": "XLU 公用"}
vals = [ret["1M"][k] for k in order]
colors = [TECH if v < 0 else DEF for v in vals]
bars = ax.barh([names[k] for k in order][::-1], vals[::-1], color=colors[::-1], height=0.6)
for b, v in zip(bars, vals[::-1]):
    ax.text(v + (0.25 if v >= 0 else -0.25), b.get_y() + b.get_height()/2,
            f"{v:+.1f}%", va="center", ha="left" if v >= 0 else "right",
            fontsize=13, fontweight="bold", color=INK)
ax.axvline(0, color=MUTED, lw=1)
ax.set_xlabel("近一個月累積報酬 (%)", fontsize=12)
ax.set_xlim(min(vals) * 1.3, max(vals) * 1.35)
ax.spines[["top", "right"]].set_visible(False)
ax.tick_params(labelsize=11.5)
ax.text(0.98, 0.14,
        f"SKEW {skew['now']:.0f}（尾部風險偏高）\nQQQ×防禦 60日相關 {corr['3m_ago']:+.2f} → {corr['now']:+.2f}",
        transform=ax.transAxes, ha="right", va="bottom", fontsize=12, color=ACCENT,
        fontweight="bold", bbox=dict(boxstyle="round,pad=0.5", fc="#fdf6e8", ec=ACCENT))
_footer(fig)
fig.savefig(OUT / "results-return.png", facecolor=BG, bbox_inches="tight")
plt.close(fig)

print("DONE:", [p.name for p in sorted(OUT.glob("*.png"))])
