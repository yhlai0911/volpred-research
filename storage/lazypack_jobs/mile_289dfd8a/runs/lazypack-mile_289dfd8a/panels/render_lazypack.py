#!/usr/bin/env python3
"""Render the mile_289dfd8a evidence-bound infographic panels."""

from __future__ import annotations

import json
import math
import os
import textwrap
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyBboxPatch, Rectangle


RESULTS_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1698/k1698_results.json"
)
README_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1698/README.md"
)
PLAN_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_289dfd8a/runs/lazypack-mile_289dfd8a/plan.json"
)
ARTICLE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_289dfd8a/runs/lazypack-mile_289dfd8a/panels/"
    "mile_289dfd8a_article.md"
)
out_dir = (
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_289dfd8a/runs/lazypack-mile_289dfd8a/panels"
)

EXPECTED_PANELS = {
    "panel_question",
    "panel_method",
    "panel_result",
    "panel_takeaway",
}

INK = "#162235"
NAVY = "#14263D"
MUTED = "#586577"
PALE = "#F3F6F9"
LINE = "#D9E1EA"
WHITE = "#FFFFFF"
TEAL = "#087F8C"
AMBER = "#C77D17"

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def require_nonempty_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError(f"Evidence file is empty: {path}")
    return text


def resolve_json_pointer(document: Any, pointer: str) -> Any:
    """Resolve RFC 6901-style paths and fail loudly on every mismatch."""
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValueError(f"Invalid JSON pointer: {pointer!r}")
    current = document
    for raw_token in pointer[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            if token not in current:
                raise KeyError(f"Missing evidence field: {pointer}")
            current = current[token]
        elif isinstance(current, list):
            try:
                current = current[int(token)]
            except (ValueError, IndexError) as exc:
                raise KeyError(f"Missing evidence field: {pointer}") from exc
        else:
            raise KeyError(f"Cannot descend through evidence field: {pointer}")
    return current


def format_metric(value: Any, format_spec: dict[str, Any], pointer: str) -> str:
    if format_spec.get("kind") != "number":
        raise ValueError(f"Unsupported metric format at {pointer}: {format_spec!r}")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"Expected numeric evidence at {pointer}, got {type(value).__name__}")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"Non-finite evidence at {pointer}: {value!r}")
    digits = format_spec.get("digits")
    if not isinstance(digits, int) or digits < 0:
        raise ValueError(f"Invalid digits at {pointer}: {digits!r}")
    return f"{number:.{digits}f}"


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


def wrap_source(text: str, width: int = 166) -> str:
    return "\n".join(
        textwrap.wrap(
            text,
            width=width,
            break_long_words=False,
            break_on_hyphens=False,
        )
    )


def wrap_paragraphs(text: str, width: int) -> str:
    """Wrap each paragraph independently while preserving paragraph breaks."""
    return "\n\n".join(
        wrap_zh(paragraph, width) for paragraph in text.split("\n\n")
    )


def add_fitted_text(
    fig: Any,
    ax: Any,
    text: str,
    bounds: tuple[float, float, float, float],
    *,
    max_fontsize: float,
    min_fontsize: float,
    max_chars: int,
    color: str,
    fontweight: str = "normal",
    linespacing: float = 1.3,
    ha: str = "left",
    va: str = "top",
) -> Any:
    """Add wrapped text whose measured glyph bounds fit inside an axes box.

    Character-count wrapping alone is unreliable for Heiti TC at 150 DPI.
    This routine measures the actual rendered glyph extent and tightens the
    wrap (then the font size) until all four sides are inside ``bounds``.
    """
    x, y, width, height = bounds
    if width <= 0 or height <= 0:
        raise ValueError(f"Invalid text bounds: {bounds!r}")

    anchor_x = x if ha == "left" else x + width / 2 if ha == "center" else x + width
    anchor_y = y + height if va == "top" else y + height / 2 if va == "center" else y
    box_left, box_bottom = ax.transAxes.transform((x, y))
    box_right, box_top = ax.transAxes.transform((x + width, y + height))
    epsilon = 0.5

    font_steps = int(round((max_fontsize - min_fontsize) * 2))
    font_sizes = [max_fontsize - step * 0.5 for step in range(font_steps + 1)]
    if font_sizes[-1] > min_fontsize:
        font_sizes.append(min_fontsize)

    for fontsize in font_sizes:
        for char_width in range(max_chars, 0, -1):
            wrapped = wrap_paragraphs(text, char_width)
            artist = ax.text(
                anchor_x,
                anchor_y,
                wrapped,
                transform=ax.transAxes,
                ha=ha,
                va=va,
                fontsize=fontsize,
                fontweight=fontweight,
                color=color,
                linespacing=linespacing,
            )
            fig.canvas.draw()
            extent = artist.get_window_extent(renderer=fig.canvas.get_renderer())
            fits = (
                extent.x0 >= box_left - epsilon
                and extent.x1 <= box_right + epsilon
                and extent.y0 >= box_bottom - epsilon
                and extent.y1 <= box_top + epsilon
            )
            if fits:
                return artist
            artist.remove()

    raise ValueError(
        f"Text cannot fit reserved layout even at {min_fontsize}pt: {text[:80]!r}"
    )


