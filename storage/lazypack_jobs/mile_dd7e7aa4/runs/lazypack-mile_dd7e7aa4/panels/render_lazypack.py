#!/usr/bin/env python3
"""Render the three data-bound PNG panels for the mile_dd7e7aa4 article."""

from __future__ import annotations

import json
import os
import textwrap
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle


PLAN_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_dd7e7aa4/runs/lazypack-mile_dd7e7aa4/plan.json"
)
RESULTS_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1448/k1448_results.json"
)
ARTICLE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_dd7e7aa4/runs/lazypack-mile_dd7e7aa4/panels/"
    "mile_dd7e7aa4_article.md"
)
out_dir = (
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_dd7e7aa4/runs/lazypack-mile_dd7e7aa4/panels"
)

WIDTH_PX = 1600
HEIGHT_PX = 1000
DPI = 150

NAVY = "#14263D"
INK = "#182230"
MUTED = "#536273"
LINE = "#D9E1E8"
PAPER = "#F4F7F9"
WHITE = "#FFFFFF"
TEAL = "#087F8C"
TEAL_LIGHT = "#E4F3F4"
BLUE = "#2D5F8B"
BLUE_LIGHT = "#E8F0F7"
AMBER = "#B66A16"
AMBER_LIGHT = "#F8EEDF"
COOL = "#50718E"
WARM = "#C56B35"

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_evidence() -> tuple[dict[str, Any], dict[str, Any]]:
    plan = load_json(PLAN_PATH)
    results = load_json(RESULTS_PATH)
    # The article is part of the evidence package. Reading it here also makes a
    # missing or unreadable article fail loudly before any output is written.
    article = ARTICLE_PATH.read_text(encoding="utf-8")
    if not article.strip():
        raise ValueError(f"Article evidence is empty: {ARTICLE_PATH}")

    if not isinstance(plan, dict) or not isinstance(results, dict):
        raise TypeError("plan.json and results.json must each contain a JSON object")
    evidence = require_dict(plan, "evidence")
    result_spec = require_dict(evidence, "results")
    if require_string(result_spec, "label") == "":
        raise ValueError("plan evidence.results.label must not be empty")
    return plan, results


def require_dict(mapping: dict[str, Any], key: str) -> dict[str, Any]:
    value = mapping[key]
    if not isinstance(value, dict):
        raise TypeError(f"Expected object at {key}")
    return value


def require_list(mapping: dict[str, Any], key: str) -> list[Any]:
    value = mapping[key]
    if not isinstance(value, list):
        raise TypeError(f"Expected array at {key}")
    return value


def require_string(mapping: dict[str, Any], key: str) -> str:
    value = mapping[key]
    if not isinstance(value, str):
        raise TypeError(f"Expected string at {key}")
    return value


