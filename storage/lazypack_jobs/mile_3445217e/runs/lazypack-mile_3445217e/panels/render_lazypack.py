#!/usr/bin/env python3
"""Render the three data-bound PNG panels for mile_3445217e.

All displayed metrics are resolved from the strict plan into the pinned K1325
results JSON. Missing sources, fields, formats, or required panel structures
raise immediately instead of producing a partial or misleading graphic.
"""
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
    "/Users/yhlai0911/volpred-research/experiments/k1325/k1325_results.json"
)
README_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1325/README.md"
)
PLAN_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_3445217e/runs/lazypack-mile_3445217e/plan.json"
)
ARTICLE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_3445217e/runs/lazypack-mile_3445217e/panels/"
    "mile_3445217e_article.md"
)
out_dir = (
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_3445217e/runs/lazypack-mile_3445217e/panels"
)

WIDTH_PX = 1600
HEIGHT_PX = 1000
DPI = 150

NAVY = "#102A43"
INK = "#172B3A"
MUTED = "#526777"
LIGHT = "#E8EEF3"
PAPER = "#F5F8FA"
WHITE = "#FFFFFF"
TEAL = "#087F8C"
TEAL_LIGHT = "#DDF2F2"
RED = "#B44343"
RED_LIGHT = "#F9E5E3"
AMBER = "#B66A12"
AMBER_LIGHT = "#FAEDD8"

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def require_text(path: Path) -> str:
    """Read the required prose evidence so missing packages fail loudly."""
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError(f"Evidence file is empty: {path}")
    return text


def resolve_pointer(document: Any, pointer: str) -> Any:
    """Resolve a strict RFC 6901-style JSON pointer and raise on any miss."""
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValueError(f"Expected absolute JSON pointer, got {pointer!r}")
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


def format_bound_value(value_spec: dict[str, Any], sources: dict[str, Any]) -> str:
    source_id = value_spec["source"]
    if source_id not in sources:
        raise KeyError(f"Unknown evidence source: {source_id}")
    pointer = value_spec["path"]
    raw = resolve_pointer(sources[source_id], pointer)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise TypeError(f"Expected numeric evidence at {pointer}, got {type(raw).__name__}")

    fmt = value_spec["format"]
    kind = fmt["kind"]
    if kind == "integer":
        if isinstance(raw, float) and not raw.is_integer():
            raise ValueError(f"Expected integer-valued evidence at {pointer}, got {raw}")
        return f"{int(raw):d}"
    if kind == "number":
        digits = fmt["digits"]
        if not isinstance(digits, int) or digits < 0:
            raise ValueError(f"Invalid digits for {pointer}: {digits!r}")
        return f"{float(raw):.{digits}f}"
    raise ValueError(f"Unsupported metric format at {pointer}: {kind!r}")


def add_wrapped_text(
    ax: Any,
    x: float,
    y: float,
    text: str,
    *,
    width: int,
    fontsize: float,
    color: str,
    weight: str = "normal",
    line_height: float = 1.35,
    va: str = "top",
) -> None:
    wrapped = textwrap.fill(
        text,
        width=width,
        break_long_words=False,
        break_on_hyphens=False,
    )
    ax.text(
        x,
        y,
        wrapped,
        transform=ax.transAxes,
        ha="left",
        va=va,
        fontsize=fontsize,
        color=color,
        weight=weight,
        linespacing=line_height,
    )


def add_header(ax: Any, title: str) -> None:
    ax.add_patch(
        Rectangle((0, 0.81), 1, 0.19, transform=ax.transAxes, color=NAVY, zorder=0)
    )
    ax.text(
        0.065,
        0.905,
        title,
        transform=ax.transAxes,
        ha="left",
        va="center",
        fontsize=31,
        weight="bold",
        color=WHITE,
    )
    ax.add_patch(
        Rectangle((0.065, 0.835), 0.075, 0.008, transform=ax.transAxes, color="#42B3B8")
    )


