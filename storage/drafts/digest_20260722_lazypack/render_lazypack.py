#!/usr/bin/env python3
"""Render the three data-bound PNG panels for the 2026-07-22 VolPred digest.

All displayed statistics are loaded from the evidence JSON files below.  The
article body is also loaded and checked for the narrative anchors used by the
panels.  Missing evidence fails loudly instead of producing a partial graphic.
"""

from __future__ import annotations

import json
import math
import os
import textwrap
from pathlib import Path
from typing import Any, Iterable, Sequence

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyBboxPatch


plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False

WIDTH_PX = 1600
HEIGHT_PX = 1000
DPI = 150
FIGSIZE = (WIDTH_PX / DPI, HEIGHT_PX / DPI)

K492_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k492/"
    "k492_research_efficiency_results.json"
)
K812V2_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k812v2/"
    "k812v2_us_taiwan_leadlag_otc_results.json"
)
K1109_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1109/k1109_results.json"
)
K1056_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1056/k1056_results.json"
)
BODY_PATH = Path("/tmp/digest31_body.md")

out_dir = "/Users/yhlai0911/volpred-research/storage/drafts/digest_20260722_lazypack"

SOURCE_LABELS = {
    "k492": "K492 研究效率回顧（68 個實驗分類與跨樣本期存活統計）",
    "k812v2": "K812v2 美股對台股領先落後策略（昨收到今收 vs 今開到今收）",
    "k1109": "K1109 預先登錄隨機產業樣本（對照 K1106b 事後挑樣）",
    "k1056": "K1056 A4f 波動率模型跨五個市場時代穩健性驗證",
}

INK = "#17212B"
MUTED = "#5E6875"
FAINT = "#7D8794"
PAPER = "#F7F5F0"
WHITE = "#FFFFFF"
LINE = "#DDE2E7"
NAVY = "#183B56"
BLUE = "#2C6E9B"
BLUE_SOFT = "#E7F0F6"
TEAL = "#177C78"
TEAL_SOFT = "#E2F1EF"
RED = "#B8483E"
RED_SOFT = "#F7E8E5"
AMBER = "#AA711C"
AMBER_SOFT = "#F6EEDC"
PURPLE = "#6A5A91"
PURPLE_SOFT = "#EEEAF5"
GREEN = "#39795B"
GREEN_SOFT = "#E6F0E9"


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise TypeError(f"Expected a JSON object in {path}")
    return value


def load_body(path: Path) -> str:
    body = path.read_text(encoding="utf-8")
    required_anchors = (
        "一次只換一個零件",
        "17 個候選只活 8 個",
        "今開到今收",
        "五段全勝",
    )
    for anchor in required_anchors:
        if anchor not in body:
            raise KeyError(f"Article body is missing required anchor: {anchor}")
    return body


def resolve(data: Any, path: str) -> Any:
    """Resolve either a dot path or an RFC 6901-style JSON Pointer."""
    if path.startswith("/"):
        parts = [part.replace("~1", "/").replace("~0", "~") for part in path[1:].split("/")]
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
            raise KeyError(f"Missing evidence field: {path}")
    return current


def numeric(data: dict[str, Any], path: str) -> float:
    value = resolve(data, path)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"Expected numeric evidence at {path}, got {type(value).__name__}")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"Expected finite evidence at {path}, got {number}")
    return number


def format_value(
    data: dict[str, Any],
    path: str,
    *,
    kind: str,
    digits: int = 0,
    suffix: str = "",
) -> str:
    value = numeric(data, path)
    if kind == "integer":
        if not value.is_integer():
            raise ValueError(f"Expected integer evidence at {path}, got {value}")
        return f"{int(value):,}{suffix}"
    if kind == "number":
        return f"{value:,.{digits}f}{suffix}"
    if kind == "percent":
        return f"{value * 100:,.{digits}f}%{suffix}"
    raise ValueError(f"Unknown format kind: {kind}")


def zh_wrap(text: str, width: int) -> str:
    """Character-aware wrapping suitable for Chinese display text."""
    lines: list[str] = []
    for paragraph in text.splitlines() or [""]:
        wrapped = textwrap.wrap(
            paragraph,
            width=width,
            break_long_words=True,
            break_on_hyphens=False,
            replace_whitespace=False,
            drop_whitespace=True,
        )
        lines.extend(wrapped or [""])
    return "\n".join(lines)


