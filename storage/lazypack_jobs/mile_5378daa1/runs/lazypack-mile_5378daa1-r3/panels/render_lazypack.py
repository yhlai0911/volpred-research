#!/usr/bin/env python3
"""Render the four data-bound PNG panels for mile_5378daa1 lazypack r3."""

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
    "/Users/yhlai0911/volpred-research/experiments/k1450/k1450_results.json"
)
README_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1450/README.md"
)
PLAN_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_5378daa1/runs/lazypack-mile_5378daa1-r3/plan.json"
)
ARTICLE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_5378daa1/runs/lazypack-mile_5378daa1-r3/panels/"
    "mile_5378daa1_article.md"
)
out_dir = (
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_5378daa1/runs/lazypack-mile_5378daa1-r3/panels"
)

EXPECTED_PANEL_NAMES = (
    "panel_question",
    "panel_result",
    "panel_not_stock",
    "panel_limit",
)
EXPECTED_SOURCE_LABEL = (
    "experiment K1450 results (VNQ forward volatility and stock or bond affinity "
    "under lagged rate regimes)"
)

WIDTH_PX = 1600
HEIGHT_PX = 1000
DPI = 150

NAVY = "#142A43"
NAVY_2 = "#203B59"
INK = "#152334"
MUTED = "#526273"
PALE = "#F3F6F9"
BORDER = "#D9E2EA"
WHITE = "#FFFFFF"
TEAL = "#17807C"
TEAL_SOFT = "#DDEFEA"
BLUE = "#3A6D9A"
BLUE_SOFT = "#E4EDF5"
AMBER = "#B87924"
AMBER_SOFT = "#F6EAD7"
RED = "#B55252"
RED_SOFT = "#F5E2E0"

PANEL_ACCENTS = {
    "panel_question": (BLUE, BLUE_SOFT),
    "panel_result": (TEAL, TEAL_SOFT),
    "panel_not_stock": (BLUE, BLUE_SOFT),
    "panel_limit": (AMBER, AMBER_SOFT),
}

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


def resolve_pointer(document: Any, pointer: str) -> Any:
    """Resolve a strict RFC 6901-style JSON pointer and raise on every mismatch."""
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValueError(f"Expected absolute JSON pointer, got: {pointer!r}")
    current = document
    for raw_part in pointer.split("/")[1:]:
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            if part not in current:
                raise KeyError(f"Missing evidence field: {pointer}")
            current = current[part]
        elif isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError) as exc:
                raise KeyError(f"Invalid evidence list field: {pointer}") from exc
        else:
            raise KeyError(f"Evidence path enters a scalar: {pointer}")
    return current


def require_number(value: Any, pointer: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"Expected a number at {pointer}, got {type(value).__name__}")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"Non-finite number at {pointer}: {number}")
    return number


def format_metric(value: Any, fmt: dict[str, Any], pointer: str) -> str:
    kind = fmt["kind"]
    number = require_number(value, pointer)
    digits = fmt.get("digits")

    if kind == "integer":
        if not number.is_integer():
            raise ValueError(f"Expected integer-compatible value at {pointer}: {value}")
        return f"{int(number):,}"
    if kind == "number":
        if not isinstance(digits, int) or digits < 0:
            raise ValueError(f"Invalid digits for {pointer}: {digits!r}")
        prefix = "+" if fmt.get("show_plus", False) and number >= 0 else ""
        return f"{prefix}{number:.{digits}f}"
    if kind == "percent":
        if not isinstance(digits, int) or digits < 0:
            raise ValueError(f"Invalid digits for {pointer}: {digits!r}")
        return f"{number * 100:.{digits}f}%"
    raise ValueError(f"Unsupported metric format at {pointer}: {kind!r}")


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


def rounded_box(
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
            boxstyle=f"round,pad=0,rounding_size={radius}",
            transform=ax.transAxes,
            facecolor=facecolor,
            edgecolor=edgecolor,
            linewidth=linewidth,
        )
    )


def draw_header(ax: plt.Axes, title: str, accent: str) -> None:
    ax.add_patch(
        Rectangle(
            (0, 0.80), 1, 0.20, transform=ax.transAxes, facecolor=NAVY, edgecolor="none"
        )
    )
    ax.add_patch(
        Rectangle(
            (0.055, 0.84), 0.008, 0.10,
            transform=ax.transAxes,
            facecolor=accent,
            edgecolor="none",
        )
    )
    ax.text(
        0.082,
        0.90,
        wrap_zh(title, 30),
        transform=ax.transAxes,
        ha="left",
        va="center",
        color=WHITE,
        fontsize=25,
        fontweight="bold",
        linespacing=1.20,
    )


