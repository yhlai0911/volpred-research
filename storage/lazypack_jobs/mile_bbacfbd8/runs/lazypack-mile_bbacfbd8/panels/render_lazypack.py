#!/usr/bin/env python3
"""Render the three data-bound PNG panels for the mile_bbacfbd8 lazypack.

This renderer is intentionally article-specific.  All displayed research values
are resolved from the strict plan and k1478_results.json at runtime; missing
fields raise immediately instead of producing a plausible-looking substitute.
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
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch


PLAN_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_bbacfbd8/runs/lazypack-mile_bbacfbd8/plan.json"
)
RESULTS_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1478/k1478_results.json"
)
ARTICLE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_bbacfbd8/runs/lazypack-mile_bbacfbd8/panels/"
    "mile_bbacfbd8_article.md"
)
out_dir = (
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_bbacfbd8/runs/lazypack-mile_bbacfbd8/panels"
)

WIDTH_PX = 1600
HEIGHT_PX = 1000
DPI = 150

INK = "#172033"
NAVY = "#152B46"
BLUE = "#2F6FA3"
TEAL = "#157B78"
AMBER = "#B06F18"
RED = "#A5413B"
MUTED = "#586779"
PALE = "#F4F7FA"
LINE = "#D7E0E8"
WHITE = "#FFFFFF"

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def require_mapping(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{context} must be an object")
    return value


def require_text(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{context} must be a non-empty string")
    return value


def resolve_pointer(document: Any, pointer: str) -> Any:
    """Resolve a strict RFC 6901-style JSON pointer and raise on any miss."""
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValueError(f"Invalid JSON pointer: {pointer!r}")
    current = document
    for raw_part in pointer.split("/")[1:]:
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            if part not in current:
                raise KeyError(f"Missing evidence field {pointer!r} at {part!r}")
            current = current[part]
        elif isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError) as exc:
                raise KeyError(f"Missing evidence field {pointer!r} at {part!r}") from exc
        else:
            raise KeyError(f"Evidence path {pointer!r} traverses a scalar")
    return current


def require_number(value: Any, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{context} must be numeric")
    return float(value)


def format_bound_value(value_spec: dict[str, Any], results: dict[str, Any]) -> str:
    source = require_text(value_spec.get("source"), "metric source")
    if source != "results":
        raise ValueError(f"Unsupported metric source: {source}")
    pointer = require_text(value_spec.get("path"), "metric path")
    value = require_number(resolve_pointer(results, pointer), pointer)
    fmt = require_mapping(value_spec.get("format"), f"format for {pointer}")
    kind = require_text(fmt.get("kind"), f"format kind for {pointer}")
    if kind == "integer":
        if not value.is_integer():
            raise ValueError(f"Expected an integer at {pointer}, got {value}")
        return f"{int(value)}"
    if kind == "number":
        digits = fmt.get("digits")
        if not isinstance(digits, int) or digits < 0:
            raise TypeError(f"digits for {pointer} must be a non-negative integer")
        return f"{value:.{digits}f}"
    raise ValueError(f"Unsupported metric format {kind!r} at {pointer}")


_ZH_DIGITS = "零一二三四五六七八九"


def chinese_integer(value: int) -> str:
    """Format the small positive sample counts used in this article."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > 9999:
        raise ValueError(f"Unsupported Chinese integer: {value!r}")
    if value == 0:
        return _ZH_DIGITS[0]
    units = ((1000, "千"), (100, "百"), (10, "十"), (1, ""))
    remaining = value
    parts: list[str] = []
    pending_zero = False
    for divisor, unit in units:
        digit, remaining = divmod(remaining, divisor)
        if digit:
            if pending_zero and parts:
                parts.append("零")
            if not (divisor == 10 and digit == 1 and not parts):
                parts.append(_ZH_DIGITS[digit])
            parts.append(unit)
            pending_zero = False
        elif parts and remaining:
            pending_zero = True
    return "".join(parts)


def chinese_fixed(value: float, digits: int) -> str:
    rendered = f"{abs(value):.{digits}f}"
    whole, fraction = rendered.split(".")
    prefix = "負" if value < 0 else ""
    whole_zh = chinese_integer(int(whole))
    fraction_zh = "".join(_ZH_DIGITS[int(char)] for char in fraction)
    return f"{prefix}{whole_zh}點{fraction_zh}"


