#!/usr/bin/env python3
"""Render the three data-bound PNG panels for 「恐慌半衰期四問」.

All displayed metrics are resolved from the evidence package at runtime.  A
missing source, path, or numeric value raises immediately instead of producing
an incomplete graphic.
"""

from __future__ import annotations

import json
import os
import textwrap
from typing import Any

import matplotlib


matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyBboxPatch


EVIDENCE_PATH = (
    "/Users/yhlai0911/volpred-research/storage/drafts/assets/"
    "digest_20260716/evidence.json"
)
OUT_DIR = (
    "/Users/yhlai0911/volpred-research/storage/drafts/assets/"
    "digest_20260716/digest_20260716_fear_halflife_panels"
)

WIDTH_PX = 1600
HEIGHT_PX = 1000
DPI = 150

SOURCE_LABELS = {
    "market": "Yahoo Finance 日收盤證據包（VIX、OVX、WTI；產生於台北時間 2026-07-16）"
}

INK = "#172033"
MUTED = "#5B6575"
FAINT = "#8B94A3"
PAPER = "#FFFFFF"
NAVY = "#173B62"
BLUE = "#2D6EA6"
BLUE_SOFT = "#EAF2F9"
TEAL = "#177D7A"
TEAL_SOFT = "#E4F3F1"
AMBER = "#B66C16"
AMBER_SOFT = "#FAEEDC"
RED = "#B84646"
RED_SOFT = "#F8E8E7"
LINE = "#DCE2E9"
CARD = "#F8FAFC"

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False


