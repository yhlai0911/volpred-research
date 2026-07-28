#!/usr/bin/env python3
"""Render the three data-bound PNG panels for the mile_eaacd072 article.

All displayed copy and metric formatting come from the strict plan.  All
displayed metric values are resolved from the results evidence at runtime.
Missing or malformed evidence raises an exception instead of producing a
plausible-looking fallback.
"""
from __future__ import annotations

import json
import math
import os
import unicodedata
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyBboxPatch, Rectangle


PLAN_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_eaacd072/runs/lazypack-mile_eaacd072/plan.json"
)
RESULTS_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1492/k1492_results.json"
)
ARTICLE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_eaacd072/runs/lazypack-mile_eaacd072/panels/"
    "mile_eaacd072_article.md"
)
out_dir = (
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_eaacd072/runs/lazypack-mile_eaacd072/panels"
)

WIDTH_PX = 1600
HEIGHT_PX = 1000
DPI = 150

NAVY = "#102A43"
NAVY_2 = "#163B5C"
INK = "#172B3A"
MUTED = "#526675"
PALE = "#F4F7FA"
LINE = "#D8E2EA"
WHITE = "#FFFFFF"
TEAL = "#087F8C"
TEAL_PALE = "#E5F4F5"
BLUE = "#2F6B9A"
BLUE_PALE = "#E8F0F7"
AMBER = "#B36B00"
AMBER_PALE = "#FFF2D8"

EXPECTED_PANELS = {
    "panel_question",
    "panel_result",
    "panel_takeaway",
}
EXPECTED_SOURCE_LABEL = (
    "experiment K1492 results "
    "(stablecoin peg deviation vs redemption flows → crypto/Treasury RV)"
)

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def require_nonempty_article(path: Path) -> str:
    article = path.read_text(encoding="utf-8")
    if not article.strip():
        raise ValueError(f"Article evidence is empty: {path}")
    return article


def resolve_json_pointer(document: Any, pointer: str) -> Any:
    """Resolve an RFC 6901-style pointer and fail loudly on any bad segment."""
    if pointer == "":
        return document
    if not pointer.startswith("/"):
        raise ValueError(f"JSON pointer must start with '/': {pointer!r}")

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
            except ValueError as exc:
                raise KeyError(
                    f"Expected list index in {pointer!r}, got {token!r}"
                ) from exc
            if index < 0 or index >= len(current):
                raise IndexError(
                    f"List index {index} out of range while resolving {pointer!r}"
                )
            current = current[index]
        else:
            raise KeyError(
                f"Cannot descend through {type(current).__name__} "
                f"while resolving {pointer!r}"
            )
    return current


def as_finite_number(value: Any, pointer: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(
            f"Expected numeric evidence at {pointer!r}, "
            f"got {type(value).__name__}"
        )
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"Non-finite evidence at {pointer!r}: {number!r}")
    return number


def format_metric(raw_value: Any, spec: dict[str, Any], pointer: str) -> str:
    number = as_finite_number(raw_value, pointer)
    kind = spec["kind"]
    digits = int(spec["digits"])
    if digits < 0:
        raise ValueError(f"Negative digits in formatting spec for {pointer!r}")

    if kind == "percent":
        number *= 100.0
    elif kind != "number":
        raise ValueError(f"Unsupported metric format kind: {kind!r}")

    number *= float(spec.get("scale", 1.0))
    show_plus = bool(spec.get("show_plus", False))
    use_grouping = bool(spec.get("thousands", False))
    sign = "+" if show_plus else ""
    grouping = "," if use_grouping else ""
    rendered = f"{number:{sign}{grouping}.{digits}f}"
    return f"{rendered}{spec.get('suffix', '')}"


def _glyph_width(character: str) -> float:
    """Return a conservative width in CJK-em units for deterministic wrapping."""
    if character == "\n":
        return 0.0
    if character.isspace():
        return 0.45
    if unicodedata.east_asian_width(character) in {"W", "F", "A"}:
        return 1.0
    # Latin capitals and digits in Heiti TC are wider than half a CJK glyph.
    return 0.65


def wrap_zh(text: str, width: float) -> str:
    """Wrap mixed Chinese/Latin copy by rendered-width units, never by words.

    ``textwrap`` treats an unspaced Chinese clause as one word.  Its nominal
    character limit therefore produced lines wider than the cards.  Walking
    glyphs also makes punctuation and embedded Latin tokens wrap predictably.
    """
    if width <= 0:
        raise ValueError("wrap width must be positive")

    lines: list[str] = []
    line: list[str] = []
    line_width = 0.0
    for character in text:
        if character == "\n":
            lines.append("".join(line).rstrip())
            line = []
            line_width = 0.0
            continue

        character_width = _glyph_width(character)
        if line and line_width + character_width > width:
            lines.append("".join(line).rstrip())
            line = []
            line_width = 0.0
            if character.isspace():
                continue
        line.append(character)
        line_width += character_width

    if line or not lines:
        lines.append("".join(line).rstrip())
    return "\n".join(lines)


