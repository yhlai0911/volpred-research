#!/usr/bin/env python3
"""Render the AI-capex funding-shift lazypack from its strict evidence package.

Every displayed statistic is resolved from ``evidence.json`` through the JSON
Pointer stored in ``plan.json``. Missing or malformed fields are fatal by
design: this renderer must never substitute or silently invent a value.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import textwrap
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.patches import FancyBboxPatch, Rectangle


REPO_ROOT = Path("/Users/yhlai0911/volpred-research")
PLAN_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_2d1d356b/runs/lazypack-mile_2d1d356b/plan.json"
)
EVIDENCE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_2d1d356b/evidence.json"
)
ARTICLE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_2d1d356b/runs/lazypack-mile_2d1d356b/panels/"
    "mile_2d1d356b_article.md"
)
OUT_DIR = (
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_2d1d356b/runs/lazypack-mile_2d1d356b/panels"
)

WIDTH_PX = 1600
HEIGHT_PX = 1000
DPI = 150

INK = "#172033"
MUTED = "#657083"
FAINT = "#98A2B3"
NAVY = "#172A46"
BLUE = "#2867B2"
BLUE_SOFT = "#E8F0FA"
TEAL = "#17837B"
TEAL_SOFT = "#E2F3F0"
AMBER = "#B06C16"
AMBER_SOFT = "#F8EEDC"
RED = "#B94747"
RED_SOFT = "#F8E7E7"
PAPER = "#F5F6F8"
WHITE = "#FFFFFF"
RULE = "#D8DEE8"

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False


def load_json(path: Path) -> Any:
    """Load JSON from an absolute path, preserving a visible traceback."""
    if not path.is_absolute():
        raise ValueError(f"JSON path must be absolute: {path}")
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def require_dict(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"Expected object at {where}, got {type(value).__name__}")
    return value


def require_list(value: Any, where: str) -> list[Any]:
    if not isinstance(value, list):
        raise TypeError(f"Expected array at {where}, got {type(value).__name__}")
    return value


def require_str(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"Expected non-empty string at {where}")
    return value


def require_number(value: Any, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"Expected number at {where}, got {type(value).__name__}")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"Expected finite number at {where}, got {value!r}")
    return number


def resolve_json_pointer(document: Any, pointer: str) -> Any:
    """Resolve RFC 6901-style object/array pointers and fail on every miss."""
    if pointer == "":
        return document
    if not pointer.startswith("/"):
        raise ValueError(f"JSON Pointer must start with '/': {pointer!r}")
    current = document
    for raw_token in pointer[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            if token not in current:
                raise KeyError(f"Missing evidence field at {pointer!r}")
            current = current[token]
        elif isinstance(current, list):
            if not token.isdigit():
                raise KeyError(f"Non-numeric array index in {pointer!r}")
            index = int(token)
            if index >= len(current):
                raise IndexError(f"Array index out of range in {pointer!r}")
            current = current[index]
        else:
            raise KeyError(f"Cannot descend through scalar in {pointer!r}")
    return current


def format_bound_value(raw: Any, spec: dict[str, Any], pointer: str) -> str:
    """Apply only the strict plan's supported number/percent formats."""
    number = require_number(raw, pointer)
    kind = require_str(spec.get("kind"), f"format for {pointer}")
    digits_raw = spec.get("digits")
    if isinstance(digits_raw, bool) or not isinstance(digits_raw, int):
        raise TypeError(f"Expected integer digits for {pointer}")
    if digits_raw < 0 or digits_raw > 6:
        raise ValueError(f"Unsupported digits={digits_raw} for {pointer}")

    if kind == "number":
        shown = number
    elif kind == "percent":
        shown = number * 100.0
    else:
        raise ValueError(f"Unsupported format kind {kind!r} for {pointer}")

    suffix = spec.get("suffix", "%" if kind == "percent" else "")
    if not isinstance(suffix, str):
        raise TypeError(f"Expected string suffix for {pointer}")
    return f"{shown:.{digits_raw}f}{suffix}"


