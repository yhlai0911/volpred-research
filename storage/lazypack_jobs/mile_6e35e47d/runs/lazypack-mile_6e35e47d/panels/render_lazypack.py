#!/usr/bin/env python3
"""Render the three data-bound PNG panels for mile_6e35e47d."""

from __future__ import annotations

import json
import os
import textwrap
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyBboxPatch, Rectangle


ORIGINAL_RESULTS_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1623/k1623_results.json"
)
README_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1623/README.md"
)
PLAN_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_6e35e47d/runs/lazypack-mile_6e35e47d/plan.json"
)
RESULTS_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1623/"
    "k1623_rev2_results.json"
)
ARTICLE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_6e35e47d/runs/lazypack-mile_6e35e47d/panels/"
    "mile_6e35e47d_article.md"
)
OUT_DIR = (
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_6e35e47d/runs/lazypack-mile_6e35e47d/panels"
)

EXPECTED_PANEL_NAMES = {
    "panel_question",
    "panel_result",
    "panel_takeaway",
}
EXPECTED_SOURCE_LABEL = (
    "experiment K1623 rev2 results (loss-function dependence of "
    "ARFIMA-vs-HAR ranking; HAC DM tests with multiple-comparison correction)"
)

NAVY = "#142B45"
NAVY_2 = "#1E3A58"
BLUE = "#2F6B9A"
TEAL = "#187B79"
GOLD = "#C28A2C"
INK = "#172534"
MUTED = "#536273"
PALE = "#F3F6F9"
LINE = "#DCE3EA"
WHITE = "#FFFFFF"

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError(f"Evidence file is empty: {path}")
    return text


def resolve_json_pointer(document: Any, pointer: str) -> Any:
    """Resolve an RFC 6901-style JSON pointer, raising on every mismatch."""
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValueError(f"Invalid JSON pointer: {pointer!r}")
    current = document
    for raw_token in pointer[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            current = current[token]
        elif isinstance(current, list):
            try:
                index = int(token)
            except ValueError as exc:
                raise TypeError(
                    f"List index in JSON pointer must be an integer: {pointer}"
                ) from exc
            current = current[index]
        else:
            raise TypeError(
                f"Cannot descend through {type(current).__name__} at {pointer}"
            )
    return current


def format_bound_value(value_spec: dict[str, Any], evidence: dict[str, Any]) -> str:
    source_key = value_spec["source"]
    pointer = value_spec["path"]
    format_spec = value_spec["format"]
    if source_key not in evidence:
        raise KeyError(f"Unknown evidence source: {source_key}")
    value = resolve_json_pointer(evidence[source_key], pointer)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"Expected a numeric value at {pointer}, got {value!r}")
    if format_spec["kind"] != "number":
        raise ValueError(f"Unsupported format kind at {pointer}: {format_spec}")
    digits = format_spec["digits"]
    if not isinstance(digits, int) or digits < 0:
        raise ValueError(f"Invalid number of digits at {pointer}: {digits!r}")
    return f"{value:.{digits}f}"


def wrap_zh(text: str, width: int) -> str:
    """Deterministically wrap Chinese copy without relying on renderer clipping."""
    return "\n".join(
        textwrap.wrap(
            text,
            width=width,
            break_long_words=True,
            break_on_hyphens=False,
            replace_whitespace=False,
        )
    )


def add_round_rect(
    ax: plt.Axes,
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    facecolor: str,
    edgecolor: str = "none",
    linewidth: float = 1.0,
    radius: float = 0.018,
) -> FancyBboxPatch:
    patch = FancyBboxPatch(
        (x, y),
        width,
        height,
        boxstyle=f"round,pad=0.008,rounding_size={radius}",
        transform=ax.transAxes,
        facecolor=facecolor,
        edgecolor=edgecolor,
        linewidth=linewidth,
    )
    ax.add_patch(patch)
    return patch


def draw_header(ax: plt.Axes, title: str) -> None:
    ax.add_patch(
        Rectangle(
            (0, 0.79),
            1,
            0.21,
            transform=ax.transAxes,
            facecolor=NAVY,
            edgecolor="none",
        )
    )
    ax.add_patch(
        Rectangle(
            (0.055, 0.835),
            0.008,
            0.11,
            transform=ax.transAxes,
            facecolor=GOLD,
            edgecolor="none",
        )
    )
    ax.text(
        0.083,
        0.89,
        wrap_zh(title, 23),
        transform=ax.transAxes,
        ha="left",
        va="center",
        color=WHITE,
        fontsize=29,
        fontweight="bold",
        linespacing=1.18,
    )


def draw_text_block(ax: plt.Axes, block: dict[str, Any]) -> None:
    add_round_rect(
        ax,
        0.055,
        0.485,
        0.89,
        0.245,
        facecolor=PALE,
        edgecolor=LINE,
        linewidth=1.1,
    )
    ax.add_patch(
        Rectangle(
            (0.055, 0.485),
            0.012,
            0.245,
            transform=ax.transAxes,
            facecolor=TEAL,
            edgecolor="none",
        )
    )
    ax.text(
        0.088,
        0.685,
        block["heading"],
        transform=ax.transAxes,
        ha="left",
        va="center",
        fontsize=19,
        fontweight="bold",
        color=INK,
    )
    body = block["body"]
    if not isinstance(body, list) or not body:
        raise ValueError("Text block body must be a non-empty list")
    wrapped_paragraphs = [wrap_zh(str(paragraph), 48) for paragraph in body]
    ax.text(
        0.088,
        0.642,
        "\n\n".join(wrapped_paragraphs),
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=14.5,
        color=MUTED,
        linespacing=1.42,
    )


