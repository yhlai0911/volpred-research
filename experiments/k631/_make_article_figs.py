#!/usr/bin/env python3
"""Generate article figures for K631 publication (general audience).

Reads experiments/k631/k631_results.json (canonical numbers).
Writes 3 PNGs to experiments/k631/:
  fig1_dow_3market.png    — 5 weekday × 3 market mean RV bar
  fig2_calendar_dm.png    — Calendar overlay QLIKE % change + DM p
  fig3_opex_effect.png    — OpEx vs Non-OpEx mean RV across 3 markets

No new computation; only re-displays canonical results.
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parent
RESULTS = json.loads((ROOT / "k631_results.json").read_text())

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
WD_ZH = ["週一", "週二", "週三", "週四", "週五"]
MARKETS = ["SPY", "GLD", "0050.TW"]
COLOURS = {"SPY": "#2563eb", "GLD": "#d97706", "0050.TW": "#16a34a"}

# Set up Chinese font (best effort - falls back to default if unavailable)
try:
    from matplotlib import font_manager
    for f in ["PingFang TC", "Heiti TC", "STHeiti", "Songti SC", "Arial Unicode MS"]:
        if any(f in fn.name for fn in font_manager.fontManager.ttflist):
            plt.rcParams["font.family"] = f
            break
except Exception:
    pass
plt.rcParams["axes.unicode_minus"] = False


# ---------- Fig 1: Day-of-week × 3 market ----------
def fig1():
    fig, ax = plt.subplots(figsize=(9, 5.2))
    x = np.arange(len(WEEKDAYS))
    bar_w = 0.27

    for i, mkt in enumerate(MARKETS):
        vals = []
        for wd in WEEKDAYS:
            v = RESULTS["assets"][mkt]["day_of_week"][wd]["mean_r2"]
            # Convert squared return to annualised vol % for readability
            vals.append(np.sqrt(v * 252) * 100)
        ax.bar(x + (i - 1) * bar_w, vals, bar_w,
               color=COLOURS[mkt], label=mkt, alpha=0.85)

    ax.set_xticks(x)
    ax.set_xticklabels(WD_ZH)
    ax.set_ylabel("年化波動率 (%)")
    ax.set_title("各星期幾的平均波動率（SPY / GLD / 0050.TW，2006-2026）",
                 fontsize=12, pad=10)
    ax.legend(loc="upper right", framealpha=0.9)
    ax.grid(axis="y", linestyle=":", alpha=0.5)

    spy_kw = RESULTS["assets"]["SPY"]["day_of_week"]["kruskal_wallis"]["p_value"]
    gld_kw = RESULTS["assets"]["GLD"]["day_of_week"]["kruskal_wallis"]["p_value"]
    tw_kw = RESULTS["assets"]["0050.TW"]["day_of_week"]["kruskal_wallis"]["p_value"]
    sub = (f"Kruskal–Wallis 顯著性：SPY={spy_kw:.3f}（不顯著）  "
           f"GLD={gld_kw:.3f}（不顯著）  0050.TW={tw_kw:.3f}（邊緣）")
    ax.text(0.5, -0.18, sub, transform=ax.transAxes, ha="center",
            fontsize=9, color="#555")
    plt.tight_layout()
    out = ROOT / "fig1_dow_3market.png"
    plt.savefig(out, dpi=150, bbox_inches="tight")
    plt.close()
    print("wrote", out)


# ---------- Fig 2: Calendar overlay QLIKE % change + DM ----------
def fig2():
    fig, ax = plt.subplots(figsize=(9, 5))

    fc = RESULTS["forecasting"]
    rows = [
        ("SPY HAR + Calendar",
         fc["SPY_har"]["qlike_pct_change_calendar"],
         fc["SPY_har"]["dm_test_calendar_vs_har"]["p_value"]),
        ("SPY GJR + Calendar",
         fc["SPY_gjr"]["qlike_pct_change"],
         fc["SPY_gjr"]["dm_test"]["p_value"]),
        ("GLD HAR + Calendar",
         fc["GLD_har"]["qlike_pct_change_calendar"],
         fc["GLD_har"]["dm_test_calendar_vs_har"]["p_value"]),
        ("0050.TW HAR + Calendar",
         fc["0050.TW_har"]["qlike_pct_change_calendar"],
         fc["0050.TW_har"]["dm_test_calendar_vs_har"]["p_value"]),
    ]
    labels = [r[0] for r in rows]
    pct = [r[1] for r in rows]
    pvals = [r[2] for r in rows]
    y = np.arange(len(labels))
    bars = ax.barh(y, pct,
                   color=["#2563eb" if p > 0.05 else "#16a34a" for p in pvals],
                   alpha=0.85)
    ax.axvline(0, color="black", linewidth=0.8)
    ax.set_yticks(y)
    ax.set_yticklabels(labels)
    ax.invert_yaxis()
    ax.set_xlabel("QLIKE 改善 % （負值＝預測誤差變大）")
    ax.set_title("加上「星期幾」校正之後，預測有變好嗎？",
                 fontsize=12, pad=10)
    for i, (b, p) in enumerate(zip(bars, pvals)):
        x_text = b.get_width() + (0.4 if b.get_width() >= 0 else -0.4)
        ha = "left" if b.get_width() >= 0 else "right"
        ax.text(x_text, b.get_y() + b.get_height() / 2,
                f"顯著性={p:.3f}", va="center", ha=ha, fontsize=10,
                color="#222")
    ax.grid(axis="x", linestyle=":", alpha=0.5)
    ax.text(0.5, -0.16,
            "全部顯著性 > 0.05 → 沒有任何一個市場通過嚴格統計門檻",
            transform=ax.transAxes, ha="center", fontsize=9, color="#555")
    plt.tight_layout()
    out = ROOT / "fig2_calendar_dm.png"
    plt.savefig(out, dpi=150, bbox_inches="tight")
    plt.close()
    print("wrote", out)


# ---------- Fig 3: OpEx effect ----------
def fig3():
    fig, ax = plt.subplots(figsize=(9, 5))

    rows = []
    for mkt in MARKETS:
        ox = RESULTS["assets"][mkt]["opex_effect"]
        opex_vol = np.sqrt(ox["opex_day_mean_r2"] * 252) * 100
        non_vol = np.sqrt(ox["non_opex_mean_r2"] * 252) * 100
        rows.append((mkt, opex_vol, non_vol, ox["p_value"]))

    x = np.arange(len(rows))
    bar_w = 0.36
    opex_vals = [r[1] for r in rows]
    non_vals = [r[2] for r in rows]
    ax.bar(x - bar_w / 2, opex_vals, bar_w, label="期權到期日 (OpEx)",
           color="#dc2626", alpha=0.85)
    ax.bar(x + bar_w / 2, non_vals, bar_w, label="非期權到期日",
           color="#94a3b8", alpha=0.85)
    ax.set_xticks(x)
    ax.set_xticklabels([r[0] for r in rows])
    ax.set_ylabel("年化波動率 (%)")
    ax.set_title("期權到期日 vs 一般交易日的波動率比較",
                 fontsize=12, pad=10)
    ax.legend(framealpha=0.9)
    ax.grid(axis="y", linestyle=":", alpha=0.5)

    for i, (mkt, ov, nv, p) in enumerate(rows):
        sig = "★ 顯著" if p < 0.05 else "不顯著"
        ax.text(i, max(ov, nv) + 0.6,
                f"顯著性={p:.3f}\n{sig}",
                ha="center", fontsize=9,
                color="#dc2626" if p < 0.05 else "#555")

    ax.text(0.5, -0.16,
            "唯一邊緣顯著：SPY OpEx 當天 vol 反而較低 (-33%)；GLD/0050.TW 不顯著",
            transform=ax.transAxes, ha="center", fontsize=9, color="#555")
    plt.tight_layout()
    out = ROOT / "fig3_opex_effect.png"
    plt.savefig(out, dpi=150, bbox_inches="tight")
    plt.close()
    print("wrote", out)


if __name__ == "__main__":
    fig1()
    fig2()
    fig3()
