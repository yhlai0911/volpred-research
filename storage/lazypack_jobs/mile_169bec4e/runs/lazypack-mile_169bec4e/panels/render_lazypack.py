#!/usr/bin/env python3
"""Render the three data-bound PNG panels for mile_169bec4e.

All visible copy and metric specifications come from the strict plan. Numeric
values are resolved from the results JSON at render time; missing evidence is
an error. The article is also loaded as part of the evidence package so an
empty or missing article fails loudly before any output is written.
"""

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
    "mile_169bec4e/runs/lazypack-mile_169bec4e/plan.json"
)
RESULTS_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1585/k1585_results.json"
)
ARTICLE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_169bec4e/runs/lazypack-mile_169bec4e/panels/"
    "mile_169bec4e_article.md"
)
out_dir = (
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_169bec4e/runs/lazypack-mile_169bec4e/panels"
)

EXPECTED_PANELS = ("panel_question", "panel_result", "panel_takeaway")
WIDTH_PX = 1600
HEIGHT_PX = 1000
DPI = 150

NAVY = "#13283F"
INK = "#172536"
MUTED = "#526273"
BLUE = "#2878B8"
BLUE_SOFT = "#EAF3FA"
RED = "#B84949"
RED_SOFT = "#F9EEEE"
GREEN = "#23745B"
GREEN_SOFT = "#EAF5F0"
BORDER = "#D9E2EA"
PAPER = "#FFFFFF"

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def resolve_json_pointer(document: Any, pointer: str) -> Any:
    """Resolve an RFC 6901-style JSON Pointer and raise on every mismatch."""
    if pointer == "":
        return document
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValueError(f"Invalid JSON Pointer: {pointer!r}")

    current = document
    for raw_token in pointer[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            if token not in current:
                raise KeyError(f"Missing evidence field at {pointer!r}")
            current = current[token]
        elif isinstance(current, list):
            try:
                current = current[int(token)]
            except (ValueError, IndexError) as exc:
                raise KeyError(f"Missing evidence field at {pointer!r}") from exc
        else:
            raise KeyError(f"Cannot descend to evidence field at {pointer!r}")
    return current


def require_string(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} must be a non-empty string")
    return value


def format_number(value: Any, format_spec: dict[str, Any], pointer: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"Expected a number at {pointer!r}, got {type(value).__name__}")
    if format_spec.get("kind") != "number":
        raise ValueError(f"Unsupported metric format at {pointer!r}: {format_spec!r}")
    digits = format_spec.get("digits")
    if not isinstance(digits, int) or digits < 0:
        raise ValueError(f"Invalid digits at {pointer!r}: {digits!r}")
    return f"{value:.{digits}f}"


def wrap_zh(text: str, width: int) -> str:
    """Deterministically wrap CJK-heavy copy without relying on renderer wrap."""
    return "\n".join(
        textwrap.wrap(
            text,
            width=width,
            break_long_words=True,
            break_on_hyphens=False,
            replace_whitespace=False,
        )
    )


def rounded_box(
    ax: plt.Axes,
    x: float,
    y: float,
    width: float,
    height: float,
    facecolor: str,
    edgecolor: str = BORDER,
    linewidth: float = 1.0,
    radius: float = 0.018,
) -> None:
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            width,
            height,
            boxstyle=f"round,pad=0.012,rounding_size={radius}",
            transform=ax.transAxes,
            facecolor=facecolor,
            edgecolor=edgecolor,
            linewidth=linewidth,
        )
    )


def panel_theme(name: str) -> tuple[str, str]:
    if name == "panel_result":
        return RED, RED_SOFT
    if name == "panel_takeaway":
        return GREEN, GREEN_SOFT
    return BLUE, BLUE_SOFT


def metric_blocks(panel: dict[str, Any]) -> list[dict[str, Any]]:
    blocks = panel.get("blocks")
    if not isinstance(blocks, list):
        raise ValueError(f"Panel {panel.get('name')!r} has no blocks list")
    metrics = [block for block in blocks if block.get("kind") == "metric"]
    if not metrics:
        raise ValueError(f"Panel {panel.get('name')!r} has no metric blocks")
    return metrics


