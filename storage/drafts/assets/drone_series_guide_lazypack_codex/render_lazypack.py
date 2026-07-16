#!/usr/bin/env python3
"""Render the three data-bound PNG panels for the drone-series guide.

Every displayed statistic is read from ``drone_series_guide_evidence.json``.
The evidence package cites mile IDs rather than experiment K IDs, so the
footers reproduce those source IDs instead of inventing a K number.
"""

from __future__ import annotations

import json
import math
import os
import textwrap
from pathlib import Path
from typing import Any, Mapping, Sequence

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.patches import Circle, FancyBboxPatch, Rectangle


plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["font.family"] = "sans-serif"
plt.rcParams["axes.unicode_minus"] = False


EVIDENCE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/drafts/assets/"
    "drone_series_guide_evidence.json"
)
out_dir = (
    "/Users/yhlai0911/volpred-research/storage/drafts/assets/"
    "drone_series_guide_lazypack_codex"
)

DPI = 150
WIDTH_PX = 1600
HEIGHT_PX = 1000

NAVY = "#142A43"
NAVY_2 = "#203B59"
TEAL = "#167D7F"
TEAL_SOFT = "#E8F4F3"
BLUE = "#2E5F91"
BLUE_SOFT = "#EAF1F8"
AMBER = "#B36A12"
AMBER_SOFT = "#FBF1E2"
RED = "#B9443D"
RED_SOFT = "#F9ECEA"
INK = "#172331"
MUTED = "#5E6A78"
FAINT = "#7B8794"
BORDER = "#DCE3EA"
GRID = "#E8EDF2"
PAPER = "#F7F9FB"
WHITE = "#FFFFFF"


def _required(mapping: Mapping[str, Any], key: str, path: str) -> Any:
    if key not in mapping:
        raise KeyError(f"Missing required evidence field: {path}.{key}")
    return mapping[key]


def _as_mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"Expected object at {path}, got {type(value).__name__}")
    return value


def _as_sequence(value: Any, path: str) -> Sequence[Any]:
    if not isinstance(value, list):
        raise TypeError(f"Expected array at {path}, got {type(value).__name__}")
    return value


def _as_text(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"Expected non-empty string at {path}")
    return value


def _as_number(value: Any, path: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"Expected number at {path}, got {type(value).__name__}")
    if not math.isfinite(float(value)):
        raise ValueError(f"Expected finite number at {path}")
    return value


def _as_int(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"Expected integer at {path}, got {type(value).__name__}")
    return value


def _format_number(value: int | float) -> str:
    """Preserve the JSON number's visible precision (for example, 104.0)."""

    return str(value)


def _format_pct(value: int | float) -> str:
    return f"{_format_number(value)}%"


def _load_evidence() -> Mapping[str, Any]:
    with EVIDENCE_PATH.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return _as_mapping(data, str(EVIDENCE_PATH))


