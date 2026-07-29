#!/usr/bin/env python3
"""Render the four data-bound PNG panels for the mile_35863986 lazypack."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyBboxPatch, Rectangle


README_PATH = Path("/Users/yhlai0911/volpred-research/experiments/k781/README.md")
PLAN_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_35863986/runs/lazypack-mile_35863986/plan.json"
)
RESULTS_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k781/k781_mvf_results.json"
)
ARTICLE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_35863986/runs/lazypack-mile_35863986/panels/mile_35863986_article.md"
)
OUT_DIR = (
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_35863986/runs/lazypack-mile_35863986/panels"
)

WIDTH_PX = 1600
HEIGHT_PX = 1000
DPI = 150

NAVY = "#12263A"
INK = "#1E2933"
MUTED = "#5E6B78"
LINE = "#D9E1E8"
PAPER = "#F7F9FB"
WHITE = "#FFFFFF"
BLUE = "#2367A8"
BLUE_SOFT = "#E7F0F8"
TEAL = "#167D7F"
TEAL_SOFT = "#E1F1F0"
GOLD = "#B17A22"
GOLD_SOFT = "#F7EDD8"
GREEN = "#2E7D5A"
GREEN_SOFT = "#E3F1E9"
RED = "#A84444"
RED_SOFT = "#F6E5E5"

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False


def load_evidence() -> tuple[dict[str, Any], dict[str, Any]]:
    """Load every requested evidence file and return the two structured sources."""
    # Reading the prose evidence is intentional: a missing evidence package must fail.
    README_PATH.read_text(encoding="utf-8")
    ARTICLE_PATH.read_text(encoding="utf-8")
    with PLAN_PATH.open("r", encoding="utf-8") as handle:
        plan = json.load(handle)
    with RESULTS_PATH.open("r", encoding="utf-8") as handle:
        results = json.load(handle)
    if not isinstance(plan, dict) or not isinstance(results, dict):
        raise TypeError("plan.json and results.json must both contain JSON objects")
    return plan, results


def json_pointer(document: Any, pointer: str) -> Any:
    """Resolve an RFC 6901-style pointer, raising on every missing field."""
    if not pointer.startswith("/"):
        raise ValueError(f"JSON pointer must begin with '/': {pointer}")
    value = document
    for raw_token in pointer.split("/")[1:]:
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(value, dict):
            if token not in value:
                raise KeyError(f"Missing evidence field: {pointer}")
            value = value[token]
        elif isinstance(value, list):
            try:
                index = int(token)
                value = value[index]
            except (ValueError, IndexError) as exc:
                raise KeyError(f"Missing evidence field: {pointer}") from exc
        else:
            raise KeyError(f"Cannot descend into evidence field: {pointer}")
    return value


def format_value(value: Any, spec: dict[str, Any]) -> str:
    """Format a plan-bound value without weakening its type contract."""
    kind = spec["kind"]
    suffix = spec.get("suffix", "")
    if kind == "text":
        if not isinstance(value, str):
            raise TypeError(f"Expected text evidence, got {type(value).__name__}")
        return value + suffix
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"Expected numeric evidence, got {type(value).__name__}")
    if kind == "integer":
        if isinstance(value, float) and not value.is_integer():
            raise ValueError(f"Expected integer evidence, got {value}")
        return f"{int(value):d}{suffix}"
    digits = int(spec["digits"])
    if kind == "number":
        return f"{value:.{digits}f}{suffix}"
    if kind == "percent":
        return f"{value * 100:.{digits}f}%{suffix}"
    raise ValueError(f"Unsupported value format: {kind}")


def metric_value(block: dict[str, Any], results: dict[str, Any]) -> str:
    value_spec = block["value"]
    if value_spec["source"] != "results":
        raise KeyError(f"Unsupported evidence source: {value_spec['source']}")
    raw = json_pointer(results, value_spec["path"])
    return format_value(raw, value_spec["format"])


def _wrap_artist_to_width(
    artist: plt.Text, text: str, renderer: Any, max_width_px: float
) -> str:
    """Wrap text against the real Heiti TC glyph widths, not character counts."""
    output: list[str] = []
    for paragraph in text.split("\n"):
        if not paragraph:
            output.append("")
            continue
        line = ""
        for character in paragraph:
            candidate = line + character
            artist.set_text(candidate)
            if line and artist.get_window_extent(renderer).width > max_width_px:
                output.append(line.rstrip())
                line = character.lstrip()
            else:
                line = candidate
        output.append(line.rstrip())
    return "\n".join(output)


def draw_fitted_text(
    ax: plt.Axes,
    text: str,
    box: tuple[float, float, float, float],
    *,
    fontsize: float,
    color: str,
    fontweight: str = "normal",
    ha: str = "left",
    va: str = "top",
    linespacing: float = 1.2,
    min_fontsize: float = 6.0,
    wrap: bool = True,
) -> plt.Text:
    """Draw text wholly inside an axes-coordinate box, shrinking when necessary."""
    x, y, w, h = box
    if w <= 0 or h <= 0:
        raise ValueError(f"Text box must have positive dimensions: {box}")

    if ha == "left":
        anchor_x = x
    elif ha == "center":
        anchor_x = x + w / 2
    elif ha == "right":
        anchor_x = x + w
    else:
        raise ValueError(f"Unsupported horizontal alignment: {ha}")

    if va == "top":
        anchor_y = y + h
    elif va == "center":
        anchor_y = y + h / 2
    elif va == "bottom":
        anchor_y = y
    else:
        raise ValueError(f"Unsupported vertical alignment: {va}")

    artist = ax.text(
        anchor_x,
        anchor_y,
        "",
        transform=ax.transAxes,
        ha=ha,
        va=va,
        fontsize=fontsize,
        fontweight=fontweight,
        color=color,
        linespacing=linespacing,
    )
    renderer = ax.figure.canvas.get_renderer()
    lower_left = ax.transAxes.transform((x, y))
    upper_right = ax.transAxes.transform((x + w, y + h))
    max_width_px = upper_right[0] - lower_left[0]
    max_height_px = upper_right[1] - lower_left[1]

    size = fontsize
    while size >= min_fontsize:
        artist.set_fontsize(size)
        fitted = (
            _wrap_artist_to_width(artist, text, renderer, max_width_px)
            if wrap
            else text
        )
        artist.set_text(fitted)
        extent = artist.get_window_extent(renderer)
        if (
            extent.width <= max_width_px + 0.5
            and extent.height <= max_height_px + 0.5
            and extent.x0 >= lower_left[0] - 0.5
            and extent.x1 <= upper_right[0] + 0.5
            and extent.y0 >= lower_left[1] - 0.5
            and extent.y1 <= upper_right[1] + 0.5
        ):
            return artist
        size -= 0.5

    artist.remove()
    raise ValueError(f"Text cannot fit safely inside its assigned box: {text!r}")


def add_round_rect(
    ax: plt.Axes,
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    face: str = WHITE,
    edge: str = LINE,
    radius: float = 0.018,
    linewidth: float = 1.0,
) -> None:
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle=f"round,pad=0.008,rounding_size={radius}",
            facecolor=face,
            edgecolor=edge,
            linewidth=linewidth,
            transform=ax.transAxes,
            clip_on=False,
        )
    )


def draw_header(ax: plt.Axes, title: str, *, dark: bool = False) -> None:
    if dark:
        ax.add_patch(
            Rectangle(
                (0, 0.855),
                1,
                0.145,
                transform=ax.transAxes,
                facecolor=NAVY,
                edgecolor="none",
            )
        )
        color = WHITE
    else:
        color = NAVY
        ax.plot([0.055, 0.945], [0.852, 0.852], color=LINE, lw=1.5)
    draw_fitted_text(
        ax,
        title,
        (0.055, 0.875, 0.89, 0.10),
        fontsize=24,
        fontweight="bold",
        color=color,
        va="center",
        linespacing=1.1,
        min_fontsize=18,
    )


def draw_footer(ax: plt.Axes, source_label: str) -> None:
    ax.plot([0.055, 0.945], [0.055, 0.055], color=LINE, lw=1.0)
    draw_fitted_text(
        ax,
        f"資料來源｜{source_label}",
        (0.055, 0.008, 0.89, 0.038),
        fontsize=8.5,
        color=MUTED,
        va="center",
        min_fontsize=7,
    )


def draw_text_card(
    ax: plt.Axes,
    block: dict[str, Any],
    box: tuple[float, float, float, float],
    *,
    accent: str = BLUE,
    face: str = WHITE,
    body_size: float = 10.5,
) -> None:
    x, y, w, h = box
    add_round_rect(ax, x, y, w, h, face=face)
    ax.add_patch(
        Rectangle(
            (x, y),
            0.008,
            h,
            transform=ax.transAxes,
            facecolor=accent,
            edgecolor="none",
        )
    )
    horizontal_pad = min(0.025, w * 0.08)
    vertical_pad = min(0.022, h * 0.10)
    heading_height = min(0.045, h * 0.22)
    heading_y = y + h - vertical_pad - heading_height
    body_top = heading_y - min(0.010, h * 0.06)
    draw_fitted_text(
        ax,
        block["heading"],
        (
            x + horizontal_pad,
            heading_y,
            w - horizontal_pad - 0.018,
            heading_height,
        ),
        fontsize=13,
        fontweight="bold",
        color=NAVY,
        min_fontsize=10,
    )
    body = "\n".join(block["body"])
    draw_fitted_text(
        ax,
        body,
        (
            x + horizontal_pad,
            y + vertical_pad,
            w - horizontal_pad - 0.018,
            body_top - y - vertical_pad,
        ),
        fontsize=body_size,
        color=INK,
        linespacing=1.45,
        min_fontsize=7.5,
    )


def draw_metric_card(
    ax: plt.Axes,
    label: str,
    value: str,
    box: tuple[float, float, float, float],
    *,
    accent: str = BLUE,
    face: str = WHITE,
    value_size: float = 23,
) -> None:
    x, y, w, h = box
    add_round_rect(ax, x, y, w, h, face=face)
    horizontal_pad = min(0.02, w * 0.08)
    draw_fitted_text(
        ax,
        label,
        (
            x + horizontal_pad,
            y + h * 0.48,
            w - horizontal_pad - 0.015,
            h * 0.38,
        ),
        fontsize=9.5,
        color=MUTED,
        linespacing=1.25,
        min_fontsize=7,
    )
    draw_fitted_text(
        ax,
        value,
        (
            x + horizontal_pad,
            y + 0.022,
            w - horizontal_pad - 0.015,
            h * 0.31,
        ),
        fontsize=value_size,
        fontweight="bold",
        color=accent,
        va="bottom",
        min_fontsize=10,
        wrap=False,
    )


def panel_source_label(panel: dict[str, Any], plan: dict[str, Any]) -> str:
    labels: list[str] = []
    for source in panel["sources"]:
        evidence = plan["evidence"][source]
        label = evidence["label"]
        if not isinstance(label, str) or not label:
            raise ValueError(f"Missing reader-facing evidence label for {source}")
        labels.append(label)
    return "；".join(labels)


def render_concept(
    panel: dict[str, Any], plan: dict[str, Any], results: dict[str, Any]
) -> plt.Figure:
    fig, ax = new_canvas(PAPER)
    draw_header(ax, panel["title"], dark=True)
    texts = [block for block in panel["blocks"] if block["kind"] == "text"]
    metrics = [block for block in panel["blocks"] if block["kind"] == "metric"]
    if len(texts) != 3 or len(metrics) != 2:
        raise ValueError("Concept panel contract changed")

    draw_text_card(
        ax,
        texts[0],
        (0.055, 0.565, 0.275, 0.23),
        accent=GOLD,
        face=GOLD_SOFT,
    )
    draw_text_card(
        ax,
        texts[1],
        (0.36, 0.565, 0.585, 0.23),
        accent=TEAL,
        face=TEAL_SOFT,
    )

    draw_fitted_text(
        ax,
        "快速層的兩個反應零件",
        (0.055, 0.49, 0.58, 0.05),
        fontsize=12,
        fontweight="bold",
        color=NAVY,
        va="center",
        min_fontsize=10,
    )
    draw_metric_card(
        ax,
        metrics[0]["label"],
        metric_value(metrics[0], results),
        (0.055, 0.30, 0.275, 0.17),
        accent=BLUE,
        face=BLUE_SOFT,
        value_size=29,
    )
    draw_fitted_text(
        ax,
        "＋",
        (0.333, 0.35, 0.024, 0.07),
        ha="center",
        va="center",
        fontsize=26,
        color=MUTED,
        wrap=False,
        min_fontsize=18,
    )
    draw_metric_card(
        ax,
        metrics[1]["label"],
        metric_value(metrics[1], results),
        (0.36, 0.30, 0.275, 0.17),
        accent=TEAL,
        face=TEAL_SOFT,
        value_size=29,
    )
    draw_fitted_text(
        ax,
        "→",
        (0.638, 0.35, 0.024, 0.07),
        ha="center",
        va="center",
        fontsize=26,
        color=MUTED,
        wrap=False,
        min_fontsize=18,
    )
    draw_text_card(
        ax,
        texts[2],
        (0.68, 0.235, 0.265, 0.235),
        accent=RED,
        face=RED_SOFT,
        body_size=10,
    )

    ax.add_patch(
        FancyBboxPatch(
            (0.055, 0.105),
            0.58,
            0.12,
            boxstyle="round,pad=0.008,rounding_size=0.018",
            transform=ax.transAxes,
            facecolor=NAVY,
            edgecolor="none",
        )
    )
    draw_fitted_text(
        ax,
        "慢速水位線  ×  快速相對偏離  ＝  當天預測",
        (0.075, 0.125, 0.54, 0.08),
        ha="center",
        va="center",
        fontsize=17,
        fontweight="bold",
        color=WHITE,
        min_fontsize=12,
    )
    draw_footer(ax, panel_source_label(panel, plan))
    return fig


def render_method(
    panel: dict[str, Any], plan: dict[str, Any], results: dict[str, Any]
) -> plt.Figure:
    fig, ax = new_canvas(WHITE)
    draw_header(ax, panel["title"])
    text_blocks = [block for block in panel["blocks"] if block["kind"] == "text"]
    metrics = [block for block in panel["blocks"] if block["kind"] == "metric"]
    if len(text_blocks) != 1 or len(metrics) != 9:
        raise ValueError("Method panel contract changed")

    draw_text_card(
        ax,
        text_blocks[0],
        (0.055, 0.57, 0.39, 0.225),
        accent=BLUE,
        face=BLUE_SOFT,
        body_size=10.2,
    )
    steps = ["只用過去資料", "往後預測一天", "對照實際震盪", "誤差越低越準"]
    start_x = 0.49
    for index, step in enumerate(steps):
        cx = start_x + index * 0.115
        ax.add_patch(
            Circle(
                (cx, 0.69),
                0.033,
                transform=ax.transAxes,
                facecolor=TEAL if index < 3 else GOLD,
                edgecolor="none",
            )
        )
        draw_fitted_text(
            ax,
            str(index + 1),
            (cx - 0.023, 0.667, 0.046, 0.046),
            ha="center",
            va="center",
            fontsize=13,
            fontweight="bold",
            color=WHITE,
            wrap=False,
            min_fontsize=10,
        )
        draw_fitted_text(
            ax,
            step,
            (cx - 0.048, 0.58, 0.096, 0.065),
            ha="center",
            fontsize=9.5,
            color=INK,
            linespacing=1.25,
            min_fontsize=8,
        )
        if index < len(steps) - 1:
            ax.plot(
                [cx + 0.037, cx + 0.078],
                [0.69, 0.69],
                transform=ax.transAxes,
                color=LINE,
                lw=2,
            )

    boxes = [
        (0.055, 0.39, 0.27, 0.13),
        (0.345, 0.39, 0.27, 0.13),
        (0.635, 0.39, 0.31, 0.13),
        (0.055, 0.23, 0.27, 0.13),
        (0.345, 0.23, 0.27, 0.13),
        (0.635, 0.23, 0.31, 0.13),
        (0.055, 0.08, 0.27, 0.12),
        (0.345, 0.08, 0.27, 0.12),
        (0.635, 0.08, 0.31, 0.12),
    ]
    accents = [BLUE, BLUE, BLUE, TEAL, TEAL, TEAL, GOLD, GOLD, GOLD]
    faces = [PAPER, PAPER, PAPER, TEAL_SOFT, TEAL_SOFT, TEAL_SOFT, GOLD_SOFT, GOLD_SOFT, GOLD_SOFT]
    for block, box, accent, face in zip(metrics, boxes, accents, faces):
        value = metric_value(block, results)
        value_size = 15 if len(value) > 23 else 20
        draw_metric_card(
            ax,
            block["label"],
            value,
            box,
            accent=accent,
            face=face,
            value_size=value_size,
        )
    draw_footer(ax, panel_source_label(panel, plan))
    return fig


def render_results(
    panel: dict[str, Any], plan: dict[str, Any], results: dict[str, Any]
) -> plt.Figure:
    fig, ax = new_canvas(PAPER)
    draw_header(ax, panel["title"])
    texts = [block for block in panel["blocks"] if block["kind"] == "text"]
    metrics = [block for block in panel["blocks"] if block["kind"] == "metric"]
    if len(texts) != 1 or len(metrics) != 9:
        raise ValueError("Results panel contract changed")

    boxes = [
        (0.055, 0.66, 0.27, 0.15),
        (0.345, 0.66, 0.27, 0.15),
        (0.635, 0.66, 0.31, 0.15),
        (0.055, 0.455, 0.27, 0.16),
        (0.345, 0.455, 0.27, 0.16),
        (0.635, 0.455, 0.31, 0.16),
        (0.055, 0.265, 0.27, 0.15),
        (0.345, 0.265, 0.27, 0.15),
        (0.635, 0.265, 0.31, 0.15),
    ]
    accents = [GOLD, BLUE, RED, BLUE, BLUE, TEAL, GREEN, GREEN, RED]
    faces = [GOLD_SOFT, BLUE_SOFT, RED_SOFT, WHITE, WHITE, TEAL_SOFT, GREEN_SOFT, GREEN_SOFT, RED_SOFT]
    for block, box, accent, face in zip(metrics, boxes, accents, faces):
        draw_metric_card(
            ax,
            block["label"],
            metric_value(block, results),
            box,
            accent=accent,
            face=face,
            value_size=24,
        )

    draw_text_card(
        ax,
        texts[0],
        (0.055, 0.075, 0.89, 0.145),
        accent=NAVY,
        face=WHITE,
        body_size=9.5,
    )
    draw_footer(ax, panel_source_label(panel, plan))
    return fig


def render_takeaway(
    panel: dict[str, Any], plan: dict[str, Any], results: dict[str, Any]
) -> plt.Figure:
    fig, ax = new_canvas("#F5F1E9")
    draw_header(ax, panel["title"])
    texts = [block for block in panel["blocks"] if block["kind"] == "text"]
    metrics = [block for block in panel["blocks"] if block["kind"] == "metric"]
    if len(texts) != 2 or len(metrics) != 3:
        raise ValueError("Takeaway panel contract changed")

    ax.add_patch(
        FancyBboxPatch(
            (0.055, 0.465),
            0.49,
            0.34,
            boxstyle="round,pad=0.012,rounding_size=0.025",
            transform=ax.transAxes,
            facecolor=NAVY,
            edgecolor="none",
        )
    )
    draw_fitted_text(
        ax,
        texts[0]["heading"],
        (0.085, 0.73, 0.43, 0.05),
        fontsize=14,
        fontweight="bold",
        color="#8FD4D1",
        min_fontsize=11,
    )
    draw_fitted_text(
        ax,
        "\n".join(texts[0]["body"]),
        (0.085, 0.555, 0.43, 0.155),
        fontsize=12.2,
        color=WHITE,
        linespacing=1.5,
        min_fontsize=8.5,
    )
    draw_fitted_text(
        ax,
        "維持現狀",
        (0.085, 0.485, 0.43, 0.05),
        ha="center",
        va="center",
        fontsize=28,
        fontweight="bold",
        color="#F3C86B",
        min_fontsize=20,
        wrap=False,
    )

    draw_metric_card(
        ax,
        metrics[0]["label"],
        metric_value(metrics[0], results),
        (0.585, 0.635, 0.36, 0.17),
        accent=GOLD,
        face=GOLD_SOFT,
        value_size=28,
    )
    draw_metric_card(
        ax,
        metrics[1]["label"],
        metric_value(metrics[1], results),
        (0.585, 0.435, 0.36, 0.17),
        accent=BLUE,
        face=BLUE_SOFT,
        value_size=28,
    )

    draw_text_card(
        ax,
        texts[1],
        (0.055, 0.145, 0.67, 0.255),
        accent=RED,
        face=WHITE,
        body_size=10.5,
    )
    draw_metric_card(
        ax,
        metrics[2]["label"],
        metric_value(metrics[2], results),
        (0.765, 0.195, 0.18, 0.155),
        accent=TEAL,
        face=TEAL_SOFT,
        value_size=24,
    )
    draw_fitted_text(
        ax,
        "一次完整實驗的計算成本",
        (0.765, 0.12, 0.18, 0.04),
        fontsize=8.5,
        color=MUTED,
        min_fontsize=7,
    )
    draw_footer(ax, panel_source_label(panel, plan))
    return fig


def new_canvas(background: str) -> tuple[plt.Figure, plt.Axes]:
    fig = plt.figure(
        figsize=(WIDTH_PX / DPI, HEIGHT_PX / DPI),
        dpi=DPI,
        facecolor=background,
    )
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.set_facecolor(background)
    return fig, ax


def save_panel(fig: plt.Figure, panel: dict[str, Any]) -> None:
    output = os.path.join(OUT_DIR, f"{panel['name']}.png")
    fig.savefig(
        output,
        dpi=DPI,
        facecolor=fig.get_facecolor(),
        edgecolor="none",
        metadata={"Title": panel["title"], "Description": panel["alt"]},
    )
    plt.close(fig)


def main() -> None:
    plan, results = load_evidence()
    os.makedirs(OUT_DIR, exist_ok=True)
    renderers = {
        "1_concept": render_concept,
        "2_method": render_method,
        "3_results": render_results,
        "4_takeaway": render_takeaway,
    }
    panels = plan["panels"]
    if not isinstance(panels, list):
        raise TypeError("plan.panels must be a list")
    by_name = {panel["name"]: panel for panel in panels}
    if set(by_name) != set(renderers):
        raise ValueError(
            f"Expected panels {sorted(renderers)}, got {sorted(by_name)}"
        )
    for name, renderer in renderers.items():
        panel = by_name[name]
        fig = renderer(panel, plan, results)
        save_panel(fig, panel)


if __name__ == "__main__":
    main()
