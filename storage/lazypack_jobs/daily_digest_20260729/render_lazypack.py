#!/usr/bin/env python3
"""Render the four data-bound PNG panels for the 2026-07-29 VolPred digest."""

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


EVIDENCE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/drafts/assets/"
    "crypto_canary_20260729.json"
)
ARTICLE_PATH = Path("/tmp/digest_20260729.md")
OUT_DIR = (
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "daily_digest_20260729"
)
SOURCE_LABEL = "2026-07-29 精選導讀證據包（逐字取自 8 篇已發佈來源文章）"

WIDTH_PX = 1600
HEIGHT_PX = 1000
DPI = 150
FIGSIZE = (WIDTH_PX / DPI, HEIGHT_PX / DPI)

INK = "#14202B"
NAVY = "#18324A"
BLUE = "#2563A6"
BLUE_SOFT = "#EAF2FA"
TEAL = "#0D7C78"
TEAL_SOFT = "#E5F3F1"
AMBER = "#B56A17"
AMBER_SOFT = "#FBF0DE"
RED = "#B7433D"
RED_SOFT = "#F9E9E7"
GREEN = "#287653"
GREEN_SOFT = "#E7F2EB"
MUTED = "#5D6975"
FAINT = "#8A949E"
LINE = "#D8E0E6"
PAPER = "#FFFFFF"
OFF_WHITE = "#F6F8FA"

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["figure.facecolor"] = PAPER
plt.rcParams["savefig.facecolor"] = PAPER


def load_inputs() -> tuple[dict[str, Any], str]:
    """Load both required absolute-path inputs and fail loudly on bad input."""
    with EVIDENCE_PATH.open("r", encoding="utf-8") as fh:
        evidence = json.load(fh)
    if not isinstance(evidence, dict):
        raise TypeError(f"{EVIDENCE_PATH} must contain a JSON object")

    article = ARTICLE_PATH.read_text(encoding="utf-8")
    if not article.strip():
        raise ValueError(f"{ARTICLE_PATH} is empty")
    if "金絲雀，還是住隔壁的鄰居？" not in article:
        raise ValueError(f"{ARTICLE_PATH} does not contain the expected article title")
    return evidence, article


def resolve_pointer(data: dict[str, Any], pointer: str) -> Any:
    """Resolve a strict RFC-6901-style JSON pointer; missing fields raise."""
    if not pointer.startswith("/"):
        raise ValueError(f"JSON pointer must begin with '/': {pointer}")
    current: Any = data
    for raw_part in pointer.split("/")[1:]:
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict):
            raise TypeError(
                f"Cannot descend into {type(current).__name__} while resolving {pointer}"
            )
        if part not in current:
            raise KeyError(f"Missing required evidence field: {pointer}")
        current = current[part]
    return current


def numeric(data: dict[str, Any], pointer: str) -> float:
    value = resolve_pointer(data, pointer)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"Expected a number at {pointer}, got {type(value).__name__}")
    return float(value)


def format_metric(
    data: dict[str, Any],
    pointer: str,
    *,
    digits: int | None = None,
    integer: bool = False,
    suffix: str = "",
    show_plus: bool = False,
) -> str:
    value = numeric(data, pointer)
    if integer:
        if not value.is_integer():
            raise ValueError(f"Expected an integer-valued number at {pointer}: {value}")
        rendered = f"{int(value):,}"
    else:
        if digits is None:
            raise ValueError(f"digits is required for non-integer metric {pointer}")
        sign = "+" if show_plus else ""
        rendered = f"{value:{sign}.{digits}f}"
    return f"{rendered}{suffix}"


def wrapped(text: str, width: int) -> str:
    return "\n".join(
        textwrap.wrap(
            text,
            width=width,
            # Chinese prose has no spaces, so textwrap otherwise treats an
            # entire sentence as one unbreakable word and lets it overflow.
            break_long_words=True,
            break_on_hyphens=False,
            replace_whitespace=False,
        )
    )


def new_canvas() -> tuple[plt.Figure, plt.Axes]:
    fig = plt.figure(figsize=FIGSIZE, dpi=DPI, facecolor=PAPER)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    return fig, ax


def rounded_box(
    ax: plt.Axes,
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    face: str = PAPER,
    edge: str = LINE,
    radius: float = 0.018,
    linewidth: float = 1.0,
) -> None:
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle=f"round,pad=0.012,rounding_size={radius}",
            facecolor=face,
            edgecolor=edge,
            linewidth=linewidth,
        )
    )