def panel_by_name(plan: dict[str, Any], name: str) -> dict[str, Any]:
    panels = plan.get("panels")
    if not isinstance(panels, list):
        raise TypeError("plan.panels must be an array")
    matches = [item for item in panels if isinstance(item, dict) and item.get("name") == name]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one panel named {name!r}")
    return matches[0]


def metric_block(panel: dict[str, Any], index: int) -> dict[str, Any]:
    blocks = panel.get("blocks")
    if not isinstance(blocks, list):
        raise TypeError(f"{panel.get('name')}.blocks must be an array")
    metrics = [block for block in blocks if isinstance(block, dict) and block.get("kind") == "metric"]
    try:
        return metrics[index]
    except IndexError as exc:
        raise ValueError(f"Missing metric {index} in {panel.get('name')}") from exc


def text_block(panel: dict[str, Any], index: int) -> dict[str, Any]:
    blocks = panel.get("blocks")
    if not isinstance(blocks, list):
        raise TypeError(f"{panel.get('name')}.blocks must be an array")
    texts = [block for block in blocks if isinstance(block, dict) and block.get("kind") == "text"]
    try:
        block = texts[index]
    except IndexError as exc:
        raise ValueError(f"Missing text block {index} in {panel.get('name')}") from exc
    require_text(block.get("heading"), "text heading")
    body = block.get("body")
    if not isinstance(body, list) or not body:
        raise TypeError("text body must be a non-empty array")
    for item in body:
        require_text(item, "text body item")
    return block


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
    ax: Axes,
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    facecolor: str = WHITE,
    edgecolor: str = LINE,
    linewidth: float = 1.2,
    radius: float = 0.018,
) -> None:
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            width,
            height,
            boxstyle=f"round,pad=0.008,rounding_size={radius}",
            linewidth=linewidth,
            edgecolor=edgecolor,
            facecolor=facecolor,
            transform=ax.transAxes,
            clip_on=False,
        )
    )


def new_canvas(title: str) -> tuple[Figure, Axes]:
    fig = plt.figure(figsize=(WIDTH_PX / DPI, HEIGHT_PX / DPI), dpi=DPI, facecolor=WHITE)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.add_patch(
        FancyBboxPatch(
            (0.028, 0.85),
            0.944,
            0.125,
            boxstyle="round,pad=0.008,rounding_size=0.018",
            linewidth=0,
            facecolor=NAVY,
            transform=ax.transAxes,
        )
    )
    fig.text(
        0.055,
        0.912,
        title,
        color=WHITE,
        fontsize=27,
        fontweight="bold",
        va="center",
        ha="left",
    )
    return fig, ax


def draw_footer(fig: Figure, ax: Axes, source_label: str) -> None:
    ax.plot([0.05, 0.95], [0.145, 0.145], color=LINE, linewidth=1.0, transform=ax.transAxes)
    fig.text(
        0.05,
        0.083,
        wrap_zh(f"資料來源：{source_label}", 78),
        color=MUTED,
        fontsize=8.7,
        va="center",
        ha="left",
        linespacing=1.38,
    )


def draw_metric_card(
    fig: Figure,
    ax: Axes,
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    label: str,
    value: str,
    note: str,
    accent: str,
    compact: bool = False,
) -> None:
    rounded_box(ax, x, y, width, height, facecolor=PALE, edgecolor=LINE)
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            0.012,
            height,
            boxstyle="round,pad=0,rounding_size=0.008",
            linewidth=0,
            facecolor=accent,
            transform=ax.transAxes,
        )
    )
    if compact:
        # Keep the label, value, and note in three distinct vertical rows.  The
        # previous anchors let the 33 pt value grow upward into the label.
        fig.text(x + 0.025, y + height - 0.025, wrap_zh(label, 13), color=MUTED, fontsize=10.2,
                 va="top", ha="left", linespacing=1.28)
        fig.text(x + 0.025, y + 0.066, value, color=accent, fontsize=28, fontweight="bold",
                 va="bottom", ha="left")
        fig.text(x + 0.025, y + 0.018, wrap_zh(note, 15), color=MUTED, fontsize=8.9,
                 va="bottom", ha="left", linespacing=1.22)
        return
    fig.text(x + 0.027, y + height - 0.034, wrap_zh(label, 24), color=MUTED, fontsize=11.5,
             va="top", ha="left", linespacing=1.25)
    fig.text(x + 0.027, y + 0.102, value, color=accent, fontsize=38, fontweight="bold",
             va="bottom", ha="left")
    fig.text(x + 0.027, y + 0.025, wrap_zh(note, 31), color=MUTED, fontsize=10.2,
             va="bottom", ha="left", linespacing=1.28)


