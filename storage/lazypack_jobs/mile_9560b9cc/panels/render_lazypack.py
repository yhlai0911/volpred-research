#!/usr/bin/env python3
"""Render the CPI event-date audit lazypack as three data-bound PNG panels.

Every displayed date and statistic is loaded from the evidence JSON.  The
article Markdown is also loaded as part of the evidence package, but it is used
only as non-numeric context.  Missing or malformed inputs deliberately raise so
the caller receives a traceback instead of a plausible-looking false graphic.
"""

from __future__ import annotations

import json
import os
import re
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch, Rectangle


EVIDENCE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/event_articles/"
    "us_cpi_2026_07_14_t2/evidence.json"
)
ARTICLE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_9560b9cc/panels/mile_9560b9cc_article.md"
)
out_dir = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_9560b9cc/panels"
)

WIDTH = 1600
HEIGHT = 1000
DPI = 150

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False


# Restrained, high-contrast palette shared by all panels.
NAVY = "#10283F"
NAVY_2 = "#173B57"
INK = "#17212B"
MUTED = "#5B6875"
FAINT = "#8A96A3"
LINE = "#D8E0E7"
PAPER = "#FFFFFF"
COOL_BG = "#F4F7FA"
WARM_BG = "#FBF8F3"
TEAL = "#0E7C7B"
TEAL_LIGHT = "#DDF1EF"
RED = "#B33A3A"
RED_LIGHT = "#F7E7E4"
AMBER = "#C97924"
SLATE = "#8293A3"


def require(data: Any, dotted_path: str) -> Any:
    """Return a required dotted-path value or raise with the full field path."""

    current = data
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise KeyError(f"缺少 evidence 欄位：{dotted_path}")
        current = current[part]
    if current is None:
        raise ValueError(f"evidence 欄位不可為 null：{dotted_path}")
    return current


def require_number(data: Any, dotted_path: str) -> float:
    value = require(data, dotted_path)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"evidence 欄位必須是數字：{dotted_path}")
    return float(value)


def require_int(data: Any, dotted_path: str) -> int:
    value = require(data, dotted_path)
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"evidence 欄位必須是整數：{dotted_path}")
    return value


def require_text(data: Any, dotted_path: str) -> str:
    value = require(data, dotted_path)
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"evidence 欄位必須是非空字串：{dotted_path}")
    return value.strip()


def require_list(data: Any, dotted_path: str) -> list[Any]:
    value = require(data, dotted_path)
    if not isinstance(value, list):
        raise TypeError(f"evidence 欄位必須是陣列：{dotted_path}")
    return value


def quantize_2(value: float) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def signed_pct(value: float) -> str:
    rounded = quantize_2(value)
    if rounded > 0:
        sign = "+"
    elif rounded < 0:
        sign = "−"
    else:
        sign = ""
    return f"{sign}{abs(rounded):.2f}%"


def p_value(value: float) -> str:
    return f"{quantize_2(value):.2f}"


def load_inputs() -> tuple[dict[str, Any], str]:
    with EVIDENCE_PATH.open("r", encoding="utf-8") as handle:
        evidence = json.load(handle)
    if not isinstance(evidence, dict):
        raise TypeError("evidence.json 最外層必須是物件")

    article_text = ARTICLE_PATH.read_text(encoding="utf-8")
    if not article_text.strip():
        raise ValueError("文章 Markdown 不可為空")
    if not article_text.lstrip().startswith("# "):
        raise ValueError("文章 Markdown 缺少一級標題")

    return evidence, article_text


