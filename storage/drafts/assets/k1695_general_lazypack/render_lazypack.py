#!/usr/bin/env python3
"""Render the four data-bound K1695 general-reader lazypack panels.

The article evidence package supplies the strict-plan field names.  Every
displayed metric is also checked against the authoritative experiment results
before rendering; missing or drifting fields fail closed with a traceback.
"""
from __future__ import annotations

import json
import math
import os
import textwrap
from pathlib import Path
from typing import Any, Callable

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch, Rectangle


RESULTS_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1695/k1695_results.json"
)
README_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1695/README.md"
)
ARTICLE_EVIDENCE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/drafts/k1695_article_evidence.json"
)
ARTICLE_DRAFT_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/drafts/K1695_general_draft.md"
)
OUT_DIR = "/Users/yhlai0911/volpred-research/storage/drafts/assets/k1695_general_lazypack"

WIDTH_PX = 1600
HEIGHT_PX = 1000
DPI = 150
SOURCE_LABEL = "跨市場共同樣本與同風險口徑重算"

INK = "#152238"
NAVY = "#10233F"
BLUE = "#1D5D9B"
BLUE_SOFT = "#E9F1F8"
TEAL = "#157A78"
TEAL_SOFT = "#E3F2F0"
RED = "#B93B42"
RED_SOFT = "#F8E8E9"
AMBER = "#B56A16"
AMBER_SOFT = "#FAF0DF"
MUTED = "#5D6978"
FAINT = "#D8E0E8"
PAPER = "#F5F7FA"
WHITE = "#FFFFFF"

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["figure.facecolor"] = WHITE
plt.rcParams["savefig.facecolor"] = WHITE


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_nonempty_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError(f"Evidence file is empty: {path}")
    return text


def resolve_path(data: Any, dotted_path: str) -> Any:
    current = data
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise KeyError(f"Missing required evidence field: {dotted_path}")
        current = current[part]
    return current


def numeric(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"Expected numeric evidence at {path}, got {type(value).__name__}")
    if not math.isfinite(float(value)):
        raise ValueError(f"Non-finite evidence at {path}: {value!r}")
    return float(value)


def identity(value: float) -> float:
    return value


def vol_cut_from_ratio(value: float) -> float:
    return (1.0 - value) * 100.0


# strict-plan article path -> (authoritative results path, transform)
AUTHORITATIVE_BINDINGS: dict[str, tuple[str, Callable[[float], float]]] = {
    "common_sample.n_markets": (
        "samples.common_period.summary.n_markets",
        identity,
    ),
    "common_sample.n_obs": ("samples.common_period.n_obs", identity),
    "exposure_matched.mean_vol_cut_pct": (
        "samples.common_period.summary.average_vol_ratio",
        vol_cut_from_ratio,
    ),
    "exposure_matched.n_markets_vol_mismatch_flagged": (
        "samples.common_period.summary.n_exposure_mismatch",
        identity,
    ),
    "exposure_matched.avg_raw_mdd_gap_pp": (
        "samples.common_period.summary.average_delta_mdd_pp",
        identity,
    ),
    "exposure_matched.avg_exposure_matched_gap_pp": (
        "samples.common_period.summary.average_exposure_matched_delta_mdd_pp",
        identity,
    ),
    "exposure_matched.n_markets_matched_gap_positive": (
        "samples.common_period.summary.n_exposure_matched_improved",
        identity,
    ),
    "published_k1695.n_sharpe_improved_common": (
        "samples.common_period.summary.n_sharpe_improved",
        identity,
    ),
    "published_k1695.avg_annual_return_cost_pp_common": (
        "samples.common_period.summary.average_annual_return_cost_pp",
        identity,
    ),
    "published_k1695.vix_r_common": (
        "samples.common_period.summary.vix_sensitivity_vs_delta_mdd.pearson_r",
        identity,
    ),
}


def bind_metrics(article_evidence: dict[str, Any], results: dict[str, Any]) -> dict[str, float]:
    bound: dict[str, float] = {}
    for article_path, (results_path, transform) in AUTHORITATIVE_BINDINGS.items():
        derived_value = numeric(resolve_path(article_evidence, article_path), article_path)
        results_value = numeric(resolve_path(results, results_path), results_path)
        authoritative_value = transform(results_value)
        if not math.isclose(
            derived_value,
            authoritative_value,
            rel_tol=1e-12,
            abs_tol=1e-9,
        ):
            raise ValueError(
                "Evidence drift for "
                f"{article_path}: article={derived_value!r}, "
                f"results={authoritative_value!r} ({results_path})"
            )
        bound[article_path] = authoritative_value
    return bound