def add_intro(ax: Any, block: dict[str, Any]) -> None:
    if block["kind"] != "text":
        raise ValueError("The first panel block must be text")
    ax.text(
        0.065,
        0.755,
        block["heading"],
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=20,
        weight="bold",
        color=INK,
    )
    body = block["body"]
    if not isinstance(body, list) or len(body) != 2 or not all(isinstance(x, str) for x in body):
        raise ValueError("Intro body must contain exactly two strings")
    add_wrapped_text(
        ax, 0.065, 0.708, body[0], width=55, fontsize=13.2, color=MUTED
    )
    add_wrapped_text(
        ax, 0.065, 0.635, body[1], width=55, fontsize=13.2, color=MUTED
    )


def metric_palette(value: str, panel_name: str, metric_index: int) -> tuple[str, str]:
    if panel_name == "panel_result" and metric_index >= 2:
        return RED_LIGHT, RED
    if panel_name == "panel_method":
        return AMBER_LIGHT, AMBER
    if panel_name == "panel_takeaway" and metric_index == 2:
        return RED_LIGHT, RED
    return TEAL_LIGHT, TEAL


def add_metric_card(
    ax: Any,
    metric: dict[str, Any],
    value: str,
    *,
    x: float,
    y: float,
    w: float,
    h: float,
    fill: str,
    accent: str,
) -> None:
    label = metric["label"]
    if not isinstance(label, str) or not label.strip():
        raise ValueError("Metric label must be a non-empty string")
    # Chinese labels contain no whitespace, so textwrap cannot wrap them while
    # break_long_words is disabled.  Split at the semantic boundary first,
    # then cap every remaining CJK line explicitly.  Eight full-width glyphs
    # plus the card padding fit safely in the narrow four-column cards.
    if "：" in label:
        subject, description = label.split("：", 1)
        description = description.strip()
        description_lines = [
            description[start : start + 8]
            for start in range(0, len(description), 8)
        ]
        label = "\n".join([subject.strip() + "：", *description_lines])

    card = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle="round,pad=0.012,rounding_size=0.018",
        transform=ax.transAxes,
        linewidth=1.0,
        edgecolor=LIGHT,
        facecolor=WHITE,
    )
    ax.add_patch(card)
    ax.add_patch(
        FancyBboxPatch(
            (x + 0.018, y + h - 0.035),
            0.052,
            0.012,
            boxstyle="round,pad=0.002,rounding_size=0.006",
            transform=ax.transAxes,
            linewidth=0,
            facecolor=accent,
        )
    )
    add_wrapped_text(
        ax,
        x + 0.022,
        y + h - 0.062,
        label,
        width=8,
        fontsize=10.5,
        color=MUTED,
        weight="bold",
        line_height=1.22,
    )
    ax.add_patch(
        FancyBboxPatch(
            (x + 0.020, y + 0.055),
            w - 0.040,
            0.102,
            boxstyle="round,pad=0.008,rounding_size=0.015",
            transform=ax.transAxes,
            linewidth=0,
            facecolor=fill,
        )
    )
    ax.text(
        x + 0.040,
        y + 0.106,
        value,
        transform=ax.transAxes,
        ha="left",
        va="center",
        fontsize=29,
        weight="bold",
        color=accent,
    )
    note = metric.get("note")
    if note is not None:
        if not isinstance(note, str):
            raise TypeError("Metric note must be a string")
        add_wrapped_text(
            ax,
            x + 0.022,
            y + 0.032,
            note,
            width=23,
            fontsize=9.7,
            color=MUTED,
            va="bottom",
            line_height=1.15,
        )


def add_source_footer(ax: Any, source_label: str) -> None:
    ax.plot([0.065, 0.935], [0.062, 0.062], transform=ax.transAxes, color=LIGHT, lw=1)
    label = "資料來源：" + source_label
    add_wrapped_text(
        ax,
        0.065,
        0.044,
        label,
        width=145,
        fontsize=7.3,
        color=MUTED,
        line_height=1.15,
    )


