#!/usr/bin/env python3
"""Render the four data-bound EP2 midstream infographic panels.

All displayed statistics are loaded from the evidence JSON.  Supporting
evidence files are also opened from absolute paths so missing inputs fail
loudly before any PNG is written.  The renderer is deterministic and uses no
network access or image-generation service.
"""

from __future__ import annotations

import json
import math
import os
import re
import textwrap
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.patches import Circle, FancyBboxPatch, Rectangle


EVIDENCE_JSON = "/Users/yhlai0911/volpred-research/storage/drafts/drone_ep2_midstream_evidence.json"
EVIDENCE_SCRIPT = "/Users/yhlai0911/volpred-research/scripts/drone_ep2_midstream_evidence.py"
GENERAL_DRAFT = "/Users/yhlai0911/volpred-research/storage/drafts/drone_ep2_general_draft.md"
ARTICLE_MD = "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_cdc7f6e8/panels/mile_cdc7f6e8_article.md"

out_dir = "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_cdc7f6e8/panels"

WIDTH_PX = 1600
HEIGHT_PX = 1000
DPI = 150

plt.rcParams["font.family"] = "sans-serif"
plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False

NAVY = "#11283F"
INK = "#17212B"
MUTED = "#5C6977"
FAINT = "#84909C"
PAPER = "#FFFFFF"
PANEL_BG = "#F5F7FA"
GRID = "#D9E0E8"
BLUE = "#28699B"
BLUE_SOFT = "#E4EFF7"
TEAL = "#117C78"
TEAL_SOFT = "#E0F1EF"
AMBER = "#A96D1D"
AMBER_SOFT = "#F7EEDC"
RED = "#B74845"
RED_SOFT = "#F7E6E4"
GREEN = "#287650"
GREEN_SOFT = "#E4F1E9"
PURPLE = "#67558C"
PURPLE_SOFT = "#EEEAF5"

DIRECT_STAGES = {"直接產品／製造", "直接產品／合作", "開始出貨"}
DEVELOPMENT_STAGES = {"共同開發／意向", "開發／展會"}
ADJACENT_STAGES = {"相鄰能力", "航太相鄰能力"}


