#!/usr/bin/env python3
"""Render the four data-bound PNG panels for the K1709 general-reader article.

All displayed statistics are resolved from the strict plan into the experiment
results JSON at runtime. Missing evidence, plan fields, or JSON-pointer targets
raise immediately; the renderer never substitutes a default statistic.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
from matplotlib.patches import FancyBboxPatch, Rectangle


RESULTS_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1709/k1709_results.json"
)
README_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1709/README.md"
)
PLAN_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_a415679b/runs/lazypack-mile_a415679b/plan.json"
)
ARTICLE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_a415679b/runs/lazypack-mile_a415679b/panels/"
    "mile_a415679b_article.md"
)
out_dir = (
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_a415679b/runs/lazypack-mile_a415679b/panels"
)

WIDTH_PX = 1600
HEIGHT_PX = 1000
DPI = 150
EXPECTED_PANELS = (
    "panel_question",
    "panel_method",
    "panel_result",
    "panel_takeaway",
)

NAVY = "#13283F"
INK = "#162333"
MUTED = "#5E6B78"
PAPER = "#F5F7FA"
WHITE = "#FFFFFF"
BORDER = "#DDE4EC"
TEAL = "#16837A"
BLUE = "#2C65A2"
AMBER = "#B46A16"
RED = "#B84A4A"

PANEL_ACCENTS = {
    "panel_question": TEAL,
    "panel_method": BLUE,
    "panel_result": RED,
    "panel_takeaway": AMBER,
}

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def require_text_file(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError(f"Evidence file is empty: {path}")
    return text


def require(mapping: dict[str, Any], key: str, context: str) -> Any:
    if key not in mapping:
        raise KeyError(f"Missing {context}.{key}")
    return mapping[key]


def resolve_json_pointer(document: Any, pointer: str) -> Any:
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValueError(f"Expected absolute JSON Pointer, got {pointer!r}")
    current = document
    for raw_token in pointer[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            if token not in current:
                raise KeyError(f"Missing evidence field at {pointer!r}: {token!r}")
            current = current[token]
        elif isinstance(current, list):
            try:
                index = int(token)
                current = current[index]
            except (ValueError, IndexError) as exc:
                raise KeyError(f"Invalid evidence list index in {pointer!r}") from exc
        else:
            raise KeyError(f"Evidence path crosses a scalar at {pointer!r}")
    return current


def numeric(value: Any, pointer: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"Expected a number at {pointer}, got {type(value).__name__}")
    return float(value)


def format_value(raw: Any, spec: dict[str, Any], pointer: str) -> str:
    kind = require(spec, "kind", f"format for {pointer}")
    number = numeric(raw, pointer)
    digits = int(spec.get("digits", 0))
    scale = float(spec.get("scale", 100 if kind == "percent" else 1))
    show_plus = bool(spec.get("show_plus", False))

    if kind == "integer":
        if not number.is_integer():
            raise ValueError(f"Expected integer-valued evidence at {pointer}: {number}")
        return f"{int(number):,}"
    if kind == "number":
        return f"{number:+.{digits}f}" if show_plus else f"{number:.{digits}f}"
    if kind == "percent":
        scaled = number * scale
        sign = "+" if show_plus else ""
        return f"{scaled:{sign}.{digits}f}%"
    raise ValueError(f"Unsupported format kind {kind!r} at {pointer}")


def wrap_to_width(
    ax: plt.Axes,
    text: str,
    width_axes: float,
    fontsize: float,
    *,
    fontweight: str = "normal",
) -> str:
    """Wrap text to a measured pixel width using the required Heiti TC font.

    ``textwrap`` cannot wrap Chinese when ``break_long_words`` is disabled: a
    paragraph without ASCII spaces is treated as one very long word.  Character
    counts are also unsafe here because CJK and Latin glyphs have very different
    widths.  Measure every candidate line with the Agg renderer instead.  The
    small safety margin keeps antialiasing/rounding at the right edge from being
    interpreted as clipping by the post-render layout guard.
    """
    if not isinstance(text, str):
        raise TypeError(f"Expected text to wrap, got {type(text).__name__}")
    if width_axes <= 0:
        raise ValueError(f"Text width must be positive, got {width_axes}")

    renderer = ax.figure.canvas.get_renderer()
    font = FontProperties(family="Heiti TC", size=fontsize, weight=fontweight)
    x0 = ax.transAxes.transform((0.0, 0.0))[0]
    x1 = ax.transAxes.transform((width_axes, 0.0))[0]
    max_width_px = (x1 - x0) * 0.96

    def measured_width(candidate: str) -> float:
        return renderer.get_text_width_height_descent(candidate, font, False)[0]

    wrapped: list[str] = []
    for paragraph in text.split("\n"):
        if not paragraph:
            wrapped.append("")
            continue
        line = ""
        for character in paragraph:
            candidate = line + character
            if line and measured_width(candidate) > max_width_px:
                # Avoid beginning a line with whitespace.  Chinese punctuation
                # is deliberately kept with the following line only when the
                # measured width requires it; visual correctness takes priority.
                wrapped.append(line.rstrip())
                line = character.lstrip()
            else:
                line = candidate
        if line or not wrapped:
            wrapped.append(line.rstrip())
    return "\n".join(wrapped)


def line_count(text: str) -> int:
    return text.count("\n") + 1


def add_rounded_box(
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
            boxstyle=f"round,pad=0.008,rounding_size={radius}",
            transform=ax.transAxes,
            facecolor=facecolor,
            edgecolor=edgecolor,
            linewidth=linewidth,
        )
    )


def draw_header(ax: plt.Axes, title: str, accent: str) -> None:
    ax.add_patch(
        Rectangle((0, 0.82), 1, 0.18, transform=ax.transAxes, color=NAVY, linewidth=0)
    )
    ax.add_patch(
        Rectangle((0.045, 0.855), 0.009, 0.095, transform=ax.transAxes, color=accent, linewidth=0)
    )
    fontsize = 27
    title_lines = wrap_to_width(ax, title, 0.855, fontsize, fontweight="bold")
    if line_count(title_lines) == 1:
        fontsize = 31
        title_lines = wrap_to_width(ax, title, 0.855, fontsize, fontweight="bold")
    ax.text(
        0.072,
        0.91,
        title_lines,
        transform=ax.transAxes,
        ha="left",
        va="center",
        color=WHITE,
        fontsize=fontsize,
        fontweight="bold",
        linespacing=1.10,
    )


def draw_story(ax: plt.Axes, block: dict[str, Any], accent: str) -> None:
    heading = require(block, "heading", "text block")
    body = require(block, "body", "text block")
    if not isinstance(body, list) or len(body) != 2 or not all(isinstance(x, str) for x in body):
        raise ValueError("Each panel text block must contain exactly two body paragraphs")

    add_rounded_box(
        ax,
        0.045,
        0.465,
        0.91,
        0.305,
        facecolor=WHITE,
        edgecolor=BORDER,
        linewidth=1.2,
    )
    ax.add_patch(
        Rectangle((0.045, 0.465), 0.012, 0.305, transform=ax.transAxes, color=accent, linewidth=0)
    )
    ax.text(
        0.077,
        0.724,
        wrap_to_width(ax, heading, 0.845, 19, fontweight="bold"),
        transform=ax.transAxes,
        ha="left",
        va="top",
        color=INK,
        fontsize=19,
        fontweight="bold",
    )
    first_paragraph = wrap_to_width(ax, body[0], 0.845, 14.2)
    second_paragraph = wrap_to_width(ax, body[1], 0.845, 14.2)
    first_y = 0.671
    # At 150 dpi, a 14.2 pt line with 1.35 spacing occupies just under
    # 0.041 of this 1000 px canvas.  Position paragraph two from the actual
    # wrapped line count so the two text objects can never overlap.
    second_y = first_y - line_count(first_paragraph) * 0.041 - 0.014
    ax.text(
        0.077,
        first_y,
        first_paragraph,
        transform=ax.transAxes,
        ha="left",
        va="top",
        color=INK,
        fontsize=14.2,
        linespacing=1.35,
    )
    ax.text(
        0.077,
        second_y,
        second_paragraph,
        transform=ax.transAxes,
        ha="left",
        va="top",
        color=MUTED,
        fontsize=14.2,
        linespacing=1.35,
    )


def bind_metrics(panel: dict[str, Any], results: dict[str, Any]) -> list[dict[str, str]]:
    blocks = require(panel, "blocks", f"panel {panel.get('name', '?')}")
    if not isinstance(blocks, list):
        raise TypeError("panel.blocks must be a list")
    metrics: list[dict[str, str]] = []
    for block in blocks:
        if block.get("kind") != "metric":
            continue
        value_spec = require(block, "value", "metric block")
        source = require(value_spec, "source", "metric value")
        if source != "results":
            raise ValueError(f"Unsupported metric source: {source!r}")
        pointer = require(value_spec, "path", "metric value")
        raw = resolve_json_pointer(results, pointer)
        rendered = format_value(raw, require(value_spec, "format", "metric value"), pointer)
        metrics.append(
            {
                "label": require(block, "label", "metric block"),
                "value": rendered,
                "note": block.get("note", ""),
            }
        )
    if len(metrics) not in (3, 4):
        raise ValueError(f"Expected 3 or 4 metrics, found {len(metrics)}")
    return metrics


def draw_metrics(ax: plt.Axes, metrics: list[dict[str, str]], accent: str) -> None:
    count = len(metrics)
    gap = 0.018
    left = 0.045
    total_width = 0.91
    card_width = (total_width - gap * (count - 1)) / count
    y = 0.135
    height = 0.295

    for index, metric in enumerate(metrics):
        x = left + index * (card_width + gap)
        add_rounded_box(
            ax,
            x,
            y,
            card_width,
            height,
            facecolor=WHITE,
            edgecolor=BORDER,
            linewidth=1.2,
        )
        ax.add_patch(
            Rectangle(
                (x + 0.017, y + height - 0.027),
                0.055,
                0.008,
                transform=ax.transAxes,
                color=accent,
                linewidth=0,
            )
        )
        label_fontsize = 10.2 if count == 4 else 11.4
        label_text = wrap_to_width(
            ax,
            metric["label"],
            card_width - 0.04,
            label_fontsize,
        )
        ax.text(
            x + 0.02,
            y + height - 0.052,
            label_text,
            transform=ax.transAxes,
            ha="left",
            va="top",
            color=MUTED,
            fontsize=label_fontsize,
            linespacing=1.18,
        )
        ax.text(
            x + 0.02,
            y + 0.137,
            metric["value"],
            transform=ax.transAxes,
            ha="left",
            va="center",
            color=accent,
            fontsize=27 if count == 4 else 32,
            fontweight="bold",
        )
        if metric["note"]:
            note_fontsize = 8.2 if count == 4 else 9.2
            ax.text(
                x + 0.02,
                y + 0.027,
                wrap_to_width(
                    ax,
                    metric["note"],
                    card_width - 0.04,
                    note_fontsize,
                ),
                transform=ax.transAxes,
                ha="left",
                va="bottom",
                color=MUTED,
                fontsize=note_fontsize,
                linespacing=1.18,
            )


def draw_source(ax: plt.Axes, source_label: str) -> None:
    source_text = f"資料來源：{source_label}"
    ax.plot([0.045, 0.955], [0.102, 0.102], transform=ax.transAxes, color=BORDER, linewidth=1)
    ax.text(
        0.045,
        0.061,
        wrap_to_width(ax, source_text, 0.91, 7.8),
        transform=ax.transAxes,
        ha="left",
        va="center",
        color=MUTED,
        fontsize=7.8,
        linespacing=1.12,
    )


def render_panel(panel: dict[str, Any], results: dict[str, Any], source_label: str) -> None:
    name = require(panel, "name", "panel")
    if name not in EXPECTED_PANELS:
        raise ValueError(f"Unexpected panel name: {name!r}")
    title = require(panel, "title", f"panel {name}")
    blocks = require(panel, "blocks", f"panel {name}")
    text_blocks = [block for block in blocks if block.get("kind") == "text"]
    if len(text_blocks) != 1:
        raise ValueError(f"Panel {name} must contain exactly one text block")

    accent = PANEL_ACCENTS[name]
    figure = plt.figure(
        figsize=(WIDTH_PX / DPI, HEIGHT_PX / DPI),
        dpi=DPI,
        facecolor=PAPER,
    )
    ax = figure.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    draw_header(ax, title, accent)
    draw_story(ax, text_blocks[0], accent)
    draw_metrics(ax, bind_metrics(panel, results), accent)
    draw_source(ax, source_label)

    output_path = Path(out_dir) / f"{name}.png"
    figure.savefig(
        output_path,
        dpi=DPI,
        facecolor=PAPER,
        edgecolor="none",
        bbox_inches=None,
        pad_inches=0,
        metadata={"Title": title, "Description": require(panel, "alt", f"panel {name}")},
    )
    plt.close(figure)


def main() -> None:
    results = load_json(RESULTS_PATH)
    plan = load_json(PLAN_PATH)
    # These are required members of the evidence package. Reading them here makes
    # a missing or empty package fail visibly even though displayed numbers come
    # exclusively from results.json.
    require_text_file(README_PATH)
    require_text_file(ARTICLE_PATH)

    evidence = require(plan, "evidence", "plan")
    results_evidence = require(evidence, "results", "plan.evidence")
    source_label = require(results_evidence, "label", "plan.evidence.results")
    if not isinstance(source_label, str) or not source_label.strip():
        raise ValueError("plan.evidence.results.label must be a non-empty string")

    panels = require(plan, "panels", "plan")
    if not isinstance(panels, list):
        raise TypeError("plan.panels must be a list")
    names = tuple(require(panel, "name", "panel") for panel in panels)
    if names != EXPECTED_PANELS:
        raise ValueError(f"Expected panels {EXPECTED_PANELS}, found {names}")

    os.makedirs(out_dir, exist_ok=True)
    for panel in panels:
        render_panel(panel, results, source_label)


if __name__ == "__main__":
    main()
