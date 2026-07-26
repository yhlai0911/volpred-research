#!/usr/bin/env python3
"""Render the three data-bound PNG panels for the mile_1ef77049 lazypack."""

from __future__ import annotations

import hashlib
import json
import numbers
import os
import textwrap
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle


RESULT_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1719/k1719_results.json"
)
README_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1719/README.md"
)
PLAN_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_1ef77049/runs/lazypack-mile_1ef77049/plan.json"
)
ARTICLE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_1ef77049/runs/lazypack-mile_1ef77049/panels/"
    "mile_1ef77049_article.md"
)
out_dir = (
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_1ef77049/runs/lazypack-mile_1ef77049/panels"
)

WIDTH_PX = 1600
HEIGHT_PX = 1000
DPI = 150

NAVY = "#11243A"
NAVY_2 = "#18324F"
INK = "#152536"
MUTED = "#5E6B78"
LINE = "#D9E1E8"
PAPER = "#FFFFFF"
PALE_BLUE = "#EEF4F8"
PALE_TEAL = "#E9F4F1"
PALE_RED = "#F9ECEA"
TEAL = "#19746A"
GREEN = "#247A60"
RED = "#B2453E"
GOLD = "#C7902D"
SOFT_GRAY = "#F5F7F9"

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["figure.facecolor"] = PAPER
plt.rcParams["savefig.facecolor"] = PAPER


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise TypeError(f"{path} 的頂層必須是 JSON object")
    return payload


def read_required_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError(f"evidence 檔案不可為空：{path}")
    return text