def load_inputs() -> dict[str, Any]:
    """Load every named evidence input and reject missing or empty files."""
    supporting_paths = (EVIDENCE_SCRIPT, GENERAL_DRAFT, ARTICLE_MD)
    for path in supporting_paths:
        with open(path, "r", encoding="utf-8") as handle:
            if not handle.read().strip():
                raise ValueError(f"Supporting evidence is empty: {path}")
    with open(EVIDENCE_JSON, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise TypeError(f"Evidence root must be an object: {EVIDENCE_JSON}")
    return data


def required(data: Any, *parts: str) -> Any:
    current = data
    walked: list[str] = []
    for part in parts:
        walked.append(part)
        if not isinstance(current, dict) or part not in current:
            raise KeyError(".".join(walked))
        current = current[part]
    return current


def required_str(data: Any, *parts: str) -> str:
    value = required(data, *parts)
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{'.'.join(parts)} must be a non-empty string")
    return value


def required_num(data: Any, *parts: str) -> float:
    value = required(data, *parts)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{'.'.join(parts)} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{'.'.join(parts)} must be finite")
    return result


def required_int(data: Any, *parts: str) -> int:
    value = required_num(data, *parts)
    if not value.is_integer():
        raise ValueError(f"{'.'.join(parts)} must be an integer")
    return int(value)


def companies(data: dict[str, Any]) -> list[dict[str, Any]]:
    rows = required(data, "companies")
    if not isinstance(rows, list) or not rows:
        raise TypeError("companies must be a non-empty list")
    if not all(isinstance(row, dict) for row in rows):
        raise TypeError("Every companies item must be an object")
    expected = required_int(data, "summary", "n_companies")
    if len(rows) != expected:
        raise ValueError(f"companies has {len(rows)} rows; summary expects {expected}")
    return rows


def company(data: dict[str, Any], name: str) -> dict[str, Any]:
    matches = [row for row in companies(data) if required_str(row, "name") == name]
    if len(matches) != 1:
        raise KeyError(f"Expected exactly one company row named {name}; got {len(matches)}")
    return matches[0]


def current_year_financial(company_row: dict[str, Any]) -> dict[str, Any]:
    latest_fy = required_int(company_row, "latest_fy")
    annual = required(company_row, "by_year", str(latest_fy))
    if not isinstance(annual, dict):
        raise TypeError(f"{required_str(company_row, 'name')}.by_year.{latest_fy} must be an object")
    return annual


def pct(value: float, *, sign: bool = False) -> str:
    percentage = value * 100.0
    if abs(percentage) < 0.05:
        percentage = 0.0
    return f"{percentage:+.1f}%" if sign else f"{percentage:.1f}%"


def pp(value: float) -> str:
    points = abs(value) * 100.0
    if abs(points) < 0.05:
        points = 0.0
    return f"{points:.1f} 個百分點"


def money_wan(value: float) -> str:
    rounded = (Decimal(str(abs(value))) / Decimal("10000")).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return f"{int(rounded):,} 萬元"


def money_yi(value: float) -> str:
    rounded = (Decimal(str(abs(value))) / Decimal("100000000")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return f"{rounded:.2f} 億元"


def wrap_zh(text: str, width: int) -> str:
    lines: list[str] = []
    for paragraph in text.splitlines() or [text]:
        lines.extend(
            textwrap.wrap(
                paragraph,
                width=width,
                break_long_words=True,
                break_on_hyphens=False,
                replace_whitespace=False,
                drop_whitespace=True,
            )
            or [""]
        )
    return "\n".join(lines)


def canvas() -> tuple[Figure, Axes]:
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


def rect(
    ax: Axes,
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    face: str = PAPER,
    edge: str = GRID,
    linewidth: float = 1.0,
    radius: float = 0.014,
) -> None:
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle=f"round,pad=0.008,rounding_size={radius}",
            transform=ax.transAxes,
            facecolor=face,
            edgecolor=edge,
            linewidth=linewidth,
        )
    )


def dark_header(ax: Axes, title: str, subtitle: str) -> None:
    ax.add_patch(
        Rectangle((0, 0.85), 1, 0.15, transform=ax.transAxes, facecolor=NAVY, edgecolor="none")
    )
    ax.text(
        0.055,
        0.935,
        title,
        transform=ax.transAxes,
        ha="left",
        va="center",
        color="white",
        fontsize=26,
        fontweight="bold",
    )
    ax.text(
        0.055,
        0.882,
        subtitle,
        transform=ax.transAxes,
        ha="left",
        va="center",
        color="#D9E4EE",
        fontsize=12.5,
    )


def source_footer(ax: Axes, text: str) -> None:
    ax.plot([0.055, 0.945], [0.061, 0.061], transform=ax.transAxes, color=GRID, linewidth=0.8)
    ax.text(
        0.055,
        0.029,
        text,
        transform=ax.transAxes,
        ha="left",
        va="center",
        color=MUTED,
        fontsize=9.2,
    )


def save(fig: Figure, filename: str) -> None:
    fig.savefig(
        os.path.join(out_dir, filename),
        dpi=DPI,
        facecolor=PAPER,
        edgecolor="none",
    )
    plt.close(fig)


def grouped_disclosures(data: dict[str, Any]) -> tuple[list[str], list[str], list[str]]:
    direct: list[str] = []
    development: list[str] = []
    adjacent: list[str] = []
    for row in companies(data):
        name = required_str(row, "name")
        stage = required_str(row, "linkage_stage")
        if stage in DIRECT_STAGES:
            direct.append(name)
        elif stage in DEVELOPMENT_STAGES:
            development.append(name)
        elif stage in ADJACENT_STAGES:
            adjacent.append(name)
        else:
            raise ValueError(f"Unclassified linkage_stage for {name}: {stage}")

    expected_names = (
        {"碳基", "系統電", "富田"},
        {"永虹先進", "力山"},
        {"加百裕", "寶一", "晟田"},
    )
    actual_names = (set(direct), set(development), set(adjacent))
    if actual_names != expected_names:
        raise ValueError(f"Disclosure group names do not match the checked evidence: {actual_names}")

    expected_counts = (
        required_int(data, "summary", "n_direct_product_or_shipment"),
        required_int(data, "summary", "n_development_or_intent"),
        required_int(data, "summary", "n_adjacent_capability_only"),
    )
    if tuple(map(len, (direct, development, adjacent))) != expected_counts:
        raise ValueError("Disclosure group counts disagree with summary fields")
    return direct, development, adjacent