def draw_text_card(
    fig: Figure,
    ax: Axes,
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    block: dict[str, Any],
    accent: str,
    wrap_width: int,
) -> None:
    rounded_box(ax, x, y, width, height)
    ax.add_patch(
        FancyBboxPatch(
            (x + 0.022, y + height - 0.058),
            0.042,
            0.012,
            boxstyle="round,pad=0,rounding_size=0.006",
            linewidth=0,
            facecolor=accent,
            transform=ax.transAxes,
        )
    )
    heading = require_text(block.get("heading"), "text heading")
    body = block.get("body")
    if not isinstance(body, list):
        raise TypeError("text body must be an array")
    paragraphs = [wrap_zh(require_text(item, "text paragraph"), wrap_width) for item in body]
    fig.text(x + 0.027, y + height - 0.082, heading, color=INK, fontsize=15.5,
             fontweight="bold", va="top", ha="left")
    fig.text(x + 0.027, y + height - 0.137, "\n\n".join(paragraphs), color=MUTED,
             fontsize=11.2, va="top", ha="left", linespacing=1.48)


def source_label_from_plan(plan: dict[str, Any]) -> str:
    evidence = require_mapping(plan.get("evidence"), "plan.evidence")
    results_evidence = require_mapping(evidence.get("results"), "plan.evidence.results")
    return require_text(results_evidence.get("label"), "plan.evidence.results.label")


def save_panel(fig: Figure, panel: dict[str, Any]) -> None:
    name = require_text(panel.get("name"), "panel name")
    alt = require_text(panel.get("alt"), f"{name}.alt")
    path = os.path.join(out_dir, f"{name}.png")
    fig.savefig(
        path,
        dpi=DPI,
        facecolor=WHITE,
        edgecolor=WHITE,
        metadata={
            "Title": require_text(panel.get("title"), f"{name}.title"),
            "Description": alt,
        },
    )
    plt.close(fig)


def render_framework(plan: dict[str, Any], results: dict[str, Any], source_label: str) -> None:
    panel = panel_by_name(plan, "panel_framework")
    metric = metric_block(panel, 0)
    block_left = text_block(panel, 0)
    block_right = text_block(panel, 1)
    value = format_bound_value(require_mapping(metric.get("value"), "framework metric value"), results)

    fig, ax = new_canvas(require_text(panel.get("title"), "panel_framework.title"))

    stages = (
        (0.05, "每日重設", "基金承諾的倍數"),
        (0.28, "指數漲跌", "壓力隨波動放大"),
        (0.51, "收盤前調整", "上漲加碼、下跌減碼"),
    )
    for x, heading, caption in stages:
        rounded_box(ax, x, 0.675, 0.18, 0.125, facecolor=PALE, edgecolor=LINE, radius=0.014)
        fig.text(x + 0.09, 0.754, heading, color=INK, fontsize=13.5, fontweight="bold",
                 ha="center", va="center")
        fig.text(x + 0.09, 0.708, caption, color=MUTED, fontsize=9.5,
                 ha="center", va="center")
    for x0, x1 in ((0.23, 0.28), (0.46, 0.51)):
        ax.add_patch(
            FancyArrowPatch(
                (x0, 0.738),
                (x1, 0.738),
                arrowstyle="-|>",
                mutation_scale=15,
                linewidth=1.6,
                color=BLUE,
                transform=ax.transAxes,
            )
        )

    draw_metric_card(
        fig,
        ax,
        x=0.735,
        y=0.625,
        width=0.215,
        height=0.175,
        label=require_text(metric.get("label"), "framework metric label"),
        value=value,
        note=require_text(metric.get("note"), "framework metric note"),
        accent=TEAL,
        compact=True,
    )
    draw_text_card(fig, ax, x=0.05, y=0.18, width=0.43, height=0.425,
                   block=block_left, accent=BLUE, wrap_width=25)
    draw_text_card(fig, ax, x=0.52, y=0.18, width=0.43, height=0.425,
                   block=block_right, accent=AMBER, wrap_width=25)
    draw_footer(fig, ax, source_label)
    save_panel(fig, panel)


