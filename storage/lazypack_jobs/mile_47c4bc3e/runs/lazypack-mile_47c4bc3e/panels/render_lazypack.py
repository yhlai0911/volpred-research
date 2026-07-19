#!/usr/bin/env python3
"""Render the four data-bound PNG panels for the 0050 margin/volatility article."""

from __future__ import annotations

import json
import os
import textwrap
from datetime import date
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.patches import Circle, FancyBboxPatch, Rectangle


PLAN_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_47c4bc3e/runs/lazypack-mile_47c4bc3e/plan.json"
)
STATS_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/article_assets/"
    "tw-margin-vol-leadlag/stats_raw.json"
)
ARTICLE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_47c4bc3e/runs/lazypack-mile_47c4bc3e/panels/"
    "mile_47c4bc3e_article.md"
)
out_dir = (
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_47c4bc3e/runs/lazypack-mile_47c4bc3e/panels"
)

WIDTH_PX = 1600
HEIGHT_PX = 1000
DPI = 150

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False

NAVY = "#102A43"
INK = "#172B3A"
MUTED = "#5A6B78"
LINE = "#D9E2EC"
PAPER = "#FFFFFF"
SOFT = "#F4F7FA"
BLUE = "#286B9E"
BLUE_SOFT = "#E8F1F8"
TEAL = "#087F7B"
TEAL_SOFT = "#E2F3F1"
AMBER = "#C77A16"
AMBER_SOFT = "#FBF0DF"
RED = "#B84040"
RED_SOFT = "#F8E8E7"
GREEN = "#24745B"


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise TypeError(f"Expected JSON object: {path}")
    return value


def load_text(path: Path) -> str:
    value = path.read_text(encoding="utf-8")
    if not value.strip():
        raise ValueError(f"Evidence article is empty: {path}")
    return value


def required(mapping: dict[str, Any], key: str, context: str) -> Any:
    if key not in mapping:
        raise KeyError(f"Missing {context}.{key}")
    return mapping[key]


def resolve_path(data: Any, dotted_path: str) -> Any:
    current = data
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise KeyError(f"Missing evidence field: {dotted_path}")
        current = current[part]
    return current


def require_number(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"Expected numeric evidence at {path}")
    return float(value)


def format_bound_value(stats: dict[str, Any], value_spec: dict[str, Any]) -> str:
    if required(value_spec, "source", "value") != "stats":
        raise ValueError("Only the declared stats evidence source is supported")
    path = required(value_spec, "path", "value")
    fmt = required(value_spec, "format", "value")
    if not isinstance(path, str) or not isinstance(fmt, dict):
        raise TypeError("Malformed bound value specification")
    raw = resolve_path(stats, path)
    kind = required(fmt, "kind", f"format for {path}")

    if kind == "date":
        if not isinstance(raw, str):
            raise TypeError(f"Expected ISO date string at {path}")
        parsed = date.fromisoformat(raw)
        return parsed.strftime("%Y.%m.%d")

    if kind == "integer":
        number = require_number(raw, path)
        if not number.is_integer():
            raise ValueError(f"Expected integer evidence at {path}")
        rendered = f"{int(number):,d}"
    elif kind == "number":
        number = require_number(raw, path)
        digits = required(fmt, "digits", f"format for {path}")
        if not isinstance(digits, int) or digits < 0:
            raise TypeError(f"Invalid digits for {path}")
        show_plus = bool(fmt.get("show_plus", False))
        rendered = f"{number:+.{digits}f}" if show_plus else f"{number:.{digits}f}"
    else:
        raise ValueError(f"Unsupported format kind '{kind}' for {path}")

    suffix = fmt.get("suffix", "")
    if not isinstance(suffix, str):
        raise TypeError(f"Invalid suffix for {path}")
    return rendered + suffix


