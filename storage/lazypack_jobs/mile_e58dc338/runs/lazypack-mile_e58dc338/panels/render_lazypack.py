#!/usr/bin/env python3
"""Render the three data-bound PNG panels for mile_e58dc338.

All displayed statistics are resolved at runtime from the certified K1010
results JSON.  Titles, labels, notes, and takeaway copy are read from the
panel plan.  Missing files, panels, blocks, or result fields raise immediately.
"""

from __future__ import annotations

import json
import os
import textwrap
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Circle, FancyBboxPatch, Polygon, Rectangle


RESULTS_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1010/k1010_results.json"
)
README_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1010/README.md"
)
PLAN_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_e58dc338/runs/lazypack-mile_e58dc338/plan.json"
)
ARTICLE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_e58dc338/runs/lazypack-mile_e58dc338/panels/"
    "mile_e58dc338_article.md"
)
OUT_DIR = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_e58dc338/runs/lazypack-mile_e58dc338/panels"
)

WIDTH_PX = 1600
HEIGHT_PX = 1000
DPI = 150

INK = "#10233F"
MUTED = "#5D6B7D"
FAINT = "#8A96A6"
LINE = "#DCE3EA"
PAPER = "#FFFFFF"
SOFT = "#F4F7FA"
NAVY = "#10233F"
BLUE = "#1D6FA5"
TEAL = "#138A82"
TEAL_SOFT = "#E7F4F2"
AMBER = "#B96B18"
AMBER_SOFT = "#FFF2DE"
RED = "#B23A48"
RED_SOFT = "#FBEAEC"


plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False


def load_json_required(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        value = json.load(fh)
    if not isinstance(value, dict):
        raise TypeError(f"Expected a JSON object: {path}")
    return value


def load_text_required(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError(f"Evidence text is empty: {path}")
    return text


def require(mapping: dict[str, Any], key: str, context: str) -> Any:
    if key not in mapping:
        raise KeyError(f"Missing {context}.{key}")
    return mapping[key]


def resolve_path(data: Any, path: str) -> Any:
    """Resolve either JSON Pointer (/a/b) or dotted (a.b) paths."""
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
                raise KeyError(f"Missing evidence field: {path}")
            current = current[part]
        elif isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError) as exc:
                raise KeyError(f"Missing evidence field: {path}") from exc
        else:
            raise KeyError(f"Missing evidence field: {path}")
    return current


def format_value(raw: Any, spec: dict[str, Any], path: str) -> str:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise TypeError(f"Expected numeric value at {path}, got {type(raw).__name__}")

    kind = require(spec, "kind", f"format for {path}")
    suffix = spec.get("suffix", "")
    scale = spec.get("scale", 1)
    if isinstance(scale, bool) or not isinstance(scale, (int, float)):
        raise TypeError(f"Invalid scale for {path}: {scale!r}")
    value = raw * scale

    if kind == "integer":
        if not float(value).is_integer():
            raise ValueError(f"Expected integer-compatible value at {path}: {value}")
        return f"{int(value):,}{suffix}"
    if kind == "number":
        digits = require(spec, "digits", f"format for {path}")
        if isinstance(digits, bool) or not isinstance(digits, int) or digits < 0:
            raise TypeError(f"Invalid digits for {path}: {digits!r}")
        return f"{value:,.{digits}f}{suffix}"
    raise ValueError(f"Unsupported format kind for {path}: {kind!r}")


def panel_by_name(plan: dict[str, Any], name: str) -> dict[str, Any]:
    panels = require(plan, "panels", "plan")
    if not isinstance(panels, list):
        raise TypeError("plan.panels must be a list")
    for panel in panels:
        if not isinstance(panel, dict):
            raise TypeError("Every plan panel must be an object")
        if panel.get("name") == name:
            return panel
    raise KeyError(f"Missing plan panel: {name}")


def metric_blocks(panel: dict[str, Any], result: dict[str, Any]) -> list[dict[str, Any]]:
    blocks = require(panel, "blocks", f"panel {panel.get('name')}")
    if not isinstance(blocks, list):
        raise TypeError(f"Panel {panel.get('name')} blocks must be a list")
    bound: list[dict[str, Any]] = []
    for block in blocks:
        if not isinstance(block, dict):
            raise TypeError(f"Panel {panel.get('name')} block must be an object")
        if block.get("kind") != "metric":
            continue
        value_spec = require(block, "value", f"metric {block.get('label')}")
        if not isinstance(value_spec, dict):
            raise TypeError(f"Metric value must be an object: {block.get('label')}")
        if require(value_spec, "source", f"metric {block.get('label')}") != "result":
            raise ValueError(f"Unsupported metric source: {value_spec.get('source')}")
        path = require(value_spec, "path", f"metric {block.get('label')}")
        fmt = require(value_spec, "format", f"metric {block.get('label')}")
        if not isinstance(fmt, dict):
            raise TypeError(f"Metric format must be an object: {block.get('label')}")
        raw = resolve_path(result, path)
        bound.append(
            {
                "label": require(block, "label", "metric block"),
                "note": block.get("note"),
                "raw": raw,
                "rendered": format_value(raw, fmt, path),
                "path": path,
            }
        )
    return bound


def text_blocks(panel: dict[str, Any]) -> list[dict[str, str]]:
    blocks = require(panel, "blocks", f"panel {panel.get('name')}")
    if not isinstance(blocks, list):
        raise TypeError(f"Panel {panel.get('name')} blocks must be a list")
    texts: list[dict[str, str]] = []
    for block in blocks:
        if not isinstance(block, dict):
            raise TypeError(f"Panel {panel.get('name')} block must be an object")
        if block.get("kind") != "text":
            continue
        body = require(block, "body", f"text block {block.get('heading')}")
        if not isinstance(body, list) or not body or not all(isinstance(x, str) for x in body):
            raise TypeError(f"Text body must be a non-empty string list: {block.get('heading')}")
        texts.append(
            {
                "heading": require(block, "heading", "text block"),
                "body": "\n".join(body),
            }
        )
    return texts


def make_canvas() -> plt.Figure:
    return plt.figure(
        figsize=(WIDTH_PX / DPI, HEIGHT_PX / DPI),
        dpi=DPI,
        facecolor=PAPER,
    )


def add_rect(
    fig: plt.Figure,
    x: float,
    y: float,
    w: float,
    h: float,
    face: str,
    edge: str = "none",
    radius: float = 0.018,
    linewidth: float = 1.0,
) -> None:
    fig.add_artist(
        FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle=f"round,pad=0,rounding_size={radius}",
            transform=fig.transFigure,
            facecolor=face,
            edgecolor=edge,
            linewidth=linewidth,
        )
    )


