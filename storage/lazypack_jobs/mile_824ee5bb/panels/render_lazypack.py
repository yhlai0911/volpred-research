#!/usr/bin/env python3
"""Render the VolPred「爆量之後會漲還會跌？」lazy-pack PNG set.

Every displayed statistic is resolved from the experiment results JSON at
runtime.  The README files and article draft are also loaded as part of the
evidence package so a missing source fails loudly before any PNG is written.
"""

from __future__ import annotations

import json
import math
import os
import re
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch, Rectangle


plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False


K1636_RESULTS = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1636/k1636_results.json"
)
K1636_README = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1636/README.md"
)
K1653_RESULTS = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1653/k1653_results.json"
)
K1653_README = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1653/README.md"
)
K1659_RESULTS = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1659/k1659_results.json"
)
K1659_README = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1659/README.md"
)
K1671_RESULTS = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1671/k1671_results.json"
)
K1671_README = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1671/README.md"
)
ARTICLE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_824ee5bb/panels/mile_824ee5bb_article.md"
)

out_dir = (
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_824ee5bb/panels"
)

WIDTH = 1600
HEIGHT = 1000
DPI = 150

WHITE = "#FFFFFF"
NAVY = "#14263D"
NAVY_2 = "#1C3654"
INK = "#182432"
MUTED = "#647184"
FAINT = "#8D99A8"
LINE = "#DDE3EA"
PAPER = "#F5F7FA"
TEAL = "#147D80"
TEAL_SOFT = "#E3F2F1"
BLUE = "#2D67A3"
BLUE_SOFT = "#E7EFF8"
AMBER = "#A96B16"
AMBER_SOFT = "#F8EEDC"
RED = "#B64A45"
RED_SOFT = "#F8E7E5"
GREEN = "#297453"
GREEN_SOFT = "#E5F1EB"


@dataclass(frozen=True)
class EvidenceBundle:
    k1636: dict[str, Any]
    k1653: dict[str, Any]
    k1659: dict[str, Any]
    k1671: dict[str, Any]
    documents: dict[str, str]


def load_json_required(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise TypeError(f"Evidence root must be a JSON object: {path}")
    return data


def load_text_required(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError(f"Evidence text is empty: {path}")
    return text


def load_evidence() -> EvidenceBundle:
    documents = {
        "k1636_readme": load_text_required(K1636_README),
        "k1653_readme": load_text_required(K1653_README),
        "k1659_readme": load_text_required(K1659_README),
        "k1671_readme": load_text_required(K1671_README),
        "article": load_text_required(ARTICLE_PATH),
    }
    return EvidenceBundle(
        k1636=load_json_required(K1636_RESULTS),
        k1653=load_json_required(K1653_RESULTS),
        k1659=load_json_required(K1659_RESULTS),
        k1671=load_json_required(K1671_RESULTS),
        documents=documents,
    )


def require_path(root: Any, *parts: Any) -> Any:
    current = root
    walked: list[str] = []
    for part in parts:
        walked.append(str(part))
        location = ".".join(walked)
        if isinstance(part, int):
            if not isinstance(current, list):
                raise TypeError(f"Expected list before {location}")
            if part < 0 or part >= len(current):
                raise KeyError(location)
            current = current[part]
        else:
            if not isinstance(current, dict):
                raise TypeError(f"Expected object before {location}")
            if part not in current:
                raise KeyError(location)
            current = current[part]
    return current


def require_dict(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"Expected object at {label}")
    return value


def require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise TypeError(f"Expected list at {label}")
    return value


def require_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"Expected number at {label}")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"Non-finite number at {label}")
    return number


def require_int(value: Any, label: str) -> int:
    number = require_number(value, label)
    if not number.is_integer():
        raise TypeError(f"Expected integer at {label}")
    return int(number)


def require_bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"Expected boolean at {label}")
    return value


def require_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"Expected non-empty string at {label}")
    return value