def new_canvas() -> tuple[plt.Figure, plt.Axes]:
    fig = plt.figure(figsize=FIGSIZE, dpi=DPI, facecolor=PAPER)
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    return fig, ax


def rounded_box(
    ax: plt.Axes,
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    facecolor: str = WHITE,
    edgecolor: str = LINE,
    linewidth: float = 1.0,
    radius: float = 0.018,
    zorder: int = 1,
) -> None:
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            width,
            height,
            boxstyle=f"round,pad=0.006,rounding_size={radius}",
            facecolor=facecolor,
            edgecolor=edgecolor,
            linewidth=linewidth,
            transform=ax.transAxes,
            zorder=zorder,
        )
    )


def add_header(ax: plt.Axes, title: str, subtitle: str, accent: str) -> None:
    ax.add_patch(
        FancyBboxPatch(
            (0.055, 0.935),
            0.072,
            0.009,
            boxstyle="round,pad=0,rounding_size=0.004",
            facecolor=accent,
            edgecolor="none",
            transform=ax.transAxes,
        )
    )
    ax.text(
        0.055,
        0.908,
        title,
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=25,
        fontweight="bold",
        color=INK,
    )
    ax.text(
        0.055,
        0.842,
        subtitle,
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=10.5,
        color=MUTED,
    )
    ax.text(
        0.945,
        0.925,
        "VolPred｜一般讀者圖解",
        transform=ax.transAxes,
        ha="right",
        va="top",
        fontsize=8.5,
        color=FAINT,
    )


def add_footer(ax: plt.Axes, source_keys: Sequence[str]) -> None:
    labels = []
    for key in source_keys:
        if key not in SOURCE_LABELS:
            raise KeyError(f"Missing strict-plan source label: {key}")
        labels.append(SOURCE_LABELS[key])

    ax.plot((0.055, 0.945), (0.105, 0.105), color=LINE, linewidth=0.8, transform=ax.transAxes)
    source_text = "資料來源：" + "\n".join(labels)
    ax.text(
        0.055,
        0.088,
        source_text,
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=6.6 if len(labels) > 1 else 7.4,
        linespacing=1.22,
        color=FAINT,
    )


def add_metric_card(
    ax: plt.Axes,
    box: tuple[float, float, float, float],
    *,
    label: str,
    value: str,
    note: str,
    accent: str,
    soft: str,
    label_width: int = 13,
    note_width: int = 16,
) -> None:
    x, y, width, height = box
    rounded_box(ax, x, y, width, height, facecolor=WHITE)
    ax.add_patch(
        FancyBboxPatch(
            (x + 0.012, y + height - 0.018),
            width - 0.024,
            0.007,
            boxstyle="round,pad=0,rounding_size=0.003",
            facecolor=accent,
            edgecolor="none",
            transform=ax.transAxes,
            zorder=2,
        )
    )
    ax.text(
        x + 0.017,
        y + height - 0.040,
        zh_wrap(label, label_width),
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=9.4,
        fontweight="bold",
        linespacing=1.13,
        color=accent,
        zorder=3,
    )
    ax.text(
        x + 0.017,
        y + height * 0.50,
        value,
        transform=ax.transAxes,
        ha="left",
        va="center",
        fontsize=22,
        fontweight="bold",
        color=INK,
        zorder=3,
    )
    ax.text(
        x + 0.017,
        y + 0.025,
        zh_wrap(note, note_width),
        transform=ax.transAxes,
        ha="left",
        va="bottom",
        fontsize=7.6,
        linespacing=1.22,
        color=MUTED,
        zorder=3,
    )
    ax.add_patch(
        Circle(
            (x + width - 0.027, y + 0.033),
            0.010,
            transform=ax.transAxes,
            facecolor=soft,
            edgecolor="none",
            zorder=2,
        )
    )


def save_panel(fig: plt.Figure, filename: str, *, title: str, alt: str) -> None:
    output = Path(out_dir) / filename
    fig.savefig(
        output,
        dpi=DPI,
        facecolor=PAPER,
        edgecolor="none",
        metadata={"Title": title, "Description": alt},
    )
    plt.close(fig)


