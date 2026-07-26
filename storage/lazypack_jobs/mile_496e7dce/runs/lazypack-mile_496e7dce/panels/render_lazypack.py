#!/usr/bin/env python3
"""Render the four data-bound PNG panels for the mile_496e7dce lazy pack."""

from __future__ import annotations

import json
import os
import textwrap
from pathlib import Path
from typing import Any, Iterable

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle


PLAN_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_496e7dce/runs/lazypack-mile_496e7dce/plan.json"
)
RESULTS_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1711/k1711_results.json"
)
ARTICLE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_496e7dce/runs/lazypack-mile_496e7dce/panels/"
    "mile_496e7dce_article.md"
)
out_dir = (
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_496e7dce/runs/lazypack-mile_496e7dce/panels"
)

WIDTH = 1600
HEIGHT = 1000
DPI = 150

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False

INK = "#142337"
MUTED = "#526173"
FAINT = "#7E8A99"
NAVY = "#102A43"
BLUE = "#246B9E"
BLUE_SOFT = "#E7F0F7"
TEAL = "#147D79"
TEAL_SOFT = "#E3F2F0"
GREEN = "#247553"
GREEN_SOFT = "#E4F1EA"
RED = "#B74D4D"
RED_SOFT = "#F7E9E7"
AMBER = "#A66A20"
AMBER_SOFT = "#F7EEDC"
PAPER = "#F7F4ED"
CARD = "#FFFFFF"
LINE = "#D8E0E8"


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_evidence() -> tuple[dict[str, Any], dict[str, Any], str]:
    """Load every path in the supplied evidence package and fail loudly."""
    plan = load_json(PLAN_PATH)
    results = load_json(RESULTS_PATH)
    article = ARTICLE_PATH.read_text(encoding="utf-8")
    if not article.strip():
        raise ValueError(f"Article evidence is empty: {ARTICLE_PATH}")

    evidence = plan["evidence"]
    result_spec = evidence["results"]
    label = result_spec["label"]
    if not isinstance(label, str) or not label.strip():
        raise TypeError("plan.evidence.results.label must be a non-empty string")

    panels = plan["panels"]
    if not isinstance(panels, list):
        raise TypeError("plan.panels must be a list")
    return plan, results, article


def resolve_pointer(document: Any, pointer: str) -> Any:
    """Resolve an RFC 6901-style JSON Pointer, raising on any missing field."""
    if pointer == "":
        return document
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValueError(f"Invalid JSON Pointer: {pointer!r}")

    current = document
    for raw_token in pointer[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            if token not in current:
                raise KeyError(f"Missing JSON field at {pointer!r}: {token!r}")
            current = current[token]
        elif isinstance(current, list):
            try:
                index = int(token)
                current = current[index]
            except (ValueError, IndexError) as exc:
                raise KeyError(
                    f"Missing JSON list item at {pointer!r}: {token!r}"
                ) from exc
        else:
            raise KeyError(
                f"Cannot descend through {type(current).__name__} at {pointer!r}"
            )
    return current


def require_panel(plan: dict[str, Any], name: str) -> dict[str, Any]:
    matches = [panel for panel in plan["panels"] if panel["name"] == name]
    if len(matches) != 1:
        raise KeyError(f"Expected exactly one panel named {name!r}")
    panel = matches[0]
    if panel["sources"] != ["results"]:
        raise ValueError(f"{name}: only the strict results source is supported")
    return panel


def require_block(
    panel: dict[str, Any], *, kind: str, key: str, value: str
) -> dict[str, Any]:
    matches = [
        block
        for block in panel["blocks"]
        if block["kind"] == kind and block[key] == value
    ]
    if len(matches) != 1:
        raise KeyError(
            f"{panel['name']}: expected one {kind!r} block with {key}={value!r}"
        )
    return matches[0]


def format_metric(block: dict[str, Any], results: dict[str, Any]) -> str:
    spec = block["value"]
    if spec["source"] != "results":
        raise ValueError(f"Unsupported metric source: {spec['source']!r}")
    value = resolve_pointer(results, spec["path"])
    formatting = spec["format"]
    kind = formatting["kind"]

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(
            f"Expected numeric evidence at {spec['path']!r}, "
            f"got {type(value).__name__}"
        )
    if kind == "integer":
        if isinstance(value, float) and not value.is_integer():
            raise ValueError(f"Expected integer evidence at {spec['path']!r}")
        rendered = f"{int(value):,}"
    elif kind == "number":
        digits = formatting["digits"]
        if not isinstance(digits, int) or digits < 0:
            raise ValueError(f"Invalid decimal precision: {digits!r}")
        rendered = f"{float(value):.{digits}f}"
    else:
        raise ValueError(f"Unsupported metric format kind: {kind!r}")
    return rendered + formatting.get("suffix", "")


def numeric_metric(block: dict[str, Any], results: dict[str, Any]) -> float:
    spec = block["value"]
    if spec["source"] != "results":
        raise ValueError(f"Unsupported metric source: {spec['source']!r}")
    value = resolve_pointer(results, spec["path"])
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"Expected numeric evidence at {spec['path']!r}")
    return float(value)


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