def draw_metric_cards(
    ax: plt.Axes,
    metric_blocks: list[dict[str, Any]],
    evidence: dict[str, Any],
) -> None:
    count = len(metric_blocks)
    if count not in (2, 3):
        raise ValueError(f"Expected two or three metric blocks, got {count}")
    gap = 0.025
    total_width = 0.89
    card_width = (total_width - gap * (count - 1)) / count
    accents = [BLUE, TEAL, GOLD]
    for index, block in enumerate(metric_blocks):
        x = 0.055 + index * (card_width + gap)
        add_round_rect(
            ax,
            x,
            0.155,
            card_width,
            0.255,
            facecolor=WHITE,
            edgecolor=LINE,
            linewidth=1.2,
        )
        ax.add_patch(
            Rectangle(
                (x, 0.392),
                card_width,
                0.018,
                transform=ax.transAxes,
                facecolor=accents[index],
                edgecolor="none",
            )
        )
        ax.add_patch(
            Circle(
                (x + 0.045, 0.345),
                0.015,
                transform=ax.transAxes,
                facecolor=accents[index],
                edgecolor="none",
            )
        )
        rendered_value = format_bound_value(block["value"], evidence)
        ax.text(
            x + card_width / 2,
            0.285,
            rendered_value,
            transform=ax.transAxes,
            ha="center",
            va="center",
            fontsize=38 if count == 3 else 42,
            fontweight="bold",
            color=NAVY_2,
        )
        label_width = 18 if count == 3 else 25
        ax.text(
            x + card_width / 2,
            0.205,
            wrap_zh(block["label"], label_width),
            transform=ax.transAxes,
            ha="center",
            va="center",
            fontsize=12.5 if count == 3 else 14,
            color=MUTED,
            linespacing=1.28,
        )


def draw_source_footer(
    ax: plt.Axes,
    source_keys: list[str],
    source_labels: dict[str, str],
) -> None:
    if not source_keys:
        raise ValueError("Every panel must contain at least one source")
    labels = [source_labels[key] for key in source_keys]
    source_line = "資料來源：" + "；".join(labels)
    ax.plot(
        [0.055, 0.945],
        [0.108, 0.108],
        transform=ax.transAxes,
        color=LINE,
        linewidth=1.0,
    )
    ax.text(
        0.055,
        0.071,
        "\n".join(
            textwrap.wrap(
                source_line,
                width=142,
                break_long_words=False,
                break_on_hyphens=False,
            )
        ),
        transform=ax.transAxes,
        ha="left",
        va="center",
        fontsize=8.3,
        color=MUTED,
        linespacing=1.25,
    )


def render_panel(
    panel: dict[str, Any],
    evidence: dict[str, Any],
    source_labels: dict[str, str],
) -> None:
    name = panel["name"]
    if name not in EXPECTED_PANEL_NAMES:
        raise ValueError(f"Unexpected panel name: {name}")
    if panel["style"] != "professional":
        raise ValueError(f"Unexpected panel style for {name}: {panel['style']}")

    blocks = panel["blocks"]
    text_blocks = [block for block in blocks if block["kind"] == "text"]
    metric_blocks = [block for block in blocks if block["kind"] == "metric"]
    if len(text_blocks) != 1:
        raise ValueError(f"{name} must have exactly one text block")
    if len(text_blocks) + len(metric_blocks) != len(blocks):
        raise ValueError(f"{name} contains an unsupported block kind")

    figure = plt.figure(figsize=(10.6666667, 6.6666667), dpi=150, facecolor=WHITE)
    ax = figure.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    draw_header(ax, panel["title"])
    draw_text_block(ax, text_blocks[0])
    draw_metric_cards(ax, metric_blocks, evidence)
    draw_source_footer(ax, panel["sources"], source_labels)

    output_path = Path(OUT_DIR) / f"{name}.png"
    figure.savefig(
        output_path,
        dpi=150,
        facecolor=WHITE,
        metadata={
            "Title": panel["title"],
            "Description": panel["alt"],
            "Software": "VolPred data-bound matplotlib renderer",
        },
    )
    plt.close(figure)


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)

    # Read the complete evidence package. The original result, README, and
    # article are intentionally not used for numbers: rev2 is authoritative.
    original_results = load_json(ORIGINAL_RESULTS_PATH)
    readme = load_text(README_PATH)
    plan = load_json(PLAN_PATH)
    results = load_json(RESULTS_PATH)
    article = load_text(ARTICLE_PATH)
    if not isinstance(original_results, dict):
        raise TypeError("Original results evidence must be a JSON object")
    if not readme or not article:
        raise ValueError("README and article evidence must be non-empty")

    evidence_plan = plan["evidence"]
    results_plan = evidence_plan["results"]
    if results_plan["label"] != EXPECTED_SOURCE_LABEL:
        raise ValueError("Strict-plan results source label changed unexpectedly")
    if Path(results_plan["path"]).as_posix() != (
        "experiments/k1623/k1623_rev2_results.json"
    ):
        raise ValueError("Strict-plan results path changed unexpectedly")

    panels = plan["panels"]
    panel_names = {panel["name"] for panel in panels}
    if panel_names != EXPECTED_PANEL_NAMES or len(panels) != len(
        EXPECTED_PANEL_NAMES
    ):
        raise ValueError(f"Unexpected strict-plan panel set: {sorted(panel_names)}")

    evidence = {"results": results}
    source_labels = {"results": results_plan["label"]}
    for panel in panels:
        render_panel(panel, evidence, source_labels)


if __name__ == "__main__":
    main()
