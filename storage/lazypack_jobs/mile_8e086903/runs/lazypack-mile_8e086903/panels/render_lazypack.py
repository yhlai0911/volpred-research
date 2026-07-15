#!/usr/bin/env python3
"""Render the three data-bound K1386 general-audience lazypack panels."""

from __future__ import annotations

import json
import os
import textwrap
from dataclasses import dataclass
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyBboxPatch, Rectangle


RESULT_PATH = "/Users/yhlai0911/volpred-research/experiments/k1386/k1386_results.json"
README_PATH = "/Users/yhlai0911/volpred-research/experiments/k1386/README.md"
PLAN_PATH = "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_8e086903/runs/lazypack-mile_8e086903/plan.json"
ARTICLE_PATH = "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_8e086903/runs/lazypack-mile_8e086903/panels/mile_8e086903_article.md"
OUT_DIR = "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_8e086903/runs/lazypack-mile_8e086903/panels"

WIDTH = 1600
HEIGHT = 1000
DPI = 150

PAPER = "#FFFFFF"
INK = "#162333"
MUTED = "#5D6876"
FAINT = "#8792A0"
GRID = "#DCE3EA"
NAVY = "#16324F"
BLUE = "#176B87"
BLUE_SOFT = "#E8F2F6"
TEAL = "#167D7F"
TEAL_SOFT = "#E5F3F1"
AMBER = "#B77816"
AMBER_SOFT = "#FAF0DC"
SLATE_SOFT = "#F4F6F8"

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False


@dataclass(frozen=True)
class Metric:
    label: str
    rendered: str
    raw: int | float
    path: str
    note: str = ""


def load_json(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise TypeError(f"Expected a JSON object: {path}")
    return value


def load_required_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as handle:
        value = handle.read()
    if not value.strip():
        raise ValueError(f"Evidence text is empty: {path}")
    return value


def require_path(data: Any, path: str) -> Any:
    current = data
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise KeyError(f"Missing required result field: {path}")
        current = current[part]
    return current


def require_string(data: dict[str, Any], key: str, context: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise KeyError(f"Missing required string {context}.{key}")
    return value


def format_bound_value(raw: Any, spec: dict[str, Any], path: str) -> str:
    kind = require_string(spec, "kind", f"format for {path}")
    suffix = spec.get("suffix", "")
    if not isinstance(suffix, str):
        raise TypeError(f"Format suffix must be a string for {path}")

    if kind == "number":
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise TypeError(f"Expected numeric result at {path}")
        digits = spec.get("digits")
        if type(digits) is not int or digits < 0:
            raise TypeError(f"Expected non-negative integer digits for {path}")
        return f"{raw:.{digits}f}{suffix}"

    if kind == "integer":
        if type(raw) is not int:
            raise TypeError(f"Expected integer result at {path}")
        return f"{raw:d}{suffix}"

    raise ValueError(f"Unsupported format kind {kind!r} for {path}")


def panel_by_name(plan: dict[str, Any], name: str) -> dict[str, Any]:
    panels = plan.get("panels")
    if not isinstance(panels, list):
        raise KeyError("Missing required plan.panels list")
    matches = [panel for panel in panels if isinstance(panel, dict) and panel.get("name") == name]
    if len(matches) != 1:
        raise KeyError(f"Expected exactly one panel named {name!r}")
    return matches[0]


def metric_at(panel: dict[str, Any], index: int, result: dict[str, Any]) -> Metric:
    blocks = panel.get("blocks")
    if not isinstance(blocks, list) or index >= len(blocks):
        raise KeyError(f"Missing metric block {index} in panel {panel.get('name')}")
    block = blocks[index]
    if not isinstance(block, dict) or block.get("kind") != "metric":
        raise TypeError(f"Block {index} in panel {panel.get('name')} must be a metric")
    label = require_string(block, "label", f"panel {panel.get('name')} block {index}")
    value_spec = block.get("value")
    if not isinstance(value_spec, dict) or value_spec.get("source") != "result":
        raise TypeError(f"Metric {label!r} must bind to source=result")
    path = require_string(value_spec, "path", f"metric {label}")
    fmt = value_spec.get("format")
    if not isinstance(fmt, dict):
        raise TypeError(f"Metric {label!r} is missing its format object")
    raw = require_path(result, path)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise TypeError(f"Metric {label!r} did not resolve to a number at {path}")
    note = block.get("note", "")
    if not isinstance(note, str):
        raise TypeError(f"Metric note must be text for {label!r}")
    return Metric(label, format_bound_value(raw, fmt, path), raw, path, note)


def text_block_at(panel: dict[str, Any], index: int) -> tuple[str, str]:
    blocks = panel.get("blocks")
    if not isinstance(blocks, list) or index >= len(blocks):
        raise KeyError(f"Missing text block {index} in panel {panel.get('name')}")
    block = blocks[index]
    if not isinstance(block, dict) or block.get("kind") != "text":
        raise TypeError(f"Block {index} in panel {panel.get('name')} must be text")
    heading = require_string(block, "heading", f"panel {panel.get('name')} block {index}")
    body = block.get("body")
    if not isinstance(body, list) or not body or not all(isinstance(item, str) and item.strip() for item in body):
        raise TypeError(f"Text body {index} in panel {panel.get('name')} must be non-empty text")
    return heading, "\n".join(body)


def make_canvas() -> tuple[plt.Figure, plt.Axes]:
    fig = plt.figure(figsize=(WIDTH / DPI, HEIGHT / DPI), dpi=DPI, facecolor=PAPER)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    return fig, ax


def rounded_box(
    ax: plt.Axes,
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    facecolor: str,
    edgecolor: str = GRID,
    linewidth: float = 1.2,
    radius: float = 0.018,
) -> None:
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            width,
            height,
            boxstyle=f"round,pad=0.006,rounding_size={radius}",
            transform=ax.transAxes,
            facecolor=facecolor,
            edgecolor=edgecolor,
            linewidth=linewidth,
        )
    )


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


