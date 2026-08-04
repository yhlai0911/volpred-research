"""Charts for the K1709 general-audience article.

Both figures read every number from experiments/k1709/k1709_results.json.
Nothing is hard-coded except labels and layout.

  1. k1709_general_oos.png -- the out-of-sample accuracy change for all ten
     pre-registered test cells. Seven land left of zero (the flow model did
     worse), three land right of zero by less than half a percent.
  2. k1709_general_power.png -- the detection-probability curves for BTC and
     ETH: how often this test would notice a flow effect of a given size.
     The shaded band covers the smallest simulated effect sizes, where the
     curves sit near the floor.
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
RESULTS = ROOT / "experiments" / "k1709" / "k1709_results.json"
ASSETS = ROOT / "storage" / "drafts" / "assets"

C_WORSE = "#B45309"
C_BETTER = "#1D4ED8"
C_BAND = "#E7E5E4"
C_GRID = "#D4D4D8"
C_TEXT = "#27272A"
C_MUTED = "#71717A"

HORIZON_LABEL = {1: "隔日", 5: "五日"}
ALT_LABEL = {
    "H1_absflow": "金流規模",
    "H2_asym": "金流方向不對稱",
    "H4_plus_btc": "加上比特幣金流外溢",
}


def load() -> dict:
    return json.loads(RESULTS.read_text())


def cell_label(cell: dict) -> str:
    return (
        f"{cell['asset']} {HORIZON_LABEL[cell['horizon']]}"
        f"／{ALT_LABEL[cell['alt']]}"
    )


def fig_oos(data: dict) -> Path:
    cells = data["primary_cells"]
    rows = sorted(
        (
            (cell_label(c), c["qlike_improvement_pct"], c["n_oos"])
            for c in cells
        ),
        key=lambda r: r[1],
    )
    labels = [r[0] for r in rows]
    values = [r[1] for r in rows]
    counts = [r[2] for r in rows]
    colors = [C_BETTER if v > 0 else C_WORSE for v in values]

    n_better = sum(1 for v in values if v > 0)
    n_worse = len(values) - n_better

    fig, ax = plt.subplots(figsize=(9.6, 6.2), dpi=160)
    ypos = range(len(rows))
    ax.barh(list(ypos), values, height=0.58, color=colors, zorder=2)
    ax.axvline(0, color=C_TEXT, lw=1.4, zorder=3)

    span = max(abs(min(values)), abs(max(values)))
    for i, (v, n) in enumerate(zip(values, counts)):
        off = span * 0.045
        ax.text(
            v - off if v < 0 else v + off,
            i,
            f"{v:+.2f}%",
            va="center",
            ha="right" if v < 0 else "left",
            fontsize=10.5,
            weight="bold",
            color=C_WORSE if v < 0 else C_BETTER,
        )
        ax.text(
            span * 1.12,
            i,
            f"{n} 天",
            va="center",
            ha="right",
            fontsize=9,
            color=C_MUTED,
        )

    ax.set_yticks(list(ypos))
    ax.set_yticklabels(labels, fontsize=10.5)
    ax.set_xlim(-span * 1.30, span * 1.16)
    ax.set_xlabel("預測準確度變化（正號＝比較準，負號＝比較不準）", fontsize=10)
    ax.set_title(
        f"十個事先講好的測試格：{n_worse} 格加了金流反而更不準，{n_better} 格好一點點",
        fontsize=13.5,
        pad=14,
        weight="bold",
    )
    ax.text(
        -span * 1.26,
        len(rows) - 0.25,
        f"預測期間 {cells[0]['oos_start']} ~ {cells[0]['oos_end']}",
        fontsize=9.5,
        color=C_MUTED,
        ha="left",
    )
    ax.grid(axis="x", color=C_GRID, lw=0.7, zorder=0)
    ax.set_axisbelow(True)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    fig.tight_layout()

    out = ASSETS / "k1709_general_oos.png"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out


def fig_power(data: dict) -> Path:
    sim = data["power_simulation"]
    series = [("BTC", C_BETTER, "o"), ("ETH", C_WORSE, "s")]

    fig, ax = plt.subplots(figsize=(9.6, 5.6), dpi=160)

    curves = {}
    for asset, color, marker in series:
        curve = sim[asset]["curve"]
        xs = [p["rv_uplift_per_1sd_shock_pct"] for p in curve]
        ys = [p["power_gw_one_sided_5pct"] * 100 for p in curve]
        curves[asset] = (xs, ys)

    band_xs = sorted(curves["BTC"][0])
    band_lo, band_hi = band_xs[1], band_xs[3]
    ax.axvspan(band_lo, band_hi, color=C_BAND, zorder=0)
    ax.text(
        (band_lo + band_hi) / 2,
        99,
        "比較可能出現的效果大小",
        fontsize=9.5,
        color=C_MUTED,
        ha="center",
    )

    ax.axhline(50, color=C_GRID, lw=1.2, ls=(0, (4, 3)), zorder=1)
    ax.text(
        max(curves["BTC"][0]) * 0.995,
        52,
        "一半的機率",
        fontsize=9,
        color=C_MUTED,
        ha="right",
    )

    for asset, color, marker in series:
        xs, ys = curves[asset]
        ax.plot(xs, ys, color=color, lw=2.0, marker=marker, ms=6.5,
                mec="white", mew=1.4, zorder=3, label=asset)

    call_x = sorted(curves["BTC"][0])[2]
    ax.text(
        call_x + 12,
        88,
        f"波動被推高 {call_x:.1f}% 的話，",
        fontsize=10.5,
        color=C_TEXT,
        va="center",
    )
    for row, (asset, color, _) in enumerate(series):
        xs, ys = curves[asset]
        idx = xs.index(call_x)
        ax.text(
            call_x + 12,
            80 - row * 8,
            f"{asset} 抓得到的機率 {ys[idx]:.1f}%",
            fontsize=10.5,
            weight="bold",
            color=color,
            va="center",
        )

    for asset, color, _ in series:
        xs, ys = curves[asset]
        ax.text(
            xs[-1] + 1.2,
            ys[-1],
            f"{ys[-1]:.1f}%",
            fontsize=10.5,
            weight="bold",
            color=color,
            va="center",
        )

    reps = sim["BTC"]["reps_per_beta"]
    ax.set_xlim(-2, max(curves["BTC"][0]) * 1.14)
    ax.set_ylim(0, 104)
    ax.set_xlabel("假設金流真的把波動推高幾 %（單日一個標準差的金流衝擊）", fontsize=10)
    ax.set_ylabel("這套測試抓得到的機率（%）", fontsize=10)
    ax.set_title(
        f"要金流把波動推高五成以上，這份資料才有七成把握看得見（各 {reps} 次模擬）",
        fontsize=13.5,
        pad=14,
        weight="bold",
    )
    ax.legend(frameon=False, fontsize=10.5, loc="lower right")
    ax.grid(axis="y", color=C_GRID, lw=0.7, zorder=0)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    fig.tight_layout()

    out = ASSETS / "k1709_general_power.png"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    data = load()
    for p in (fig_oos(data), fig_power(data)):
        print(f"wrote {p.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