def add_card(ax: Any, x: float, y: float, w: float, h: float) -> None:
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle="round,pad=0.008,rounding_size=0.012",
            transform=ax.transAxes,
            facecolor=WHITE,
            edgecolor=LINE,
            linewidth=1.2,
        )
    )
    ax.add_patch(
        Rectangle(
            (x, y),
            0.006,
            h,
            transform=ax.transAxes,
            facecolor=TEAL,
            edgecolor="none",
        )
    )


def draw_panel_icon(ax: Any, panel_name: str) -> None:
    cx, cy = 0.925, 0.905
    ax.add_patch(
        Circle(
            (cx, cy),
            0.037,
            transform=ax.transAxes,
            facecolor=TEAL,
            edgecolor="none",
        )
    )
    glyphs = {
        "panel_question": "?",
        "panel_method": "↗",
        "panel_result": "⇄",
        "panel_takeaway": "✓",
    }
    ax.text(
        cx,
        cy,
        glyphs[panel_name],
        transform=ax.transAxes,
        ha="center",
        va="center",
        fontsize=25,
        color=WHITE,
        fontweight="bold",
    )


def metric_blocks(panel: dict[str, Any]) -> list[dict[str, Any]]:
    metrics = [block for block in panel["blocks"] if block.get("kind") == "metric"]
    if len(metrics) not in {3, 4}:
        raise ValueError(f"Expected three or four metrics in {panel['name']}")
    return metrics


def narrative_block(panel: dict[str, Any]) -> dict[str, Any]:
    texts = [block for block in panel["blocks"] if block.get("kind") == "text"]
    if len(texts) != 1:
        raise ValueError(f"Expected exactly one text block in {panel['name']}")
    block = texts[0]
    if not isinstance(block.get("heading"), str) or not isinstance(block.get("body"), list):
        raise TypeError(f"Malformed text block in {panel['name']}")
    if not block["body"] or not all(isinstance(item, str) and item for item in block["body"]):
        raise TypeError(f"Malformed body copy in {panel['name']}")
    return block


