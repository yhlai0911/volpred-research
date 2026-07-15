#!/usr/bin/env python3
"""Render the K1410 general-audience lazypack as three data-bound PNGs."""

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
from matplotlib.patches import Circle, FancyBboxPatch


RESULT_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1410/k1410_results.json"
)
README_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1410/README.md"
)
PLAN_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_3c0ea15f/runs/lazypack-mile_3c0ea15f/plan.json"
)
ARTICLE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_3c0ea15f/runs/lazypack-mile_3c0ea15f/panels/"
    "mile_3c0ea15f_article.md"
)
OUT_DIR = (
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_3c0ea15f/runs/lazypack-mile_3c0ea15f/panels"
)

WIDTH_PX = 1600
HEIGHT_PX = 1000
DPI = 150
FIGSIZE = (WIDTH_PX / DPI, HEIGHT_PX / DPI)

INK = "#17212B"
MUTED = "#5D6975"
FAINT = "#89939D"
PAPER = "#FFFFFF"
WARM = "#F5F1E9"
NAVY = "#142B45"
BLUE = "#2F6B9A"
BLUE_SOFT = "#E8F0F7"
TEAL = "#19776F"
TEAL_SOFT = "#E4F1EF"
RED = "#B6463D"
RED_SOFT = "#F7E8E5"
AMBER = "#A66C20"
AMBER_SOFT = "#F7EEDC"
LINE = "#D9E0E6"

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_required_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError(f"Evidence file is empty: {path}")
    return text


def require_dict(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"Expected object at {context}, got {type(value).__name__}")
    return value


def require_string(mapping: dict[str, Any], key: str, context: str) -> str:
    if key not in mapping:
        raise KeyError(f"Missing {context}.{key}")
    value = mapping[key]
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"Expected non-empty string at {context}.{key}")
    return value


def resolve_result_path(data: Any, path: str) -> Any:
    """Resolve either RFC 6901-style pointers or plan dot paths."""
    if not isinstance(path, str) or not path:
        raise TypeError("Metric result path must be a non-empty string")

    if path.startswith("/"):
        parts = [part.replace("~1", "/").replace("~0", "~") for part in path[1:].split("/")]
    else:
        parts = path.split(".")

    current = data
    for part in parts:
        if isinstance(current, dict):
            if part not in current:
                raise KeyError(f"Missing result field: {path}")
            current = current[part]
        elif isinstance(current, list):
            try:
                index = int(part)
                current = current[index]
            except (ValueError, IndexError) as exc:
                raise KeyError(f"Invalid result list index in: {path}") from exc
        else:
            raise KeyError(f"Cannot descend through result path: {path}")
    return current


def finite_number(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"Expected numeric result at {path}, got {type(value).__name__}")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"Expected finite result at {path}, got {number}")
    return number


def format_metric(number: float, fmt: dict[str, Any], path: str) -> str:
    kind = fmt.get("kind")
    digits = fmt.get("digits")
    if not isinstance(digits, int) or digits < 0:
        raise TypeError(f"Invalid digits setting for {path}")
    if kind == "percent":
        return f"{number * 100:.{digits}f}%"
    if kind == "number":
        return f"{number:,.{digits}f}"
    raise ValueError(f"Unsupported metric format '{kind}' for {path}")


def metric_blocks(panel: dict[str, Any], results: dict[str, Any], count: int) -> list[dict[str, Any]]:
    blocks = panel.get("blocks")
    if not isinstance(blocks, list):
        raise TypeError(f"Expected blocks list for panel {panel.get('name')}")

    bound: list[dict[str, Any]] = []
    for index, raw_block in enumerate(blocks):
        block = require_dict(raw_block, f"panel.blocks[{index}]")
        if block.get("kind") != "metric":
            continue
        label = require_string(block, "label", f"panel.blocks[{index}]")
        value_spec = require_dict(block.get("value"), f"panel.blocks[{index}].value")
        if value_spec.get("source") != "result":
            raise ValueError(f"Metric '{label}' must use source=result")
        path = require_string(value_spec, "path", f"panel.blocks[{index}].value")
        fmt = require_dict(value_spec.get("format"), f"panel.blocks[{index}].value.format")
        number = finite_number(resolve_result_path(results, path), path)
        bound.append(
            {
                "label": label,
                "number": number,
                "display": format_metric(number, fmt, path),
                "path": path,
            }
        )

    if len(bound) != count:
        raise ValueError(
            f"Panel {panel.get('name')} requires {count} metrics, found {len(bound)}"
        )
    return bound


