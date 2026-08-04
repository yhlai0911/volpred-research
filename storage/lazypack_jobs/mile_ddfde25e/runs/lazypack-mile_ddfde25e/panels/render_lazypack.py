#!/usr/bin/env python3
"""Render the three evidence-bound PNG panels for the mile_ddfde25e article."""

from __future__ import annotations

import json
import os
import textwrap
from pathlib import Path
from typing import Any, Mapping, Sequence

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle


PLAN_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_ddfde25e/runs/lazypack-mile_ddfde25e/plan.json"
)
RESULTS_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1584/k1584_results.json"
)
ARTICLE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_ddfde25e/runs/lazypack-mile_ddfde25e/panels/"
    "mile_ddfde25e_article.md"
)
OUT_DIR = (
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_ddfde25e/runs/lazypack-mile_ddfde25e/panels"
)

FIGURE_SIZE = (1600 / 150, 1000 / 150)
DPI = 150

NAVY = "#17263C"
INK = "#192534"
MUTED = "#526273"
ACCENT = "#0F7C7E"
ACCENT_SOFT = "#E8F3F3"
NEGATIVE = "#A84A3A"
NEGATIVE_SOFT = "#F8ECE9"
CARD = "#F4F7FA"
BORDER = "#D9E1E8"
WHITE = "#FFFFFF"

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise TypeError(f"Expected a JSON object at {path}")
    return value


def require(mapping: Mapping[str, Any], key: str, context: str) -> Any:
    if key not in mapping:
        raise KeyError(f"Missing {context}.{key}")
    return mapping[key]


def require_mapping(value: Any, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"Expected object at {context}")
    return value


def require_sequence(value: Any, context: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise TypeError(f"Expected array at {context}")
    return value


def json_pointer(document: Any, pointer: str) -> Any:
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValueError(f"Invalid JSON pointer: {pointer!r}")
    current = document
    for raw_token in pointer.split("/")[1:]:
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, Mapping):
            if token not in current:
                raise KeyError(f"Missing evidence field at {pointer!r}: {token!r}")
            current = current[token]
        elif isinstance(current, Sequence) and not isinstance(current, (str, bytes)):
            current = current[int(token)]
        else:
            raise TypeError(f"Cannot traverse {pointer!r} through {type(current).__name__}")
    return current