def footer(ax: plt.Axes) -> None:
    ax.plot([0.055, 0.945], [0.062, 0.062], color=LINE, linewidth=0.8)
    ax.text(
        0.055,
        0.035,
        f"資料來源｜{SOURCE_LABEL}",
        ha="left",
        va="center",
        fontsize=8.5,
        color=MUTED,
    )
    ax.text(
        0.945,
        0.035,
        "VolPred",
        ha="right",
        va="center",
        fontsize=9,
        color=NAVY,
        fontweight="bold",
    )


def editorial_header(ax: plt.Axes, title: str, deck: str) -> None:
    ax.text(
        0.055,
        0.935,
        title,
        ha="left",
        va="top",
        fontsize=28,
        color=INK,
        fontweight="bold",
    )
    ax.text(
        0.058,
        0.873,
        deck,
        ha="left",
        va="top",
        fontsize=11.5,
        color=MUTED,
    )
    ax.plot([0.055, 0.945], [0.835, 0.835], color=NAVY, linewidth=2.0)


def professional_header(ax: plt.Axes, title: str, deck: str) -> None:
    ax.add_patch(Rectangle((0, 0.835), 1, 0.165, facecolor=NAVY, edgecolor="none"))
    ax.text(
        0.055,
        0.935,
        title,
        ha="left",
        va="top",
        fontsize=28,
        color=PAPER,
        fontweight="bold",
    )
    ax.text(
        0.057,
        0.875,
        deck,
        ha="left",
        va="top",
        fontsize=11,
        color="#D5E2ED",
    )


def metric_card(
    ax: plt.Axes,
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    label: str,
    value: str,
    accent: str = BLUE,
    face: str = PAPER,
    note: str | None = None,
    label_width: int = 25,
) -> None:
    rounded_box(ax, x, y, w, h, face=face)
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            0.008,
            h,
            boxstyle="round,pad=0,rounding_size=0.008",
            facecolor=accent,
            edgecolor=accent,
            linewidth=0,
        )
    )
    ax.text(
        x + 0.028,
        y + h - 0.030,
        wrapped(label, label_width),
        ha="left",
        va="top",
        fontsize=10.5,
        color=MUTED,
        linespacing=1.3,
    )
    ax.text(
        x + 0.028,
        y + (0.038 if note else 0.028),
        value,
        ha="left",
        va="bottom",
        fontsize=25 if h >= 0.15 else 21,
        color=accent,
        fontweight="bold",
    )
    if note:
        ax.text(
            x + w - 0.020,
            y + 0.026,
            wrapped(note, 29),
            ha="right",
            va="bottom",
            fontsize=8.8,
            color=MUTED,
            linespacing=1.25,
        )


def save_panel(fig: plt.Figure, filename: str, alt: str) -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    output_path = os.path.join(OUT_DIR, filename)
    fig.savefig(
        output_path,
        dpi=DPI,
        facecolor=PAPER,
        edgecolor="none",
        metadata={"Title": filename, "Description": alt},
    )
    plt.close(fig)


