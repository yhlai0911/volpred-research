#!/usr/bin/env python3
"""Render the three data-bound PNG panels for the AI-power-volatility article."""

from __future__ import annotations

import json
import math
import os
import re
import textwrap
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch, Rectangle


DATA_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/drafts/assets/"
    "trending_ai_power_vol_20260715_data.json"
)
ARTICLE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/drafts/assets/"
    "trending_ai_power_vol_20260715_lazypack_codex/mile_50ce135b_article.md"
)
OUT_DIR = (
    "/Users/yhlai0911/volpred-research/storage/drafts/assets/"
    "trending_ai_power_vol_20260715_lazypack_codex"
)

DPI = 150
WIDTH_PX = 1600
HEIGHT_PX = 1000

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False

NAVY = "#14263D"
INK = "#182230"
MUTED = "#536174"
FAINT = "#7A8797"
GRID = "#DCE3EA"
PAPER = "#FFFFFF"
PALE = "#F5F7FA"
TEAL = "#148A86"
TEAL_SOFT = "#E8F5F3"
ORANGE = "#D46A2F"
ORANGE_SOFT = "#FAEEE7"
BLUE = "#34699A"
BLUE_SOFT = "#EAF1F8"
GREEN = "#2F7D5C"
GREEN_SOFT = "#E9F4EE"
RED = "#B84A4A"
RED_SOFT = "#F8EAEA"


def load_inputs() -> tuple[dict[str, Any], str]:
    with DATA_PATH.open("r", encoding="utf-8") as handle:
        evidence = json.load(handle)
    if not isinstance(evidence, dict):
        raise TypeError(f"Evidence root must be a JSON object: {DATA_PATH}")

    with ARTICLE_PATH.open("r", encoding="utf-8") as handle:
        article = handle.read()
    if not article.strip():
        raise ValueError(f"Article evidence is empty: {ARTICLE_PATH}")
    return evidence, article


def require_number(evidence: dict[str, Any], path: str) -> float:
    current: Any = evidence
    for key in path.split("."):
        if not isinstance(current, dict) or key not in current:
            raise KeyError(f"Missing required evidence field: {path}")
        current = current[key]
    if isinstance(current, bool) or not isinstance(current, (int, float)):
        raise TypeError(f"Evidence field must be numeric: {path}")
    value = float(current)
    if not math.isfinite(value):
        raise ValueError(f"Evidence field must be finite: {path}")
    return value


def bind_values(evidence: dict[str, Any]) -> dict[str, float]:
    paths = {
        "smh_current": "SMH.rv20_current",
        "smh_median": "SMH.rv20_median_1y",
        "xlu_current": "XLU.rv20_current",
        "xlu_median": "XLU.rv20_median_1y",
        "corr_current": "_power_vs_SMH_corr60.current",
        "corr_3m": "_power_vs_SMH_corr60.3m_ago",
        "corr_1y_median": "_power_vs_SMH_corr60.1y_median",
        "gev_return": "GEV.ytd_return_pct",
        "gev_current": "GEV.rv20_current",
        "ceg_return": "CEG.ytd_return_pct",
    }
    return {name: require_number(evidence, path) for name, path in paths.items()}


def source_note_from_article(article: str) -> str:
    match = re.search(
        r"\*資料來源：(.*?)所有數字可自行以公開資料複驗",
        article,
        flags=re.DOTALL,
    )
    if match is None:
        raise ValueError(f"Article evidence lacks its source/method paragraph: {ARTICLE_PATH}")
    detail = " ".join(match.group(1).split()).rstrip("。 ")
    return f"資料來源：{detail}。"


def fmt_pct(value: float) -> str:
    return f"{value:.1f}%"


def fmt_signed_pct(value: float) -> str:
    sign = "+" if value >= 0 else "−"
    return f"{sign}{abs(value):.1f}%"


def fmt_corr(value: float) -> str:
    return f"{value:.2f}"


