#!/usr/bin/env python3
"""Render the three data-bound PNG panels for the mile_a87265ab article."""

from __future__ import annotations

import json
import os
import textwrap
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle


RESULTS_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1406/k1406_results.json"
)
README_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1406/README.md"
)
PLAN_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_a87265ab/runs/lazypack-mile_a87265ab/plan.json"
)
ARTICLE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_a87265ab/runs/lazypack-mile_a87265ab/panels/"
    "mile_a87265ab_article.md"
)
out_dir = (
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_a87265ab/runs/lazypack-mile_a87265ab/panels"
)

EXPECTED_SOURCE_LABEL = (
    "experiment K1406 results (lump-sum vs staged entry and dip-buying, "
    "conditional block bootstrap on US and Taiwan broad-market ETFs)"
)
EXPECTED_PANELS = (
    "panel_question",
    "panel_two_yardsticks",
    "panel_takeaway",
)

INK = "#14263D"
INK_SOFT = "#40546B"
NAVY = "#102A43"
BLUE = "#1677A8"
TEAL = "#16877B"
AMBER = "#C68218"
RED = "#B65045"
PAPER = "#FFFFFF"
PANEL = "#F4F7FA"
RULE = "#D6E0E8"
MUTED = "#6A7C8E"

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False


def require(mapping: dict[str, Any], key: str, context: str) -> Any:
    """Return a required mapping field, raising a useful error if absent."""
    if key not in mapping:
        raise KeyError(f"缺少必要欄位：{context}/{key}")
    return mapping[key]


def load_evidence() -> tuple[dict[str, Any], dict[str, Any]]:
    """Load every file in the evidence package and validate the strict label."""
    with RESULTS_PATH.open("r", encoding="utf-8") as handle:
        results = json.load(handle)
    with PLAN_PATH.open("r", encoding="utf-8") as handle:
        plan = json.load(handle)

    # These two reads deliberately make absence of either evidence document fatal.
    README_PATH.read_text(encoding="utf-8")
    ARTICLE_PATH.read_text(encoding="utf-8")

    evidence = require(plan, "evidence", "plan")
    results_evidence = require(evidence, "results", "plan/evidence")
    source_label = require(results_evidence, "label", "plan/evidence/results")
    if source_label != EXPECTED_SOURCE_LABEL:
        raise ValueError("plan 的 results source label 與 strict plan 指定值不一致")

    panels = require(plan, "panels", "plan")
    names = tuple(require(panel, "name", "plan/panels[]") for panel in panels)
    if names != EXPECTED_PANELS:
        raise ValueError(f"panel 名稱或順序不符：{names!r}")
    return results, plan


def resolve_json_pointer(document: Any, pointer: str) -> Any:
    """Resolve an RFC 6901-style JSON pointer; missing fields always raise."""
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValueError(f"無效 JSON pointer：{pointer!r}")
    current = document
    for raw_token in pointer.split("/")[1:]:
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            if token not in current:
                raise KeyError(f"results 缺少欄位：{pointer}")
            current = current[token]
        elif isinstance(current, list):
            try:
                current = current[int(token)]
            except (ValueError, IndexError) as exc:
                raise KeyError(f"results 缺少欄位：{pointer}") from exc
        else:
            raise KeyError(f"results 無法解析欄位：{pointer}")
    return current


def format_value(results: dict[str, Any], value_spec: dict[str, Any]) -> tuple[str, float | None]:
    """Read and format one metric strictly from results.json."""
    source = require(value_spec, "source", "panel metric/value")
    if source != "results":
        raise ValueError(f"不支援的數據來源：{source!r}")
    pointer = require(value_spec, "path", "panel metric/value")
    fmt = require(value_spec, "format", "panel metric/value")
    kind = require(fmt, "kind", "panel metric/value/format")
    raw = resolve_json_pointer(results, pointer)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise TypeError(f"{pointer} 必須是數值，實際為 {type(raw).__name__}")

    if kind == "integer":
        if float(raw) != int(raw):
            raise ValueError(f"{pointer} 不是整數：{raw!r}")
        return f"{int(raw):,}", None
    if kind == "percent":
        digits = require(fmt, "digits", "panel metric/value/format")
        if isinstance(digits, bool) or not isinstance(digits, int) or digits < 0:
            raise ValueError(f"percent digits 無效：{digits!r}")
        return f"{float(raw) * 100:.{digits}f}%", float(raw)
    raise ValueError(f"不支援的格式：{kind!r}")


