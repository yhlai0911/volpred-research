#!/usr/bin/env python3
"""Render the three data-bound K1678 general-audience lazypack panels."""

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
from matplotlib.lines import Line2D
from matplotlib.patches import Circle, FancyBboxPatch, Polygon, Rectangle


RESULT_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/K1678/K1678_results.json"
)
RESULT_LOWERCASE_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1678/k1678_results.json"
)
README_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1678/README.md"
)
PLAN_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_5f3f1589/runs/lazypack-mile_5f3f1589/plan.json"
)
ARTICLE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_5f3f1589/runs/lazypack-mile_5f3f1589/panels/"
    "mile_5f3f1589_article.md"
)
out_dir = (
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_5f3f1589/runs/lazypack-mile_5f3f1589/panels"
)

WIDTH_PX = 1600
HEIGHT_PX = 1000
DPI = 150

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False

NAVY = "#13263A"
INK = "#182433"
MUTED = "#667281"
LIGHT_TEXT = "#E9F0F5"
PAPER = "#FFFFFF"
PALE = "#F4F7FA"
GRID = "#D9E1E8"
BLUE = "#2E6F9E"
BLUE_LIGHT = "#DDEBF5"
TEAL = "#23827B"
TEAL_LIGHT = "#DDF1EE"
RED = "#B84A4A"
RED_LIGHT = "#F7E6E4"
AMBER = "#B57422"
AMBER_LIGHT = "#F7ECD9"
GREEN = "#377C60"
GREEN_LIGHT = "#E3F0E8"


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_text(path: Path) -> str:
    with path.open("r", encoding="utf-8") as handle:
        return handle.read()


def resolve_path(data: Any, path: str) -> Any:
    """Resolve either a JSON Pointer or a dot-separated path; missing data raises."""
    if not isinstance(path, str) or not path:
        raise ValueError(f"Invalid evidence path: {path!r}")
    if path.startswith("/"):
        parts = [part.replace("~1", "/").replace("~0", "~") for part in path[1:].split("/")]
    else:
        parts = path.split(".")

    current = data
    for part in parts:
        if isinstance(current, dict):
            if part not in current:
                raise KeyError(f"Missing evidence field {path!r} at {part!r}")
            current = current[part]
        elif isinstance(current, list):
            try:
                index = int(part)
                current = current[index]
            except (ValueError, IndexError) as exc:
                raise KeyError(f"Invalid list index in evidence path {path!r}: {part!r}") from exc
        else:
            raise KeyError(f"Cannot descend into evidence path {path!r} at {part!r}")
    return current


def require_number(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"Evidence field {path!r} must be numeric, got {type(value).__name__}")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"Evidence field {path!r} is not finite")
    return number


def format_value(value: Any, fmt: dict[str, Any], path: str) -> tuple[str, str]:
    """Return the formatted numeric core and plan-provided suffix separately."""
    kind = fmt["kind"]
    suffix = str(fmt.get("suffix", "")).strip()
    number = require_number(value, path)

    if kind == "integer":
        if not number.is_integer():
            raise ValueError(f"Evidence field {path!r} must be integral for integer formatting")
        core = f"{int(number):,}"
    elif kind == "number":
        digits = fmt["digits"]
        if isinstance(digits, bool) or not isinstance(digits, int) or digits < 0:
            raise ValueError(f"Invalid digits setting for {path!r}: {digits!r}")
        sign = "+" if fmt.get("show_plus", False) else ""
        core = f"{number:{sign}.{digits}f}"
    else:
        raise ValueError(f"Unsupported format kind {kind!r} for {path!r}")
    return core, suffix


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


def add_box(
    fig: plt.Figure,
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    facecolor: str,
    edgecolor: str = "none",
    linewidth: float = 1.0,
    radius: float = 0.016,
) -> FancyBboxPatch:
    patch = FancyBboxPatch(
        (x, y),
        width,
        height,
        boxstyle=f"round,pad=0.008,rounding_size={radius}",
        transform=fig.transFigure,
        facecolor=facecolor,
        edgecolor=edgecolor,
        linewidth=linewidth,
        clip_on=False,
    )
    fig.add_artist(patch)
    return patch


