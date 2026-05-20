"""K455 figure generator. Reads k455_vol_spillover_results.json and writes
PNGs to experiments/k455/figures/. Traditional Chinese, ≥150 dpi, 4 figures.
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib import font_manager

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "k455_vol_spillover_results.json"
FIGDIR = ROOT / "figures"
FIGDIR.mkdir(exist_ok=True)

# zh-Hant font
for f in ["Heiti TC", "PingFang TC", "Arial Unicode MS", "Heiti SC"]:
    try:
        font_manager.findfont(f, fallback_to_default=False)
        plt.rcParams["font.sans-serif"] = [f, "Arial"]
        break
    except Exception:
        continue
plt.rcParams["axes.unicode_minus"] = False

with open(RESULTS) as fh:
    R = json.load(fh)

TICKERS = R["tickers"]
LABEL = {
    "SPY": "美國 SPY",
    "EWJ": "日本 EWJ",
    "EWT": "台灣 EWT",
    "EWY": "韓國 EWY",
    "EWH": "香港 EWH",
    "EWA": "澳洲 EWA",
    "FXI": "中國 FXI",
}


def fig1_network():
    """Spillover network diagram: SPY centred, edges weighted by US→Asia spillover."""
    fig, ax = plt.subplots(figsize=(9, 7), dpi=160)
    pairs = R["pairwise_us_asia"]
    asia = ["EWJ", "EWT", "EWY", "EWH", "EWA", "FXI"]

    # SPY at centre
    spy_xy = (0, 0)
    n = len(asia)
    angles = np.linspace(np.pi / 2, np.pi / 2 + 2 * np.pi, n, endpoint=False)
    asia_xy = {a: (np.cos(t) * 1.5, np.sin(t) * 1.5) for a, t in zip(asia, angles)}

    # Edges (US→Asia, width = us_to_asia value)
    for a in asia:
        v = pairs[a]["us_to_asia"]
        x2, y2 = asia_xy[a]
        # Arrow from SPY to Asia, width prop to value
        ax.annotate(
            "",
            xy=(x2 * 0.78, y2 * 0.78),
            xytext=(spy_xy[0] * 0.18, spy_xy[1] * 0.18),
            arrowprops=dict(
                arrowstyle="-|>",
                lw=v / 4,
                color="#d62728",
                alpha=0.7,
            ),
        )
        # Label edge
        mx, my = x2 * 0.5, y2 * 0.5
        ax.text(mx, my, f"{v:.1f}%", fontsize=9, color="#7f1d1d", ha="center")

    # Asia→US (smaller, blue)
    for a in asia:
        v = pairs[a]["asia_to_us"]
        x1, y1 = asia_xy[a]
        ax.annotate(
            "",
            xy=(spy_xy[0] * 0.18 + 0.05, spy_xy[1] * 0.18 - 0.05),
            xytext=(x1 * 0.78, y1 * 0.78),
            arrowprops=dict(
                arrowstyle="-|>",
                lw=v / 5,
                color="#1f77b4",
                alpha=0.5,
            ),
        )

    # Nodes
    for ticker, (x, y) in {**{"SPY": spy_xy}, **asia_xy}.items():
        size = R["full_sample_spillover"]["to_others"][ticker]
        circ = plt.Circle((x, y), 0.18 + size / 200, color="#fde68a", ec="black", lw=1.5, zorder=5)
        ax.add_patch(circ)
        ax.text(x, y, LABEL[ticker], ha="center", va="center", fontsize=10, zorder=6, fontweight="bold")

    ax.set_xlim(-2.3, 2.3)
    ax.set_ylim(-2.3, 2.3)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title(
        "美國→亞洲 波動率溢出網絡（全樣本 2007-2026）\n紅箭頭：美國→亞洲；藍箭頭：亞洲→美國；數字 = FEVD %",
        fontsize=12,
    )
    fig.tight_layout()
    out = FIGDIR / "fig1_network.png"
    fig.savefig(out, dpi=160, bbox_inches="tight")
    plt.close(fig)
    return out


def fig2_heatmap():
    """Spillover matrix heatmap (i→j FEVD share)."""
    table = R["full_sample_spillover"]["spillover_table"]
    # rows = source i, cols = receiver j; spillover_table[j][i] in original code design
    # Inspect: spillover_table[i_key][j_key] where i_key is "from market" (in Diebold tradition rows = from)
    # We'll plot with rows=Receiver, cols=Source for "誰把波動率傳給誰"
    n = len(TICKERS)
    M = np.zeros((n, n))
    for i, src in enumerate(TICKERS):
        for j, rcv in enumerate(TICKERS):
            # table[rcv][src] = how much of rcv's FEV comes from src
            M[i, j] = table[rcv].get(src, 0.0)

    fig, ax = plt.subplots(figsize=(8, 7), dpi=160)
    im = ax.imshow(M, cmap="YlOrRd", aspect="auto")
    ax.set_xticks(range(n))
    ax.set_yticks(range(n))
    ax.set_xticklabels([LABEL[t] for t in TICKERS], rotation=45, ha="right")
    ax.set_yticklabels([LABEL[t] for t in TICKERS])
    ax.set_xlabel("接收方（FEV 來自何處）")
    ax.set_ylabel("傳出方（波動率來源）")
    ax.set_title("波動率溢出矩陣（FEVD %，全樣本）", fontsize=12)
    for i in range(n):
        for j in range(n):
            ax.text(j, i, f"{M[i, j]:.0f}", ha="center", va="center",
                    color="black" if M[i, j] < 18 else "white", fontsize=8)
    fig.colorbar(im, ax=ax, label="FEVD %")
    fig.tight_layout()
    out = FIGDIR / "fig2_heatmap.png"
    fig.savefig(out, dpi=160, bbox_inches="tight")
    plt.close(fig)
    return out


def fig3_rolling():
    """Time-varying total spillover index with crisis annotations."""
    ts = pd.DataFrame(R["rolling_spillover"]["time_series"])
    ts["date"] = pd.to_datetime(ts["date"])

    fig, axes = plt.subplots(2, 1, figsize=(10, 7), dpi=160, sharex=True)
    ax1, ax2 = axes

    ax1.plot(ts["date"], ts["total"], color="#1f77b4", lw=2)
    ax1.axhline(R["rolling_spillover"]["mean"], ls="--", color="gray", lw=1,
                label=f"平均 {R['rolling_spillover']['mean']:.1f}%")
    ax1.fill_between(ts["date"], 0, ts["total"], alpha=0.15, color="#1f77b4")
    ax1.set_ylabel("總溢出指數 (%)")
    ax1.set_title("全市場波動率溢出指數（200 日滾動視窗）", fontsize=12)
    # Crisis annotations
    crises = [
        ("2008-09-15", "雷曼"),
        ("2020-03-15", "COVID"),
        ("2022-03-16", "升息週期"),
        ("2025-04-02", "關稅震盪"),
    ]
    for d, lbl in crises:
        ax1.axvline(pd.Timestamp(d), ls=":", color="red", alpha=0.5)
        ax1.text(pd.Timestamp(d), ax1.get_ylim()[1] * 0.95, lbl,
                 rotation=90, fontsize=8, color="red", va="top")
    ax1.legend(loc="lower right")
    ax1.grid(alpha=0.3)

    # SPY net spillover
    ax2.plot(ts["date"], ts["spy_net"], color="#d62728", lw=1.8)
    ax2.axhline(0, ls="-", color="black", lw=0.8)
    ax2.fill_between(ts["date"], 0, ts["spy_net"],
                     where=(ts["spy_net"] >= 0), alpha=0.3, color="#d62728",
                     label="SPY 為淨傳出")
    ax2.fill_between(ts["date"], 0, ts["spy_net"],
                     where=(ts["spy_net"] < 0), alpha=0.3, color="#1f77b4",
                     label="SPY 為淨接收")
    ax2.set_ylabel("SPY 淨溢出 (%)")
    ax2.set_xlabel("日期")
    ax2.set_title("SPY 淨溢出（>0：美國輸出風險；<0：美國接收風險）", fontsize=11)
    ax2.legend(loc="upper left")
    ax2.grid(alpha=0.3)

    fig.tight_layout()
    out = FIGDIR / "fig3_rolling.png"
    fig.savefig(out, dpi=160, bbox_inches="tight")
    plt.close(fig)
    return out


def fig4_ranking():
    """Top spillover sources / receivers + US→Asia pairwise ranking."""
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.5), dpi=160)

    # Left: net spillover ranking
    net = R["full_sample_spillover"]["net"]
    items = sorted(net.items(), key=lambda x: x[1], reverse=True)
    names = [LABEL[t] for t, _ in items]
    vals = [v for _, v in items]
    colors = ["#d62728" if v >= 0 else "#1f77b4" for v in vals]
    ax1 = axes[0]
    bars = ax1.barh(names, vals, color=colors, edgecolor="black", lw=0.8)
    ax1.axvline(0, color="black", lw=0.8)
    ax1.set_xlabel("淨溢出（傳出 - 接收，%）")
    ax1.set_title("市場淨溢出排序（>0 = 風險輸出國）", fontsize=11)
    ax1.invert_yaxis()
    for bar, v in zip(bars, vals):
        ax1.text(v + (0.05 if v >= 0 else -0.05), bar.get_y() + bar.get_height() / 2,
                 f"{v:+.2f}%", va="center", ha="left" if v >= 0 else "right", fontsize=9)
    ax1.grid(axis="x", alpha=0.3)

    # Right: US→Asia net (each Asian market)
    pairs = R["pairwise_us_asia"]
    asia_items = sorted(pairs.items(), key=lambda x: x[1]["net_us_to_asia"], reverse=True)
    a_names = [LABEL[t] for t, _ in asia_items]
    a_vals = [v["net_us_to_asia"] for _, v in asia_items]
    ax2 = axes[1]
    bars2 = ax2.barh(a_names, a_vals, color="#fb923c", edgecolor="black", lw=0.8)
    ax2.set_xlabel("美國→亞洲 淨溢出（%）")
    ax2.set_title("美國對亞洲各市場的淨溢出強度", fontsize=11)
    ax2.invert_yaxis()
    for bar, v in zip(bars2, a_vals):
        ax2.text(v + 0.05, bar.get_y() + bar.get_height() / 2,
                 f"{v:+.2f}%", va="center", fontsize=9)
    ax2.grid(axis="x", alpha=0.3)

    fig.suptitle("誰是波動率傳染的源頭與最終承受者？", fontsize=13, y=1.02)
    fig.tight_layout()
    out = FIGDIR / "fig4_ranking.png"
    fig.savefig(out, dpi=160, bbox_inches="tight")
    plt.close(fig)
    return out


if __name__ == "__main__":
    outs = []
    for fn in (fig1_network, fig2_heatmap, fig3_rolling, fig4_ranking):
        out = fn()
        print(f"wrote {out}")
        outs.append(out)
    print(f"done; {len(outs)} figures")
