#!/usr/bin/env python3
"""Render the VolPred drone EP1 upstream lazypack as four PNG panels.

All displayed statistics are loaded from the evidence JSON.  The accompanying
article draft is also required so the renderer fails loudly if the evidence
package is incomplete or mismatched.
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
from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch, Rectangle


EVIDENCE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/drafts/"
    "drone_ep1_upstream_evidence.json"
)
DRAFT_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/drafts/"
    "drone_ep1_general_draft.md"
)
out_dir = "/tmp/drone_ep1_poster"

WIDTH = 1600
HEIGHT = 1000
DPI = 72

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False


# Restrained editorial palette: navy, data blue, teal, and one warning accent.
NAVY = "#12253A"
NAVY_2 = "#1C3854"
BLUE = "#2E6F9E"
BLUE_SOFT = "#E8F1F7"
TEAL = "#16847A"
TEAL_SOFT = "#E5F3F0"
AMBER = "#C8872E"
AMBER_SOFT = "#F8EDD9"
RED = "#B84A4A"
RED_SOFT = "#F7E7E5"
INK = "#182431"
MUTED = "#5E6C79"
FAINT = "#8793A0"
GRID = "#D9E1E7"
PAPER = "#F5F7F8"
WHITE = "#FFFFFF"


def load_inputs() -> tuple[dict[str, Any], str]:
    """Load both absolute-path evidence inputs; missing files/fields must raise."""
    with EVIDENCE_PATH.open("r", encoding="utf-8") as handle:
        evidence = json.load(handle)
    if not isinstance(evidence, dict):
        raise TypeError("Evidence root must be a JSON object")

    draft = DRAFT_PATH.read_text(encoding="utf-8")
    if not draft.strip():
        raise ValueError(f"Article draft is empty: {DRAFT_PATH}")
    if "無人載具" not in draft or "EP1" not in draft or "上游" not in draft:
        raise ValueError("Article draft does not match 無人載具 EP1 上游")
    return evidence, draft


def req(data: Any, path: str) -> Any:
    """Resolve a dotted JSON path and raise on every missing or invalid step."""
    current = data
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise KeyError(f"Missing required evidence field: {path}")
        current = current[part]
    return current


def number(data: Any, path: str) -> float:
    value = req(data, path)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"Expected number at {path}, got {type(value).__name__}")
    return float(value)


def integer(data: Any, path: str) -> int:
    value = number(data, path)
    if not value.is_integer():
        raise ValueError(f"Expected integer-valued number at {path}, got {value}")
    return int(value)


def text_value(data: Any, path: str) -> str:
    value = req(data, path)
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"Expected non-empty string at {path}")
    return value


def list_value(data: Any, path: str) -> list[Any]:
    value = req(data, path)
    if not isinstance(value, list) or not value:
        raise TypeError(f"Expected non-empty list at {path}")
    return value


def upstream_by_name(evidence: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = list_value(evidence, "upstream")
    index: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise TypeError("Each upstream entry must be a JSON object")
        name = row.get("name")
        if not isinstance(name, str) or not name:
            raise KeyError("Each upstream entry requires a non-empty name")
        if name in index:
            raise ValueError(f"Duplicate upstream company: {name}")
        index[name] = row
    return index


def pct(value: float, digits: int = 1, signed: bool = False) -> str:
    sign = "+" if signed else ""
    return f"{value * 100:{sign}.{digits}f}%"


def decimal(value: float, digits: int = 2, signed: bool = False) -> str:
    sign = "+" if signed else ""
    return f"{value:{sign}.{digits}f}"


def twd_yi(value: float) -> str:
    return f"{value / 100_000_000:.1f} 億元"


def p_label(value: float) -> str:
    if value < 0.001:
        return "p < 0.001"
    return f"p = {value:.3f}"


def wrap_text(value: str, width: int) -> str:
    paragraphs = value.splitlines() or [value]
    wrapped: list[str] = []
    for paragraph in paragraphs:
        if not paragraph:
            wrapped.append("")
            continue
        wrapped.extend(
            textwrap.wrap(
                paragraph,
                width=width,
                break_long_words=True,
                break_on_hyphens=False,
                replace_whitespace=False,
            )
        )
    return "\n".join(wrapped)


def make_canvas(background: str = PAPER) -> tuple[Any, Any]:
    fig = plt.figure(
        figsize=(WIDTH / DPI, HEIGHT / DPI), dpi=DPI, facecolor=background
    )
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, WIDTH)
    ax.set_ylim(0, HEIGHT)
    ax.axis("off")
    ax.set_facecolor(background)
    return fig, ax


def rounded_box(
    ax: Any,
    x: float,
    y: float,
    w: float,
    h: float,
    face: str = WHITE,
    edge: str = "none",
    radius: float = 22,
    linewidth: float = 1.2,
    zorder: int = 1,
) -> None:
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle=f"round,pad=0,rounding_size={radius}",
            facecolor=face,
            edgecolor=edge,
            linewidth=linewidth,
            zorder=zorder,
        )
    )


def label(
    ax: Any,
    x: float,
    y: float,
    value: str,
    size: float,
    *,
    color: str = INK,
    weight: str = "normal",
    ha: str = "left",
    va: str = "top",
    max_chars: int | None = None,
    linespacing: float = 1.25,
    zorder: int = 5,
) -> Any:
    rendered = wrap_text(value, max_chars) if max_chars else value
    return ax.text(
        x,
        y,
        rendered,
        fontsize=size,
        color=color,
        fontweight=weight,
        ha=ha,
        va=va,
        linespacing=linespacing,
        zorder=zorder,
    )


def pill(
    ax: Any,
    x: float,
    y: float,
    w: float,
    h: float,
    value: str,
    *,
    face: str,
    color: str,
    size: float = 17,
) -> None:
    rounded_box(ax, x, y, w, h, face=face, radius=h / 2)
    label(
        ax,
        x + w / 2,
        y + h / 2,
        value,
        size,
        color=color,
        weight="bold",
        ha="center",
        va="center",
    )


def common_header(
    ax: Any,
    title: str,
    subtitle: str,
    *,
    dark: bool = False,
) -> None:
    if dark:
        ax.add_patch(Rectangle((0, 815), WIDTH, 185, facecolor=NAVY, edgecolor="none"))
        kicker_color = "#9CC4DD"
        title_color = WHITE
        subtitle_color = "#D7E2EB"
    else:
        kicker_color = BLUE
        title_color = NAVY
        subtitle_color = MUTED
    label(
        ax,
        70,
        950,
        "VOLPRED｜無人載具 EP1｜上游環節",
        17,
        color=kicker_color,
        weight="bold",
    )
    label(ax, 70, 910, title, 35, color=title_color, weight="bold")
    label(
        ax,
        70,
        852,
        subtitle,
        19,
        color=subtitle_color,
        max_chars=62,
        linespacing=1.2,
    )


def common_footer(ax: Any, source_label: str) -> None:
    ax.plot([70, 1530], [72, 72], color=GRID, linewidth=1.1, zorder=2)
    label(ax, 70, 47, source_label, 13.5, color=MUTED, va="center")
    label(
        ax,
        1530,
        47,
        "VOLPRED",
        13.5,
        color=FAINT,
        weight="bold",
        ha="right",
        va="center",
    )


def save_panel(fig: Any, filename: str) -> None:
    path = Path(out_dir) / filename
    fig.savefig(path, dpi=DPI, facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close(fig)


def render_framework(evidence: dict[str, Any], source_label: str) -> None:
    """概念/框架面板：上游六個環節、代表公司與技術壁壘。只講框架，不放結果數字。"""
    rows = list_value(evidence, "upstream")
    n_upstream = integer(evidence, "summary.n_upstream")

    seg_order = [
        ("飛控/MCU", "飛控與馬達控制 MCU", "無人機的小腦：姿態穩定與即時控制", BLUE, BLUE_SOFT),
        ("射頻/微波", "射頻與微波", "抗干擾資料鏈與圖傳，戰場先被干擾的一環", TEAL, TEAL_SOFT),
        ("光學/感測", "光學與感測", "從「會飛」升級到「會判斷」：鏡頭與邊緣 AI", NAVY_2, BLUE_SOFT),
        ("精密結構件", "精密結構件", "賣的是軍規製程與認證資格，不是專利", AMBER, AMBER_SOFT),
        ("通訊", "通訊模組", "資料傳輸與連線模組", BLUE, BLUE_SOFT),
        ("晶片(題材)", "晶片（題材性）", "SoC 平台技術上說得通，無人機營收佔比極小", MUTED, PAPER),
    ]

    by_seg: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_seg.setdefault(str(row["segment"]), []).append(row)
    for members in by_seg.values():
        members.sort(key=lambda r: float(r["revenue_latest"]), reverse=True)

    missing = [s for s, *_ in seg_order if s not in by_seg]
    if missing:
        raise ValueError(f"evidence lost upstream segments: {missing}")
    covered = sum(len(by_seg[s]) for s, *_ in seg_order)
    if covered != n_upstream:
        raise ValueError(f"segment coverage {covered} != n_upstream {n_upstream}")

    fig, ax = make_canvas(WHITE)
    common_header(
        ax,
        f"無人載具上游：{n_upstream} 檔，六個環節",
        "上游負責讓無人機「會飛」與「會判斷」。每個環節的技術門檻不同，台廠站的位置也不同。",
        dark=True,
    )

    card_w, card_h, gap = 460, 245, 40
    xs = [70, 70 + card_w + gap, 70 + 2 * (card_w + gap)]
    ys = [515, 250]

    for idx, (seg, title, barrier, accent, soft) in enumerate(seg_order):
        cx = xs[idx % 3]
        cy = ys[idx // 3]
        rounded_box(ax, cx, cy, card_w, card_h, face=PAPER, edge=GRID, radius=18)
        pill(ax, cx + 26, cy + card_h - 54, 34 + 15 * len(title), 36, title,
             face=soft, color=accent, size=16)
        label(ax, cx + 26, cy + card_h - 68, barrier, 14, color=MUTED,
              max_chars=30, linespacing=1.35)

        line_y = cy + card_h - 118
        for member in by_seg[seg]:
            code = str(member["ticker"]).split(".")[0]
            rev = float(member["revenue_latest"]) / 1e8
            label(ax, cx + 26, line_y, f"{member['name']} {code}", 18,
                  color=INK, weight="bold")
            label(ax, cx + card_w - 26, line_y, f"營收 {rev:,.1f} 億", 15,
                  color=FAINT, ha="right")
            line_y -= 36

    rounded_box(ax, 70, 158, 1460, 74, face=RED_SOFT, edge="none", radius=16)
    label(ax, 100, 208, "還缺的環節", 16, color=RED, weight="bold")
    label(ax, 100, 178,
          "高能量密度電池、飛控軟體、光纖陀螺儀等慣性導航元件：公開資料裡找不到具規模的上市櫃供應商。",
          16, color=INK)

    common_footer(ax, source_label)
    save_panel(fig, "1_framework.png")


def render_method(evidence: dict[str, Any], source_label: str) -> None:
    members = list_value(evidence, "theme_factor.members")
    if not all(isinstance(item, str) and item for item in members):
        raise TypeError("theme_factor.members must contain non-empty strings")
    proxy = text_value(evidence, "theme_factor.smallcap_proxy")
    obs = integer(evidence, "theme_factor.obs")
    start = text_value(evidence, "price_window.start")
    end_exclusive = text_value(evidence, "price_window.end_exclusive")
    note = text_value(evidence, "theme_factor.note")
    regression = text_value(evidence, "method.regression_main")
    caveat = text_value(evidence, "method.caveat")
    if "HAC(Newey-West)" not in regression:
        raise ValueError("method.regression_main must specify HAC(Newey-West)")
    if "同期描述性迴歸" not in caveat or "非預測模型" not in caveat:
        raise ValueError("method.caveat must identify a descriptive, non-predictive model")
    if "序貫正交化" not in note:
        raise ValueError("theme_factor.note must describe sequential orthogonalization")

    fig, ax = make_canvas(PAPER)
    common_header(
        ax,
        "題材載荷怎麼量？先把共同漲跌一層層剝掉",
        "這是同期描述性分析：目的是辨認「一起動」，不是拿來預測明天。",
    )

    # Main editorial visual: a left-to-right residualization pipeline.
    rounded_box(ax, 70, 150, 1050, 640, face=WHITE, edge=GRID)
    label(ax, 105, 748, f"先組成 {len(members)} 家整機／軍工等權籃", 24, color=NAVY, weight="bold")
    label(ax, 105, 710, "籃子刻意不放上游股，避免自己解釋自己", 17, color=MUTED)

    pill_w, pill_h = 285, 55
    member_positions = [
        (105, 620), (415, 620), (725, 620),
        (105, 545), (415, 545), (725, 545),
    ]
    if len(members) != len(member_positions):
        raise ValueError("Method panel expects exactly the evidence package's six factor members")
    for member, (x, y) in zip(members, member_positions):
        pill(ax, x, y, pill_w, pill_h, member, face=BLUE_SOFT, color=BLUE, size=16)

    stages = [
        (105, 350, 250, "整機／軍工籃", "等權日對數報酬", BLUE, BLUE_SOFT),
        (385, 350, 210, "扣除大盤", "加權指數", NAVY_2, "#E8EDF1"),
        (625, 350, 230, "扣除小型股", proxy, TEAL, TEAL_SOFT),
        (885, 350, 195, "題材載荷", "個股一起動程度", AMBER, AMBER_SOFT),
    ]
    for x, y, w, title, sub, color, face in stages:
        rounded_box(ax, x, y, w, 130, face=face, edge=color, radius=16, linewidth=1.4)
        label(ax, x + w / 2, y + 88, title, 20, color=color, weight="bold", ha="center", va="center")
        label(ax, x + w / 2, y + 42, sub, 14.5, color=MUTED, ha="center", va="center")
    for x1, x2 in [(355, 385), (595, 625), (855, 885)]:
        ax.add_patch(
            FancyArrowPatch(
                (x1, 415),
                (x2, 415),
                arrowstyle="-|>",
                mutation_scale=15,
                linewidth=1.8,
                color=FAINT,
            )
        )

    label(ax, 105, 286, "迴歸標準誤", 15, color=FAINT, weight="bold")
    label(ax, 105, 251, "Newey–West HAC 修正", 19, color=INK, weight="bold")
    label(ax, 420, 286, "有效觀測", 15, color=FAINT, weight="bold")
    label(ax, 420, 251, f"{obs} 個日報酬", 19, color=INK, weight="bold")
    label(ax, 700, 286, "價格窗口", 15, color=FAINT, weight="bold")
    label(ax, 700, 251, f"{start} 起，至 {end_exclusive} 前", 17, color=INK, weight="bold")

    # Right-side annotation column.
    rounded_box(ax, 1155, 150, 375, 640, face=NAVY, radius=22)
    ax.add_patch(Circle((1215, 720), 24, facecolor=TEAL, edgecolor="none"))
    label(ax, 1215, 720, "i", 20, color=WHITE, weight="bold", ha="center", va="center")
    label(ax, 1260, 742, "讀圖重點", 23, color=WHITE, weight="bold")
    label(
        ax,
        1200,
        656,
        "載荷越高，代表軍工整機漲跌時，這檔上游股越常同方向移動。",
        19,
        color="#DDE8F0",
        max_chars=17,
        linespacing=1.35,
    )
    ax.plot([1200, 1485], [492, 492], color="#36536C", linewidth=1.2)
    label(ax, 1200, 451, "別誤讀", 19, color="#E7B86E", weight="bold")
    label(
        ax,
        1200,
        410,
        "一起動不等於無人機營收占比，也不代表因果或可交易訊號。",
        19,
        color="#F4D9A9",
        max_chars=17,
        linespacing=1.35,
    )
    pill(ax, 1200, 225, 285, 56, "描述，不是預測", face="#284B67", color="#B9D9EA", size=18)

    common_footer(ax, source_label)
    save_panel(fig, "2_method.png")


def render_results(evidence: dict[str, Any], source_label: str) -> None:
    n_naive = integer(evidence, "summary.n_theme_significant_naive_no_size_control")
    n_controlled = integer(evidence, "summary.n_theme_significant_5pct")
    n_upstream = integer(evidence, "summary.n_upstream")
    rho_size = number(
        evidence, "summary.cross_section.spearman_loading_vs_log_marketcap.rho"
    )
    p_size = number(
        evidence, "summary.cross_section.spearman_loading_vs_log_marketcap.p"
    )
    cross_n = integer(evidence, "summary.cross_section.n")

    companies = upstream_by_name(evidence)
    if len(companies) != n_upstream:
        raise ValueError("summary.n_upstream does not match upstream row count")

    sorted_rows = sorted(
        companies.values(),
        key=lambda row: number(row, "theme_loading"),
        reverse=True,
    )
    top_rows = sorted_rows[:5]
    top_revenue = sum(number(row, "revenue_latest") for row in top_rows)
    mediatek = companies.get("聯發科")
    if mediatek is None:
        raise KeyError("Missing required upstream company: 聯發科")
    mediatek_revenue = number(mediatek, "revenue_latest")
    revenue_ratio = top_revenue / mediatek_revenue

    leader = top_rows[0]
    leader_name = text_value(leader, "name")
    leader_loading = number(leader, "theme_loading")
    leader_p = number(leader, "theme_p")

    chip_names = ["新唐", "聯發科", "聯詠"]
    chip_rows: list[dict[str, Any]] = []
    for name in chip_names:
        row = companies.get(name)
        if row is None:
            raise KeyError(f"Missing required upstream company: {name}")
        chip_rows.append(row)
    if not all(number(row, "theme_p") >= 0.05 for row in chip_rows):
        raise ValueError("Evidence no longer supports 'all three chip loadings are insignificant'")

    fig, ax = make_canvas(PAPER)
    common_header(
        ax,
        "控制規模之後，真正留下來的四個結果",
        "每一格只回答一件事：規模控制、營收基數、最高載荷，以及晶片股是否真的跟題材一起動。",
        dark=True,
    )

    # Bento card A: naive versus size-controlled significance count.
    rounded_box(ax, 70, 505, 700, 270, face=WHITE, edge=GRID)
    pill(ax, 105, 703, 175, 40, "規模控制", face=BLUE_SOFT, color=BLUE, size=16)
    label(ax, 105, 660, "顯著家數被小型股共振墊高", 23, color=NAVY, weight="bold")
    label(ax, 110, 583, f"{n_naive}", 56, color=FAINT, weight="bold")
    label(ax, 178, 573, "控制前", 16, color=MUTED, va="center")
    ax.add_patch(
        FancyArrowPatch(
            (310, 575), (400, 575), arrowstyle="-|>", mutation_scale=18,
            linewidth=2.2, color=AMBER
        )
    )
    label(ax, 435, 583, f"{n_controlled}", 56, color=TEAL, weight="bold")
    label(ax, 503, 573, "控制後", 16, color=MUTED, va="center")
    label(ax, 105, 528, f"母體共 {n_upstream} 家上游公司", 16, color=FAINT)

    # Bento card B: top-five revenue scale relative to MediaTek.
    rounded_box(ax, 805, 505, 725, 270, face=NAVY, radius=22)
    pill(ax, 840, 703, 175, 40, "營收基數", face="#284B67", color="#B9D9EA", size=16)
    label(ax, 840, 660, "題材載荷最高五家，合計仍很小", 23, color=WHITE, weight="bold")
    label(ax, 840, 590, pct(revenue_ratio, 2), 53, color="#78C8BF", weight="bold")
    label(ax, 1060, 578, "相當於聯發科營收", 17, color="#D7E2EB", va="center")
    label(ax, 840, 525, twd_yi(top_revenue), 18, color="#F4D9A9", weight="bold")
    top_names = "、".join(text_value(row, "name") for row in top_rows)
    label(ax, 1030, 528, top_names, 14.5, color="#B9C9D5", max_chars=23)

    # Bento card C: highest individual loading.
    rounded_box(ax, 70, 145, 445, 325, face=TEAL_SOFT, edge="#B7DCD6")
    pill(ax, 105, 398, 150, 40, "最高載荷", face=WHITE, color=TEAL, size=16)
    label(ax, 105, 342, leader_name, 25, color=NAVY, weight="bold")
    label(ax, 105, 292, decimal(leader_loading, 2, True), 52, color=TEAL, weight="bold")
    label(ax, 105, 221, p_label(leader_p), 17, color=MUTED)
    label(ax, 105, 184, "只代表共同波動較強", 16, color=MUTED)

    # Bento card D: cross-sectional relation with company size.
    rounded_box(ax, 550, 145, 500, 325, face=WHITE, edge=GRID)
    pill(ax, 585, 398, 170, 40, "規模關聯", face=AMBER_SOFT, color=AMBER, size=16)
    label(ax, 585, 342, "公司越小，載荷越高", 23, color=NAVY, weight="bold")
    label(ax, 585, 292, decimal(rho_size, 3), 49, color=AMBER, weight="bold")
    label(ax, 585, 230, f"Spearman ρ｜n = {cross_n}", 16, color=MUTED)
    label(ax, 585, 190, f"p = {p_size:.6f}｜截面描述，非因果", 15.5, color=FAINT)

    # Bento card E: the three chip names and their evidence-bound loadings.
    rounded_box(ax, 1085, 145, 445, 325, face=RED_SOFT, edge="#E7C6C3")
    pill(ax, 1120, 398, 185, 40, "晶片三家", face=WHITE, color=RED, size=16)
    label(ax, 1120, 342, "載荷全部不顯著", 23, color=NAVY, weight="bold")
    row_y = [285, 238, 191]
    for row, y in zip(chip_rows, row_y):
        name = text_value(row, "name")
        loading = number(row, "theme_loading")
        label(ax, 1120, y, name, 17, color=MUTED, weight="bold", va="center")
        label(
            ax,
            1475,
            y,
            decimal(loading, 2, True),
            19,
            color=RED,
            weight="bold",
            ha="right",
            va="center",
        )

    common_footer(ax, source_label)
    save_panel(fig, "3_results.png")


def render_takeaway(evidence: dict[str, Any], source_label: str) -> None:
    upstream_ret = number(evidence, "summary.upstream_basket_ret_1y")
    upstream_vol = number(evidence, "summary.upstream_basket_vol")
    twii_ret = number(evidence, "summary.twii_ret_1y")
    twii_vol = number(evidence, "summary.twii_vol")
    return_gap = twii_ret - upstream_ret
    caveat = text_value(evidence, "method.caveat")
    if "不可用於擇時" not in caveat:
        raise ValueError("method.caveat must retain the no-timing limitation")

    fig, ax = make_canvas(WHITE)
    common_header(
        ax,
        "上游這一層：報酬落後，波動反而更高",
        "題材熱不等於風險報酬比較好。把上游等權籃與同期加權指數放在同一把尺上，差距很清楚。",
    )

    # Main editorial visual: return bars with volatility annotations.
    rounded_box(ax, 70, 160, 970, 620, face=PAPER, edge=GRID)
    label(ax, 110, 730, "一年報酬比較", 24, color=NAVY, weight="bold")
    label(ax, 110, 691, "等權上游籃 vs 加權指數", 16, color=MUTED)

    chart_x = 260
    chart_w = 680
    max_value = max(upstream_ret, twii_ret)
    bar_specs = [
        ("上游等權籃", upstream_ret, upstream_vol, 550, BLUE),
        ("加權指數", twii_ret, twii_vol, 350, TEAL),
    ]
    for name, ret, vol, y, color in bar_specs:
        label(ax, 110, y + 52, name, 19, color=INK, weight="bold", va="center")
        ax.add_patch(
            FancyBboxPatch(
                (chart_x, y), chart_w, 90,
                boxstyle="round,pad=0,rounding_size=15",
                facecolor="#E4E9ED", edgecolor="none"
            )
        )
        actual_w = chart_w * ret / max_value
        ax.add_patch(
            FancyBboxPatch(
                (chart_x, y), actual_w, 90,
                boxstyle="round,pad=0,rounding_size=15",
                facecolor=color, edgecolor="none"
            )
        )
        label(
            ax,
            chart_x + actual_w - 18,
            y + 48,
            pct(ret, 1, True),
            26,
            color=WHITE,
            weight="bold",
            ha="right",
            va="center",
        )
        label(
            ax,
            chart_x,
            y - 30,
            f"年化波動 {pct(vol, 1)}",
            16,
            color=MUTED,
        )

    rounded_box(ax, 110, 205, 830, 88, face=AMBER_SOFT, radius=14)
    label(ax, 145, 250, "報酬差", 16, color=AMBER, weight="bold", va="center")
    label(
        ax,
        300,
        250,
        f"上游少 {return_gap * 100:.1f} 個百分點",
        25,
        color=NAVY,
        weight="bold",
        va="center",
    )

    # Right takeaway column.
    rounded_box(ax, 1080, 160, 450, 620, face=NAVY, radius=22)
    ax.add_patch(Rectangle((1080, 690), 10, 90, facecolor=TEAL, edgecolor="none"))
    label(ax, 1120, 738, "一句話帶走", 18, color="#9CC4DD", weight="bold")
    label(
        ax,
        1120,
        683,
        "被市場當成題材股，不代表已經把題材變成營收。",
        28,
        color=WHITE,
        weight="bold",
        max_chars=14,
        linespacing=1.32,
    )
    ax.plot([1120, 1490], [505, 505], color="#36536C", linewidth=1.2)
    label(ax, 1120, 466, "現有資料能確認", 17, color="#78C8BF", weight="bold")
    label(
        ax,
        1120,
        426,
        "上游籃報酬落後大盤，且承受更高的年化波動。",
        19,
        color="#DDE8F0",
        max_chars=17,
        linespacing=1.35,
    )
    label(ax, 1120, 318, "現有資料不能確認", 17, color="#E7B86E", weight="bold")
    label(
        ax,
        1120,
        278,
        "共同波動究竟來自真受惠，還是同一批投機資金輪動。",
        19,
        color="#F4D9A9",
        max_chars=17,
        linespacing=1.35,
    )
    label(
        ax,
        1120,
        190,
        "同期描述性分析｜非預測模型｜不可用於擇時",
        14.5,
        color="#9FB0BE",
        max_chars=23,
    )

    common_footer(ax, source_label)
    save_panel(fig, "4_takeaway.png")


def main() -> None:
    os.makedirs(out_dir, exist_ok=True)
    evidence, _draft = load_inputs()

    raw_source = text_value(evidence, "data_source")
    if "yfinance" not in raw_source or "annual income statement" not in raw_source:
        raise ValueError("Unexpected evidence data_source; update the displayed source label")
    source_label = (
        "資料來源：drone_ep1_upstream_evidence.json｜"
        "yfinance 還原價與年度損益表"
    )

    render_framework(evidence, source_label)
    render_method(evidence, source_label)
    render_results(evidence, source_label)
    render_takeaway(evidence, source_label)


if __name__ == "__main__":
    main()