def load_package() -> tuple[dict[str, Any], dict[str, Any], str]:
    plan = require_dict(load_json(PLAN_PATH), str(PLAN_PATH))
    evidence = require_dict(load_json(EVIDENCE_PATH), str(EVIDENCE_PATH))

    if not ARTICLE_PATH.is_absolute():
        raise ValueError(f"Article path must be absolute: {ARTICLE_PATH}")
    article = ARTICLE_PATH.read_text(encoding="utf-8")
    if not article.strip():
        raise ValueError(f"Article markdown is empty: {ARTICLE_PATH}")

    evidence_plan = require_dict(plan.get("evidence"), "plan.evidence")
    analysis_plan = require_dict(evidence_plan.get("analysis"), "plan.evidence.analysis")
    relative_path = require_str(analysis_plan.get("path"), "plan.evidence.analysis.path")
    planned_path = (REPO_ROOT / relative_path).resolve()
    if planned_path != EVIDENCE_PATH.resolve():
        raise ValueError(
            "plan.evidence.analysis.path does not identify the required evidence file: "
            f"{relative_path!r}"
        )

    expected_hash = require_str(
        analysis_plan.get("sha256"), "plan.evidence.analysis.sha256"
    )
    actual_hash = hashlib.sha256(EVIDENCE_PATH.read_bytes()).hexdigest()
    if actual_hash != expected_hash:
        raise ValueError(
            f"Evidence SHA-256 mismatch: expected {expected_hash}, got {actual_hash}"
        )

    return plan, evidence, article


def panel_by_name(plan: dict[str, Any], name: str) -> dict[str, Any]:
    panels = require_list(plan.get("panels"), "plan.panels")
    matches = [
        require_dict(item, f"plan.panels[{index}]")
        for index, item in enumerate(panels)
        if isinstance(item, dict) and item.get("name") == name
    ]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one panel named {name!r}, found {len(matches)}")
    return matches[0]


def metric_blocks(
    panel: dict[str, Any], evidence_by_source: dict[str, dict[str, Any]]
) -> list[tuple[str, str, str]]:
    """Return (label, formatted value, pointer) tuples bound to evidence."""
    blocks = require_list(panel.get("blocks"), f"panel {panel.get('name')}.blocks")
    metrics: list[tuple[str, str, str]] = []
    for index, raw_block in enumerate(blocks):
        block = require_dict(raw_block, f"panel {panel.get('name')}.blocks[{index}]")
        if block.get("kind") != "metric":
            continue
        label = require_str(block.get("label"), f"metric label at block {index}")
        value = require_dict(block.get("value"), f"metric value at block {index}")
        source = require_str(value.get("source"), f"metric source at block {index}")
        if source not in evidence_by_source:
            raise KeyError(f"Unknown evidence source {source!r} at block {index}")
        pointer = require_str(value.get("path"), f"metric path at block {index}")
        fmt = require_dict(value.get("format"), f"metric format at block {index}")
        raw_number = resolve_json_pointer(evidence_by_source[source], pointer)
        metrics.append((label, format_bound_value(raw_number, fmt, pointer), pointer))
    return metrics


def text_block(panel: dict[str, Any]) -> tuple[str, str]:
    blocks = require_list(panel.get("blocks"), f"panel {panel.get('name')}.blocks")
    found: list[tuple[str, str]] = []
    for index, raw_block in enumerate(blocks):
        block = require_dict(raw_block, f"panel {panel.get('name')}.blocks[{index}]")
        if block.get("kind") != "text":
            continue
        heading = require_str(block.get("heading"), f"text heading at block {index}")
        body_parts = require_list(block.get("body"), f"text body at block {index}")
        body = "".join(
            require_str(part, f"text body item at block {index}") for part in body_parts
        )
        found.append((heading, body))
    if len(found) != 1:
        raise ValueError(
            f"Expected exactly one text block in {panel.get('name')!r}, found {len(found)}"
        )
    return found[0]


def source_footer(panel: dict[str, Any], plan: dict[str, Any]) -> str:
    sources = require_list(panel.get("sources"), f"panel {panel.get('name')}.sources")
    evidence_plan = require_dict(plan.get("evidence"), "plan.evidence")
    labels: list[str] = []
    for index, raw_source in enumerate(sources):
        source = require_str(raw_source, f"source {index} for panel {panel.get('name')}")
        source_spec = require_dict(evidence_plan.get(source), f"plan.evidence.{source}")
        label = require_str(source_spec.get("label"), f"plan.evidence.{source}.label")
        if label not in labels:
            labels.append(label)
    if not labels:
        raise ValueError(f"Panel {panel.get('name')!r} has no source label")
    return "資料來源：" + "；".join(labels)


def wrap_zh(text: str, width: int) -> str:
    """Deterministically wrap Chinese prose without relying on renderer clipping."""
    return "\n".join(
        textwrap.wrap(
            text,
            width=width,
            break_long_words=True,
            break_on_hyphens=False,
            replace_whitespace=False,
        )
    )


def new_canvas(background: str = WHITE) -> tuple[Figure, Axes]:
    fig = plt.figure(
        figsize=(WIDTH_PX / DPI, HEIGHT_PX / DPI), dpi=DPI, facecolor=background
    )
    ax = fig.add_axes([0.0, 0.0, 1.0, 1.0])
    ax.set_xlim(0.0, 1.0)
    ax.set_ylim(0.0, 1.0)
    ax.axis("off")
    ax.set_facecolor(background)
    return fig, ax


