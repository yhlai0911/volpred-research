#!/usr/bin/env python3
"""Render the three data-bound PNG panels for the mile_e96cad4e lazy pack."""

from __future__ import annotations

import json
import os
import textwrap
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyBboxPatch


PLAN_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_e96cad4e/runs/lazypack-mile_e96cad4e/plan.json"
)
RESULTS_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1588/k1588_results.json"
)
ARTICLE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_e96cad4e/runs/lazypack-mile_e96cad4e/panels/"
    "mile_e96cad4e_article.md"
)
out_dir = (
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_e96cad4e/runs/lazypack-mile_e96cad4e/panels"
)

WIDTH_PX = 1600
HEIGHT_PX = 1000
DPI = 150

NAVY = "#14283D"
INK = "#17212B"
MUTED = "#526271"
PALE = "#F3F6F8"
LINE = "#D6E0E7"
TEAL = "#167D82"
TEAL_PALE = "#E4F2F2"
AMBER = "#B87318"
RED = "#B6403A"
WHITE = "#FFFFFF"

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def resolve_pointer(document: Any, pointer: str) -> Any:
    """Resolve an RFC 6901-style JSON pointer and fail loudly on missing fields."""
    if not pointer.startswith("/"):
        raise ValueError(f"JSON pointer must begin with '/': {pointer}")
    current = document
    for raw_token in pointer[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            if token not in current:
                raise KeyError(f"Missing evidence field: {pointer} (stopped at {token!r})")
            current = current[token]
        elif isinstance(current, list):
            try:
                current = current[int(token)]
            except (ValueError, IndexError) as exc:
                raise KeyError(f"Invalid evidence list index in {pointer}: {token!r}") from exc
        else:
            raise KeyError(f"Cannot descend through scalar while resolving {pointer}")
    return current


def require_number(value: Any, pointer: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"Expected numeric evidence at {pointer}, got {type(value).__name__}")
    return float(value)


def format_bound_value(value: Any, fmt: dict[str, Any], pointer: str) -> str:
    kind = fmt["kind"]
    number = require_number(value, pointer)
    if kind == "integer":
        if not number.is_integer():
            raise ValueError(f"Expected integer-valued evidence at {pointer}, got {number}")
        return f"{int(number):,}"
    if kind == "percent":
        digits = int(fmt.get("digits", 0))
        return f"{number * 100:.{digits}f}%"
    if kind == "number":
        digits = int(fmt.get("digits", 3))
        plus = "+" if fmt.get("show_plus", False) else ""
        return f"{number:{plus}.{digits}f}"
    raise ValueError(f"Unsupported plan number format {kind!r} at {pointer}")


def wrap_zh(text: str, width: int) -> str:
    """Wrap Chinese prose deterministically without dropping punctuation."""
    return "\n".join(
        textwrap.wrap(
            text,
            width=width,
            break_long_words=True,
            break_on_hyphens=False,
            replace_whitespace=False,
        )
    )


def add_round_box(
    ax: plt.Axes,
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    facecolor: str,
    edgecolor: str = "none",
    linewidth: float = 1.0,
    radius: float = 0.018,
) -> None:
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            width,
            height,
            boxstyle=f"round,pad=0.008,rounding_size={radius}",
            transform=ax.transAxes,
            facecolor=facecolor,
            edgecolor=edgecolor,
            linewidth=linewidth,
        )
    )


def draw_header(ax: plt.Axes, title: str, panel_name: str) -> None:
    ax.add_patch(
        FancyBboxPatch(
            (0, 0.805),
            1,
            0.195,
            boxstyle="square,pad=0",
            transform=ax.transAxes,
            facecolor=NAVY,
            edgecolor="none",
        )
    )
    ax.text(
        0.055,
        0.902,
        wrap_zh(title, 27),
        transform=ax.transAxes,
        ha="left",
        va="center",
        fontsize=26,
        fontweight="bold",
        color=WHITE,
        linespacing=1.25,
    )
    accent = TEAL if panel_name == "panel_method" else AMBER if panel_name == "panel_results" else RED
    ax.add_patch(
        FancyBboxPatch(
            (0.055, 0.832),
            0.085,
            0.008,
            boxstyle="round,pad=0,rounding_size=0.004",
            transform=ax.transAxes,
            facecolor=accent,
            edgecolor="none",
        )
    )