def wrap_zh(text: str, width: int) -> str:
    return "\n".join(
        textwrap.wrap(
            text,
            width=width,
            break_long_words=True,
            break_on_hyphens=False,
            replace_whitespace=False,
        )
    )


def new_canvas() -> tuple[plt.Figure, plt.Axes]:
    fig = plt.figure(
        figsize=(WIDTH_PX / DPI, HEIGHT_PX / DPI),
        dpi=DPI,
        facecolor=PAPER,
    )
    canvas = fig.add_axes([0.0, 0.0, 1.0, 1.0])
    canvas.set_xlim(0.0, 1.0)
    canvas.set_ylim(0.0, 1.0)
    canvas.axis("off")
    return fig, canvas


def rounded_box(
    canvas: plt.Axes,
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    facecolor: str,
    edgecolor: str = GRID,
    linewidth: float = 1.2,
    radius: float = 0.018,
) -> None:
    canvas.add_patch(
        FancyBboxPatch(
            (x, y),
            width,
            height,
            boxstyle=f"round,pad=0.006,rounding_size={radius}",
            transform=canvas.transAxes,
            facecolor=facecolor,
            edgecolor=edgecolor,
            linewidth=linewidth,
        )
    )


def add_footer(fig: plt.Figure, canvas: plt.Axes, source_note: str) -> None:
    canvas.plot(
        [0.06, 0.94],
        [0.095, 0.095],
        color=GRID,
        linewidth=1.0,
        transform=canvas.transAxes,
        clip_on=False,
    )
    fig.text(
        0.06,
        0.052,
        wrap_zh(source_note, 74),
        ha="left",
        va="center",
        fontsize=9.7,
        color=FAINT,
        linespacing=1.25,
    )


def save_panel(fig: plt.Figure, filename: str) -> None:
    fig.savefig(
        os.path.join(OUT_DIR, filename),
        dpi=DPI,
        facecolor=PAPER,
        edgecolor="none",
        transparent=False,
    )
    plt.close(fig)


