#!/usr/bin/env python3
"""Render the Gold/Oil/VIX article lazypack from its strict evidence package."""

from __future__ import annotations

import hashlib
import json
import math
import os
import textwrap
from pathlib import Path
from typing import Any, Mapping

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch, Rectangle


PLAN_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_63ec8636/"
    "runs/lazypack-mile_63ec8636/plan.json"
)
EVIDENCE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_63ec8636/evidence.json"
)
ARTICLE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_63ec8636/"
    "runs/lazypack-mile_63ec8636/panels/mile_63ec8636_article.md"
)
OUT_DIR = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_63ec8636/"
    "runs/lazypack-mile_63ec8636/panels"
)

WIDTH_PX = 1600
HEIGHT_PX = 1000
DPI = 150

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False

INK = "#182334"
MUTED = "#5E6877"
FAINT = "#8791A0"
GRID = "#DCE2E9"
PAPER = "#F6F8FA"
WHITE = "#FFFFFF"
GOLD = "#B57A16"
GOLD_SOFT = "#F7ECD5"
OIL = "#176B66"
OIL_SOFT = "#DDEFEA"
BLUE = "#25678A"
BLUE_SOFT = "#E2F0F6"
RED = "#B64B43"
RED_SOFT = "#F6E6E3"


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise TypeError(f"Expected a JSON object at {path}")
    return payload


def required(mapping: Mapping[str, Any], key: str, context: str) -> Any:
    if key not in mapping:
        raise KeyError(f"Missing {context}.{key}")
    return mapping[key]


def resolve_pointer(document: Any, pointer: str) -> Any:
    """Resolve an RFC 6901-style JSON pointer and fail loudly on any miss."""
    if pointer == "":
        return document
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValueError(f"Invalid JSON pointer: {pointer!r}")
    current = document
    for raw_part in pointer[1:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, Mapping):
            if part not in current:
                raise KeyError(f"Missing evidence field at {pointer!r}: {part!r}")
            current = current[part]
        elif isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError) as exc:
                raise KeyError(f"Missing evidence list item at {pointer!r}") from exc
        else:
            raise KeyError(f"Cannot descend through {type(current).__name__} at {part!r}")
    return current