def panels_by_name(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw_panels = required(plan, "panels", "plan")
    if not isinstance(raw_panels, list):
        raise TypeError("plan.panels must be a list")
    result: dict[str, dict[str, Any]] = {}
    for panel in raw_panels:
        if not isinstance(panel, dict):
            raise TypeError("Each plan panel must be an object")
        name = required(panel, "name", "panel")
        if not isinstance(name, str):
            raise TypeError("Panel name must be text")
        if name in result:
            raise ValueError(f"Duplicate panel name: {name}")
        result[name] = panel
    expected = {"1_concept", "2_method", "3_results", "4_takeaway"}
    if set(result) != expected:
        raise ValueError(f"Expected panels {sorted(expected)}, got {sorted(result)}")
    return result


def get_block(panel: dict[str, Any], kind: str, label: str) -> dict[str, Any]:
    blocks = required(panel, "blocks", f"panel {panel.get('name', '?')}")
    if not isinstance(blocks, list):
        raise TypeError("panel.blocks must be a list")
    matches = [
        block
        for block in blocks
        if isinstance(block, dict)
        and block.get("kind") == kind
        and (block.get("label") == label or block.get("heading") == label)
    ]
    if len(matches) != 1:
        raise KeyError(f"Expected exactly one {kind} block named '{label}'")
    return matches[0]


def metric(panel: dict[str, Any], stats: dict[str, Any], label: str) -> tuple[str, str | None]:
    block = get_block(panel, "metric", label)
    value_spec = required(block, "value", f"metric {label}")
    if not isinstance(value_spec, dict):
        raise TypeError(f"Metric value must be an object: {label}")
    note = block.get("note")
    if note is not None and not isinstance(note, str):
        raise TypeError(f"Metric note must be text: {label}")
    return format_bound_value(stats, value_spec), note


def text_block(panel: dict[str, Any], heading: str) -> list[str]:
    block = get_block(panel, "text", heading)
    body = required(block, "body", f"text block {heading}")
    if not isinstance(body, list) or not body or not all(isinstance(x, str) for x in body):
        raise TypeError(f"Text block body must be a non-empty string list: {heading}")
    return body


def new_canvas() -> tuple[Figure, Axes]:
    fig = plt.figure(figsize=(WIDTH_PX / DPI, HEIGHT_PX / DPI), dpi=DPI, facecolor=PAPER)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    return fig, ax


def rounded_box(
    ax: Axes,
    x: float,
    y: float,
    width: float,
    height: float,
    facecolor: str,
    edgecolor: str = "none",
    linewidth: float = 1.2,
    radius: float = 0.018,
) -> None:
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            width,
            height,
            boxstyle=f"round,pad=0.008,rounding_size={radius}",
            facecolor=facecolor,
            edgecolor=edgecolor,
            linewidth=linewidth,
        )
    )


def wrapped(value: str, width: int) -> str:
    if not isinstance(value, str):
        raise TypeError("Text to wrap must be a string")
    if not isinstance(width, int) or width <= 0:
        raise ValueError("Wrap width must be a positive integer")
    # Chinese prose normally has no spaces.  Keeping ``break_long_words`` off
    # therefore leaves an entire paragraph on one line and defeats every
    # caller-supplied card width.  TextWrapper can safely break those CJK runs
    # at the requested character count while still preferring whitespace for
    # Latin text.
    return "\n".join(
        textwrap.wrap(
            value,
            width=width,
            break_long_words=True,
            break_on_hyphens=False,
        )
    )


def add_header(ax: Axes, title: str, dark: bool = False) -> None:
    if not isinstance(title, str) or not title:
        raise ValueError("Panel title is required")
    if dark:
        ax.add_patch(Rectangle((0, 0.855), 1, 0.145, facecolor=NAVY, edgecolor="none"))
        color = PAPER
    else:
        ax.add_patch(Rectangle((0.052, 0.89), 0.035, 0.008, facecolor=TEAL, edgecolor="none"))
        color = NAVY
    ax.text(
        0.06,
        0.925,
        title,
        ha="left",
        va="center",
        fontsize=29,
        fontweight="bold",
        color=color,
    )


