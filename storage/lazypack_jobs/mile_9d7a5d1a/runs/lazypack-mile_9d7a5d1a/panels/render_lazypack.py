#!/usr/bin/env python3
"""Render the K1427 VolPred lazy-pack panels from their evidence package."""

from __future__ import annotations

import json
import os
import re
import textwrap
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.patches import Circle, FancyBboxPatch, Rectangle


RESULT_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1427/k1427_results.json"
)
README_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1427/README.md"
)
PLAN_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_9d7a5d1a/runs/lazypack-mile_9d7a5d1a/plan.json"
)
ARTICLE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_9d7a5d1a/runs/lazypack-mile_9d7a5d1a/panels/"
    "mile_9d7a5d1a_article.md"
)
OUT_DIR = (
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_9d7a5d1a/runs/lazypack-mile_9d7a5d1a/panels"
)

WIDTH_PX = 1600
HEIGHT_PX = 1000
DPI = 150

INK = "#17212B"
MUTED = "#5E6A75"
FAINT = "#DCE2E7"
PAPER = "#FFFFFF"
NAVY = "#17324D"
RED = "#B93A3A"
RED_SOFT = "#F8E9E7"
GREEN = "#247254"
GREEN_SOFT = "#E6F2EC"
BLUE = "#315E89"
BLUE_SOFT = "#E8F0F7"
AMBER = "#A86C1D"
AMBER_SOFT = "#F6EEDD"

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def load_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError(f"Evidence file is empty: {path}")
    return text


def resolve_path(data: Any, dotted_path: str) -> Any:
    current = data
    for key in dotted_path.split("."):
        if not isinstance(current, dict) or key not in current:
            raise KeyError(f"Missing evidence field: {dotted_path}")
        current = current[key]
    return current


def require_number(value: Any, dotted_path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"Expected numeric evidence at {dotted_path}")
    return float(value)


def get_panel(plan: dict[str, Any], name: str) -> dict[str, Any]:
    panels = plan.get("panels")
    if not isinstance(panels, list):
        raise TypeError("plan.panels must be a list")
    matches = [panel for panel in panels if panel.get("name") == name]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one panel named {name}")
    panel = matches[0]
    for required in ("title", "alt", "sources", "blocks"):
        if required not in panel:
            raise KeyError(f"Missing plan field for {name}: {required}")
    if panel["sources"] != ["result"]:
        raise ValueError(f"Unexpected sources for {name}: {panel['sources']}")
    return panel


def metric_blocks(panel: dict[str, Any]) -> list[dict[str, Any]]:
    return [block for block in panel["blocks"] if block.get("kind") == "metric"]


def text_blocks(panel: dict[str, Any]) -> list[dict[str, Any]]:
    return [block for block in panel["blocks"] if block.get("kind") == "text"]


def metric_value(result: dict[str, Any], block: dict[str, Any]) -> float:
    value_spec = block.get("value")
    if not isinstance(value_spec, dict):
        raise TypeError(f"Metric {block.get('label')} has no value spec")
    if value_spec.get("source") != "result":
        raise ValueError(f"Metric {block.get('label')} must use result evidence")
    path = value_spec.get("path")
    if not isinstance(path, str) or not path:
        raise TypeError(f"Metric {block.get('label')} has no evidence path")
    return require_number(resolve_path(result, path), path)


def format_metric(result: dict[str, Any], block: dict[str, Any]) -> str:
    value = metric_value(result, block)
    spec = block["value"]
    fmt = spec.get("format")
    if not isinstance(fmt, dict):
        raise TypeError(f"Metric {block.get('label')} has no format spec")
    kind = fmt.get("kind")
    suffix = fmt.get("suffix", "")

    if kind == "percent":
        digits = fmt.get("digits")
        if not isinstance(digits, int):
            raise TypeError("Percent format requires integer digits")
        sign = "+" if fmt.get("show_plus") and value >= 0 else ""
        rendered = f"{sign}{value * 100:.{digits}f}%"
    elif kind == "integer":
        if not value.is_integer():
            raise ValueError(f"Integer format received non-integer value: {value}")
        rendered = f"{int(value)}"
    elif kind == "number":
        digits = fmt.get("digits")
        if not isinstance(digits, int):
            raise TypeError("Number format requires integer digits")
        rendered = f"{value:.{digits}f}"
    else:
        raise ValueError(f"Unsupported metric format: {kind}")

    return rendered.replace("-", "−") + str(suffix)


