"""Charts for the K1478 general-audience article.

Every number is read from experiments/k1478/k1478_results.json at run time.
Only labels, colours and layout are written here.

  1. k1478_general_dose.png -- last-hour movement by leverage-pressure quartile.
     This is the figure that makes the claim look true: both last-hour measures
     climb monotonically from the calmest quartile to the busiest one. It is
     shown first precisely because it is the misleading one.
  2. k1478_general_control.png -- the same three questions asked twice. Left of
     each pair is the raw quartile comparison (Welch t); right is the pressure
     coefficient once the day's own absolute move is in the regression (HAC t).
     The two last-hour effects collapse to nothing; the overnight one appears
     only after the control, which is why it is reported as a weaker secondary
     signal rather than a finding.

Palette: #B45309 (raw / uncontrolled), #1D4ED8 (after controlling for the day's
own move), #71717A (the |t| = 1.96 significance reference). Every bar carries a
direct value label, so the figures do not rely on colour discrimination alone.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

plt.rcParams["font.sans-serif"] = [
    "PingFang TC",
    "PingFang HK",
    "Heiti TC",
    "Arial Unicode MS",
]
plt.rcParams["axes.unicode_minus"] = False

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "experiments" / "k1478" / "k1478_results.json"
ASSETS = ROOT / "storage" / "drafts" / "assets"

C_RAW = "#B45309"
C_CTRL = "#1D4ED8"
C_REF = "#71717A"

OUTCOME_LABEL = {
    "same_sign_last_hour": "最後一小時的順勢推進",
    "last_hour_range_var": "最後一小時的振幅",
    "overnight_cont": "隔夜延續",
}


def load() -> dict:
    return json.loads(RESULTS.read_text(encoding="utf-8"))


def chart_dose(d: dict) -> Path:
    """The monotone quartile pattern that makes the story look convincing."""
    buckets = d["pressure_bucket_means"]
    names = [b["pressure_bucket"] for b in buckets]
    var = [b["last_hour_range_var"] * 1e6 for b in buckets]
    same = [b["same_sign_last_hour"] * 1e4 for b in buckets]

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.6))

    for ax, vals, title, unit in (
        (axes[0], var, "最後一小時的振幅", "百萬分之一"),
        (axes[1], same, "最後一小時的順勢推進", "萬分之一"),
    ):
        colours = [C_RAW if n == "Q4" else C_REF for n in names]
        bars = ax.bar(names, vals, color=colours, width=0.62)
        for b, v in zip(bars, vals):
            ax.text(
                b.get_x() + b.get_width() / 2,
                v + max(vals) * 0.03,
                f"{v:.2f}",
                ha="center",
                va="bottom",
                fontsize=10,
            )
        ax.set_title(title, fontsize=12)
        ax.set_ylabel(f"平均值（{unit}）", fontsize=10)
        ax.set_xlabel("再平衡壓力由低到高的四等分", fontsize=10)
        ax.set_ylim(0, max(vals) * 1.22)
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(axis="y", alpha=0.25)

    ratio_var = var[3] / var[0]
    ratio_same = same[3] / same[0]
    fig.suptitle(
        "壓力最大的那四分之一交易日，尾盤確實比最平靜的那批更會動"
        f"（振幅 {ratio_var:.1f} 倍、順勢推進 {ratio_same:.1f} 倍）",
        fontsize=12.5,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    out = ASSETS / "k1478_general_dose.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out


def chart_control(d: dict) -> Path:
    """Same three questions, before and after controlling for the day's own move."""
    outcomes = d["methodology"]["primary_outcomes"]
    raw_t = [abs(d["top_quartile_tests"][o]["welch_t"]) for o in outcomes]
    ctrl_t = [abs(d["hac_regressions"][o]["t_log_pressure"]) for o in outcomes]
    labels = [OUTCOME_LABEL[o] for o in outcomes]

    x = np.arange(len(outcomes))
    width = 0.36

    fig, ax = plt.subplots(figsize=(10.5, 5.0))
    b1 = ax.bar(x - width / 2, raw_t, width, label="只看壓力高低（未控制）", color=C_RAW)
    b2 = ax.bar(
        x + width / 2, ctrl_t, width, label="把當天漲跌幅一起放進去之後", color=C_CTRL
    )

    for bars, vals in ((b1, raw_t), (b2, ctrl_t)):
        for b, v in zip(bars, vals):
            ax.text(
                b.get_x() + b.get_width() / 2,
                v + 0.12,
                f"{v:.2f}",
                ha="center",
                va="bottom",
                fontsize=10,
            )

    ax.axhline(1.96, color=C_REF, linestyle="--", linewidth=1.2)
    ax.set_xlim(-1.05, len(outcomes) - 0.45)
    ax.text(
        -1.0,
        1.96 + 0.16,
        "這條線以上\n才算站得住",
        color=C_REF,
        fontsize=9.5,
        ha="left",
        va="bottom",
        linespacing=1.35,
    )

    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=11)
    ax.set_ylabel("證據強度", fontsize=11)
    ax.set_ylim(0, max(max(raw_t), max(ctrl_t)) * 1.28)
    ax.legend(frameon=False, fontsize=10, loc="upper right")
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=0.25)
    ax.set_title(
        "把「當天本來就漲跌多少」放進去之後，兩個尾盤效果直接垮掉",
        fontsize=13,
        pad=14,
    )

    fig.tight_layout()
    out = ASSETS / "k1478_general_control.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    d = load()
    for path in (chart_dose(d), chart_control(d)):
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