def rounded_box(
    ax: Axes,
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    facecolor: str,
    edgecolor: str = "none",
    linewidth: float = 0.0,
    radius: float = 0.02,
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
        )
    )


def add_title(ax: Axes, panel: dict[str, Any], *, dark: bool = False) -> None:
    title = require_str(panel.get("title"), f"panel {panel.get('name')}.title")
    alt = require_str(panel.get("alt"), f"panel {panel.get('name')}.alt")
    color = WHITE if dark else INK
    alt_color = "#D8E2EF" if dark else MUTED
    ax.text(
        0.06,
        0.915,
        wrap_zh(title, 22),
        ha="left",
        va="center",
        fontsize=29,
        fontweight="bold",
        color=color,
        linespacing=1.08,
    )
    ax.text(
        0.06,
        0.795,
        wrap_zh(alt, 35),
        ha="left",
        va="center",
        fontsize=15,
        color=alt_color,
        linespacing=1.15,
    )


def add_footer(ax: Axes, footer: str, *, dark: bool = False) -> None:
    ax.plot([0.06, 0.94], [0.095, 0.095], color="#38506E" if dark else RULE, lw=1.0)
    ax.text(
        0.06,
        0.055,
        footer,
        ha="left",
        va="center",
        fontsize=10.5,
        color="#D8E2EF" if dark else MUTED,
    )


def save_panel(fig: Figure, panel: dict[str, Any], footer: str) -> None:
    name = require_str(panel.get("name"), "panel.name")
    title = require_str(panel.get("title"), f"panel {name}.title")
    alt = require_str(panel.get("alt"), f"panel {name}.alt")
    destination = os.path.join(OUT_DIR, f"{name}.png")
    fig.savefig(
        destination,
        dpi=DPI,
        facecolor=fig.get_facecolor(),
        edgecolor="none",
        bbox_inches=None,
        pad_inches=0,
        metadata={"Title": title, "Description": alt, "Source": footer},
    )
    plt.close(fig)


def render_funding_shift(
    panel: dict[str, Any], plan: dict[str, Any], evidence: dict[str, Any]
) -> None:
    if panel.get("style") != "professional":
        raise ValueError("panel_funding_shift must use professional style")
    metrics = metric_blocks(panel, {"analysis": evidence})
    if len(metrics) != 2:
        raise ValueError("panel_funding_shift must contain exactly two metrics")
    heading, body = text_block(panel)
    footer = source_footer(panel, plan)

    fig, ax = new_canvas(WHITE)
    ax.add_patch(Rectangle((0.0, 0.74), 1.0, 0.26, facecolor=NAVY, edgecolor="none"))
    add_title(ax, panel, dark=True)

    cards = [
        (0.06, BLUE_SOFT, BLUE, metrics[0]),
        (0.52, TEAL_SOFT, TEAL, metrics[1]),
    ]
    for x, fill, accent, (label, value, _pointer) in cards:
        rounded_box(ax, x, 0.455, 0.42, 0.205, facecolor=fill)
        ax.add_patch(Rectangle((x, 0.455), 0.010, 0.205, facecolor=accent, edgecolor="none"))
        ax.text(x + 0.035, 0.615, label, ha="left", va="center", fontsize=14, color=MUTED)
        ax.text(
            x + 0.035,
            0.525,
            value,
            ha="left",
            va="center",
            fontsize=31,
            fontweight="bold",
            color=accent,
        )

    rounded_box(ax, 0.06, 0.155, 0.88, 0.205, facecolor=PAPER)
    ax.text(0.09, 0.315, heading, ha="left", va="center", fontsize=15, fontweight="bold", color=INK)
    ax.text(
        0.09,
        0.235,
        wrap_zh(body, 38),
        ha="left",
        va="center",
        fontsize=16,
        color=INK,
        linespacing=1.35,
    )
    add_footer(ax, footer)
    save_panel(fig, panel, footer)