def render_disclosure_ladder(data: dict[str, Any]) -> None:
    n = required_int(data, "summary", "n_companies")
    direct, development, adjacent = grouped_disclosures(data)
    fig, ax = canvas()
    dark_header(
        ax,
        f"{n} 家中游公司，公開揭露走到哪裡？",
        "用途：追蹤證據進度｜不構成投資評等",
    )

    rows = [
        (
            direct,
            "直接產品／合作／出貨",
            "公開資料已看得到產品、合作角色或出貨敘述",
            TEAL,
            TEAL_SOFT,
        ),
        (
            development,
            "共同開發／意向",
            "仍待主合約、金額、數量與交期往下確認",
            AMBER,
            AMBER_SOFT,
        ),
        (
            adjacent,
            "相鄰能力",
            "只能確認製程可轉用，不能推論已有無人機訂單",
            PURPLE,
            PURPLE_SOFT,
        ),
    ]
    y_positions = [0.665, 0.505, 0.345]
    for (names, label, note, color, soft), y in zip(rows, y_positions):
        rect(ax, 0.07, y, 0.87, 0.125, face=PAPER, edge=GRID, linewidth=1.1)
        rect(ax, 0.085, y + 0.018, 0.115, 0.089, face=soft, edge=soft, radius=0.012)
        ax.text(
            0.142,
            y + 0.064,
            f"{len(names)} 家",
            transform=ax.transAxes,
            ha="center",
            va="center",
            color=color,
            fontsize=23,
            fontweight="bold",
        )
        ax.text(
            0.225,
            y + 0.087,
            label,
            transform=ax.transAxes,
            ha="left",
            va="center",
            color=INK,
            fontsize=16.5,
            fontweight="bold",
        )
        ax.text(
            0.225,
            y + 0.041,
            "｜".join(names),
            transform=ax.transAxes,
            ha="left",
            va="center",
            color=color,
            fontsize=14.5,
            fontweight="bold",
        )
        ax.text(
            0.925,
            y + 0.064,
            wrap_zh(note, 22),
            transform=ax.transAxes,
            ha="right",
            va="center",
            color=MUTED,
            fontsize=10.8,
            linespacing=1.3,
        )

    gates = ["技術能做", "具約束力訂單", "營收認列", "留下毛利"]
    ax.text(
        0.07,
        0.282,
        f"核心提醒：{len(gates)} 道關卡要分開查",
        transform=ax.transAxes,
        ha="left",
        va="center",
        color=INK,
        fontsize=14,
        fontweight="bold",
    )
    gate_x = [0.07, 0.295, 0.52, 0.745]
    for index, (x, label) in enumerate(zip(gate_x, gates)):
        rect(ax, x, 0.105, 0.185, 0.115, face=PANEL_BG, edge=GRID, radius=0.012)
        ax.add_patch(
            Circle(
                (x + 0.028, 0.162),
                0.016,
                transform=ax.transAxes,
                facecolor=BLUE,
                edgecolor="none",
            )
        )
        ax.text(
            x + 0.028,
            0.162,
            str(index + 1),
            transform=ax.transAxes,
            ha="center",
            va="center",
            color="white",
            fontsize=9.5,
            fontweight="bold",
        )
        ax.text(
            x + 0.055,
            0.162,
            label,
            transform=ax.transAxes,
            ha="left",
            va="center",
            color=INK,
            fontsize=12.5,
            fontweight="bold",
        )
        if index < len(gates) - 1:
            ax.text(
                x + 0.205,
                0.162,
                "→",
                transform=ax.transAxes,
                ha="center",
                va="center",
                color=FAINT,
                fontsize=16,
            )

    source_footer(
        ax,
        "資料來源：drone_ep2_midstream_evidence.json｜公司官網、法說、永續報告及逐筆公開來源",
    )
    save(fig, "1_disclosure_ladder.png")