def add_footer(ax: Axes, source_label: str) -> None:
    if not isinstance(source_label, str) or not source_label:
        raise ValueError("Source label is required")
    ax.plot([0.06, 0.94], [0.075, 0.075], color=LINE, linewidth=1.0)
    ax.text(
        0.06,
        0.042,
        f"資料來源｜{source_label}",
        ha="left",
        va="center",
        fontsize=10.5,
        color=MUTED,
    )


def add_metric_card(
    ax: Axes,
    x: float,
    y: float,
    width: float,
    height: float,
    label: str,
    value: str,
    note: str | None = None,
    accent: str = BLUE,
    facecolor: str = SOFT,
    value_size: float = 36,
    label_width: int = 18,
) -> None:
    rounded_box(ax, x, y, width, height, facecolor, LINE)
    ax.add_patch(Rectangle((x, y), 0.008, height, facecolor=accent, edgecolor="none"))
    ax.text(
        x + 0.032,
        y + height - 0.052,
        wrapped(label, label_width),
        ha="left",
        va="top",
        fontsize=14.5,
        linespacing=1.28,
        color=MUTED,
    )
    value_y = y + (0.087 if note else 0.074)
    ax.text(
        x + 0.032,
        value_y,
        value,
        ha="left",
        va="bottom",
        fontsize=value_size,
        fontweight="bold",
        color=accent,
    )
    if note:
        ax.text(
            x + width - 0.025,
            y + 0.036,
            note,
            ha="right",
            va="bottom",
            fontsize=11.5,
            color=MUTED,
        )


def render_concept(panel: dict[str, Any], stats: dict[str, Any], source: str) -> Figure:
    fig, ax = new_canvas()
    add_header(ax, required(panel, "title", "1_concept"), dark=True)
    body = text_block(panel, "要檢驗的說法")
    drop, drop_note = metric(panel, stats, "當日跌幅")
    rv20, rv20_note = metric(panel, stats, "二十日已實現波動 當天跳到")

    rounded_box(ax, 0.055, 0.135, 0.535, 0.655, PAPER, LINE, linewidth=1.4)
    ax.add_patch(Circle((0.095, 0.735), 0.019, facecolor=RED_SOFT, edgecolor="none"))
    ax.add_patch(Rectangle((0.091, 0.719), 0.008, 0.032, facecolor=RED, edgecolor="none"))
    ax.text(0.13, 0.735, "要檢驗的說法", ha="left", va="center", fontsize=19, fontweight="bold", color=NAVY)

    y_positions = (0.65, 0.485, 0.32)
    markers = (RED, AMBER, TEAL)
    for sentence, y, color in zip(body, y_positions, markers):
        ax.add_patch(Circle((0.098, y + 0.014), 0.007, facecolor=color, edgecolor="none"))
        ax.text(
            0.125,
            y + 0.045,
            wrapped(sentence, 20),
            ha="left",
            va="top",
            fontsize=17,
            linespacing=1.5,
            color=INK,
        )

    add_metric_card(
        ax, 0.625, 0.49, 0.315, 0.30, "當日跌幅", drop, drop_note,
        accent=RED, facecolor=RED_SOFT, value_size=43,
    )
    add_metric_card(
        ax, 0.625, 0.135, 0.315, 0.30, "二十日已實現波動 當天跳到", rv20, rv20_note,
        accent=TEAL, facecolor=TEAL_SOFT, value_size=43,
    )
    add_footer(ax, source)
    return fig