def add_line(
    fig: plt.Figure,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    *,
    color: str,
    linewidth: float = 1.5,
) -> None:
    fig.add_artist(
        Line2D(
            [x1, x2],
            [y1, y2],
            transform=fig.transFigure,
            color=color,
            linewidth=linewidth,
            solid_capstyle="round",
            clip_on=False,
        )
    )


def new_figure(header_color: str = NAVY) -> plt.Figure:
    fig = plt.figure(figsize=(WIDTH_PX / DPI, HEIGHT_PX / DPI), dpi=DPI, facecolor=PAPER)
    fig.add_artist(
        Rectangle(
            (0, 0.82),
            1,
            0.18,
            transform=fig.transFigure,
            facecolor=header_color,
            edgecolor="none",
            clip_on=False,
        )
    )
    return fig


def add_header(fig: plt.Figure, title: str, *, accent: str) -> None:
    fig.add_artist(
        Rectangle(
            (0.05, 0.868),
            0.008,
            0.078,
            transform=fig.transFigure,
            facecolor=accent,
            edgecolor="none",
            clip_on=False,
        )
    )
    fig.text(
        0.075,
        0.905,
        title,
        ha="left",
        va="center",
        fontsize=31,
        fontweight="bold",
        color=PAPER,
    )


def add_footer(fig: plt.Figure, source_label: str) -> None:
    add_line(fig, 0.055, 0.077, 0.945, 0.077, color=GRID, linewidth=1.0)
    fig.text(
        0.055,
        0.045,
        f"資料來源：{source_label}",
        ha="left",
        va="center",
        fontsize=12.5,
        color=MUTED,
    )


def metric_blocks(panel: dict[str, Any]) -> list[dict[str, Any]]:
    blocks = [block for block in panel["blocks"] if block["kind"] == "metric"]
    if not blocks:
        raise ValueError(f"Panel {panel.get('name')!r} has no metric blocks")
    return blocks


def text_blocks(panel: dict[str, Any]) -> list[dict[str, Any]]:
    return [block for block in panel["blocks"] if block["kind"] == "text"]


def bind_metric(
    block: dict[str, Any], source_data: dict[str, Any], mirror_data: dict[str, Any]
) -> dict[str, Any]:
    value_spec = block["value"]
    source = value_spec["source"]
    path = value_spec["path"]
    if source not in source_data:
        raise KeyError(f"Unknown evidence source {source!r}")
    value = resolve_path(source_data[source], path)
    mirror_value = resolve_path(mirror_data[source], path)
    if value != mirror_value:
        raise ValueError(
            f"Evidence mismatch between uppercase/lowercase result files at {path!r}: "
            f"{value!r} != {mirror_value!r}"
        )
    core, suffix = format_value(value, value_spec["format"], path)
    return {
        "label": block["label"],
        "path": path,
        "raw": require_number(value, path),
        "core": core,
        "suffix": suffix,
        "note": block.get("note"),
    }


def panel_source_label(panel: dict[str, Any], evidence_plan: dict[str, Any]) -> str:
    labels: list[str] = []
    for source in panel["sources"]:
        label = evidence_plan[source]["label"]
        if not isinstance(label, str) or not label.strip():
            raise ValueError(f"Missing reader-facing label for evidence source {source!r}")
        labels.append(label)
    return "、".join(labels)


def draw_value(
    fig: plt.Figure,
    x: float,
    y: float,
    core: str,
    suffix: str,
    *,
    core_size: float,
    color: str,
    ha: str = "left",
) -> None:
    if suffix:
        fig.text(
            x,
            y + 0.016,
            core,
            ha=ha,
            va="center",
            fontsize=core_size,
            fontweight="bold",
            color=color,
        )
        fig.text(
            x,
            y - 0.040,
            suffix,
            ha=ha,
            va="center",
            fontsize=14,
            color=MUTED,
        )
    else:
        fig.text(
            x,
            y,
            core,
            ha=ha,
            va="center",
            fontsize=core_size,
            fontweight="bold",
            color=color,
        )