def draw_narrative(ax: plt.Axes, block: dict[str, Any], accent: str) -> None:
    if block["kind"] != "text":
        raise ValueError("The first block of every panel must be text")
    body = block["body"]
    if not isinstance(body, list) or len(body) != 2 or not all(isinstance(x, str) for x in body):
        raise ValueError("Each panel must contain exactly two narrative paragraphs")

    rounded_box(ax, 0.055, 0.43, 0.89, 0.30, facecolor=PALE)
    ax.add_patch(
        Circle((0.083, 0.676), 0.011, transform=ax.transAxes, facecolor=accent, edgecolor="none")
    )
    ax.text(
        0.105,
        0.676,
        block["heading"],
        transform=ax.transAxes,
        ha="left",
        va="center",
        color=INK,
        fontsize=17,
        fontweight="bold",
    )

    # Heiti TC's CJK glyphs are wider than textwrap's character-count estimate.
    # Keep each rendered line comfortably inside the narrative card rather than
    # relying on the card's canvas edge as the final clipping boundary.
    first = wrap_zh(body[0], 44)
    second = wrap_zh(body[1], 44)
    ax.text(
        0.083,
        0.625,
        first,
        transform=ax.transAxes,
        ha="left",
        va="top",
        color=INK,
        fontsize=13,
        linespacing=1.45,
    )
    ax.text(
        0.083,
        0.515,
        second,
        transform=ax.transAxes,
        ha="left",
        va="top",
        color=MUTED,
        fontsize=13,
        linespacing=1.45,
    )


def draw_metric_card(
    ax: plt.Axes,
    x: float,
    metric: dict[str, Any],
    results: dict[str, Any],
    accent: str,
    accent_soft: str,
) -> None:
    value_spec = metric["value"]
    if metric["kind"] != "metric" or value_spec["source"] != "results":
        raise ValueError("Only results-bound metric blocks are supported")
    pointer = value_spec["path"]
    raw_value = resolve_pointer(results, pointer)
    rendered = format_metric(raw_value, value_spec["format"], pointer)

    card_width = 0.278
    rounded_box(
        ax,
        x,
        0.125,
        card_width,
        0.245,
        facecolor=WHITE,
        edgecolor=BORDER,
        linewidth=1.15,
    )
    rounded_box(ax, x + 0.020, 0.318, 0.039, 0.039, facecolor=accent_soft, radius=0.019)
    ax.add_patch(
        Circle(
            (x + 0.0395, 0.3375),
            0.007,
            transform=ax.transAxes,
            facecolor=accent,
            edgecolor="none",
        )
    )
    ax.text(
        x + 0.020,
        0.292,
        wrap_zh(metric["label"], 13),
        transform=ax.transAxes,
        ha="left",
        va="top",
        color=MUTED,
        fontsize=12.5,
        linespacing=1.15,
    )
    ax.text(
        x + 0.020,
        0.238,
        rendered,
        transform=ax.transAxes,
        ha="left",
        va="top",
        color=INK,
        fontsize=25,
        fontweight="bold",
    )
    if "note" in metric:
        ax.text(
            x + 0.020,
            0.179,
            wrap_zh(metric["note"], 15),
            transform=ax.transAxes,
            ha="left",
            va="top",
            color=accent,
            fontsize=9.5,
            linespacing=1.15,
        )


def draw_source(ax: plt.Axes, label: str) -> None:
    ax.plot([0.055, 0.945], [0.105, 0.105], transform=ax.transAxes, color=BORDER, linewidth=0.8)
    ax.text(
        0.055,
        0.068,
        f"資料來源：{label}",
        transform=ax.transAxes,
        ha="left",
        va="center",
        color=MUTED,
        fontsize=8.8,
    )


def render_panel(panel: dict[str, Any], results: dict[str, Any], source_label: str) -> None:
    name = panel["name"]
    if name not in PANEL_ACCENTS:
        raise ValueError(f"Unexpected panel name: {name}")
    if panel.get("style") != "professional":
        raise ValueError(f"Panel {name} must use professional style")
    blocks = panel["blocks"]
    if len(blocks) != 4:
        raise ValueError(f"Panel {name} must contain one text block and three metrics")

    accent, accent_soft = PANEL_ACCENTS[name]
    fig = plt.figure(figsize=(WIDTH_PX / DPI, HEIGHT_PX / DPI), dpi=DPI, facecolor=WHITE)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    draw_header(ax, panel["title"], accent)
    draw_narrative(ax, blocks[0], accent)
    for x, metric in zip((0.055, 0.361, 0.667), blocks[1:]):
        draw_metric_card(ax, x, metric, results, accent, accent_soft)
    draw_source(ax, source_label)

    destination = Path(out_dir) / f"{name}.png"
    fig.savefig(
        destination,
        dpi=DPI,
        facecolor=WHITE,
        edgecolor="none",
        metadata={
            "Title": panel["title"],
            "Description": panel["alt"],
            "Source": source_label,
        },
    )
    plt.close(fig)


def main() -> None:
    results = load_json(RESULTS_PATH)
    plan = load_json(PLAN_PATH)
    # These two evidence documents are required inputs to this package. Reading and
    # checking them here makes a missing or empty package component fail loudly.
    load_text(README_PATH)
    load_text(ARTICLE_PATH)

    evidence = plan["evidence"]
    source_label = evidence["results"]["label"]
    if source_label != EXPECTED_SOURCE_LABEL:
        raise ValueError("Strict-plan results source label changed unexpectedly")

    panels = plan["panels"]
    names = tuple(panel["name"] for panel in panels)
    if names != EXPECTED_PANEL_NAMES:
        raise ValueError(f"Unexpected panel order or names: {names}")

    os.makedirs(out_dir, exist_ok=True)
    for panel in panels:
        render_panel(panel, results, source_label)


if __name__ == "__main__":
    main()