def first_text_block(panel: dict[str, Any]) -> dict[str, Any]:
    blocks = panel.get("blocks")
    if not isinstance(blocks, list):
        raise TypeError(f"Expected blocks list for panel {panel.get('name')}")
    for index, raw_block in enumerate(blocks):
        block = require_dict(raw_block, f"panel.blocks[{index}]")
        if block.get("kind") == "text":
            heading = require_string(block, "heading", f"panel.blocks[{index}]")
            body = block.get("body")
            if not isinstance(body, list) or not body or not all(
                isinstance(line, str) and line.strip() for line in body
            ):
                raise TypeError(f"Expected non-empty text body at panel.blocks[{index}]")
            return {"heading": heading, "body": body}
    raise KeyError(f"Missing text block for panel {panel.get('name')}")


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


def new_figure() -> tuple[plt.Figure, plt.Axes]:
    fig, ax = plt.subplots(figsize=FIGSIZE, dpi=DPI, facecolor=PAPER)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
    return fig, ax


def rounded_card(
    ax: plt.Axes,
    x: float,
    y: float,
    width: float,
    height: float,
    facecolor: str,
    edgecolor: str = LINE,
    radius: float = 0.022,
    linewidth: float = 1.2,
) -> FancyBboxPatch:
    patch = FancyBboxPatch(
        (x, y),
        width,
        height,
        boxstyle=f"round,pad=0.012,rounding_size={radius}",
        facecolor=facecolor,
        edgecolor=edgecolor,
        linewidth=linewidth,
    )
    ax.add_patch(patch)
    return patch


def draw_title(fig: plt.Figure, title: str, color: str = INK) -> None:
    fig.text(
        0.06,
        0.925,
        title,
        ha="left",
        va="center",
        fontsize=31,
        fontweight="bold",
        color=color,
    )


def draw_footer(fig: plt.Figure, source_label: str, color: str = MUTED) -> None:
    fig.text(
        0.06,
        0.035,
        f"資料來源：experiment {source_label}",
        ha="left",
        va="center",
        fontsize=12,
        color=color,
    )


def render_same_returns(
    panel: dict[str, Any], results: dict[str, Any], source_label: str, output_path: Path
) -> None:
    title = require_string(panel, "title", "panel")
    alt = require_string(panel, "alt", "panel")
    metrics = metric_blocks(panel, results, 3)
    narrative = first_text_block(panel)

    fig, ax = new_figure()
    draw_title(fig, title)
    fig.text(
        0.06,
        0.865,
        alt,
        ha="left",
        va="center",
        fontsize=17,
        color=MUTED,
    )
    ax.plot([0.06, 0.94], [0.83, 0.83], color=INK, linewidth=1.4)

    rounded_card(ax, 0.055, 0.145, 0.42, 0.625, WARM, edgecolor="#E6DED1")
    fig.text(
        0.085,
        0.725,
        narrative["heading"],
        ha="left",
        va="center",
        fontsize=22,
        fontweight="bold",
        color=INK,
    )
    fig.text(
        0.085,
        0.655,
        wrap_zh("".join(narrative["body"]), 17),
        ha="left",
        va="top",
        fontsize=17,
        linespacing=1.55,
        color=MUTED,
    )
    ax.add_patch(Circle((0.265, 0.475), 0.07, facecolor=PAPER, edgecolor=TEAL, linewidth=2.4))
    fig.text(
        0.265,
        0.475,
        "×",
        ha="center",
        va="center",
        fontsize=43,
        fontweight="bold",
        color=TEAL,
    )
    fig.text(
        0.265,
        0.345,
        metrics[0]["label"],
        ha="center",
        va="center",
        fontsize=15,
        color=MUTED,
    )
    fig.text(
        0.265,
        0.265,
        metrics[0]["display"],
        ha="center",
        va="center",
        fontsize=38,
        fontweight="bold",
        color=TEAL,
    )

    rounded_card(ax, 0.51, 0.145, 0.435, 0.625, PAPER, edgecolor=LINE)
    fig.text(
        0.545,
        0.725,
        "加入固定提款",
        ha="left",
        va="center",
        fontsize=22,
        fontweight="bold",
        color=INK,
    )
    fig.text(
        0.545,
        0.672,
        "同一籃報酬，順序不同便走向不同終值",
        ha="left",
        va="center",
        fontsize=15,
        color=MUTED,
    )
    ax.plot([0.62, 0.835], [0.58, 0.58], color=BLUE, linewidth=3.0, solid_capstyle="round")
    ax.add_patch(Circle((0.62, 0.58), 0.018, facecolor=RED, edgecolor=PAPER, linewidth=2))
    ax.add_patch(Circle((0.835, 0.58), 0.018, facecolor=TEAL, edgecolor=PAPER, linewidth=2))
    ax.plot([0.7275, 0.7275], [0.58, 0.63], color=BLUE, linewidth=2.0)

    rounded_card(ax, 0.545, 0.245, 0.17, 0.235, RED_SOFT, edgecolor="#ECCEC9")
    rounded_card(ax, 0.74, 0.245, 0.17, 0.235, TEAL_SOFT, edgecolor="#C9E2DE")
    for x, metric, value_color in (
        (0.63, metrics[2], RED),
        (0.825, metrics[1], TEAL),
    ):
        fig.text(
            x,
            0.425,
            wrap_zh(metric["label"], 10),
            ha="center",
            va="center",
            fontsize=14,
            linespacing=1.25,
            color=MUTED,
        )
        fig.text(
            x,
            0.325,
            metric["display"],
            ha="center",
            va="center",
            fontsize=29,
            fontweight="bold",
            color=value_color,
        )

    draw_footer(fig, source_label)
    fig.savefig(
        output_path,
        dpi=DPI,
        facecolor=PAPER,
        metadata={"Title": title, "Description": alt},
    )
    plt.close(fig)


