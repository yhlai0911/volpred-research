#!/usr/bin/env python3
"""Render the K1410 general-audience lazypack as three data-bound PNGs."""

from __future__ import annotations

import json
import math
import os
import re
import textwrap
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyBboxPatch, Rectangle


RESULTS_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1410/k1410_results.json"
)
README_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1410/README.md"
)
PLAN_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_3c0ea15f/runs/lazypack-mile_3c0ea15f-r2/plan.json"
)
ARTICLE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_3c0ea15f/runs/lazypack-mile_3c0ea15f-r2/panels/"
    "mile_3c0ea15f_article.md"
)
out_dir = (
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_3c0ea15f/runs/lazypack-mile_3c0ea15f-r2/panels"
)

WIDTH_PX = 1600
HEIGHT_PX = 1000
DPI = 150

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False

INK = "#142033"
MUTED = "#5E6978"
FAINT = "#8994A3"
PAPER = "#F7F5F0"
WHITE = "#FFFFFF"
NAVY = "#102A43"
BLUE = "#246BCE"
BLUE_SOFT = "#E8F0FC"
TEAL = "#087F8C"
TEAL_SOFT = "#E2F3F3"
RED = "#C3423F"
RED_SOFT = "#F8E8E6"
GREEN = "#18815B"
GREEN_SOFT = "#E1F1EA"
GOLD = "#B7791F"
GOLD_SOFT = "#F8EEDB"
LINE = "#D8DEE8"


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError(f"Evidence file is empty: {path}")
    return text


def resolve_path(data: Any, path: str) -> Any:
    """Resolve either an RFC 6901-style pointer or a dot-separated path."""
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
                index = int(part)
                current = current[index]
            except (ValueError, IndexError) as exc:
                raise KeyError(f"Missing evidence field: {path}") from exc
        else:
            raise KeyError(f"Evidence path traverses a scalar: {path}")
    return current


def require_number(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"Expected a numeric value at {path}, got {type(value).__name__}")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"Expected a finite value at {path}, got {number}")
    return number


def format_value(value: Any, spec: dict[str, Any], path: str) -> str:
    number = require_number(value, path)
    kind = spec["kind"]
    digits = int(spec["digits"])
    if kind == "percent":
        return f"{number * 100:.{digits}f}%"
    if kind == "number":
        return f"{number:.{digits}f}"
    raise ValueError(f"Unsupported format kind {kind!r} at {path}")


def get_panels(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    panels = plan["panels"]
    if not isinstance(panels, list):
        raise TypeError("plan.panels must be a list")
    by_name = {panel["name"]: panel for panel in panels}
    required = {"1_same_returns", "2_crash_timing", "3_withdrawal_rule"}
    missing = required.difference(by_name)
    if missing:
        raise KeyError(f"Missing required panels: {sorted(missing)}")
    return by_name


def bind_metrics(panel: dict[str, Any], results: dict[str, Any]) -> list[dict[str, Any]]:
    bound: list[dict[str, Any]] = []
    for block in panel["blocks"]:
        if block["kind"] != "metric":
            continue
        value_spec = block["value"]
        if value_spec["source"] != "result":
            raise ValueError(f"Unsupported source in panel {panel['name']}: {value_spec['source']}")
        path = value_spec["path"]
        raw = resolve_path(results, path)
        numeric = require_number(raw, path)
        bound.append(
            {
                "label": block["label"],
                "raw": numeric,
                "rendered": format_value(numeric, value_spec["format"], path),
                "path": path,
            }
        )
    if not bound:
        raise ValueError(f"Panel {panel['name']} has no metrics")
    return bound


def get_text_block(panel: dict[str, Any]) -> dict[str, Any]:
    blocks = [block for block in panel["blocks"] if block["kind"] == "text"]
    if len(blocks) != 1:
        raise ValueError(f"Panel {panel['name']} must contain exactly one text block")
    if not blocks[0]["body"]:
        raise ValueError(f"Panel {panel['name']} has an empty text body")
    return blocks[0]


def new_canvas(background: str = WHITE):
    fig = plt.figure(
        figsize=(WIDTH_PX / DPI, HEIGHT_PX / DPI),
        dpi=DPI,
        facecolor=background,
    )
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    return fig, ax


def rounded_card(ax, x: float, y: float, w: float, h: float, face: str, edge: str = "none"):
    patch = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle="round,pad=0.008,rounding_size=0.018",
        linewidth=1.2 if edge != "none" else 0,
        edgecolor=edge,
        facecolor=face,
        transform=ax.transAxes,
        clip_on=False,
    )
    ax.add_patch(patch)
    return patch