def method_values(data: dict[str, Any]) -> tuple[int, int]:
    rows = companies(data)
    years = {required_int(row, "latest_fy") for row in rows}
    if len(years) != 1:
        raise ValueError(f"Companies do not share one latest fiscal year: {years}")
    latest_fy = next(iter(years))

    volatility_method = required_str(data, "method", "volatility")
    match = re.search(r"sqrt\((\d+)\)", volatility_method)
    if not match:
        raise ValueError("method.volatility must contain sqrt(<annualization days>)")
    annualization_days = int(match.group(1))

    basket_method = required_str(data, "method", "basket")
    return_method = required_str(data, "method", "return")
    financial_method = required_str(data, "method", "financials")
    if "equal-weight" not in basket_method or "rebalanced daily" not in basket_method:
        raise ValueError("method.basket does not support the daily equal-weight description")
    if "adjusted-close" not in return_method:
        raise ValueError("method.return does not support the adjusted-close description")
    if "annual income statements" not in financial_method:
        raise ValueError("method.financials does not support the annual-statement description")
    required_str(data, "method", "disclosure_classification")
    required_str(data, "method", "caveat")
    required_str(data, "data_source")
    return latest_fy, annualization_days


def render_method(data: dict[str, Any]) -> None:
    n = required_int(data, "summary", "n_companies")
    start = required_str(data, "price_window_common", "start")
    end = required_str(data, "price_window_common", "end")
    observations = required_int(data, "price_window_common", "observations")
    latest_fy, annualization_days = method_values(data)

    fig, ax = canvas()
    ax.add_patch(Rectangle((0.055, 0.86), 0.012, 0.105, transform=ax.transAxes, color=TEAL))
    ax.text(
        0.085,
        0.925,
        "證據怎麼查，市場數字怎麼算",
        transform=ax.transAxes,
        ha="left",
        va="center",
        color=INK,
        fontsize=27,
        fontweight="bold",
    )
    ax.text(
        0.085,
        0.875,
        "公司關聯、財報與市場資料分開處理，避免把能力誤寫成訂單",
        transform=ax.transAxes,
        ha="left",
        va="center",
        color=MUTED,
        fontsize=12.5,
    )

    rect(ax, 0.055, 0.225, 0.565, 0.575, face=PANEL_BG, edge=PANEL_BG, radius=0.018)
    steps = [
        (
            "公司關聯",
            "逐筆讀公司官網／法說／永續報告；相鄰製程不列為無人機訂單。",
            BLUE,
            BLUE_SOFT,
        ),
        (
            "年度財報",
            f"取 yfinance FY{latest_fy} 年度損益表；公司整體財報不等於無人機業務財報。",
            PURPLE,
            PURPLE_SOFT,
        ),
        (
            "市場比較",
            f"{n} 檔每日等權；報酬看共同窗口起訖，波動用日對數報酬。",
            TEAL,
            TEAL_SOFT,
        ),
    ]
    step_y = [0.635, 0.465, 0.295]
    for index, ((title, body, color, soft), y) in enumerate(zip(steps, step_y), start=1):
        rect(ax, 0.078, y, 0.52, 0.135, face=PAPER, edge=GRID, radius=0.012)
        ax.add_patch(Circle((0.112, y + 0.068), 0.022, transform=ax.transAxes, facecolor=color, edgecolor="none"))
        ax.text(
            0.112,
            y + 0.068,
            str(index),
            transform=ax.transAxes,
            ha="center",
            va="center",
            color="white",
            fontsize=11,
            fontweight="bold",
        )
        ax.text(
            0.15,
            y + 0.092,
            title,
            transform=ax.transAxes,
            ha="left",
            va="center",
            color=color,
            fontsize=15,
            fontweight="bold",
        )
        ax.text(
            0.15,
            y + 0.047,
            wrap_zh(body, 34),
            transform=ax.transAxes,
            ha="left",
            va="center",
            color=INK,
            fontsize=11.2,
            linespacing=1.25,
        )

    right_cards = [
        (
            0.635,
            0.165,
            "共同市場窗口",
            f"{start} 至 {end}\n{observations} 個交易日",
            BLUE,
            BLUE_SOFT,
        ),
        (
            0.445,
            0.165,
            "報酬",
            "共同窗口起訖\n還原收盤價變化",
            TEAL,
            TEAL_SOFT,
        ),
        (
            0.235,
            0.185,
            "年化波動",
            f"日對數報酬標準差\n× √{annualization_days}",
            AMBER,
            AMBER_SOFT,
        ),
    ]
    for y, h, title, body, color, soft in right_cards:
        rect(ax, 0.66, y, 0.285, h, face=soft, edge=soft, radius=0.015)
        ax.text(
            0.69,
            y + h - 0.043,
            title,
            transform=ax.transAxes,
            ha="left",
            va="center",
            color=color,
            fontsize=13,
            fontweight="bold",
        )
        ax.text(
            0.69,
            y + 0.052,
            body,
            transform=ax.transAxes,
            ha="left",
            va="center",
            color=INK,
            fontsize=14,
            fontweight="bold",
            linespacing=1.35,
        )

    rect(ax, 0.055, 0.085, 0.89, 0.095, face=NAVY, edge=NAVY, radius=0.012)
    limits = ["描述性比較", "未計交易成本", "公司整體財報 ≠ 無人機業務財報"]
    x_positions = [0.12, 0.39, 0.66]
    for x, label in zip(x_positions, limits):
        ax.text(
            x,
            0.132,
            label,
            transform=ax.transAxes,
            ha="left",
            va="center",
            color="white",
            fontsize=12.2,
            fontweight="bold",
        )

    source_footer(
        ax,
        "資料來源：drone_ep2_midstream_evidence.json｜yfinance 與公司逐筆公開資料",
    )
    save(fig, "2_method.png")