def render_concept(values: dict[str, float], source_note: str) -> None:
    fig, canvas = new_canvas()
    canvas.add_patch(
        Rectangle(
            (0.0, 0.78),
            1.0,
            0.22,
            transform=canvas.transAxes,
            facecolor=NAVY,
            edgecolor="none",
        )
    )
    fig.text(
        0.06,
        0.912,
        "口號很響，板塊卻沒動",
        ha="left",
        va="center",
        fontsize=30,
        fontweight="bold",
        color=PAPER,
    )
    fig.text(
        0.06,
        0.842,
        "AI 瓶頸轉向電力的故事，尚未出現在公用事業板塊的波動率。",
        ha="left",
        va="center",
        fontsize=16,
        color="#DCE6F0",
    )

    rounded_box(canvas, 0.06, 0.635, 0.37, 0.09, facecolor=PALE, edgecolor="#E4E9EF")
    rounded_box(canvas, 0.57, 0.635, 0.37, 0.09, facecolor=TEAL_SOFT, edgecolor="#CFE7E4")
    fig.text(0.085, 0.695, "市場共識", fontsize=11.5, color=MUTED, va="center")
    fig.text(
        0.085,
        0.660,
        "AI 瓶頸：晶片 → 電力",
        fontsize=16.5,
        fontweight="bold",
        color=INK,
        va="center",
    )
    fig.text(0.595, 0.695, "波動率訊號", fontsize=11.5, color=TEAL, va="center")
    fig.text(
        0.595,
        0.660,
        "板塊重定價尚未發生",
        fontsize=16.5,
        fontweight="bold",
        color=INK,
        va="center",
    )
    canvas.add_patch(
        FancyArrowPatch(
            (0.455, 0.68),
            (0.545, 0.68),
            transform=canvas.transAxes,
            arrowstyle="-|>",
            mutation_scale=18,
            linewidth=1.8,
            color=FAINT,
        )
    )

    fig.text(
        0.08,
        0.585,
        "目前年化已實現波動率 vs 過去一年中位",
        fontsize=15.5,
        fontweight="bold",
        color=INK,
        va="center",
    )
    chart = fig.add_axes([0.08, 0.175, 0.52, 0.37], facecolor="none")
    rows = [
        ("SMH｜目前", values["smh_current"], ORANGE),
        ("SMH｜一年中位", values["smh_median"], "#E8B89D"),
        ("XLU｜目前", values["xlu_current"], TEAL),
        ("XLU｜一年中位", values["xlu_median"], "#9ED0CC"),
    ]
    y_positions = [3.35, 2.55, 1.35, 0.55]
    max_value = max(value for _, value, _ in rows)
    chart.set_xlim(0.0, max_value * 1.28)
    chart.set_ylim(0.0, 3.9)
    for (label, value, color), y_pos in zip(rows, y_positions):
        chart.barh(y_pos, value, height=0.48, color=color, edgecolor="none")
        chart.text(
            value + max_value * 0.025,
            y_pos,
            fmt_pct(value),
            va="center",
            ha="left",
            fontsize=12.5,
            fontweight="bold",
            color=INK,
        )
    chart.axhline(1.95, color=GRID, linewidth=1.0)
    chart.set_yticks(
        y_positions,
        [label.replace("｜", "\n", 1) for label, _, _ in rows],
    )
    chart.tick_params(axis="y", labelsize=11.0, length=0, pad=7, colors=MUTED)
    chart.set_xticks([])
    for spine in chart.spines.values():
        spine.set_visible(False)

    rounded_box(canvas, 0.66, 0.175, 0.28, 0.39, facecolor=PALE, edgecolor="#E3E8EE")
    fig.text(
        0.695,
        0.515,
        "怎麼讀這張圖",
        fontsize=16,
        fontweight="bold",
        color=NAVY,
        va="center",
    )
    fig.text(
        0.695,
        0.465,
        "半導體\n目前波動明顯高於自身中位\n\n"
        "公用事業\n目前波動貼近自身中位\n\n"
        "結論\n真正沸騰的仍是晶片",
        fontsize=13.2,
        color=MUTED,
        va="top",
        linespacing=1.38,
    )

    add_footer(fig, canvas, source_note)
    save_panel(fig, "1_concept.png")