def resolve_json_pointer(document: Any, pointer: str) -> Any:
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValueError(f"Expected an absolute JSON Pointer, got {pointer!r}")
    current = document
    for raw_token in pointer[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            current = current[token]
        elif isinstance(current, list):
            current = current[int(token)]
        else:
            raise KeyError(f"Cannot descend through {token!r} in {pointer!r}")
    return current


def format_bound_value(value_spec: dict[str, Any], results: dict[str, Any]) -> str:
    source = require_string(value_spec, "source")
    if source != "results":
        raise KeyError(f"Unsupported evidence source: {source}")
    pointer = require_string(value_spec, "path")
    raw_value = resolve_json_pointer(results, pointer)
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        raise TypeError(f"Expected a number at {pointer}, got {type(raw_value).__name__}")

    format_spec = require_dict(value_spec, "format")
    if require_string(format_spec, "kind") != "number":
        raise ValueError(f"Unsupported number format at {pointer}")
    digits = format_spec["digits"]
    if not isinstance(digits, int) or isinstance(digits, bool) or digits < 0:
        raise TypeError(f"digits must be a non-negative integer at {pointer}")
    return f"{raw_value:.{digits}f}"


def panel_by_name(plan: dict[str, Any], name: str) -> dict[str, Any]:
    panels = require_list(plan, "panels")
    matches = [
        panel
        for panel in panels
        if isinstance(panel, dict) and panel.get("name") == name
    ]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one panel named {name!r}")
    return matches[0]


def text_block(panel: dict[str, Any]) -> dict[str, Any]:
    matches = [
        block
        for block in require_list(panel, "blocks")
        if isinstance(block, dict) and block.get("kind") == "text"
    ]
    if len(matches) != 1:
        raise ValueError(f"Expected one text block in {panel.get('name')!r}")
    require_string(matches[0], "heading")
    bodies = require_list(matches[0], "body")
    if not bodies or not all(isinstance(item, str) for item in bodies):
        raise TypeError(f"Text block body must be a non-empty string array")
    return matches[0]


def metric_blocks(panel: dict[str, Any], count: int) -> list[dict[str, Any]]:
    matches = [
        block
        for block in require_list(panel, "blocks")
        if isinstance(block, dict) and block.get("kind") == "metric"
    ]
    if len(matches) != count:
        raise ValueError(
            f"Expected {count} metric blocks in {panel.get('name')!r}, "
            f"found {len(matches)}"
        )
    for block in matches:
        require_string(block, "label")
        require_dict(block, "value")
    return matches


def wrap(text: str, width: int) -> str:
    return "\n".join(
        textwrap.wrap(
            text,
            width=width,
            break_long_words=True,
            break_on_hyphens=False,
            replace_whitespace=False,
        )
    )


def new_figure() -> tuple[plt.Figure, plt.Axes]:
    fig = plt.figure(
        figsize=(WIDTH_PX / DPI, HEIGHT_PX / DPI),
        dpi=DPI,
        facecolor=WHITE,
    )
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    return fig, ax


def rounded_box(
    ax: plt.Axes,
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    facecolor: str,
    edgecolor: str = LINE,
    linewidth: float = 1.2,
    radius: float = 0.018,
) -> None:
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            width,
            height,
            boxstyle=f"round,pad=0.008,rounding_size={radius}",
            facecolor=facecolor,
            edgecolor=edgecolor,
            linewidth=linewidth,
            transform=ax.transAxes,
        )
    )


def draw_header(fig: plt.Figure, ax: plt.Axes, panel: dict[str, Any]) -> None:
    ax.add_patch(
        Rectangle(
            (0, 0.84),
            1,
            0.16,
            facecolor=NAVY,
            edgecolor=NAVY,
            transform=ax.transAxes,
        )
    )
    fig.text(
        0.065,
        0.925,
        require_string(panel, "title"),
        color=WHITE,
        fontsize=30,
        fontweight="bold",
        ha="left",
        va="center",
    )
    fig.text(
        0.065,
        0.785,
        # CJK glyphs are substantially wider than the Latin-heavy source
        # labels.  Keep this below the measured one-line capacity of the
        # 0.87-wide text area so the alt copy always wraps inside the canvas.
        wrap(require_string(panel, "alt"), 42),
        color=MUTED,
        fontsize=14,
        linespacing=1.35,
        ha="left",
        va="top",
    )


def draw_footer(
    fig: plt.Figure, ax: plt.Axes, panel: dict[str, Any], plan: dict[str, Any]
) -> None:
    sources = require_list(panel, "sources")
    evidence = require_dict(plan, "evidence")
    labels: list[str] = []
    for source in sources:
        if not isinstance(source, str):
            raise TypeError("Panel sources must be strings")
        labels.append(require_string(require_dict(evidence, source), "label"))
    source_text = "資料來源：" + "；".join(labels)

    ax.plot(
        [0.055, 0.945],
        [0.075, 0.075],
        color=LINE,
        linewidth=1,
        transform=ax.transAxes,
    )
    fig.text(
        0.055,
        0.055,
        wrap(source_text, 112),
        color=MUTED,
        fontsize=8.3,
        linespacing=1.25,
        ha="left",
        va="top",
    )