def require_mapping(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{context} 必須是 object")
    return value


def require_string(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{context} 必須是非空字串")
    return value


def get_path(payload: dict[str, Any], dotted_path: str) -> Any:
    current: Any = payload
    traversed: list[str] = []
    for part in dotted_path.split("."):
        traversed.append(part)
        if not isinstance(current, dict) or part not in current:
            raise KeyError(f"results 缺少必要欄位：{'.'.join(traversed)}")
        current = current[part]
    return current


def panel_by_name(plan: dict[str, Any], name: str) -> dict[str, Any]:
    panels = plan.get("panels")
    if not isinstance(panels, list):
        raise TypeError("plan.panels 必須是 array")
    matches = [
        require_mapping(panel, f"plan.panels[{index}]")
        for index, panel in enumerate(panels)
        if isinstance(panel, dict) and panel.get("name") == name
    ]
    if len(matches) != 1:
        raise KeyError(f"plan.panels 必須恰有一個 name={name!r}，實際為 {len(matches)} 個")
    return matches[0]


def block_by_label(panel: dict[str, Any], label: str) -> dict[str, Any]:
    blocks = panel.get("blocks")
    if not isinstance(blocks, list):
        raise TypeError(f"{panel.get('name')}.blocks 必須是 array")
    matches = [
        require_mapping(block, f"{panel.get('name')}.blocks[{index}]")
        for index, block in enumerate(blocks)
        if isinstance(block, dict) and block.get("label") == label
    ]
    if len(matches) != 1:
        raise KeyError(
            f"{panel.get('name')}.blocks 必須恰有一個 label={label!r}，"
            f"實際為 {len(matches)} 個"
        )
    return matches[0]


def block_by_heading(panel: dict[str, Any], heading: str) -> dict[str, Any]:
    blocks = panel.get("blocks")
    if not isinstance(blocks, list):
        raise TypeError(f"{panel.get('name')}.blocks 必須是 array")
    matches = [
        require_mapping(block, f"{panel.get('name')}.blocks[{index}]")
        for index, block in enumerate(blocks)
        if isinstance(block, dict) and block.get("heading") == heading
    ]
    if len(matches) != 1:
        raise KeyError(
            f"{panel.get('name')}.blocks 必須恰有一個 heading={heading!r}，"
            f"實際為 {len(matches)} 個"
        )
    return matches[0]


def metric_value(results: dict[str, Any], block: dict[str, Any]) -> str:
    if block.get("kind") != "metric":
        raise ValueError(f"{block.get('label')} 必須是 metric block")

    value_spec = require_mapping(block.get("value"), f"{block.get('label')}.value")
    if value_spec.get("source") != "result":
        raise ValueError(f"{block.get('label')} 的數值來源必須是 result")

    dotted_path = require_string(
        value_spec.get("path"), f"{block.get('label')}.value.path"
    )
    raw_value = get_path(results, dotted_path)
    if isinstance(raw_value, bool) or not isinstance(raw_value, numbers.Real):
        raise TypeError(f"{dotted_path} 必須是數值")

    format_spec = require_mapping(
        value_spec.get("format"), f"{block.get('label')}.value.format"
    )
    kind = format_spec.get("kind")
    suffix = format_spec.get("suffix", "")
    if not isinstance(suffix, str):
        raise TypeError(f"{block.get('label')}.value.format.suffix 必須是字串")

    if kind == "integer":
        if int(raw_value) != raw_value:
            raise ValueError(f"{dotted_path} 不是整數：{raw_value!r}")
        rendered = f"{int(raw_value):,d}"
    elif kind == "number":
        digits = format_spec.get("digits")
        if isinstance(digits, bool) or not isinstance(digits, int) or digits < 0:
            raise TypeError(f"{block.get('label')}.value.format.digits 必須是非負整數")
        sign = "+" if format_spec.get("show_plus") else ""
        rendered = format(float(raw_value), f"{sign}.{digits}f")
    else:
        raise ValueError(f"不支援的數值格式：{kind!r}")

    return f"{rendered}{suffix}"


def block_note(block: dict[str, Any]) -> str:
    return require_string(block.get("note"), f"{block.get('label')}.note")


def block_body(block: dict[str, Any]) -> str:
    if block.get("kind") != "text":
        raise ValueError(f"{block.get('heading')} 必須是 text block")
    body = block.get("body")
    if not isinstance(body, list) or not body:
        raise TypeError(f"{block.get('heading')}.body 必須是非空 array")
    paragraphs = [
        require_string(paragraph, f"{block.get('heading')}.body[{index}]")
        for index, paragraph in enumerate(body)
    ]
    return "\n".join(paragraphs)


def source_line(plan: dict[str, Any], panel: dict[str, Any]) -> str:
    sources = panel.get("sources")
    if not isinstance(sources, list) or not sources:
        raise TypeError(f"{panel.get('name')}.sources 必須是非空 array")
    evidence = require_mapping(plan.get("evidence"), "plan.evidence")
    labels: list[str] = []
    for source in sources:
        source_name = require_string(source, f"{panel.get('name')}.sources[]")
        source_spec = require_mapping(
            evidence.get(source_name), f"plan.evidence.{source_name}"
        )
        labels.append(
            require_string(
                source_spec.get("label"), f"plan.evidence.{source_name}.label"
            )
        )
    return "資料來源：" + "、".join(labels)


def wrap_text(text: str, width: int) -> str:
    if width <= 0:
        raise ValueError("折行寬度必須大於零")
    wrapped_paragraphs: list[str] = []
    for paragraph in text.splitlines() or [""]:
        lines = textwrap.wrap(
            paragraph,
            width=width,
            break_long_words=True,
            break_on_hyphens=False,
            drop_whitespace=True,
            replace_whitespace=False,
        )
        wrapped_paragraphs.append("\n".join(lines) if lines else "")
    return "\n".join(wrapped_paragraphs)


def new_figure() -> plt.Figure:
    return plt.figure(
        figsize=(WIDTH_PX / DPI, HEIGHT_PX / DPI),
        dpi=DPI,
        facecolor=PAPER,
    )


def add_text(
    fig: plt.Figure,
    x: float,
    y: float,
    text: str,
    *,
    size: float,
    color: str = INK,
    weight: str = "normal",
    ha: str = "left",
    va: str = "top",
    max_chars: int | None = None,
    linespacing: float = 1.24,
) -> None:
    rendered = wrap_text(text, max_chars) if max_chars is not None else text
    fig.text(
        x,
        y,
        rendered,
        fontsize=size,
        color=color,
        fontweight=weight,
        ha=ha,
        va=va,
        linespacing=linespacing,
        fontfamily="Heiti TC",
    )


def add_rect(
    fig: plt.Figure,
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    facecolor: str,
    edgecolor: str = "none",
    linewidth: float = 0.0,
) -> None:
    fig.patches.append(
        Rectangle(
            (x, y),
            width,
            height,
            transform=fig.transFigure,
            facecolor=facecolor,
            edgecolor=edgecolor,
            linewidth=linewidth,
        )
    )


def add_card(
    fig: plt.Figure,
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    facecolor: str = PAPER,
    edgecolor: str = LINE,
    linewidth: float = 1.2,
    radius: float = 0.018,
) -> None:
    fig.patches.append(
        FancyBboxPatch(
            (x, y),
            width,
            height,
            boxstyle=f"round,pad=0.008,rounding_size={radius}",
            transform=fig.transFigure,
            facecolor=facecolor,
            edgecolor=edgecolor,
            linewidth=linewidth,
        )
    )


def add_dark_header(fig: plt.Figure, panel: dict[str, Any]) -> None:
    title = require_string(panel.get("title"), f"{panel.get('name')}.title")
    alt = require_string(panel.get("alt"), f"{panel.get('name')}.alt")
    add_rect(fig, 0.0, 0.76, 1.0, 0.24, facecolor=NAVY)
    add_rect(fig, 0.0, 0.76, 0.016, 0.24, facecolor=GOLD)
    add_text(
        fig,
        0.065,
        0.932,
        title,
        size=32,
        color=PAPER,
        weight="bold",
        va="center",
    )
    add_text(
        fig,
        0.065,
        0.856,
        alt,
        size=16.5,
        color="#DCE6EE",
        max_chars=38,
        linespacing=1.18,
    )


def add_footer(fig: plt.Figure, text: str) -> None:
    add_rect(fig, 0.055, 0.092, 0.89, 0.002, facecolor=LINE)
    add_text(
        fig,
        0.055,
        0.052,
        text,
        size=12.5,
        color=MUTED,
        va="center",
        max_chars=58,
    )


def save_figure(fig: plt.Figure, filename: str) -> None:
    os.makedirs(out_dir, exist_ok=True)
    output_path = os.path.join(out_dir, filename)
    fig.savefig(
        output_path,
        dpi=DPI,
        facecolor=PAPER,
        edgecolor="none",
        bbox_inches=None,
        pad_inches=0,
    )
    plt.close(fig)


def render_method(
    results: dict[str, Any], plan: dict[str, Any], panel: dict[str, Any]
) -> None:
    days = block_by_label(panel, "日本實測比對天數")
    threshold = block_by_label(panel, "站得住腳的及格線")
    method = block_by_heading(panel, "怎麼比")

    fig = new_figure()
    add_dark_header(fig, panel)

    add_card(fig, 0.06, 0.43, 0.40, 0.27, facecolor=PALE_BLUE)
    add_text(
        fig,
        0.09,
        0.655,
        require_string(days.get("label"), "日本實測比對天數.label"),
        size=18,
        color=MUTED,
        weight="bold",
    )
    add_text(
        fig,
        0.09,
        0.545,
        metric_value(results, days),
        size=46,
        color=NAVY,
        weight="bold",
        va="center",
    )

    add_card(fig, 0.54, 0.43, 0.40, 0.27, facecolor=PALE_TEAL)
    add_text(
        fig,
        0.57,
        0.655,
        require_string(threshold.get("label"), "站得住腳的及格線.label"),
        size=18,
        color=MUTED,
        weight="bold",
    )
    add_text(
        fig,
        0.57,
        0.545,
        metric_value(results, threshold),
        size=46,
        color=TEAL,
        weight="bold",
        va="center",
    )
    add_text(
        fig,
        0.57,
        0.480,
        block_note(threshold),
        size=14,
        color=MUTED,
        max_chars=25,
    )

    add_card(fig, 0.06, 0.13, 0.88, 0.24, facecolor=PAPER)
    add_rect(fig, 0.06, 0.13, 0.009, 0.24, facecolor=GOLD)
    add_text(
        fig,
        0.09,
        0.340,
        require_string(method.get("heading"), "怎麼比.heading"),
        size=20,
        color=NAVY,
        weight="bold",
    )
    add_text(
        fig,
        0.09,
        0.280,
        block_body(method),
        size=16.2,
        color=INK,
        max_chars=34,
        linespacing=1.30,
    )

    add_footer(fig, source_line(plan, panel))
    save_figure(fig, "1_method.png")


def render_scorecard(
    results: dict[str, Any], plan: dict[str, Any], panel: dict[str, Any]
) -> None:
    japan_improvement = block_by_label(panel, "日本：預測誤差改善")
    japan_strength = block_by_label(panel, "日本：訊號強度")
    sea_strength = block_by_label(panel, "東南亞四國合併：訊號強度")
    improved_count = block_by_label(panel, "改善的市場數（六市場中）")
    strong_count = block_by_label(panel, "真正站得住腳的市場數")
    others = block_by_heading(panel, "其餘市場")

    fig = new_figure()
    add_dark_header(fig, panel)

    add_card(fig, 0.055, 0.48, 0.38, 0.26, facecolor=PALE_TEAL)
    add_rect(fig, 0.055, 0.48, 0.008, 0.26, facecolor=GREEN)
    add_text(
        fig,
        0.085,
        0.690,
        require_string(japan_improvement.get("label"), "日本：預測誤差改善.label"),
        size=17,
        color=MUTED,
        weight="bold",
    )
    add_text(
        fig,
        0.085,
        0.565,
        metric_value(results, japan_improvement),
        size=46,
        color=GREEN,
        weight="bold",
        va="center",
    )

    add_card(fig, 0.455, 0.48, 0.23, 0.26, facecolor=PALE_BLUE)
    add_text(
        fig,
        0.480,
        0.690,
        require_string(japan_strength.get("label"), "日本：訊號強度.label"),
        size=16.5,
        color=MUTED,
        weight="bold",
        max_chars=10,
    )
    add_text(
        fig,
        0.480,
        0.560,
        metric_value(results, japan_strength),
        size=36,
        color=NAVY,
        weight="bold",
        va="center",
    )
    add_text(
        fig,
        0.480,
        0.508,
        block_note(japan_strength),
        size=12.5,
        color=MUTED,
        max_chars=12,
    )

    add_card(fig, 0.705, 0.48, 0.24, 0.26, facecolor=SOFT_GRAY)
    add_text(
        fig,
        0.730,
        0.690,
        require_string(sea_strength.get("label"), "東南亞四國合併：訊號強度.label"),
        size=16.5,
        color=MUTED,
        weight="bold",
        max_chars=10,
        linespacing=1.18,
    )
    add_text(
        fig,
        0.730,
        0.560,
        metric_value(results, sea_strength),
        size=36,
        color=INK,
        weight="bold",
        va="center",
    )
    add_text(
        fig,
        0.730,
        0.508,
        block_note(sea_strength),
        size=12.5,
        color=MUTED,
        max_chars=13,
    )

    add_card(fig, 0.055, 0.16, 0.28, 0.26, facecolor=PAPER)
    add_text(
        fig,
        0.080,
        0.375,
        require_string(improved_count.get("label"), "改善的市場數.label"),
        size=15.5,
        color=MUTED,
        weight="bold",
        max_chars=13,
        linespacing=1.18,
    )
    add_text(
        fig,
        0.080,
        0.250,
        metric_value(results, improved_count),
        size=34,
        color=GOLD,
        weight="bold",
        va="center",
    )
    add_text(
        fig,
        0.080,
        0.202,
        block_note(improved_count),
        size=12.5,
        color=MUTED,
        max_chars=13,
    )

    add_card(fig, 0.355, 0.16, 0.28, 0.26, facecolor=PAPER)
    add_text(
        fig,
        0.380,
        0.375,
        require_string(strong_count.get("label"), "真正站得住腳的市場數.label"),
        size=15.5,
        color=MUTED,
        weight="bold",
        max_chars=13,
        linespacing=1.18,
    )
    add_text(
        fig,
        0.380,
        0.250,
        metric_value(results, strong_count),
        size=34,
        color=RED,
        weight="bold",
        va="center",
    )
    add_text(
        fig,
        0.380,
        0.202,
        block_note(strong_count),
        size=12.5,
        color=MUTED,
        max_chars=14,
    )

    add_card(fig, 0.655, 0.16, 0.29, 0.26, facecolor=NAVY_2, edgecolor=NAVY_2)
    add_text(
        fig,
        0.680,
        0.375,
        require_string(others.get("heading"), "其餘市場.heading"),
        size=18,
        color=PAPER,
        weight="bold",
    )
    add_text(
        fig,
        0.680,
        0.315,
        block_body(others),
        size=14.5,
        color="#E6EDF3",
        max_chars=12,
        linespacing=1.25,
    )

    add_footer(fig, source_line(plan, panel))
    save_figure(fig, "2_scorecard.png")


def add_chain_visual(fig: plt.Figure) -> None:
    node_y = 0.64
    node_h = 0.09
    nodes = (
        (0.07, 0.24, NAVY, PAPER, "美股／恐慌指數"),
        (0.39, 0.18, PALE_TEAL, GREEN, "日本"),
        (0.66, 0.27, SOFT_GRAY, MUTED, "台灣／東南亞"),
    )
    for x, width, facecolor, text_color, label in nodes:
        add_card(
            fig,
            x,
            node_y,
            width,
            node_h,
            facecolor=facecolor,
            edgecolor=facecolor if facecolor == NAVY else LINE,
            radius=0.014,
        )
        add_text(
            fig,
            x + width / 2,
            node_y + node_h / 2,
            label,
            size=17,
            color=text_color,
            weight="bold",
            ha="center",
            va="center",
        )

    first_arrow = FancyArrowPatch(
        (0.315, 0.685),
        (0.385, 0.685),
        transform=fig.transFigure,
        arrowstyle="-|>",
        mutation_scale=16,
        linewidth=2.2,
        color=GREEN,
    )
    second_arrow = FancyArrowPatch(
        (0.575, 0.685),
        (0.655, 0.685),
        transform=fig.transFigure,
        arrowstyle="-|>",
        mutation_scale=16,
        linewidth=1.8,
        linestyle="--",
        color="#9AA5AE",
    )
    fig.add_artist(first_arrow)
    fig.add_artist(second_arrow)
    add_text(
        fig,
        0.350,
        0.755,
        "隔夜資訊",
        size=11.5,
        color=GREEN,
        weight="bold",
        ha="center",
        va="bottom",
    )
    add_text(
        fig,
        0.615,
        0.755,
        "訊號散去",
        size=11.5,
        color=MUTED,
        weight="bold",
        ha="center",
        va="bottom",
    )


def render_takeaway(
    results: dict[str, Any], plan: dict[str, Any], panel: dict[str, Any]
) -> None:
    taiwan = block_by_label(panel, "台灣：加料後反而變差")
    supported = block_by_heading(panel, "能支持")
    unsupported = block_by_heading(panel, "不能支持")

    fig = new_figure()
    add_rect(fig, 0.06, 0.875, 0.010, 0.095, facecolor=RED)
    add_text(
        fig,
        0.09,
        0.925,
        require_string(panel.get("title"), "3_takeaway.title"),
        size=33,
        color=NAVY,
        weight="bold",
        va="center",
    )
    add_text(
        fig,
        0.09,
        0.855,
        require_string(panel.get("alt"), "3_takeaway.alt"),
        size=17,
        color=MUTED,
        max_chars=40,
    )

    add_chain_visual(fig)

    add_card(fig, 0.06, 0.15, 0.35, 0.41, facecolor=PALE_RED, edgecolor="#EACBC7")
    add_rect(fig, 0.06, 0.15, 0.009, 0.41, facecolor=RED)
    add_text(
        fig,
        0.09,
        0.510,
        require_string(taiwan.get("label"), "台灣：加料後反而變差.label"),
        size=19,
        color=MUTED,
        weight="bold",
        max_chars=15,
    )
    add_text(
        fig,
        0.09,
        0.380,
        metric_value(results, taiwan),
        size=48,
        color=RED,
        weight="bold",
        va="center",
    )
    add_text(
        fig,
        0.09,
        0.250,
        block_note(taiwan),
        size=14.2,
        color=INK,
        max_chars=16,
        linespacing=1.28,
    )

    add_card(fig, 0.44, 0.15, 0.24, 0.41, facecolor=PALE_TEAL, edgecolor="#CFE2DC")
    add_text(
        fig,
        0.465,
        0.510,
        require_string(supported.get("heading"), "能支持.heading"),
        size=18.5,
        color=GREEN,
        weight="bold",
    )
    add_text(
        fig,
        0.465,
        0.435,
        block_body(supported),
        size=15.2,
        color=INK,
        max_chars=9,
        linespacing=1.27,
    )

    add_card(fig, 0.70, 0.15, 0.25, 0.41, facecolor=SOFT_GRAY)
    add_text(
        fig,
        0.725,
        0.510,
        require_string(unsupported.get("heading"), "不能支持.heading"),
        size=18.5,
        color=RED,
        weight="bold",
    )
    add_text(
        fig,
        0.725,
        0.435,
        block_body(unsupported),
        size=15.2,
        color=INK,
        max_chars=9,
        linespacing=1.27,
    )

    add_footer(fig, source_line(plan, panel))
    save_figure(fig, "3_takeaway.png")


def main() -> None:
    plan = load_json(PLAN_PATH)

    evidence = require_mapping(plan.get("evidence"), "plan.evidence")
    result_spec = require_mapping(evidence.get("result"), "plan.evidence.result")
    expected_sha256 = require_string(
        result_spec.get("sha256"), "plan.evidence.result.sha256"
    )
    result_bytes = RESULT_PATH.read_bytes()
    actual_sha256 = hashlib.sha256(result_bytes).hexdigest()
    if actual_sha256 != expected_sha256:
        raise ValueError(
            "results evidence SHA-256 與 strict plan 不一致："
            f"expected={expected_sha256}, actual={actual_sha256}"
        )
    results = json.loads(result_bytes)
    if not isinstance(results, dict):
        raise TypeError(f"{RESULT_PATH} 的頂層必須是 JSON object")

    # These two evidence files contain the narrative and methodological context.
    # Reading them here makes a missing/empty evidence package fail loudly.
    read_required_text(README_PATH)
    read_required_text(ARTICLE_PATH)

    render_method(results, plan, panel_by_name(plan, "1_method"))
    render_scorecard(results, plan, panel_by_name(plan, "2_scorecard"))
    render_takeaway(results, plan, panel_by_name(plan, "3_takeaway"))


if __name__ == "__main__":
    main()
