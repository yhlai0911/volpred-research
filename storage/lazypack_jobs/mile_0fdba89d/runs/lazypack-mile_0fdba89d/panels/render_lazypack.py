#!/usr/bin/env python3
"""Render the three data-bound PNG panels for the mile_0fdba89d article."""

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
    "mile_0fdba89d/runs/lazypack-mile_0fdba89d/plan.json"
)
RESULTS_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1705/k1705_results.json"
)
ARTICLE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_0fdba89d/runs/lazypack-mile_0fdba89d/panels/"
    "mile_0fdba89d_article.md"
)
out_dir = (
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_0fdba89d/runs/lazypack-mile_0fdba89d/panels"
)

EXPECTED_PANELS = {
    "panel_question": "panel_question.png",
    "panel_result": "panel_result.png",
    "panel_takeaway": "panel_takeaway.png",
}
EXPECTED_SOURCE_LABEL = (
    "experiment K1705 results (correction of the archived K1100c "
    "copula-superiority claim: sign convention audit plus marginal-first "
    "re-evaluation)"
)

NAVY = "#13283F"
NAVY_2 = "#203A55"
INK = "#172536"
MUTED = "#526174"
PAPER = "#F4F7FA"
WHITE = "#FFFFFF"
LINE = "#D9E1E8"
BLUE = "#2670A8"
BLUE_PALE = "#E8F1F8"
AMBER = "#C07A16"
AMBER_PALE = "#FAF0DE"
RED = "#B84C4C"
RED_PALE = "#F8E7E7"

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def resolve_json_pointer(document: Any, pointer: str) -> Any:
    """Resolve an RFC 6901-style JSON Pointer, raising on every bad segment."""
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValueError(f"Invalid JSON Pointer: {pointer!r}")
    current = document
    for raw_segment in pointer[1:].split("/"):
        segment = raw_segment.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            current = current[segment]
        elif isinstance(current, list):
            if not segment.isdigit():
                raise TypeError(
                    f"List segment must be an integer in JSON Pointer {pointer!r}"
                )
            current = current[int(segment)]
        else:
            raise TypeError(
                f"Cannot descend through {type(current).__name__} "
                f"in JSON Pointer {pointer!r}"
            )
    return current


def format_bound_value(value_spec: dict[str, Any], results: dict[str, Any]) -> str:
    if value_spec["source"] != "results":
        raise ValueError(f"Unsupported evidence source: {value_spec['source']!r}")

    pointer = value_spec["path"]
    raw_value = resolve_json_pointer(results, pointer)
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        raise TypeError(f"Expected a number at {pointer}, got {raw_value!r}")

    format_spec = value_spec["format"]
    if format_spec["kind"] != "number":
        raise ValueError(f"Unsupported number format at {pointer}: {format_spec!r}")
    digits = format_spec["digits"]
    if not isinstance(digits, int) or digits < 0:
        raise ValueError(f"Invalid digits value at {pointer}: {digits!r}")
    return f"{raw_value:,.{digits}f}"


def wrapped(text: str, width: int) -> str:
    """Wrap both space-delimited text and unspaced CJK text."""
    return "\n".join(
        textwrap.wrap(
            text,
            width=width,
            # Chinese sentences contain no spaces and are otherwise treated as
            # one long word, which leaves them completely unwrapped.
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
) -> None:
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            width,
            height,
            boxstyle=f"round,pad=0.004,rounding_size={radius}",
            transform=ax.transAxes,
            facecolor=facecolor,
            edgecolor=edgecolor,
            linewidth=linewidth,
            clip_on=False,
        )
    )