def text_block(panel: dict[str, Any]) -> dict[str, Any]:
    blocks = panel.get("blocks")
    if not isinstance(blocks, list):
        raise ValueError(f"Panel {panel.get('name')!r} has no blocks list")
    texts = [block for block in blocks if block.get("kind") == "text"]
    if len(texts) != 1:
        raise ValueError(
            f"Panel {panel.get('name')!r} must contain exactly one text block"
        )
    return texts[0]


def draw_metric_card(
    ax: plt.Axes,
    block: dict[str, Any],
    results: dict[str, Any],
    x: float,
    y: float,
    width: float,
    height: float,
    accent: str,
    soft: str,
) -> None:
    label = require_string(block.get("label"), "metric label")
    value_spec = block.get("value")
    if not isinstance(value_spec, dict):
        raise ValueError(f"Metric {label!r} has no value specification")
    if value_spec.get("source") != "results":
        raise ValueError(f"Metric {label!r} does not use the results evidence")
    pointer = require_string(value_spec.get("path"), f"metric path for {label}")
    fmt = value_spec.get("format")
    if not isinstance(fmt, dict):
        raise ValueError(f"Metric {label!r} has no format specification")
    value = resolve_json_pointer(results, pointer)
    rendered = format_number(value, fmt, pointer)
    compact = height < 0.15
    label_wrap = 18 if compact else 21
    label_size = 9.6 if compact else 12.2
    label_top_padding = 0.016 if compact else 0.036
    value_size = 20 if compact else 29
    value_bottom_padding = 0.018 if compact else 0.035

    rounded_box(ax, x, y, width, height, PAPER, edgecolor=BORDER)
    ax.add_patch(
        Rectangle(
            (x, y),
            0.009,
            height,
            transform=ax.transAxes,
            facecolor=accent,
            edgecolor="none",
        )
    )
    ax.text(
        x + 0.035,
        y + height - label_top_padding,
        wrap_zh(label, label_wrap),
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=label_size,
        color=MUTED,
        linespacing=1.16 if compact else 1.22,
    )
    ax.text(
        x + width - 0.035,
        y + value_bottom_padding,
        rendered,
        transform=ax.transAxes,
        ha="right",
        va="bottom",
        fontsize=value_size,
        fontweight="bold",
        color=accent,
    )
    ax.add_patch(
        Rectangle(
            (x + 0.027, y + 0.025),
            0.038,
            0.008,
            transform=ax.transAxes,
            facecolor=soft,
            edgecolor="none",
        )
    )