def bullet_text(items: Iterable[str], width: int) -> str:
    paragraphs: list[str] = []
    for item in items:
        paragraph = textwrap.fill(
            item,
            width=width,
            initial_indent="• ",
            subsequent_indent="  ",
            break_long_words=True,
            break_on_hyphens=False,
            replace_whitespace=False,
        )
        if paragraph:
            paragraphs.append(paragraph)
    return "\n".join(paragraphs)


def new_figure(background: str = CARD) -> plt.Figure:
    fig = plt.figure(
        figsize=(WIDTH / DPI, HEIGHT / DPI),
        dpi=DPI,
        facecolor=background,
    )
    return fig


def card(
    fig: plt.Figure,
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    facecolor: str = CARD,
    edgecolor: str = LINE,
    radius: float = 0.018,
    linewidth: float = 1.2,
) -> None:
    patch = FancyBboxPatch(
        (x, y),
        width,
        height,
        boxstyle=f"round,pad=0.008,rounding_size={radius}",
        transform=fig.transFigure,
        facecolor=facecolor,
        edgecolor=edgecolor,
        linewidth=linewidth,
        zorder=0,
    )
    fig.add_artist(patch)


def source_footer(fig: plt.Figure, source_label: str) -> None:
    fig.add_artist(
        Rectangle(
            (0.055, 0.077),
            0.89,
            0.0015,
            transform=fig.transFigure,
            facecolor=LINE,
            edgecolor="none",
        )
    )
    fig.text(
        0.06,
        0.043,
        f"資料來源：{source_label}",
        fontsize=9.8,
        color=MUTED,
        ha="left",
        va="center",
    )


def save_panel(fig: plt.Figure, panel: dict[str, Any]) -> None:
    os.makedirs(out_dir, exist_ok=True)
    output_path = os.path.join(out_dir, f"{panel['name']}.png")
    fig.savefig(
        output_path,
        dpi=DPI,
        facecolor=fig.get_facecolor(),
        metadata={
            "Title": panel["title"],
            "Description": panel["alt"],
        },
    )
    plt.close(fig)


def professional_text_card(
    fig: plt.Figure,
    block: dict[str, Any],
    x: float,
    y: float,
    width: float,
    height: float,
) -> None:
    card(fig, x, y, width, height, facecolor="#F8FAFC")
    fig.add_artist(
        Rectangle(
            (x, y),
            0.008,
            height,
            transform=fig.transFigure,
            facecolor=BLUE,
            edgecolor="none",
        )
    )
    fig.text(
        x + 0.03,
        y + height - 0.055,
        block["heading"],
        fontsize=17,
        fontweight="bold",
        color=INK,
        ha="left",
        va="top",
    )
    fig.text(
        x + 0.03,
        y + height - 0.115,
        bullet_text(block["body"], 28),
        fontsize=13.3,
        color=MUTED,
        ha="left",
        va="top",
        linespacing=1.45,
    )


def professional_metric_card(
    fig: plt.Figure,
    block: dict[str, Any],
    results: dict[str, Any],
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    color: str,
    soft_color: str,
) -> None:
    card(fig, x, y, width, height, facecolor=soft_color, edgecolor=soft_color)
    fig.text(
        x + 0.035,
        y + height - 0.055,
        wrapped(block["label"], 18),
        fontsize=13.5,
        fontweight="bold",
        color=INK,
        ha="left",
        va="top",
        linespacing=1.25,
    )
    fig.text(
        x + 0.035,
        y + 0.055,
        format_metric(block, results),
        fontsize=31,
        fontweight="bold",
        color=color,
        ha="left",
        va="bottom",
    )


