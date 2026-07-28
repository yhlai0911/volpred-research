#!/usr/bin/env python3
"""Render the four data-bound PNG panels for the K1436 reader article.

This script intentionally fails loudly when an evidence field or strict-plan value is
missing.  All displayed metrics are resolved from the evidence JSON at render time.
"""

import json
import os
import textwrap
from pathlib import Path
from typing import Any, Iterable

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle


RESULTS_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1436/k1436_results.json"
)
README_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1436/README.md"
)
PLAN_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_3c83e665/runs/lazypack-mile_3c83e665-r4/plan.json"
)
ARTICLE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_3c83e665/runs/lazypack-mile_3c83e665-r4/panels/"
    "mile_3c83e665_article.md"
)
out_dir = (
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_3c83e665/runs/lazypack-mile_3c83e665-r4/panels"
)

EXPECTED_SOURCE_LABEL = (
    "experiment K1436 results (BTC perpetual funding rate as HAR-RV covariate)"
)

INK = "#14213D"
NAVY = "#102A43"
BLUE = "#2F6BFF"
CYAN = "#39A9DB"
PALE_BLUE = "#EAF2FF"
PALE_CYAN = "#EAF8FB"
MUTED = "#52606D"
LIGHT = "#F5F7FA"
LINE = "#D9E2EC"
WHITE = "#FFFFFF"
AMBER = "#E9A23B"
GREEN = "#16876B"
RED = "#C94C4C"

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise TypeError(f"Expected a JSON object at {path}")
    return value


def require_text(path: Path) -> str:
    value = path.read_text(encoding="utf-8")
    if not value.strip():
        raise ValueError(f"Evidence file is empty: {path}")
    return value


def pointer(document: Any, json_pointer: str) -> Any:
    """Resolve an RFC 6901-style pointer and raise on every missing segment."""
    if not json_pointer.startswith("/"):
        raise ValueError(f"JSON pointer must start with '/': {json_pointer}")
    current = document
    for raw_part in json_pointer.split("/")[1:]:
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            if part not in current:
                raise KeyError(f"Missing evidence field: {json_pointer}")
            current = current[part]
        elif isinstance(current, list):
            current = current[int(part)]
        else:
            raise TypeError(f"Cannot descend through {part!r} in {json_pointer}")
    return current


def require_number(document: dict[str, Any], json_pointer: str) -> float:
    value = pointer(document, json_pointer)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"Evidence field is not numeric: {json_pointer}")
    return float(value)


def format_percent(document: dict[str, Any], json_pointer: str, digits: int) -> str:
    return f"{require_number(document, json_pointer) * 100:.{digits}f}%"


def format_integer(
    document: dict[str, Any], json_pointer: str, suffix: str = ""
) -> str:
    value = require_number(document, json_pointer)
    if not value.is_integer():
        raise ValueError(f"Expected integer-valued evidence field: {json_pointer}")
    return f"{int(value):,}{suffix}"


def format_number(document: dict[str, Any], json_pointer: str, digits: int) -> str:
    return f"{require_number(document, json_pointer):.{digits}f}"


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


def new_figure(title: str, subtitle: str | None = None):
    fig = plt.figure(figsize=(1600 / 150, 1000 / 150), dpi=150, facecolor=WHITE)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    ax.add_patch(Rectangle((0, 0.865), 1, 0.135, facecolor=NAVY, edgecolor="none"))
    fig.text(
        0.055,
        0.942 if subtitle else 0.925,
        title,
        color=WHITE,
        fontsize=30,
        fontweight="bold",
        ha="left",
        va="center",
    )
    if subtitle:
        fig.text(
            0.055,
            0.885,
            subtitle,
            color="#DCE8F4",
            fontsize=13,
            ha="left",
            va="center",
        )
    return fig, ax


def rounded_box(
    ax,
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    facecolor: str = WHITE,
    edgecolor: str = LINE,
    linewidth: float = 1.3,
    radius: float = 0.018,
):
    patch = FancyBboxPatch(
        (x, y),
        width,
        height,
        boxstyle=f"round,pad=0.012,rounding_size={radius}",
        facecolor=facecolor,
        edgecolor=edgecolor,
        linewidth=linewidth,
    )
    ax.add_patch(patch)
    return patch