def render_numbers(plan: dict[str, Any], results: dict[str, Any], source_label: str) -> None:
    panel = panel_by_name(plan, "panel_numbers")
    metric_days = metric_block(panel, 0)
    metric_t = metric_block(panel, 1)
    explanation = text_block(panel, 0)

    n_high = format_bound_value(require_mapping(metric_days.get("value"), "n_high value"), results)
    t_uncontrolled = format_bound_value(require_mapping(metric_t.get("value"), "Welch t value"), results)
    n_low_raw = resolve_pointer(results, "/top_quartile_tests/last_hour_range_var/n_low")
    if isinstance(n_low_raw, bool) or not isinstance(n_low_raw, int):
        raise TypeError("/top_quartile_tests/last_hour_range_var/n_low must be an integer")
    n_low_zh = chinese_integer(n_low_raw)

    fig, ax = new_canvas(require_text(panel.get("title"), "panel_numbers.title"))
    draw_metric_card(
        fig,
        ax,
        x=0.05,
        y=0.565,
        width=0.43,
        height=0.24,
        label=require_text(metric_days.get("label"), "n_high label"),
        value=n_high,
        note=f"其餘三等分合計{n_low_zh}天，作為對照",
        accent=BLUE,
    )
    draw_metric_card(
        fig,
        ax,
        x=0.52,
        y=0.565,
        width=0.43,
        height=0.24,
        label=require_text(metric_t.get("label"), "Welch t label"),
        value=t_uncontrolled,
        note=require_text(metric_t.get("note"), "Welch t note"),
        accent=AMBER,
    )
    draw_text_card(fig, ax, x=0.05, y=0.19, width=0.90, height=0.315,
                   block=explanation, accent=RED, wrap_width=55)
    draw_footer(fig, ax, source_label)
    save_panel(fig, panel)


def render_takeaway(plan: dict[str, Any], results: dict[str, Any], source_label: str) -> None:
    panel = panel_by_name(plan, "panel_takeaway")
    metric_tail = metric_block(panel, 0)
    metric_overnight = metric_block(panel, 1)
    explanation = text_block(panel, 0)

    controlled_tail = format_bound_value(
        require_mapping(metric_tail.get("value"), "controlled tail value"), results
    )
    controlled_overnight = format_bound_value(
        require_mapping(metric_overnight.get("value"), "controlled overnight value"), results
    )
    uncontrolled_tail = require_number(
        resolve_pointer(results, "/top_quartile_tests/last_hour_range_var/welch_t"),
        "/top_quartile_tests/last_hour_range_var/welch_t",
    )
    uncontrolled_overnight = require_number(
        resolve_pointer(results, "/top_quartile_tests/overnight_cont/welch_t"),
        "/top_quartile_tests/overnight_cont/welch_t",
    )

    tail_note = (
        f"未控制時為{chinese_fixed(uncontrolled_tail, 2)}；"
        "一般認定站得住約需二以上"
    )
    overnight_note = (
        f"只比較壓力高低時為{chinese_fixed(uncontrolled_overnight, 2)}，"
        "控制後才浮現，貼著門檻，列為次要訊號"
    )

    fig, ax = new_canvas(require_text(panel.get("title"), "panel_takeaway.title"))
    draw_metric_card(
        fig,
        ax,
        x=0.05,
        y=0.565,
        width=0.43,
        height=0.24,
        label=require_text(metric_tail.get("label"), "controlled tail label"),
        value=controlled_tail,
        note=tail_note,
        accent=TEAL,
    )
    draw_metric_card(
        fig,
        ax,
        x=0.52,
        y=0.565,
        width=0.43,
        height=0.24,
        label=require_text(metric_overnight.get("label"), "controlled overnight label"),
        value=controlled_overnight,
        note=overnight_note,
        accent=AMBER,
    )
    draw_text_card(fig, ax, x=0.05, y=0.19, width=0.90, height=0.315,
                   block=explanation, accent=TEAL, wrap_width=55)
    draw_footer(fig, ax, source_label)
    save_panel(fig, panel)


def main() -> None:
    plan = require_mapping(load_json(PLAN_PATH), "plan")
    results = require_mapping(load_json(RESULTS_PATH), "results")
    article = ARTICLE_PATH.read_text(encoding="utf-8")
    if not article.strip():
        raise ValueError("Article evidence is empty")
    for required_phrase in ("每天", "再平衡壓力", "代理變數", "隔夜延續"):
        if required_phrase not in article:
            raise ValueError(f"Article evidence is missing required phrase: {required_phrase}")

    source_label = source_label_from_plan(plan)
    os.makedirs(out_dir, exist_ok=True)
    render_framework(plan, results, source_label)
    render_numbers(plan, results, source_label)
    render_takeaway(plan, results, source_label)


if __name__ == "__main__":
    main()