def new_figure() -> tuple[Figure, Axes]:
    fig = plt.figure(
        figsize=(WIDTH_PX / DPI, HEIGHT_PX / DPI),
        dpi=DPI,
        facecolor=PAPER,
    )
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    return fig, ax


def rounded_box(
    ax: Axes,
    x: float,
    y: float,
    width: float,
    height: float,
    facecolor: str,
    edgecolor: str = "none",
    linewidth: float = 0.0,
    radius: float = 0.025,
) -> None:
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            width,
            height,
            boxstyle=f"round,pad=0.012,rounding_size={radius}",
            facecolor=facecolor,
            edgecolor=edgecolor,
            linewidth=linewidth,
        )
    )


def add_source(fig: Figure, experiment_id: str, color: str = MUTED) -> None:
    fig.text(
        0.06,
        0.045,
        f"資料來源：experiment {experiment_id.upper()}",
        ha="left",
        va="center",
        fontsize=12,
        color=color,
    )


def save_panel(fig: Figure, filename: str) -> None:
    fig.savefig(
        os.path.join(OUT_DIR, filename),
        dpi=DPI,
        facecolor=PAPER,
        edgecolor="none",
        bbox_inches=None,
        pad_inches=0,
    )
    plt.close(fig)


def render_latest_day(
    result: dict[str, Any], panel: dict[str, Any], experiment_id: str
) -> None:
    blocks = metric_blocks(panel)
    if [block.get("label") for block in blocks] != [
        "大盤",
        "科技",
        "必需消費",
        "能源",
    ]:
        raise ValueError("Panel 1 metric blocks do not match the approved plan")

    values = [metric_value(result, block) for block in blocks]
    rendered = [format_metric(result, block) for block in blocks]
    max_abs_value = max(abs(value) for value in values)
    primary_bar_width = (
        0.0
        if max_abs_value == 0.0
        else 0.26 * min(abs(values[0]) / max_abs_value, 1.0)
    )
    fig, ax = new_figure()

    fig.text(
        0.055,
        0.915,
        panel["title"],
        ha="left",
        va="center",
        fontsize=29,
        fontweight="bold",
        color=INK,
    )
    fig.text(
        0.055,
        0.855,
        "同一段行情的累積報酬",
        ha="left",
        va="center",
        fontsize=15,
        color=MUTED,
    )

    rounded_box(ax, 0.055, 0.17, 0.40, 0.60, RED_SOFT)
    fig.text(0.085, 0.705, blocks[0]["label"], fontsize=19, color=MUTED)
    fig.text(
        0.085,
        0.465,
        rendered[0],
        fontsize=54,
        fontweight="bold",
        color=RED if values[0] < 0 else GREEN,
        va="center",
    )
    fig.text(
        0.085,
        0.255,
        "下跌" if values[0] < 0 else "上漲",
        fontsize=17,
        fontweight="bold",
        color=RED if values[0] < 0 else GREEN,
    )
    ax.add_patch(Rectangle((0.085, 0.315), 0.26, 0.012, color=FAINT, linewidth=0))
    ax.add_patch(
        Rectangle(
            (0.085, 0.315),
            primary_bar_width,
            0.012,
            color=RED if values[0] < 0 else GREEN,
            linewidth=0,
        )
    )

    card_y = [0.585, 0.375, 0.165]
    soft_colors = [RED_SOFT, GREEN_SOFT, AMBER_SOFT]
    accent_colors = [RED, GREEN, AMBER]
    for index, (block, value, label) in enumerate(
        zip(blocks[1:], values[1:], rendered[1:])
    ):
        y = card_y[index]
        rounded_box(ax, 0.505, y, 0.44, 0.165, soft_colors[index])
        fig.text(
            0.535,
            y + 0.112,
            block["label"],
            ha="left",
            va="center",
            fontsize=17,
            color=MUTED,
        )
        fig.text(
            0.905,
            y + 0.078,
            label,
            ha="right",
            va="center",
            fontsize=34,
            fontweight="bold",
            color=GREEN if value > 0 else accent_colors[index],
        )
        fig.text(
            0.535,
            y + 0.046,
            "上漲" if value > 0 else "下跌",
            ha="left",
            va="center",
            fontsize=13,
            fontweight="bold",
            color=GREEN if value > 0 else accent_colors[index],
        )

    add_source(fig, experiment_id)
    save_panel(fig, "1_latest_day.png")


