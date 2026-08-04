"""Charts for the K1325 general-audience article.

Every number is read from experiments/k1325/k1325_results.json. Only labels
and layout are hard-coded.

  1. k1325_general_scores.png -- the three test-window scorecards (forecast
     error under QLIKE, squared error, and share-of-variance-explained).
     HAR wins all three, but the third panel carries a zero line that both
     models sit below: beating the rival is not the same as beating a
     constant.
  2. k1325_general_power.png -- how the head-to-head test statistic would
     grow with the length of the test window, if the per-day edge stayed
     exactly what we measured. Marks today's 18 days, the project's own
     revisit gate at 50 days, and the ~208 days the Harvey |t|>3 bar would
     actually need.

Palette validated with the dataviz skill's validate_palette.js
("#1D4ED8,#B45309,#15803D", light surface: all checks pass). Every mark
carries a direct value label, so no judgement depends on hue alone.
"""

from __future__ import annotations

import json
import math
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
RESULTS = ROOT / "experiments" / "k1325" / "k1325_results.json"
ASSETS = ROOT / "storage" / "drafts" / "assets"

C_HAR = "#1D4ED8"
C_RW = "#B45309"
C_GATE = "#15803D"
C_GRID = "#D4D4D8"
C_TEXT = "#27272A"
C_MUTED = "#71717A"
C_SURFACE = "#FCFCFB"

HARVEY_BAR = 3.0


def load() -> dict:
    return json.loads(RESULTS.read_text())


