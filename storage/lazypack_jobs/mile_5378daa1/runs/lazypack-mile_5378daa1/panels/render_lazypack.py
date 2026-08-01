#!/usr/bin/env python3
"""Render the four data-bound PNG panels for lazypack mile_5378daa1.

All panel copy and field bindings come from the strict plan.  Every displayed
number is resolved from the K1450 results JSON at render time; missing or
ill-typed fields deliberately raise an exception.
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
from matplotlib.patches import Circle, FancyBboxPatch, Rectangle


PLAN_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_5378daa1/runs/lazypack-mile_5378daa1/plan.json"
)
RESULTS_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1450/k1450_results.json"
)
ARTICLE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_5378daa1/runs/lazypack-mile_5378daa1/panels/"
    "mile_5378daa1_article.md"
)
out_dir = (
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_5378daa1/runs/lazypack-mile_5378daa1/panels"
)

WIDTH_PX = 1600
HEIGHT_PX = 1000
DPI = 150
EXPECTED_PANELS = {
    "panel_question",
    "panel_result",
    "panel_not_stock",
    "panel_limit",
}

NAVY = "#12243A"
NAVY_2 = "#1C3553"
BLUE = "#2878B5"
TEAL = "#16867A"
AMBER = "#C78324"
RED = "#B94A48"
INK = "#172334"
MUTED = "#5B6777"
PALE = "#F3F6F9"
BORDER = "#DDE4EB"
WHITE = "#FFFFFF"

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def resolve_json_pointer(document: Any, pointer: str) -> Any:
    """Resolve a strict RFC 6901-style pointer; never return a fallback."""
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValueError(f"Invalid JSON pointer: {pointer!r}")
    current = document
    for raw_token in pointer[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            if token not in current:
                raise KeyError(f"Missing evidence field: {pointer}")
            current = current[token]
        elif isinstance(current, list):
            try:
                current = current[int(token)]
            except (ValueError, IndexError) as exc:
                raise KeyError(f"Missing evidence field: {pointer}") from exc
        else:
            raise KeyError(f"Cannot descend through evidence field: {pointer}")
    return current


def format_evidence_value(value_spec: dict[str, Any], results: dict[str, Any]) -> str:
    if value_spec.get("source") != "results":
        raise ValueError(f"Unsupported evidence source: {value_spec.get('source')!r}")
    pointer = value_spec["path"]
    value = resolve_json_pointer(results, pointer)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"Expected numeric evidence at {pointer}, got {type(value).__name__}")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"Non-finite evidence value at {pointer}")

    fmt = value_spec["format"]
    kind = fmt["kind"]
    digits = int(fmt.get("digits", 0))
    if kind == "integer":
        if not number.is_integer():
            raise ValueError(f"Expected integer evidence at {pointer}, got {value!r}")
        return f"{int(number):,}"
    if kind == "number":
        sign = "+" if fmt.get("show_plus", False) else ""
        return f"{number:{sign}.{digits}f}"
    if kind == "percent":
        return f"{number * 100:.{digits}f}%"
    raise ValueError(f"Unsupported number format {kind!r} at {pointer}")


def wrapped(text: str, width: int) -> str:
    """Deterministically wrap Chinese copy without relying on renderer clipping."""
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
    linewidth: float = 0.0,
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


def accent_for(panel_name: str) -> str:
    return {
        "panel_question": BLUE,
        "panel_result": TEAL,
        "panel_not_stock": BLUE,
        "panel_limit": AMBER,
    }[panel_name]


def draw_text_block(ax: plt.Axes, block: dict[str, Any], accent: str) -> None:
    # Keep every text artist comfortably inside the left card.  At 150 DPI a
    # 15.5 pt CJK glyph is roughly 32 px wide, so the old 27-character lines
    # were substantially wider than the usable 570 px text column.  The
    # smaller type and 18-character wrap below leave a real right-hand inset.
    add_round_box(
        ax,
        0.055,
        0.184,
        0.414,
        0.525,
        facecolor=PALE,
        edgecolor=BORDER,
        linewidth=1.2,
    )
    ax.add_patch(
        Rectangle(
            (0.055, 0.184),
            0.009,
            0.525,
            transform=ax.transAxes,
            facecolor=accent,
            edgecolor="none",
        )
    )
    ax.text(
        0.088,
        0.665,
        wrapped(block["heading"], 13),
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=20,
        fontweight="bold",
        color=INK,
        linespacing=1.18,
    )

    bodies = block["body"]
    if not isinstance(bodies, list) or len(bodies) != 2:
        raise ValueError("Each panel must contain exactly two body paragraphs")
    # Each paragraph owns a separate vertical band.  The longest first
    # paragraph occupies four wrapped lines and still ends above the second.
    y_positions = (0.515, 0.345)
    for body, y in zip(bodies, y_positions, strict=True):
        ax.add_patch(
            Circle(
                (0.092, y + 0.002),
                0.006,
                transform=ax.transAxes,
                facecolor=accent,
                edgecolor="none",
            )
        )
        ax.text(
            0.111,
            y,
            wrapped(body, 18),
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=12.5,
            color=INK,
            linespacing=1.38,
        )


def draw_metric_cards(
    ax: plt.Axes,
    metrics: list[dict[str, Any]],
    results: dict[str, Any],
    accent: str,
) -> None:
    if len(metrics) != 3:
        raise ValueError("Each panel must contain exactly three metric blocks")
    card_x, card_w, card_h = 0.505, 0.44, 0.155
    card_ys = (0.555, 0.375, 0.195)

    for index, (metric, y) in enumerate(zip(metrics, card_ys, strict=True)):
        value = format_evidence_value(metric["value"], results)
        add_round_box(
            ax,
            card_x,
            y,
            card_w,
            card_h,
            facecolor=WHITE,
            edgecolor=BORDER,
            linewidth=1.35,
        )
        ax.add_patch(
            Circle(
                (card_x + 0.035, y + card_h - 0.042),
                0.015,
                transform=ax.transAxes,
                facecolor=accent,
                alpha=0.16,
                edgecolor="none",
            )
        )
        ax.text(
            card_x + 0.035,
            y + card_h - 0.042,
            str(index + 1),
            transform=ax.transAxes,
            ha="center",
            va="center",
            fontsize=10.5,
            fontweight="bold",
            color=accent,
        )
        ax.text(
            card_x + 0.062,
            y + card_h - 0.027,
            wrapped(metric["label"], 24),
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=10.0,
            fontweight="bold",
            color=MUTED,
            linespacing=1.1,
        )
        ax.text(
            card_x + card_w - 0.025,
            y + 0.028,
            value,
            transform=ax.transAxes,
            ha="right",
            va="bottom",
            fontsize=26,
            fontweight="bold",
            color=accent if index < 2 else NAVY,
        )
        note = metric.get("note")
        if note:
            ax.text(
                card_x + 0.025,
                y + 0.026,
                wrapped(note, 22),
                transform=ax.transAxes,
                ha="left",
                va="bottom",
                fontsize=8.6,
                color=MUTED,
            )


def render_panel(
    panel: dict[str, Any],
    results: dict[str, Any],
    evidence_labels: dict[str, str],
) -> None:
    name = panel["name"]
    if name not in EXPECTED_PANELS:
        raise ValueError(f"Unexpected panel name: {name!r}")
    if panel.get("style") != "professional":
        raise ValueError(f"Panel {name} must use professional style")
    if panel.get("sources") != ["results"]:
        raise ValueError(f"Panel {name} must bind only to results evidence")

    text_blocks = [block for block in panel["blocks"] if block.get("kind") == "text"]
    metrics = [block for block in panel["blocks"] if block.get("kind") == "metric"]
    if len(text_blocks) != 1:
        raise ValueError(f"Panel {name} must contain exactly one text block")

    accent = accent_for(name)
    fig = plt.figure(
        figsize=(WIDTH_PX / DPI, HEIGHT_PX / DPI),
        dpi=DPI,
        facecolor=WHITE,
    )
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    ax.add_patch(
        Rectangle(
            (0, 0.76),
            1,
            0.24,
            transform=ax.transAxes,
            facecolor=NAVY,
            edgecolor="none",
        )
    )
    ax.add_patch(
        Rectangle(
            (0, 0.752),
            1,
            0.008,
            transform=ax.transAxes,
            facecolor=accent,
            edgecolor="none",
        )
    )
    ax.text(
        0.055,
        0.885,
        wrapped(panel["title"], 25),
        transform=ax.transAxes,
        ha="left",
        va="center",
        fontsize=29,
        fontweight="bold",
        color=WHITE,
        linespacing=1.22,
    )
    ax.text(
        0.945,
        0.807,
        "VolPred 懶人包",
        transform=ax.transAxes,
        ha="right",
        va="center",
        fontsize=12.5,
        color="#CCD7E3",
    )

    draw_text_block(ax, text_blocks[0], accent)
    draw_metric_cards(ax, metrics, results, accent)

    source_lines = []
    for source_key in panel["sources"]:
        if source_key not in evidence_labels:
            raise KeyError(f"Missing strict-plan evidence label: {source_key}")
        source_lines.append(evidence_labels[source_key])
    source_text = "；".join(source_lines)
    ax.plot([0.055, 0.945], [0.127, 0.127], transform=ax.transAxes, color=BORDER, lw=1.0)
    ax.text(
        0.055,
        0.082,
        f"資料來源：{source_text}",
        transform=ax.transAxes,
        ha="left",
        va="center",
        fontsize=9.6,
        color=MUTED,
    )
    ax.text(
        0.945,
        0.082,
        "資料分析，非投資建議",
        transform=ax.transAxes,
        ha="right",
        va="center",
        fontsize=10.2,
        fontweight="bold",
        color=NAVY_2,
    )

    output_path = Path(out_dir) / f"{name}.png"
    fig.savefig(
        output_path,
        dpi=DPI,
        facecolor=WHITE,
        edgecolor="none",
        metadata={"Title": panel["title"], "Description": panel["alt"]},
    )
    plt.close(fig)


def main() -> None:
    plan = load_json(PLAN_PATH)
    results = load_json(RESULTS_PATH)
    # The article is part of the evidence package. Reading it here also makes a
    # missing or unreadable package fail loudly, while the strict plan remains
    # the sole source of rendered prose and bindings.
    article = ARTICLE_PATH.read_text(encoding="utf-8")
    if not article.strip():
        raise ValueError(f"Article evidence is empty: {ARTICLE_PATH}")

    evidence = plan["evidence"]
    if evidence["results"]["path"] != "experiments/k1450/k1450_results.json":
        raise ValueError("Strict plan points to an unexpected results artifact")
    evidence_labels = {key: item["label"] for key, item in evidence.items()}

    panels = plan["panels"]
    names = [panel["name"] for panel in panels]
    if len(names) != len(EXPECTED_PANELS) or set(names) != EXPECTED_PANELS:
        raise ValueError(f"Strict plan panel set mismatch: {names!r}")

    os.makedirs(out_dir, exist_ok=True)
    for panel in panels:
        render_panel(panel, results, evidence_labels)


if __name__ == "__main__":
    main()
