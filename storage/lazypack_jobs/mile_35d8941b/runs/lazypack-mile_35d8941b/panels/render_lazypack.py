#!/usr/bin/env python3
"""Render the three data-bound PNG panels for the mile_35d8941b article."""

from __future__ import annotations

import json
import os
import textwrap
from datetime import date
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.patches import Circle, FancyBboxPatch, Polygon, Rectangle


RESULTS_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1415/k1415_results.json"
)
README_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1415/README.md"
)
PLAN_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_35d8941b/runs/lazypack-mile_35d8941b/plan.json"
)
ARTICLE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_35d8941b/runs/lazypack-mile_35d8941b/panels/"
    "mile_35d8941b_article.md"
)
OUT_DIR = (
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_35d8941b/runs/lazypack-mile_35d8941b/panels"
)

WIDTH = 1600
HEIGHT = 1000
DPI = 150

NAVY = "#102A43"
NAVY_2 = "#163B63"
BLUE = "#2878B5"
BLUE_SOFT = "#EAF3FA"
CYAN = "#19A7AE"
CYAN_SOFT = "#E6F7F7"
GREEN = "#238B57"
GREEN_SOFT = "#E7F4ED"
AMBER = "#D58A16"
AMBER_SOFT = "#FFF4DE"
RED = "#C44B4F"
INK = "#172B3A"
MUTED = "#536777"
FAINT = "#758797"
BORDER = "#D9E3EA"
PAPER = "#F5F8FA"
WHITE = "#FFFFFF"

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_text(path: Path) -> str:
    with path.open("r", encoding="utf-8") as handle:
        content = handle.read()
    if not content.strip():
        raise ValueError(f"Evidence file is empty: {path}")
    return content


def require_mapping(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"Expected object at {context}, got {type(value).__name__}")
    return value


def require_list(value: Any, context: str) -> list[Any]:
    if not isinstance(value, list):
        raise TypeError(f"Expected list at {context}, got {type(value).__name__}")
    return value


