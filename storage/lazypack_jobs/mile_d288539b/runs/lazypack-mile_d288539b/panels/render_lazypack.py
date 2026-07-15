#!/usr/bin/env python3
"""Render the three data-bound PNG panels for the stablecoin/short-bond article."""

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
from matplotlib.patches import Circle, FancyBboxPatch, Rectangle


PLAN_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_d288539b/runs/lazypack-mile_d288539b/plan.json"
)
RESULT_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/K1586/K1586_results.json"
)
ARTICLE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_d288539b/runs/lazypack-mile_d288539b/panels/"
    "mile_d288539b_article.md"
)
out_dir = (
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_d288539b/runs/lazypack-mile_d288539b/panels"
)

WIDTH = 1600
HEIGHT = 1000
DPI = 150

INK = "#172033"
MUTED = "#5D6878"
FAINT = "#8792A2"
LINE = "#DCE2EA"
PAPER = "#FFFFFF"
SOFT = "#F4F6F9"
NAVY = "#17385E"
BLUE = "#2767A6"
BLUE_SOFT = "#E8F0F8"
TEAL = "#197B79"
TEAL_SOFT = "#E2F2F0"
AMBER = "#A9671B"
AMBER_SOFT = "#F7EEDF"

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise TypeError(f"Expected a JSON object in {path}")
    return data


def resolve_path(data: Any, path: str) -> Any:
    current = data
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise KeyError(f"Missing evidence field: {path}")
        current = current[part]
    return current


def panel_by_name(plan: dict[str, Any], name: str) -> dict[str, Any]:
    panels = plan["panels"]
    if not isinstance(panels, list):
        raise TypeError("plan.panels must be a list")
    matches = [p for p in panels if isinstance(p, dict) and p.get("name") == name]
    if len(matches) != 1:
        raise KeyError(f"Expected exactly one panel named {name}")
    return matches[0]


def metric_block(panel: dict[str, Any], label: str) -> dict[str, Any]:
    matches = [
        block
        for block in panel["blocks"]
        if isinstance(block, dict)
        and block.get("kind") == "metric"
        and block.get("label") == label
    ]
    if len(matches) != 1:
        raise KeyError(f"Expected exactly one metric block labeled {label}")
    return matches[0]


def text_block(panel: dict[str, Any], heading: str) -> dict[str, Any]:
    matches = [
        block
        for block in panel["blocks"]
        if isinstance(block, dict)
        and block.get("kind") == "text"
        and block.get("heading") == heading
    ]
    if len(matches) != 1:
        raise KeyError(f"Expected exactly one text block headed {heading}")
    return matches[0]


def format_bound_value(value: Any, spec: dict[str, Any], path: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"Expected numeric evidence at {path}")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"Expected finite evidence at {path}")

    kind = spec["kind"]
    suffix = spec.get("suffix", "")
    if kind == "integer":
        if not number.is_integer():
            raise ValueError(f"Expected integer evidence at {path}")
        return f"{int(number):,}{suffix}"
    if kind == "number":
        digits = spec["digits"]
        if not isinstance(digits, int) or digits < 0:
            raise ValueError(f"Invalid digits for {path}")
        return f"{number:.{digits}f}{suffix}"
    raise ValueError(f"Unsupported format kind {kind!r} at {path}")


def bind_metric(
    panel: dict[str, Any], label: str, sources: dict[str, dict[str, Any]]
) -> tuple[str, str]:
    block = metric_block(panel, label)
    value_spec = block["value"]
    source_key = value_spec["source"]
    if source_key not in sources:
        raise KeyError(f"Unknown evidence source: {source_key}")
    path = value_spec["path"]
    value = resolve_path(sources[source_key], path)
    rendered = format_bound_value(value, value_spec["format"], path)
    return block["label"], rendered


def body_text(panel: dict[str, Any], heading: str) -> tuple[str, str]:
    block = text_block(panel, heading)
    body = block["body"]
    if not isinstance(body, list) or not body or not all(isinstance(x, str) for x in body):
        raise TypeError(f"Text block {heading} must contain a non-empty string list")
    return block["heading"], "\n".join(body)


def source_footer(plan: dict[str, Any], panel: dict[str, Any]) -> str:
    evidence = plan["evidence"]
    labels: list[str] = []
    for source_key in panel["sources"]:
        source = evidence[source_key]
        label = source["label"]
        if not isinstance(label, str) or not label.strip():
            raise ValueError(f"Evidence source {source_key} has no reader-facing label")
        labels.append(label)
    if labels != ["穩定幣與短債事件窗重跑結果"]:
        raise ValueError("Unexpected strict-plan source label")
    return "資料來源：" + "、".join(labels)


def require_article_phrase(article: str, phrase: str) -> str:
    if phrase not in article:
        raise ValueError(f"Required article evidence phrase is missing: {phrase}")
    return phrase