def render_model(evidence: dict[str, Any]) -> None:
    fig, ax = new_canvas()
    editorial_header(
        ax,
        "金絲雀，還是住隔壁的鄰居？",
        "一起動，不等於誰先動。差別只在一件事：有沒有提前量。",
    )

    ax.text(
        0.055,
        0.795,
        "兩種燈，差別在「提前」",
        ha="left",
        va="top",
        fontsize=17,
        color=INK,
        fontweight="bold",
    )

    # The paired circles are an abstract signal/clock motif, not an illustration.
    ax.plot([0.098, 0.098], [0.665, 0.735], color=AMBER, linewidth=3)
    ax.add_patch(Circle((0.098, 0.700), 0.032, facecolor=AMBER_SOFT, edgecolor=AMBER, linewidth=2))
    ax.add_patch(Circle((0.098, 0.700), 0.010, facecolor=AMBER, edgecolor="none"))
    ax.text(
        0.145,
        0.736,
        wrapped("金絲雀：牠先倒下，你才有時間跑。這是領先指標該有的樣子。", 25),
        fontsize=11.2,
        color=INK,
        va="top",
        linespacing=1.45,
        fontweight="bold",
    )

    ax.plot([0.098, 0.098], [0.485, 0.555], color=TEAL, linewidth=3)
    ax.add_patch(Circle((0.098, 0.520), 0.032, facecolor=TEAL_SOFT, edgecolor=TEAL, linewidth=2))
    ax.add_patch(Circle((0.098, 0.520), 0.010, facecolor=TEAL, edgecolor="none"))
    ax.text(
        0.145,
        0.556,
        wrapped(
            "鄰居：同一場暴風雨一起淋濕，牠甚至淋得比你慘，但牠不會提前敲你家的門。",
            25,
        ),
        fontsize=11.2,
        color=INK,
        va="top",
        linespacing=1.45,
        fontweight="bold",
    )

    rounded_box(ax, 0.055, 0.190, 0.485, 0.190, face=OFF_WHITE, edge=OFF_WHITE)
    ax.text(
        0.082,
        0.337,
        "八年資料的歸類",
        fontsize=10,
        color=BLUE,
        fontweight="bold",
        va="top",
    )
    ax.text(
        0.082,
        0.292,
        wrapped("八年日資料把幣圈放在鄰居那一格。共動很真，提前量沒有。", 21),
        fontsize=15,
        color=INK,
        fontweight="bold",
        va="top",
        linespacing=1.45,
    )

    metric_card(
        ax,
        0.585,
        0.610,
        0.360,
        0.180,
        label="比特幣領先美股的顯著性（0.05 才及格）",
        value=format_metric(
            evidence, "/lead_lag/significance_btc_to_spy", digits=3
        ),
        accent=RED,
        face=RED_SOFT,
    )
    metric_card(
        ax,
        0.585,
        0.385,
        0.360,
        0.180,
        label="檢定樣本（對齊美股交易日）",
        value=format_metric(
            evidence, "/lead_lag/trading_days", integer=True, suffix=" 天"
        ),
        accent=BLUE,
        face=BLUE_SOFT,
    )
    metric_card(
        ax,
        0.585,
        0.160,
        0.360,
        0.180,
        label="比特幣與美股的平均相關（共動是真的）",
        value=format_metric(evidence, "/lead_lag/avg_dcc_btc_spy", digits=3),
        accent=TEAL,
        face=TEAL_SOFT,
    )
    footer(ax)
    save_panel(
        fig,
        "panel_model.png",
        "心智模型：金絲雀會提前倒下替你報時，鄰居只是跟你淋同一場雨；"
        "八年資料把幣圈歸在鄰居那一格",
    )


def render_shopping_list(evidence: dict[str, Any]) -> None:
    fig, ax = new_canvas()
    professional_header(
        ax,
        "幣圈訊號採購清單",
        "五個市場真的在盯的讀數，只有一個值得買單。",
    )

    rows = [
        (
            "比特幣暴跌預告美股｜直接跳過（顯著性）",
            format_metric(evidence, "/lead_lag/significance_btc_to_spy", digits=3),
            "四個傳遞方向全部沒過 "
            + format_metric(evidence, "/lead_lag/threshold", digits=2),
            RED,
            RED_SOFT,
        ),
        (
            "穩定幣贖回量｜直接跳過（出於巧合的機率）",
            format_metric(
                evidence,
                "/stablecoin/flow_coincidence_prob_pct",
                digits=1,
                suffix="%",
            ),
            "預測改善約 "
            + format_metric(
                evidence, "/stablecoin/flow_improvement", digits=7
            ).replace("-", "−")
            + "，準度近似丟銅板",
            RED,
            RED_SOFT,
        ),
        (
            "穩定幣脫鉤幅度｜可以買單（預測改善）",
            format_metric(evidence, "/stablecoin/depeg_improvement", digits=5),
            (
                "95% 時間壓在 "
                f"{format_metric(evidence, '/stablecoin/depeg_p95_pct', digits=2, suffix='%')}"
                " 內、平均 "
                f"{format_metric(evidence, '/stablecoin/depeg_mean_pct', digits=2, suffix='%')}"
                "；四資產只有比特幣通過"
            ),
            GREEN,
            GREEN_SOFT,
        ),
        (
            "永續合約資金費率｜半價都不要（方向顯著性）",
            format_metric(
                evidence, "/funding_rate/significance_direction", digits=3
            ),
            format_metric(
                evidence, "/funding_rate/oos_days", integer=True, suffix=" 天"
            )
            + "樣本外，誤差改善不到 1%",
            AMBER,
            AMBER_SOFT,
        ),
        (
            "拿 VIX 反推比特幣｜半價都不要（最佳比較強度）",
            format_metric(
                evidence,
                "/reverse_direction/strength_on_when_corr_high",
                digits=2,
                show_plus=True,
            ),
            format_metric(
                evidence, "/reverse_direction/oos_days", integer=True, suffix=" 天"
            )
            + "驗收，嚴格通過線是 "
            + format_metric(
                evidence, "/reverse_direction/strict_threshold", integer=True
            )
            + "，四種用法全沒碰到",
            AMBER,
            AMBER_SOFT,
        ),
    ]

    start_y = 0.695
    row_h = 0.115
    gap = 0.022
    for index, (label, value, note, accent, face) in enumerate(rows):
        y = start_y - index * (row_h + gap)
        rounded_box(ax, 0.055, y, 0.890, row_h, face=PAPER, edge=LINE, radius=0.012)
        ax.add_patch(Rectangle((0.055, y), 0.010, row_h, facecolor=accent, edgecolor="none"))
        ax.add_patch(
            Circle((0.095, y + row_h / 2), 0.020, facecolor=face, edgecolor=accent, linewidth=1.5)
        )
        ax.text(
            0.095,
            y + row_h / 2,
            str(index + 1),
            ha="center",
            va="center",
            fontsize=10,
            color=accent,
            fontweight="bold",
        )
        ax.text(
            0.130,
            y + 0.078,
            label,
            ha="left",
            va="center",
            fontsize=11.2,
            color=INK,
            fontweight="bold",
        )
        ax.text(
            0.130,
            y + 0.035,
            note,
            ha="left",
            va="center",
            fontsize=9.2,
            color=MUTED,
        )
        ax.text(
            0.910,
            y + row_h / 2,
            value,
            ha="right",
            va="center",
            fontsize=22,
            color=accent,
            fontweight="bold",
        )

    footer(ax)
    save_panel(
        fig,
        "panel_shopping_list.png",
        "五個市場真的在盯的幣圈讀數，實測後只有穩定幣脫鉤幅度值得買單，"
        "其餘半價都不要或直接跳過",
    )


