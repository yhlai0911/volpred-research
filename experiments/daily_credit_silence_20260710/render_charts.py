"""Charts for the credit-silence piece. All numbers read from panel.csv / results JSON."""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
PRE_WINDOW = 60

plt.rcParams.update(
    {
        "figure.dpi": 140,
        "font.size": 10,
        "axes.spines.top": False,
        "axes.spines.right": False,
    }
)

EQUITY = "#c2410c"
CREDIT = "#0f766e"
GREY = "#94a3b8"

df = pd.read_csv(HERE / "panel.csv", index_col=0, parse_dates=True)
res = json.loads((HERE / "credit_silence_results.json").read_text(encoding="utf-8"))
cur = res["current"]
cond = res["conditional_on_equity_vol_spike"]

# ---------------- Figure 1: the two vol lines pulling apart ----------------
sub = df.loc["2025-07-01":]
fig, ax = plt.subplots(figsize=(9, 4.4))
ax.plot(sub.index, sub["qqq_rv"], color=EQUITY, lw=1.8, label="QQQ 20-day realized vol (left)")
ax.set_ylabel("QQQ realized vol (%, annualized)", color=EQUITY)
ax.tick_params(axis="y", labelcolor=EQUITY)
ax.set_ylim(0, max(sub["qqq_rv"]) * 1.15)

ax2 = ax.twinx()
ax2.spines["top"].set_visible(False)
ax2.plot(sub.index, sub["hyg_rv"], color=CREDIT, lw=1.8, label="HYG 20-day realized vol (right)")
ax2.set_ylabel("HYG realized vol (%, annualized)", color=CREDIT)
ax2.tick_params(axis="y", labelcolor=CREDIT)
ax2.set_ylim(0, max(sub["hyg_rv"]) * 1.15)

ax.axvline(sub.index[-1], color=GREY, ls=":", lw=1)
ax.annotate(
    f"{cur['as_of']}\nQQQ {cur['qqq_rv']:.1f}%  vs  HYG {cur['hyg_rv']:.1f}%",
    xy=(sub.index[-1], sub["qqq_rv"].iloc[-1]),
    xytext=(-150, -18),
    textcoords="offset points",
    fontsize=9,
    color="#334155",
)
ax.set_title(
    "Equity vol climbed; credit vol did not\nQQQ vs HYG, 20-day realized volatility",
    loc="left",
    fontsize=12,
    weight="bold",
)
h1, l1 = ax.get_legend_handles_labels()
h2, l2 = ax2.get_legend_handles_labels()
ax.legend(h1 + h2, l1 + l2, loc="upper left", frameon=False, fontsize=9)
fig.text(
    0.01, -0.04,
    f"Source: yfinance close prices (auto-adjusted). Sample shown 2025-07-01 to {cur['as_of']}. "
    "Realized vol = stdev of 20 daily log returns, annualized.",
    fontsize=7.5, color="#64748b",
)
fig.tight_layout()
fig.savefig(HERE / "fig1_vol_divergence.png", bbox_inches="tight", facecolor="white")
plt.close(fig)

# --------- Figure 2: conditional distribution of HY OAS change ---------
qqq_base = df["qqq_rv"].rolling(PRE_WINDOW).mean().shift(1)
hy_base = df["hy_oas"].rolling(PRE_WINDOW).mean().shift(1)
hyg_base = df["hyg_rv"].rolling(PRE_WINDOW).mean().shift(1)
panel = pd.DataFrame(
    {
        "qqq_rv_change": df["qqq_rv"] - qqq_base,
        "hy_oas_bp_change": (df["hy_oas"] - hy_base) * 100,
        "hyg_rv_change": df["hyg_rv"] - hyg_base,
    }
).dropna()
spike = cur["qqq_rv_change"]
sel = panel[panel["qqq_rv_change"] >= spike].iloc[:-1]

fig, axes = plt.subplots(1, 2, figsize=(10, 4.0))

ax = axes[0]
ax.hist(sel["hy_oas_bp_change"], bins=16, color=CREDIT, alpha=0.75, edgecolor="white")
ax.axvline(0, color=GREY, lw=1)
ax.axvline(cur["hy_oas_bp_change"], color=EQUITY, lw=2.2)
ax.annotate(
    f"today {cur['hy_oas_bp_change']:+.1f} bp\n({cond['hy_oas_bp_change']['current_percentile']:.0f}th pct)",
    xy=(cur["hy_oas_bp_change"], ax.get_ylim()[1] * 0.72),
    xytext=(14, 0), textcoords="offset points", color=EQUITY, fontsize=9, weight="bold",
)
ax.set_title("High-yield spread change", loc="left", fontsize=11, weight="bold")
ax.set_xlabel("HY OAS vs 60d mean (bp)")
ax.set_ylabel(f"days (n={len(sel)})")

ax = axes[1]
ax.hist(sel["hyg_rv_change"], bins=16, color=CREDIT, alpha=0.75, edgecolor="white")
ax.axvline(0, color=GREY, lw=1)
ax.axvline(cur["hyg_rv_change"], color=EQUITY, lw=2.2)
ax.annotate(
    f"today {cur['hyg_rv_change']:+.2f} pp\n(lowest of {len(sel)})",
    xy=(cur["hyg_rv_change"], ax.get_ylim()[1] * 0.72),
    xytext=(14, 0), textcoords="offset points", color=EQUITY, fontsize=9, weight="bold",
)
ax.set_title("Credit-ETF realized vol change", loc="left", fontsize=11, weight="bold")
ax.set_xlabel("HYG 20d RV vs 60d mean (pp)")

fig.suptitle(
    f"On past days when QQQ vol ran {spike:+.1f} pp hot, credit usually flinched",
    fontsize=12, weight="bold", x=0.01, ha="left",
)
fig.text(
    0.01, -0.06,
    f"Source: yfinance + FRED (ICE BofA BAMLH0A0HYM2). Conditional sample: all days {res['sample']['start']}–{cur['as_of']} "
    f"where QQQ 20d RV >= its trailing 60d mean + {spike:.1f} pp (n={len(sel)}). Overlapping 20-day windows -> "
    "these days are autocorrelated; percentiles are descriptive, not a significance test.",
    fontsize=7.5, color="#64748b",
)
fig.tight_layout()
fig.savefig(HERE / "fig2_conditional_credit.png", bbox_inches="tight", facecolor="white")
plt.close(fig)

print("wrote fig1_vol_divergence.png, fig2_conditional_credit.png")
print("conditional n =", len(sel))