def render_crash_timing(
    panel: dict[str, Any], results: dict[str, Any], source_label: str, output_path: Path
) -> None:
    title = require_string(panel, "title", "panel")
    alt = require_string(panel, "alt", "panel")
    metrics = metric_blocks(panel, results, 4)

    fig, ax = new_figure()
    draw_title(fig, title)
    fig.text(
        0.06,
        0.865,
        alt,
        ha="left",
        va="center",
        fontsize=17,
        color=MUTED,
    )

    positions = (
        (0.06, 0.50),
        (0.515, 0.50),
        (0.06, 0.17),
        (0.515, 0.17),
    )
    fills = (RED_SOFT, BLUE_SOFT, RED_SOFT, BLUE_SOFT)
    accents = (RED, BLUE, RED, BLUE)
    edges = ("#EDCEC9", "#CDDFEC", "#EDCEC9", "#CDDFEC")

    for metric, (x, y), fill, accent, edge in zip(metrics, positions, fills, accents, edges):
        rounded_card(ax, x, y, 0.425, 0.265, fill, edgecolor=edge)
        ax.add_patch(Circle((x + 0.055, y + 0.205), 0.021, facecolor=accent, edgecolor="none"))
        fig.text(
            x + 0.09,
            y + 0.205,
            metric["label"],
            ha="left",
            va="center",
            fontsize=17,
            fontweight="bold",
            color=INK,
        )
        fig.text(
            x + 0.035,
            y + 0.105,
            metric["display"],
            ha="left",
            va="center",
            fontsize=41,
            fontweight="bold",
            color=accent,
        )
        fig.text(
            x + 0.305,
            y + 0.075,
            "資產耗盡率",
            ha="center",
            va="center",
            fontsize=13,
            color=MUTED,
        )

    draw_footer(fig, source_label)
    fig.savefig(
        output_path,
        dpi=DPI,
        facecolor=PAPER,
        metadata={"Title": title, "Description": alt},
    )
    plt.close(fig)