def require_summary_row(
    rows: Any,
    *,
    ticker: str,
    test: str,
) -> dict[str, Any]:
    row_list = require_list(rows, "k1671.summary.rows")
    matches = [
        row
        for row in row_list
        if isinstance(row, dict)
        and row.get("ticker") == ticker
        and row.get("test") == test
    ]
    if len(matches) != 1:
        raise KeyError(
            f"Expected exactly one k1671 summary row for {ticker}/{test}; "
            f"found {len(matches)}"
        )
    return matches[0]


def experiment_id(data: dict[str, Any], label: str) -> str:
    return require_string(require_path(data, "experiment_id"), label).upper()


def fmt_pp(value: float, digits: int = 2) -> str:
    return f"{value * 100:+.{digits}f}"


def fmt_pct(value: float, digits: int) -> str:
    return f"{value:+.{digits}%}"


def fmt_ratio(value: float) -> str:
    return f"{value:.2f} 倍"


def zh_small_int(value: int) -> str:
    numerals = {
        0: "零",
        1: "一",
        2: "二",
        3: "三",
        4: "四",
        5: "五",
        6: "六",
        7: "七",
        8: "八",
        9: "九",
        10: "十",
    }
    return numerals.get(value, str(value))


def parse_down_threshold_percent(method_text: str) -> float:
    match = re.search(r"<=\s*(-?\d+(?:\.\d+)?)%", method_text)
    if match is None:
        raise ValueError("Cannot resolve the K1636 down-day threshold")
    return abs(float(match.group(1)))


def parse_forward_horizon(method_text: str) -> int:
    match = re.search(r"t\+1\.\.t\+(\d+)", method_text)
    if match is None:
        raise ValueError("Cannot resolve the K1636 forward-volatility horizon")
    return int(match.group(1))


def wrap_zh(text: str, width: int) -> str:
    lines: list[str] = []
    for paragraph in text.splitlines() or [""]:
        if not paragraph:
            lines.append("")
            continue
        lines.extend(
            textwrap.wrap(
                paragraph,
                width=width,
                break_long_words=True,
                break_on_hyphens=False,
                replace_whitespace=False,
            )
        )
    return "\n".join(lines)


def rounded_box(
    ax: Axes,
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    face: str = WHITE,
    edge: str = LINE,
    radius: float = 0.018,
    linewidth: float = 1.2,
    zorder: int = 1,
) -> FancyBboxPatch:
    patch = FancyBboxPatch(
        (x, y),
        width,
        height,
        boxstyle=f"round,pad=0.008,rounding_size={radius}",
        linewidth=linewidth,
        edgecolor=edge,
        facecolor=face,
        transform=ax.transAxes,
        zorder=zorder,
    )
    ax.add_patch(patch)
    return patch


def add_text(
    ax: Axes,
    x: float,
    y: float,
    text: str,
    *,
    size: float,
    color: str = INK,
    weight: str = "normal",
    ha: str = "left",
    va: str = "center",
    linespacing: float = 1.22,
    zorder: int = 5,
) -> Any:
    return ax.text(
        x,
        y,
        text,
        transform=ax.transAxes,
        fontsize=size,
        color=color,
        fontweight=weight,
        fontfamily="Heiti TC",
        ha=ha,
        va=va,
        linespacing=linespacing,
        zorder=zorder,
    )


def pill(
    ax: Axes,
    x: float,
    y: float,
    width: float,
    height: float,
    text: str,
    *,
    face: str,
    color: str,
    size: float = 12,
) -> None:
    rounded_box(
        ax,
        x,
        y,
        width,
        height,
        face=face,
        edge=face,
        radius=height * 0.42,
        linewidth=0,
        zorder=3,
    )
    add_text(
        ax,
        x + width / 2,
        y + height / 2,
        text,
        size=size,
        color=color,
        weight="bold",
        ha="center",
        zorder=4,
    )