def extract_bindings(evidence: dict[str, Any]) -> dict[str, Any]:
    """Resolve and cross-check every evidence field used by the posters."""

    event = require_text(evidence, "event")
    event_date_match = re.search(r"\b\d{4}-\d{2}-\d{2}\b", event)
    event_time_match = re.search(r"\b\d{2}:\d{2}\s+ET\b", event)
    if event_date_match is None or event_time_match is None:
        raise ValueError("event 欄位缺少可辨識的發布日期或美東時間")

    event_date_source = require_text(evidence, "event_date_source")
    source_match = re.fullmatch(
        r"BLS schedule \+ ALFRED release_id=(\d+)", event_date_source
    )
    if source_match is None:
        raise ValueError("event_date_source 格式與預期的 BLS／ALFRED 出處不符")
    source_display = (
        "BLS 官方發布時程表＋ALFRED release_id=" + source_match.group(1)
    )

    price_source = require_text(evidence, "price_source")
    price_match = re.fullmatch(
        r"yfinance (.+), auto_adjust=(True|False)", price_source
    )
    if price_match is None:
        raise ValueError("price_source 格式與預期的 yfinance 出處不符")
    price_display = (
        "yfinance "
        + price_match.group(1).replace(" / ", "／")
        + f"（auto_adjust={price_match.group(2)}）"
    )

    n_legacy = require_int(evidence, "date_error_audit.n_legacy")
    n_wrong = require_int(evidence, "date_error_audit.n_wrong")
    legacy_dates = require_list(evidence, "date_error_audit.legacy_dates")
    wrong_dates = require_list(evidence, "date_error_audit.wrong_dates")
    phantom_dates = require_list(
        evidence, "date_error_audit.phantom_dates_no_cpi_published"
    )
    if len(legacy_dates) != n_legacy:
        raise ValueError("n_legacy 與 legacy_dates 長度不一致")
    if len(wrong_dates) != n_wrong:
        raise ValueError("n_wrong 與 wrong_dates 長度不一致")
    if not 0 <= n_wrong <= n_legacy:
        raise ValueError("n_wrong 必須介於零與 n_legacy 之間")
    if len(phantom_dates) != 1 or not isinstance(phantom_dates[0], str):
        raise ValueError("phantom_dates_no_cpi_published 必須恰有一個日期")
    phantom_date = phantom_dates[0]
    if phantom_date not in wrong_dates or phantom_date not in legacy_dates:
        raise ValueError("不存在的 CPI 日期未同時列入 legacy_dates 與 wrong_dates")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", phantom_date) is None:
        raise ValueError("不存在的 CPI 日期格式不是 YYYY-MM-DD")

    root_cause = require_text(evidence, "date_error_audit.root_cause")
    proxy_day_match = re.search(
        r"'(\d+)(?:st|nd|rd|th) of month'", root_cause
    )
    if proxy_day_match is None:
        raise ValueError("root_cause 缺少固定日代理值")
    proxy_day = proxy_day_match.group(1)

    legacy_mean = require_number(
        evidence, "reaction_legacy_dates.vix_pct_change_on_cpi_day.mean"
    )
    official_mean = require_number(
        evidence, "reaction_official_dates.vix_pct_change_on_cpi_day.mean"
    )
    legacy_p = require_number(evidence, "reaction_legacy_dates.vix_welch_p")
    official_p = require_number(evidence, "reaction_official_dates.vix_welch_p")
    legacy_n = require_int(evidence, "reaction_legacy_dates.n_event_days")
    official_n = require_int(evidence, "reaction_official_dates.n_event_days")
    if legacy_n != official_n or legacy_n != n_legacy:
        raise ValueError("兩版事件日樣本數與日期稽核筆數不一致")
    if not 0.0 <= legacy_p <= 1.0 or not 0.0 <= official_p <= 1.0:
        raise ValueError("Welch p 值必須介於零與一之間")

    return {
        "event_date": event_date_match.group(0),
        "event_time": event_time_match.group(0),
        "event_source": source_display,
        "price_source": price_display,
        "footer_source": f"{source_display}；{price_display}",
        "n_legacy": n_legacy,
        "n_wrong": n_wrong,
        "n_correct": n_legacy - n_wrong,
        "phantom_date": phantom_date,
        "proxy_day": proxy_day,
        "legacy_mean": legacy_mean,
        "official_mean": official_mean,
        "legacy_p": legacy_p,
        "official_p": official_p,
        "n_event_days": legacy_n,
    }