def render_data_funnel(
    panel: dict[str, Any],
    source_data: dict[str, Any],
    mirror_data: dict[str, Any],
    evidence_plan: dict[str, Any],
) -> None:
    metrics = [bind_metric(block, source_data, mirror_data) for block in metric_blocks(panel)]
    if len(metrics) != 4:
        raise ValueError("1_data_funnel must contain exactly four metrics")
    copy_blocks = text_blocks(panel)
    if len(copy_blocks) != 1:
        raise ValueError("1_data_funnel must contain exactly one text block")

    fig = new_figure()
    add_header(fig, panel["title"], accent=TEAL)

    # Keep every stage on one row and give every card the same three-row
    # structure: stage badge, label, then value.  The previous two short cards
    # put their labels and values on effectively the same baseline.
    cards = [
        (0.055, 0.455, 0.205, 0.235, BLUE_LIGHT, BLUE),
        (0.285, 0.455, 0.205, 0.235, TEAL_LIGHT, TEAL),
        (0.515, 0.455, 0.205, 0.235, GREEN_LIGHT, GREEN),
        (0.745, 0.455, 0.205, 0.235, AMBER_LIGHT, AMBER),
    ]
    for index, (metric, card) in enumerate(zip(metrics, cards, strict=True), start=1):
        x, y, width, height, fill, accent = card
        add_box(fig, x, y, width, height, facecolor=fill, edgecolor="none", radius=0.014)
        fig.add_artist(
            Circle(
                (x + 0.030, y + height - 0.034),
                0.014,
                transform=fig.transFigure,
                facecolor=accent,
                edgecolor="none",
                clip_on=False,
            )
        )
        fig.text(
            x + 0.030,
            y + height - 0.034,
            str(index),
            ha="center",
            va="center",
            fontsize=11,
            fontweight="bold",
            color=PAPER,
        )
        fig.text(
            x + 0.028,
            y + height - 0.091,
            metric["label"],
            ha="left",
            va="center",
            fontsize=13.5,
            color=INK,
        )
        draw_value(
            fig,
            x + width / 2,
            y + 0.064,
            metric["core"],
            metric["suffix"],
            core_size=36,
            color=accent,
            ha="center",
        )

    for x1, x2 in ((0.260, 0.285), (0.490, 0.515), (0.720, 0.745)):
        add_line(fig, x1, 0.572, x2, 0.572, color=GRID, linewidth=3.0)
        fig.add_artist(
            Polygon(
                [(x2 - 0.008, 0.582), (x2, 0.572), (x2 - 0.008, 0.562)],
                closed=True,
                transform=fig.transFigure,
                facecolor=GRID,
                edgecolor="none",
                clip_on=False,
            )
        )

    copy = copy_blocks[0]
    add_box(fig, 0.055, 0.135, 0.885, 0.155, facecolor=PALE, edgecolor=GRID, radius=0.012)
    fig.text(
        0.082,
        0.242,
        copy["heading"],
        ha="left",
        va="center",
        fontsize=16,
        fontweight="bold",
        color=NAVY,
    )
    body = "".join(copy["body"])
    fig.text(
        0.082,
        0.188,
        wrap_zh(body, 58),
        ha="left",
        va="center",
        fontsize=15,
        color=INK,
        linespacing=1.4,
    )

    add_footer(fig, panel_source_label(panel, evidence_plan))
    output_path = Path(out_dir) / f"{panel['name']}.png"
    fig.savefig(
        output_path,
        dpi=DPI,
        facecolor=PAPER,
        metadata={"Title": panel["title"], "Description": panel["alt"]},
    )
    plt.close(fig)