def render_question(
    plan: dict[str, Any], results: dict[str, Any], source_label: str
) -> None:
    panel = require_panel(plan, "panel_question")
    popular = require_block(panel, kind="text", key="heading", value="熱門主張")
    framing = require_block(panel, kind="text", key="heading", value="我們的問法")
    dates = require_block(
        panel, kind="metric", key="label", value="跨市場共同交易日"
    )
    spy_count = require_block(
        panel, kind="metric", key="label", value="SPY 評分筆數"
    )

    fig = new_figure()
    fig.add_artist(
        Rectangle(
            (0, 0.79),
            1,
            0.21,
            transform=fig.transFigure,
            facecolor=NAVY,
            edgecolor="none",
        )
    )
    fig.text(
        0.06,
        0.925,
        panel["title"],
        fontsize=27,
        fontweight="bold",
        color="white",
        ha="left",
        va="center",
    )
    fig.text(
        0.06,
        0.845,
        wrapped(panel["alt"], 47),
        fontsize=13.5,
        color="#D9E6F2",
        ha="left",
        va="center",
        linespacing=1.25,
    )

    professional_text_card(fig, popular, 0.06, 0.505, 0.54, 0.205)
    professional_text_card(fig, framing, 0.06, 0.145, 0.54, 0.30)
    professional_metric_card(
        fig,
        dates,
        results,
        0.65,
        0.505,
        0.29,
        0.205,
        color=BLUE,
        soft_color=BLUE_SOFT,
    )
    professional_metric_card(
        fig,
        spy_count,
        results,
        0.65,
        0.145,
        0.29,
        0.30,
        color=TEAL,
        soft_color=TEAL_SOFT,
    )
    source_footer(fig, source_label)
    save_panel(fig, panel)


def method_text_card(
    fig: plt.Figure,
    block: dict[str, Any],
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    accent: str,
    badge: str,
) -> None:
    card(fig, x, y, width, height, facecolor=CARD)
    fig.add_artist(
        FancyBboxPatch(
            (x + 0.025, y + height - 0.075),
            0.09,
            0.04,
            boxstyle="round,pad=0.004,rounding_size=0.012",
            transform=fig.transFigure,
            facecolor=accent,
            edgecolor="none",
        )
    )
    fig.text(
        x + 0.07,
        y + height - 0.055,
        badge,
        fontsize=10.5,
        fontweight="bold",
        color="white",
        ha="center",
        va="center",
    )
    fig.text(
        x + 0.025,
        y + height - 0.11,
        block["heading"],
        fontsize=18,
        fontweight="bold",
        color=INK,
        ha="left",
        va="top",
    )
    fig.text(
        x + 0.025,
        y + height - 0.17,
        bullet_text(block["body"], 22),
        fontsize=12.5,
        color=MUTED,
        ha="left",
        va="top",
        linespacing=1.32,
    )


def method_metric(
    fig: plt.Figure,
    block: dict[str, Any],
    results: dict[str, Any],
    x: float,
    y: float,
    width: float,
) -> None:
    card(fig, x, y, width, 0.19, facecolor="#F8FAFC")
    fig.text(
        x + 0.03,
        y + 0.135,
        wrapped(block["label"], 25),
        fontsize=13.2,
        fontweight="bold",
        color=INK,
        ha="left",
        va="center",
        linespacing=1.2,
    )
    fig.text(
        x + width - 0.03,
        y + 0.05,
        format_metric(block, results),
        fontsize=27,
        fontweight="bold",
        color=BLUE,
        ha="right",
        va="bottom",
    )


def render_method(
    plan: dict[str, Any], results: dict[str, Any], source_label: str
) -> None:
    panel = require_panel(plan, "panel_method")
    camps = require_block(panel, kind="text", key="heading", value="兩邊陣營")
    scoring = require_block(panel, kind="text", key="heading", value="評分")
    tw_count = require_block(
        panel, kind="metric", key="label", value="台股 0050.TW 評分筆數"
    )
    tx_count = require_block(
        panel, kind="metric", key="label", value="台指期 TX 評分筆數"
    )

    fig = new_figure("#F6F8FA")
    fig.add_artist(
        Rectangle(
            (0.055, 0.825),
            0.012,
            0.115,
            transform=fig.transFigure,
            facecolor=TEAL,
            edgecolor="none",
        )
    )
    fig.text(
        0.085,
        0.915,
        panel["title"],
        fontsize=27,
        fontweight="bold",
        color=INK,
        ha="left",
        va="center",
    )
    fig.text(
        0.085,
        0.85,
        wrapped(panel["alt"], 53),
        fontsize=13.5,
        color=MUTED,
        ha="left",
        va="center",
    )
    fig.text(
        0.06,
        0.772,
        "方法框架",
        fontsize=11.5,
        fontweight="bold",
        color=TEAL,
        ha="left",
        va="center",
    )

    method_text_card(
        fig, camps, 0.06, 0.435, 0.405, 0.295, accent=BLUE, badge="候選模型池"
    )
    fig.text(
        0.5,
        0.585,
        "→",
        fontsize=25,
        fontweight="bold",
        color=FAINT,
        ha="center",
        va="center",
    )
    method_text_card(
        fig, scoring, 0.535, 0.435, 0.405, 0.295, accent=TEAL, badge="同場評分"
    )

    fig.text(
        0.06,
        0.385,
        "可比較的樣本",
        fontsize=11.5,
        fontweight="bold",
        color=TEAL,
        ha="left",
        va="center",
    )
    method_metric(fig, tw_count, results, 0.06, 0.145, 0.405)
    method_metric(fig, tx_count, results, 0.535, 0.145, 0.405)
    source_footer(fig, source_label)
    save_panel(fig, panel)