def canvas(background: str) -> tuple[Figure, Axes]:
    fig = plt.figure(
        figsize=(WIDTH / DPI, HEIGHT / DPI), dpi=DPI, facecolor=background
    )
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_xlim(0, WIDTH)
    ax.set_ylim(HEIGHT, 0)
    ax.set_facecolor(background)
    ax.axis("off")
    return fig, ax


def text(
    ax: Axes,
    x: float,
    y: float,
    value: str,
    size: float,
    color: str = INK,
    weight: str = "normal",
    ha: str = "left",
    va: str = "top",
    linespacing: float = 1.16,
    zorder: int = 5,
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
        zorder=zorder,
        clip_on=False,
    )


def rounded_box(
    ax: Axes,
    x: float,
    y: float,
    width: float,
    height: float,
    face: str,
    edge: str = "none",
    linewidth: float = 1.5,
    radius: float = 22,
    zorder: int = 1,
) -> None:
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            width,
            height,
            boxstyle=f"round,pad=0,rounding_size={radius}",
            facecolor=face,
            edgecolor=edge,
            linewidth=linewidth,
            zorder=zorder,
        )
    )


def draw_x(ax: Axes, cx: float, cy: float, size: float, color: str, lw: float) -> None:
    ax.plot(
        (cx - size, cx + size),
        (cy - size, cy + size),
        color=color,
        linewidth=lw,
        solid_capstyle="round",
        zorder=6,
    )
    ax.plot(
        (cx - size, cx + size),
        (cy + size, cy - size),
        color=color,
        linewidth=lw,
        solid_capstyle="round",
        zorder=6,
    )


def draw_check(
    ax: Axes, cx: float, cy: float, size: float, color: str, lw: float
) -> None:
    ax.plot(
        (cx - size, cx - size * 0.2, cx + size),
        (cy, cy + size * 0.72, cy - size * 0.72),
        color=color,
        linewidth=lw,
        solid_capstyle="round",
        solid_joinstyle="round",
        zorder=6,
    )


def draw_calendar(ax: Axes, x: float, y: float, width: float, height: float) -> None:
    rounded_box(ax, x, y, width, height, PAPER, edge=LINE, linewidth=2, radius=14)
    ax.add_patch(
        Rectangle((x, y), width, height * 0.28, facecolor=TEAL, edgecolor="none", zorder=3)
    )
    for ring_x in (x + width * 0.28, x + width * 0.72):
        ax.plot(
            (ring_x, ring_x),
            (y - 7, y + 15),
            color=NAVY,
            linewidth=5,
            solid_capstyle="round",
            zorder=5,
        )
    dot_y = y + height * 0.52
    for row in range(2):
        for col in range(3):
            ax.add_patch(
                Circle(
                    (x + 24 + col * 23, dot_y + row * 23),
                    radius=4,
                    facecolor=SLATE,
                    edgecolor="none",
                    zorder=4,
                )
            )


def add_footer(ax: Axes, source: str) -> None:
    ax.plot((75, 1525), (930, 930), color=LINE, linewidth=1.4, zorder=2)
    text(
        ax,
        75,
        959,
        f"資料來源：{source}",
        11.5,
        color=FAINT,
        va="center",
    )


def save_panel(fig: Figure, filename: str) -> None:
    target = out_dir / filename
    fig.savefig(
        target,
        dpi=DPI,
        facecolor=fig.get_facecolor(),
        edgecolor="none",
        bbox_inches=None,
        pad_inches=0,
        metadata={"Software": "VolPred data-bound matplotlib renderer"},
    )
    plt.close(fig)