def render_attention_gate(
    panel: dict[str, Any],
    source_data: dict[str, Any],
    mirror_data: dict[str, Any],
    evidence_plan: dict[str, Any],
) -> None:
    metrics = [bind_metric(block, source_data, mirror_data) for block in metric_blocks(panel)]
    if len(metrics) != 4:
        raise ValueError("2_attention_gate must contain exactly four metrics")
    copy_blocks = text_blocks(panel)
    if len(copy_blocks) != 1:
        raise ValueError("2_attention_gate must contain exactly one text block")

    fig = new_figure()
    add_header(fig, panel["title"], accent=RED)
    cards = [
        (0.055, 0.570, 0.425, 0.185, BLUE_LIGHT, BLUE),
        (0.520, 0.570, 0.425, 0.185, RED_LIGHT, RED),
        (0.055, 0.345, 0.425, 0.185, AMBER_LIGHT, AMBER),
        (0.520, 0.345, 0.425, 0.185, PALE, NAVY),
    ]

    for index, (metric, card) in enumerate(zip(metrics, cards, strict=True)):
        x, y, width, height, fill, accent = card
        add_box(fig, x, y, width, height, facecolor=fill, edgecolor="none", radius=0.018)
        fig.text(
            x + 0.028,
            y + height - 0.047,
            metric["label"],
            ha="left",
            va="center",
            fontsize=16,
            fontweight="bold",
            color=INK,
        )
        fig.add_artist(
            Circle(
                (x + width - 0.038, y + height - 0.042),
                0.017,
                transform=fig.transFigure,
                facecolor=accent,
                edgecolor="none",
                clip_on=False,
            )
        )
        fig.text(
            x + width - 0.038,
            y + height - 0.042,
            "×" if index in (1, 2, 3) else "p",
            ha="center",
            va="center",
            fontsize=13,
            fontweight="bold",
            color=PAPER,
        )
        draw_value(
            fig,
            x + 0.028,
            y + 0.063,
            metric["core"],
            metric["suffix"],
            core_size=43,
            color=accent,
        )
        if metric["note"]:
            fig.text(
                x + 0.175,
                y + 0.049,
                wrap_zh(metric["note"], 14),
                ha="left",
                va="center",
                fontsize=12,
                color=MUTED,
                linespacing=1.25,
            )

    copy = copy_blocks[0]
    add_box(fig, 0.055, 0.125, 0.890, 0.150, facecolor=NAVY, edgecolor="none", radius=0.016)
    fig.text(
        0.083,
        0.227,
        copy["heading"],
        ha="left",
        va="center",
        fontsize=16,
        fontweight="bold",
        color=LIGHT_TEXT,
    )
    body = "".join(copy["body"])
    fig.text(
        0.083,
        0.174,
        wrap_zh(body, 59),
        ha="left",
        va="center",
        fontsize=15,
        color=PAPER,
        linespacing=1.38,
    )

    add_footer(fig, panel_source_label(panel, evidence_plan))
    output_path = Path(out_dir) / f"{panel['name']}.png"
    fig.savefig(
        output_path,
        dpi=DPI,
        facecolor=PAPER,
        metadata={"Title": panel["title"], "Description": panel["alt"]},
    )
    plt.close(fig)


