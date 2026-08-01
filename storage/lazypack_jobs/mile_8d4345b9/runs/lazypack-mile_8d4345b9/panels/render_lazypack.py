#!/usr/bin/env python3
"""Render the three data-bound PNG panels for mile_8d4345b9."""

from __future__ import annotations

import json
import os
import textwrap
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Circle, FancyArrowPatch


PLAN_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_8d4345b9/runs/lazypack-mile_8d4345b9/plan.json"
)
RESULTS_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1331/K1331_results.json"
)
ARTICLE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_8d4345b9/runs/lazypack-mile_8d4345b9/panels/"
    "mile_8d4345b9_article.md"
)
OUT_DIR = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_8d4345b9/runs/lazypack-mile_8d4345b9/panels"
)

WIDTH_PX = 1600
HEIGHT_PX = 1000
DPI = 150

NAVY = "#102A43"
BLUE = "#176B87"
TEAL = "#148A8A"
GREEN = "#27805B"
AMBER = "#C47D16"
RED = "#B8463F"
INK = "#172B3A"
MUTED = "#5D6C78"
LINE = "#D8E1E8"
PALE_BLUE = "#EAF3F7"
PALE_TEAL = "#E8F4F2"
PALE_AMBER = "#FBF1DE"
PALE_RED = "#F9EBE9"
WHITE = "#FFFFFF"

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def resolve_pointer(document: Any, pointer: str) -> Any:
    """Resolve a strict RFC-6901-style JSON pointer; missing fields must raise."""
    if not pointer.startswith("/"):
        raise ValueError(f"JSON pointer must begin with '/': {pointer}")
    current = document
    for raw_part in pointer[1:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            current = current[part]
        elif isinstance(current, list):
            current = current[int(part)]
        else:
            raise KeyError(pointer)
    return current


def format_value(raw: Any, spec: dict[str, Any]) -> str:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise TypeError(f"Expected numeric evidence value, got {type(raw).__name__}")
    value = float(raw)
    if spec.get("absolute", False):
        value = abs(value)
    digits = int(spec["digits"])
    kind = spec["kind"]
    if kind == "number":
        rendered = f"{value:.{digits}f}"
    elif kind == "percent":
        rendered = f"{value * 100:.{digits}f}%"
    else:
        raise ValueError(f"Unsupported number format: {kind}")
    return rendered + str(spec.get("suffix", ""))


def bound_value(value_spec: dict[str, Any], results: dict[str, Any]) -> str:
    if value_spec["source"] != "results":
        raise KeyError(f"Unsupported evidence source: {value_spec['source']}")
    raw = resolve_pointer(results, value_spec["path"])
    return format_value(raw, value_spec["format"])


def materialize_body(item: Any, results: dict[str, Any]) -> str:
    if isinstance(item, str):
        return item
    template = item["template"]
    replacements = {
        name: bound_value(binding, results)
        for name, binding in item["bindings"].items()
    }
    return template.format(**replacements)


def new_figure() -> tuple[plt.Figure, plt.Axes]:
    fig = plt.figure(
        figsize=(WIDTH_PX / DPI, HEIGHT_PX / DPI), dpi=DPI, facecolor=WHITE
    )
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    return fig, ax


def rounded_box(
    ax: plt.Axes,
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    face: str = WHITE,
    edge: str = LINE,
    radius: float = 0.018,
    linewidth: float = 1.2,
) -> None:
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle=f"round,pad=0.008,rounding_size={radius}",
            facecolor=face,
            edgecolor=edge,
            linewidth=linewidth,
        )
    )


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


def draw_header(ax: plt.Axes, panel: dict[str, Any], accent: str) -> None:
    ax.add_patch(plt.Rectangle((0, 0.835), 1, 0.165, color=NAVY))
    ax.add_patch(plt.Rectangle((0.055, 0.862), 0.008, 0.088, color=accent))
    ax.text(
        0.078,
        0.925,
        panel["title"],
        ha="left",
        va="center",
        fontsize=25,
        fontweight="bold",
        color=WHITE,
    )
    ax.text(
        0.079,
        0.872,
        panel["subtitle"],
        ha="left",
        va="center",
        fontsize=12.5,
        color="#D8E7F0",
    )


def draw_footer(ax: plt.Axes, source_label: str) -> None:
    ax.plot([0.055, 0.945], [0.092, 0.092], color=LINE, linewidth=1)
    ax.text(
        0.055,
        0.067,
        wrapped(f"資料來源：{source_label}", 82),
        ha="left",
        va="center",
        fontsize=7.4,
        color=MUTED,
        linespacing=1.25,
    )