def render_panel(
    panel: dict[str, Any],
    results: dict[str, Any],
    evidence: dict[str, Any],
) -> None:
    name = require_string(panel.get("name"), "panel name")
    if name not in EXPECTED_PANELS:
        raise ValueError(f"Unexpected panel name: {name!r}")
    if panel.get("style") != "professional":
        raise ValueError(f"Panel {name!r} must use professional style")

    title = require_string(panel.get("title"), f"title for {name}")
    alt = require_string(panel.get("alt"), f"alt text for {name}")
    source_keys = panel.get("sources")
    if source_keys != ["results"]:
        raise ValueError(f"Panel {name!r} must cite only results evidence")
    source_label = require_string(
        evidence["results"]["label"], "results evidence label"
    )

    narrative = text_block(panel)
    heading = require_string(narrative.get("heading"), f"heading for {name}")
    body = narrative.get("body")
    if (
        not isinstance(body, list)
        or len(body) != 2
        or any(not isinstance(item, str) or not item.strip() for item in body)
    ):
        raise ValueError(f"Panel {name!r} must have exactly two body paragraphs")

    metrics = metric_blocks(panel)
    accent, soft = panel_theme(name)

    fig = plt.figure(
        figsize=(WIDTH_PX / DPI, HEIGHT_PX / DPI),
        dpi=DPI,
        facecolor=PAPER,
    )
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    # Deep title rail.
    ax.add_patch(
        Rectangle(
            (0, 0.81),
            1,
            0.19,
            transform=ax.transAxes,
            facecolor=NAVY,
            edgecolor="none",
        )
    )
    ax.add_patch(
        Rectangle(
            (0.058, 0.855),
            0.010,
            0.090,
            transform=ax.transAxes,
            facecolor=accent,
            edgecolor="none",
        )
    )
    ax.text(
        0.087,
        0.900,
        title,
        transform=ax.transAxes,
        ha="left",
        va="center",
        fontsize=29,
        fontweight="bold",
        color=PAPER,
    )

    # Alt text is rendered as a compact standfirst, keeping it distinct from
    # the title and the explanatory block.
    ax.text(
        0.07,
        0.772,
        wrap_zh(alt, 57),
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=12.4,
        color=MUTED,
        linespacing=1.32,
    )
    ax.plot(
        [0.07, 0.93],
        [0.692, 0.692],
        transform=ax.transAxes,
        color=BORDER,
        linewidth=1.0,
    )

    # Narrative area.
    rounded_box(ax, 0.06, 0.205, 0.485, 0.445, soft, edgecolor=soft)
    ax.text(
        0.087,
        0.605,
        wrap_zh(heading, 23),
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=18.5,
        fontweight="bold",
        color=INK,
        linespacing=1.25,
    )
    ax.add_patch(
        Rectangle(
            (0.087, 0.545),
            0.050,
            0.007,
            transform=ax.transAxes,
            facecolor=accent,
            edgecolor="none",
        )
    )
    ax.text(
        0.087,
        0.505,
        wrap_zh(body[0], 25),
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=13.0,
        color=INK,
        linespacing=1.42,
    )
    ax.text(
        0.087,
        0.355,
        wrap_zh(body[1], 25),
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=13.0,
        color=INK,
        linespacing=1.42,
    )

    # Metric cards use fixed, non-overlapping slots for either two or three
    # cards. Values remain visually dominant without entering the footer.
    card_x = 0.59
    card_width = 0.35
    if len(metrics) == 2:
        card_height = 0.185
        card_gap = 0.035
        card_top = 0.650
    elif len(metrics) == 3:
        card_height = 0.140
        card_gap = 0.012
        card_top = 0.650
    else:
        raise ValueError(f"Panel {name!r} has unsupported metric count")

    for index, metric in enumerate(metrics):
        card_y = card_top - card_height - index * (card_height + card_gap)
        draw_metric_card(
            ax,
            metric,
            results,
            card_x,
            card_y,
            card_width,
            card_height,
            accent,
            soft,
        )

    # The strict-plan reader-facing source label is reproduced verbatim.
    ax.plot(
        [0.06, 0.94],
        [0.145, 0.145],
        transform=ax.transAxes,
        color=BORDER,
        linewidth=1.0,
    )
    ax.text(
        0.06,
        0.113,
        "資料來源：",
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=8.2,
        fontweight="bold",
        color=MUTED,
    )
    ax.text(
        0.125,
        0.113,
        wrap_zh(source_label, 112),
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=8.2,
        color=MUTED,
        linespacing=1.25,
    )

    output_path = Path(out_dir) / f"{name}.png"
    fig.savefig(
        output_path,
        dpi=DPI,
        facecolor=PAPER,
        edgecolor="none",
        bbox_inches=None,
        pad_inches=0,
    )
    plt.close(fig)


def main() -> None:
    plan = load_json(PLAN_PATH)
    results = load_json(RESULTS_PATH)
    article = ARTICLE_PATH.read_text(encoding="utf-8")
    if not article.strip():
        raise ValueError(f"Article evidence is empty: {ARTICLE_PATH}")

    evidence = plan.get("evidence")
    if not isinstance(evidence, dict) or "results" not in evidence:
        raise KeyError("Strict plan is missing evidence.results")
    require_string(evidence["results"].get("label"), "results evidence label")

    panels = plan.get("panels")
    if not isinstance(panels, list):
        raise ValueError("Strict plan is missing panels")
    indexed = {
        require_string(panel.get("name"), "panel name"): panel for panel in panels
    }
    if set(indexed) != set(EXPECTED_PANELS):
        raise ValueError(
            f"Expected exactly {EXPECTED_PANELS!r}, got {tuple(indexed)!r}"
        )

    os.makedirs(out_dir, exist_ok=True)
    for panel_name in EXPECTED_PANELS:
        render_panel(indexed[panel_name], results, evidence)


if __name__ == "__main__":
    main()