def render_framework() -> None:
    title = "換件測試：一次只換一個零件"
    alt = "懶人包：換件測試框架，逐一替換資料來源、樣本期、下單時點、報酬口徑、量尺、估計窗口與樣本名單"
    fig, ax = new_canvas()
    add_header(ax, title, "把設定拆開、逐一替換；其餘條件保持不動，再看績效表是否還成立。", RED)

    rounded_box(ax, 0.055, 0.555, 0.89, 0.245, facecolor=WHITE)
    ax.text(
        0.078,
        0.764,
        "怎麼用",
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=15,
        fontweight="bold",
        color=RED,
    )
    how_to = (
        "修車廠診斷引擎抖動，一次只換一個零件，換完發動看看還抖不抖。回測報告可以照做。\n\n"
        "任何績效表背後都掛著一串看不見的設定。一次換掉其中一件、其餘不動，看那張表還活不活。"
    )
    ax.text(
        0.078,
        0.720,
        zh_wrap(how_to, 33),
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=9.1,
        linespacing=1.34,
        color=MUTED,
    )

    center_x, center_y = 0.723, 0.672
    rounded_box(ax, center_x - 0.068, center_y - 0.035, 0.136, 0.070, facecolor=RED_SOFT, edgecolor=RED)
    ax.text(
        center_x,
        center_y,
        "績效表",
        transform=ax.transAxes,
        ha="center",
        va="center",
        fontsize=12.5,
        fontweight="bold",
        color=RED,
        zorder=4,
    )
    part_positions = (
        ("資料來源", 0.540, 0.738),
        ("樣本期", 0.655, 0.754),
        ("下單時點", 0.790, 0.754),
        ("報酬口徑", 0.875, 0.698),
        ("量尺", 0.820, 0.590),
        ("估計窗口", 0.680, 0.585),
        ("樣本名單", 0.548, 0.620),
    )
    for label, x, y in part_positions:
        ax.plot((center_x, x), (center_y, y), color=LINE, linewidth=1.1, transform=ax.transAxes, zorder=1)
        rounded_box(ax, x - 0.043, y - 0.022, 0.086, 0.044, facecolor=PAPER, edgecolor=LINE, radius=0.012, zorder=2)
        ax.text(
            x,
            y,
            label,
            transform=ax.transAxes,
            ha="center",
            va="center",
            fontsize=7.8,
            fontweight="bold",
            color=NAVY,
            zorder=3,
        )

    blocks = (
        (
            "換資料來源與樣本期",
            (
                "把行情拿去跟交易所原始紀錄交叉核對，確認那天市場真的有交易。",
                "參數鎖死，換一段完全不同的歷史重跑一次。",
            ),
            TEAL,
            TEAL_SOFT,
        ),
        (
            "換下單時點與報酬口徑",
            (
                "訊號改成隔一天才能下單，看優勢還在不在。",
                "報酬只認你進場後那一段，進場前的跳空不算你的。",
            ),
            BLUE,
            BLUE_SOFT,
        ),
        (
            "換量尺、窗口與名單",
            (
                "換一把更精準的波動量尺，換兩個指標重排名次。",
                "參數估計期間乘以零點五倍與兩倍各跑一次；標的名單要事前鎖死，不能事後挑。",
            ),
            PURPLE,
            PURPLE_SOFT,
        ),
    )
    card_xs = (0.055, 0.356, 0.657)
    for x, (heading, paragraphs, accent, soft) in zip(card_xs, blocks, strict=True):
        rounded_box(ax, x, 0.155, 0.288, 0.345, facecolor=WHITE)
        ax.add_patch(
            Circle((x + 0.030, 0.457), 0.013, transform=ax.transAxes, facecolor=soft, edgecolor=accent, linewidth=1.0)
        )
        ax.text(
            x + 0.052,
            0.466,
            heading,
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=11.2,
            fontweight="bold",
            color=accent,
        )
        y = 0.405
        for paragraph in paragraphs:
            ax.text(
                x + 0.024,
                y,
                "— " + zh_wrap(paragraph, 20),
                transform=ax.transAxes,
                ha="left",
                va="top",
                fontsize=8.8,
                linespacing=1.32,
                color=MUTED,
            )
            y -= 0.105 if len(paragraph) < 31 else 0.132

    add_footer(ax, ("k492",))
    save_panel(fig, "1_framework.png", title=title, alt=alt)


