#!/usr/bin/env python3
"""Render the four-panel Traditional-Chinese lazy-pack for the 2026-07-17 digest.

Every displayed statistic is resolved from the evidence JSON at render time,
except the approximately seven-month VIXTWN limitation, which is stated only in
the supplied article markdown.  Missing evidence fields deliberately raise.
"""
from __future__ import annotations

import json
import os
import textwrap
from pathlib import Path
from typing import Any, Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyBboxPatch, Rectangle


EVIDENCE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/drafts/assets/"
    "digest_20260717/evidence.json"
)
ARTICLE_PATH = Path("/tmp/digest_20260717.md")
OUT_DIR = "/tmp/digest_20260717_poster"

WIDTH = 1600
HEIGHT = 1000
DPI = 150

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False

NAVY = "#102A43"
INK = "#172B3A"
MUTED = "#5B6B78"
PALE = "#F4F7FA"
LINE = "#D9E2EA"
BLUE = "#2774AE"
BLUE_SOFT = "#E7F1F8"
TEAL = "#16827A"
TEAL_SOFT = "#E5F4F1"
RED = "#C43D43"
RED_SOFT = "#FAE9EA"
AMBER = "#B56B12"
AMBER_SOFT = "#FBF0DD"
GREEN = "#397A55"
GREEN_SOFT = "#E7F2EB"
WHITE = "#FFFFFF"


def load_inputs() -> tuple[dict[str, Any], str]:
    with EVIDENCE_PATH.open("r", encoding="utf-8") as handle:
        evidence = json.load(handle)
    article = ARTICLE_PATH.read_text(encoding="utf-8")
    if not article.strip():
        raise ValueError(f"Article markdown is empty: {ARTICLE_PATH}")
    if not isinstance(evidence, dict):
        raise TypeError("Evidence root must be a JSON object")
    return evidence, article


def require(data: dict[str, Any], path: str) -> Any:
    current: Any = data
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise KeyError(f"Missing required evidence field: {path}")
        current = current[part]
    if current is None:
        raise ValueError(f"Required evidence field is null: {path}")
    return current


def number(data: dict[str, Any], path: str) -> float:
    value = require(data, path)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"Expected numeric evidence field: {path}")
    return float(value)


def integer(data: dict[str, Any], path: str, commas: bool = False) -> str:
    value = number(data, path)
    if not value.is_integer():
        raise ValueError(f"Expected integer-valued evidence field: {path}")
    return f"{int(value):,}" if commas else str(int(value))


def decimal(data: dict[str, Any], path: str, places: int = 1) -> str:
    return f"{number(data, path):.{places}f}"


def signed(data: dict[str, Any], path: str, places: int = 1) -> str:
    return f"{number(data, path):+.{places}f}"


def evidence_labels(data: Any) -> list[str]:
    """Collect only explicit reader-facing labels; never derive experiment IDs."""
    found: list[str] = []
    if isinstance(data, dict):
        label = data.get("label")
        if isinstance(label, str) and label.strip():
            found.append(label.strip())
        for value in data.values():
            found.extend(evidence_labels(value))
    elif isinstance(data, list):
        for value in data:
            found.extend(evidence_labels(value))
    return list(dict.fromkeys(found))


def footer_text(data: dict[str, Any]) -> str:
    labels = evidence_labels(data)
    if labels:
        return "資料來源：" + "、".join(labels)
    # The strict plan contains no evidence.*.label.  This neutral reader-facing
    # fallback identifies the publisher/package without guessing internal IDs.
    return "資料來源：VolPred｜數據綁定本文證據包"


def canvas() -> tuple[plt.Figure, plt.Axes]:
    fig = plt.figure(figsize=(WIDTH / DPI, HEIGHT / DPI), dpi=DPI, facecolor=WHITE)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, WIDTH)
    ax.set_ylim(0, HEIGHT)
    ax.axis("off")
    return fig, ax


def card(
    ax: plt.Axes,
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    face: str = WHITE,
    edge: str = LINE,
    radius: float = 20,
    linewidth: float = 1.2,
) -> FancyBboxPatch:
    patch = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle=f"round,pad=0,rounding_size={radius}",
        facecolor=face,
        edgecolor=edge,
        linewidth=linewidth,
    )
    ax.add_patch(patch)
    return patch