def draw_flow_icon(ax: plt.Axes, panel_name: str) -> None:
    """Small professional schematic; labels contain no unbound statistics."""
    if panel_name == "panel_method":
        labels = ["郡對郡連結", "連結廣度", "財報日波動"]
        color = TEAL
        xs = [0.095, 0.285, 0.475]
        for index, (x, label) in enumerate(zip(xs, labels, strict=True)):
            ax.add_patch(Circle((x, 0.715), 0.044, transform=ax.transAxes, color=TEAL_PALE, ec=color, lw=1.4))
            ax.text(x, 0.715, str(index + 1), transform=ax.transAxes, ha="center", va="center", fontsize=14, color=color, fontweight="bold")
            ax.text(x, 0.648, label, transform=ax.transAxes, ha="center", va="top", fontsize=10.5, color=INK)
            if index < 2:
                ax.annotate("", xy=(xs[index + 1] - 0.052, 0.715), xytext=(x + 0.052, 0.715), xycoords=ax.transAxes, arrowprops={"arrowstyle": "->", "lw": 1.5, "color": MUTED})
    elif panel_name == "panel_results":
        add_round_box(ax, 0.07, 0.675, 0.48, 0.085, facecolor=PALE, edgecolor=LINE)
        ax.text(0.10, 0.718, "粗比較", transform=ax.transAxes, ha="left", va="center", fontsize=12, color=MUTED, fontweight="bold")
        ax.text(0.225, 0.718, "方向相反", transform=ax.transAxes, ha="left", va="center", fontsize=15, color=RED, fontweight="bold")
        ax.text(0.39, 0.718, "→", transform=ax.transAxes, ha="center", va="center", fontsize=17, color=MUTED)
        ax.text(0.43, 0.718, "控制後近零", transform=ax.transAxes, ha="left", va="center", fontsize=15, color=TEAL, fontweight="bold")
    else:
        add_round_box(ax, 0.07, 0.675, 0.48, 0.085, facecolor=PALE, edgecolor=LINE)
        ax.text(0.10, 0.718, "事件很多", transform=ax.transAxes, ha="left", va="center", fontsize=15, color=INK, fontweight="bold")
        ax.text(0.235, 0.718, "≠", transform=ax.transAxes, ha="center", va="center", fontsize=18, color=RED, fontweight="bold")
        ax.text(0.275, 0.718, "獨立公司很多", transform=ax.transAxes, ha="left", va="center", fontsize=15, color=INK, fontweight="bold")


def draw_text_block(ax: plt.Axes, block: dict[str, Any], panel_name: str) -> None:
    ax.text(
        0.07,
        0.61,
        block["heading"],
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=16,
        fontweight="bold",
        color=INK,
    )
    paragraphs = block["body"]
    if not isinstance(paragraphs, list) or not paragraphs:
        raise ValueError(f"{panel_name} must have a non-empty text body")
    y = 0.555
    line_height = 0.033
    for paragraph in paragraphs:
        wrapped = wrap_zh(str(paragraph), 35)
        ax.text(
            0.07,
            y,
            wrapped,
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=11.8,
            color=MUTED,
            linespacing=1.55,
        )
        y -= line_height * (wrapped.count("\n") + 1) + 0.035


