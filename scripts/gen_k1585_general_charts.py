"""Charts for the K1585 general-audience article.

Both figures read straight from experiments/k1585/k1585_results.json so the
prose and the plots cannot drift apart.

  1. k1585_general_effect_forest.png -- the four regime contrasts expressed in
     units of their own uncertainty. The four metrics live on wildly different
     scales (a variance, a probability, a drawdown), so plotting the raw
     differences side by side would be meaningless; dividing each by its own
     standard error puts them on one comparable axis and makes the shared
     conclusion -- every one of them sits inside the noise band -- readable at
     a glance.
  2. k1585_general_oos_cost.png -- what adding the survey signal does to
     out-of-sample forecast accuracy at each horizon.
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
RESULTS = ROOT / "experiments" / "k1585" / "k1585_results.json"
ASSETS = ROOT / "storage" / "assets"

C_NULL = "#52525B"
C_BAND = "#E4E4E7"
C_WORSE = "#B45309"
C_BETTER = "#0F766E"
C_GRID = "#D4D4D8"
C_TEXT = "#27272A"

# Reader-facing names for the four forward-looking outcomes that were tested.
METRICS = [
    ("fwd_rv5", "未來一週的波動"),
    ("fwd_rv21", "未來一個月的波動"),
    ("tail_event21", "未來一個月出現急殺的機率"),
    ("fwd_drawdown21", "未來一個月的最大跌幅"),
]

Z95 = 1.959963984540054


def load() -> dict:
    return json.loads(RESULTS.read_text())


def fig_effect_forest(data: dict) -> Path:
    tests = data["agreed_vs_disagreed_tests"]
    rows = []
    for key, label in METRICS:
        t = tests[key]
        diff = t["observed_diff_agreed_minus_disagreed"]
        se = (t["ci95_high"] - t["ci95_low"]) / (2 * Z95)
        rows.append((label, diff / se))

    labels = [r[0] for r in rows]
    zs = [r[1] for r in rows]
    y = list(range(len(rows)))

    fig, ax = plt.subplots(figsize=(9.5, 4.8), dpi=160)
    ax.axvspan(-Z95, Z95, color=C_BAND, zorder=0)
    ax.axvline(0, color=C_TEXT, lw=1.3, zorder=2)

    ax.errorbar(zs, y, xerr=Z95, fmt="o", color=C_NULL, ecolor=C_NULL,
                elinewidth=2.0, capsize=5, markersize=8, zorder=3)

    for i, z in enumerate(zs):
        ax.text(z, i + 0.22, f"{z:+.2f}", ha="center", fontsize=9,
                color=C_TEXT)

    ax.text(0, len(rows) - 0.42, "  灰帶內 = 和「什麼都沒有」分不開",
            fontsize=9.5, color=C_TEXT, va="center")

    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=10.5)
    ax.set_ylim(-0.7, len(rows) - 0.15)
    ax.set_xlim(-4.2, 4.2)
    ax.set_xlabel("效果大小 ÷ 自己的誤差範圍（往右 = 專家一致時波動較大）",
                  fontsize=10)
    ax.set_title("四個指標全部落在雜訊帶裡，沒有一個站得住",
                 fontsize=13.5, pad=14, weight="bold")
    ax.grid(axis="x", color=C_GRID, lw=0.7)
    ax.set_axisbelow(True)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    fig.tight_layout()

    out = ASSETS / "k1585_general_effect_forest.png"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out


def fig_oos_cost(data: dict) -> Path:
    oos = data["oos_forecast"]
    labels = ["預測未來一週", "預測未來一個月"]
    vals = [oos["h5"]["qlike_improvement_pct_augmented_vs_baseline"],
            oos["h21"]["qlike_improvement_pct_augmented_vs_baseline"]]

    fig, ax = plt.subplots(figsize=(8.6, 4.6), dpi=160)
    colors = [C_BETTER if v > 0 else C_WORSE for v in vals]
    bars = ax.bar(labels, vals, width=0.5, color=colors)
    ax.axhline(0, color=C_TEXT, lw=1.3)

    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v - 0.22, f"{v:+.2f}%",
                ha="center", va="top", fontsize=12, weight="bold",
                color=C_WORSE)

    ax.set_ylabel("加進專家分歧後，預測準確度的變化", fontsize=10)
    ax.set_ylim(min(vals) - 1.4, 1.0)
    ax.set_title("把專家分歧加進模型，兩個時間尺度上預測都變差",
                 fontsize=13.5, pad=14, weight="bold")
    ax.grid(axis="y", color=C_GRID, lw=0.7)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    fig.tight_layout()

    out = ASSETS / "k1585_general_oos_cost.png"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    data = load()
    for p in (fig_effect_forest(data), fig_oos_cost(data)):
        print(f"wrote {p.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