def new_canvas() -> tuple[plt.Figure, plt.Axes]:
    fig = plt.figure(figsize=(WIDTH / DPI, HEIGHT / DPI), dpi=DPI, facecolor=PAPER)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, WIDTH)
    ax.set_ylim(0, HEIGHT)
    ax.axis("off")
    return fig, ax


def add_footer(ax: plt.Axes, footer: str, color: str = MUTED) -> None:
    ax.plot([80, 1520], [92, 92], color=LINE, linewidth=1.4)
    ax.text(80, 48, footer, fontsize=17, color=color, va="center", ha="left")


def rounded_card(
    ax: plt.Axes,
    x: float,
    y: float,
    width: float,
    height: float,
    facecolor: str,
    edgecolor: str = LINE,
    radius: float = 24,
    linewidth: float = 1.5,
) -> None:
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            width,
            height,
            boxstyle=f"round,pad=0,rounding_size={radius}",
            facecolor=facecolor,
            edgecolor=edgecolor,
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


def save_panel(fig: plt.Figure, panel: dict[str, Any]) -> None:
    filename = os.path.join(out_dir, f"{panel['name']}.png")
    fig.savefig(
        filename,
        dpi=DPI,
        facecolor=PAPER,
        metadata={"Title": panel["title"], "Description": panel["alt"]},
    )
    plt.close(fig)


def render_two_short_bonds(
    plan: dict[str, Any], sources: dict[str, dict[str, Any]], article: str
) -> None:
    panel = panel_by_name(plan, "1_two_short_bonds")
    event_label, event_value = bind_metric(panel, "事件窗交易日", sources)
    control_label, control_value = bind_metric(panel, "對照期交易日", sources)
    reading_heading, reading_body = body_text(panel, "讀法")
    bil_range = require_article_phrase(article, "BIL，1 至 3 個月")
    shy_range = require_article_phrase(article, "SHY，1 至 3 年")

    fig, ax = new_canvas()
    ax.text(90, 914, panel["title"], fontsize=52, weight="bold", color=INK, va="top")
    ax.add_patch(Rectangle((90, 824), 118, 7, facecolor=TEAL, edgecolor="none"))

    # Editorial hero: the two maturity bands are intentionally presented on one scale.
    ax.text(90, 748, "先辨認到期區間", fontsize=24, color=MUTED, va="center")
    ax.text(90, 660, bil_range, fontsize=30, weight="bold", color=INK, va="center")
    ax.text(90, 548, shy_range, fontsize=30, weight="bold", color=INK, va="center")
    ax.plot([420, 1470], [660, 660], color=LINE, linewidth=12, solid_capstyle="round")
    ax.plot([420, 1470], [548, 548], color=LINE, linewidth=12, solid_capstyle="round")
    ax.plot([420, 535], [660, 660], color=TEAL, linewidth=30, solid_capstyle="round")
    ax.plot([760, 1470], [548, 548], color=BLUE, linewidth=30, solid_capstyle="round")
    ax.add_patch(Circle((420, 660), 9, facecolor=INK, edgecolor="none"))
    ax.add_patch(Circle((420, 548), 9, facecolor=INK, edgecolor="none"))

    # Keep the explanation in its own left column.  At this canvas/DPI a CJK
    # glyph is roughly twice the font size in pixels, so the former 28-character
    # lines extended underneath both metric cards even though they looked short
    # in source code.
    ax.text(90, 435, reading_heading, fontsize=23, weight="bold", color=INK, va="top")
    ax.text(
        90,
        365,
        wrapped(reading_body, 13),
        fontsize=22,
        color=MUTED,
        va="top",
        linespacing=1.42,
    )

    rounded_card(ax, 850, 175, 310, 250, TEAL_SOFT, edgecolor=TEAL_SOFT)
    rounded_card(ax, 1190, 175, 320, 250, BLUE_SOFT, edgecolor=BLUE_SOFT)
    ax.text(
        1005,
        378,
        event_label,
        fontsize=16,
        color=MUTED,
        va="top",
        ha="center",
    )
    ax.text(
        1005,
        270,
        event_value,
        fontsize=30,
        weight="bold",
        color=TEAL,
        va="center",
        ha="center",
    )
    ax.text(
        1350,
        378,
        control_label,
        fontsize=16,
        color=MUTED,
        va="top",
        ha="center",
    )
    ax.text(
        1350,
        270,
        control_value,
        fontsize=30,
        weight="bold",
        color=BLUE,
        va="center",
        ha="center",
    )

    add_footer(ax, source_footer(plan, panel))
    save_panel(fig, panel)


