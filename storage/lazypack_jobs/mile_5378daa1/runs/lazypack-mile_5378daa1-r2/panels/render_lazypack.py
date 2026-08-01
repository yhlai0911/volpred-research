#!/usr/bin/env python3
"""Render the four data-bound PNG panels for the mile_5378daa1 article."""

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


PLAN_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_5378daa1/runs/lazypack-mile_5378daa1-r2/plan.json"
)
RESULTS_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1450/k1450_results.json"
)
ARTICLE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_5378daa1/runs/lazypack-mile_5378daa1-r2/panels/"
    "mile_5378daa1_article.md"
)
out_dir = (
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_5378daa1/runs/lazypack-mile_5378daa1-r2/panels"
)

EXPECTED_PANELS = (
    "panel_question",
    "panel_result",
    "panel_not_stock",
    "panel_limit",
)

NAVY = "#13283F"
INK = "#152536"
MUTED = "#526271"
FAINT = "#7B8996"
LINE = "#DCE3E9"
PAPER = "#F4F7F9"
WHITE = "#FFFFFF"
TEAL = "#087F8C"
TEAL_SOFT = "#E7F4F4"
BLUE = "#2C5F8A"

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_inputs() -> tuple[dict[str, Any], dict[str, Any]]:
    plan = load_json(PLAN_PATH)
    results = load_json(RESULTS_PATH)

    # The article is part of the evidence package. Reading it here makes a missing
    # or empty package component fail loudly even though panel copy is canonical in
    # the strict plan.
    article = ARTICLE_PATH.read_text(encoding="utf-8")
    if not article.strip():
        raise ValueError(f"Article evidence is empty: {ARTICLE_PATH}")

    if not isinstance(plan, dict) or not isinstance(results, dict):
        raise TypeError("Plan and results evidence must both be JSON objects")
    if "panels" not in plan or "evidence" not in plan:
        raise KeyError("Strict plan must contain /panels and /evidence")
    if "results" not in plan["evidence"]:
        raise KeyError("Strict plan must contain /evidence/results")
    if "label" not in plan["evidence"]["results"]:
        raise KeyError("Strict plan must contain /evidence/results/label")

    panel_names = tuple(panel["name"] for panel in plan["panels"])
    if panel_names != EXPECTED_PANELS:
        raise ValueError(
            f"Unexpected panel order or names: {panel_names!r}; "
            f"expected {EXPECTED_PANELS!r}"
        )
    return plan, results