def render_concept(values: dict[str, Any]) -> None:
    fig, ax = canvas(PAPER)

    ax.add_patch(Rectangle((0, 0), WIDTH, 170, facecolor=NAVY, edgecolor="none"))
    ax.add_patch(Rectangle((75, 32), 92, 7, facecolor=TEAL, edgecolor="none"))
    text(ax, 75, 48, "VolPred｜CPI 事件研究懶人包", 14, color="#C9D7E3")
    text(
        ax,
        75,
        82,
        "事件日期是資料，必須有出處",
        34,
        color=PAPER,
        weight="bold",
    )

    rounded_box(ax, 75, 210, 1450, 190, COOL_BG, edge=LINE, linewidth=1.5)
    draw_calendar(ax, 110, 251, 92, 96)
    text(ax, 235, 236, "本次 CPI 官方發布日", 15, color=MUTED, weight="bold")
    text(ax, 235, 278, values["event_date"], 31, color=NAVY, weight="bold")
    ax.plot((825, 825), (238, 352), color=LINE, linewidth=2)
    text(ax, 875, 236, "美東發布時間", 15, color=MUTED, weight="bold")
    text(ax, 875, 278, values["event_time"], 31, color=TEAL, weight="bold")
    text(
        ax,
        235,
        370,
        f"可追溯出處：{values['event_source']}",
        12.5,
        color=FAINT,
        va="center",
    )

    rounded_box(ax, 75, 430, 600, 345, RED_LIGHT, edge="#EBCBC5", linewidth=1.4)
    ax.add_patch(Circle((175, 535), 58, facecolor=PAPER, edgecolor="#E7BEB7", linewidth=2))
    draw_x(ax, 175, 535, 24, RED, 7)
    text(ax, 270, 462, "錯誤方法", 15, color=RED, weight="bold")
    text(ax, 270, 505, "用固定日曆\n猜發布日", 27, color=INK, weight="bold")
    text(
        ax,
        270,
        655,
        f"每月 {values['proxy_day']} 日代理值\n沒有官方出處",
        17,
        color=MUTED,
    )

    rounded_box(ax, 925, 430, 600, 345, TEAL_LIGHT, edge="#B9DCD8", linewidth=1.4)
    ax.add_patch(Circle((1025, 535), 58, facecolor=PAPER, edgecolor="#A8D5D0", linewidth=2))
    draw_check(ax, 1025, 535, 27, TEAL, 7)
    text(ax, 1120, 462, "正確方法", 15, color=TEAL, weight="bold")
    text(ax, 1120, 505, "先讀官方\n發布時程", 27, color=INK, weight="bold")
    text(
        ax,
        1120,
        655,
        "BLS＋ALFRED\n每個事件日都可追溯",
        17,
        color=MUTED,
    )

    ax.add_patch(
        FancyArrowPatch(
            (705, 602),
            (895, 602),
            arrowstyle="-|>",
            mutation_scale=34,
            linewidth=3,
            color=SLATE,
            zorder=5,
        )
    )
    text(ax, 800, 553, "修正", 14, color=MUTED, weight="bold", ha="center")

    rounded_box(ax, 75, 815, 1450, 80, NAVY_2, radius=16)
    text(
        ax,
        800,
        855,
        "先驗證事件日，再計算市場反應。",
        22,
        color=PAPER,
        weight="bold",
        ha="center",
        va="center",
    )

    add_footer(ax, values["footer_source"])
    save_panel(fig, "1_concept.png")


