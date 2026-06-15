"""
make_figure.py — event_article_fomc_2026_06_17_t1_dotplot
Produces 2 figures:
  fig1: MOVE + VIX dual-axis, 1-year window, with FOMC event markers
  fig2: Past 6 FOMC T-1 bar chart (MOVE water level + SPY 5d post return)
"""
import json
import warnings
from pathlib import Path

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.ticker as mticker
from matplotlib.lines import Line2D

warnings.filterwarnings("ignore")

# ─── paths ────────────────────────────────────────────────────────────────────
BASE = Path("/Users/yhlai0911/Desktop/volpred-research/experiments/event_article_fomc_2026_06_17_t1_dotplot")
FIG_DIR = BASE / "figs"
FIG_DIR.mkdir(exist_ok=True)

close = pd.read_csv(BASE / "raw_close.csv", index_col=0, parse_dates=True)
with open(BASE / "results.json") as f:
    results = json.load(f)

FOMC_DATES = [
    "2025-09-17", "2025-10-29", "2025-12-10",
    "2026-01-29", "2026-03-19", "2026-04-30",
]
TARGET_FOMC = "2026-06-17"

# ─── style ────────────────────────────────────────────────────────────────────
BG   = "#0d1117"
FG   = "#e6edf3"
GRID = "#21262d"
C_MOVE = "#f0883e"   # orange for MOVE
C_VIX  = "#58a6ff"   # blue for VIX
C_VIX9D = "#3fb950"  # green for VIX9D
C_FOMC = "#8b949e"   # gray dashes for past FOMC
C_NEXT = "#f85149"   # red for upcoming FOMC

plt.rcParams.update({
    "figure.facecolor": BG,
    "axes.facecolor":   BG,
    "axes.edgecolor":   GRID,
    "axes.labelcolor":  FG,
    "xtick.color":      FG,
    "ytick.color":      FG,
    "text.color":       FG,
    "grid.color":       GRID,
    "grid.linestyle":   "--",
    "grid.alpha":       0.5,
    "font.family":      "DejaVu Sans",
    "font.size":        11,
})

# ─── Figure 1: MOVE + VIX dual-axis, 1-year window ───────────────────────────
cutoff_1y = pd.Timestamp("2025-06-15")
df = close[close.index >= cutoff_1y].copy()

move_s  = df["^MOVE"].dropna()
vix_s   = df["^VIX"].dropna()
vix9d_s = df["^VIX9D"].dropna()

fig, ax1 = plt.subplots(figsize=(12, 5.5))
ax2 = ax1.twinx()

ax1.set_facecolor(BG)
ax2.set_facecolor(BG)

# MOVE on left axis
ax1.plot(move_s.index, move_s.values, color=C_MOVE, linewidth=1.8, label="MOVE", zorder=3)
ax1.fill_between(move_s.index, move_s.values, alpha=0.12, color=C_MOVE)

# VIX on right axis
ax2.plot(vix_s.index, vix_s.values,   color=C_VIX,  linewidth=1.6, label="VIX",   zorder=3)
ax2.plot(vix9d_s.index, vix9d_s.values, color=C_VIX9D, linewidth=1.2, linestyle="--", label="VIX9D", zorder=3)

# FOMC event lines
for fd in FOMC_DATES:
    fdt = pd.Timestamp(fd)
    if fdt >= cutoff_1y:
        ax1.axvline(fdt, color=C_FOMC, linewidth=1, linestyle=":", alpha=0.7, zorder=2)
        ax1.text(fdt, ax1.get_ylim()[1] if ax1.get_ylim()[1] != 0 else 100,
                 fd[5:7]+"/"+fd[8:], color=C_FOMC, fontsize=7.5,
                 ha="center", va="bottom", rotation=90)

# Upcoming FOMC
ax1.axvline(pd.Timestamp(TARGET_FOMC), color=C_NEXT, linewidth=1.8, linestyle="--", alpha=0.9, zorder=4)
ax1.text(pd.Timestamp(TARGET_FOMC) + pd.Timedelta(days=1),
         move_s.max() * 0.97,
         "6/17 FOMC", color=C_NEXT, fontsize=9.5, fontweight="bold")

# Today marker
last_date = move_s.index[-1]
last_move = move_s.iloc[-1]
ax1.axvline(last_date, color="#f7c948", linewidth=1.2, linestyle="-.", alpha=0.7)
ax1.scatter([last_date], [last_move], color=C_MOVE, s=60, zorder=5)
ax1.annotate(f"T-1\nMOVE {last_move:.1f}", xy=(last_date, last_move),
             xytext=(-50, -30), textcoords="offset points",
             color=C_MOVE, fontsize=9, arrowprops=dict(arrowstyle="->", color=C_MOVE, lw=0.8))

last_vix9d = vix9d_s.dropna().iloc[-1]
ax2.scatter([vix9d_s.dropna().index[-1]], [last_vix9d], color=C_VIX9D, s=55, zorder=5)

ax1.set_ylabel("MOVE Index", color=C_MOVE, fontsize=12)
ax2.set_ylabel("VIX / VIX9D", color=C_VIX, fontsize=12)
ax1.tick_params(axis="y", colors=C_MOVE)
ax2.tick_params(axis="y", colors=C_VIX)

ax1.xaxis.set_major_formatter(mdates.DateFormatter("%b %y"))
ax1.xaxis.set_major_locator(mdates.MonthLocator(interval=2))