PANELS: list[dict[str, Any]] = [
    {
        "name": "1_framework",
        "title": "恐慌半衰期：先問四件事",
        "alt": "懶人包：用源頭、傳導、事件型態與部位代價判斷恐慌半衰期",
        "sources": ["market"],
        "blocks": [
            {
                "kind": "text",
                "heading": "源頭",
                "body": [
                    "衝擊源自己的恐慌正在收斂，還在擴散？油市事件先看油市自己的恐慌指標。"
                ],
            },
            {
                "kind": "text",
                "heading": "傳導",
                "body": [
                    "源頭通往你的資產，真的有可驗證的領先路徑嗎？同日共振不等於隔日傳染。"
                ],
            },
            {
                "kind": "text",
                "heading": "事件型態",
                "body": [
                    "消息一次落地就結束，還是每天長出續集？連環劇會反覆改寫市場定價。"
                ],
            },
            {
                "kind": "text",
                "heading": "部位代價",
                "body": [
                    "半衰期判錯時，部位能否留下來？先設計承受方式，再決定要不要押方向。"
                ],
            },
        ],
    },
    {
        "name": "2_today",
        "title": "上一個收盤：VIX 已退，OVX 未退",
        "alt": "懶人包：拆開最新完成收盤與盤中時點，查看 VIX、OVX、WTI 及油市恐慌半衰期進度",
        "sources": ["market"],
        "blocks": [
            {
                "kind": "metric",
                "label": "VIX 最新收盤",
                "value": {
                    "source": "market",
                    "path": "latest.vix_close",
                    "format": {"kind": "number", "digits": 2},
                },
                "note": "上一個美股收盤；尚未納入最新攻擊",
            },
            {
                "kind": "metric",
                "label": "OVX 最新收盤",
                "value": {
                    "source": "market",
                    "path": "latest.ovx_close",
                    "format": {"kind": "number", "digits": 2},
                },
                "note": "上一個美股收盤；油市恐慌仍接近近期高點",
            },
            {
                "kind": "metric",
                "label": "WTI 最近成交價",
                "value": {
                    "source": "market",
                    "path": "latest.wti_close",
                    "format": {
                        "kind": "number",
                        "digits": 1,
                        "suffix": " 美元/桶",
                    },
                },
                "note": "最新盤中值，時點晚於波動率收盤",
            },
            {
                "kind": "metric",
                "label": "OVX 半衰門檻",
                "value": {
                    "source": "market",
                    "path": "supplementary_ovx_event.half_level",
                    "format": {"kind": "number", "digits": 2},
                },
                "note": "最新收盤仍高於門檻，半衰期尚未完成",
            },
            {
                "kind": "metric",
                "label": "OVX 峰值後經過",
                "value": {
                    "source": "market",
                    "path": "supplementary_ovx_event.days_elapsed_since_peak",
                    "format": {"kind": "integer", "suffix": " 個交易日"},
                },
                "note": "這是上一個完成收盤的分裂，下一個收盤需重算",
            },
        ],
    },
    {
        "name": "3_history",
        "title": "第一次退燒，不代表病程結束",
        "alt": "懶人包：關稅戰、中東衝突與本輪油市衝擊的 VIX 半衰期比較",
        "sources": ["market"],
        "blocks": [
            {
                "kind": "text",
                "heading": "統一算法",
                "body": [
                    "基線取事件前一段交易日的收盤中位數；半衰門檻取峰值與基線的中點。",
                    "同時看首次跌破、持續跌破與回到基線，避免被單日政策反轉騙到。",
                ],
            },
            {
                "kind": "metric",
                "label": "關稅戰：首次跌破",
                "value": {
                    "source": "market",
                    "path": "/events/0/half_life_trading_days",
                    "format": {"kind": "integer", "suffix": " 個交易日"},
                },
                "note": "單日政策反轉造成暫時退燒",
            },
            {
                "kind": "metric",
                "label": "關稅戰：持續跌破",
                "value": {
                    "source": "market",
                    "path": "/events/0/sustained_half_life_trading_days",
                    "format": {"kind": "integer", "suffix": " 個交易日"},
                },
                "note": "市場之後曾再度升溫",
            },
            {
                "kind": "metric",
                "label": "關稅戰：回到基線",
                "value": {
                    "source": "market",
                    "path": "/events/0/return_to_baseline_trading_days",
                    "format": {"kind": "integer", "suffix": " 個交易日"},
                },
                "note": "完整病程遠長於第一次退燒",
            },
            {
                "kind": "metric",
                "label": "前輪中東衝突：回到基線",
                "value": {
                    "source": "market",
                    "path": "/events/1/return_to_baseline_trading_days",
                    "format": {"kind": "integer", "suffix": " 個交易日"},
                },
                "note": "當時的股市恐慌較快消退",
            },
            {
                "kind": "metric",
                "label": "本輪 VIX：回到基線",
                "value": {
                    "source": "market",
                    "path": "/events/2/return_to_baseline_trading_days",
                    "format": {"kind": "integer", "suffix": " 個交易日"},
                },
                "note": "峰值只比基線略高，屬雜訊等級，解讀要保守",
            },
        ],
    },
]


