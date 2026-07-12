#!/usr/bin/env python3
"""Render the four K1700 data-bound lazypack panels.

Every displayed statistic is loaded from k1700_results.json.  README.md and the
article draft are also loaded and checked so a mismatched evidence package fails
loudly instead of producing plausible-looking but unrelated graphics.
"""

from __future__ import annotations

import json
import math
import os
import re
import textwrap
from datetime import date
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle


RESULTS_PATH = "/Users/yhlai0911/volpred-research/experiments/k1700/k1700_results.json"
README_PATH = "/Users/yhlai0911/volpred-research/experiments/k1700/README.md"
ARTICLE_PATH = (
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_d84aa7d0/panels/mile_d84aa7d0_article.md"
)
out_dir = "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_d84aa7d0/panels"

WIDTH_PX = 1600
HEIGHT_PX = 1000
DPI = 150

NAVY = "#0B2239"
INK = "#17324D"
MUTED = "#5C7184"
BLUE = "#176B87"
TEAL = "#2A9D8F"
RED = "#C84C4C"
AMBER = "#E6A23C"
PALE_BLUE = "#EAF4F8"
PALE_TEAL = "#EAF7F4"
PALE_RED = "#FBEDEE"
PALE_AMBER = "#FFF5E3"
PANEL_BG = "#F5F8FA"
LINE = "#D8E2EA"
WHITE = "#FFFFFF"

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["figure.facecolor"] = WHITE
plt.rcParams["savefig.facecolor"] = WHITE


def require_path(root: Any, *path: Any) -> Any:
    """Return a nested value and raise a descriptive error on any missing step."""
    current = root
    traversed: list[str] = []
    for key in path:
        traversed.append(str(key))
        if isinstance(key, int):
            if not isinstance(current, list):
                raise TypeError(f"Expected list at {'.'.join(traversed[:-1])}")
            if key < 0 or key >= len(current):
                raise KeyError(f"Missing list index {'.'.join(traversed)}")
            current = current[key]
        else:
            if not isinstance(current, dict):
                raise TypeError(f"Expected object at {'.'.join(traversed[:-1])}")
            if key not in current:
                raise KeyError(f"Missing evidence field: {'.'.join(traversed)}")
            current = current[key]
    return current


def require_number(root: Any, *path: Any) -> float:
    value = require_path(root, *path)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"Evidence field {'.'.join(map(str, path))} must be numeric")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"Evidence field {'.'.join(map(str, path))} is not finite")
    return value


def require_int(root: Any, *path: Any) -> int:
    value = require_number(root, *path)
    if not value.is_integer():
        raise ValueError(f"Evidence field {'.'.join(map(str, path))} must be an integer")
    return int(value)


def require_text(root: Any, *path: Any) -> str:
    value = require_path(root, *path)
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"Evidence field {'.'.join(map(str, path))} must be non-empty text")
    return value.strip()


def read_nonempty_text(path: str, label: str) -> str:
    with open(path, "r", encoding="utf-8") as handle:
        text = handle.read()
    if not text.strip():
        raise ValueError(f"{label} is empty: {path}")
    return text


def load_evidence() -> dict[str, Any]:
    with open(RESULTS_PATH, "r", encoding="utf-8") as handle:
        results = json.load(handle)
    if not isinstance(results, dict):
        raise TypeError("k1700_results.json must contain a JSON object")

    readme = read_nonempty_text(README_PATH, "README evidence")
    article = read_nonempty_text(ARTICLE_PATH, "article evidence")
    experiment_id = require_text(results, "experiment_id")
    if experiment_id not in readme:
        raise ValueError(f"README does not identify experiment {experiment_id}")
    if experiment_id not in article:
        raise ValueError(f"Article does not identify experiment {experiment_id}")

    # These sources are part of the evidence contract for the leverage panel.
    require_text(results, "data_sources", "prices")
    require_text(results, "data_sources", "dividends")
    require_text(results, "data_sources", "financing")
    return results


