"""Charts for the K1680 general-audience article.

Both figures read from experiments/k1680/K1680_results.json.

  1. k1680_general_multiplicity.png -- each of the four tested targets before
     and after the correction for having tested four things at once. The
     before/after pair is the point: one target looks interesting on its own
     and stops looking interesting once the family is accounted for.
  2. k1680_general_per_firm.png -- the per-firm accuracy change on the best
     target. Signs disagree across the six firms, which is what a real effect
     is not supposed to look like.
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
RESULTS = ROOT / "experiments" / "k1680" / "K1680_results.json"
ASSETS = ROOT / "storage" / "assets"

C_RAW = "#B45309"
C_ADJ = "#52525B"
C_POS = "#0F766E"
C_NEG = "#B45309"
C_BAND = "#E4E4E7"
C_GRID = "#D4D4D8"
C_TEXT = "#27272A"

TARGET_LABEL = {
    "rv": "下週的波動幅度",
    "gap": "下週的跳空缺口",
    "corwin_schultz": "下週的買賣價差",
    "national_attention": "下週的全國搜尋熱度",
}

ALPHA = 0.05


def load() -> dict:
    return json.loads(RESULTS.read_text())


def fig_multiplicity(data: dict) -> Path:
    raw = data["multiple_testing"]["raw_one_sided_cw_p"]
    oos = data["retrospective_pseudo_oos_results"]

    targets = list(TARGET_LABEL)
    labels = [TARGET_LABEL[t] for t in targets]
    p_raw = [raw[t] for t in targets]
    p_adj = [oos[t]["pooled_by_week"]["clark_west"]["holm_p"] for t in targets]

    y = range(len(targets))
    h = 0.34
    fig, ax = plt.subplots(figsize=(9.6, 5.0), dpi=160)
    ax.axvspan(0, ALPHA, color=C_BAND, zorder=0)
    ax.barh([i + h / 2 for i in y], p_raw, height=h, color=C_RAW,
            label="單獨看這一個目標", zorder=2)
    ax.barh([i - h / 2 for i in y], p_adj, height=h, color=C_ADJ,
            label="把四個目標一起算進去", zorder=2)

    for i, (a, b) in enumerate(zip(p_raw, p_adj)):
        ax.text(a + 0.012, i + h / 2, f"{a:.3f}", va="center", fontsize=9,
                color=C_RAW)
        ax.text(b + 0.012, i - h / 2, f"{b:.3f}", va="center", fontsize=9,
                color=C_ADJ)

    ax.text(ALPHA + 0.01, len(targets) - 0.45, "灰帶 = 一般會說「像有東西」的範圍",
            fontsize=9.5, color=C_TEXT, va="center")
    ax.set_yticks(list(y))
    ax.set_yticklabels(labels, fontsize=10.5)
    ax.set_xlim(0, 1.06)
    ax.set_xlabel("數字越小代表越像有東西（越靠左越可疑）", fontsize=10)
    ax.set_title("唯一鑽進灰帶的那個，一做多重比較校正就退出來了",
                 fontsize=13.5, pad=14, weight="bold")
    ax.legend(loc="lower right", frameon=False, fontsize=9.5)
    ax.grid(axis="x", color=C_GRID, lw=0.7)
    ax.set_axisbelow(True)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    fig.tight_layout()

    out = ASSETS / "k1680_general_multiplicity.png"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out


def fig_per_firm(data: dict) -> Path:
    per_firm = data["retrospective_pseudo_oos_results"]["rv"]["per_firm"]
    firms = list(per_firm)
    vals = [per_firm[f]["mse_improvement_pct"] for f in firms]

    fig, ax = plt.subplots(figsize=(9.2, 4.8), dpi=160)
    colors = [C_POS if v > 0 else C_NEG for v in vals]
    bars = ax.bar(firms, vals, width=0.52, color=colors)
    ax.axhline(0, color=C_TEXT, lw=1.3)

    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2,
                v + (0.06 if v >= 0 else -0.06), f"{v:+.2f}%",
                ha="center", va="bottom" if v >= 0 else "top",
                fontsize=10, weight="bold", color=colors[bars.index(b)])

    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * 0.28
    ax.set_ylim(lo - pad, hi + pad)
    ax.set_ylabel("加進搜尋熱度後，預測準確度的變化", fontsize=10)
    ax.set_title("六檔股票，有的變好有的變差——真的效果不長這樣",
                 fontsize=13.5, pad=14, weight="bold")
    ax.grid(axis="y", color=C_GRID, lw=0.7)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    fig.tight_layout()

    out = ASSETS / "k1680_general_per_firm.png"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    data = load()
    for p in (fig_multiplicity(data), fig_per_firm(data)):
        print(f"wrote {p.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