def render_cash_pressure(
    panel: dict[str, Any], plan: dict[str, Any], evidence: dict[str, Any]
) -> None:
    if panel.get("style") != "bento-grid":
        raise ValueError("panel_cash_pressure must use bento-grid style")
    metrics = metric_blocks(panel, {"analysis": evidence})
    if len(metrics) != 3:
        raise ValueError("panel_cash_pressure must contain exactly three metrics")
    heading, body = text_block(panel)
    footer = source_footer(panel, plan)

    fig, ax = new_canvas(PAPER)
    add_title(ax, panel)

    fills = [BLUE_SOFT, TEAL_SOFT, AMBER_SOFT]
    accents = [BLUE, TEAL, AMBER]
    x_positions = [0.06, 0.365, 0.67]
    for x, fill, accent, (label, value, _pointer) in zip(
        x_positions, fills, accents, metrics, strict=True
    ):
        rounded_box(ax, x, 0.485, 0.27, 0.25, facecolor=fill)
        ax.add_patch(Rectangle((x + 0.025, 0.690), 0.052, 0.007, facecolor=accent, edgecolor="none"))
        ax.text(x + 0.025, 0.655, label, ha="left", va="center", fontsize=13.5, color=MUTED)
        ax.text(
            x + 0.025,
            0.555,
            value,
            ha="left",
            va="center",
            fontsize=31,
            fontweight="bold",
            color=accent,
        )

    rounded_box(ax, 0.06, 0.155, 0.88, 0.215, facecolor=WHITE, edgecolor=RULE, linewidth=1.0)
    ax.text(0.09, 0.320, heading, ha="left", va="center", fontsize=15, fontweight="bold", color=RED)
    ax.text(
        0.09,
        0.235,
        wrap_zh(body, 38),
        ha="left",
        va="center",
        fontsize=16,
        color=INK,
        linespacing=1.35,
    )
    add_footer(ax, footer)
    save_panel(fig, panel, footer)


def render_market_gap(
    panel: dict[str, Any], plan: dict[str, Any], evidence: dict[str, Any]
) -> None:
    if panel.get("style") != "editorial":
        raise ValueError("panel_market_gap must use editorial style")
    metrics = metric_blocks(panel, {"analysis": evidence})
    if len(metrics) != 2:
        raise ValueError("panel_market_gap must contain exactly two metrics")
    heading, body = text_block(panel)
    footer = source_footer(panel, plan)

    fig, ax = new_canvas(WHITE)
    add_title(ax, panel)
    ax.plot([0.06, 0.94], [0.755, 0.755], color=INK, lw=2.0)

    current_label, current_value, _current_pointer = metrics[0]
    median_label, median_value, _median_pointer = metrics[1]

    rounded_box(ax, 0.06, 0.405, 0.53, 0.285, facecolor=NAVY)
    ax.text(0.095, 0.645, current_label, ha="left", va="center", fontsize=14, color="#D8E2EF")
    ax.text(
        0.095,
        0.525,
        current_value,
        ha="left",
        va="center",
        fontsize=34,
        fontweight="bold",
        color=WHITE,
    )
    ax.add_patch(Rectangle((0.095, 0.455), 0.105, 0.008, facecolor=TEAL, edgecolor="none"))

    rounded_box(ax, 0.63, 0.405, 0.31, 0.285, facecolor=PAPER)
    ax.text(0.665, 0.645, median_label, ha="left", va="center", fontsize=13.5, color=MUTED)
    ax.text(
        0.665,
        0.535,
        median_value,
        ha="left",
        va="center",
        fontsize=25,
        fontweight="bold",
        color=INK,
    )
    ax.add_patch(Rectangle((0.665, 0.455), 0.085, 0.008, facecolor=FAINT, edgecolor="none"))

    rounded_box(ax, 0.06, 0.155, 0.88, 0.175, facecolor=RED_SOFT)
    ax.text(0.09, 0.292, heading, ha="left", va="center", fontsize=14.5, fontweight="bold", color=RED)
    ax.text(
        0.09,
        0.222,
        wrap_zh(body, 38),
        ha="left",
        va="center",
        fontsize=15.5,
        color=INK,
        linespacing=1.32,
    )
    add_footer(ax, footer)
    save_panel(fig, panel, footer)


def main() -> None:
    plan, evidence, _article = load_package()
    os.makedirs(OUT_DIR, exist_ok=True)

    expected_names = {
        "panel_funding_shift",
        "panel_cash_pressure",
        "panel_market_gap",
    }
    actual_names = {
        require_str(require_dict(item, "plan.panels item").get("name"), "panel.name")
        for item in require_list(plan.get("panels"), "plan.panels")
    }
    if actual_names != expected_names:
        raise ValueError(
            f"Unexpected panel set: expected {sorted(expected_names)}, got {sorted(actual_names)}"
        )

    render_funding_shift(panel_by_name(plan, "panel_funding_shift"), plan, evidence)
    render_cash_pressure(panel_by_name(plan, "panel_cash_pressure"), plan, evidence)
    render_market_gap(panel_by_name(plan, "panel_market_gap"), plan, evidence)


if __name__ == "__main__":
    main()