def make_canvas(title: str, subtitle: str) -> tuple[Figure, Axes]:
    fig = plt.figure(figsize=(WIDTH / DPI, HEIGHT / DPI), dpi=DPI, facecolor=WHITE)
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.set_facecolor(WHITE)

    ax.add_patch(
        Rectangle(
            (0, 0.80),
            1,
            0.20,
            transform=ax.transAxes,
            facecolor=NAVY,
            edgecolor="none",
            zorder=0,
        )
    )
    ax.add_patch(
        Rectangle(
            (0.055, 0.946),
            0.045,
            0.005,
            transform=ax.transAxes,
            facecolor="#49B7B2",
            edgecolor="none",
            zorder=2,
        )
    )
    add_text(
        ax,
        0.108,
        0.949,
        "VOLPRED｜爆量之後會漲還會跌？",
        size=11,
        color="#BFD2E6",
        weight="bold",
    )
    add_text(
        ax,
        0.055,
        0.890,
        title,
        size=29,
        color=WHITE,
        weight="bold",
    )
    add_text(
        ax,
        0.055,
        0.825,
        subtitle,
        size=12.5,
        color="#CAD8E6",
    )
    return fig, ax


def add_footer(ax: Axes, source: str) -> None:
    ax.add_line(
        Line2D(
            [0.055, 0.945],
            [0.070, 0.070],
            transform=ax.transAxes,
            color=LINE,
            linewidth=1.0,
            zorder=2,
        )
    )
    add_text(ax, 0.055, 0.035, source, size=9.5, color=MUTED)
    add_text(
        ax,
        0.945,
        0.035,
        "研究結果不構成投資建議",
        size=9.5,
        color=FAINT,
        ha="right",
    )


def save_panel(fig: Figure, filename: str) -> None:
    path = os.path.join(out_dir, filename)
    fig.savefig(
        path,
        dpi=DPI,
        facecolor=WHITE,
        edgecolor="none",
        format="png",
    )
    plt.close(fig)


def draw_question_icon(ax: Axes, cx: float, cy: float, kind: str) -> None:
    ax.add_patch(
        Circle(
            (cx, cy),
            0.027,
            transform=ax.transAxes,
            facecolor=BLUE_SOFT if kind != "risk" else AMBER_SOFT,
            edgecolor="none",
            zorder=3,
        )
    )
    if kind == "up":
        ax.add_patch(
            FancyArrowPatch(
                (cx - 0.012, cy - 0.010),
                (cx + 0.013, cy + 0.013),
                transform=ax.transAxes,
                arrowstyle="-|>",
                mutation_scale=12,
                linewidth=1.8,
                color=BLUE,
                zorder=4,
            )
        )
    elif kind == "down":
        ax.add_patch(
            FancyArrowPatch(
                (cx - 0.012, cy + 0.010),
                (cx + 0.013, cy - 0.013),
                transform=ax.transAxes,
                arrowstyle="-|>",
                mutation_scale=12,
                linewidth=1.8,
                color=RED,
                zorder=4,
            )
        )
    else:
        xs = [cx - 0.015, cx - 0.005, cx + 0.004, cx + 0.015]
        ys = [cy - 0.004, cy + 0.010, cy - 0.010, cy + 0.014]
        ax.add_line(
            Line2D(
                xs,
                ys,
                transform=ax.transAxes,
                color=AMBER,
                linewidth=1.8,
                zorder=4,
            )
        )


