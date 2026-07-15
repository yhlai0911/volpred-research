#!/usr/bin/env python3
"""Render the K1575 general-audience lazypack as three data-bound PNGs.

Every displayed statistic is resolved from k1575_results.json through the
binding paths in the strict plan. Missing inputs, fields, or panel blocks raise
immediately so the caller receives a useful traceback instead of a plausible
but incorrect graphic.
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


RESULTS_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1575/k1575_results.json"
)
README_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1575/README.md"
)
PLAN_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_009a85c8/runs/lazypack-mile_009a85c8/plan.json"
)
ARTICLE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_009a85c8/runs/lazypack-mile_009a85c8/panels/"
    "mile_009a85c8_article.md"
)
OUT_DIR = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_009a85c8/runs/lazypack-mile_009a85c8/panels"
)

WIDTH_PX = 1600
HEIGHT_PX = 1000
DPI = 150

INK = "#16202A"
MUTED = "#5F6975"
FAINT = "#7F8994"
PAPER = "#FFFFFF"
SURFACE = "#F5F7F9"
GRID = "#DDE3E8"
NAVY = "#17324D"
BLUE = "#2D638B"
BLUE_SOFT = "#E8F0F6"
TEAL = "#16756F"
TEAL_SOFT = "#E4F2F0"
AMBER = "#B8741A"
AMBER_SOFT = "#F7EEDC"
RED = "#B94343"
RED_SOFT = "#F8E8E8"

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_inputs() -> tuple[dict[str, Any], dict[str, Any]]:
    """Load all four absolute-path evidence-package files."""
    results = load_json(RESULTS_PATH)
    plan = load_json(PLAN_PATH)
    readme = README_PATH.read_text(encoding="utf-8")
    article = ARTICLE_PATH.read_text(encoding="utf-8")
    if not isinstance(results, dict):
        raise TypeError("results JSON must be an object")
    if not isinstance(plan, dict):
        raise TypeError("plan JSON must be an object")
    if not readme.strip():
        raise ValueError(f"Empty evidence file: {README_PATH}")
    if not article.strip():
        raise ValueError(f"Empty evidence file: {ARTICLE_PATH}")
    return results, plan


def require(mapping: dict[str, Any], key: str, context: str) -> Any:
    if key not in mapping:
        raise KeyError(f"Missing {context}.{key}")
    return mapping[key]


def resolve_path(data: Any, path: str) -> Any:
    """Resolve either RFC 6901-style pointers or strict dotted paths."""
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
                raise KeyError(f"Missing evidence field at {path!r}: {part!r}")
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


def numeric(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"Expected numeric evidence at {path!r}, got {type(value).__name__}")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"Non-finite evidence at {path!r}: {value!r}")
    return number


def format_value(raw: Any, spec: dict[str, Any], path: str) -> str:
    kind = require(spec, "kind", f"format for {path}")
    number = numeric(raw, path)
    suffix = str(spec.get("suffix", ""))
    if kind == "integer":
        if not number.is_integer():
            raise ValueError(f"Expected integer evidence at {path!r}, got {raw!r}")
        rendered = f"{int(number)}"
    elif kind == "number":
        digits = require(spec, "digits", f"format for {path}")
        if isinstance(digits, bool) or not isinstance(digits, int) or digits < 0:
            raise ValueError(f"Invalid digits for {path!r}: {digits!r}")
        sign = "+" if spec.get("show_plus", False) else ""
        rendered = f"{number:{sign}.{digits}f}"
    else:
        raise ValueError(f"Unsupported number format {kind!r} for {path!r}")
    return rendered + suffix


def get_panel(plan: dict[str, Any], name: str) -> dict[str, Any]:
    panels = require(plan, "panels", "plan")
    if not isinstance(panels, list):
        raise TypeError("plan.panels must be a list")
    matches = [panel for panel in panels if isinstance(panel, dict) and panel.get("name") == name]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one panel named {name!r}, found {len(matches)}")
    panel = matches[0]
    for key in ("title", "alt", "sources", "blocks"):
        require(panel, key, f"panel {name}")
    return panel


def source_label(plan: dict[str, Any], panel: dict[str, Any]) -> str:
    sources = require(panel, "sources", f"panel {panel.get('name')}")
    if sources != ["result"]:
        raise ValueError(f"Panel sources must be exactly ['result'], got {sources!r}")
    evidence = require(plan, "evidence", "plan")
    result_spec = require(evidence, "result", "plan.evidence")
    label = require(result_spec, "label", "plan.evidence.result")
    if not isinstance(label, str) or not label:
        raise ValueError("plan.evidence.result.label must be a non-empty string")
    return label


def bind_blocks(panel: dict[str, Any], results: dict[str, Any]) -> list[dict[str, Any]]:
    bound: list[dict[str, Any]] = []
    blocks = require(panel, "blocks", f"panel {panel.get('name')}")
    if not isinstance(blocks, list):
        raise TypeError(f"panel {panel.get('name')}.blocks must be a list")
    for index, block in enumerate(blocks):
        if not isinstance(block, dict):
            raise TypeError(f"Panel block {index} must be an object")
        kind = require(block, "kind", f"panel block {index}")
        item = dict(block)
        if kind == "metric":
            require(block, "label", f"metric block {index}")
            value_spec = require(block, "value", f"metric block {index}")
            if not isinstance(value_spec, dict):
                raise TypeError(f"metric block {index}.value must be an object")
            if require(value_spec, "source", f"metric block {index}.value") != "result":
                raise ValueError(f"metric block {index} must bind to result evidence")
            path = require(value_spec, "path", f"metric block {index}.value")
            fmt = require(value_spec, "format", f"metric block {index}.value")
            if not isinstance(fmt, dict):
                raise TypeError(f"metric block {index}.value.format must be an object")
            raw = resolve_path(results, path)
            item["raw"] = numeric(raw, path)
            item["rendered"] = format_value(raw, fmt, path)
            item["evidence_path"] = path
        elif kind == "text":
            require(block, "heading", f"text block {index}")
            body = require(block, "body", f"text block {index}")
            if not isinstance(body, list) or not body or not all(isinstance(x, str) for x in body):
                raise TypeError(f"text block {index}.body must be a non-empty string list")
        else:
            raise ValueError(f"Unsupported panel block kind: {kind!r}")
        bound.append(item)
    return bound


def metric_by_label(blocks: list[dict[str, Any]], label: str) -> dict[str, Any]:
    matches = [block for block in blocks if block.get("kind") == "metric" and block.get("label") == label]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one metric labelled {label!r}, found {len(matches)}")
    return matches[0]


def text_block(blocks: list[dict[str, Any]], heading: str) -> dict[str, Any]:
    matches = [block for block in blocks if block.get("kind") == "text" and block.get("heading") == heading]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one text block headed {heading!r}, found {len(matches)}")
    return matches[0]


def new_figure(background: str = PAPER) -> plt.Figure:
    fig = plt.figure(
        figsize=(WIDTH_PX / DPI, HEIGHT_PX / DPI),
        dpi=DPI,
        facecolor=background,
    )
    fig.subplots_adjust(0, 0, 1, 1)
    return fig


def rect(
    fig: plt.Figure,
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    color: str,
    radius: float = 0.018,
    edge: str | None = None,
    linewidth: float = 1.0,
) -> None:
    patch = FancyBboxPatch(
        (x, y),
        width,
        height,
        boxstyle=f"round,pad=0.004,rounding_size={radius}",
        transform=fig.transFigure,
        facecolor=color,
        edgecolor=edge or color,
        linewidth=linewidth,
        clip_on=False,
    )
    fig.patches.append(patch)


def label_text(fig: plt.Figure, x: float, y: float, text: str, **kwargs: Any) -> None:
    defaults: dict[str, Any] = {
        "ha": "left",
        "va": "top",
        "color": INK,
        "fontfamily": "Heiti TC",
    }
    defaults.update(kwargs)
    fig.text(x, y, text, transform=fig.transFigure, **defaults)


def wrapped(text: str, width: int) -> str:
    return textwrap.fill(
        text,
        width=width,
        break_long_words=True,
        break_on_hyphens=False,
        replace_whitespace=False,
    )


def draw_footer(fig: plt.Figure, label: str, color: str = FAINT) -> None:
    fig.patches.append(
        Rectangle(
            (0.06, 0.077),
            0.88,
            0.0015,
            transform=fig.transFigure,
            facecolor=GRID,
            edgecolor="none",
        )
    )
    label_text(fig, 0.06, 0.055, f"資料來源：{label}", fontsize=10.5, color=color, va="center")


def save_panel(fig: plt.Figure, panel: dict[str, Any]) -> None:
    name = require(panel, "name", "panel")
    title = require(panel, "title", f"panel {name}")
    alt = require(panel, "alt", f"panel {name}")
    path = OUT_DIR / f"{name}.png"
    fig.savefig(
        path,
        dpi=DPI,
        facecolor=fig.get_facecolor(),
        edgecolor="none",
        bbox_inches=None,
        pad_inches=0,
        metadata={"Title": title, "Description": alt},
    )
    plt.close(fig)


def render_scoreboard(panel: dict[str, Any], blocks: list[dict[str, Any]], source: str) -> None:
    fig = new_figure()
    label_text(fig, 0.06, 0.93, wrapped(panel["title"], 25), fontsize=29, weight="bold")
    fig.patches.append(
        Rectangle((0.06, 0.842), 0.09, 0.008, transform=fig.transFigure, facecolor=TEAL, edgecolor="none")
    )

    labels = [
        "公開公告",
        "ETF 與大盤對照",
        "主要波動檢查",
        "嚴格門檻後過關",
        "平均比值",
        "中位數比值",
    ]
    metrics = [metric_by_label(blocks, label) for label in labels]
    positions = [
        (0.06, 0.53, 0.27, 0.25),
        (0.365, 0.53, 0.27, 0.25),
        (0.67, 0.53, 0.27, 0.25),
        (0.06, 0.16, 0.27, 0.27),
        (0.365, 0.16, 0.27, 0.27),
        (0.67, 0.16, 0.27, 0.27),
    ]
    fills = [BLUE_SOFT, TEAL_SOFT, SURFACE, RED_SOFT, AMBER_SOFT, SURFACE]
    accents = [BLUE, TEAL, NAVY, RED, AMBER, NAVY]

    for metric, (x, y, width, height), fill, accent in zip(metrics, positions, fills, accents):
        rect(fig, x, y, width, height, color=fill, edge=GRID, linewidth=0.9)
        label_text(fig, x + 0.022, y + height - 0.035, metric["label"], fontsize=15, color=accent, weight="bold")
        label_text(fig, x + 0.022, y + height - 0.105, metric["rendered"], fontsize=36, weight="bold")
        note = metric.get("note")
        if note:
            label_text(fig, x + 0.022, y + 0.035, wrapped(note, 16), fontsize=11.5, color=MUTED, va="bottom")

    draw_footer(fig, source)
    save_panel(fig, panel)


def render_two_jumps(panel: dict[str, Any], blocks: list[dict[str, Any]], source: str) -> None:
    fig = new_figure()
    fig.patches.append(
        Rectangle((0, 0.81), 1, 0.19, transform=fig.transFigure, facecolor=NAVY, edgecolor="none")
    )
    label_text(fig, 0.06, 0.925, wrapped(panel["title"], 28), fontsize=27, color=PAPER, weight="bold")
    label_text(fig, 0.06, 0.848, "同一事件週的五日最大絕對報酬檢查", fontsize=13.5, color="#CAD7E2")

    test_count = metric_by_label(blocks, "五日最大跳動檢查")
    pass_count = metric_by_label(blocks, "嚴格門檻後過關")
    lit = metric_by_label(blocks, "LIT 最大跳動比值")
    remx = metric_by_label(blocks, "REMX 最大跳動比值")
    reading = text_block(blocks, "讀法")

    for metric, x, accent in ((test_count, 0.06, BLUE), (pass_count, 0.515, RED)):
        rect(fig, x, 0.665, 0.425, 0.105, color=SURFACE, edge=GRID)
        label_text(fig, x + 0.022, 0.742, metric["label"], fontsize=13.5, color=accent, weight="bold")
        label_text(fig, x + 0.403, 0.718, metric["rendered"], fontsize=29, ha="right", va="center", weight="bold")

    for metric, x, fill, accent in (
        (lit, 0.06, BLUE_SOFT, BLUE),
        (remx, 0.515, TEAL_SOFT, TEAL),
    ):
        rect(fig, x, 0.39, 0.425, 0.225, color=fill, edge=GRID)
        label_text(fig, x + 0.025, 0.575, metric["label"], fontsize=15.5, color=accent, weight="bold")
        label_text(fig, x + 0.025, 0.505, metric["rendered"], fontsize=38, weight="bold")
        label_text(fig, x + 0.025, 0.425, wrapped(metric["note"], 19), fontsize=11.5, color=MUTED)

    rect(fig, 0.06, 0.12, 0.88, 0.22, color=PAPER, edge=GRID, linewidth=1.0)
    label_text(fig, 0.085, 0.305, reading["heading"], fontsize=15, color=NAVY, weight="bold")
    for index, sentence in enumerate(reading["body"]):
        y = 0.255 - index * 0.075
        label_text(fig, 0.087, y, "•", fontsize=13, color=TEAL, weight="bold")
        label_text(fig, 0.11, y, wrapped(sentence, 48), fontsize=12, color=MUTED)

    draw_footer(fig, source)
    save_panel(fig, panel)


def render_benchmark(panel: dict[str, Any], blocks: list[dict[str, Any]], source: str) -> None:
    fig = new_figure()
    label_text(fig, 0.06, 0.93, panel["title"], fontsize=31, weight="bold")
    label_text(fig, 0.06, 0.855, "同一事件週，直接礦業 ETF 與大盤對照", fontsize=14, color=MUTED)

    direct = metric_by_label(blocks, "直接礦業五日平均比值")
    benchmark = metric_by_label(blocks, "大盤五日平均比值")
    rv_delta = metric_by_label(blocks, "直接礦業減大盤")
    jump_delta = metric_by_label(blocks, "最大跳動差值")
    boundary = text_block(blocks, "使用邊界")

    rect(fig, 0.06, 0.40, 0.56, 0.38, color=SURFACE, edge=GRID)
    label_text(fig, 0.085, 0.735, "五日平均波動比值", fontsize=16, color=NAVY, weight="bold")
    scale = max(direct["raw"], benchmark["raw"])
    if scale <= 0:
        raise ValueError("Benchmark comparison ratios must be positive")
    bar_x = 0.085
    bar_width = 0.45
    for metric, y, color in ((direct, 0.61, TEAL), (benchmark, 0.49, NAVY)):
        label_text(fig, bar_x, y + 0.063, metric["label"], fontsize=13, color=MUTED, weight="bold")
        fig.patches.append(
            Rectangle(
                (bar_x, y),
                bar_width * metric["raw"] / scale,
                0.045,
                transform=fig.transFigure,
                facecolor=color,
                edgecolor="none",
            )
        )
        label_text(fig, bar_x + bar_width + 0.01, y + 0.022, metric["rendered"], fontsize=20, ha="left", va="center", weight="bold", color=color)
    label_text(fig, 0.085, 0.435, "較長的深色橫條代表同週大盤對照更高。", fontsize=11.5, color=FAINT)

    rect(fig, 0.66, 0.40, 0.28, 0.38, color=NAVY, edge=NAVY)
    label_text(fig, 0.685, 0.735, "對照後差值", fontsize=16, color="#D8E5EF", weight="bold")
    label_text(fig, 0.685, 0.665, rv_delta["label"], fontsize=12.5, color="#D8E5EF")
    label_text(fig, 0.685, 0.625, rv_delta["rendered"], fontsize=28, color=PAPER, weight="bold")
    label_text(fig, 0.685, 0.570, wrapped(rv_delta["note"], 14), fontsize=10.3, color="#C4D2DD")
    fig.patches.append(
        Rectangle(
            (0.685, 0.515),
            0.23,
            0.0015,
            transform=fig.transFigure,
            facecolor="#496078",
            edgecolor="none",
        )
    )
    label_text(fig, 0.685, 0.495, jump_delta["label"], fontsize=12.5, color="#D8E5EF")
    label_text(fig, 0.685, 0.455, jump_delta["rendered"], fontsize=27, color=PAPER, weight="bold")
    label_text(fig, 0.790, 0.470, wrapped(jump_delta["note"], 8), fontsize=9.8, color="#C4D2DD")

    rect(fig, 0.06, 0.12, 0.88, 0.23, color=PAPER, edge=GRID)
    label_text(fig, 0.085, 0.31, boundary["heading"], fontsize=15, color=NAVY, weight="bold")
    for index, sentence in enumerate(boundary["body"]):
        y = 0.255 - index * 0.055
        label_text(fig, 0.087, y, "•", fontsize=12.5, color=AMBER, weight="bold")
        label_text(fig, 0.11, y, wrapped(sentence, 52), fontsize=11.8, color=MUTED)

    draw_footer(fig, source)
    save_panel(fig, panel)


def main() -> None:
    results, plan = load_inputs()
    os.makedirs(OUT_DIR, exist_ok=True)

    scoreboard = get_panel(plan, "1_scoreboard")
    two_jumps = get_panel(plan, "2_two_jumps")
    benchmark = get_panel(plan, "3_benchmark")

    render_scoreboard(scoreboard, bind_blocks(scoreboard, results), source_label(plan, scoreboard))
    render_two_jumps(two_jumps, bind_blocks(two_jumps, results), source_label(plan, two_jumps))
    render_benchmark(benchmark, bind_blocks(benchmark, results), source_label(plan, benchmark))


if __name__ == "__main__":
    main()