def leverage_row(
    results: dict[str, Any], leverage: float, financing: str | None = None
) -> dict[str, Any]:
    rows = require_path(results, "leverage_30y")
    if not isinstance(rows, list):
        raise TypeError("leverage_30y must be a list")
    matches: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise TypeError("Every leverage_30y entry must be an object")
        row_leverage = require_number(row, "leverage")
        row_financing = require_text(row, "financing")
        if math.isclose(row_leverage, leverage, rel_tol=0.0, abs_tol=1e-12):
            if financing is None or row_financing == financing:
                matches.append(row)
    if len(matches) != 1:
        detail = f"leverage={leverage:g}"
        if financing is not None:
            detail += f", financing={financing!r}"
        raise KeyError(f"Expected exactly one leverage row for {detail}; found {len(matches)}")
    row = matches[0]
    require_number(row, "cagr_median")
    require_number(row, "share_ge_target")
    require_number(row, "mdd_median")
    return row


def find_single_caveat(results: dict[str, Any], *terms: str) -> str:
    caveats = require_path(results, "caveats")
    if not isinstance(caveats, list) or not all(isinstance(item, str) for item in caveats):
        raise TypeError("caveats must be a list of strings")
    matches = [item for item in caveats if all(term in item for term in terms)]
    if len(matches) != 1:
        raise KeyError(f"Expected exactly one caveat containing {terms}; found {len(matches)}")
    return matches[0]


def threshold_from_field(field_name: str) -> int:
    match = re.search(r"_(\d+)pct$", field_name)
    if not match:
        raise ValueError(f"Cannot recover percentage threshold from field name: {field_name}")
    return int(match.group(1))


def year_month(iso_date: str) -> str:
    date.fromisoformat(iso_date)
    return iso_date[:7]


def year_only(iso_date: str) -> str:
    date.fromisoformat(iso_date)
    return iso_date[:4]


def pct(value: float, decimals: int = 1) -> str:
    return f"{value * 100:.{decimals}f}%"


def pct_share(value: float) -> str:
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"Share outside [0, 1]: {value}")
    if math.isclose(value, 0.0, rel_tol=0.0, abs_tol=1e-12):
        return "0%"
    if math.isclose(value, 1.0, rel_tol=0.0, abs_tol=1e-12):
        return "100%"
    return pct(value, 1)


def multiple(value: float) -> str:
    return f"{value:.1f} 倍"


def leverage_label(value: float) -> str:
    return f"{value:g}x"


def wrap_zh(text: str, width: int) -> str:
    return "\n".join(
        textwrap.wrap(
            text,
            width=width,
            break_long_words=True,
            break_on_hyphens=False,
            replace_whitespace=False,
        )
    )


def new_canvas() -> tuple[plt.Figure, plt.Axes]:
    fig = plt.figure(figsize=(WIDTH_PX / DPI, HEIGHT_PX / DPI), dpi=DPI)
    ax = fig.add_axes([0.0, 0.0, 1.0, 1.0])
    ax.set_xlim(0.0, 1.0)
    ax.set_ylim(0.0, 1.0)
    ax.axis("off")
    return fig, ax


def add_text(
    ax: plt.Axes,
    x: float,
    y: float,
    text: str,
    *,
    size: float,
    color: str = INK,
    weight: str = "normal",
    ha: str = "left",
    va: str = "center",
    linespacing: float = 1.22,
    rotation: float = 0.0,
    zorder: int = 5,
) -> None:
    ax.text(
        x,
        y,
        text,
        transform=ax.transAxes,
        fontsize=size,
        color=color,
        fontweight=weight,
        ha=ha,
        va=va,
        linespacing=linespacing,
        rotation=rotation,
        clip_on=True,
        zorder=zorder,
    )


def rounded_card(
    ax: plt.Axes,
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    facecolor: str = PANEL_BG,
    edgecolor: str = LINE,
    linewidth: float = 1.0,
    radius: float = 0.018,
) -> None:
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            width,
            height,
            boxstyle=f"round,pad=0.008,rounding_size={radius}",
            transform=ax.transAxes,
            facecolor=facecolor,
            edgecolor=edgecolor,
            linewidth=linewidth,
            zorder=1,
        )
    )


