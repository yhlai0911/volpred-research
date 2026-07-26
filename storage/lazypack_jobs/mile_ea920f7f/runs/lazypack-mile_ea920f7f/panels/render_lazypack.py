#!/usr/bin/env python3
"""Render the K1443 general-reader lazypack panels from the evidence package."""

from __future__ import annotations

import json
import os
import textwrap
from numbers import Integral, Real
from typing import Any, Mapping, Sequence

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle


RESULT_PATH = (
    "/Users/yhlai0911/volpred-research/experiments/k1443/"
    "k1443_results.json"
)
README_PATH = (
    "/Users/yhlai0911/volpred-research/experiments/k1443/"
    "README.md"
)
PLAN_PATH = (
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_ea920f7f/runs/lazypack-mile_ea920f7f/plan.json"
)
ARTICLE_PATH = (
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_ea920f7f/runs/lazypack-mile_ea920f7f/panels/"
    "mile_ea920f7f_article.md"
)
OUT_DIR = (
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_ea920f7f/runs/lazypack-mile_ea920f7f/panels"
)

WIDTH_PX = 1600
HEIGHT_PX = 1000
DPI = 150

INK = "#122033"
NAVY = "#14283F"
BLUE = "#3973E6"
CYAN = "#4AA8C8"
PAPER = "#F6F8FB"
WHITE = "#FFFFFF"
MUTED = "#657386"
LINE = "#DDE4EC"
SOFT_BLUE = "#EEF4FF"
SOFT_GREEN = "#EDF7F2"
GREEN = "#23825C"
SOFT_AMBER = "#FFF5E6"
AMBER = "#B86A18"
SOFT_RED = "#FFF0EF"
RED = "#B64B43"


plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False


def load_json(path: str) -> Mapping[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, Mapping):
        raise TypeError(f"Expected a JSON object at {path}")
    return value


def load_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as handle:
        value = handle.read()
    if not value.strip():
        raise ValueError(f"Evidence file is empty: {path}")
    return value


def require_key(mapping: Mapping[str, Any], key: str, context: str) -> Any:
    if key not in mapping:
        raise KeyError(f"Missing required field {context}.{key}")
    return mapping[key]


def require_path(root: Mapping[str, Any], path: str, context: str) -> Any:
    current: Any = root
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            raise KeyError(f"Missing required evidence field {context}.{path}")
        current = current[part]
    return current


def require_mapping(value: Any, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"Expected object at {context}")
    return value


def require_sequence(value: Any, context: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"Expected array at {context}")
    return value


def load_evidence() -> dict[str, Any]:
    evidence = {
        "result": load_json(RESULT_PATH),
        "plan": load_json(PLAN_PATH),
        "readme": load_text(README_PATH),
        "article": load_text(ARTICLE_PATH),
    }
    return evidence


