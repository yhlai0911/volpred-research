"""EP4 三張圖 — 全部直讀 drone_ep4_six_dim_evidence.json，不硬寫任何數字。"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager, rcParams

for cand in ["Heiti TC", "PingFang TC", "Songti TC", "Arial Unicode MS"]:
    if any(cand in f.name for f in font_manager.fontManager.ttflist):
        rcParams["font.sans-serif"] = [cand]
        break
rcParams["axes.unicode_minus"] = False

EV = json.loads(Path("storage/drafts/drone_ep4_six_dim_evidence.json").read_text(encoding="utf-8"))
OUT = Path("storage/drafts/assets")
OUT.mkdir(parents=True, exist_ok=True)

cos = EV["companies"]
names = [c["name"] for c in cos]
bench_ret = EV["benchmark"]["window_return"] * 100

INK, HOT, COOL, WARN = "#1f2933", "#d64545", "#2f6f8f", "#e8a33d"


# --- 圖 1：股價漲幅 vs 營收成長 ------------------------------------------------
fig, ax = plt.subplots(figsize=(11, 6))
px = [c["market"]["window_return"] * 100 for c in cos]
rev = [(c["fundamental"].get("revenue_yoy") or 0) * 100 for c in cos]
x = range(len(names))
w = 0.38
ax.bar([i - w / 2 for i in x], px, w, label="近一年股價報酬", color=HOT)
ax.bar([i + w / 2 for i in x], rev, w, label="最新年度營收年增率", color=COOL)
ax.axhline(bench_ret, ls="--", lw=1.6, color=INK, alpha=0.7)
ax.text(len(names) - 0.45, bench_ret + 6, f"台股加權指數 +{bench_ret:.0f}%", ha="right", fontsize=10, color=INK)
ax.axhline(0, color=INK, lw=0.8)
for i, (p, r) in enumerate(zip(px, rev)):
    ax.text(i - w / 2, p + 6, f"{p:+.0f}%", ha="center", fontsize=9, color=HOT)
    ax.text(i + w / 2, r + (6 if r >= 0 else -14), f"{r:+.1f}%", ha="center", fontsize=9, color=COOL)
ax.set_xticks(list(x))
ax.set_xticklabels(names, fontsize=11)
ax.set_ylabel("%")
ax.set_title("六檔龍頭：股價跑得多快，營收跟上了多少\n"
             f"價格 {EV['method']['price_window'][0]} → {EV['method']['price_window'][1]}；營收為公司年報揭露之最新年度 vs 前一年度",
             fontsize=13, pad=14)
ax.legend(loc="upper right", frameon=False)
ax.spines[["top", "right"]].set_visible(False)
fig.tight_layout()
fig.savefig(OUT / "drone_ep4_price_vs_revenue.png", dpi=150)
plt.close(fig)


# --- 圖 2：本業賺不賺 vs 市場給多少估值 -----------------------------------------
fig, ax = plt.subplots(figsize=(10.5, 6.5))
om = [c["fundamental"]["fy_rows"][str(c["fundamental"]["latest_fy"])]["operating_margin"] * 100 for c in cos]
pe = [c["fundamental"].get("pe_asof") for c in cos]
colors = [HOT if o < 0 else COOL for o in om]
ax.scatter(om, pe, s=190, c=colors, zorder=3, edgecolor="white", linewidth=1.5)
# 標籤錯開：中光電與漢翔、長榮航太與龍德造船兩組座標相近，靠左右對齊分開
offsets = {
    "雷虎": ((14, -6), "left"),
    "中光電": ((12, 10), "left"),
    "漢翔": ((12, -4), "left"),
    "亞航": ((12, 6), "left"),
    "長榮航太": ((-12, 10), "right"),
    "龍德造船": ((-12, 8), "right"),
}
for n, o, p in zip(names, om, pe):
    xy, ha = offsets.get(n, ((12, 6), "left"))
    ax.annotate(f"{n}｜營益率 {o:+.1f}%、本益比 {p:.0f} 倍",
                (o, p), textcoords="offset points", xytext=xy, ha=ha,
                fontsize=10, color=INK)
ax.set_ylim(20, 600)
ax.axvline(0, color=HOT, ls="--", lw=1.4, alpha=0.8)
ax.set_yscale("log")
ax.set_yticks([25, 50, 100, 200, 400])
ax.get_yaxis().set_major_formatter(matplotlib.ticker.ScalarFormatter())
ax.set_xlim(-5, 24)
ax.text(-4.6, 330, "← 左側：本業是虧的", fontsize=10.5, color=HOT)
ax.set_xlabel("最新年度營業利益率（本業賺錢能力，%）")
ax.set_ylabel("本益比（倍，對數刻度）")
asof = cos[0]["fundamental"].get("valuation_asof_date")
ax.set_title("本業越不賺錢的，市場給的倍數反而越高\n"
             f"營業利益率為年報揭露值；本益比 = {asof} 收盤價 ÷ 每股盈餘（固定於查核日，非盤中浮動值）",
             fontsize=12.5, pad=14)
ax.spines[["top", "right"]].set_visible(False)
ax.grid(alpha=0.25, zorder=0)
fig.tight_layout()
fig.savefig(OUT / "drone_ep4_margin_vs_pe.png", dpi=150)
plt.close(fig)


# --- 圖 3：兩個熱度指標（籌碼 + 技術）------------------------------------------
fig, (a1, a2) = plt.subplots(1, 2, figsize=(13, 5.6))

chip_names, chip_vals = [], []
for c in cos:
    v = c["chip"].get("total_net_pct_of_shares_out")
    if v is not None:
        chip_names.append(c["name"])
        chip_vals.append(v * 100)
bars = a1.bar(chip_names, chip_vals, color=[HOT if v > 0 else COOL for v in chip_vals])
for b, v in zip(bars, chip_vals):
    a1.text(b.get_x() + b.get_width() / 2, v + (0.3 if v >= 0 else -0.7),
            f"{v:+.2f}%", ha="center", fontsize=9.5, color=INK)
a1.axhline(0, color=INK, lw=0.9)
days = EV["method"]["chip_lookback_trading_days"]
rng = EV["method"]["chip_date_range"]
a1.set_title(f"籌碼面：三大法人 {days} 個交易日累計淨買超\n占股本比重（{rng[0]}→{rng[1]}，TWSE T86；上櫃的中光電無同口徑資料）",
             fontsize=11.5, pad=10)
a1.set_ylabel("占已發行股數 %")
a1.spines[["top", "right"]].set_visible(False)

rsi = [c["technical"]["rsi14"] for c in cos]
bars = a2.bar(names, rsi, color=[HOT if r >= 70 else WARN if r >= 60 else COOL for r in rsi])
for b, r in zip(bars, rsi):
    a2.text(b.get_x() + b.get_width() / 2, r + 1.2, f"{r:.0f}", ha="center", fontsize=9.5, color=INK)
a2.axhline(70, ls="--", lw=1.3, color=HOT, alpha=0.8)
a2.text(len(names) - 0.4, 71.5, "70 = 一般視為過熱", ha="right", fontsize=9, color=HOT)
a2.set_ylim(0, 100)
a2.set_title("技術面：RSI(14) 相對強弱指標\n六檔全數站上月線、季線與年線", fontsize=11.5, pad=10)
a2.spines[["top", "right"]].set_visible(False)

fig.suptitle("兩個「熱度」面向，六檔幾乎全票通過", fontsize=13.5, y=0.99)
fig.tight_layout(rect=[0, 0, 1, 0.95])
fig.savefig(OUT / "drone_ep4_chips_technical.png", dpi=150)
plt.close(fig)

print("wrote 3 charts to", OUT)