def wrap_zh(text: str, width: int) -> str:
    """Wrap mixed Chinese/Latin text without dropping any characters."""
    return "\n".join(
        textwrap.wrap(
            text,
            width=width,
            break_long_words=True,
            break_on_hyphens=False,
            replace_whitespace=False,
        )
    )


def new_canvas(title: str) -> tuple[plt.Figure, plt.Axes]:
    """Create a 1600×1000 white canvas with the shared dark title band."""
    fig = plt.figure(figsize=(10.6666667, 6.6666667), dpi=150, facecolor=PAPER)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    ax.add_patch(Rectangle((0, 0.82), 1, 0.18, facecolor=NAVY, edgecolor="none"))
    ax.add_patch(Rectangle((0.055, 0.875), 0.008, 0.058, facecolor=TEAL, edgecolor="none"))
    ax.text(
        0.08,
        0.905,
        title,
        ha="left",
        va="center",
        fontsize=27,
        fontweight="bold",
        color=PAPER,
    )
    return fig, ax


def footer(ax: plt.Axes, source_label: str) -> None:
    """Draw the exact strict-plan source label in a reserved footer."""
    ax.plot([0.055, 0.945], [0.085, 0.085], color=RULE, linewidth=1.0)
    ax.text(
        0.055,
        0.046,
        f"資料來源：{source_label}",
        ha="left",
        va="center",
        fontsize=9.2,
        color=MUTED,
    )


def get_text_block(panel: dict[str, Any]) -> dict[str, Any]:
    blocks = require(panel, "blocks", f"panel/{require(panel, 'name', 'panel')}")
    text_blocks = [block for block in blocks if require(block, "kind", "panel/block") == "text"]
    if len(text_blocks) != 1:
        raise ValueError("每張 panel 必須恰有一個 text block")
    body = require(text_blocks[0], "body", "panel/text block")
    if not isinstance(body, list) or len(body) != 2 or not all(isinstance(x, str) for x in body):
        raise ValueError("text block/body 必須是兩段文字")
    return text_blocks[0]


def get_metrics(
    panel: dict[str, Any], results: dict[str, Any]
) -> list[tuple[str, str, float | None]]:
    metrics: list[tuple[str, str, float | None]] = []
    for block in require(panel, "blocks", "panel"):
        if require(block, "kind", "panel/block") != "metric":
            continue
        label = require(block, "label", "panel/metric")
        display, proportion = format_value(
            results, require(block, "value", "panel/metric")
        )
        metrics.append((label, display, proportion))
    if not metrics:
        raise ValueError("panel 沒有 metric block")
    return metrics


def narrative(
    ax: plt.Axes,
    block: dict[str, Any],
    *,
    x: float,
    top: float,
    wrap_width: int,
    body_size: float = 15.2,
) -> None:
    """Draw a heading and two fully wrapped narrative paragraphs."""
    heading = require(block, "heading", "panel/text block")
    body = require(block, "body", "panel/text block")
    ax.text(
        x,
        top,
        heading,
        ha="left",
        va="top",
        fontsize=19,
        fontweight="bold",
        color=INK,
    )
    y = top - 0.07
    for paragraph in body:
        wrapped = wrap_zh(paragraph, wrap_width)
        line_count = wrapped.count("\n") + 1
        ax.text(
            x,
            y,
            wrapped,
            ha="left",
            va="top",
            fontsize=body_size,
            color=INK_SOFT,
            linespacing=1.55,
        )
        y -= line_count * 0.042 + 0.038


def metric_card(
    ax: plt.Axes,
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    label: str,
    value: str,
    proportion: float | None,
    accent: str,
    label_wrap: int,
    value_bottom_offset: float | None = None,
) -> None:
    """Draw one metric card, optionally with a proportion bar."""
    card = FancyBboxPatch(
        (x, y),
        width,
        height,
        boxstyle="round,pad=0.012,rounding_size=0.012",
        facecolor=PANEL,
        edgecolor=RULE,
        linewidth=1.0,
    )
    ax.add_patch(card)
    ax.add_patch(Rectangle((x, y), 0.008, height, facecolor=accent, edgecolor="none"))
    ax.text(
        x + 0.028,
        y + height - 0.030,
        wrap_zh(label, label_wrap),
        ha="left",
        va="top",
        fontsize=12.2,
        color=INK_SOFT,
        linespacing=1.2,
    )
    ax.text(
        x + 0.028,
        y
        + (
            value_bottom_offset
            if value_bottom_offset is not None
            else (0.048 if proportion is not None else 0.040)
        ),
        value,
        ha="left",
        va="bottom",
        fontsize=31,
        fontweight="bold",
        color=INK,
    )
    if proportion is not None:
        if not 0 <= proportion <= 1:
            raise ValueError(f"百分比超出 [0, 1]：{proportion}")
        bar_x = x + 0.165
        bar_y = y + 0.055
        bar_w = width - 0.195
        ax.add_patch(
            Rectangle((bar_x, bar_y), bar_w, 0.012, facecolor=RULE, edgecolor="none")
        )
        ax.add_patch(
            Rectangle(
                (bar_x, bar_y),
                bar_w * proportion,
                0.012,
                facecolor=accent,
                edgecolor="none",
            )
        )


