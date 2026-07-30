#!/usr/bin/env python3
"""Render the three data-bound PNG panels for the mile_08d47597 article."""

from __future__ import annotations

import hashlib
import json
import os
import textwrap
from datetime import date
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyBboxPatch, Rectangle


RESULTS_LOWER_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1649/k1649_results.json"
)
README_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1649/README.md"
)
PLAN_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_08d47597/runs/lazypack-mile_08d47597/plan.json"
)
RESULTS_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1649/K1649_results.json"
)
ARTICLE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_08d47597/runs/lazypack-mile_08d47597/panels/"
    "mile_08d47597_article.md"
)
out_dir = (
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_08d47597/runs/lazypack-mile_08d47597/panels"
)

WIDTH_PX = 1600
HEIGHT_PX = 1000
DPI = 150

NAVY = "#102A43"
NAVY_2 = "#163B5C"
BLUE = "#247BA0"
TEAL = "#168C86"
AMBER = "#D9911B"
RED = "#C94C4C"
INK = "#18212B"
MUTED = "#52616F"
PALE = "#F4F7FA"
LINE = "#D9E2EC"
WHITE = "#FFFFFF"

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def require_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError(f"Evidence file is empty: {path}")
    return text


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_pointer(document: Any, pointer: str) -> Any:
    """Resolve a strict RFC 6901-style JSON Pointer, raising on any miss."""
    if not pointer.startswith("/"):
        raise ValueError(f"JSON Pointer must begin with '/': {pointer}")
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


def require_number(value: Any, pointer: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"Expected a number at {pointer}, got {type(value).__name__}")
    return float(value)


def format_value(value: Any, fmt: dict[str, Any], pointer: str) -> str:
    kind = fmt["kind"]
    if kind == "date":
        if not isinstance(value, str):
            raise TypeError(f"Expected an ISO date string at {pointer}")
        parsed = date.fromisoformat(value)
        return f"{parsed.year} 年 {parsed.month} 月 {parsed.day} 日"
    if kind == "integer":
        number = require_number(value, pointer)
        if not number.is_integer():
            raise ValueError(f"Expected an integer-valued number at {pointer}")
        return f"{int(number):,}"
    if kind == "number":
        number = require_number(value, pointer)
        if fmt.get("absolute", False):
            number = abs(number)
        number *= require_number(fmt.get("scale", 1), f"{pointer} format scale")
        digits = fmt["digits"]
        if isinstance(digits, bool) or not isinstance(digits, int):
            raise TypeError(f"Invalid digits format for {pointer}")
        return f"{number:.{digits}f}"
    raise ValueError(f"Unsupported value format '{kind}' at {pointer}")


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


def add_header(fig: plt.Figure, title: str) -> None:
    fig.patches.append(
        Rectangle(
            (0, 0.81),
            1,
            0.19,
            transform=fig.transFigure,
            facecolor=NAVY,
            edgecolor="none",
            zorder=-1,
        )
    )
    fig.text(
        0.07,
        0.905,
        title,
        color=WHITE,
        fontsize=30,
        fontweight="bold",
        ha="left",
        va="center",
    )
    fig.patches.append(
        Rectangle(
            (0.07, 0.842),
            0.075,
            0.009,
            transform=fig.transFigure,
            facecolor=TEAL,
            edgecolor="none",
        )
    )


def add_explainer(fig: plt.Figure, block: dict[str, Any]) -> None:
    body = block["body"]
    if not isinstance(body, list) or len(body) != 2:
        raise ValueError("Each panel text block must contain exactly two body paragraphs")
    fig.text(
        0.07,
        0.755,
        block["heading"],
        color=INK,
        fontsize=21,
        fontweight="bold",
        ha="left",
        va="top",
    )
    fig.text(
        0.07,
        0.695,
        wrapped(body[0], 48),
        color=MUTED,
        fontsize=15.5,
        ha="left",
        va="top",
        linespacing=1.42,
    )
    fig.text(
        0.07,
        0.625,
        wrapped(body[1], 48),
        color=MUTED,
        fontsize=15.5,
        ha="left",
        va="top",
        linespacing=1.42,
    )


def add_card(
    fig: plt.Figure,
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    label: str,
    value: str,
    accent: str,
    note: str | None = None,
) -> None:
    # The three-column cards are only about 434 px wide after rendering.
    # CJK glyphs at 13.5 pt are substantially wider than textwrap's
    # character-count model assumes, so keep each rendered line comfortably
    # inside the card's horizontal padding.
    label_wrap_width = 11 if width < 0.3 else 20
    note_wrap_width = 14 if width < 0.3 else 23

    fig.patches.append(
        FancyBboxPatch(
            (x, y),
            width,
            height,
            boxstyle="round,pad=0.008,rounding_size=0.015",
            transform=fig.transFigure,
            facecolor=WHITE,
            edgecolor=LINE,
            linewidth=1.4,
            zorder=-1,
        )
    )
    fig.patches.append(
        Rectangle(
            (x, y + height - 0.012),
            width,
            0.012,
            transform=fig.transFigure,
            facecolor=accent,
            edgecolor="none",
        )
    )
    fig.text(
        x + 0.025,
        y + height - 0.062,
        wrapped(label, label_wrap_width),
        color=MUTED,
        fontsize=13.5,
        ha="left",
        va="top",
        linespacing=1.28,
    )
    fig.text(
        x + 0.025,
        y + (0.085 if note else 0.055),
        value,
        color=accent,
        fontsize=31 if len(value) < 12 else 25,
        fontweight="bold",
        ha="left",
        va="bottom",
    )
    if note:
        fig.text(
            x + 0.025,
            y + 0.026,
            wrapped(note, note_wrap_width),
            color=MUTED,
            fontsize=10.5,
            ha="left",
            va="bottom",
            linespacing=1.2,
        )