def render_panel(
    panel: dict[str, Any], results: dict[str, Any], source_labels: dict[str, str]
) -> None:
    name = panel.get("name")
    if name not in EXPECTED_PANELS:
        raise ValueError(f"Unexpected panel name: {name!r}")
    if panel.get("style") != "professional":
        raise ValueError(f"Panel {name} must use professional style")
    title = panel.get("title")
    alt = panel.get("alt")
    sources = panel.get("sources")
    if not isinstance(title, str) or not title or not isinstance(alt, str) or not alt:
        raise TypeError(f"Panel {name} is missing title or alt text")
    if not isinstance(sources, list) or not sources:
        raise TypeError(f"Panel {name} is missing sources")

    text_block = narrative_block(panel)
    metrics = metric_blocks(panel)

    fig = plt.figure(figsize=(1600 / 150, 1000 / 150), dpi=150, facecolor=WHITE)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    ax.add_patch(Rectangle((0, 0.825), 1, 0.175, transform=ax.transAxes, color=NAVY))
    add_fitted_text(
        fig,
        ax,
        title,
        (0.055, 0.855, 0.805, 0.11),
        max_fontsize=29,
        min_fontsize=22,
        max_chars=32,
        color=WHITE,
        fontweight="bold",
        linespacing=1.1,
        va="center",
    )
    draw_panel_icon(ax, name)

    ax.add_patch(
        FancyBboxPatch(
            (0.045, 0.155),
            0.445,
            0.615,
            boxstyle="round,pad=0.014,rounding_size=0.016",
            transform=ax.transAxes,
            facecolor=PALE,
            edgecolor="none",
        )
    )
    add_fitted_text(
        fig,
        ax,
        text_block["heading"],
        (0.075, 0.65, 0.365, 0.09),
        max_fontsize=20,
        min_fontsize=15,
        max_chars=18,
        color=INK,
        fontweight="bold",
        linespacing=1.18,
    )
    ax.add_patch(Rectangle((0.075, 0.625), 0.058, 0.007, transform=ax.transAxes, color=AMBER))

    add_fitted_text(
        fig,
        ax,
        "\n\n".join(text_block["body"]),
        (0.075, 0.18, 0.365, 0.42),
        max_fontsize=14.2,
        min_fontsize=10.5,
        max_chars=22,
        color=MUTED,
        linespacing=1.4,
    )

    positions = [
        (0.535, 0.485),
        (0.745, 0.485),
        (0.535, 0.195),
        (0.745, 0.195),
    ]
    for index, (block, (x, y)) in enumerate(
        zip(metrics, positions[: len(metrics)], strict=True)
    ):
        value_spec = block.get("value")
        label = block.get("label")
        if not isinstance(value_spec, dict) or not isinstance(label, str) or not label:
            raise TypeError(f"Malformed metric in {name}")
        if value_spec.get("source") != "results":
            raise ValueError(f"Unsupported metric source in {name}: {value_spec.get('source')!r}")
        pointer = value_spec.get("path")
        if not isinstance(pointer, str):
            raise TypeError(f"Metric path must be text in {name}")
        raw_value = resolve_json_pointer(results, pointer)
        rendered_value = format_metric(raw_value, value_spec.get("format", {}), pointer)

        add_card(ax, x, y, 0.19, 0.235)
        add_fitted_text(
            fig,
            ax,
            rendered_value,
            (x + 0.018, y + 0.145, 0.15, 0.075),
            max_fontsize=29,
            min_fontsize=20,
            max_chars=12,
            color=TEAL if index % 2 == 0 else INK,
            fontweight="bold",
            linespacing=1.0,
            va="center",
        )
        add_fitted_text(
            fig,
            ax,
            label,
            (x + 0.018, y + 0.025, 0.15, 0.105),
            max_fontsize=11.7,
            min_fontsize=8.5,
            max_chars=11,
            color=MUTED,
            linespacing=1.22,
        )

    labels: list[str] = []
    for source_id in sources:
        if source_id not in source_labels:
            raise KeyError(f"Missing strict-plan source label: {source_id}")
        labels.append(source_labels[source_id])
    source_text = "資料來源：" + "；".join(labels)
    ax.plot([0.05, 0.95], [0.105, 0.105], transform=ax.transAxes, color=LINE, linewidth=1)
    add_fitted_text(
        fig,
        ax,
        source_text,
        (0.05, 0.025, 0.90, 0.06),
        max_fontsize=7.6,
        min_fontsize=6.0,
        max_chars=150,
        color=MUTED,
        linespacing=1.15,
        va="center",
    )

    destination = Path(out_dir) / f"{name}.png"
    fig.savefig(
        destination,
        dpi=150,
        facecolor=WHITE,
        metadata={"Title": title, "Description": alt},
    )
    plt.close(fig)


def main() -> None:
    results = load_json(RESULTS_PATH)
    plan = load_json(PLAN_PATH)
    require_nonempty_text(README_PATH)
    require_nonempty_text(ARTICLE_PATH)

    evidence = plan.get("evidence")
    panels = plan.get("panels")
    if not isinstance(evidence, dict) or not isinstance(panels, list):
        raise TypeError("Strict plan must contain evidence and panels")
    if {panel.get("name") for panel in panels} != EXPECTED_PANELS:
        raise ValueError("Strict plan panel set does not match the required four panels")

    source_labels: dict[str, str] = {}
    for source_id, source_spec in evidence.items():
        if not isinstance(source_spec, dict) or not isinstance(source_spec.get("label"), str):
            raise TypeError(f"Evidence source {source_id!r} has no reader-facing label")
        source_labels[source_id] = source_spec["label"]

    os.makedirs(out_dir, exist_ok=True)
    for panel in panels:
        render_panel(panel, results, source_labels)


if __name__ == "__main__":
    main()