def panel_1(bundle: EvidenceBundle) -> None:
    id1636 = experiment_id(bundle.k1636, "k1636.experiment_id")
    id1653 = experiment_id(bundle.k1653, "k1653.experiment_id")
    id1659 = experiment_id(bundle.k1659, "k1659.experiment_id")
    id1671 = experiment_id(bundle.k1671, "k1671.experiment_id")

    verdict1636 = require_string(
        require_path(bundle.k1636, "verdict", "myth_verdict"),
        "k1636.verdict.myth_verdict",
    )
    supporting1636 = require_list(
        require_path(bundle.k1636, "verdict", "primary_downside_supporting_tests"),
        "k1636.verdict.primary_downside_supporting_tests",
    )
    verdict1659 = require_string(
        require_path(bundle.k1659, "verdict", "myth_verdict"),
        "k1659.verdict.myth_verdict",
    )
    supported1659 = require_int(
        require_path(bundle.k1659, "verdict", "n_myth_consistent_bh_significant"),
        "k1659.verdict.n_myth_consistent_bh_significant",
    )
    require_list(require_path(bundle.k1653, "results"), "k1653.results")

    if verdict1636 != "not_supported_as_next_day_direction_rule":
        raise ValueError("K1636 no longer supports the prescribed direction claim")
    if supporting1636:
        raise ValueError("K1636 now contains a primary downside-supporting test")
    if verdict1659 != "not_supported_as_next_day_direction_rule" or supported1659 != 0:
        raise ValueError("K1659 no longer supports the prescribed direction claim")

    forward_method = require_string(
        require_path(bundle.k1636, "method", "targets", "fwd5_realized_vol"),
        "k1636.method.targets.fwd5_realized_vol",
    )
    horizon = parse_forward_horizon(forward_method)
    horizon_zh = zh_small_int(horizon)

    fig, ax = make_canvas(
        "方向與風險，是兩個不同問題",
        "同一個爆量事件，要拆成不同問題再判讀",
    )

    cards = [
        {
            "x": 0.055,
            "icon": "up",
            "question": "爆量後\n隔日會漲嗎？",
            "pill": "方向證據弱",
            "pill_w": 0.128,
            "pill_face": BLUE_SOFT,
            "pill_color": BLUE,
            "body": "少數資產可能出現例外，\n不能當成跨市場規則。",
        },
        {
            "x": 0.367,
            "icon": "down",
            "question": "爆量長黑後\n隔日會跌嗎？",
            "pill": "多輪檢驗不支持",
            "pill_w": 0.154,
            "pill_face": RED_SOFT,
            "pill_color": RED,
            "body": "隔日續跌沒有穩健證據，\n原始方向反而偏正。",
        },
        {
            "x": 0.679,
            "icon": "risk",
            "question": f"爆量長黑後\n未來{horizon_zh}日\n會更震嗎？",
            "question_size": 18,
            "question_linespacing": 1.08,
            "pill": "有次要風險線索",
            "pill_w": 0.154,
            "pill_face": AMBER_SOFT,
            "pill_color": AMBER,
            "body": f"{id1636} 觀察到事件後波動放大，\n但證據層級低於主要方向檢定。",
        },
    ]

    for card in cards:
        x = float(card["x"])
        rounded_box(ax, x, 0.345, 0.266, 0.405, face=WHITE, edge=LINE)
        draw_question_icon(ax, x + 0.045, 0.694, str(card["icon"]))
        add_text(
            ax,
            x + 0.082,
            0.701,
            str(card["question"]),
            size=float(card.get("question_size", 20)),
            weight="bold",
            va="top",
            linespacing=float(card.get("question_linespacing", 1.28)),
        )
        pill(
            ax,
            x + 0.026,
            0.505,
            float(card["pill_w"]),
            0.052,
            str(card["pill"]),
            face=str(card["pill_face"]),
            color=str(card["pill_color"]),
            size=11.5,
        )
        add_text(
            ax,
            x + 0.026,
            0.458,
            str(card["body"]),
            size=13,
            color=MUTED,
            va="top",
            linespacing=1.5,
        )

    rounded_box(
        ax,
        0.055,
        0.102,
        0.890,
        0.185,
        face=PAPER,
        edge=PAPER,
        radius=0.016,
        linewidth=0,
    )
    add_text(ax, 0.080, 0.250, "讀圖結論", size=11, color=TEAL, weight="bold")
    core = (
        f"隔日方向證據弱；{id1636} 留下一項事件後{horizon_zh}日波動放大的次要線索。"
    )
    add_text(
        ax,
        0.080,
        0.196,
        wrap_zh(core, 42),
        size=18,
        weight="bold",
        va="center",
        linespacing=1.35,
    )
    pill(
        ax,
        0.650,
        0.122,
        0.265,
        0.046,
        f"重疊{horizon_zh}日窗口｜仍待更多資產獨立驗證",
        face=AMBER_SOFT,
        color=AMBER,
        size=10.5,
    )
    add_footer(
        ax,
        f"資料來源：experiments {id1636}/{id1653}/{id1659}/{id1671}。",
    )
    save_panel(fig, "1_question.png")