def render_method(panel: dict[str, Any], stats: dict[str, Any], source: str) -> Figure:
    fig, ax = new_canvas()
    add_header(ax, required(panel, "title", "2_method"))
    body = text_block(panel, "怎麼算的")
    start, _ = metric(panel, stats, "樣本起點")
    end, _ = metric(panel, stats, "樣本終點")
    n_days, _ = metric(panel, stats, "交集交易日")

    step_labels = ("融資訊號", "預測目標", "資料斷點")
    step_colors = (BLUE, TEAL, AMBER)
    step_faces = (BLUE_SOFT, TEAL_SOFT, AMBER_SOFT)
    x_positions = (0.055, 0.365, 0.675)
    for x, label, sentence, color, face in zip(x_positions, step_labels, body, step_colors, step_faces):
        rounded_box(ax, x, 0.46, 0.27, 0.325, PAPER, LINE, linewidth=1.3)
        ax.add_patch(Rectangle((x, 0.74), 0.27, 0.045, facecolor=face, edgecolor="none"))
        ax.add_patch(Circle((x + 0.032, 0.762), 0.008, facecolor=color, edgecolor="none"))
        ax.text(x + 0.052, 0.762, label, ha="left", va="center", fontsize=17, fontweight="bold", color=NAVY)
        ax.text(
            x + 0.027,
            0.69,
            wrapped(sentence, 11),
            ha="left",
            va="top",
            fontsize=14,
            linespacing=1.38,
            color=INK,
        )

    ax.text(0.06, 0.405, "可用樣本", ha="left", va="center", fontsize=15, fontweight="bold", color=MUTED)
    sample_specs = (
        ("樣本起點", start, BLUE),
        ("樣本終點", end, TEAL),
        ("交集交易日", n_days, NAVY),
    )
    for x, (label, value, color) in zip(x_positions, sample_specs):
        rounded_box(ax, x, 0.145, 0.27, 0.21, SOFT, "none")
        ax.text(x + 0.025, 0.305, label, ha="left", va="top", fontsize=13.5, color=MUTED)
        ax.text(x + 0.025, 0.205, value, ha="left", va="center", fontsize=27, fontweight="bold", color=color)

    add_footer(ax, source)
    return fig


def render_results(panel: dict[str, Any], stats: dict[str, Any], source: str) -> Figure:
    fig, ax = new_canvas()
    add_header(ax, required(panel, "title", "3_results"))
    labels = (
        "融資變動 對其後二十日波動 相關",
        "波動自己 對其後二十日波動 相關",
        "加入融資後 解釋力增量",
        "融資係數 t 值",
    )
    values = [metric(panel, stats, label) for label in labels]
    cards = (
        (0.055, 0.50, BLUE, BLUE_SOFT),
        (0.515, 0.50, TEAL, TEAL_SOFT),
        (0.055, 0.15, AMBER, AMBER_SOFT),
        (0.515, 0.15, RED, RED_SOFT),
    )
    for label, (value, note), (x, y, color, face) in zip(labels, values, cards):
        rounded_box(ax, x, y, 0.43, 0.29, face, "none")
        ax.add_patch(Rectangle((x + 0.025, y + 0.24), 0.06, 0.008, facecolor=color, edgecolor="none"))
        ax.text(
            x + 0.025,
            y + 0.215,
            wrapped(label, 22),
            ha="left",
            va="top",
            fontsize=15.5,
            linespacing=1.25,
            color=MUTED,
        )
        ax.text(
            x + 0.025,
            y + 0.055,
            value,
            ha="left",
            va="bottom",
            fontsize=40,
            fontweight="bold",
            color=color,
        )
        if note:
            ax.text(
                x + 0.405,
                y + 0.042,
                note,
                ha="right",
                va="bottom",
                fontsize=11.5,
                color=MUTED,
            )

    add_footer(ax, source)
    return fig


def interval_text(stats: dict[str, Any], group: str) -> str:
    lower_path = f"double_sort.{group}.boot_diff_p05"
    upper_path = f"double_sort.{group}.boot_diff_p95"
    lower = require_number(resolve_path(stats, lower_path), lower_path)
    upper = require_number(resolve_path(stats, upper_path), upper_path)
    return f"拔靴區間 {lower:.1f} 至 {upper:.1f} pp"


