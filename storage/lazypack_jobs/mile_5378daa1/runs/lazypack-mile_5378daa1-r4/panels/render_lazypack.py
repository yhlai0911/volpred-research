#!/usr/bin/env python3
"""Render the four data-bound PNG panels for mile_5378daa1 lazypack r4."""

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
    "/Users/yhlai0911/volpred-research/experiments/k1450/k1450_results.json"
)
README_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1450/README.md"
)
PLAN_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_5378daa1/runs/lazypack-mile_5378daa1-r4/plan.json"
)
ARTICLE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_5378daa1/runs/lazypack-mile_5378daa1-r4/panels/"
    "mile_5378daa1_article.md"
)
out_dir = (
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_5378daa1/runs/lazypack-mile_5378daa1-r4/panels"
)

EXPECTED_PANEL_NAMES = (
    "panel_question",
    "panel_result",
    "panel_not_stock",
    "panel_limit",
)
EXPECTED_SOURCE_LABEL = (
    "experiment K1450 results (VNQ forward volatility and stock or bond "
    "affinity under lagged rate regimes)"
)

NAVY = "#12233F"
NAVY_2 = "#1B3155"
INK = "#17243A"
MUTED = "#596779"
PALE = "#F3F6FA"
LINE = "#DCE3EC"
WHITE = "#FFFFFF"
TEAL = "#137D7A"
TEAL_PALE = "#E8F5F3"
BLUE = "#356BA6"
AMBER = "#B97816"

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_text(path: Path) -> str:
    with path.open("r", encoding="utf-8") as handle:
        value = handle.read()
    if not value.strip():
        raise ValueError(f"Evidence text is empty: {path}")
    return value


def resolve_pointer(document: Any, pointer: str) -> Any:
    """Resolve an RFC 6901 JSON Pointer; every missing segment raises."""
    if pointer == "":
        return document
    if not pointer.startswith("/"):
        raise ValueError(f"JSON Pointer must begin with '/': {pointer!r}")

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
            raise KeyError(f"Missing evidence field: {pointer}")
    return current


def require_number(value: Any, pointer: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"Expected a number at {pointer}, got {type(value).__name__}")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"Non-finite number at {pointer}: {value!r}")
    return number


def format_bound_value(results: dict[str, Any], value_spec: dict[str, Any]) -> str:
    if value_spec.get("source") != "results":
        raise ValueError(f"Unsupported evidence source: {value_spec.get('source')!r}")

    pointer = value_spec["path"]
    number = require_number(resolve_pointer(results, pointer), pointer)
    formatting = value_spec["format"]
    kind = formatting["kind"]
    digits = formatting.get("digits")

    if kind == "integer":
        if not number.is_integer():
            raise ValueError(f"Expected an integer-valued number at {pointer}: {number}")
        return f"{int(number):,}"
    if kind == "number":
        if not isinstance(digits, int) or digits < 0:
            raise ValueError(f"Invalid digits for {pointer}: {digits!r}")
        sign = "+" if formatting.get("show_plus", False) else ""
        return f"{number:{sign}.{digits}f}"
    if kind == "percent":
        if not isinstance(digits, int) or digits < 0:
            raise ValueError(f"Invalid digits for {pointer}: {digits!r}")
        return f"{number * 100:.{digits}f}%"
    raise ValueError(f"Unsupported format kind for {pointer}: {kind!r}")


def wrap(text: str, width: int) -> str:
    # The panel copy is predominantly Chinese.  With break_long_words=False,
    # textwrap treats an entire Chinese sentence as one word and therefore does
    # not wrap it at all.  Allowing long-word breaks makes ``width`` a real
    # per-line limit for CJK copy while still preferring whitespace boundaries
    # in the English source label.
    return "\n".join(
        textwrap.wrap(
            text,
            width=width,
            break_long_words=True,
            break_on_hyphens=False,
            replace_whitespace=False,
        )
    )


def add_rounded_box(
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
            facecolor=facecolor,
            edgecolor=edgecolor,
            linewidth=linewidth,
            transform=ax.transAxes,
            clip_on=False,
        )
    )