def rounded_box(
    ax: plt.Axes,
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    facecolor: str,
    edgecolor: str = "none",
    linewidth: float = 0.0,
    radius: float = 0.018,
) -> FancyBboxPatch:
    patch = FancyBboxPatch(
        (x, y),
        width,
        height,
        boxstyle=f"round,pad=0.012,rounding_size={radius}",
        transform=ax.transAxes,
        facecolor=facecolor,
        edgecolor=edgecolor,
        linewidth=linewidth,
    )
    ax.add_patch(patch)
    return patch


def draw_header_icon(ax: plt.Axes, panel_name: str) -> None:
    """Draw a restrained, non-numeric line icon in reserved header space."""
    x0, y0 = 0.917, 0.875
    if panel_name == "panel_question":
        ax.add_patch(
            Circle(
                (x0, y0),
                0.042,
                transform=ax.transAxes,
                facecolor="none",
                edgecolor=WHITE,
                linewidth=2.2,
            )
        )
        ax.plot(
            [x0 - 0.020, x0 + 0.020],
            [y0, y0],
            color=WHITE,
            linewidth=2.2,
            transform=ax.transAxes,
        )
        ax.plot(
            [x0, x0],
            [y0 - 0.020, y0 + 0.020],
            color=WHITE,
            linewidth=2.2,
            transform=ax.transAxes,
        )
    elif panel_name == "panel_result":
        for i, height in enumerate((0.024, 0.048, 0.074)):
            ax.add_patch(
                Rectangle(
                    (x0 - 0.043 + i * 0.032, y0 - 0.038),
                    0.018,
                    height,
                    transform=ax.transAxes,
                    facecolor=WHITE,
                    edgecolor="none",
                )
            )
    else:
        ax.plot(
            [x0 - 0.045, x0 - 0.010, x0 + 0.045],
            [y0 - 0.020, y0 + 0.030, y0 - 0.030],
            color=WHITE,
            linewidth=3.0,
            solid_capstyle="round",
            transform=ax.transAxes,
        )
        ax.add_patch(
            Circle(
                (x0 - 0.045, y0 - 0.020),
                0.008,
                transform=ax.transAxes,
                facecolor=WHITE,
                edgecolor="none",
            )
        )


def metric_palette(panel_name: str, index: int) -> tuple[str, str]:
    if panel_name == "panel_question":
        return ((TEAL_PALE, TEAL), (BLUE_PALE, BLUE))[index % 2]
    if panel_name == "panel_result":
        return (
            (TEAL_PALE, TEAL),
            (BLUE_PALE, BLUE),
            (AMBER_PALE, AMBER),
        )[index % 3]
    return ((TEAL_PALE, TEAL), (BLUE_PALE, BLUE))[index % 2]


