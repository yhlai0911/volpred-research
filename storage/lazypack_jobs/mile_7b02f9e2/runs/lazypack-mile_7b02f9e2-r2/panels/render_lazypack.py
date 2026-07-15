#!/usr/bin/env python3
"""Render the K1583 general-audience lazypack as four data-bound PNGs.

All displayed metrics are resolved from the paths declared in plan.json and
then read from k1583_results.json. Missing panels, blocks, sources, paths, or
unexpected value types fail loudly instead of producing placeholder values.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.font_manager import FontProperties
from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch, Rectangle
from matplotlib.text import Text


RESULTS_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1583/k1583_results.json"
)
README_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1583/README.md"
)
PLAN_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_7b02f9e2/runs/lazypack-mile_7b02f9e2-r2/plan.json"
)
ARTICLE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_7b02f9e2/runs/lazypack-mile_7b02f9e2-r2/panels/"
    "mile_7b02f9e2_article.md"
)
out_dir = (
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_7b02f9e2/runs/lazypack-mile_7b02f9e2-r2/panels"
)

WIDTH = 1600
HEIGHT = 1000
DPI = 150

INK = "#142033"
NAVY = "#12263F"
BLUE = "#235A97"
TEAL = "#187B7B"
GOLD = "#B87918"
RED = "#B8463C"
MUTED = "#5D6878"
FAINT = "#8A94A3"
LINE = "#D8DEE7"
PAPER = "#FFFFFF"
SOFT_BLUE = "#EAF1F8"
SOFT_TEAL = "#E7F3F1"
SOFT_GOLD = "#F7EEDC"
SOFT_RED = "#F8E8E5"
SOFT_GRAY = "#F3F5F7"

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False


@dataclass(frozen=True)
class BoundMetric:
    label: str
    rendered: str
    path: str
    note: str | None


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def resolve_path(data: Any, dotted_path: str) -> Any:
    current = data
    for part in dotted_path.split("."):
        if isinstance(current, dict):
            if part not in current:
                raise KeyError(f"Missing evidence field: {dotted_path}")
            current = current[part]
        elif isinstance(current, list):
            try:
                index = int(part)
                current = current[index]
            except (ValueError, IndexError) as exc:
                raise KeyError(f"Missing evidence field: {dotted_path}") from exc
        else:
            raise KeyError(f"Missing evidence field: {dotted_path}")
    return current


def require_nonempty_text(path: Path) -> str:
    value = path.read_text(encoding="utf-8")
    if not value.strip():
        raise ValueError(f"Evidence file is empty: {path}")
    return value


def panel_by_name(plan: dict[str, Any], name: str) -> dict[str, Any]:
    panels = plan.get("panels")
    if not isinstance(panels, list):
        raise KeyError("plan.panels")
    matches = [panel for panel in panels if panel.get("name") == name]
    if len(matches) != 1:
        raise KeyError(f"Expected exactly one plan panel named {name}")
    panel = matches[0]
    if not isinstance(panel.get("title"), str) or not panel["title"].strip():
        raise KeyError(f"plan panel {name} has no title")
    return panel


def block_by_heading(panel: dict[str, Any], heading: str) -> dict[str, Any]:
    matches = [
        block
        for block in panel.get("blocks", [])
        if block.get("kind") == "text" and block.get("heading") == heading
    ]
    if len(matches) != 1:
        raise KeyError(f"Expected one text block named {heading}")
    body = matches[0].get("body")
    if not isinstance(body, list) or not body or not all(isinstance(x, str) for x in body):
        raise TypeError(f"Invalid body for text block {heading}")
    return matches[0]


def format_value(value: Any, spec: dict[str, Any], path: str) -> str:
    kind = spec.get("kind")
    suffix = spec.get("suffix", "")
    if not isinstance(suffix, str):
        raise TypeError(f"Invalid suffix for {path}")

    if kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"Expected integer at {path}, got {type(value).__name__}")
        rendered = f"{value:,d}"
    elif kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"Expected number at {path}, got {type(value).__name__}")
        digits = spec.get("digits")
        if not isinstance(digits, int) or digits < 0:
            raise TypeError(f"Invalid digits for {path}")
        rendered = f"{float(value):.{digits}f}"
    elif kind == "date":
        if not isinstance(value, str):
            raise TypeError(f"Expected ISO date at {path}, got {type(value).__name__}")
        datetime.strptime(value, "%Y-%m-%d")
        rendered = value
    else:
        raise ValueError(f"Unsupported format kind {kind!r} for {path}")
    return rendered + suffix


def bind_metric(
    panel: dict[str, Any], label: str, results: dict[str, Any]
) -> BoundMetric:
    matches = [
        block
        for block in panel.get("blocks", [])
        if block.get("kind") == "metric" and block.get("label") == label
    ]
    if len(matches) != 1:
        raise KeyError(f"Expected one metric block named {label}")
    block = matches[0]
    value_spec = block.get("value")
    if not isinstance(value_spec, dict):
        raise TypeError(f"Invalid value spec for {label}")
    if value_spec.get("source") != "k1583":
        raise KeyError(f"Unsupported evidence source for {label}")
    path = value_spec.get("path")
    fmt = value_spec.get("format")
    if not isinstance(path, str) or not isinstance(fmt, dict):
        raise TypeError(f"Invalid path or format for {label}")
    raw_value = resolve_path(results, path)
    note = block.get("note")
    if note is not None and not isinstance(note, str):
        raise TypeError(f"Invalid note for {label}")
    return BoundMetric(
        label=label,
        rendered=format_value(raw_value, fmt, path),
        path=path,
        note=note,
    )


def _wrap_to_pixel_width(
    value: str,
    renderer: Any,
    font: FontProperties,
    max_width_px: float,
) -> str:
    """Wrap CJK prose using the renderer's real glyph widths, not char counts."""
    if max_width_px <= 0:
        raise ValueError("Text box width must be positive")

    wrapped: list[str] = []
    for paragraph in value.split("\n"):
        if not paragraph:
            wrapped.append("")
            continue
        line = ""
        for char in paragraph:
            candidate = line + char
            width, _, _ = renderer.get_text_width_height_descent(
                candidate, font, ismath=False
            )
            if line and width > max_width_px:
                wrapped.append(line.rstrip())
                line = char.lstrip()
            else:
                line = candidate
        wrapped.append(line.rstrip())
    return "\n".join(wrapped)


