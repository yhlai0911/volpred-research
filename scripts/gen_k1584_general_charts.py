"""Charts for the K1584 general-audience article.

Every number is read from experiments/k1584/k1584_results.json at run time.
Only labels, colours and layout are written here.

  1. k1584_general_ladder.png -- next-day forecast error for the plain baseline
     and the four progressively more decomposed variants. The point of the
     figure is that the error rises at every single step: the more finely the
     same data is split into calm-part and jump-part, the worse tomorrow's
     forecast gets. Lower is better, so this is a descending-quality ladder.
  2. k1584_general_jumps.png -- why that is surprising. Jumps are not rare
     (they appear on well over half of all trading days) but they are small
     (the median jump day carries only a few percent of that day's variance).
     A component that common is exactly the kind of thing people expect to be
     worth modelling separately.

Palette: #1D4ED8 (the plain baseline), #B45309 (each decomposed variant),
#71717A (reference / secondary). Every bar carries a direct value label, so the
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
RESULTS = ROOT / "experiments" / "k1584" / "k1584_results.json"
ASSETS = ROOT / "storage" / "drafts" / "assets"

C_BASE = "#1D4ED8"
C_SPLIT = "#B45309"
C_REF = "#71717A"

#: Reader-facing names for each specification, in the order they add structure.
MODEL_ORDER = [
    ("HAR", "完全不拆\n（基準）"),
    ("HAR_C", "只留平穩的\n那一部分"),
    ("HAR_RVJ", "拆成平穩\n＋跳動"),
    ("HAR_CJ", "兩部分各自\n分短中長期"),
    ("HAR_CJ_cluster", "再加上\n跳動會群聚"),
]


def load() -> dict:
    return json.loads(RESULTS.read_text(encoding="utf-8"))


def chart_ladder(d: dict) -> Path:
    t = d["tx_harcj_test"]
    models = t["models"]
    keys = [k for k, _ in MODEL_ORDER]
    labels = [lab for _, lab in MODEL_ORDER]
    vals = [models[k]["mean_qlike"] for k in keys]
    colours = [C_BASE] + [C_SPLIT] * (len(keys) - 1)

    fig, ax = plt.subplots(figsize=(10.6, 5.2))
    bars = ax.bar(labels, vals, color=colours, width=0.6)
    for b, v in zip(bars, vals):
        ax.text(
            b.get_x() + b.get_width() / 2,
            v + (max(vals) - min(vals)) * 0.06,
            f"{v:.5f}",
            ha="center",
            va="bottom",
            fontsize=10.5,
        )

    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * 0.55
    ax.set_ylim(lo - pad, hi + pad)
    ax.axhline(vals[0], color=C_REF, linestyle="--", linewidth=1.2)
    ax.text(
        len(keys) - 0.45,
        vals[0] - (hi - lo) * 0.16,
        "基準線",
        color=C_REF,
        fontsize=9.5,
        ha="right",
    )

    worst_pct = abs(
        t["pairwise_vs_har"]["HAR_CJ_cluster"]["qlike_improvement_pct"]
    )
    ax.set_ylabel("隔日預測誤差（數字越低越好）", fontsize=11)
    ax.set_title(
        "每多拆一層，隔天的預測就差一點，五個等級沒有一次反轉"
        f"（拆到最細比完全不拆差 {worst_pct:.2f}%）",
        fontsize=12.5,
        pad=14,
    )
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=0.25)
    ax.tick_params(axis="x", labelsize=10)
    # The gap is real and never reverses, but it is under one percent. Say so
    # on the figure rather than let a zoomed axis imply a chasm.
    ax.text(
        0.0,
        -0.235,
        f"注意：縱軸已放大以看出順序，最大與最小的實際差距只有 {worst_pct:.2f}%，"
        "而且統計上並未達到顯著",
        transform=ax.transAxes,
        fontsize=9.5,
        color=C_REF,
        ha="left",
    )

    fig.tight_layout()
    out = ASSETS / "k1584_general_ladder.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out


def chart_jumps(d: dict) -> Path:
    t = d["tx_harcj_test"]
    jd = t["jump_detection"]
    rate = jd["jump_event_rate"] * 100
    mean_share = jd["mean_jump_variance_share"] * 100
    median_share = jd["median_jump_variance_share"] * 100

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))

    ax = axes[0]
    bars = ax.bar(
        ["有跳動的日子", "沒有跳動的日子"],
        [rate, 100 - rate],
        color=[C_SPLIT, C_REF],
        width=0.58,
    )
    for b, v in zip(bars, [rate, 100 - rate]):
        ax.text(
            b.get_x() + b.get_width() / 2,
            v + 2,
            f"{v:.1f}%",
            ha="center",
            va="bottom",
            fontsize=11,
        )
    ax.set_ylim(0, 100)
    ax.set_ylabel("佔全部交易日的比例", fontsize=10.5)
    ax.set_title("跳動一點都不罕見", fontsize=12)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=0.25)

    ax = axes[1]
    bars = ax.bar(
        ["一半的日子\n低於這個數", "平均"],
        [median_share, mean_share],
        color=[C_SPLIT, C_REF],
        width=0.5,
    )
    for b, v in zip(bars, [median_share, mean_share]):
        ax.text(
            b.get_x() + b.get_width() / 2,
            v + 0.2,
            f"{v:.2f}%",
            ha="center",
            va="bottom",
            fontsize=11,
        )
    ax.set_ylim(0, max(mean_share, median_share) * 1.45)
    ax.set_ylabel("跳動佔當天總變動的比例", fontsize=10.5)
    ax.set_title("但每次都只佔一小塊", fontsize=12)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=0.25)

    fig.suptitle(
        "常見、但每次都很小，這正是最容易讓人以為「值得單獨處理」的組合",
        fontsize=12.5,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    out = ASSETS / "k1584_general_jumps.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    d = load()
    for path in (chart_ladder(d), chart_jumps(d)):
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