def render_method(values: dict[str, float], source_note: str) -> None:
    fig, canvas = new_canvas()
    fig.text(
        0.06,
        0.925,
        "板塊看不出的東西，去看橫斷面離散度",
        ha="left",
        va="center",
        fontsize=28,
        fontweight="bold",
        color=NAVY,
    )
    fig.text(
        0.06,
        0.862,
        "同一套公開收盤價，先估波動率，再分開檢查板塊與成分股訊號。",
        ha="left",
        va="center",
        fontsize=15.5,
        color=MUTED,
    )
    canvas.plot(
        [0.06, 0.94],
        [0.81, 0.81],
        transform=canvas.transAxes,
        color=TEAL,
        linewidth=3.0,
    )

    steps = [
        (0.06, "步驟一｜收盤價", "讀取 yfinance\n每日收盤資料"),
        (0.37, "步驟二｜計算報酬", "相鄰收盤價的\n對數變化"),
        (0.68, "步驟三｜估計波動", "滾動標準差\n再換算為年化"),
    ]
    for x_pos, heading, body in steps:
        rounded_box(canvas, x_pos, 0.655, 0.26, 0.105, facecolor=PALE, edgecolor="#DDE5EC")
        fig.text(
            x_pos + 0.02,
            0.727,
            heading,
            fontsize=13.3,
            fontweight="bold",
            color=TEAL,
            va="center",
        )
        fig.text(
            x_pos + 0.02,
            0.685,
            body,
            fontsize=11.5,
            color=MUTED,
            va="center",
            linespacing=1.22,
        )
    for start_x, end_x in ((0.325, 0.355), (0.635, 0.665)):
        canvas.add_patch(
            FancyArrowPatch(
                (start_x, 0.707),
                (end_x, 0.707),
                transform=canvas.transAxes,
                arrowstyle="-|>",
                mutation_scale=14,
                linewidth=1.5,
                color=FAINT,
            )
        )

    fig.text(
        0.08,
        0.575,
        "板塊有沒有重定價？",
        fontsize=15.5,
        fontweight="bold",
        color=INK,
        va="center",
    )
    left = fig.add_axes([0.08, 0.225, 0.38, 0.30], facecolor="none")
    left_rows = [
        ("XLU｜目前", values["xlu_current"], TEAL),
        ("XLU｜一年中位", values["xlu_median"], "#9ED0CC"),
    ]
    left_positions = [1.25, 0.45]
    left_max = max(value for _, value, _ in left_rows)
    left.set_xlim(0.0, left_max * 1.43)
    left.set_ylim(0.0, 1.75)
    for (label, value, color), y_pos in zip(left_rows, left_positions):
        left.barh(y_pos, value, height=0.46, color=color, edgecolor="none")
        left.text(
            value + left_max * 0.035,
            y_pos,
            fmt_pct(value),
            va="center",
            fontsize=13,
            fontweight="bold",
            color=INK,
        )
    left.set_yticks(
        left_positions,
        [label.replace("｜", "\n", 1) for label, _, _ in left_rows],
    )
    left.tick_params(axis="y", labelsize=11.0, length=0, pad=7, colors=MUTED)
    left.set_xticks([])
    for spine in left.spines.values():
        spine.set_visible(False)
    fig.text(
        0.08,
        0.165,
        "目前值貼近自身歷史中位，板塊層級沒有明顯跳升。",
        fontsize=11.7,
        color=MUTED,
        va="center",
    )

    fig.text(
        0.55,
        0.575,
        "電力籃子 vs SMH｜60 日滾動相關",
        fontsize=15.5,
        fontweight="bold",
        color=INK,
        va="center",
    )
    right = fig.add_axes([0.56, 0.225, 0.36, 0.30], facecolor="none")
    corr_values = [values["corr_current"], values["corr_3m"], values["corr_1y_median"]]
    x_positions = [0, 1, 2]
    baseline = 0.0
    right.vlines(x_positions, baseline, corr_values, color="#B8C7D5", linewidth=4)
    right.scatter(
        x_positions,
        corr_values,
        s=150,
        color=[TEAL, BLUE, NAVY],
        edgecolor=PAPER,
        linewidth=1.5,
        zorder=3,
    )
    for x_pos, value in zip(x_positions, corr_values):
        right.text(
            x_pos,
            value + 0.075,
            fmt_corr(value),
            ha="center",
            va="bottom",
            fontsize=13,
            fontweight="bold",
            color=INK,
        )
    right.set_xlim(-0.45, 2.45)
    right.set_ylim(0.0, max(corr_values) + 0.22)
    right.set_xticks(x_positions, ["目前", "三個月前", "一年中位"])
    right.tick_params(axis="x", labelsize=11.5, length=0, pad=8, colors=MUTED)
    right.set_yticks([])
    for spine in right.spines.values():
        spine.set_visible(False)
    fig.text(
        0.56,
        0.165,
        "三個觀測值幾乎相同，沒有形成同步升高的證據。",
        fontsize=11.7,
        color=MUTED,
        va="center",
    )

    add_footer(fig, canvas, source_note)
    save_panel(fig, "2_method.png")