def bento_metric(
    fig: plt.Figure,
    block: dict[str, Any],
    results: dict[str, Any],
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    accent: str,
    soft: str,
    maximum: float,
) -> None:
    value = numeric_metric(block, results)
    card(fig, x, y, width, height, facecolor=soft, edgecolor=soft)
    fig.text(
        x + 0.025,
        y + height - 0.045,
        wrapped(block["label"], 19),
        fontsize=11.7,
        fontweight="bold",
        color=INK,
        ha="left",
        va="top",
        linespacing=1.16,
    )
    fig.text(
        x + 0.025,
        y + 0.075,
        format_metric(block, results),
        fontsize=27,
        fontweight="bold",
        color=accent,
        ha="left",
        va="bottom",
    )
    bar_x = x + 0.025
    bar_y = y + 0.035
    bar_width = width - 0.05
    fig.add_artist(
        FancyBboxPatch(
            (bar_x, bar_y),
            bar_width,
            0.012,
            boxstyle="round,pad=0,rounding_size=0.006",
            transform=fig.transFigure,
            facecolor="#D5DEE7",
            edgecolor="none",
        )
    )
    fig.add_artist(
        FancyBboxPatch(
            (bar_x, bar_y),
            bar_width * (value / maximum),
            0.012,
            boxstyle="round,pad=0,rounding_size=0.006",
            transform=fig.transFigure,
            facecolor=accent,
            edgecolor="none",
        )
    )


def render_results(
    plan: dict[str, Any], results: dict[str, Any], source_label: str
) -> None:
    panel = require_panel(plan, "panel_results")
    har_a = require_block(
        panel,
        kind="metric",
        key="label",
        value="最佳模型 HAR-A（QLIKE，越低越好）",
    )
    timesfm = require_block(
        panel, kind="metric", key="label", value="TimesFM 裸用"
    )
    timesfm_mz = require_block(
        panel, kind="metric", key="label", value="TimesFM 校準後"
    )
    har = require_block(panel, kind="metric", key="label", value="老公式 HAR")
    reading = require_block(panel, kind="text", key="heading", value="怎麼讀")
    metric_blocks = [har_a, timesfm, timesfm_mz, har]
    maximum = max(numeric_metric(block, results) for block in metric_blocks)
    if maximum <= 0:
        raise ValueError("SPY QLIKE values must be positive")

    fig = new_figure("#F3F6F9")
    fig.add_artist(
        Rectangle(
            (0, 0.805),
            1,
            0.195,
            transform=fig.transFigure,
            facecolor=INK,
            edgecolor="none",
        )
    )
    fig.text(
        0.06,
        0.925,
        panel["title"],
        fontsize=27,
        fontweight="bold",
        color="white",
        ha="left",
        va="center",
    )
    fig.text(
        0.06,
        0.855,
        wrapped(panel["alt"], 53),
        fontsize=13.5,
        color="#DDE7F0",
        ha="left",
        va="center",
    )

    bento_metric(
        fig,
        har_a,
        results,
        0.06,
        0.49,
        0.265,
        0.245,
        accent=GREEN,
        soft=GREEN_SOFT,
        maximum=maximum,
    )
    bento_metric(
        fig,
        timesfm,
        results,
        0.355,
        0.49,
        0.265,
        0.245,
        accent=RED,
        soft=RED_SOFT,
        maximum=maximum,
    )
    bento_metric(
        fig,
        timesfm_mz,
        results,
        0.06,
        0.16,
        0.265,
        0.245,
        accent=BLUE,
        soft=BLUE_SOFT,
        maximum=maximum,
    )
    bento_metric(
        fig,
        har,
        results,
        0.355,
        0.16,
        0.265,
        0.245,
        accent=TEAL,
        soft=TEAL_SOFT,
        maximum=maximum,
    )

    card(fig, 0.66, 0.16, 0.28, 0.575, facecolor=CARD)
    fig.text(
        0.69,
        0.675,
        reading["heading"],
        fontsize=19,
        fontweight="bold",
        color=INK,
        ha="left",
        va="top",
    )
    fig.text(
        0.69,
        0.60,
        bullet_text(reading["body"], 14),
        fontsize=13,
        color=MUTED,
        ha="left",
        va="top",
        linespacing=1.4,
    )
    fig.text(
        0.69,
        0.235,
        "QLIKE 越低越好",
        fontsize=11.5,
        fontweight="bold",
        color=GREEN,
        ha="left",
        va="center",
    )
    source_footer(fig, source_label)
    save_panel(fig, panel)