def format_metric(value: Any, fmt: Mapping[str, Any], pointer: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"Evidence value at {pointer!r} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"Evidence value at {pointer!r} must be finite")

    kind = required(fmt, "kind", f"format for {pointer}")
    suffix = fmt.get("suffix", "")
    if not isinstance(suffix, str):
        raise TypeError(f"Format suffix for {pointer!r} must be text")

    if kind == "integer":
        if not number.is_integer():
            raise ValueError(f"Evidence value at {pointer!r} is not an integer")
        return f"{int(number):,}{suffix}"
    if kind == "percent":
        digits = required(fmt, "digits", f"format for {pointer}")
        if not isinstance(digits, int) or digits < 0:
            raise ValueError(f"Invalid percent digits for {pointer!r}")
        sign = "+" if bool(fmt.get("show_plus", False)) else ""
        return f"{number * 100:{sign}.{digits}f}%{suffix}"
    if kind == "number":
        digits = required(fmt, "digits", f"format for {pointer}")
        if not isinstance(digits, int) or digits < 0:
            raise ValueError(f"Invalid number digits for {pointer!r}")
        return f"{number:.{digits}f}{suffix}"
    raise ValueError(f"Unsupported metric format kind {kind!r} at {pointer!r}")


def panel_by_name(plan: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    panels = required(plan, "panels", "plan")
    if not isinstance(panels, list):
        raise TypeError("plan.panels must be a list")
    matches = [p for p in panels if isinstance(p, Mapping) and p.get("name") == name]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one panel named {name!r}")
    return matches[0]


def metric(
    panel: Mapping[str, Any], label: str, evidence_by_source: Mapping[str, Any]
) -> tuple[str, float]:
    blocks = required(panel, "blocks", f"panel {panel.get('name')}")
    if not isinstance(blocks, list):
        raise TypeError(f"blocks for panel {panel.get('name')!r} must be a list")
    matches = [
        block
        for block in blocks
        if isinstance(block, Mapping)
        and block.get("kind") == "metric"
        and block.get("label") == label
    ]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one metric labelled {label!r}")
    spec = required(matches[0], "value", f"metric {label}")
    if not isinstance(spec, Mapping):
        raise TypeError(f"value spec for metric {label!r} must be an object")
    source = required(spec, "source", f"metric {label}.value")
    pointer = required(spec, "path", f"metric {label}.value")
    fmt = required(spec, "format", f"metric {label}.value")
    if source not in evidence_by_source:
        raise KeyError(f"Unknown evidence source {source!r} for metric {label!r}")
    if not isinstance(fmt, Mapping):
        raise TypeError(f"format for metric {label!r} must be an object")
    raw = resolve_pointer(evidence_by_source[source], pointer)
    rendered = format_metric(raw, fmt, pointer)
    return rendered, float(raw)


def narrative(panel: Mapping[str, Any], heading: str) -> str:
    blocks = required(panel, "blocks", f"panel {panel.get('name')}")
    matches = [
        block
        for block in blocks
        if isinstance(block, Mapping)
        and block.get("kind") == "text"
        and block.get("heading") == heading
    ]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one text block headed {heading!r}")
    body = required(matches[0], "body", f"text block {heading}")
    if not isinstance(body, list) or not body or not all(isinstance(x, str) for x in body):
        raise TypeError(f"body for text block {heading!r} must be a non-empty text list")
    return "\n".join(body)


def wrap_zh(text: str, max_units: float) -> str:
    """Wrap mixed Chinese/Latin text without relying on whitespace-only wrapping."""
    lines: list[str] = []
    current: list[str] = []
    units = 0.0
    for char in text:
        if char == "\n":
            lines.append("".join(current).strip())
            current, units = [], 0.0
            continue
        char_units = 0.55 if ord(char) < 128 else 1.0
        if current and units + char_units > max_units:
            lines.append("".join(current).strip())
            current, units = [], 0.0
        current.append(char)
        units += char_units
    if current:
        lines.append("".join(current).strip())
    return "\n".join(lines)


def new_canvas() -> tuple[plt.Figure, plt.Axes]:
    fig = plt.figure(
        figsize=(WIDTH_PX / DPI, HEIGHT_PX / DPI), dpi=DPI, facecolor=WHITE
    )
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    return fig, ax


def rounded_card(
    ax: plt.Axes,
    x: float,
    y: float,
    width: float,
    height: float,
    facecolor: str = WHITE,
    edgecolor: str = GRID,
    linewidth: float = 1.2,
    radius: float = 0.018,
) -> None:
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            width,
            height,
            boxstyle=f"round,pad=0.008,rounding_size={radius}",
            linewidth=linewidth,
            edgecolor=edgecolor,
            facecolor=facecolor,
            transform=ax.transAxes,
        )
    )


def add_header(fig: plt.Figure, ax: plt.Axes, panel: Mapping[str, Any]) -> None:
    title = required(panel, "title", f"panel {panel.get('name')}")
    alt = required(panel, "alt", f"panel {panel.get('name')}")
    if not isinstance(title, str) or not isinstance(alt, str):
        raise TypeError("Panel title and alt must be text")
    fig.text(0.055, 0.925, title, fontsize=29, fontweight="bold", color=INK, va="top")
    fig.text(0.055, 0.842, alt, fontsize=15.5, color=MUTED, va="top")
    ax.plot([0.055, 0.945], [0.795, 0.795], color=GRID, linewidth=1.2)


def source_text(plan: Mapping[str, Any], panel: Mapping[str, Any]) -> str:
    sources = required(panel, "sources", f"panel {panel.get('name')}")
    evidence_specs = required(plan, "evidence", "plan")
    if not isinstance(sources, list) or not sources:
        raise TypeError("panel.sources must be a non-empty list")
    if not isinstance(evidence_specs, Mapping):
        raise TypeError("plan.evidence must be an object")
    labels: list[str] = []
    for source in sources:
        spec = required(evidence_specs, source, "plan.evidence")
        if not isinstance(spec, Mapping):
            raise TypeError(f"Evidence spec {source!r} must be an object")
        label = required(spec, "label", f"plan.evidence.{source}")
        if not isinstance(label, str) or not label.strip():
            raise ValueError(f"Evidence label for {source!r} must be non-empty text")
        labels.append(label)
    return "；".join(labels)


