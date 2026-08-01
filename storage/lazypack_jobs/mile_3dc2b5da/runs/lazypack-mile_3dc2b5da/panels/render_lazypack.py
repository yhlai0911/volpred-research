#!/usr/bin/env python3
"""Render the three evidence-bound PNG panels for mile_3dc2b5da."""

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
    "mile_3dc2b5da/runs/lazypack-mile_3dc2b5da/plan.json"
)
RESULTS_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1717/k1717_results.json"
)
ARTICLE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_3dc2b5da/runs/lazypack-mile_3dc2b5da/panels/"
    "mile_3dc2b5da_article.md"
)
OUT_DIR = (
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_3dc2b5da/runs/lazypack-mile_3dc2b5da/panels"
)

EXPECTED_PANELS = (
    "panel_result_local",
    "panel_method",
    "panel_takeaway",
)

WIDTH = 1600
HEIGHT = 1000
DPI = 150

NAVY = "#172A3A"
NAVY_2 = "#223E52"
PAPER = "#F6F8FA"
WHITE = "#FFFFFF"
INK = "#17212B"
MUTED = "#52606D"
BORDER = "#D7DEE5"
TEAL = "#0F7C77"
TEAL_SOFT = "#E5F3F1"
RED = "#B9473F"
RED_SOFT = "#F8EAE8"
AMBER = "#A66A16"
AMBER_SOFT = "#F8F0E2"
BLUE = "#2F6690"
BLUE_SOFT = "#E8F0F6"

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def json_pointer(document: Any, pointer: str) -> Any:
    """Resolve an RFC 6901-style pointer, raising on every missing segment."""
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValueError(f"Invalid JSON pointer: {pointer!r}")
    current = document
    for raw_part in pointer[1:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            if part not in current:
                raise KeyError(f"Missing evidence field: {pointer}")
            current = current[part]
        elif isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError) as exc:
                raise KeyError(f"Missing evidence field: {pointer}") from exc
        else:
            raise KeyError(f"Missing evidence field: {pointer}")
    return current


def format_value(value: Any, format_spec: dict[str, Any], pointer: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(
            f"Expected numeric evidence at {pointer}, got {type(value).__name__}"
        )
    kind = format_spec["kind"]
    if kind == "integer":
        return f"{int(value):,}"
    if kind == "number":
        digits = format_spec["digits"]
        if not isinstance(digits, int) or digits < 0:
            raise ValueError(f"Invalid digit count for {pointer}: {digits!r}")
        return f"{float(value):.{digits}f}"
    raise ValueError(f"Unsupported number format for {pointer}: {kind!r}")


def wrapped(text: str, width: int) -> str:
    return "\n".join(
        textwrap.wrap(
            text,
            width=width,
            break_long_words=True,
            break_on_hyphens=False,
            replace_whitespace=False,
        )
    )


def wrapped_for_pixels(text: str, width_px: float, fontsize: float) -> str:
    """Conservatively wrap text to a pixel-wide box at the output DPI.

    ``textwrap`` measures characters, while Matplotlib font sizes are points.
    At 150 DPI a 18pt CJK glyph is roughly 37.5 pixels wide, so fixed values
    such as ``width=25`` can overflow a 616px card.  CJK glyphs are close to
    one em wide; the small safety factor also covers punctuation and bold text.
    """
    glyph_width_px = fontsize * DPI / 72 * 1.08
    max_chars = max(1, int(width_px / glyph_width_px))
    return wrapped(text, max_chars)


def rounded_box(
    ax: plt.Axes,
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    facecolor: str,
    edgecolor: str = BORDER,
    linewidth: float = 1.2,
    radius: float = 18,
) -> None:
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            width,
            height,
            boxstyle=f"round,pad=0,rounding_size={radius}",
            facecolor=facecolor,
            edgecolor=edgecolor,
            linewidth=linewidth,
        )
    )


def panel_accent(panel_name: str) -> tuple[str, str]:
    if panel_name == "panel_result_local":
        return TEAL, TEAL_SOFT
    if panel_name == "panel_method":
        return BLUE, BLUE_SOFT
    if panel_name == "panel_takeaway":
        return AMBER, AMBER_SOFT
    raise KeyError(f"No palette for panel: {panel_name}")