def render_withdrawal_rule(
    panel: dict[str, Any], results: dict[str, Any], source_label: str, output_path: Path
) -> None:
    title = require_string(panel, "title", "panel")
    alt = require_string(panel, "alt", "panel")
    metrics = metric_blocks(panel, results, 4)
    caveat = first_text_block(panel)

    fig, ax = new_figure()
    ax.add_patch(FancyBboxPatch((0, 0.77), 1, 0.23, boxstyle="square,pad=0", facecolor=NAVY, edgecolor=NAVY))
    draw_title(fig, title, color=PAPER)
    fig.text(
        0.06,
        0.835,
        alt,
        ha="left",
        va="center",
        fontsize=17,
        color="#D8E3ED",
    )

    positions = (
        (0.06, 0.49, 0.415, 0.205),
        (0.525, 0.49, 0.415, 0.205),
        (0.06, 0.245, 0.415, 0.19),
        (0.525, 0.245, 0.415, 0.19),
    )
    accents = (BLUE, TEAL, BLUE, TEAL)
    fills = (BLUE_SOFT, TEAL_SOFT, BLUE_SOFT, TEAL_SOFT)

    for metric, (x, y, width, height), accent, fill in zip(metrics, positions, accents, fills):
        rounded_card(ax, x, y, width, height, PAPER, edgecolor=LINE)
        fig.text(
            x + 0.025,
            y + height - 0.048,
            metric["label"],
            ha="left",
            va="center",
            fontsize=16,
            fontweight="bold",
            color=INK,
        )
        fig.text(
            x + 0.025,
            y + height * 0.43,
            metric["display"],
            ha="left",
            va="center",
            fontsize=34,
            fontweight="bold",
            color=accent,
        )
        bar_x = x + 0.205
        bar_y = y + 0.052
        bar_width = width - 0.235
        ax.plot([bar_x, bar_x + bar_width], [bar_y, bar_y], color=fill, linewidth=12, solid_capstyle="round")
        ax.plot(
            [bar_x, bar_x + bar_width * metric["number"]],
            [bar_y, bar_y],
            color=accent,
            linewidth=12,
            solid_capstyle="round",
        )

    rounded_card(ax, 0.06, 0.085, 0.88, 0.105, AMBER_SOFT, edgecolor="#E8D5AE", radius=0.015)
    fig.text(
        0.085,
        0.15,
        caveat["heading"],
        ha="left",
        va="center",
        fontsize=15,
        fontweight="bold",
        color=AMBER,
    )
    fig.text(
        0.175,
        0.137,
        wrap_zh("".join(caveat["body"]), 43),
        ha="left",
        va="center",
        fontsize=14,
        linespacing=1.35,
        color=INK,
    )

    draw_footer(fig, source_label)
    fig.savefig(
        output_path,
        dpi=DPI,
        facecolor=PAPER,
        metadata={"Title": title, "Description": alt},
    )
    plt.close(fig)


def panel_map(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    panels = plan.get("panels")
    if not isinstance(panels, list):
        raise TypeError("plan.json must contain a panels list")
    mapped: dict[str, dict[str, Any]] = {}
    for index, raw_panel in enumerate(panels):
        panel = require_dict(raw_panel, f"plan.panels[{index}]")
        name = require_string(panel, "name", f"plan.panels[{index}]")
        if name in mapped:
            raise ValueError(f"Duplicate panel name: {name}")
        mapped[name] = panel
    return mapped


def main() -> None:
    results = require_dict(load_json(RESULT_PATH), str(RESULT_PATH))
    plan = require_dict(load_json(PLAN_PATH), str(PLAN_PATH))

    # Read every supplied evidence artifact. The two prose files are required
    # context, while all displayed statistics remain bound to results.json.
    load_required_text(README_PATH)
    load_required_text(ARTICLE_PATH)

    experiment_id = require_string(results, "experiment_id", "results")
    source_label = experiment_id.upper()
    panels = panel_map(plan)
    required_names = ("1_same_returns", "2_crash_timing", "3_withdrawal_rule")
    for name in required_names:
        if name not in panels:
            raise KeyError(f"Missing required panel in plan.json: {name}")

    out_dir = OUT_DIR
    os.makedirs(out_dir, exist_ok=True)

    render_same_returns(
        panels["1_same_returns"],
        results,
        source_label,
        Path(out_dir) / "1_same_returns.png",
    )
    render_crash_timing(
        panels["2_crash_timing"],
        results,
        source_label,
        Path(out_dir) / "2_crash_timing.png",
    )
    render_withdrawal_rule(
        panels["3_withdrawal_rule"],
        results,
        source_label,
        Path(out_dir) / "3_withdrawal_rule.png",
    )


if __name__ == "__main__":
    main()
