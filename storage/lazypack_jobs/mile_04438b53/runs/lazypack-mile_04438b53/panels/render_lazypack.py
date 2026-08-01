#!/usr/bin/env python3
"""Render the three data-bound PNG panels for mile_04438b53.

Every displayed metric is resolved from the JSON Pointer declared in the
strict plan.  Missing evidence, malformed values, or an altered plan contract
raise immediately instead of producing a partial or misleading image.
"""

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


PLAN_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_04438b53/runs/lazypack-mile_04438b53/plan.json"
)
RESULTS_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/K1342/K1342_results.json"
)
ARTICLE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_04438b53/runs/lazypack-mile_04438b53/panels/"
    "mile_04438b53_article.md"
)
out_dir = (
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_04438b53/runs/lazypack-mile_04438b53/panels"
)

WIDTH_PX = 1600
HEIGHT_PX = 1000
DPI = 150

EXPECTED_PANELS = (
    "panel_method",
    "panel_results",
    "panel_takeaway",
)
EXPECTED_SOURCE_LABEL = (
    "experiment K1342 results (free public-data proxy for NYSE/Nasdaq "
    "closing-auction MOC imbalance: signed-volume pressure measured "
    "15:30-15:48 ET, tested against three holding windows on 10 US tickers "
    "after a 3.4 bps round-trip cost; overall verdict NULL)"
)

NAVY = "#13263D"
NAVY_2 = "#203B59"
INK = "#172535"
MUTED = "#586777"
FAINT = "#82909E"
PAPER = "#F7F9FC"
CARD = "#FFFFFF"
LINE = "#DDE4EC"
TEAL = "#0B7B78"
TEAL_SOFT = "#DCEFED"
RED = "#B6423C"
RED_SOFT = "#F6E3E1"
AMBER = "#AA6B12"
AMBER_SOFT = "#F6EBD8"


plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def require_text(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"Expected non-empty text at {where}")
    return value


def resolve_json_pointer(document: Any, pointer: str) -> Any:
    """Resolve an RFC 6901-style JSON Pointer and raise on any missing field."""
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValueError(f"Invalid JSON Pointer: {pointer!r}")
    current = document
    for raw_token in pointer[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            if token not in current:
                raise KeyError(f"Missing evidence field at {pointer!r}: {token!r}")
            current = current[token]
        elif isinstance(current, list):
            try:
                current = current[int(token)]
            except (ValueError, IndexError) as exc:
                raise KeyError(f"Invalid list index in {pointer!r}: {token!r}") from exc
        else:
            raise KeyError(f"Cannot descend through scalar while resolving {pointer!r}")
    return current


def format_bound_value(value: Any, fmt: dict[str, Any], pointer: str) -> str:
    kind = fmt.get("kind")
    if kind == "text":
        return require_text(value, pointer)
    if kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"Expected integer at {pointer}, got {type(value).__name__}")
        return f"{value:d}"
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"Expected number at {pointer}, got {type(value).__name__}")
        number = float(value)
        if not math.isfinite(number):
            raise ValueError(f"Non-finite number at {pointer}")
        digits = fmt.get("digits")
        if not isinstance(digits, int) or digits < 0 or digits > 8:
            raise ValueError(f"Invalid digits format at {pointer}: {digits!r}")
        sign = "+" if fmt.get("show_plus") else ""
        return f"{number:{sign}.{digits}f}"
    raise ValueError(f"Unsupported format kind at {pointer}: {kind!r}")


def visual_width(text: str) -> float:
    """Approximate line width: CJK glyphs are roughly twice Latin glyphs."""
    return sum(1.0 if ord(char) > 255 else 0.52 for char in text)


def wrap_visual(text: str, max_units: float) -> list[str]:
    if not text:
        return [""]
    lines: list[str] = []
    current = ""
    current_width = 0.0
    for char in text:
        char_width = 1.0 if ord(char) > 255 else 0.52
        if current and current_width + char_width > max_units:
            lines.append(current.rstrip())
            current = char.lstrip()
            current_width = visual_width(current)
        else:
            current += char
            current_width += char_width
    if current:
        lines.append(current.rstrip())
    return lines