def bounded_text(
    ax: Axes,
    value: str,
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    fontsize: float,
    min_fontsize: float,
    color: str,
    fontweight: str = "normal",
    ha: str = "left",
    va: str = "top",
    linespacing: float = 1.2,
    wrap: bool = True,
) -> Text:
    """Draw text wholly inside a dedicated rectangle, shrinking if necessary.

    The layout guard measures rendered glyph boxes.  Measuring with the same
    renderer here makes every content-bearing text artist obey its assigned
    card/canvas bounds even when CJK glyphs are much wider than a Python
    character-count estimate.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Bounded text must be a non-empty string")
    if w <= 0 or h <= 0:
        raise ValueError("Bounded text box must have positive dimensions")

    fig = ax.figure
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    lower_left = ax.transData.transform((x, y))
    upper_right = ax.transData.transform((x + w, y + h))
    left = min(lower_left[0], upper_right[0])
    right = max(lower_left[0], upper_right[0])
    bottom = min(lower_left[1], upper_right[1])
    top = max(lower_left[1], upper_right[1])
    width_px = right - left

    if ha == "left":
        text_x = x
    elif ha == "center":
        text_x = x + w / 2
    elif ha == "right":
        text_x = x + w
    else:
        raise ValueError(f"Unsupported horizontal alignment: {ha}")
    if va == "top":
        text_y = y + h
    elif va == "center":
        text_y = y + h / 2
    elif va == "bottom":
        text_y = y
    else:
        raise ValueError(f"Unsupported vertical alignment: {va}")

    size = float(fontsize)
    while size + 1e-9 >= min_fontsize:
        font = FontProperties(
            family="Heiti TC",
            size=size,
            weight=fontweight,
        )
        rendered_value = (
            _wrap_to_pixel_width(value, renderer, font, width_px - 2)
            if wrap
            else value
        )
        artist = ax.text(
            text_x,
            text_y,
            rendered_value,
            fontproperties=font,
            color=color,
            ha=ha,
            va=va,
            linespacing=linespacing,
        )
        fig.canvas.draw()
        bounds = artist.get_window_extent(renderer=renderer)
        tolerance = 0.75
        fits = (
            bounds.x0 >= left - tolerance
            and bounds.x1 <= right + tolerance
            and bounds.y0 >= bottom - tolerance
            and bounds.y1 <= top + tolerance
        )
        if fits:
            return artist
        artist.remove()
        size -= 0.5

    raise RuntimeError(
        f"Text cannot fit its {w:.0f}x{h:.0f}px box above "
        f"{min_fontsize:.1f}pt: {value!r}"
    )


def new_canvas() -> tuple[Figure, Axes]:
    fig, ax = plt.subplots(figsize=(WIDTH / DPI, HEIGHT / DPI), dpi=DPI)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor(PAPER)
    ax.set_xlim(0, WIDTH)
    ax.set_ylim(0, HEIGHT)
    ax.axis("off")
    fig.subplots_adjust(left=0, right=1, bottom=0, top=1)
    return fig, ax


def rounded_box(
    ax: Axes,
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    face: str,
    edge: str = LINE,
    radius: float = 24,
    linewidth: float = 1.5,
) -> None:
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle=f"round,pad=0,rounding_size={radius}",
            facecolor=face,
            edgecolor=edge,
            linewidth=linewidth,
        )
    )


def footer(ax: Axes, experiment_id: str) -> None:
    if not experiment_id.startswith("k") or not experiment_id[1:].isdigit():
        raise ValueError(f"Unexpected experiment_id: {experiment_id!r}")
    label = f"資料來源：VolPred 第 {experiment_id[1:]} 號實驗（{experiment_id.upper()}）"
    ax.plot([80, 1520], [70, 70], color=LINE, linewidth=1.2)
    bounded_text(
        ax,
        label,
        80,
        12,
        1440,
        46,
        fontsize=15,
        min_fontsize=12,
        color=MUTED,
        va="center",
        wrap=False,
    )


def metric_card(
    ax: Axes,
    metric: BoundMetric,
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    face: str = PAPER,
    edge: str = LINE,
    accent: str = BLUE,
    value_size: float = 44,
) -> None:
    rounded_box(ax, x, y, w, h, face=face, edge=edge, radius=22)
    ax.add_patch(Rectangle((x, y), 8, h, facecolor=accent, edgecolor="none"))
    inner_x = x + 30
    inner_y = y + 18
    inner_w = w - 52
    inner_h = h - 36
    label_h = 42
    gap = 8

    bounded_text(
        ax,
        metric.label,
        inner_x,
        inner_y + inner_h - label_h,
        inner_w,
        label_h,
        fontsize=20,
        min_fontsize=12,
        color=MUTED,
        va="center",
    )

    remaining_h = inner_h - label_h - gap
    if metric.note:
        value_h = min(100, remaining_h * 0.56)
        note_h = remaining_h - value_h - gap
    else:
        value_h = remaining_h
        note_h = 0

    bounded_text(
        ax,
        metric.rendered,
        inner_x,
        inner_y + note_h + (gap if metric.note else 0),
        inner_w,
        value_h,
        fontsize=value_size,
        min_fontsize=20,
        fontweight="bold",
        color=INK,
        va="center",
        wrap=False,
    )
    if metric.note:
        bounded_text(
            ax,
            metric.note,
            inner_x,
            inner_y,
            inner_w,
            note_h,
            fontsize=12.5,
            min_fontsize=9,
            color=MUTED,
            va="center",
            linespacing=1.2,
        )


def draw_text_section(
    ax: Axes,
    block: dict[str, Any],
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    heading_size: float = 23,
    body_size: float = 19,
    color: str = INK,
) -> None:
    heading_h = min(46, h * 0.28)
    gap = 8
    bounded_text(
        ax,
        block["heading"],
        x,
        y + h - heading_h,
        w,
        heading_h,
        fontsize=heading_size,
        min_fontsize=13,
        fontweight="bold",
        color=color,
        va="center",
    )
    bounded_text(
        ax,
        "\n".join(block["body"]),
        x,
        y,
        w,
        h - heading_h - gap,
        fontsize=body_size,
        min_fontsize=10.5,
        color=color,
        linespacing=1.3,
    )


def save_panel(fig: Figure, filename: str) -> None:
    path = os.path.join(out_dir, filename)
    fig.savefig(path, dpi=DPI, facecolor=PAPER, edgecolor="none")
    plt.close(fig)


def render_concept(
    results: dict[str, Any], plan: dict[str, Any], experiment_id: str
) -> None:
    panel = panel_by_name(plan, "1_concept")
    intro = block_by_heading(panel, "排行榜的直覺")
    competitors = bind_metric(panel, "參賽模型", results)
    days = bind_metric(panel, "對答案的交易日", results)
    changes = bind_metric(panel, "七年裡冠軍換手", results)
    start = bind_metric(panel, "測試期起點", results)
    end = bind_metric(panel, "測試期終點", results)

    fig, ax = new_canvas()
    ax.add_patch(Rectangle((0, 825), WIDTH, 175, facecolor=NAVY, edgecolor="none"))
    bounded_text(
        ax,
        panel["title"],
        80,
        850,
        1170,
        125,
        fontsize=43,
        min_fontsize=28,
        fontweight="bold",
        color=PAPER,
        va="center",
        wrap=False,
    )
    for cx in (1335, 1410, 1485):
        ax.add_patch(Circle((cx, 913), 24, facecolor="none", edgecolor="#89A7C5", linewidth=3))
    ax.add_patch(
        FancyArrowPatch(
            (1360, 913),
            (1383, 913),
            arrowstyle="-|>",
            mutation_scale=18,
            color="#89A7C5",
            linewidth=2.5,
        )
    )
    ax.add_patch(
        FancyArrowPatch(
            (1435, 913),
            (1458, 913),
            arrowstyle="-|>",
            mutation_scale=18,
            color="#89A7C5",
            linewidth=2.5,
        )
    )

    draw_text_section(
        ax,
        intro,
        80,
        650,
        1440,
        145,
        heading_size=22,
        body_size=18.5,
    )

    metric_card(ax, competitors, 80, 392, 450, 225, face=SOFT_BLUE, accent=BLUE)
    metric_card(ax, days, 575, 392, 450, 225, face=SOFT_GRAY, accent=TEAL)
    metric_card(ax, changes, 1070, 392, 450, 225, face=SOFT_GOLD, accent=GOLD)
    metric_card(ax, start, 80, 145, 695, 190, face=PAPER, accent=NAVY, value_size=39)
    metric_card(ax, end, 825, 145, 695, 190, face=PAPER, accent=NAVY, value_size=39)

    footer(ax, experiment_id)
    save_panel(fig, "1_concept.png")


def render_method(
    results: dict[str, Any], plan: dict[str, Any], experiment_id: str
) -> None:
    panel = panel_by_name(plan, "2_method")
    question = block_by_heading(panel, "它問的是一句話")
    meaning = block_by_heading(panel, "留在集合裡的意思")
    bootstrap = bind_metric(panel, "重抽樣模擬", results)
    alpha = bind_metric(panel, "淘汰門檻", results)
    window = bind_metric(panel, "滾動視窗長度", results)
    stride = bind_metric(panel, "每次往前推", results)

    fig, ax = new_canvas()
    ax.add_patch(Rectangle((0, 855), WIDTH, 145, facecolor=NAVY, edgecolor="none"))
    bounded_text(
        ax,
        panel["title"],
        80,
        875,
        1250,
        105,
        fontsize=42,
        min_fontsize=28,
        fontweight="bold",
        color=PAPER,
        va="center",
        wrap=False,
    )
    bounded_text(
        ax,
        "MCS",
        1370,
        890,
        148,
        75,
        fontsize=24,
        min_fontsize=18,
        color="#9CB4CB",
        ha="right",
        va="center",
        wrap=False,
    )

    rounded_box(ax, 80, 620, 695, 195, face=SOFT_BLUE, edge="#C8D8E8", radius=18)
    rounded_box(ax, 825, 620, 695, 195, face=SOFT_TEAL, edge="#C9E0DC", radius=18)
    draw_text_section(ax, question, 112, 632, 631, 169, heading_size=21, body_size=17.2)
    draw_text_section(ax, meaning, 857, 632, 631, 169, heading_size=21, body_size=17.2)

    metric_card(ax, bootstrap, 80, 330, 335, 245, face=PAPER, accent=BLUE, value_size=38)
    metric_card(ax, alpha, 448, 330, 335, 245, face=PAPER, accent=RED, value_size=38)
    metric_card(ax, window, 816, 330, 335, 245, face=PAPER, accent=TEAL, value_size=36)
    metric_card(ax, stride, 1184, 330, 336, 245, face=PAPER, accent=GOLD, value_size=36)

    bounded_text(
        ax,
        "檢定流程",
        80,
        248,
        180,
        38,
        fontsize=18,
        min_fontsize=14,
        fontweight="bold",
        color=MUTED,
        va="center",
        wrap=False,
    )
    flow = [
        (80, 118, 390, "比較整批模型的預測誤差"),
        (605, 118, 390, "重抽樣衡量隨機性幅度"),
        (1130, 118, 390, "保留整批，或剔除最差再問"),
    ]
    for x, y, w, label in flow:
        rounded_box(ax, x, y, w, 112, face=SOFT_GRAY, edge=LINE, radius=16)
        bounded_text(
            ax,
            label,
            x + 24,
            y + 18,
            w - 48,
            76,
            fontsize=18,
            min_fontsize=12,
            color=INK,
            ha="center",
            va="center",
            linespacing=1.15,
        )
    for x1, x2 in ((470, 605), (995, 1130)):
        ax.add_patch(
            FancyArrowPatch(
                (x1 + 20, 174),
                (x2 - 20, 174),
                arrowstyle="-|>",
                mutation_scale=18,
                color=BLUE,
                linewidth=2.2,
            )
        )

    footer(ax, experiment_id)
    save_panel(fig, "2_method.png")


def render_results(
    results: dict[str, Any], plan: dict[str, Any], experiment_id: str
) -> None:
    panel = panel_by_name(plan, "3_results")
    labels = [
        "全期存活模型",
        "全期終止統計量",
        "高波動存活模型",
        "高波動終止統計量",
        "中波動存活模型",
        "中波動終止統計量",
        "低波動存活模型",
        "低波動終止統計量",
    ]
    metrics = [bind_metric(panel, label, results) for label in labels]

    fig, ax = new_canvas()
    bounded_text(
        ax,
        panel["title"],
        80,
        890,
        940,
        88,
        fontsize=43,
        min_fontsize=28,
        fontweight="bold",
        color=INK,
        va="center",
        wrap=False,
    )
    bounded_text(
        ax,
        "全期與三種波動狀態",
        1080,
        900,
        440,
        68,
        fontsize=18,
        min_fontsize=13,
        color=MUTED,
        ha="right",
        va="center",
        wrap=False,
    )
    ax.plot([80, 1520], [875, 875], color=NAVY, linewidth=5)

    xs = [80, 450, 820, 1190]
    ys = [500, 155]
    faces = [SOFT_BLUE, SOFT_GRAY, SOFT_RED, SOFT_RED, SOFT_TEAL, SOFT_TEAL, SOFT_GOLD, SOFT_GOLD]
    accents = [BLUE, NAVY, RED, RED, TEAL, TEAL, GOLD, GOLD]
    for index, metric in enumerate(metrics):
        row = index // 4
        col = index % 4
        metric_card(
            ax,
            metric,
            xs[col],
            ys[row],
            330,
            305,
            face=faces[index],
            edge="none",
            accent=accents[index],
            value_size=47,
        )

    footer(ax, experiment_id)
    save_panel(fig, "3_results.png")


def render_takeaway(
    results: dict[str, Any], plan: dict[str, Any], experiment_id: str
) -> None:
    panel = panel_by_name(plan, "4_takeaway")
    questions = block_by_heading(panel, "下次看到排行榜，問三件事")
    boundaries = block_by_heading(panel, "其他邊界")
    recession_t = bind_metric(panel, "衰退期樣本", results)
    recession_m = bind_metric(panel, "衰退期存活模型", results)
    expansion_t = bind_metric(panel, "擴張期樣本", results)
    expansion_m = bind_metric(panel, "擴張期存活模型", results)

    fig, ax = new_canvas()
    ax.add_patch(Rectangle((80, 872), 18, 86, facecolor=GOLD, edgecolor="none"))
    bounded_text(
        ax,
        panel["title"],
        128,
        872,
        1392,
        86,
        fontsize=42,
        min_fontsize=27,
        fontweight="bold",
        color=INK,
        va="center",
        wrap=False,
    )
    ax.plot([80, 1520], [842, 842], color=LINE, linewidth=1.5)

    bounded_text(
        ax,
        questions["heading"],
        80,
        770,
        740,
        42,
        fontsize=24,
        min_fontsize=16,
        fontweight="bold",
        color=NAVY,
        va="center",
        wrap=False,
    )
    question_colors = [SOFT_BLUE, SOFT_TEAL, SOFT_GOLD]
    question_marks = ["一", "二", "三"]
    question_y = [654, 526, 398]
    for mark, sentence, y, face in zip(question_marks, questions["body"], question_y, question_colors):
        rounded_box(ax, 80, y, 740, 104, face=face, edge="none", radius=16)
        bounded_text(
            ax,
            mark,
            108,
            y + 24,
            48,
            56,
            fontsize=25,
            min_fontsize=18,
            fontweight="bold",
            color=NAVY,
            ha="center",
            va="center",
            wrap=False,
        )
        bounded_text(
            ax,
            sentence,
            178,
            y + 15,
            610,
            74,
            fontsize=19,
            min_fontsize=11,
            color=INK,
            va="center",
            linespacing=1.15,
        )

    rounded_box(ax, 875, 515, 645, 282, face=SOFT_RED, edge="#E9C9C4", radius=22)
    bounded_text(
        ax,
        recession_t.label,
        915,
        730,
        270,
        42,
        fontsize=21,
        min_fontsize=14,
        fontweight="bold",
        color=RED,
        va="center",
    )
    bounded_text(
        ax,
        recession_t.rendered,
        915,
        638,
        270,
        80,
        fontsize=52,
        min_fontsize=25,
        fontweight="bold",
        color=INK,
        va="center",
        wrap=False,
    )
    bounded_text(
        ax,
        recession_m.label,
        1230,
        730,
        250,
        42,
        fontsize=19,
        min_fontsize=13,
        color=MUTED,
        va="center",
    )
    bounded_text(
        ax,
        recession_m.rendered,
        1230,
        638,
        250,
        80,
        fontsize=37,
        min_fontsize=22,
        fontweight="bold",
        color=INK,
        va="center",
        wrap=False,
    )
    if recession_t.note is None:
        raise KeyError("衰退期樣本 note")
    bounded_text(
        ax,
        recession_t.note,
        915,
        535,
        565,
        82,
        fontsize=13,
        min_fontsize=10,
        color=RED,
        va="center",
        linespacing=1.2,
    )

    rounded_box(ax, 875, 340, 645, 140, face=SOFT_GRAY, edge=LINE, radius=18)
    bounded_text(
        ax,
        expansion_t.label,
        915,
        420,
        250,
        38,
        fontsize=18,
        min_fontsize=12,
        color=MUTED,
        va="center",
    )
    bounded_text(
        ax,
        expansion_t.rendered,
        915,
        355,
        250,
        55,
        fontsize=33,
        min_fontsize=20,
        fontweight="bold",
        color=INK,
        va="center",
        wrap=False,
    )
    ax.plot([1195, 1195], [365, 455], color=LINE, linewidth=1.5)
    bounded_text(
        ax,
        expansion_m.label,
        1240,
        420,
        240,
        38,
        fontsize=18,
        min_fontsize=12,
        color=MUTED,
        va="center",
    )
    bounded_text(
        ax,
        expansion_m.rendered,
        1240,
        355,
        240,
        55,
        fontsize=33,
        min_fontsize=20,
        fontweight="bold",
        color=INK,
        va="center",
        wrap=False,
    )

    rounded_box(ax, 80, 112, 1440, 190, face=NAVY, edge=NAVY, radius=20)
    bounded_text(
        ax,
        boundaries["heading"],
        118,
        244,
        1364,
        38,
        fontsize=22,
        min_fontsize=15,
        fontweight="bold",
        color=PAPER,
        va="center",
        wrap=False,
    )
    bounded_text(
        ax,
        "\n".join(boundaries["body"]),
        118,
        134,
        1364,
        94,
        fontsize=18,
        min_fontsize=11,
        color="#E6EDF4",
        linespacing=1.25,
    )

    footer(ax, experiment_id)
    save_panel(fig, "4_takeaway.png")


def main() -> None:
    os.makedirs(out_dir, exist_ok=True)

    results = load_json(RESULTS_PATH)
    plan = load_json(PLAN_PATH)
    # These prose files are part of the evidence package. Read them explicitly
    # so a missing or empty package fails before any output is written.
    require_nonempty_text(README_PATH)
    require_nonempty_text(ARTICLE_PATH)

    experiment_id = results.get("experiment_id")
    if not isinstance(experiment_id, str):
        raise KeyError("experiment_id")
    evidence = plan.get("evidence")
    if not isinstance(evidence, dict) or "k1583" not in evidence:
        raise KeyError("plan.evidence.k1583")

    render_concept(results, plan, experiment_id)
    render_method(results, plan, experiment_id)
    render_results(results, plan, experiment_id)
    render_takeaway(results, plan, experiment_id)


if __name__ == "__main__":
    main()