def draw_bento_card(
    fig: plt.Figure,
    canvas: plt.Axes,
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    label: str,
    value: str,
    note: str,
    ticker: str,
    facecolor: str,
    accent: str,
) -> None:
    rounded_box(
        canvas,
        x,
        y,
        width,
        height,
        facecolor=facecolor,
        edgecolor=facecolor,
        radius=0.022,
    )
    fig.text(
        x + 0.028,
        y + height - 0.052,
        wrap_zh(label, 23),
        fontsize=13.5,
        fontweight="bold",
        color=MUTED,
        va="center",
        linespacing=1.15,
    )
    circle_x = x + width - 0.052
    circle_y = y + height - 0.055
    canvas.add_patch(
        Circle(
            (circle_x, circle_y),
            0.029,
            transform=canvas.transAxes,
            facecolor=PAPER,
            edgecolor=accent,
            linewidth=1.5,
        )
    )
    fig.text(
        circle_x,
        circle_y,
        ticker,
        fontsize=8.5,
        fontweight="bold",
        color=accent,
        ha="center",
        va="center",
    )
    fig.text(
        x + 0.028,
        y + 0.118,
        value,
        fontsize=35,
        fontweight="bold",
        color=accent,
        va="center",
    )
    fig.text(
        x + 0.028,
        y + 0.044,
        wrap_zh(note, 27),
        fontsize=11.8,
        color=INK,
        va="center",
        linespacing=1.22,
    )


def render_results(values: dict[str, float], source_note: str) -> None:
    fig, canvas = new_canvas()
    canvas.add_patch(
        Rectangle(
            (0.0, 0.81),
            1.0,
            0.19,
            transform=canvas.transAxes,
            facecolor=NAVY,
            edgecolor="none",
        )
    )
    fig.text(
        0.06,
        0.915,
        "同樣掛 AI 電力，命運天差地別",
        fontsize=29,
        fontweight="bold",
        color=PAPER,
        va="center",
    )
    fig.text(
        0.06,
        0.855,
        "板塊平均值遮住的，是設備商、核電商與晶片之間的巨大離散。",
        fontsize=15,
        color="#DCE6F0",
        va="center",
    )

    draw_bento_card(
        fig,
        canvas,
        x=0.06,
        y=0.465,
        width=0.42,
        height=0.285,
        label="GE Vernova｜今年以來報酬",
        value=fmt_signed_pct(values["gev_return"]),
        note="電力設備的「鏟子商」，被市場當成 AI 題材股。",
        ticker="GEV",
        facecolor=GREEN_SOFT,
        accent=GREEN,
    )
    draw_bento_card(
        fig,
        canvas,
        x=0.52,
        y=0.465,
        width=0.42,
        height=0.285,
        label="GE Vernova｜目前已實現波動率",
        value=fmt_pct(values["gev_current"]),
        note="目前波動率甚至高於半導體基準。",
        ticker="GEV",
        facecolor=BLUE_SOFT,
        accent=BLUE,
    )
    draw_bento_card(
        fig,
        canvas,
        x=0.06,
        y=0.145,
        width=0.42,
        height=0.265,
        label="Constellation｜今年以來報酬",
        value=fmt_signed_pct(values["ceg_return"]),
        note="實際供電的核電商，報酬走向相反。",
        ticker="CEG",
        facecolor=RED_SOFT,
        accent=RED,
    )
    draw_bento_card(
        fig,
        canvas,
        x=0.52,
        y=0.145,
        width=0.42,
        height=0.265,
        label="半導體 SMH｜目前已實現波動率",
        value=fmt_pct(values["smh_current"]),
        note="AI 交易的波動熱點仍在晶片。",
        ticker="SMH",
        facecolor=ORANGE_SOFT,
        accent=ORANGE,
    )

    add_footer(fig, canvas, source_note)
    save_panel(fig, "3_results.png")


def main() -> None:
    evidence, article = load_inputs()
    values = bind_values(evidence)
    source_note = source_note_from_article(article)
    os.makedirs(OUT_DIR, exist_ok=True)

    render_concept(values, source_note)
    render_method(values, source_note)
    render_results(values, source_note)


if __name__ == "__main__":
    main()