def draw_metric_card(
    fig: plt.Figure,
    ax: plt.Axes,
    block: dict[str, Any],
    results: dict[str, Any],
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    accent: str,
    fill: str,
    label_width: int,
) -> None:
    rounded_box(ax, x, y, width, height, facecolor=fill, edgecolor=accent)
    ax.add_patch(
        Rectangle(
            (x, y),
            0.009,
            height,
            facecolor=accent,
            edgecolor=accent,
            transform=ax.transAxes,
        )
    )
    fig.text(
        x + 0.028,
        y + height - 0.032,
        wrap(require_string(block, "label"), label_width),
        color=MUTED,
        fontsize=10.8,
        linespacing=1.25,
        ha="left",
        va="top",
    )
    rendered = format_bound_value(require_dict(block, "value"), results)
    fig.text(
        x + 0.028,
        y + 0.025,
        rendered,
        color=accent,
        fontsize=25,
        fontweight="bold",
        ha="left",
        va="bottom",
    )


def draw_bullets(
    fig: plt.Figure,
    lines: list[str],
    *,
    x: float,
    top: float,
    wrap_width: int,
    fontsize: float,
    step: float,
    bullet_color: str = TEAL,
) -> None:
    for index, line in enumerate(lines):
        y = top - index * step
        fig.text(
            x,
            y,
            "●",
            color=bullet_color,
            fontsize=9,
            ha="left",
            va="top",
        )
        fig.text(
            x + 0.023,
            y,
            wrap(line, wrap_width),
            color=INK,
            fontsize=fontsize,
            linespacing=1.3,
            ha="left",
            va="top",
        )


def render_question(
    plan: dict[str, Any], results: dict[str, Any], panel: dict[str, Any]
) -> None:
    fig, ax = new_figure()
    draw_header(fig, ax, panel)
    copy = text_block(panel)
    metric = metric_blocks(panel, 1)[0]

    rounded_box(ax, 0.055, 0.17, 0.57, 0.46, facecolor=PAPER)
    fig.text(
        0.085,
        0.585,
        require_string(copy, "heading"),
        color=NAVY,
        fontsize=21,
        fontweight="bold",
        ha="left",
        va="top",
    )
    bodies = require_list(copy, "body")
    draw_bullets(
        fig,
        bodies,
        x=0.086,
        top=0.515,
        # The usable width is the card width minus the bullet and both
        # insets.  At Heiti TC 13.5 pt, 26 CJK glyphs fit with safe padding.
        wrap_width=26,
        fontsize=13.5,
        step=0.112,
    )

    rounded_box(
        ax,
        0.66,
        0.17,
        0.285,
        0.46,
        facecolor=TEAL_LIGHT,
        edgecolor=TEAL,
        linewidth=1.5,
    )
    fig.text(
        0.695,
        0.565,
        wrap(require_string(metric, "label"), 13),
        color=MUTED,
        fontsize=14,
        linespacing=1.3,
        ha="left",
        va="top",
    )
    fig.text(
        0.695,
        0.39,
        format_bound_value(require_dict(metric, "value"), results),
        color=TEAL,
        fontsize=47,
        fontweight="bold",
        ha="left",
        va="center",
    )
    fig.text(
        0.695,
        0.315,
        "共同交易日",
        color=NAVY,
        fontsize=15,
        ha="left",
        va="center",
    )
    ax.plot(
        [0.695, 0.905],
        [0.27, 0.27],
        color=TEAL,
        linewidth=2.5,
        transform=ax.transAxes,
    )
    fig.text(
        0.695,
        0.235,
        "以前一日訊號對未來市場",
        color=MUTED,
        fontsize=11,
        ha="left",
        va="center",
    )

    draw_footer(fig, ax, panel, plan)
    fig.savefig(
        os.path.join(out_dir, "panel_question.png"),
        dpi=DPI,
        facecolor=WHITE,
        bbox_inches=None,
    )
    plt.close(fig)