def panel_2(bundle: EvidenceBundle) -> None:
    id1671 = experiment_id(bundle.k1671, "k1671.experiment_id")
    assets = require_dict(
        require_path(bundle.k1671, "config", "assets"),
        "k1671.config.assets",
    )
    asset_count = len(assets)
    n_tests = require_int(
        require_path(bundle.k1671, "summary", "n_primary_tests"),
        "k1671.summary.n_primary_tests",
    )
    n_passed = require_int(
        require_path(bundle.k1671, "summary", "n_myth_supported_bh_5pct"),
        "k1671.summary.n_myth_supported_bh_5pct",
    )
    rows = require_path(bundle.k1671, "summary", "rows")
    honhai = require_summary_row(
        rows,
        ticker="2317.TW",
        test="A_high_volume_next_up",
    )
    tw0050 = require_summary_row(
        rows,
        ticker="0050.TW",
        test="A_high_volume_next_up",
    )

    honhai_lift = require_number(
        require_path(honhai, "hit_rate_minus_base"),
        "k1671.summary.rows[2317 A].hit_rate_minus_base",
    )
    honhai_mean_diff = require_number(
        require_path(honhai, "mean_diff"),
        "k1671.summary.rows[2317 A].mean_diff",
    )
    honhai_q = require_number(
        require_path(honhai, "q_bh"),
        "k1671.summary.rows[2317 A].q_bh",
    )
    honhai_supported = require_bool(
        require_path(honhai, "myth_supported"),
        "k1671.summary.rows[2317 A].myth_supported",
    )
    tw0050_lift = require_number(
        require_path(tw0050, "hit_rate_minus_base"),
        "k1671.summary.rows[0050 A].hit_rate_minus_base",
    )
    tw0050_supported = require_bool(
        require_path(tw0050, "myth_supported"),
        "k1671.summary.rows[0050 A].myth_supported",
    )

    if n_passed != 1 or not honhai_supported or tw0050_supported:
        raise ValueError("K1671 support status no longer matches the prescribed panel")

    fig, ax = make_canvas(
        f"{zh_small_int(asset_count)}檔資產的方向結果",
        "主要檢定經 BH-FDR 多重比較校正",
    )

    rounded_box(ax, 0.055, 0.500, 0.300, 0.245, face=NAVY_2, edge=NAVY_2)
    add_text(ax, 0.080, 0.700, "全體結果", size=12, color="#BFD2E6", weight="bold")
    add_text(
        ax,
        0.080,
        0.615,
        f"{n_passed} / {n_tests}",
        size=39,
        color=WHITE,
        weight="bold",
    )
    add_text(
        ax,
        0.080,
        0.545,
        f"{n_tests} 組主要測試，只有 {n_passed} 組通過",
        size=13,
        color="#D7E3EF",
    )

    rounded_box(ax, 0.380, 0.500, 0.565, 0.245, face=WHITE, edge=LINE)
    pill(
        ax,
        0.405,
        0.675,
        0.092,
        0.042,
        "唯一通過",
        face=GREEN_SOFT,
        color=GREEN,
        size=10.5,
    )
    add_text(
        ax,
        0.515,
        0.696,
        "鴻海（2317.TW）爆量後隔日上漲",
        size=15,
        weight="bold",
    )
    ax.add_line(
        Line2D(
            [0.596, 0.596],
            [0.525, 0.650],
            transform=ax.transAxes,
            color=LINE,
            linewidth=1.0,
        )
    )
    ax.add_line(
        Line2D(
            [0.774, 0.774],
            [0.525, 0.650],
            transform=ax.transAxes,
            color=LINE,
            linewidth=1.0,
        )
    )
    add_text(ax, 0.405, 0.642, "命中率比基準高", size=10.5, color=MUTED)
    add_text(
        ax,
        0.405,
        0.585,
        fmt_pp(honhai_lift),
        size=29,
        color=TEAL,
        weight="bold",
    )
    add_text(ax, 0.405, 0.535, "個百分點", size=10.5, color=MUTED)

    add_text(ax, 0.620, 0.642, "平均報酬差", size=10.5, color=MUTED)
    add_text(
        ax,
        0.620,
        0.585,
        fmt_pct(honhai_mean_diff, 3),
        size=25,
        color=BLUE,
        weight="bold",
    )

    add_text(ax, 0.798, 0.642, "校正後顯著性數值", size=10.5, color=MUTED)
    add_text(
        ax,
        0.798,
        0.585,
        f"{honhai_q:.4f}",
        size=25,
        color=GREEN,
        weight="bold",
    )

    rounded_box(ax, 0.055, 0.315, 0.890, 0.135, face=BLUE_SOFT, edge=BLUE_SOFT)
    add_text(ax, 0.080, 0.382, "0050", size=18, color=NAVY, weight="bold")
    add_text(
        ax,
        0.205,
        0.382,
        f"命中率差 {fmt_pp(tw0050_lift)} 個百分點",
        size=18,
        color=BLUE,
        weight="bold",
    )
    pill(
        ax,
        0.790,
        0.350,
        0.120,
        0.058,
        "未通過",
        face=RED_SOFT,
        color=RED,
        size=12,
    )

    rounded_box(ax, 0.055, 0.105, 0.890, 0.155, face=PAPER, edge=PAPER, linewidth=0)
    add_text(ax, 0.080, 0.222, "結論", size=11, color=TEAL, weight="bold")
    add_text(
        ax,
        0.080,
        0.165,
        "鴻海是資產特定例外，不能外推成普世規則",
        size=21,
        weight="bold",
    )
    add_footer(ax, f"資料來源：{id1671} results JSON。")
    save_panel(fig, "2_direction.png")


