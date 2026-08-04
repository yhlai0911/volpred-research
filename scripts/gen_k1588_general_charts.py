"""Charts for the K1588 general-audience article.

Every number is read from experiments/k1588/k1588_results.json at run time.
Only labels, colours and layout are written here.

  1. k1588_general_tercile.png -- mean earnings-day jump and mean decay speed
     for the low / mid / high SCI terciles. The point of the figure is that
     the low tercile sits clearly above the other two while mid and high are
     effectively tied, so the pattern is a gap at one end rather than a dose
     response along the SCI axis.
  2. k1588_general_gap.png -- the same high-minus-low gap shown twice: once
     as the raw group difference with its cluster bootstrap interval over
     companies, and once as the SCI coefficient from the controlled
     regression with its own bootstrap interval. All four intervals cross
     zero.

Palette: #B45309 (low tercile / raw cut), #1D4ED8 (high tercile / adjusted
cut), #71717A (mid tercile). Every mark carries a direct value label, so the
figures do not rely on colour discrimination alone.
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
RESULTS = ROOT / "experiments" / "k1588" / "k1588_results.json"
ASSETS = ROOT / "storage" / "drafts" / "assets"

C_LOW = "#B45309"
C_MID = "#71717A"
C_HIGH = "#1D4ED8"
C_GRID = "#D4D4D8"
C_TEXT = "#27272A"
C_MUTED = "#71717A"
C_SURFACE = "#FCFCFB"

TERCILE_LABELS = {
    "Low SCI": "連結最窄的三分之一",
    "Mid SCI": "中間的三分之一",
    "High SCI": "連結最廣的三分之一",
}
TERCILE_COLORS = {"Low SCI": C_LOW, "Mid SCI": C_MID, "High SCI": C_HIGH}
ORDER = ["Low SCI", "Mid SCI", "High SCI"]


def load() -> dict:
    return json.loads(RESULTS.read_text())


def _by_tercile(rows: list[dict]) -> dict[str, dict]:
    return {r["tercile"]: r for r in rows}


def fig_tercile(data: dict) -> Path:
    res = data["results"]
    panels = [
        ("財報日的波動跳升", _by_tercile(res["jump_tercile_summary"])),
        ("跳升之後的衰退速度", _by_tercile(res["decay_tercile_summary"])),
    ]
    n_events = data["data"]["sample_size"]["events"]
    n_tickers = data["data"]["sample_size"]["tickers"]

    fig, axes = plt.subplots(1, 2, figsize=(11.2, 6.0), dpi=160)
    fig.patch.set_facecolor(C_SURFACE)

    for ax, (panel_title, table) in zip(axes, panels):
        ax.set_facecolor(C_SURFACE)
        values = [table[k]["mean"] for k in ORDER]
        colors = [TERCILE_COLORS[k] for k in ORDER]
        xpos = list(range(len(ORDER)))

        ax.bar(xpos, values, width=0.52, color=colors, zorder=3,
               edgecolor=C_SURFACE, linewidth=2.0)

        top = max(values)
        ax.set_ylim(0, top * 1.28)
        for x, v, k in zip(xpos, values, ORDER):
            ax.text(x, v + top * 0.035, f"{v:.4f}", ha="center", va="bottom",
                    fontsize=12.5, weight="bold", color=C_TEXT, zorder=5)
            ax.text(x, top * 0.045, f"{table[k]['n']} 場", ha="center",
                    va="bottom", fontsize=9.5, color=C_SURFACE, zorder=6)

        ax.set_xticks(xpos)
        ax.set_xticklabels(
            [TERCILE_LABELS[k].replace("的三分之一", "\n的三分之一") for k in ORDER],
            fontsize=10.5,
        )
        ax.set_title(panel_title, fontsize=12.5, pad=10, color=C_TEXT)
        ax.grid(axis="y", color=C_GRID, lw=0.7, zorder=0)
        ax.set_axisbelow(True)
        ax.tick_params(axis="y", labelsize=9, colors=C_MUTED)
        for s in ("top", "right", "left"):
            ax.spines[s].set_visible(False)
        ax.spines["bottom"].set_color(C_GRID)

    axes[0].set_ylabel("倍率取對數後的平均值（越高＝反應越大）",
                       fontsize=10.5, color=C_TEXT)

    fig.suptitle(
        "低的那一組自己站得比較高，中間和最高那兩組幾乎一樣",
        fontsize=15, weight="bold", color=C_TEXT, y=0.98,
    )
    fig.text(
        0.5, 0.905,
        f"依總部所在郡的社交連結廣度分成三組，{n_tickers} 家美國公司、"
        f"{n_events} 場財報。橫軸沒有控制產業、年份或市場環境。",
        fontsize=9.5, color=C_MUTED, ha="center",
    )
    fig.tight_layout(rect=(0, 0.01, 1, 0.885))

    out = ASSETS / "k1588_general_tercile.png"
    fig.savefig(out, bbox_inches="tight", facecolor=C_SURFACE)
    plt.close(fig)
    return out


def fig_gap(data: dict) -> Path:
    res = data["results"]
    full = data["model"]["full_sample"]

    rows = [
        (
            "粗比較　波動跳升",
            res["welch_tests"]["jump_log_abs_high_vs_low"]["mean_diff"],
            res["bootstrap_group_diff"]["jump_log_abs"]["ci"],
            C_LOW,
        ),
        (
            "粗比較　衰退速度",
            res["welch_tests"]["decay_speed_log_abs_high_vs_low"]["mean_diff"],
            res["bootstrap_group_diff"]["decay_speed_log_abs"]["ci"],
            C_LOW,
        ),
        (
            "控制後　波動跳升",
            full["jump_log_abs"]["params"]["county_sci_z"],
            full["jump_log_abs"]["cluster_bootstrap"]["ci"]["county_sci_z"],
            C_HIGH,
        ),
        (
            "控制後　衰退速度",
            full["decay_speed_log_abs"]["params"]["county_sci_z"],
            full["decay_speed_log_abs"]["cluster_bootstrap"]["ci"]["county_sci_z"],
            C_HIGH,
        ),
    ]

    fig, ax = plt.subplots(figsize=(10.6, 5.8), dpi=160)
    fig.patch.set_facecolor(C_SURFACE)
    ax.set_facecolor(C_SURFACE)

    ypos = list(range(len(rows)))[::-1]
    for y, (label, point, ci, color) in zip(ypos, rows):
        lo, hi = ci["lo"], ci["hi"]
        ax.plot([lo, hi], [y, y], color=color, lw=3.2, solid_capstyle="round",
                alpha=0.42, zorder=3)
        ax.plot([lo, lo], [y - 0.13, y + 0.13], color=color, lw=2.0, zorder=3)
        ax.plot([hi, hi], [y - 0.13, y + 0.13], color=color, lw=2.0, zorder=3)
        ax.scatter([point], [y], s=115, color=color, zorder=5,
                   edgecolor=C_SURFACE, linewidth=1.6)
        ax.text(point, y + 0.26, f"{point:+.4f}", ha="center", va="bottom",
                fontsize=11.5, weight="bold", color=C_TEXT, zorder=6)
        ax.text(lo, y - 0.30, f"{lo:+.4f}", ha="center", va="top",
                fontsize=9, color=C_MUTED)
        ax.text(hi, y - 0.30, f"{hi:+.4f}", ha="center", va="top",
                fontsize=9, color=C_MUTED)

    ax.axvline(0.0, color=C_TEXT, lw=1.6, ls=(0, (5, 4)), zorder=4)
    ax.text(0.0, len(rows) - 0.42, "零", fontsize=11, weight="bold",
            color=C_TEXT, ha="center", va="bottom")

    ax.set_yticks(ypos)
    ax.set_yticklabels([r[0] for r in rows], fontsize=11)
    ax.set_ylim(-0.75, len(rows) - 0.35)
    ax.set_xlabel("連結最廣那一端相對於最窄那一端的差距（越右邊＝反應越大）",
                  fontsize=10.5, color=C_TEXT)
    ax.grid(axis="x", color=C_GRID, lw=0.7, zorder=0)
    ax.set_axisbelow(True)
    ax.tick_params(axis="x", labelsize=9, colors=C_MUTED)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(C_GRID)

    n_boot = res["bootstrap_group_diff"]["jump_log_abs"]["n_boot"]
    fig.suptitle(
        "四條線全部壓在零上面，包含那兩條粗比較",
        fontsize=15, weight="bold", color=C_TEXT, y=0.99,
    )
    fig.text(
        0.5, 0.915,
        f"橫線是以公司為單位重抽 {n_boot} 次得到的區間。上兩列是三分組的平均值直接相減，"
        "下兩列是控制產業、年份、市場波動環境與財報意外之後，社交連結每高一個標準差的估計值。",
        fontsize=9.5, color=C_MUTED, ha="center",
    )
    fig.tight_layout(rect=(0, 0.01, 1, 0.895))

    out = ASSETS / "k1588_general_gap.png"
    fig.savefig(out, bbox_inches="tight", facecolor=C_SURFACE)
    plt.close(fig)
    return out


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    data = load()
    for path in (fig_tercile(data), fig_gap(data)):
        print(path)


if __name__ == "__main__":
    main()
