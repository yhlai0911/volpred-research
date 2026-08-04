"""Charts for the K1342 general-audience article.

Every number is read from experiments/K1342/K1342_results.json at run time.
Only labels, layout and colours are hard-coded.

  1. k1342_general_horizons.png -- the three holding windows, gross vs net of
     the 3.4 bps round-trip cost, on one bps axis with a zero line. The point
     the reader should see: the 15:52-to-close leg is already the only negative
     gross bar, and the cost line pushes it further down, while the two
     next-session bars survive the cost but sit on tiny statistical strength.
  2. k1342_general_pressure.png -- full sample vs the high-pressure subset,
     net mean return per holding window. Filtering for a louder signal makes
     the late-close leg worse, not better.

Palette: two categorical slots #1D4ED8 (blue) / #B45309 (amber) on light
surface #FCFCFB. Verified with the dataviz skill's validate_palette.js --
all six checks PASS, worst adjacent CVD dE 30.0 (protan), normal-vision 35.3.
Every bar also carries a direct value label, so identity never rests on hue
alone.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.sans-serif"] = [
    "PingFang TC",
    "PingFang HK",
    "Heiti TC",
    "Arial Unicode MS",
]
plt.rcParams["axes.unicode_minus"] = False

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "experiments" / "K1342" / "K1342_results.json"
ASSETS = ROOT / "storage" / "drafts" / "assets"

C_A = "#1D4ED8"
C_B = "#B45309"
C_GRID = "#D4D4D8"
C_TEXT = "#27272A"
C_MUTED = "#71717A"
C_SURFACE = "#FCFCFB"

HORIZONS = [
    ("late_close", "收盤前那幾分鐘\n（15:52 → 收盤）"),
    ("overnight_open", "抱過夜\n（收盤 → 隔日開盤）"),
    ("next_close", "抱一整天\n（收盤 → 隔日收盤）"),
]


def load() -> dict:
    return json.loads(RESULTS.read_text())


def _style_axis(ax) -> None:
    ax.set_facecolor(C_SURFACE)
    ax.grid(axis="y", color=C_GRID, lw=0.7, zorder=0)
    ax.set_axisbelow(True)
    ax.tick_params(axis="y", labelsize=9, colors=C_MUTED)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(C_GRID)


def _label_bars(ax, xs, values, span) -> None:
    for x, v in zip(xs, values):
        above = v >= 0
        ax.text(
            x,
            v + (span * 0.022 if above else -span * 0.022),
            f"{v:+.2f}",
            ha="center",
            va="bottom" if above else "top",
            fontsize=11,
            weight="bold",
            color=C_TEXT,
            zorder=6,
        )


def fig_horizons(data: dict) -> Path:
    pooled = data["pooled_daily_equal_weight"]["all_days"]
    cost = data["round_trip_cost_bps"]
    n_obs = data["sample"]["n_observations_all"]
    n_dates = data["sample"]["n_dates_all"]

    gross = [pooled[k]["gross_mean_bps"] for k, _ in HORIZONS]
    net = [pooled[k]["net_mean_bps"] for k, _ in HORIZONS]

    fig, ax = plt.subplots(figsize=(10.6, 6.2), dpi=160)
    fig.patch.set_facecolor(C_SURFACE)
    _style_axis(ax)

    xs = [0.0, 1.0, 2.0]
    w = 0.34
    xs_g = [x - w / 2 - 0.012 for x in xs]
    xs_n = [x + w / 2 + 0.012 for x in xs]

    ax.bar(xs_g, gross, width=w, color=C_A, zorder=3,
           edgecolor=C_SURFACE, linewidth=2.0, label="還沒扣交易成本")
    ax.bar(xs_n, net, width=w, color=C_B, zorder=3,
           edgecolor=C_SURFACE, linewidth=2.0, label="扣掉來回成本後")

    lo = min(net + gross + [0.0])
    hi = max(net + gross + [0.0])
    span = hi - lo
    ax.set_ylim(lo - span * 0.30, hi + span * 0.26)

    _label_bars(ax, xs_g, gross, span)
    _label_bars(ax, xs_n, net, span)

    ax.axhline(0, color=C_TEXT, lw=1.4, zorder=4)

    ax.set_xlim(-0.72, 2.62)
    ax.text(
        0.0,
        lo - span * 0.22,
        "這一組還沒扣成本就是負的",
        fontsize=11,
        weight="bold",
        color=C_B,
        ha="center",
        va="center",
    )
    ax.text(
        2.34,
        (gross[2] + net[2]) / 2,
        f"每一組藍橘的落差\n都是同一筆來回成本\n{cost} 個基點",
        fontsize=10,
        color=C_MUTED,
        ha="left",
        va="center",
    )

    ax.set_xticks(xs)
    ax.set_xticklabels([lab for _, lab in HORIZONS], fontsize=11, color=C_TEXT)
    ax.set_ylabel("平均每次進出的報酬（基點）", fontsize=11, color=C_TEXT)
    ax.set_title(
        "順著盤尾買賣壓做：三個抱單長度，只有最短的那個連成本都還沒扣就是負的",
        fontsize=14.5,
        weight="bold",
        color=C_TEXT,
        pad=32,
    )
    ax.text(
        0.0,
        1.015,
        f"10 檔標的、{n_obs} 個標的日、{n_dates} 個交易日，"
        f"{data['sample']['first_signal_date']} 至 {data['sample']['last_signal_date']}",
        transform=ax.transAxes,
        fontsize=9.5,
        color=C_MUTED,
        ha="left",
        va="bottom",
    )
    ax.legend(loc="upper left", frameon=False, fontsize=10.5, ncol=1)

    fig.tight_layout()
    out = ASSETS / "k1342_general_horizons.png"
    fig.savefig(out, bbox_inches="tight", facecolor=C_SURFACE)
    plt.close(fig)
    return out


def fig_pressure(data: dict) -> Path:
    pooled = data["pooled_daily_equal_weight"]
    sample = data["sample"]

    all_net = [pooled["all_days"][k]["net_mean_bps"] for k, _ in HORIZONS]
    hp_net = [pooled["high_pressure_days"][k]["net_mean_bps"] for k, _ in HORIZONS]

    fig, ax = plt.subplots(figsize=(10.6, 6.2), dpi=160)
    fig.patch.set_facecolor(C_SURFACE)
    _style_axis(ax)

    xs = [0.0, 1.0, 2.0]
    w = 0.34
    xs_a = [x - w / 2 - 0.012 for x in xs]
    xs_h = [x + w / 2 + 0.012 for x in xs]

    ax.bar(
        xs_a, all_net, width=w, color=C_A, zorder=3,
        edgecolor=C_SURFACE, linewidth=2.0,
        label=f"全部日子（{sample['n_observations_all']} 個標的日）",
    )
    ax.bar(
        xs_h, hp_net, width=w, color=C_B, zorder=3,
        edgecolor=C_SURFACE, linewidth=2.0,
        label=f"只留買賣壓最明顯的日子（{sample['n_observations_high_pressure']} 個標的日）",
    )

    lo = min(all_net + hp_net + [0.0])
    hi = max(all_net + hp_net + [0.0])
    span = hi - lo
    ax.set_ylim(lo - span * 0.32, hi + span * 0.24)

    _label_bars(ax, xs_a, all_net, span)
    _label_bars(ax, xs_h, hp_net, span)

    ax.axhline(0, color=C_TEXT, lw=1.4, zorder=4)

    ax.set_xlim(-0.72, 2.62)
    ax.text(
        0.0,
        lo - span * 0.22,
        "把雜訊篩掉之後，這一格反而更負",
        fontsize=11,
        weight="bold",
        color=C_B,
        ha="center",
        va="center",
    )

    ax.set_xticks(xs)
    ax.set_xticklabels([lab for _, lab in HORIZONS], fontsize=11, color=C_TEXT)
    ax.set_ylabel("扣掉成本後的平均報酬（基點）", fontsize=11, color=C_TEXT)
    ax.set_title(
        "訊號挑得更嚴，收盤前那一段的虧損反而擴大",
        fontsize=14.5,
        weight="bold",
        color=C_TEXT,
        pad=32,
    )
    ax.text(
        0.0,
        1.015,
        "門檻＝該檔前 20 個交易日買賣壓絕對值的第 70 百分位，只用當天之前的資料算，"
        f"留下 {sample['n_dates_high_pressure']} 個交易日",
        transform=ax.transAxes,
        fontsize=9.5,
        color=C_MUTED,
        ha="left",
        va="bottom",
    )
    ax.legend(loc="upper left", frameon=False, fontsize=10.5, ncol=1)

    fig.tight_layout()
    out = ASSETS / "k1342_general_pressure.png"
    fig.savefig(out, bbox_inches="tight", facecolor=C_SURFACE)
    plt.close(fig)
    return out


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    data = load()
    for path in (fig_horizons(data), fig_pressure(data)):
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