def operating_loss_amount(row: dict[str, Any]) -> float:
    financial = current_year_financial(row)
    value = required_num(financial, "operating_income")
    if value >= 0:
        raise ValueError(f"{required_str(row, 'name')} is expected to have an operating loss")
    return abs(value)


def render_financial_results(data: dict[str, Any]) -> None:
    n = required_int(data, "summary", "n_companies")
    direct = required_int(data, "summary", "n_direct_product_or_shipment")
    development = required_int(data, "summary", "n_development_or_intent")
    adjacent = required_int(data, "summary", "n_adjacent_capability_only")
    no_revenue_share = required_int(data, "summary", "n_with_separately_disclosed_uav_revenue_share")
    no_binding_orders = required_int(
        data, "summary", "n_with_public_binding_uav_order_value_in_checked_sources"
    )
    positive_growth = required_int(data, "summary", "n_positive_revenue_growth")
    operating_loss = required_int(data, "summary", "n_operating_loss")
    median_growth = required_num(data, "summary", "median_revenue_yoy")
    median_margin = required_num(data, "summary", "median_operating_margin")

    ever = company(data, "永虹先進")
    carbon = company(data, "碳基")
    ever_fy = required_int(ever, "latest_fy")
    carbon_fy = required_int(carbon, "latest_fy")
    if ever_fy != carbon_fy:
        raise ValueError("永虹先進與碳基 latest_fy must match")
    ever_revenue = required_num(current_year_financial(ever), "revenue")
    carbon_revenue = required_num(current_year_financial(carbon), "revenue")
    ever_growth = required_num(ever, "revenue_yoy")
    ever_loss = operating_loss_amount(ever)
    carbon_loss = operating_loss_amount(carbon)

    fig, ax = canvas()
    dark_header(
        ax,
        f"{n} 家基本面與揭露查核",
        "能做、能接單、能認列、能留下毛利，要看不同證據",
    )

    top_cards = [
        (direct, "直接產品／合作／出貨", TEAL, TEAL_SOFT),
        (development, "共同開發／意向", AMBER, AMBER_SOFT),
        (adjacent, "只有相鄰能力", PURPLE, PURPLE_SOFT),
    ]
    x_positions = [0.055, 0.365, 0.675]
    for x, (value, label, color, soft) in zip(x_positions, top_cards):
        rect(ax, x, 0.655, 0.27, 0.135, face=soft, edge=soft, radius=0.016)
        ax.text(
            x + 0.032,
            0.735,
            f"{value}/{n}",
            transform=ax.transAxes,
            ha="left",
            va="center",
            color=color,
            fontsize=27,
            fontweight="bold",
        )
        ax.text(
            x + 0.032,
            0.687,
            label,
            transform=ax.transAxes,
            ha="left",
            va="center",
            color=INK,
            fontsize=12.2,
            fontweight="bold",
        )

    visibility_cards = [
        (0.055, no_revenue_share, "單獨揭露無人機營收占比"),
        (0.515, no_binding_orders, "公開具約束力無人機訂單金額"),
    ]
    for x, value, label in visibility_cards:
        rect(ax, x, 0.485, 0.43, 0.115, face=PAPER, edge=RED_SOFT, linewidth=1.4, radius=0.014)
        ax.text(
            x + 0.035,
            0.543,
            f"{value}/{n}",
            transform=ax.transAxes,
            ha="left",
            va="center",
            color=RED,
            fontsize=24,
            fontweight="bold",
        )
        ax.text(
            x + 0.14,
            0.543,
            wrap_zh(label, 19),
            transform=ax.transAxes,
            ha="left",
            va="center",
            color=INK,
            fontsize=12.2,
            fontweight="bold",
            linespacing=1.25,
        )

    rect(ax, 0.055, 0.145, 0.43, 0.275, face=PANEL_BG, edge=PANEL_BG, radius=0.016)
    ax.text(
        0.082,
        0.383,
        f"FY{ever_fy} 概況",
        transform=ax.transAxes,
        ha="left",
        va="center",
        color=INK,
        fontsize=14.5,
        fontweight="bold",
    )
    fy_metrics = [
        (0.15, 0.31, f"{positive_growth}/{n}", "營收成長"),
        (0.37, 0.31, f"{operating_loss}/{n}", "營業虧損"),
        (0.15, 0.205, f"約 {pct(median_growth)}", "營收年增中位數"),
        (0.37, 0.205, pct(median_margin), "營益率中位數"),
    ]
    for x, y, value, label in fy_metrics:
        ax.text(
            x,
            y,
            value,
            transform=ax.transAxes,
            ha="center",
            va="center",
            color=BLUE if y > 0.25 else RED,
            fontsize=20,
            fontweight="bold",
        )
        ax.text(
            x,
            y - 0.044,
            label,
            transform=ax.transAxes,
            ha="center",
            va="center",
            color=MUTED,
            fontsize=10.5,
        )

    rect(ax, 0.515, 0.145, 0.43, 0.275, face=AMBER_SOFT, edge=AMBER_SOFT, radius=0.016)
    ax.text(
        0.542,
        0.383,
        "極小基數會放大成長率",
        transform=ax.transAxes,
        ha="left",
        va="center",
        color=AMBER,
        fontsize=14.5,
        fontweight="bold",
    )
    ax.text(
        0.542,
        0.321,
        f"永虹  {pct(ever_growth, sign=True)}",
        transform=ax.transAxes,
        ha="left",
        va="center",
        color=INK,
        fontsize=20,
        fontweight="bold",
    )
    ax.text(
        0.542,
        0.275,
        f"全年營收 {money_wan(ever_revenue)}｜營業虧損 {money_yi(ever_loss)}",
        transform=ax.transAxes,
        ha="left",
        va="center",
        color=MUTED,
        fontsize=11.2,
    )
    ax.plot([0.542, 0.918], [0.244, 0.244], transform=ax.transAxes, color="#E2D0AD", linewidth=0.9)
    ax.text(
        0.542,
        0.207,
        "碳基",
        transform=ax.transAxes,
        ha="left",
        va="center",
        color=INK,
        fontsize=16,
        fontweight="bold",
    )
    ax.text(
        0.63,
        0.207,
        f"營收 {money_wan(carbon_revenue)}｜營業虧損 {money_wan(carbon_loss)}",
        transform=ax.transAxes,
        ha="left",
        va="center",
        color=MUTED,
        fontsize=11.2,
    )

    source_footer(
        ax,
        f"資料來源：drone_ep2_midstream_evidence.json｜yfinance FY{ever_fy} 年度損益表與公司逐筆公開資料",
    )
    save(fig, "3_financial_results.png")