def txt(
    ax: plt.Axes,
    x: float,
    y: float,
    value: str,
    *,
    size: float,
    color: str = INK,
    weight: str = "normal",
    ha: str = "left",
    va: str = "top",
    linespacing: float = 1.25,
    alpha: float = 1.0,
) -> None:
    ax.text(
        x,
        y,
        value,
        fontsize=size,
        color=color,
        fontweight=weight,
        ha=ha,
        va=va,
        linespacing=linespacing,
        alpha=alpha,
        family="Heiti TC",
    )


def wrap_chars(value: str, width: int) -> str:
    """Wrap reader-facing dynamic copy without changing its evidence content."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Reader-facing text must be a non-empty string")
    return "\n".join(
        textwrap.wrap(
            value.strip(),
            width=width,
            break_long_words=True,
            break_on_hyphens=False,
            replace_whitespace=False,
        )
    )


def page_header(
    ax: plt.Axes,
    kicker: str,
    title: str,
    subtitle: str,
    *,
    title_color: str = NAVY,
) -> None:
    # Matplotlib's CJK line box is substantially taller than the visible ink.
    # These are deliberately separate rows with enough line-box clearance for
    # the layout guard, rather than visually adjacent baselines.
    txt(ax, 70, 982, kicker, size=12, color=BLUE, weight="bold")
    txt(ax, 70, 942, title, size=27, color=title_color, weight="bold")
    txt(ax, 70, 846, subtitle, size=14, color=MUTED)
    ax.plot([70, 1530], [800, 800], color=LINE, lw=1.4)


def page_footer(ax: plt.Axes, data: dict[str, Any]) -> None:
    ax.plot([70, 1530], [54, 54], color=LINE, lw=1.0)
    txt(ax, 70, 35, footer_text(data), size=10.5, color=MUTED, va="center")
    txt(ax, 1530, 35, "換錨日四問｜2026-07-17", size=10.5, color=MUTED, ha="right", va="center")


def save(fig: plt.Figure, filename: str) -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    fig.savefig(
        os.path.join(OUT_DIR, filename),
        dpi=DPI,
        facecolor=WHITE,
        edgecolor="none",
    )
    plt.close(fig)


def render_panel_1(e: dict[str, Any]) -> None:
    fig, ax = canvas()
    page_header(
        ax,
        "VOLPRED 精選導讀",
        "財報不是成績單，是換錨日",
        "市場不是替上一季打分數；它在重算下一季的估值座標。",
    )

    card(ax, 70, 566, 440, 226, face=PALE, edge=LINE)
    txt(ax, 104, 756, "已知數", size=21, color=MUTED, weight="bold")
    txt(ax, 104, 690, "營收 ／ 毛利率 ／ EPS", size=15.5, color=INK, weight="bold")
    txt(ax, 104, 638, "回答「上一季交了什麼」", size=13, color=MUTED)
    txt(ax, 104, 596, "公布後，資訊差歸零", size=13.5, color=MUTED, weight="bold")

    ax.plot([555, 675], [678, 678], color=BLUE, lw=5, solid_capstyle="round")
    ax.plot([647, 675, 647], [696, 678, 660], color=BLUE, lw=5, solid_capstyle="round")
    txt(ax, 615, 726, "市場視線往前", size=14, color=BLUE, weight="bold", ha="center")

    card(ax, 720, 566, 810, 226, face=BLUE_SOFT, edge="#BFD8E8")
    txt(ax, 754, 756, "錨", size=21, color=BLUE, weight="bold")
    txt(ax, 754, 690, "指引 ／ 毛利率走向 ／ 資本支出", size=15.5, color=INK, weight="bold")
    txt(ax, 754, 638, "回答「下一季該用哪組假設」", size=13, color=MUTED)
    txt(ax, 754, 596, "錨一換，估值就要重算", size=13.5, color=BLUE, weight="bold")

    card(ax, 70, 102, 1460, 414, face=WHITE, edge=LINE)
    txt(
        ax,
        104,
        478,
        f"{require(e, 'anchor_event.company')}｜{require(e, 'anchor_event.date')}",
        size=16,
        color=BLUE,
        weight="bold",
    )
    txt(ax, 104, 437, "三項全贏", size=29, color=GREEN, weight="bold")

    metrics = [
        (
            "營收",
            f"{integer(e, 'anchor_event.q2_revenue_usd_bn')} 億美元",
            f"共識 {decimal(e, 'anchor_event.q2_revenue_consensus_usd_bn')} 億美元",
        ),
        (
            "毛利率",
            f"{decimal(e, 'anchor_event.q2_gross_margin_pct')}%",
            f"越過指引上緣 {decimal(e, 'anchor_event.q2_gross_margin_guide_high_pct')}%",
        ),
        (
            "ADR EPS",
            f"{decimal(e, 'anchor_event.q2_adr_eps_usd', 2)} 美元",
            f"共識 {decimal(e, 'anchor_event.q2_adr_eps_consensus_usd', 2)} 美元",
        ),
    ]
    for index, (label, value, note) in enumerate(metrics):
        x = 104 + index * 230
        txt(ax, x, 350, label, size=11.5, color=MUTED, weight="bold")
        txt(ax, x, 310, value, size=18, color=INK, weight="bold")
        txt(ax, x, 252, note, size=10.5, color=MUTED)

    ax.plot([850, 850], [151, 463], color=LINE, lw=1.4)
    txt(ax, 898, 447, "盤前反而", size=13, color=MUTED, weight="bold")
    txt(
        ax,
        898,
        407,
        f"{signed(e, 'anchor_event.adr_premarket_move_pct')}%  ADR",
        size=37,
        color=RED,
        weight="bold",
    )
    txt(ax, 898, 309, "因為被換掉的是兩個未來錨：", size=13.5, color=INK, weight="bold")
    old_capex = (
        f"{integer(e, 'anchor_event.capex_old_low_usd_bn')}–"
        f"{integer(e, 'anchor_event.capex_old_high_usd_bn')}"
    )
    new_capex = (
        f"{integer(e, 'anchor_event.capex_new_low_usd_bn')}–"
        f"{integer(e, 'anchor_event.capex_new_high_usd_bn')}"
    )
    txt(
        ax,
        898,
        267,
        f"資本支出  {old_capex} → {new_capex} 億美元",
        size=13.5,
        color=INK,
    )
    txt(
        ax,
        898,
        229,
        f"中點 +{integer(e, 'anchor_event.capex_midpoint_hike_pct')}%",
        size=16,
        color=RED,
        weight="bold",
    )
    txt(
        ax,
        898,
        181,
        "Q3 毛利率指引  "
        f"{integer(e, 'anchor_event.q3_gross_margin_guide_low_pct')}–"
        f"{integer(e, 'anchor_event.q3_gross_margin_guide_high_pct')}%"
        f"\n（低於 Q2 的 {decimal(e, 'anchor_event.q2_gross_margin_pct')}%）",
        size=13,
        color=INK,
        linespacing=1.35,
    )
    page_footer(ax, e)
    save(fig, "1_concept_anchor_day.png")


def bento_badge(ax: plt.Axes, x: float, y: float, label: str, color: str) -> None:
    ax.add_patch(Circle((x, y), 27, facecolor=color, edgecolor="none"))
    txt(ax, x, y, label, size=17, color=WHITE, weight="bold", ha="center", va="center")


def render_panel_2(e: dict[str, Any]) -> None:
    fig, ax = canvas()
    page_header(
        ax,
        "SUMMARY CARD",
        f"{require(e, 'framework.name')}｜看到財報先走這四格",
        "每格只做一件事：辨認錨、核對保費、劃掉 beat、拉長時間窗。",
    )

    positions = [(70, 455), (815, 455), (70, 120), (815, 120)]
    faces = [BLUE_SOFT, TEAL_SOFT, AMBER_SOFT, RED_SOFT]
    edges = ["#BFD8E8", "#B9DDD8", "#E7CFA9", "#E8BEC1"]
    colors = [BLUE, TEAL, AMBER, RED]
    for (x, y), face, edge in zip(positions, faces, edges):
        card(ax, x, y, 715, 295, face=face, edge=edge)

    # Q1
    bento_badge(ax, 115, 706, "一", colors[0])
    txt(
        ax,
        158,
        730,
        wrap_chars(require(e, "q1_anchor_or_known.question"), 15),
        size=16,
        weight="bold",
        linespacing=1.25,
    )
    txt(ax, 104, 632, "個股換錨，不等於大盤換錨", size=13.5, color=MUTED)
    txt(
        ax,
        104,
        588,
        f"{integer(e, 'q1_anchor_or_known.spy_sample_days', commas=True)} 個交易日",
        size=25,
        color=colors[0],
        weight="bold",
    )
    txt(
        ax,
        104,
        521,
        "財報季／非財報季五個波動比值全部 < 1\n"
        f"最低 {decimal(e, 'q1_anchor_or_known.ratio_squared_return', 3)}",
        size=12.5,
        color=INK,
        linespacing=1.35,
    )

    # Q2
    bento_badge(ax, 860, 706, "二", colors[1])
    txt(ax, 903, 730, require(e, "q2_premium_paid.question"), size=16, weight="bold")
    txt(ax, 849, 661, "保費有先付，但沒有超收", size=13.5, color=MUTED)
    txt(
        ax,
        849,
        610,
        f"{decimal(e, 'q2_premium_paid.iv_expiry_0717_pct')}%",
        size=25,
        color=colors[1],
        weight="bold",
    )
    txt(
        ax,
        849,
        551,
        f"隱含  vs  已實現 {integer(e, 'q2_premium_paid.realized_vol_20d_pct')}%",
        size=12.5,
        color=MUTED,
        weight="bold",
    )
    txt(
        ax,
        849,
        511,
        f"事件加價只有 {decimal(e, 'q2_premium_paid.earnings_bump_pp')} 個百分點\n不是肥保費，是標的本身在震",
        size=12.5,
        color=INK,
        linespacing=1.35,
    )

    # Q3
    bento_badge(ax, 115, 371, "三", colors[2])
    txt(ax, 158, 395, "beat 幅度別看", size=16, weight="bold")
    txt(ax, 104, 326, "知道「有沒有公布」比「贏多少」更有用", size=13.5, color=MUTED)
    txt(
        ax,
        104,
        272,
        f"t = {decimal(e, 'q3_beat_size.same_day.binary_flag_t', 2)}｜二元旗幟",
        size=24,
        color=colors[2],
        weight="bold",
    )
    txt(
        ax,
        104,
        204,
        f"連續驚喜幅度只有 t = {decimal(e, 'q3_beat_size.same_day.surprise_size_t', 2)}",
        size=13,
        color=INK,
    )

    # Q4
    bento_badge(ax, 860, 371, "四", colors[3])
    txt(ax, 903, 395, require(e, "q4_t_plus_5.question"), size=16, weight="bold")
    txt(ax, 849, 326, "公告日可能只是價格發現的起點", size=13.5, color=MUTED)
    txt(
        ax,
        849,
        272,
        f"+{decimal(e, 'q4_t_plus_5.us_event_study.msft_post5_diff_pct')}%｜MSFT 財報後 5 日",
        size=22,
        color=colors[3],
        weight="bold",
    )
    txt(
        ax,
        849,
        204,
        "Bonferroni 後 "
        f"p = {decimal(e, 'q4_t_plus_5.us_event_study.msft_post5_bonferroni_p', 4)}",
        size=13,
        color=INK,
    )

    page_footer(ax, e)
    save(fig, "2_method_four_questions.png")


def scientific_column(
    ax: plt.Axes,
    x: float,
    title: str,
    subtitle: str,
    accent: str,
) -> None:
    card(ax, x, 110, 462, 680, face=WHITE, edge=LINE, radius=14)
    ax.add_patch(Rectangle((x, 742), 462, 48, facecolor=accent, edgecolor="none"))
    txt(ax, x + 24, 766, title, size=18, color=WHITE, weight="bold", va="center")
    txt(ax, x + 24, 716, subtitle, size=11.5, color=MUTED)


def render_panel_3(e: dict[str, Any]) -> None:
    fig, ax = canvas()
    page_header(
        ax,
        "三層獨立證據",
        "beat 幅度：看得到，卻預測不了波動",
        "從當天、下個月到公開特徵，訊號逐層接受樣本外檢驗。",
    )

    xs = [70, 569, 1068]
    scientific_column(ax, xs[0], "A｜當天", "事件旗幟 vs 驚喜幅度", BLUE)
    scientific_column(ax, xs[1], "B｜下個月", "panel 迴歸的經濟量級", TEAL)
    scientific_column(ax, xs[2], "C｜看得到的特徵", "預先鎖定的確認性檢驗", AMBER)

    # Column A
    txt(
        ax,
        xs[0] + 24,
        680,
        f"{integer(e, 'q3_beat_size.same_day.n_stocks')} 支 S&P 500\n"
        f"{integer(e, 'q3_beat_size.same_day.n_obs', commas=True)} 筆日報酬｜"
        f"{integer(e, 'q3_beat_size.same_day.n_earnings_events', commas=True)} 個財報事件",
        size=11.5,
        color=INK,
        weight="bold",
        linespacing=1.35,
    )
    labels = ["二元旗幟", "驚喜幅度"]
    t_paths = [
        "q3_beat_size.same_day.binary_flag_t",
        "q3_beat_size.same_day.surprise_size_t",
    ]
    p_paths = [
        "q3_beat_size.same_day.binary_flag_p",
        "q3_beat_size.same_day.surprise_size_p",
    ]
    bar_colors = [BLUE, "#AFC4D5"]
    max_t = max(number(e, path) for path in t_paths)
    for i, (label, t_path, p_path, color) in enumerate(zip(labels, t_paths, p_paths, bar_colors)):
        label_y = 570 - i * 130
        bar_y = label_y - 58
        txt(
            ax,
            xs[0] + 24,
            label_y,
            label,
            size=12.5,
            color=MUTED,
            weight="bold",
            va="center",
        )
        txt(
            ax,
            xs[0] + 438,
            label_y,
            f"t={decimal(e, t_path, 2)}｜p={decimal(e, p_path, 2)}",
            size=11,
            color=INK,
            weight="bold",
            va="center",
            ha="right",
        )
        width = 414 * number(e, t_path) / max_t
        ax.add_patch(Rectangle((xs[0] + 24, bar_y), width, 26, facecolor=color, edgecolor="none"))
    card(ax, xs[0] + 24, 210, 414, 116, face=BLUE_SOFT, edge="none", radius=12)
    txt(ax, xs[0] + 46, 304, "模型代價差", size=12.5, color=MUTED, weight="bold")
    txt(
        ax,
        xs[0] + 46,
        258,
        f"AIC 差 {integer(e, 'q3_beat_size.same_day.aic_gap', commas=True)}",
        size=22,
        color=BLUE,
        weight="bold",
    )
    txt(ax, xs[0] + 24, 171, "結論｜幅度沒有多帶來預測力", size=14, color=INK, weight="bold")

    # Column B
    txt(
        ax,
        xs[1] + 24,
        680,
        f"{integer(e, 'q3_beat_size.next_month.n_firms')} 家公司｜"
        f"{integer(e, 'q3_beat_size.next_month.n_months')} 個月\n"
        f"{integer(e, 'q3_beat_size.next_month.n_firm_months', commas=True)} 筆公司月份",
        size=11.5,
        color=INK,
        weight="bold",
        linespacing=1.35,
    )
    txt(ax, xs[1] + 231, 565, "係數", size=12.5, color=MUTED, weight="bold", ha="center")
    txt(
        ax,
        xs[1] + 231,
        525,
        f"+{decimal(e, 'q3_beat_size.next_month.coef', 3)}",
        size=36,
        color=TEAL,
        weight="bold",
        ha="center",
    )
    ax.plot([xs[1] + 58, xs[1] + 404], [420, 420], color=LINE, lw=5, solid_capstyle="round")
    ax.plot([xs[1] + 231, xs[1] + 231], [398, 442], color=INK, lw=1.5)
    ax.add_patch(Circle((xs[1] + 244, 420), 9, facecolor=TEAL, edgecolor=WHITE, lw=2))
    txt(ax, xs[1] + 231, 377, "估計接近零；誤差範圍跨零", size=12, color=MUTED, ha="center")
    card(ax, xs[1] + 24, 210, 414, 116, face=TEAL_SOFT, edge="none", radius=12)
    txt(ax, xs[1] + 46, 304, "換成年化波動影響", size=12.5, color=MUTED, weight="bold")
    txt(
        ax,
        xs[1] + 46,
        258,
        f"僅 {decimal(e, 'q3_beat_size.next_month.annualized_vol_impact_pp')} 個百分點",
        size=19,
        color=TEAL,
        weight="bold",
    )
    txt(ax, xs[1] + 24, 171, "結論｜小到不足以調整部位", size=14, color=INK, weight="bold")

    # Column C
    txt(
        ax,
        xs[2] + 24,
        680,
        f"{integer(e, 'q3_beat_size.visible_features.n_firms')} 家公司｜"
        f"{integer(e, 'q3_beat_size.visible_features.n_indicators')} 個指標\n"
        f"{integer(e, 'q3_beat_size.visible_features.n_hypotheses')} 個假設",
        size=11.5,
        color=INK,
        weight="bold",
        linespacing=1.35,
    )
    txt(ax, xs[2] + 24, 602, "通過", size=12, color=MUTED, weight="bold")
    for i in range(int(number(e, "q3_beat_size.visible_features.n_hypotheses"))):
        ax.add_patch(Circle((xs[2] + 92 + i * 52, 558), 15, facecolor=WHITE, edgecolor=AMBER, lw=2))
    txt(
        ax,
        xs[2] + 395,
        558,
        f"{integer(e, 'q3_beat_size.visible_features.n_passed')} 個",
        size=17,
        color=AMBER,
        weight="bold",
        ha="right",
        va="center",
    )
    rows: Iterable[tuple[str, str, str]] = [
        (
            "BH 校正後最小 p",
            decimal(e, "q3_beat_size.visible_features.min_bh_adjusted_p", 3),
            MUTED,
        ),
        ("交叉驗證 R²", signed(e, "q3_beat_size.visible_features.cv_r2", 3), RED),
        ("Tier A", integer(e, "q3_beat_size.visible_features.tier_a_count") + " 家", AMBER),
    ]
    for i, (label, value, color) in enumerate(rows):
        y = 472 - i * 72
        ax.plot([xs[2] + 24, xs[2] + 438], [y - 20, y - 20], color=LINE, lw=1)
        txt(ax, xs[2] + 24, y + 8, label, size=13, color=MUTED, va="center")
        txt(ax, xs[2] + 420, y + 8, value, size=18, color=color, weight="bold", ha="right", va="center")
    card(ax, xs[2] + 24, 210, 414, 78, face=AMBER_SOFT, edge="none", radius=12)
    txt(ax, xs[2] + 231, 249, "R² < 0：比猜平均值還差", size=15, color=RED, weight="bold", ha="center", va="center")
    txt(ax, xs[2] + 24, 171, "結論｜分類系統沒有成立", size=14, color=INK, weight="bold")

    page_footer(ax, e)
    save(fig, "3_results_beat_is_noise.png")


def score_card(
    ax: plt.Axes,
    x: float,
    y: float,
    w: float,
    h: float,
    number_label: str,
    title: str,
    verdict: str,
    accent: str,
) -> None:
    card(ax, x, y, w, h, face=WHITE, edge=LINE, radius=14)
    ax.add_patch(Rectangle((x, y + h - 54), w, 54, facecolor=PALE, edgecolor="none"))
    ax.add_patch(Circle((x + 35, y + h - 27), 19, facecolor=accent, edgecolor="none"))
    txt(ax, x + 35, y + h - 27, number_label, size=12, color=WHITE, weight="bold", ha="center", va="center")
    txt(ax, x + 65, y + h - 27, title, size=16, color=INK, weight="bold", va="center")
    txt(ax, x + w - 26, y + h - 27, verdict, size=13, color=accent, weight="bold", ha="right", va="center")


def render_panel_4(e: dict[str, Any]) -> None:
    fig, ax = canvas()
    ax.add_patch(Rectangle((0, 780), WIDTH, 220, facecolor=NAVY, edgecolor="none"))
    txt(ax, 70, 982, "2026-07-16｜台積電法說會對帳", size=11.5, color="#9FC5E1", weight="bold")
    txt(ax, 70, 938, "四問走完：三項全贏，市場仍往下開", size=27, color=WHITE, weight="bold")
    txt(ax, 70, 835, "市場重算的是下一季的假設。", size=14, color="#D7E6F1")

    score_card(ax, 70, 545, 715, 230, "一", "已知數還是錨？", "是換錨日", BLUE)
    txt(ax, 100, 686, f"資本支出中點 +{integer(e, 'anchor_event.capex_midpoint_hike_pct')}%", size=20, color=BLUE, weight="bold")
    txt(
        ax,
        100,
        621,
        "Q3 毛利率指引 "
        f"{integer(e, 'anchor_event.q3_gross_margin_guide_low_pct')}–"
        f"{integer(e, 'anchor_event.q3_gross_margin_guide_high_pct')}%"
        f"，低於 Q2 的 {decimal(e, 'anchor_event.q2_gross_margin_pct')}%",
        size=12.5,
        color=INK,
    )
    txt(
        ax,
        100,
        575,
        "但只是個股：SPY 五個比值全 < 1，最低 "
        f"{decimal(e, 'q1_anchor_or_known.ratio_squared_return', 3)}",
        size=11.5,
        color=MUTED,
    )

    score_card(ax, 815, 545, 715, 230, "二", "市場有沒有先付保費？", "付了，沒超收", TEAL)
    txt(
        ax,
        845,
        686,
        f"隱含 ±{decimal(e, 'q2_premium_paid.implied_single_day_move_pct')}% ｜ "
        f"實際盤前 {signed(e, 'anchor_event.adr_premarket_move_pct')}%",
        size=18,
        color=TEAL,
        weight="bold",
    )
    txt(ax, 845, 624, "幅度標對，方向標錯", size=14, color=INK, weight="bold")
    txt(
        ax,
        845,
        575,
        f"隱含 {decimal(e, 'q2_premium_paid.iv_expiry_0717_pct')}% vs 已實現 "
        f"{integer(e, 'q2_premium_paid.realized_vol_20d_pct')}%",
        size=11.5,
        color=MUTED,
    )

    score_card(ax, 70, 270, 715, 245, "三", "beat 幅度別看", "再次失效", AMBER)
    txt(ax, 100, 426, "三項全贏，ADR 仍下跌", size=20, color=AMBER, weight="bold")
    txt(
        ax,
        100,
        364,
        f"營收 {integer(e, 'anchor_event.q2_revenue_usd_bn')} > "
        f"{decimal(e, 'anchor_event.q2_revenue_consensus_usd_bn')} 億美元",
        size=12.5,
        color=INK,
    )
    txt(
        ax,
        100,
        319,
        f"毛利率 {decimal(e, 'anchor_event.q2_gross_margin_pct')}% > "
        f"{decimal(e, 'anchor_event.q2_gross_margin_guide_high_pct')}%｜"
        f"EPS {decimal(e, 'anchor_event.q2_adr_eps_usd', 2)} > "
        f"{decimal(e, 'anchor_event.q2_adr_eps_consensus_usd', 2)}",
        size=11.5,
        color=MUTED,
    )

    score_card(ax, 815, 270, 715, 245, "四", "看 T+5，不是 T+0", "反應尚未結清", RED)
    txt(ax, 845, 426, "盤前價不是收盤答案", size=20, color=RED, weight="bold")
    txt(ax, 845, 364, "台股真正反應日：2026-07-17", size=12.5, color=INK, weight="bold")
    txt(
        ax,
        845,
        325,
        f"{integer(e, 'q4_t_plus_5.tsmc_event_profile.n_calls')} 場基準：反應日 "
        f"{decimal(e, 'q4_t_plus_5.tsmc_event_profile.reaction_day_abs_move_pct', 2)}%"
        f"｜平常 {decimal(e, 'q4_t_plus_5.tsmc_event_profile.normal_day_abs_move_pct', 2)}% 的 "
        f"{decimal(e, 'q4_t_plus_5.tsmc_event_profile.reaction_day_multiple')} 倍",
        size=10.5,
        color=MUTED,
    )
    txt(
        ax,
        845,
        292,
        f"反應後 5 日回到 {decimal(e, 'q4_t_plus_5.tsmc_event_profile.post5d_abs_move_pct', 2)}% 的日常",
        size=10.5,
        color=MUTED,
    )

    card(ax, 70, 94, 1460, 145, face=PALE, edge=LINE, radius=14)
    txt(ax, 100, 215, "誠實限制", size=13, color=NAVY, weight="bold")
    txt(
        ax,
        100,
        171,
        "美股事件研究每家公司僅 "
        f"{integer(e, 'q4_t_plus_5.us_event_study.n_earnings_per_firm')} 次財報；"
        "VIXTWN 樣本僅約七個月。",
        size=13,
        color=INK,
        weight="bold",
    )
    txt(ax, 100, 126, "平均輪廓是統計重心，不是這一場必然照走的劇本。", size=11.5, color=MUTED)

    page_footer(ax, e)
    save(fig, "4_takeaway_tsmc_scorecard.png")


def validate_required_fields(e: dict[str, Any]) -> None:
    """Fail before drawing if any displayed evidence field is unavailable."""
    paths = [
        "framework.name",
        "anchor_event.company",
        "anchor_event.date",
        "anchor_event.q2_revenue_usd_bn",
        "anchor_event.q2_revenue_consensus_usd_bn",
        "anchor_event.q2_gross_margin_pct",
        "anchor_event.q2_gross_margin_guide_high_pct",
        "anchor_event.q2_adr_eps_usd",
        "anchor_event.q2_adr_eps_consensus_usd",
        "anchor_event.adr_premarket_move_pct",
        "anchor_event.capex_old_low_usd_bn",
        "anchor_event.capex_old_high_usd_bn",
        "anchor_event.capex_new_low_usd_bn",
        "anchor_event.capex_new_high_usd_bn",
        "anchor_event.capex_midpoint_hike_pct",
        "anchor_event.q3_gross_margin_guide_low_pct",
        "anchor_event.q3_gross_margin_guide_high_pct",
        "q1_anchor_or_known.question",
        "q1_anchor_or_known.spy_sample_days",
        "q1_anchor_or_known.ratio_squared_return",
        "q2_premium_paid.question",
        "q2_premium_paid.iv_expiry_0717_pct",
        "q2_premium_paid.earnings_bump_pp",
        "q2_premium_paid.implied_single_day_move_pct",
        "q2_premium_paid.realized_vol_20d_pct",
        "q3_beat_size.same_day.binary_flag_t",
        "q3_beat_size.same_day.binary_flag_p",
        "q3_beat_size.same_day.surprise_size_t",
        "q3_beat_size.same_day.surprise_size_p",
        "q3_beat_size.same_day.aic_gap",
        "q3_beat_size.same_day.n_obs",
        "q3_beat_size.same_day.n_earnings_events",
        "q3_beat_size.same_day.n_stocks",
        "q3_beat_size.next_month.coef",
        "q3_beat_size.next_month.annualized_vol_impact_pp",
        "q3_beat_size.next_month.n_firm_months",
        "q3_beat_size.next_month.n_firms",
        "q3_beat_size.next_month.n_months",
        "q3_beat_size.visible_features.n_firms",
        "q3_beat_size.visible_features.n_indicators",
        "q3_beat_size.visible_features.n_hypotheses",
        "q3_beat_size.visible_features.n_passed",
        "q3_beat_size.visible_features.min_bh_adjusted_p",
        "q3_beat_size.visible_features.cv_r2",
        "q3_beat_size.visible_features.tier_a_count",
        "q4_t_plus_5.question",
        "q4_t_plus_5.us_event_study.n_earnings_per_firm",
        "q4_t_plus_5.us_event_study.msft_post5_diff_pct",
        "q4_t_plus_5.us_event_study.msft_post5_bonferroni_p",
        "q4_t_plus_5.tsmc_event_profile.n_calls",
        "q4_t_plus_5.tsmc_event_profile.normal_day_abs_move_pct",
        "q4_t_plus_5.tsmc_event_profile.reaction_day_abs_move_pct",
        "q4_t_plus_5.tsmc_event_profile.reaction_day_multiple",
        "q4_t_plus_5.tsmc_event_profile.post5d_abs_move_pct",
    ]
    for path in paths:
        require(e, path)


def main() -> None:
    evidence, _article = load_inputs()
    validate_required_fields(evidence)
    os.makedirs(OUT_DIR, exist_ok=True)
    render_panel_1(evidence)
    render_panel_2(evidence)
    render_panel_3(evidence)
    render_panel_4(evidence)


if __name__ == "__main__":
    main()