def add_card(
    fig: plt.Figure,
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    label: str,
    value: str,
    note: str | None,
    accent: str,
    soft: str,
) -> None:
    card = FancyBboxPatch(
        (x, y),
        width,
        height,
        boxstyle="round,pad=0.008,rounding_size=0.014",
        transform=fig.transFigure,
        facecolor=CARD,
        edgecolor=LINE,
        linewidth=1.15,
        zorder=1,
    )
    fig.patches.append(card)
    fig.patches.append(
        Rectangle(
            (x, y),
            0.008,
            height,
            transform=fig.transFigure,
            facecolor=accent,
            edgecolor="none",
            zorder=2,
        )
    )
    fig.patches.append(
        Circle(
            (x + 0.037, y + height - 0.041),
            0.013,
            transform=fig.transFigure,
            facecolor=soft,
            edgecolor="none",
            zorder=2,
        )
    )
    fig.text(
        x + 0.062,
        y + height - 0.024,
        "\n".join(wrap_visual(label, 25)),
        ha="left",
        va="top",
        fontsize=10.7,
        color=MUTED,
        linespacing=1.08,
        zorder=3,
    )
    fig.text(
        x + 0.032,
        y + 0.060,
        value,
        ha="left",
        va="bottom",
        fontsize=27,
        fontweight="bold",
        color=accent,
        zorder=3,
    )
    if note:
        fig.text(
            x + 0.032,
            y + 0.020,
            "\n".join(wrap_visual(note, 31)),
            ha="left",
            va="bottom",
            fontsize=9.2,
            color=FAINT,
            linespacing=1.08,
            zorder=3,
        )


def add_body_block(fig: plt.Figure, block: dict[str, Any], accent: str) -> None:
    heading = require_text(block.get("heading"), "panel text heading")
    body = block.get("body")
    if not isinstance(body, list) or not body:
        raise TypeError("Panel text body must be a non-empty list")
    paragraphs = [require_text(item, "panel text body") for item in body]

    fig.patches.append(
        Rectangle(
            (0.058, 0.725),
            0.030,
            0.006,
            transform=fig.transFigure,
            facecolor=accent,
            edgecolor="none",
        )
    )
    fig.text(
        0.058,
        0.700,
        heading,
        ha="left",
        va="top",
        fontsize=17,
        fontweight="bold",
        color=INK,
    )

    y = 0.642
    for paragraph in paragraphs:
        # Keep body copy inside the left column.  At 150 DPI a 12.3 pt CJK
        # glyph is roughly 25 px wide, so the old 38-unit wrap could extend
        # beyond x=0.60 and collide with the metric text that starts at
        # x=0.617.  Twenty-five units end near x=0.46, leaving a deliberate
        # gutter before the cards at x=0.555 even on the longest line.
        lines = wrap_visual(paragraph, 25)
        fig.text(
            0.058,
            y,
            "\n".join(lines),
            ha="left",
            va="top",
            fontsize=12.3,
            color=MUTED,
            linespacing=1.48,
        )
        y -= len(lines) * 0.034 + 0.032
    if y < 0.135:
        raise ValueError("Body copy exceeds its reserved layout area")


def panel_palette(name: str) -> tuple[str, str]:
    if name == "panel_results":
        return RED, RED_SOFT
    if name == "panel_takeaway":
        return AMBER, AMBER_SOFT
    return TEAL, TEAL_SOFT


def validate_contract(plan: dict[str, Any], article: str) -> list[dict[str, Any]]:
    require_text(article, str(ARTICLE_PATH))
    evidence = plan.get("evidence")
    if not isinstance(evidence, dict) or "results" not in evidence:
        raise KeyError("Strict plan is missing evidence.results")
    results_evidence = evidence["results"]
    if not isinstance(results_evidence, dict):
        raise TypeError("Strict plan evidence.results must be an object")
    source_label = require_text(results_evidence.get("label"), "evidence.results.label")
    if source_label != EXPECTED_SOURCE_LABEL:
        raise ValueError("Strict-plan source label changed; refusing to guess a replacement")

    panels = plan.get("panels")
    if not isinstance(panels, list):
        raise TypeError("Strict plan panels must be a list")
    names = tuple(panel.get("name") for panel in panels if isinstance(panel, dict))
    if names != EXPECTED_PANELS:
        raise ValueError(f"Unexpected panel contract: {names!r}")
    return panels