def resolve_json_pointer(document: Any, pointer: str) -> Any:
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValueError(f"Expected an absolute JSON Pointer, got {pointer!r}")
    current = document
    for raw_token in pointer[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            if token not in current:
                raise KeyError(f"Missing evidence field at {pointer!r}")
            current = current[token]
        elif isinstance(current, list):
            try:
                current = current[int(token)]
            except (ValueError, IndexError) as exc:
                raise KeyError(f"Missing evidence field at {pointer!r}") from exc
        else:
            raise KeyError(f"Cannot descend through evidence field at {pointer!r}")
    return current


def numeric_value(value: Any, pointer: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"Expected numeric evidence at {pointer!r}, got {value!r}")
    return float(value)


def format_bound_value(results: dict[str, Any], spec: dict[str, Any]) -> str:
    if spec["source"] != "results":
        raise ValueError(f"Unsupported evidence source: {spec['source']!r}")
    pointer = spec["path"]
    raw = resolve_json_pointer(results, pointer)
    fmt = spec["format"]
    kind = fmt["kind"]

    if kind == "integer":
        if isinstance(raw, bool) or not isinstance(raw, int):
            raise TypeError(f"Expected integer evidence at {pointer!r}, got {raw!r}")
        return f"{raw:,d}"

    number = numeric_value(raw, pointer)
    digits = fmt["digits"]
    if not isinstance(digits, int) or digits < 0:
        raise ValueError(f"Invalid digits value for {pointer!r}: {digits!r}")
    if kind == "number":
        sign = "+" if fmt.get("show_plus", False) else ""
        return f"{number:{sign}.{digits}f}"
    if kind == "percent":
        return f"{number * 100:.{digits}f}%"
    raise ValueError(f"Unsupported number format {kind!r} at {pointer!r}")


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


def add_metric_card(
    ax: Any,
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    label: str,
    value: str,
    note: str | None,
    accent: str,
) -> None:
    card = FancyBboxPatch(
        (x, y),
        width,
        height,
        boxstyle="round,pad=0.008,rounding_size=0.015",
        transform=ax.transAxes,
        linewidth=1.1,
        edgecolor=LINE,
        facecolor=WHITE,
        zorder=2,
    )
    ax.add_patch(card)
    ax.add_patch(
        Rectangle(
            (x, y + height - 0.010),
            width,
            0.010,
            transform=ax.transAxes,
            linewidth=0,
            facecolor=accent,
            zorder=3,
        )
    )
    ax.text(
        x + 0.020,
        y + height - 0.038,
        wrapped(label, 17),
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=13.5,
        color=MUTED,
        linespacing=1.18,
        zorder=4,
    )
    ax.text(
        x + 0.020,
        y + 0.093,
        value,
        transform=ax.transAxes,
        ha="left",
        va="center",
        fontsize=32,
        fontweight="bold",
        color=INK,
        zorder=4,
    )
    if note:
        ax.text(
            x + 0.020,
            y + 0.028,
            wrapped(note, 23),
            transform=ax.transAxes,
            ha="left",
            va="bottom",
            fontsize=9.5,
            color=FAINT,
            linespacing=1.16,
            zorder=4,
        )


def render_panel(
    panel: dict[str, Any],
    results: dict[str, Any],
    source_label: str,
) -> None:
    required_panel_keys = {"name", "title", "alt", "sources", "blocks"}
    missing = required_panel_keys.difference(panel)
    if missing:
        raise KeyError(f"Panel is missing required keys: {sorted(missing)}")
    if panel["sources"] != ["results"]:
        raise ValueError(f"Panel {panel['name']} must use only the results source")

    text_blocks = [block for block in panel["blocks"] if block["kind"] == "text"]
    metric_blocks = [block for block in panel["blocks"] if block["kind"] == "metric"]
    if len(text_blocks) != 1 or len(metric_blocks) != 3:
        raise ValueError(
            f"Panel {panel['name']} must have exactly one text block and three metrics"
        )
    text_block = text_blocks[0]
    if len(text_block["body"]) != 2:
        raise ValueError(f"Panel {panel['name']} must have exactly two body paragraphs")

    values = [
        format_bound_value(results, metric["value"]) for metric in metric_blocks
    ]

    # 10.666... x 6.666... inches at 150 dpi gives exactly 1600 x 1000 px.
    fig = plt.figure(figsize=(32 / 3, 20 / 3), dpi=150, facecolor=WHITE)
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    ax.add_patch(
        Rectangle(
            (0, 0.80), 1, 0.20, transform=ax.transAxes, facecolor=NAVY, linewidth=0
        )
    )
    ax.add_patch(
        Rectangle(
            (0.055, 0.865),
            0.008,
            0.070,
            transform=ax.transAxes,
            facecolor="#31B3B6",
            linewidth=0,
        )
    )
    ax.text(
        0.080,
        0.900,
        wrapped(panel["title"], 28),
        transform=ax.transAxes,
        ha="left",
        va="center",
        fontsize=27,
        fontweight="bold",
        color=WHITE,
        linespacing=1.16,
    )

    ax.text(
        0.060,
        0.745,
        text_block["heading"],
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=20,
        fontweight="bold",
        color=INK,
    )
    ax.add_patch(
        Rectangle(
            (0.060, 0.707),
            0.055,
            0.006,
            transform=ax.transAxes,
            facecolor=TEAL,
            linewidth=0,
        )
    )
    # Keep CJK body copy inside the content column.  Character-count wrapping
    # needs a conservative width here because Heiti TC glyphs are much wider
    # than the Latin-character average assumed by the previous 59-char limit.
    body_text = "\n\n".join(wrapped(paragraph, 42) for paragraph in text_block["body"])
    ax.text(
        0.060,
        0.675,
        body_text,
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=13.5,
        color=MUTED,
        linespacing=1.48,
    )

    ax.add_patch(
        Rectangle(
            (0, 0.090), 1, 0.310, transform=ax.transAxes, facecolor=PAPER, linewidth=0
        )
    )
    card_width = 0.276
    card_gap = 0.028
    card_y = 0.135
    card_height = 0.225
    accents = (BLUE, TEAL, NAVY)
    for index, (metric, value) in enumerate(zip(metric_blocks, values, strict=True)):
        add_metric_card(
            ax,
            x=0.058 + index * (card_width + card_gap),
            y=card_y,
            width=card_width,
            height=card_height,
            label=metric["label"],
            value=value,
            note=metric.get("note"),
            accent=accents[index],
        )

    ax.plot(
        [0.060, 0.940],
        [0.074, 0.074],
        transform=ax.transAxes,
        color=LINE,
        linewidth=0.9,
    )
    ax.text(
        0.060,
        0.043,
        f"資料來源｜{source_label}",
        transform=ax.transAxes,
        ha="left",
        va="center",
        fontsize=8.2,
        color=FAINT,
    )

    output_path = os.path.join(out_dir, f"{panel['name']}.png")
    fig.savefig(
        output_path,
        dpi=150,
        facecolor=WHITE,
        edgecolor="none",
        metadata={
            "Title": panel["title"],
            "Description": panel["alt"],
            "Source": source_label,
        },
    )
    plt.close(fig)


def main() -> None:
    plan, results = load_inputs()
    source_label = plan["evidence"]["results"]["label"]
    if not isinstance(source_label, str) or not source_label.strip():
        raise ValueError("Strict plan evidence label must be a non-empty string")

    os.makedirs(out_dir, exist_ok=True)
    for panel in plan["panels"]:
        render_panel(panel, results, source_label)


if __name__ == "__main__":
    main()