def render_correction(evidence: dict[str, Any]) -> None:
    fig, ax = new_canvas()
    editorial_header(
        ax,
        "我們自己打臉自己",
        "舊結論沒有被藏起來；新規格把它放回更嚴格的檢驗。",
    )

    ax.text(
        0.055,
        0.795,
        "舊結論 vs 新重測",
        ha="left",
        va="top",
        fontsize=17,
        color=INK,
        fontweight="bold",
    )

    rounded_box(ax, 0.055, 0.600, 0.500, 0.135, face=RED_SOFT, edge=RED_SOFT)
    prior_date = resolve_pointer(evidence, "/prior_claim/published_at")
    if not isinstance(prior_date, str):
        raise TypeError("Expected a string at /prior_claim/published_at")
    old_sig = format_metric(
        evidence, "/prior_claim/significance_btc_vol_to_vix", digits=5
    )
    ax.text(
        0.080,
        0.704,
        wrapped(
            f"{prior_date} 舊文：比特幣波動對 VIX 的顯著性 {old_sig}，"
            "寫成「可作為早期預警」。",
            37,
        ),
        fontsize=10.6,
        color=INK,
        va="top",
        linespacing=1.35,
        fontweight="bold",
    )

    rounded_box(ax, 0.055, 0.425, 0.500, 0.135, face=TEAL_SOFT, edge=TEAL_SOFT)
    new_sig = format_metric(
        evidence, "/lead_lag/significance_btc_to_spy", digits=3
    )
    ax.text(
        0.080,
        0.529,
        wrapped(
            f"2026-07-27 重測：四個方向全部不顯著，比特幣領先美股只有 {new_sig}。",
            37,
        ),
        fontsize=10.6,
        color=INK,
        va="top",
        linespacing=1.35,
        fontweight="bold",
    )

    rounded_box(ax, 0.055, 0.145, 0.500, 0.230, face=OFF_WHITE, edge=OFF_WHITE)
    method_text = (
        "新版可信在四點：樣本拉到八年、全部對齊美股交易日、週末震盪併進下一個交易日、"
        "再加三資產聯合檢定當保險。"
    )
    ax.text(
        0.080,
        0.340,
        wrapped(method_text, 27),
        fontsize=11.5,
        color=INK,
        va="top",
        linespacing=1.5,
        fontweight="bold",
    )

    metric_card(
        ax,
        0.600,
        0.600,
        0.345,
        0.150,
        label="舊文樣本",
        value=format_metric(
            evidence, "/prior_claim/trading_days", integer=True, suffix=" 天"
        ),
        accent=RED,
        face=RED_SOFT,
    )
    metric_card(
        ax,
        0.600,
        0.390,
        0.345,
        0.150,
        label="新重測樣本",
        value=format_metric(
            evidence, "/lead_lag/trading_days", integer=True, suffix=" 天"
        ),
        accent=TEAL,
        face=TEAL_SOFT,
    )
    metric_card(
        ax,
        0.600,
        0.180,
        0.345,
        0.150,
        label="三資產聯手對美股的顯著性",
        value=format_metric(
            evidence, "/lead_lag/joint_combined_to_spy", digits=3
        ),
        accent=BLUE,
        face=BLUE_SOFT,
    )
    footer(ax)
    save_panel(
        fig,
        "panel_correction.png",
        "三月的舊文替金絲雀說法背書，七月的八年重測推翻它；新版樣本更長、"
        "對齊美股交易日、週末併入次日、加三資產聯合檢定",
    )


