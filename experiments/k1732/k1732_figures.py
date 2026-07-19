"""K1732 圖表：(1) 2026-07-17 案例時序 (2) 29 年回測摘要 (3) 全歷史警戒負擔誠實圖。
色盤：Okabe-Ito（CVD-safe），固定色序；無雙 y 軸（堆疊 panel）。
"""
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd

plt.rcParams["font.sans-serif"] = ["PingFang TC", "Heiti TC", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False
C_BLUE, C_ORANGE, C_GREEN, C_VERM, C_GRAY = "#0072B2", "#E69F00", "#009E73", "#D55E00", "#999999"

D = os.path.dirname(os.path.abspath(__file__))
m = pd.read_csv(os.path.join(D, "k1732_metrics_weekly.csv"), index_col=0, parse_dates=True)
px = pd.read_csv(os.path.join(D, "k1732_twii_weekly_close.csv"), index_col=0, parse_dates=True).iloc[:, 0]
res = json.load(open(os.path.join(D, "k1732_results.json")))
MA_S, MA_L = 20, 30


def ma_state(s):
    gap = s.rolling(MA_S).mean() - s.rolling(MA_L).mean()
    active = ((gap < 0) & gap.notna()).astype(bool)
    return gap, active


# ---------- Fig 1: 2026-07-17 案例 ----------
lo, hi = pd.Timestamp("2025-07-01"), pd.Timestamp("2026-07-24")
fig, (ax1, ax2, ax3) = plt.subplots(
    3, 1, figsize=(9, 8.4), sharex=True, gridspec_kw={"height_ratios": [2, 1.4, 1.4], "hspace": 0.12})

pxz = px.loc[lo:hi]
ax1.plot(pxz.index, pxz.values, color=C_BLUE, lw=2)
gap_bs, act_bs = ma_state(m["beta_s"])
act_z = act_bs.loc[lo:hi]
ax1.fill_between(pxz.index, *ax1.get_ylim() if False else (pxz.min() * 0.97, pxz.max() * 1.02),
                 where=act_z.reindex(pxz.index).fillna(False), color=C_ORANGE, alpha=0.14, lw=0)
ax1.axvline(pd.Timestamp("2026-07-17"), color=C_VERM, lw=1.2, ls="--")
ax1.annotate("7/17 單日 −6.5%", xy=(pd.Timestamp("2026-07-17"), pxz.min()), xytext=(-118, 8),
             textcoords="offset points", color=C_VERM, fontsize=10)
ax1.annotate("β 死亡交叉警戒區（3/27 起）", xy=(pd.Timestamp("2026-04-10"), pxz.max() * 0.99),
             color="#8a6100", fontsize=10)
ax1.set_ylabel("台股加權指數（週收盤）")
ax1.set_title("2026-07-17 大跌前：論文三訊號的實際時序", fontsize=13, loc="left", pad=10)

bsz = m["beta_s"].loc[lo:hi]
ax2.plot(bsz.index, m["beta_s"].rolling(MA_S).mean().loc[lo:hi],
         color=C_ORANGE, lw=2, label="β_s 短均線 MA20")
ax2.plot(bsz.index, m["beta_s"].rolling(MA_L).mean().loc[lo:hi], color=C_GRAY, lw=2, label="β_s 長均線 MA30")
ax2.axvline(pd.Timestamp("2026-03-27"), color=C_VERM, lw=1, ls=":")
ax2.annotate("3/27 死亡交叉\n（大跌前 16 週）", xy=(pd.Timestamp("2026-03-27"), m["beta_s"].rolling(MA_L).mean().loc[lo:hi].min()),
             xytext=(8, 6), textcoords="offset points", color=C_VERM, fontsize=9)
ax2.set_ylabel("偏態敏感度 β_s")
ax2.legend(frameon=False, fontsize=9, loc="upper right")

ax3.plot(bsz.index, m["IS_k"].rolling(MA_S).mean().loc[lo:hi], color=C_GREEN, lw=2, label="IS_k 短均線 MA20")
ax3.plot(bsz.index, m["IS_k"].rolling(MA_L).mean().loc[lo:hi], color=C_GRAY, lw=2, label="IS_k 長均線 MA30")
ax3.axvline(pd.Timestamp("2026-07-17"), color=C_VERM, lw=1.2, ls="--")
ax3.annotate("6 月 gap 收斂近零\n（7/10 小幅回彈）", xy=(pd.Timestamp("2026-06-05"), m["IS_k"].rolling(MA_L).mean().loc[lo:hi].mean()),
             xytext=(-90, 14), textcoords="offset points", color="#1b6e54", fontsize=9)
ax3.annotate("7/17 當天才交叉", xy=(pd.Timestamp("2026-07-17"), m["IS_k"].rolling(MA_S).mean().loc[lo:hi].iloc[-1]),
             xytext=(-104, -12), textcoords="offset points", color=C_VERM, fontsize=9)
ax3.set_ylabel("峰態影響份額 IS_k")
ax3.legend(frameon=False, fontsize=9, loc="upper right")
for ax in (ax1, ax2, ax3):
    ax.grid(alpha=0.22, lw=0.5)
    ax.spines[["top", "right"]].set_visible(False)
ax3.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
fig.align_ylabels()
fig.text(0.99, 0.005, "資料：Yahoo Finance ^TWII 週資料｜方法：Lai & Chang CF-VaR 分解（26 週動差、MA20/30）｜VolPred K1732",
         ha="right", fontsize=7.5, color="#777")
fig.savefig(os.path.join(D, "k1732_fig1_case2026.png"), dpi=160, bbox_inches="tight")
plt.close(fig)

# ---------- Fig 2: 回測摘要 ----------
sig_labels = {"beta_s": "β 敏感度訊號\n(≈波動率趨勢)", "IS_k": "IS_k 峰態份額訊號"}
fig, (axa, axb) = plt.subplots(1, 2, figsize=(9.6, 4.4), gridspec_kw={"wspace": 0.3})

x = np.arange(2)
for i, key in enumerate(["beta_s", "IS_k"]):
    s = res["signals"][key]
    p1, p0 = s["assoc_P_onset13_given_active"], s["assoc_P_onset13_given_inactive"]
    axa.bar(i - 0.17, p1, 0.3, color=C_VERM if key == "IS_k" else C_GRAY, alpha=0.95)
    axa.bar(i + 0.17, p0, 0.3, color="#cccccc")
    axa.text(i - 0.17, p1 + 0.008, f"{p1:.0%}", ha="center", fontsize=11, fontweight="bold")
    axa.text(i + 0.17, p0 + 0.008, f"{p0:.0%}", ha="center", fontsize=11, color="#666")
axa.set_xticks(x, [sig_labels["beta_s"], sig_labels["IS_k"]], fontsize=10)
axa.set_ylabel("未來 13 週出現崩跌起點的機率")
axa.set_title("警戒中（深色）vs 非警戒（淺色）", fontsize=11, loc="left")
axa.set_ylim(0, 0.42)
axa.annotate("IS_k：17%→32%\nbootstrap CI 排除 0", xy=(1, 0.385), fontsize=9,
             ha="center", color=C_VERM)
axa.annotate("β：差異不顯著\n(p=0.74)", xy=(0, 0.31), fontsize=9, ha="center", color="#666")

for i, key in enumerate(["beta_s", "IS_k"]):
    s = res["signals"][key]
    hr, bd = s["hit_rate_active_at_t_minus_1"], s["warning_burden_frac_weeks_active"]
    axb.bar(i - 0.17, hr, 0.3, color=C_BLUE)
    axb.bar(i + 0.17, bd, 0.3, color="#cccccc")
    axb.text(i - 0.17, hr + 0.008, f"{hr:.0%}", ha="center", fontsize=11, fontweight="bold")
    axb.text(i + 0.17, bd + 0.008, f"{bd:.0%}", ha="center", fontsize=11, color="#666")
axb.set_xticks(x, [sig_labels["beta_s"], sig_labels["IS_k"]], fontsize=10)
axb.set_ylabel("比率")
axb.set_title("命中率（藍）vs 警戒時間占比（灰）", fontsize=11, loc="left")
axb.set_ylim(0, 0.85)
axb.annotate("命中≈占比\n（未優於隨機覆蓋）", xy=(0, 0.56), fontsize=9, ha="center", color="#666")
axb.annotate("71% > 49%", xy=(1 - 0.17, 0.76), fontsize=9, ha="center", color=C_BLUE)
for ax in (axa, axb):
    ax.grid(alpha=0.22, lw=0.5, axis="y")
    ax.spines[["top", "right"]].set_visible(False)
fig.suptitle("台股 29 年系統性回測（30 次崩跌起點、28 次落在評估期，1997–2026）", fontsize=13, x=0.02, ha="left")
fig.text(0.99, -0.02, "崩跌起點=週跌幅≤−5% 且前 13 週無事件｜訊號取前一週狀態（無 lookahead）｜VolPred K1732",
         ha="right", fontsize=7.5, color="#777")
fig.savefig(os.path.join(D, "k1732_fig2_backtest.png"), dpi=160, bbox_inches="tight")
plt.close(fig)

# ---------- Fig 3: 全歷史 + 警戒負擔 ----------
fig, ax = plt.subplots(figsize=(9.6, 4.6))
gap_k, act_k = ma_state(m["IS_k"])
ax.semilogy(px.index, px.values, color=C_BLUE, lw=1.1)
ax.fill_between(px.index, px.min() * 0.9, px.max() * 1.1,
                where=act_k.reindex(px.index).fillna(False), color=C_GREEN, alpha=0.12, lw=0)
onsets = pd.to_datetime(res["event_definition"]["onsets_primary"])
ax.plot(onsets, px.reindex(onsets, method="nearest") * 1.0, "v", color=C_VERM, ms=7,
        markeredgecolor="white", markeredgewidth=0.6)
ax.set_ylabel("台股加權指數（log 尺度）")
ax.set_title("29 年全景：▼=30 次崩跌起點；綠色底=IS_k 警戒期（49% 的時間）", fontsize=12, loc="left", pad=8)
ax.grid(alpha=0.22, lw=0.5)
ax.spines[["top", "right"]].set_visible(False)
ax.annotate("警戒期覆蓋 20/28 次可評估起點，但也覆蓋近半的承平時光 —\n它是「體質變差」的 regime 訊號，不是擇日工具",
            xy=(pd.Timestamp("1999-01-01"), px.max() * 0.75), fontsize=9.5, color="#1b6e54")
fig.text(0.99, -0.02, "資料：Yahoo Finance ^TWII 1997–2026 週資料｜VolPred K1732", ha="right", fontsize=7.5, color="#777")
fig.savefig(os.path.join(D, "k1732_fig3_history.png"), dpi=160, bbox_inches="tight")
plt.close(fig)
print("figures done")