def draw_metric_tile(
    ax: plt.Axes,
    x: float,
    y: float,
    width: float,
    height: float,
    label: str,
    value: str,
    accent: str,
    soft: str,
    motif: str,
) -> None:
    rounded_card(ax, x, y, width, height, soft, edgecolor=soft, radius=30)
    ax.add_patch(Rectangle((x, y), 10, height, facecolor=accent, edgecolor="none"))
    ax.text(x + 46, y + height - 48, label, fontsize=25, color=MUTED, va="top")
    ax.text(x + 46, y + 95, value, fontsize=58, weight="bold", color=INK, va="center")

    if motif == "ratio":
        ax.plot(
            [x + width - 155, x + width - 58],
            [y + 78, y + 175],
            color=accent,
            linewidth=8,
            solid_capstyle="round",
        )
        ax.plot(
            [x + width - 95, x + width - 58, x + width - 58],
            [y + 175, y + 175, y + 138],
            color=accent,
            linewidth=8,
            solid_capstyle="round",
        )
    elif motif == "test":
        for index, radius in enumerate((12, 18, 24)):
            ax.add_patch(
                Circle(
                    (x + width - 120 + index * 38, y + 135),
                    radius,
                    facecolor=accent,
                    edgecolor="none",
                    alpha=0.35 + index * 0.22,
                )
            )
    else:
        raise ValueError(f"Unknown tile motif: {motif}")


def render_event_split(
    plan: dict[str, Any], sources: dict[str, dict[str, Any]]
) -> None:
    panel = panel_by_name(plan, "2_event_split")
    shy_ratio = bind_metric(panel, "SHY 事件窗倍率", sources)
    shy_p = bind_metric(panel, "SHY 分組重抽調整值", sources)
    bil_ratio = bind_metric(panel, "BIL 事件窗倍率", sources)
    bil_p = bind_metric(panel, "BIL 分組重抽調整值", sources)

    fig, ax = new_canvas()
    ax.text(90, 918, panel["title"], fontsize=48, weight="bold", color=INK, va="top")

    # SHY/BIL already lead every tile label.  A second legend in the title row
    # duplicated that information and occupied the same pixels as the long title.
    draw_metric_tile(ax, 90, 492, 680, 300, *shy_ratio, BLUE, BLUE_SOFT, "ratio")
    draw_metric_tile(ax, 830, 492, 680, 300, *shy_p, BLUE, SOFT, "test")
    draw_metric_tile(ax, 90, 145, 680, 300, *bil_ratio, AMBER, AMBER_SOFT, "ratio")
    draw_metric_tile(ax, 830, 145, 680, 300, *bil_p, AMBER, SOFT, "test")

    add_footer(ax, source_footer(plan, panel))
    save_panel(fig, panel)


def render_honest_boundary(
    plan: dict[str, Any], sources: dict[str, dict[str, Any]]
) -> None:
    panel = panel_by_name(plan, "3_honest_boundary")
    daily_label, daily_value = bind_metric(panel, "日常檢查最低顯著性數字", sources)
    sample_label, sample_value = bind_metric(panel, "完整樣本營業日", sources)
    boundary_heading, boundary_body = body_text(panel, "研究邊界")

    fig, ax = new_canvas()
    ax.add_patch(Rectangle((0, 760), WIDTH, 240, facecolor=NAVY, edgecolor="none"))
    ax.text(90, 902, panel["title"], fontsize=40, weight="bold", color=PAPER, va="top")
    ax.add_patch(Rectangle((90, 803), 118, 7, facecolor="#69C7C2", edgecolor="none"))

    rounded_card(ax, 90, 455, 680, 250, PAPER, edgecolor=LINE, radius=24)
    rounded_card(ax, 830, 455, 680, 250, PAPER, edgecolor=LINE, radius=24)
    ax.text(130, 652, daily_label, fontsize=18, color=MUTED, va="top")
    ax.text(130, 525, daily_value, fontsize=42, weight="bold", color=NAVY, va="center")
    ax.text(870, 652, sample_label, fontsize=18, color=MUTED, va="top")
    ax.text(870, 525, sample_value, fontsize=42, weight="bold", color=NAVY, va="center")

    ax.add_patch(Rectangle((90, 145), 12, 265, facecolor=TEAL, edgecolor="none"))
    ax.text(140, 390, boundary_heading, fontsize=24, weight="bold", color=INK, va="top")
    ax.text(
        140,
        320,
        wrapped(boundary_body, 24),
        fontsize=20,
        color=MUTED,
        va="top",
        linespacing=1.45,
    )

    add_footer(ax, source_footer(plan, panel))
    save_panel(fig, panel)


def main() -> None:
    os.makedirs(out_dir, exist_ok=True)
    plan = load_json(PLAN_PATH)
    results = load_json(RESULT_PATH)
    article = ARTICLE_PATH.read_text(encoding="utf-8")
    if not article.strip():
        raise ValueError(f"Article evidence is empty: {ARTICLE_PATH}")

    sources = {"result": results}
    render_two_short_bonds(plan, sources, article)
    render_event_split(plan, sources)
    render_honest_boundary(plan, sources)


if __name__ == "__main__":
    main()
