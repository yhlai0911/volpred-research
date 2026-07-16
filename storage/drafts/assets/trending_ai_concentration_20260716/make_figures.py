"""兩張圖: fig1 集中度+波動缺口時序, fig2 避險成本對比"""
import json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import rcParams
from pathlib import Path

rcParams["font.family"] = ["Heiti TC", "Arial Unicode MS"]
rcParams["axes.unicode_minus"] = False
np.random.seed(42)

OUT = Path("/Users/yhlai0911/volpred-research/storage/drafts/assets/trending_ai_concentration_20260716")
df = pd.read_csv(OUT / "daily_series.csv", index_col=0, parse_dates=True)
ev = json.loads((OUT / "evidence.json").read_text())

C_MAIN = "#1a5fb4"; C_ACC = "#c01c28"; C_GRAY = "#77767b"; C_FILL = "#f6d32d"

# ---------- Fig 1 ----------
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(9, 7.6), sharex=True,
                               gridspec_kw={"height_ratios": [1, 1], "hspace": 0.12})
w5 = df["w5_approx"] * 100
ax1.plot(w5.index, w5, color=C_MAIN, lw=1.6)
ax1.fill_between(w5.index, 0, w5, color=C_MAIN, alpha=0.08)
pk_date = pd.Timestamp(ev["weight_stats"]["max"]["date"]); pk = ev["weight_stats"]["max"]["w5_pct"]
la_date = pd.Timestamp(ev["weight_stats"]["latest"]["date"]); la = ev["weight_stats"]["latest"]["w5_pct"]
ax1.annotate(f"高點 {pk:.1f}%\n({pk_date:%Y-%m})", xy=(pk_date, pk), xytext=(pk_date - pd.Timedelta(days=560), pk - 1.2),
             fontsize=9, color=C_ACC, arrowprops=dict(arrowstyle="->", color=C_ACC, lw=1))
ax1.annotate(f"最新 {la:.1f}%", xy=(la_date, la), xytext=(la_date - pd.Timedelta(days=330), la - 3.4),
             fontsize=9, color=C_MAIN, arrowprops=dict(arrowstyle="->", color=C_MAIN, lw=1))
ax1.set_ylabel("前五大公司合計權重（%）")
ax1.set_title("S&P 500 前五大公司權重與「個股—指數」波動缺口（2020–2026）", fontsize=13, pad=10)
ax1.set_ylim(12, 32)
ax1.grid(alpha=0.25, lw=0.5)
ax1.text(0.01, 0.03, "五巨頭＝NVDA・AAPL・Alphabet・MSFT・AMZN（2026-07 當前前五大回溯）",
         transform=ax1.transAxes, fontsize=8, color=C_GRAY)

avg5 = df["top5_avg_rv20"]; spyv = df["spy_rv20"]
ax2.plot(avg5.index, avg5, color=C_ACC, lw=1.2, label="五巨頭平均個股波動（20日已實現・年化）")
ax2.plot(spyv.index, spyv, color=C_MAIN, lw=1.2, label="SPY 指數波動（20日已實現・年化）")
ax2.fill_between(avg5.index, spyv, avg5, where=avg5 >= spyv, color=C_FILL, alpha=0.35, label="波動缺口（分散假象區）")
gl = ev["vol_gap_stats"]
ax2.annotate(f"最新缺口 {gl['latest_gap_pct']:.1f} 個百分點\n（個股 {gl['latest_top5avg_rv20_pct']:.1f}% vs 指數 {gl['latest_spy_rv20_pct']:.1f}%）",
             xy=(pd.Timestamp(gl["latest_date"]), (gl["latest_top5avg_rv20_pct"] + gl["latest_spy_rv20_pct"]) / 2),
             xytext=(pd.Timestamp(gl["latest_date"]) - pd.Timedelta(days=900), 68),
             fontsize=9, color="#3d3846", arrowprops=dict(arrowstyle="->", color=C_GRAY, lw=1))
ax2.set_ylabel("年化波動率（%）")
ax2.set_ylim(0, 105)
ax2.legend(fontsize=8.5, loc="upper right", framealpha=0.9)
ax2.grid(alpha=0.25, lw=0.5)
fig.text(0.99, 0.005, "資料：yfinance 日資料 2020-01–2026-07-15；權重＝市值近似、最新日錨定官方 27.8%（Yahoo/SSGA）",
         ha="right", fontsize=7.5, color=C_GRAY)
fig.savefig(OUT / "fig1_concentration_volgap.png", dpi=150, bbox_inches="tight")
plt.close(fig)

# ---------- Fig 2 ----------
hc = ev["hedge_cost"]
fm, bm = hc["front_month"], hc["back_month"]
labels = [f"最近月\n{fm['expiry']}（{fm['dte']} 天）", f"次月\n{bm['expiry']}（{bm['dte']} 天）"]
naked = [fm["naked_put_annualized_pct"], bm["naked_put_annualized_pct"]]
spread = [fm["spread_annualized_pct"], bm["spread_annualized_pct"]]
sav = [fm["cost_saving_pct"], bm["cost_saving_pct"]]

x = np.arange(2); w = 0.34
fig, ax = plt.subplots(figsize=(8, 5.4))
b1 = ax.bar(x - w / 2, naked, w, color=C_ACC, alpha=0.85, label="裸買 5% OTM 賣權")
b2 = ax.bar(x + w / 2, spread, w, color=C_MAIN, alpha=0.85, label="賣權價差（買 5%／賣 10% OTM）")
for i, (n, s) in enumerate(zip(naked, spread)):
    ax.text(x[i] - w / 2, n + 0.12, f"{n:.1f}%", ha="center", fontsize=10, color=C_ACC, fontweight="bold")
    ax.text(x[i] + w / 2, s + 0.12, f"{s:.1f}%", ha="center", fontsize=10, color=C_MAIN, fontweight="bold")
    ax.annotate(f"省 {sav[i]:.0f}%", xy=(x[i] + w / 2, s / 2), ha="center", fontsize=9, color="white", fontweight="bold")
ax.set_xticks(x); ax.set_xticklabels(labels, fontsize=10)
ax.set_ylabel("避險保費（年化・佔現貨 %）")
ax.set_title("SPY 下檔避險成本：裸買賣權 vs 賣權價差（2026-07-15 收盤報價）", fontsize=12.5, pad=12)
ax.set_ylim(0, max(naked) * 1.25)
ax.grid(axis="y", alpha=0.25, lw=0.5)
ax.legend(fontsize=9, loc="upper right")
ax.text(0.01, -0.16,
        f"價差保護上限＝履約價差 {fm['spread_max_payoff_pct_of_spot']:.0f}%（95%→90%）；跌破 10% 之後不再增加保護。\n"
        f"資料：yfinance SPY 選擇權鏈；premium 用 lastPrice（盤外 bid/ask 為 0），成交時間見 evidence.json。",
        transform=ax.transAxes, fontsize=7.5, color=C_GRAY, va="top")
fig.savefig(OUT / "fig2_hedge_cost.png", dpi=150, bbox_inches="tight")
plt.close(fig)
print("figures saved")