def validate_plan(plan: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    evidence = plan["evidence"]
    source = evidence["results"]
    source_label = source["label"]
    if source_label != EXPECTED_SOURCE_LABEL:
        raise ValueError("The strict-plan evidence label does not match the required label")

    panels = plan["panels"]
    names = tuple(panel["name"] for panel in panels)
    if names != EXPECTED_PANEL_NAMES:
        raise ValueError(f"Unexpected panel sequence: {names!r}")

    for panel in panels:
        required = {"name", "title", "alt", "sources", "blocks"}
        missing = required.difference(panel)
        if missing:
            raise KeyError(f"Panel {panel.get('name', '<unnamed>')} missing: {sorted(missing)}")
        if panel["sources"] != ["results"]:
            raise ValueError(f"Panel {panel['name']} must use only the results source")
        text_blocks = [block for block in panel["blocks"] if block.get("kind") == "text"]
        metric_blocks = [block for block in panel["blocks"] if block.get("kind") == "metric"]
        if len(text_blocks) != 1 or len(metric_blocks) != 3:
            raise ValueError(f"Panel {panel['name']} must contain one text and three metrics")
    return source_label, panels


def draw_metric_card(
    ax: plt.Axes,
    block: dict[str, Any],
    results: dict[str, Any],
    y: float,
    index: int,
) -> None:
    card_x, card_w, card_h = 0.665, 0.275, 0.165
    add_rounded_box(
        ax,
        card_x,
        y,
        card_w,
        card_h,
        facecolor=WHITE,
        edgecolor=LINE,
        linewidth=1.2,
        radius=0.014,
    )
    accent = (TEAL, BLUE, AMBER)[index]
    ax.add_patch(
        Rectangle(
            (card_x, y),
            0.008,
            card_h,
            facecolor=accent,
            edgecolor="none",
            transform=ax.transAxes,
        )
    )
    ax.text(
        card_x + 0.03,
        y + card_h - 0.025,
        block["label"],
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=15.5,
        color=MUTED,
        fontweight="medium",
    )
    ax.text(
        card_x + 0.03,
        y + 0.045,
        format_bound_value(results, block["value"]),
        transform=ax.transAxes,
        ha="left",
        va="bottom",
        fontsize=27,
        color=INK,
        fontweight="bold",
    )
    note = block.get("note")
    if note:
        ax.text(
            card_x + card_w - 0.018,
            y + 0.014,
            wrap(note, 16),
            transform=ax.transAxes,
            ha="right",
            va="bottom",
            fontsize=8.5,
            linespacing=1.10,
            color=MUTED,
        )


def render_panel(
    panel: dict[str, Any], results: dict[str, Any], source_label: str
) -> None:
    fig = plt.figure(figsize=(1600 / 150, 1000 / 150), dpi=150, facecolor=WHITE)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    # Header: the longest strict-plan title wraps onto two lines without
    # competing with the content region below.
    ax.add_patch(
        Rectangle((0, 0.805), 1, 0.195, facecolor=NAVY, edgecolor="none", transform=ax.transAxes)
    )
    ax.add_patch(
        Rectangle((0.056, 0.866), 0.010, 0.074, facecolor=TEAL, edgecolor="none", transform=ax.transAxes)
    )
    title = wrap(panel["title"], 20)
    ax.text(
        0.083,
        0.903,
        title,
        transform=ax.transAxes,
        ha="left",
        va="center",
        fontsize=30 if "\n" in title else 34,
        linespacing=1.18,
        color=WHITE,
        fontweight="bold",
    )

    text_block = next(block for block in panel["blocks"] if block["kind"] == "text")
    metric_blocks = [block for block in panel["blocks"] if block["kind"] == "metric"]

    add_rounded_box(ax, 0.056, 0.205, 0.565, 0.535, facecolor=PALE, radius=0.018)
    ax.text(
        0.088,
        0.685,
        text_block["heading"],
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=24,
        color=INK,
        fontweight="bold",
    )
    ax.plot(
        [0.088, 0.172],
        [0.642, 0.642],
        color=TEAL,
        linewidth=4,
        solid_capstyle="round",
        transform=ax.transAxes,
    )

    body_y = (0.588, 0.405)
    for index, paragraph in enumerate(text_block["body"]):
        ax.text(
            0.091,
            body_y[index],
            "●",
            transform=ax.transAxes,
            ha="center",
            va="top",
            fontsize=12,
            color=TEAL,
        )
        ax.text(
            0.112,
            body_y[index],
            wrap(paragraph, 23),
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=14.5,
            linespacing=1.42,
            color=INK,
        )

    for index, (block, y) in enumerate(zip(metric_blocks, (0.575, 0.385, 0.195))):
        draw_metric_card(ax, block, results, y, index)

    ax.plot([0.056, 0.94], [0.128, 0.128], color=LINE, linewidth=1, transform=ax.transAxes)
    ax.text(
        0.056,
        0.075,
        f"資料來源｜{source_label}",
        transform=ax.transAxes,
        ha="left",
        va="center",
        fontsize=10.5,
        color=MUTED,
    )
    ax.text(
        0.94,
        0.075,
        "VolPred",
        transform=ax.transAxes,
        ha="right",
        va="center",
        fontsize=13,
        color=NAVY_2,
        fontweight="bold",
    )

    output_path = os.path.join(out_dir, f"{panel['name']}.png")
    fig.savefig(
        output_path,
        dpi=150,
        facecolor=WHITE,
        metadata={"Title": panel["title"], "Description": panel["alt"]},
    )
    plt.close(fig)


def main() -> None:
    # All four evidence-package files are deliberately opened by absolute path.
    # The prose files are evidence/context checks; displayed numbers remain bound
    # exclusively to RESULTS_PATH through the strict plan's JSON Pointers.
    results = load_json(RESULTS_PATH)
    _readme = load_text(README_PATH)
    plan = load_json(PLAN_PATH)
    _article = load_text(ARTICLE_PATH)

    if not isinstance(results, dict) or not isinstance(plan, dict):
        raise TypeError("Results and plan evidence must be JSON objects")
    source_label, panels = validate_plan(plan)

    # Resolve and format all fields before creating any output, so a missing
    # evidence field fails the run before a partial panel set is written.
    for panel in panels:
        for block in panel["blocks"]:
            if block["kind"] == "metric":
                format_bound_value(results, block["value"])

    os.makedirs(out_dir, exist_ok=True)
    for panel in panels:
        render_panel(panel, results, source_label)


if __name__ == "__main__":
    main()