def render_method(values: dict[str, Any]) -> None:
    fig, ax = canvas(WARM_BG)

    ax.add_patch(Rectangle((75, 42), 72, 7, facecolor=RED, edgecolor="none"))
    text(ax, 75, 59, "CPI 發布日稽核", 14, color=RED, weight="bold")
    text(
        ax,
        75,
        92,
        f"{values['n_legacy']} 個日期，錯了 {values['n_wrong']} 個",
        38,
        color=NAVY,
        weight="bold",
    )
    text(
        ax,
        75,
        166,
        "浮動的官方發布時程，不能用固定日期代理。",
        18,
        color=MUTED,
    )
    ax.plot((75, 1525), (213, 213), color="#DDD5CA", linewidth=1.5)

    rounded_box(ax, 75, 240, 865, 550, PAPER, edge="#E6DED4", linewidth=1.4)
    text(ax, 115, 276, "日期稽核結果", 14, color=MUTED, weight="bold")
    text(
        ax,
        115,
        318,
        f"{values['n_wrong']} / {values['n_legacy']}",
        62,
        color=RED,
        weight="bold",
    )
    text(ax, 115, 455, "個發布日對不上官方時程", 19, color=INK, weight="bold")

    tile_x = 115
    tile_y = 530
    tile_w = 95
    tile_h = 55
    tile_gap_x = 20
    tile_gap_y = 22
    for index in range(values["n_legacy"]):
        row = index // 7
        col = index % 7
        x = tile_x + col * (tile_w + tile_gap_x)
        y = tile_y + row * (tile_h + tile_gap_y)
        is_wrong = index < values["n_wrong"]
        fill = RED_LIGHT if is_wrong else "#E8EEF2"
        edge = "#E2B7AF" if is_wrong else "#C8D4DD"
        rounded_box(ax, x, y, tile_w, tile_h, fill, edge=edge, linewidth=1.2, radius=10)
        if is_wrong:
            draw_x(ax, x + tile_w / 2, y + tile_h / 2, 11, RED, 4)
        else:
            draw_check(ax, x + tile_w / 2, y + tile_h / 2, 12, NAVY_2, 4)

    ax.add_patch(Rectangle((115, 703), 24, 10, facecolor=RED_LIGHT, edgecolor="#E2B7AF"))
    text(ax, 151, 708, "錯誤日期", 13, color=MUTED, va="center")
    ax.add_patch(Rectangle((282, 703), 24, 10, facecolor="#E8EEF2", edgecolor="#C8D4DD"))
    text(ax, 318, 708, "對上官方", 13, color=MUTED, va="center")

    rounded_box(ax, 990, 240, 535, 550, NAVY, radius=22)
    ax.add_patch(Rectangle((1030, 276), 78, 7, facecolor=AMBER, edgecolor="none"))
    text(ax, 1030, 304, "不存在的事件日", 15, color="#D7E0E8", weight="bold")
    text(
        ax,
        1030,
        350,
        values["phantom_date"],
        36,
        color=PAPER,
        weight="bold",
    )
    ax.plot((1030, 1485), (435, 435), color="#3A5267", linewidth=1.5)
    text(
        ax,
        1030,
        474,
        "這天根本沒有\nCPI 發布",
        27,
        color="#FFD7A7",
        weight="bold",
    )
    text(
        ax,
        1030,
        620,
        "卻被舊日期表列為事件日，\n普通交易日因此混進事件樣本。",
        17,
        color="#D7E0E8",
        linespacing=1.28,
    )

    rounded_box(ax, 75, 825, 1450, 70, "#F1E9DF", edge="#E2D5C7", linewidth=1.2, radius=14)
    ax.add_patch(Rectangle((75, 825), 14, 70, facecolor=RED, edgecolor="none"))
    text(
        ax,
        115,
        860,
        f"根因：排程腳本用「每月 {values['proxy_day']} 日」代理 BLS 官方發布日。",
        17,
        color=INK,
        weight="bold",
        va="center",
    )

    add_footer(ax, values["footer_source"])
    save_panel(fig, "2_method.png")