def draw_header(ax: plt.Axes, title: str, subtitle: str) -> None:
    ax.add_patch(
        Rectangle(
            (0.0, 0.855),
            1.0,
            0.145,
            transform=ax.transAxes,
            facecolor=NAVY,
            edgecolor="none",
            zorder=0,
        )
    )
    add_text(ax, 0.055, 0.945, title, size=27, color=WHITE, weight="bold")
    add_text(ax, 0.055, 0.885, subtitle, size=12.5, color="#C8D7E3")


def draw_footer(ax: plt.Axes, experiment_id: str) -> None:
    ax.plot([0.055, 0.945], [0.066, 0.066], color=LINE, linewidth=0.9, transform=ax.transAxes)
    add_text(
        ax,
        0.055,
        0.035,
        f"資料來源：experiment {experiment_id}",
        size=9.5,
        color=MUTED,
    )


def save_panel(fig: plt.Figure, filename: str) -> None:
    fig.savefig(
        os.path.join(out_dir, filename),
        dpi=DPI,
        facecolor=WHITE,
        edgecolor="none",
    )
    plt.close(fig)


def render_target(results: dict[str, Any]) -> None:
    experiment_id = require_text(results, "experiment_id")
    target = require_number(results, "target_cagr")
    window_years = require_int(results, "window_years")
    target_multiple = require_number(results, "target_multiple_30y")

    spx = require_path(results, "spx_total_return_30y")
    n_windows = require_int(spx, "n_windows")
    n_ge_target = require_int(spx, "n_ge_target")
    cagr_median = require_number(spx, "cagr_median")
    cagr_max = require_number(spx, "cagr_max")
    max_start = year_month(require_text(spx, "cagr_max_start"))
    first_year = year_only(require_text(spx, "first_start"))
    last_year = year_only(require_text(spx, "last_end"))
    gap_pp = (target - cagr_max) * 100
    if gap_pp <= 0:
        raise ValueError("Target panel expects the historical maximum to remain below target")

    fig, ax = new_canvas()
    draw_header(
        ax,
        f"年化 {pct(target, 0)}：近百年沒有一個 {window_years} 年視窗做到",
        f"S&P 500 含息｜{first_year}–{last_year}｜每個交易日起算",
    )

    ax.plot(
        [0.07, 0.93],
        [0.795, 0.795],
        color=RED,
        linewidth=2.0,
        linestyle=(0, (5, 5)),
        transform=ax.transAxes,
        zorder=2,
    )
    ax.text(
        0.50,
        0.795,
        f"{pct(target, 0)} 門檻未被跨過",
        transform=ax.transAxes,
        fontsize=13,
        color=RED,
        fontweight="bold",
        ha="center",
        va="center",
        bbox={"facecolor": WHITE, "edgecolor": "none", "pad": 5.0},
        clip_on=True,
        zorder=3,
    )

    rounded_card(ax, 0.055, 0.335, 0.41, 0.39, facecolor=PALE_BLUE, edgecolor="#BBD9E5")
    rounded_card(ax, 0.535, 0.335, 0.41, 0.39, facecolor=PANEL_BG, edgecolor=LINE)

    add_text(ax, 0.26, 0.675, "會員目標", size=16, color=BLUE, weight="bold", ha="center")
    add_text(ax, 0.26, 0.555, pct(target, 0), size=61, color=BLUE, weight="bold", ha="center")
    add_text(
        ax,
        0.26,
        0.405,
        f"{window_years} 年後資產要變成 {multiple(target_multiple)}",
        size=18,
        color=INK,
        weight="bold",
        ha="center",
    )

    add_text(ax, 0.74, 0.675, "歷史最高", size=16, color=MUTED, weight="bold", ha="center")
    add_text(ax, 0.74, 0.555, pct(cagr_max, 2), size=54, color=INK, weight="bold", ha="center")
    add_text(ax, 0.74, 0.435, f"起點 {max_start}", size=17, color=INK, ha="center")
    add_text(
        ax,
        0.74,
        0.375,
        f"仍差 {gap_pp:.1f} 個百分點",
        size=15,
        color=RED,
        weight="bold",
        ha="center",
    )

    rounded_card(ax, 0.055, 0.105, 0.89, 0.145, facecolor=WHITE, edgecolor=LINE)
    kpis = [
        ("達標視窗", f"{n_ge_target:,} / {n_windows:,}"),
        ("年化中位數", pct(cagr_median, 2)),
        ("目標複利倍數", multiple(target_multiple)),
    ]
    for x, (label, value) in zip((0.20, 0.50, 0.80), kpis):
        add_text(ax, x, 0.212, label, size=11.5, color=MUTED, ha="center")
        add_text(ax, x, 0.153, value, size=22, color=INK, weight="bold", ha="center")

    draw_footer(ax, experiment_id)
    save_panel(fig, "1_target.png")