def render_panel(
    panel: dict[str, Any], results: dict[str, Any], source_label: str
) -> None:
    name = require_text(panel.get("name"), "panel.name")
    title = require_text(panel.get("title"), f"{name}.title")
    alt = require_text(panel.get("alt"), f"{name}.alt")
    if panel.get("sources") != ["results"]:
        raise ValueError(f"{name} must use only the declared results evidence")
    blocks = panel.get("blocks")
    if not isinstance(blocks, list) or len(blocks) != 4:
        raise ValueError(f"{name} must contain one text block and three metrics")
    if blocks[0].get("kind") != "text":
        raise ValueError(f"{name} first block must be text")

    metrics: list[tuple[str, str, str | None]] = []
    for index, block in enumerate(blocks[1:], start=1):
        if not isinstance(block, dict) or block.get("kind") != "metric":
            raise ValueError(f"{name} block {index} must be a metric")
        label = require_text(block.get("label"), f"{name}.blocks[{index}].label")
        value_spec = block.get("value")
        if not isinstance(value_spec, dict) or value_spec.get("source") != "results":
            raise ValueError(f"{name} metric {index} must bind to results")
        pointer = require_text(value_spec.get("path"), f"{name} metric path")
        fmt = value_spec.get("format")
        if not isinstance(fmt, dict):
            raise TypeError(f"{name} metric {index} format must be an object")
        raw_value = resolve_json_pointer(results, pointer)
        rendered = format_bound_value(raw_value, fmt, pointer)
        note_value = block.get("note")
        note = None if note_value is None else require_text(note_value, f"{name} metric note")
        metrics.append((label, rendered, note))

    accent, soft = panel_palette(name)
    fig = plt.figure(
        figsize=(WIDTH_PX / DPI, HEIGHT_PX / DPI),
        dpi=DPI,
        facecolor=PAPER,
    )
    fig.patches.append(
        Rectangle(
            (0, 0.805),
            1,
            0.195,
            transform=fig.transFigure,
            facecolor=NAVY,
            edgecolor="none",
            zorder=0,
        )
    )
    fig.patches.append(
        Rectangle(
            (0, 0.805),
            0.014,
            0.195,
            transform=fig.transFigure,
            facecolor=accent,
            edgecolor="none",
            zorder=1,
        )
    )
    fig.text(
        0.058,
        0.965,
        "VolPred｜研究圖解",
        ha="left",
        va="top",
        fontsize=10.5,
        color="#BFD0E1",
    )
    title_lines = wrap_visual(title, 39)
    if len(title_lines) > 2:
        raise ValueError(f"Title is too long for the reserved header: {title!r}")
    fig.text(
        0.058,
        0.923,
        "\n".join(title_lines),
        ha="left",
        va="top",
        fontsize=24,
        fontweight="bold",
        color="white",
        linespacing=1.18,
    )

    add_body_block(fig, blocks[0], accent)
    for (label, value, note), y in zip(metrics, (0.607, 0.393, 0.179), strict=True):
        add_card(
            fig,
            x=0.555,
            y=y,
            width=0.390,
            height=0.174,
            label=label,
            value=value,
            note=note,
            accent=accent,
            soft=soft,
        )

    fig.patches.append(
        Rectangle(
            (0.058, 0.112),
            0.887,
            0.0015,
            transform=fig.transFigure,
            facecolor=LINE,
            edgecolor="none",
        )
    )
    wrapped_source = "\n".join(textwrap.wrap(source_label, width=150))
    fig.text(
        0.058,
        0.091,
        "資料來源：" + wrapped_source,
        ha="left",
        va="top",
        fontsize=7.4,
        color=FAINT,
        linespacing=1.25,
    )
    fig.text(
        0.945,
        0.026,
        "本文為資料分析，不是投資建議。",
        ha="right",
        va="bottom",
        fontsize=8.5,
        color=FAINT,
    )

    output_path = Path(out_dir) / f"{name}.png"
    fig.savefig(
        output_path,
        dpi=DPI,
        facecolor=PAPER,
        edgecolor="none",
        metadata={"Title": title, "Description": alt},
    )
    plt.close(fig)


def main() -> None:
    plan = load_json(PLAN_PATH)
    results = load_json(RESULTS_PATH)
    article = ARTICLE_PATH.read_text(encoding="utf-8")
    if not isinstance(plan, dict) or not isinstance(results, dict):
        raise TypeError("Plan and results evidence must both be JSON objects")
    panels = validate_contract(plan, article)
    source_label = plan["evidence"]["results"]["label"]
    os.makedirs(out_dir, exist_ok=True)
    for panel in panels:
        render_panel(panel, results, source_label)


if __name__ == "__main__":
    main()