def render_results(evidence: dict[str, dict[str, Any]]) -> None:
    title = "我們自己換件時，數字掉了多少"
    alt = "懶人包：跨樣本期存活率、報酬口徑差異、事後挑樣與預先登錄的統計強度落差"
    k492 = evidence["k492"]
    k812v2 = evidence["k812v2"]
    k1109 = evidence["k1109"]

    cards = (
        (
            "換樣本期後陣亡率",
            format_value(k492, "cross_oos_analysis.failure_rate_pct", kind="number", digits=1, suffix="%"),
            "單期看起來有效的候選，換一段歷史重測",
            RED,
            RED_SOFT,
        ),
        (
            "換期後存活數",
            format_value(k492, "cross_oos_analysis.n_survived", kind="integer", suffix=" 個"),
            "對照陣亡數，擲硬幣的存活率是五成",
            TEAL,
            TEAL_SOFT,
        ),
        (
            "換期後陣亡數",
            format_value(k492, "cross_oos_analysis.n_failed", kind="integer", suffix=" 個"),
            "每一個在第一段樣本期都很漂亮",
            RED,
            RED_SOFT,
        ),
        (
            "昨收到今收的評分",
            format_value(k812v2, "otc_vs_c2c_sharpe.s4.c2c_sharpe", kind="number", digits=3),
            "含進場前的隔夜跳空，你吃不到",
            AMBER,
            AMBER_SOFT,
        ),
        (
            "今開到今收的評分",
            format_value(k812v2, "otc_vs_c2c_sharpe.s4.otc_sharpe", kind="number", digits=3),
            "只算可交易的那一段，優勢消失",
            BLUE,
            BLUE_SOFT,
        ),
        (
            "可交易口徑的方向準確度",
            format_value(k812v2, "direction_accuracy.otc.overall", kind="percent", digits=1),
            "等同擲硬幣",
            BLUE,
            BLUE_SOFT,
        ),
        (
            "事後挑樣的統計強度",
            format_value(k1109, "/k1106b_comparison/k1106b_fabless_beta/t", kind="number", digits=2),
            "六家裡先挑兩家答案符合假說的",
            PURPLE,
            PURPLE_SOFT,
        ),
        (
            "預先登錄後的統計強度",
            format_value(k1109, "/k1106b_comparison/k1109_fabless_beta/t", kind="number", digits=2),
            "樣本清單事前鎖死並打時間戳記後重估",
            GREEN,
            GREEN_SOFT,
        ),
    )

    fig, ax = new_canvas()
    add_header(ax, title, "同一個想法，只換一個設定；漂亮結果可能縮水、翻負，或直接失去統計力道。", NAVY)
    xs = (0.055, 0.2825, 0.510, 0.7375)
    ys = (0.505, 0.175)
    card_width = 0.2075
    card_height = 0.275
    for index, (label, value, note, accent, soft) in enumerate(cards):
        row = index // 4
        col = index % 4
        add_metric_card(
            ax,
            (xs[col], ys[row], card_width, card_height),
            label=label,
            value=value,
            note=note,
            accent=accent,
            soft=soft,
            label_width=13,
            note_width=15,
        )

    add_footer(ax, ("k492", "k812v2", "k1109"))
    save_panel(fig, "2_results.png", title=title, alt=alt)


