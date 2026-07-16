"""Figures for digest_20260716 — real yfinance data, Traditional Chinese labels."""
import json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd

OUT = "/Users/yhlai0911/volpred-research/storage/drafts/assets/digest_20260716"

plt.rcParams["font.sans-serif"] = ["Heiti TC", "Arial Unicode MS", "PingFang TC", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

# Okabe-Ito colorblind-safe hues
C_BLUE = "#0072B2"
C_VERM = "#D55E00"
C_ORANGE = "#E69F00"
C_GRAY = "#7F7F7F"
C_GREEN = "#009E73"

vix = pd.read_csv(f"{OUT}/vix_close.csv", index_col=0, parse_dates=True)["Close"]
ovx = pd.read_csv(f"{OUT}/ovx_close.csv", index_col=0, parse_dates=True)["Close"]
wti = pd.read_csv(f"{OUT}/wti_close.csv", index_col=0, parse_dates=True)["Close"]
ev = json.load(open(f"{OUT}/evidence.json"))

# ---------------- fig 1: dual-axis VIX vs WTI, last 30 trading days ----------------
v30 = vix.tail(30)
w30 = wti[wti.index >= v30.index[0]]

fig, ax1 = plt.subplots(figsize=(11, 5.5), dpi=150)
ax1.plot(v30.index, v30.values, color=C_BLUE, lw=2, label="VIX（左軸）")
ax1.set_ylabel("VIX 指數", color=C_BLUE, fontsize=11)
ax1.tick_params(axis="y", labelcolor=C_BLUE)

ax2 = ax1.twinx()
ax2.plot(w30.index, w30.values, color=C_VERM, lw=2, label="WTI 原油（右軸）")
ax2.set_ylabel("WTI 原油（美元/桶）", color=C_VERM, fontsize=11)
ax2.tick_params(axis="y", labelcolor=C_VERM)

# annotations: recent VIX high (7/13) and latest close (7/15)
hi_d = pd.Timestamp(ev["latest"]["vix_recent_high_date"])
hi_v = ev["latest"]["vix_recent_high_close"]
last_d = pd.Timestamp(ev["latest"]["vix_date"])
last_v = ev["latest"]["vix_close"]
ax1.scatter([hi_d], [hi_v], color=C_BLUE, zorder=5, s=45)
ax1.annotate(f"7/13 近期高點 {hi_v}", xy=(hi_d, hi_v), xytext=(-115, 14),
             textcoords="offset points", fontsize=10, color=C_BLUE,
             arrowprops=dict(arrowstyle="->", color=C_BLUE, lw=1))
ax1.scatter([last_d], [last_v], color=C_BLUE, zorder=5, s=45)
ax1.annotate(f"7/15 最新 {last_v}", xy=(last_d, last_v), xytext=(-80, -28),
             textcoords="offset points", fontsize=10, color=C_BLUE,
             arrowprops=dict(arrowstyle="->", color=C_BLUE, lw=1))
w_last_d, w_last_v = w30.index[-1], float(w30.iloc[-1])
ax2.annotate(f"WTI 最新 {w_last_v:.1f}", xy=(w_last_d, w_last_v), xytext=(-95, 16),
             textcoords="offset points", fontsize=10, color=C_VERM,
             arrowprops=dict(arrowstyle="->", color=C_VERM, lw=1))

ax1.set_title("油在漲、VIX 在退：近 30 個交易日的背離", fontsize=15, pad=12)
ax1.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
ax1.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=mdates.MO))
ax1.grid(alpha=0.25, lw=0.6)
lines = ax1.get_lines() + ax2.get_lines()
ax1.legend(lines, [l.get_label() for l in lines], loc="upper left", fontsize=10, framealpha=0.9)
fig.text(0.99, 0.01, "資料：Yahoo Finance 日收盤（VIX 至 2026-07-15；WTI 至 2026-07-16）",
         ha="right", fontsize=8, color="#666666")
fig.tight_layout()
fig.savefig(f"{OUT}/fig1_vix_wti_recent.png", bbox_inches="tight")
plt.close(fig)

# ---------------- fig 2: aligned decay curves ----------------
def decay(series, peak_date, n=40):
    pk = pd.Timestamp(peak_date)
    seg = series[series.index >= pk].iloc[: n + 1]
    return list(range(len(seg))), (seg / seg.iloc[0]).values

events = ev["events"]
specs = [
    (events[0], vix, C_VERM, "-",
     f"2025-04 關稅戰（峰值 {events[0]['peak_close']}，首破半衰 {events[0]['half_life_trading_days']} 天／持穩 {events[0]['sustained_half_life_trading_days']} 天）"),
    (events[1], vix, C_ORANGE, "-",
     f"2026-06 中東衝突（峰值 {events[1]['peak_close']}，半衰 {events[1]['half_life_trading_days']} 天）"),
    (events[2], vix, C_BLUE, "-",
     f"2026-07 油市衝擊 VIX（峰值僅 {events[2]['peak_close']}，幾乎沒起漲）"),
]
sup = ev["supplementary_ovx_event"]

fig, ax = plt.subplots(figsize=(11, 6), dpi=150)
for e, series, color, ls, label in specs:
    x, y = decay(series, e["peak_date"])
    ax.plot(x, y, color=color, ls=ls, lw=2, label=label)
    # mark first half-level crossing
    if e["half_life_trading_days"] is not None and e["half_life_trading_days"] <= len(x) - 1:
        d = e["half_life_trading_days"]
        ax.scatter([x[d]], [y[d]], color=color, s=40, zorder=5)
    # short/ongoing curves: mark endpoint
    if len(x) - 1 < 40:
        ax.scatter([x[-1]], [y[-1]], color=color, s=28, zorder=5, marker="s")

# supplementary OVX curve (clearly labeled, ongoing)
xo, yo = decay(ovx, sup["peak_date"])
ax.plot(xo, yo, color=C_GREEN, ls="--", lw=2,
        label=f"2026-07 油市衝擊 OVX（補充；峰值 {sup['peak_close']}，半衰進行中，已 {sup['days_elapsed_since_peak']} 天）")
ax.scatter([xo[-1]], [yo[-1]], color=C_GREEN, s=28, zorder=5, marker="s")

ax.axhline(1.0, color="#BBBBBB", lw=0.8, ls=":")
ax.set_xlim(0, 40)
ax.set_xlabel("峰值後交易日數", fontsize=11)
ax.set_ylabel("相對峰值水準（峰值 = 1.0）", fontsize=11)
ax.set_title("恐慌半衰期不只一種：不同衝擊源的波動率衰減路徑", fontsize=15, pad=12)
ax.grid(alpha=0.25, lw=0.6)
ax.legend(loc="upper right", fontsize=9.5, framealpha=0.9)
fig.text(0.99, 0.01,
         "資料：Yahoo Finance 日收盤。圓點＝首次跌破半衰水準；方點＝資料最新端點（曲線尚短或進行中）",
         ha="right", fontsize=8, color="#666666")
fig.tight_layout()
fig.savefig(f"{OUT}/fig2_halflife_compare.png", bbox_inches="tight")
plt.close(fig)
print("figures saved")