def render_panel(
    panel: dict[str, Any],
    evidence: dict[str, Any],
    source_labels: dict[str, str],
) -> None:
    name = panel["name"]
    blocks = panel["blocks"]
    text_blocks = [block for block in blocks if block["kind"] == "text"]
    metric_blocks = [block for block in blocks if block["kind"] == "metric"]
    if len(text_blocks) != 1:
        raise ValueError(f"{name}: expected exactly one text block")
    if not metric_blocks:
        raise ValueError(f"{name}: expected at least one metric block")

    fig = plt.figure(
        figsize=(WIDTH_PX / DPI, HEIGHT_PX / DPI),
        dpi=DPI,
        facecolor=WHITE,
    )
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    # Header: title and subtitle occupy separate fixed bands.
    ax.add_patch(
        Rectangle(
            (0, 0.755),
            1,
            0.245,
            transform=ax.transAxes,
            facecolor=NAVY,
            edgecolor="none",
        )
    )
    ax.add_patch(
        Rectangle(
            (0, 0.755),
            0.012,
            0.245,
            transform=ax.transAxes,
            facecolor=TEAL,
            edgecolor="none",
        )
    )
    ax.text(
        0.052,
        0.928,
        wrap_zh(panel["title"], 27),
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=24,
        fontweight="bold",
        color=WHITE,
        linespacing=1.18,
    )
    ax.text(
        0.052,
        0.813,
        wrap_zh(panel["alt"], 47),
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=13,
        color="#DCE8F1",
        linespacing=1.32,
    )
    draw_header_icon(ax, name)

    # Narrative card on the left.
    rounded_box(
        ax,
        0.050,
        0.154,
        0.505,
        0.548,
        facecolor=PALE,
        edgecolor=LINE,
        linewidth=1.0,
    )
    text_block = text_blocks[0]
    ax.text(
        0.082,
        0.653,
        text_block["heading"],
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=20,
        fontweight="bold",
        color=NAVY,
    )
    ax.plot(
        [0.082, 0.168],
        [0.613, 0.613],
        transform=ax.transAxes,
        color=TEAL,
        linewidth=4.0,
        solid_capstyle="round",
    )
    if len(text_block["body"]) != 2:
        raise ValueError(f"{name}: layout requires exactly two body paragraphs")
    body_fontsize = 14.5
    body_linespacing = 1.42
    body_y = 0.568
    for paragraph in text_block["body"]:
        wrapped_paragraph = wrap_zh(paragraph, 21)
        ax.text(
            0.082,
            body_y,
            wrapped_paragraph,
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=body_fontsize,
            color=INK,
            linespacing=body_linespacing,
        )
        line_count = wrapped_paragraph.count("\n") + 1
        line_step = body_fontsize * DPI / 72 / HEIGHT_PX * body_linespacing
        body_y -= line_count * line_step + 0.034

    # Metric cards on the right; card count determines safe vertical spacing.
    card_x = 0.595
    card_width = 0.355
    card_top = 0.702
    card_bottom = 0.154
    gap = 0.020
    card_height = (
        card_top - card_bottom - gap * (len(metric_blocks) - 1)
    ) / len(metric_blocks)
    for index, block in enumerate(metric_blocks):
        card_y = card_top - (index + 1) * card_height - index * gap
        bg, accent = metric_palette(name, index)
        rounded_box(
            ax,
            card_x,
            card_y,
            card_width,
            card_height,
            facecolor=bg,
            edgecolor="none",
        )
        ax.add_patch(
            Rectangle(
                (card_x, card_y),
                0.008,
                card_height,
                transform=ax.transAxes,
                facecolor=accent,
                edgecolor="none",
            )
        )

        value_spec = block["value"]
        source_key = value_spec["source"]
        if source_key not in evidence:
            raise KeyError(f"{name}: unknown evidence source {source_key!r}")
        pointer = value_spec["path"]
        raw_value = resolve_json_pointer(evidence[source_key], pointer)
        rendered_value = format_metric(
            raw_value,
            value_spec["format"],
            pointer,
        )

        compact_cards = len(metric_blocks) == 3
        label_y = card_y + card_height - (0.030 if compact_cards else 0.038)
        value_y = card_y + (0.024 if compact_cards else 0.040)
        ax.text(
            card_x + 0.030,
            label_y,
            wrap_zh(block["label"], 18 if compact_cards else 19),
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=11.5 if compact_cards else 13,
            color=MUTED,
            linespacing=1.20,
        )
        ax.text(
            card_x + 0.030,
            value_y,
            rendered_value,
            transform=ax.transAxes,
            ha="left",
            va="bottom",
            fontsize=24 if compact_cards else 31,
            fontweight="bold",
            color=accent,
        )

    # Footer uses the strict plan label verbatim, without deriving a name.
    panel_sources = panel["sources"]
    if not panel_sources:
        raise ValueError(f"{name}: panel has no declared source")
    labels = []
    for source_key in panel_sources:
        if source_key not in source_labels:
            raise KeyError(f"{name}: missing label for source {source_key!r}")
        labels.append(source_labels[source_key])
    source_line = "資料來源：" + "；".join(labels)
    ax.plot(
        [0.05, 0.95],
        [0.105, 0.105],
        transform=ax.transAxes,
        color=LINE,
        linewidth=1.0,
    )
    ax.text(
        0.050,
        0.069,
        wrap_zh(source_line, 120),
        transform=ax.transAxes,
        ha="left",
        va="center",
        fontsize=9,
        color=MUTED,
        linespacing=1.15,
    )

    output_path = Path(out_dir) / f"{name}.png"
    fig.savefig(
        output_path,
        dpi=DPI,
        facecolor=WHITE,
        edgecolor="none",
        bbox_inches=None,
        pad_inches=0,
        metadata={
            "Title": panel["title"],
            "Description": panel["alt"],
        },
    )
    plt.close(fig)


def validate_plan(plan: dict[str, Any]) -> None:
    if plan["schema_version"] != 1:
        raise ValueError(
            f"Unsupported plan schema_version: {plan['schema_version']!r}"
        )
    evidence_spec = plan["evidence"]
    if set(evidence_spec) != {"results"}:
        raise ValueError(
            "This renderer requires exactly the strict-plan 'results' evidence"
        )
    if evidence_spec["results"]["label"] != EXPECTED_SOURCE_LABEL:
        raise ValueError("Strict-plan results label changed unexpectedly")

    panels = plan["panels"]
    names = [panel["name"] for panel in panels]
    if len(names) != len(set(names)):
        raise ValueError("Duplicate panel names in strict plan")
    if set(names) != EXPECTED_PANELS:
        raise ValueError(
            f"Unexpected panel set: {sorted(names)!r}; "
            f"expected {sorted(EXPECTED_PANELS)!r}"
        )
    for panel in panels:
        if panel["style"] != "professional":
            raise ValueError(
                f"{panel['name']}: only professional style is supported"
            )


def main() -> None:
    plan = load_json(PLAN_PATH)
    results = load_json(RESULTS_PATH)
    require_nonempty_article(ARTICLE_PATH)
    validate_plan(plan)

    evidence = {"results": results}
    source_labels = {
        source_key: source_spec["label"]
        for source_key, source_spec in plan["evidence"].items()
    }

    os.makedirs(out_dir, exist_ok=True)
    for panel in plan["panels"]:
        render_panel(panel, evidence, source_labels)


if __name__ == "__main__":
    main()