def add_header(ax: plt.Axes, title: str, alt: str, accent: str = BLUE) -> None:
    ax.add_patch(Rectangle((0.07, 0.936), 0.085, 0.010, transform=ax.transAxes, color=accent, linewidth=0))
    ax.text(0.07, 0.889, title, fontsize=29, fontweight="bold", color=INK, ha="left", va="center")
    ax.text(0.07, 0.822, alt, fontsize=15, color=MUTED, ha="left", va="center")


def add_footer(ax: plt.Axes, experiment_id: str) -> None:
    ax.plot([0.07, 0.93], [0.108, 0.108], color=GRID, linewidth=1.0, transform=ax.transAxes)
    ax.text(
        0.07,
        0.067,
        f"資料來源：experiment {experiment_id}",
        fontsize=11.5,
        color=FAINT,
        ha="left",
        va="center",
    )
    ax.text(0.93, 0.067, "VolPred", fontsize=11.5, color=FAINT, ha="right", va="center")


def save_panel(fig: plt.Figure, name: str) -> None:
    path = os.path.join(OUT_DIR, f"{name}.png")
    fig.savefig(path, format="png", dpi=DPI, facecolor=PAPER, bbox_inches=None, pad_inches=0)
    plt.close(fig)


def render_scoreboard(panel: dict[str, Any], result: dict[str, Any], experiment_id: str) -> None:
    title = require_string(panel, "title", "scoreboard panel")
    alt = require_string(panel, "alt", "scoreboard panel")
    har = metric_at(panel, 0, result)
    uni = metric_at(panel, 1, result)
    multi = metric_at(panel, 2, result)
    n_eval = metric_at(panel, 3, result)

    fig, ax = make_canvas()
    add_header(ax, title, alt, BLUE)

    rounded_box(ax, 0.07, 0.38, 0.42, 0.36, facecolor=NAVY, edgecolor=NAVY)
    ax.text(0.10, 0.675, har.label, fontsize=18, color="#DCEAF2", ha="left", va="center")
    ax.text(0.10, 0.515, har.rendered, fontsize=50, fontweight="bold", color=PAPER, ha="left", va="center")
    ax.text(0.10, 0.420, "QLIKE 越低越好", fontsize=13.5, color="#BFD3DE", ha="left", va="center")
    ax.add_patch(Circle((0.445, 0.685), 0.016, transform=ax.transAxes, facecolor=TEAL, edgecolor="none"))

    rounded_box(ax, 0.52, 0.57, 0.41, 0.17, facecolor=BLUE_SOFT)
    ax.text(0.55, 0.690, uni.label, fontsize=15.5, color=MUTED, ha="left", va="center")
    ax.text(0.90, 0.615, uni.rendered, fontsize=30, fontweight="bold", color=INK, ha="right", va="center")
    ax.add_patch(Rectangle((0.52, 0.57), 0.008, 0.17, transform=ax.transAxes, color=BLUE, linewidth=0))

    rounded_box(ax, 0.52, 0.38, 0.41, 0.17, facecolor=SLATE_SOFT)
    ax.text(0.55, 0.500, multi.label, fontsize=15.5, color=MUTED, ha="left", va="center")
    ax.text(0.90, 0.425, multi.rendered, fontsize=30, fontweight="bold", color=INK, ha="right", va="center")
    ax.add_patch(Rectangle((0.52, 0.38), 0.008, 0.17, transform=ax.transAxes, color=AMBER, linewidth=0))

    rounded_box(ax, 0.07, 0.17, 0.86, 0.13, facecolor=TEAL_SOFT, edgecolor="#CFE5E1")
    ax.text(0.105, 0.235, n_eval.label, fontsize=16, color=TEAL, fontweight="bold", ha="left", va="center")
    ax.text(0.895, 0.235, n_eval.rendered, fontsize=30, color=INK, fontweight="bold", ha="right", va="center")

    add_footer(ax, experiment_id)
    save_panel(fig, require_string(panel, "name", "scoreboard panel"))