def format_metric(
    value: float,
    *,
    kind: str,
    digits: int | None = None,
    suffix: str = "",
    show_plus: bool = False,
) -> str:
    if kind == "integer":
        if not value.is_integer():
            raise ValueError(f"Expected integer-valued evidence, got {value!r}")
        rendered = f"{int(value):,}"
    elif kind == "number":
        if digits is None:
            raise ValueError("digits is required for number formatting")
        sign = "+" if show_plus else ""
        rendered = f"{value:{sign}.{digits}f}"
    else:
        raise ValueError(f"Unsupported metric format: {kind}")
    return rendered + suffix


def wrap_text(text: str, width: int) -> str:
    return "\n".join(
        textwrap.wrap(
            text,
            width=width,
            break_long_words=True,
            break_on_hyphens=False,
            replace_whitespace=False,
        )
    )


def new_figure(background: str = WHITE) -> tuple[Figure, Axes]:
    fig = plt.figure(figsize=(WIDTH_PX / DPI, HEIGHT_PX / DPI), dpi=DPI)
    fig.patch.set_facecolor(background)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.set_facecolor(background)
    return fig, ax


def rounded_card(
    ax: Axes,
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    facecolor: str = WHITE,
    edgecolor: str = FAINT,
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


def panel_header(
    ax: Axes,
    title: str,
    alt: str,
    *,
    dark: bool = False,
) -> None:
    title_color = WHITE if dark else INK
    subtitle_color = "#D5DFEA" if dark else MUTED
    ax.text(
        0.06,
        0.915,
        title,
        fontsize=31,
        fontweight="bold",
        color=title_color,
        ha="left",
        va="top",
        transform=ax.transAxes,
    )
    ax.text(
        0.06,
        0.842,
        alt,
        fontsize=16,
        color=subtitle_color,
        ha="left",
        va="top",
        transform=ax.transAxes,
    )


def footer(ax: Axes, *, dark: bool = False) -> None:
    color = "#CAD5E0" if dark else MUTED
    line = "#42556D" if dark else FAINT
    ax.plot([0.06, 0.94], [0.075, 0.075], color=line, linewidth=0.8, transform=ax.transAxes)
    ax.text(
        0.06,
        0.045,
        f"資料來源：{SOURCE_LABEL}",
        fontsize=11.5,
        color=color,
        ha="left",
        va="center",
        transform=ax.transAxes,
    )


def text_block(
    ax: Axes,
    x: float,
    y: float,
    heading: str,
    body: str,
    *,
    width_chars: int,
    heading_color: str = BLUE,
    body_color: str = INK,
    heading_size: float = 17,
    body_size: float = 16,
    line_spacing: float = 1.55,
) -> None:
    ax.text(
        x,
        y,
        heading,
        fontsize=heading_size,
        fontweight="bold",
        color=heading_color,
        ha="left",
        va="top",
        transform=ax.transAxes,
    )
    ax.text(
        x,
        y - 0.065,
        wrap_text(body, width_chars),
        fontsize=body_size,
        color=body_color,
        linespacing=line_spacing,
        ha="left",
        va="top",
        transform=ax.transAxes,
    )


def metric_card(
    ax: Axes,
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    label: str,
    value: str,
    note: str | None = None,
    accent: str = BLUE,
    facecolor: str = WHITE,
    value_size: float = 32,
    label_size: float = 14,
    label_wrap_chars: int = 22,
    label_top_padding: float = 0.042,
    value_bottom_padding: float | None = None,
    note_bottom_padding: float = 0.032,
) -> None:
    if value_bottom_padding is None:
        value_bottom_padding = 0.077 if note else 0.052
    rounded_card(ax, x, y, width, height, facecolor=facecolor, edgecolor="none")
    ax.add_patch(
        Rectangle(
            (x, y),
            0.009,
            height,
            transform=ax.transAxes,
            facecolor=accent,
            edgecolor="none",
        )
    )
    ax.text(
        x + 0.028,
        y + height - label_top_padding,
        wrap_text(label, label_wrap_chars),
        fontsize=label_size,
        color=MUTED,
        ha="left",
        va="top",
        transform=ax.transAxes,
    )
    ax.text(
        x + 0.028,
        y + value_bottom_padding,
        value,
        fontsize=value_size,
        fontweight="bold",
        color=accent,
        ha="left",
        va="bottom",
        transform=ax.transAxes,
    )
    if note:
        ax.text(
            x + 0.028,
            y + note_bottom_padding,
            wrap_text(note, 24),
            fontsize=12.5,
            color=MUTED,
            ha="left",
            va="bottom",
            transform=ax.transAxes,
        )


def save_panel(fig: Figure, filename: str, title: str, alt: str) -> None:
    target = Path(OUT_DIR) / filename
    fig.savefig(
        target,
        dpi=DPI,
        facecolor=fig.get_facecolor(),
        edgecolor="none",
        metadata={"Title": title, "Description": alt},
    )
    plt.close(fig)


def render_concept(values: dict[str, float]) -> None:
    title = "策略在做什麼，以及一個容易被跳過的問題"
    alt = "波動率目標策略的規則，與回撤比較的前提"
    fig, ax = new_figure(WHITE)
    ax.add_patch(Rectangle((0, 0.76), 1, 0.24, transform=ax.transAxes, color=NAVY))
    panel_header(ax, title, alt, dark=True)

    rounded_card(ax, 0.06, 0.385, 0.415, 0.295, facecolor=PAPER, edgecolor="none")
    rounded_card(ax, 0.525, 0.385, 0.415, 0.295, facecolor=AMBER_SOFT, edgecolor="none")
    text_block(
        ax,
        0.09,
        0.635,
        "規則",
        "月底看一次恐慌指數 VIX，指數越高，下個月股票部位放越少，其餘擺短債。整個月不動，下月初再調。",
        width_chars=18,
        heading_color=BLUE,
        body_size=16,
    )
    text_block(
        ax,
        0.555,
        0.635,
        "要先問的問題",
        "回撤變淺，可能是因為會挑時機，也可能只是因為部位放得少。兩者長得一樣，必須拆開來看。",
        width_chars=18,
        heading_color=AMBER,
        body_size=16,
    )

    # A restrained rule-to-question flow icon; no additional statistics.
    ax.add_patch(Circle((0.44, 0.705), 0.017, transform=ax.transAxes, color=BLUE))
    ax.add_patch(Circle((0.56, 0.705), 0.017, transform=ax.transAxes, color=AMBER))
    ax.add_patch(
        FancyArrowPatch(
            (0.462, 0.705),
            (0.538, 0.705),
            arrowstyle="-|>",
            mutation_scale=16,
            linewidth=1.5,
            color="#B6C1CD",
            transform=ax.transAxes,
        )
    )

    metric_card(
        ax,
        0.06,
        0.145,
        0.415,
        0.16,
        label="回測市場數",
        value=format_metric(values["common_sample.n_markets"], kind="integer", suffix=" 個"),
        accent=TEAL,
        facecolor=TEAL_SOFT,
        value_size=31,
        label_top_padding=0.020,
        value_bottom_padding=0.018,
    )
    metric_card(
        ax,
        0.525,
        0.145,
        0.415,
        0.16,
        label="共同樣本交易日",
        value=format_metric(values["common_sample.n_obs"], kind="integer", suffix=" 日"),
        accent=BLUE,
        facecolor=BLUE_SOFT,
        value_size=31,
        label_top_padding=0.020,
        value_bottom_padding=0.018,
    )
    footer(ax)
    save_panel(fig, "1_concept.png", title, alt)


def render_method(values: dict[str, float]) -> None:
    title = "重做版把口徑修回誠實"
    alt = "重做版的方法與資料口徑"
    fig, ax = new_figure(PAPER)
    panel_header(ax, title, alt)

    rounded_card(ax, 0.06, 0.395, 0.575, 0.355, facecolor=WHITE, edgecolor=FAINT)
    text_block(
        ax,
        0.09,
        0.705,
        "修了什麼",
        "資料釘死成快照不再連網重抓；訊號用上月底 VIX、落後一期；現金部位改買短債並計入實際報酬；每次調倉按實際換手扣交易成本；重抽樣時所有市場同步抽同一組日期，保留一起崩盤的相依性。",
        width_chars=26,
        heading_color=BLUE,
        body_size=15,
        line_spacing=1.48,
    )

    rounded_card(ax, 0.06, 0.145, 0.575, 0.18, facecolor=NAVY, edgecolor="none")
    text_block(
        ax,
        0.09,
        0.285,
        "關鍵檢查",
        "策略的實際波動遠低於買進持有，代表兩者曝險不同，帳面回撤不能直接對比。",
        width_chars=26,
        heading_color="#8EC4F1",
        body_color=WHITE,
        body_size=15,
        line_spacing=1.45,
    )

    metric_card(
        ax,
        0.68,
        0.49,
        0.26,
        0.26,
        label="策略平均壓低的波動",
        value=format_metric(
            values["exposure_matched.mean_vol_cut_pct"],
            kind="number",
            digits=0,
            suffix="%",
        ),
        accent=TEAL,
        facecolor=WHITE,
        value_size=38,
    )
    bar_x, bar_y, bar_w = 0.708, 0.525, 0.195
    ax.add_patch(
        FancyBboxPatch(
            (bar_x, bar_y),
            bar_w,
            0.018,
            boxstyle="round,pad=0,rounding_size=0.009",
            transform=ax.transAxes,
            facecolor="#D9E3E8",
            edgecolor="none",
        )
    )
    ax.add_patch(
        FancyBboxPatch(
            (bar_x, bar_y),
            bar_w * values["exposure_matched.mean_vol_cut_pct"] / 100.0,
            0.018,
            boxstyle="round,pad=0,rounding_size=0.009",
            transform=ax.transAxes,
            facecolor=TEAL,
            edgecolor="none",
        )
    )

    metric_card(
        ax,
        0.68,
        0.145,
        0.26,
        0.26,
        label="曝險不匹配的市場",
        value=format_metric(
            values["exposure_matched.n_markets_vol_mismatch_flagged"],
            kind="integer",
            suffix=" 個（全部）",
        ),
        accent=RED,
        facecolor=RED_SOFT,
        value_size=26,
    )
    footer(ax)
    save_panel(fig, "2_method.png", title, alt)


def render_results(values: dict[str, float]) -> None:
    title = "把「少冒險」扣掉，抗跌效果就站不穩"
    alt = "原始回撤改善與同風險口徑下的回撤改善對照"
    fig, ax = new_figure(PAPER)
    panel_header(ax, title, alt)

    metric_card(
        ax,
        0.06,
        0.505,
        0.42,
        0.27,
        label="帳面平均回撤改善",
        value=format_metric(
            values["exposure_matched.avg_raw_mdd_gap_pp"],
            kind="number",
            digits=2,
            show_plus=True,
            suffix=" 個百分點",
        ),
        note="看起來很漂亮",
        accent=TEAL,
        facecolor=TEAL_SOFT,
        value_size=29,
    )
    metric_card(
        ax,
        0.52,
        0.505,
        0.42,
        0.27,
        label="同風險口徑平均回撤改善",
        value=format_metric(
            values["exposure_matched.avg_exposure_matched_gap_pp"],
            kind="number",
            digits=2,
            show_plus=True,
            suffix=" 個百分點",
        ),
        note="把買進持有縮到同樣風險後再比",
        accent=RED,
        facecolor=RED_SOFT,
        value_size=29,
    )

    # Direct visual comparison, scaled only from the two displayed evidence values.
    raw = values["exposure_matched.avg_raw_mdd_gap_pp"]
    matched = values["exposure_matched.avg_exposure_matched_gap_pp"]
    max_abs = max(abs(raw), abs(matched))
    center_x = 0.50
    ax.plot([center_x, center_x], [0.455, 0.485], color="#9DA9B7", linewidth=1.2)
    ax.plot(
        [center_x, center_x + 0.34 * raw / max_abs],
        [0.472, 0.472],
        color=TEAL,
        linewidth=8,
        solid_capstyle="round",
    )
    ax.plot(
        [center_x, center_x + 0.34 * matched / max_abs],
        [0.455, 0.455],
        color=RED,
        linewidth=8,
        solid_capstyle="round",
    )

    metric_card(
        ax,
        0.06,
        0.145,
        0.34,
        0.245,
        label="同風險口徑下仍為正的市場",
        value=format_metric(
            values["exposure_matched.n_markets_matched_gap_positive"],
            kind="integer",
            suffix=" 個市場",
        ),
        note="接近擲硬幣",
        accent=AMBER,
        facecolor=AMBER_SOFT,
        value_size=31,
    )
    rounded_card(ax, 0.44, 0.145, 0.50, 0.245, facecolor=NAVY, edgecolor="none")
    text_block(
        ax,
        0.475,
        0.345,
        "讀法",
        "帳面上的抗跌，主要成分是槓桿，不是擇時。任何人把持股等比例縮小都能複製同樣的改善。",
        width_chars=24,
        heading_color="#8EC4F1",
        body_color=WHITE,
        body_size=14.5,
        line_spacing=1.45,
    )
    footer(ax)
    save_panel(fig, "3_results.png", title, alt)


def render_takeaway(values: dict[str, float]) -> None:
    title = "代價是真的，機制沒有站穩"
    alt = "策略付出的報酬代價與站不住的機制解釋"
    fig, ax = new_figure(WHITE)
    panel_header(ax, title, alt)

    rounded_card(ax, 0.06, 0.35, 0.49, 0.42, facecolor=NAVY, edgecolor="none")
    ax.text(
        0.095,
        0.715,
        "每年的報酬代價",
        fontsize=17,
        color="#BFD0E1",
        ha="left",
        va="top",
        transform=ax.transAxes,
    )
    ax.text(
        0.095,
        0.585,
        format_metric(
            values["published_k1695.avg_annual_return_cost_pp_common"],
            kind="number",
            digits=2,
            suffix=" 個百分點／年",
        ),
        fontsize=36,
        fontweight="bold",
        color=WHITE,
        ha="left",
        va="center",
        transform=ax.transAxes,
    )
    ax.text(
        0.095,
        0.435,
        "回撤變淺並不是免費午餐；\n長期複利會把這個差距放大。",
        fontsize=16,
        color="#D9E3EC",
        linespacing=1.5,
        ha="left",
        va="top",
        transform=ax.transAxes,
    )

    metric_card(
        ax,
        0.59,
        0.545,
        0.35,
        0.225,
        label="風險報酬比變好的市場",
        value=format_metric(
            values["published_k1695.n_sharpe_improved_common"],
            kind="integer",
            suffix=" 個市場",
        ),
        note="一個都沒有",
        accent=RED,
        facecolor=RED_SOFT,
        value_size=32,
    )
    metric_card(
        ax,
        0.59,
        0.35,
        0.35,
        0.18,
        label="VIX 敏感度與保護幅度的關聯（共同期間）",
        value=format_metric(
            values["published_k1695.vix_r_common"],
            kind="number",
            digits=2,
            show_plus=True,
        ),
        note="換樣本就翻面，統計上不成立",
        accent=AMBER,
        facecolor=AMBER_SOFT,
        value_size=23,
        label_size=12,
        label_wrap_chars=34,
        label_top_padding=0.018,
        value_bottom_padding=0.065,
        note_bottom_padding=0.028,
    )

    rounded_card(ax, 0.06, 0.125, 0.88, 0.155, facecolor=PAPER, edgecolor=FAINT)
    text_block(
        ax,
        0.09,
        0.245,
        "帶走這句",
        "下次看到策略宣稱大幅降低回撤，先問它平均放了幾成部位。真正該比的，是把對照組也縮到同樣風險水位之後，它還剩多少優勢。",
        width_chars=48,
        heading_color=BLUE,
        body_size=12.5,
        line_spacing=1.35,
    )
    footer(ax)
    save_panel(fig, "4_takeaway.png", title, alt)


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)

    results = load_json(RESULTS_PATH)
    article_evidence = load_json(ARTICLE_EVIDENCE_PATH)
    # These are part of the supplied evidence package.  Loading them here makes
    # absence/emptiness fail closed even though displayed statistics come only
    # from the two machine-readable JSON files above.
    load_nonempty_text(README_PATH)
    load_nonempty_text(ARTICLE_DRAFT_PATH)

    if not isinstance(results, dict) or not isinstance(article_evidence, dict):
        raise TypeError("Both JSON evidence roots must be objects")
    values = bind_metrics(article_evidence, results)

    render_concept(values)
    render_method(values)
    render_results(values)
    render_takeaway(values)


if __name__ == "__main__":
    main()