def render_question(
    panel: dict[str, Any], results: dict[str, Any], source_label: str
) -> None:
    fig, ax = new_canvas(require(panel, "title", "panel_question"))
    narrative(
        ax,
        get_text_block(panel),
        x=0.065,
        top=0.745,
        wrap_width=23,
        body_size=15.0,
    )
    metrics = get_metrics(panel, results)
    if len(metrics) != 3:
        raise ValueError("panel_question 必須有三個 metric")
    for (label, value, proportion), y, accent in zip(
        metrics,
        (0.615, 0.405, 0.195),
        (BLUE, TEAL, AMBER),
        strict=True,
    ):
        metric_card(
            ax,
            x=0.585,
            y=y,
            width=0.35,
            height=0.155,
            label=label,
            value=value,
            proportion=proportion,
            accent=accent,
            label_wrap=16,
        )
    footer(ax, source_label)
    fig.savefig(
        Path(out_dir) / "panel_question.png",
        dpi=150,
        facecolor=PAPER,
        metadata={"Description": require(panel, "alt", "panel_question")},
    )
    plt.close(fig)


def render_two_yardsticks(
    panel: dict[str, Any], results: dict[str, Any], source_label: str
) -> None:
    fig, ax = new_canvas(require(panel, "title", "panel_two_yardsticks"))
    narrative(
        ax,
        get_text_block(panel),
        x=0.055,
        top=0.745,
        wrap_width=21,
        body_size=14.5,
    )
    metrics = get_metrics(panel, results)
    if len(metrics) != 4:
        raise ValueError("panel_two_yardsticks 必須有四個 metric")
    positions = (
        (0.515, 0.515),
        (0.745, 0.515),
        (0.515, 0.235),
        (0.745, 0.235),
    )
    accents = (BLUE, TEAL, AMBER, RED)
    for (label, value, proportion), (x, y), accent in zip(
        metrics, positions, accents, strict=True
    ):
        metric_card(
            ax,
            x=x,
            y=y,
            width=0.20,
            height=0.215,
            label=label,
            value=value,
            proportion=proportion,
            accent=accent,
            label_wrap=10,
        )
    footer(ax, source_label)
    fig.savefig(
        Path(out_dir) / "panel_two_yardsticks.png",
        dpi=150,
        facecolor=PAPER,
        metadata={"Description": require(panel, "alt", "panel_two_yardsticks")},
    )
    plt.close(fig)


def render_takeaway(
    panel: dict[str, Any], results: dict[str, Any], source_label: str
) -> None:
    fig, ax = new_canvas(require(panel, "title", "panel_takeaway"))
    narrative(
        ax,
        get_text_block(panel),
        x=0.065,
        top=0.745,
        wrap_width=23,
        body_size=15.0,
    )
    metrics = get_metrics(panel, results)
    if len(metrics) != 3:
        raise ValueError("panel_takeaway 必須有三個 metric")
    for (label, value, proportion), y, accent in zip(
        metrics,
        (0.615, 0.405, 0.195),
        (RED, AMBER, BLUE),
        strict=True,
    ):
        metric_card(
            ax,
            x=0.585,
            y=y,
            width=0.35,
            height=0.155,
            label=label,
            value=value,
            proportion=proportion,
            accent=accent,
            label_wrap=16,
            value_bottom_offset=0.022,
        )
    footer(ax, source_label)
    fig.savefig(
        Path(out_dir) / "panel_takeaway.png",
        dpi=150,
        facecolor=PAPER,
        metadata={"Description": require(panel, "alt", "panel_takeaway")},
    )
    plt.close(fig)


def main() -> None:
    os.makedirs(out_dir, exist_ok=True)
    results, plan = load_evidence()
    source_label = plan["evidence"]["results"]["label"]
    panels_by_name = {panel["name"]: panel for panel in plan["panels"]}

    render_question(panels_by_name["panel_question"], results, source_label)
    render_two_yardsticks(
        panels_by_name["panel_two_yardsticks"], results, source_label
    )
    render_takeaway(panels_by_name["panel_takeaway"], results, source_label)


if __name__ == "__main__":
    main()