def render_rough_not_better(panel: dict[str, Any], result: dict[str, Any], experiment_id: str) -> None:
    title = require_string(panel, "title", "roughness panel")
    alt = require_string(panel, "alt", "roughness panel")
    spy = metric_at(panel, 0, result)
    qqq = metric_at(panel, 1, result)
    dm_uni = metric_at(panel, 2, result)
    dm_multi = metric_at(panel, 3, result)

    fig, ax = make_canvas()
    ax.add_patch(Rectangle((0, 0.76), 1, 0.24, transform=ax.transAxes, color=NAVY, linewidth=0))
    ax.add_patch(Rectangle((0.07, 0.928), 0.085, 0.010, transform=ax.transAxes, color=TEAL, linewidth=0))
    ax.text(0.07, 0.880, title, fontsize=29, fontweight="bold", color=PAPER, ha="left", va="center")
    ax.text(0.07, 0.812, alt, fontsize=15, color="#C7D5DF", ha="left", va="center")

    ax.text(0.07, 0.695, "路徑特徵", fontsize=17, color=BLUE, fontweight="bold", ha="left", va="center")
    ax.text(0.55, 0.695, "樣本外比較", fontsize=17, color=TEAL, fontweight="bold", ha="left", va="center")
    ax.plot([0.515, 0.515], [0.29, 0.69], color=GRID, linewidth=1.2, transform=ax.transAxes)

    for x, metric in ((0.07, spy), (0.29, qqq)):
        rounded_box(ax, x, 0.30, 0.20, 0.33, facecolor=BLUE_SOFT, edgecolor="#D6E6ED")
        ax.text(x + 0.025, 0.565, metric.label, fontsize=14.5, color=MUTED, ha="left", va="center")
        ax.text(x + 0.025, 0.455, metric.rendered, fontsize=34, fontweight="bold", color=INK, ha="left", va="center")
        ax.text(x + 0.025, 0.350, "H 估計", fontsize=12.5, color=BLUE, ha="left", va="center")

    for x, metric in ((0.55, dm_uni), (0.75, dm_multi)):
        rounded_box(ax, x, 0.30, 0.18, 0.33, facecolor=TEAL_SOFT, edgecolor="#D2E7E3")
        ax.text(x + 0.022, 0.565, metric.label, fontsize=14, color=MUTED, ha="left", va="center")
        ax.text(x + 0.022, 0.455, metric.rendered, fontsize=34, fontweight="bold", color=INK, ha="left", va="center")
        ax.text(
            x + 0.022,
            0.350,
            wrap_zh(metric.note, 11),
            fontsize=11.5,
            color=TEAL,
            ha="left",
            va="center",
            linespacing=1.25,
        )

    rounded_box(ax, 0.07, 0.15, 0.86, 0.09, facecolor=SLATE_SOFT, edgecolor=SLATE_SOFT, radius=0.012)
    ax.text(
        0.50,
        0.195,
        "粗糙度描述路徑形狀；正的比較統計量代表近似模型損失更高。",
        fontsize=14,
        color=INK,
        ha="center",
        va="center",
    )

    add_footer(ax, experiment_id)
    save_panel(fig, require_string(panel, "name", "roughness panel"))