def add_bar_labels(axis: Axes, bars: Iterable[Any], values: Iterable[float]) -> None:
    for bar, value in zip(bars, values):
        axis.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height(),
            pct(value, sign=True),
            ha="center",
            va="bottom",
            fontsize=10.5,
            fontweight="bold",
            color=INK,
        )


def render_market_takeaway(data: dict[str, Any]) -> None:
    n = required_int(data, "summary", "n_companies")
    basket_return = required_num(data, "summary", "basket_return_common_window")
    basket_vol = required_num(data, "summary", "basket_annualized_volatility")
    twii_return = required_num(data, "summary", "twii_return_common_window")
    twii_vol = required_num(data, "summary", "twii_annualized_volatility")
    return_gap = required_num(data, "summary", "return_gap_basket_minus_twii")
    if not math.isclose(return_gap, basket_return - twii_return, rel_tol=1e-10, abs_tol=1e-12):
        raise ValueError("summary.return_gap_basket_minus_twii is inconsistent")
    volatility_gap = basket_vol - twii_vol
    if volatility_gap <= 0:
        raise ValueError("Expected basket volatility to exceed TWII volatility")

    start = required_str(data, "price_window_common", "start")
    end = required_str(data, "price_window_common", "end")
    observations = required_int(data, "price_window_common", "observations")
    names = ["碳基", "系統電", "寶一", "富田"]
    stock_returns = [required_num(company(data, name), "common_window_return") for name in names]

    fig, ax = canvas()
    dark_header(
        ax,
        "供應鏈標籤，沒有替報酬排隊",
        "共同窗口的歷史描述：籃子落後大盤，波動反而更高",
    )
    # Reserve a dedicated metadata row below the header.  Keeping the charts
    # below this strip prevents their titles and upper y ticks from colliding
    # with the date/window description when values produce three-digit ticks.
    rect(ax, 0.055, 0.785, 0.89, 0.045, face=PANEL_BG, edge=PANEL_BG, radius=0.009)
    ax.text(
        0.075,
        0.807,
        f"{start} 至 {end}｜{observations} 個共同交易日｜{n} 檔每日等權｜yfinance 還原收盤價",
        transform=ax.transAxes,
        ha="left",
        va="center",
        color=MUTED,
        fontsize=10.5,
    )

    return_ax = fig.add_axes([0.075, 0.495, 0.39, 0.23])
    return_values = [basket_return, twii_return]
    return_bars = return_ax.bar(
        ["中游等權籃", "加權指數"],
        [value * 100 for value in return_values],
        color=[BLUE, NAVY],
        width=0.55,
    )
    return_ax.set_title("共同窗口報酬", fontsize=13, fontweight="bold", color=INK, pad=10)
    return_ax.set_ylabel("%", fontsize=9, color=MUTED)
    return_ax.set_ylim(0, max(value * 100 for value in return_values) * 1.23)
    return_ax.grid(axis="y", alpha=0.2)
    return_ax.spines[["top", "right", "left"]].set_visible(False)
    return_ax.tick_params(axis="both", labelsize=9, colors=MUTED, length=0)
    add_bar_labels(return_ax, return_bars, return_values)

    vol_ax = fig.add_axes([0.545, 0.495, 0.38, 0.23])
    vol_values = [basket_vol, twii_vol]
    vol_bars = vol_ax.bar(
        ["中游等權籃", "加權指數"],
        [value * 100 for value in vol_values],
        color=[TEAL, "#7E8995"],
        width=0.55,
    )
    vol_ax.set_title("年化波動", fontsize=13, fontweight="bold", color=INK, pad=10)
    vol_ax.set_ylabel("%", fontsize=9, color=MUTED)
    vol_ax.set_ylim(0, max(value * 100 for value in vol_values) * 1.28)
    vol_ax.grid(axis="y", alpha=0.2)
    vol_ax.spines[["top", "right", "left"]].set_visible(False)
    vol_ax.tick_params(axis="both", labelsize=9, colors=MUTED, length=0)
    add_bar_labels(vol_ax, vol_bars, vol_values)

    rect(ax, 0.075, 0.425, 0.85, 0.055, face=RED_SOFT, edge=RED_SOFT, radius=0.01)
    ax.text(
        0.5,
        0.452,
        f"籃子少 {pp(return_gap)}報酬，同時多 {pp(volatility_gap)}波動",
        transform=ax.transAxes,
        ha="center",
        va="center",
        color=RED,
        fontsize=15,
        fontweight="bold",
    )

    stock_ax = fig.add_axes([0.09, 0.155, 0.45, 0.21])
    colors = [TEAL if value >= 0 else RED for value in stock_returns]
    y_positions = list(range(len(names)))
    stock_bars = stock_ax.barh(y_positions, [value * 100 for value in stock_returns], color=colors, height=0.55)
    stock_ax.set_yticks(y_positions, names)
    stock_ax.invert_yaxis()
    stock_ax.axvline(0, color=INK, linewidth=0.8)
    min_value = min(value * 100 for value in stock_returns)
    max_value = max(value * 100 for value in stock_returns)
    stock_ax.set_xlim(min(-35, min_value - 15), max(140, max_value + 22))
    stock_ax.set_title("個股同窗口報酬", fontsize=13, fontweight="bold", color=INK, pad=8)
    stock_ax.spines[["top", "right", "bottom", "left"]].set_visible(False)
    stock_ax.tick_params(axis="x", bottom=False, labelbottom=False)
    stock_ax.tick_params(axis="y", labelsize=10, colors=INK, length=0)
    for bar, value in zip(stock_bars, stock_returns):
        x_value = value * 100
        # Negative values are labelled inside their own bar.  Drawing the text
        # to the left of a short negative bar can cross both the axes boundary
        # and the y-axis company label (寶一 in the current evidence).
        is_negative = value < 0
        stock_ax.text(
            x_value + 2.5,
            bar.get_y() + bar.get_height() / 2,
            pct(value, sign=True),
            ha="left",
            va="center",
            fontsize=10.5,
            fontweight="bold",
            color="white" if is_negative else INK,
        )

    rect(ax, 0.61, 0.145, 0.315, 0.225, face=NAVY, edge=NAVY, radius=0.016)
    ax.text(
        0.64,
        0.325,
        "判讀順序",
        transform=ax.transAxes,
        ha="left",
        va="center",
        color="#9FC4DF",
        fontsize=12,
        fontweight="bold",
    )
    ax.text(
        0.64,
        0.295,
        wrap_zh("看到公司會做，先等具約束力合約與營收分部，再談受惠。", 13),
        transform=ax.transAxes,
        ha="left",
        va="top",
        color="white",
        fontsize=13.5,
        fontweight="bold",
        linespacing=1.25,
    )
    ax.text(
        0.64,
        0.175,
        "歷史描述不等於未來報酬",
        transform=ax.transAxes,
        ha="left",
        va="center",
        color="#D9E4EE",
        fontsize=10.5,
    )

    source_footer(
        ax,
        "資料來源：drone_ep2_midstream_evidence.json｜yfinance 還原收盤價；描述性比較、未計交易成本",
    )
    save(fig, "4_market_takeaway.png")


def main() -> None:
    os.makedirs(out_dir, exist_ok=True)
    data = load_inputs()
    render_disclosure_ladder(data)
    render_method(data)
    render_financial_results(data)
    render_market_takeaway(data)


if __name__ == "__main__":
    main()
