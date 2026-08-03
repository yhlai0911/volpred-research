#!/usr/bin/env python3
"""Render the three data-bound PNG panels for mile_b4223d34.

The panel copy, metric JSON pointers, precision, and reader-facing source label
come from the strict plan.  Metric values come only from K1354_results.json.
Missing or malformed evidence raises immediately instead of producing a partial
or guessed graphic.
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
from matplotlib.patches import FancyBboxPatch, Rectangle


PLAN_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_b4223d34/runs/lazypack-mile_b4223d34/plan.json"
)
RESULTS_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1354/K1354_results.json"
)
ARTICLE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_b4223d34/runs/lazypack-mile_b4223d34/panels/"
    "mile_b4223d34_article.md"
)
out_dir = (
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_b4223d34/runs/lazypack-mile_b4223d34/panels"
)

EXPECTED_SOURCE_LABEL = (
    "experiment K1354 results (event study of SPY monthly option-expiration "
    "days on Parkinson high-low range variance, testing the practitioner "
    "gamma-cliff story of pre-expiration compression and post-expiration "
    "release against a pre-registered |t|>3.0 / Bonferroni 0.0125 / bootstrap "
    "gate)"
)
EXPECTED_PANELS = ("panel_question", "panel_results", "panel_takeaway")

WIDTH_PX = 1600
HEIGHT_PX = 1000
DPI = 150

INK = "#18212F"
MUTED = "#536174"
FAINT = "#7A8798"
PAPER = "#F5F7FA"
WHITE = "#FFFFFF"
LINE = "#DCE2EA"
HEADER = "#14253B"

THEMES = {
    "panel_question": {"accent": "#2D69A8", "soft": "#EAF2FA"},
    "panel_results": {"accent": "#A94B3F", "soft": "#F8ECE9"},
    "panel_takeaway": {"accent": "#28796D", "soft": "#E8F4F1"},
}

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_evidence() -> tuple[dict[str, Any], dict[str, Any], str]:
    plan = load_json(PLAN_PATH)
    results = load_json(RESULTS_PATH)
    article = ARTICLE_PATH.read_text(encoding="utf-8")
    if not isinstance(plan, dict):
        raise TypeError("plan.json root must be an object")
    if not isinstance(results, dict):
        raise TypeError("K1354_results.json root must be an object")
    if not article.strip():
        raise ValueError("mile_b4223d34_article.md is empty")
    return plan, results, article


def require(mapping: dict[str, Any], key: str, context: str) -> Any:
    if key not in mapping:
        raise KeyError(f"Missing {context}.{key}")
    return mapping[key]


def resolve_json_pointer(document: Any, pointer: str) -> Any:
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
            raise KeyError(f"Missing evidence field at {pointer!r}")
    return current


def format_metric(value: Any, fmt: dict[str, Any], pointer: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"Expected a number at {pointer!r}, got {type(value).__name__}")
    if not math.isfinite(float(value)):
        raise ValueError(f"Non-finite number at {pointer!r}")
    if require(fmt, "kind", f"format for {pointer}") != "number":
        raise ValueError(f"Unsupported format kind at {pointer!r}")
    digits = require(fmt, "digits", f"format for {pointer}")
    if isinstance(digits, bool) or not isinstance(digits, int) or digits < 0:
        raise TypeError(f"digits must be a non-negative integer at {pointer!r}")
    return f"{float(value):,.{digits}f}"


def wrapped(text: str, width: int) -> str:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Panel text must be a non-empty string")
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
    ax: Any,
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    facecolor: str,
    edgecolor: str = "none",
    linewidth: float = 0.0,
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


def panel_map(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    panels = require(plan, "panels", "plan")
    if not isinstance(panels, list):
        raise TypeError("plan.panels must be an array")
    mapped: dict[str, dict[str, Any]] = {}
    for panel in panels:
        if not isinstance(panel, dict):
            raise TypeError("Every plan panel must be an object")
        name = require(panel, "name", "panel")
        if not isinstance(name, str):
            raise TypeError("panel.name must be a string")
        if name in mapped:
            raise ValueError(f"Duplicate panel name: {name}")
        mapped[name] = panel
    missing = [name for name in EXPECTED_PANELS if name not in mapped]
    if missing:
        raise KeyError(f"Missing required panels: {', '.join(missing)}")
    return mapped


def source_label(plan: dict[str, Any], panel: dict[str, Any]) -> str:
    evidence = require(plan, "evidence", "plan")
    if not isinstance(evidence, dict):
        raise TypeError("plan.evidence must be an object")
    sources = require(panel, "sources", f"panel {panel.get('name', '?')}")
    if sources != ["results"]:
        raise ValueError(f"Panel sources must be exactly ['results'], got {sources!r}")
    results_meta = require(evidence, "results", "plan.evidence")
    if not isinstance(results_meta, dict):
        raise TypeError("plan.evidence.results must be an object")
    label = require(results_meta, "label", "plan.evidence.results")
    if label != EXPECTED_SOURCE_LABEL:
        raise ValueError("Strict reader-facing source label does not match the evidence package")
    return label


def split_blocks(panel: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    blocks = require(panel, "blocks", f"panel {panel.get('name', '?')}")
    if not isinstance(blocks, list):
        raise TypeError("panel.blocks must be an array")
    text_blocks = [block for block in blocks if isinstance(block, dict) and block.get("kind") == "text"]
    metrics = [block for block in blocks if isinstance(block, dict) and block.get("kind") == "metric"]
    if len(text_blocks) != 1 or len(metrics) != 3 or len(blocks) != 4:
        raise ValueError("Each panel must contain exactly one text block and three metric blocks")
    return text_blocks[0], metrics


def draw_header(ax: Any, title: str, accent: str) -> None:
    ax.add_patch(Rectangle((0, 0.79), 1, 0.21, transform=ax.transAxes, color=HEADER))
    ax.add_patch(Rectangle((0.055, 0.824), 0.055, 0.006, transform=ax.transAxes, color=accent))
    ax.text(
        0.055,
        0.958,
        "市場研究懶人包",
        transform=ax.transAxes,
        color="#B8C8DA",
        fontsize=11,
        fontweight="medium",
        va="top",
    )
    ax.text(
        0.055,
        0.902,
        wrapped(title, 30),
        transform=ax.transAxes,
        color=WHITE,
        fontsize=26,
        fontweight="bold",
        linespacing=1.08,
        va="top",
    )


def draw_text_block(ax: Any, block: dict[str, Any], accent: str, soft: str) -> None:
    add_round_rect(ax, 0.055, 0.515, 0.89, 0.235, facecolor=WHITE, edgecolor=LINE, linewidth=1.0)
    ax.add_patch(Rectangle((0.055, 0.515), 0.009, 0.235, transform=ax.transAxes, color=accent))
    heading = require(block, "heading", "text block")
    body = require(block, "body", "text block")
    if not isinstance(body, list) or len(body) != 2 or not all(isinstance(item, str) for item in body):
        raise TypeError("text block body must contain exactly two strings")
    ax.text(
        0.088,
        0.710,
        heading,
        transform=ax.transAxes,
        color=INK,
        fontsize=17,
        fontweight="bold",
        va="top",
    )

    y = 0.655
    for sentence in body:
        lines = wrapped(sentence, 49)
        line_count = lines.count("\n") + 1
        ax.add_patch(
            FancyBboxPatch(
                (0.089, y - 0.014),
                0.012,
                0.012,
                boxstyle="round,pad=0.001,rounding_size=0.004",
                transform=ax.transAxes,
                facecolor=soft,
                edgecolor=accent,
                linewidth=1.2,
            )
        )
        ax.text(
            0.116,
            y,
            lines,
            transform=ax.transAxes,
            color=MUTED,
            fontsize=12.8,
            linespacing=1.35,
            va="top",
        )
        y -= line_count * 0.038 + 0.012


def draw_metric_card(
    ax: Any,
    block: dict[str, Any],
    results: dict[str, Any],
    x: float,
    accent: str,
    soft: str,
) -> None:
    add_round_rect(ax, x, 0.185, 0.28, 0.27, facecolor=WHITE, edgecolor=LINE, linewidth=1.0)
    ax.add_patch(Rectangle((x, 0.185), 0.28, 0.008, transform=ax.transAxes, color=accent))

    label = require(block, "label", "metric block")
    value_spec = require(block, "value", f"metric {label}")
    if not isinstance(value_spec, dict):
        raise TypeError(f"Metric value spec must be an object: {label}")
    if require(value_spec, "source", f"metric {label}") != "results":
        raise ValueError(f"Metric source must be results: {label}")
    pointer = require(value_spec, "path", f"metric {label}")
    fmt = require(value_spec, "format", f"metric {label}")
    if not isinstance(fmt, dict):
        raise TypeError(f"Metric format must be an object: {label}")
    rendered_value = format_metric(resolve_json_pointer(results, pointer), fmt, pointer)

    ax.text(
        x + 0.024,
        0.420,
        wrapped(label, 14),
        transform=ax.transAxes,
        color=MUTED,
        fontsize=11.5,
        fontweight="medium",
        linespacing=1.18,
        va="top",
    )
    ax.text(
        x + 0.024,
        0.340,
        rendered_value,
        transform=ax.transAxes,
        color=accent,
        fontsize=31,
        fontweight="bold",
        va="top",
    )

    note = block.get("note")
    if note is not None:
        if not isinstance(note, str) or not note.strip():
            raise TypeError(f"Metric note must be a non-empty string: {label}")
        ax.add_patch(
            FancyBboxPatch(
                (x + 0.021, 0.218),
                0.238,
                0.052,
                boxstyle="round,pad=0.006,rounding_size=0.010",
                transform=ax.transAxes,
                facecolor=soft,
                edgecolor="none",
            )
        )
        ax.text(
            x + 0.031,
            0.256,
            wrapped(note, 18),
            transform=ax.transAxes,
            color=INK,
            fontsize=9.2,
            linespacing=1.18,
            va="top",
        )


def draw_footer(ax: Any, label: str) -> None:
    ax.plot([0.055, 0.945], [0.145, 0.145], transform=ax.transAxes, color=LINE, linewidth=1.0)
    ax.text(
        0.055,
        0.125,
        "資料來源",
        transform=ax.transAxes,
        color=INK,
        fontsize=9.5,
        fontweight="bold",
        va="top",
    )
    ax.text(
        0.055,
        0.094,
        wrapped(label, 174),
        transform=ax.transAxes,
        color=FAINT,
        fontsize=7.4,
        linespacing=1.22,
        va="top",
    )


def render_panel(panel: dict[str, Any], results: dict[str, Any], label: str) -> None:
    name = require(panel, "name", "panel")
    title = require(panel, "title", f"panel {name}")
    if require(panel, "style", f"panel {name}") != "professional":
        raise ValueError(f"Panel {name} must use professional style")
    require(panel, "alt", f"panel {name}")
    text_block, metric_blocks = split_blocks(panel)
    theme = THEMES[name]

    fig = plt.figure(
        figsize=(WIDTH_PX / DPI, HEIGHT_PX / DPI),
        dpi=DPI,
        facecolor=PAPER,
    )
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    draw_header(ax, title, theme["accent"])
    draw_text_block(ax, text_block, theme["accent"], theme["soft"])
    for x, metric in zip((0.055, 0.360, 0.665), metric_blocks, strict=True):
        draw_metric_card(ax, metric, results, x, theme["accent"], theme["soft"])
    draw_footer(ax, label)

    output_path = Path(out_dir) / f"{name}.png"
    fig.savefig(output_path, dpi=DPI, facecolor=PAPER, edgecolor="none")
    plt.close(fig)


def main() -> None:
    plan, results, _article = load_evidence()
    panels = panel_map(plan)
    os.makedirs(out_dir, exist_ok=True)
    for name in EXPECTED_PANELS:
        panel = panels[name]
        render_panel(panel, results, source_label(plan, panel))


if __name__ == "__main__":
    main()
