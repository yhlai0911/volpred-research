#!/usr/bin/env python3
"""K1580 圖表：regime heatmap + 全期對比 bar + 32 年累積曲線。"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
matplotlib.rcParams["font.sans-serif"] = [
    "Arial Unicode MS", "PingFang TC", "Heiti TC", "Microsoft JhengHei", "sans-serif",
]
matplotlib.rcParams["axes.unicode_minus"] = False
import matplotlib.pyplot as plt
import numpy as np

HERE = Path(__file__).parent
RES = json.load(open(HERE / "k1580_results.json"))

BASKET_ZH = {
    "TW_large_caps": "台灣大型股\n(對照0050)",
    "TW_large_caps_TWII": "台灣大型股\n(對照TWII)",
    "US_large_caps": "美國大型股\n(對照SPY)",
    "US_sector_ETFs": "美國產業ETF\n(無個股偏差)",
    "US_multi_asset": "多資產類別\n(股債金REIT商品)",
    "Global_country_ETFs": "跨國家ETF\n(9國)",
}
REGIMES = [p[0] for p in [
    ("2000-2002 網路泡沫破裂",), ("2003-2007 多頭",), ("2008-2009 金融海嘯",),
    ("2010-2019 長多頭/低波",), ("2020-2021 COVID 崩跌+反彈",),
    ("2022 升息/輪動",), ("2023-2024 AI 大型股",),
]]
REGIME_SHORT = {
    "2000-2002 網路泡沫破裂": "2000-02\n網路泡沫",
    "2003-2007 多頭": "2003-07\n多頭",
    "2008-2009 金融海嘯": "2008-09\n金融海嘯",
    "2010-2019 長多頭/低波": "2010-19\n長多/低波",
    "2020-2021 COVID 崩跌+反彈": "2020-21\nCOVID",
    "2022 升息/輪動": "2022\n升息輪動",
    "2023-2024 AI 大型股": "2023-24\nAI大型股",
}
baskets = [b for b in BASKET_ZH if b in RES["baskets"] and "error" not in RES["baskets"][b]]


def chart_a_heatmap():
    mat = np.full((len(baskets), len(REGIMES)), np.nan)
    for i, bk in enumerate(baskets):
        sp = {s["period"]: s for s in RES["baskets"][bk].get("subperiods_default_cost", [])}
        for j, rg in enumerate(REGIMES):
            if rg in sp:
                mat[i, j] = sp[rg]["rebal_minus_bh_cagr"] * 100
    fig, ax = plt.subplots(figsize=(12, 6.5))
    vmax = np.nanmax(np.abs(mat))
    im = ax.imshow(mat, cmap="RdYlGn", vmin=-vmax, vmax=vmax, aspect="auto")
    ax.set_xticks(range(len(REGIMES)))
    ax.set_xticklabels([REGIME_SHORT[r] for r in REGIMES], fontsize=9)
    ax.set_yticks(range(len(baskets)))
    ax.set_yticklabels([BASKET_ZH[b] for b in baskets], fontsize=9)
    for i in range(len(baskets)):
        for j in range(len(REGIMES)):
            if not np.isnan(mat[i, j]):
                v = mat[i, j]
                ax.text(j, i, f"{v:+.1f}", ha="center", va="center", fontsize=9,
                        color="black" if abs(v) < vmax * 0.6 else "white", fontweight="bold")
            else:
                ax.text(j, i, "—", ha="center", va="center", fontsize=10, color="gray")
    ax.set_title("年度等權再平衡「贏買進持有多少」分時期熱力圖（rebal − BH，年化 CAGR 差，%/年）\n"
                 "綠=再平衡贏　紅=再平衡輸　危機/輪動年(2008,2022)幾乎全綠　單邊大型股年(2020-21,2023-24)轉紅",
                 fontsize=11, pad=14)
    cbar = fig.colorbar(im, ax=ax, shrink=0.8)
    cbar.set_label("rebal − BH 年化差 (%/年)", fontsize=9)
    fig.tight_layout()
    fig.savefig(HERE / "fig_a_regime_heatmap.png", dpi=140, bbox_inches="tight")
    plt.close(fig)
    print("fig_a_regime_heatmap.png")


def chart_b_fullperiod():
    fig, ax = plt.subplots(figsize=(12, 6))
    x = np.arange(len(baskets))
    w = 0.27
    reb, bh, bench, periods = [], [], [], []
    for bk in baskets:
        b = RES["baskets"][bk]; dc = b["verdict"]["default_cost"]; m = b["by_cost"][dc]
        reb.append(m["rebalance"]["cagr"] * 100)
        bh.append(m["buy_hold"]["cagr"] * 100)
        bench.append(m["benchmark"]["cagr"] * 100)
        periods.append(b["period"]["start"][:4] + "–" + b["period"]["end"][:4])
    ax.bar(x - w, reb, w, label="年度等權再平衡", color="#2b8cbe")
    ax.bar(x, bh, w, label="買進持有(同籃子)", color="#e34a33")
    ax.bar(x + w, bench, w, label="大盤指數", color="#999999")
    for i in range(len(baskets)):
        ax.text(i - w, reb[i] + 0.2, f"{reb[i]:.1f}", ha="center", fontsize=8)
        ax.text(i, bh[i] + 0.2, f"{bh[i]:.1f}", ha="center", fontsize=8)
    ax.set_xticks(x)
    ax.set_xticklabels([BASKET_ZH[b] + f"\n{periods[i]}" for i, b in enumerate(baskets)], fontsize=8)
    ax.set_ylabel("年化報酬 CAGR (%)")
    ax.set_title("全期年化報酬：再平衡 vs 買進持有 vs 大盤指數（7 籃子）\n"
                 "再平衡與買進持有在每個籃子都幾乎打平（差異全部統計不顯著）", fontsize=11)
    ax.legend(fontsize=9)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(HERE / "fig_b_fullperiod_bar.png", dpi=140, bbox_inches="tight")
    plt.close(fig)
    print("fig_b_fullperiod_bar.png")


def chart_c_cumulative():
    """美國大型股 1993-2024 累積曲線（重 simulate）。"""
    import k1580
    spec = k1580.BASKETS["US_large_caps"]
    prices_raw = k1580._download(spec["tickers"], k1580.START, k1580.END)
    bench_raw = k1580._download([spec["benchmark"]], k1580.START, k1580.END)
    prices, bench = k1580._basket_window(prices_raw, bench_raw.iloc[:, 0])
    cr = k1580.COST_BPS_GRID[spec["default_cost"]]
    reb = k1580._simulate(prices, True, cr) / k1580.INITIAL
    bh = k1580._simulate(prices, False, cr) / k1580.INITIAL
    bm = k1580._simulate_benchmark(bench, cr) / k1580.INITIAL
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(reb.index, reb, label="年度等權再平衡", color="#2b8cbe", lw=1.6)
    ax.plot(bh.index, bh, label="買進持有(同籃子)", color="#e34a33", lw=1.6)
    ax.plot(bm.index, bm, label="SPY 大盤", color="#999999", lw=1.3, ls="--")
    ax.set_yscale("log")
    ax.set_ylabel("累積淨值（對數軸，期初=1）")
    ax.set_title("美國大型股 1993–2024（32 年）累積淨值：再平衡 vs 買進持有 vs SPY\n"
                 "兩條策略線幾乎重疊 — 32 年下來再平衡與買進持有打平（rebal 15.94% vs BH 15.89%）", fontsize=11)
    ax.legend(fontsize=9)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(HERE / "fig_c_us_cumulative.png", dpi=140, bbox_inches="tight")
    plt.close(fig)
    print("fig_c_us_cumulative.png")


if __name__ == "__main__":
    chart_a_heatmap()
    chart_b_fullperiod()
    chart_c_cumulative()
    print("圖表完成")