def add_footer(fig: plt.Figure, source_label: str) -> None:
    fig.lines.append(
        plt.Line2D(
            [0.07, 0.93],
            [0.085, 0.085],
            transform=fig.transFigure,
            color=LINE,
            linewidth=1.0,
        )
    )
    fig.text(
        0.07,
        0.05,
        f"資料來源：{source_label}",
        color=MUTED,
        fontsize=11,
        ha="left",
        va="center",
    )
    fig.text(
        0.93,
        0.05,
        "VolPred",
        color=NAVY,
        fontsize=12,
        fontweight="bold",
        ha="right",
        va="center",
    )


def metric_blocks(panel: dict[str, Any]) -> list[dict[str, Any]]:
    blocks = panel["blocks"]
    text_blocks = [block for block in blocks if block["kind"] == "text"]
    metrics = [block for block in blocks if block["kind"] == "metric"]
    if len(text_blocks) != 1:
        raise ValueError(f"Panel {panel['name']} must have exactly one text block")
    expected_metrics = 2 if panel["name"] == "panel_question" else 3
    if len(metrics) != expected_metrics:
        raise ValueError(
            f"Panel {panel['name']} must have exactly {expected_metrics} metrics"
        )
    return metrics


def bound_metric(metric: dict[str, Any], results: dict[str, Any]) -> str:
    value_spec = metric["value"]
    if value_spec["source"] != "results":
        raise ValueError(f"Unsupported evidence source: {value_spec['source']}")
    pointer = value_spec["path"]
    raw_value = resolve_pointer(results, pointer)
    return format_value(raw_value, value_spec["format"], pointer)


def render_panel(
    panel: dict[str, Any],
    results: dict[str, Any],
    source_label: str,
) -> None:
    fig = plt.figure(
        figsize=(WIDTH_PX / DPI, HEIGHT_PX / DPI),
        dpi=DPI,
        facecolor=WHITE,
    )
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    add_header(fig, panel["title"])
    text_block = next(block for block in panel["blocks"] if block["kind"] == "text")
    add_explainer(fig, text_block)
    metrics = metric_blocks(panel)

    if panel["name"] == "panel_question":
        positions = [
            (0.07, 0.19, 0.405, 0.29, TEAL),
            (0.525, 0.19, 0.405, 0.29, BLUE),
        ]
    else:
        positions = [
            (0.07, 0.19, 0.255, 0.29, TEAL),
            (0.3725, 0.19, 0.255, 0.29, BLUE),
            (0.675, 0.19, 0.255, 0.29, AMBER),
        ]
        if panel["name"] == "panel_takeaway":
            positions[0] = (*positions[0][0:4], RED)

    for metric, (x, y, width, height, accent) in zip(metrics, positions, strict=True):
        add_card(
            fig,
            x=x,
            y=y,
            width=width,
            height=height,
            label=metric["label"],
            value=bound_metric(metric, results),
            accent=accent,
            note=metric.get("note"),
        )

    add_footer(fig, source_label)
    output_path = Path(out_dir) / f"{panel['name']}.png"
    fig.savefig(
        output_path,
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
    os.makedirs(out_dir, exist_ok=True)

    results = load_json(RESULTS_PATH)
    results_lower = load_json(RESULTS_LOWER_PATH)
    plan = load_json(PLAN_PATH)
    require_text(README_PATH)
    require_text(ARTICLE_PATH)

    if results != results_lower:
        raise ValueError("The two supplied results JSON files do not agree")

    evidence = plan["evidence"]["results"]
    if sha256(RESULTS_PATH) != evidence["sha256"]:
        raise ValueError("Results SHA-256 does not match the strict plan")
    source_label = evidence["label"]
    if not isinstance(source_label, str) or not source_label.strip():
        raise ValueError("Strict plan is missing the reader-facing source label")

    panels = plan["panels"]
    expected_names = ["panel_question", "panel_scorecard", "panel_takeaway"]
    actual_names = [panel["name"] for panel in panels]
    if actual_names != expected_names:
        raise ValueError(
            f"Unexpected panel sequence: expected {expected_names}, got {actual_names}"
        )

    for panel in panels:
        if panel["sources"] != ["results"]:
            raise ValueError(f"Unexpected sources for panel {panel['name']}")
        render_panel(panel, results, source_label)


if __name__ == "__main__":
    main()