def render_stability(results: dict[str, Any]) -> None:
    experiment_id = require_text(results, "experiment_id")
    window_years = require_int(results, "window_years")
    spx = require_path(results, "spx_total_return_30y")
    best = require_path(results, "best_decile_windows")

    n_windows = require_int(spx, "n_windows")
    n_best = require_int(best, "n")
    if n_windows <= 0 or n_best <= 0:
        raise ValueError("Window counts must be positive")
    best_share = n_best / n_windows
    cagr_min = require_number(best, "cagr_min")
    cagr_max = require_number(best, "cagr_max")

    field_30 = "share_with_mdd_worse_than_30pct"
    field_40 = "share_with_mdd_worse_than_40pct"
    threshold_30 = threshold_from_field(field_30)
    threshold_40 = threshold_from_field(field_40)
    share_30 = require_number(best, field_30)
    share_40 = require_number(best, field_40)
    if not 0.0 <= share_30 <= 1.0 or not 0.0 <= share_40 <= 1.0:
        raise ValueError("MDD shares must lie in [0, 1]")
    shallowest = require_number(best, "mdd_shallowest")
    full_median = require_number(spx, "mdd_median")

    fig, ax = new_canvas()
    draw_header(
        ax,
        "高報酬和「穩定」無法同時出現",
        (
            f"報酬最高 {pct(best_share, 0)}：{n_best:,} 個 {window_years} 年視窗｜"
            f"年化 {pct(cagr_min, 2)}–{pct(cagr_max, 2)}"
        ),
    )

    bar_x = 0.075
    bar_w = 0.85
    bar_h = 0.064
    rows = [
        (0.715, 0.635, f"曾跌超過 {threshold_30}%", share_30, RED),
        (0.505, 0.425, f"曾跌超過 {threshold_40}%", share_40, AMBER),
    ]
    for label_y, bar_y, label, value, color in rows:
        add_text(ax, bar_x, label_y, label, size=17, color=INK, weight="bold")
        add_text(ax, 0.925, label_y, pct_share(value), size=30, color=color, weight="bold", ha="right")
        rounded_card(ax, bar_x, bar_y, bar_w, bar_h, facecolor="#E8EDF1", edgecolor="#E8EDF1", radius=0.012)
        rounded_card(
            ax,
            bar_x,
            bar_y,
            bar_w * value,
            bar_h,
            facecolor=color,
            edgecolor=color,
            radius=0.012,
        )

    rounded_card(ax, 0.06, 0.125, 0.415, 0.19, facecolor=PALE_RED, edgecolor="#F0C8CB")
    rounded_card(ax, 0.525, 0.125, 0.415, 0.19, facecolor=PANEL_BG, edgecolor=LINE)
    add_text(ax, 0.2675, 0.270, "最好的十分位中，回撤最淺的一個", size=12.5, color=MUTED, ha="center")
    add_text(ax, 0.2675, 0.190, pct(shallowest, 1), size=35, color=RED, weight="bold", ha="center")
    add_text(ax, 0.7325, 0.270, f"全體 {window_years} 年視窗 MDD 中位數", size=12.5, color=MUTED, ha="center")
    add_text(ax, 0.7325, 0.190, pct(full_median, 1), size=35, color=INK, weight="bold", ha="center")

    draw_footer(ax, experiment_id)
    save_panel(fig, "2_stability.png")