def add_footer(fig: plt.Figure, ax: plt.Axes, plan: Mapping[str, Any], panel: Mapping[str, Any]) -> None:
    ax.plot([0.055, 0.945], [0.092, 0.092], color=GRID, linewidth=1.0)
    fig.text(
        0.055,
        0.047,
        f"資料來源：{source_text(plan, panel)}",
        fontsize=10.5,
        color=MUTED,
        va="center",
    )


def save_panel(fig: plt.Figure, name: str) -> None:
    fig.savefig(
        OUT_DIR / f"{name}.png",
        dpi=DPI,
        facecolor=WHITE,
        edgecolor="none",
        bbox_inches=None,
        pad_inches=0,
        metadata={"Title": name},
    )
    plt.close(fig)


def render_event_window(
    plan: Mapping[str, Any], panel: Mapping[str, Any], evidence_by_source: Mapping[str, Any]
) -> None:
    event_count, _ = metric(panel, "納入的衝突事件", evidence_by_source)
    gold_up_count, _ = metric(panel, "黃金事件日上漲", evidence_by_source)
    body = narrative(panel, "同一把尺")

    fig, ax = new_canvas()
    add_header(fig, ax, panel)

    rounded_card(ax, 0.055, 0.17, 0.565, 0.57, facecolor=WHITE)
    rounded_card(ax, 0.65, 0.17, 0.295, 0.57, facecolor=PAPER, edgecolor=PAPER)

    # Two evidence-bound sample metrics.
    for x, label, value, color, fill in (
        (0.078, "納入的衝突事件", event_count, BLUE, BLUE_SOFT),
        (0.348, "黃金事件日上漲", gold_up_count, GOLD, GOLD_SOFT),
    ):
        rounded_card(ax, x, 0.545, 0.245, 0.15, facecolor=fill, edgecolor=fill)
        fig.text(x + 0.02, 0.665, label, fontsize=14.5, color=INK, va="top")
        fig.text(x + 0.02, 0.615, value, fontsize=34, fontweight="bold", color=color, va="top")

    fig.text(0.083, 0.495, "事件窗比較方式", fontsize=16.5, fontweight="bold", color=INK, va="top")
    timeline_y = 0.355
    nodes = (
        (0.13, "前一個收盤", BLUE),
        (0.32, "衝突日", RED),
        (0.52, "後續路徑", GOLD),
    )
    for start, end in ((0.15, 0.295), (0.345, 0.495)):
        ax.add_patch(
            FancyArrowPatch(
                (start, timeline_y),
                (end, timeline_y),
                arrowstyle="-|>",
                mutation_scale=15,
                linewidth=1.8,
                color=FAINT,
                transform=ax.transAxes,
            )
        )
    for x, label, color in nodes:
        ax.add_patch(Circle((x, timeline_y), 0.017, transform=ax.transAxes, facecolor=color, edgecolor=WHITE, linewidth=2))
        fig.text(x, 0.309, label, fontsize=13.5, color=INK, ha="center", va="top")

    # Asset lanes explain the method without inventing additional observations.
    lane_y = (0.248, 0.212, 0.176)
    lane_labels = ("黃金", "原油", "恐慌指數")
    lane_colors = (GOLD, OIL, BLUE)
    for y, label, color in zip(lane_y, lane_labels, lane_colors):
        ax.plot([0.39, 0.56], [y, y], color=color, linewidth=3.0, solid_capstyle="round")
        ax.add_patch(Circle((0.39, y), 0.006, transform=ax.transAxes, facecolor=color, edgecolor="none"))
        fig.text(0.373, y, label, fontsize=11.5, color=MUTED, ha="right", va="center")

    fig.text(0.685, 0.685, "同一把尺", fontsize=20, fontweight="bold", color=INK, va="top")
    ax.add_patch(Circle((0.797, 0.497), 0.075, transform=ax.transAxes, facecolor=WHITE, edgecolor=BLUE, linewidth=2.2))
    ax.add_patch(Circle((0.797, 0.497), 0.043, transform=ax.transAxes, facecolor="none", edgecolor=BLUE, linewidth=1.4))
    ax.plot([0.725, 0.869], [0.497, 0.497], color=BLUE, linewidth=1.4)
    ax.plot([0.797, 0.797], [0.425, 0.569], color=BLUE, linewidth=1.4)
    fig.text(
        0.685,
        0.355,
        wrap_zh(body, 12),
        fontsize=13.5,
        color=INK,
        va="top",
        linespacing=1.5,
    )

    add_footer(fig, ax, plan, panel)
    save_panel(fig, required(panel, "name", "panel"))