def render_reading_rule(panel: dict[str, Any], result: dict[str, Any], experiment_id: str) -> None:
    title = require_string(panel, "title", "reading-rule panel")
    alt = require_string(panel, "alt", "reading-rule panel")
    rules = [text_block_at(panel, index) for index in range(3)]
    seed = metric_at(panel, 3, result)

    fig, ax = make_canvas()
    add_header(ax, title, alt, AMBER)

    ax.plot([0.105, 0.105], [0.245, 0.685], color=GRID, linewidth=2.0, transform=ax.transAxes)
    centers = [0.655, 0.465, 0.275]
    for (heading, body), center in zip(rules, centers, strict=True):
        ax.add_patch(Circle((0.105, center), 0.014, transform=ax.transAxes, facecolor=PAPER, edgecolor=AMBER, linewidth=2.2))
        ax.text(0.15, center + 0.040, heading, fontsize=18, fontweight="bold", color=INK, ha="left", va="center")
        ax.text(
            0.15,
            center - 0.030,
            wrap_zh(body, 25),
            fontsize=14,
            color=MUTED,
            ha="left",
            va="center",
            linespacing=1.35,
        )

    rounded_box(ax, 0.72, 0.22, 0.21, 0.48, facecolor=AMBER_SOFT, edgecolor="#EBDCBF", radius=0.022)
    ax.add_patch(Rectangle((0.755, 0.625), 0.060, 0.008, transform=ax.transAxes, color=AMBER, linewidth=0))
    ax.text(0.755, 0.570, seed.label, fontsize=16, color=AMBER, fontweight="bold", ha="left", va="center")
    ax.text(0.755, 0.455, seed.rendered, fontsize=52, color=INK, fontweight="bold", ha="left", va="center")
    ax.text(
        0.755,
        0.330,
        wrap_zh("模型本身為確定性估計，保留重現設定。", 10),
        fontsize=13,
        color=MUTED,
        ha="left",
        va="center",
        linespacing=1.35,
    )

    add_footer(ax, experiment_id)
    save_panel(fig, require_string(panel, "name", "reading-rule panel"))


def main() -> None:
    result = load_json(RESULT_PATH)
    plan = load_json(PLAN_PATH)
    # These two evidence documents are required parts of the package. Reading
    # them here makes a missing or empty package component fail loudly.
    load_required_text(README_PATH)
    load_required_text(ARTICLE_PATH)

    experiment_id = require_string(result, "experiment_id", "result")
    if not experiment_id.startswith("K"):
        raise ValueError(f"Unexpected experiment_id: {experiment_id!r}")

    scoreboard = panel_by_name(plan, "1_scoreboard")
    roughness = panel_by_name(plan, "2_rough_not_better")
    reading_rule = panel_by_name(plan, "3_reading_rule")

    os.makedirs(OUT_DIR, exist_ok=True)
    render_scoreboard(scoreboard, result, experiment_id)
    render_rough_not_better(roughness, result, experiment_id)
    render_reading_rule(reading_rule, result, experiment_id)


if __name__ == "__main__":
    main()