def draw_metric_cards(
    ax: plt.Axes,
    metrics: list[dict[str, Any]],
    results: dict[str, Any],
    panel_name: str,
) -> None:
    if len(metrics) != 3:
        raise ValueError(f"{panel_name} expected exactly three metric blocks")
    card_x = 0.625
    card_w = 0.315
    card_h = 0.176
    card_ys = [0.596, 0.395, 0.194]
    accent = TEAL if panel_name == "panel_method" else AMBER if panel_name == "panel_results" else RED

    for index, (metric, y) in enumerate(zip(metrics, card_ys, strict=True), start=1):
        value_spec = metric["value"]
        if value_spec["source"] != "results":
            raise ValueError(f"Unsupported evidence source in {panel_name}: {value_spec['source']!r}")
        pointer = value_spec["path"]
        raw_value = resolve_pointer(results, pointer)
        display_value = format_bound_value(raw_value, value_spec["format"], pointer)

        add_round_box(ax, card_x, y, card_w, card_h, facecolor=WHITE, edgecolor=LINE, linewidth=1.2)
        ax.add_patch(Circle((card_x + 0.035, y + card_h - 0.036), 0.016, transform=ax.transAxes, color=accent))
        ax.text(card_x + 0.035, y + card_h - 0.036, str(index), transform=ax.transAxes, ha="center", va="center", fontsize=8.5, color=WHITE, fontweight="bold")
        ax.text(
            card_x + 0.062,
            y + card_h - 0.028,
            wrap_zh(metric["label"], 19),
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=10.5,
            color=MUTED,
            linespacing=1.25,
        )
        ax.text(
            card_x + 0.028,
            y + 0.071,
            display_value,
            transform=ax.transAxes,
            ha="left",
            va="center",
            fontsize=27,
            fontweight="bold",
            color=accent,
        )
        note = metric.get("note")
        if note:
            ax.text(
                card_x + 0.028,
                y + 0.024,
                wrap_zh(note, 27),
                transform=ax.transAxes,
                ha="left",
                va="bottom",
                fontsize=8.6,
                color=MUTED,
                linespacing=1.25,
            )


def draw_footer(ax: plt.Axes, source_label: str) -> None:
    ax.plot([0.055, 0.945], [0.105, 0.105], transform=ax.transAxes, color=LINE, lw=0.8)
    source_text = "資料來源：" + source_label
    ax.text(
        0.055,
        0.072,
        "\n".join(textwrap.wrap(source_text, width=126, break_long_words=False, break_on_hyphens=False)),
        transform=ax.transAxes,
        ha="left",
        va="center",
        fontsize=6.6,
        color=MUTED,
        linespacing=1.25,
    )
    ax.text(
        0.945,
        0.025,
        "本文是資料分析，不是投資建議。",
        transform=ax.transAxes,
        ha="right",
        va="bottom",
        fontsize=8.5,
        color=MUTED,
    )


def render_panel(panel: dict[str, Any], results: dict[str, Any], source_label: str) -> None:
    name = panel["name"]
    if name not in {"panel_method", "panel_results", "panel_takeaway"}:
        raise ValueError(f"Unexpected panel name: {name!r}")
    if panel.get("style") != "professional":
        raise ValueError(f"{name} must use the professional style")
    if panel.get("sources") != ["results"]:
        raise ValueError(f"{name} must use only the results evidence source")

    text_blocks = [block for block in panel["blocks"] if block.get("kind") == "text"]
    metric_blocks = [block for block in panel["blocks"] if block.get("kind") == "metric"]
    if len(text_blocks) != 1:
        raise ValueError(f"{name} expected exactly one text block")

    fig = plt.figure(figsize=(WIDTH_PX / DPI, HEIGHT_PX / DPI), dpi=DPI, facecolor=WHITE)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.set_facecolor(WHITE)

    draw_header(ax, panel["title"], name)
    draw_flow_icon(ax, name)
    draw_text_block(ax, text_blocks[0], name)
    draw_metric_cards(ax, metric_blocks, results, name)
    draw_footer(ax, source_label)

    output_path = Path(out_dir) / f"{name}.png"
    fig.savefig(output_path, dpi=DPI, facecolor=WHITE, metadata={"Title": panel["title"], "Description": panel["alt"]})
    plt.close(fig)


def main() -> None:
    plan = load_json(PLAN_PATH)
    results = load_json(RESULTS_PATH)
    article = ARTICLE_PATH.read_text(encoding="utf-8")
    if not article.strip():
        raise ValueError(f"Article evidence is empty: {ARTICLE_PATH}")

    evidence = plan["evidence"]
    source_label = evidence["results"]["label"]
    if not isinstance(source_label, str) or not source_label.strip():
        raise ValueError("Strict plan evidence.results.label is missing or empty")
    panels = plan["panels"]
    if [panel["name"] for panel in panels] != ["panel_method", "panel_results", "panel_takeaway"]:
        raise ValueError("Strict plan must contain the three expected panels in order")

    os.makedirs(out_dir, exist_ok=True)
    for panel in panels:
        render_panel(panel, results, source_label)


if __name__ == "__main__":
    main()