def draw_text_block(
    ax: plt.Axes,
    block: dict[str, Any],
    results: dict[str, Any],
    *,
    x: float,
    y: float,
    width_chars: int,
    heading_color: str = NAVY,
    body_size: float = 10.5,
    line_gap: float = 0.059,
) -> None:
    ax.text(
        x,
        y,
        block["heading"],
        ha="left",
        va="top",
        fontsize=14,
        fontweight="bold",
        color=heading_color,
    )
    cursor = y - 0.045
    for body in block["body"]:
        rendered = wrapped(materialize_body(body, results), width_chars)
        ax.text(
            x,
            cursor,
            "• " + rendered.replace("\n", "\n  "),
            ha="left",
            va="top",
            fontsize=body_size,
            color=INK,
            linespacing=1.42,
        )
        cursor -= line_gap * max(1, rendered.count("\n") + 1)


def draw_metric_card(
    ax: plt.Axes,
    block: dict[str, Any],
    results: dict[str, Any],
    *,
    x: float,
    y: float,
    w: float,
    h: float,
    accent: str,
    face: str,
    label_width: int,
    value_size: float = 23,
) -> None:
    rounded_box(ax, x, y, w, h, face=face, edge=LINE)
    ax.add_patch(plt.Rectangle((x, y), 0.006, h, color=accent))
    ax.text(
        x + 0.025,
        y + h - 0.035,
        wrapped(block["label"], label_width),
        ha="left",
        va="top",
        fontsize=9.2,
        color=MUTED,
        linespacing=1.28,
    )
    ax.text(
        x + 0.025,
        y + 0.070,
        bound_value(block["value"], results),
        ha="left",
        va="center",
        fontsize=value_size,
        fontweight="bold",
        color=accent,
    )
    if "note" in block:
        ax.text(
            x + w - 0.020,
            y + 0.026,
            wrapped(block["note"], label_width),
            ha="right",
            va="bottom",
            fontsize=7.8,
            color=MUTED,
            linespacing=1.15,
        )


def draw_horizontal_metric_card(
    ax: plt.Axes,
    block: dict[str, Any],
    results: dict[str, Any],
    *,
    x: float,
    y: float,
    w: float,
    h: float,
    accent: str,
    face: str,
    label_width: int,
    label_size: float = 8.3,
    value_size: float = 20,
) -> None:
    """Draw a compact metric with separate label and value columns.

    The results panel has long explanatory labels.  Giving the value its own
    right-aligned column prevents wrapped labels from colliding with it.
    """
    rounded_box(ax, x, y, w, h, face=face, edge=LINE)
    ax.add_patch(plt.Rectangle((x, y), 0.006, h, color=accent))
    ax.text(
        x + 0.022,
        y + h / 2 + (0.010 if "note" in block else 0),
        wrapped(block["label"], label_width),
        ha="left",
        va="center",
        fontsize=label_size,
        color=MUTED,
        linespacing=1.22,
    )
    ax.text(
        x + w - 0.020,
        y + h / 2,
        bound_value(block["value"], results),
        ha="right",
        va="center",
        fontsize=value_size,
        fontweight="bold",
        color=accent,
    )
    if "note" in block:
        ax.text(
            x + 0.022,
            y + 0.017,
            block["note"],
            ha="left",
            va="bottom",
            fontsize=7.2,
            color=accent,
        )


def render_concept(
    panel: dict[str, Any], results: dict[str, Any], source_label: str
) -> None:
    fig, ax = new_figure()
    draw_header(ax, panel, TEAL)
    text_block = panel["blocks"][0]
    metrics = panel["blocks"][1:]

    rounded_box(ax, 0.055, 0.638, 0.890, 0.158, face=PALE_TEAL, edge="#C7E1DD")
    draw_text_block(
        ax,
        text_block,
        results,
        x=0.085,
        y=0.773,
        width_chars=62,
        body_size=10.2,
        line_gap=0.047,
    )
    # A restrained portfolio icon: many paths converge into one index.
    for cy in (0.688, 0.718, 0.748):
        ax.add_patch(Circle((0.785, cy), 0.010, facecolor=TEAL, edgecolor="none"))
        ax.add_patch(
            FancyArrowPatch(
                (0.800, cy),
                (0.865, 0.718),
                arrowstyle="-",
                linewidth=1.5,
                color="#68A9A4",
            )
        )
    ax.add_patch(Circle((0.885, 0.718), 0.025, facecolor=NAVY, edgecolor="none"))

    positions = [
        (0.055, 0.392),
        (0.510, 0.392),
        (0.055, 0.142),
        (0.510, 0.142),
    ]
    for index, (metric, (x, y)) in enumerate(zip(metrics, positions)):
        draw_metric_card(
            ax,
            metric,
            results,
            x=x,
            y=y,
            w=0.435,
            h=0.205,
            accent=TEAL if index in (0, 3) else BLUE,
            face=WHITE if index < 2 else "#F8FAFC",
            label_width=25,
            value_size=25,
        )

    draw_footer(ax, source_label)
    fig.savefig(OUT_DIR / "panel_concept.png", dpi=DPI, facecolor=WHITE)
    plt.close(fig)