def render_leverage(results: dict[str, Any]) -> None:
    experiment_id = require_text(results, "experiment_id")
    target = require_number(results, "target_cagr")
    best = require_path(results, "best_decile_windows")
    right_axis_ceiling = require_number(best, "share_with_mdd_worse_than_30pct")
    if not math.isclose(right_axis_ceiling, 1.0, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError("The leverage chart expects a 100% evidence-bound MDD scale ceiling")

    base = leverage_row(results, 1.0)
    actual_financing = require_text(leverage_row(results, 2.0, "實際短率+1pp"), "financing")
    actual_rows = [
        base,
        leverage_row(results, 1.5, actual_financing),
        leverage_row(results, 2.0, actual_financing),
        leverage_row(results, 3.0, actual_financing),
    ]
    free_2x = leverage_row(results, 2.0, "免費借貸（理論上界）")
    free_3x = leverage_row(results, 3.0, "免費借貸（理論上界）")

    leverages = [require_number(row, "leverage") for row in actual_rows]
    cagr_values = [require_number(row, "cagr_median") for row in actual_rows]
    target_shares = [require_number(row, "share_ge_target") for row in actual_rows]
    mdd_values = [require_number(row, "mdd_median") for row in actual_rows]
    for value in target_shares:
        if not 0.0 <= value <= 1.0:
            raise ValueError("Leverage target shares must lie in [0, 1]")
    if any(value >= 0.0 for value in mdd_values):
        raise ValueError("MDD values must be negative")

    free_2x_cagr = require_number(free_2x, "cagr_median")
    free_3x_cagr = require_number(free_3x, "cagr_median")
    actual_2x_cagr = require_number(actual_rows[2], "cagr_median")
    actual_3x_cagr = require_number(actual_rows[3], "cagr_median")
    if actual_3x_cagr >= actual_2x_cagr:
        raise ValueError("Panel narrative requires actual-cost 3x CAGR to be below 2x")

    financing_mean = require_number(results, "financing_rate_context", "tb3ms_mean")
    financing_note = require_text(results, "financing_rate_context", "note")

    fig, ax = new_canvas()
    draw_header(
        ax,
        (
            f"借錢有成本：{leverage_label(leverages[3])} 報酬低於 "
            f"{leverage_label(leverages[2])}，回撤更深"
        ),
        f"借貸成本：FRED TB3MS｜{actual_financing}",
    )

    add_text(ax, 0.075, 0.785, "實際借貸成本下的取捨", size=16, color=INK, weight="bold")
    ax.add_patch(Rectangle((0.306, 0.765), 0.018, 0.018, transform=ax.transAxes, facecolor=BLUE, edgecolor="none"))
    add_text(ax, 0.331, 0.774, "年化中位數", size=10.5, color=MUTED)
    ax.add_patch(Rectangle((0.445, 0.765), 0.018, 0.018, transform=ax.transAxes, facecolor=RED, edgecolor="none"))
    add_text(ax, 0.470, 0.774, "MDD 深度", size=10.5, color=MUTED)

    chart = fig.add_axes([0.075, 0.305, 0.50, 0.405])
    chart.set_facecolor(WHITE)
    drawdown_axis = chart.twinx()
    x_positions = list(range(len(actual_rows)))
    width = 0.32
    cagr_bars = chart.bar(
        [x - width / 1.7 for x in x_positions],
        cagr_values,
        width=width,
        color=BLUE,
        edgecolor="none",
        zorder=3,
    )
    mdd_bars = drawdown_axis.bar(
        [x + width / 1.7 for x in x_positions],
        [abs(value) for value in mdd_values],
        width=width,
        color=RED,
        alpha=0.82,
        edgecolor="none",
        zorder=2,
    )
    chart.set_ylim(0.0, target)
    drawdown_axis.set_ylim(0.0, right_axis_ceiling)
    chart.set_xlim(-0.55, len(actual_rows) - 0.45)
    chart.set_yticks([])
    drawdown_axis.set_yticks([])
    chart.set_xticks(x_positions)
    chart.set_xticklabels(
        [
            f"{leverage_label(lev)}\n達標 {pct_share(share)}"
            for lev, share in zip(leverages, target_shares)
        ],
        fontsize=10.5,
        color=INK,
    )
    chart.tick_params(axis="x", length=0, pad=10)
    chart.axhline(0.0, color=LINE, linewidth=1.0)
    for spine in chart.spines.values():
        spine.set_visible(False)
    for spine in drawdown_axis.spines.values():
        spine.set_visible(False)

    for bar, value in zip(cagr_bars, cagr_values):
        chart.text(
            bar.get_x() + bar.get_width() / 2,
            value + target * 0.018,
            pct(value, 2),
            ha="center",
            va="bottom",
            fontsize=9.5,
            color=BLUE,
            fontweight="bold",
            clip_on=True,
        )
    for bar, value in zip(mdd_bars, mdd_values):
        drawdown_axis.text(
            bar.get_x() + bar.get_width() / 2,
            abs(value) + right_axis_ceiling * 0.022,
            pct(value, 1),
            ha="center",
            va="bottom",
            fontsize=9.5,
            color=RED,
            fontweight="bold",
            clip_on=True,
        )

    rounded_card(ax, 0.65, 0.245, 0.30, 0.525, facecolor=PALE_AMBER, edgecolor="#EFD39E")
    free_label = require_text(free_2x, "financing")
    if require_text(free_3x, "financing") != free_label:
        raise ValueError("Free-financing labels disagree between 2x and 3x rows")
    add_text(ax, 0.80, 0.725, free_label, size=15, color=INK, weight="bold", ha="center")
    add_text(ax, 0.80, 0.682, "同一套每日再平衡算法", size=10.5, color=MUTED, ha="center")

    comparison_rows = [
        (0.625, leverages[2], actual_2x_cagr, free_2x_cagr, False),
        (0.425, leverages[3], actual_3x_cagr, free_3x_cagr, True),
    ]
    max_comparison = max(free_2x_cagr, free_3x_cagr)
    for row_y, lev, actual_value, free_value, is_lower in comparison_rows:
        row_label = leverage_label(lev)
        if is_lower:
            row_label += f"（實際低於 {leverage_label(leverages[2])}）"
        add_text(ax, 0.685, row_y, row_label, size=13, color=INK, weight="bold")
        add_text(ax, 0.685, row_y - 0.055, f"實際成本  {pct(actual_value, 2)}", size=11.5, color=BLUE)
        ax.add_patch(
            Rectangle(
                (0.685, row_y - 0.094),
                0.225 * actual_value / max_comparison,
                0.018,
                transform=ax.transAxes,
                facecolor=BLUE,
                edgecolor="none",
                zorder=3,
            )
        )
        add_text(ax, 0.685, row_y - 0.135, f"免費借貸  {pct(free_value, 2)}", size=11.5, color=RED)
        ax.add_patch(
            Rectangle(
                (0.685, row_y - 0.174),
                0.225 * free_value / max_comparison,
                0.018,
                transform=ax.transAxes,
                facecolor=RED,
                edgecolor="none",
                zorder=3,
            )
        )

    rounded_card(ax, 0.06, 0.085, 0.89, 0.105, facecolor=PANEL_BG, edgecolor=LINE)
    add_text(ax, 0.085, 0.155, "TB3MS 歷史均值", size=10.5, color=MUTED)
    add_text(ax, 0.085, 0.115, pct(financing_mean, 2), size=23, color=INK, weight="bold")
    add_text(
        ax,
        0.27,
        0.137,
        wrap_zh(financing_note, 48),
        size=10.5,
        color=MUTED,
        linespacing=1.25,
    )

    draw_footer(ax, experiment_id)
    save_panel(fig, "3_leverage.png")


def render_questions(results: dict[str, Any]) -> None:
    experiment_id = require_text(results, "experiment_id")
    target = require_number(results, "target_cagr")
    window_years = require_int(results, "window_years")
    spx = require_path(results, "spx_total_return_30y")
    best = require_path(results, "best_decile_windows")

    cagr_max = require_number(spx, "cagr_max")
    cagr_median = require_number(spx, "cagr_median")
    n_independent = require_number(spx, "n_independent_windows")
    n_windows = require_int(spx, "n_windows")
    n_best = require_int(best, "n")
    if n_windows <= 0:
        raise ValueError("n_windows must be positive")
    best_share = n_best / n_windows
    field_30 = "share_with_mdd_worse_than_30pct"
    threshold_30 = threshold_from_field(field_30)
    share_30 = require_number(best, field_30)
    if not 0.0 <= share_30 <= 1.0:
        raise ValueError("Best-decile MDD share must lie in [0, 1]")

    actual_2x = leverage_row(results, 2.0, "實際短率+1pp")
    lev_2x = require_number(actual_2x, "leverage")
    target_share_2x = require_number(actual_2x, "share_ge_target")
    mdd_2x = require_number(actual_2x, "mdd_median")
    find_single_caveat(results, "槓桿", "上界")

    cards = [
        {
            "question": f"{pct(target, 0)} 這個目標哪來的？",
            "metric": pct(cagr_max, 2),
            "caption": f"史上最高的 {window_years} 年年化",
            "face": PALE_BLUE,
            "accent": BLUE,
        },
        {
            "question": "你的回撤預算是多少？",
            "metric": pct_share(share_30),
            "caption": (
                f"報酬前 {pct(best_share, 0)} 視窗\n"
                f"全都跌過 {threshold_30}%"
            ),
            "face": PALE_RED,
            "accent": RED,
        },
        {
            "question": "這個報酬是誰的？",
            "metric": pct(cagr_median, 2),
            "caption": "指數年化中位數｜未扣稅費",
            "face": PALE_TEAL,
            "accent": TEAL,
        },
        {
            "question": "你拿什麼換？",
            "metric": f"{pct_share(target_share_2x)}  →  {pct(mdd_2x, 1)}",
            "caption": f"{leverage_label(lev_2x)} 達標比例 → MDD 中位數",
            "face": PALE_AMBER,
            "accent": AMBER,
        },
    ]

    fig, ax = new_canvas()
    draw_header(
        ax,
        f"追求年化 {pct(target, 0)} 前，先問 {len(cards)} 件事",
        f"每一題都對應 experiment {experiment_id} 的歷史數字",
    )

    positions = [
        (0.06, 0.535),
        (0.515, 0.535),
        (0.06, 0.245),
        (0.515, 0.245),
    ]
    card_w = 0.425
    card_h = 0.245
    for index, (card, (x, y)) in enumerate(zip(cards, positions), start=1):
        rounded_card(ax, x, y, card_w, card_h, facecolor=card["face"], edgecolor=LINE)
        ax.text(
            x + 0.035,
            y + card_h - 0.046,
            str(index),
            transform=ax.transAxes,
            fontsize=11,
            color=WHITE,
            fontweight="bold",
            ha="center",
            va="center",
            bbox={
                "boxstyle": "circle,pad=0.38",
                "facecolor": card["accent"],
                "edgecolor": "none",
            },
            clip_on=True,
            zorder=5,
        )
        add_text(
            ax,
            x + 0.072,
            y + card_h - 0.046,
            card["question"],
            size=14.5,
            color=INK,
            weight="bold",
        )
        metric_size = 28 if index == len(cards) else 34
        add_text(
            ax,
            x + card_w / 2,
            y + 0.128,
            card["metric"],
            size=metric_size,
            color=card["accent"],
            weight="bold",
            ha="center",
        )
        add_text(
            ax,
            x + card_w / 2,
            y + 0.055,
            card["caption"],
            size=11.5,
            color=MUTED,
            ha="center",
            linespacing=1.18,
        )

    rounded_card(ax, 0.06, 0.085, 0.89, 0.105, facecolor=NAVY, edgecolor=NAVY)
    limitation = (
        f"限制：高度重疊樣本只約含 {n_independent:.1f} 個獨立的 "
        f"{window_years} 年區間；槓桿未扣交易成本與內扣費用，數字屬上界。"
    )
    add_text(ax, 0.505, 0.137, limitation, size=12.5, color=WHITE, ha="center")

    draw_footer(ax, experiment_id)
    save_panel(fig, "4_questions.png")


def main() -> None:
    results = load_evidence()
    os.makedirs(out_dir, exist_ok=True)
    render_target(results)
    render_stability(results)
    render_leverage(results)
    render_questions(results)


if __name__ == "__main__":
    main()