def load_evidence() -> dict[str, Any]:
    with open(EVIDENCE_PATH, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise TypeError(f"Evidence root must be an object: {EVIDENCE_PATH}")
    return data


def resolve_path(data: Any, path: str) -> Any:
    """Resolve a dotted path or a JSON Pointer; missing components raise."""

    if not isinstance(path, str) or not path:
        raise ValueError("Evidence path must be a non-empty string")

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
                index = int(part)
            except ValueError as exc:
                raise KeyError(f"Invalid list index in evidence path: {path}") from exc
            if index < 0 or index >= len(current):
                raise KeyError(f"List index out of range in evidence path: {path}")
            current = current[index]
        else:
            raise KeyError(f"Evidence path crosses a scalar value: {path}")
    return current


def format_metric(value: Any, spec: dict[str, Any], path: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"Expected numeric evidence at {path}, got {type(value).__name__}")

    kind = spec["kind"]
    suffix = spec.get("suffix", "")
    if kind == "number":
        digits = spec["digits"]
        if not isinstance(digits, int) or digits < 0:
            raise ValueError(f"Invalid digits for {path}: {digits!r}")
        rendered = f"{value:.{digits}f}"
    elif kind == "integer":
        if isinstance(value, float) and not value.is_integer():
            raise ValueError(f"Expected an integer-valued metric at {path}: {value!r}")
        rendered = f"{int(value)}"
    else:
        raise ValueError(f"Unsupported metric format at {path}: {kind!r}")
    return rendered + suffix


def bind_metrics(panel: dict[str, Any], sources: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    bound: list[dict[str, Any]] = []
    for block in panel["blocks"]:
        if block["kind"] != "metric":
            continue
        value_spec = block["value"]
        source_name = value_spec["source"]
        if source_name not in sources:
            raise KeyError(f"Unknown evidence source: {source_name}")
        path = value_spec["path"]
        raw_value = resolve_path(sources[source_name], path)
        bound.append(
            {
                **block,
                "raw_value": raw_value,
                "display_value": format_metric(raw_value, value_spec["format"], path),
            }
        )
    return bound


def new_canvas() -> tuple[plt.Figure, plt.Axes]:
    fig = plt.figure(
        figsize=(WIDTH_PX / DPI, HEIGHT_PX / DPI),
        dpi=DPI,
        facecolor=PAPER,
    )
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    return fig, ax


def wrap(text: str, width: int) -> str:
    return "\n".join(
        textwrap.wrap(
            text,
            width=width,
            break_long_words=True,
            break_on_hyphens=False,
        )
    )


def rounded_box(
    ax: plt.Axes,
    x: float,
    y: float,
    w: float,
    h: float,
    facecolor: str,
    edgecolor: str = "none",
    linewidth: float = 1.0,
    radius: float = 0.018,
) -> None:
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle=f"round,pad=0.008,rounding_size={radius}",
            transform=ax.transAxes,
            linewidth=linewidth,
            edgecolor=edgecolor,
            facecolor=facecolor,
        )
    )


def draw_header(fig: plt.Figure, title: str, eyebrow: str) -> None:
    fig.text(0.055, 0.948, eyebrow, fontsize=10.5, color=TEAL, weight="bold", va="top")
    fig.text(0.055, 0.906, title, fontsize=28, color=INK, weight="bold", va="top")
    fig.add_artist(
        plt.Line2D([0.055, 0.945], [0.855, 0.855], transform=fig.transFigure, color=LINE, linewidth=1.2)
    )


def draw_footer(fig: plt.Figure, panel: dict[str, Any]) -> None:
    labels: list[str] = []
    for source in panel["sources"]:
        if source not in SOURCE_LABELS:
            raise KeyError(f"Missing reader-facing source label: {source}")
        labels.append(SOURCE_LABELS[source])
    fig.add_artist(
        plt.Line2D([0.055, 0.945], [0.105, 0.105], transform=fig.transFigure, color=LINE, linewidth=1.0)
    )
    fig.text(
        0.055,
        0.074,
        "資料來源：" + "；".join(labels),
        fontsize=9.2,
        color=MUTED,
        va="center",
        ha="left",
    )


def save_panel(fig: plt.Figure, panel: dict[str, Any]) -> None:
    output_path = os.path.join(OUT_DIR, panel["name"] + ".png")
    fig.savefig(
        output_path,
        dpi=DPI,
        facecolor=PAPER,
        edgecolor="none",
        metadata={
            "Title": panel["title"],
            "Description": panel["alt"],
            "Source": "；".join(SOURCE_LABELS[source] for source in panel["sources"]),
        },
    )
    plt.close(fig)