def draw_black_candle_icon(ax: Axes, x: float, y: float) -> None:
    ax.add_line(
        Line2D(
            [x, x],
            [y - 0.052, y + 0.052],
            transform=ax.transAxes,
            color=NAVY,
            linewidth=2.0,
            zorder=4,
        )
    )
    ax.add_patch(
        Rectangle(
            (x - 0.016, y - 0.025),
            0.032,
            0.055,
            transform=ax.transAxes,
            facecolor=NAVY,
            edgecolor=NAVY,
            zorder=4,
        )
    )
    for dx, height in [(-0.055, 0.035), (-0.040, 0.055), (-0.025, 0.075)]:
        ax.add_patch(
            Rectangle(
                (x + dx, y - 0.052),
                0.008,
                height,
                transform=ax.transAxes,
                facecolor=RED,
                edgecolor="none",
                zorder=3,
            )
        )


def panel_3(bundle: EvidenceBundle) -> None:
    id1671 = experiment_id(bundle.k1671, "k1671.experiment_id")
    pooled = require_dict(
        require_path(
            bundle.k1671,
            "pooled_diagnostic",
            "B_high_volume_black_next_down",
            "raw_next_day_return",
        ),
        "k1671.pooled_diagnostic.B.raw_next_day_return",
    )
    n_dates = require_int(
        require_path(pooled, "n_dates"),
        "k1671.pooled_diagnostic.B.raw_next_day_return.n_dates",
    )
    raw_mean = require_number(
        require_path(pooled, "mean"),
        "k1671.pooled_diagnostic.B.raw_next_day_return.mean",
    )
    short_strategy = require_dict(
        require_path(bundle.k1671, "strategy", "B_short_after_black"),
        "k1671.strategy.B_short_after_black",
    )
    short_sharpe = require_number(
        require_path(short_strategy, "sharpe"),
        "k1671.strategy.B_short_after_black.sharpe",
    )
    max_drawdown = require_number(
        require_path(short_strategy, "max_drawdown"),
        "k1671.strategy.B_short_after_black.max_drawdown",
    )
    if raw_mean <= 0 or short_sharpe >= 0 or max_drawdown >= 0:
        raise ValueError("K1671 black-candle direction no longer matches the panel")

    fig, ax = make_canvas(
        "爆量長黑後，方向反而相反",
        "事件結果與隔日放空策略｜不放入後續波動倍數",
    )

    rounded_box(ax, 0.055, 0.135, 0.410, 0.610, face=WHITE, edge=LINE)
    draw_black_candle_icon(ax, 0.385, 0.660)
    add_text(ax, 0.085, 0.692, "事件日隔日平均報酬", size=14, color=MUTED, weight="bold")
    add_text(
        ax,
        0.085,
        0.555,
        fmt_pct(raw_mean, 3),
        size=43,
        color=TEAL,
        weight="bold",
    )
    add_text(
        ax,
        0.085,
        0.465,
        f"{n_dates} 個事件日",
        size=18,
        color=NAVY,
        weight="bold",
    )
    ax.add_line(
        Line2D(
            [0.085, 0.430],
            [0.405, 0.405],
            transform=ax.transAxes,
            color=LINE,
            linewidth=1.0,
        )
    )
    add_text(
        ax,
        0.085,
        0.352,
        "同日多檔觸發時，\n先按日期聚合成一筆觀測。",
        size=13,
        color=MUTED,
        va="top",
        linespacing=1.5,
    )

    rounded_box(ax, 0.495, 0.445, 0.450, 0.300, face=NAVY_2, edge=NAVY_2)
    add_text(
        ax,
        0.525,
        0.697,
        "照口訣：爆量長黑後隔日放空",
        size=14,
        color="#D7E3EF",
        weight="bold",
    )
    ax.add_line(
        Line2D(
            [0.720, 0.720],
            [0.485, 0.655],
            transform=ax.transAxes,
            color="#45617E",
            linewidth=1.0,
        )
    )
    add_text(ax, 0.525, 0.625, "Sharpe", size=11, color="#BFD2E6")
    add_text(
        ax,
        0.525,
        0.555,
        f"{short_sharpe:.3f}",
        size=32,
        color="#FFB5AE",
        weight="bold",
    )
    add_text(ax, 0.752, 0.625, "最大回撤", size=11, color="#BFD2E6")
    add_text(
        ax,
        0.752,
        0.555,
        f"{max_drawdown:.1%}",
        size=32,
        color="#FFB5AE",
        weight="bold",
    )

    rounded_box(ax, 0.495, 0.135, 0.450, 0.260, face=RED_SOFT, edge=RED_SOFT)
    add_text(ax, 0.525, 0.345, "反證", size=11, color=RED, weight="bold")
    add_text(
        ax,
        0.525,
        0.275,
        "方向與「隔日續跌」相反",
        size=22,
        color=NAVY,
        weight="bold",
    )
    add_text(
        ax,
        0.525,
        0.205,
        "歷史平均偏正，機械放空的風險報酬也很差。",
        size=12.5,
        color=MUTED,
    )
    add_footer(ax, f"資料來源：{id1671} results JSON。")
    save_panel(fig, "3_black_candle.png")