def render_takeaway(panel: dict[str, Any], stats: dict[str, Any], source: str) -> Figure:
    fig, ax = new_canvas()
    add_header(ax, required(panel, "title", "4_takeaway"))
    mid_value, mid_note = metric(panel, stats, "中波動層 融資快慢兩組 其後波動差距")
    low_value, low_note = metric(panel, stats, "低波動層 同樣差距")
    body = text_block(panel, "所以什麼時候有用")
    mid_interval = interval_text(stats, "中波動")
    low_interval = interval_text(stats, "低波動")

    rounded_box(ax, 0.055, 0.19, 0.49, 0.61, NAVY, "none")
    ax.text(0.09, 0.745, "中波動層", ha="left", va="center", fontsize=17, fontweight="bold", color="#BFE9E4")
    ax.text(
        0.09,
        0.67,
        wrapped("融資快慢兩組 其後波動差距", 18),
        ha="left",
        va="top",
        fontsize=18,
        linespacing=1.25,
        color=PAPER,
    )
    ax.text(0.09, 0.49, mid_value, ha="left", va="center", fontsize=55, fontweight="bold", color="#69D2C9")
    ax.text(0.09, 0.39, mid_note or "", ha="left", va="center", fontsize=14, color="#D7E5ED")
    ax.plot([0.09, 0.505], [0.335, 0.335], color="#36536A", linewidth=1.2)
    ax.text(0.09, 0.285, mid_interval, ha="left", va="center", fontsize=15, color=PAPER)

    rounded_box(ax, 0.59, 0.59, 0.35, 0.21, SOFT, LINE)
    ax.text(0.62, 0.75, "低波動層 同樣差距", ha="left", va="top", fontsize=14.5, color=MUTED)
    ax.text(0.62, 0.67, low_value, ha="left", va="center", fontsize=30, fontweight="bold", color=BLUE)
    ax.text(0.77, 0.68, low_note or "", ha="left", va="center", fontsize=11.5, color=MUTED)
    ax.text(0.62, 0.62, low_interval, ha="left", va="center", fontsize=12, color=MUTED)

    ax.text(0.59, 0.535, "所以什麼時候有用", ha="left", va="center", fontsize=18, fontweight="bold", color=NAVY)
    y_positions = (0.47, 0.37, 0.27)
    for sentence, y in zip(body, y_positions):
        ax.add_patch(Circle((0.603, y + 0.012), 0.0055, facecolor=TEAL, edgecolor="none"))
        ax.text(
            0.622,
            y + 0.035,
            wrapped(sentence, 17),
            ha="left",
            va="top",
            fontsize=13,
            linespacing=1.32,
            color=INK,
        )

    add_footer(ax, source)
    return fig


def main() -> None:
    plan = load_json(PLAN_PATH)
    stats = load_json(STATS_PATH)
    _article = load_text(ARTICLE_PATH)

    evidence = required(plan, "evidence", "plan")
    if not isinstance(evidence, dict):
        raise TypeError("plan.evidence must be an object")
    stats_evidence = required(evidence, "stats", "plan.evidence")
    if not isinstance(stats_evidence, dict):
        raise TypeError("plan.evidence.stats must be an object")
    source_label = required(stats_evidence, "label", "plan.evidence.stats")
    if not isinstance(source_label, str):
        raise TypeError("plan.evidence.stats.label must be text")

    panels = panels_by_name(plan)
    renderers = {
        "1_concept": render_concept,
        "2_method": render_method,
        "3_results": render_results,
        "4_takeaway": render_takeaway,
    }

    os.makedirs(out_dir, exist_ok=True)
    for name, renderer in renderers.items():
        panel = panels[name]
        figure = renderer(panel, stats, source_label)
        output_path = os.path.join(out_dir, f"{name}.png")
        figure.savefig(output_path, dpi=DPI, facecolor=PAPER, metadata={"Title": panel["title"]})
        plt.close(figure)


if __name__ == "__main__":
    main()