def render_framework(panel: dict[str, Any]) -> None:
    fig, ax = new_canvas()
    draw_header(fig, panel["title"], "判斷框架")

    card_positions = [
        (0.055, 0.585, 0.315, 0.215),
        (0.630, 0.585, 0.315, 0.215),
        (0.055, 0.255, 0.315, 0.215),
        (0.630, 0.255, 0.315, 0.215),
    ]
    accents = [TEAL, BLUE, AMBER, RED]
    soft_colors = [TEAL_SOFT, BLUE_SOFT, AMBER_SOFT, RED_SOFT]

    center = (0.500, 0.527)
    connection_points = [(0.370, 0.630), (0.630, 0.630), (0.370, 0.420), (0.630, 0.420)]
    for point, color in zip(connection_points, accents):
        ax.plot(
            [center[0], point[0]],
            [center[1], point[1]],
            transform=ax.transAxes,
            color=color,
            alpha=0.42,
            linewidth=2.0,
            zorder=1,
        )

    ax.add_patch(
        Circle(
            center,
            0.103,
            transform=ax.transAxes,
            facecolor=NAVY,
            edgecolor="white",
            linewidth=5,
            zorder=3,
        )
    )
    fig.text(
        center[0],
        center[1],
        "恐慌\n半衰期",
        fontsize=21,
        color="white",
        weight="bold",
        ha="center",
        va="center",
        linespacing=1.20,
        zorder=4,
    )

    for block, position, accent, soft in zip(
        panel["blocks"], card_positions, accents, soft_colors
    ):
        if block["kind"] != "text":
            raise ValueError("Framework panel accepts text blocks only")
        x, y, w, h = position
        rounded_box(ax, x, y, w, h, CARD, LINE, linewidth=1.0)
        rounded_box(ax, x + 0.018, y + h - 0.073, 0.104, 0.047, soft, radius=0.012)
        fig.text(
            x + 0.070,
            y + h - 0.049,
            block["heading"],
            fontsize=15.5,
            color=accent,
            weight="bold",
            ha="center",
            va="center",
        )
        fig.text(
            x + 0.022,
            y + h - 0.098,
            wrap(block["body"][0], 18),
            fontsize=11.6,
            color=INK,
            ha="left",
            va="top",
            linespacing=1.55,
        )

    draw_footer(fig, panel)
    save_panel(fig, panel)


def draw_metric_card(
    fig: plt.Figure,
    ax: plt.Axes,
    metric: dict[str, Any],
    position: tuple[float, float, float, float],
    accent: str,
    soft: str,
    note_wrap: int,
) -> None:
    x, y, w, h = position
    rounded_box(ax, x, y, w, h, CARD, LINE, linewidth=1.0)
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            0.010,
            h,
            boxstyle="round,pad=0,rounding_size=0.008",
            transform=ax.transAxes,
            linewidth=0,
            facecolor=accent,
        )
    )
    fig.text(x + 0.030, y + h - 0.055, metric["label"], fontsize=12.5, color=MUTED, weight="bold", va="top")
    fig.text(
        x + 0.030,
        y + h - 0.115,
        metric["display_value"],
        fontsize=26,
        color=accent,
        weight="bold",
        va="top",
    )
    fig.text(
        x + 0.030,
        y + 0.042,
        wrap(metric["note"], note_wrap),
        fontsize=10.2,
        color=INK,
        va="bottom",
        linespacing=1.35,
    )
    ax.add_patch(
        Circle(
            (x + w - 0.037, y + h - 0.046),
            0.015,
            transform=ax.transAxes,
            facecolor=soft,
            edgecolor="none",
        )
    )


def render_today(panel: dict[str, Any], metrics: list[dict[str, Any]]) -> None:
    if len(metrics) != 5:
        raise ValueError("Today panel requires exactly five metrics")

    fig, ax = new_canvas()
    draw_header(fig, panel["title"], "時點拆開看")
    fig.text(
        0.945,
        0.906,
        "最新攻擊晚於波動率收盤，下一個完整收盤再更新",
        fontsize=11.5,
        color=MUTED,
        ha="right",
        va="top",
    )

    positions = [
        (0.055, 0.530, 0.280, 0.275),
        (0.360, 0.530, 0.280, 0.275),
        (0.665, 0.530, 0.280, 0.275),
        (0.055, 0.190, 0.430, 0.275),
        (0.515, 0.190, 0.430, 0.275),
    ]
    colors = [BLUE, RED, AMBER, RED, TEAL]
    soft_colors = [BLUE_SOFT, RED_SOFT, AMBER_SOFT, RED_SOFT, TEAL_SOFT]
    note_wraps = [19, 19, 19, 30, 30]
    for metric, position, color, soft, note_width in zip(
        metrics, positions, colors, soft_colors, note_wraps
    ):
        draw_metric_card(fig, ax, metric, position, color, soft, note_width)

    draw_footer(fig, panel)
    save_panel(fig, panel)