def metric_tone(panel_name: str, index: int) -> tuple[str, str]:
    if panel_name == "panel_result_local":
        return (
            (NAVY_2, PAPER),
            (TEAL, TEAL_SOFT),
            (RED, RED_SOFT),
        )[index]
    if panel_name == "panel_method":
        return (
            (NAVY_2, PAPER),
            (TEAL, TEAL_SOFT),
            (RED, RED_SOFT),
            (BLUE, BLUE_SOFT),
        )[index]
    if panel_name == "panel_takeaway":
        return (
            (TEAL, TEAL_SOFT),
            (AMBER, AMBER_SOFT),
            (BLUE, BLUE_SOFT),
        )[index]
    raise KeyError(f"No metric palette for panel: {panel_name}")


def extract_panel_data(
    panel: dict[str, Any], results: dict[str, Any]
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    text_blocks = [block for block in panel["blocks"] if block["kind"] == "text"]
    if len(text_blocks) != 1:
        raise ValueError(f"{panel['name']} must contain exactly one text block")

    metrics: list[dict[str, str]] = []
    for block in panel["blocks"]:
        if block["kind"] != "metric":
            continue
        value_spec = block["value"]
        if value_spec["source"] != "results":
            raise ValueError(f"Unsupported metric source: {value_spec['source']!r}")
        pointer = value_spec["path"]
        raw_value = json_pointer(results, pointer)
        metrics.append(
            {
                "label": block["label"],
                "value": format_value(raw_value, value_spec["format"], pointer),
                "note": block.get("note", ""),
                "pointer": pointer,
            }
        )
    if not metrics:
        raise ValueError(f"{panel['name']} has no metric blocks")
    return text_blocks[0], metrics


def render_panel(
    panel: dict[str, Any], results: dict[str, Any], source_label: str
) -> None:
    name = panel["name"]
    if panel["style"] != "professional":
        raise ValueError(f"Unexpected style for {name}: {panel['style']!r}")
    if panel["sources"] != ["results"]:
        raise ValueError(f"Unexpected sources for {name}: {panel['sources']!r}")

    text_block, metrics = extract_panel_data(panel, results)
    accent, accent_soft = panel_accent(name)

    fig = plt.figure(figsize=(WIDTH / DPI, HEIGHT / DPI), dpi=DPI, facecolor=WHITE)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, WIDTH)
    ax.set_ylim(0, HEIGHT)
    ax.axis("off")

    # Header: one restrained, high-contrast title band.
    ax.add_patch(Rectangle((0, 800), WIDTH, 200, facecolor=NAVY, edgecolor="none"))
    ax.add_patch(Rectangle((68, 850), 9, 88, facecolor=accent, edgecolor="none"))
    title_fontsize = 31
    ax.text(
        105,
        900,
        wrapped_for_pixels(panel["title"], 1390, title_fontsize),
        color=WHITE,
        fontsize=title_fontsize,
        fontweight="bold",
        ha="left",
        va="center",
        linespacing=1.12,
    )

    # Narrative area.
    narrative_x = 68
    narrative_y = 190
    narrative_width = 616
    narrative_height = 570
    narrative_padding = 30
    narrative_header_height = 92
    rounded_box(
        ax,
        narrative_x,
        narrative_y,
        narrative_width,
        narrative_height,
        facecolor=PAPER,
    )
    ax.add_patch(
        Rectangle(
            (
                narrative_x,
                narrative_y + narrative_height - narrative_header_height,
            ),
            narrative_width,
            narrative_header_height,
            facecolor=accent_soft,
            edgecolor="none",
        )
    )
    heading_fontsize = 15.5
    ax.text(
        narrative_x + narrative_padding,
        narrative_y + narrative_height - narrative_header_height / 2,
        wrapped_for_pixels(
            text_block["heading"],
            narrative_width - 2 * narrative_padding,
            heading_fontsize,
        ),
        color=accent,
        fontsize=heading_fontsize,
        fontweight="bold",
        ha="left",
        va="center",
        linespacing=1.18,
    )

    body_fontsize = 14
    body_linespacing = 1.25
    body_line_height = body_fontsize * DPI / 72 * body_linespacing
    paragraph_gap = 20
    body_y = narrative_y + narrative_height - narrative_header_height - 24
    for paragraph in text_block["body"]:
        paragraph_text = wrapped_for_pixels(
            paragraph,
            narrative_width - 2 * narrative_padding,
            body_fontsize,
        )
        paragraph_lines = paragraph_text.splitlines()
        ax.text(
            narrative_x + narrative_padding,
            body_y,
            paragraph_text,
            color=INK,
            fontsize=body_fontsize,
            ha="left",
            va="top",
            linespacing=body_linespacing,
        )
        body_y -= len(paragraph_lines) * body_line_height + paragraph_gap
    if body_y < narrative_y + 16:
        raise ValueError(f"Narrative layout overflow in {name}")

    # Metric cards. Card geometry is determined solely by the plan's metric count.
    metric_x = 732
    metric_width = 800
    available_height = 570
    gap = 16
    card_height = (available_height - gap * (len(metrics) - 1)) / len(metrics)
    if card_height < 118:
        raise ValueError(f"Too many metrics to render safely in {name}")

    for index, metric in enumerate(metrics):
        card_y = 190 + (len(metrics) - 1 - index) * (card_height + gap)
        tone, soft = metric_tone(name, index)
        rounded_box(
            ax,
            metric_x,
            card_y,
            metric_width,
            card_height,
            facecolor=WHITE,
            edgecolor=BORDER,
        )
        ax.add_patch(
            FancyBboxPatch(
                (metric_x, card_y),
                13,
                card_height,
                boxstyle="round,pad=0,rounding_size=6",
                facecolor=tone,
                edgecolor=tone,
                linewidth=0,
            )
        )
        ax.add_patch(
            FancyBboxPatch(
                (metric_x + 32, card_y + 23),
                445,
                card_height - 46,
                boxstyle="round,pad=0,rounding_size=12",
                facecolor=soft,
                edgecolor="none",
            )
        )
        label_fontsize = 12 if len(metrics) == 4 else 13
        ax.text(
            metric_x + 54,
            card_y + card_height / 2,
            wrapped_for_pixels(metric["label"], 395, label_fontsize),
            color=INK,
            fontsize=label_fontsize,
            fontweight="bold",
            ha="left",
            va="center",
            linespacing=1.18,
        )
        ax.text(
            metric_x + metric_width - 34,
            card_y + card_height * (0.68 if metric["note"] else 0.50),
            metric["value"],
            color=tone,
            fontsize=27 if len(metrics) == 4 else 29,
            fontweight="bold",
            ha="right",
            va="center",
        )
        if metric["note"]:
            note_fontsize = 10
            ax.text(
                metric_x + metric_width - 34,
                card_y + card_height * 0.24,
                wrapped_for_pixels(metric["note"], 240, note_fontsize),
                color=MUTED,
                fontsize=note_fontsize,
                ha="right",
                va="center",
                linespacing=1.15,
            )

    # The plan's evidence label is used verbatim; it is deliberately not inferred.
    ax.plot([68, 1532], [151, 151], color=BORDER, linewidth=1.1)
    source_text = f"資料來源：{source_label}"
    source_fontsize = 9.5
    ax.text(
        68,
        116,
        wrapped_for_pixels(source_text, 1464, source_fontsize),
        color=MUTED,
        fontsize=source_fontsize,
        ha="left",
        va="top",
        linespacing=1.25,
    )

    output_path = Path(OUT_DIR) / f"{name}.png"
    fig.savefig(
        output_path,
        dpi=DPI,
        facecolor=WHITE,
        metadata={"Description": panel["alt"]},
    )
    plt.close(fig)


def main() -> None:
    plan = load_json(PLAN_PATH)
    results = load_json(RESULTS_PATH)
    article = ARTICLE_PATH.read_text(encoding="utf-8")
    if not article.strip():
        raise ValueError(f"Article evidence is empty: {ARTICLE_PATH}")

    evidence = plan["evidence"]
    source_label = evidence["results"]["label"]
    if not isinstance(source_label, str) or not source_label.strip():
        raise ValueError("plan.json evidence.results.label must be a non-empty string")

    panels_by_name = {panel["name"]: panel for panel in plan["panels"]}
    missing = [name for name in EXPECTED_PANELS if name not in panels_by_name]
    if missing:
        raise KeyError(f"Missing required panel definitions: {missing}")

    os.makedirs(OUT_DIR, exist_ok=True)
    for name in EXPECTED_PANELS:
        render_panel(panels_by_name[name], results, source_label)


if __name__ == "__main__":
    main()