def render_honest_boundary(
    panel: dict[str, Any],
    source_data: dict[str, Any],
    mirror_data: dict[str, Any],
    evidence_plan: dict[str, Any],
) -> None:
    metrics = [bind_metric(block, source_data, mirror_data) for block in metric_blocks(panel)]
    if len(metrics) != 4:
        raise ValueError("3_honest_boundary must contain exactly four metrics")
    copy_blocks = text_blocks(panel)
    if len(copy_blocks) != 2:
        raise ValueError("3_honest_boundary must contain exactly two text blocks")

    fig = new_figure()
    add_header(fig, panel["title"], accent=AMBER)
    fig.text(
        0.065,
        0.785,
        "事件日相對同股票對照日的差距",
        ha="left",
        va="center",
        fontsize=16,
        fontweight="bold",
        color=NAVY,
    )
    fig.text(
        0.935,
        0.785,
        "正值代表事件日較大",
        ha="right",
        va="center",
        fontsize=13,
        color=MUTED,
    )

    raw_values = [metric["raw"] for metric in metrics]
    max_abs = max(abs(value) for value in raw_values)
    if max_abs == 0:
        raise ValueError("Cannot render zero-range direct event-minus-control differences")
    bar_y = [0.690, 0.605, 0.500, 0.415]
    fills = [BLUE, TEAL, BLUE, TEAL]
    light_fills = [BLUE_LIGHT, TEAL_LIGHT, BLUE_LIGHT, TEAL_LIGHT]
    for metric, y, fill, light_fill in zip(metrics, bar_y, fills, light_fills, strict=True):
        fig.text(
            0.065,
            y,
            metric["label"],
            ha="left",
            va="center",
            fontsize=15,
            color=INK,
        )
        add_box(fig, 0.300, y - 0.025, 0.455, 0.050, facecolor=light_fill, radius=0.010)
        bar_width = 0.455 * abs(metric["raw"]) / max_abs
        bar_x = 0.300 if metric["raw"] >= 0 else 0.755 - bar_width
        fig.add_artist(
            Rectangle(
                (bar_x, y - 0.025),
                bar_width,
                0.050,
                transform=fig.transFigure,
                facecolor=fill if metric["raw"] >= 0 else RED,
                edgecolor="none",
                clip_on=False,
            )
        )
        formatted = metric["core"] + (f" {metric['suffix']}" if metric["suffix"] else "")
        fig.text(
            0.785,
            y,
            formatted,
            ha="left",
            va="center",
            fontsize=20,
            fontweight="bold",
            color=fill if metric["raw"] >= 0 else RED,
        )

    copy_cards = [
        (0.055, 0.105, 0.425, 0.230, GREEN_LIGHT, GREEN),
        (0.520, 0.105, 0.425, 0.230, RED_LIGHT, RED),
    ]
    for copy, card in zip(copy_blocks, copy_cards, strict=True):
        x, y, width, height, fill, accent = card
        add_box(fig, x, y, width, height, facecolor=fill, edgecolor="none", radius=0.014)
        fig.add_artist(
            Rectangle(
                (x + 0.020, y + 0.032),
                0.006,
                height - 0.064,
                transform=fig.transFigure,
                facecolor=accent,
                edgecolor="none",
                clip_on=False,
            )
        )
        fig.text(
            x + 0.045,
            y + height - 0.045,
            copy["heading"],
            ha="left",
            va="center",
            fontsize=16,
            fontweight="bold",
            color=accent,
        )
        body = "".join(copy["body"])
        fig.text(
            x + 0.045,
            y + 0.095,
            wrap_zh(body, 18),
            ha="left",
            va="center",
            fontsize=12.5,
            color=INK,
            linespacing=1.32,
        )

    add_footer(fig, panel_source_label(panel, evidence_plan))
    output_path = Path(out_dir) / f"{panel['name']}.png"
    fig.savefig(
        output_path,
        dpi=DPI,
        facecolor=PAPER,
        metadata={"Title": panel["title"], "Description": panel["alt"]},
    )
    plt.close(fig)


def validate_panel(panel: dict[str, Any], expected_name: str) -> None:
    if panel["name"] != expected_name:
        raise ValueError(f"Expected panel {expected_name!r}, got {panel['name']!r}")
    if not isinstance(panel["title"], str) or not panel["title"]:
        raise ValueError(f"Panel {expected_name!r} has no title")
    if not isinstance(panel["alt"], str) or not panel["alt"]:
        raise ValueError(f"Panel {expected_name!r} has no alt text")
    if panel["sources"] != ["result"]:
        raise ValueError(f"Panel {expected_name!r} must use only the result evidence source")


def main() -> None:
    # Read every file in the supplied evidence package. README/article text is
    # contextual evidence; displayed numbers remain JSON-bound through plan.json.
    result = load_json(RESULT_PATH)
    lowercase_result = load_json(RESULT_LOWERCASE_PATH)
    plan = load_json(PLAN_PATH)
    readme = load_text(README_PATH)
    article = load_text(ARTICLE_PATH)
    if not readme.strip() or not article.strip():
        raise ValueError("README.md and article evidence must both be non-empty")

    evidence_plan = plan["evidence"]
    if evidence_plan["result"]["path"] != "experiments/K1678/K1678_results.json":
        raise ValueError("Strict plan result path changed unexpectedly")
    source_data = {"result": result}
    mirror_data = {"result": lowercase_result}

    panels = plan["panels"]
    expected_names = ["1_data_funnel", "2_attention_gate", "3_honest_boundary"]
    if len(panels) != len(expected_names):
        raise ValueError(f"Expected three panels, found {len(panels)}")
    for panel, expected_name in zip(panels, expected_names, strict=True):
        validate_panel(panel, expected_name)

    os.makedirs(out_dir, exist_ok=True)
    render_data_funnel(panels[0], source_data, mirror_data, evidence_plan)
    render_attention_gate(panels[1], source_data, mirror_data, evidence_plan)
    render_honest_boundary(panels[2], source_data, mirror_data, evidence_plan)


if __name__ == "__main__":
    main()