def draw_header(ax: plt.Axes, title: str, deck: str) -> None:
    ax.add_patch(
        Rectangle(
            (0, 0.815),
            1,
            0.185,
            transform=ax.transAxes,
            facecolor=NAVY,
            edgecolor="none",
        )
    )
    ax.add_patch(
        Rectangle(
            (0.047, 0.875),
            0.008,
            0.072,
            transform=ax.transAxes,
            facecolor=AMBER,
            edgecolor="none",
        )
    )
    ax.text(
        0.075,
        0.925,
        title,
        transform=ax.transAxes,
        ha="left",
        va="center",
        fontsize=29,
        fontweight="bold",
        color=WHITE,
    )
    ax.text(
        0.075,
        0.852,
        wrapped(deck, 52),
        transform=ax.transAxes,
        ha="left",
        va="center",
        fontsize=12.5,
        color="#DDE7F0",
        linespacing=1.35,
    )


def draw_text_card(
    ax: plt.Axes,
    block: dict[str, Any],
    *,
    x: float,
    y: float,
    width: float,
    height: float,
) -> None:
    add_round_rect(
        ax,
        x,
        y,
        width,
        height,
        facecolor=WHITE,
        edgecolor=LINE,
        linewidth=1.2,
    )
    ax.text(
        x + 0.03,
        y + height - 0.07,
        wrapped(block["heading"], 24),
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=19,
        fontweight="bold",
        color=INK,
        linespacing=1.25,
    )
    body = block["body"]
    if not isinstance(body, list) or not body or not all(
        isinstance(item, str) for item in body
    ):
        raise TypeError("Text block body must be a non-empty list of strings")
    is_wide = width >= 0.6
    body_wrap_width = 46 if is_wide else 23
    body_fontsize = 13.5
    line_step = 0.041
    paragraph_gap = 0.025
    y_cursor = y + height - (0.13 if is_wide else 0.18)
    for paragraph in body:
        paragraph_text = wrapped(paragraph, body_wrap_width)
        ax.text(
            x + 0.03,
            y_cursor,
            paragraph_text,
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=body_fontsize,
            color=MUTED,
            linespacing=1.45,
        )
        y_cursor -= line_step * paragraph_text.count("\n")
        y_cursor -= line_step + paragraph_gap


def draw_metric_card(
    ax: plt.Axes,
    block: dict[str, Any],
    results: dict[str, Any],
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    accent: str,
    pale: str,
) -> None:
    add_round_rect(
        ax,
        x,
        y,
        width,
        height,
        facecolor=WHITE,
        edgecolor=LINE,
        linewidth=1.2,
    )
    ax.add_patch(
        FancyBboxPatch(
            (x + 0.018, y + 0.025),
            0.012,
            height - 0.05,
            boxstyle="round,pad=0,rounding_size=0.005",
            transform=ax.transAxes,
            facecolor=accent,
            edgecolor="none",
        )
    )
    ax.add_patch(
        FancyBboxPatch(
            (x + width - 0.095, y + height - 0.105),
            0.055,
            0.055,
            boxstyle="round,pad=0.006,rounding_size=0.012",
            transform=ax.transAxes,
            facecolor=pale,
            edgecolor="none",
        )
    )
    ax.text(
        x + 0.05,
        y + height - 0.055,
        wrapped(block["label"], 11 if width < 0.31 else 15),
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=12.5,
        fontweight="bold",
        color=MUTED,
        linespacing=1.3,
    )
    ax.text(
        x + 0.05,
        y + 0.055,
        format_bound_value(block["value"], results),
        transform=ax.transAxes,
        ha="left",
        va="bottom",
        fontsize=32 if width < 0.31 else 38,
        fontweight="bold",
        color=accent,
    )


def draw_footer(ax: plt.Axes, source_label: str) -> None:
    ax.plot(
        [0.05, 0.95],
        [0.105, 0.105],
        transform=ax.transAxes,
        color=LINE,
        linewidth=1,
    )
    ax.text(
        0.05,
        0.075,
        "資料來源",
        transform=ax.transAxes,
        ha="left",
        va="center",
        fontsize=9.5,
        fontweight="bold",
        color=INK,
    )
    ax.text(
        0.125,
        0.075,
        wrapped(source_label, 115),
        transform=ax.transAxes,
        ha="left",
        va="center",
        fontsize=7.5,
        color=MUTED,
        linespacing=1.25,
    )