def find_panel(plan: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    panels = require_sequence(require(plan, "panels", "plan"), "plan.panels")
    for item in panels:
        panel = require_mapping(item, "plan.panels[]")
        if require(panel, "name", "panel") == name:
            return panel
    raise KeyError(f"Missing panel {name!r} in plan")


def wrap(text: str, width: int) -> str:
    if not isinstance(text, str) or not text:
        raise ValueError("Expected non-empty text")
    lines = textwrap.wrap(
        text,
        width=width,
        break_long_words=True,
        break_on_hyphens=False,
        replace_whitespace=False,
        drop_whitespace=True,
    )
    return "\n".join(lines)


def format_metric(spec: Mapping[str, Any], sources: Mapping[str, Any]) -> str:
    source_name = require(spec, "source", "metric.value")
    pointer = require(spec, "path", "metric.value")
    fmt = require_mapping(require(spec, "format", "metric.value"), "metric.value.format")
    if source_name not in sources:
        raise KeyError(f"Unknown evidence source {source_name!r}")
    raw = json_pointer(sources[source_name], pointer)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise TypeError(f"Expected numeric evidence at {pointer!r}")

    kind = require(fmt, "kind", "metric.value.format")
    if kind == "integer":
        if int(raw) != raw:
            raise ValueError(f"Expected integer evidence at {pointer!r}")
        return f"{int(raw):,}"

    digits = require(fmt, "digits", "metric.value.format")
    if isinstance(digits, bool) or not isinstance(digits, int) or digits < 0:
        raise TypeError(f"Invalid digits for {pointer!r}")
    if kind == "percent":
        return f"{raw * 100:.{digits}f}%"
    if kind == "number":
        suffix = "%" if pointer.endswith("_pct") else ""
        return f"{raw:.{digits}f}{suffix}"
    raise ValueError(f"Unsupported metric format kind {kind!r}")


def metric_payload(
    block: Mapping[str, Any], sources: Mapping[str, Any], context: str
) -> tuple[str, str, str]:
    if require(block, "kind", context) != "metric":
        raise ValueError(f"Expected metric block at {context}")
    label = require(block, "label", context)
    note = require(block, "note", context)
    value_spec = require_mapping(require(block, "value", context), f"{context}.value")
    return label, format_metric(value_spec, sources), note


def text_payload(block: Mapping[str, Any], context: str) -> tuple[str, list[str]]:
    if require(block, "kind", context) != "text":
        raise ValueError(f"Expected text block at {context}")
    heading = require(block, "heading", context)
    body_raw = require_sequence(require(block, "body", context), f"{context}.body")
    body = []
    for index, item in enumerate(body_raw):
        if not isinstance(item, str) or not item:
            raise TypeError(f"Expected non-empty string at {context}.body[{index}]")
        body.append(item)
    return heading, body


def new_figure() -> Figure:
    fig = plt.figure(figsize=FIGURE_SIZE, dpi=DPI, facecolor=WHITE)
    fig.add_artist(
        Rectangle(
            (0, 0.865),
            1,
            0.135,
            transform=fig.transFigure,
            facecolor=NAVY,
            edgecolor="none",
            zorder=0,
        )
    )
    return fig


def add_title(fig: Figure, title: str) -> None:
    fig.text(
        0.06,
        0.932,
        title,
        ha="left",
        va="center",
        color=WHITE,
        fontsize=27,
        fontweight="bold",
    )


def add_card(
    fig: Figure,
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    facecolor: str = CARD,
    accent: str = ACCENT,
) -> None:
    fig.add_artist(
        Rectangle(
            (x, y),
            width,
            height,
            transform=fig.transFigure,
            facecolor=facecolor,
            edgecolor=BORDER,
            linewidth=1.0,
            zorder=0,
        )
    )
    fig.add_artist(
        Rectangle(
            (x, y),
            0.007,
            height,
            transform=fig.transFigure,
            facecolor=accent,
            edgecolor="none",
            zorder=1,
        )
    )


def add_footer(fig: Figure, source_label: str) -> None:
    fig.add_artist(
        Rectangle(
            (0.06, 0.168),
            0.88,
            0.0015,
            transform=fig.transFigure,
            facecolor=BORDER,
            edgecolor="none",
        )
    )
    fig.text(
        0.06,
        0.095,
        wrap(f"資料來源｜{source_label}", 70),
        ha="left",
        va="center",
        color=MUTED,
        fontsize=8.5,
        linespacing=1.35,
    )


def add_metric_card(
    fig: Figure,
    bounds: tuple[float, float, float, float],
    *,
    label: str,
    value: str,
    note: str,
    label_width: int,
    note_width: int,
    negative: bool = False,
) -> None:
    x, y, width, height = bounds
    accent = NEGATIVE if negative else ACCENT
    face = NEGATIVE_SOFT if negative else ACCENT_SOFT
    add_card(fig, x, y, width, height, facecolor=face, accent=accent)
    fig.text(
        x + 0.028,
        y + height - 0.052,
        wrap(label, label_width),
        ha="left",
        va="top",
        color=INK,
        fontsize=12.5,
        fontweight="bold",
        linespacing=1.28,
    )
    fig.text(
        x + 0.028,
        y + height * 0.49,
        value,
        ha="left",
        va="center",
        color=accent,
        fontsize=29,
        fontweight="bold",
    )
    fig.text(
        x + 0.028,
        y + 0.038,
        wrap(note, note_width),
        ha="left",
        va="bottom",
        color=MUTED,
        fontsize=10.7,
        linespacing=1.34,
    )


def render_framework(
    panel: Mapping[str, Any], sources: Mapping[str, Any], source_label: str
) -> Figure:
    blocks = require_sequence(require(panel, "blocks", "panel_framework"), "panel_framework.blocks")
    if len(blocks) != 3:
        raise ValueError("panel_framework must contain exactly three blocks")
    heading, body = text_payload(
        require_mapping(blocks[0], "panel_framework.blocks[0]"),
        "panel_framework.blocks[0]",
    )
    metric_1 = metric_payload(
        require_mapping(blocks[1], "panel_framework.blocks[1]"),
        sources,
        "panel_framework.blocks[1]",
    )
    metric_2 = metric_payload(
        require_mapping(blocks[2], "panel_framework.blocks[2]"),
        sources,
        "panel_framework.blocks[2]",
    )

    fig = new_figure()
    add_title(fig, require(panel, "title", "panel_framework"))

    add_card(fig, 0.06, 0.235, 0.53, 0.555, facecolor=CARD, accent=ACCENT)
    fig.text(
        0.098,
        0.735,
        heading,
        ha="left",
        va="top",
        color=INK,
        fontsize=19,
        fontweight="bold",
    )
    fig.add_artist(
        Rectangle(
            (0.098, 0.649),
            0.06,
            0.004,
            transform=fig.transFigure,
            facecolor=ACCENT,
            edgecolor="none",
        )
    )
    fig.text(
        0.098,
        0.605,
        wrap(body[0], 24),
        ha="left",
        va="top",
        color=INK,
        fontsize=14.5,
        linespacing=1.48,
    )
    fig.text(
        0.098,
        0.455,
        wrap(body[1], 24),
        ha="left",
        va="top",
        color=INK,
        fontsize=14.5,
        linespacing=1.48,
    )

    add_metric_card(
        fig,
        (0.625, 0.53, 0.315, 0.26),
        label=metric_1[0],
        value=metric_1[1],
        note=metric_1[2],
        label_width=14,
        note_width=18,
    )
    add_metric_card(
        fig,
        (0.625, 0.235, 0.315, 0.26),
        label=metric_2[0],
        value=metric_2[1],
        note=metric_2[2],
        label_width=14,
        note_width=18,
    )
    add_footer(fig, source_label)
    return fig


def render_numbers(
    panel: Mapping[str, Any], sources: Mapping[str, Any], source_label: str
) -> Figure:
    blocks = require_sequence(require(panel, "blocks", "panel_numbers"), "panel_numbers.blocks")
    if len(blocks) != 3:
        raise ValueError("panel_numbers must contain exactly three blocks")
    metrics = [
        metric_payload(
            require_mapping(block, f"panel_numbers.blocks[{index}]"),
            sources,
            f"panel_numbers.blocks[{index}]",
        )
        for index, block in enumerate(blocks)
    ]

    fig = new_figure()
    add_title(fig, require(panel, "title", "panel_numbers"))
    positions = (
        (0.06, 0.245, 0.27, 0.545),
        (0.365, 0.245, 0.27, 0.545),
        (0.67, 0.245, 0.27, 0.545),
    )
    for index, (metric, bounds) in enumerate(zip(metrics, positions)):
        add_metric_card(
            fig,
            bounds,
            label=metric[0],
            value=metric[1],
            note=metric[2],
            label_width=12,
            note_width=14,
            negative=index < 2,
        )
    add_footer(fig, source_label)
    return fig


def render_takeaway(
    panel: Mapping[str, Any], sources: Mapping[str, Any], source_label: str
) -> Figure:
    blocks = require_sequence(require(panel, "blocks", "panel_takeaway"), "panel_takeaway.blocks")
    if len(blocks) != 3:
        raise ValueError("panel_takeaway must contain exactly three blocks")
    metric = metric_payload(
        require_mapping(blocks[0], "panel_takeaway.blocks[0]"),
        sources,
        "panel_takeaway.blocks[0]",
    )
    first_heading, first_body = text_payload(
        require_mapping(blocks[1], "panel_takeaway.blocks[1]"),
        "panel_takeaway.blocks[1]",
    )
    second_heading, second_body = text_payload(
        require_mapping(blocks[2], "panel_takeaway.blocks[2]"),
        "panel_takeaway.blocks[2]",
    )

    fig = new_figure()
    add_title(fig, require(panel, "title", "panel_takeaway"))
    add_metric_card(
        fig,
        (0.06, 0.235, 0.275, 0.555),
        label=metric[0],
        value=metric[1],
        note=metric[2],
        label_width=12,
        note_width=14,
    )

    add_card(fig, 0.375, 0.53, 0.565, 0.26, facecolor=CARD, accent=NEGATIVE)
    fig.text(
        0.412,
        0.737,
        first_heading,
        ha="left",
        va="top",
        color=INK,
        fontsize=17,
        fontweight="bold",
    )
    fig.text(
        0.412,
        0.665,
        wrap(first_body[0], 28),
        ha="left",
        va="top",
        color=INK,
        fontsize=12.8,
        linespacing=1.38,
    )
    fig.text(
        0.412,
        0.584,
        wrap(first_body[1], 29),
        ha="left",
        va="top",
        color=MUTED,
        fontsize=12.2,
        linespacing=1.35,
    )

    add_card(fig, 0.375, 0.235, 0.565, 0.26, facecolor=ACCENT_SOFT, accent=ACCENT)
    fig.text(
        0.412,
        0.442,
        second_heading,
        ha="left",
        va="top",
        color=INK,
        fontsize=17,
        fontweight="bold",
    )
    fig.text(
        0.412,
        0.37,
        wrap(second_body[0], 28),
        ha="left",
        va="top",
        color=INK,
        fontsize=12.8,
        linespacing=1.38,
    )
    fig.text(
        0.412,
        0.302,
        wrap(second_body[1], 29),
        ha="left",
        va="top",
        color=MUTED,
        fontsize=12.2,
        linespacing=1.35,
    )
    add_footer(fig, source_label)
    return fig


def save_panel(fig: Figure, panel: Mapping[str, Any]) -> None:
    name = require(panel, "name", "panel")
    title = require(panel, "title", name)
    alt = require(panel, "alt", name)
    output_path = os.path.join(OUT_DIR, f"{name}.png")
    fig.savefig(
        output_path,
        dpi=DPI,
        facecolor=WHITE,
        edgecolor="none",
        metadata={"Title": title, "Description": alt},
    )
    plt.close(fig)


def main() -> None:
    plan = load_json(PLAN_PATH)
    results = load_json(RESULTS_PATH)
    article = ARTICLE_PATH.read_text(encoding="utf-8")
    if not article.strip():
        raise ValueError(f"Article evidence is empty: {ARTICLE_PATH}")

    evidence = require_mapping(require(plan, "evidence", "plan"), "plan.evidence")
    results_evidence = require_mapping(
        require(evidence, "results", "plan.evidence"), "plan.evidence.results"
    )
    source_label = require(results_evidence, "label", "plan.evidence.results")
    sources = {"results": results}

    framework = find_panel(plan, "panel_framework")
    numbers = find_panel(plan, "panel_numbers")
    takeaway = find_panel(plan, "panel_takeaway")

    os.makedirs(OUT_DIR, exist_ok=True)
    save_panel(render_framework(framework, sources, source_label), framework)
    save_panel(render_numbers(numbers, sources, source_label), numbers)
    save_panel(render_takeaway(takeaway, sources, source_label), takeaway)


if __name__ == "__main__":
    main()