def source_footer(fig, label: str) -> None:
    fig.text(
        0.055,
        0.032,
        f"資料來源：{label}",
        color=MUTED,
        fontsize=10.5,
        ha="left",
        va="center",
    )


def metric_card(
    fig,
    ax,
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    label: str,
    value: str,
    accent: str = BLUE,
    value_size: int = 31,
    label_top_offset: float = 0.055,
    value_bottom_offset: float = 0.055,
) -> None:
    rounded_box(ax, x, y, width, height, facecolor=WHITE)
    ax.add_patch(
        Rectangle(
            (x, y),
            0.009,
            height,
            facecolor=accent,
            edgecolor="none",
        )
    )
    fig.text(
        x + 0.028,
        y + height - label_top_offset,
        wrapped(label, 19),
        color=MUTED,
        fontsize=13,
        ha="left",
        va="top",
        linespacing=1.25,
    )
    fig.text(
        x + 0.028,
        y + value_bottom_offset,
        value,
        color=INK,
        fontsize=value_size,
        fontweight="bold",
        ha="left",
        va="bottom",
    )


def paragraph_block(
    fig,
    ax,
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    heading: str,
    paragraphs: Iterable[str],
    facecolor: str = LIGHT,
    accent: str = BLUE,
    wrap_width: int = 30,
    body_size: int = 15,
    body_linespacing: float = 1.5,
    paragraph_separator: str = "\n\n",
) -> None:
    rounded_box(ax, x, y, width, height, facecolor=facecolor, edgecolor=facecolor)
    fig.text(
        x + 0.03,
        y + height - 0.055,
        heading,
        color=accent,
        fontsize=17,
        fontweight="bold",
        ha="left",
        va="top",
    )
    body = paragraph_separator.join(
        wrapped(item, wrap_width) for item in paragraphs
    )
    fig.text(
        x + 0.03,
        y + height - 0.115,
        body,
        color=INK,
        fontsize=body_size,
        ha="left",
        va="top",
        linespacing=body_linespacing,
    )


def render_question(results: dict[str, Any], source_label: str) -> None:
    fig, ax = new_figure(
        "資金費率能預告比特幣波動嗎",
        "把熱門市場直覺，交給模型沒看過的日子驗證",
    )

    paragraph_block(
        fig,
        ax,
        x=0.055,
        y=0.18,
        width=0.49,
        height=0.60,
        heading="熱門主張",
        paragraphs=[
            "費率飆高＝多單太擠＝要變盤。這套說法把資金費率當成聰明錢的溫度計。",
            "合理歸合理，能不能真的預測波動，得拿沒看過的日子驗。",
        ],
        facecolor=LIGHT,
        accent=BLUE,
        wrap_width=22,
    )

    fig.text(
        0.605,
        0.795,
        "先看資料長什麼樣",
        color=INK,
        fontsize=17,
        fontweight="bold",
        ha="left",
        va="top",
    )
    metric_card(
        fig,
        ax,
        x=0.60,
        y=0.49,
        width=0.345,
        height=0.235,
        label="費率為正的比例（多方在付錢）",
        value=format_percent(
            results, "/funding_construction/pct_positive_8h", digits=1
        ),
        accent=CYAN,
    )
    metric_card(
        fig,
        ax,
        x=0.60,
        y=0.18,
        width=0.345,
        height=0.235,
        label="建構的每日波動樣本",
        value=format_integer(results, "/sample/n_days_total", suffix=" 天"),
        accent=BLUE,
    )
    source_footer(fig, source_label)
    fig.savefig(
        os.path.join(out_dir, "panel_question.png"),
        dpi=150,
        facecolor=WHITE,
        bbox_inches=None,
    )
    plt.close(fig)