def editorial_metric(
    fig: plt.Figure,
    block: dict[str, Any],
    results: dict[str, Any],
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    accent: str,
    maximum: float,
) -> None:
    value = numeric_metric(block, results)
    card(fig, x, y, width, height, facecolor=CARD, edgecolor="#D7D0C5")
    fig.text(
        x + 0.03,
        y + height - 0.055,
        wrapped(block["label"], 25),
        fontsize=13,
        fontweight="bold",
        color=INK,
        ha="left",
        va="top",
        linespacing=1.2,
    )
    fig.text(
        x + 0.03,
        y + 0.09,
        format_metric(block, results),
        fontsize=38,
        fontweight="bold",
        color=accent,
        ha="left",
        va="bottom",
    )
    bar_x = x + 0.03
    bar_y = y + 0.05
    bar_width = width - 0.06
    fig.add_artist(
        Rectangle(
            (bar_x, bar_y),
            bar_width,
            0.012,
            transform=fig.transFigure,
            facecolor="#E6E0D7",
            edgecolor="none",
        )
    )
    fig.add_artist(
        Rectangle(
            (bar_x, bar_y),
            bar_width * (value / maximum),
            0.012,
            transform=fig.transFigure,
            facecolor=accent,
            edgecolor="none",
        )
    )


def render_takeaway(
    plan: dict[str, Any], results: dict[str, Any], source_label: str
) -> None:
    panel = require_panel(plan, "panel_takeaway")
    har_a = require_block(
        panel,
        kind="metric",
        key="label",
        value="跨市場最佳 HAR-A（QLIKE）",
    )
    comb_mz = require_block(
        panel,
        kind="metric",
        key="label",
        value="AI 加 HAR 校準組合 COMB-MZ",
    )
    takeaway = require_block(
        panel, kind="text", key="heading", value="帶走三句話"
    )
    maximum = max(
        numeric_metric(har_a, results), numeric_metric(comb_mz, results)
    )
    if maximum <= 0:
        raise ValueError("Pooled QLIKE values must be positive")

    fig = new_figure(PAPER)
    fig.add_artist(
        Rectangle(
            (0.055, 0.825),
            0.89,
            0.003,
            transform=fig.transFigure,
            facecolor=AMBER,
            edgecolor="none",
        )
    )
    fig.text(
        0.06,
        0.925,
        panel["title"],
        fontsize=28,
        fontweight="bold",
        color=INK,
        ha="left",
        va="center",
    )
    fig.text(
        0.06,
        0.865,
        wrapped(panel["alt"], 52),
        fontsize=13.5,
        color=MUTED,
        ha="left",
        va="center",
    )

    editorial_metric(
        fig,
        har_a,
        results,
        0.06,
        0.49,
        0.42,
        0.27,
        accent=GREEN,
        maximum=maximum,
    )
    editorial_metric(
        fig,
        comb_mz,
        results,
        0.52,
        0.49,
        0.42,
        0.27,
        accent=BLUE,
        maximum=maximum,
    )

    card(fig, 0.06, 0.135, 0.88, 0.285, facecolor="#EFE9DE", edgecolor="#EFE9DE")
    fig.text(
        0.09,
        0.37,
        takeaway["heading"],
        fontsize=19,
        fontweight="bold",
        color=INK,
        ha="left",
        va="top",
    )
    fig.text(
        0.09,
        0.305,
        bullet_text(takeaway["body"], 54),
        fontsize=14.3,
        color=INK,
        ha="left",
        va="top",
        linespacing=1.48,
    )
    source_footer(fig, source_label)
    save_panel(fig, panel)


def main() -> None:
    plan, results, _article = load_evidence()
    source_label = plan["evidence"]["results"]["label"]
    render_question(plan, results, source_label)
    render_method(plan, results, source_label)
    render_results(plan, results, source_label)
    render_takeaway(plan, results, source_label)


if __name__ == "__main__":
    main()