def _frame(ax) -> None:
    ax.set_facecolor(C_SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(C_GRID)
    ax.tick_params(colors=C_MUTED, labelsize=10)


def fig_scores(data: dict) -> Path:
    res = data["results"]
    n_test = data["sample"]["n_test"]

    panels = [
        (
            "預測誤差分數（QLIKE）",
            res["HAR_QLIKE_test"],
            res["RW_QLIKE_test"],
            "越低越準",
            False,
        ),
        (
            "平方誤差（MSE）",
            res["HAR_MSE_test"],
            res["RW_MSE_test"],
            "越低越準",
            False,
        ),
        (
            "解釋掉的變異比例（OOS R²）",
            res["HAR_OOS_R2"],
            res["RW_OOS_R2"],
            "低於 0 = 輸給「猜平均值」",
            True,
        ),
    ]

    fig, axes = plt.subplots(1, 3, figsize=(12.4, 5.4), dpi=160)
    fig.patch.set_facecolor(C_SURFACE)

    for ax, (title, har_v, rw_v, note, zero_line) in zip(axes, panels):
        _frame(ax)
        bars = ax.bar(
            [0, 1],
            [har_v, rw_v],
            width=0.56,
            color=[C_HAR, C_RW],
            zorder=3,
        )
        ax.set_xticks([0, 1])
        ax.set_xticklabels(["HAR 模型", "昨天照抄"], fontsize=11, color=C_TEXT)
        ax.set_title(title, fontsize=12.5, color=C_TEXT, pad=14)
        ax.grid(axis="y", color=C_GRID, linewidth=0.7, zorder=0)
        ax.set_axisbelow(True)

        lo = min(0.0, har_v, rw_v)
        hi = max(0.0, har_v, rw_v)
        span = hi - lo
        ax.set_ylim(lo - span * 0.22, hi + span * 0.26)

        if zero_line:
            ax.axhline(0.0, color=C_TEXT, linewidth=1.2, zorder=4)

        for bar, val in zip(bars, [har_v, rw_v]):
            up = val >= 0
            ax.annotate(
                f"{val:.3f}",
                (bar.get_x() + bar.get_width() / 2, val),
                textcoords="offset points",
                xytext=(0, 7 if up else -17),
                ha="center",
                fontsize=12,
                color=C_TEXT,
                fontweight="bold",
            )

        ax.annotate(
            note,
            (0.5, -0.155),
            xycoords="axes fraction",
            ha="center",
            fontsize=10,
            color=C_MUTED,
        )

    fig.suptitle(
        f"0050 五分鐘資料：HAR 模型三項全勝，但第三項兩個都在零以下（樣本外 {n_test} 天）",
        fontsize=14,
        color=C_TEXT,
        y=0.97,
    )
    fig.tight_layout(rect=(0, 0.03, 1, 0.93))

    out = ASSETS / "k1325_general_scores.png"
    fig.savefig(out, facecolor=C_SURFACE)
    plt.close(fig)
    return out


def fig_power(data: dict) -> Path:
    res = data["results"]
    sample = data["sample"]
    gate = data["revisit_gate"]

    t_obs = res["DM_HLN_t"]
    n_obs = sample["n_test"]
    n_gate = gate["n_test_days_required"]
    n_needed = n_obs * (HARVEY_BAR / t_obs) ** 2

    xs = [n_obs + i * 2 for i in range(0, int((260 - n_obs) / 2) + 1)]
    ys = [t_obs * math.sqrt(x / n_obs) for x in xs]

    fig, ax = plt.subplots(figsize=(11.2, 5.9), dpi=160)
    fig.patch.set_facecolor(C_SURFACE)
    _frame(ax)

    ax.grid(color=C_GRID, linewidth=0.7, zorder=0)
    ax.set_axisbelow(True)
    ax.plot(xs, ys, color=C_HAR, linewidth=2.4, zorder=3)

    ax.axhline(HARVEY_BAR, color=C_RW, linewidth=1.8, linestyle="--", zorder=2)
    ax.annotate(
        f"我們的及格線 |t| > {HARVEY_BAR:.0f}（Harvey 標準）",
        (xs[-1], HARVEY_BAR),
        textcoords="offset points",
        xytext=(-6, 9),
        ha="right",
        fontsize=11,
        color=C_RW,
        fontweight="bold",
    )

    marks = [
        (n_obs, t_obs, f"現在\n{n_obs} 天，t={t_obs:.2f}", C_HAR, (12, -6)),
        (
            n_gate,
            t_obs * math.sqrt(n_gate / n_obs),
            f"自訂的重啟門檻\n{n_gate} 天，推估 t≈{t_obs * math.sqrt(n_gate / n_obs):.2f}",
            C_GATE,
            (14, -4),
        ),
        (
            n_needed,
            HARVEY_BAR,
            f"真正要過關\n約 {n_needed:.0f} 天",
            C_RW,
            (-18, -46),
        ),
    ]
    for x, y, label, color, off in marks:
        ax.scatter([x], [y], s=90, color=color, zorder=5, edgecolor=C_SURFACE, linewidth=1.6)
        ax.annotate(
            label,
            (x, y),
            textcoords="offset points",
            xytext=off,
            fontsize=11,
            color=color,
            fontweight="bold",
        )

    ax.set_xlim(0, 265)
    ax.set_ylim(0, 3.7)
    ax.set_xlabel("樣本外測試天數", fontsize=11.5, color=C_TEXT, labelpad=9)
    ax.set_ylabel("勝負的統計強度 |t|", fontsize=11.5, color=C_TEXT, labelpad=9)
    ax.set_title(
        "若每天的差距維持現在這麼大，測試窗要拉到約 208 天才碰得到及格線",
        fontsize=13.5,
        color=C_TEXT,
        pad=16,
    )
    ax.annotate(
        "曲線是把現有的每日差距等比例外推（t 隨天數開根號成長），是估算不是保證",
        (0.5, -0.165),
        xycoords="axes fraction",
        ha="center",
        fontsize=10,
        color=C_MUTED,
    )

    fig.tight_layout(rect=(0, 0.04, 1, 1))
    out = ASSETS / "k1325_general_power.png"
    fig.savefig(out, facecolor=C_SURFACE)
    plt.close(fig)
    return out


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    data = load()
    for path in (fig_scores(data), fig_power(data)):
        print(f"wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