def render_paths(
    plan: Mapping[str, Any], panel: Mapping[str, Any], evidence_by_source: Mapping[str, Any]
) -> None:
    gold_value, gold_raw = metric(panel, "黃金窗尾中位報酬", evidence_by_source)
    oil_value, oil_raw = metric(panel, "原油窗尾中位報酬", evidence_by_source)
    body = narrative(panel, "差別在路徑")

    fig, ax = new_canvas()
    add_header(fig, ax, panel)

    rounded_card(ax, 0.055, 0.445, 0.425, 0.295, facecolor=GOLD_SOFT, edgecolor=GOLD_SOFT)
    rounded_card(ax, 0.505, 0.445, 0.44, 0.295, facecolor=OIL_SOFT, edgecolor=OIL_SOFT)
    rounded_card(ax, 0.055, 0.155, 0.89, 0.245, facecolor=WHITE)

    fig.text(0.085, 0.695, "黃金窗尾中位報酬", fontsize=16, color=INK, va="top")
    fig.text(0.085, 0.62, gold_value, fontsize=47, fontweight="bold", color=GOLD, va="top")
    fig.text(0.535, 0.695, "原油窗尾中位報酬", fontsize=16, color=INK, va="top")
    fig.text(0.535, 0.62, oil_value, fontsize=47, fontweight="bold", color=OIL, va="top")

    # Endpoint glyphs are driven only by the signs and magnitudes of the two evidence fields.
    magnitude = max(abs(gold_raw), abs(oil_raw))
    if magnitude == 0:
        raise ValueError("Both endpoint returns are zero; comparison scale is undefined")
    for x0, raw, color in ((0.09, gold_raw, GOLD), (0.54, oil_raw, OIL)):
        baseline_y = 0.485
        ax.plot([x0, x0 + 0.31], [baseline_y, baseline_y], color=WHITE, linewidth=4.5, solid_capstyle="round")
        end_x = x0 + 0.155 + 0.135 * (raw / magnitude)
        ax.plot([x0 + 0.155, end_x], [baseline_y, baseline_y], color=color, linewidth=8, solid_capstyle="round")
        ax.add_patch(Circle((end_x, baseline_y), 0.012, transform=ax.transAxes, facecolor=color, edgecolor=WHITE, linewidth=2))

    fig.text(0.085, 0.355, "差別在路徑", fontsize=19, fontweight="bold", color=INK, va="top")
    fig.text(
        0.085,
        0.294,
        wrap_zh(body, 40),
        fontsize=16,
        color=MUTED,
        va="top",
        linespacing=1.55,
    )
    ax.add_patch(
        FancyArrowPatch(
            (0.745, 0.275),
            (0.865, 0.275),
            connectionstyle="arc3,rad=-0.28",
            arrowstyle="-|>",
            mutation_scale=20,
            linewidth=2.5,
            color=GOLD,
            transform=ax.transAxes,
        )
    )
    ax.add_patch(
        FancyArrowPatch(
            (0.865, 0.245),
            (0.765, 0.205),
            connectionstyle="arc3,rad=-0.22",
            arrowstyle="-|>",
            mutation_scale=20,
            linewidth=2.5,
            color=OIL,
            transform=ax.transAxes,
        )
    )

    add_footer(fig, ax, plan, panel)
    save_panel(fig, required(panel, "name", "panel"))