def panel_from_plan(plan: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    panels = require_sequence(require_key(plan, "panels", "plan"), "plan.panels")
    matches = [
        require_mapping(panel, f"plan.panels[{index}]")
        for index, panel in enumerate(panels)
        if isinstance(panel, Mapping) and panel.get("name") == name
    ]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one panel named {name}, found {len(matches)}")
    return matches[0]


def block_at(
    panel: Mapping[str, Any],
    index: int,
    expected_kind: str,
) -> Mapping[str, Any]:
    panel_name = str(require_key(panel, "name", "panel"))
    blocks = require_sequence(
        require_key(panel, "blocks", f"panel.{panel_name}"),
        f"panel.{panel_name}.blocks",
    )
    try:
        block = require_mapping(blocks[index], f"panel.{panel_name}.blocks[{index}]")
    except IndexError as exc:
        raise KeyError(f"Missing panel.{panel_name}.blocks[{index}]") from exc
    kind = require_key(block, "kind", f"panel.{panel_name}.blocks[{index}]")
    if kind != expected_kind:
        raise ValueError(
            f"Expected panel.{panel_name}.blocks[{index}].kind={expected_kind!r}, "
            f"got {kind!r}"
        )
    return block


def block_body(block: Mapping[str, Any], context: str) -> str:
    body = require_sequence(require_key(block, "body", context), f"{context}.body")
    if not body or not all(isinstance(item, str) and item for item in body):
        raise ValueError(f"{context}.body must contain non-empty strings")
    return "\n".join(body)


def metric_value(block: Mapping[str, Any], evidence: Mapping[str, Any]) -> tuple[str, float]:
    value_spec = require_mapping(require_key(block, "value", "metric"), "metric.value")
    source = require_key(value_spec, "source", "metric.value")
    path = require_key(value_spec, "path", "metric.value")
    if not isinstance(source, str) or source not in evidence:
        raise KeyError(f"Unknown evidence source: {source!r}")
    if not isinstance(path, str) or not path:
        raise TypeError("metric.value.path must be a non-empty string")

    source_data = require_mapping(evidence[source], f"evidence.{source}")
    raw_value = require_path(source_data, path, f"evidence.{source}")
    if isinstance(raw_value, bool) or not isinstance(raw_value, Real):
        raise TypeError(f"Expected numeric value at evidence.{source}.{path}")

    format_spec = require_mapping(
        require_key(value_spec, "format", "metric.value"),
        "metric.value.format",
    )
    format_kind = require_key(format_spec, "kind", "metric.value.format")
    suffix = format_spec.get("suffix", "")
    if not isinstance(suffix, str):
        raise TypeError("metric.value.format.suffix must be a string")

    if format_kind == "integer":
        if not isinstance(raw_value, Integral) and float(raw_value) != int(raw_value):
            raise ValueError(f"Expected integer-compatible value at evidence.{source}.{path}")
        rendered = f"{int(raw_value):,}{suffix}"
    elif format_kind == "number":
        digits = require_key(format_spec, "digits", "metric.value.format")
        if isinstance(digits, bool) or not isinstance(digits, Integral) or digits < 0:
            raise TypeError("metric.value.format.digits must be a non-negative integer")
        rendered = f"{float(raw_value):.{int(digits)}f}{suffix}"
    else:
        raise ValueError(f"Unsupported metric format kind: {format_kind!r}")

    return rendered, float(raw_value)


def source_footer(panel: Mapping[str, Any], plan: Mapping[str, Any]) -> str:
    panel_name = str(require_key(panel, "name", "panel"))
    sources = require_sequence(
        require_key(panel, "sources", f"panel.{panel_name}"),
        f"panel.{panel_name}.sources",
    )
    evidence_plan = require_mapping(
        require_key(plan, "evidence", "plan"),
        "plan.evidence",
    )
    labels: list[str] = []
    for source in sources:
        if not isinstance(source, str):
            raise TypeError(f"panel.{panel_name}.sources must contain strings")
        source_spec = require_mapping(
            require_key(evidence_plan, source, "plan.evidence"),
            f"plan.evidence.{source}",
        )
        label = require_key(source_spec, "label", f"plan.evidence.{source}")
        if not isinstance(label, str) or not label:
            raise ValueError(f"plan.evidence.{source}.label must be non-empty")
        labels.append(label)
    if not labels:
        raise ValueError(f"panel.{panel_name}.sources must not be empty")
    return "資料來源：" + "、".join(labels)


def wrap_zh(text: str, width: int) -> str:
    if not isinstance(text, str) or not text:
        raise ValueError("Text content must be a non-empty string")
    return "\n".join(
        textwrap.wrap(
            text,
            width=width,
            break_long_words=True,
            break_on_hyphens=False,
            replace_whitespace=False,
            drop_whitespace=True,
        )
    )


def new_figure(background: str = WHITE) -> plt.Figure:
    figure = plt.figure(
        figsize=(WIDTH_PX / DPI, HEIGHT_PX / DPI),
        dpi=DPI,
        facecolor=background,
    )
    return figure


def rounded_box(
    figure: plt.Figure,
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
    patch = FancyBboxPatch(
        (x, y),
        width,
        height,
        boxstyle=f"round,pad=0,rounding_size={radius}",
        transform=figure.transFigure,
        facecolor=facecolor,
        edgecolor=edgecolor,
        linewidth=linewidth,
        clip_on=False,
    )
    figure.add_artist(patch)


def footer(figure: plt.Figure, text: str, color: str = MUTED) -> None:
    figure.add_artist(
        Rectangle(
            (0.07, 0.092),
            0.86,
            0.0015,
            transform=figure.transFigure,
            facecolor=LINE,
            edgecolor="none",
        )
    )
    figure.text(
        0.07,
        0.054,
        text,
        ha="left",
        va="center",
        fontsize=11.5,
        color=color,
    )


def save_panel(figure: plt.Figure, panel: Mapping[str, Any]) -> None:
    name = require_key(panel, "name", "panel")
    title = require_key(panel, "title", f"panel.{name}")
    alt = require_key(panel, "alt", f"panel.{name}")
    if not all(isinstance(item, str) and item for item in (name, title, alt)):
        raise ValueError("Panel name, title, and alt must be non-empty strings")
    output_path = os.path.join(OUT_DIR, f"{name}.png")
    figure.savefig(
        output_path,
        dpi=DPI,
        facecolor=figure.get_facecolor(),
        metadata={"Title": title, "Description": alt},
    )
    plt.close(figure)


def render_method(
    panel: Mapping[str, Any],
    plan: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> None:
    metric = block_at(panel, 0, "metric")
    explanation = block_at(panel, 1, "text")
    metric_text, _ = metric_value(metric, evidence)

    title = str(require_key(panel, "title", "panel.1_method"))
    alt = str(require_key(panel, "alt", "panel.1_method"))
    metric_label = str(require_key(metric, "label", "panel.1_method.blocks[0]"))
    metric_note = str(require_key(metric, "note", "panel.1_method.blocks[0]"))
    heading = str(require_key(explanation, "heading", "panel.1_method.blocks[1]"))
    body = block_body(explanation, "panel.1_method.blocks[1]")

    figure = new_figure(PAPER)
    figure.add_artist(
        Rectangle(
            (0.0, 0.80),
            1.0,
            0.20,
            transform=figure.transFigure,
            facecolor=NAVY,
            edgecolor="none",
        )
    )
    figure.text(
        0.07,
        0.925,
        title,
        ha="left",
        va="center",
        fontsize=34,
        fontweight="bold",
        color=WHITE,
    )
    figure.text(
        0.07,
        0.850,
        wrap_zh(alt, 43),
        ha="left",
        va="center",
        fontsize=17,
        color="#D8E3EF",
        linespacing=1.3,
    )

    rounded_box(
        figure,
        0.07,
        0.18,
        0.31,
        0.51,
        facecolor=WHITE,
        edgecolor=LINE,
        linewidth=1.2,
    )
    figure.add_artist(
        Rectangle(
            (0.07, 0.18),
            0.009,
            0.51,
            transform=figure.transFigure,
            facecolor=BLUE,
            edgecolor="none",
        )
    )
    figure.text(
        0.105,
        0.625,
        wrap_zh(metric_label, 16),
        ha="left",
        va="center",
        fontsize=17,
        color=MUTED,
    )
    figure.text(
        0.105,
        0.505,
        metric_text,
        ha="left",
        va="center",
        fontsize=49,
        fontweight="bold",
        color=INK,
    )
    figure.text(
        0.105,
        0.385,
        wrap_zh(metric_note, 17),
        ha="left",
        va="top",
        fontsize=14.5,
        color=MUTED,
        linespacing=1.45,
    )

    rounded_box(
        figure,
        0.42,
        0.18,
        0.51,
        0.51,
        facecolor=WHITE,
        edgecolor=LINE,
        linewidth=1.2,
    )
    figure.text(
        0.46,
        0.625,
        heading,
        ha="left",
        va="center",
        fontsize=21,
        fontweight="bold",
        color=INK,
    )
    figure.add_artist(
        Rectangle(
            (0.46, 0.578),
            0.055,
            0.006,
            transform=figure.transFigure,
            facecolor=CYAN,
            edgecolor="none",
        )
    )
    figure.text(
        0.46,
        0.545,
        wrap_zh(body, 21),
        ha="left",
        va="top",
        fontsize=15.5,
        color=INK,
        linespacing=1.45,
    )

    footer(figure, source_footer(panel, plan))
    save_panel(figure, panel)


def render_scorecard(
    panel: Mapping[str, Any],
    plan: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> None:
    metrics = [block_at(panel, index, "metric") for index in range(4)]
    values = [metric_value(metric, evidence) for metric in metrics]

    title = str(require_key(panel, "title", "panel.2_scorecard"))
    alt = str(require_key(panel, "alt", "panel.2_scorecard"))

    figure = new_figure(WHITE)
    figure.text(
        0.07,
        0.920,
        title,
        ha="left",
        va="center",
        fontsize=32,
        fontweight="bold",
        color=INK,
    )
    figure.text(
        0.07,
        0.848,
        wrap_zh(alt, 46),
        ha="left",
        va="center",
        fontsize=17,
        color=MUTED,
        linespacing=1.3,
    )
    figure.add_artist(
        Rectangle(
            (0.07, 0.790),
            0.86,
            0.003,
            transform=figure.transFigure,
            facecolor=BLUE,
            edgecolor="none",
        )
    )

    positions = [
        (0.07, 0.465),
        (0.52, 0.465),
        (0.07, 0.155),
        (0.52, 0.155),
    ]
    raw_values = [value[1] for value in values]
    closest_index = raw_values.index(min(raw_values))

    for index, (metric, (rendered, _), (x, y)) in enumerate(
        zip(metrics, values, positions)
    ):
        is_closest = index == closest_index
        card_background = SOFT_AMBER if is_closest else SOFT_BLUE
        accent = AMBER if is_closest else BLUE
        rounded_box(
            figure,
            x,
            y,
            0.41,
            0.27,
            facecolor=card_background,
            edgecolor=LINE,
            linewidth=1.0,
        )
        figure.add_artist(
            Rectangle(
                (x, y + 0.247),
                0.41,
                0.023,
                transform=figure.transFigure,
                facecolor=accent,
                edgecolor="none",
            )
        )
        label = str(require_key(metric, "label", f"panel.2_scorecard.blocks[{index}]"))
        note = str(require_key(metric, "note", f"panel.2_scorecard.blocks[{index}]"))
        figure.text(
            x + 0.035,
            y + 0.205,
            label,
            ha="left",
            va="center",
            fontsize=19,
            fontweight="bold",
            color=INK,
        )
        figure.text(
            x + 0.035,
            y + 0.125,
            f"p = {rendered}",
            ha="left",
            va="center",
            fontsize=42,
            fontweight="bold",
            color=accent,
        )
        figure.text(
            x + 0.035,
            y + 0.050,
            wrap_zh(note, 19),
            ha="left",
            va="center",
            fontsize=14,
            color=MUTED,
            linespacing=1.35,
        )

    footer(figure, source_footer(panel, plan))
    save_panel(figure, panel)


def render_takeaway(
    panel: Mapping[str, Any],
    plan: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> None:
    btc_metric = block_at(panel, 0, "metric")
    eth_metric = block_at(panel, 1, "metric")
    supported = block_at(panel, 2, "text")
    unsupported = block_at(panel, 3, "text")
    btc_text, btc_value = metric_value(btc_metric, evidence)
    eth_text, eth_value = metric_value(eth_metric, evidence)

    if not 0.0 <= btc_value <= 1.0:
        raise ValueError("BTC-SPY dynamic correlation mean must be in [0, 1]")
    if not 0.0 <= eth_value <= 1.0:
        raise ValueError("ETH-SPY dynamic correlation mean must be in [0, 1]")

    title = str(require_key(panel, "title", "panel.3_takeaway"))
    alt = str(require_key(panel, "alt", "panel.3_takeaway"))
    btc_label = str(require_key(btc_metric, "label", "panel.3_takeaway.blocks[0]"))
    btc_note = str(require_key(btc_metric, "note", "panel.3_takeaway.blocks[0]"))
    eth_label = str(require_key(eth_metric, "label", "panel.3_takeaway.blocks[1]"))
    supported_heading = str(
        require_key(supported, "heading", "panel.3_takeaway.blocks[2]")
    )
    unsupported_heading = str(
        require_key(unsupported, "heading", "panel.3_takeaway.blocks[3]")
    )
    supported_body = block_body(supported, "panel.3_takeaway.blocks[2]")
    unsupported_body = block_body(unsupported, "panel.3_takeaway.blocks[3]")

    figure = new_figure(PAPER)
    figure.text(
        0.07,
        0.920,
        title,
        ha="left",
        va="center",
        fontsize=32,
        fontweight="bold",
        color=INK,
    )
    figure.text(
        0.07,
        0.848,
        wrap_zh(alt, 46),
        ha="left",
        va="center",
        fontsize=17,
        color=MUTED,
        linespacing=1.3,
    )
    figure.add_artist(
        Rectangle(
            (0.07, 0.790),
            0.86,
            0.003,
            transform=figure.transFigure,
            facecolor=INK,
            edgecolor="none",
        )
    )

    rounded_box(
        figure,
        0.07,
        0.16,
        0.41,
        0.57,
        facecolor=NAVY,
        radius=0.022,
    )

    figure.text(
        0.105,
        0.665,
        wrap_zh(btc_label, 20),
        ha="left",
        va="center",
        fontsize=15.5,
        color="#D8E3EF",
        linespacing=1.3,
    )
    figure.text(
        0.105,
        0.585,
        btc_text,
        ha="left",
        va="center",
        fontsize=42,
        fontweight="bold",
        color=WHITE,
    )
    rounded_box(
        figure,
        0.105,
        0.510,
        0.325,
        0.018,
        facecolor="#31475E",
        radius=0.009,
    )
    rounded_box(
        figure,
        0.105,
        0.510,
        0.325 * btc_value,
        0.018,
        facecolor=CYAN,
        radius=0.009,
    )
    figure.text(
        0.105,
        0.470,
        wrap_zh(btc_note, 20),
        ha="left",
        va="top",
        fontsize=13.5,
        color="#BFD0E1",
        linespacing=1.35,
    )
    figure.add_artist(
        Rectangle(
            (0.105, 0.405),
            0.325,
            0.0015,
            transform=figure.transFigure,
            facecolor="#52667B",
            edgecolor="none",
        )
    )

    figure.text(
        0.105,
        0.360,
        wrap_zh(eth_label, 20),
        ha="left",
        va="center",
        fontsize=15.5,
        color="#D8E3EF",
        linespacing=1.3,
    )
    figure.text(
        0.105,
        0.282,
        eth_text,
        ha="left",
        va="center",
        fontsize=42,
        fontweight="bold",
        color=WHITE,
    )
    rounded_box(
        figure,
        0.105,
        0.212,
        0.325,
        0.018,
        facecolor="#31475E",
        radius=0.009,
    )
    rounded_box(
        figure,
        0.105,
        0.212,
        0.325 * eth_value,
        0.018,
        facecolor=BLUE,
        radius=0.009,
    )

    rounded_box(
        figure,
        0.52,
        0.490,
        0.41,
        0.24,
        facecolor=SOFT_GREEN,
        edgecolor=LINE,
        linewidth=1.0,
    )
    figure.add_artist(
        Rectangle(
            (0.52, 0.490),
            0.009,
            0.24,
            transform=figure.transFigure,
            facecolor=GREEN,
            edgecolor="none",
        )
    )
    figure.text(
        0.555,
        0.665,
        supported_heading,
        ha="left",
        va="center",
        fontsize=20,
        fontweight="bold",
        color=GREEN,
    )
    figure.text(
        0.555,
        0.615,
        wrap_zh(supported_body, 19),
        ha="left",
        va="top",
        fontsize=14,
        color=INK,
        linespacing=1.35,
    )

    rounded_box(
        figure,
        0.52,
        0.160,
        0.41,
        0.29,
        facecolor=SOFT_RED,
        edgecolor=LINE,
        linewidth=1.0,
    )
    figure.add_artist(
        Rectangle(
            (0.52, 0.160),
            0.009,
            0.29,
            transform=figure.transFigure,
            facecolor=RED,
            edgecolor="none",
        )
    )
    figure.text(
        0.555,
        0.395,
        unsupported_heading,
        ha="left",
        va="center",
        fontsize=20,
        fontweight="bold",
        color=RED,
    )
    figure.text(
        0.555,
        0.340,
        wrap_zh(unsupported_body, 20),
        ha="left",
        va="top",
        fontsize=13,
        color=INK,
        linespacing=1.32,
    )

    footer(figure, source_footer(panel, plan))
    save_panel(figure, panel)


def main() -> None:
    evidence = load_evidence()
    plan = require_mapping(evidence["plan"], "plan")

    os.makedirs(OUT_DIR, exist_ok=True)

    method_panel = panel_from_plan(plan, "1_method")
    scorecard_panel = panel_from_plan(plan, "2_scorecard")
    takeaway_panel = panel_from_plan(plan, "3_takeaway")

    render_method(method_panel, plan, evidence)
    render_scorecard(scorecard_panel, plan, evidence)
    render_takeaway(takeaway_panel, plan, evidence)


if __name__ == "__main__":
    main()