def render_history(panel: dict[str, Any], metrics: list[dict[str, Any]]) -> None:
    if len(metrics) != 5:
        raise ValueError("History panel requires exactly five metrics")

    text_blocks = [block for block in panel["blocks"] if block["kind"] == "text"]
    if len(text_blocks) != 1:
        raise ValueError("History panel requires exactly one method block")
    method = text_blocks[0]

    fig, ax = new_canvas()
    draw_header(fig, panel["title"], "歷史事件比較")

    rounded_box(ax, 0.055, 0.190, 0.330, 0.615, BLUE_SOFT, edgecolor="#C9DBEC", linewidth=1.0)
    fig.text(0.082, 0.765, method["heading"], fontsize=17, color=NAVY, weight="bold", va="top")
    fig.text(
        0.082,
        0.700,
        wrap(method["body"][0], 18),
        fontsize=11.8,
        color=INK,
        va="top",
        linespacing=1.55,
    )

    step_y = 0.525
    step_labels = ["事件前基線", "峰值與基線中點", "首次／持續／回基線"]
    for index, label in enumerate(step_labels):
        y = step_y - index * 0.092
        ax.add_patch(
            Circle(
                (0.095, y),
                0.014,
                transform=ax.transAxes,
                facecolor=[TEAL, AMBER, NAVY][index],
                edgecolor="none",
            )
        )
        fig.text(0.120, y, label, fontsize=11.2, color=INK, weight="bold", va="center")
        if index < len(step_labels) - 1:
            ax.plot(
                [0.095, 0.095],
                [y - 0.021, y - 0.071],
                transform=ax.transAxes,
                color="#AEC3D7",
                linewidth=1.5,
            )

    fig.text(
        0.082,
        0.305,
        wrap(method["body"][1], 18),
        fontsize=11.8,
        color=INK,
        va="top",
        linespacing=1.55,
    )

    fig.text(0.430, 0.802, "交易日數比較", fontsize=13.5, color=NAVY, weight="bold", va="top")
    row_top = 0.750
    row_height = 0.112
    max_value = max(float(metric["raw_value"]) for metric in metrics)
    if max_value <= 0:
        raise ValueError("History metrics must contain at least one positive value")

    row_colors = [TEAL, BLUE, NAVY, AMBER, RED]
    for index, (metric, color) in enumerate(zip(metrics, row_colors)):
        y_top = row_top - index * row_height
        fig.text(0.430, y_top, metric["label"], fontsize=11.2, color=INK, weight="bold", va="top")
        fig.text(
            0.932,
            y_top,
            metric["display_value"],
            fontsize=12.2,
            color=color,
            weight="bold",
            ha="right",
            va="top",
        )

        track_y = y_top - 0.040
        ax.plot(
            [0.430, 0.932],
            [track_y, track_y],
            transform=ax.transAxes,
            color="#E8ECF1",
            linewidth=8,
            solid_capstyle="round",
        )
        bar_end = 0.430 + 0.502 * (float(metric["raw_value"]) / max_value)
        ax.plot(
            [0.430, bar_end],
            [track_y, track_y],
            transform=ax.transAxes,
            color=color,
            linewidth=8,
            solid_capstyle="round",
        )
        fig.text(
            0.430,
            y_top - 0.064,
            metric["note"],
            fontsize=9.2,
            color=MUTED,
            va="top",
        )

    draw_footer(fig, panel)
    save_panel(fig, panel)


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    evidence = load_evidence()
    sources = {"market": evidence}

    # Resolve every planned metric before writing any image.  This keeps a bad
    # evidence package from leaving behind a plausible-looking partial set.
    bound_by_name = {
        panel["name"]: bind_metrics(panel, sources)
        for panel in PANELS
    }

    render_framework(PANELS[0])
    render_today(PANELS[1], bound_by_name["2_today"])
    render_history(PANELS[2], bound_by_name["3_history"])


if __name__ == "__main__":
    main()