def render_false_signal(
    plan: Mapping[str, Any], panel: Mapping[str, Any], evidence_by_source: Mapping[str, Any]
) -> None:
    corr_value, corr_raw = metric(panel, "恐慌指數與標普日變動相關", evidence_by_source)
    p_value, p_raw = metric(panel, "分歧訊號控制後檢定值", evidence_by_source)
    body = narrative(panel, "帶走一句")
    if not -1.0 <= corr_raw <= 1.0:
        raise ValueError("Correlation evidence must lie between minus one and one")
    if not 0.0 <= p_raw <= 1.0:
        raise ValueError("p-value evidence must lie between zero and one")

    fig, ax = new_canvas()
    add_header(fig, ax, panel)

    rounded_card(ax, 0.055, 0.155, 0.56, 0.585, facecolor=BLUE_SOFT, edgecolor=BLUE_SOFT)
    rounded_card(ax, 0.65, 0.49, 0.295, 0.25, facecolor=RED_SOFT, edgecolor=RED_SOFT)
    rounded_card(ax, 0.65, 0.155, 0.295, 0.29, facecolor=WHITE)

    fig.text(0.085, 0.69, "恐慌指數與標普日變動相關", fontsize=16, color=INK, va="top")
    fig.text(0.085, 0.61, corr_value, fontsize=54, fontweight="bold", color=BLUE, va="top")

    # A restrained mirror motif: the opposite arrows visualize the negative sign.
    ax.plot([0.34, 0.34], [0.31, 0.665], color=WHITE, linewidth=3.0)
    ax.add_patch(Rectangle((0.337, 0.31), 0.006, 0.355, transform=ax.transAxes, facecolor=WHITE, edgecolor="none"))
    fig.text(0.265, 0.445, "恐慌指數", fontsize=15, color=INK, ha="center", va="center")
    fig.text(0.415, 0.445, "標普", fontsize=15, color=INK, ha="center", va="center")
    ax.add_patch(
        FancyArrowPatch(
            (0.285, 0.385),
            (0.285, 0.52),
            arrowstyle="-|>",
            mutation_scale=21,
            linewidth=3.0,
            color=BLUE,
            transform=ax.transAxes,
        )
    )
    ax.add_patch(
        FancyArrowPatch(
            (0.395, 0.52),
            (0.395, 0.385),
            arrowstyle="-|>",
            mutation_scale=21,
            linewidth=3.0,
            color=RED,
            transform=ax.transAxes,
        )
    )
    fig.text(0.335, 0.235, "同日變動方向高度相反", fontsize=14.5, color=MUTED, ha="center", va="center")

    fig.text(0.68, 0.69, "分歧訊號控制後檢定值", fontsize=15, color=INK, va="top")
    fig.text(0.68, 0.605, p_value, fontsize=42, fontweight="bold", color=RED, va="top")

    fig.text(0.68, 0.395, "帶走一句", fontsize=19, fontweight="bold", color=INK, va="top")
    fig.text(
        0.68,
        0.335,
        wrap_zh(body, 14),
        fontsize=15,
        color=INK,
        va="top",
        linespacing=1.55,
    )

    add_footer(fig, ax, plan, panel)
    save_panel(fig, required(panel, "name", "panel"))


def load_package() -> tuple[dict[str, Any], dict[str, Any], str]:
    plan = load_json(PLAN_PATH)
    evidence = load_json(EVIDENCE_PATH)
    article = ARTICLE_PATH.read_text(encoding="utf-8")
    if not article.strip():
        raise ValueError(f"Article is empty: {ARTICLE_PATH}")

    analysis_spec = required(required(plan, "evidence", "plan"), "analysis", "plan.evidence")
    if not isinstance(analysis_spec, Mapping):
        raise TypeError("plan.evidence.analysis must be an object")
    expected_sha = required(analysis_spec, "sha256", "plan.evidence.analysis")
    actual_sha = hashlib.sha256(EVIDENCE_PATH.read_bytes()).hexdigest()
    if actual_sha != expected_sha:
        raise ValueError(
            f"Evidence hash mismatch for {EVIDENCE_PATH}: expected {expected_sha}, got {actual_sha}"
        )
    return plan, evidence, article


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    plan, evidence, _article = load_package()
    evidence_by_source = {"analysis": evidence}

    expected_names = {"panel_event_window", "panel_paths", "panel_false_signal"}
    panels = required(plan, "panels", "plan")
    actual_names = {
        required(panel, "name", "panel")
        for panel in panels
        if isinstance(panel, Mapping)
    }
    if actual_names != expected_names:
        raise ValueError(f"Unexpected panel set: {sorted(actual_names)!r}")

    renderers = {
        "panel_event_window": render_event_window,
        "panel_paths": render_paths,
        "panel_false_signal": render_false_signal,
    }
    for name in ("panel_event_window", "panel_paths", "panel_false_signal"):
        panel = panel_by_name(plan, name)
        renderers[name](plan, panel, evidence_by_source)


if __name__ == "__main__":
    main()
