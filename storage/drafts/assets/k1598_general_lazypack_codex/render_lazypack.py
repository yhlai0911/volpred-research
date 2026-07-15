#!/usr/bin/env python3
"""Render three data-bound PNG panels for the general-reader interval article.

All displayed statistics are loaded from the K1598 results JSON at runtime.
Missing paths or non-numeric metric values deliberately raise an exception.
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
from matplotlib.patches import Circle, FancyBboxPatch, Rectangle


RESULTS_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1598/k1598_results.json"
)
README_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1598/README.md"
)
OUT_DIR = (
    "/Users/yhlai0911/volpred-research/"
    "storage/drafts/assets/k1598_general_lazypack_codex"
)
SOURCE_LABEL = "K1598 independently reviewed online interval results"

WIDTH = 1600
HEIGHT = 1000
DPI = 150

NAVY = "#12233F"
NAVY_2 = "#1E365D"
BLUE = "#2368A2"
BLUE_SOFT = "#E8F1F8"
TEAL = "#147D78"
TEAL_SOFT = "#E2F2F0"
GREEN = "#287A57"
GREEN_SOFT = "#E7F2EC"
AMBER = "#B06B16"
AMBER_SOFT = "#F8EDDD"
RED = "#A84742"
RED_SOFT = "#F7E7E5"
INK = "#152033"
MUTED = "#5C687A"
LINE = "#D8DFE8"
PAPER = "#FFFFFF"
OFF_WHITE = "#F7F9FC"

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False


def load_evidence() -> dict[str, Any]:
    """Load both evidence files and fail loudly if either is unavailable."""
    with RESULTS_PATH.open("r", encoding="utf-8") as handle:
        result = json.load(handle)
    with README_PATH.open("r", encoding="utf-8") as handle:
        readme = handle.read()
    if not isinstance(result, dict):
        raise TypeError(f"Expected a JSON object in {RESULTS_PATH}")
    if not readme.strip():
        raise ValueError(f"Evidence README is empty: {README_PATH}")
    return result


def resolve(data: Any, path: str) -> Any:
    """Resolve either a JSON Pointer (/a/b/0) or dotted path (a.b.0)."""
    if not path:
        raise ValueError("Evidence path must not be empty")
    if path.startswith("/"):
        parts = [p.replace("~1", "/").replace("~0", "~") for p in path[1:].split("/")]
    else:
        parts = path.split(".")

    current = data
    for part in parts:
        if isinstance(current, dict):
            if part not in current:
                raise KeyError(f"Missing evidence field: {path}")
            current = current[part]
        elif isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError) as exc:
                raise KeyError(f"Missing evidence field: {path}") from exc
        else:
            raise KeyError(f"Cannot traverse evidence field: {path}")
    return current


def number(data: dict[str, Any], path: str) -> float:
    value = resolve(data, path)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"Expected numeric evidence at {path}; got {type(value).__name__}")
    return float(value)


def integer(data: dict[str, Any], path: str, suffix: str = "") -> str:
    value = number(data, path)
    if not value.is_integer():
        raise ValueError(f"Expected integer-valued evidence at {path}; got {value}")
    return f"{int(value):,}{suffix}"


def percent(data: dict[str, Any], path: str, digits: int) -> str:
    return f"{number(data, path) * 100:.{digits}f}%"


def decimal(
    data: dict[str, Any], path: str, digits: int, show_plus: bool = False
) -> str:
    value = number(data, path)
    spec = f"+.{digits}f" if show_plus else f".{digits}f"
    return format(value, spec)


def new_figure():
    fig = plt.figure(figsize=(WIDTH / DPI, HEIGHT / DPI), dpi=DPI, facecolor=PAPER)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    return fig, ax


def add_header(ax, title: str, alt: str, accent: str = TEAL) -> None:
    ax.add_patch(Rectangle((0, 0.795), 1, 0.205, facecolor=NAVY, edgecolor="none"))
    ax.add_patch(Rectangle((0.055, 0.92), 0.045, 0.007, facecolor=accent, edgecolor="none"))
    ax.text(
        0.055,
        0.875,
        title,
        fontsize=26,
        fontweight="bold",
        color="white",
        ha="left",
        va="center",
    )
    ax.text(
        0.055,
        0.825,
        alt,
        fontsize=11.5,
        color="#DDE7F3",
        ha="left",
        va="center",
    )


def add_footer(ax) -> None:
    ax.plot([0.055, 0.945], [0.052, 0.052], color=LINE, linewidth=1)
    ax.text(
        0.055,
        0.027,
        f"資料來源：{SOURCE_LABEL}",
        fontsize=8.5,
        color=MUTED,
        ha="left",
        va="center",
    )


def rounded_box(ax, x: float, y: float, w: float, h: float, face: str, edge: str = "none") -> None:
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle="round,pad=0.008,rounding_size=0.016",
            linewidth=1.1 if edge != "none" else 0,
            facecolor=face,
            edgecolor=edge,
        )
    )


def wrapped(text: str, width: int) -> str:
    return "\n".join(textwrap.wrap(text, width=width, break_long_words=False))


def metric_card(
    ax,
    x: float,
    y: float,
    w: float,
    h: float,
    label: str,
    value: str,
    *,
    note: str | None = None,
    face: str = OFF_WHITE,
    accent: str = BLUE,
    value_size: float = 27,
) -> None:
    rounded_box(ax, x, y, w, h, face, LINE)
    ax.add_patch(Rectangle((x, y), 0.007, h, facecolor=accent, edgecolor="none"))
    ax.text(
        x + 0.024,
        y + h - 0.035,
        wrapped(label, 18),
        fontsize=10.5,
        color=MUTED,
        ha="left",
        va="top",
        linespacing=1.2,
    )
    ax.text(
        x + 0.024,
        y + (0.052 if note else 0.035),
        value,
        fontsize=value_size,
        fontweight="bold",
        color=accent,
        ha="left",
        va="bottom",
    )
    if note:
        ax.text(
            x + 0.024,
            y + 0.020,
            wrapped(note, 21),
            fontsize=8.5,
            color=MUTED,
            ha="left",
            va="bottom",
            linespacing=1.2,
        )


def save_panel(fig, filename: str, alt: str) -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    fig.savefig(
        os.path.join(OUT_DIR, filename),
        dpi=DPI,
        facecolor=PAPER,
        edgecolor="none",
        metadata={"Title": filename, "Description": alt, "Source": SOURCE_LABEL},
    )
    plt.close(fig)


def render_daily_update(data: dict[str, Any]) -> None:
    title = "每天先交答案，再用結果調整明天"
    alt = "線上風險區間只使用當日前可見資料並在收盤後更新"
    fig, ax = new_figure()
    add_header(ax, title, alt, TEAL)

    # Two-step online timeline. Text lives in fixed, non-overlapping columns.
    step_y, step_h = 0.505, 0.225
    rounded_box(ax, 0.055, step_y, 0.405, step_h, BLUE_SOFT, LINE)
    rounded_box(ax, 0.540, step_y, 0.405, step_h, TEAL_SOFT, LINE)
    ax.add_patch(Circle((0.100, 0.678), 0.026, facecolor=BLUE, edgecolor="none"))
    ax.add_patch(Circle((0.585, 0.678), 0.026, facecolor=TEAL, edgecolor="none"))
    ax.text(0.100, 0.678, "1", fontsize=14, fontweight="bold", color="white", ha="center", va="center")
    ax.text(0.585, 0.678, "2", fontsize=14, fontweight="bold", color="white", ha="center", va="center")
    ax.text(0.140, 0.680, "先畫範圍", fontsize=18, fontweight="bold", color=INK, ha="left", va="center")
    ax.text(0.625, 0.680, "再看有沒有漏", fontsize=18, fontweight="bold", color=INK, ha="left", va="center")
    ax.text(
        0.085,
        0.605,
        wrapped("用前一天以前的波動與歷史誤差，先決定今天報酬的上下界。", 22),
        fontsize=12.5,
        color=INK,
        ha="left",
        va="top",
        linespacing=1.55,
    )
    ax.text(
        0.570,
        0.605,
        wrapped("當天結束後才知道報酬是否超出範圍，結果只拿來更新下一天。", 22),
        fontsize=12.5,
        color=INK,
        ha="left",
        va="top",
        linespacing=1.55,
    )
    ax.annotate(
        "",
        xy=(0.525, 0.615),
        xytext=(0.475, 0.615),
        arrowprops={"arrowstyle": "-|>", "color": NAVY_2, "lw": 2.2},
    )

    card_y, card_h, card_w = 0.145, 0.275, 0.280
    metric_card(
        ax,
        0.055,
        card_y,
        card_w,
        card_h,
        "每檔樣本外預測",
        integer(data, "dataset.sample_by_asset.SPY.n_oos_candidate", " 天"),
        face=OFF_WHITE,
        accent=NAVY_2,
        value_size=25,
    )
    metric_card(
        ax,
        0.360,
        card_y,
        card_w,
        card_h,
        "較寬目標的容許漏網率",
        percent(data, "/primary_test/coverage_levels/0", 0),
        face=AMBER_SOFT,
        accent=AMBER,
    )
    metric_card(
        ax,
        0.665,
        card_y,
        card_w,
        card_h,
        "較保守目標的容許漏網率",
        percent(data, "/primary_test/coverage_levels/1", 0),
        face=GREEN_SOFT,
        accent=GREEN,
    )
    add_footer(ax)
    save_panel(fig, "1_daily_update.png", alt)


def render_two_scores(data: dict[str, Any]) -> None:
    title = "覆蓋追蹤變好，整體損失沒有領先"
    alt = "UP lite 與滾動門檻及自適應方法的漏網率差距與區間損失比較"
    fig, ax = new_figure()
    add_header(ax, title, alt, BLUE)

    # Coverage-tracking row: three like-for-like mean absolute miss gaps.
    ax.text(0.055, 0.755, "第一科｜漏網率貼近目標嗎？", fontsize=14, fontweight="bold", color=INK, ha="left", va="center")
    top_y, top_h, top_w = 0.485, 0.225, 0.280
    metric_card(
        ax, 0.055, top_y, top_w, top_h,
        "滾動門檻平均偏差",
        percent(data, "summary.method_summary.Rolling252.mean_abs_miss_gap", 2),
        face=RED_SOFT, accent=RED,
    )
    metric_card(
        ax, 0.360, top_y, top_w, top_h,
        "UP-lite 平均偏差",
        percent(data, "summary.method_summary.UP_AggACI_lite.mean_abs_miss_gap", 2),
        note="更貼近目標漏網率", face=TEAL_SOFT, accent=TEAL,
    )
    metric_card(
        ax, 0.665, top_y, top_w, top_h,
        "單一自適應法平均偏差",
        percent(data, "summary.method_summary.ACI_eta_0p01.mean_abs_miss_gap", 2),
        note="仍低於 UP-lite", face=GREEN_SOFT, accent=GREEN,
    )

    # Loss row plus a distinct interpretation block.
    ax.text(0.055, 0.440, "第二科｜整體區間品質好嗎？", fontsize=14, fontweight="bold", color=INK, ha="left", va="center")
    bottom_y, bottom_h = 0.125, 0.270
    metric_card(
        ax, 0.055, bottom_y, 0.245, bottom_h,
        "UP-lite 區間損失",
        decimal(data, "summary.method_summary.UP_AggACI_lite.mean_pinball_loss", 3),
        face=BLUE_SOFT, accent=BLUE,
    )
    metric_card(
        ax, 0.325, bottom_y, 0.245, bottom_h,
        "固定門檻區間損失",
        decimal(data, "summary.method_summary.FixedIS.mean_pinball_loss", 3),
        note="數值略低；較低較好", face=AMBER_SOFT, accent=AMBER,
    )
    rounded_box(ax, 0.595, bottom_y, 0.350, bottom_h, NAVY, NAVY)
    ax.text(0.625, 0.345, "判讀", fontsize=14, fontweight="bold", color="#9ED8D3", ha="left", va="center")
    ax.text(
        0.625,
        0.305,
        wrapped("UP-lite 修正了滾動門檻容易漏太多的問題，仍沒有在整體區間品質上超過較強基準。", 22),
        fontsize=12.5,
        color="white",
        ha="left",
        va="top",
        linespacing=1.45,
    )
    add_footer(ax)
    save_panel(fig, "2_two_scores.png", alt)


def render_honest_boundary(data: dict[str, Any]) -> None:
    title = "局部勝出，還不能接管整套風控"
    alt = "材料類股在較寬目標下的單一嚴格勝出與研究適用邊界"
    fig, ax = new_figure()
    add_header(ax, title, alt, AMBER)

    # Editorial hero: one cell-level result, with the adjusted threshold beside it.
    rounded_box(ax, 0.055, 0.355, 0.405, 0.385, NAVY, NAVY)
    ax.text(0.085, 0.690, "材料類股｜較寬目標", fontsize=12, color="#C8D8EA", ha="left", va="center")
    ax.text(0.085, 0.635, "比較強度", fontsize=14, fontweight="bold", color="white", ha="left", va="center")
    ax.text(
        0.085,
        0.515,
        decimal(
            data,
            "/summary/dm_tests_up_vs_baselines/XLB_a0.10_UP_AggACI_lite_vs_Rolling252/t_stat",
            2,
            show_plus=True,
        ),
        fontsize=48,
        fontweight="bold",
        color="#83D1C8",
        ha="left",
        va="center",
    )
    ax.text(0.085, 0.430, "負值代表 UP-lite 區間損失較低", fontsize=10.5, color="#DDE7F3", ha="left", va="center")

    metric_card(
        ax, 0.490, 0.560, 0.215, 0.180,
        "多重比較後門檻值",
        percent(
            data,
            "/summary/dm_tests_up_vs_baselines/XLB_a0.10_UP_AggACI_lite_vs_Rolling252/holm_p_value",
            2,
        ),
        face=AMBER_SOFT, accent=AMBER, value_size=25,
    )
    metric_card(
        ax, 0.730, 0.560, 0.215, 0.180,
        "UP-lite 平均半寬",
        percent(data, "summary.method_summary.UP_AggACI_lite.mean_radius", 2),
        face=BLUE_SOFT, accent=BLUE, value_size=25,
    )

    # Two annotation columns make the evidence boundary explicit.
    rounded_box(ax, 0.490, 0.355, 0.215, 0.170, GREEN_SOFT, LINE)
    ax.text(0.515, 0.492, "可以支持", fontsize=13, fontweight="bold", color=GREEN, ha="left", va="center")
    ax.text(
        0.515,
        0.458,
        "• " + wrapped("用多種更新速度混合，能改善老舊滾動門檻的覆蓋追蹤。", 15).replace("\n", "\n  "),
        fontsize=9.5,
        color=INK,
        ha="left",
        va="top",
        linespacing=1.3,
    )
    ax.text(0.515, 0.377, "• 本次沒有任何嚴格失利。", fontsize=9.5, color=INK, ha="left", va="bottom")

    rounded_box(ax, 0.730, 0.355, 0.215, 0.170, RED_SOFT, LINE)
    ax.text(0.755, 0.492, "仍不能支持", fontsize=13, fontweight="bold", color=RED, ha="left", va="center")
    ax.text(
        0.755,
        0.458,
        "• " + wrapped("本次只是近似版混合，不是原論文的完整演算法。", 15).replace("\n", "\n  "),
        fontsize=9.5,
        color=INK,
        ha="left",
        va="top",
        linespacing=1.3,
    )
    ax.text(
        0.755,
        0.393,
        "• " + wrapped("區間左右對稱，尚未檢驗單邊最大損失或實際交易成績。", 15).replace("\n", "\n  "),
        fontsize=9.5,
        color=INK,
        ha="left",
        va="top",
        linespacing=1.3,
    )

    ax.text(
        0.055,
        0.270,
        "研究邊界",
        fontsize=12,
        fontweight="bold",
        color=AMBER,
        ha="left",
        va="center",
    )
    ax.text(
        0.055,
        0.215,
        "這是一個特定資產、特定目標下的嚴格勝出；它是線索，不是全面換手的證明。",
        fontsize=16,
        fontweight="bold",
        color=INK,
        ha="left",
        va="center",
    )
    ax.text(
        0.055,
        0.165,
        "先把覆蓋追蹤與區間損失分開評分，再決定方法能否擴大使用。",
        fontsize=11.5,
        color=MUTED,
        ha="left",
        va="center",
    )
    add_footer(ax)
    save_panel(fig, "3_honest_boundary.png", alt)


def main() -> None:
    data = load_evidence()
    render_daily_update(data)
    render_two_scores(data)
    render_honest_boundary(data)


if __name__ == "__main__":
    main()