def render_history_split(
    result: dict[str, Any], panel: dict[str, Any], experiment_id: str
) -> None:
    blocks = metric_blocks(panel)
    expected_labels = ["大跌段落", "真輪動", "全跌但跌幅不同", "同步清算"]
    if [block.get("label") for block in blocks] != expected_labels:
        raise ValueError("Panel 2 metric blocks do not match the approved plan")

    values = [metric_value(result, block) for block in blocks]
    if any(not value.is_integer() for value in values):
        raise ValueError("Panel 2 requires integer episode counts")
    total = int(values[0])
    categories = [int(value) for value in values[1:]]
    if sum(categories) != total:
        raise ValueError("Regime episode counts do not sum to n_episodes")

    rendered = [format_metric(result, block) for block in blocks]
    fig, ax = new_figure()
    ax.add_patch(Rectangle((0, 0.79), 1, 0.21, color=NAVY, linewidth=0))
    fig.text(
        0.06,
        0.905,
        panel["title"],
        ha="left",
        va="center",
        fontsize=30,
        fontweight="bold",
        color=PAPER,
    )
    fig.text(
        0.06,
        0.835,
        "把連續衝擊合併後，再依方向與差距分類",
        ha="left",
        va="center",
        fontsize=15,
        color="#D7E3ED",
    )

    fig.text(0.065, 0.665, blocks[0]["label"], fontsize=18, color=MUTED)
    fig.text(
        0.065,
        0.515,
        rendered[0],
        fontsize=48,
        fontweight="bold",
        color=NAVY,
        va="center",
    )
    fig.text(
        0.065,
        0.415,
        "分類母體",
        fontsize=13,
        color=MUTED,
    )
    ax.plot([0.305, 0.305], [0.39, 0.70], color=FAINT, linewidth=1.4)

    card_x = [0.355, 0.565, 0.775]
    colors = [GREEN, AMBER, BLUE]
    wrapped_labels = ["真輪動", "全跌但\n跌幅不同", "同步清算"]
    for x, block, label, display, color in zip(
        card_x, blocks[1:], wrapped_labels, rendered[1:], colors
    ):
        fig.text(
            x,
            0.665,
            label,
            ha="left",
            va="top",
            fontsize=16,
            color=MUTED,
            linespacing=1.25,
        )
        fig.text(
            x,
            0.505,
            display,
            ha="left",
            va="center",
            fontsize=36,
            fontweight="bold",
            color=color,
        )

    bar_x, bar_y, bar_w, bar_h = 0.065, 0.245, 0.87, 0.075
    cursor = bar_x
    for count, color in zip(categories, colors):
        width = bar_w * count / total
        ax.add_patch(Rectangle((cursor, bar_y), width, bar_h, color=color, linewidth=0))
        cursor += width
    fig.text(
        bar_x,
        0.345,
        "各類型在全部大跌段落中的相對規模",
        ha="left",
        va="center",
        fontsize=14,
        color=MUTED,
    )

    add_source(fig, experiment_id)
    save_panel(fig, "2_history_split.png")