def split_blocks(panel: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    text_blocks = [block for block in panel["blocks"] if block["kind"] == "text"]
    metric_blocks = [
        block for block in panel["blocks"] if block["kind"] == "metric"
    ]
    if len(text_blocks) != 1:
        raise ValueError(
            f"{panel['name']} must contain exactly one text block; "
            f"found {len(text_blocks)}"
        )
    if len(metric_blocks) not in (2, 3):
        raise ValueError(
            f"{panel['name']} must contain two or three metrics; "
            f"found {len(metric_blocks)}"
        )
    if len(text_blocks) + len(metric_blocks) != len(panel["blocks"]):
        raise ValueError(f"{panel['name']} contains an unsupported block kind")
    return text_blocks[0], metric_blocks


def render_panel(
    panel: dict[str, Any],
    results: dict[str, Any],
    source_label: str,
    output_path: Path,
) -> None:
    fig = plt.figure(figsize=(10.6666667, 6.6666667), dpi=150, facecolor=PAPER)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    draw_header(ax, panel["title"], panel["alt"])
    text_block, metric_blocks = split_blocks(panel)

    if len(metric_blocks) == 2:
        draw_text_card(
            ax, text_block, x=0.05, y=0.16, width=0.52, height=0.60
        )
        metric_positions = [(0.61, 0.48), (0.61, 0.16)]
        for index, (block, (x, y)) in enumerate(
            zip(metric_blocks, metric_positions, strict=True)
        ):
            accent, pale = ((BLUE, BLUE_PALE), (AMBER, AMBER_PALE))[index]
            draw_metric_card(
                ax,
                block,
                results,
                x=x,
                y=y,
                width=0.34,
                height=0.28,
                accent=accent,
                pale=pale,
            )
    else:
        draw_text_card(
            ax, text_block, x=0.05, y=0.48, width=0.90, height=0.28
        )
        metric_styles = [
            (BLUE, BLUE_PALE),
            (RED, RED_PALE),
            (AMBER, AMBER_PALE),
        ]
        for block, x, (accent, pale) in zip(
            metric_blocks,
            (0.05, 0.36, 0.67),
            metric_styles,
            strict=True,
        ):
            draw_metric_card(
                ax,
                block,
                results,
                x=x,
                y=0.16,
                width=0.28,
                height=0.27,
                accent=accent,
                pale=pale,
            )

    draw_footer(ax, source_label)
    fig.savefig(
        output_path,
        dpi=150,
        facecolor=PAPER,
        edgecolor="none",
        metadata={
            "Title": panel["title"],
            "Description": panel["alt"],
            "Source": source_label,
        },
    )
    plt.close(fig)


def main() -> None:
    plan = load_json(PLAN_PATH)
    results = load_json(RESULTS_PATH)
    article = ARTICLE_PATH.read_text(encoding="utf-8")
    if not article.strip():
        raise ValueError(f"Article evidence is empty: {ARTICLE_PATH}")

    evidence = plan["evidence"]["results"]
    source_label = evidence["label"]
    if source_label != EXPECTED_SOURCE_LABEL:
        raise ValueError("Strict-plan source label changed; refusing to rewrite it")

    panels = plan["panels"]
    names = [panel["name"] for panel in panels]
    if len(names) != len(set(names)):
        raise ValueError("Duplicate panel names in strict plan")
    if set(names) != set(EXPECTED_PANELS):
        raise ValueError(
            f"Unexpected panel set: {names!r}; expected {list(EXPECTED_PANELS)!r}"
        )

    os.makedirs(out_dir, exist_ok=True)
    output_root = Path(out_dir)
    for panel in panels:
        if panel["sources"] != ["results"]:
            raise ValueError(
                f"{panel['name']} has unexpected sources: {panel['sources']!r}"
            )
        render_panel(
            panel,
            results,
            source_label,
            output_root / EXPECTED_PANELS[panel["name"]],
        )


if __name__ == "__main__":
    main()