ax1.grid(True, axis="y", linestyle="--", alpha=0.3)
ax1.set_xlabel("")

# Legend
handles = [
    Line2D([0],[0], color=C_MOVE,  linewidth=2, label="MOVE（左軸）"),
    Line2D([0],[0], color=C_VIX,   linewidth=2, label="VIX（右軸）"),
    Line2D([0],[0], color=C_VIX9D, linewidth=2, linestyle="--", label="VIX9D（右軸）"),
    Line2D([0],[0], color=C_FOMC,  linewidth=1, linestyle=":", label="過去 FOMC"),
    Line2D([0],[0], color=C_NEXT,  linewidth=2, linestyle="--", label="6/17 FOMC（明日）"),
]
ax1.legend(handles=handles, loc="upper left", framealpha=0.25,
           facecolor=BG, edgecolor=GRID, fontsize=9)

ax1.set_title("MOVE 指數與 VIX 並排水位（過去一年）\n來源：yfinance  |  2026-06-15 收盤",
              color=FG, fontsize=12, pad=12)
fig.tight_layout()

fig1_path = FIG_DIR / "fig1_move_vix_1y.png"
fig.savefig(fig1_path, dpi=150, bbox_inches="tight", facecolor=BG)
plt.close()
print(f"Saved: {fig1_path}")

# ─── Figure 2: Past 6 FOMC — T-1 MOVE water level + SPY T0→T+5 ──────────────
fomc_rows = results["fomc_t1_cross_section"]

labels    = [r["fomc_date"][5:] for r in fomc_rows]     # "09-17", "10-29", ...
move_vals = [r.get("t1_MOVE")           or 0 for r in fomc_rows]
vix_vals  = [r.get("t1_VIX")            or 0 for r in fomc_rows]
spy5d     = [r.get("spy_t0_to_t5_pct")  or 0 for r in fomc_rows]

x = np.arange(len(labels))
w = 0.30

fig2, (axA, axB) = plt.subplots(2, 1, figsize=(11, 7), gridspec_kw={"height_ratios": [1.2, 1]})
fig2.set_facecolor(BG)
for ax in (axA, axB):
    ax.set_facecolor(BG)
    ax.grid(True, axis="y", linestyle="--", alpha=0.3)

# --- Top: MOVE vs VIX T-1 levels ---
bars1 = axA.bar(x - w/2, move_vals, width=w, color=C_MOVE, alpha=0.85, label="MOVE (T-1)")
bars2 = axA.bar(x + w/2, vix_vals,  width=w, color=C_VIX,  alpha=0.85, label="VIX (T-1)")

# Today's MOVE reference line
today_move = results["today"]["MOVE"]
axA.axhline(today_move, color=C_MOVE, linewidth=1.5, linestyle="--", alpha=0.9)
axA.text(len(labels) - 0.3, today_move + 1.0,
         f"今日 MOVE {today_move:.1f}", color=C_MOVE, fontsize=9)

for bar, v in zip(bars1, move_vals):
    axA.text(bar.get_x() + bar.get_width()/2, v + 0.5, f"{v:.1f}",
             ha="center", va="bottom", fontsize=8, color=C_MOVE)
for bar, v in zip(bars2, vix_vals):
    axA.text(bar.get_x() + bar.get_width()/2, v + 0.5, f"{v:.1f}",
             ha="center", va="bottom", fontsize=8, color=C_VIX)

axA.set_xticks(x)
axA.set_xticklabels(labels, fontsize=9)
axA.set_ylabel("指數水位", fontsize=11)
axA.set_title("過去 6 場 FOMC —— T-1 MOVE / VIX 水位 vs 事後 5 日 SPY 報酬\n來源：yfinance",
              color=FG, fontsize=11, pad=10)
axA.legend(loc="upper right", framealpha=0.2, facecolor=BG, edgecolor=GRID, fontsize=9)

# --- Bottom: SPY T0→T+5 return ---
colors_bar = [C_VIX if v > 0 else C_NEXT for v in spy5d]
bars3 = axB.bar(x, spy5d, width=0.5, color=colors_bar, alpha=0.85)
axB.axhline(0, color=FG, linewidth=0.8, alpha=0.5)

for bar, v in zip(bars3, spy5d):
    offset = 0.08 if v > 0 else -0.18
    axB.text(bar.get_x() + bar.get_width()/2, v + offset, f"{v:+.2f}%",
             ha="center", va="bottom", fontsize=8.5, color=FG)

axB.set_xticks(x)
axB.set_xticklabels(labels, fontsize=9)
axB.set_ylabel("SPY T0→T+5 報酬 (%)", fontsize=11)

# Mean line
mean_spy5d = float(np.mean(spy5d))
axB.axhline(mean_spy5d, color="#f7c948", linewidth=1.2, linestyle="--", alpha=0.8)
axB.text(len(labels) - 1, mean_spy5d + 0.08,
         f"均值 {mean_spy5d:+.2f}%", color="#f7c948", fontsize=9)

fig2.tight_layout(pad=2.0)
fig2_path = FIG_DIR / "fig2_fomc_t1_comparison.png"
fig2.savefig(fig2_path, dpi=150, bbox_inches="tight", facecolor=BG)
plt.close()
print(f"Saved: {fig2_path}")

print("\nAll figures saved.")