def render_reading_rule(
    result: dict[str, Any], panel: dict[str, Any], experiment_id: str
) -> None:
    steps = text_blocks(panel)
    metrics = metric_blocks(panel)
    if len(steps) != 3 or len(metrics) != 1:
        raise ValueError("Panel 3 requires three text steps and one metric")
    for step in steps:
        if not isinstance(step.get("heading"), str):
            raise TypeError("Panel 3 step heading must be text")
        body = step.get("body")
        if not isinstance(body, list) or len(body) != 1 or not isinstance(body[0], str):
            raise TypeError("Panel 3 step body must contain exactly one text item")

    rendered_metric = format_metric(result, metrics[0])
    fig, ax = new_figure()
    ax.add_patch(Rectangle((0.06, 0.865), 0.075, 0.012, color=GREEN, linewidth=0))
    fig.text(
        0.06,
        0.925,
        panel["title"],
        ha="left",
        va="center",
        fontsize=30,
        fontweight="bold",
        color=INK,
    )

    line_x = 0.095
    ax.plot([line_x, line_x], [0.225, 0.735], color=FAINT, linewidth=2.0)
    centers = [0.715, 0.475, 0.235]
    numerals = ["一", "二", "三"]
    for center_y, numeral, step in zip(centers, numerals, steps):
        ax.add_patch(Circle((line_x, center_y), 0.031, color=NAVY, linewidth=0))
        fig.text(
            line_x,
            center_y,
            numeral,
            ha="center",
            va="center",
            fontsize=15,
            fontweight="bold",
            color=PAPER,
        )
        fig.text(
            0.145,
            center_y + 0.047,
            step["heading"],
            ha="left",
            va="center",
            fontsize=19,
            fontweight="bold",
            color=INK,
        )
        wrapped = textwrap.fill(step["body"][0], width=22)
        fig.text(
            0.145,
            center_y - 0.013,
            wrapped,
            ha="left",
            va="top",
            fontsize=15,
            color=MUTED,
            linespacing=1.45,
        )

    rounded_box(ax, 0.665, 0.205, 0.285, 0.57, BLUE_SOFT)
    fig.text(
        0.705,
        0.700,
        metrics[0]["label"],
        ha="left",
        va="center",
        fontsize=17,
        color=MUTED,
    )
    fig.text(
        0.705,
        0.520,
        rendered_metric,
        ha="left",
        va="center",
        fontsize=45,
        fontweight="bold",
        color=BLUE,
    )
    ax.add_patch(Rectangle((0.705, 0.415), 0.19, 0.009, color=BLUE, linewidth=0))
    fig.text(
        0.705,
        0.345,
        "大跌日板塊差距\n相對平常日",
        ha="left",
        va="center",
        fontsize=16,
        color=INK,
        linespacing=1.4,
    )
    fig.text(
        0.705,
        0.255,
        "差距變大只是起點，\n方向才是輪動證據。",
        ha="left",
        va="center",
        fontsize=13,
        color=MUTED,
        linespacing=1.4,
    )

    add_source(fig, experiment_id)
    save_panel(fig, "3_reading_rule.png")


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)

    result = load_json(RESULT_PATH)
    plan = load_json(PLAN_PATH)
    load_text(README_PATH)
    load_text(ARTICLE_PATH)

    if not isinstance(result, dict) or not isinstance(plan, dict):
        raise TypeError("Result and plan evidence must both be JSON objects")
    experiment_id = result.get("experiment_id")
    if not isinstance(experiment_id, str) or not re.fullmatch(r"k\d+", experiment_id):
        raise ValueError("result.experiment_id must match k followed by digits")

    panel_1 = get_panel(plan, "1_latest_day")
    panel_2 = get_panel(plan, "2_history_split")
    panel_3 = get_panel(plan, "3_reading_rule")

    render_latest_day(result, panel_1, experiment_id)
    render_history_split(result, panel_2, experiment_id)
    render_reading_rule(result, panel_3, experiment_id)


if __name__ == "__main__":
    main()