def validate_and_render_panel(
    panel: dict[str, Any], sources: dict[str, Any], labels: dict[str, str]
) -> None:
    name = panel["name"]
    expected_metric_counts = {
        "panel_result": 4,
        "panel_method": 4,
        "panel_takeaway": 3,
    }
    if name not in expected_metric_counts:
        raise ValueError(f"Unexpected panel name: {name}")
    if panel["style"] != "professional":
        raise ValueError(f"Panel {name} must use professional style")
    if not isinstance(panel["alt"], str) or not panel["alt"].strip():
        raise ValueError(f"Panel {name} requires non-empty alt text")
    source_ids = panel["sources"]
    if source_ids != ["results"]:
        raise ValueError(f"Panel {name} must be bound only to results evidence")

    blocks = panel["blocks"]
    if len(blocks) != expected_metric_counts[name] + 1:
        raise ValueError(f"Unexpected block count for {name}")
    metrics = blocks[1:]
    if any(metric["kind"] != "metric" for metric in metrics):
        raise ValueError(f"All non-intro blocks must be metrics in {name}")
    rendered_values = [format_bound_value(metric["value"], sources) for metric in metrics]

    fig = plt.figure(
        figsize=(WIDTH_PX / DPI, HEIGHT_PX / DPI), dpi=DPI, facecolor=WHITE
    )
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.add_patch(Rectangle((0, 0), 1, 1, transform=ax.transAxes, color=PAPER, zorder=-5))

    add_header(ax, panel["title"])
    add_intro(ax, blocks[0])

    if len(metrics) == 4:
        positions = [
            (0.065, 0.105, 0.205, 0.425),
            (0.287, 0.105, 0.205, 0.425),
            (0.509, 0.105, 0.205, 0.425),
            (0.731, 0.105, 0.205, 0.425),
        ]
    else:
        positions = [
            (0.065, 0.105, 0.270, 0.425),
            (0.365, 0.105, 0.270, 0.425),
            (0.665, 0.105, 0.270, 0.425),
        ]

    for index, (metric, value, position) in enumerate(
        zip(metrics, rendered_values, positions, strict=True)
    ):
        fill, accent = metric_palette(value, name, index)
        add_metric_card(
            ax,
            metric,
            value,
            x=position[0],
            y=position[1],
            w=position[2],
            h=position[3],
            fill=fill,
            accent=accent,
        )

    add_source_footer(ax, labels["results"])
    output_path = Path(out_dir) / f"{name}.png"
    fig.savefig(output_path, dpi=DPI, facecolor=WHITE, metadata={"Description": panel["alt"]})
    plt.close(fig)


def main() -> None:
    results = load_json(RESULTS_PATH)
    plan = load_json(PLAN_PATH)
    require_text(README_PATH)
    require_text(ARTICLE_PATH)

    evidence = plan["evidence"]
    result_evidence = evidence["results"]
    source_label = result_evidence["label"]
    if not isinstance(source_label, str) or not source_label.strip():
        raise ValueError("Strict plan evidence.results.label is missing or empty")
    expected_evidence_path = "experiments/k1325/k1325_results.json"
    if result_evidence["path"] != expected_evidence_path:
        raise ValueError("Strict plan points at an unexpected results evidence path")

    panels = plan["panels"]
    if not isinstance(panels, list) or [p["name"] for p in panels] != [
        "panel_result",
        "panel_method",
        "panel_takeaway",
    ]:
        raise ValueError("Strict plan must contain the three required panels in order")

    os.makedirs(out_dir, exist_ok=True)
    sources = {"results": results}
    labels = {"results": source_label}
    for panel in panels:
        validate_and_render_panel(panel, sources, labels)


if __name__ == "__main__":
    main()