def render_results(values: dict[str, Any]) -> None:
    fig, ax = canvas(COOL_BG)

    ax.add_patch(Rectangle((75, 42), 72, 7, facecolor=TEAL, edgecolor="none"))
    text(ax, 75, 59, "CPI 事件研究｜日期修正後", 14, color=TEAL, weight="bold")
    text(
        ax,
        75,
        92,
        "方向翻轉，但證據仍然不顯著",
        37,
        color=NAVY,
        weight="bold",
    )
    text(
        ax,
        75,
        166,
        "更正日期移除了假象，沒有建立新的方向結論。",
        18,
        color=MUTED,
    )
    ax.plot((75, 1525), (213, 213), color=LINE, linewidth=1.5)

    rounded_box(ax, 75, 245, 940, 290, PAPER, edge=LINE, linewidth=1.4)
    text(ax, 115, 278, "CPI 當天 VIX 平均變動", 16, color=MUTED, weight="bold")

    text(ax, 125, 333, "舊日期", 14, color=FAINT, weight="bold")
    text(
        ax,
        125,
        370,
        signed_pct(values["legacy_mean"]),
        40,
        color=RED,
        weight="bold",
    )
    text(ax, 700, 333, "官方日期", 14, color=FAINT, weight="bold")
    text(
        ax,
        700,
        370,
        signed_pct(values["official_mean"]),
        40,
        color=TEAL,
        weight="bold",
    )
    ax.add_patch(
        FancyArrowPatch(
            (485, 419),
            (655, 419),
            arrowstyle="-|>",
            mutation_scale=32,
            linewidth=3,
            color=SLATE,
            zorder=5,
        )
    )
    text(ax, 115, 505, "同一分析，只更換發布日。", 13, color=FAINT, va="center")

    rounded_box(ax, 1055, 245, 470, 135, PAPER, edge=LINE, linewidth=1.4)
    text(ax, 1090, 274, "舊日期 Welch 檢定", 13, color=MUTED, weight="bold")
    text(
        ax,
        1090,
        318,
        f"p={p_value(values['legacy_p'])}",
        28,
        color=NAVY,
        weight="bold",
    )
    rounded_box(ax, 1360, 288, 125, 43, RED_LIGHT, radius=21)
    text(ax, 1422.5, 310, "不顯著", 13, color=RED, weight="bold", ha="center", va="center")

    rounded_box(ax, 1055, 400, 470, 135, PAPER, edge=LINE, linewidth=1.4)
    text(ax, 1090, 429, "官方日期 Welch 檢定", 13, color=MUTED, weight="bold")
    text(
        ax,
        1090,
        473,
        f"p={p_value(values['official_p'])}",
        28,
        color=NAVY,
        weight="bold",
    )
    rounded_box(ax, 1360, 443, 125, 43, TEAL_LIGHT, radius=21)
    text(ax, 1422.5, 465, "不顯著", 13, color=TEAL, weight="bold", ha="center", va="center")

    rounded_box(ax, 75, 575, 1450, 310, NAVY, radius=24)
    text(ax, 115, 613, "誠實的結論", 15, color="#AFC1D0", weight="bold")
    text(ax, 115, 656, "沒有方向性", 42, color=PAPER, weight="bold")
    text(
        ax,
        115,
        760,
        "舊版的上漲與新版的下跌，\n都不足以證明 CPI 日固定往哪個方向走。",
        19,
        color="#D7E0E8",
        linespacing=1.25,
    )
    ax.plot((1000, 1000), (615, 845), color="#3A5267", linewidth=1.5)
    text(ax, 1060, 620, "兩版 Welch p 值", 14, color="#AFC1D0", weight="bold")
    text(
        ax,
        1060,
        668,
        f"{p_value(values['legacy_p'])} ／ {p_value(values['official_p'])}",
        30,
        color="#FFD7A7",
        weight="bold",
    )
    text(ax, 1060, 744, "都不顯著", 22, color=PAPER, weight="bold")
    text(
        ax,
        1060,
        804,
        f"兩版各 {values['n_event_days']} 個事件日",
        15,
        color="#AFC1D0",
    )

    add_footer(ax, values["footer_source"])
    save_panel(fig, "3_results.png")


def main() -> None:
    os.makedirs(out_dir, exist_ok=True)
    evidence, _article_text = load_inputs()
    values = extract_bindings(evidence)
    render_concept(values)
    render_method(values)
    render_results(values)


if __name__ == "__main__":
    main()