def render_results(
    panel: dict[str, Any], results: dict[str, Any], source_label: str
) -> None:
    fig, ax = new_figure()
    draw_header(ax, panel, AMBER)
    first_text, slope, r2, second_text, baseline, dispersion, dm = panel["blocks"]

    rounded_box(ax, 0.055, 0.535, 0.890, 0.260, face=PALE_BLUE, edge="#CDDEE8")
    draw_text_block(
        ax,
        first_text,
        results,
        x=0.083,
        y=0.765,
        width_chars=31,
        body_size=8.9,
        line_gap=0.047,
    )
    # Keep evidence metrics in their own column so prose cannot enter the cards.
    draw_horizontal_metric_card(
        ax,
        slope,
        results,
        x=0.600,
        y=0.665,
        w=0.315,
        h=0.090,
        accent=BLUE,
        face=WHITE,
        label_width=17,
        label_size=8.0,
        value_size=18,
    )
    draw_horizontal_metric_card(
        ax,
        r2,
        results,
        x=0.600,
        y=0.555,
        w=0.315,
        h=0.090,
        accent=TEAL,
        face=WHITE,
        label_width=16,
        label_size=8.0,
        value_size=18,
    )

    rounded_box(ax, 0.055, 0.135, 0.890, 0.365, face=WHITE, edge=LINE)
    draw_text_block(
        ax,
        second_text,
        results,
        x=0.083,
        y=0.470,
        width_chars=66,
        body_size=9.0,
        line_gap=0.042,
        heading_color=RED,
    )
    for metric, x, accent, face in (
        (baseline, 0.083, NAVY, "#F5F7FA"),
        (dispersion, 0.374, BLUE, PALE_BLUE),
        (dm, 0.665, RED, PALE_RED),
    ):
        draw_horizontal_metric_card(
            ax,
            metric,
            results,
            x=x,
            y=0.155,
            w=0.252,
            h=0.145,
            accent=accent,
            face=face,
            label_width=14,
            label_size=7.7,
            value_size=18,
        )

    draw_footer(ax, source_label)
    fig.savefig(OUT_DIR / "panel_results.png", dpi=DPI, facecolor=WHITE)
    plt.close(fig)


def render_takeaway(
    panel: dict[str, Any], results: dict[str, Any], source_label: str
) -> None:
    fig, ax = new_figure()
    draw_header(ax, panel, GREEN)
    opening = panel["blocks"][0]
    metrics = panel["blocks"][1:6]
    closing = panel["blocks"][6]

    rounded_box(ax, 0.055, 0.645, 0.890, 0.150, face=PALE_AMBER, edge="#EBD6B0")
    draw_text_block(
        ax,
        opening,
        results,
        x=0.082,
        y=0.768,
        width_chars=74,
        body_size=9.8,
        line_gap=0.044,
        heading_color=AMBER,
    )

    card_x = [0.055, 0.237, 0.419, 0.601, 0.783]
    accents = [NAVY, GREEN, BLUE, GREEN, RED]
    faces = ["#F6F8FA", PALE_TEAL, PALE_BLUE, PALE_TEAL, PALE_RED]
    for metric, x, accent, face in zip(metrics, card_x, accents, faces):
        draw_metric_card(
            ax,
            metric,
            results,
            x=x,
            y=0.365,
            w=0.162,
            h=0.225,
            accent=accent,
            face=face,
            label_width=12,
            value_size=20,
        )

    rounded_box(ax, 0.055, 0.135, 0.890, 0.175, face=NAVY, edge=NAVY)
    ax.text(
        0.083,
        0.278,
        closing["heading"],
        ha="left",
        va="top",
        fontsize=14,
        fontweight="bold",
        color="#8FD5C5",
    )
    closing_text = "\n".join(
        "• " + wrapped(materialize_body(item, results), 73).replace("\n", "\n  ")
        for item in closing["body"]
    )
    ax.text(
        0.083,
        0.235,
        closing_text,
        ha="left",
        va="top",
        fontsize=9.7,
        color=WHITE,
        linespacing=1.42,
    )

    draw_footer(ax, source_label)
    fig.savefig(OUT_DIR / "panel_takeaway.png", dpi=DPI, facecolor=WHITE)
    plt.close(fig)


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    plan = load_json(PLAN_PATH)
    results = load_json(RESULTS_PATH)
    # The article is part of the evidence package. Read it explicitly and fail
    # loudly if the supplied artifact is missing or empty.
    article = ARTICLE_PATH.read_text(encoding="utf-8")
    if not article.strip():
        raise ValueError(f"Article evidence is empty: {ARTICLE_PATH}")

    evidence = plan["evidence"]
    source_label = evidence["results"]["label"]
    panels = {panel["name"]: panel for panel in plan["panels"]}
    required = {"panel_concept", "panel_results", "panel_takeaway"}
    if set(panels) != required:
        raise ValueError(f"Expected exactly {sorted(required)}, got {sorted(panels)}")

    render_concept(panels["panel_concept"], results, source_label)
    render_results(panels["panel_results"], results, source_label)
    render_takeaway(panels["panel_takeaway"], results, source_label)


if __name__ == "__main__":
    main()
