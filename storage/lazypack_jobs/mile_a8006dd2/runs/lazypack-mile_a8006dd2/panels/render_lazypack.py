#!/usr/bin/env python3
"""Render the three data-bound lazy-pack panels for the K1420 reader article.

Every displayed number is resolved from the results JSON through the field path
declared in the strict plan. Missing evidence, fields, formats, or panel blocks
raise immediately instead of producing a partial or fabricated graphic.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import textwrap
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle


RESULTS_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1420/k1420_results.json"
)
README_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1420/README.md"
)
PLAN_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_a8006dd2/runs/lazypack-mile_a8006dd2/plan.json"
)
ARTICLE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_a8006dd2/runs/lazypack-mile_a8006dd2/panels/"
    "mile_a8006dd2_article.md"
)
out_dir = (
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_a8006dd2/runs/lazypack-mile_a8006dd2/panels"
)

WIDTH = 1600
HEIGHT = 1000
DPI = 150

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False

NAVY = "#142A3A"
NAVY_2 = "#1E4158"
BLUE = "#1E6F9F"
BLUE_SOFT = "#E8F2F7"
TEAL = "#167B72"
TEAL_SOFT = "#E4F3F0"
RED = "#B8423A"
RED_SOFT = "#F8EAE8"
AMBER = "#D5A63C"
INK = "#17242D"
MUTED = "#5D6B75"
LIGHT_MUTED = "#8A969E"
PAPER = "#FFFFFF"
PANEL = "#F4F7F8"
LINE = "#DCE3E7"


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_text(path: Path) -> str:
    with path.open("r", encoding="utf-8") as handle:
        value = handle.read()
    if not value.strip():
        raise ValueError(f"Evidence text is empty: {path}")
    return value


def require(mapping: Any, key: str, context: str) -> Any:
    if not isinstance(mapping, dict) or key not in mapping:
        raise KeyError(f"Missing {context}.{key}")
    return mapping[key]


def resolve_path(data: Any, dotted_path: str) -> Any:
    current = data
    for component in dotted_path.split("."):
        if not isinstance(current, dict) or component not in current:
            raise KeyError(f"Missing results field: {dotted_path}")
        current = current[component]
    if current is None:
        raise ValueError(f"Null results field: {dotted_path}")
    return current


def numeric_value(value: Any, dotted_path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"Expected a number at {dotted_path}, got {type(value).__name__}")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"Non-finite number at {dotted_path}")
    return number


def format_metric(results: dict[str, Any], block: dict[str, Any]) -> str:
    value_spec = require(block, "value", "metric")
    source = require(value_spec, "source", "metric.value")
    if source != "result":
        raise ValueError(f"Unsupported metric source: {source!r}")

    dotted_path = require(value_spec, "path", "metric.value")
    raw_value = resolve_path(results, dotted_path)
    number = numeric_value(raw_value, dotted_path)
    format_spec = require(value_spec, "format", "metric.value")
    kind = require(format_spec, "kind", "metric.value.format")

    if kind == "integer":
        if not number.is_integer():
            raise ValueError(f"Expected an integer at {dotted_path}, got {raw_value!r}")
        rendered = f"{int(number):,}"
    elif kind == "percent":
        digits = require(format_spec, "digits", "metric.value.format")
        if isinstance(digits, bool) or not isinstance(digits, int) or digits < 0:
            raise ValueError(f"Invalid percent digits for {dotted_path}: {digits!r}")
        rendered = f"{number * 100:.{digits}f}%"
    else:
        raise ValueError(f"Unsupported metric format at {dotted_path}: {kind!r}")

    suffix = format_spec.get("suffix", "")
    if not isinstance(suffix, str):
        raise TypeError(f"Metric suffix must be a string at {dotted_path}")
    return rendered + suffix


def load_evidence() -> tuple[dict[str, Any], dict[str, Any]]:
    results = load_json(RESULTS_PATH)
    plan = load_json(PLAN_PATH)

    # Read the complete evidence package so a missing package member fails loudly.
    load_text(README_PATH)
    load_text(ARTICLE_PATH)

    result_evidence = require(require(plan, "evidence", "plan"), "result", "plan.evidence")
    expected_sha256 = require(result_evidence, "sha256", "plan.evidence.result")
    actual_sha256 = hashlib.sha256(RESULTS_PATH.read_bytes()).hexdigest()
    if actual_sha256 != expected_sha256:
        raise ValueError(
            "Results JSON does not match plan evidence hash: "
            f"expected {expected_sha256}, got {actual_sha256}"
        )

    source_label = require(result_evidence, "label", "plan.evidence.result")
    if not isinstance(source_label, str) or not source_label.strip():
        raise ValueError("plan.evidence.result.label must be a non-empty string")

    return results, plan


def panel_map(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    panels = require(plan, "panels", "plan")
    if not isinstance(panels, list):
        raise TypeError("plan.panels must be a list")
    mapped: dict[str, dict[str, Any]] = {}
    for panel in panels:
        name = require(panel, "name", "panel")
        if name in mapped:
            raise ValueError(f"Duplicate panel name: {name}")
        mapped[name] = panel

    expected = {"1_method", "2_scorecard", "3_takeaway"}
    if set(mapped) != expected:
        raise ValueError(f"Expected panels {sorted(expected)}, got {sorted(mapped)}")
    return mapped


def blocks_of_kind(
    panel: dict[str, Any], kind: str, expected_count: int
) -> list[dict[str, Any]]:
    blocks = require(panel, "blocks", f"panel {require(panel, 'name', 'panel')}")
    if not isinstance(blocks, list):
        raise TypeError("panel.blocks must be a list")
    selected = [block for block in blocks if require(block, "kind", "panel.block") == kind]
    if len(selected) != expected_count:
        raise ValueError(
            f"Panel {panel['name']} must contain {expected_count} {kind} blocks; "
            f"got {len(selected)}"
        )
    return selected


def new_figure(background: str = PAPER) -> tuple[Any, Any]:
    figure = plt.figure(
        figsize=(WIDTH / DPI, HEIGHT / DPI),
        dpi=DPI,
        facecolor=background,
    )
    axes = figure.add_axes([0, 0, 1, 1])
    axes.set_xlim(0, 1)
    axes.set_ylim(0, 1)
    axes.axis("off")
    return figure, axes


def rounded_box(
    axes: Any,
    x: float,
    y: float,
    width: float,
    height: float,
    facecolor: str,
    edgecolor: str = "none",
    linewidth: float = 1.0,
    radius: float = 0.018,
) -> None:
    axes.add_patch(
        FancyBboxPatch(
            (x, y),
            width,
            height,
            boxstyle=f"round,pad=0.0001,rounding_size={radius}",
            linewidth=linewidth,
            edgecolor=edgecolor,
            facecolor=facecolor,
            transform=axes.transAxes,
        )
    )


def wrap_text(value: str, width: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Panel text must be a non-empty string")
    return "\n".join(
        textwrap.wrap(
            value,
            width=width,
            break_long_words=True,
            break_on_hyphens=False,
            replace_whitespace=False,
        )
    )


def draw_header(
    axes: Any,
    title: str,
    *,
    dark: bool,
) -> None:
    if dark:
        axes.add_patch(
            Rectangle(
                (0, 0.82),
                1,
                0.18,
                transform=axes.transAxes,
                facecolor=NAVY,
                edgecolor="none",
            )
        )
        title_color = PAPER
        line_color = AMBER
    else:
        title_color = INK
        line_color = BLUE

    axes.text(
        0.065,
        0.912,
        title,
        transform=axes.transAxes,
        fontsize=34,
        fontweight="bold",
        color=title_color,
        ha="left",
        va="center",
    )
    axes.add_patch(
        Rectangle(
            (0.065, 0.852),
            0.075,
            0.008,
            transform=axes.transAxes,
            facecolor=line_color,
            edgecolor="none",
        )
    )


def draw_footer(axes: Any, source_label: str) -> None:
    axes.plot(
        [0.065, 0.935],
        [0.087, 0.087],
        transform=axes.transAxes,
        color=LINE,
        linewidth=1.2,
    )
    axes.text(
        0.065,
        0.045,
        f"資料來源｜{source_label}",
        transform=axes.transAxes,
        fontsize=12.5,
        color=MUTED,
        ha="left",
        va="center",
    )


def metric_label(block: dict[str, Any]) -> str:
    label = require(block, "label", "metric")
    if not isinstance(label, str) or not label.strip():
        raise ValueError("Metric label must be a non-empty string")
    return label


def metric_note(block: dict[str, Any]) -> str | None:
    note = block.get("note")
    if note is not None and (not isinstance(note, str) or not note.strip()):
        raise ValueError("Metric note must be a non-empty string when present")
    return note


def draw_metric_card(
    axes: Any,
    results: dict[str, Any],
    block: dict[str, Any],
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    facecolor: str,
    accent: str,
    value_color: str = INK,
    value_size: float = 43,
) -> None:
    rounded_box(axes, x, y, width, height, facecolor)
    axes.add_patch(
        Rectangle(
            (x, y),
            0.007,
            height,
            transform=axes.transAxes,
            facecolor=accent,
            edgecolor="none",
        )
    )
    axes.text(
        x + 0.032,
        y + height - 0.058,
        metric_label(block),
        transform=axes.transAxes,
        fontsize=17,
        fontweight="bold",
        color=MUTED,
        ha="left",
        va="center",
    )
    axes.text(
        x + 0.032,
        y + height * 0.49,
        format_metric(results, block),
        transform=axes.transAxes,
        fontsize=value_size,
        fontweight="bold",
        color=value_color,
        ha="left",
        va="center",
    )
    note = metric_note(block)
    if note:
        axes.text(
            x + 0.032,
            y + 0.038,
            wrap_text(note, 25),
            transform=axes.transAxes,
            fontsize=13.5,
            color=MUTED,
            ha="left",
            va="center",
            linespacing=1.35,
        )


def text_block_parts(block: dict[str, Any]) -> tuple[str, str]:
    heading = require(block, "heading", "text block")
    body_items = require(block, "body", "text block")
    if not isinstance(heading, str) or not heading.strip():
        raise ValueError("Text block heading must be a non-empty string")
    if (
        not isinstance(body_items, list)
        or not body_items
        or any(not isinstance(item, str) or not item.strip() for item in body_items)
    ):
        raise ValueError("Text block body must be a non-empty list of strings")
    return heading, "\n".join(body_items)


def source_label_from_plan(plan: dict[str, Any]) -> str:
    evidence = require(plan, "evidence", "plan")
    result_evidence = require(evidence, "result", "plan.evidence")
    return require(result_evidence, "label", "plan.evidence.result")


def render_method(
    results: dict[str, Any],
    plan: dict[str, Any],
    panel: dict[str, Any],
) -> None:
    if require(panel, "style", "panel 1_method") != "professional":
        raise ValueError("Panel 1_method must use professional style")
    metrics = blocks_of_kind(panel, "metric", 2)
    text_blocks = blocks_of_kind(panel, "text", 1)
    heading, body = text_block_parts(text_blocks[0])

    figure, axes = new_figure()
    draw_header(axes, require(panel, "title", "panel 1_method"), dark=True)

    draw_metric_card(
        axes,
        results,
        metrics[0],
        x=0.065,
        y=0.50,
        width=0.41,
        height=0.27,
        facecolor=PANEL,
        accent=BLUE,
        value_color=NAVY_2,
    )
    draw_metric_card(
        axes,
        results,
        metrics[1],
        x=0.525,
        y=0.50,
        width=0.41,
        height=0.27,
        facecolor=TEAL_SOFT,
        accent=TEAL,
        value_color=TEAL,
    )

    rounded_box(
        axes,
        0.065,
        0.145,
        0.87,
        0.305,
        PAPER,
        edgecolor=LINE,
        linewidth=1.4,
    )
    axes.text(
        0.095,
        0.397,
        heading,
        transform=axes.transAxes,
        fontsize=21,
        fontweight="bold",
        color=NAVY,
        ha="left",
        va="center",
    )
    axes.text(
        0.095,
        0.345,
        # At 150 DPI, a 17 pt Heiti TC CJK glyph is about 35 px wide.
        # Keep each line comfortably inside the card's 1,344 px text area.
        wrap_text(body, 34),
        transform=axes.transAxes,
        fontsize=17,
        color=INK,
        ha="left",
        va="top",
        linespacing=1.6,
    )

    draw_footer(axes, source_label_from_plan(plan))
    save_panel(figure, panel)


def render_scorecard(
    results: dict[str, Any],
    plan: dict[str, Any],
    panel: dict[str, Any],
) -> None:
    if require(panel, "style", "panel 2_scorecard") != "bento-grid":
        raise ValueError("Panel 2_scorecard must use bento-grid style")
    metrics = blocks_of_kind(panel, "metric", 4)

    figure, axes = new_figure("#FBFCFC")
    draw_header(axes, require(panel, "title", "panel 2_scorecard"), dark=False)

    card_specs = [
        (0.065, 0.49, BLUE_SOFT, BLUE, NAVY_2),
        (0.515, 0.49, RED_SOFT, RED, RED),
        (0.065, 0.16, PANEL, BLUE, NAVY_2),
        (0.515, 0.16, "#F7EFEE", RED, RED),
    ]
    for block, (x, y, facecolor, accent, value_color) in zip(metrics, card_specs):
        draw_metric_card(
            axes,
            results,
            block,
            x=x,
            y=y,
            width=0.42,
            height=0.29,
            facecolor=facecolor,
            accent=accent,
            value_color=value_color,
            value_size=47,
        )

    draw_footer(axes, source_label_from_plan(plan))
    save_panel(figure, panel)


def render_takeaway(
    results: dict[str, Any],
    plan: dict[str, Any],
    panel: dict[str, Any],
) -> None:
    if require(panel, "style", "panel 3_takeaway") != "editorial":
        raise ValueError("Panel 3_takeaway must use editorial style")
    metrics = blocks_of_kind(panel, "metric", 2)
    text_blocks = blocks_of_kind(panel, "text", 1)
    heading, body = text_block_parts(text_blocks[0])

    figure, axes = new_figure("#FBFAF7")
    draw_header(axes, require(panel, "title", "panel 3_takeaway"), dark=False)

    rounded_box(axes, 0.065, 0.135, 0.49, 0.65, NAVY, radius=0.024)
    axes.add_patch(
        Rectangle(
            (0.065, 0.135),
            0.012,
            0.65,
            transform=axes.transAxes,
            facecolor=AMBER,
            edgecolor="none",
        )
    )
    axes.text(
        0.105,
        0.695,
        metric_label(metrics[0]),
        transform=axes.transAxes,
        fontsize=21,
        fontweight="bold",
        color="#C9D6DE",
        ha="left",
        va="center",
    )
    axes.text(
        0.105,
        0.515,
        format_metric(results, metrics[0]),
        transform=axes.transAxes,
        fontsize=92,
        fontweight="bold",
        color=PAPER,
        ha="left",
        va="center",
    )
    axes.plot(
        [0.105, 0.315],
        [0.38, 0.38],
        transform=axes.transAxes,
        color=AMBER,
        linewidth=4,
        solid_capstyle="butt",
    )
    first_note = metric_note(metrics[0])
    if first_note is None:
        raise ValueError("Primary takeaway metric requires its plan note")
    axes.text(
        0.105,
        0.32,
        wrap_text(first_note, 18),
        transform=axes.transAxes,
        fontsize=17,
        color="#E2E9ED",
        ha="left",
        va="top",
        linespacing=1.55,
    )

    rounded_box(
        axes,
        0.60,
        0.57,
        0.335,
        0.215,
        PAPER,
        edgecolor=LINE,
        linewidth=1.3,
    )
    axes.text(
        0.635,
        0.715,
        metric_label(metrics[1]),
        transform=axes.transAxes,
        fontsize=17,
        fontweight="bold",
        color=MUTED,
        ha="left",
        va="center",
    )
    axes.text(
        0.635,
        0.625,
        format_metric(results, metrics[1]),
        transform=axes.transAxes,
        fontsize=44,
        fontweight="bold",
        color=NAVY_2,
        ha="left",
        va="center",
    )

    rounded_box(
        axes,
        0.60,
        0.135,
        0.335,
        0.39,
        PAPER,
        edgecolor=LINE,
        linewidth=1.3,
    )
    axes.text(
        0.635,
        0.465,
        heading,
        transform=axes.transAxes,
        fontsize=20,
        fontweight="bold",
        color=RED,
        ha="left",
        va="center",
    )
    axes.text(
        0.635,
        0.405,
        # The usable text width is 480 px; 14 Heiti TC glyphs leave enough
        # horizontal padding while the six wrapped lines still fit vertically.
        wrap_text(body, 14),
        transform=axes.transAxes,
        fontsize=14.5,
        color=INK,
        ha="left",
        va="top",
        linespacing=1.52,
    )

    draw_footer(axes, source_label_from_plan(plan))
    save_panel(figure, panel)


def save_panel(figure: Any, panel: dict[str, Any]) -> None:
    name = require(panel, "name", "panel")
    alt = require(panel, "alt", f"panel {name}")
    if not isinstance(alt, str) or not alt.strip():
        raise ValueError(f"Panel {name} alt must be a non-empty string")

    output_path = os.path.join(out_dir, f"{name}.png")
    figure.savefig(
        output_path,
        dpi=DPI,
        facecolor=figure.get_facecolor(),
        edgecolor="none",
        bbox_inches=None,
        pad_inches=0,
        metadata={"Description": alt},
    )
    plt.close(figure)


def main() -> None:
    os.makedirs(out_dir, exist_ok=True)
    results, plan = load_evidence()
    panels = panel_map(plan)

    render_method(results, plan, panels["1_method"])
    render_scorecard(results, plan, panels["2_scorecard"])
    render_takeaway(results, plan, panels["3_takeaway"])


if __name__ == "__main__":
    main()