def require_string(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise TypeError(f"Expected non-empty string at {context}")
    return value


def resolve_path(data: Any, dotted_path: str) -> Any:
    current = data
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise KeyError(f"Missing evidence field: {dotted_path}")
        current = current[part]
    return current


def numeric_value(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"Expected numeric evidence at {path}")
    return float(value)


def format_value(value: Any, fmt: dict[str, Any], path: str) -> str:
    kind = require_string(fmt.get("kind"), f"{path}.format.kind")
    digits = fmt.get("digits", 0)
    if not isinstance(digits, int) or isinstance(digits, bool) or digits < 0:
        raise TypeError(f"Expected non-negative integer digits for {path}")

    if kind == "date":
        raw = require_string(value, path)
        parsed = date.fromisoformat(raw)
        return f"{parsed.year:04d} 年 {parsed.month:02d} 月 {parsed.day:02d} 日"

    number = numeric_value(value, path)
    if fmt.get("absolute", False):
        number = abs(number)

    if kind == "integer":
        if not number.is_integer():
            raise ValueError(f"Expected integer-valued evidence at {path}")
        rendered = f"{int(number):,d}"
    elif kind == "number":
        rendered = f"{number:+.{digits}f}" if fmt.get("show_plus") else f"{number:.{digits}f}"
    elif kind == "percent":
        scale = fmt.get("scale", 100)
        if isinstance(scale, bool) or not isinstance(scale, (int, float)):
            raise TypeError(f"Expected numeric percent scale for {path}")
        number *= float(scale)
        rendered = f"{number:+.{digits}f}" if fmt.get("show_plus") else f"{number:.{digits}f}"
        rendered += "%"
    else:
        raise ValueError(f"Unsupported format kind {kind!r} at {path}")

    suffix = fmt.get("suffix", "")
    if not isinstance(suffix, str):
        raise TypeError(f"Expected string suffix for {path}")
    return rendered + suffix


def get_panel(plan: dict[str, Any], name: str) -> dict[str, Any]:
    panels = require_list(plan.get("panels"), "plan.panels")
    matches = [
        require_mapping(panel, f"plan.panels[{index}]")
        for index, panel in enumerate(panels)
        if isinstance(panel, dict) and panel.get("name") == name
    ]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one panel named {name!r}")
    return matches[0]


def panel_blocks(panel: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    blocks = require_list(panel.get("blocks"), f"{panel.get('name')}.blocks")
    return [
        require_mapping(block, f"{panel.get('name')}.blocks[{index}]")
        for index, block in enumerate(blocks)
        if isinstance(block, dict) and block.get("kind") == kind
    ]


def bind_metric(block: dict[str, Any], results: dict[str, Any]) -> tuple[str, str, float | str]:
    label = require_string(block.get("label"), "metric.label")
    value_spec = require_mapping(block.get("value"), f"{label}.value")
    source = require_string(value_spec.get("source"), f"{label}.value.source")
    if source != "results":
        raise ValueError(f"Unsupported metric source {source!r} for {label}")
    path = require_string(value_spec.get("path"), f"{label}.value.path")
    fmt = require_mapping(value_spec.get("format"), f"{label}.value.format")
    raw = resolve_path(results, path)
    return label, format_value(raw, fmt, path), raw


def source_label(panel: dict[str, Any], plan: dict[str, Any]) -> str:
    source_ids = require_list(panel.get("sources"), f"{panel.get('name')}.sources")
    evidence = require_mapping(plan.get("evidence"), "plan.evidence")
    labels: list[str] = []
    for source_id in source_ids:
        source_name = require_string(source_id, f"{panel.get('name')}.sources")
        source_spec = require_mapping(evidence.get(source_name), f"plan.evidence.{source_name}")
        labels.append(require_string(source_spec.get("label"), f"plan.evidence.{source_name}.label"))
    if not labels:
        raise ValueError(f"Panel {panel.get('name')} has no sources")
    return "；".join(labels)


def new_canvas() -> tuple[Figure, Axes]:
    fig = plt.figure(figsize=(WIDTH / DPI, HEIGHT / DPI), dpi=DPI, facecolor=WHITE)
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
    *,
    facecolor: str = WHITE,
    edgecolor: str = BORDER,
    linewidth: float = 1.0,
    radius: float = 0.018,
) -> FancyBboxPatch:
    patch = FancyBboxPatch(
        (x, y),
        width,
        height,
        boxstyle=f"round,pad=0.008,rounding_size={radius}",
        facecolor=facecolor,
        edgecolor=edgecolor,
        linewidth=linewidth,
    )
    ax.add_patch(patch)
    return patch


def wrap_lines(text: str, width: int) -> str:
    return "\n".join(
        textwrap.wrap(
            text,
            width=width,
            break_long_words=True,
            break_on_hyphens=False,
            replace_whitespace=False,
        )
    )


def draw_header(ax: Axes, panel: dict[str, Any], *, accent: str) -> None:
    title = require_string(panel.get("title"), f"{panel.get('name')}.title")
    alt = require_string(panel.get("alt"), f"{panel.get('name')}.alt")
    ax.add_patch(Rectangle((0, 0.79), 1, 0.21, facecolor=NAVY, edgecolor="none"))
    ax.add_patch(Rectangle((0.05, 0.875), 0.009, 0.068, facecolor=accent, edgecolor="none"))
    ax.text(
        0.075,
        0.92,
        title,
        ha="left",
        va="center",
        fontsize=28,
        fontweight="bold",
        color=WHITE,
    )
    ax.text(
        0.075,
        0.845,
        wrap_lines(alt, 44),
        ha="left",
        va="center",
        fontsize=14.5,
        linespacing=1.35,
        color="#DDEAF3",
    )


def draw_footer(ax: Axes, label: str, *, accent: str) -> None:
    ax.plot([0.05, 0.95], [0.072, 0.072], color=BORDER, linewidth=1.0)
    ax.add_patch(Circle((0.059, 0.038), 0.006, facecolor=accent, edgecolor="none"))
    ax.text(
        0.072,
        0.038,
        f"資料來源｜{label}",
        ha="left",
        va="center",
        fontsize=11.5,
        color=MUTED,
    )


def save_panel(fig: Figure, panel: dict[str, Any]) -> None:
    name = require_string(panel.get("name"), "panel.name")
    title = require_string(panel.get("title"), f"{name}.title")
    alt = require_string(panel.get("alt"), f"{name}.alt")
    output_path = Path(OUT_DIR) / f"{name}.png"
    fig.savefig(
        output_path,
        dpi=DPI,
        facecolor=WHITE,
        edgecolor="none",
        metadata={"Title": title, "Description": alt},
    )
    plt.close(fig)


def draw_bullets(
    ax: Axes,
    body: list[Any],
    *,
    x: float,
    y: float,
    width_chars: int,
    fontsize: float,
    line_height: float,
    paragraph_gap: float,
    color: str = INK,
    bullet_color: str = BLUE,
) -> None:
    cursor_y = y
    for index, item in enumerate(body):
        text = require_string(item, f"text.body[{index}]")
        wrapped = wrap_lines(text, width_chars)
        line_count = wrapped.count("\n") + 1
        ax.add_patch(Circle((x, cursor_y - 0.007), 0.006, facecolor=bullet_color, edgecolor="none"))
        ax.text(
            x + 0.018,
            cursor_y,
            wrapped,
            ha="left",
            va="top",
            fontsize=fontsize,
            linespacing=1.35,
            color=color,
        )
        cursor_y -= line_count * line_height + paragraph_gap


def render_concept(panel: dict[str, Any], plan: dict[str, Any], results: dict[str, Any]) -> None:
    metrics = panel_blocks(panel, "metric")
    texts = panel_blocks(panel, "text")
    if len(metrics) != 2 or len(texts) != 1:
        raise ValueError("1_concept must contain two metrics and one text block")
    bound_metrics = [bind_metric(block, results) for block in metrics]
    text_block = texts[0]
    heading = require_string(text_block.get("heading"), "1_concept.text.heading")
    body = require_list(text_block.get("body"), "1_concept.text.body")
    if len(body) != 3:
        raise ValueError("1_concept text block must contain three statements")

    fig, ax = new_canvas()
    draw_header(ax, panel, accent=CYAN)

    rounded_box(ax, 0.05, 0.31, 0.52, 0.43, facecolor=WHITE)
    ax.text(
        0.075,
        0.698,
        heading,
        ha="left",
        va="center",
        fontsize=19,
        fontweight="bold",
        color=NAVY,
    )
    ax.plot([0.075, 0.545], [0.668, 0.668], color=BORDER, linewidth=1.0)
    draw_bullets(
        ax,
        body,
        x=0.082,
        y=0.638,
        width_chars=23,
        fontsize=15.2,
        line_height=0.043,
        paragraph_gap=0.017,
        bullet_color=CYAN,
    )

    rounded_box(ax, 0.60, 0.31, 0.35, 0.43, facecolor=PAPER)
    ax.text(
        0.625,
        0.698,
        "訊號補進預測的路徑",
        ha="left",
        va="center",
        fontsize=18,
        fontweight="bold",
        color=NAVY,
    )

    rounded_box(ax, 0.625, 0.585, 0.125, 0.075, facecolor=CYAN_SOFT, edgecolor="#BFE4E5")
    ax.text(
        0.6875,
        0.622,
        "短天期 VIX",
        ha="center",
        va="center",
        fontsize=14,
        fontweight="bold",
        color=NAVY_2,
    )
    rounded_box(ax, 0.80, 0.585, 0.125, 0.075, facecolor=BLUE_SOFT, edgecolor="#C9DEEE")
    ax.text(
        0.8625,
        0.622,
        "長天期 VIX",
        ha="center",
        va="center",
        fontsize=14,
        fontweight="bold",
        color=NAVY_2,
    )

    ax.plot([0.688, 0.688, 0.775], [0.577, 0.545, 0.545], color=CYAN, linewidth=2.0)
    ax.plot([0.863, 0.863, 0.775], [0.577, 0.545, 0.545], color=BLUE, linewidth=2.0)
    ax.add_patch(
        Polygon(
            [[0.765, 0.552], [0.785, 0.552], [0.775, 0.535]],
            closed=True,
            facecolor=NAVY_2,
            edgecolor="none",
        )
    )
    rounded_box(ax, 0.685, 0.455, 0.18, 0.075, facecolor=WHITE, edgecolor="#AFC5D5")
    ax.text(
        0.775,
        0.492,
        "比值取對數",
        ha="center",
        va="center",
        fontsize=15,
        fontweight="bold",
        color=INK,
    )
    ax.annotate(
        "",
        xy=(0.775, 0.382),
        xytext=(0.775, 0.446),
        arrowprops={"arrowstyle": "-|>", "color": NAVY_2, "lw": 2.0},
    )
    rounded_box(ax, 0.655, 0.33, 0.24, 0.055, facecolor=NAVY_2, edgecolor=NAVY_2)
    ax.text(
        0.775,
        0.357,
        "補進 HAR-RV 基準",
        ha="center",
        va="center",
        fontsize=14.5,
        fontweight="bold",
        color=WHITE,
    )

    card_width = 0.43
    for index, (label, rendered, _raw) in enumerate(bound_metrics):
        x = 0.05 + index * 0.47
        rounded_box(
            ax,
            x,
            0.105,
            card_width,
            0.145,
            facecolor=CYAN_SOFT if index == 0 else BLUE_SOFT,
            edgecolor="#C7E2E6" if index == 0 else "#C9DEEE",
        )
        ax.text(
            x + 0.025,
            0.215,
            label,
            ha="left",
            va="center",
            fontsize=13,
            color=MUTED,
        )
        ax.text(
            x + 0.025,
            0.155,
            rendered,
            ha="left",
            va="center",
            fontsize=23 if index == 0 else 20.5,
            fontweight="bold",
            color=NAVY,
        )

    draw_footer(ax, source_label(panel, plan), accent=CYAN)
    save_panel(fig, panel)


def render_results(panel: dict[str, Any], plan: dict[str, Any], results: dict[str, Any]) -> None:
    metrics = panel_blocks(panel, "metric")
    if len(metrics) != 4:
        raise ValueError("2_results must contain four metrics")
    bound = [bind_metric(block, results) for block in metrics]

    fig, ax = new_canvas()
    ax.add_patch(Rectangle((0, 0), 1, 1, facecolor=PAPER, edgecolor="none"))
    draw_header(ax, panel, accent=AMBER)

    # Hero improvement card.
    rounded_box(ax, 0.05, 0.42, 0.43, 0.31, facecolor=NAVY_2, edgecolor=NAVY_2)
    ax.add_patch(Circle((0.421, 0.668), 0.034, facecolor=GREEN, edgecolor="none"))
    ax.annotate(
        "",
        xy=(0.421, 0.645),
        xytext=(0.421, 0.687),
        arrowprops={"arrowstyle": "-|>", "color": WHITE, "lw": 2.4},
    )
    ax.text(
        0.08,
        0.67,
        bound[0][0],
        ha="left",
        va="center",
        fontsize=17,
        color="#DDEAF3",
    )
    ax.text(
        0.08,
        0.555,
        bound[0][1],
        ha="left",
        va="center",
        fontsize=46,
        fontweight="bold",
        color=WHITE,
    )
    ax.text(
        0.08,
        0.465,
        "QLIKE 越低，預測誤差越小",
        ha="left",
        va="center",
        fontsize=14,
        color="#BFD2E0",
    )

    # Side-by-side baseline and augmented-model cards.
    side_cards = [
        (0.51, bound[1], BLUE_SOFT, BLUE),
        (0.74, bound[2], GREEN_SOFT, GREEN),
    ]
    for x, metric, fill, accent in side_cards:
        rounded_box(ax, x, 0.42, 0.21, 0.31, facecolor=fill, edgecolor=BORDER)
        ax.add_patch(Rectangle((x + 0.017, 0.695), 0.055, 0.008, facecolor=accent, edgecolor="none"))
        ax.text(
            x + 0.025,
            0.65,
            wrap_lines(metric[0], 12),
            ha="left",
            va="top",
            fontsize=14,
            linespacing=1.3,
            color=MUTED,
        )
        ax.text(
            x + 0.025,
            0.515,
            metric[1],
            ha="left",
            va="center",
            fontsize=30,
            fontweight="bold",
            color=NAVY,
        )
        ax.add_patch(Rectangle((x + 0.025, 0.458), 0.16, 0.012, facecolor="#D4DEE5", edgecolor="none"))
        ax.add_patch(Rectangle((x + 0.025, 0.458), 0.12, 0.012, facecolor=accent, edgecolor="none"))

    # A wide statistical-test card keeps the fourth information type separate.
    rounded_box(ax, 0.05, 0.115, 0.90, 0.25, facecolor=WHITE, edgecolor=BORDER)
    ax.add_patch(Rectangle((0.05, 0.115), 0.018, 0.25, facecolor=AMBER, edgecolor="none"))
    ax.text(
        0.095,
        0.31,
        bound[3][0],
        ha="left",
        va="center",
        fontsize=16,
        color=MUTED,
    )
    ax.text(
        0.095,
        0.215,
        bound[3][1],
        ha="left",
        va="center",
        fontsize=38,
        fontweight="bold",
        color=NAVY,
    )
    ax.plot([0.32, 0.32], [0.16, 0.32], color=BORDER, linewidth=1.2)
    ax.text(
        0.365,
        0.27,
        "逐日比較兩套模型的樣本外誤差",
        ha="left",
        va="center",
        fontsize=17,
        fontweight="bold",
        color=INK,
    )
    ax.text(
        0.365,
        0.205,
        "檢定結果拒絕兩模型表現相等",
        ha="left",
        va="center",
        fontsize=15,
        color=MUTED,
    )

    draw_footer(ax, source_label(panel, plan), accent=AMBER)
    save_panel(fig, panel)


def render_takeaway(panel: dict[str, Any], plan: dict[str, Any], results: dict[str, Any]) -> None:
    metrics = panel_blocks(panel, "metric")
    texts = panel_blocks(panel, "text")
    if len(metrics) != 4 or len(texts) != 1:
        raise ValueError("3_takeaway must contain four metrics and one text block")
    bound = [bind_metric(block, results) for block in metrics]
    text_block = texts[0]
    heading = require_string(text_block.get("heading"), "3_takeaway.text.heading")
    body = require_list(text_block.get("body"), "3_takeaway.text.body")
    if len(body) != 3:
        raise ValueError("3_takeaway text block must contain three statements")

    r2_m0 = numeric_value(bound[0][2], "models.M0.r2_full_sample")
    r2_m1 = numeric_value(bound[1][2], "models.M1.r2_full_sample")
    if r2_m0 < 0 or r2_m1 < 0:
        raise ValueError("R² chart requires non-negative evidence values")
    r2_max = max(r2_m0, r2_m1)
    if r2_max == 0:
        raise ValueError("R² chart cannot scale two zero values")

    fig, ax = new_canvas()
    draw_header(ax, panel, accent=BLUE)

    card_fills = [BLUE_SOFT, GREEN_SOFT, CYAN_SOFT, AMBER_SOFT]
    card_accents = [BLUE, GREEN, CYAN, AMBER]
    for index, metric in enumerate(bound):
        x = 0.05 + index * 0.23
        rounded_box(ax, x, 0.625, 0.21, 0.135, facecolor=card_fills[index], edgecolor=BORDER)
        ax.add_patch(Rectangle((x + 0.017, 0.731), 0.047, 0.007, facecolor=card_accents[index], edgecolor="none"))
        ax.text(
            x + 0.018,
            0.704,
            wrap_lines(metric[0], 13),
            ha="left",
            va="top",
            fontsize=11.8,
            linespacing=1.25,
            color=MUTED,
        )
        ax.text(
            x + 0.018,
            0.651,
            metric[1],
            ha="left",
            va="center",
            fontsize=21,
            fontweight="bold",
            color=NAVY,
        )

    # Poster-style results chart.
    rounded_box(ax, 0.05, 0.115, 0.42, 0.455, facecolor=WHITE, edgecolor=BORDER)
    ax.text(
        0.075,
        0.525,
        "全樣本 R² 比較",
        ha="left",
        va="center",
        fontsize=18,
        fontweight="bold",
        color=NAVY,
    )
    ax.text(
        0.075,
        0.487,
        "同一份樣本、同一預測目標",
        ha="left",
        va="center",
        fontsize=12.5,
        color=MUTED,
    )

    chart_specs = [
        ("純 HAR", r2_m0, bound[0][1], 0.405, BLUE),
        ("加訊號", r2_m1, bound[1][1], 0.305, GREEN),
    ]
    for short_label, raw, rendered, y, color in chart_specs:
        bar_width = 0.26
        ax.text(
            0.075,
            y + 0.028,
            short_label,
            ha="left",
            va="center",
            fontsize=13,
            color=INK,
        )
        ax.add_patch(
            Rectangle(
                (0.155, y),
                bar_width,
                0.055,
                facecolor="#E5EBF0",
                edgecolor="none",
            )
        )
        ax.add_patch(
            Rectangle(
                (0.155, y),
                bar_width * raw / r2_max,
                0.055,
                facecolor=color,
                edgecolor="none",
            )
        )
        ax.text(
            0.402,
            y + 0.028,
            rendered,
            ha="right",
            va="center",
            fontsize=14,
            fontweight="bold",
            color=NAVY,
            bbox={
                "boxstyle": "round,pad=0.2",
                "facecolor": WHITE,
                "edgecolor": "none",
                "alpha": 0.92,
            },
        )

    ax.plot([0.075, 0.445], [0.254, 0.254], color=BORDER, linewidth=1.0)
    rounded_box(ax, 0.075, 0.177, 0.155, 0.05, facecolor=BLUE_SOFT, edgecolor="#C9DEEE")
    ax.text(
        0.1525,
        0.202,
        "全樣本迴歸",
        ha="center",
        va="center",
        fontsize=12,
        fontweight="bold",
        color=NAVY_2,
    )
    ax.annotate(
        "",
        xy=(0.272, 0.202),
        xytext=(0.238, 0.202),
        arrowprops={"arrowstyle": "-|>", "color": FAINT, "lw": 1.5},
    )
    rounded_box(ax, 0.28, 0.177, 0.155, 0.05, facecolor=CYAN_SOFT, edgecolor="#BFE4E5")
    ax.text(
        0.3575,
        0.202,
        "判讀係數方向",
        ha="center",
        va="center",
        fontsize=12,
        fontweight="bold",
        color=NAVY_2,
    )

    # Limitations and boundary conditions.
    rounded_box(ax, 0.50, 0.115, 0.45, 0.455, facecolor=PAPER, edgecolor=BORDER)
    ax.text(
        0.525,
        0.525,
        heading,
        ha="left",
        va="center",
        fontsize=18,
        fontweight="bold",
        color=NAVY,
    )
    ax.plot([0.525, 0.925], [0.493, 0.493], color=BORDER, linewidth=1.0)
    draw_bullets(
        ax,
        body,
        x=0.532,
        y=0.462,
        width_chars=21,
        fontsize=13.6,
        line_height=0.039,
        paragraph_gap=0.019,
        bullet_color=RED,
    )

    draw_footer(ax, source_label(panel, plan), accent=BLUE)
    save_panel(fig, panel)


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)

    results = require_mapping(load_json(RESULTS_PATH), "results")
    plan = require_mapping(load_json(PLAN_PATH), "plan")

    # These files are part of the evidence package. Reading and checking them here
    # makes a missing or empty package fail loudly before any panel is written.
    load_text(README_PATH)
    load_text(ARTICLE_PATH)

    concept = get_panel(plan, "1_concept")
    results_panel = get_panel(plan, "2_results")
    takeaway = get_panel(plan, "3_takeaway")

    render_concept(concept, plan, results)
    render_results(results_panel, plan, results)
    render_takeaway(takeaway, plan, results)


if __name__ == "__main__":
    main()