def render_method(results: dict[str, Any], source_label: str) -> None:
    fig, ax = new_figure(
        "怎麼公平地測",
        "基準一致、資訊落後、模型外評分",
    )

    paragraph_block(
        fig,
        ax,
        x=0.055,
        y=0.54,
        width=0.89,
        height=0.23,
        heading="比法",
        paragraphs=[
            "基準模型只看過去的波動；對照組多加一個資金費率項。",
            "只拿模型沒見過的未來日子評分，全程只用前一天以前的資訊。",
        ],
        facecolor=PALE_BLUE,
        accent=BLUE,
        wrap_width=48,
    )

    stages = [
        ("過去波動", "建立基準"),
        ("加上費率", "唯一差異"),
        ("未來日子", "模型外評分"),
    ]
    stage_x = [0.075, 0.365, 0.655]
    for idx, ((heading, detail), x) in enumerate(zip(stages, stage_x)):
        rounded_box(
            ax,
            x,
            0.365,
            0.225,
            0.105,
            facecolor=WHITE,
            edgecolor=CYAN if idx == 1 else LINE,
            linewidth=2 if idx == 1 else 1.3,
        )
        fig.text(
            x + 0.1125,
            0.425,
            heading,
            color=INK,
            fontsize=16,
            fontweight="bold",
            ha="center",
            va="center",
        )
        fig.text(
            x + 0.1125,
            0.386,
            detail,
            color=MUTED,
            fontsize=12,
            ha="center",
            va="center",
        )
        if idx < len(stages) - 1:
            ax.annotate(
                "",
                xy=(stage_x[idx + 1] - 0.015, 0.417),
                xytext=(x + 0.24, 0.417),
                arrowprops=dict(arrowstyle="->", color=BLUE, lw=2),
            )

    metric_card(
        fig,
        ax,
        x=0.055,
        y=0.105,
        width=0.425,
        height=0.17,
        label="模型外實測日數",
        value=format_integer(results, "/sample/n_obs_oos", suffix=" 天"),
        accent=GREEN,
        value_size=24,
        label_top_offset=0.035,
        value_bottom_offset=0.020,
    )
    metric_card(
        fig,
        ax,
        x=0.52,
        y=0.105,
        width=0.425,
        height=0.17,
        label="滾動估計窗口",
        value=format_integer(results, "/sample/rolling_window", suffix=" 天"),
        accent=BLUE,
        value_size=24,
        label_top_offset=0.035,
        value_bottom_offset=0.020,
    )
    source_footer(fig, source_label)
    fig.savefig(
        os.path.join(out_dir, "panel_method.png"),
        dpi=150,
        facecolor=WHITE,
        bbox_inches=None,
    )
    plt.close(fig)


def render_result(results: dict[str, Any], source_label: str) -> None:
    fig, ax = new_figure(
        "兩條線幾乎疊在一起",
        "預測誤差越低越好；p 值用來判斷勝出是否可靠",
    )

    baseline_qlike = require_number(results, "/baseline/qlike")
    funding_qlike = require_number(results, "/with_funding/qlike")
    signed_p = require_number(results, "/clark_west/cw_pvalue_one_sided")
    absolute_p = require_number(
        results, "/clark_west_abs_funding/cw_pvalue_one_sided"
    )

    fig.text(
        0.055,
        0.81,
        "預測誤差",
        color=INK,
        fontsize=18,
        fontweight="bold",
        ha="left",
        va="center",
    )
    metric_card(
        fig,
        ax,
        x=0.055,
        y=0.53,
        width=0.425,
        height=0.22,
        label="基準預測誤差（越低越好）",
        value=f"{baseline_qlike:.3f}",
        accent=MUTED,
    )
    metric_card(
        fig,
        ax,
        x=0.52,
        y=0.53,
        width=0.425,
        height=0.22,
        label="加資金費率後的誤差",
        value=f"{funding_qlike:.3f}",
        accent=BLUE,
    )

    fig.text(
        0.055,
        0.455,
        "顯著度",
        color=INK,
        fontsize=18,
        fontweight="bold",
        ha="left",
        va="center",
    )
    metric_card(
        fig,
        ax,
        x=0.055,
        y=0.15,
        width=0.425,
        height=0.245,
        label="看方向：顯著度 p 值（過不了門檻）",
        value=f"{signed_p:.3f}",
        accent=RED,
    )
    metric_card(
        fig,
        ax,
        x=0.52,
        y=0.15,
        width=0.425,
        height=0.245,
        label="看強度：顯著度 p 值（勉強擦邊）",
        value=f"{absolute_p:.3f}",
        accent=AMBER,
    )
    source_footer(fig, source_label)
    fig.savefig(
        os.path.join(out_dir, "panel_result.png"),
        dpi=150,
        facecolor=WHITE,
        bbox_inches=None,
    )
    plt.close(fig)


