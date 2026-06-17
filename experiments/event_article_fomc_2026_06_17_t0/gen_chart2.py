#!/usr/bin/env python3
"""Generate fig_spy_recovery.png — SPY price recovery + vol recovery chart."""
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
from pathlib import Path

ROOT = Path(__file__).parent

data = pd.read_csv(ROOT / "data.csv")
data["Date"] = pd.to_datetime(data["Date"])
data = data.set_index("Date")

# Fill 6/15 ratio (missing VIX9D) with NaN for gap
fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
fig.patch.set_facecolor("#FAFAFA")

# Top: SPY price
ax1 = axes[0]
ax1.set_facecolor("#FAFAFA")
ax1.plot(data.index, data["SPY"], color="#1A5276", linewidth=2, marker="o", markersize=4, label="SPY")

# Mark 6/5 shock and FOMC date
shock_date = pd.Timestamp("2026-06-05")
fomc_date = pd.Timestamp("2026-06-17")
t7_date = pd.Timestamp("2026-06-09")
t2_date = pd.Timestamp("2026-06-15")
t0_date = pd.Timestamp("2026-06-16")

ax1.axvline(shock_date, color="#E74C3C", linestyle="--", linewidth=1.2, alpha=0.8, label="6/5 vol shock")
ax1.axvline(fomc_date, color="#8E44AD", linestyle=":", linewidth=1.5, alpha=0.9, label="FOMC 6/17 02:00")

spy_shock = float(data.loc[shock_date, "SPY"])
spy_peak_low = float(data.loc["2026-06-10", "SPY"])
spy_t0 = float(data.loc[t0_date, "SPY"])

ax1.annotate("6/5 衝擊\n737.55", xy=(shock_date, spy_shock),
             xytext=(shock_date + pd.Timedelta(days=0.3), spy_shock - 9),
             fontsize=7.5, color="#E74C3C",
             arrowprops=dict(arrowstyle="->", color="#E74C3C", lw=0.8))
ax1.annotate(f"6/16 收盤\n{spy_t0}", xy=(t0_date, spy_t0),
             xytext=(t0_date - pd.Timedelta(days=3), spy_t0 + 8),
             fontsize=7.5, color="#1A5276",
             arrowprops=dict(arrowstyle="->", color="#1A5276", lw=0.8))

# Recovery zone shading
ax1.fill_between(data.loc["2026-06-05":"2026-06-16"].index,
                 data.loc["2026-06-05":"2026-06-16", "SPY"],
                 757.09, alpha=0.07, color="#E74C3C", label="未收復區間")

ax1.set_ylabel("SPY 收盤價", fontsize=10)
ax1.legend(fontsize=8, loc="lower right")
ax1.set_title("SPY 價格修復路徑（2026-05-29 至 6/16）", fontsize=11, pad=8)
ax1.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f"))
ax1.grid(axis="y", linestyle="--", alpha=0.4)

# Bottom: VIX9D/VIX ratio
ax2 = axes[1]
ax2.set_facecolor("#FAFAFA")

# Exclude 6/15 (missing VIX9D)
ratio_data = data[["ratio"]].dropna()
ax2.plot(ratio_data.index, ratio_data["ratio"],
         color="#D35400", linewidth=2, marker="o", markersize=4, label="VIX9D/VIX")
ax2.axhline(1.0, color="#7F8C8D", linestyle="-", linewidth=1, alpha=0.7, label="backwardation 邊界 = 1.0")
ax2.axvline(shock_date, color="#E74C3C", linestyle="--", linewidth=1.2, alpha=0.8)
ax2.axvline(fomc_date, color="#8E44AD", linestyle=":", linewidth=1.5, alpha=0.9)

# Shade backwardation zone
backwardation = ratio_data[ratio_data["ratio"] >= 1.0]
if not backwardation.empty:
    ax2.fill_between(ratio_data.index, ratio_data["ratio"], 1.0,
                     where=(ratio_data["ratio"] >= 1.0),
                     alpha=0.15, color="#E74C3C", label="Backwardation 區")

# Annotate key points
ax2.annotate("Peak\n1.155", xy=(pd.Timestamp("2026-06-10"), 1.155),
             xytext=(pd.Timestamp("2026-06-10") + pd.Timedelta(days=0.4), 1.175),
             fontsize=7.5, color="#C0392B",
             arrowprops=dict(arrowstyle="->", color="#C0392B", lw=0.8))
ax2.annotate("T-0: 0.961", xy=(t0_date, 0.961),
             xytext=(t0_date - pd.Timedelta(days=3.5), 0.910),
             fontsize=7.5, color="#D35400",
             arrowprops=dict(arrowstyle="->", color="#D35400", lw=0.8))

# T-7 / T-2 markers
for lbl, dt, val in [("T-7\n1.114", t7_date, 1.114), ("T-2\n0.961", pd.Timestamp("2026-06-12"), 0.976)]:
    ax2.annotate(lbl, xy=(dt, val),
                 xytext=(dt + pd.Timedelta(days=0.4), val + 0.02),
                 fontsize=7, color="#555")

ax2.set_ylabel("VIX9D / VIX ratio", fontsize=10)
ax2.set_xlabel("")
ax2.legend(fontsize=8, loc="upper right")
ax2.set_title("VIX9D/VIX Term Structure Ratio — backwardation 完整消退", fontsize=11, pad=8)
ax2.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.3f"))
ax2.grid(axis="y", linestyle="--", alpha=0.4)

# X-axis format
import matplotlib.dates as mdates
ax2.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
ax2.xaxis.set_major_locator(mdates.DayLocator(interval=2))
fig.autofmt_xdate(rotation=30, ha="right")

plt.tight_layout(rect=[0, 0, 1, 0.97])
out = ROOT / "fig_spy_recovery.png"
plt.savefig(out, dpi=150, bbox_inches="tight")
print(f"Saved: {out}")