def _episode_index(evidence: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    ladder = _as_sequence(
        _required(evidence, "evidence_ladder", "root"),
        "evidence_ladder",
    )
    indexed: dict[str, Mapping[str, Any]] = {}
    for index, raw_item in enumerate(ladder):
        item_path = f"evidence_ladder.{index}"
        item = _as_mapping(raw_item, item_path)
        episode = _as_text(_required(item, "ep", item_path), f"{item_path}.ep")
        if episode in indexed:
            raise ValueError(f"Duplicate episode in evidence_ladder: {episode}")
        _as_text(_required(item, "question", item_path), f"{item_path}.question")
        _as_text(_required(item, "blocker", item_path), f"{item_path}.blocker")
        _as_text(_required(item, "source", item_path), f"{item_path}.source")
        _as_mapping(_required(item, "numbers", item_path), f"{item_path}.numbers")
        indexed[episode] = item

    required_episodes = ("EP0", "EP1", "EP2", "EP3", "EP4", "Final")
    missing = [episode for episode in required_episodes if episode not in indexed]
    if missing:
        raise KeyError(f"Missing required evidence episodes: {', '.join(missing)}")
    return indexed


def _question(item: Mapping[str, Any]) -> str:
    return _as_text(_required(item, "question", "episode"), "episode.question")


def _source_id(item: Mapping[str, Any]) -> str:
    source = _as_text(_required(item, "source", "episode"), "episode.source")
    source_id = source.split("/", 1)[0].strip()
    if not source_id:
        raise ValueError("Episode source does not contain a source identifier")
    return source_id


def _number(item: Mapping[str, Any], key: str) -> int | float:
    numbers = _as_mapping(_required(item, "numbers", "episode"), "episode.numbers")
    return _as_number(_required(numbers, key, "episode.numbers"), f"episode.numbers.{key}")


def _integer(item: Mapping[str, Any], key: str) -> int:
    numbers = _as_mapping(_required(item, "numbers", "episode"), "episode.numbers")
    return _as_int(_required(numbers, key, "episode.numbers"), f"episode.numbers.{key}")


def _ratio(item: Mapping[str, Any], numerator: str, denominator: str) -> str:
    return f"{_integer(item, numerator)}/{_integer(item, denominator)}"


def _wrap(text: str, width: int) -> str:
    lines = textwrap.wrap(
        text,
        width=width,
        break_long_words=True,
        break_on_hyphens=False,
        replace_whitespace=False,
    )
    return "\n".join(lines) if lines else text


def _new_panel() -> tuple[Figure, Axes]:
    fig = plt.figure(
        figsize=(WIDTH_PX / DPI, HEIGHT_PX / DPI),
        dpi=DPI,
        facecolor=WHITE,
    )
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.add_patch(Rectangle((0, 0), 1, 1, facecolor=PAPER, edgecolor="none", zorder=0))
    return fig, ax


def _rounded_box(
    ax: Axes,
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    facecolor: str = WHITE,
    edgecolor: str = BORDER,
    linewidth: float = 1.1,
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


def _add_header(ax: Axes, title: str, subtitle: str, accent: str) -> None:
    ax.add_patch(Rectangle((0, 0.84), 1, 0.16, facecolor=NAVY, edgecolor="none", zorder=2))
    ax.add_patch(Rectangle((0.055, 0.865), 0.006, 0.095, facecolor=accent, edgecolor="none", zorder=3))
    ax.text(
        0.078,
        0.932,
        title,
        ha="left",
        va="center",
        fontsize=27,
        fontweight="bold",
        color=WHITE,
        transform=ax.transAxes,
        zorder=4,
    )
    ax.text(
        0.079,
        0.872,
        subtitle,
        ha="left",
        va="center",
        fontsize=11.5,
        color="#D8E1EA",
        transform=ax.transAxes,
        zorder=4,
    )


def _add_footer(ax: Axes, source_ids: Sequence[str]) -> None:
    unique_sources = list(dict.fromkeys(source_ids))
    source_text = (
        f"資料來源：{EVIDENCE_PATH.name}；原始來源："
        + "、".join(unique_sources)
    )
    ax.plot((0.055, 0.945), (0.085, 0.085), color=BORDER, linewidth=1.0, transform=ax.transAxes)
    ax.text(
        0.055,
        0.048,
        _wrap(source_text, 116),
        ha="left",
        va="center",
        fontsize=8.3,
        linespacing=1.28,
        color=FAINT,
        transform=ax.transAxes,
    )


def _save(fig: Figure, filename: str) -> None:
    destination = Path(out_dir) / filename
    fig.savefig(destination, format="png", dpi=DPI, facecolor=WHITE, edgecolor="none")
    plt.close(fig)


def _render_concept(episodes: Mapping[str, Mapping[str, Any]]) -> None:
    ep0 = episodes["EP0"]
    ep1 = episodes["EP1"]
    ep2 = episodes["EP2"]
    ep3 = episodes["EP3"]
    ep4 = episodes["EP4"]
    final = episodes["Final"]

    cards = [
        (
            "市場總覽",
            ep0,
            f"{_format_pct(_number(ep0, 'all29_return_pct'))}／"
            f"{_format_pct(_number(ep0, 'twii_return_pct'))}",
            "題材股全集／臺灣加權指數",
            BLUE,
            BLUE_SOFT,
        ),
        (
            "上游",
            ep1,
            _format_pct(_number(ep1, "revenue_concentration_pct")),
            "營收集中度",
            TEAL,
            TEAL_SOFT,
        ),
        (
            "中游",
            ep2,
            _ratio(ep2, "disclose_revenue", "checked"),
            "可拆出無人機營收",
            AMBER,
            AMBER_SOFT,
        ),
        (
            "下游",
            ep3,
            _ratio(ep3, "shipping", "checked"),
            "已量產或交船",
            AMBER,
            AMBER_SOFT,
        ),
        (
            "龍頭個股",
            ep4,
            _ratio(ep4, "pass", "checked"),
            "六面向通過",
            RED,
            RED_SOFT,
        ),
        (
            "組合檢驗",
            final,
            f"{_format_pct(_number(final, 'core6_return_pct'))}／"
            f"{_format_pct(_number(final, 'twii_return_pct'))}",
            "核心組合／臺灣加權指數",
            NAVY_2,
            BLUE_SOFT,
        ),
    ]

    fig, ax = _new_panel()
    _add_header(
        ax,
        "題材如何變成證據：系列查核路線",
        "從市場表現一路追到營收揭露、實際交付、個股品質與組合風險。",
        TEAL,
    )
    ax.text(
        0.055,
        0.785,
        "每個環節都要有可核對的數字，故事才有機會變成投資證據。",
        ha="left",
        va="center",
        fontsize=14.5,
        fontweight="bold",
        color=INK,
        transform=ax.transAxes,
    )

    x_positions = (0.055, 0.365, 0.675)
    y_positions = (0.500, 0.180)
    card_width = 0.270
    card_height = 0.225

    for index, (stage, item, value, descriptor, accent, soft) in enumerate(cards):
        col = index % 3
        row = index // 3
        x = x_positions[col]
        y = y_positions[row]
        _rounded_box(ax, x, y, card_width, card_height, facecolor=WHITE)
        ax.add_patch(
            Rectangle(
                (x, y + 0.018),
                0.006,
                card_height - 0.036,
                facecolor=accent,
                edgecolor="none",
                transform=ax.transAxes,
                zorder=2,
            )
        )
        ax.add_patch(
            Circle(
                (x + 0.033, y + 0.185),
                0.014,
                facecolor=soft,
                edgecolor=accent,
                linewidth=1.2,
                transform=ax.transAxes,
                zorder=3,
            )
        )
        ax.text(
            x + 0.058,
            y + 0.185,
            stage,
            ha="left",
            va="center",
            fontsize=10.5,
            fontweight="bold",
            color=accent,
            transform=ax.transAxes,
        )
        ax.text(
            x + 0.025,
            y + 0.145,
            _question(item),
            ha="left",
            va="center",
            fontsize=11.5,
            fontweight="bold",
            color=INK,
            transform=ax.transAxes,
        )
        value_fontsize = 19 if len(value) > 8 else 24
        ax.text(
            x + 0.025,
            y + 0.095,
            value,
            ha="left",
            va="center",
            fontsize=value_fontsize,
            fontweight="bold",
            color=INK,
            transform=ax.transAxes,
        )
        ax.text(
            x + 0.025,
            y + 0.052,
            descriptor,
            ha="left",
            va="center",
            fontsize=9.3,
            color=MUTED,
            transform=ax.transAxes,
        )
        ax.text(
            x + 0.025,
            y + 0.019,
            _source_id(item),
            ha="left",
            va="center",
            fontsize=7.2,
            color=FAINT,
            transform=ax.transAxes,
        )

    _add_footer(ax, [_source_id(card[1]) for card in cards])
    _save(fig, "1_concept.png")


def _draw_pair_bar(
    ax: Axes,
    y: float,
    label: str,
    value: int | float,
    display: str,
    maximum: float,
    color: str,
) -> None:
    if float(value) < 0:
        raise ValueError("This panel expects non-negative return values")
    if maximum <= 0:
        raise ValueError("Pair-bar maximum must be positive")

    ax.text(
        0.083,
        y,
        label,
        ha="left",
        va="center",
        fontsize=11.5,
        fontweight="bold",
        color=INK,
        transform=ax.transAxes,
    )
    bar_x = 0.255
    bar_width = 0.500
    bar_height = 0.034
    _rounded_box(
        ax,
        bar_x,
        y - bar_height / 2,
        bar_width,
        bar_height,
        facecolor=GRID,
        edgecolor=GRID,
        linewidth=0,
        radius=0.012,
    )
    filled_width = bar_width * float(value) / maximum
    _rounded_box(
        ax,
        bar_x,
        y - bar_height / 2,
        filled_width,
        bar_height,
        facecolor=color,
        edgecolor=color,
        linewidth=0,
        radius=0.012,
        zorder=3,
    )
    ax.text(
        0.885,
        y,
        display,
        ha="right",
        va="center",
        fontsize=15,
        fontweight="bold",
        color=INK,
        transform=ax.transAxes,
    )


def _metric_pair_card(
    ax: Axes,
    x: float,
    title: str,
    core_value: str,
    market_value: str,
    accent: str,
    soft: str,
) -> None:
    y = 0.180
    width = 0.260
    height = 0.225
    _rounded_box(ax, x, y, width, height, facecolor=WHITE)
    ax.add_patch(
        Rectangle(
            (x + 0.020, y + height - 0.012),
            width - 0.040,
            0.006,
            facecolor=accent,
            edgecolor="none",
            transform=ax.transAxes,
            zorder=2,
        )
    )
    ax.text(
        x + 0.020,
        y + 0.181,
        title,
        ha="left",
        va="center",
        fontsize=12.5,
        fontweight="bold",
        color=accent,
        transform=ax.transAxes,
    )
    ax.text(
        x + 0.020,
        y + 0.124,
        "核心組合",
        ha="left",
        va="center",
        fontsize=9.5,
        color=MUTED,
        transform=ax.transAxes,
    )
    ax.text(
        x + width - 0.020,
        y + 0.124,
        core_value,
        ha="right",
        va="center",
        fontsize=18,
        fontweight="bold",
        color=INK,
        transform=ax.transAxes,
    )
    ax.plot(
        (x + 0.020, x + width - 0.020),
        (y + 0.091, y + 0.091),
        color=BORDER,
        linewidth=0.9,
        transform=ax.transAxes,
    )
    ax.text(
        x + 0.020,
        y + 0.054,
        "臺灣加權指數",
        ha="left",
        va="center",
        fontsize=9.5,
        color=MUTED,
        transform=ax.transAxes,
    )
    ax.text(
        x + width - 0.020,
        y + 0.054,
        market_value,
        ha="right",
        va="center",
        fontsize=15,
        fontweight="bold",
        color=INK,
        transform=ax.transAxes,
    )


def _render_results(episodes: Mapping[str, Mapping[str, Any]]) -> None:
    ep0 = episodes["EP0"]
    final = episodes["Final"]

    all_return = _number(ep0, "all29_return_pct")
    ep0_market_return = _number(ep0, "twii_return_pct")
    top_maximum = max(float(all_return), float(ep0_market_return))

    core_return = _number(final, "core6_return_pct")
    final_market_return = _number(final, "twii_return_pct")
    core_vol = _number(final, "core6_vol_pct")
    market_vol = _number(final, "twii_vol_pct")
    core_mdd = _number(final, "core6_mdd_pct")
    market_mdd = _number(final, "twii_mdd_pct")

    fig, ax = _new_panel()
    _add_header(
        ax,
        "結果：報酬追平，不代表風險相同",
        "全體題材股先落後；縮成核心組合後，報酬接近大盤，但波動與回撤明顯更高。",
        AMBER,
    )

    _rounded_box(ax, 0.055, 0.565, 0.890, 0.225, facecolor=WHITE)
    ax.text(
        0.080,
        0.750,
        "全體題材股的一年報酬",
        ha="left",
        va="center",
        fontsize=14.5,
        fontweight="bold",
        color=INK,
        transform=ax.transAxes,
    )
    _draw_pair_bar(
        ax,
        0.682,
        "題材股全集",
        all_return,
        _format_pct(all_return),
        top_maximum,
        BLUE,
    )
    _draw_pair_bar(
        ax,
        0.612,
        "臺灣加權指數",
        ep0_market_return,
        _format_pct(ep0_market_return),
        top_maximum,
        TEAL,
    )

    _rounded_box(ax, 0.055, 0.145, 0.890, 0.375, facecolor=BLUE_SOFT, edgecolor="#D6E2EE")
    ax.text(
        0.080,
        0.480,
        "核心組合與大盤：同期間三項對照",
        ha="left",
        va="center",
        fontsize=14.5,
        fontweight="bold",
        color=INK,
        transform=ax.transAxes,
    )
    ax.text(
        0.920,
        0.480,
        "每格只比較同一指標",
        ha="right",
        va="center",
        fontsize=9.2,
        color=MUTED,
        transform=ax.transAxes,
    )

    _metric_pair_card(
        ax,
        0.075,
        "累積報酬",
        _format_pct(core_return),
        _format_pct(final_market_return),
        TEAL,
        TEAL_SOFT,
    )
    _metric_pair_card(
        ax,
        0.370,
        "年化波動率",
        _format_pct(core_vol),
        _format_pct(market_vol),
        AMBER,
        AMBER_SOFT,
    )
    _metric_pair_card(
        ax,
        0.665,
        "最大回撤（絕對值）",
        _format_pct(core_mdd),
        _format_pct(market_mdd),
        RED,
        RED_SOFT,
    )

    _add_footer(ax, [_source_id(ep0), _source_id(final)])
    _save(fig, "2_results.png")


def _status_card(
    ax: Axes,
    x: float,
    label: str,
    value: str,
    note: str,
    accent: str,
    soft: str,
) -> None:
    y = 0.440
    width = 0.205
    height = 0.205
    _rounded_box(ax, x, y, width, height, facecolor=WHITE)
    ax.add_patch(
        Circle(
            (x + 0.026, y + 0.169),
            0.012,
            facecolor=soft,
            edgecolor=accent,
            linewidth=1.1,
            transform=ax.transAxes,
            zorder=2,
        )
    )
    ax.text(
        x + 0.048,
        y + 0.169,
        label,
        ha="left",
        va="center",
        fontsize=10.2,
        fontweight="bold",
        color=INK,
        transform=ax.transAxes,
    )
    ax.text(
        x + 0.020,
        y + 0.105,
        value,
        ha="left",
        va="center",
        fontsize=24,
        fontweight="bold",
        color=accent,
        transform=ax.transAxes,
    )
    ax.text(
        x + 0.020,
        y + 0.045,
        _wrap(note, 12),
        ha="left",
        va="center",
        fontsize=8.7,
        linespacing=1.25,
        color=MUTED,
        transform=ax.transAxes,
    )


def _conclusion_metric(
    ax: Axes,
    center_x: float,
    label: str,
    core_value: str,
    market_value: str,
) -> None:
    ax.text(
        center_x,
        0.298,
        label,
        ha="center",
        va="center",
        fontsize=10.5,
        fontweight="bold",
        color=MUTED,
        transform=ax.transAxes,
    )
    ax.text(
        center_x,
        0.247,
        f"{core_value}／{market_value}",
        ha="center",
        va="center",
        fontsize=17,
        fontweight="bold",
        color=INK,
        transform=ax.transAxes,
    )
    ax.text(
        center_x,
        0.198,
        "核心組合／臺灣加權指數",
        ha="center",
        va="center",
        fontsize=8.5,
        color=FAINT,
        transform=ax.transAxes,
    )


def _render_conclusion(
    evidence: Mapping[str, Any],
    episodes: Mapping[str, Mapping[str, Any]],
) -> None:
    ep2 = episodes["EP2"]
    ep3 = episodes["EP3"]
    ep4 = episodes["EP4"]
    final = episodes["Final"]
    headline = _as_mapping(
        _required(evidence, "headline_zeros", "root"),
        "headline_zeros",
    )
    revenue_breakdown = _as_text(
        _required(headline, "revenue_breakdown", "headline_zeros"),
        "headline_zeros.revenue_breakdown",
    )
    verifiable_orders = _as_text(
        _required(headline, "verifiable_orders", "headline_zeros"),
        "headline_zeros.verifiable_orders",
    )
    _as_text(
        _required(headline, "source", "headline_zeros"),
        "headline_zeros.source",
    )

    core_return = _number(final, "core6_return_pct")
    market_return = _number(final, "twii_return_pct")
    core_vol = _number(final, "core6_vol_pct")
    market_vol = _number(final, "twii_vol_pct")
    core_mdd = _number(final, "core6_mdd_pct")
    market_mdd = _number(final, "twii_mdd_pct")

    fig, ax = _new_panel()
    _add_header(
        ax,
        "結論：題材很熱，財務證據還沒到",
        "目前較適合列入觀察清單；若要進一步投資，仍需等營收、訂單與交付證據補齊。",
        RED,
    )

    _rounded_box(ax, 0.055, 0.685, 0.890, 0.105, facecolor=AMBER_SOFT, edgecolor="#ECD8B7")
    ax.text(
        0.500,
        0.755,
        "系列查核沒有否定題材，而是把『可驗證』的門檻拉回來。",
        ha="center",
        va="center",
        fontsize=19,
        fontweight="bold",
        color=INK,
        transform=ax.transAxes,
    )
    ax.text(
        0.500,
        0.706,
        "在財務鏈條補齊前，價格表現不能取代基本面證據。",
        ha="center",
        va="center",
        fontsize=10.2,
        color=MUTED,
        transform=ax.transAxes,
    )

    _status_card(
        ax,
        0.055,
        "逐家營收拆分",
        revenue_breakdown,
        "仍未取得可分拆數據",
        RED,
        RED_SOFT,
    )
    _status_card(
        ax,
        0.278,
        "可驗證訂單",
        verifiable_orders,
        "逐家查核仍是空白",
        RED,
        RED_SOFT,
    )
    _status_card(
        ax,
        0.501,
        "量產或交船",
        _ratio(ep3, "shipping", "checked"),
        "只有少數公司已落地",
        AMBER,
        AMBER_SOFT,
    )
    _status_card(
        ax,
        0.724,
        "個股六面向",
        _ratio(ep4, "pass", "checked"),
        "基本面通過者有限",
        AMBER,
        AMBER_SOFT,
    )

    _rounded_box(ax, 0.055, 0.140, 0.890, 0.250, facecolor=WHITE)
    ax.text(
        0.080,
        0.355,
        "核心組合最後仍要接受同期間風險報酬檢驗",
        ha="left",
        va="center",
        fontsize=13.5,
        fontweight="bold",
        color=INK,
        transform=ax.transAxes,
    )
    ax.plot((0.080, 0.920), (0.330, 0.330), color=BORDER, linewidth=0.9, transform=ax.transAxes)
    ax.plot((0.355, 0.355), (0.175, 0.315), color=BORDER, linewidth=0.9, transform=ax.transAxes)
    ax.plot((0.645, 0.645), (0.175, 0.315), color=BORDER, linewidth=0.9, transform=ax.transAxes)

    _conclusion_metric(
        ax,
        0.210,
        "累積報酬",
        _format_pct(core_return),
        _format_pct(market_return),
    )
    _conclusion_metric(
        ax,
        0.500,
        "年化波動率",
        _format_pct(core_vol),
        _format_pct(market_vol),
    )
    _conclusion_metric(
        ax,
        0.790,
        "最大回撤（絕對值）",
        _format_pct(core_mdd),
        _format_pct(market_mdd),
    )

    _add_footer(
        ax,
        [_source_id(ep2), _source_id(ep3), _source_id(ep4), _source_id(final)],
    )
    _save(fig, "3_conclusion.png")


def main() -> None:
    evidence = _load_evidence()
    episodes = _episode_index(evidence)
    os.makedirs(out_dir, exist_ok=True)
    _render_concept(episodes)
    _render_results(episodes)
    _render_conclusion(evidence, episodes)


if __name__ == "__main__":
    main()