def render_result(
    plan: dict[str, Any], results: dict[str, Any], panel: dict[str, Any]
) -> None:
    fig, ax = new_figure()
    draw_header(fig, ax, panel)
    metrics = metric_blocks(panel, 4)
    copy = text_block(panel)

    card_positions = [
        (0.055, 0.485, COOL, BLUE_LIGHT),
        (0.51, 0.485, WARM, AMBER_LIGHT),
        (0.055, 0.325, COOL, BLUE_LIGHT),
        (0.51, 0.325, WARM, AMBER_LIGHT),
    ]
    for block, (x, y, accent, fill) in zip(metrics, card_positions, strict=True):
        draw_metric_card(
            fig,
            ax,
            block,
            results,
            x=x,
            y=y,
            width=0.435,
            height=0.125,
            accent=accent,
            fill=fill,
            label_width=25,
        )

    rounded_box(ax, 0.055, 0.105, 0.89, 0.175, facecolor=PAPER)
    fig.text(
        0.082,
        0.252,
        require_string(copy, "heading"),
        color=NAVY,
        fontsize=17,
        fontweight="bold",
        ha="left",
        va="top",
    )
    bodies = require_list(copy, "body")
    columns = [0.082, 0.377, 0.672]
    for x, line in zip(columns, bodies, strict=True):
        fig.text(
            x,
            0.205,
            # Each paragraph owns one 0.25-wide column.  Fifteen Heiti TC
            # glyphs fit within that column and leave a gutter before the
            # next paragraph, preventing both clipping and overlap.
            wrap(line, 15),
            color=INK,
            fontsize=12.2,
            linespacing=1.28,
            ha="left",
            va="top",
        )

    draw_footer(fig, ax, panel, plan)
    fig.savefig(
        os.path.join(out_dir, "panel_result.png"),
        dpi=DPI,
        facecolor=WHITE,
        bbox_inches=None,
    )
    plt.close(fig)


def render_takeaway(
    plan: dict[str, Any], results: dict[str, Any], panel: dict[str, Any]
) -> None:
    fig, ax = new_figure()
    draw_header(fig, ax, panel)
    metrics = metric_blocks(panel, 2)
    copy = text_block(panel)

    draw_metric_card(
        fig,
        ax,
        metrics[0],
        results,
        x=0.055,
        y=0.505,
        width=0.435,
        height=0.13,
        accent=TEAL,
        fill=TEAL_LIGHT,
        label_width=25,
    )
    draw_metric_card(
        fig,
        ax,
        metrics[1],
        results,
        x=0.51,
        y=0.505,
        width=0.435,
        height=0.13,
        accent=BLUE,
        fill=BLUE_LIGHT,
        label_width=25,
    )

    rounded_box(ax, 0.055, 0.105, 0.89, 0.35, facecolor=PAPER)
    fig.text(
        0.082,
        0.425,
        require_string(copy, "heading"),
        color=NAVY,
        fontsize=18,
        fontweight="bold",
        ha="left",
        va="top",
    )
    bodies = require_list(copy, "body")
    draw_bullets(
        fig,
        bodies,
        x=0.082,
        top=0.372,
        # Keep long CJK lines within the paper card's padded content width.
        wrap_width=44,
        fontsize=12.6,
        step=0.057,
        bullet_color=AMBER,
    )

    draw_footer(fig, ax, panel, plan)
    fig.savefig(
        os.path.join(out_dir, "panel_takeaway.png"),
        dpi=DPI,
        facecolor=WHITE,
        bbox_inches=None,
    )
    plt.close(fig)


def main() -> None:
    os.makedirs(out_dir, exist_ok=True)
    plan, results = load_evidence()
    question = panel_by_name(plan, "panel_question")
    result = panel_by_name(plan, "panel_result")
    takeaway = panel_by_name(plan, "panel_takeaway")
    render_question(plan, results, question)
    render_result(plan, results, result)
    render_takeaway(plan, results, takeaway)


if __name__ == "__main__":
    main()