def add_source(fig, experiment_id: str, color: str = MUTED) -> None:
    fig.text(
        0.05,
        0.047,
        f"資料來源：experiment {experiment_id.upper()}",
        ha="left",
        va="center",
        fontsize=12,
        color=color,
    )


def save_panel(fig, name: str) -> None:
    path = os.path.join(out_dir, f"{name}.png")
    fig.savefig(path, dpi=DPI, facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close(fig)


def render_same_returns(panel: dict[str, Any], results: dict[str, Any], experiment_id: str) -> None:
    metrics = bind_metrics(panel, results)
    if len(metrics) != 3:
        raise ValueError("1_same_returns must contain exactly three metrics")
    text_block = get_text_block(panel)

    fig, ax = new_canvas(PAPER)
    ax.add_patch(Rectangle((0.05, 0.835), 0.085, 0.008, color=GOLD, transform=ax.transAxes))
    fig.text(0.05, 0.914, panel["title"], ha="left", va="center", fontsize=36, color=INK, weight="bold")

    rounded_card(ax, 0.05, 0.19, 0.39, 0.57, WHITE, LINE)
    fig.text(0.08, 0.692, text_block["heading"], ha="left", va="center", fontsize=21, color=TEAL, weight="bold")
    wrapped_body = "\n".join(textwrap.wrap(text_block["body"][0], width=14))
    fig.text(
        0.08,
        0.605,
        wrapped_body,
        ha="left",
        va="top",
        fontsize=17,
        color=MUTED,
        linespacing=1.55,
    )
    fig.text(0.08, 0.352, metrics[0]["rendered"], ha="left", va="center", fontsize=51, color=INK, weight="bold")
    fig.text(0.08, 0.275, metrics[0]["label"], ha="left", va="center", fontsize=15, color=MUTED)

    ax.plot([0.44, 0.495], [0.475, 0.475], color=GOLD, linewidth=3, transform=ax.transAxes)
    ax.plot([0.495, 0.495], [0.355, 0.60], color=GOLD, linewidth=3, transform=ax.transAxes)
    ax.plot([0.495, 0.54], [0.60, 0.60], color=GOLD, linewidth=3, transform=ax.transAxes)
    ax.plot([0.495, 0.54], [0.355, 0.355], color=GOLD, linewidth=3, transform=ax.transAxes)
    ax.add_patch(Circle((0.495, 0.475), 0.009, facecolor=GOLD, edgecolor="none", transform=ax.transAxes))

    rounded_card(ax, 0.54, 0.49, 0.41, 0.27, GREEN_SOFT)
    fig.text(0.58, 0.688, metrics[1]["label"], ha="left", va="center", fontsize=17, color=GREEN, weight="bold")
    fig.text(0.58, 0.578, metrics[1]["rendered"], ha="left", va="center", fontsize=49, color=INK, weight="bold")

    rounded_card(ax, 0.54, 0.19, 0.41, 0.23, RED_SOFT)
    fig.text(0.58, 0.355, metrics[2]["label"], ha="left", va="center", fontsize=17, color=RED, weight="bold")
    fig.text(0.58, 0.265, metrics[2]["rendered"], ha="left", va="center", fontsize=47, color=INK, weight="bold")

    add_source(fig, experiment_id)
    save_panel(fig, panel["name"])


def draw_timing_icon(ax, center: tuple[float, float], early: bool, color: str) -> None:
    x, y = center
    ax.add_patch(Circle((x, y), 0.031, facecolor="none", edgecolor=color, linewidth=2.2, transform=ax.transAxes))
    ax.plot([x, x], [y, y + 0.019], color=color, linewidth=2.2, solid_capstyle="round", transform=ax.transAxes)
    direction = -0.018 if early else 0.018
    ax.plot([x, x + direction], [y, y - 0.012], color=color, linewidth=2.2, solid_capstyle="round", transform=ax.transAxes)


def render_crash_timing(panel: dict[str, Any], results: dict[str, Any], experiment_id: str) -> None:
    metrics = bind_metrics(panel, results)
    if len(metrics) != 4:
        raise ValueError("2_crash_timing must contain exactly four metrics")

    fig, ax = new_canvas(PAPER)
    ax.add_patch(Rectangle((0.05, 0.835), 0.085, 0.008, color=RED, transform=ax.transAxes))
    fig.text(0.05, 0.914, panel["title"], ha="left", va="center", fontsize=36, color=INK, weight="bold")

    cards = [
        (0.05, 0.49, 0.425, 0.27, RED_SOFT, RED, True),
        (0.525, 0.49, 0.425, 0.27, BLUE_SOFT, BLUE, False),
        (0.05, 0.18, 0.425, 0.27, RED_SOFT, RED, True),
        (0.525, 0.18, 0.425, 0.27, TEAL_SOFT, TEAL, False),
    ]
    for metric, (x, y, w, h, face, accent, early) in zip(metrics, cards, strict=True):
        rounded_card(ax, x, y, w, h, face)
        draw_timing_icon(ax, (x + 0.055, y + h - 0.071), early=early, color=accent)
        fig.text(x + 0.105, y + h - 0.071, metric["label"], ha="left", va="center", fontsize=17, color=accent, weight="bold")
        fig.text(x + 0.055, y + 0.087, metric["rendered"], ha="left", va="center", fontsize=50, color=INK, weight="bold")

    add_source(fig, experiment_id)
    save_panel(fig, panel["name"])


def draw_strategy_card(ax, fig, x: float, market: str, first: dict[str, Any], second: dict[str, Any]) -> None:
    y, w, h = 0.385, 0.435, 0.315
    rounded_card(ax, x, y, w, h, WHITE, LINE)
    fig.text(x + 0.032, y + h - 0.052, market, ha="left", va="center", fontsize=18, color=NAVY, weight="bold")

    rows = [
        (first, y + 0.185, MUTED, BLUE),
        (second, y + 0.075, GREEN, GREEN),
    ]
    for metric, row_y, label_color, bar_color in rows:
        fig.text(x + 0.032, row_y + 0.042, metric["label"], ha="left", va="center", fontsize=14, color=label_color, weight="bold")
        fig.text(x + w - 0.032, row_y + 0.042, metric["rendered"], ha="right", va="center", fontsize=28, color=INK, weight="bold")
        ax.plot(
            [x + 0.032, x + w - 0.032],
            [row_y, row_y],
            color="#E7EBF0",
            linewidth=8,
            solid_capstyle="round",
            transform=ax.transAxes,
        )
        usable = w - 0.064
        ax.plot(
            [x + 0.032, x + 0.032 + usable * metric["raw"]],
            [row_y, row_y],
            color=bar_color,
            linewidth=8,
            solid_capstyle="round",
            transform=ax.transAxes,
        )


def render_withdrawal_rule(panel: dict[str, Any], results: dict[str, Any], experiment_id: str) -> None:
    metrics = bind_metrics(panel, results)
    if len(metrics) != 4:
        raise ValueError("3_withdrawal_rule must contain exactly four metrics")
    text_block = get_text_block(panel)

    fig, ax = new_canvas("#F4F6F8")
    ax.add_patch(Rectangle((0, 0.76), 1, 0.24, color=NAVY, transform=ax.transAxes))
    fig.text(0.05, 0.900, panel["title"], ha="left", va="center", fontsize=35, color=WHITE, weight="bold")
    fig.text(0.05, 0.820, "固定提款與動態提款的未耗盡比例", ha="left", va="center", fontsize=17, color="#C8D8E8")

    draw_strategy_card(ax, fig, 0.05, "美股", metrics[0], metrics[1])
    draw_strategy_card(ax, fig, 0.515, "台股", metrics[2], metrics[3])

    rounded_card(ax, 0.05, 0.13, 0.90, 0.195, GOLD_SOFT)
    fig.text(0.08, 0.273, text_block["heading"], ha="left", va="center", fontsize=18, color=GOLD, weight="bold")
    caveat = "\n".join(textwrap.wrap(text_block["body"][0], width=41))
    fig.text(0.08, 0.210, caveat, ha="left", va="top", fontsize=16, color=INK, linespacing=1.45)

    add_source(fig, experiment_id)
    save_panel(fig, panel["name"])


def main() -> None:
    results = load_json(RESULTS_PATH)
    plan = load_json(PLAN_PATH)
    load_text(README_PATH)
    load_text(ARTICLE_PATH)

    experiment_id = results["experiment_id"]
    if not isinstance(experiment_id, str) or re.fullmatch(r"k\d+", experiment_id, re.IGNORECASE) is None:
        raise ValueError(f"Invalid experiment_id in results: {experiment_id!r}")
    panels = get_panels(plan)
    os.makedirs(out_dir, exist_ok=True)
    render_same_returns(panels["1_same_returns"], results, experiment_id)
    render_crash_timing(panels["2_crash_timing"], results, experiment_id)
    render_withdrawal_rule(panels["3_withdrawal_rule"], results, experiment_id)


if __name__ == "__main__":
    main()