def render_pass(evidence: dict[str, dict[str, Any]]) -> None:
    title = "全部換過還活著的長這樣"
    alt = "懶人包：通過換件測試的模型在五個市場時代全勝，並附上樣本邊界"
    k1056 = evidence["k1056"]

    wins = int(numeric(k1056, "sub_period_summary.n_a4f_wins"))
    periods = int(numeric(k1056, "sub_period_summary.n_periods"))
    if wins < 0 or periods <= 0 or wins > periods:
        raise ValueError("Invalid wins/periods evidence in sub_period_summary")

    cards = (
        (
            "勝出的市場時代數",
            format_value(k1056, "sub_period_summary.n_a4f_wins", kind="integer", suffix=" 段"),
            "低波動牛市、崩盤、暴力修正、升息後期與近期各切一段",
            GREEN,
            GREEN_SOFT,
        ),
        (
            "純靠運氣連贏的機率",
            format_value(k1056, "sub_period_summary.binomial_p", kind="percent", digits=2),
            "兩個模型預測力相同時，連贏這麼多段的機率",
            PURPLE,
            PURPLE_SOFT,
        ),
        (
            "整段樣本外預測誤差改善",
            format_value(k1056, "full_oos.improvement_pct", kind="number", digits=2, suffix="%"),
            "邊界：中等恐慌區間幾乎打平，市場多數時間待在那裡",
            BLUE,
            BLUE_SOFT,
        ),
        (
            "有效樣本外筆數",
            format_value(k1056, "full_oos.n_valid", kind="integer", suffix=" 筆"),
            "資料來源 yfinance，標的 SPY",
            TEAL,
            TEAL_SOFT,
        ),
    )

    fig, ax = new_canvas()
    add_header(ax, title, "不只看全期間：把市場切開、把視窗滾動，再把不確定性與樣本邊界一起交代。", GREEN)

    rounded_box(ax, 0.055, 0.475, 0.405, 0.325, facecolor=WHITE)
    ax.text(
        0.080,
        0.758,
        "判準",
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=15,
        fontweight="bold",
        color=GREEN,
    )
    criteria = (
        "換時代、換波動環境、換滾動視窗都沒翻，而且每個沒把握的地方都標出來。\n\n"
        "把恐慌指數加進波動率模型的版本，是目前唯一走完全部換件的發現。"
    )
    ax.text(
        0.080,
        0.704,
        zh_wrap(criteria, 27),
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=10,
        linespacing=1.42,
        color=MUTED,
    )
    ax.text(
        0.080,
        0.510,
        "讀法：方向一致先過關，再看幅度、正式檢定與樣本限制。",
        transform=ax.transAxes,
        ha="left",
        va="bottom",
        fontsize=8.1,
        color=FAINT,
    )

    rounded_box(ax, 0.485, 0.475, 0.460, 0.325, facecolor=NAVY, edgecolor=NAVY)
    ax.text(
        0.515,
        0.758,
        "跨市場時代一致性",
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=12,
        fontweight="bold",
        color=WHITE,
    )
    ax.text(
        0.915,
        0.758,
        f"{wins} / {periods}",
        transform=ax.transAxes,
        ha="right",
        va="top",
        fontsize=23,
        fontweight="bold",
        color=WHITE,
    )
    block_x = 0.515
    block_y = 0.600
    block_width = 0.066
    gap = 0.015
    for index in range(periods):
        passed = index < wins
        rounded_box(
            ax,
            block_x + index * (block_width + gap),
            block_y,
            block_width,
            0.090,
            facecolor=TEAL if passed else "#50677A",
            edgecolor=TEAL if passed else "#50677A",
            radius=0.010,
        )
        ax.text(
            block_x + index * (block_width + gap) + block_width / 2,
            block_y + 0.045,
            "勝" if passed else "未勝",
            transform=ax.transAxes,
            ha="center",
            va="center",
            fontsize=10 if passed else 7,
            fontweight="bold",
            color=WHITE,
            zorder=4,
        )
    ax.text(
        0.515,
        0.545,
        "每一格代表一個互不重疊的市場時代；全部由同一套樣本外比較規則判定。",
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=8.2,
        color="#D9E4EC",
    )

    xs = (0.055, 0.2825, 0.510, 0.7375)
    for x, (label, value, note, accent, soft) in zip(xs, cards, strict=True):
        add_metric_card(
            ax,
            (x, 0.175, 0.2075, 0.245),
            label=label,
            value=value,
            note=note,
            accent=accent,
            soft=soft,
            label_width=13,
            note_width=15,
        )

    add_footer(ax, ("k1056",))
    save_panel(fig, "3_pass.png", title=title, alt=alt)


def main() -> None:
    os.makedirs(out_dir, exist_ok=True)
    evidence = {
        "k492": load_json(K492_PATH),
        "k812v2": load_json(K812V2_PATH),
        "k1109": load_json(K1109_PATH),
        "k1056": load_json(K1056_PATH),
    }
    load_body(BODY_PATH)

    render_framework()
    render_results(evidence)
    render_pass(evidence)


if __name__ == "__main__":
    main()