def panel_4(bundle: EvidenceBundle) -> None:
    id1636 = experiment_id(bundle.k1636, "k1636.experiment_id")
    down_method = require_string(
        require_path(bundle.k1636, "method", "down_day"),
        "k1636.method.down_day",
    )
    forward_method = require_string(
        require_path(bundle.k1636, "method", "targets", "fwd5_realized_vol"),
        "k1636.method.targets.fwd5_realized_vol",
    )
    down_threshold = parse_down_threshold_percent(down_method)
    horizon = parse_forward_horizon(forward_method)
    horizon_zh = zh_small_int(horizon)

    tw_signal = require_dict(
        require_path(
            bundle.k1636,
            "asset_results",
            "0050.TW",
            "signals",
            "volume_2x_down_m2pct",
        ),
        "k1636.asset_results.0050.TW.signals.volume_2x_down_m2pct",
    )
    tsmc_signal = require_dict(
        require_path(
            bundle.k1636,
            "asset_results",
            "2330.TW",
            "signals",
            "volume_2x_down_m2pct",
        ),
        "k1636.asset_results.2330.TW.signals.volume_2x_down_m2pct",
    )
    tw_ratio = require_number(
        require_path(tw_signal, "fwd5_realized_vol", "ratio_event_vs_nonevent"),
        "k1636.0050.volume_2x_down_m2pct.fwd5_realized_vol.ratio",
    )
    tsmc_ratio = require_number(
        require_path(tsmc_signal, "fwd5_realized_vol", "ratio_event_vs_nonevent"),
        "k1636.2330.volume_2x_down_m2pct.fwd5_realized_vol.ratio",
    )
    tw_events = require_int(
        require_path(tw_signal, "n_events"),
        "k1636.0050.volume_2x_down_m2pct.n_events",
    )
    tsmc_events = require_int(
        require_path(tsmc_signal, "n_events"),
        "k1636.2330.volume_2x_down_m2pct.n_events",
    )
    if tw_ratio <= 1 or tsmc_ratio <= 1:
        raise ValueError("K1636 forward-volatility ratios no longer show a lift")

    fig, ax = make_canvas(
        f"{id1636} 留下的次要風險線索",
        f"只看事件後{horizon_zh}日年化波動，不拿來猜隔日方向",
    )

    pill(
        ax,
        0.055,
        0.724,
        0.360,
        0.052,
        f"爆量且當日下跌至少 {down_threshold:g}% 後",
        face=AMBER_SOFT,
        color=AMBER,
        size=12,
    )

    rounded_box(ax, 0.055, 0.135, 0.575, 0.545, face=WHITE, edge=LINE)
    add_text(
        ax,
        0.085,
        0.635,
        f"事件後{horizon_zh}日年化波動／一般日",
        size=14,
        color=MUTED,
        weight="bold",
    )

    max_ratio = max(tw_ratio, tsmc_ratio)
    rows = [
        ("0050", tw_ratio, tw_events, 0.535, TEAL, TEAL_SOFT),
        ("台積電", tsmc_ratio, tsmc_events, 0.345, BLUE, BLUE_SOFT),
    ]
    for label, ratio, events, y, color, soft in rows:
        add_text(ax, 0.085, y + 0.025, label, size=17, color=NAVY, weight="bold")
        ax.add_patch(
            FancyBboxPatch(
                (0.195, y - 0.005),
                0.245,
                0.055,
                boxstyle="round,pad=0,rounding_size=0.018",
                transform=ax.transAxes,
                facecolor=soft,
                edgecolor="none",
                zorder=2,
            )
        )
        ax.add_patch(
            FancyBboxPatch(
                (0.195, y - 0.005),
                0.245 * ratio / max_ratio,
                0.055,
                boxstyle="round,pad=0,rounding_size=0.018",
                transform=ax.transAxes,
                facecolor=color,
                edgecolor="none",
                zorder=3,
            )
        )
        add_text(
            ax,
            0.470,
            y + 0.036,
            fmt_ratio(ratio),
            size=25,
            color=color,
            weight="bold",
        )
        add_text(
            ax,
            0.470,
            y - 0.018,
            f"事件數 {events}",
            size=11,
            color=MUTED,
        )

    add_text(
        ax,
        0.085,
        0.205,
        "倍數比較的是符合事件後的波動，\n相對於未符合該事件的一般日。",
        size=11.5,
        color=FAINT,
        va="top",
        linespacing=1.45,
    )

    rounded_box(ax, 0.660, 0.135, 0.285, 0.545, face=PAPER, edge=PAPER, linewidth=0)
    add_text(ax, 0.690, 0.635, "怎麼使用這條線索？", size=14, color=TEAL, weight="bold")
    add_text(
        ax,
        0.690,
        0.545,
        "先檢查部位、槓桿與\n回撤承受度，\n不猜下一根 K 棒。",
        size=19,
        color=NAVY,
        weight="bold",
        va="top",
        linespacing=1.35,
    )
    rounded_box(
        ax,
        0.690,
        0.235,
        0.225,
        0.145,
        face=AMBER_SOFT,
        edge=AMBER_SOFT,
        linewidth=0,
    )
    add_text(ax, 0.712, 0.340, "證據限制", size=10.5, color=AMBER, weight="bold")
    add_text(
        ax,
        0.712,
        0.285,
        f"重疊{horizon_zh}日窗口\n尚未跨更多資產獨立複製",
        size=11.5,
        color=INK,
        va="center",
        linespacing=1.45,
    )
    add_footer(ax, f"資料來源：{id1636} results JSON。")
    save_panel(fig, "4_risk_use.png")


def main() -> None:
    os.makedirs(out_dir, exist_ok=True)
    bundle = load_evidence()
    panel_1(bundle)
    panel_2(bundle)
    panel_3(bundle)
    panel_4(bundle)


if __name__ == "__main__":
    main()