def render_takeaway(results: dict[str, Any], source_label: str) -> None:
    # Resolve the result fields that substantiate the editorial conclusion.  They are
    # deliberately not reprinted: this panel is a takeaway, not another metric panel.
    require_number(results, "/clark_west/cw_pvalue_one_sided")
    require_number(results, "/clark_west_abs_funding/cw_pvalue_one_sided")
    require_number(results, "/baseline/qlike")
    require_number(results, "/with_funding/qlike")

    fig, ax = new_figure("訊號早被更基本的東西吃掉了")

    # Main visual: funding enters a funnel, while the established volatility baseline
    # occupies the foreground.  It is intentionally abstract and non-cartoon.
    ax.add_patch(
        FancyBboxPatch(
            (0.055, 0.16),
            0.34,
            0.62,
            boxstyle="round,pad=0.014,rounding_size=0.025",
            facecolor=NAVY,
            edgecolor="none",
        )
    )
    fig.text(
        0.09,
        0.69,
        "資金費率",
        color="#BFD7EA",
        fontsize=16,
        ha="left",
        va="center",
    )
    ax.plot([0.10, 0.34], [0.62, 0.62], color=CYAN, lw=5, solid_capstyle="round")
    ax.annotate(
        "",
        xy=(0.34, 0.49),
        xytext=(0.13, 0.49),
        arrowprops=dict(arrowstyle="->", color=CYAN, lw=3),
    )
    fig.text(
        0.225,
        0.405,
        "昨天的波動\n已先解釋大部分",
        color=WHITE,
        fontsize=23,
        fontweight="bold",
        ha="center",
        va="center",
        linespacing=1.35,
    )
    fig.text(
        0.225,
        0.235,
        "新增訊號留下的空間很小",
        color="#BFD7EA",
        fontsize=13,
        ha="center",
        va="center",
    )

    paragraph_block(
        fig,
        ax,
        x=0.45,
        y=0.48,
        width=0.495,
        height=0.30,
        heading="結論",
        paragraphs=[
            "方向：對次日波動沒有可靠的額外資訊。",
            "強度：勉強顯著，但誤差改善微乎其微，經濟上約等於零。",
        ],
        facecolor=PALE_BLUE,
        accent=BLUE,
        wrap_width=22,
        body_size=12,
        body_linespacing=1.25,
        paragraph_separator="\n",
    )
    paragraph_block(
        fig,
        ax,
        x=0.45,
        y=0.16,
        width=0.495,
        height=0.25,
        heading="為什麼",
        paragraphs=[
            "費率飆高時波動通常本來就在高檔，而昨天的波動基準模型早看到了。",
            "資金費率對套利成本很實在，但拿來預判波動這條路走不通。",
        ],
        facecolor=LIGHT,
        accent=GREEN,
        wrap_width=22,
        body_size=12,
        body_linespacing=1.25,
        paragraph_separator="\n",
    )
    source_footer(fig, source_label)
    fig.savefig(
        os.path.join(out_dir, "panel_takeaway.png"),
        dpi=150,
        facecolor=WHITE,
        bbox_inches=None,
    )
    plt.close(fig)


def main() -> None:
    results = load_json(RESULTS_PATH)
    plan = load_json(PLAN_PATH)
    require_text(README_PATH)
    require_text(ARTICLE_PATH)

    source_label = pointer(plan, "/evidence/results/label")
    if not isinstance(source_label, str):
        raise TypeError("Strict-plan source label must be a string")
    if source_label != EXPECTED_SOURCE_LABEL:
        raise ValueError(
            "Strict-plan source label changed; refusing to render with an "
            "unverified reader-facing source name"
        )

    panel_names = pointer(plan, "/panels")
    if not isinstance(panel_names, list):
        raise TypeError("Strict-plan panels must be a list")
    actual_names = [
        item["name"] if isinstance(item, dict) and "name" in item else None
        for item in panel_names
    ]
    expected_names = [
        "panel_question",
        "panel_method",
        "panel_result",
        "panel_takeaway",
    ]
    if actual_names != expected_names:
        raise ValueError(
            f"Strict-plan panel order/names changed: expected {expected_names}, "
            f"got {actual_names}"
        )

    os.makedirs(out_dir, exist_ok=True)
    render_question(results, source_label)
    render_method(results, source_label)
    render_result(results, source_label)
    render_takeaway(results, source_label)


if __name__ == "__main__":
    main()