def render_takeaway(evidence: dict[str, Any]) -> None:
    fig, ax = new_canvas()
    professional_header(
        ax,
        "事件週怎麼用這盞燈",
        "Fed 拍板加四大雲端財報週：把同步訊號和領先訊號分開。",
    )

    ax.text(
        0.055,
        0.790,
        "三個動作",
        ha="left",
        va="top",
        fontsize=17,
        color=INK,
        fontweight="bold",
    )

    corr_crisis = format_metric(
        evidence, "/neighbour_evidence/corr_vix_above_35", digits=3
    )
    corr_alt = format_metric(
        evidence, "/hedge_illusion/corr_vix_above_25", digits=2
    )
    actions = [
        (
            "01",
            "比特幣今晚急殺？在你的美股決策裡權重接近零，"
            "它講的風險偏好你已從美股自己讀到。",
            RED,
            RED_SOFT,
        ),
        (
            "02",
            f"比特幣安靜？也別當成背書。危機期相關跳到 {corr_crisis} 到 {corr_alt}，"
            "講的是同步不是保證。",
            AMBER,
            AMBER_SOFT,
        ),
        (
            "03",
            "只留一個位置給穩定幣脫鉤幅度，並且清楚它只管比特幣未來一週，"
            "不管你的 SPY。",
            GREEN,
            GREEN_SOFT,
        ),
    ]
    action_y = [0.580, 0.365, 0.150]
    for y, (number, body, accent, face) in zip(action_y, actions):
        rounded_box(ax, 0.055, y, 0.545, 0.165, face=PAPER, edge=LINE)
        ax.add_patch(
            Circle((0.100, y + 0.113), 0.024, facecolor=face, edgecolor=accent, linewidth=1.3)
        )
        ax.text(
            0.100,
            y + 0.113,
            number,
            ha="center",
            va="center",
            fontsize=9.5,
            color=accent,
            fontweight="bold",
        )
        ax.text(
            0.140,
            y + 0.132,
            wrapped(body, 34),
            ha="left",
            va="top",
            fontsize=10.5,
            color=INK,
            linespacing=1.4,
            fontweight="bold",
        )

    metric_card(
        ax,
        0.645,
        0.590,
        0.300,
        0.160,
        label="危機期（VIX 破 35）比特幣與美股相關",
        value=corr_crisis,
        accent=RED,
        face=RED_SOFT,
        label_width=20,
    )
    metric_card(
        ax,
        0.645,
        0.380,
        0.300,
        0.160,
        label="平靜期（VIX 低於 15）相關",
        value=format_metric(
            evidence, "/neighbour_evidence/corr_vix_below_15", digits=3
        ),
        accent=TEAL,
        face=TEAL_SOFT,
        label_width=20,
    )
    metric_card(
        ax,
        0.645,
        0.170,
        0.300,
        0.160,
        label="加 20% 比特幣後的組合偏態（越負尾巴越長）",
        value=format_metric(
            evidence, "/hedge_illusion/skew_plus_20pct_btc", digits=2
        ),
        accent=AMBER,
        face=AMBER_SOFT,
        label_width=20,
    )
    footer(ax)
    save_panel(
        fig,
        "panel_takeaway.png",
        "Fed 拍板加四大雲端財報週的用法：比特幣急殺在美股決策裡權重接近零，"
        "只留一個位置給穩定幣脫鉤幅度",
    )


def main() -> None:
    evidence, _article = load_inputs()
    render_model(evidence)
    render_shopping_list(evidence)
    render_correction(evidence)
    render_takeaway(evidence)


if __name__ == "__main__":
    main()