def add_line(
    fig: plt.Figure,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    color: str,
    linewidth: float = 1.0,
) -> None:
    fig.add_artist(
        Line2D(
            [x1, x2],
            [y1, y2],
            transform=fig.transFigure,
            color=color,
            linewidth=linewidth,
            solid_capstyle="round",
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


def title_area(fig: plt.Figure, panel: dict[str, Any], dark: bool = False) -> None:
    title = require(panel, "title", f"panel {panel.get('name')}")
    alt = require(panel, "alt", f"panel {panel.get('name')}")
    color = PAPER if dark else INK
    subcolor = "#D6E1ED" if dark else MUTED
    fig.text(0.06, 0.925, title, ha="left", va="center", fontsize=34, fontweight="bold", color=color)
    fig.text(0.06, 0.860, alt, ha="left", va="center", fontsize=18, color=subcolor)


def source_footer(fig: plt.Figure, source_label: str, dark: bool = False) -> None:
    color = "#C8D2DE" if dark else MUTED
    line_color = "#3A4B60" if dark else LINE
    add_line(fig, 0.06, 0.075, 0.94, 0.075, line_color, 1.0)
    fig.text(0.06, 0.038, source_label, ha="left", va="center", fontsize=14, color=color)


def render_probability_promise(
    panel: dict[str, Any], result: dict[str, Any], source_label: str
) -> None:
    metrics = metric_blocks(panel, result)
    if len(metrics) != 4:
        raise ValueError("Panel 1 must contain exactly four metric blocks")

    fig = make_canvas()
    title_area(fig, panel)
    add_line(fig, 0.06, 0.815, 0.94, 0.815, LINE, 1.2)

    # Promise card
    add_rect(fig, 0.06, 0.475, 0.265, 0.275, SOFT, LINE, 0.020, 1.0)
    fig.add_artist(Circle((0.095, 0.700), 0.014, transform=fig.transFigure, facecolor=BLUE, edgecolor="none"))
    fig.text(0.125, 0.700, metrics[0]["label"], ha="left", va="center", fontsize=17, color=MUTED)
    fig.text(0.085, 0.585, metrics[0]["rendered"], ha="left", va="center", fontsize=50, fontweight="bold", color=INK)
    fig.text(0.085, 0.515, "名義警戒頻率", ha="left", va="center", fontsize=15, color=FAINT)

    # Student-t result card
    add_rect(fig, 0.35, 0.475, 0.315, 0.275, TEAL_SOFT, "#B7DDD8", 0.020, 1.0)
    fig.add_artist(Circle((0.385, 0.700), 0.014, transform=fig.transFigure, facecolor=TEAL, edgecolor="none"))
    fig.text(0.415, 0.700, metrics[1]["label"], ha="left", va="center", fontsize=17, color=MUTED)
    fig.text(0.375, 0.585, metrics[1]["rendered"], ha="left", va="center", fontsize=50, fontweight="bold", color=TEAL)
    if not metrics[1]["note"]:
        raise KeyError("Panel 1 thick-tail metric note is required")
    fig.text(0.375, 0.515, metrics[1]["note"], ha="left", va="center", fontsize=15, color=TEAL)

    # Rolling calibration result card, intentionally taller for the risk signal.
    add_rect(fig, 0.69, 0.235, 0.25, 0.515, RED_SOFT, "#E7BCC2", 0.020, 1.0)
    fig.add_artist(
        Polygon(
            [[0.725, 0.685], [0.742, 0.715], [0.759, 0.685]],
            closed=True,
            transform=fig.transFigure,
            facecolor=RED,
            edgecolor="none",
        )
    )
    fig.text(0.785, 0.700, wrapped(metrics[2]["label"], 10), ha="center", va="center", fontsize=17, color=MUTED, linespacing=1.25)
    fig.text(0.815, 0.535, metrics[2]["rendered"], ha="center", va="center", fontsize=52, fontweight="bold", color=RED)
    if not metrics[2]["note"]:
        raise KeyError("Panel 1 rolling-calibration metric note is required")
    fig.text(0.815, 0.435, wrapped(metrics[2]["note"], 10), ha="center", va="center", fontsize=16, color=RED, linespacing=1.25)
    add_line(fig, 0.735, 0.355, 0.895, 0.355, "#E0A7AF", 1.0)
    fig.text(0.815, 0.300, "警戒線明顯失真", ha="center", va="center", fontsize=15, color=MUTED)

    # Shared evaluation card
    add_rect(fig, 0.06, 0.235, 0.605, 0.195, PAPER, LINE, 0.020, 1.2)
    fig.text(0.085, 0.375, metrics[3]["label"], ha="left", va="center", fontsize=17, color=MUTED)
    fig.text(0.085, 0.295, metrics[3]["rendered"], ha="left", va="center", fontsize=36, fontweight="bold", color=INK)
    add_line(fig, 0.37, 0.270, 0.37, 0.390, LINE, 1.0)
    fig.text(0.405, 0.345, "同一評估區間", ha="left", va="center", fontsize=17, color=INK)
    fig.text(0.405, 0.295, "承諾與實際頻率直接對照", ha="left", va="center", fontsize=15, color=MUTED)

    source_footer(fig, source_label)
    fig.savefig(OUT_DIR / "1_probability_promise.png", dpi=DPI, facecolor=PAPER)
    plt.close(fig)


def render_calibration_ranking(
    panel: dict[str, Any], result: dict[str, Any], source_label: str
) -> None:
    metrics = metric_blocks(panel, result)
    if len(metrics) != 4:
        raise ValueError("Panel 2 must contain exactly four metric blocks")

    fig = make_canvas()
    fig.add_artist(Rectangle((0, 0.795), 1, 0.205, transform=fig.transFigure, facecolor=NAVY, edgecolor="none"))
    title_area(fig, panel, dark=True)

    primary = metrics[:2]
    max_value = max(float(item["raw"]) for item in primary)
    if max_value <= 0:
        raise ValueError("Panel 2 calibration deviations must be positive")

    card_specs = [
        (0.06, TEAL_SOFT, "#B7DDD8", TEAL),
        (0.52, RED_SOFT, "#E7BCC2", RED),
    ]
    for metric, (x, face, edge, accent) in zip(primary, card_specs):
        add_rect(fig, x, 0.435, 0.42, 0.285, face, edge, 0.018, 1.0)
        fig.text(x + 0.03, 0.670, metric["label"], ha="left", va="center", fontsize=18, color=MUTED)
        fig.text(x + 0.03, 0.575, metric["rendered"], ha="left", va="center", fontsize=48, fontweight="bold", color=accent)
        if not metric["note"]:
            raise KeyError(f"Panel 2 metric note is required: {metric['label']}")
        fig.text(x + 0.03, 0.500, metric["note"], ha="left", va="center", fontsize=16, color=accent)
        bar_x = x + 0.25
        bar_y = 0.548
        bar_w = 0.135
        add_line(fig, bar_x, bar_y, bar_x + bar_w, bar_y, "#CED7DF", 8.0)
        add_line(fig, bar_x, bar_y, bar_x + bar_w * (float(metric["raw"]) / max_value), bar_y, accent, 8.0)

    secondary_specs = [(metrics[2], 0.06), (metrics[3], 0.52)]
    for metric, x in secondary_specs:
        add_rect(fig, x, 0.165, 0.42, 0.195, PAPER, LINE, 0.018, 1.1)
        fig.text(x + 0.03, 0.310, metric["label"], ha="left", va="center", fontsize=17, color=MUTED)
        fig.text(x + 0.03, 0.235, metric["rendered"], ha="left", va="center", fontsize=34, fontweight="bold", color=INK)
        fig.add_artist(Circle((x + 0.365, 0.262), 0.020, transform=fig.transFigure, facecolor="#E8EEF4", edgecolor="none"))
        add_line(fig, x + 0.365, 0.262, x + 0.365, 0.275, BLUE, 1.7)
        add_line(fig, x + 0.365, 0.262, x + 0.376, 0.254, BLUE, 1.7)

    source_footer(fig, source_label)
    fig.savefig(OUT_DIR / "2_calibration_ranking.png", dpi=DPI, facecolor=PAPER)
    plt.close(fig)


def render_honest_boundary(
    panel: dict[str, Any], result: dict[str, Any], source_label: str
) -> None:
    texts = text_blocks(panel)
    metrics = metric_blocks(panel, result)
    if len(texts) != 3:
        raise ValueError("Panel 3 must contain exactly three text blocks")
    if len(metrics) != 1:
        raise ValueError("Panel 3 must contain exactly one metric block")
    metric = metrics[0]
    if not metric["note"]:
        raise KeyError("Panel 3 metric note is required")

    fig = make_canvas()
    title_area(fig, panel)
    add_line(fig, 0.06, 0.815, 0.94, 0.815, LINE, 1.2)

    # Main editorial visual: a restrained, data-bound metric feature.
    add_rect(fig, 0.06, 0.185, 0.31, 0.565, NAVY, NAVY, 0.020, 0.0)
    fig.add_artist(Circle((0.105, 0.685), 0.018, transform=fig.transFigure, facecolor=TEAL, edgecolor="none"))
    fig.text(0.135, 0.685, metric["label"], ha="left", va="center", fontsize=18, color="#D8E2ED")
    fig.text(0.215, 0.515, metric["rendered"], ha="center", va="center", fontsize=72, fontweight="bold", color=PAPER)
    add_line(fig, 0.105, 0.410, 0.325, 0.410, "#40536A", 1.0)
    fig.text(0.105, 0.335, wrapped(metric["note"], 13), ha="left", va="center", fontsize=17, color="#D8E2ED", linespacing=1.35)
    fig.text(0.105, 0.235, "研究限制也要一起讀", ha="left", va="center", fontsize=15, color="#9FB0C2")

    # Three reading rules, each in its own non-overlapping editorial row.
    y_positions = [0.615, 0.415, 0.215]
    accents = [TEAL, BLUE, AMBER]
    for item, y, accent in zip(texts, y_positions, accents):
        fig.add_artist(Circle((0.435, y + 0.073), 0.010, transform=fig.transFigure, facecolor=accent, edgecolor="none"))
        fig.text(0.462, y + 0.075, item["heading"], ha="left", va="center", fontsize=21, fontweight="bold", color=INK)
        fig.text(0.462, y - 0.005, wrapped(item["body"], 25), ha="left", va="center", fontsize=17, color=MUTED, linespacing=1.35)
        if y > y_positions[-1]:
            add_line(fig, 0.425, y - 0.095, 0.94, y - 0.095, LINE, 1.0)

    source_footer(fig, source_label)
    fig.savefig(OUT_DIR / "3_honest_boundary.png", dpi=DPI, facecolor=PAPER)
    plt.close(fig)


def main() -> None:
    result = load_json_required(RESULTS_PATH)
    plan = load_json_required(PLAN_PATH)
    # These are part of the evidence package; reading them also makes missing or
    # empty evidence fail visibly before any output is written.
    load_text_required(README_PATH)
    load_text_required(ARTICLE_PATH)

    experiment_id = require(result, "experiment_id", "result")
    if not isinstance(experiment_id, str) or not experiment_id.strip():
        raise TypeError("result.experiment_id must be a non-empty string")
    source_label = f"資料來源：experiment {experiment_id.upper()}"

    panel_1 = panel_by_name(plan, "1_probability_promise")
    panel_2 = panel_by_name(plan, "2_calibration_ranking")
    panel_3 = panel_by_name(plan, "3_honest_boundary")

    os.makedirs(OUT_DIR, exist_ok=True)
    render_probability_promise(panel_1, result, source_label)
    render_calibration_ranking(panel_2, result, source_label)
    render_honest_boundary(panel_3, result, source_label)


if __name__ == "__main__":
    main()
